"""Training process for one watch's model. Run by finetune.train(); prints @@{json} progress lines.

  python -m vigil.learning.train_worker --kind detector|classifier --dir data/models/watch_N/finetune --epochs 12

Detector: RF-DETR Nano fine-tuned on the COCO split in <dir>/dataset. Classifier: MobileNetV3-Large fine-tuned on
<dir>/dataset/{train,valid}/{yes,no}. Afterwards the model is scored on the held-out validation images, and the
alert threshold is the one with the best F1 there.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np


def emit(**msg) -> None:
    print("@@" + json.dumps(msg), flush=True)


def _f1_threshold(scores: np.ndarray, labels: np.ndarray) -> tuple[float, dict]:
    best = (0.5, {"f1": 0.0})
    for t in np.arange(0.05, 0.91, 0.025):
        pred = scores >= t
        tp = int((pred & (labels == 1)).sum())
        fp = int((pred & (labels == 0)).sum())
        fn = int((~pred & (labels == 1)).sum())
        tn = int((~pred & (labels == 0)).sum())
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        if f1 > best[1]["f1"]:
            best = (float(t), {"f1": f1, "precision": p, "recall": r, "accuracy": (tp + tn) / max(1, len(labels)),
                               "n": int(len(labels)), "n_yes": int((labels == 1).sum())})
    return best


# ---------------------------------------------------------------------------------------------
# detector


def train_detector(d: Path, epochs: int) -> dict:
    import cv2
    import rfdetr

    ds = d / "dataset"
    out = d / "run"
    out.mkdir(parents=True, exist_ok=True)
    cats = json.loads((ds / "train" / "_annotations.coco.json").read_text())["categories"]
    names = [c["name"] for c in cats]
    model = rfdetr.RFDETRNano()
    emit(type="progress", stage="train", progress=0.0, message=f"training on {len(names)} classes")

    # report progress by watching the epoch checkpoints appear
    done = threading.Event()

    def watch():
        t0 = time.time()
        while not done.wait(5):
            ep, m50 = 0, None
            csv = out / "metrics.csv"
            if csv.exists():
                rows = csv.read_text().splitlines()
                head = rows[0].split(",") if rows else []
                col = head.index("val/mAP_50") if "val/mAP_50" in head else -1
                vals = [r.split(",") for r in rows[1:]]
                done_rows = [v for v in vals if col >= 0 and len(v) > col and v[col]]
                ep = len(done_rows)
                if done_rows:
                    m50 = float(done_rows[-1][col])
            el = int(time.time() - t0)
            eta = f" · about {max(1, round(el / ep * (epochs - ep) / 60))} min left" if ep else ""
            emit(type="progress", stage="train", progress=min(0.99, ep / max(1, epochs)),
                 message=f"epoch {min(ep + 1, epochs)} of {epochs}"
                         + (f" · detection score (mAP50) {round(100 * m50)}%" if m50 is not None else "") + eta,
                 epoch=ep, map50=m50)

    threading.Thread(target=watch, daemon=True).start()
    try:
        model.train(dataset_dir=str(ds), epochs=epochs, batch_size=4, grad_accum_steps=4, lr=1e-4,
                    output_dir=str(out), device="mps", num_workers=0, progress_bar=False, tensorboard=False,
                    run_test=False, early_stopping=True, early_stopping_patience=4, class_names=names)
    finally:
        done.set()
    weights = next((p for p in (out / "checkpoint_best_total.pth", out / "checkpoint_best_ema.pth",
                                out / "checkpoint_best_regular.pth", out / "checkpoint.pth") if p.exists()), None)
    if weights is None:
        cands = sorted(out.glob("*.pth"), key=lambda p: p.stat().st_mtime)
        weights = cands[-1] if cands else None
    if weights is None:
        raise RuntimeError("training produced no weights")
    for p in out.glob("*.ckpt"):
        p.unlink(missing_ok=True)  # resumable Lightning checkpoints are ~0.5 GB each; the .pth is all we need

    # held-out check: does the model find the target in images that have one, and stay quiet otherwise?
    emit(type="progress", stage="evaluate", progress=0.0, message="testing on held-out images")
    trained = rfdetr.RFDETRNano(pretrain_weights=str(weights), num_classes=len(names))
    val = json.loads((ds / "valid" / "_annotations.coco.json").read_text())
    has = {a["image_id"] for a in val["annotations"] if a["category_id"] == 0}
    scores, labels = [], []
    for i, im in enumerate(val["images"]):
        img = cv2.imread(str(ds / "valid" / im["file_name"]))
        if img is None:
            continue
        det = trained.predict(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), threshold=0.05)
        s = max((float(c) for k, c in zip(det.class_id, det.confidence) if int(k) == 0), default=0.0)
        scores.append(s)
        labels.append(1 if im["id"] in has else 0)
        if i % 20 == 0:
            emit(type="progress", stage="evaluate", progress=i / max(1, len(val["images"])),
                 message=f"tested {i}/{len(val['images'])} held-out images")
    thr, m = _f1_threshold(np.array(scores), np.array(labels))
    return {"type": "result", "kind": "detector", "weights": str(weights), "num_classes": len(names),
            "class_names": names, "target_class_id": 0, "threshold": thr, "eval": m, "epochs": epochs}


# ---------------------------------------------------------------------------------------------
# classifier


def train_classifier(d: Path, epochs: int) -> dict:
    import torch
    from torch.utils.data import DataLoader
    from torchvision import datasets, models, transforms

    ds = d / "dataset"
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    norm = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    tr = transforms.Compose([transforms.RandomResizedCrop(224, scale=(0.6, 1.0)), transforms.RandomHorizontalFlip(),
                             transforms.ColorJitter(0.3, 0.3, 0.2), transforms.ToTensor(), norm])
    te = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(), norm])
    train_ds = datasets.ImageFolder(ds / "train", tr)
    val_ds = datasets.ImageFolder(ds / "valid", te)
    yes_index = train_ds.class_to_idx.get("yes", 1)
    m = models.mobilenet_v3_large(weights=models.MobileNet_V3_Large_Weights.IMAGENET1K_V2)
    m.classifier[3] = torch.nn.Linear(m.classifier[3].in_features, 2)
    m = m.to(dev)
    opt = torch.optim.AdamW(m.parameters(), lr=3e-4, weight_decay=1e-4)
    counts = np.bincount([y for _, y in train_ds.samples], minlength=2).astype(np.float32)
    weight = torch.tensor(counts.sum() / np.maximum(counts, 1) / 2, dtype=torch.float32, device=dev)
    loss_fn = torch.nn.CrossEntropyLoss(weight=weight)
    dl = DataLoader(train_ds, batch_size=32, shuffle=True, num_workers=0)
    vl = DataLoader(val_ds, batch_size=64, num_workers=0)
    best, best_state = -1.0, None
    t0 = time.time()

    def evaluate():
        m.eval()
        ss, ys = [], []
        with torch.no_grad():
            for x, y in vl:
                p = torch.softmax(m(x.to(dev)), 1)[:, yes_index].cpu().numpy()
                ss += list(p)
                ys += [1 if int(v) == yes_index else 0 for v in y]
        m.train()
        return np.array(ss), np.array(ys)

    for ep in range(epochs):
        m.train()
        for x, y in dl:
            opt.zero_grad()
            loss = loss_fn(m(x.to(dev)), y.to(dev))
            loss.backward()
            opt.step()
        s, y = evaluate()
        _, met = _f1_threshold(s, y)
        if met["f1"] > best:
            best, best_state = met["f1"], {k: v.detach().cpu().clone() for k, v in m.state_dict().items()}
        emit(type="progress", stage="train", progress=(ep + 1) / epochs,
             message=f"epoch {ep + 1} of {epochs} · held-out F1 {met['f1']:.2f} · {int(time.time() - t0)}s")
    m.load_state_dict(best_state)
    s, y = evaluate()
    thr, met = _f1_threshold(s, y)
    weights = d / "classifier.pt"
    torch.save(m.state_dict(), weights)
    return {"type": "result", "kind": "classifier", "weights": str(weights), "yes_index": yes_index,
            "threshold": thr, "eval": met, "epochs": epochs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--epochs", type=int, default=12)
    a = ap.parse_args()
    d = Path(a.dir)
    try:
        res = train_detector(d, a.epochs) if a.kind == "detector" else train_classifier(d, a.epochs)
    except Exception as exc:  # noqa: BLE001
        print(f"training error: {exc}", flush=True)
        raise
    emit(**res)


if __name__ == "__main__":
    sys.exit(main())
