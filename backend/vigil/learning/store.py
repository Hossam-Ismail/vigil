"""Model versions and labeled samples for each watch, plus the retrain entry point."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..bus import bus
from ..config import settings
from ..db import DB
from ..perception.embedder import Embedder
from ..schemas import WatchSpec
from .heads import Head, train_head

log = logging.getLogger("vigil.learning")

BOOTSTRAP_ORIGINS = {"history", "live"}  # samples taken from past/collected footage while building


def prior_labels(spec: WatchSpec) -> tuple[str, str]:
    """Text pair that defines the zero-shot direction for this watch's head."""
    if spec.kind == "state" or spec.target_question:
        return spec.positive_label, spec.negative_label
    target = spec.targets[0] if spec.targets else "object"
    return f"a {target}", "an empty background"


def crop_task(spec: WatchSpec, prompt: str, camera_name: str = "") -> "LabelTask":
    """The yes/no question asked about each training crop.

    State watches: the frame-level question about the region. Presence/count watches: an object-level
    question ("is this a real person?" or the attribute check). Entering, counting and timing are handled
    by the tracker and zone logic, so they must not leak into crop labels.
    """
    from ..brain.base import LabelTask

    pos, neg = prior_labels(spec)
    ctx = (f"Camera '{camera_name}'. " if camera_name else "") + f"User request: {prompt}"
    if spec.kind == "state":
        return LabelTask(spec.question, pos, neg, context=ctx)
    if spec.target_question:
        return LabelTask(spec.target_question, pos, neg,
                         context=ctx + ". Each image is a close-up crop of one detected object.")
    target = spec.targets[0] if spec.targets else "object"
    return LabelTask(
        f"Does this crop clearly show a real {target}?",
        f"a {target}",
        f"not a {target}: background, a reflection, a picture or poster, or a wrong detection",
        context=ctx + ". Each image is a close-up crop of something an object detector flagged.",
    )


def watch_dir(wid: int) -> Path:
    d = settings.data_dir / "models" / f"watch_{wid}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sample_dir(wid: int) -> Path:
    d = settings.data_dir / "media" / "samples" / str(wid)
    d.mkdir(parents=True, exist_ok=True)
    return d


class ModelStore:
    def __init__(self, db: DB, embedder_fn: Callable[[], Embedder]):
        self.db = db
        self._embedder_fn = embedder_fn
        self._locks: dict[int, threading.Lock] = {}
        self.on_head: Callable[[int, Head], None] | None = None  # engine hook for hot-swapping

    @property
    def embedder(self) -> Embedder:
        return self._embedder_fn()

    def zero_shot(self, spec: WatchSpec) -> Head:
        pos, neg = prior_labels(spec)
        w0, b0 = self.embedder.zero_shot_direction(pos, neg)
        return Head(w0, b0, 0.5, "zeroshot", 0, {"mode": "zeroshot", "n": 0, "n_pos": 0, "n_neg": 0})

    def load(self, watch: dict) -> Head:
        version = watch.get("model_version") or 0
        path = watch_dir(watch["id"]) / f"v{version}.npz"
        if version and path.exists():
            try:
                return Head.load(path)
            except Exception as exc:  # noqa: BLE001
                log.warning("could not load head %s: %s", path, exc)
        return self.zero_shot(WatchSpec.model_validate(watch["spec"]))

    def add_sample(self, wid: int, image: np.ndarray, emb: np.ndarray | None = None, **fields) -> dict:
        if emb is None:
            emb = self.embedder.embed_images([image])[0]
        ts = fields.pop("ts", time.time())
        path = sample_dir(wid) / f"{int(ts * 1000)}_{np.random.randint(1e6)}.jpg"
        h, w = image.shape[:2]
        s = min(1.0, 384 / max(h, w))
        thumb = cv2.resize(image, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else image
        cv2.imwrite(str(path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 88])
        rel = str(path.relative_to(settings.data_dir / "media"))
        sid = self.db.add_sample(wid, rel, emb, ts=ts, **fields)
        return self.db.sample(sid)  # type: ignore[return-value]

    def retrain(self, wid: int, reason: str = "") -> Head | None:
        lock = self._locks.setdefault(wid, threading.Lock())
        with lock:
            watch = self.db.watch(wid)
            if not watch:
                return None
            spec = WatchSpec.model_validate(watch["spec"])
            X, y, _, sources, origins = self.db.training_set(wid, with_origin=True)
            if len(y) and not y.any():
                # The event has never been seen. Past footage only shows "normal", so learning from it would
                # just bake in today's scene; stay on the prompt until a real event is confirmed. Corrections
                # made on live alerts (feedback, verifier, teach, active learning) still count.
                keep = np.array([o not in BOOTSTRAP_ORIGINS for o in origins], dtype=bool)
                X, y = X[keep], y[keep]
                sources = [s_ for s_, k in zip(sources, keep) if k]
            pos, neg = prior_labels(spec)
            w0, b0 = self.embedder.zero_shot_direction(pos, neg)
            version = (watch.get("model_version") or 0) + 1
            t = time.time()
            head = train_head(X, y, w0, b0, version=version) if len(y) else Head(
                w0, b0, 0.5, "zeroshot", version, {"mode": "zeroshot", "n": 0, "n_pos": 0, "n_neg": 0})
            head.metrics["trained_at"] = time.time()
            head.metrics["train_ms"] = round((time.time() - t) * 1000, 1)
            head.metrics["reason"] = reason
            head.metrics["sources"] = {s: sources.count(s) for s in set(sources)}
            head.save(watch_dir(wid) / f"v{version}.npz")
            self.db.update_watch(wid, model_version=version, metrics=head.metrics)
            log.info("watch %s retrained v%s (%s, n=%s) %s", wid, version, head.mode, len(y), reason)
        if self.on_head:
            self.on_head(wid, head)
        bus.publish("model", {"watch_id": wid, "version": version, "metrics": head.metrics})
        return head
