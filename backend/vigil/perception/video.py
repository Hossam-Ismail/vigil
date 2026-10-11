"""Video-text model: a short clip in, a score for each written option out.

X-CLIP (microsoft/xclip-base-patch32) embeds 8 frames together, so motion counts: "a person pressing a button"
and "a person resting a hand on a button" look different over a second even when single frames do not. Any
option text works without training (zero-shot), like SigLIP does for single images.
"""

from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np
import torch

from ..config import settings
from . import gpu_lock

log = logging.getLogger("vigil.video")

MODEL_ID = "microsoft/xclip-base-patch32"
NUM_FRAMES = 8


class VideoText:
    def __init__(self, model_id: str = MODEL_ID, device: str | None = None):
        from transformers import XCLIPModel, XCLIPProcessor

        self.model_id = model_id
        self.device = device or settings.device
        self.model = XCLIPModel.from_pretrained(model_id).to(self.device).eval()
        self.processor = XCLIPProcessor.from_pretrained(model_id)

    @staticmethod
    def sample(frames: list[np.ndarray], n: int = NUM_FRAMES) -> list[np.ndarray]:
        """n frames spread evenly over the clip (repeats frames when the clip is shorter)."""
        idx = np.linspace(0, len(frames) - 1, n).round().astype(int)
        return [frames[i] for i in idx]

    @torch.no_grad()
    def score(self, frames_bgr: list[np.ndarray], options: list[str]) -> tuple[list[float], float]:
        """Probability of each option for this clip (softmax over the options) and the time it took in ms."""
        if not frames_bgr or not options:
            raise ValueError("need frames and at least one option")
        clip = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in self.sample(frames_bgr)]
        t = time.perf_counter()
        inputs = self.processor(text=options, videos=[clip], return_tensors="pt", padding=True)
        with gpu_lock:
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            logits = self.model(**inputs).logits_per_video[0].float()
            probs = torch.softmax(logits, dim=-1).cpu().numpy()
        return [float(p) for p in probs], (time.perf_counter() - t) * 1000


_model: VideoText | None = None
_init_lock = threading.Lock()


def get_videotext() -> VideoText:
    global _model
    with _init_lock:
        if _model is None:
            log.info("loading video-text model %s", MODEL_ID)
            with gpu_lock:
                try:
                    _model = VideoText()
                except Exception:  # noqa: BLE001
                    log.exception("could not load %s on %s; using the CPU", MODEL_ID, settings.device)
                    _model = VideoText(device="cpu")
        return _model
