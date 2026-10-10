"""Claude as the brain: request compiler, data labeler and alert verifier (cloud)."""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

import anthropic
import numpy as np

from ..config import settings
from .base import (
    COMPILE_SCHEMA,
    COMPILE_SYSTEM,
    JUDGE_SCHEMA,
    MARK_SCHEMA,
    VERIFY_SCHEMA,
    Brain,
    Judgement,
    LabelTask,
    judge_prompt,
    mark_prompt,
    to_jpeg,
    to_judgement,
    verify_prompt,
)

log = logging.getLogger("vigil.brain.claude")

JUDGE_BATCH = 8


class BrainError(RuntimeError):
    pass


def _image_block(img: np.ndarray, max_side: int) -> dict:
    data = base64.standard_b64encode(to_jpeg(img, max_side=max_side)).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


class ClaudeBrain(Brain):
    name = "anthropic"
    label = "Claude"
    cost_per_image_usd = 0.003

    def __init__(self, model: str | None = None):
        self.model = model or settings.claude_model
        self.label = f"Claude ({self.model})"
        self._client: anthropic.Anthropic | None = None

    @staticmethod
    def has_credentials() -> bool:
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return True
        return (Path.home() / ".config" / "anthropic").exists()

    def available(self) -> bool:
        return self.has_credentials()

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(max_retries=3, timeout=90.0)
        return self._client

    def _call(self, content: list[dict], schema: dict, *, system: str | None = None, effort: str = "low",
              max_tokens: int = 8000) -> dict:
        kwargs: dict = {}
        if system:
            kwargs["system"] = system
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": content}],
                **kwargs,
            )
        except anthropic.AuthenticationError as exc:
            raise BrainError("Claude rejected the API key") from exc
        except anthropic.RateLimitError as exc:
            raise BrainError("Claude rate limit hit; try again shortly") from exc
        except anthropic.APIStatusError as exc:
            raise BrainError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise BrainError("cannot reach the Claude API") from exc
        if resp.stop_reason == "refusal":
            raise BrainError("Claude declined this request")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        if not text:
            raise BrainError(f"empty response (stop_reason={resp.stop_reason})")
        return json.loads(text)

    def text_json(self, prompt: str, schema: dict) -> dict | None:
        return self._call([{"type": "text", "text": prompt}], schema, effort="low", max_tokens=4000)

    def compile(self, request: str, frame: np.ndarray | None, camera_name: str) -> dict:
        content: list[dict] = []
        if frame is not None:
            content.append(_image_block(frame, 1280))
        content.append({"type": "text", "text": f"Camera: {camera_name}\nUser request: {request}"})
        return self._call(content, COMPILE_SCHEMA, system=COMPILE_SYSTEM, effort="medium", max_tokens=16000)

    def judge(self, images: list[np.ndarray], task: LabelTask) -> list[Judgement]:
        out: list[Judgement] = []
        for start in range(0, len(images), JUDGE_BATCH):
            chunk = images[start : start + JUDGE_BATCH]
            content: list[dict] = [{"type": "text", "text": judge_prompt(task, len(chunk))}]
            for i, img in enumerate(chunk, 1):
                content.append({"type": "text", "text": f"Image {i}:"})
                content.append(_image_block(img, 512))
            data = self._call(content, JUDGE_SCHEMA, effort="low")
            by_idx = {int(it.get("image", 0)): it for it in data.get("items", [])}
            out.extend(to_judgement(by_idx.get(i, {"answer": "unsure", "confidence": 0})) for i in range(1, len(chunk) + 1))
        return out

    def verify(self, frames: list[np.ndarray], task: LabelTask) -> Judgement:
        content: list[dict] = [{"type": "text", "text": verify_prompt(task, len(frames))}]
        for i, img in enumerate(frames, 1):
            content.append({"type": "text", "text": f"Image {i}:"})
            content.append(_image_block(img, 1024))
        return to_judgement(self._call(content, VERIFY_SCHEMA, effort="medium"))

    def choose_mark(self, marked: np.ndarray, description: str, n: int) -> int | None:
        data = self._call(
            [_image_block(marked, 1280), {"type": "text", "text": mark_prompt(description, n)}], MARK_SCHEMA
        )
        idx = int(data.get("box", 0))
        return idx if 1 <= idx <= n else None
