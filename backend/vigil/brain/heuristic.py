"""Offline fallback brain: keyword request parsing + SigLIP zero-shot judgments.

Weaker than a real VLM, but it means Vigil works with no API key and no local VLM download.
"""

from __future__ import annotations

import re

import numpy as np

from ..perception.detector import COCO_SYNONYMS, coco_class_for
from .base import Brain, Judgement, LabelTask

STATE_PATTERNS: list[tuple[str, str, str]] = [
    # regex on condition words, positive template, negative template
    (r"\b(empty|runs? out|run out|out of stock|out of|depleted|used up|gone)\b", "an empty {o}", "a {o} full of boxes"),
    (r"\b(low|running low|almost empty|nearly empty)\b", "a nearly empty {o}", "a well stocked {o}"),
    (r"\b(full|overflowing|overflows)\b", "an overflowing {o}", "a {o} with space left"),
    (r"\b(open|opened|left open|ajar)\b", "an open {o}", "a closed {o}"),
    (r"\b(closed|shut)\b", "a closed {o}", "an open {o}"),
    (r"\b(spill|spilled|leak|leaking|puddle|wet)\b", "a {o} with a liquid spill", "a clean dry {o}"),
    (r"\b(on|lit|turned on|red|flashing)\b", "a {o} that is lit up", "a {o} that is off"),
    (r"\b(off|dark)\b", "a {o} that is off", "a {o} that is lit up"),
    (r"\b(missing|removed|taken)\b", "an empty spot where the {o} was", "a {o} in its place"),
    (r"\b(blocked|obstructed)\b", "a blocked {o}", "a clear {o}"),
    (r"\b(smoke|fire)\b", "smoke or fire near the {o}", "a normal {o} with no smoke"),
]

ZONE_WORDS = r"(front door|back door|door|doorway|gate|entrance|driveway|garage|loading dock|dock|porch|yard|hallway|room|kitchen|aisle|area|zone|window|fence)"


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" .,!?")
    return re.sub(r"^(the|a|an|my|our|any)\s+", "", s)


def _noun(phrase: str) -> str:
    head = re.split(r"\b(on|in|at|near|by|next to|under|behind|of|from|with)\b", phrase)[0]
    words = head.split()
    return " ".join(words[-2:]) if words else phrase


ALERT_WORDS = r"\b(when|whenever|if|alert|notify|text me|tell me|let me know|ping|message me)\b"


def _metric_for(text: str, spec: dict) -> dict:
    """Requests that ask for a number over time rather than (or as well as) an alert.

    "count walk-ins" / "how many people come in" -> crossings on a tripwire; "how many people are waiting" ->
    a count of objects in view; "what % of the time is the bin empty" -> occupancy (share of time YES).
    """
    out: dict = {"metric": None, "alerts": True}
    noun_m = re.search(r"\b(?:how many|number of|count(?: the| how many| all)?)\s+([a-z]+)", text)
    noun = _noun(_clean(noun_m.group(1))) if noun_m else ""
    noun = noun if noun not in ("", "everyone", "everybody", "each", "of", "the") else "people"
    single = coco_class_for(re.sub(r"s$", "", noun)) or ("person" if noun in ("people", "persons") else re.sub(r"s$", "", noun))
    if re.search(r"\bwalk-?ins?\b|\bfoot ?traffic\b|\b(?:how many|count|number of)\b.*\b(?:come in|comes in|enter|enters|walk in|walks in|arrive|arrives|leave|leaves|pass|passes)\b", text):
        leaving = re.search(r"\b(leave|leaves|leaving|exit|exits)\b", text)
        if not coco_class_for(single) or single == "walk":
            single = "person"
        plural = "people" if single == "person" else f"{single}s"
        name = ("Walk-ins" if single == "person" and not leaving
                else f"{plural.capitalize()} {'leaving' if leaving else 'arriving'}")
        out["metric"] = {"kind": "crossings", "name": name, "unit": plural}
        out.update(kind="presence", targets=[single], crossing="up" if leaving else "down", trigger="per_object",
                   positive_label=f"a {single}", negative_label="an empty background", min_duration_s=0,
                   name=out["metric"]["name"])
    elif re.search(r"\b(?:how many|number of|count)\b", text):
        where = spec.get("locate", "").removeprefix("the ")
        out["metric"] = {"kind": "count", "name": f"{noun.capitalize()} in view" if where in ("", "area")
                         else f"{noun.capitalize()} at {where}", "unit": noun}
        if spec.get("kind") != "count":
            out.update(kind="count", targets=[single], count_op=">=", count_value=1,
                       positive_label=f"a {single}", negative_label="an empty background", name=out["metric"]["name"])
    elif re.search(r"(?:%|percent|share|how much|what part) of (?:the )?(?:time|day|shift|hour)|\bhow often\b|\bhow long\b", text):
        out["metric"] = {"kind": "occupancy", "name": f"% of time: {spec.get('positive_label') or 'yes'}"[:60],
                         "unit": "%"}
    if out["metric"] is not None:
        rest = re.sub(r"\b(?:how many|how often|how long)\b", "", text)
        out["alerts"] = bool(re.search(ALERT_WORDS, rest))
    return out


class HeuristicBrain(Brain):
    name = "heuristic"
    label = "Built-in (offline, basic)"

    def __init__(self) -> None:
        self._embedder = None

    @property
    def embedder(self):
        if self._embedder is None:
            from ..perception.embedder import get_embedder

            self._embedder = get_embedder()
        return self._embedder

    # ---- compile ------------------------------------------------------
    def compile(self, request: str, frame: np.ndarray | None, camera_name: str) -> dict:
        full = request.lower().strip()
        text = re.sub(r"^(?:what|how much)\s*(?:%|percent|share|part)?\s*of (?:the )?(?:time|day|shift|hour)\s+(is|are)\s+(.+?)\s+"
                      r"(empty|full|open|closed|blocked|occupied|free|on|off)\b", r"when \2 \1 \3", full)
        spec = {
            "name": request.strip()[:40],
            "kind": "state",
            "summary": "",
            "question": request.strip().rstrip("?.") + "?",
            "positive_label": "",
            "negative_label": "",
            "targets": [],
            "target_question": "",
            "locate": "",
            "locate_noun": "",
            "crossing": "none",
            "count_op": ">=",
            "count_value": 1,
            "min_duration_s": 2,
            "cooldown_s": 300,
            "trigger": "rising",
            "verify_with_vlm": False,
            "severity": "warning",
            "alert_message": "",
            "clarifications": [],
        }
        targets = [syn for syns in COCO_SYNONYMS.values() for syn in syns if re.search(rf"\b{re.escape(syn)}\b", text)]
        count_m = re.search(r"\b(fewer than|less than|more than|over|under|at least|at most)\s+(\d+)\s+([a-z ]+)", text)
        zone_m = re.search(ZONE_WORDS, text)

        if count_m:
            op = {"fewer than": "<", "less than": "<", "under": "<", "more than": ">", "over": ">",
                  "at least": ">=", "at most": "<="}[count_m.group(1)]
            noun = _noun(_clean(count_m.group(3)))
            noun_singular = re.sub(r"s$", "", noun)
            noun_singular = coco_class_for(noun_singular) or ("person" if "people" in count_m.group(3) else noun_singular)
            spec.update(kind="count", count_op=op, count_value=int(count_m.group(2)), targets=[noun_singular],
                        positive_label=f"a {noun_singular}", negative_label="an empty background",
                        name=f"{noun_singular.title()} count {op} {count_m.group(2)}",
                        alert_message=f"{noun_singular.title()} count is {op} {count_m.group(2)}",
                        min_duration_s=10, trigger="rising")
        elif targets and re.search(r"\b(enter|enters|entering|arrive|arrives|appear|appears|shows up|comes|is in|in the|at the|near|on the|walks|detected|there is|someone|anyone)\b", text):
            target = coco_class_for(targets[0]) or targets[0]
            per_obj = bool(re.search(r"\b(enter|enters|arrive|arrives|comes|shows up|walks)\b", text))
            spec.update(kind="presence", targets=[target], positive_label=f"a {target}",
                        negative_label="an empty background", min_duration_s=1,
                        trigger="per_object" if per_obj else "rising", cooldown_s=60 if per_obj else 300,
                        name=f"{target.title()} " + ("arrives" if per_obj else "present"),
                        alert_message=f"{target.title()} detected" + (f" at the {zone_m.group(1)}" if zone_m else ""))
            if zone_m:
                spec.update(locate=f"the {zone_m.group(1)}", locate_noun=zone_m.group(1))
            if re.search(r"\b(enter|enters|entering|walks in|comes in|comes into)\b", text):
                spec["crossing"] = "down"
            elif re.search(r"\b(leave|leaves|leaving|exits|walks out|goes out)\b", text):
                spec["crossing"] = "up"
        else:
            obj = ""
            m = re.search(r"\b(?:when|if|whenever|once)\s+(?:the|a|an|my|our)?\s*(.+?)\s+(?:is|are|gets|get|runs|run|becomes|goes|has|have)\b", text)
            if m:
                obj = _clean(m.group(1))
            if not obj:
                m = re.search(r"\b(?:the|a|an|my|our)\s+([a-z ]+?)\s+(?:is|are|runs|gets)\b", text)
                obj = _clean(m.group(1)) if m else "area"
            # labels describe only what is visible inside the crop: "blue bin", not "blue bin on the top shelf"
            short = _noun(obj)
            pos, neg = f"{short}", f"normal {short}"
            for pat, ptpl, ntpl in STATE_PATTERNS:
                if re.search(pat, text):
                    pos, neg = ptpl.format(o=short), ntpl.format(o=short)
                    break
            spec.update(kind="state", positive_label=pos, negative_label=neg, locate=f"the {obj}",
                        locate_noun=_noun(obj), min_duration_s=15, name=pos[:40].capitalize(),
                        alert_message=pos.capitalize())
        dur = re.search(r"\bfor (?:more than |over |at least )?(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?)\b", text)
        if dur:
            unit = dur.group(2)
            spec["min_duration_s"] = float(dur.group(1)) * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)
        spec["actions"] = []
        if re.search(r"\b(text me|imessage|message me|send me a text)\b", text):
            spec["actions"].append({"type": "imessage", "object": "", "note": ""})
        if re.search(r"\b(hubspot|crm)\b", text):
            obj = "task" if "task" in text else "note" if "note" in text else "ticket"
            spec["actions"].append({"type": "hubspot", "object": obj, "note": ""})
        if "slack" in text:
            spec["actions"].append({"type": "slack", "object": "", "note": ""})
        if "webhook" in text:
            spec["actions"].append({"type": "webhook", "object": "", "note": ""})
        spec.update(_metric_for(full, spec))
        spec["summary"] = (f"I'll track {spec['metric']['name'].lower()}." if spec.get("metric")
                           and not spec["alerts"] else f"I'll watch for: {spec['positive_label']}.")
        return spec

    # ---- judgments ----------------------------------------------------
    def _p(self, images: list[np.ndarray], task: LabelTask) -> np.ndarray:
        X = self.embedder.embed_images(images)
        w, b = self.embedder.zero_shot_direction(task.positive_label, task.negative_label)
        return 1 / (1 + np.exp(-(X @ w + b)))

    def judge(self, images: list[np.ndarray], task: LabelTask) -> list[Judgement]:
        out = []
        for p in self._p(images, task):
            conf = float(abs(p - 0.5) * 2)
            answer = None if conf < 0.2 else bool(p > 0.5)
            out.append(Judgement(answer, conf, f"zero-shot similarity {p:.2f}"))
        return out

    def verify(self, frames: list[np.ndarray], task: LabelTask) -> Judgement:
        p = float(self._p(frames[-1:], task)[0])
        return Judgement(p > 0.5, float(abs(p - 0.5) * 2), f"zero-shot similarity {p:.2f}")
