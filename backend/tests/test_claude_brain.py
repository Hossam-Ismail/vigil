"""Checks the Claude request shape and response handling without network access."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from vigil.brain.base import COMPILE_SCHEMA, LabelTask
from vigil.brain.claude import BrainError, ClaudeBrain


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, SimpleNamespace):
            return reply
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(reply))])


def _brain(replies):
    b = ClaudeBrain(model="claude-opus-5-5")
    fake = FakeMessages(replies)
    b._client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    return b, fake


IMG = np.zeros((120, 160, 3), np.uint8)


def test_compile_uses_structured_output_and_fallbacks():
    spec = {k: "" for k in COMPILE_SCHEMA["required"]}
    spec.update(kind="state", targets=[], clarifications=[], count_op=">=", count_value=1, min_duration_s=30,
                cooldown_s=600, trigger="rising", verify_with_vlm=True, severity="warning")
    b, fake = _brain([spec])
    out = b.compile("alert when the bin is empty", IMG, "Aisle A")
    assert out["kind"] == "state"
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in call["betas"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["format"]["schema"] is COMPILE_SCHEMA
    assert "thinking" not in call  # Opus 5.5: thinking is adaptive by default and cannot be disabled
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"


def test_judge_batches_eight_images_per_request_and_maps_answers():
    replies = [
        {"items": [{"image": i, "answer": "yes" if i % 2 else "no", "confidence": 0.9, "reason": "r"} for i in range(1, 9)]},
        {"items": [{"image": 1, "answer": "unsure", "confidence": 0.3, "reason": "dark"}]},
    ]
    b, fake = _brain(replies)
    out = b.judge([IMG] * 9, LabelTask("Is it empty?", "an empty bin", "a full bin"))
    assert len(fake.calls) == 2
    assert [j.answer for j in out[:4]] == [True, False, True, False]
    assert out[8].answer is None and out[8].confidence == pytest.approx(0.3)
    images = [c for c in fake.calls[0]["messages"][0]["content"] if c["type"] == "image"]
    assert len(images) == 8


def test_refusal_raises_brain_error():
    b, _ = _brain([SimpleNamespace(stop_reason="refusal", content=[])])
    with pytest.raises(BrainError):
        b.verify([IMG], LabelTask("q", "p", "n"))
