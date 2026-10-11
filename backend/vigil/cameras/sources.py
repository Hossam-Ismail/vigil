"""Frame sources. Each yields BGR numpy frames until stopped; the camera runtime handles reconnects."""

from __future__ import annotations

import logging
import platform
import queue
import subprocess
import shutil
import threading
import time
from collections.abc import Iterator

import av
import cv2
import numpy as np

log = logging.getLogger("vigil.sources")

MAX_WIDTH = 1280  # analysis + display resolution cap; recordings come from the same frames


def _fit(frame: np.ndarray, max_w: int = MAX_WIDTH) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= max_w:
        return frame
    scale = max_w / w
    return cv2.resize(frame, (max_w, int(round(h * scale))), interpolation=cv2.INTER_AREA)


class FrameSource:
    live = True

    def frames(self, stop: threading.Event) -> Iterator[np.ndarray]:  # pragma: no cover - interface
        raise NotImplementedError


class AVSource(FrameSource):
    """RTSP/RTSPS/HTTP(S)/HLS/file via PyAV (FFmpeg). Files loop and play back in real time."""

    def __init__(self, url: str, *, max_fps: float = 15.0, loop: bool = True):
        self.url = url
        self.max_fps = max_fps
        self.loop = loop
        self.live = not self._is_file(url)

    @staticmethod
    def _is_file(url: str) -> bool:
        return "://" not in url or url.startswith("file://")

    def _options(self) -> dict[str, str]:
        if self.url.startswith(("rtsp://", "rtsps://")):
            return {
                "rtsp_transport": "tcp",
                "fflags": "nobuffer",
                "flags": "low_delay",
                "max_delay": "500000",
                "timeout": "8000000",  # microseconds; socket I/O timeout
            }
        if self.url.startswith(("http://", "https://")):
            return {"reconnect": "1", "reconnect_streamed": "1", "reconnect_delay_max": "5"}
        return {}

    def frames(self, stop: threading.Event) -> Iterator[np.ndarray]:
        import av

        path = self.url[len("file://"):] if self.url.startswith("file://") else self.url
        while not stop.is_set():
            container = av.open(path, options=self._options(), timeout=(10.0, 10.0))
            try:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                tb = float(stream.time_base) if stream.time_base else 1 / 30
                start_wall = time.monotonic()
                first_pts: float | None = None
                min_gap = 1.0 / self.max_fps
                last_emit = 0.0
                for frame in container.decode(stream):
                    if stop.is_set():
                        return
                    if not self.live and frame.pts is not None:
                        # pace file playback to real time
                        t = frame.pts * tb
                        if first_pts is None:
                            first_pts = t
                        delay = (t - first_pts) - (time.monotonic() - start_wall)
                        if delay > 0:
                            time.sleep(min(delay, 1.0))
                    now = time.monotonic()
                    if now - last_emit < min_gap:
                        continue
                    last_emit = now
                    w = frame.width
                    if w > MAX_WIDTH:
                        h = int(round(frame.height * MAX_WIDTH / w)) // 2 * 2
                        img = frame.reformat(width=MAX_WIDTH, height=h, format="bgr24").to_ndarray()
                    else:
                        img = frame.to_ndarray(format="bgr24")
                    yield img
            finally:
                container.close()
            if self.live or not self.loop:
                return  # live stream ended: let the runtime reconnect


class WebcamSource(FrameSource):
    """A camera on this machine, chosen by NAME ("FaceTime HD Camera"); see webcams.py for why.

    Opens the named device through FFmpeg's AVFoundation input on macOS, so a nearby iPhone (Continuity
    Camera) can never be picked by accident; falls back to OpenCV at the device's current index.
    """

    def __init__(self, url: str):
        self.url = url

    def frames(self, stop: threading.Event) -> Iterator[np.ndarray]:
        from .webcams import resolve

        cam = resolve(self.url)
        if cam is None:
            raise RuntimeError(f"no camera named {self.url!r} on this machine" if self.url and not self.url.isdigit()
                               else "no camera found on this machine")
        if platform.system() == "Darwin" and shutil.which("ffmpeg"):
            got = False
            for frame in self._ffmpeg(cam.name, stop):
                got = True
                yield frame
            if got or stop.is_set():
                return
            log.warning("FFmpeg could not open %r; trying OpenCV index %d", cam.name, cam.index)
        cap = cv2.VideoCapture(cam.index)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open {cam.name} (camera permission?)")
        try:
            while not stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError(f"{cam.name}: read failed")
                yield _fit(frame)
        finally:
            cap.release()

    @staticmethod
    def _ffmpeg(name: str, stop: threading.Event, w: int = 1280, h: int = 720) -> Iterator[np.ndarray]:
        """The named AVFoundation camera through an FFmpeg child process (exact device, no in-process AVFoundation)."""
        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        for size in (["-video_size", "1280x720"], []):
            proc = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "avfoundation", "-framerate", "30", *size,
                 "-i", f"{name}:none", "-vf", vf, "-r", "15", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            n = w * h * 3
            got = False
            try:
                while not stop.is_set():
                    buf = proc.stdout.read(n) if proc.stdout else b""
                    if len(buf) < n:
                        break
                    got = True
                    yield np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()
            finally:
                proc.kill()
                proc.wait(timeout=5)
            if got:
                return


class PushSource(FrameSource):
    """Frames pushed in from a browser tab (phone or laptop camera) over WebSocket."""

    def __init__(self) -> None:
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=2)
        self.last_push = 0.0

    def push_jpeg(self, data: bytes) -> None:
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return
        self.last_push = time.time()
        if self.q.full():
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
        self.q.put_nowait(_fit(img))

    def frames(self, stop: threading.Event) -> Iterator[np.ndarray]:
        while not stop.is_set():
            try:
                yield self.q.get(timeout=0.5)
            except queue.Empty:
                continue
