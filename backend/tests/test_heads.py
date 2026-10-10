import numpy as np

from vigil.learning.heads import Head, train_head


def _data(n_pos, n_neg, d=64, sep=0.35, seed=0):
    rng = np.random.default_rng(seed)
    axis = np.zeros(d)
    axis[0] = 1
    pos = rng.normal(0, 0.15, (n_pos, d)) + axis * sep
    neg = rng.normal(0, 0.15, (n_neg, d)) - axis * sep
    X = np.vstack([pos, neg]).astype(np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    y = np.array([1] * n_pos + [0] * n_neg)
    return X, y


def test_zero_shot_when_no_labels():
    w0 = np.ones(8, np.float32)
    head = train_head(np.zeros((0, 8), np.float32), np.zeros(0), w0, 0.0)
    assert head.mode == "zeroshot"
    assert np.allclose(head.w, w0)


def test_trained_head_separates_and_reports_cv():
    X, y = _data(15, 25)
    # a deliberately weak/misaligned prior: training must fix it
    w0 = np.zeros(X.shape[1], np.float32)
    w0[1] = 5
    head = train_head(X, y, w0, 0.0, version=3)
    assert head.mode == "trained"
    assert head.version == 3
    assert head.metrics["cv"]["f1"] > 0.9
    acc = ((head.proba(X) >= head.threshold).astype(int) == y).mean()
    assert acc > 0.95


def test_oneclass_negatives_stay_below_threshold():
    X, y = _data(0, 20)
    w0 = np.zeros(X.shape[1], np.float32)
    w0[0] = 30  # prior points the right way but its bias is off
    head = train_head(X, y, w0, 5.0)
    assert head.mode == "oneclass_neg"
    assert head.proba(X).max() < 0.5


def test_single_positive_low_data_mode():
    X, y = _data(1, 10)
    w0 = np.zeros(X.shape[1], np.float32)
    w0[0] = 30
    head = train_head(X, y, w0, 0.0)
    assert head.mode == "trained" and head.metrics.get("low_data")
    assert head.proba(X[:1])[0] > 0.5


def test_save_load_roundtrip(tmp_path):
    X, y = _data(6, 6)
    head = train_head(X, y, np.zeros(X.shape[1], np.float32), 0.0, version=2)
    p = tmp_path / "v2.npz"
    head.save(p)
    again = Head.load(p)
    assert again.version == 2 and again.mode == head.mode
    assert np.allclose(again.proba(X), head.proba(X), atol=1e-5)


def test_nonlinear_head_when_one_direction_is_not_enough(tmp_path):
    rng = np.random.default_rng(0)
    d = 16
    # "yes" sits in two opposite clusters, so no single direction separates it from "no"
    c = np.eye(d)[0] * 0.9
    pos = np.concatenate([c + rng.normal(0, 0.05, (60, d)), -c + rng.normal(0, 0.05, (60, d))])
    neg = rng.normal(0, 0.05, (120, d)) + np.eye(d)[1] * 0.9
    X = np.concatenate([pos, neg]).astype(np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    y = np.array([1] * 120 + [0] * 120)
    head = train_head(X, y, np.eye(d, dtype=np.float32)[0] * 5)
    assert head.rff and head.metrics["nonlinear"]
    assert head.metrics["cv"]["accuracy"] > 0.95
    head.save(tmp_path / "v1.npz")
    again = Head.load(tmp_path / "v1.npz")
    assert np.allclose(again.proba(X), head.proba(X), atol=1e-5)
