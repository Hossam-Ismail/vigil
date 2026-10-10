"""Per-watch actions that run when an alert is confirmed: iMessage (Photon), HubSpot, webhooks, Slack, ntfy.

iMessage goes through a small local bridge built on Photon's imessage-kit (see /imessage-bridge). Each iMessage
is recorded in the outbox so a reply ("yes", "no") can be matched back to its event and used as a training label.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from ..config import settings
from ..db import DB
from ..schemas import Action

log = logging.getLogger("vigil.actions")

HUBSPOT_API = "https://api.hubapi.com"


class ActionRunner:
    def __init__(self, db: DB):
        self.db = db
        self.http = httpx.Client(timeout=15.0)

    # ---- configuration ------------------------------------------------
    def integrations(self) -> dict:
        return self.db.get_kv("integrations", {}) or {}

    def bridge_url(self) -> str:
        return (self.integrations().get("imessage_bridge") or "http://127.0.0.1:8790").rstrip("/")

    def public_url(self) -> str:
        return (self.integrations().get("public_url") or f"http://{settings.host}:{settings.port}").rstrip("/")

    def status(self) -> dict:
        integ = self.integrations()
        bridge = {"url": self.bridge_url(), "ok": False}
        try:
            r = self.http.get(self.bridge_url() + "/health", timeout=2.0)
            if r.status_code == 200:
                bridge.update(r.json())
            bridge["ok"] = r.status_code == 200
        except Exception as exc:  # noqa: BLE001
            bridge["error"] = str(exc)[:120]
        return {
            "imessage": {**bridge, "default_to": integ.get("imessage_to", "")},
            "hubspot": {"configured": bool(integ.get("hubspot_token"))},
        }

    # ---- running --------------------------------------------------------
    def run(self, actions: list[Action], event: dict, watch: dict, camera: dict, snapshot: Path | None) -> list[dict]:
        results = []
        for a in actions:
            try:
                info = getattr(self, f"_{a.type}")(a, event, watch, camera, snapshot)
                results.append({"action": a.type, "ok": True, **(info or {})})
            except Exception as exc:  # noqa: BLE001
                log.warning("action %s failed: %s", a.type, exc)
                results.append({"action": a.type, "ok": False, "error": str(exc)[:200]})
        return results

    def _link(self, event: dict) -> str:
        return f"{self.public_url()}/events?open={event['id']}"

    def _imessage(self, a: Action, event, watch, camera, snapshot) -> dict:
        to = (a.target or self.integrations().get("imessage_to") or "").strip()
        if not to:
            raise RuntimeError("no iMessage recipient; set one on the action or in Settings")
        when = time.strftime("%-I:%M %p", time.localtime(event["ts"]))
        text = (f"{event['message']} ({camera['name']}, {when})"
                + (f"\n{event['verdict']}" if event.get("verdict") else "")
                + (f"\n{a.note}" if a.note else "")
                + "\n\nWas this right? Reply YES or NO and Vigil will learn from it.")
        body = {"to": to, "text": text, "attachments": [str(snapshot)] if snapshot and snapshot.exists() else []}
        r = self.http.post(self.bridge_url() + "/send", json=body)
        r.raise_for_status()
        self.db.add_outbox(event["id"], "imessage", normalize_handle(to))
        return {"to": to}

    def _hubspot(self, a: Action, event, watch, camera, snapshot) -> dict:
        token = self.integrations().get("hubspot_token", "")
        if not token:
            raise RuntimeError("HubSpot is not connected; add a private-app token in Settings")
        obj = (a.object or "ticket").lower()
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(event["ts"]))
        title = f"{watch['name']}: {event['message']}"[:240]
        body = (f"{event['message']}\nCamera: {camera['name']} · {when}\nRequest: “{watch['prompt']}”"
                + (f"\nDouble-check: {event['verdict']}" if event.get("verdict") else "")
                + (f"\n{a.note}" if a.note else "")
                + f"\nEvidence: {self._link(event)}")
        ts_ms = int(event["ts"] * 1000)
        if obj == "task":
            path, props = "tasks", {"hs_task_subject": title, "hs_task_body": body, "hs_timestamp": ts_ms,
                                    "hs_task_status": "NOT_STARTED", "hs_task_priority": "HIGH"}
        elif obj == "note":
            path, props = "notes", {"hs_note_body": f"{title}\n{body}", "hs_timestamp": ts_ms}
        else:
            path, props = "tickets", {"subject": title, "content": body, "hs_pipeline": "0",
                                      "hs_pipeline_stage": "1", "hs_ticket_priority": "HIGH"}
        r = self.http.post(f"{HUBSPOT_API}/crm/v3/objects/{path}", json={"properties": props},
                           headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return {"object": obj, "id": r.json().get("id")}

    def _webhook(self, a: Action, event, watch, camera, snapshot) -> dict:
        if not a.target:
            raise RuntimeError("webhook URL missing")
        payload = {"event_id": event["id"], "watch": watch["name"], "prompt": watch["prompt"],
                   "camera": camera["name"], "ts": event["ts"], "message": event["message"],
                   "verdict": event.get("verdict", ""), "link": self._link(event), "note": a.note}
        self.http.post(a.target, json=payload).raise_for_status()
        return {}

    def _slack(self, a: Action, event, watch, camera, snapshot) -> dict:
        if not a.target:
            raise RuntimeError("Slack webhook URL missing")
        text = f"*{watch['name']} · {camera['name']}*\n{event['message']}\n<{self._link(event)}|Open in Vigil>"
        self.http.post(a.target, json={"text": text}).raise_for_status()
        return {}

    def _ntfy(self, a: Action, event, watch, camera, snapshot) -> dict:
        topic = a.target.strip()
        if not topic:
            raise RuntimeError("ntfy topic missing")
        url = topic if topic.startswith("http") else f"https://ntfy.sh/{topic}"
        headers = {"Title": f"{watch['name']} · {camera['name']}", "Click": self._link(event)}
        self.http.post(url, content=event["message"].encode(), headers=headers).raise_for_status()
        return {}

    # ---- replies ----------------------------------------------------------
    def reply(self, handle: str, text: str) -> None:
        try:
            self.http.post(self.bridge_url() + "/send", json={"to": handle, "text": text}).raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("could not send iMessage reply: %s", exc)


def normalize_handle(h: str) -> str:
    h = h.strip().lower()
    if "@" in h:
        return h
    digits = "".join(ch for ch in h if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


YES = {"yes", "y", "yep", "yeah", "correct", "right", "true", "1", "👍", "✅", "ok", "confirmed"}
NO = {"no", "n", "nope", "wrong", "false", "false alarm", "incorrect", "2", "👎", "❌", "not really"}


def parse_reply(text: str) -> str | None:
    t = text.strip().lower().strip(".!? ")
    if t in YES or t.startswith(("yes", "yep", "correct")):
        return "correct"
    if t in NO or t.startswith(("no", "wrong", "false")):
        return "false_alarm"
    return None
