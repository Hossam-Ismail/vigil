"""The model library: already-trained, real-time vision models that Vigil picks automatically from a prompt.

Ten models. Eight run watches natively; two (zero-shot actions, body pose) are listed for the Lab or later work.
Every speed below was measured on this project's M3 Pro (MPS); accuracy notes only state what was measured.

When a request matches a specialist (hard hats, falls, forklifts, fire or smoke, an everyday action), that model
runs the watch directly: its own output is the answer. Anything else falls back to the three general models
(RF-DETR on COCO, OWLv2, SigLIP 2) chosen by learning/existing.py.
"""

from __future__ import annotations

import logging
import re
import time
import threading
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from ..config import settings
from . import gpu_lock

log = logging.getLogger("vigil.library")


@dataclass
class LibModel:
    id: str
    name: str
    what: str                     # one line: what it answers
    repo: str
    kind: str                     # yolo | image | video | coco | owl | siglip | xclip | pose
    native: bool                  # runs watches in the app (False: Lab or not wired in)
    license: str
    speed_ms: int | None          # measured on this Mac
    classes: list[str] = field(default_factory=list)
    file: str = ""
    threshold: float = 0.5
    measured: str = ""            # what we measured, if anything
    examples: list[str] = field(default_factory=list)
    note: str = ""
    webcam: list[str] = field(default_factory=list)   # prompts that demo well live on a laptop webcam

    def card(self) -> dict:
        d = asdict(self)
        d["url"] = f"https://huggingface.co/{self.repo}" if "/" in self.repo else self.repo
        return d


LIBRARY: list[LibModel] = [
    LibModel("coco", "People, vehicles & everyday objects", "Finds and counts 80 everyday things: people, cars, "
             "trucks, bikes, dogs, cats, bags, bottles, chairs…", "roboflow/rf-detr (COCO)", "coco", True, "Apache-2.0",
             None, examples=["How many people are waiting in line?", "Text me when a car pulls into the driveway",
                             "Tell me when the dog is on the couch"],
             webcam=["Count how many people are in front of the camera",
                     "Text me when someone is on their phone"]),
    LibModel("owl", "Find anything by name", "Finds objects from a description, even ones no model was trained on: "
             "a package, a ladder, a pallet", "google/owlv2-base-patch16-ensemble", "owl", True, "Apache-2.0", None,
             examples=["Text me when a package is left at the door", "Tell me if a ladder is left in the aisle"]),
    LibModel("siglip", "Is it true? (scene check)", "Compares the whole picture with your sentence: open or closed, "
             "empty or full, clean or messy", "google/siglip2-base-patch16-224", "siglip", True, "Apache-2.0", 22,
             examples=["Text me if the garage door is open", "Tell me when the blue bin is empty"]),
    LibModel("hardhat", "Hard hat check", "Finds every head and says if it wears a hard hat",
             "keremberke/yolov8m-hard-hat-detection", "yolo", True, "not stated (YOLOv8 / AGPL runtime)", 36,
             ["Hardhat", "NO-Hardhat"], "best.pt", 0.45,
             examples=["Text the shift lead if anyone isn't wearing a hard hat",
                       "Count workers without hard hats at the pump"]),
    LibModel("fall", "Fall detection", "Sees whether each person is standing, sitting or has fallen",
             "melihuzunoglu/human-fall-detection", "yolo", True, "AGPL-3.0", 10, ["fallen", "sitting", "standing"],
             "best.pt", 0.5, measured="On the plaza camera it labelled every walking person “standing”.",
             examples=["Text me if someone falls in the lobby", "Alert me if a resident is on the floor"]),
    LibModel("forklift", "Forklift detection", "Finds forklifts (and the people near them) in warehouses",
             "keremberke/yolov8m-forklift-detection", "yolo", True, "not stated (YOLOv8 / AGPL runtime)", 27,
             ["forklift", "person"], "best.pt", 0.5,
             measured="On the plaza camera it found the people and no forklifts.",
             examples=["Tell me when a forklift enters aisle 3", "Count forklifts in the loading bay"]),
    LibModel("fire", "Fire & smoke", "Says if a frame shows fire, smoke, or both",
             "shawnmichael/vit-base-fire-smoke-detection-v6", "image", True, "Apache-2.0", 33,
             ["None", "Fire", "Smoke", "Smoke and Fire"], threshold=0.5,
             measured="On 80 real CCTV wildfire frames: caught 23 of 40 fire/smoke frames, 2 false alarms in 40 "
                      "clean ones (distant plumes are the hard case).",
             examples=["Text me immediately if there's smoke in the kitchen", "Alert facilities if a fire starts"]),
    LibModel("actions", "Everyday actions (400)", "Watches a 2-second clip and names the action: smoking, drinking, "
             "texting, mopping, cleaning, eating, exercising and 390 more",
             "MCG-NJU/videomae-base-finetuned-kinetics", "video", True, "CC-BY-NC-4.0 (non-commercial)", 159,
             threshold=0.2, webcam=["Text me when someone is drinking", "Tell me when I touch my hair",
                                  "Text me if anyone claps", "Alert me when someone yawns"],
             examples=["Text me if anyone is smoking by the entrance",
                                      "Tell me when someone is mopping the floor", "Text me if someone is drinking in the lab"],
             note="Non-commercial license: fine for the beta and demos, needs a commercial alternative to sell."),
    LibModel("xclip", "Any action, described (zero-shot)", "Compares a 1.5-second clip with any wording you give",
             "microsoft/xclip-base-patch32", "xclip", False, "MIT", 60,
             measured="Fast, but unsure on wide CCTV views in our tests: kept in the Lab until it is reliable.",
             note="Try it in the Lab tab."),
    LibModel("pose", "Body pose", "17 body keypoints per person: hands, elbows, knees, head",
             "usyd-community/vitpose-plus-base", "pose", False, "Apache-2.0", None,
             note="Not wired in: turning keypoints into answers needs rules (hand above head…), which is the "
                  "geometry-style logic we decided to avoid as the default."),
]
BY_ID = {m.id: m for m in LIBRARY}

# ---------------------------------------------------------------------------------------------
# picking a model from the words of a request

NEG = re.compile(r"\b(no|not|without|missing|isn'?t|aren'?t|doesn'?t|don'?t|never|lacks?|n't)\b", re.I)
RULES: list[tuple[str, re.Pattern]] = [
    ("hardhat", re.compile(r"\bhard ?hats?\b|\bhardhats?\b|\bsafety helmets?\b|\bhelmets?\b", re.I)),
    ("fire", re.compile(r"\bfires?\b|\bflames?\b|\bsmoke\b|\bburning\b|\bon fire\b", re.I)),
    ("fall", re.compile(r"\bfall(s|en|ing)?\b|\bfell\b|\bon the (floor|ground)\b|\bcollaps(e|es|ed|ing)\b|"
                        r"\blying on\b", re.I)),
    ("forklift", re.compile(r"\bfork ?lifts?\b", re.I)),
]
_STOP = {"a", "an", "the", "someone", "somebody", "anyone", "anybody", "person", "people", "me", "text", "tell",
         "alert", "notify", "when", "if", "is", "are", "be", "being", "while", "by", "in", "on", "at", "of", "to",
         "and", "or", "my", "the", "it", "this", "that", "who", "let", "know", "watch", "for", "starts", "start"}


def _kinetics_labels() -> list[str]:
    from transformers import AutoConfig

    try:   # the copy already on disk first: no network, no waiting on a busy machine
        cfg = AutoConfig.from_pretrained(BY_ID["actions"].repo, local_files_only=True)
    except Exception:  # noqa: BLE001
        cfg = AutoConfig.from_pretrained(BY_ID["actions"].repo)
    return [cfg.id2label[i] for i in range(len(cfg.id2label))]


_labels_cache: list[str] | None = None


def kinetics_labels() -> list[str]:
    """The 400 action names. A failed read (e.g. while the model files are being refreshed at start-up) is
    retried a few times and never remembered as "no actions"."""
    global _labels_cache
    if _labels_cache is None:
        for attempt in range(4):
            try:
                _labels_cache = _kinetics_labels()
                break
            except Exception:  # noqa: BLE001
                if attempt == 3:
                    log.warning("could not read the action labels; will try again next time", exc_info=True)
                else:
                    time.sleep(0.75)
    return _labels_cache or []


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP and len(w) > 2}


def _stem(w: str) -> str:
    """drinks / drinking / drink -> drink; claps / clapping -> clap; fixes / fixing -> fix."""
    for suf in ("ing", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            break
    if len(w) >= 4 and w[-1] == w[-2] and w[-1] not in "aeiouls":
        w = w[:-1]
    return w


ALIASES = [({"touch", "hair"}, "fixing hair"), ({"phone", "typing"}, "texting"),
           # Kinetics names with no "-ing" word, and the other ways people drink on camera
           ({"pushup"}, "push up"), ({"situp"}, "situp"),
           ({"drink"}, "drinking beer"), ({"drink"}, "drinking shots"), ({"drink"}, "tasting beer")]


def match_action(text: str) -> list[str]:
    """Kinetics actions named in the request, in any verb form ("drinks", "is drinking", "mopping the floor"):
    every word of the action's name must be in the request ("floor"/"hands" may be left out)."""
    text = re.sub(r"\b(push|sit)[\s-]*ups?\b", r"\1up", text, flags=re.I)  # push ups / push-ups -> pushup
    stems = {_stem(w) for w in _words(text)}
    out = []
    for label in kinetics_labels():
        lw = _words(label)
        verbs = {w for w in lw if w.endswith("ing")}
        if verbs and {_stem(w) for w in lw - {"floor", "hands"}} <= stems:
            out.append(label)
    for need, label in ALIASES:
        if need <= stems and label not in out and label in kinetics_labels():
            out.append(label)
    return out[:8]


def match(text: str, kind: str = "state") -> dict | None:
    """The specialist model for a request, and which of its outputs mean YES; None for the general models.
    Counting requests ("how many people are waiting in line") stay with the counting detector."""
    for mid, pat in RULES:
        if not pat.search(text):
            continue
        if mid == "hardhat":
            return {"id": mid, "yes": ["NO-Hardhat"] if NEG.search(text) else ["Hardhat"]}
        if mid == "fire":
            smoke, fire = bool(re.search(r"\bsmoke\b", text, re.I)), bool(re.search(r"\bfires?\b|\bflames?\b|\bburning\b", text, re.I))
            yes = ["Fire", "Smoke", "Smoke and Fire"] if smoke == fire else (["Smoke", "Smoke and Fire"] if smoke else ["Fire", "Smoke and Fire"])
            return {"id": mid, "yes": yes}
        if mid == "fall":
            return {"id": mid, "yes": ["fallen"]}
        if mid == "forklift":
            return {"id": mid, "yes": ["forklift"]}
    acts = match_action(text) if kind != "count" else []
    if acts:
        return {"id": "actions", "yes": acts}
    return None


def kind_of(lib: dict) -> str:
    """detector (boxes) | classifier (one frame) | video (a clip)."""
    k = BY_ID[lib["id"]].kind
    return {"yolo": "detector", "image": "classifier", "video": "video"}[k]


# ---------------------------------------------------------------------------------------------
# running a model

_models: dict[str, object] = {}
_load_lock = threading.Lock()


def _load(m: LibModel):
    with _load_lock:
        if m.id in _models:
            return _models[m.id]
        from huggingface_hub import hf_hub_download

        with gpu_lock:
            if m.kind == "yolo":
                from ultralytics import YOLO

                obj = YOLO(hf_hub_download(m.repo, m.file))
            elif m.kind == "image":
                from transformers import AutoImageProcessor, AutoModelForImageClassification

                obj = (AutoImageProcessor.from_pretrained(m.repo),
                       AutoModelForImageClassification.from_pretrained(m.repo).to(settings.device).eval())
            elif m.kind == "video":
                from transformers import VideoMAEForVideoClassification, VideoMAEImageProcessor

                obj = (VideoMAEImageProcessor.from_pretrained(m.repo),
                       VideoMAEForVideoClassification.from_pretrained(m.repo).to(settings.device).eval())
            else:
                raise ValueError(f"{m.id} does not run watches")
        _models[m.id] = obj
        log.info("library model %s loaded", m.id)
        return obj


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class Runner:
    """Same shape as learning.finetune.TrainedModel, so the engine runs both the same way."""

    def __init__(self, lib: dict):
        self.m = BY_ID[lib["id"]]
        self.yes = set(lib.get("yes") or [])
        self.kind = kind_of(lib)
        self.threshold = float(lib.get("threshold") or self.m.threshold)
        self.meta = {"library": self.m.id}

    def detect(self, frame: np.ndarray):
        from ..learning.finetune import Hit

        model = _load(self.m)
        h, w = frame.shape[:2]
        with gpu_lock:
            r = model.predict(frame, device=settings.device, verbose=False, conf=0.25)[0]
        names = r.names
        dets = sorted(((box, names[int(cls)], float(conf)) for box, cls, conf in
                       zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist())), key=lambda d: -d[2])
        if self.m.id == "hardhat" and "NO-Hardhat" in self.yes:
            return self._bare_heads(frame, dets)
        kept: list = []
        for box, label, conf in dets:  # one label per object: the most confident one wins
            if all(_iou(box, k[0]) < 0.6 for k in kept):
                kept.append((box, label, conf))
        out = []
        for box, label, conf in kept:
            if label not in self.yes:
                continue
            if self.m.id == "fall" and label == "fallen" and (box[2] - box[0]) < 0.8 * (box[3] - box[1]):
                continue  # someone lying down is wider than tall; an upright box called "fallen" is a misread
            out.append(Hit((box[0] / w, box[1] / h, box[2] / w, box[3] / h), conf))
        return out

    def _bare_heads(self, frame: np.ndarray, dets: list) -> list:
        """Anyone not wearing a hard hat. The helmet model finds helmets well but rarely calls a bare head, so every
        person the person detector finds is checked for a helmet sitting on their head."""
        from ..learning.finetune import Hit
        from .detector import get_coco

        h, w = frame.shape[:2]
        helmets = [box for box, label, conf in dets if label == "Hardhat"]
        out = []
        for p in get_coco().detect(frame, {"person": ["person"]}, threshold=0.5):
            x1, y1, x2, y2 = p.box[0] * w, p.box[1] * h, p.box[2] * w, p.box[3] * h
            bw, bh = x2 - x1, y2 - y1
            if bh < 40:  # too small to judge a head
                continue
            head = (x1 + 0.1 * bw, y1 - 0.08 * bh, x2 - 0.1 * bw, y1 + 0.3 * bh)
            covered = False
            for b in helmets:
                iw, ih = min(head[2], b[2]) - max(head[0], b[0]), min(head[3], b[3]) - max(head[1], b[1])
                if iw > 0 and ih > 0 and iw * ih / max(1.0, (b[2] - b[0]) * (b[3] - b[1])) > 0.4:
                    covered = True
                    break
            if not covered:
                out.append(Hit(p.box, p.conf))
        return out

    def _probs(self, model, inputs) -> dict[str, float]:
        import torch

        proc, net = model
        with gpu_lock, torch.no_grad():
            logits = net(**{k: v.to(settings.device) for k, v in inputs.items()}).logits[0].float()
            p = torch.softmax(logits, -1).cpu().numpy()
        return {net.config.id2label[i]: float(v) for i, v in enumerate(p)}

    def proba(self, frame: np.ndarray) -> float:
        model = _load(self.m)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        probs = self._probs(model, model[0](images=rgb, return_tensors="pt"))
        return sum(v for k, v in probs.items() if k in self.yes)

    def proba_clip(self, frames: list[np.ndarray]) -> float:
        model = _load(self.m)
        idx = np.linspace(0, len(frames) - 1, 16).round().astype(int)
        clip = [cv2.cvtColor(frames[i], cv2.COLOR_BGR2RGB) for i in idx]
        probs = self._probs(model, model[0](clip, return_tensors="pt"))
        return min(1.0, sum(v for k, v in probs.items() if k in self.yes))  # chance of any of the matched actions

    def top(self, frames: list[np.ndarray], n: int = 3) -> list[tuple[str, float]]:
        """The model's own top answers for a clip (shown in the review screen)."""
        model = _load(self.m)
        idx = np.linspace(0, len(frames) - 1, 16).round().astype(int)
        clip = [cv2.cvtColor(frames[i], cv2.COLOR_BGR2RGB) for i in idx]
        probs = self._probs(model, model[0](clip, return_tensors="pt"))
        return sorted(probs.items(), key=lambda kv: -kv[1])[:n]


def runner_for(spec) -> Runner | None:
    lib = getattr(spec, "library", None)
    if not lib or lib.get("id") not in BY_ID or not BY_ID[lib["id"]].native or BY_ID[lib["id"]].kind not in ("yolo", "image", "video"):
        return None
    return Runner(lib)


# ---------------------------------------------------------------------------------------------
# prebuilt: weights are downloaded in the background at startup so a matching prompt starts instantly

_status: dict[str, str] = {}


def prefetch() -> None:
    from huggingface_hub import hf_hub_download, snapshot_download

    for m in LIBRARY:
        if m.kind not in ("yolo", "image", "video", "xclip"):
            _status[m.id] = "ready"
            continue
        _status[m.id] = "downloading"
        try:
            if m.file:
                hf_hub_download(m.repo, m.file)
            else:
                snapshot_download(m.repo, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"])
            _status[m.id] = "ready"
        except Exception as exc:  # noqa: BLE001
            _status[m.id] = f"download failed: {str(exc)[:80]}"
            log.warning("library prefetch %s failed: %s", m.id, exc)
    kinetics_labels()


def status() -> list[dict]:
    return [{**m.card(), "status": _status.get(m.id, "not downloaded" if m.kind in ("yolo", "image", "video", "xclip")
                                                  else "ready")} for m in LIBRARY]
