"""Vigil in iMessage: the owner texts Vigil, Vigil answers and acts.

Messages arrive through the Photon Spectrum bridge (/imessage-bridge). Only the owner's handles (Settings ->
iMessage, comma-separated) are answered; anyone else is ignored without a reply.

What the owner can text:
  "Text me when a package is left at the front door"  -> builds a new watch (same safety policy as the app)
  "What's happening at the dock?" / "show me"          -> a live, face-blurred snapshot and what Vigil sees
  "How many cars are in the lot?"                       -> the live number from a counting watch
  "What are you watching?" / "status"                   -> every watch and its state
  "Pause dock" / "Resume dock"                          -> pause or resume a watch
  "Yes" / "No" after an alert                           -> a training label for that alert's watch

Routing is deterministic on purpose: predictable, instant, and it works with the cloud brain switched off.
Understanding a new watch request is the brain's job (the same compile step the app uses).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .engine.actions import normalize_handle, parse_reply

HELP = ("Hi, I'm Vigil. I watch your cameras and text you. You can text me:\n"
        "• “Text me when a package is left at the door” to start a new watch\n"
        "• “What's happening at the dock?” for a live photo\n"
        "• “How many cars are in the lot?” for a live count\n"
        "• “What are you watching?” for a status check\n"
        "• “Pause dock” or “Resume dock”\n"
        "After an alert, reply YES or NO and I learn from it.")

CREATE = re.compile(
    r"^(?:please\s+)?(?:text me|tell me|alert me|let me know|notify me|ping me|message me|warn me|watch for|"
    r"watch (?:the|my|if|when|out)|keep an eye|keep watch|track|count|can you (?:watch|tell me|let me know|count))\b",
    re.I)
LOOK = re.compile(
    r"^(?:show(?: me)?|look(?: at)?|snapshot|photo|pic(?:ture)?|check(?: on)?|what(?:'s| is) (?:happening|going on)|"
    r"what do you see|what(?:'s| is) (?:at|on|in))\b", re.I)
METRIC = re.compile(r"^(?:how many|how busy|how full|what(?:'s| is) the count|count of|number of)\b", re.I)
LIST = re.compile(r"^(?:status|list|watches|what are you watching(?: for)?|what(?:'s| is) running|"
                  r"what(?:'s| are) my watches|my watches)\b", re.I)
PAUSE = re.compile(r"^(?:pause|stop|mute|turn off|disable)\s+(.+)", re.I)
RESUME = re.compile(r"^(?:resume|unpause|unmute|turn on|enable|restart)\s+(.+)", re.I)
HELLO = {"help", "hi", "hello", "hey", "menu", "?", "commands", "what can you do", "start", "vigil", "hey vigil",
         "hi vigil"}


@dataclass
class Intent:
    kind: str  # feedback | help | list | pause | resume | look | metric | create | pick | unknown
    arg: str = ""


def route(text: str, *, pending: bool = False) -> Intent:
    t = " ".join((text or "").split()).strip()
    low = t.lower().strip(".!? ")
    if pending and (low.isdigit() or len(low.split()) <= 4) and not (CREATE.search(low) or LIST.search(low)):
        return Intent("pick", low)
    verdict = parse_reply(low) if len(low.split()) <= 3 else None
    if verdict:
        return Intent("feedback", verdict)
    if low in HELLO:
        return Intent("help")
    if LIST.search(low):
        return Intent("list")
    if m := PAUSE.match(low):
        return Intent("pause", m.group(1))
    if m := RESUME.match(low):
        return Intent("resume", m.group(1))
    if METRIC.search(low):
        return Intent("metric", low)
    if LOOK.search(low):
        return Intent("look", low)
    if CREATE.search(low):
        return Intent("create", t)
    return Intent("unknown", t)


def owners(integrations: dict) -> set[str]:
    """Handles allowed to talk to Vigil: the iMessage recipients set in Settings."""
    raw = str(integrations.get("imessage_to") or "")
    return {normalize_handle(h) for h in re.split(r"[,;]+", raw) if h.strip()}


def best_match(query: str, names: list[str]) -> int | None:
    """Index of the name that best matches words in the query (camera or watch), or None."""
    q = set(re.findall(r"[a-z0-9]+", query.lower())) - {"the", "a", "an", "at", "on", "in", "my", "of", "is", "to"}
    best, score = None, 0
    for i, n in enumerate(names):
        words = set(re.findall(r"[a-z0-9]+", n.lower()))
        s = len(q & words) + (2 if n.lower() in query.lower() else 0)
        if s > score:
            best, score = i, s
    return best


def count_phrase(counts: dict[str, int]) -> str:
    plural = {"person": "people", "bus": "buses"}
    parts = [f"{n} {k if n == 1 else plural.get(k, k + 's')}" for k, n in counts.items() if n]
    if not parts:
        return "nobody and nothing that moves"
    return ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
