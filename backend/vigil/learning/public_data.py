"""Find a public dataset that matches a watch's request and turn it into training examples.

When a watch is created, Vigil searches the Hugging Face Hub for datasets about the same thing (hard hats, parking
spaces, forklifts...), keeps the ones with an open license and a layout it can read, maps their class names onto the
watch's YES / NO, checks that mapping against what the images actually look like, and returns a balanced sample of
labeled crops. They train the watch's model from day one at a lower weight than the camera's own confirmed examples,
which still decide in the end.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import cv2
import numpy as np

from ..config import settings
from ..schemas import WatchSpec

log = logging.getLogger("vigil.public_data")

# licenses that allow commercial use; anything non-commercial, no-derivatives or unknown is skipped
OPEN_LICENSES = {"cc0-1.0", "cc-by-4.0", "cc-by-3.0", "cc-by-2.0", "cc-by-sa-4.0", "cc-by-sa-3.0", "mit",
                 "apache-2.0", "bsd-3-clause", "bsd-2-clause", "odbl", "pddl", "unlicense", "openrail"}
STOP = {"a", "an", "the", "of", "in", "on", "at", "to", "is", "are", "with", "without", "no", "not", "someone",
        "person's", "persons", "their", "its", "it", "and", "or", "any", "some", "this", "that", "wearing", "being",
        "has", "have", "there", "empty", "full", "open", "closed", "left", "parked", "for", "by", "from", "one"}
NEG = {"no", "not", "without", "missing", "empty", "vacant", "free", "none", "unoccupied", "nohelmet", "nohardhat",
       "bare", "absent"}
TASKS = {"object-detection", "image-classification"}
HUGE = {"1M<n<10M", "10M<n<100M", "100M<n<1B", "1B<n<10B", "n>1T"}
GENERIC = {"person", "people", "head", "thing", "object", "area", "region", "image", "camera", "photo", "someone",
           "anyone", "front", "back", "side", "row", "door"}
CACHE = settings.data_dir / "public_data"


@dataclass
class Found:
    repo: str
    license: str
    yes: list[str]
    no: list[str]
    X: np.ndarray                      # embeddings
    y: np.ndarray                      # 1 = YES for this watch
    crops: list[np.ndarray] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"dataset": self.repo, "license": self.license, "yes_classes": self.yes, "no_classes": self.no,
                "n": int(len(self.y)), "n_yes": int(self.y.sum())}


# ---------------------------------------------------------------------------------------------
# search


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z'-]+", text.lower()) if t not in STOP and len(t) > 2]


def brain_queries(spec: WatchSpec, prompt: str, brain) -> list[str]:
    """Ask the brain for dataset names and search terms (it knows datasets like PKLot that keyword search misses)."""
    if brain is None:
        return []
    try:
        out = brain.text_json(
            "We need labeled public images to train a camera classifier.\n"
            f"Request: {prompt or spec.question}\nYES looks like: {spec.positive_label}\n"
            f"NO looks like: {spec.negative_label}\n"
            "Suggest up to 4 short Hugging Face dataset search terms: names of well-known public datasets for this "
            "(e.g. PKLot for parking spaces) and plain keywords. Short terms only, no sentences.",
            {"type": "object", "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
             "required": ["terms"], "additionalProperties": False})
        terms = [str(t).strip() for t in (out or {}).get("terms", []) if 1 < len(str(t).strip()) <= 40]
        return terms[:4]
    except Exception as exc:  # noqa: BLE001
        log.info("brain could not suggest dataset terms: %s", exc)
        return []


def queries(spec: WatchSpec, prompt: str = "") -> list[str]:
    """Search phrases for the thing being watched, most specific first."""
    phrases: dict[str, int] = {}
    sources = [spec.positive_label, spec.negative_label, spec.target_question, *spec.targets, spec.locate_noun]
    for text in sources:
        toks = _tokens(text or "")
        for n in (2, 1):
            for i in range(len(toks) - n + 1):
                p = " ".join(toks[i : i + n])
                if n == 1 and p in GENERIC:
                    continue
                phrases[p] = phrases.get(p, 0) + (2 if n == 2 else 1)
    ranked = sorted(phrases, key=lambda p: (-phrases[p], -len(p)))
    out = []
    for p in ranked:
        if p not in out:
            out.append(p)
        if p.replace(" ", "") not in out and " " in p:
            out.append(p.replace(" ", ""))  # "hard hat" -> "hardhat"
    return out[:6]


def search(qs: list[str], exclude: tuple[str, ...] = (), limit: int = 12) -> list[dict]:
    from huggingface_hub import HfApi

    api, seen, out = HfApi(), set(), []
    for q in qs:
        try:
            hits = list(api.list_datasets(search=q, sort="downloads", limit=limit, full=True))
        except Exception as exc:  # noqa: BLE001
            log.warning("dataset search failed for %r: %s", q, exc)
            continue
        for d in hits:
            if d.id in seen or any(x in d.id for x in exclude):
                continue
            seen.add(d.id)
            tags = d.tags or []
            lic = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), "")
            tasks = {t.split(":", 1)[1] for t in tags if t.startswith("task_categories:")}
            sizes = {t.split(":", 1)[1] for t in tags if t.startswith("size_categories:")}
            mods = {t.split(":", 1)[1] for t in tags if t.startswith("modality:")}
            restricted = lic and (lic not in OPEN_LICENSES or "-nc" in lic or "-nd" in lic)
            vision = bool(tasks & TASKS) or ("image" in mods and not tasks)
            if restricted or not vision or sizes & HUGE:
                continue
            rank = (0 if lic else 2) + (0 if tasks & TASKS else 1) + (1 if "synth" in d.id.lower() else 0)
            out.append({"id": d.id, "license": lic or "not stated", "downloads": d.downloads or 0, "query": q,
                        "tasks": sorted(tasks), "rank": rank, "order": len(out)})
    # open license + labeled-vision first; within a tier keep the search order (brain terms come first)
    return sorted(out, key=lambda c: (c["rank"], c["order"]))


# ---------------------------------------------------------------------------------------------
# reading a dataset


def _bgr(img) -> np.ndarray:
    arr = np.asarray(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _card_names(repo: str) -> dict[int, str]:
    """Class names for integer labels, read from the dataset card when the features don't carry them."""
    from huggingface_hub import hf_hub_download

    try:
        text = Path(hf_hub_download(repo, "README.md", repo_type="dataset")).read_text(errors="ignore")
    except Exception:  # noqa: BLE001
        return {}
    names: dict[int, str] = {}
    for m in re.finditer(r"'?(\d+)'?\s*:\s*['\"]?([A-Za-z][\w -]{1,30})['\"]?\s*$", text, re.M):
        names.setdefault(int(m.group(1)), m.group(2).strip())
    for m in re.finditer(r"[Cc]lass\s*`?(\d+)`?\s*(?:is|=|means)\s*`?([A-Za-z][\w-]{1,30})`?", text):
        names[int(m.group(1))] = m.group(2)
    return names


def _boxes(objects: dict) -> tuple[list, list]:
    bbox = objects.get("bbox") or objects.get("bboxes") or []
    cats = objects.get("category", objects.get("categories", objects.get("label", objects.get("labels", []))))
    return list(bbox), list(cats)


def _to_xywh(b, w: int, h: int) -> tuple[float, float, float, float]:
    x0, y0, a, c = [float(v) for v in b[:4]]
    if a > x0 and c > y0 and (x0 + a > w * 1.02 or y0 + c > h * 1.02):
        return x0, y0, a - x0, c - y0       # it was x0, y0, x1, y1
    return x0, y0, a, c


def _coco_zip(repo: str) -> Iterator[tuple[np.ndarray, list[tuple[tuple, str]]]]:
    from huggingface_hub import HfApi, hf_hub_download

    files = []
    for folder in ("data", None):
        try:
            files += [e.path for e in HfApi().list_repo_tree(repo, path_in_repo=folder, repo_type="dataset")]
        except Exception:  # noqa: BLE001
            pass
    zips = [f for f in files if re.search(r"(^|/)(valid|validation|test|train)\.zip$", f)]
    zips.sort(key=lambda f: (0 if "valid" in f else 1 if "test" in f else 2))
    if not zips:
        return
    dest = CACHE / repo.replace("/", "__") / Path(zips[0]).stem
    if not dest.exists():
        with zipfile.ZipFile(hf_hub_download(repo, zips[0], repo_type="dataset")) as z:
            z.extractall(dest)
    ann = next(dest.rglob("_annotations.coco.json"), None)
    if ann is None:
        return
    coco = json.loads(ann.read_text())
    cat = {c["id"]: c["name"] for c in coco["categories"]}
    by_img: dict[int, list] = {}
    for a in coco["annotations"]:
        by_img.setdefault(a["image_id"], []).append((tuple(a["bbox"]), cat[a["category_id"]]))
    for im in coco["images"]:
        img = cv2.imread(str(ann.parent / im["file_name"]))
        if img is not None and im["id"] in by_img:
            yield img, by_img[im["id"]]


def examples(repo: str, max_images: int = 300, keep: Callable[[str], bool] | None = None
             ) -> Iterator[tuple[np.ndarray, list[tuple[tuple | None, str]]]]:
    """Yield (image, [(xywh box or None for whole image, class name)]) from the common Hub layouts."""
    from datasets import ClassLabel, get_dataset_split_names, load_dataset

    try:
        splits = get_dataset_split_names(repo)
        split = next((s for s in ("train", "validation", "valid", "test") if s in splits), splits[0])
        ds = load_dataset(repo, split=split, streaming=True)
        feats = ds.features or {}
    except Exception as exc:  # noqa: BLE001
        log.info("%s does not stream (%s); trying a COCO zip", repo, str(exc)[:120])
        n = 0
        for item in _coco_zip(repo):
            yield item
            n += 1
            if n >= max_images:
                return
        return

    names: dict[int, str] = {}
    lab = feats.get("label") if isinstance(feats, dict) else None
    if isinstance(lab, ClassLabel):
        names = dict(enumerate(lab.names))
    obj = feats.get("objects") if isinstance(feats, dict) else None
    if obj is not None:
        inner = obj.feature if hasattr(obj, "feature") else obj
        for key in ("category", "categories", "label", "labels"):
            f = inner.get(key) if isinstance(inner, dict) else None
            f = getattr(f, "feature", f)
            if isinstance(f, ClassLabel):
                names = dict(enumerate(f.names))
    card = None
    pattern: str | None = None
    n = 0
    for ex in ds:
        if n >= max_images:
            return
        if keep is not None and "file_name" in ex and not keep(ex["file_name"]):
            continue
        img = ex.get("image")
        if img is None and "file_name" in ex:
            # metadata-only streaming (imagefolder): fetch the image file next to the metadata
            from huggingface_hub import hf_hub_download
            from PIL import Image

            fn = ex["file_name"]
            patterns = [pattern] if pattern else [f"data/images/{split}/{{}}", f"data/{split}/{{}}", f"{split}/{{}}",
                                                  f"images/{split}/{{}}", "images/{}", "{}"]
            for pat in patterns:
                try:
                    img = Image.open(hf_hub_download(repo, pat.format(fn), repo_type="dataset"))
                    pattern = pat
                    break
                except Exception:  # noqa: BLE001
                    continue
            if img is None:
                if pattern is None:
                    return
                continue
        if img is None:
            return
        bgr = _bgr(img)
        h, w = bgr.shape[:2]

        def name_of(c):
            nonlocal card
            if isinstance(c, str):
                return c
            if int(c) in names:
                return names[int(c)]
            if card is None:
                card = _card_names(repo)
            return card.get(int(c), f"class {int(c)}")

        if "objects" in ex and ex["objects"]:
            bb, cats = _boxes(ex["objects"])
            items = [(_to_xywh(b, w, h), name_of(c)) for b, c in zip(bb, cats)]
        elif "label" in ex:
            items = [(None, name_of(ex["label"]))]
        else:
            return
        n += 1
        yield bgr, items


# ---------------------------------------------------------------------------------------------
# mapping classes to the watch's YES / NO


def _has_neg(text: str) -> bool:
    toks = set(re.findall(r"[a-z]+", text.lower().replace("-", " ").replace("_", " ")))
    return bool(toks & NEG) or bool(re.search(r"\bno[a-z]", text.lower()))


def text_mapping(classes: list[str], spec: WatchSpec, embedder, brain=None) -> dict[str, str]:
    """yes / no / skip per class. Asks the brain when it can answer text questions, else uses text similarity."""
    pos, neg = spec.positive_label, spec.negative_label
    if brain is not None and hasattr(brain, "text_json"):
        try:
            out = brain.text_json(
                "A camera watch answers YES when this is true: " + (spec.question or pos) +
                f"\nYES looks like: {pos}\nNO looks like: {neg}\n"
                "A public dataset labels image crops with these classes: " + json.dumps(classes) +
                "\nFor each class, would a crop of that class be a YES, a NO, or unrelated (skip) for this watch?",
                {"type": "object", "properties": {"mapping": {"type": "array", "items": {
                    "type": "object", "properties": {"label": {"type": "string"},
                                                     "answer": {"type": "string", "enum": ["yes", "no", "skip"]}},
                    "required": ["label", "answer"], "additionalProperties": False}}},
                 "required": ["mapping"], "additionalProperties": False})
            got = {m["label"]: m["answer"] for m in (out or {}).get("mapping", []) if m.get("label") in classes}
            if got:
                return {c: got.get(c, "skip") for c in classes}
        except Exception as exc:  # noqa: BLE001
            log.info("brain class mapping failed (%s); using text similarity", exc)
    tp, tn = embedder.embed_text(pos), embedder.embed_text(neg)
    pos_neg = _has_neg(pos)
    out = {}
    for c in classes:
        t = embedder.embed_text(c.replace("-", " ").replace("_", " "))
        margin = float(t @ tp - t @ tn)
        if _has_neg(c) != _has_neg(neg):        # negation agreement is a strong hint ("no-hardhat" vs "without")
            margin += 0.03 if _has_neg(c) == pos_neg else -0.03
        out[c] = "yes" if margin > 0.01 else "no" if margin < -0.01 else "skip"
    return out


# ---------------------------------------------------------------------------------------------
# putting it together


def _crop(img: np.ndarray, box, pad: float) -> np.ndarray | None:
    if box is None:
        return img
    x, y, w, h = box
    if min(w, h) < 16:
        return None
    H, W = img.shape[:2]
    px, py = w * pad, h * pad
    c = img[max(0, int(y - py)):min(H, int(y + h + py)), max(0, int(x - px)):min(W, int(x + w + px))]
    return c if c.size else None


def collect(spec: WatchSpec, embedder, *, prompt: str = "", brain=None, exclude: tuple[str, ...] = (),
            per_class: int = 200, max_images: int = 300, max_datasets: int = 5,
            progress: Callable[[str], None] | None = None, keep: Callable[[str], bool] | None = None) -> Found | None:
    """Search, read, map and sample. Returns None when nothing usable was found."""
    say = progress or (lambda m: log.info(m))
    pad = 0.25 if spec.target_question else 0.15
    qs = brain_queries(spec, prompt, brain) + queries(spec, prompt)
    say(f"searching public datasets for: {', '.join(qs[:6])}")
    cands = search(qs, exclude=exclude)
    say(f"found {len(cands)} open-license datasets to try")
    w0, b0 = embedder.zero_shot_direction(spec.positive_label, spec.negative_label)
    for cand in cands[:max_datasets]:
        repo = cand["id"]
        try:
            crops: dict[str, list[np.ndarray]] = {}
            for img, items in examples(repo, max_images=max_images, keep=keep):
                for box, cls in items[:8]:
                    c = _crop(img, box, pad)
                    if c is not None and len(crops.setdefault(cls, [])) < per_class * 2:
                        crops[cls].append(c)
                if sum(len(v) for v in crops.values()) >= per_class * 6:
                    break
        except Exception as exc:  # noqa: BLE001
            say(f"{repo}: could not read it ({str(exc)[:80]})")
            continue
        classes = [c for c, v in crops.items() if len(v) >= 10]
        if len(classes) < 1:
            say(f"{repo}: no usable labels")
            continue
        mapping = text_mapping(classes, spec, embedder, brain)
        yes = [c for c in classes if mapping[c] == "yes"]
        no = [c for c in classes if mapping[c] == "no"]
        if not yes or not no:
            say(f"{repo}: classes {classes} don't split into YES and NO for this watch")
            continue
        # check the mapping against the images: YES crops should look more like the YES description
        probe = {c: embedder.embed_images(crops[c][:40]) for c in yes + no}
        m = {c: float((1 / (1 + np.exp(-(probe[c] @ w0 + b0)))).mean()) for c in probe}
        gap = np.mean([m[c] for c in yes]) - np.mean([m[c] for c in no])
        if gap < -0.03:
            yes, no = no, yes
            say(f"{repo}: the images disagreed with the class names, so the mapping was flipped")
        elif gap < 0.02:
            say(f"{repo}: can't tell which classes mean YES from the images; skipped")
            continue
        rng = np.random.default_rng(0)
        imgs, labels = [], []
        for group, lab in ((yes, 1), (no, 0)):
            pool = [c for cls in group for c in crops[cls]]
            idx = rng.permutation(len(pool))[:per_class]
            imgs += [pool[i] for i in idx]
            labels += [lab] * len(idx)
        X = embedder.embed_images(imgs)
        say(f"{repo}: {labels.count(1)} YES ({', '.join(yes)}) and {labels.count(0)} NO ({', '.join(no)}) examples")
        return Found(repo, cand["license"], yes, no, X, np.array(labels), imgs, classes)
    return None
