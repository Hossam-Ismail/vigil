"""Alert delivery: generic webhook, ntfy (phone push, no account needed), Slack, macOS desktop."""

from __future__ import annotations

import base64
import logging
import platform
import subprocess
from pathlib import Path

import httpx

from ..db import DB

log = logging.getLogger("vigil.notify")

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
NTFY_PRIORITY = {"info": "3", "warning": "4", "critical": "5"}


class Notifier:
    def __init__(self, db: DB, public_url: str = ""):
        self.db = db
        self.public_url = public_url.rstrip("/")
        self.http = httpx.Client(timeout=10.0)

    def channels(self) -> list[dict]:
        return self.db.get_kv("channels", [])

    def send(self, event: dict, watch: dict, camera: dict, snapshot: Path | None, *, only: str | None = None) -> list[dict]:
        severity = watch["spec"].get("severity", "warning")
        results = []
        for ch in self.channels():
            if only and ch["id"] != only:
                continue
            if not only and (not ch.get("enabled", True) or
                             SEVERITY_RANK[severity] < SEVERITY_RANK.get(ch.get("min_severity", "info"), 0)):
                continue
            try:
                getattr(self, f"_{ch['type']}")(ch, event, watch, camera, snapshot, severity)
                results.append({"channel": ch["id"], "ok": True})
            except Exception as exc:  # noqa: BLE001
                log.warning("notify %s failed: %s", ch["id"], exc)
                results.append({"channel": ch["id"], "ok": False, "error": str(exc)[:200]})
        return results

    def _title(self, watch: dict, camera: dict) -> str:
        return f"{watch['name']} · {camera['name']}"

    def _link(self, event: dict) -> str:
        return f"{self.public_url}/events/{event['id']}" if self.public_url else ""

    def _webhook(self, ch, event, watch, camera, snapshot, severity) -> None:
        payload = {
            "event_id": event["id"],
            "watch": {"id": watch["id"], "name": watch["name"], "prompt": watch["prompt"]},
            "camera": {"id": camera["id"], "name": camera["name"]},
            "ts": event["ts"],
            "message": event["message"],
            "severity": severity,
            "verdict": event.get("verdict", ""),
            "status": event.get("status"),
            "link": self._link(event),
        }
        if snapshot and snapshot.exists():
            payload["snapshot_jpeg_b64"] = base64.b64encode(snapshot.read_bytes()).decode()
        self.http.post(ch["target"], json=payload).raise_for_status()

    def _ntfy(self, ch, event, watch, camera, snapshot, severity) -> None:
        target = ch["target"].strip()
        url = target if target.startswith("http") else f"https://ntfy.sh/{target}"
        headers = {
            "Title": self._title(watch, camera),
            "Priority": NTFY_PRIORITY[severity],
            "Tags": "rotating_light" if severity == "critical" else "eyes",
            "Message": event["message"] + (f"\n{event['verdict']}" if event.get("verdict") else ""),
        }
        if self._link(event):
            headers["Click"] = self._link(event)
        if snapshot and snapshot.exists():
            headers["Filename"] = "snapshot.jpg"
            self.http.put(url, content=snapshot.read_bytes(), headers=headers).raise_for_status()
        else:
            self.http.post(url, content=headers.pop("Message").encode(), headers=headers).raise_for_status()

    def _slack(self, ch, event, watch, camera, snapshot, severity) -> None:
        text = f"*{self._title(watch, camera)}*\n{event['message']}"
        if event.get("verdict"):
            text += f"\n_{event['verdict']}_"
        if self._link(event):
            text += f"\n<{self._link(event)}|Open in Vigil>"
        self.http.post(ch["target"], json={"text": text}).raise_for_status()

    def _desktop(self, ch, event, watch, camera, snapshot, severity) -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("desktop notifications are only implemented for macOS")
        title = self._title(watch, camera).replace('"', "'")
        msg = event["message"].replace('"', "'")
        subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "Vigil" subtitle "{title}"'],
                       check=True, timeout=5)
