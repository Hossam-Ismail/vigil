"""Measure Vigil's per-watch heads on real camera footage.

Two real datasets (CC BY 4.0), fetched by scripts/fetch_bench.py:

* PKLot: three fixed parking-lot cameras. Request: "tell me when a parking spot opens up". Each labeled space is a
  region; positive = vacant. A watch belongs to one camera, so each camera gets its own head: labels come from
  that camera's train split, scores from its test split, which holds only capture days the head never saw.
* Hard Hats: real construction/factory photos. Request: "tell me if someone isn't wearing a hard hat". Each labeled
  head is an object crop; positive = no hard hat. Images are split in half: labels from one half, scores on the other.

For each dataset the head starts from the request's words (zero-shot, no examples), then learns from k confirmed
examples (what a YES/NO reply or a correction gives it). Every k is repeated over several random draws.

    .venv/bin/python scripts/benchmark.py ../data/bench
    VIGIL_EMBED_MODEL=google/siglip2-so400m-patch16-384 .venv/bin/python scripts/benchmark.py ../data/bench
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vigil.config import settings  # noqa: E402
from vigil.learning.heads import train_head  # noqa: E402
from vigil.perception.embedder import get_embedder  # noqa: E402

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "../data/bench")
KS = (0, 4, 8, 16, 32, 64, 128, 256, -1)  # -1 = every label in the train pool
MODEL = settings.embed_model.split("/")[-1]
SEEDS = 5


def crop(img: np.ndarray, x: float, y: float, w: float, h: float, pad: float = 0.15) -> np.ndarray:
    H, W = img.shape[:2]
    px, py = w * pad, h * pad
    x0, y0 = max(0, int(x - px)), max(0, int(y - py))
    x1, y1 = min(W, int(x + w + px)), min(H, int(y + h + py))
    return img[y0:y1, x0:x1]


def embed_cached(name: str, build) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cache = ROOT / f"{name}_{MODEL}_emb.npz"
    if cache.exists():
        d = np.load(cache)
        return d["X"], d["y"], d["g"]
    crops, y, g = build()
    t = time.time()
    X = get_embedder().embed_images(crops, batch=32)
    print(f"  embedded {len(crops)} crops in {time.time() - t:.0f}s")
    np.savez(cache, X=X, y=np.array(y), g=np.array(g))
    return X, np.array(y), np.array(g)


def pklot(split: str):
    rows = [json.loads(l) for l in open(ROOT / "pklot" / split / "metadata.jsonl")]
    crops, y, g = [], [], []
    for r in rows:
        img = cv2.imread(str(ROOT / "pklot" / split / r["file_name"]))
        cam = r["file_name"].split("_")[0]
        for (x, yy, w, h), c in zip(r["objects"]["bbox"], r["objects"]["categories"]):
            if w < 8 or h < 8:
                continue
            crops.append(crop(img, x, yy, w, h))
            y.append(1 if c == 0 else 0)  # 0 = vacant -> the thing we alert on
            g.append(cam)
    return crops, y, g


def hardhat():
    coco = json.load(open(ROOT / "hardhat" / "_annotations.coco.json"))
    files = {im["id"]: im["file_name"] for im in coco["images"]}
    crops, y, g = [], [], []
    cache: dict[int, np.ndarray] = {}
    for a in coco["annotations"]:
        x, yy, w, h = a["bbox"]
        if min(w, h) < 16:  # too small to judge at all; Vigil's tracker would not classify these either
            continue
        iid = a["image_id"]
        if iid not in cache:
            cache = {iid: cv2.imread(str(ROOT / "hardhat" / files[iid]))}
        crops.append(crop(cache[iid], x, yy, w, h, pad=0.25))
        y.append(1 if a["category_id"] == 1 else 0)  # 1 = no-hardhat -> alert
        g.append(iid)
    return crops, y, g


def metrics(y: np.ndarray, p: np.ndarray, thr: float) -> dict:
    pred = p >= thr
    tp, tn = int((pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
    fp, fn = int((pred & (y == 0)).sum()), int((~pred & (y == 1)).sum())
    return {
        "acc": (tp + tn) / len(y),
        "bal_acc": 0.5 * (tp / max(1, tp + fn) + tn / max(1, tn + fp)),
        "precision": tp / max(1, tp + fp),
        "recall": tp / max(1, tp + fn),
    }


def curve(name, Xtr, ytr, Xte, yte, pos, neg) -> list[dict]:
    emb = get_embedder()
    w0, b0 = emb.zero_shot_direction(pos, neg)
    out = []
    for k in KS:
        all_labels = k < 0 or k >= len(ytr)
        runs = []
        for s in range(1 if (k == 0 or all_labels) else SEEDS):
            rng = np.random.default_rng(s)
            if k == 0:
                p, thr = 1 / (1 + np.exp(-(Xte @ w0 + b0))), 0.5
            else:
                if all_labels:
                    idx = np.arange(len(ytr))
                else:
                    pi, ni = np.where(ytr == 1)[0], np.where(ytr == 0)[0]
                    idx = np.concatenate([rng.choice(pi, min(k // 2, len(pi)), replace=False),
                                          rng.choice(ni, min(k - k // 2, len(ni)), replace=False)])
                head = train_head(Xtr[idx], ytr[idx], w0, b0)
                p, thr = head.proba(Xte), head.threshold
            runs.append(metrics(yte, p, thr))
        kk = len(ytr) if all_labels else k
        row = {"k": kk, **{m: float(np.mean([r[m] for r in runs])) for m in runs[0]},
               "acc_min": float(np.min([r["acc"] for r in runs]))}
        out.append(row)
        print(f"  {name:8s} k={kk:5d}  acc {row['acc']*100:5.1f}%  (worst draw {row['acc_min']*100:5.1f}%)  "
              f"balanced {row['bal_acc']*100:5.1f}%  precision {row['precision']*100:5.1f}%  recall {row['recall']*100:5.1f}%",
              flush=True)
        if all_labels:
            break
    return out


def main() -> None:
    results = {}
    print("PKLot: 'tell me when a parking spot opens up' (test = unseen days)")
    Xte, yte, gte = embed_cached("pklot_test", lambda: pklot("test"))
    Xtr, ytr, gtr = embed_cached("pklot_train", lambda: pklot("train"))
    results["pklot"] = {}
    for cam in ("PUCPR", "UFPR04", "UFPR05"):
        a, b = gtr == cam, gte == cam
        print(f"  {cam}: train pool {int(a.sum())} spaces, test {int(b.sum())} spaces ({int(yte[b].sum())} vacant)")
        results["pklot"][cam] = {"n_test": int(b.sum()), "n_pos_test": int(yte[b].sum()),
                                 "curve": curve(cam, Xtr[a], ytr[a], Xte[b], yte[b], "an empty parking space",
                                                "a car parked in a parking space")}

    print("Hard Hats: 'tell me if someone isn't wearing a hard hat' (test = unseen images)")
    X, y, g = embed_cached("hardhat", hardhat)
    imgs = np.unique(g)
    rng = np.random.default_rng(0)
    test_imgs = set(rng.choice(imgs, len(imgs) // 2, replace=False).tolist())
    te = np.array([gi in test_imgs for gi in g])
    print(f"  train pool {int((~te).sum())} heads, test {int(te.sum())} heads ({int(y[te].sum())} without a hard hat)")
    results["hardhat"] = {"n_test": int(te.sum()), "n_pos_test": int(y[te].sum()),
                          "curve": curve("hardhat", X[~te], y[~te], X[te], y[te],
                                         "a person's head without a hard hat", "a person wearing a hard hat")}
    out = ROOT / f"results_{MODEL}.json"
    out.write_text(json.dumps({"model": settings.embed_model, **results}, indent=2))
    print("saved", out)


if __name__ == "__main__":
    main()
