"""The 'brain' is the large model behind Vigil: it compiles requests, labels training data and
double-checks alerts. Implementations: Claude (cloud), a local MLX VLM, and a heuristic fallback."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import cv2
import numpy as np

from ..perception.geometry import Box


@dataclass
class Judgement:
    answer: bool | None  # None = unsure
    confidence: float
    reason: str = ""


@dataclass
class LabelTask:
    question: str
    positive_label: str
    negative_label: str
    context: str = ""  # e.g. camera name + original request


class Brain:
    name = "base"
    label = "Base"
    supports_boxes = False
    cost_per_image_usd = 0.0  # rough, for UI budgeting

    def available(self) -> bool:
        return True

    def compile(self, request: str, frame: np.ndarray | None, camera_name: str) -> dict:
        raise NotImplementedError

    def judge(self, images: list[np.ndarray], task: LabelTask) -> list[Judgement]:
        raise NotImplementedError

    def verify(self, frames: list[np.ndarray], task: LabelTask) -> Judgement:
        raise NotImplementedError

    def choose_mark(self, marked: np.ndarray, description: str, n: int) -> int | None:
        """Set-of-mark grounding: pick which numbered box matches the description (1-based)."""
        return None

    def locate(self, frame: np.ndarray, description: str) -> Box | None:
        return None

    def text_json(self, prompt: str, schema: dict) -> dict | None:
        """Answer a text-only question as JSON matching `schema`; None when this brain can't."""
        return None


# ---------------------------------------------------------------------------------------------
# shared prompt text + schema


COMPILE_SYSTEM = """You are the rule compiler inside Vigil, a camera monitoring product. A user types, in plain
language, something they want to be alerted about on one specific camera. You are shown the camera's current
frame. Convert the request into a watch specification that a fast vision pipeline will run continuously.

Vigil supports three kinds of watches:
- "state": the condition or appearance of a fixed thing or area (a bin is empty, a door is open, a machine
  light is red, a spill on the floor, a shelf gap, a gate left open). Vigil crops that region and classifies it.
- "presence": objects or people appearing in the scene or a zone ("a person enters", "a car in the driveway",
  "a dog on the couch", "someone without a hard hat"). An object detector finds the targets, a tracker follows
  them, and an optional per-object check tests an attribute.
- "count": a numeric threshold on detected objects ("fewer than 3 pallets", "more than 5 people waiting").

Field guidance:
- question: a yes/no question about the frame (or the cropped region for state watches). YES must mean the
  alert-worthy condition is true. Make it self-contained, e.g. "Is the blue bin on the top-left shelf empty?".
- positive_label / negative_label: short visual noun phrases (3-8 words) for zero-shot image-text matching
  against the cropped region. Describe only what is visible inside the crop: no location words ("on the left
  shelf", "by the door"), which hurt matching.
  state: the region in each state ("an empty blue plastic bin" / "a blue plastic bin full of boxes").
  presence with an object attribute: the object crop ("a worker without a hard hat" / "a worker wearing a hard hat").
  plain presence: ("a person" / "an empty background").
- targets: presence/count only. 1-3 singular common nouns an object detector can find ("person", "car",
  "forklift", "cardboard box"). Empty list for state watches.
- target_question: presence/count only, when the request is about an attribute or action of each object;
  phrased so YES is alert-worthy ("Is this person NOT wearing a hard hat?"). Empty string otherwise.
- locate: the specific region to watch, as it would be described while pointing at the image ("the blue bin
  on the top-left shelf", "the front door"). Empty string when the whole frame matters.
- locate_noun: 1-3 words an open-vocabulary detector could use to find candidate regions for `locate`
  ("blue bin", "door", "shelf"). Empty string when locate is empty.
- crossing: presence only. Use a tripwire when direction matters ("someone enters / leaves / walks in through
  the door", "a car exits the lot"): the image-space direction a person or object moves when doing the alerting
  thing: "down" (toward the bottom of the frame, usually toward the camera), "up", "left", "right", or "any".
  Think about motion, not the side named: "walks in from the left side" means moving RIGHT; "comes in through
  the door at the back of the room" usually means moving DOWN; "leaves through the door at the back" means UP.
  Use "none" when mere presence is enough ("a person is in the yard", "a dog on the couch").
  Never put direction, entering or leaving into target_question; the tripwire handles that.
- count_op / count_value: for count watches; for presence use ">=" and 1.
- min_duration_s: how long the condition must hold before alerting. Typical: entering/presence 1, safety
  violations 3-5, spills 10, empty/stock-out states 20-60.
- cooldown_s: minimum seconds between alerts for this watch (60-3600).
- trigger: "rising" (alert once each time the condition becomes true), "sustained" (repeat every cooldown
  while it stays true), "per_object" (alert for each new tracked object; best for "tell me when someone
  enters/arrives").
- verify_with_vlm: true unless the condition is trivial to see.
- alert_message: a short notification line ("Bin A-01 is empty", "Person at the front door").
- name: 2-5 word title. summary: one sentence, second person, describing what Vigil will do.
- actions: what should happen when it fires, taken from the request. "text me" / "iMessage me" → imessage;
  "log it in HubSpot" / "open a ticket" / "update the CRM" → hubspot with object ticket, task or note;
  "post in Slack" → slack; "call my webhook" / "tell our system" → webhook. Empty list when the request names
  no follow-up (Vigil always records the alert). Put any detail worth passing on in `note`.
- clarifications: short questions if the request is ambiguous for this image (e.g. two blue bins are visible).
  Still give your best-guess spec.
Use what you can see in the frame to make labels and locate phrases concrete."""

COMPILE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "kind": {"type": "string", "enum": ["state", "presence", "count"]},
        "summary": {"type": "string"},
        "question": {"type": "string"},
        "positive_label": {"type": "string"},
        "negative_label": {"type": "string"},
        "targets": {"type": "array", "items": {"type": "string"}},
        "target_question": {"type": "string"},
        "locate": {"type": "string"},
        "locate_noun": {"type": "string"},
        "crossing": {"type": "string", "enum": ["none", "any", "down", "up", "left", "right"]},
        "count_op": {"type": "string", "enum": [">=", ">", "<=", "<", "=="]},
        "count_value": {"type": "integer"},
        "min_duration_s": {"type": "number"},
        "cooldown_s": {"type": "number"},
        "trigger": {"type": "string", "enum": ["rising", "sustained", "per_object"]},
        "verify_with_vlm": {"type": "boolean"},
        "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
        "alert_message": {"type": "string"},
        "clarifications": {"type": "array", "items": {"type": "string"}},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["imessage", "hubspot", "webhook", "slack", "ntfy"]},
                    "object": {"type": "string", "enum": ["ticket", "task", "note", ""]},
                    "note": {"type": "string"},
                },
                "required": ["type", "object", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "name", "kind", "summary", "question", "positive_label", "negative_label", "targets", "target_question",
        "locate", "locate_noun", "crossing", "count_op", "count_value", "min_duration_s", "cooldown_s", "trigger",
        "verify_with_vlm", "severity", "alert_message", "clarifications", "actions",
    ],
    "additionalProperties": False,
}

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image": {"type": "integer"},
                    "answer": {"type": "string", "enum": ["yes", "no", "unsure"]},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["image", "answer", "confidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "enum": ["yes", "no", "unsure"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["answer", "confidence", "reason"],
    "additionalProperties": False,
}

MARK_SCHEMA = {
    "type": "object",
    "properties": {"box": {"type": "integer"}, "confidence": {"type": "number"}},
    "required": ["box", "confidence"],
    "additionalProperties": False,
}


def judge_prompt(task: LabelTask, n: int) -> str:
    return (
        "You are labeling security-camera images to train a small detector.\n"
        f"Question: {task.question}\n"
        f"YES looks like: {task.positive_label}. NO looks like: {task.negative_label}.\n"
        + (f"Context: {task.context}\n" if task.context else "")
        + f"There are {n} image(s), numbered in order. Answer each one independently. Use \"unsure\" only when the "
        "image genuinely does not show enough to decide. Keep each reason under 15 words."
    )


def verify_prompt(task: LabelTask, n: int) -> str:
    return (
        "A fast on-camera model raised an alert and you are the final check before a person is notified.\n"
        f"Alert condition (YES means notify): {task.question}\n"
        f"YES looks like: {task.positive_label}. NO looks like: {task.negative_label}.\n"
        + (f"Context: {task.context}\n" if task.context else "")
        + f"You are given {n} image(s) in time order; the last image(s) may be a close-up of the watched region. "
        "Answer yes only if the condition is clearly true in the most recent frames. Keep the reason under 25 words."
    )


def mark_prompt(description: str, n: int) -> str:
    return (
        f"The image has {n} numbered candidate boxes drawn on it. Which box best matches: \"{description}\"? "
        "Answer with the box number, or 0 if none match."
    )


# ---------------------------------------------------------------------------------------------
# helpers


def to_jpeg(img: np.ndarray, max_side: int = 1024, quality: int = 85) -> bytes:
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s < 1:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return buf.tobytes()


def parse_json(text: str) -> dict:
    """Extract the last JSON object from model text (handles code fences and thinking preambles)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = text.replace("```json", "```")
    fenced = re.findall(r"```(.*?)```", text, flags=re.S)
    candidates = fenced + [text]
    for cand in candidates:
        start = cand.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(cand)):
                if cand[i] == "{":
                    depth += 1
                elif cand[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cand[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start = cand.find("{", start + 1)
    raise ValueError(f"no JSON object in model output: {text[:200]!r}")


def to_judgement(item: dict) -> Judgement:
    ans = str(item.get("answer", "unsure")).lower()
    conf = float(item.get("confidence", 0.5) or 0.5)
    conf = max(0.0, min(1.0, conf if conf <= 1 else conf / 100))
    value = True if ans in ("yes", "true") else False if ans in ("no", "false") else None
    return Judgement(value, conf, str(item.get("reason", ""))[:300])


def draw_marks(frame: np.ndarray, boxes: list[Box]) -> np.ndarray:
    """Draw numbered boxes for set-of-mark prompting."""
    img = frame.copy()
    h, w = img.shape[:2]
    for i, (x1, y1, x2, y2) in enumerate(boxes, 1):
        p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
        cv2.rectangle(img, p1, p2, (0, 0, 0), 5)
        cv2.rectangle(img, p1, p2, (0, 255, 255), 2)
        label = str(i)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
        cv2.rectangle(img, (p1[0], p1[1]), (p1[0] + tw + 10, p1[1] + th + 10), (0, 255, 255), -1)
        cv2.putText(img, label, (p1[0] + 5, p1[1] + th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2, cv2.LINE_AA)
    return img
