"""Object detectors.

- COCO targets (person, car, dog, ...) go to RF-DETR (Apache-2.0, ~40 ms/frame on an M3 Pro).
- Anything else goes to OWLv2 (Apache-2.0, open vocabulary, ~0.4 s/frame), run less often.
Per-watch verifier heads on top of SigLIP crop embeddings clean up both.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import cv2
import numpy as np
import torch
from PIL import Image

from ..config import settings
from . import gpu_lock
from .geometry import Box, iou

log = logging.getLogger("vigil.detector")

# user vocabulary -> COCO class name
COCO_SYNONYMS: dict[str, list[str]] = {
    "person": [
        "person", "people", "human", "humans", "man", "men", "woman", "women", "someone", "somebody", "anyone",
        "worker", "workers", "employee", "employees", "visitor", "visitors", "intruder", "intruders", "child",
        "children", "kid", "kids", "pedestrian", "pedestrians", "customer", "customers", "individual", "stranger",
        "strangers", "delivery person", "courier", "guest", "operator", "staff", "people", "persons",
    ],
    "car": ["car", "cars", "vehicle", "vehicles", "automobile", "sedan", "suv"],
    "truck": ["truck", "trucks", "lorry", "pickup truck", "delivery truck", "semi truck"],
    "bus": ["bus", "buses"],
    "motorcycle": ["motorcycle", "motorbike", "scooter"],
    "bicycle": ["bicycle", "bike", "bikes", "bicycles"],
    "dog": ["dog", "dogs", "puppy"],
    "cat": ["cat", "cats", "kitten"],
    "bird": ["bird", "birds"],
    "backpack": ["backpack", "rucksack"],
    "handbag": ["handbag", "purse"],
    "suitcase": ["suitcase", "luggage"],
    "bottle": ["bottle", "bottles"],
    "cup": ["cup", "mug"],
    "chair": ["chair", "chairs"],
    "laptop": ["laptop"],
    "cell phone": ["phone", "cell phone", "mobile phone", "smartphone"],
    "knife": ["knife"],
    "umbrella": ["umbrella"],
    "boat": ["boat"],
    "horse": ["horse"],
    "sheep": ["sheep"],
    "cow": ["cow", "cattle"],
    "bear": ["bear"],
    "fire hydrant": ["fire hydrant"],
    "potted plant": ["plant", "potted plant"],
    "tv": ["tv", "television", "monitor"],
}
_SYN_INDEX = {syn: coco for coco, syns in COCO_SYNONYMS.items() for syn in syns}


def coco_class_for(target: str) -> str | None:
    t = re.sub(r"[^a-z ]", "", target.lower()).strip()
    t = re.sub(r"^(a|an|the|any)\s+", "", t)
    if t in _SYN_INDEX:
        return _SYN_INDEX[t]
    return None


@dataclass
class Detection:
    label: str  # the user's target word
    conf: float
    box: Box  # normalized xyxy
    source: str = "coco"


class CocoDetector:
    def __init__(self, size: str | None = None):
        import rfdetr
        from rfdetr.assets.coco_classes import COCO_CLASSES

        size = (size or settings.coco_model).lower()
        cls = {
            "nano": rfdetr.RFDETRNano,
            "small": rfdetr.RFDETRSmall,
            "medium": rfdetr.RFDETRMedium,
        }.get(size, rfdetr.RFDETRNano)
        self.model = cls()
        self.names: dict[int, str] = dict(COCO_CLASSES)

    def detect(self, frame: np.ndarray, wanted: dict[str, list[str]], threshold: float = 0.4) -> list[Detection]:
        """`wanted` maps COCO class name -> user target labels that should receive that class."""
        if not wanted:
            return []
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        with gpu_lock:
            dets = self.model.predict(rgb, threshold=threshold)
        out: list[Detection] = []
        for xyxy, cid, conf in zip(dets.xyxy, dets.class_id, dets.confidence):
            name = self.names.get(int(cid))
            if name not in wanted:
                continue
            box = (float(xyxy[0] / w), float(xyxy[1] / h), float(xyxy[2] / w), float(xyxy[3] / h))
            for label in wanted[name]:
                out.append(Detection(label, float(conf), box, "coco"))
        return out


class OpenVocabDetector:
    def __init__(self, model_id: str | None = None):
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        self.model_id = model_id or settings.open_vocab_model
        self.device = settings.device
        self.processor = Owlv2Processor.from_pretrained(self.model_id)
        self.model = Owlv2ForObjectDetection.from_pretrained(self.model_id).to(self.device).eval()

    @torch.no_grad()
    def detect(self, frame: np.ndarray, queries: list[str], threshold: float = 0.2, top_k: int = 50) -> list[Detection]:
        if not queries:
            return []
        h, w = frame.shape[:2]
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        texts = [[f"a photo of {q}" for q in queries]]
        with gpu_lock:
            inputs = self.processor(text=texts, images=image, return_tensors="pt").to(self.device)
            outputs = self.model(**inputs)
            side = max(h, w)  # OWLv2 pads to a square; boxes are relative to the padded image
            res = self.processor.post_process_grounded_object_detection(
                outputs, threshold=threshold, target_sizes=[(side, side)], text_labels=texts
            )[0]
        boxes = res["boxes"].float().cpu().numpy()
        scores = res["scores"].float().cpu().numpy()
        labels = res["labels"].cpu().numpy()
        order = np.argsort(-scores)[:top_k]
        dets: list[Detection] = []
        for i in order:
            x1, y1, x2, y2 = (float(v) for v in boxes[i])
            box = (max(0.0, x1 / w), max(0.0, y1 / h), min(1.0, x2 / w), min(1.0, y2 / h))
            if box[2] - box[0] < 0.005 or box[3] - box[1] < 0.005:
                continue
            dets.append(Detection(queries[int(labels[i])], float(scores[i]), box, "owl"))
        return nms(dets, 0.5)


def nms(dets: list[Detection], thr: float) -> list[Detection]:
    keep: list[Detection] = []
    for d in sorted(dets, key=lambda d: -d.conf):
        if all(not (k.label == d.label and iou(k.box, d.box) > thr) for k in keep):
            keep.append(d)
    return keep


_coco: CocoDetector | None = None
_owl: OpenVocabDetector | None = None
_init_lock = threading.Lock()


def get_coco() -> CocoDetector:
    global _coco
    with _init_lock:
        if _coco is None:
            log.info("loading RF-DETR (%s)", settings.coco_model)
            _coco = CocoDetector()
        return _coco


def get_owl() -> OpenVocabDetector:
    global _owl
    with _init_lock:
        if _owl is None:
            log.info("loading OWLv2 %s", settings.open_vocab_model)
            _owl = OpenVocabDetector()
        return _owl
