"""Find the region a request refers to ("the blue bin on the top-left shelf").

1. If the brain can output boxes directly (local Qwen), ask it.
2. Otherwise propose candidate boxes with OWLv2 and ask the brain which numbered box matches
   (set-of-mark prompting, works with any VLM including Claude).
3. Without a capable brain, rank the candidates by SigLIP text-image similarity.
"""

from __future__ import annotations

import logging

import numpy as np

from ..brain.base import Brain, draw_marks
from ..perception.detector import get_owl
from ..perception.embedder import get_embedder
from ..perception.geometry import Box, crop, iou, pad_box
from ..schemas import WatchSpec, Zone

log = logging.getLogger("vigil.locate")


def proposals(frame: np.ndarray, queries: list[str], k: int = 8) -> list[Box]:
    queries = [q for q in dict.fromkeys(queries) if q]
    if not queries:
        return []
    dets = [d for d in get_owl().detect(frame, queries, threshold=0.08, top_k=40)
            if 0.002 <= (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]) <= 0.6]
    # OWLv2 fires on parts (the front lip of a bin), whole objects (the bin) and groups (a row of bins).
    # Groups contain two or more other candidates: drop them. Parts sit inside exactly one larger,
    # similarly scored candidate: drop those too, keeping whole objects.
    def inside(inner, outer) -> bool:
        return inner is not outer and _area(outer.box) > _area(inner.box) * 1.2 and _contained(inner.box, outer.box) > 0.85

    groups = {id(o) for o in dets if sum(1 for d in dets if inside(d, o)) >= 2}
    dets = [d for d in dets if id(d) not in groups]
    whole = [d for d in dets if not any(inside(d, o) and o.conf >= 0.6 * d.conf for o in dets)]
    boxes: list[Box] = []
    for d in whole:
        if all(iou(d.box, b) < 0.5 for b in boxes):
            boxes.append(d.box)
        if len(boxes) >= k:
            break
    return boxes


def _area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _contained(inner: Box, outer: Box) -> float:
    """Fraction of `inner` that lies inside `outer`."""
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    a = _area(inner)
    return ix * iy / a if a else 0.0


def propose_zone(frame: np.ndarray, spec: WatchSpec, brain: Brain) -> tuple[Zone | None, dict]:
    if not spec.locate:
        return None, {"method": "full_frame"}
    pad = 0.06 if spec.kind == "state" else 0.15
    info: dict = {"method": None, "candidates": []}

    if brain.supports_boxes:
        try:
            box = brain.locate(frame, spec.locate)
            if box:
                info["method"] = "vlm_box"
                return Zone.from_box(*pad_box(box, pad)), info
        except Exception as exc:  # noqa: BLE001
            log.warning("direct locate failed: %s", exc)

    boxes = proposals(frame, [spec.locate_noun, spec.locate])
    info["candidates"] = [[round(v, 4) for v in b] for b in boxes]
    if not boxes:
        info["method"] = "full_frame"
        return None, info

    idx: int | None = None
    if len(boxes) == 1:
        idx = 1
        info["method"] = "single_candidate"
    else:
        try:
            idx = brain.choose_mark(draw_marks(frame, boxes), spec.locate, len(boxes))
            if idx:
                info["method"] = "set_of_mark"
        except Exception as exc:  # noqa: BLE001
            log.warning("set-of-mark failed: %s", exc)
    if not idx:
        emb = get_embedder()
        X = emb.embed_images([crop(frame, b) for b in boxes])
        sims = X @ emb.embed_text(spec.locate)
        sims = (sims - sims.mean()) / (sims.std() + 1e-6) + _spatial_bonus(spec.locate, boxes)
        idx = int(np.argmax(sims)) + 1
        info["method"] = "siglip_rank"
    info["chosen"] = idx
    return Zone.from_box(*pad_box(boxes[idx - 1], pad)), info


SPATIAL = {
    "top": (0, -1), "upper": (0, -1), "above": (0, -1), "bottom": (0, 1), "lower": (0, 1), "below": (0, 1),
    "left": (-1, 0), "leftmost": (-1, 0), "right": (1, 0), "rightmost": (1, 0),
}


def _spatial_bonus(phrase: str, boxes: list[Box]) -> np.ndarray:
    """Position words ("top shelf", "on the left") favour candidates in that part of the frame."""
    words = set(phrase.lower().replace("-", " ").split())
    bonus = np.zeros(len(boxes))
    centers = np.array([((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes])
    for w, (dx, dy) in SPATIAL.items():
        if w in words:
            axis = centers[:, 0] if dx else centers[:, 1]
            spread = axis.max() - axis.min()
            if spread > 0.05:
                bonus += 1.5 * (dx or dy) * (axis - axis.mean()) / spread
    return bonus
