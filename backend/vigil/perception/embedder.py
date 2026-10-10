"""SigLIP 2 image/text embeddings: the shared backbone for every per-watch head.

One forward pass per crop serves all watches on a camera; each watch only adds a dot product.
Text embeddings give a zero-shot head before any labels exist.
"""

from __future__ import annotations

import logging
import threading

import cv2
import numpy as np
import torch
from PIL import Image

from ..config import settings
from . import gpu_lock

log = logging.getLogger("vigil.embedder")

TEMPLATES = [
    "{}",
    "a photo of {}",
    "a security camera image of {}",
    "a close-up photo of {}",
]


class Embedder:
    def __init__(self, model_id: str | None = None, device: str | None = None):
        from transformers import AutoModel, AutoProcessor

        self.model_id = model_id or settings.embed_model
        self.device = device or settings.device
        dtype = torch.float16 if self.device in ("mps", "cuda") else torch.float32
        self.dtype = dtype
        self.model = AutoModel.from_pretrained(self.model_id, dtype=dtype).to(self.device).eval()
        self.processor = AutoProcessor.from_pretrained(self.model_id)
        self.logit_scale = float(self.model.logit_scale.exp().item())
        self._text_cache: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()
        size = getattr(self.processor.image_processor, "size", None) or {}
        side = int(size.get("height") or size.get("shortest_edge") or 224)
        with torch.no_grad():
            self.dim = int(self._image_features(torch.zeros(1, 3, side, side)).shape[-1])

    def _image_features(self, pixel_values: torch.Tensor) -> torch.Tensor:
        out = self.model.get_image_features(pixel_values=pixel_values.to(self.device, self.dtype))
        return getattr(out, "pooler_output", out)

    @torch.no_grad()
    def embed_images(self, images: list[np.ndarray], bgr: bool = True, batch: int = 16) -> np.ndarray:
        """Embed a list of HxWx3 uint8 images. Returns L2-normalized float32 [N, D]."""
        if not images:
            return np.zeros((0, self.dim), np.float32)
        pils = [Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB) if bgr else im) for im in images]
        outs = []
        with gpu_lock:
            for i in range(0, len(pils), batch):
                px = self.processor(images=pils[i : i + batch], return_tensors="pt")["pixel_values"]
                feats = self._image_features(px).float()
                outs.append(torch.nn.functional.normalize(feats, dim=-1).cpu().numpy())
        return np.concatenate(outs).astype(np.float32)

    @torch.no_grad()
    def embed_text(self, phrase: str) -> np.ndarray:
        """Prompt-ensembled, L2-normalized text embedding for a phrase."""
        key = phrase.strip().lower()
        with self._lock:
            if key in self._text_cache:
                return self._text_cache[key]
        texts = [t.format(phrase) for t in TEMPLATES]
        with gpu_lock:
            tok = self.processor(text=texts, padding="max_length", max_length=64, return_tensors="pt").to(self.device)
            out = self.model.get_text_features(**tok)
            feats = getattr(out, "pooler_output", out).float()
            feats = torch.nn.functional.normalize(feats, dim=-1).mean(0)
            emb = torch.nn.functional.normalize(feats, dim=-1).cpu().numpy().astype(np.float32)
        with self._lock:
            self._text_cache[key] = emb
        return emb

    def zero_shot_direction(self, positive: str, negative: str) -> tuple[np.ndarray, float]:
        """Weights for a linear head equivalent to a two-way SigLIP softmax: p = sigmoid(w.x + b)."""
        w = self.logit_scale * (self.embed_text(positive) - self.embed_text(negative))
        return w.astype(np.float32), 0.0


_embedder: Embedder | None = None
_init_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _embedder
    with _init_lock:
        if _embedder is None:
            log.info("loading embedder %s on %s", settings.embed_model, settings.device)
            _embedder = Embedder()
        return _embedder
