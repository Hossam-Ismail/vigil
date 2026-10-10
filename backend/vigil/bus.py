"""Thread-safe pub/sub that fans worker-thread messages out to asyncio WebSocket clients."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any


class Bus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queues: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._throttle: dict[str, float] = {}

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        with self._lock:
            self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._queues.discard(q)

    def publish(self, type_: str, data: Any, *, throttle_key: str | None = None, min_interval: float = 0.0) -> None:
        """Publish from any thread. Optional per-key throttling for high-rate streams."""
        if throttle_key is not None:
            now = time.monotonic()
            last = self._throttle.get(throttle_key, 0.0)
            if now - last < min_interval:
                return
            self._throttle[throttle_key] = now
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        msg = {"type": type_, "data": data, "ts": time.time()}
        with self._lock:
            queues = list(self._queues)
        for q in queues:
            loop.call_soon_threadsafe(_put_nowait, q, msg)


def _put_nowait(q: asyncio.Queue, msg: dict) -> None:
    if q.full():
        try:
            q.get_nowait()  # drop the oldest message for slow clients
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(msg)


bus = Bus()
