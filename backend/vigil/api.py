"""HTTP + WebSocket API, and static hosting for the built web app."""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
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
from .engine.bridge import BridgeSupervisor
from . import agent, mail, privacy
from .accounts import Accounts, AuthError, use_key
from .safety import Verdict, check_spec, check_text
from .engine.actions import ActionRunner, normalize_handle
from .engine.events import EventManager
from .engine.notify import Notifier
from .learning.active import ActiveLearner
from .learning.locate import propose_zone
from .learning.store import ModelStore, prior_labels
from .perception.embedder import get_embedder
from .perception.geometry import crop, zone_crop
from .schemas import (
    Action,
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

from .lan import lan_url  # noqa: E402

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
        self.bridge = BridgeSupervisor(self.actions.bridge_url)
        self.janitor = privacy.Janitor(self.db)
        self.accounts = Accounts(self.db)
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
        privacy.apply(self.db.get_kv("privacy"))
        use_key(self.accounts.latest_key())  # the brain uses the most recently checked account key
        pref = self.db.get_kv("brain")
        if pref:
            try:
                brains.set_preference(pref)
            except ValueError:
                pass
        for cam in self.db.cameras():
            self.hub.start(cam)
        threading.Thread(target=self._warm, daemon=True).start()
        from .perception import library

        threading.Thread(target=library.prefetch, name="library-prefetch", daemon=True).start()
        self.engine.load_all()
        self.learner.start()
        self.bridge.start()
        self.janitor.start()

    def _warm(self) -> None:
        t = time.time()
        get_embedder()
        self.models_ready.set()
        log.info("embedder ready in %.1fs", time.time() - t)

    def shutdown(self) -> None:
        self.janitor.stop()
        self.bridge.stop()
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
# accounts: nothing but sign-in and onboarding works until a verified .edu account with a checked AI key exists

COOKIE = "vigil_session"
OPEN_PATHS = ("/api/auth/", "/api/health", "/api/imessage/inbound")
# the "connect a camera" onboarding step needs these before the account is fully set up
CAMERA_STEP_PATHS = ("/api/cameras", "/api/webcams", "/api/discover")


@app.middleware("http")
async def require_account(request: Request, call_next):
    path = request.url.path
    gated = path.startswith("/api/") or path.startswith("/media/")
    if not gated or path.startswith(OPEN_PATHS) or app_state is None:
        return await call_next(request)
    user = S().accounts.session_user(request.cookies.get(COOKIE))
    if user is None:
        return JSONResponse({"detail": {"code": "signin", "message": "Sign in to use Vigil."}}, status_code=401)
    step = S().accounts.next_step(user)
    if step != "ready" and not (step == "camera" and path.startswith(CAMERA_STEP_PATHS)):
        return JSONResponse({"detail": {"code": "onboarding", "step": step,
                                        "message": "Finish setting up your account first."}}, status_code=403)
    request.state.user = user
    return await call_next(request)


def _me(request: Request) -> dict:
    user = S().accounts.session_user(request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Sign in first.")
    return user


def _auth_call(fn, *args):
    try:
        return fn(*args)
    except AuthError as exc:
        raise HTTPException(exc.status, exc.message) from exc


def _with_session(user: dict, extra: dict | None = None) -> JSONResponse:
    resp = JSONResponse({"user": S().accounts.public(user), **(extra or {})})
    resp.set_cookie(COOKIE, S().accounts.new_session(user["id"]), max_age=30 * 86400, httponly=True,
                    samesite="lax", path="/")
    return resp


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict:
    user = S().accounts.session_user(request.cookies.get(COOKIE))
    return {"user": S().accounts.public(user) if user else None, "mail": mail.configured(), "beta": True}


@app.post("/api/auth/signup")
def auth_signup(email: str = Body(...), password: str = Body(...), consent: bool = Body(False)) -> JSONResponse:
    user = _auth_call(S().accounts.sign_up, email, password, consent)
    try:
        sent = S().accounts.send_code(user)
    except AuthError:
        sent = {"delivery": "throttled"}
    except Exception as exc:  # noqa: BLE001
        log.exception("could not send the verification email")
        sent = {"delivery": "failed", "error": str(exc)[:160]}
    return _with_session(user, sent)


@app.post("/api/auth/login")
def auth_login(email: str = Body(...), password: str = Body(...)) -> JSONResponse:
    return _with_session(_auth_call(S().accounts.sign_in, email, password))


@app.post("/api/auth/logout")
def auth_logout(request: Request) -> JSONResponse:
    S().accounts.end_session(request.cookies.get(COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.post("/api/auth/resend")
def auth_resend(request: Request) -> dict:
    user = _me(request)
    if user["verified"]:
        return {"delivery": "already_verified"}
    try:
        return _auth_call(S().accounts.send_code, user)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("could not send the verification email")
        raise HTTPException(502, f"Couldn't send the email: {str(exc)[:160]}") from exc


@app.post("/api/auth/verify")
def auth_verify(request: Request, code: str = Body(..., embed=True)) -> dict:
    return {"user": S().accounts.public(_auth_call(S().accounts.verify, _me(request), code))}


@app.post("/api/auth/profile")
def auth_profile(request: Request, profile: dict = Body(..., embed=True)) -> dict:
    user = _me(request)
    if not user["verified"]:
        raise HTTPException(403, "Verify your email first.")
    return {"user": S().accounts.public(_auth_call(S().accounts.set_profile, user, profile))}


@app.post("/api/auth/ai-key")
def auth_ai_key(request: Request, key: str = Body(...), provider: str = Body("anthropic"),
                use_cloud: bool = Body(True)) -> dict:
    user = _me(request)
    if not user["verified"]:
        raise HTTPException(403, "Verify your email first.")
    user = _auth_call(S().accounts.set_ai_key, user, provider, key)
    # their choice: let Claude read requests and double-check alerts (a few frames per alert leave the computer)
    S().db.set_kv("privacy", privacy.apply({**privacy.current(), "private_mode": not use_cloud}))
    return {"user": S().accounts.public(user), "privacy": privacy.current()}


@app.post("/api/auth/finish")
def auth_finish(request: Request) -> dict:
    return {"user": S().accounts.public(_auth_call(S().accounts.finish, _me(request)))}


@app.post("/api/feedback")
def send_feedback(request: Request, rating: int | None = Body(None), kind: str = Body("general"),
                  text: str = Body(""), page: str = Body("")) -> dict:
    user = getattr(request.state, "user", None)
    return _auth_call(S().accounts.add_feedback, user, rating, kind, text, page)


@app.get("/api/feedback")
def list_feedback() -> list[dict]:
    return S().accounts.feedback()


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


def _metric_value(kind: str, b: dict) -> float:
    """One bucket's value: average objects (count), total crossings, or % of time YES (occupancy)."""
    n = max(1, int(b.get("n") or 0))
    if kind == "crossings":
        return round(float(b.get("sum") or 0), 2)
    if kind == "occupancy":
        return round(100.0 * float(b.get("sum") or 0) / n, 1)
    return round(float(b.get("sum") or 0) / n, 2)


def _metric_out(w: dict, hours: float = 24, bucket_s: float = 900) -> dict | None:
    spec = WatchSpec.model_validate(w["spec"])
    m = spec.metric
    if m is None:
        return None
    now = time.time()
    since = now - hours * 3600
    rows = S().db.metric_buckets(w["id"], since, bucket_s)
    rt = S().engine.runtimes.get(w["id"])
    live = rt.live_bucket() if rt else None
    if live and live["ts"] >= since:  # fold in the minute still being counted
        key = live["ts"] - live["ts"] % bucket_s
        hit = next((r for r in rows if r["ts"] == key), None)
        if hit:
            hit["sum"] += live["sum"]
            hit["n"] += live["n"]
            hit["max"] = max(hit["max"], live["max"])
        else:
            rows.append({"ts": key, "sum": live["sum"], "n": live["n"], "max": live["max"]})
    series = [{"ts": r["ts"], "value": _metric_value(m.kind, r), "peak": round(float(r["max"]), 2)} for r in rows]
    tot_sum = sum(float(r["sum"]) for r in rows)
    tot_n = sum(int(r["n"]) for r in rows)
    summary: dict = {"checks": tot_n}
    if m.kind == "count":
        summary.update(now=rt.count if rt and rt.count is not None else None,
                       avg=round(tot_sum / tot_n, 2) if tot_n else None,
                       peak=max((float(r["max"]) for r in rows), default=None))
    elif m.kind == "crossings":
        hour = S().db.metric_buckets(w["id"], now - 3600, 3600)
        last_hour = sum(float(r["sum"]) for r in hour) + (live["sum"] if live and live["ts"] >= now - 3600 else 0)
        span_h = min(hours, max(1 / 60, (now - min((r["ts"] for r in rows), default=now)) / 3600))
        summary.update(total=round(tot_sum), last_hour=round(last_hour), per_hour=round(tot_sum / span_h, 1))
    else:
        summary.update(now=bool(rt.cond) if rt else None, pct=round(100.0 * tot_sum / tot_n, 1) if tot_n else None)
    cam = S().db.camera(w["camera_id"])
    return {"watch_id": w["id"], "name": w["name"], "status": w["status"], "camera_id": w["camera_id"],
            "camera_name": cam["name"] if cam else "", "alerts": spec.alerts, "metric": m.model_dump(),
            "hours": hours, "bucket_s": bucket_s, "summary": summary, "series": series}


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
        "lan_url": lan_url(),
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
        "privacy": privacy.current(),
        "policy_refusals": S().db.get_kv("policy_refusals", {}) or {},
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
    if body.privacy is not None:
        S().db.set_kv("privacy", privacy.apply({**privacy.current(), **body.privacy}))
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
    out = S().actions.status()
    out["imessage"].update(managed=S().bridge.managed(), setup_problem=S().bridge.problem)
    return out


SETTINGS_PANES = {
    "full_disk_access": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
    "automation": "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
    "camera": "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",
}


@app.post("/api/system/open-settings")
def open_settings(pane: str = Body(..., embed=True)) -> dict:
    """Open the right page of macOS System Settings for a permission Vigil needs (local machine only)."""
    url = SETTINGS_PANES.get(pane)
    if not url or platform.system() != "Darwin":
        raise HTTPException(400, "unknown settings page")
    import subprocess

    subprocess.Popen(["open", url])
    return {"ok": True}


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
    """A text from the owner arrived through the Photon Spectrum bridge. Vigil answers it as an agent.

    Returns {reply, attachments, react}; the bridge sends the reply in the same conversation with Spectrum.
    Anyone who is not an owner (Settings -> iMessage) is ignored, with no reply.
    """
    handle = normalize_handle(sender)
    if handle not in agent.owners(S().actions.integrations()):
        return {"ok": False, "reason": "not an owner", "reply": ""}
    pending = S().db.get_kv(f"agent:pending:{handle}")
    if pending and time.time() - float(pending.get("ts", 0)) > 600:
        pending = None
    intent = agent.route(text, pending=bool(pending))
    try:
        out = _agent_do(intent, sender, handle, pending)
    except HTTPException as exc:
        d = exc.detail if isinstance(exc.detail, dict) else {"reason": str(exc.detail)}
        if d.get("code") == "policy":
            out = {"reply": f"I won't watch for that. {d.get('reason', '')}\n{d.get('suggestion', '')}".strip(),
                   "react": "‼️"}
        else:
            out = {"reply": f"I couldn't do that: {d.get('reason') or exc.detail}"}
    except Exception as exc:  # noqa: BLE001
        log.exception("iMessage agent failed")
        out = {"reply": f"Something went wrong on my side ({str(exc)[:80]}). Try again in a moment."}
    log.info("iMessage agent: %s -> %s", intent.kind, (out.get("reply") or "")[:80])
    return {"ok": True, "intent": intent.kind, "attachments": [], "react": "", **out}


def _agent_do(intent: "agent.Intent", sender: str, handle: str, pending: dict | None) -> dict:
    db = S().db
    cams = [c for c in db.cameras() if c.get("enabled", True)]
    if intent.kind == "feedback":
        row = db.latest_outbox(handle)
        if not row:
            return {"reply": "Thanks! There's no recent alert to grade, though. Text HELP to see what I can do."}
        ev = S().events.feedback(row["event_id"], intent.arg)
        db.execute("UPDATE outbox SET answered=1 WHERE id=?", (row["id"],))
        watch = db.watch(ev["watch_id"]) if ev else None
        name = watch["name"] if watch else "this watch"
        if intent.arg == "correct":
            return {"reply": f"Thanks! “{name}” just learned from it.", "react": "👍"}
        return {"reply": f"Got it, false alarm. “{name}” just learned from it and will be more careful.", "react": "👍"}
    if intent.kind == "help":
        return {"reply": agent.HELP}
    if intent.kind == "list":
        ws = db.watches()
        if not ws:
            return {"reply": "I'm not watching anything yet. Text me something like “Text me when a package is left at the door”."}
        lines = []
        for w in ws[:12]:
            cam = db.camera(w["camera_id"])
            state = {"active": "on", "paused": "paused", "building": "learning", "draft": "not started"}.get(w["status"], w["status"])
            lines.append(f"• {w['name']} ({cam['name'] if cam else '?'}): {state}{_agent_live(w)}")
        return {"reply": "Here's what I'm watching:\n" + "\n".join(lines)}
    if intent.kind in ("pause", "resume"):
        ws = db.watches()
        i = agent.best_match(intent.arg, [w["name"] for w in ws])
        if i is None:
            return {"reply": f"I couldn't find a watch called “{intent.arg}”. Text STATUS to see them all."}
        w = ws[i]
        if intent.kind == "pause":
            pause_watch(w["id"])
            return {"reply": f"Paused “{w['name']}”. Text “resume {w['name'].lower()}” to turn it back on.", "react": "👍"}
        if w["status"] not in ("paused", "active"):
            return {"reply": f"“{w['name']}” is still {w['status']}; it turns on by itself when it's ready."}
        resume_watch(w["id"])
        return {"reply": f"“{w['name']}” is back on.", "react": "👍"}
    if intent.kind == "metric":
        ms = [m for m in (_metric_out(w, 24, 3600) for w in db.watches()) if m]
        if not ms:
            return {"reply": "Nothing is being counted yet. Text me “Count the cars in the lot” to start."}
        i = agent.best_match(intent.arg, [f"{m['name']} {m['camera_name']} {m['metric'].get('name', '')}" for m in ms])
        if i is not None:
            return {"reply": _agent_metric_line(ms[i])}
        return {"reply": "I'm not counting that yet (text “Count the …” to start). Here's what I do count:\n"
                         + "\n".join(_agent_metric_line(m) for m in ms[:4])}
    if intent.kind == "look":
        if not cams:
            return {"reply": "No cameras are connected yet. Add one in the Vigil app first."}
        i = agent.best_match(intent.arg, [c["name"] for c in cams])
        out = _agent_look(cams[i if i is not None else 0])
        if i is None and len(cams) > 1:
            out["reply"] += "\n\nOther cameras: " + ", ".join(c["name"] for c in cams[1:]) + ". Ask “show me <name>”."
        return out
    if intent.kind == "pick" and pending:
        i = (int(intent.arg) - 1) if intent.arg.isdigit() else agent.best_match(intent.arg, [c["name"] for c in cams])
        if i is None or not 0 <= i < len(cams):
            return {"reply": "Which camera? Reply with its number:\n" + _agent_cam_list(cams)}
        db.set_kv(f"agent:pending:{handle}", None)
        return _agent_create(pending["prompt"], cams[i], sender)
    if intent.kind == "create":
        _enforce(check_text(intent.arg))
        if not cams:
            return {"reply": "No cameras are connected yet. Add one in the Vigil app first."}
        i = agent.best_match(intent.arg, [c["name"] for c in cams])
        if i is None and len(cams) > 1:
            db.set_kv(f"agent:pending:{handle}", {"prompt": intent.arg, "ts": time.time()})
            return {"reply": "Which camera should I use? Reply with its number:\n" + _agent_cam_list(cams)}
        return _agent_create(intent.arg, cams[i or 0], sender)
    return {"reply": "I'm not sure what you mean. To start a new watch, begin with “Text me when…”. "
                     "Text HELP to see everything I can do."}


def _agent_cam_list(cams: list[dict]) -> str:
    return "\n".join(f"{n}. {c['name']}" for n, c in enumerate(cams, 1))


def _agent_live(w: dict) -> str:
    rt = S().engine.runtimes.get(w["id"])
    if not rt or w["status"] != "active" or (w["spec"] or {}).get("crossing", "none") != "none":
        return ""  # a tripwire's live number is people in view, not crossings; STATUS/how many report those
    s = rt.snapshot(spark=False)
    if s["kind"] == "state" and s["cond"] is not None:
        return " · right now: yes" if s["cond"] else " · right now: no"
    if s["count"] is not None:
        return f" · right now: {s['count']}"
    return ""


def _agent_metric_line(m: dict) -> str:
    s, unit = m["summary"], m["metric"].get("unit") or ""
    name = m["metric"].get("name") or m["name"]
    if m["metric"]["kind"] == "count":
        avg = f", {s['avg']:.1f} on average today" if s.get("avg") is not None else ""
        return f"{name} ({m['camera_name']}): {s.get('now') if s.get('now') is not None else '–'} {unit} now{avg}".replace("  ", " ")
    if m["metric"]["kind"] == "crossings":
        return f"{name} ({m['camera_name']}): {s['last_hour']} in the last hour, {s['total']} today"
    pct = f"{s['pct']}% of the time today" if s.get("pct") is not None else "no data yet"
    return f"{name} ({m['camera_name']}): {pct}" + (" (yes right now)" if s.get("now") else "")


def _agent_look(cam: dict) -> dict:
    from .perception.detector import get_coco

    frame = _latest_frame(cam["id"])
    wanted = {"person": ["person"], "car": ["car"], "truck": ["truck"], "bus": ["bus"], "bicycle": ["bike"],
              "motorcycle": ["motorcycle"], "dog": ["dog"], "cat": ["cat"]}
    counts: dict[str, int] = {}
    for d in get_coco().detect(frame, wanted, threshold=0.45):
        counts[d.label] = counts.get(d.label, 0) + 1
    out_dir = settings.data_dir / "media" / "agent"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{int(time.time() * 1000)}.jpg"
    cv2.imwrite(str(path), privacy.blur_faces(frame), [cv2.IMWRITE_JPEG_QUALITY, 85])
    when = time.strftime("%-I:%M %p")
    lines = [f"{cam['name']}, {when}: I see {agent.count_phrase(counts)}."]
    for w in S().db.watches(cam["id"]):
        live = _agent_live(w)
        if live:
            lines.append(f"• {w['name']}{live}")
    return {"reply": "\n".join(lines), "attachments": [str(path)]}


def _agent_create(prompt: str, cam: dict, sender: str) -> dict:
    """Build a new watch from a text, exactly as the app does (same safety checks), and text when it's live."""
    w = draft_watch(WatchDraftIn(camera_id=cam["id"], prompt=prompt))
    spec = dict(w["spec"])
    if not any(a.get("type") == "imessage" for a in spec.get("actions") or []):
        spec["actions"] = [*(spec.get("actions") or []), {"type": "imessage", "target": sender, "object": "", "note": ""}][:4]
        S().db.update_watch(w["id"], spec=spec)
    build_watch(w["id"])
    threading.Thread(target=_agent_follow_build, args=(w["id"], sender), daemon=True).start()
    what = "count it" if spec.get("metric") and not spec.get("alerts", True) else "text you when it happens"
    return {"reply": f"On it. I'm building “{w['name']}” on {cam['name']}: a small model just for this. "
                     f"I'll tell you when it's live, then {what}.", "react": "👀"}


def _agent_follow_build(wid: int, sender: str) -> None:
    deadline = time.time() + 20 * 60
    while time.time() < deadline:
        time.sleep(3)
        w = S().db.watch(wid)
        if not w:
            return
        if w["status"] == "active":
            S().actions.reply(sender, f"“{w['name']}” is live. Text STATUS any time, or “pause {w['name'].lower()}”.")
            return
        if w["status"] in ("failed", "error"):
            S().actions.reply(sender, f"I couldn't finish “{w['name']}”: {w.get('status_detail') or 'unknown error'}. "
                                      "Open the Vigil app to see why.")
            return


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


@app.post("/api/watches/{wid}/preview")
def preview_watch(wid: int, spec: WatchSpec | None = Body(None, embed=True)) -> dict:
    """What the watch would answer on the camera right now (the unsaved spec from the review screen if given)."""
    w = _watch_or_404(wid)
    spec = spec or WatchSpec.model_validate(w["spec"])
    frame = _latest_frame(w["camera_id"])
    t = time.perf_counter()
    from .perception import library

    runner = library.runner_for(spec)
    if runner is not None:
        if runner.kind == "detector":
            hits = [h for h in runner.detect(frame) if h.conf >= runner.threshold]
            out = {"kind": spec.kind, "count": len(hits), "found": len(hits), "answer": bool(hits),
                   "yes": round(max((h.conf for h in hits), default=0.0), 3), "question": ", ".join(sorted(runner.yes))}
        else:
            if runner.kind == "video":
                rt = S().hub.get(w["camera_id"])
                ring = rt.clip_frames(time.time() - 2.0, time.time()) if rt else []
                frames = [f for f in (cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR) for _, j in ring)
                          if f is not None] or [frame]
                p = runner.proba_clip(frames)
                top = runner.top(frames)
            else:
                p, top = runner.proba(zone_crop(frame, spec.zone)), []
            out = {"kind": "state", "yes": round(p, 3), "answer": p >= runner.threshold,
                   "top": [[k, round(v, 3)] for k, v in top]}
        out["model"] = runner.m.name
        out["ms"] = round((time.perf_counter() - t) * 1000, 1)
        return out
    if spec.kind == "state":
        emb = get_embedder()
        w0, b0 = emb.zero_shot_direction(spec.positive_label, spec.negative_label)
        x = emb.embed_images([zone_crop(frame, spec.zone)])[0]
        p = float(1 / (1 + np.exp(-(x @ w0 + b0))))
        out = {"kind": "state", "yes": round(p, 3), "answer": p >= 0.5}
    else:
        from .perception.detector import coco_class_for, get_coco, get_owl

        coco = {c: [t] for t in spec.targets if (c := coco_class_for(t))}
        others = [t for t in spec.targets if not coco_class_for(t)]
        dets = (get_coco().detect(frame, coco, threshold=0.4) if coco else []) + \
               (get_owl().detect(frame, others, threshold=0.2) if others else [])
        found = len(dets)
        best = None
        if spec.target_question and dets:
            # same check the live watch runs: each found object's crop, judged by SigLIP 2 zero-shot
            emb = get_embedder()
            w0, b0 = emb.zero_shot_direction(*prior_labels(spec))
            X = emb.embed_images([crop(frame, d.box, pad=0.12) for d in dets])
            ps = 1 / (1 + np.exp(-(X @ w0 + b0)))
            best = round(float(ps.max()), 3)
            dets = [d for d, q in zip(dets, ps) if q >= 0.5]
        out = {"kind": spec.kind, "count": len(dets), "found": found, "yes": best,
               "question": spec.target_question or "", "answer": len(dets) > 0}
    out["ms"] = round((time.perf_counter() - t) * 1000, 1)
    return out


@app.get("/api/library")
def list_library() -> list[dict]:
    """The prebuilt model library, with download status and which watches use each model."""
    from .perception import library

    used: dict[str, list[str]] = {}
    for w in S().db.watches():
        lid = ((w.get("spec") or {}).get("library") or {}).get("id")
        if lid:
            used.setdefault(lid, []).append(w["name"])
    return [{**m, "watches": used.get(m["id"], [])} for m in library.status()]


@app.post("/api/lab/clip")
def lab_clip(camera_id: int = Body(...), options: list[str] = Body(...), seconds: float = Body(1.5)) -> dict:
    """Test bench: score the last few seconds of a camera against written options with the video-text model,
    next to a single-frame SigLIP baseline on the newest frame."""
    from .perception.video import get_videotext

    opts = [o.strip() for o in options if o and o.strip()][:8]
    if len(opts) < 2:
        raise HTTPException(400, "write at least two options")
    rt = S().hub.get(camera_id)
    if not rt:
        raise HTTPException(409, "camera is not running")
    now = time.time()
    ring = rt.clip_frames(now - min(max(seconds, 0.5), 5.0), now)
    frames = [f for f in (cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR) for _, j in ring) if f is not None]
    if len(frames) < 2:
        raise HTTPException(409, "camera has no recent frames yet")
    video, ms_video = get_videotext().score(frames, opts)
    emb = get_embedder()
    t = time.perf_counter()
    img = emb.embed_images([frames[-1]])[0]
    sims = np.array([float(img @ emb.embed_text(o)) for o in opts]) * emb.logit_scale
    image = np.exp(sims - sims.max())
    image = image / image.sum()
    ms_image = (time.perf_counter() - t) * 1000
    return {"video": [{"option": o, "p": round(p, 4)} for o, p in zip(opts, video)],
            "image": [{"option": o, "p": round(float(p), 4)} for o, p in zip(opts, image)],
            "ms_video": round(ms_video, 1), "ms_image": round(ms_image, 1), "frames": len(frames),
            "span_s": round(ring[-1][0] - ring[0][0], 2)}


@app.get("/api/webcams")
def webcams() -> list[dict]:
    """Cameras attached to this machine, by name, built-in first (an iPhone via Continuity Camera is marked)."""
    from .cameras.webcams import list_webcams

    return [c.out() for c in list_webcams()]


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


def _enforce(v: Verdict) -> None:
    """Refuse a request that breaks the safety policy; count refusals (category only, never the words)."""
    if v.allowed:
        return
    counts = S().db.get_kv("policy_refusals", {}) or {}
    counts[v.category] = int(counts.get(v.category, 0)) + 1
    S().db.set_kv("policy_refusals", counts)
    raise HTTPException(422, {"code": "policy", **v.out()})


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
    m = raw.get("metric")
    mk = str((m or {}).get("kind") or "none").lower() if isinstance(m, dict) else "none"
    mk = {"counting": "count", "number": "count", "crossing": "crossings", "line": "crossings",
          "percent": "occupancy", "share": "occupancy", "time": "occupancy"}.get(mk, mk)
    raw["metric"] = ({"kind": mk, "name": str(m.get("name") or raw.get("name") or "").strip()[:60],
                      "unit": str(m.get("unit") or "").strip()[:20]}
                     if mk in ("count", "crossings", "occupancy") else None)
    raw["alerts"] = str(raw.get("alerts", True)).lower() not in ("false", "0", "no", "none") or not raw["metric"]
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


PHONE_USE = re.compile(r"\b(on (their|his|her|my|a|the) (cell ?)?phone|using (their|his|her|my|a|the) (cell ?)?phone|"
                       r"holding (a|their|his|her|my|the) (cell ?)?phone|(cell ?)?phones? (out|in (their|his|her|my) hand)|"
                       r"picks? up (their|his|her|my|a|the) phone|on the phone|smartphone)\b", re.I)
EXPLICIT_TIME = re.compile(r"\b\d+\s*(s|sec|secs|second|seconds|min|mins|minute|minutes|h|hr|hrs|hour|hours)\b", re.I)
EACH_NEW = re.compile(r"\b(each|every) (new )?(person|one|arrival|car|truck|visitor|customer)\b|\bnew (person|people|arrival)\b|"
                      r"\b(comes|walks|steps|drives) in\b|\benters\b|\barrives\b", re.I)


def _live_defaults(spec: WatchSpec, prompt: str) -> None:
    """Make a fresh watch respond the way people expect when they try it live.

    "On their phone" is a phone being visible, which the detector sees directly. Unless the request names a
    duration, an alert needs about a second of agreement (not five) and can repeat after 20 seconds; "once per
    person" only when the request asks for each new arrival.
    """
    if PHONE_USE.search(prompt) and spec.kind in ("presence", "state") and not spec.library:
        spec.kind = "presence"
        spec.targets = ["cell phone"]
        spec.target_question = ""
        spec.zone = None
        spec.check_interval_s = 0.0
    if not EXPLICIT_TIME.search(prompt):
        spec.min_duration_s = min(spec.min_duration_s, 1.0)
        spec.cooldown_s = min(spec.cooldown_s, 20.0)
    if spec.trigger == "per_object" and spec.crossing == "none" and not EACH_NEW.search(prompt):
        spec.trigger = "rising"


def _text_by_default(spec: WatchSpec) -> None:
    """Every alerting watch texts the owner over iMessage when iMessage is set up, whether or not the request said
    "text me"; other actions the request asked for (HubSpot, webhooks) stay as they are."""
    if not spec.alerts or any(a.type == "imessage" for a in spec.actions):
        return
    if (S().db.get_kv("integrations", {}) or {}).get("imessage_to"):
        spec.actions.append(Action(type="imessage", note=spec.alert_message or spec.name))


@app.post("/api/watches/draft")
def draft_watch(body: WatchDraftIn) -> dict:
    cam = _cam_or_404(body.camera_id)
    prompt = body.prompt.strip()
    if len(prompt) < 4:
        raise HTTPException(400, "describe what to watch for")
    _enforce(check_text(prompt))
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
    pol = raw.get("policy") if isinstance(raw, dict) else None
    if isinstance(pol, dict) and str(pol.get("allowed", True)).lower() in ("false", "0", "no"):
        _enforce(Verdict(False, str(pol.get("category") or "policy"), str(pol.get("reason") or "This request is outside what Vigil watches for."),
                         str(pol.get("suggestion") or "Describe an object, event or condition instead.")))
    spec = _sanitize(raw)
    _live_defaults(spec, prompt)
    _text_by_default(spec)
    _enforce(check_spec(spec.model_dump()))
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
    from .learning import finetune as ft

    coco = ft.pretrained_fits(spec) if settings.finetune else None
    if settings.finetune:
        spec.zone = None  # the watch's own model looks at the whole view; the user can still limit it to an area
    if coco:
        spec.target_question = ""
    from .learning import existing
    from .perception import library

    lib = library.match(f"{prompt} {spec.positive_label}", spec.kind) if not settings.finetune else None
    if lib:
        spec.library = lib
        spec.zone = None
        spec.crossing = "none"
        spec.target_question = ""
        if library.kind_of(lib) == "detector":
            spec.kind = "count" if spec.kind == "count" else "presence"
            spec.targets = [library.BY_ID[lib["id"]].name.lower()]
            if spec.trigger not in ("rising", "sustained", "per_object"):
                spec.trigger = "rising"
        else:
            spec.kind = "state"
            spec.targets = []
            if spec.trigger == "per_object":
                spec.trigger = "rising"
    dataset = (existing.choose(spec) if not settings.finetune else
               {"state": "pretrained", "classes": coco} if coco else {"state": "searching"})
    w = S().db.add_watch(cam["id"], spec.name, prompt, spec.model_dump(), status="draft")
    S().db.update_watch(w["id"], metrics={"compile": {"brain": brain.label, "ms": compile_ms, "zone": zinfo,
                                                      "warnings": warnings}, "dataset": dataset})
    if settings.finetune and not coco:
        threading.Thread(target=_find_dataset, args=(w["id"], spec, prompt, brain), daemon=True).start()
    return {**_watch_out(S().db.watch(w["id"])), "proposal": zinfo, "warnings": warnings}


def _find_dataset(wid: int, spec: WatchSpec, prompt: str, brain) -> None:
    """Look for the public data this watch will be trained on while the user reviews the plan."""
    from .learning import finetune as ft

    def note(**d) -> None:
        w = S().db.watch(wid)
        if w:
            m = dict(w.get("metrics") or {})
            m["dataset"] = {**(m.get("dataset") or {}), **d}
            S().db.update_watch(wid, metrics=m)
            bus.publish("dataset", {"watch_id": wid, **m["dataset"]})

    try:
        plan = ft.find(spec, prompt, wid, brain=brain if hasattr(brain, "text_json") else None,
                       embedder=get_embedder(), say=lambda msg: note(message=msg))
        note(state="found" if plan else "none", plan=plan.out() if plan else None)
    except Exception as exc:  # noqa: BLE001
        log.exception("dataset search failed for watch %s", wid)
        note(state="none", message=f"search failed: {str(exc)[:100]}")


@app.get("/api/watches/{wid}/dataset/{name}")
def dataset_preview(wid: int, name: str) -> FileResponse:
    from .learning import finetune as ft

    p = (ft.root(wid) / "preview" / name).resolve()
    if p.parent != (ft.root(wid) / "preview").resolve() or not p.exists():
        raise HTTPException(404, "no such preview")
    return FileResponse(p, media_type="image/jpeg")


@app.get("/api/watches")
def list_watches(camera_id: int | None = None) -> list[dict]:
    return [_watch_out(w) for w in S().db.watches(camera_id)]


@app.get("/api/metrics")
def list_metrics(hours: float = 24, bucket: float = 900) -> list[dict]:
    """Every watch that keeps a number (counts, crossings, share of time), with a summary and a time series."""
    hours, bucket = min(max(hours, 0.1), 24 * 31), min(max(bucket, 60), 86400)
    out = [_metric_out(w, hours, bucket) for w in S().db.watches()]
    return [m for m in out if m]


@app.get("/api/watches/{wid}/metrics")
def watch_metrics(wid: int, hours: float = 24, bucket: float = 900) -> dict:
    m = _metric_out(_watch_or_404(wid), min(max(hours, 0.1), 24 * 31), min(max(bucket, 60), 86400))
    if m is None:
        raise HTTPException(404, "this watch keeps no metric")
    return m


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
        _enforce(check_spec(body.spec.model_dump()))
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
    user = S().accounts.session_user(ws.cookies.get(COOKIE))
    if user is None or S().accounts.next_step(user) != "ready":
        await ws.close(code=4401)
        return
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
