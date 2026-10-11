"""Metric watches: compile, runtime buckets, storage roll-up and the API summary."""

import time

import numpy as np

from vigil.api import _metric_value, _sanitize
from vigil.brain.heuristic import HeuristicBrain
from vigil.db import DB
from vigil.engine.runtime import METRIC_BUCKET_S, WatchRuntime
from vigil.learning.heads import Head


def _spec(q: str):
    return _sanitize(HeuristicBrain().compile(q, None, "cam"))


def test_compile_metric_requests():
    s = _spec("Count walk-ins at the front door")
    assert s.metric and s.metric.kind == "crossings" and s.crossing == "down" and not s.alerts
    s = _spec("How many people are waiting in line?")
    assert s.metric and s.metric.kind == "count" and s.targets == ["person"] and not s.alerts
    s = _spec("What % of the time is the blue bin empty?")
    assert s.metric and s.metric.kind == "occupancy" and s.kind == "state"
    s = _spec("Track how many cars are in the lot and text me if more than 20")
    assert s.metric and s.metric.kind == "count" and s.alerts
    assert _spec("Text me when a package is left on the front step").metric is None


def test_runtime_buckets_and_storage(tmp_path):
    spec = _spec("What % of the time is the blue bin empty?").model_dump()
    head = Head(np.zeros(4, np.float32), 0.0, 0.5, "zeroshot")
    rt = WatchRuntime({"id": 1, "camera_id": 1, "name": "bin", "status": "active", "spec": spec}, head)
    t0 = 1_000_000 * METRIC_BUCKET_S
    for i in range(int(2 * METRIC_BUCKET_S)):  # one check a second for two minutes
        rt._record(t0 + i, cond=i % 4 == 0)  # YES a quarter of the time
    rows = rt.pop_metric_rows()
    assert len(rows) == 1 and rows[0]["n"] == METRIC_BUCKET_S and rt.live_bucket()["n"] == METRIC_BUCKET_S
    db = DB(tmp_path / "v.db")
    cam = db.add_camera("c", "demo", "shelf")
    w = db.add_watch(cam["id"], "bin", "q", spec)
    for r in rows + [rt.live_bucket()]:
        r["watch_id"] = w["id"]
    db.add_metric_rows(rows + [rt.live_bucket()])
    b = db.metric_buckets(w["id"], t0 - 1, 3600)
    assert len(b) == 1 and _metric_value("occupancy", b[0]) == 25.0
    db.add_metric_rows([{**rows[0]}])  # a restart re-sending the same minute adds up instead of failing
    assert db.metric_buckets(w["id"], t0 - 1, 3600)[0]["n"] == 3 * METRIC_BUCKET_S


def test_metric_values():
    assert _metric_value("count", {"sum": 30, "n": 10, "max": 6}) == 3.0
    assert _metric_value("crossings", {"sum": 7, "n": 60, "max": 2}) == 7
    assert _metric_value("occupancy", {"sum": 15, "n": 60, "max": 1}) == 25.0
