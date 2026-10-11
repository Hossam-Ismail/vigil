"""Ready-made examples for the dashboard's walkthrough: real footage, a request that works on it, and one click to
set both up as a camera and a watch. Each one was checked against the models that run it."""

from __future__ import annotations

from .config import settings

EXAMPLES = [
    {"id": "hardhats", "cat": "Construction safety", "title": "Hard hats vs no hard hats",
     "camera": "Construction site", "file": "hardhat_site.mp4", "preview": "/landing/hardhat.mp4", "poster": "/landing/hardhat_poster.jpg",
     "prompt": "Text the shift lead if anyone on site isn't wearing a hard hat.",
     "how": "Finds every person, then checks for a hard hat on each head.",
     "expect": "The worker sitting on the left has no hard hat; everyone else does."},
    {"id": "trucks", "cat": "Logistics & yards", "title": "Log every truck that pulls in",
     "camera": "Lumber yard", "file": "truck_yard.mp4", "preview": "/landing/yard.mp4", "poster": "/landing/yard.jpg",
     "prompt": "Text receiving when a truck is in the yard.",
     "how": "Looks for trucks with the people & vehicle detector in every frame.",
     "expect": "A truck crosses the yard between the forklifts."},
    {"id": "crowd", "cat": "Safety guardrails", "title": "Try to misuse it",
     "camera": "Campus plaza", "file": "plaza.avi", "preview": "/landing/plaza.mp4", "poster": "/landing/plaza_poster.jpg",
     "prompt": "Text me when a woman walks across the plaza.",
     "safe": "Text me when more than 5 people are on the plaza, and keep a count all day.",
     "how": "Every request is checked against Vigil's safety policy before anything is watched.",
     "expect": "This one singles people out by gender. Build it and watch Vigil refuse, then build the safe version."},
]
BY_ID = {e["id"]: e for e in EXAMPLES}


def path(example: dict) -> str:
    return str(settings.data_dir / "demo" / example["file"])


def public(example: dict, camera_id: int | None) -> dict:
    return {k: v for k, v in example.items() if k != "file"} | {"camera_id": camera_id}
