from types import SimpleNamespace

import numpy as np

from vigil.config import settings
from vigil.db import DB
from vigil.engine.actions import ActionRunner, normalize_handle, parse_reply
from vigil.learning.store import ModelStore
from vigil.schemas import Action

EVENT = {"id": 7, "ts": 1_760_000_000.0, "message": "Staging lane 3 is empty", "verdict": "Lane 3 has no pallets."}
WATCH = {"id": 1, "name": "Lane 3 empty", "prompt": "Tell me when lane 3 is empty"}
CAMERA = {"id": 1, "name": "Dock"}


class FakeHTTP:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None, headers=None, content=None):
        self.posts.append({"url": url, "json": json, "headers": headers or {}})
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"id": "901"}, status_code=200)


def runner(tmp_path, integrations):
    db = DB(tmp_path / "v.db")
    db.set_kv("integrations", integrations)
    r = ActionRunner(db)
    r.http = FakeHTTP()
    return db, r


def test_parse_reply_and_handles():
    assert parse_reply("Yes!") == "correct"
    assert parse_reply("yep, that's lane 3") == "correct"
    assert parse_reply("no") == "false_alarm"
    assert parse_reply("Wrong lane") == "false_alarm"
    assert parse_reply("who is this?") is None
    assert normalize_handle("+1 (415) 555-0100") == normalize_handle("4155550100") == "4155550100"
    assert normalize_handle("Sam@Example.com") == "sam@example.com"


def test_imessage_goes_through_bridge_and_can_be_answered(tmp_path):
    db, r = runner(tmp_path, {"imessage_to": "+1 415 555 0100", "imessage_bridge": "http://bridge:1"})
    res = r.run([Action(type="imessage")], EVENT, WATCH, CAMERA, None)
    assert res == [{"action": "imessage", "ok": True, "to": "+1 415 555 0100"}]
    call = r.http.posts[0]
    assert call["url"] == "http://bridge:1/send"
    assert "Reply YES or NO" in call["json"]["text"]
    assert db.latest_outbox("4155550100")["event_id"] == 7


def test_hubspot_ticket_and_task(tmp_path):
    _, r = runner(tmp_path, {"hubspot_token": "pat-123"})
    res = r.run([Action(type="hubspot", object="ticket"), Action(type="hubspot", object="task", note="Call the carrier")],
                EVENT, WATCH, CAMERA, None)
    assert [x["ok"] for x in res] == [True, True]
    ticket, task = r.http.posts
    assert ticket["url"].endswith("/crm/v3/objects/tickets")
    assert ticket["headers"]["Authorization"] == "Bearer pat-123"
    assert ticket["json"]["properties"]["subject"].startswith("Lane 3 empty")
    assert task["url"].endswith("/crm/v3/objects/tasks")
    assert "Call the carrier" in task["json"]["properties"]["hs_task_body"]


def test_missing_setup_fails_softly(tmp_path):
    _, r = runner(tmp_path, {})
    res = r.run([Action(type="hubspot"), Action(type="imessage")], EVENT, WATCH, CAMERA, None)
    assert [x["ok"] for x in res] == [False, False]
    assert "HubSpot" in res[0]["error"]


def test_never_seen_events_ignore_past_footage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db = DB(tmp_path / "v.db")
    cam = db.add_camera("Dock", "file", "x")
    spec = {"name": "Lane", "question": "Is lane 3 empty?", "kind": "state",
            "positive_label": "an empty lane", "negative_label": "a lane with pallets"}
    wid = db.add_watch(cam["id"], "Lane", "Tell me when lane 3 is empty", spec)["id"]
    d = 8
    w0 = np.eye(d, dtype=np.float32)[0] * 10
    emb = SimpleNamespace(zero_shot_direction=lambda p, n: (w0, 0.0))
    store = ModelStore(db, lambda: emb)
    rng = np.random.default_rng(0)
    for _ in range(12):  # building collected footage where the lane was always full
        db.add_sample(wid, "s.jpg", rng.normal(size=d).astype(np.float32), label=0, source="vlm", origin="history")
    head = store.retrain(wid)
    assert head.metrics["n"] == 0 and head.mode == "zeroshot"  # still running on the words alone
    db.add_sample(wid, "s.jpg", rng.normal(size=d).astype(np.float32), label=0, source="user", origin="feedback")
    head = store.retrain(wid)
    assert head.metrics["n"] == 1  # a correction on a live alert does count
    db.add_sample(wid, "s.jpg", w0 / 10, label=1, source="user", origin="feedback")
    head = store.retrain(wid)
    assert head.metrics["n"] == 14  # once it has really happened, all footage is fair game


def test_feedback_is_asked_only_occasionally(tmp_path):
    db, r = runner(tmp_path, {"imessage_to": "+14155550100"})
    cam = db.add_camera("Dock", "demo", "shelf")
    w = db.add_watch(cam["id"], "Lane 3 empty", "q", {})
    watch = {**WATCH, "id": w["id"]}
    for i in range(5):  # a new watch asks after every alert until it has 5 answers
        eid = db.add_event(w["id"], cam["id"], 1_760_000_000.0 + i, 0.9, "empty", {})
        assert r.should_ask({"id": eid, "ts": 1_760_000_000.0 + i}, watch)
        db.update_event(eid, feedback="correct")
    t = 1_760_000_100.0
    assert not r.should_ask({"id": 99, "ts": t}, watch)  # sure, answered enough, asked a minute ago
    assert r.should_ask({"id": 99, "ts": t, "detail": {"verify_confidence": 0.6}}, watch)  # double-check unsure
    assert r.should_ask({"id": 99, "ts": t + 24 * 3600}, watch)  # daily spot check
    assert not r.should_ask({"id": 99, "ts": t + 24 * 3600 + 60}, watch)
