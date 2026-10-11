"""A local vision-language model on Apple Silicon via MLX (no API key, nothing leaves the machine)."""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from ..config import settings
from ..perception.geometry import Box
from .base import (
    COMPILE_SCHEMA,
    COMPILE_SYSTEM,
    Brain,
    Judgement,
    LabelTask,
    judge_prompt,
    mark_prompt,
    parse_json,
    to_judgement,
    verify_prompt,
)

log = logging.getLogger("vigil.brain.local")

SHEET = 6  # crops per contact sheet
TILE_W, TILE_H, GAP = 320, 240, 10


def contact_sheet(images: list[np.ndarray], cols: int = 3) -> np.ndarray:
    """Tile crops into one numbered grid image (letterboxed, dark gutters, big number badges)."""
    n = len(images)
    cols = min(cols, n)
    rows = (n + cols - 1) // cols
    sheet = np.full((rows * TILE_H + (rows + 1) * GAP, cols * TILE_W + (cols + 1) * GAP, 3), 24, np.uint8)
    for i, img in enumerate(images):
        r, c = divmod(i, cols)
        h, w = img.shape[:2]
        s = min(TILE_W / w, TILE_H / h)
        tile = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        y0 = GAP + r * (TILE_H + GAP) + (TILE_H - tile.shape[0]) // 2
        x0 = GAP + c * (TILE_W + GAP) + (TILE_W - tile.shape[1]) // 2
        sheet[y0 : y0 + tile.shape[0], x0 : x0 + tile.shape[1]] = tile
        bx, by = GAP + c * (TILE_W + GAP), GAP + r * (TILE_H + GAP)
        cv2.rectangle(sheet, (bx, by), (bx + 40, by + 36), (255, 255, 255), -1)
        cv2.putText(sheet, str(i + 1), (bx + 9, by + 28), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
    return sheet


def _model_cached(repo: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache

        path = try_to_load_from_cache(repo, "config.json")
        if not isinstance(path, str):
            return False
        snap = Path(path).parent
        index = snap / "model.safetensors.index.json"
        if index.exists():
            import json

            shards = set(json.loads(index.read_text()).get("weight_map", {}).values())
            return bool(shards) and all((snap / s).exists() for s in shards)
        return (snap / "model.safetensors").exists()
    except Exception:  # noqa: BLE001
        return False


class LocalBrain(Brain):
    name = "local"
    supports_boxes = True

    def __init__(self, repo: str | None = None):
        self.candidates = [r.strip() for r in (repo or settings.local_vlm).split(",") if r.strip()]
        self.repo = next((r for r in self.candidates if _model_cached(r)), self.candidates[0])
        self._model = None
        self._processor = None
        self._config = None
        self._lock = threading.Lock()
        self._tmp = Path(tempfile.mkdtemp(prefix="vigil-vlm-"))

    @property
    def label(self) -> str:  # type: ignore[override]
        return f"Local ({self.repo.split('/')[-1].replace('-MLX', '')})"

    def available(self) -> bool:
        try:
            import mlx_vlm  # noqa: F401
        except ImportError:
            return False
        if self._model is None and not _model_cached(self.repo):
            # a preferred model may have finished downloading since start-up
            self.repo = next((r for r in self.candidates if _model_cached(r)), self.repo)
        return _model_cached(self.repo)

    def _ensure(self) -> None:
        if self._model is None:
            from mlx_vlm import load

            t = time.time()
            self._model, self._processor = load(self.repo)
            self._config = self._model.config
            log.info("loaded %s in %.1fs", self.repo, time.time() - t)

    def _generate(self, text: str, images: list[np.ndarray], max_tokens: int = 400) -> str:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        with self._lock:
            self._ensure()
            paths = []
            for i, img in enumerate(images):
                h, w = img.shape[:2]
                s = min(1.0, 896 / max(h, w))
                if s < 1:
                    img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
                p = self._tmp / f"img{i}.jpg"
                cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                paths.append(str(p))
            try:
                prompt = apply_chat_template(
                    self._processor, self._config, text, num_images=len(paths), enable_thinking=False
                )
            except TypeError:
                prompt = apply_chat_template(self._processor, self._config, text, num_images=len(paths))
            out = generate(
                self._model, self._processor, prompt, paths or None, max_tokens=max_tokens, temperature=0.0,
                verbose=False,
            )
            return out.text if hasattr(out, "text") else str(out)

    def _json(self, text: str, images: list[np.ndarray], max_tokens: int = 400) -> dict:
        raw = self._generate(text, images, max_tokens)
        try:
            return parse_json(raw)
        except ValueError:
            raw = self._generate(text + "\nRespond with a single JSON object only.", images, max_tokens)
            return parse_json(raw)

    def text_json(self, prompt: str, schema: dict) -> dict | None:
        keys = ", ".join(schema.get("properties", {}))
        return self._json(f"{prompt}\nAnswer with one JSON object with the keys: {keys}.", [], max_tokens=500)

    def compile(self, request: str, frame: np.ndarray | None, camera_name: str) -> dict:
        template = {}
        for key, prop in COMPILE_SCHEMA["properties"].items():
            if key == "policy":
                template[key] = {"allowed": True, "category": "", "reason": "", "suggestion": ""}
                continue
            if key == "metric":
                template[key] = {"kind": "none | count | crossings | occupancy", "name": "...", "unit": "..."}
                continue
            if key == "actions":
                template[key] = [{"type": "imessage | hubspot | webhook | slack | ntfy",
                                  "object": "ticket | task | note | (empty)", "note": "..."}]
                continue
            if "enum" in prop:
                template[key] = " | ".join(prop["enum"])
            else:
                template[key] = {"string": "...", "integer": 0, "number": 0, "boolean": True,
                                 "array": ["..."]}[prop["type"]]
        import json as _json

        text = (
            f"{COMPILE_SYSTEM}\n\nCamera: {camera_name}\nUser request: {request}\n\n"
            "Respond with one JSON object shaped like this template. For fields showing options separated by |, "
            f"use exactly one of those options:\n{_json.dumps(template, indent=1)}"
        )
        return self._json(text, [frame] if frame is not None else [], max_tokens=900)

    def judge(self, images: list[np.ndarray], task: LabelTask) -> list[Judgement]:
        """Label crops in batches drawn as one numbered contact sheet: one VLM call per SHEET crops."""
        out: list[Judgement] = []
        for start in range(0, len(images), SHEET):
            chunk = images[start : start + SHEET]
            out.extend(self._judge_sheet(chunk, task) if len(chunk) > 1 else self._judge_one(chunk[0], task))
        return out

    def _judge_one(self, img: np.ndarray, task: LabelTask) -> list[Judgement]:
        text = judge_prompt(task, 1) + (
            '\nRespond with JSON: {"items": [{"image": 1, "answer": "yes"|"no"|"unsure", '
            '"confidence": 0.0-1.0, "reason": "..."}]}'
        )
        try:
            data = self._json(text, [img], max_tokens=160)
            items = data.get("items") or [data]
            return [to_judgement(items[0])]
        except Exception as exc:  # noqa: BLE001
            log.warning("local judge failed: %s", exc)
            return [Judgement(None, 0.0, "model output unreadable")]

    def _judge_sheet(self, chunk: list[np.ndarray], task: LabelTask) -> list[Judgement]:
        n = len(chunk)
        text = (
            judge_prompt(task, n)
            + f"\nThe picture is a grid of {n} separate images, each with its number in the top-left corner "
            "(numbered left to right, top to bottom). Judge each tile on its own. Keep each reason under 8 words.\n"
            'Respond with JSON: {"items": [{"image": <number>, "answer": "yes"|"no"|"unsure", '
            '"confidence": 0.0-1.0, "reason": "..."}, ...]} with one item per numbered image.'
        )
        try:
            data = self._json(text, [contact_sheet(chunk)], max_tokens=60 + 60 * n)
            by_idx = {int(it.get("image", 0)): it for it in data.get("items", []) if isinstance(it, dict)}
        except Exception as exc:  # noqa: BLE001
            log.warning("local sheet judge failed (%s); falling back to single images", exc)
            by_idx = {}
        if len(by_idx) < n // 2:
            return [j for img in chunk for j in self._judge_one(img, task)]
        return [to_judgement(by_idx[i]) if i in by_idx else self._judge_one(chunk[i - 1], task)[0]
                for i in range(1, n + 1)]

    def verify(self, frames: list[np.ndarray], task: LabelTask) -> Judgement:
        text = verify_prompt(task, len(frames)) + (
            '\nRespond with JSON: {"answer": "yes"|"no"|"unsure", "confidence": 0.0-1.0, "reason": "..."}'
        )
        return to_judgement(self._json(text, frames[-2:], max_tokens=200))

    def choose_mark(self, marked: np.ndarray, description: str, n: int) -> int | None:
        text = mark_prompt(description, n) + '\nRespond with JSON: {"box": <number>, "confidence": 0.0-1.0}'
        idx = int(self._json(text, [marked], max_tokens=60).get("box", 0))
        return idx if 1 <= idx <= n else None

    def locate(self, frame: np.ndarray, description: str) -> Box | None:
        text = (
            f'Locate "{description}" in the image. Respond with JSON {{"bbox_2d": [x1, y1, x2, y2]}} using '
            "coordinates normalized to 0-1000, or {\"bbox_2d\": []} if it is not visible."
        )
        data = self._json(text, [frame], max_tokens=80)
        bb = data.get("bbox_2d") or []
        if len(bb) != 4:
            return None
        x1, y1, x2, y2 = (float(v) / 1000 for v in bb)
        if x2 - x1 < 0.01 or y2 - y1 < 0.01:
            return None
        return (max(0, x1), max(0, y1), min(1, x2), min(1, y2))
