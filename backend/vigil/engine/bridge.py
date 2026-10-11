"""Runs the Photon iMessage bridge for the user, so nobody has to start a second program.

If no bridge answers at the configured address (default http://127.0.0.1:8790), Vigil starts
`imessage-bridge/bridge.mjs` with Node in live mode, restarts it if it exits, and stops it on shutdown.
An external bridge (another Mac, or one someone started by hand) is used as-is.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import settings

log = logging.getLogger("vigil.bridge")

BRIDGE_DIR = Path(__file__).resolve().parents[3] / "imessage-bridge"
NODE_CANDIDATES = ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node")


def _node() -> str | None:
    for c in NODE_CANDIDATES:
        p = shutil.which(c) or (c if os.path.isfile(c) else None)
        if p:
            return p
    return None


class BridgeSupervisor:
    def __init__(self, url_fn) -> None:
        self.url_fn = url_fn  # current bridge URL from Settings
        self.proc: subprocess.Popen | None = None
        self.problem = ""  # why Vigil could not start the bridge itself, in plain words
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="imessage-bridge", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def managed(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _alive(self, url: str) -> bool:
        try:
            return httpx.get(url + "/health", timeout=1.5).status_code == 200
        except httpx.HTTPError:
            return False

    def _run(self) -> None:
        while not self._stop.is_set():
            url = self.url_fn().rstrip("/")
            u = urlparse(url)
            local = u.hostname in ("127.0.0.1", "localhost")
            if local and not self._alive(url) and not self.managed():
                self._spawn(u.port or 8790)
            self._stop.wait(10)

    def _spawn(self, port: int) -> None:
        node = _node()
        if node is None:
            self.problem = "Node.js is not installed. Install it from nodejs.org, then reopen Vigil."
            return
        if not (BRIDGE_DIR / "node_modules").exists():
            self.problem = "The iMessage bridge is not installed yet. Run `npm install` in the imessage-bridge folder once."
            return
        env = {**os.environ, "PORT": str(port), "VIGIL_URL": f"http://127.0.0.1:{settings.port}"}
        env.pop("DRY_RUN", None)
        log.info("starting the iMessage bridge on port %d", port)
        self.proc = subprocess.Popen([node, str(BRIDGE_DIR / "bridge.mjs")], cwd=str(BRIDGE_DIR), env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.problem = ""
        time.sleep(2)
