import numpy as np

from vigil.engine.runtime import AlertMachine, Vote, WatchRuntime
from vigil.learning.heads import Head
from vigil.perception.detector import Detection
from vigil.perception.tracker import IoUTracker
from vigil.schemas import WatchSpec, Zone


def test_vote_hysteresis():
    v = Vote(window=5, need=3)
    states = [v.update(on, off) for on, off in [(1, 0), (0, 0), (1, 0), (1, 0), (0, 1), (0, 1), (0, 1)]]
    assert states == [False, False, False, True, True, True, False]


def test_alert_machine_dwell_and_cooldown():
    m = AlertMachine(min_duration_s=5, cooldown_s=60, trigger="rising")
    fired = [t for t in range(0, 20) if m.step(float(t), True)]
    assert fired == [5]
    assert not m.step(21, False)
    # condition returns within cooldown: no new alert
    assert not any(m.step(float(t), True) for t in range(22, 40))
    m.step(41, False)
    fired = [t for t in range(70, 90) if m.step(float(t), True)]
    assert fired == [75]


def test_alert_machine_sustained_repeats():
    m = AlertMachine(min_duration_s=0, cooldown_s=10, trigger="sustained")
    fired = [t for t in range(0, 35) if m.step(float(t), True)]
    assert fired == [0, 10, 20, 30]


def _presence_rt(trigger="per_object", zone=None, cooldown=30.0):
    spec = WatchSpec(
        name="Person enters", kind="presence", question="Is a person in the doorway?",
        positive_label="a person", negative_label="an empty doorway", targets=["person"],
        trigger=trigger, min_duration_s=1.0, cooldown_s=cooldown, zone=zone,
    )
    watch = {"id": 1, "camera_id": 1, "name": spec.name, "spec": spec.model_dump(), "status": "active"}
    head = Head(np.zeros(4, np.float32), 0.0, 0.5, "zeroshot")
    return WatchRuntime(watch, head)


def test_per_object_fires_once_per_person():
    rt = _presence_rt()
    box = (0.4, 0.3, 0.5, 0.9)
    fired = []
    for i in range(20):
        t = float(i) * 0.25
        trig = rt.step_objects(t, [Detection("person", 0.9, box)], None)
        if trig:
            fired.append(t)
    assert len(fired) == 1 and fired[0] >= 1.0


def test_zone_excludes_outside_objects():
    door = Zone.from_box(0.0, 0.0, 0.3, 1.0)
    rt = _presence_rt(zone=door)
    outside = (0.6, 0.3, 0.7, 0.9)
    assert not any(rt.step_objects(i * 0.25, [Detection("person", 0.9, outside)], None) for i in range(20))
    rt2 = _presence_rt(zone=door)
    inside = (0.1, 0.3, 0.2, 0.9)
    assert any(rt2.step_objects(i * 0.25, [Detection("person", 0.9, inside)], None) for i in range(20))


def test_tracker_keeps_identity():
    tr = IoUTracker()
    ids = set()
    for i in range(10):
        x = 0.1 + i * 0.01
        tracks = tr.update(float(i), [("person", (x, 0.2, x + 0.1, 0.8), 0.9)])
        ids |= {t.id for t in tracks}
    assert len(ids) == 1


def _crossing_rt(direction):
    spec = WatchSpec(
        name="Enters", kind="presence", question="Is someone entering?", positive_label="a person",
        negative_label="an empty background", targets=["person"], trigger="per_object", min_duration_s=0,
        cooldown_s=0.1, line=[(0.0, 0.5), (1.0, 0.5)], crossing=direction,
    )
    watch = {"id": 7, "camera_id": 1, "name": spec.name, "spec": spec.model_dump(), "status": "active"}
    return WatchRuntime(watch, Head(np.zeros(4, np.float32), 0.0, 0.5, "zeroshot"))


def _walk(rt, ys):
    fired = 0
    for i, y in enumerate(ys):
        box = (0.45, y - 0.2, 0.52, y)  # feet at y
        if rt.step_objects(i * 0.25, [Detection("person", 0.9, box)], None):
            fired += 1
    return fired


def test_tripwire_fires_once_in_the_chosen_direction():
    down = [0.3 + 0.04 * i for i in range(12)]  # feet move from 0.30 to 0.74, crossing y=0.5
    assert _walk(_crossing_rt("down"), down) == 1
    assert _walk(_crossing_rt("down"), list(reversed(down))) == 0
    assert _walk(_crossing_rt("up"), list(reversed(down))) == 1
    assert _walk(_crossing_rt("any"), down) == 1


def test_tracker_follows_fast_walker():
    tr = IoUTracker()
    ids = set()
    for i in range(8):
        x = 0.1 + i * 0.05  # moves a full box width per frame: IoU ~ 0
        ids |= {t.id for t in tr.update(float(i), [("person", (x, 0.2, x + 0.05, 0.6), 0.9)]) if t.misses == 0}
    assert len(ids) == 1
