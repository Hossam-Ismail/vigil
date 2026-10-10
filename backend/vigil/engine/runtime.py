"""Per-watch runtime: turns per-frame model outputs into reliable alerts.

Signal path:   frame -> (crop | detections) -> head probability -> k-of-n vote with hysteresis
               -> dwell timer (min_duration_s) -> trigger policy + cooldown -> Trigger
"""

from __future__ import annotations

import operator
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from ..learning.heads import Head
from ..perception.detector import Detection
from ..perception.geometry import Box, anchor, point_in_zone
from ..perception.tracker import IoUTracker, Track
from ..schemas import WatchSpec

OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt, "==": operator.eq}
DIRS = {"down": (0.0, 1.0), "up": (0.0, -1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0)}


def segments_cross(p, q, a, b) -> bool:
    """True when segment p->q properly crosses segment a-b."""
    def orient(u, v, w):
        return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])

    o1, o2, o3, o4 = orient(a, b, p), orient(a, b, q), orient(p, q, a), orient(p, q, b)
    return o1 * o2 < 0 and o3 * o4 < 0


@dataclass
class Trigger:
    watch_id: int
    camera_id: int
    ts: float
    score: float
    message: str
    boxes: list[tuple[Box, str]] = field(default_factory=list)
    crop_box: Box | None = None
    track_ids: list[int] = field(default_factory=list)


class Vote:
    """k-of-n debouncer with separate on/off thresholds (hysteresis)."""

    def __init__(self, window: int = 5, need: int = 3):
        self.window = window
        self.need = need
        self.buf: deque[int] = deque(maxlen=window)  # +1 above on, -1 below off, 0 in between
        self.state = False

    def update(self, on: bool, off: bool) -> bool:
        self.buf.append(1 if on else (-1 if off else 0))
        if not self.state and sum(1 for v in self.buf if v == 1) >= self.need:
            self.state = True
        elif self.state and sum(1 for v in self.buf if v == -1) >= self.need:
            self.state = False
        return self.state

    def reset(self) -> None:
        self.buf.clear()
        self.state = False


class AlertMachine:
    """Dwell + cooldown + trigger policy. Pure logic so it is easy to test."""

    def __init__(self, min_duration_s: float, cooldown_s: float, trigger: str):
        self.min_duration_s = min_duration_s
        self.cooldown_s = cooldown_s
        self.trigger = trigger
        self.phase = "idle"  # idle | pending | active
        self.since = 0.0
        self.last_alert = -1e18

    def step(self, ts: float, cond: bool) -> bool:
        if not cond:
            self.phase = "idle"
            return False
        if self.phase == "idle":
            self.phase, self.since = "pending", ts
        if self.phase == "pending" and ts - self.since >= self.min_duration_s:
            self.phase = "active"
            if ts - self.last_alert >= self.cooldown_s:
                self.last_alert = ts
                return True
            return False
        if self.phase == "active" and self.trigger == "sustained" and ts - self.last_alert >= self.cooldown_s:
            self.last_alert = ts
            return True
        return False


class WatchRuntime:
    def __init__(self, watch: dict, head: Head):
        self.id: int = watch["id"]
        self.camera_id: int = watch["camera_id"]
        self.name: str = watch["name"]
        self.spec = WatchSpec.model_validate(watch["spec"])
        self.head = head
        self.paused = watch["status"] == "paused"
        s = self.spec
        self.machine = AlertMachine(s.min_duration_s, s.cooldown_s, s.trigger)
        window = 5 if s.kind == "state" else 4
        self.vote = Vote(window=window, need=3 if s.kind == "state" else 2)
        self.tracker = IoUTracker()
        self.last_eval = 0.0
        self.score: float | None = None
        self.count: int | None = None
        self.cond = False
        self.history: deque[tuple[float, float]] = deque(maxlen=900)
        self.alerted_tracks: set[int] = set()
        self.last_object_alert = -1e18
        self.tracks: list[Track] = []
        self.crossings: deque[float] = deque(maxlen=500)
        self.pending_dets: list[Detection] = []
        self.last_crop: np.ndarray | None = None
        self.last_crop_emb: np.ndarray | None = None

    # ---- configuration -------------------------------------------------
    @property
    def is_state(self) -> bool:
        return self.spec.kind == "state"

    @property
    def uses_object_head(self) -> bool:
        """Presence/count watches run the per-object head only once it has something to say."""
        if self.is_state:
            return False
        if self.spec.target_question:
            return True
        # plain presence: only once the head has seen real false detections to filter out
        return self.head.mode == "trained" and (self.head.metrics.get("n_neg") or 0) >= 2

    def set_head(self, head: Head) -> None:
        self.head = head

    def due(self, ts: float) -> bool:
        return ts - self.last_eval >= self.spec.check_interval_s

    # ---- state watches -------------------------------------------------
    def step_state(self, ts: float, emb: np.ndarray) -> Trigger | None:
        self.last_eval = ts
        p = float(self.head.proba(emb)[0])
        self.score = p
        self.history.append((ts, p))
        thr = self.head.threshold
        cond = self.vote.update(p >= thr, p < max(0.05, thr - 0.12))
        self.cond = cond
        if self.machine.step(ts, cond):
            return Trigger(
                self.id, self.camera_id, ts, p, self.spec.alert_message or self.spec.positive_label,
                crop_box=self.spec.zone.bbox() if self.spec.zone else None,
            )
        return None

    # ---- presence / count watches ---------------------------------------
    @property
    def crossing_mode(self) -> bool:
        s = self.spec
        return s.kind == "presence" and s.crossing != "none" and bool(s.line) and len(s.line or []) == 2

    def relevant(self, d: Detection) -> bool:
        """Whether a detection is worth running the per-object head on (near the tripwire / inside the zone)."""
        ax, ay = anchor(d.box)
        if self.crossing_mode:
            (x1, y1), (x2, y2) = self.spec.line  # type: ignore[misc]
            vx, vy = x2 - x1, y2 - y1
            t = max(0.0, min(1.0, ((ax - x1) * vx + (ay - y1) * vy) / max(1e-9, vx * vx + vy * vy)))
            return ((ax - x1 - t * vx) ** 2 + (ay - y1 - t * vy) ** 2) ** 0.5 < 0.15
        return point_in_zone(ax, ay, self.spec.zone)

    def step_objects(self, ts: float, dets: list[Detection], probs: list[float | None] | None) -> Trigger | None:
        """dets: detections for this watch's targets; probs: per-detection head probabilities (or None)."""
        self.last_eval = ts
        keep: list[tuple[str, Box, float]] = []
        fresh: list[bool] = []  # False when the head skipped this detection (far from the tripwire)
        for i, d in enumerate(dets):
            ax, ay = anchor(d.box)
            if not self.crossing_mode and not point_in_zone(ax, ay, self.spec.zone):
                continue
            p = probs[i] if probs is not None else d.conf
            keep.append((d.label, d.box, d.conf if p is None else p))
            fresh.append(p is not None)
        tracks = self.tracker.update(ts, keep)
        for t in tracks:
            if t.det_index >= 0 and (fresh[t.det_index] or t.score is None):
                s = keep[t.det_index][2]
                t.score = s if t.score is None else 0.5 * t.score + 0.5 * s
        thr = self.head.threshold if self.uses_object_head else 0.0
        if self.crossing_mode:
            return self._step_crossing(ts, tracks, thr)
        qualifying = [t for t in tracks if t.confirmed and t.misses <= 2 and (t.score or 0) >= thr]
        self.tracks = tracks
        count = len(qualifying)
        self.count = count
        best = max((t.score or 0 for t in qualifying), default=0.0)
        self.score = best if qualifying else (max((t.score or 0 for t in tracks), default=0.0) if tracks else 0.0)
        self.history.append((ts, float(count)))
        op = OPS[self.spec.count_op]
        cond_now = op(count, self.spec.count_value)
        cond = self.vote.update(cond_now, not cond_now)
        self.cond = cond
        boxes = [(t.box, f"{t.label} #{t.id}") for t in qualifying]

        if self.spec.trigger == "per_object" and self.spec.kind == "presence":
            fresh = [
                t for t in qualifying
                if t.id not in self.alerted_tracks and ts - t.first_seen >= self.spec.min_duration_s
            ]
            if fresh and ts - self.last_object_alert >= self.spec.cooldown_s:
                self.last_object_alert = ts
                for t in qualifying:
                    self.alerted_tracks.add(t.id)
                t = max(fresh, key=lambda t: t.score or 0)
                return Trigger(self.id, self.camera_id, ts, float(t.score or 0), self.spec.alert_message,
                               boxes=boxes, crop_box=t.box, track_ids=[x.id for x in fresh])
            # objects that arrived during the cooldown should not fire later
            for t in fresh:
                self.alerted_tracks.add(t.id)
            self.alerted_tracks &= {t.id for t in tracks}
            return None

        if self.machine.step(ts, cond):
            crop_box = max(qualifying, key=lambda t: t.score or 0).box if qualifying else (
                self.spec.zone.bbox() if self.spec.zone else None)
            return Trigger(self.id, self.camera_id, ts, float(count), self.spec.alert_message, boxes=boxes,
                           crop_box=crop_box, track_ids=[t.id for t in qualifying])
        return None

    def _step_crossing(self, ts: float, tracks: list[Track], thr: float) -> Trigger | None:
        """Tripwire: fire when a tracked object's ground point crosses the line in the chosen direction."""
        a, b = self.spec.line  # type: ignore[misc]
        want = DIRS.get(self.spec.crossing)
        crossed: list[Track] = []
        for t in tracks:
            if t.misses != 0:
                continue
            cur = anchor(t.box)
            prev = t.data.get("anchor")
            t.data["anchor"] = cur
            if prev is None or t.id in self.alerted_tracks or (t.score or 0) < thr:
                continue
            if segments_cross(prev, cur, a, b):
                move = (cur[0] - prev[0], cur[1] - prev[1])
                if want is None or move[0] * want[0] + move[1] * want[1] > 0:
                    crossed.append(t)
        self.tracks = tracks
        for t in crossed:
            self.alerted_tracks.add(t.id)
            self.crossings.append(ts)
        self.alerted_tracks &= {t.id for t in tracks}
        recent = sum(1 for c in self.crossings if ts - c <= 60)
        self.count = recent
        self.score = max((t.score or 0 for t in crossed), default=0.0)
        self.cond = bool(crossed)
        self.history.append((ts, float(recent)))
        if crossed and ts - self.last_object_alert >= self.spec.cooldown_s:
            self.last_object_alert = ts
            best = max(crossed, key=lambda t: t.score or 0)
            return Trigger(self.id, self.camera_id, ts, float(best.score or 0), self.spec.alert_message,
                           boxes=[(t.box, f"{t.label} #{t.id}") for t in crossed], crop_box=best.box,
                           track_ids=[t.id for t in crossed])
        return None

    # ---- reporting -----------------------------------------------------
    def snapshot(self, spark: bool = True) -> dict:
        now = time.time()
        out = {
            "id": self.id,
            "kind": self.spec.kind,
            "score": None if self.score is None else round(self.score, 3),
            "count": self.count,
            "cond": self.cond,
            "phase": self.machine.phase,
            "threshold": round(self.head.threshold, 3),
            "head_mode": self.head.mode,
            "paused": self.paused,
            "tracks": [
                {"id": t.id, "label": t.label, "box": [round(v, 4) for v in t.box],
                 "score": None if t.score is None else round(t.score, 3), "confirmed": t.confirmed}
                for t in self.tracks if t.misses == 0
            ],
        }
        if spark:
            out["spark"] = [[round(ts - now, 1), round(v, 3)] for ts, v in list(self.history)[-240:]]
        return out
