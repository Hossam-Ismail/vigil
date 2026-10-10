"""Zones, crops and box math in normalized coordinates."""

from __future__ import annotations

import cv2
import numpy as np

from ..schemas import Zone

Box = tuple[float, float, float, float]  # normalized x1, y1, x2, y2


def crop(frame: np.ndarray, box: Box, pad: float = 0.0, min_px: int = 24) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    x1, y1, x2, y2 = x1 - bw * pad, y1 - bh * pad, x2 + bw * pad, y2 + bh * pad
    px1, py1 = int(max(0, x1 * w)), int(max(0, y1 * h))
    px2, py2 = int(min(w, x2 * w)), int(min(h, y2 * h))
    if px2 - px1 < min_px:
        cx = (px1 + px2) // 2
        px1, px2 = max(0, cx - min_px // 2), min(w, cx + min_px // 2)
    if py2 - py1 < min_px:
        cy = (py1 + py2) // 2
        py1, py2 = max(0, cy - min_px // 2), min(h, cy + min_px // 2)
    return frame[py1:py2, px1:px2]


def zone_crop(frame: np.ndarray, zone: Zone | None) -> np.ndarray:
    if zone is None or len(zone.points) < 3:
        return frame
    return crop(frame, zone.bbox())


def point_in_zone(x: float, y: float, zone: Zone | None) -> bool:
    if zone is None or len(zone.points) < 3:
        return True
    pts = np.array(zone.points, np.float32)
    return cv2.pointPolygonTest(pts, (float(x), float(y)), False) >= 0


def anchor(box: Box) -> tuple[float, float]:
    """Bottom-center of a box: where an object touches the floor, used for zone membership."""
    return ((box[0] + box[2]) / 2, box[3])


def iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def zone_mask(shape: tuple[int, int], zone: Zone | None) -> np.ndarray:
    h, w = shape
    if zone is None or len(zone.points) < 3:
        return np.ones((h, w), np.uint8)
    mask = np.zeros((h, w), np.uint8)
    pts = (np.array(zone.points) * np.array([w, h])).astype(np.int32)
    cv2.fillPoly(mask, [pts], 1)
    return mask


def pad_box(box: Box, pad: float) -> Box:
    bw, bh = box[2] - box[0], box[3] - box[1]
    return (
        max(0.0, box[0] - bw * pad),
        max(0.0, box[1] - bh * pad),
        min(1.0, box[2] + bw * pad),
        min(1.0, box[3] + bh * pad),
    )
