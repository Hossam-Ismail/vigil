"""Find local cameras by NAME, so "the webcam" means the built-in camera, not whatever got index 0.

On a Mac, Continuity Camera adds a nearby iPhone (and Desk View) as video devices, and they can take index 0
the moment the phone comes near. Vigil therefore stores a webcam by its device name and resolves it each time
it opens: by name through FFmpeg's AVFoundation input, falling back to the matching OpenCV index.
"""

from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import asdict, dataclass

import cv2

PHONE_WORDS = ("iphone", "ipad", "continuity", "desk view")
BUILTIN_WORDS = ("facetime", "built-in", "builtin", "macbook", "integrated")


@dataclass
class Webcam:
    index: int  # AVFoundation / OpenCV device index right now (it can change; the name does not)
    name: str
    kind: str  # builtin | phone | external
    default: bool = False

    def out(self) -> dict:
        return asdict(self)


def _kind(name: str) -> str:
    n = name.lower()
    if any(w in n for w in PHONE_WORDS):
        return "phone"
    if any(w in n for w in BUILTIN_WORDS):
        return "builtin"
    return "external"


def list_webcams() -> list[Webcam]:
    """Video cameras attached to this machine, by name, built-in first. Screens are left out."""
    cams: list[Webcam] = []
    if platform.system() == "Darwin":
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                                 capture_output=True, text=True, timeout=8).stderr
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        section = out.split("AVFoundation audio devices")[0]
        for m in re.finditer(r"\[(\d+)\] (.+)", section):
            name = m.group(2).strip()
            if name.lower().startswith("capture screen"):
                continue
            cams.append(Webcam(int(m.group(1)), name, _kind(name)))
    if not cams:  # other systems, or FFmpeg missing: probe the first few indexes
        for i in range(4):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                cams.append(Webcam(i, f"Camera {i}", "builtin" if i == 0 else "external"))
            cap.release()
    cams.sort(key=lambda c: ({"builtin": 0, "external": 1, "phone": 2}[c.kind], c.index))
    if cams:
        cams[0].default = True
    return cams


def resolve(url: str) -> Webcam | None:
    """A stored webcam reference -> the device to open now.

    "" or a bare index (old cameras saved as "0") means the default camera, which is the built-in one, never a
    phone that happens to sit at that index. Anything else is a device name.
    """
    cams = list_webcams()
    if not cams:
        return None
    ref = (url or "").strip()
    if ref == "" or ref.isdigit():
        return cams[0]
    exact = [c for c in cams if c.name == ref]
    if exact:
        return exact[0]
    loose = [c for c in cams if ref.lower() in c.name.lower()]
    return loose[0] if loose else None
