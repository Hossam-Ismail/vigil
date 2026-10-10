"""Per-watch classifier heads on frozen SigLIP embeddings.

The head is logistic regression whose weights are regularized toward the zero-shot text
direction (w0 = scale * (text(positive) - text(negative))):

    loss = balanced BCE + lam/2 * ||w - w0||^2

With no labels this *is* the zero-shot classifier; with a handful of labels it bends toward
the data; with many labels the data dominates. Once both classes have RFF_MIN examples, cross-validation
may also pick a non-linear variant (random Fourier features approximating an RBF kernel), which helps
when "yes" and "no" differ in ways a single direction can't capture. Training takes well under a
second, so every user correction or verifier verdict can retrain immediately.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

LAMBDAS = (1e-4, 3e-4, 1e-3, 0.003, 0.01, 0.03, 0.1, 0.3)
RFF_DIM = 1024
RFF_GAMMA = 2.0
RFF_MIN = 32  # examples of each class before the head may bend non-linearly

_rff_cache: dict[tuple[int, int, float], tuple[np.ndarray, np.ndarray]] = {}


def rff_features(X: np.ndarray, dim: int, gamma: float) -> np.ndarray:
    """Random Fourier features for exp(-gamma * ||x - y||^2), with a fixed seed so saved heads reload."""
    key = (X.shape[1], dim, gamma)
    if key not in _rff_cache:
        r = np.random.default_rng(0)
        _rff_cache[key] = (r.normal(0, math.sqrt(2 * gamma), (X.shape[1], dim)).astype(np.float32),
                           r.uniform(0, 2 * math.pi, dim).astype(np.float32))
    om, be = _rff_cache[key]
    return math.sqrt(2 / dim) * np.cos(X @ om + be)


def _features(X: np.ndarray, rff: int, gamma: float) -> np.ndarray:
    return np.concatenate([X, rff_features(X, rff, gamma)], axis=1) if rff else X


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -40, 40)))


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


@dataclass
class Head:
    w: np.ndarray
    b: float
    threshold: float = 0.5
    mode: str = "zeroshot"  # zeroshot | oneclass_neg | oneclass_pos | trained
    version: int = 0
    metrics: dict = field(default_factory=dict)
    rff: int = 0  # random Fourier feature count; 0 = linear
    gamma: float = 0.0

    def proba(self, X: np.ndarray) -> np.ndarray:
        if X.ndim == 1:
            X = X[None]
        return sigmoid(_features(X, self.rff, self.gamma) @ self.w + self.b)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, w=self.w, b=self.b)
        meta = {k: v for k, v in asdict(self).items() if k not in ("w", "b")}
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2))

    @classmethod
    def load(cls, path: Path) -> "Head":
        data = np.load(path)
        meta = json.loads(path.with_suffix(".json").read_text())
        return cls(w=data["w"].astype(np.float32), b=float(data["b"]), **meta)


def _fit(X: np.ndarray, y: np.ndarray, w0: np.ndarray, b0: float, lam: float) -> tuple[np.ndarray, float]:
    n_pos = max(1, int(y.sum()))
    n_neg = max(1, int(len(y) - y.sum()))
    sw = np.where(y == 1, len(y) / (2 * n_pos), len(y) / (2 * n_neg))
    sw = sw / sw.sum()
    d = X.shape[1]

    def f(theta: np.ndarray) -> tuple[float, np.ndarray]:
        w, b = theta[:d], theta[d]
        z = X @ w + b
        p = sigmoid(z)
        eps = 1e-9
        loss = -np.sum(sw * (y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)))
        dw = w - w0
        loss += 0.5 * lam * float(dw @ dw)
        g = sw * (p - y)
        grad_w = X.T @ g + lam * dw
        grad_b = g.sum()
        return float(loss), np.concatenate([grad_w, [grad_b]])

    theta0 = np.concatenate([w0, [b0]]).astype(np.float64)
    res = minimize(f, theta0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return res.x[:d].astype(np.float32), float(res.x[d])


def _folds(y: np.ndarray, k: int, seed: int = 0) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    pos = rng.permutation(np.flatnonzero(y == 1))
    neg = rng.permutation(np.flatnonzero(y == 0))
    folds = [np.concatenate([pos[i::k], neg[i::k]]) for i in range(k)]
    return [f for f in folds if len(f)]


def _metrics(y: np.ndarray, p: np.ndarray, thr: float) -> dict:
    pred = (p >= thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "accuracy": round((tp + tn) / max(1, len(y)), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def _best_threshold(y: np.ndarray, p: np.ndarray) -> float:
    best, best_thr = -1.0, 0.5
    for thr in np.linspace(0.25, 0.75, 21):
        m = _metrics(y, p, float(thr))
        # prefer F1; tie-break toward 0.5 for stability
        score = m["f1"] - 0.01 * abs(thr - 0.5)
        if score > best:
            best, best_thr = score, float(thr)
    return best_thr


def train_head(
    X: np.ndarray,
    y: np.ndarray,
    w0: np.ndarray,
    b0: float = 0.0,
    *,
    version: int = 0,
) -> Head:
    """Train a text-anchored head from labeled embeddings (y in {0,1})."""
    y = y.astype(np.float64)
    n = len(y)
    n_pos = int(y.sum())
    n_neg = n - n_pos
    base = {"n_pos": n_pos, "n_neg": n_neg, "n": n}

    if n:
        zs = sigmoid(X @ w0 + b0)
        base["zero_shot"] = _metrics(y.astype(int), zs, 0.5)

    if n_pos == 0 and n_neg == 0:
        return Head(w0.copy(), b0, 0.5, "zeroshot", version, {**base, "mode": "zeroshot"})

    if n_pos == 0:
        # Only "normal" examples so far: keep the text direction, but shift the bias so every
        # observed negative sits comfortably below threshold.
        z_max = float(np.max(X @ w0))
        b = min(b0, logit(0.2) - z_max)
        return Head(w0.copy(), b, 0.5, "oneclass_neg", version, {**base, "mode": "oneclass_neg"})

    if n_neg == 0:
        # Only alert-worthy examples: nudge the bias just enough that the typical positive clears the
        # threshold. Kept deliberately small, because "everything is positive" data says little about
        # what normal looks like.
        z_med = float(np.median(X @ w0))
        b = max(b0, min(logit(0.6) - z_med, b0 + 2.0))
        return Head(w0.copy(), b, 0.5, "oneclass_pos", version, {**base, "mode": "oneclass_pos"})

    k = min(5, n_pos, n_neg)
    if k >= 2:
        # pick the variant (linear or non-linear), regularization strength and threshold from out-of-fold predictions
        variants = [(0, 0.0)] + ([(RFF_DIM, RFF_GAMMA)] if min(n_pos, n_neg) >= RFF_MIN else [])
        best, best_ll, best_oof = (0, 0.0, LAMBDAS[4]), float("inf"), None
        folds = _folds(y, k)
        for rff, gamma in variants:
            F = _features(X, rff, gamma)
            W0 = np.concatenate([w0, np.zeros(rff, np.float32)]) if rff else w0
            for lam in LAMBDAS:
                oof = np.zeros(n)
                for f in folds:
                    tr = np.setdiff1d(np.arange(n), f)
                    w, b = _fit(F[tr], y[tr], W0, b0, lam)
                    oof[f] = sigmoid(F[f] @ w + b)
                ll = -np.mean(y * np.log(oof + 1e-9) + (1 - y) * np.log(1 - oof + 1e-9))
                if ll < best_ll:
                    best, best_ll, best_oof = (rff, gamma, lam), ll, oof
        assert best_oof is not None
        rff, gamma, lam = best
        thr = _best_threshold(y.astype(int), best_oof)
        cv = _metrics(y.astype(int), best_oof, thr)
        W0 = np.concatenate([w0, np.zeros(rff, np.float32)]) if rff else w0
        w, b = _fit(_features(X, rff, gamma), y, W0, b0, lam)
        metrics = {**base, "mode": "trained", "cv": cv, "cv_folds": k, "lambda": lam, "log_loss": round(best_ll, 4),
                   "nonlinear": bool(rff)}
        return Head(w, b, thr, "trained", version, metrics, rff=rff, gamma=gamma)

    # one example of the minority class: trust the prior more
    w, b = _fit(X, y, w0, b0, 0.1)
    fit = _metrics(y.astype(int), sigmoid(X @ w + b), 0.5)
    return Head(w, b, 0.5, "trained", version, {**base, "mode": "trained", "fit": fit, "low_data": True})
