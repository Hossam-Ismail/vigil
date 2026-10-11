"""Privacy controls: what may leave this computer, faces in evidence, and how long footage is kept.

Defaults are the safe ones:
  private_mode      True  -> no image ever goes to a cloud model; the local brain (or rules) does everything
  blur_faces        True  -> faces are blurred in alert snapshots and clips (what gets texted or shown)
  keep_history_days 7     -> background frames used for building watches are deleted after a week
  keep_events_days  30    -> alerts and their snapshots, crops and clips are deleted after a month
"""

from __future__ import annotations

import logging
import shutil
import threading
import time

import cv2
import numpy as np

from .config import settings

log = logging.getLogger("vigil.privacy")

DEFAULTS = {"private_mode": True, "blur_faces": True, "keep_history_days": 7, "keep_events_days": 30}

_state = dict(DEFAULTS)


def current() -> dict:
    return dict(_state)


def apply(values: dict | None) -> dict:
    """Merge saved values over the defaults (unknown keys ignored, numbers clamped)."""
    v = {**DEFAULTS, **{k: values[k] for k in (values or {}) if k in DEFAULTS}}
    v["private_mode"] = bool(v["private_mode"])
    v["blur_faces"] = bool(v["blur_faces"])
    v["keep_history_days"] = int(min(max(int(v["keep_history_days"]), 1), 365))
    v["keep_events_days"] = int(min(max(int(v["keep_events_days"]), 1), 3650))
    _state.update(v)
    from . import brain

    brain.set_private(v["private_mode"])
    return current()


def _pixelate(out: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> None:
    roi = out[y0:y1, x0:x1]
    if roi.size:
        small = cv2.resize(roi, (max(1, (x1 - x0) // 10), max(1, (y1 - y0) // 10)), interpolation=cv2.INTER_LINEAR)
        out[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)


def blur_faces(img: np.ndarray) -> np.ndarray:
    """Pixelate the head of every person Vigil's detector finds. Best effort, never raises.

    Uses the same person detector the engine runs (works from overhead angles, where frontal-face detectors miss),
    and pixelates the top quarter of each person box, where the head is.
    """
    if not _state["blur_faces"]:
        return img
    try:
        from .perception.detector import get_coco

        h, w = img.shape[:2]
        out = img.copy()
        for d in get_coco().detect(img, {"person": ["person"]}, threshold=0.35):
            x0, y0, x1, y1 = d.box
            bw, bh = (x1 - x0) * w, (y1 - y0) * h
            head = max(0.22 * bh, 0.6 * bw) if bh > bw else 0.45 * bh  # standing vs. seen from above
            pad = 0.1 * bw
            _pixelate(out, max(0, int(x0 * w - pad)), max(0, int(y0 * h - pad)),
                      min(w, int(x1 * w + pad)), min(h, int(y0 * h + head + pad)))
        return out
    except Exception:  # noqa: BLE001
        log.exception("face blur failed")
        return img


class Janitor:
    """Deletes footage past its retention period, once an hour."""

    def __init__(self, db) -> None:
        self.db = db
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="retention", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def sweep(self, now: float | None = None) -> dict:
        now = now or time.time()
        cut_hist = now - _state["keep_history_days"] * 86400
        cut_ev = now - _state["keep_events_days"] * 86400
        n_hist = 0
        for f in (settings.data_dir / "history").glob("*/*.jpg"):
            try:
                if int(f.stem) / 1000 < cut_hist:
                    f.unlink(missing_ok=True)
                    n_hist += 1
            except ValueError:
                continue
        old = self.db.all("SELECT id FROM events WHERE ts < ?", (cut_ev,))
        for e in old:
            shutil.rmtree(settings.data_dir / "media" / "events" / str(e["id"]), ignore_errors=True)
        if old:
            self.db.execute("DELETE FROM events WHERE ts < ?", (cut_ev,))
        return {"history_frames": n_hist, "events": len(old)}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                done = self.sweep()
                if any(done.values()):
                    log.info("retention: deleted %s", done)
            except Exception:  # noqa: BLE001
                log.exception("retention sweep failed")
            self._stop.wait(3600)
