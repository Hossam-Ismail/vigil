"""Brain selection: Claude when credentials exist, else a downloaded local VLM, else the heuristic fallback."""

from __future__ import annotations

import logging
import threading

from ..config import settings
from .base import Brain, Judgement, LabelTask
from .claude import BrainError, ClaudeBrain
from .heuristic import HeuristicBrain
from .local import LocalBrain

log = logging.getLogger("vigil.brain")

_brains: dict[str, Brain] = {}
_lock = threading.Lock()
_preference = settings.brain
_private = True  # private mode: never send images to a cloud model (see privacy.py)


def _instance(name: str) -> Brain:
    with _lock:
        if name not in _brains:
            _brains[name] = {"anthropic": ClaudeBrain, "local": LocalBrain, "heuristic": HeuristicBrain}[name]()
        return _brains[name]


def options() -> list[dict]:
    return [
        {"name": n, "label": _instance(n).label, "available": _instance(n).available()}
        for n in ("anthropic", "local", "heuristic")
    ]


def set_preference(name: str) -> None:
    global _preference
    if name not in ("auto", "anthropic", "local", "heuristic"):
        raise ValueError(f"unknown brain {name}")
    _preference = name


def set_private(on: bool) -> None:
    global _private
    _private = bool(on)


def private() -> bool:
    return _private


def preference() -> str:
    return _preference


def get_brain() -> Brain:
    cloud_ok = not _private
    if _preference != "auto" and (cloud_ok or _preference != "anthropic"):
        b = _instance(_preference)
        if b.available():
            return b
        log.warning("brain %s unavailable, falling back", _preference)
    for name in ("anthropic", "local", "heuristic") if cloud_ok else ("local", "heuristic"):
        b = _instance(name)
        if b.available():
            return b
    return _instance("heuristic")


__all__ = ["Brain", "BrainError", "Judgement", "LabelTask", "get_brain", "options", "set_preference", "preference",
           "set_private", "private"]
