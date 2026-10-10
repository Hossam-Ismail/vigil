"""HTTP + WebSocket API, and static hosting for the built web app."""

from __future__ import annotations

import asyncio
import logging
import platform
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, brain as brains
from .brain import BrainError, get_brain
from .brain.heuristic import HeuristicBrain
from .bus import bus
from .cameras import CameraHub
from .cameras.discovery import RTSP_TEMPLATES, discover
from .config import settings
from .db import DB
from .engine.core import Engine
from .engine.actions import ActionRunner, normalize_handle, parse_reply
from .engine.events import EventManager
from .engine.notify import Notifier
from .learning.active import ActiveLearner
from .learning.locate import propose_zone
from .learning.store import ModelStore, prior_labels
from .perception.embedder import get_embedder
from .perception.geometry import zone_crop
from .schemas import (
    CameraIn,
    CameraPatch,
    FeedbackIn,
    SampleLabelIn,
    SettingsIn,
    WatchDraftIn,
    WatchPatch,
    WatchSpec,
)

log = logging.getLogger("vigil.api")

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


class App:
    """Process-wide singletons."""

    def __init__(self) -> None:
        settings.ensure_dirs()
        self.db = DB(settings.db_path)
        self.hub = CameraHub()
        self.store = ModelStore(self.db, get_embedder)
        self.notifier = Notifier(self.db, self.db.get_kv("public_url", f"http://{settings.host}:{settings.port}"))
        self.actions = ActionRunner(self.db)
        self.events = EventManager(self.db, self.hub, self.store, self.notifier, self.actions)
        self.learner = ActiveLearner(self.db, self.store)
        self.engine = Engine(self.db, self.hub, self.store, self.events, self.learner)
        self.models_ready = threading.Event()

    def boot(self) -> None:
        if not self.db.cameras() and not self.db.get_kv("seeded"):
            self.db.add_camera("Aisle A · Parts shelf", "demo", "shelf")
            self.db.set_kv("seeded", True)
        if self.db.get_kv("channels") is None:
            chans = [{"id": "desktop", "type": "desktop", "target": "", "enabled": False, "min_severity": "info"}] \
                if platform.system() == "Darwin" else []
            self.db.set_kv("channels", chans)
        pref = self.db.get_kv("brain")
        if pref:
            try:
                brains.set_preference(pref)
            except ValueError:
                pass
        for cam in self.db.cameras():
            self.hub.start(cam)
        threading.Thread(target=self._warm, daemon=True).start()
        self.engine.load_all()
        self.learner.start()

    def _warm(self) -> None:
        t = time.time()
        get_embedder()
        self.models_ready.set()
        log.info("embedder ready in %.1fs", time.time() - t)

    def shutdown(self) -> None:
        self.learner.stop()
        self.engine.shutdown()
        self.hub.shutdown()


app_state: App | None = None


def S() -> App:
    assert app_state is not None
    return app_state


@asynccontextmanager
async def lifespan(_: FastAPI):
    global app_state
    bus.bind(asyncio.get_running_loop())
    app_state = App()
    await asyncio.to_thread(app_state.boot)
    yield
    app_state.shutdown()


app = FastAPI(title="Vigil", version=__version__, lifespan=lifespan)


# ---------------------------------------------------------------------------------------------
# helpers


def _camera_out(cam: dict) -> dict:
    rt = S().hub.get(cam["id"])
    info = rt.info() if rt else {"status": "stopped"}
    watches = S().db.watches(cam["id"])
    return {**cam, **info, "id": cam["id"], "name": cam["name"], "kind": cam["kind"],
            "watch_count": len(watches), "active_watches": sum(1 for w in watches if w["status"] == "active")}


def _watch_out(w: dict, *, spark: bool = False) -> dict:
    rt = S().engine.runtimes.get(w["id"])
    cam = S().db.camera(w["camera_id"])
    counts = S().db.one(
        "SELECT COUNT(*) AS n, SUM(label=1) AS pos, SUM(label=0) AS neg, SUM(label IS NULL) AS unl "
        "FROM samples WHERE watch_id=?", (w["id"],))
    last_event = S().db.one("SELECT ts, status FROM events WHERE watch_id=? ORDER BY ts DESC LIMIT 1", (w["id"],))
    n_events = S().db.one("SELECT COUNT(*) AS n FROM events WHERE watch_id=? AND status != 'suppressed'", (w["id"],))
    return {
        **w,
        "camera_name": cam["name"] if cam else "",
        "runtime": rt.snapshot(spark=spark) if rt else None,
        "samples": {"total": counts["n"] or 0, "yes": counts["pos"] or 0, "no": counts["neg"] or 0,
                    "unlabeled": counts["unl"] or 0},
        "last_event": last_event,
        "event_count": n_events["n"] if n_events else 0,
    }


def _cam_or_404(cid: int):
    cam = S().db.camera(cid)
    if not cam:
        raise HTTPException(404, "camera not found")
    return cam


def _watch_or_404(wid: int) -> dict:
    w = S().db.watch(wid)
    if not w:
        raise HTTPException(404, "watch not found")
    return w


def _latest_frame(cid: int, wait: float = 4.0) -> np.ndarray:
    rt = S().hub.get(cid)
    if not rt:
        raise HTTPException(409, "camera is not running")
    deadline = time.time() + wait
    while time.time() < deadline:
        frame, _, _ = rt.snapshot()
        if frame is not None:
            return frame.copy()
        time.sleep(0.2)
    raise HTTPException(409, f"camera has no frames yet ({rt.status}{': ' + rt.error if rt.error else ''})")


# ---------------------------------------------------------------------------------------------
# system


@app.get("/api/health")
def health() -> dict:
    b = get_brain()
    return {
        "version": __version__,
        "device": settings.device,
        "models_ready": S().models_ready.is_set(),
        "brain": {"name": b.name, "label": b.label, "preference": brains.preference()},
        "brains": brains.options(),
        "cameras": len(S().hub.all()),
        "watches_active": sum(1 for rt in S().engine.runtimes.values() if not rt.paused),
        "embed_model": settings.embed_model,
        "detectors": {"coco": f"RF-DETR {settings.coco_model}", "open_vocab": settings.open_vocab_model},
    }


def _integrations_public() -> dict:
    integ = dict(S().db.get_kv("integrations", {}) or {})
    tok = integ.pop("hubspot_token", "")
    integ["hubspot_token_set"] = bool(tok)
    integ["hubspot_token_hint"] = ("…" + tok[-4:]) if tok else ""
    return integ


@app.get("/api/settings")
def get_settings() -> dict:
    return {
        "integrations": _integrations_public(),
        "channels": S().db.get_kv("channels", []),
        "brain": brains.preference(),
        "brains": brains.options(),
        "public_url": S().notifier.public_url,
        "active_learning_per_hour": settings.active_learning_per_hour,
    }


@app.put("/api/settings")
def put_settings(body: SettingsIn) -> dict:
    if body.channels is not None:
        S().db.set_kv("channels", [c.model_dump() for c in body.channels])
    if body.integrations is not None:
        integ = dict(S().db.get_kv("integrations", {}) or {})
        for k in ("imessage_to", "imessage_bridge", "hubspot_token", "public_url"):
            if k in body.integrations and body.integrations[k] is not None:
                v = str(body.integrations[k]).strip()
                if v:
                    integ[k] = v
                else:
                    integ.pop(k, None)
        S().db.set_kv("integrations", integ)
    if body.brain is not None:
        try:
            brains.set_preference(body.brain)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        S().db.set_kv("brain", body.brain)
    return get_settings()


@app.post("/api/settings/test-notify")
def test_notify(channel_id: str = Body(..., embed=True)) -> dict:
    fake_event = {"id": 0, "ts": time.time(), "message": "Test alert from Vigil", "verdict": "", "status": "confirmed"}
    fake_watch = {"id": 0, "name": "Test", "prompt": "test", "spec": {"severity": "info"}}
    fake_cam = {"id": 0, "name": "Vigil"}
    res = S().notifier.send(fake_event, fake_watch, fake_cam, None, only=channel_id)
    if not res:
        raise HTTPException(404, "channel not found")
    return res[0]


@app.get("/api/integrations/status")
def integrations_status() -> dict:
    return S().actions.status()


@app.post("/api/actions/test")
def test_action(action: dict = Body(..., embed=True)) -> dict:
    """Run one action against a sample event so people can check their iMessage / HubSpot setup."""
    from .schemas import Action

    a = Action.model_validate(action)
    fake_event = {"id": 0, "ts": time.time(), "message": "Test from Vigil: this is what an alert looks like",
                  "verdict": "", "status": "confirmed"}
    fake_watch = {"id": 0, "name": "Test watch", "prompt": "test", "spec": {"severity": "info"}}
    res = S().actions.run([a], fake_event, fake_watch, {"id": 0, "name": "Vigil"}, None)
    return res[0]


@app.post("/api/imessage/inbound")
def imessage_inbound(sender: str = Body(..., alias="from"), text: str = Body(...)) -> dict:
    """A reply arrived through the Photon iMessage bridge. "yes"/"no" become training labels."""
    handle = normalize_handle(sender)
    row = S().db.latest_outbox(handle)
    if not row:
        return {"ok": False, "reason": "no recent alert sent to this number"}
    verdict = parse_reply(text)
    if verdict is None:
        S().actions.reply(sender, "Reply YES if the alert was right or NO if it wasn't, and Vigil will learn from it.")
        return {"ok": False, "reason": "not a yes/no answer"}
    ev = S().events.feedback(row["event_id"], verdict)
    S().db.execute("UPDATE outbox SET answered=1 WHERE id=?", (row["id"],))
    watch = S().db.watch(ev["watch_id"]) if ev else None
    name = watch["name"] if watch else "this watch"
    S().actions.reply(sender, (f"Thanks! Marked as right. “{name}” just learned from it." if verdict == "correct"
                               else f"Got it, false alarm. “{name}” just learned from it and will be more careful."))
    return {"ok": True, "event_id": row["event_id"], "feedback": verdict}


# ---------------------------------------------------------------------------------------------
# cameras


@app.get("/api/cameras")
def list_cameras() -> list[dict]:
    return [_camera_out(c) for c in S().db.cameras()]


@app.post("/api/cameras")
def add_camera(body: CameraIn) -> dict:
    url = body.url.strip()
    if body.kind in ("rtsp", "http") and "://" not in url:
        raise HTTPException(400, "stream URL must include a scheme, e.g. rtsp://")
    cam = S().db.add_camera(body.name.strip() or "Camera", body.kind, url, body.enabled)
    S().hub.start(cam)
    return _camera_out(cam)


@app.patch("/api/cameras/{cid}")
def patch_camera(cid: int, body: CameraPatch) -> dict:
    _cam_or_404(cid)
    fields = body.model_dump(exclude_none=True)
    cam = S().db.update_camera(cid, **fields)
    if {"url", "enabled"} & fields.keys():
        S().hub.start(cam)
        S().engine.restart_analyzer(cid)
    return _camera_out(cam)


@app.delete("/api/cameras/{cid}")
def delete_camera(cid: int) -> dict:
    _cam_or_404(cid)
    for w in S().db.watches(cid):
        S().engine.deactivate(w["id"])
    S().engine.stop_analyzer(cid)
    S().hub.stop(cid)
    S().db.delete_camera(cid)
    return {"ok": True}


@app.get("/api/cameras/{cid}/snapshot.jpg")
def snapshot(cid: int) -> Response:
    rt = S().hub.get(cid)
    data = rt.jpeg(85) if rt else None
    if not data:
        raise HTTPException(404, "no frame yet")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/cameras/{cid}/stream.mjpg")
async def stream(cid: int, fps: float = 8.0) -> StreamingResponse:
    rt = S().hub.get(cid)
    if not rt:
        raise HTTPException(404, "camera not running")
    period = 1.0 / max(1.0, min(fps, 20.0))

    async def gen():
        last = -1
        while True:
            _, _, no = rt.snapshot()
            if no != last:
                data = await asyncio.to_thread(rt.jpeg, 78)
                if data:
                    last = no
                    yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(data)).encode() + \
                        b"\r\n\r\n" + data + b"\r\n"
            await asyncio.sleep(period)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


@app.websocket("/api/cameras/{cid}/push")
async def push(ws: WebSocket, cid: int) -> None:
    await ws.accept()
    rt = S().hub.get(cid)
    if not rt or not rt.push_source:
        await ws.close(code=4404)
        return
    try:
        while True:
            data = await ws.receive_bytes()
            await asyncio.to_thread(rt.push_source.push_jpeg, data)
    except WebSocketDisconnect:
        pass


@app.get("/api/cameras/{cid}/perception")
def perception(cid: int) -> dict:
    return S().engine.perception(cid)


@app.post("/api/cameras/{cid}/demo")
def demo_control(cid: int, bin: str | None = Body(None), level: float | None = Body(None),
                 auto: bool | None = Body(None)) -> dict:
    rt = S().hub.get(cid)
    if not rt or not rt.scene:
        raise HTTPException(400, "not a demo shelf camera")
    if auto is not None:
        rt.scene.set_auto(auto)
    if bin is not None and level is not None:
        rt.scene.set_level(bin, level)
    return rt.scene.state()


@app.get("/api/discover")
def discover_cameras(timeout: float = 3.0) -> dict:
    return {"devices": discover(timeout=min(timeout, 8.0)), "templates": RTSP_TEMPLATES}


# ---------------------------------------------------------------------------------------------
# watches


def _pick(value, allowed: dict[str, str], default: str) -> str:
    v = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return allowed.get(v, default)


def _num(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sanitize(raw: dict) -> WatchSpec:
    """Coerce whatever the brain produced into a valid spec (local models ignore enum constraints)."""
    fields = set(WatchSpec.model_fields)
    raw = {k: v for k, v in dict(raw).items() if k in fields}
    for k in ("name", "summary", "question", "positive_label", "negative_label", "target_question", "locate",
              "locate_noun", "alert_message"):
        v = raw.get(k)
        raw[k] = "" if v is None else str(v).strip()
    raw["kind"] = _pick(raw.get("kind"), {"state": "state", "presence": "presence", "count": "count",
                                          "detection": "presence", "object": "presence", "counting": "count"}, "state")
    raw["severity"] = _pick(raw.get("severity"), {"info": "info", "low": "info", "warning": "warning",
                                                  "medium": "warning", "moderate": "warning", "high": "critical",
                                                  "critical": "critical", "urgent": "critical"}, "warning")
    raw["trigger"] = _pick(raw.get("trigger"), {"rising": "rising", "once": "rising", "sustained": "sustained",
                                                "repeat": "sustained", "per_object": "per_object",
                                                "each": "per_object", "each_object": "per_object"}, "rising")
    raw["crossing"] = _pick(raw.get("crossing"), {k: k for k in ("none", "any", "down", "up", "left", "right")},
                            "none")
    op = str(raw.get("count_op") or ">=").strip()
    raw["count_op"] = op if op in (">=", ">", "<=", "<", "==") else ">="
    raw["count_value"] = int(_num(raw.get("count_value"), 1))
    raw["verify_with_vlm"] = str(raw.get("verify_with_vlm", True)).lower() not in ("false", "0", "no", "none")
    acts = []
    for a in raw.get("actions") or []:
        if isinstance(a, dict) and a.get("type") in ("imessage", "hubspot", "webhook", "slack", "ntfy"):
            obj = str(a.get("object") or "").lower()
            acts.append({"type": a["type"], "target": "", "object": obj if obj in ("ticket", "task", "note") else "",
                         "note": str(a.get("note") or "")[:200]})
    raw["actions"] = acts[:4]
    for k in ("targets", "clarifications"):
        v = raw.get(k) or []
        raw[k] = [v] if isinstance(v, str) else [str(x) for x in v if x]
    if not raw["question"]:
        raw["question"] = raw["positive_label"] or raw["name"] or "Is the condition true?"
    if not raw["positive_label"]:
        raw["positive_label"] = raw["question"]
    if not raw["negative_label"]:
        raw["negative_label"] = "a normal scene"
    raw["min_duration_s"] = float(min(max(_num(raw.get("min_duration_s"), 2), 0), 3600))
    raw["cooldown_s"] = float(min(max(_num(raw.get("cooldown_s"), 300), 10), 86400))
    raw["targets"] = [t.strip().lower() for t in raw["targets"] if t.strip()][:3]
    if raw.get("kind") in ("presence", "count") and not raw["targets"]:
        raw["targets"] = ["person"]
    if raw.get("kind") == "state":
        raw["targets"] = []
        raw["check_interval_s"] = 1.0
    else:
        raw["check_interval_s"] = 0.0
    if raw.get("trigger") == "per_object" and raw.get("kind") != "presence":
        raw["trigger"] = "rising"
    if raw["kind"] != "presence":
        raw["crossing"] = "none"
    elif raw["crossing"] != "none":
        raw["trigger"] = "per_object"
        raw["min_duration_s"] = 0.0
    raw["name"] = (raw.get("name") or "Watch")[:60]
    return WatchSpec.model_validate(raw)


@app.post("/api/watches/draft")
def draft_watch(body: WatchDraftIn) -> dict:
    cam = _cam_or_404(body.camera_id)
    prompt = body.prompt.strip()
    if len(prompt) < 4:
        raise HTTPException(400, "describe what to watch for")
    frame = _latest_frame(body.camera_id)
    brain = get_brain()
    warnings: list[str] = []
    t = time.time()
    try:
        raw = brain.compile(prompt, frame, cam["name"])
    except BrainError as exc:
        warnings.append(f"{brain.label} unavailable ({exc}); used the built-in parser")
        brain = HeuristicBrain()
        raw = brain.compile(prompt, frame, cam["name"])
    compile_ms = int((time.time() - t) * 1000)
    spec = _sanitize(raw)
    t = time.time()
    try:
        zone, zinfo = propose_zone(frame, spec, brain)
    except Exception as exc:  # noqa: BLE001
        log.exception("zone proposal failed")
        zone, zinfo = None, {"method": "error", "error": str(exc)}
    if spec.crossing != "none":
        # tripwire across the located region (or the middle of the frame), perpendicular to the motion
        x1, y1, x2, y2 = zone.bbox() if zone else (0.0, 0.0, 1.0, 1.0)
        if spec.crossing in ("left", "right"):
            xm = (x1 + x2) / 2
            spec.line = [(xm, y1), (xm, y2)]
        else:
            ym = y1 + (y2 - y1) * (0.65 if zone else 0.5)
            spec.line = [(x1, ym), (x2, ym)]
        zone = None
    spec.zone = zone
    zinfo["ms"] = int((time.time() - t) * 1000)
    w = S().db.add_watch(cam["id"], spec.name, prompt, spec.model_dump(), status="draft")
    S().db.update_watch(w["id"], metrics={"compile": {"brain": brain.label, "ms": compile_ms, "zone": zinfo,
                                                      "warnings": warnings}})
    return {**_watch_out(S().db.watch(w["id"])), "proposal": zinfo, "warnings": warnings}


@app.get("/api/watches")
def list_watches(camera_id: int | None = None) -> list[dict]:
    return [_watch_out(w) for w in S().db.watches(camera_id)]


@app.get("/api/watches/{wid}")
def get_watch(wid: int) -> dict:
    return _watch_out(_watch_or_404(wid), spark=True)


@app.patch("/api/watches/{wid}")
def patch_watch(wid: int, body: WatchPatch) -> dict:
    w = _watch_or_404(wid)
    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name[:60]
    if body.spec is not None:
        old = WatchSpec.model_validate(w["spec"])
        new = body.spec
        fields["spec"] = new.model_dump()
        if body.name is None:
            fields["name"] = new.name[:60]
        relabel = (old.zone != new.zone and new.kind == "state") or \
            (old.positive_label, old.negative_label) != (new.positive_label, new.negative_label)
        if relabel and w["status"] in ("active", "paused"):
            fields["status_detail"] = "spec changed: rebuild recommended so training data matches"
    S().db.update_watch(wid, **fields)
    if "spec" in fields:
        threading.Thread(target=lambda: (S().store.retrain(wid, "spec edited"), S().engine.reload(wid)),
                         daemon=True).start()
    return _watch_out(S().db.watch(wid))


@app.post("/api/watches/{wid}/build")
def build_watch(wid: int, collect_seconds: float | None = Body(None, embed=True)) -> dict:
    _watch_or_404(wid)
    try:
        S().engine.start_build(wid, collect_seconds)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _watch_out(S().db.update_watch(wid, status="building", status_detail="starting"))


@app.post("/api/watches/{wid}/pause")
def pause_watch(wid: int) -> dict:
    _watch_or_404(wid)
    S().db.update_watch(wid, status="paused")
    S().engine.reload(wid)
    return _watch_out(S().db.watch(wid))


@app.post("/api/watches/{wid}/resume")
def resume_watch(wid: int) -> dict:
    w = _watch_or_404(wid)
    if w["status"] not in ("paused", "active"):
        raise HTTPException(409, "build the watch first")
    S().db.update_watch(wid, status="active")
    S().engine.reload(wid)
    return _watch_out(S().db.watch(wid))


@app.delete("/api/watches/{wid}")
def delete_watch(wid: int) -> dict:
    _watch_or_404(wid)
    b = S().engine.builds.get(wid)
    if b:
        b.cancelled.set()
    S().engine.deactivate(wid)
    S().db.delete_watch(wid)
    return {"ok": True}


@app.post("/api/watches/{wid}/retrain")
def retrain_watch(wid: int) -> dict:
    _watch_or_404(wid)
    head = S().store.retrain(wid, reason="manual")
    return {"metrics": head.metrics if head else {}}


@app.get("/api/watches/{wid}/samples")
def list_samples(wid: int) -> list[dict]:
    _watch_or_404(wid)
    return S().db.samples(wid)


@app.post("/api/watches/{wid}/teach")
def teach(wid: int, label: int = Body(..., embed=True)) -> dict:
    """Label what the camera sees right now ("this is what empty looks like")."""
    w = _watch_or_404(wid)
    spec = WatchSpec.model_validate(w["spec"])
    frame = _latest_frame(w["camera_id"])
    added = []
    if spec.kind == "state":
        img = zone_crop(frame, spec.zone)
        added.append(S().store.add_sample(wid, img, label=int(bool(label)), source="user", confidence=1.0,
                                          reason="taught from live view", origin="teach"))
    else:
        rt = S().engine.runtimes.get(wid)
        from .perception.geometry import crop as crop_box

        boxes = [t.box for t in (rt.tracks if rt else []) if t.misses == 0]
        if not boxes:
            raise HTTPException(409, "no tracked objects in view to label")
        for b in boxes:
            added.append(S().store.add_sample(wid, crop_box(frame, b, pad=0.12), label=int(bool(label)),
                                              source="user", confidence=1.0, reason="taught from live view",
                                              origin="teach"))
    head = S().store.retrain(wid, reason="taught from live view")
    return {"added": added, "metrics": head.metrics if head else {}}


@app.patch("/api/samples/{sid}")
def label_sample(sid: int, body: SampleLabelIn) -> dict:
    s = S().db.sample(sid)
    if not s:
        raise HTTPException(404, "sample not found")
    s = S().db.update_sample(sid, label=body.label, source="user", confidence=1.0)
    threading.Thread(target=S().store.retrain, args=(s["watch_id"], "sample relabeled"), daemon=True).start()
    return s


@app.delete("/api/samples/{sid}")
def delete_sample(sid: int) -> dict:
    s = S().db.sample(sid)
    if not s:
        raise HTTPException(404, "sample not found")
    S().db.delete_sample(sid)
    threading.Thread(target=S().store.retrain, args=(s["watch_id"], "sample removed"), daemon=True).start()
    return {"ok": True}


# ---------------------------------------------------------------------------------------------
# events


@app.get("/api/events")
def list_events(watch_id: int | None = None, camera_id: int | None = None, limit: int = Query(100, le=500),
                include_suppressed: bool = True) -> list[dict]:
    evs = S().db.events(watch_id=watch_id, camera_id=camera_id, limit=limit, include_suppressed=include_suppressed)
    return [S().events._public(e) for e in evs]


@app.get("/api/events/{eid}")
def get_event(eid: int) -> dict:
    ev = S().db.event(eid)
    if not ev:
        raise HTTPException(404, "event not found")
    return S().events._public(ev)


@app.post("/api/events/{eid}/feedback")
def event_feedback(eid: int, body: FeedbackIn) -> dict:
    ev = S().events.feedback(eid, body.feedback)
    if not ev:
        raise HTTPException(404, "event not found")
    return ev


# ---------------------------------------------------------------------------------------------
# live updates


@app.websocket("/api/live")
async def live(ws: WebSocket) -> None:
    await ws.accept()
    q = bus.subscribe()
    try:
        await ws.send_json({"type": "hello", "data": {"version": __version__}, "ts": time.time()})
        while True:
            msg = await q.get()
            await ws.send_json(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(q)


# ---------------------------------------------------------------------------------------------
# media + web app

app.mount("/media", StaticFiles(directory=str(settings.data_dir / "media"), check_dir=False), name="media")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith(("api/", "media/")):
        return JSONResponse({"detail": "not found"}, status_code=404)
    if WEB_DIST.exists():
        f = WEB_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
    return JSONResponse({"detail": "web app not built; run `npm run build` in web/ or use the Vite dev server"})
