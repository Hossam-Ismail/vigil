"""Per-camera capture threads with reconnects, a clip ring buffer and an on-disk frame history."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from ..bus import bus
from ..config import settings
from .demo import DemoSource, ShelfScene
from .sources import AVSource, FrameSource, PushSource, WebcamSource

log = logging.getLogger("vigil.cameras")


def encode_jpeg(img: np.ndarray, quality: int = 82) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()


class CameraRuntime:
    def __init__(self, cam: dict):
        self.id: int = cam["id"]
        self.name: str = cam["name"]
        self.kind: str = cam["kind"]
        self.url: str = cam["url"]
        self.status = "starting"
        self.error = ""
        self.latest: np.ndarray | None = None
        self.latest_ts = 0.0
        self.frame_no = 0
        self.fps = 0.0
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jpeg_cache: tuple[int, bytes] | None = None
        self.ring: deque[tuple[float, bytes]] = deque()
        self._last_ring = 0.0
        self._last_history = 0.0
        self.history_dir = settings.data_dir / "history" / str(self.id)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.push_source: PushSource | None = PushSource() if self.kind == "browser" else None
        self.scene: ShelfScene | None = ShelfScene() if self.kind == "demo" and self.url in ("", "shelf") else None

    # ---- lifecycle ----------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"cam-{self.id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.status = "stopped"

    def _make_source(self) -> FrameSource:
        if self.kind == "demo":
            if self.scene is not None:
                return DemoSource(self.scene)
            return AVSource(self._demo_path(self.url))
        if self.kind == "webcam":
            return WebcamSource(self.url)
        if self.kind == "browser":
            assert self.push_source is not None
            return self.push_source
        return AVSource(self.url)

    @staticmethod
    def _demo_path(name: str) -> str:
        path = settings.data_dir / "demo" / f"{name}"
        if not path.exists():
            for ext in (".mp4", ".avi", ".mov", ".mkv"):
                if (settings.data_dir / "demo" / f"{name}{ext}").exists():
                    return str(settings.data_dir / "demo" / f"{name}{ext}")
            raise FileNotFoundError(f"demo video '{name}' not found in {settings.data_dir / 'demo'}")
        return str(path)

    def _set_status(self, status: str, error: str = "") -> None:
        if status != self.status or error != self.error:
            self.status, self.error = status, error
            bus.publish("camera", self.info())

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._set_status("connecting")
                src = self._make_source()
                t_count, n_count = time.monotonic(), 0
                for frame in src.frames(self._stop):
                    self._on_frame(frame)
                    if self.status != "live":
                        self._set_status("live")
                    backoff = 1.0
                    n_count += 1
                    dt = time.monotonic() - t_count
                    if dt >= 2.0:
                        self.fps = n_count / dt
                        t_count, n_count = time.monotonic(), 0
                if self._stop.is_set():
                    break
                raise RuntimeError("stream ended")
            except Exception as exc:  # noqa: BLE001 - any source failure triggers a reconnect
                if self._stop.is_set():
                    break
                log.warning("camera %s (%s) error: %s", self.id, self.name, exc)
                self._set_status("error", str(exc)[:300])
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)

    def _on_frame(self, frame: np.ndarray) -> None:
        now = time.time()
        with self._cond:
            self.latest = frame
            self.latest_ts = now
            self.frame_no += 1
            self._cond.notify_all()
        if now - self._last_ring >= 1.0 / settings.clip_fps:
            self._last_ring = now
            self.ring.append((now, encode_jpeg(frame, 78)))
            horizon = now - (settings.clip_pre_s + settings.clip_post_s + 6)
            while self.ring and self.ring[0][0] < horizon:
                self.ring.popleft()
        if now - self._last_history >= settings.history_interval_s:
            self._last_history = now
            self._save_history(frame, now)

    def _save_history(self, frame: np.ndarray, now: float) -> None:
        h, w = frame.shape[:2]
        scale = min(1.0, 960 / w)
        small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1 else frame
        (self.history_dir / f"{int(now * 1000)}.jpg").write_bytes(encode_jpeg(small, 85))
        files = sorted(self.history_dir.glob("*.jpg"))
        for old in files[: max(0, len(files) - settings.history_max_frames)]:
            old.unlink(missing_ok=True)

    # ---- access -------------------------------------------------------
    def snapshot(self) -> tuple[np.ndarray | None, float, int]:
        with self._cond:
            return self.latest, self.latest_ts, self.frame_no

    def wait_frame(self, after: int, timeout: float = 2.0) -> tuple[np.ndarray | None, float, int]:
        with self._cond:
            self._cond.wait_for(lambda: self.frame_no > after or self._stop.is_set(), timeout=timeout)
            return self.latest, self.latest_ts, self.frame_no

    def jpeg(self, quality: int = 80) -> bytes | None:
        frame, _, no = self.snapshot()
        if frame is None:
            return None
        cached = self._jpeg_cache
        if cached and cached[0] == no:
            return cached[1]
        data = encode_jpeg(frame, quality)
        self._jpeg_cache = (no, data)
        return data

    def clip_frames(self, t0: float, t1: float) -> list[tuple[float, bytes]]:
        return [(ts, j) for ts, j in list(self.ring) if t0 <= ts <= t1]

    def history(self, limit: int = 400) -> list[Path]:
        files = sorted(self.history_dir.glob("*.jpg"))
        return files[-limit:]

    def info(self) -> dict:
        frame = self.latest
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "error": self.error,
            "fps": round(self.fps, 1),
            "width": int(frame.shape[1]) if frame is not None else None,
            "height": int(frame.shape[0]) if frame is not None else None,
            "last_frame_ts": self.latest_ts or None,
            "history_frames": len(list(self.history_dir.glob("*.jpg"))),
            "demo": self.scene.state() if self.scene else None,
        }


class CameraHub:
    def __init__(self) -> None:
        self.cams: dict[int, CameraRuntime] = {}
        self._lock = threading.Lock()

    def start(self, cam: dict) -> CameraRuntime:
        with self._lock:
            old = self.cams.pop(cam["id"], None)
        if old:
            old.stop()
        rt = CameraRuntime(cam)
        with self._lock:
            self.cams[cam["id"]] = rt
        if cam.get("enabled", True):
            rt.start()
        else:
            rt.status = "disabled"
        return rt

    def stop(self, cid: int) -> None:
        with self._lock:
            rt = self.cams.pop(cid, None)
        if rt:
            rt.stop()

    def get(self, cid: int) -> CameraRuntime | None:
        return self.cams.get(cid)

    def all(self) -> list[CameraRuntime]:
        return list(self.cams.values())

    def shutdown(self) -> None:
        for rt in self.all():
            rt.stop()
