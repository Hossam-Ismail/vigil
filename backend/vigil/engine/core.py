"""The engine: one analysis thread per camera running every active watch on that camera.

Per tick (default 4 Hz):
  motion gate -> shared detections (RF-DETR for COCO targets, OWLv2 for the rest, rate-limited)
  -> one batched SigLIP pass over every crop any watch needs -> per-watch heads -> state machines
  -> triggers go to the EventManager; uncertain crops go to the ActiveLearner.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict

import cv2
import numpy as np

from ..bus import bus
from ..cameras.manager import CameraHub, CameraRuntime
from ..config import settings
from ..db import DB
from ..learning.active import ActiveLearner
from ..learning.builder import BuildJob
from ..learning.finetune import TrainedModel
from ..perception.library import runner_for as library_runner
from ..learning.heads import Head
from ..learning.store import ModelStore
from ..perception.detector import Detection, coco_class_for, get_coco, get_owl
from ..perception.embedder import get_embedder
from ..perception.geometry import crop, zone_crop
from ..perception.motion import MotionGate
from .events import EventManager
from .runtime import WatchRuntime

log = logging.getLogger("vigil.engine")

MODEL_INTERVAL_S = 0.5  # a watch's own model runs twice a second


class CameraAnalyzer:
    def __init__(self, engine: "Engine", cam: CameraRuntime):
        self.engine = engine
        self.cam = cam
        self.gate = MotionGate()
        self.stop_event = threading.Event()
        self.last_owl = 0.0
        self.owl_cache: list[Detection] = []
        self.last: dict = {}
        self.tick_ms = 0.0
        self.thread = threading.Thread(target=self._run, name=f"analyze-{cam.id}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        last_no, last_tick = 0, 0.0
        period = 1.0 / settings.analysis_fps
        while not self.stop_event.is_set():
            frame, ts, no = self.cam.wait_frame(last_no, timeout=1.0)
            if frame is None or no == last_no:
                continue
            now = time.monotonic()
            if now - last_tick < period:
                time.sleep(max(0.0, period - (now - last_tick)) * 0.9)
                continue
            last_no, last_tick = no, time.monotonic()
            try:
                self._tick(frame, ts)
            except Exception:  # noqa: BLE001
                log.exception("analysis tick failed on camera %s", self.cam.id)
                time.sleep(1.0)

    def _run_models(self, rts: list[WatchRuntime], frame: np.ndarray, ts: float) -> list[Detection]:
        """Watches with their own fine-tuned model: the model's output is the answer, no zones or rules on top
        (an area the user drew still limits where it looks)."""
        shown: list[Detection] = []
        for rt in rts:
            if ts - rt.last_eval < MODEL_INTERVAL_S:
                continue
            m = rt.model
            try:
                if m.kind == "detector":
                    label = rt.spec.locate_noun or (rt.spec.targets[0] if rt.spec.targets else rt.name)
                    hits = [h for h in m.detect(frame) if h.conf >= m.threshold]
                    found = [Detection(label, h.conf, h.box, "watch") for h in hits]
                    shown += found
                    trig = rt.step_objects(ts, found, None)
                elif m.kind == "video":
                    ring = self.cam.clip_frames(ts - 2.0, ts)
                    frames = [f for f in (cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR) for _, j in ring)
                              if f is not None]
                    if len(frames) < 4:
                        continue
                    trig = rt.step_state(ts, p=m.proba_clip(frames), threshold=m.threshold)
                else:
                    trig = rt.step_state(ts, p=m.proba(zone_crop(frame, rt.spec.zone)), threshold=m.threshold)
            except Exception:  # noqa: BLE001
                log.exception("model for watch %s failed", rt.id)
                rt.last_eval = ts + 5
                continue
            if trig and rt.spec.alerts:
                self.engine.events.create(trig, frame)
        return shown

    def _tick(self, frame: np.ndarray, ts: float) -> None:
        t0 = time.perf_counter()
        everyone = [rt for rt in self.engine.runtimes_for(self.cam.id) if not rt.paused]
        motion = self.gate.update(frame)
        model_dets = self._run_models([rt for rt in everyone if rt.uses_model], frame, ts)
        runtimes = [rt for rt in everyone if not rt.uses_model]
        dets: list[Detection] = []
        object_rts = [rt for rt in runtimes if not rt.is_state]
        if object_rts:
            wanted: dict[str, list[str]] = defaultdict(list)
            owl_targets: list[str] = []
            for rt in object_rts:
                for t in rt.spec.targets:
                    c = coco_class_for(t)
                    if c:
                        if t not in wanted[c]:
                            wanted[c].append(t)
                    elif t not in owl_targets:
                        owl_targets.append(t)
            if wanted:
                dets += get_coco().detect(frame, dict(wanted), threshold=0.4)
            if owl_targets:
                stale = ts - self.last_owl
                if stale >= settings.open_vocab_interval_s and (motion > 0.002 or stale > 5):
                    self.owl_cache = get_owl().detect(frame, owl_targets, threshold=0.2)
                    self.last_owl = ts
                if ts - self.last_owl < 3.0:
                    dets += self.owl_cache

        # gather every crop that needs an embedding, then run one batched pass
        crops: list[np.ndarray] = []
        owners: list[tuple[WatchRuntime, int]] = []
        per_rt_dets: dict[int, list[Detection]] = {}
        for rt in runtimes:
            if rt.is_state:
                if rt.due(ts):
                    crops.append(zone_crop(frame, rt.spec.zone))
                    owners.append((rt, -1))
            else:
                mine = [d for d in dets if d.label in rt.spec.targets]
                per_rt_dets[rt.id] = mine
                if rt.uses_object_head:
                    for i, d in enumerate(mine):
                        if rt.relevant(d):  # far-away objects keep their last score; saves most of the work
                            crops.append(crop(frame, d.box, pad=0.12))
                            owners.append((rt, i))
        embs = get_embedder().embed_images(crops) if crops else np.zeros((0, 1), np.float32)

        obj_probs: dict[int, dict[int, float]] = defaultdict(dict)
        for (rt, idx), c, e in zip(owners, crops, embs):
            if idx == -1:
                trig = rt.step_state(ts, e)
                rt.last_crop, rt.last_crop_emb = c, e
                self.engine.learner.offer(rt.id, c, e, rt.score or 0.0, rt.head.threshold)
                if trig and rt.spec.alerts:
                    self.engine.events.create(trig, frame)
            else:
                p = float(rt.head.proba(e)[0])
                obj_probs[rt.id][idx] = p
                self.engine.learner.offer(rt.id, c, e, p, rt.head.threshold)
        for rt in object_rts:
            mine = per_rt_dets.get(rt.id, [])
            probs = None
            if rt.uses_object_head:
                scored = obj_probs.get(rt.id, {})
                # far-away detections are not scored this tick (None): their tracks keep the last score
                probs = [scored.get(i) for i in range(len(mine))]
            trig = rt.step_objects(ts, mine, probs)
            if trig and rt.spec.alerts:
                self.engine.events.create(trig, frame)
        dets += model_dets
        runtimes = everyone
        rows = [r for rt in runtimes for r in rt.pop_metric_rows()]
        if rows:
            self.engine.db.add_metric_rows(rows)

        self.tick_ms = (time.perf_counter() - t0) * 1000
        self.last = {
            "camera_id": self.cam.id,
            "ts": ts,
            "motion": round(motion, 4),
            "tick_ms": round(self.tick_ms, 1),
            "detections": [
                {"label": d.label, "conf": round(d.conf, 3), "box": [round(v, 4) for v in d.box], "source": d.source}
                for d in dets
            ],
            "watches": [rt.snapshot(spark=False) for rt in runtimes],
        }
        bus.publish("perception", self.last, throttle_key=f"perception-{self.cam.id}", min_interval=0.2)


class Engine:
    def __init__(self, db: DB, hub: CameraHub, store: ModelStore, events: EventManager, learner: ActiveLearner):
        self.db = db
        self.hub = hub
        self.store = store
        self.events = events
        self.learner = learner
        self.runtimes: dict[int, WatchRuntime] = {}
        self.analyzers: dict[int, CameraAnalyzer] = {}
        self.builds: dict[int, BuildJob] = {}
        self._lock = threading.RLock()
        store.on_head = self._on_head

    # ---- watches -------------------------------------------------------
    def load_all(self) -> None:
        for w in self.db.watches():
            if w["status"] in ("active", "paused"):
                try:
                    self.activate(w)
                except Exception:  # noqa: BLE001
                    log.exception("could not activate watch %s", w["id"])
            elif w["status"] == "building":
                self.db.update_watch(w["id"], status="draft", status_detail="build interrupted by restart")

    def activate(self, watch: dict) -> WatchRuntime:
        head = self.store.load(watch)
        rt = WatchRuntime(watch, head)
        rt.model = TrainedModel.load(watch["id"]) or library_runner(rt.spec)
        # keep the cooldown across restarts so an ongoing condition does not re-alert on boot
        last = self.db.one("SELECT ts FROM events WHERE watch_id=? AND status != 'suppressed' ORDER BY ts DESC LIMIT 1",
                           (watch["id"],))
        if last:
            rt.machine.last_alert = last["ts"]
            rt.last_object_alert = last["ts"]
        with self._lock:
            self.runtimes[watch["id"]] = rt
        self.ensure_analyzer(watch["camera_id"])
        return rt

    def reload(self, wid: int) -> None:
        watch = self.db.watch(wid)
        if watch and watch["status"] in ("active", "paused"):
            self.activate(watch)
        else:
            self.deactivate(wid)

    def deactivate(self, wid: int) -> None:
        with self._lock:
            self.runtimes.pop(wid, None)

    def runtimes_for(self, cid: int) -> list[WatchRuntime]:
        with self._lock:
            return [rt for rt in self.runtimes.values() if rt.camera_id == cid]

    def _on_head(self, wid: int, head: Head) -> None:
        rt = self.runtimes.get(wid)
        if rt:
            rt.set_head(head)

    # ---- cameras -------------------------------------------------------
    def ensure_analyzer(self, cid: int) -> None:
        with self._lock:
            if cid in self.analyzers:
                return
            cam = self.hub.get(cid)
            if not cam:
                return
            a = CameraAnalyzer(self, cam)
            self.analyzers[cid] = a
        a.start()

    def restart_analyzer(self, cid: int) -> None:
        self.stop_analyzer(cid)
        self.ensure_analyzer(cid)

    def stop_analyzer(self, cid: int) -> None:
        with self._lock:
            a = self.analyzers.pop(cid, None)
        if a:
            a.stop()

    def perception(self, cid: int) -> dict:
        a = self.analyzers.get(cid)
        return a.last if a else {}

    # ---- builds --------------------------------------------------------
    def start_build(self, wid: int, collect_seconds: float | None = None) -> BuildJob:
        watch = self.db.watch(wid)
        if not watch:
            raise KeyError(wid)
        cam = self.hub.get(watch["camera_id"])
        if not cam:
            raise RuntimeError("camera is not running")
        old = self.builds.get(wid)
        if old and old.thread.is_alive():
            old.cancelled.set()
        self.deactivate(wid)
        job = BuildJob(self.db, self.store, cam, wid, on_done=self.reload, collect_seconds=collect_seconds)
        self.builds[wid] = job
        job.start()
        return job

    def shutdown(self) -> None:
        for a in list(self.analyzers.values()):
            a.stop()
        for b in self.builds.values():
            b.cancelled.set()
