"""Active learning: while a watch runs, send the crops the head is least sure about to the brain,
add the answers as training data and retrain. Rate-limited per watch so cloud costs stay bounded."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import defaultdict, deque

import numpy as np

from ..brain import get_brain
from ..config import settings
from ..db import DB
from ..schemas import WatchSpec
from .builder import MIN_CONFIDENT
from .store import ModelStore, crop_task

log = logging.getLogger("vigil.active")

MIN_SPACING_S = 45.0


class ActiveLearner:
    def __init__(self, db: DB, store: ModelStore):
        self.db = db
        self.store = store
        self.q: queue.Queue = queue.Queue(maxsize=32)
        self.recent: dict[int, deque[float]] = defaultdict(deque)
        self.last: dict[int, float] = {}
        self.enabled = True
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="active-learner", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def offer(self, watch_id: int, image: np.ndarray, emb: np.ndarray, p: float, threshold: float) -> None:
        """Called by the engine for every evaluated crop; queues the informative ones."""
        if not self.enabled or abs(p - threshold) > 0.22:
            return
        now = time.time()
        if now - self.last.get(watch_id, 0) < MIN_SPACING_S:
            return
        window = self.recent[watch_id]
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= settings.active_learning_per_hour:
            return
        # skip near-duplicates of already-labeled data
        X, _, _, _ = self.db.training_set(watch_id)
        if len(X) and float(np.max(X @ emb)) > 0.97:
            return
        self.last[watch_id] = now
        window.append(now)
        try:
            self.q.put_nowait((watch_id, image.copy(), emb.copy(), p))
        except queue.Full:
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                wid, image, emb, p = self.q.get(timeout=1)
            except queue.Empty:
                continue
            watch = self.db.watch(wid)
            if not watch or watch["status"] != "active":
                continue
            spec = WatchSpec.model_validate(watch["spec"])
            brain = get_brain()
            task = crop_task(spec, watch["prompt"])
            try:
                v = brain.judge([image], task)[0]
            except Exception as exc:  # noqa: BLE001
                log.warning("active-learning label failed: %s", exc)
                continue
            label = None if v.answer is None or v.confidence < MIN_CONFIDENT else int(v.answer)
            if brain.name == "heuristic":
                label = None  # zero-shot guesses are review suggestions, not labels
            self.store.add_sample(wid, image, emb, label=label, source=brain.name, confidence=v.confidence,
                                  reason=v.reason, score=p, origin="active")
            if label is not None:
                self.store.retrain(wid, reason=f"active learning ({'yes' if label else 'no'} at p={p:.2f})")
