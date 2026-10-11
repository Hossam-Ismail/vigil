"""Event lifecycle: snapshot -> (VLM verification) -> notify -> evidence clip.

Verification verdicts double as training data: a rejected alert becomes a negative example and a
confirmed one a positive, so the fast model learns from the slow one ("distillation flywheel").
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

import cv2
import numpy as np

from ..brain import LabelTask, get_brain
from ..bus import bus
from ..cameras.manager import CameraHub
from ..config import settings
from ..db import DB
from ..learning.store import ModelStore, prior_labels
from ..perception.geometry import crop
from ..schemas import WatchSpec
from .actions import ActionRunner
from .notify import Notifier
from .runtime import Trigger
from ..privacy import blur_faces

log = logging.getLogger("vigil.events")


def event_dir(eid: int) -> Path:
    d = settings.data_dir / "media" / "events" / str(eid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel(p: Path) -> str:
    return str(p.relative_to(settings.data_dir / "media"))


def annotate(frame: np.ndarray, spec: WatchSpec, trig: Trigger) -> np.ndarray:
    img = frame.copy()
    h, w = img.shape[:2]
    if spec.zone and len(spec.zone.points) >= 3:
        pts = (np.array(spec.zone.points) * [w, h]).astype(np.int32)
        overlay = img.copy()
        cv2.fillPoly(overlay, [pts], (60, 200, 255))
        img = cv2.addWeighted(overlay, 0.18, img, 0.82, 0)
        cv2.polylines(img, [pts], True, (60, 200, 255), 2, cv2.LINE_AA)
    for box, label in trig.boxes:
        p1, p2 = (int(box[0] * w), int(box[1] * h)), (int(box[2] * w), int(box[3] * h))
        cv2.rectangle(img, p1, p2, (40, 40, 255), 3)
        cv2.putText(img, label, (p1[0] + 4, max(18, p1[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 255), 2,
                    cv2.LINE_AA)
    return img


def write_clip(frames: list[tuple[float, bytes]], path: Path, fps: float) -> bool:
    import av

    imgs = [cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR) for _, j in frames]
    imgs = [blur_faces(i) for i in imgs if i is not None]
    if len(imgs) < 2:
        return False
    h, w = imgs[0].shape[:2]
    w2, h2 = w // 2 * 2, h // 2 * 2
    with av.open(str(path), "w", options={"movflags": "+faststart"}) as out:
        stream = out.add_stream("libx264", rate=int(round(fps)))
        stream.width, stream.height, stream.pix_fmt = w2, h2, "yuv420p"
        stream.options = {"crf": "26", "preset": "veryfast"}
        for img in imgs:
            if img.shape[:2] != (h, w):
                img = cv2.resize(img, (w, h))
            frame = av.VideoFrame.from_ndarray(img[:h2, :w2], format="bgr24")
            for pkt in stream.encode(frame):
                out.mux(pkt)
        for pkt in stream.encode():
            out.mux(pkt)
    return True


def _is_action(spec: WatchSpec) -> bool:
    """Watches run by the action-recognition (video) model."""
    if not spec.library:
        return False
    from ..perception.library import BY_ID

    m = BY_ID.get(spec.library.get("id"))
    return bool(m and m.kind == "video")


class EventManager:
    def __init__(self, db: DB, hub: CameraHub, store: ModelStore, notifier: Notifier, actions: "ActionRunner | None" = None):
        self.db = db
        self.hub = hub
        self.store = store
        self.notifier = notifier
        self.actions = actions
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="event")
        self.verify_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="verify")

    def create(self, trig: Trigger, frame: np.ndarray) -> int:
        watch = self.db.watch(trig.watch_id)
        if not watch:
            return -1
        spec = WatchSpec.model_validate(watch["spec"])
        if spec.verify_with_vlm and self.db.one(
            "SELECT id FROM events WHERE watch_id=? AND status='verifying' AND ts > ?", (trig.watch_id, trig.ts - 180)
        ):
            log.info("watch %s: skipping trigger while a previous alert is still being double-checked", trig.watch_id)
            return -1
        eid = self.db.add_event(trig.watch_id, trig.camera_id, trig.ts, trig.score, trig.message,
                                {"track_ids": trig.track_ids, "boxes": [[list(b), l] for b, l in trig.boxes]})
        d = event_dir(eid)
        snap = d / "snapshot.jpg"
        # the snapshot is what gets texted and shown, so faces are blurred; the crop stays local for training
        cv2.imwrite(str(snap), annotate(blur_faces(frame), spec, trig), [cv2.IMWRITE_JPEG_QUALITY, 86])
        crop_img = crop(frame, trig.crop_box, pad=0.05) if trig.crop_box else frame
        crop_path = d / "crop.jpg"
        cv2.imwrite(str(crop_path), crop_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        # the full frame, local only: if this alert is marked wrong, the next training run learns from it
        cv2.imwrite(str(d / "frame.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        status = "verifying" if spec.verify_with_vlm else "confirmed"
        ev = self.db.update_event(eid, snapshot_path=rel(snap), crop_path=rel(crop_path), status=status)
        bus.publish("event", self._public(ev))
        self.pool.submit(self._finalize, eid, trig, crop_img)
        return eid

    def _public(self, ev: dict | None) -> dict | None:
        if not ev:
            return None
        w = self.db.watch(ev["watch_id"])
        c = self.db.camera(ev["camera_id"])
        return {**ev, "watch_name": w["name"] if w else "", "camera_name": c["name"] if c else ""}

    def _finalize(self, eid: int, trig: Trigger, crop_img: np.ndarray) -> None:
        try:
            self._verify_and_notify(eid, trig, crop_img)
        except Exception:  # noqa: BLE001
            log.exception("event %s finalize failed", eid)
        try:
            self._clip(eid, trig)
        except Exception:  # noqa: BLE001
            log.exception("event %s clip failed", eid)

    def _verify_and_notify(self, eid: int, trig: Trigger, crop_img: np.ndarray) -> None:
        watch = self.db.watch(trig.watch_id)
        camera = self.db.camera(trig.camera_id)
        if not watch or not camera:
            return
        spec = WatchSpec.model_validate(watch["spec"])
        status, verdict = "confirmed", ""
        if spec.verify_with_vlm:
            brain = get_brain()
            cam = self.hub.get(trig.camera_id)
            action = _is_action(spec)
            frames = []
            if cam:
                if action:   # the clip the video model judged: the action may already be over by now
                    ring = cam.clip_frames(trig.ts - 3.5, trig.ts)
                    pick = [ring[int(i)] for i in np.linspace(0, len(ring) - 1, 4)] if ring else []
                else:
                    ring = cam.clip_frames(trig.ts - 2.5, trig.ts + 0.5)
                    pick = ring[:: max(1, len(ring) // 3)][-3:] if ring else []
                frames = [cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR) for _, j in pick]
            frames = [f for f in frames if f is not None] + ([] if action else [crop_img])
            context = f"Camera '{camera['name']}'. User request: {watch['prompt']}"
            if action:
                context += (" This is an action that takes a few seconds; the images span it in time order. Answer yes"
                            " if the action is clearly happening in any of them, even if it has finished by the last.")
            task = LabelTask(spec.question, spec.positive_label, spec.negative_label, context=context)
            try:
                t = time.time()
                future = self.verify_pool.submit(brain.verify, frames, task)
                try:
                    v = future.result(timeout=settings.verify_timeout_s)
                except FutureTimeout:
                    # don't hold the alert hostage to a slow (e.g. local) verifier: send it now, unverified,
                    # and record the verdict when it lands
                    ev = self.db.update_event(eid, status="unverified", verdict="Still double-checking…")
                    if ev:
                        self._dispatch(ev, watch, camera, spec)
                        bus.publish("event", self._public(self.db.event(eid)))
                    v = future.result()
                    late = True
                else:
                    late = False
                verdict = v.reason
                if v.answer is False and v.confidence >= 0.5:
                    status = "suppressed"
                elif v.answer is None:
                    status = "unverified"
                self.db.update_event(eid, detail={**(self.db.event(eid) or {}).get("detail", {}),
                                                  "verifier": brain.label, "verify_ms": int((time.time() - t) * 1000),
                                                  "verify_confidence": v.confidence})
                # flywheel: the verdict is a free label for the fast model
                if (v.answer is not None and v.confidence >= 0.6 and brain.name != "heuristic"
                        and (spec.kind == "state" or (spec.kind == "presence" and spec.target_question))):
                    self.store.add_sample(trig.watch_id, crop_img, label=int(v.answer), source=brain.name,
                                          confidence=v.confidence, reason=v.reason, origin="verifier")
                    self.store.retrain(trig.watch_id, reason=f"verifier {'confirmed' if v.answer else 'rejected'} alert")
            except Exception as exc:  # noqa: BLE001
                log.warning("verification failed for event %s: %s", eid, exc)
                status, verdict, late = "unverified", f"verification unavailable: {exc}"[:200], False
            if late:
                ev = self.db.update_event(eid, status=status, verdict=verdict)
                bus.publish("event", self._public(ev))
                return
        ev = self.db.update_event(eid, status=status, verdict=verdict)
        if status in ("confirmed", "unverified") and ev:
            ev = self._dispatch(ev, watch, camera, spec)
        bus.publish("event", self._public(ev))

    def _dispatch(self, ev: dict, watch: dict, camera: dict, spec: WatchSpec) -> dict | None:
        """Notify the global channels and run the watch's own actions (iMessage, HubSpot, webhooks...)."""
        snap = settings.data_dir / "media" / ev["snapshot_path"] if ev.get("snapshot_path") else None
        notified = self.notifier.send(ev, watch, camera, snap)
        acted = self.actions.run(spec.actions, ev, watch, camera, snap) if self.actions and spec.actions else []
        return self.db.update_event(ev["id"], detail={**ev.get("detail", {}), "notified": notified, "actions": acted})

    def _clip(self, eid: int, trig: Trigger) -> None:
        cam = self.hub.get(trig.camera_id)
        if not cam:
            return
        wait = trig.ts + settings.clip_post_s - time.time()
        if wait > 0:
            time.sleep(wait)
        frames = cam.clip_frames(trig.ts - settings.clip_pre_s, trig.ts + settings.clip_post_s)
        path = event_dir(eid) / "clip.mp4"
        if frames and write_clip(frames, path, len(frames) / max(1e-3, frames[-1][0] - frames[0][0])):
            ev = self.db.event(eid) or {}
            detail = {**ev.get("detail", {}), "clip_frames": len(frames),
                      "clip_span": [round(frames[0][0] - trig.ts, 2), round(frames[-1][0] - trig.ts, 2)],
                      "ring": [round(cam.ring[0][0] - trig.ts, 2), round(cam.ring[-1][0] - trig.ts, 2), len(cam.ring)]
                      if cam.ring else None}
            ev = self.db.update_event(eid, clip_path=rel(path), detail=detail)
            bus.publish("event", self._public(ev))

    def feedback(self, eid: int, feedback: str | None) -> dict | None:
        ev = self.db.event(eid)
        if not ev:
            return None
        ev = self.db.update_event(eid, feedback=feedback)
        watch = self.db.watch(ev["watch_id"]) if ev else None
        kind = (watch or {}).get("spec", {}).get("kind")
        if feedback in ("correct", "false_alarm") and ev and ev.get("crop_path") and kind in ("state", "presence"):
            # for presence, "false alarm" on an object crop means "this is not what you think it is"
            img = cv2.imread(str(settings.data_dir / "media" / ev["crop_path"]))
            if img is not None:
                label = 1 if feedback == "correct" else 0
                self.store.add_sample(ev["watch_id"], img, label=label, source="user", confidence=1.0,
                                      reason=f"feedback on event #{eid}", origin="feedback")
                threading.Thread(target=self.store.retrain, args=(ev["watch_id"], f"user feedback: {feedback}"),
                                 daemon=True).start()
        pub = self._public(ev)
        bus.publish("event", pub)
        return pub
