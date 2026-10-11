"""Bootstrap a watch's model: collect frames -> candidate crops -> pick a diverse, informative
subset -> label with the brain (teacher) -> train the head -> deploy.

The brain is expensive, so it labels a few dozen carefully chosen crops; the head then runs on every
frame for free. Candidates come from the camera's on-disk history (hours of past frames) plus a short
live capture, so rare states that happened earlier (an empty bin this morning) can be found.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from ..brain import BrainError, get_brain
from ..bus import bus
from ..cameras.manager import CameraRuntime
from ..config import settings
from ..db import DB
from ..perception.detector import coco_class_for, get_coco, get_owl
from ..perception.geometry import anchor, crop, point_in_zone, zone_crop
from ..schemas import WatchSpec
from .store import ModelStore, crop_task, prior_labels

log = logging.getLogger("vigil.builder")

MIN_CONFIDENT = 0.55  # teacher labels below this confidence wait for human review


@dataclass
class Candidate:
    image: np.ndarray
    ts: float
    origin: str
    emb: np.ndarray | None = None
    prior: float = 0.0
    det_conf: float | None = None


def k_center(X: np.ndarray, k: int, seed_idx: list[int]) -> list[int]:
    """Greedy k-center selection on cosine distance, starting from seed indices."""
    n = len(X)
    if n <= k:
        return list(range(n))
    chosen = list(dict.fromkeys(seed_idx))[:k]
    if not chosen:
        chosen = [0]
    d = 1 - X @ X[chosen].T
    mind = d.min(axis=1)
    while len(chosen) < k:
        i = int(np.argmax(mind))
        if mind[i] <= 1e-4:
            break
        chosen.append(i)
        mind = np.minimum(mind, 1 - X @ X[i])
    return chosen


def dedupe(X: np.ndarray, thr: float = 0.985) -> list[int]:
    keep: list[int] = []
    for i in range(len(X)):
        if not keep or float(np.max(X[keep] @ X[i])) < thr:
            keep.append(i)
    return keep


class BuildJob:
    def __init__(self, db: DB, store: ModelStore, cam: CameraRuntime, watch_id: int,
                 on_done: Callable[[int], None], collect_seconds: float | None = None,
                 label_budget: int | None = None):
        self.db = db
        self.store = store
        self.cam = cam
        self.wid = watch_id
        self.on_done = on_done
        self.collect_seconds = settings.collect_seconds if collect_seconds is None else collect_seconds
        self.label_budget = label_budget or settings.label_budget
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"build-{watch_id}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    # ---- progress ----------------------------------------------------
    def _progress(self, stage: str, progress: float, message: str, **extra) -> None:
        self.db.update_watch(self.wid, status="building", status_detail=f"{stage}: {message}")
        bus.publish("build", {"watch_id": self.wid, "stage": stage, "progress": round(progress, 3),
                              "message": message, **extra})

    # ---- pipeline ----------------------------------------------------
    def _run(self) -> None:
        try:
            self._build()
        except Exception as exc:  # noqa: BLE001
            log.exception("build %s failed", self.wid)
            self.db.update_watch(self.wid, status="error", status_detail=str(exc)[:300])
            bus.publish("build", {"watch_id": self.wid, "stage": "error", "progress": 1, "message": str(exc)[:300]})

    def _go_live_existing(self, spec: WatchSpec) -> None:
        """Run on an existing model as-is: no frames collected, nothing labeled, nothing trained."""
        from . import existing
        from . import finetune as ft

        (ft.root(self.wid) / "model.json").unlink(missing_ok=True)  # never a leftover fine-tuned model
        choice = existing.choose(spec)
        names = " + ".join(m["name"] for m in choice["models"])
        metrics = {"mode": "existing", "dataset": choice, "trained_at": time.time()}
        self._merge_metrics(**metrics)
        detail = f"live on {names}, no training: {choice['how']}"
        self.db.update_watch(self.wid, status="active", status_detail=detail)
        bus.publish("build", {"watch_id": self.wid, "stage": "done", "progress": 1.0, "message": detail,
                              "metrics": metrics})
        self.on_done(self.wid)

    def _build_finetuned(self, watch: dict, spec: WatchSpec, brain) -> bool:
        """Find public data for this request, fine-tune the watch's own model on it, and go live.

        Returns False (and the older camera-labeled head is built instead) when no usable public dataset exists.
        """
        from . import finetune as ft

        coco = ft.pretrained_fits(spec)
        if coco:
            # common objects: the base detector, trained on COCO's 118k public images, is the model for this
            spec.target_question = ""
            self.db.update_watch(self.wid, spec=spec.model_dump())
            (ft.root(self.wid) / "model.json").unlink(missing_ok=True)
            metrics = {"mode": "pretrained", "dataset": {"state": "pretrained", "classes": coco},
                       "trained_at": time.time()}
            self._merge_metrics(**metrics)
            detail = (f"uses Vigil's detector trained on COCO (118k public images), where {', '.join(coco)} "
                      "is one of the 80 classes it already knows; ready instantly")
            self.db.update_watch(self.wid, status="active", status_detail=detail)
            bus.publish("build", {"watch_id": self.wid, "stage": "done", "progress": 1.0, "message": detail,
                                  "metrics": metrics})
            self.on_done(self.wid)
            return True

        found = (watch.get("metrics") or {}).get("dataset") or {}
        plan = ft.Plan(**found["plan"]) if found.get("plan") else None
        if plan is None:
            self._progress("data", 0.02, "looking for public training data")
            plan = ft.find(spec, watch["prompt"], self.wid, brain=brain, embedder=self.store.embedder,
                           say=lambda m: self._progress("data", 0.03, m))
        if plan is None or self.cancelled.is_set():
            self._merge_metrics(dataset={"state": "none"})
            self._progress("collect", 0.05, "no public dataset fits this request; learning from this camera instead")
            return False
        self._merge_metrics(dataset={"state": "found", "plan": plan.out()})
        n_max = settings.finetune_images

        def data_progress(m: str) -> None:
            got = int(m.split()[1]) if m.startswith("downloaded ") else 0
            self._progress("data", 0.05 + 0.2 * min(1.0, got / n_max), m)

        self._progress("data", 0.05, f"downloading up to {n_max} images from {plan.repo}")
        info = ft.write_dataset(plan, self.wid, max_images=n_max, extra_backgrounds=self._false_alarm_frames(),
                                say=data_progress)
        if info["target_examples"] < ft.MIN_TARGET:
            self._merge_metrics(dataset={"state": "too_small", "plan": plan.out(), "data": info})
            self._progress("collect", 0.05, f"only {info['target_examples']} examples in {plan.repo}; "
                                            "learning from this camera instead")
            return False
        self._progress("train", 0.25, f"training a {plan.kind} on {info['train']} images "
                                      f"({info['target_examples']} examples of what you asked for)", data=info)

        def on_progress(p: dict) -> None:
            if p.get("stage") == "evaluate":
                self._progress("evaluate", 0.88 + 0.1 * p.get("progress", 0), p.get("message", ""))
            else:
                self._progress("train", 0.25 + 0.6 * p.get("progress", 0), p.get("message", ""))

        res = ft.train(self.wid, plan.kind, epochs=settings.finetune_epochs, on_progress=on_progress,
                       cancelled=self.cancelled)
        ev = res.get("eval") or {}
        metrics = {"mode": "finetuned", "kind": plan.kind, "threshold": res.get("threshold"),
                   "dataset": {"state": "trained", "plan": plan.out(), "data": info}, "eval": ev,
                   "trained_at": time.time(), "n": info["train"], "n_pos": info["target_examples"]}
        self._merge_metrics(**metrics)
        detail = (f"trained on {info['images']} images from {plan.repo}; on {ev.get('n', 0)} held-out images it "
                  f"was right {round(100 * ev.get('accuracy', 0))}% of the time (F1 {ev.get('f1', 0):.2f})")
        self.db.update_watch(self.wid, status="active", status_detail=detail)
        bus.publish("build", {"watch_id": self.wid, "stage": "done", "progress": 1.0, "message": detail,
                              "metrics": metrics})
        self.on_done(self.wid)
        return True

    def _merge_metrics(self, **fields) -> None:
        w = self.db.watch(self.wid) or {}
        self.db.update_watch(self.wid, metrics={**(w.get("metrics") or {}), **fields})

    def _false_alarm_frames(self) -> list[np.ndarray]:
        """Frames from alerts someone marked wrong: next training run learns there is nothing to find there."""
        out = []
        for e in self.db.all("SELECT id FROM events WHERE watch_id=? AND feedback='false_alarm' ORDER BY ts DESC "
                             "LIMIT 40", (self.wid,)):
            p = settings.data_dir / "media" / "events" / str(e["id"]) / "frame.jpg"
            img = cv2.imread(str(p)) if p.exists() else None
            if img is not None:
                out.append(img)
        return out

    def _collect_frames(self) -> list[tuple[float, np.ndarray, str]]:
        frames: list[tuple[float, np.ndarray, str]] = []
        hist = self.cam.history(limit=600)
        if len(hist) > 120:
            idx = np.linspace(0, len(hist) - 1, 120).astype(int)
            hist = [hist[i] for i in idx]
        for p in hist:
            img = cv2.imread(str(p))
            if img is not None:
                frames.append((int(p.stem) / 1000, img, "history"))
        self._progress("collect", 0.05, f"{len(frames)} frames from history; watching live for "
                                        f"{self.collect_seconds:.0f}s")
        t_end = time.time() + self.collect_seconds
        last_no = 0
        while time.time() < t_end and not self.cancelled.is_set():
            frame, ts, no = self.cam.wait_frame(last_no, timeout=2)
            if frame is not None and no != last_no:
                last_no = no
                frames.append((ts, frame.copy(), "live"))
                frac = 1 - (t_end - time.time()) / max(1e-6, self.collect_seconds)
                self._progress("collect", 0.05 + 0.2 * frac, f"{len(frames)} frames collected")
            time.sleep(0.5)
        if not frames:
            raise RuntimeError("camera produced no frames; check that it is online")
        return frames

    def _candidates(self, spec: WatchSpec, frames: list[tuple[float, np.ndarray, str]]) -> list[Candidate]:
        if spec.kind == "state":
            return [Candidate(zone_crop(f, spec.zone), ts, origin) for ts, f, origin in frames]
        cands: list[Candidate] = []
        coco = {t: coco_class_for(t) for t in spec.targets}
        wanted: dict[str, list[str]] = {}
        for t, c in coco.items():
            if c:
                wanted.setdefault(c, []).append(t)
        owl_targets = [t for t, c in coco.items() if not c]
        for i, (ts, f, origin) in enumerate(frames):
            dets = []
            if wanted:
                dets += get_coco().detect(f, wanted, threshold=0.25)
            if owl_targets:
                dets += get_owl().detect(f, owl_targets, threshold=0.1)
            for d in dets:
                if point_in_zone(*anchor(d.box), spec.zone):
                    cands.append(Candidate(crop(f, d.box, pad=0.12), ts, origin, det_conf=d.conf))
            if i % 5 == 0:
                self._progress("candidates", 0.25 + 0.15 * i / len(frames), f"{len(cands)} object crops found")
        return cands

    def _build(self) -> None:
        watch = self.db.watch(self.wid)
        if not watch:
            return
        spec = WatchSpec.model_validate(watch["spec"])
        brain = get_brain()
        if not settings.finetune:
            self._go_live_existing(spec)
            return
        if self._build_finetuned(watch, spec, brain):
            return
        self._progress("collect", 0.0, "gathering frames")
        frames = self._collect_frames()
        if self.cancelled.is_set():
            return

        cands = self._candidates(spec, frames)
        self._progress("candidates", 0.4, f"{len(cands)} candidates")
        emb = self.store.embedder
        if cands:
            X = emb.embed_images([c.image for c in cands])
            pos, neg = prior_labels(spec)
            w0, b0 = emb.zero_shot_direction(pos, neg)
            prior = 1 / (1 + np.exp(-(X @ w0 + b0)))
            for c, x, p in zip(cands, X, prior):
                c.emb, c.prior = x, float(p)
            keep = dedupe(X)
            cands = [cands[i] for i in keep]
            X = X[keep]
            budget = min(self.label_budget, len(cands))
            if spec.kind != "state" and not spec.target_question:
                # plain presence/count: the detector already knows what a person is; spend a small
                # budget on its least confident detections, which is where false positives live
                budget = min(budget, 16)
                seeds = list(np.argsort([c.det_conf or 0 for c in cands])[: max(1, budget // 2)])
            else:
                # spend a third of the budget on the most "positive-looking" crops (rare states are what we
                # most need examples of) plus the most negative-looking one, and the rest on visual variety
                seeds = list(np.argsort([-c.prior for c in cands])[: max(1, budget // 3)])
                seeds.append(int(np.argmin([c.prior for c in cands])))
            chosen = k_center(X, budget, [int(i) for i in seeds])
            selected = [cands[i] for i in chosen]
        else:
            selected = []

        self._progress("label", 0.45, f"asking {brain.label} to label {len(selected)} examples",
                       brain=brain.label)
        task = crop_task(spec, watch["prompt"], self.cam.name)
        batch = 8 if brain.name == "anthropic" else 6
        n_labeled = n_pos = 0
        for start in range(0, len(selected), batch):
            if self.cancelled.is_set():
                return
            chunk = selected[start : start + batch]
            try:
                verdicts = brain.judge([c.image for c in chunk], task)
            except BrainError as exc:
                raise RuntimeError(f"labeling failed: {exc}") from exc
            new = []
            for c, v in zip(chunk, verdicts):
                label = None if v.answer is None or v.confidence < MIN_CONFIDENT else int(v.answer)
                if brain.name == "heuristic":
                    # zero-shot guesses are suggestions for review, never labels: training on them would just
                    # feed the prior its own output
                    label = None
                s = self.store.add_sample(
                    self.wid, c.image, c.emb, ts=c.ts, label=label, source=brain.name,
                    confidence=v.confidence, reason=v.reason, score=c.prior, origin=c.origin,
                )
                new.append(s)
                if label is not None:
                    n_labeled += 1
                    n_pos += label
            done = min(len(selected), start + batch)
            self._progress("label", 0.45 + 0.45 * done / max(1, len(selected)),
                           f"labeled {done}/{len(selected)} ({n_pos} yes)", samples=new)

        self._progress("train", 0.92, "training the watch model")
        head = self.store.retrain(self.wid, reason="bootstrap")
        detail = "ready"
        if head is not None and head.mode in ("zeroshot", "oneclass_neg") and n_pos == 0:
            detail = ("watching from your description: this hasn't happened on camera yet, so it starts from your "
                      "words and self-improves from the first confirmed event")
        elif head is not None and head.mode == "zeroshot":
            detail = "watching from your description; label a few examples to improve it"
        self.db.update_watch(self.wid, status="active", status_detail=detail)
        bus.publish("build", {"watch_id": self.wid, "stage": "done", "progress": 1.0, "message": detail,
                              "metrics": head.metrics if head else {}})
        self.on_done(self.wid)
