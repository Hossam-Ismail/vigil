"""Procedural demo cameras so the whole pipeline can be exercised without hardware.

`demo:shelf` renders a parts shelf seen by a fixed CCTV camera. Bin stock levels follow an
automatic cycle (full -> picked down -> empty -> restocked) and can also be controlled manually
through the API, which makes it easy to demo "tell me when the blue bin is empty".
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import cv2
import numpy as np

from .sources import FrameSource

W, H = 1280, 720


@dataclass
class Bin:
    key: str
    color: tuple[int, int, int]  # BGR
    x: int
    y: int
    w: int
    h: int
    capacity: int
    level: float = 1.0  # 0..1
    item_color: tuple[int, int, int] = (90, 140, 200)
    rng_seed: int = 0
    items: list[tuple[int, int, int, int, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        rng = np.random.default_rng(self.rng_seed)
        # pre-generate stacked item boxes (x, y, w, h, shade) inside the bin opening, bottom-up
        cols = 4
        rows = int(np.ceil(self.capacity / cols))
        iw = (self.w - 28) // cols
        ih = int((self.h - 30) / max(rows, 1))
        for r in range(rows):
            for c in range(cols):
                if len(self.items) >= self.capacity:
                    break
                jx = int(rng.integers(-4, 5))
                jy = int(rng.integers(-3, 3))
                bx = self.x + 14 + c * iw + jx
                by = self.y + self.h - 12 - (r + 1) * ih + jy
                self.items.append((bx, by, iw - 4, ih - 2, float(rng.uniform(0.82, 1.12))))


class ShelfScene:
    """Time-driven scene; frames depend only on wall-clock so the state is stable across readers."""

    CYCLE = 150.0  # seconds

    def __init__(self, seed: int = 7):
        rng = np.random.default_rng(seed)
        self.rng = rng
        self.bins = [
            Bin("A-01", (190, 110, 30), 150, 300, 300, 170, 16, item_color=(70, 120, 185), rng_seed=1),
            Bin("A-02", (40, 40, 200), 490, 300, 300, 170, 16, item_color=(200, 200, 205), rng_seed=2),
            Bin("A-03", (30, 190, 230), 830, 300, 300, 170, 16, item_color=(60, 95, 140), rng_seed=3),
            Bin("B-01", (70, 140, 50), 150, 545, 300, 150, 12, item_color=(150, 150, 150), rng_seed=4),
            Bin("B-02", (30, 190, 230), 490, 545, 300, 150, 12, item_color=(70, 120, 185), rng_seed=5),
            Bin("B-03", (40, 40, 200), 830, 545, 300, 150, 12, item_color=(80, 160, 90), rng_seed=6),
        ]
        self.manual: dict[str, float] = {}
        self.auto = True
        self.hand_until = 0.0
        self.hand_bin = 0
        self._lock = threading.Lock()
        self._background = self._make_background()

    # ---- control ------------------------------------------------------
    def set_level(self, key: str, level: float) -> None:
        with self._lock:
            self.manual[key] = float(np.clip(level, 0, 1))
            self.hand_until = time.time() + 1.5
            self.hand_bin = next((i for i, b in enumerate(self.bins) if b.key == key), 0)

    def set_auto(self, auto: bool) -> None:
        with self._lock:
            self.auto = auto
            if auto:
                self.manual.clear()

    def state(self) -> dict:
        now = time.time()
        return {"auto": self.auto, "levels": {b.key: round(self._level(i, b, now), 2) for i, b in enumerate(self.bins)}}

    # ---- rendering ----------------------------------------------------
    def _level(self, i: int, b: Bin, now: float) -> float:
        if b.key in self.manual:
            return self.manual[b.key]
        if not self.auto:
            return 1.0
        if i != 0:
            # other bins drift slowly so the scene is never perfectly static
            return 0.55 + 0.4 * (0.5 + 0.5 * np.sin(now / (60 + 17 * i) + i))
        t = now % self.CYCLE
        if t < 40:
            return 1.0
        if t < 75:
            return 1.0 - (t - 40) / 35
        if t < 115:
            return 0.0
        if t < 120:
            return (t - 115) / 5
        return 1.0

    def _make_background(self) -> np.ndarray:
        rng = np.random.default_rng(3)
        img = np.zeros((H, W, 3), np.float32)
        # concrete wall with vertical light falloff
        grad = np.linspace(0.92, 0.70, H)[:, None]
        img[:] = np.array([168, 176, 182], np.float32)
        img *= grad[..., None]
        noise = cv2.GaussianBlur(rng.normal(0, 9, (H, W)).astype(np.float32), (0, 0), 2.2)
        img += noise[..., None]
        # floor
        img[690:] = np.array([96, 102, 104], np.float32) + noise[690:, :, None] * 0.6
        bg = np.clip(img, 0, 255).astype(np.uint8)
        # racking uprights (blue) and beams (orange)
        for x in (120, 1150):
            cv2.rectangle(bg, (x, 110), (x + 26, 720), (150, 85, 25), -1)
            for y in range(130, 700, 38):
                cv2.circle(bg, (x + 13, y), 4, (90, 50, 15), -1)
        for y in (290, 480, 535):
            cv2.rectangle(bg, (110, y - 10 if y == 290 else y), (1180, y + (0 if y == 290 else 12)), (20, 120, 230), -1)
        cv2.rectangle(bg, (110, 470), (1180, 482), (20, 120, 230), -1)
        # upper shelf boxes (static stock)
        for i, x in enumerate(range(160, 1120, 160)):
            hgt = 110 + (i % 3) * 25
            cv2.rectangle(bg, (x, 280 - hgt), (x + 135, 280), (95, 140, 190), -1)
            cv2.rectangle(bg, (x, 280 - hgt), (x + 135, 280), (60, 95, 140), 2)
            cv2.line(bg, (x + 67, 280 - hgt), (x + 67, 280 - hgt + 30), (200, 210, 215), 6)
        # safety sign
        cv2.rectangle(bg, (1195, 140), (1265, 230), (30, 200, 240), -1)
        cv2.putText(bg, "PPE", (1203, 195), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2, cv2.LINE_AA)
        return bg

    def _draw_bin(self, img: np.ndarray, b: Bin, level: float) -> None:
        x, y, w, h = b.x, b.y, b.w, b.h
        dark = tuple(int(c * 0.55) for c in b.color)
        # back wall of bin (interior)
        cv2.rectangle(img, (x + 8, y), (x + w - 8, y + h), dark, -1)
        n = int(round(level * b.capacity))
        for bx, by, bw, bh, shade in b.items[:n]:
            col = tuple(int(np.clip(c * shade, 0, 255)) for c in b.item_color)
            cv2.rectangle(img, (bx, by), (bx + bw, by + bh), col, -1)
            cv2.rectangle(img, (bx, by), (bx + bw, by + bh), tuple(int(c * 0.6) for c in col), 2)
            cv2.line(img, (bx + 4, by + 5), (bx + bw - 4, by + 5), tuple(min(255, int(c * 1.25)) for c in col), 2)
        # front lip of the pick bin (lower, sloped front)
        pts = np.array([[x, y + int(h * 0.66)], [x + w, y + int(h * 0.66)], [x + w - 6, y + h], [x + 6, y + h]])
        cv2.fillPoly(img, [pts], b.color)
        cv2.polylines(img, [pts], True, dark, 2)
        cv2.rectangle(img, (x + w // 2 - 40, y + int(h * 0.72)), (x + w // 2 + 40, y + int(h * 0.72) + 28), (245, 245, 245), -1)
        cv2.putText(img, b.key, (x + w // 2 - 32, y + int(h * 0.72) + 21), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (30, 30, 30), 2, cv2.LINE_AA)

    def render(self, now: float | None = None) -> np.ndarray:
        now = time.time() if now is None else now
        img = self._background.copy()
        with self._lock:
            levels = [self._level(i, b, now) for i, b in enumerate(self.bins)]
            hand_active = now < self.hand_until
            hand_bin = self.hand_bin
        if self.auto and not self.manual:
            t = now % self.CYCLE
            if 40 <= t < 75 and int(t) % 7 < 2 or 115 <= t < 120:
                hand_active, hand_bin = True, 0
        for b, lvl in zip(self.bins, levels):
            self._draw_bin(img, b, lvl)
        if hand_active:
            b = self.bins[hand_bin]
            cx = b.x + b.w // 2 + int(30 * np.sin(now * 3))
            arm = np.array([[cx - 40, 0], [cx + 40, 0], [cx + 30, b.y + 40], [cx - 30, b.y + 40]])
            cv2.fillPoly(img, [arm], (60, 70, 90))  # sleeve
            cv2.ellipse(img, (cx, b.y + 55), (38, 30), 0, 0, 360, (120, 150, 200), -1)  # glove
        # lighting drift + flicker + sensor noise
        gain = 0.93 + 0.05 * np.sin(now / 23.0) + 0.01 * np.sin(now * 13.0)
        noisy = img.astype(np.float32) * gain + self.rng.normal(0, 3.0, img.shape).astype(np.float32)
        img = np.clip(noisy, 0, 255).astype(np.uint8)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        cv2.putText(img, f"CAM-02 AISLE A  {stamp}", (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, f"CAM-02 AISLE A  {stamp}", (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (235, 235, 235), 1, cv2.LINE_AA)
        return img


class DemoSource(FrameSource):
    def __init__(self, scene: ShelfScene, fps: float = 10.0):
        self.scene = scene
        self.fps = fps

    def frames(self, stop: threading.Event) -> Iterator[np.ndarray]:
        period = 1.0 / self.fps
        nxt = time.monotonic()
        while not stop.is_set():
            yield self.scene.render()
            nxt += period
            delay = nxt - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                nxt = time.monotonic()
