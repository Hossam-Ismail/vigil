"""Cheap motion gate: running-average background on a tiny grayscale frame."""

from __future__ import annotations

import cv2
import numpy as np

from ..schemas import Zone
from .geometry import zone_mask

WIDTH = 192


class MotionGate:
    def __init__(self, alpha: float = 0.05, threshold: int = 18):
        self.alpha = alpha
        self.threshold = threshold
        self.bg: np.ndarray | None = None
        self.last_diff: np.ndarray | None = None
        self._masks: dict[tuple, np.ndarray] = {}

    def update(self, frame: np.ndarray) -> float:
        """Feed a BGR frame; returns the fraction of pixels that changed (0..1)."""
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (WIDTH, max(1, int(h * WIDTH / w))), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
        if self.bg is None or self.bg.shape != gray.shape:
            self.bg = gray.copy()
            self.last_diff = np.zeros(gray.shape, np.uint8)
            return 0.0
        diff = cv2.absdiff(gray, self.bg)
        cv2.accumulateWeighted(gray, self.bg, self.alpha)
        self.last_diff = (diff > self.threshold).astype(np.uint8)
        return float(self.last_diff.mean())

    def in_zone(self, zone: Zone | None) -> float:
        if self.last_diff is None:
            return 0.0
        if zone is None:
            return float(self.last_diff.mean())
        key = tuple(map(tuple, zone.points)) + (self.last_diff.shape,)
        mask = self._masks.get(key)
        if mask is None:
            mask = zone_mask(self.last_diff.shape, zone)
            self._masks[key] = mask
        area = mask.sum()
        return float((self.last_diff * mask).sum() / area) if area else 0.0
