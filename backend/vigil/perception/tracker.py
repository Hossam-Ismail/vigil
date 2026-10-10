"""Small IoU tracker: stable ids so one person walking in produces one event, not one per frame."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from .geometry import Box, iou


@dataclass
class Track:
    id: int
    label: str
    box: Box
    conf: float
    first_seen: float
    last_seen: float
    hits: int = 1
    misses: int = 0
    score: float | None = None  # verifier head probability, smoothed
    det_index: int = -1  # index of the detection matched in the latest update (-1 = none)
    data: dict = field(default_factory=dict)

    @property
    def confirmed(self) -> bool:
        return self.hits >= 2


class IoUTracker:
    def __init__(self, iou_threshold: float = 0.3, max_misses: int = 6):
        self.iou_threshold = iou_threshold
        self.max_misses = max_misses
        self.tracks: list[Track] = []
        self._ids = itertools.count(1)

    def update(self, ts: float, dets: list[tuple[str, Box, float]]) -> list[Track]:
        """dets: (label, box, conf). Returns live tracks (matched this frame or recently seen)."""
        pairs = []
        for ti, t in enumerate(self.tracks):
            for di, (label, box, _) in enumerate(dets):
                if label != t.label:
                    continue
                o = iou(t.box, box)
                if o >= self.iou_threshold:
                    pairs.append((o, ti, di))
        pairs.sort(reverse=True)
        used_t, used_d = set(), set()
        for t in self.tracks:
            t.det_index = -1
        for _, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            t = self.tracks[ti]
            label, box, conf = dets[di]
            # light smoothing to steady the box
            t.box = tuple(0.6 * b + 0.4 * a for a, b in zip(t.box, box))  # type: ignore[assignment]
            t.conf = conf
            t.last_seen = ts
            t.hits += 1
            t.misses = 0
            t.det_index = di
        # second pass: objects that moved further than IoU can follow (fast walkers at a few fps)
        far = []
        for ti, t in enumerate(self.tracks):
            if ti in used_t:
                continue
            tw, th = t.box[2] - t.box[0], t.box[3] - t.box[1]
            tcx, tcy = (t.box[0] + t.box[2]) / 2, (t.box[1] + t.box[3]) / 2
            for di, (label, box, _) in enumerate(dets):
                if di in used_d or label != t.label:
                    continue
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                dist = ((cx - tcx) ** 2 + (cy - tcy) ** 2) ** 0.5
                bw, bh = box[2] - box[0], box[3] - box[1]
                size_ok = 0.5 < (bw * bh) / max(1e-6, tw * th) < 2.0
                if size_ok and dist < 0.9 * max(tw, th):
                    far.append((dist, ti, di))
        far.sort()
        for _, ti, di in far:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            t = self.tracks[ti]
            label, box, conf = dets[di]
            t.box, t.conf, t.last_seen, t.misses, t.det_index = box, conf, ts, 0, di
            t.hits += 1
        for ti, t in enumerate(self.tracks):
            if ti not in used_t:
                t.misses += 1
        for di, (label, box, conf) in enumerate(dets):
            if di not in used_d:
                self.tracks.append(Track(next(self._ids), label, box, conf, ts, ts, det_index=di))
        self.tracks = [t for t in self.tracks if t.misses <= self.max_misses]
        return self.tracks
