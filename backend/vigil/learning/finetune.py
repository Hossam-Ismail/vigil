"""A vision model trained for one request, on public data.

For every watch Vigil:
  1. finds an open-license public dataset about the same thing (Hugging Face Hub),
  2. maps the dataset's classes onto the watch: TARGET (what should alert) and OTHER (the contrast, e.g. "helmet"
     for a "no hard hat" watch),
  3. writes a train / validation split to disk,
  4. fine-tunes a model on it in a separate process (RF-DETR Nano for object datasets, a MobileNetV3
     classifier for whole-image datasets), and
  5. runs that model directly on the camera: the alert is the model's own output, no zones or rules on top.

Data and weights live in data/models/watch_<id>/finetune/. A NO reply to an alert adds that frame to the next
training run as an image with nothing to find.
"""

from __future__ import annotations

import json
import logging
import random
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import settings
from ..perception import gpu_lock
from ..schemas import WatchSpec
from . import public_data as pd

log = logging.getLogger("vigil.finetune")

MAX_SIDE = 640           # images are stored at most this large (training runs at the model's own resolution)
PEEK_IMAGES = 40         # images read to learn a dataset's classes before committing to it
MAX_IMAGES = 1200        # cap per watch: enough to learn one concept, small enough to train in minutes
VAL_FRAC = 0.15
MIN_TARGET = 30
CONTAINERS = {"person", "people", "persons", "human", "humans", "worker", "workers", "body", "pedestrian", "man", "woman"}          # boxes (or images) of the target needed to bother training


def root(wid: int) -> Path:
    return settings.data_dir / "models" / f"watch_{wid}" / "finetune"


@dataclass
class Plan:
    """What Vigil will learn from. Shown to the user before they build."""
    repo: str
    license: str
    kind: str                    # detector | classifier
    target: list[str]            # dataset classes that mean YES (alert)
    other: list[str]             # dataset classes that mean NO (contrast)
    classes_seen: list[str]
    url: str = ""
    previews: list[str] = field(default_factory=list)   # file names under root(wid)/preview
    tried: list[dict] = field(default_factory=list)      # datasets looked at and why they were skipped

    def out(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------------------------
# 0. is a model already trained for this?

_PLAIN = {"is", "are", "there", "a", "an", "the", "any", "anyone", "someone", "somebody", "anybody", "in", "on", "at",
          "of", "this", "that", "room", "area", "scene", "frame", "view", "image", "camera", "picture", "visible",
          "present", "here", "currently", "now", "right", "screen", "space", "zone", "region", "inside", "one", "or",
          "more", "people", "persons", "person", "how", "many", "number", "count", "seen", "shown", "who"}


def pretrained_fits(spec: WatchSpec) -> list[str] | None:
    """COCO classes when the request is just "is there / how many <common object>": Vigil's base detector was
    trained on COCO (118k public images, 80 classes) and already does that better than a quick fine-tune."""
    from ..perception.detector import coco_class_for

    if spec.kind not in ("presence", "count") or not spec.targets:
        return None
    classes = [coco_class_for(t) for t in spec.targets]
    if not all(classes):
        return None
    words = set(re.findall(r"[a-z]+", (spec.target_question or "").lower()))
    words -= _PLAIN | {w for t in spec.targets for w in re.findall(r"[a-z]+", t.lower())} | set(classes)
    words -= {w + "s" for w in classes}
    return None if words else list(dict.fromkeys(classes))


# ---------------------------------------------------------------------------------------------
# 1-2. find a dataset and map its classes


def find(spec: WatchSpec, prompt: str, wid: int, *, brain=None, embedder=None,
         say: Callable[[str], None] = lambda m: None, max_tries: int = 14, budget_s: float = 240) -> Plan | None:
    rule = pd.queries(spec, prompt)
    smart = pd.brain_queries(spec, prompt, brain)
    qs = list(dict.fromkeys([q for pair in zip(rule, smart) for q in pair] + rule + smart))  # interleave both
    say(f"searching public datasets for: {', '.join(qs[:5])}")
    cands = _distinct(pd.search(qs))
    # boxes first (a detector can say where), then a stated open license, then popularity
    cands.sort(key=lambda c: (0 if "object-detection" in c["tasks"] else 1, c["rank"], -c["downloads"]))
    tried: list[dict] = []
    t_end = time.time() + budget_s
    for cand in cands[:max_tries]:
        if time.time() > t_end:
            break
        repo = cand["id"]
        say(f"looking at {repo}")
        try:
            peek = list(_take(pd.examples(repo, max_images=PEEK_IMAGES), PEEK_IMAGES))
        except Exception as exc:  # noqa: BLE001
            tried.append({"repo": repo, "why": f"could not read it ({str(exc)[:60]})"})
            continue
        if len(peek) < 10:
            tried.append({"repo": repo, "why": "too few readable images"})
            continue
        counts = Counter(c for _, items in peek for _, c in items)
        classes = [c for c, n in counts.items() if n >= 3]
        if not classes:
            tried.append({"repo": repo, "why": "no usable labels"})
            continue
        mapping = pd.text_mapping(classes, spec, embedder, brain) if embedder is not None or brain else {}
        target = [c for c in classes if mapping.get(c) == "yes"]
        other = [c for c in classes if mapping.get(c) == "no"]
        # a catch-all class ("person") overlaps the target boxes and drowns it out; keep specific contrasts only
        specific = [c for c in other if c.lower().strip() not in CONTAINERS]
        other = specific if specific else other
        if not target:
            tried.append({"repo": repo, "why": f"none of its classes ({', '.join(classes[:6])}) is what you asked for"})
            continue
        if embedder is not None and other:
            target, other, ok = _check_with_images(peek, target, other, spec, embedder)
            if not ok:
                tried.append({"repo": repo, "why": "its labels did not match what the images show"})
                continue
        boxes = any(b is not None for _, items in peek for b, _ in items)
        plan = Plan(repo=repo, license=cand["license"], kind="detector" if boxes else "classifier",
                    target=target, other=other, classes_seen=classes,
                    url=f"https://huggingface.co/datasets/{repo}", tried=tried)
        plan.previews = _previews(peek, plan, wid)
        say(f"{repo}: learning {', '.join(target)}" + (f" vs {', '.join(other)}" if other else ""))
        return plan
    say("no open public dataset matched this request: " + "; ".join(f"{t['repo']}: {t['why']}" for t in tried[:4]))
    return None


def _distinct(cands: list[dict]) -> list[dict]:
    """Many Hub datasets are re-uploads of the same thing under another account; try each name once
    (the most downloaded copy)."""
    best: dict[str, dict] = {}
    for c in cands:
        key = c["id"].split("/")[-1].lower().replace("_", "-")
        if key not in best or c["downloads"] > best[key]["downloads"]:
            best[key] = c
    return list(best.values())


def _take(it, n):
    for i, x in enumerate(it):
        if i >= n:
            return
        yield x


def _check_with_images(peek, target, other, spec, embedder):
    """The class names say which is YES; the pictures must agree (catches swapped or cryptic names)."""
    crops: dict[str, list[np.ndarray]] = {}
    for img, items in peek:
        for box, c in items:
            if c in target or c in other:
                cr = pd._crop(img, box, 0.15)
                if cr is not None and len(crops.setdefault(c, [])) < 30:
                    crops[c].append(cr)
    if not any(crops.get(c) for c in target) or not any(crops.get(c) for c in other):
        return target, other, True
    w0, b0 = embedder.zero_shot_direction(spec.positive_label, spec.negative_label)

    def score(group):
        ims = [x for c in group for x in crops.get(c, [])]
        return float((1 / (1 + np.exp(-(embedder.embed_images(ims) @ w0 + b0)))).mean()) if ims else 0.5

    gap = score(target) - score(other)
    if gap < -0.03:
        return other, target, True       # names said one thing, images the other: trust the images
    return target, other, gap >= -0.01


def _previews(peek, plan: Plan, wid: int, n: int = 6) -> list[str]:
    """A few dataset images with the target drawn, so the user sees what the model will learn from."""
    out_dir = root(wid) / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for img, items in peek:
        hits = [(b, c) for b, c in items if c in plan.target]
        if not hits:
            continue
        im = _fit(img)[0].copy()
        s = im.shape[1] / img.shape[1]
        for b, _ in hits:
            if b is None:
                continue
            x, y, w, h = [v * s for v in b]
            cv2.rectangle(im, (int(x), int(y)), (int(x + w), int(y + h)), (96, 245, 200), 2)
        name = f"{len(names)}.jpg"
        cv2.imwrite(str(out_dir / name), im, [cv2.IMWRITE_JPEG_QUALITY, 82])
        names.append(name)
        if len(names) >= n:
            break
    return names


# ---------------------------------------------------------------------------------------------
# 3. write the training set


def _fit(img: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    s = min(1.0, MAX_SIDE / max(h, w))
    return (cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img), s


def write_dataset(plan: Plan, wid: int, *, max_images: int = MAX_IMAGES, extra_backgrounds: list[np.ndarray] = (),
                  say: Callable[[str], None] = lambda m: None) -> dict:
    """COCO folders (train/valid) for a detector, or class folders (train/valid/{yes,no}) for a classifier."""
    base = root(wid) / "dataset"
    if base.exists():
        import shutil

        shutil.rmtree(base)
    rng = random.Random(wid)
    keep = set(plan.target) | set(plan.other)
    rows: list[tuple[np.ndarray, list]] = []
    n_target = 0
    for img, items in pd.examples(plan.repo, max_images=max_images):
        mine = [(b, c) for b, c in items if c in keep]
        if plan.kind == "classifier":
            if not mine:
                continue
            label = "yes" if mine[0][1] in plan.target else "no"
            rows.append((img, [label]))
            n_target += label == "yes"
        else:
            if not mine and rng.random() > 0.15:
                continue                      # keep some empty scenes so the model learns "nothing here"
            rows.append((img, mine))
            n_target += sum(1 for _, c in mine if c in plan.target)
        if len(rows) % 100 == 0:
            say(f"downloaded {len(rows)} images ({n_target} examples of what you asked for)")
    for bg in extra_backgrounds:
        rows.append((bg, [] if plan.kind == "detector" else ["no"]))
    rng.shuffle(rows)
    n_val = max(10, int(len(rows) * VAL_FRAC))
    splits = {"valid": rows[:n_val], "train": rows[n_val:]}
    if plan.kind == "classifier":
        for split, rs in splits.items():
            for i, (img, (label,)) in enumerate(rs):
                d = base / split / label
                d.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(d / f"{i}.jpg"), _fit(img)[0], [cv2.IMWRITE_JPEG_QUALITY, 90])
    else:
        cats = [{"id": 0, "name": "target", "supercategory": "none"}]
        if plan.other:
            cats.append({"id": 1, "name": "other", "supercategory": "none"})
        for split, rs in splits.items():
            d = base / split
            d.mkdir(parents=True, exist_ok=True)
            images, anns = [], []
            for i, (img, items) in enumerate(rs):
                im, s = _fit(img)
                fn = f"{i}.jpg"
                cv2.imwrite(str(d / fn), im, [cv2.IMWRITE_JPEG_QUALITY, 90])
                h, w = im.shape[:2]
                images.append({"id": i, "file_name": fn, "width": w, "height": h})
                for b, c in items:
                    if b is None:
                        continue
                    x, y, bw, bh = [float(v) * s for v in b]
                    x, y = max(0.0, x), max(0.0, y)
                    bw, bh = min(bw, w - x), min(bh, h - y)
                    if bw < 2 or bh < 2:
                        continue
                    anns.append({"id": len(anns), "image_id": i, "category_id": 0 if c in plan.target else 1,
                                 "bbox": [x, y, bw, bh], "area": bw * bh, "iscrowd": 0})
            (d / "_annotations.coco.json").write_text(json.dumps({"images": images, "annotations": anns,
                                                                  "categories": cats}))
    info = {"images": len(rows), "train": len(splits["train"]), "valid": len(splits["valid"]),
            "target_examples": n_target}
    (root(wid) / "dataset.json").write_text(json.dumps({**info, "plan": plan.out()}))
    return info


# ---------------------------------------------------------------------------------------------
# 4. train (separate process: MPS training next to live inference in one process is not safe)


def train(wid: int, kind: str, *, epochs: int, on_progress: Callable[[dict], None],
          cancelled: threading.Event | None = None) -> dict:
    out = root(wid)
    cmd = [sys.executable, "-m", "vigil.learning.train_worker", "--kind", kind, "--dir", str(out),
           "--epochs", str(epochs)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                            cwd=str(Path(__file__).resolve().parents[2]))
    result: dict = {}
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        if cancelled is not None and cancelled.is_set():
            proc.terminate()
            raise RuntimeError("cancelled")
        line = line.strip()
        if line.startswith("@@"):
            msg = json.loads(line[2:])
            if msg.get("type") == "result":
                result = msg
            else:
                on_progress(msg)
        elif line:
            tail = (tail + [line])[-15:]
    proc.wait()
    if proc.returncode != 0 or not result:
        raise RuntimeError("training failed: " + (" | ".join(tail[-3:]) or f"exit {proc.returncode}"))
    (out / "model.json").write_text(json.dumps(result))
    return result


# ---------------------------------------------------------------------------------------------
# 5. run it


@dataclass
class Hit:
    box: tuple[float, float, float, float]   # normalized xyxy
    conf: float


class TrainedModel:
    """The watch's own model. detect() -> target boxes; proba() -> P(YES) for whole-image classifiers."""

    def __init__(self, wid: int, meta: dict):
        self.wid = wid
        self.meta = meta
        self.kind = meta["kind"]
        self.threshold = float(meta.get("threshold", 0.5))
        self._model = None
        self._tf = None

    @classmethod
    def load(cls, wid: int) -> "TrainedModel | None":
        p = root(wid) / "model.json"
        if not p.exists():
            return None
        meta = json.loads(p.read_text())
        if not Path(meta.get("weights", "")).exists():
            return None
        return cls(wid, meta)

    def _ensure(self):
        if self._model is not None:
            return
        with gpu_lock:
            if self.kind == "detector":
                import rfdetr

                self._model = rfdetr.RFDETRNano(pretrain_weights=self.meta["weights"],
                                                num_classes=int(self.meta["num_classes"]))
            else:
                import torch
                from torchvision import models, transforms

                m = models.mobilenet_v3_large()
                m.classifier[3] = torch.nn.Linear(m.classifier[3].in_features, 2)
                m.load_state_dict(torch.load(self.meta["weights"], map_location="cpu"))
                dev = "mps" if torch.backends.mps.is_available() else "cpu"
                self._model = m.to(dev).eval()
                self._dev = dev
                self._tf = transforms.Compose([transforms.ToPILImage(), transforms.Resize((224, 224)),
                                               transforms.ToTensor(),
                                               transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])

    def detect(self, frame: np.ndarray) -> list[Hit]:
        self._ensure()
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        with gpu_lock:
            d = self._model.predict(rgb, threshold=min(self.threshold, 0.3))
        tid = int(self.meta.get("target_class_id", 0))
        return [Hit((float(b[0] / w), float(b[1] / h), float(b[2] / w), float(b[3] / h)), float(c))
                for b, k, c in zip(d.xyxy, d.class_id, d.confidence) if int(k) == tid]

    def proba(self, frame: np.ndarray) -> float:
        self._ensure()
        import torch

        x = self._tf(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).unsqueeze(0).to(self._dev)
        with gpu_lock, torch.no_grad():
            p = torch.softmax(self._model(x), dim=1)[0]
        return float(p[int(self.meta.get("yes_index", 1))])


def summary(wid: int) -> dict | None:
    p = root(wid) / "model.json"
    return json.loads(p.read_text()) if p.exists() else None


