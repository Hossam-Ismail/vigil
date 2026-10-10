"""End-to-end check against the demo shelf camera, in-process.

    VIGIL_DATA=/tmp/vigil-e2e VIGIL_BRAIN=heuristic python scripts/e2e_demo.py

Creates "alert me when the blue bin on the top shelf is empty", builds the model while the demo bin is
toggled full/empty, then empties the bin and expects exactly one alert.
"""

from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("VIGIL_COLLECT_SECONDS", "8")

from fastapi.testclient import TestClient  # noqa: E402

from vigil.api import app  # noqa: E402

PROMPT = os.environ.get("E2E_PROMPT", "Alert me when the blue bin on the top shelf is empty")


def wait_for(fn, timeout, interval=0.5, what="condition"):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    raise TimeoutError(f"timed out waiting for {what}")


def main() -> int:
    with TestClient(app) as c:
        health = c.get("/api/health").json()
        print("health:", json.dumps(health["brain"]), health["device"])
        cams = c.get("/api/cameras").json()
        cam = next(x for x in cams if x["kind"] == "demo")
        cid = cam["id"]
        wait_for(lambda: c.get(f"/api/cameras/{cid}").status_code in (200, 405) or True, 1)
        wait_for(lambda: c.get(f"/api/cameras/{cid}/snapshot.jpg").status_code == 200, 20, what="first frame")
        c.post(f"/api/cameras/{cid}/demo", json={"auto": False})
        c.post(f"/api/cameras/{cid}/demo", json={"bin": "A-01", "level": 1.0})
        time.sleep(2.0)  # let the simulated restocking hand leave the frame

        t = time.time()
        r = c.post("/api/watches/draft", json={"camera_id": cid, "prompt": PROMPT})
        assert r.status_code == 200, r.text
        w = r.json()
        spec = w["spec"]
        print(f"draft in {time.time() - t:.1f}s:", spec["kind"], "|", spec["question"])
        print("  labels:", spec["positive_label"], "/", spec["negative_label"])
        print("  zone:", spec["zone"], "via", w["proposal"].get("method"), "warnings:", w.get("warnings"))
        wid = w["id"]

        # speed the test up: short dwell, no cooldown wait
        spec["min_duration_s"] = 3
        spec["cooldown_s"] = 30
        c.patch(f"/api/watches/{wid}", json={"spec": spec})

        r = c.post(f"/api/watches/{wid}/build", json={"collect_seconds": 8})
        assert r.status_code == 200, r.text
        time.sleep(3)
        c.post(f"/api/cameras/{cid}/demo", json={"bin": "A-01", "level": 0.0})  # show the empty state too
        time.sleep(3.5)
        c.post(f"/api/cameras/{cid}/demo", json={"bin": "A-01", "level": 1.0})
        t = time.time()
        w = wait_for(lambda: (lambda x: x if x["status"] in ("active", "error") else None)(
            c.get(f"/api/watches/{wid}").json()), 600, 1.0, "build")
        print(f"build finished ({w['status']}) {w['status_detail']} +{time.time() - t:.1f}s after collect")
        if w["status"] != "active":
            return 1
        m = w["metrics"]
        print("  model:", m.get("mode"), "n_pos", m.get("n_pos"), "n_neg", m.get("n_neg"),
              "cv", m.get("cv"), "zero-shot", (m.get("zero_shot") or {}).get("accuracy"))

        samples = c.get(f"/api/watches/{wid}/samples").json()
        print("  samples:", [(x["label"], round(x["confidence"] or 0, 2), round(x["score"] or 0, 2)) for x in samples])
        time.sleep(6)
        rt = c.get(f"/api/watches/{wid}").json()["runtime"]
        print("  full bin -> score", rt["score"], "cond", rt["cond"])
        before = len(c.get(f"/api/events?watch_id={wid}").json())

        c.post(f"/api/cameras/{cid}/demo", json={"bin": "A-01", "level": 0.0})
        ev = wait_for(lambda: c.get(f"/api/events?watch_id={wid}").json()[: max(0, 1)] if
                      len(c.get(f"/api/events?watch_id={wid}").json()) > before else None, 40, 0.5, "alert")
        rt = c.get(f"/api/watches/{wid}").json()["runtime"]
        print("  empty bin -> score", rt["score"], "cond", rt["cond"])
        print("  EVENT:", ev[0]["message"], ev[0]["status"])
        ev = wait_for(lambda: (lambda e: e if e["clip_path"] else None)(c.get(f"/api/events/{ev[0]['id']}").json()),
                      30, 1, "clip")
        print("  clip:", ev["clip_path"], "snapshot:", ev["snapshot_path"], "status:", ev["status"], ev["verdict"])
        ok = before == 0 and ev["status"] in ("confirmed", "unverified")
        print("E2E", "PASS" if ok else "CHECK")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
