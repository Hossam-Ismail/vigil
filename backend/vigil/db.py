"""SQLite persistence. One connection guarded by a lock; JSON stored as TEXT."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    spec TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    status_detail TEXT NOT NULL DEFAULT '',
    model_version INTEGER NOT NULL DEFAULT 0,
    metrics TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    ts REAL NOT NULL,
    image_path TEXT NOT NULL,
    label INTEGER,
    source TEXT NOT NULL DEFAULT '',
    confidence REAL,
    reason TEXT NOT NULL DEFAULT '',
    score REAL,
    origin TEXT NOT NULL DEFAULT '',
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS samples_watch ON samples(watch_id);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    camera_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    score REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    verdict TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    snapshot_path TEXT NOT NULL DEFAULT '',
    crop_path TEXT NOT NULL DEFAULT '',
    clip_path TEXT NOT NULL DEFAULT '',
    feedback TEXT,
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts DESC);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    handle TEXT NOT NULL,
    ts REAL NOT NULL,
    answered INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS outbox_handle ON outbox(handle, ts DESC);
CREATE TABLE IF NOT EXISTS metrics (
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    ts REAL NOT NULL,
    sum REAL NOT NULL,
    n INTEGER NOT NULL,
    max REAL NOT NULL,
    last REAL NOT NULL,
    PRIMARY KEY (watch_id, ts)
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

JSON_FIELDS = {"spec", "metrics", "detail"}


def _np_default(o: Any) -> Any:
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def dumps(v: Any) -> str:
    return json.dumps(v, default=_np_default)


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for k in JSON_FIELDS & out.keys():
        out[k] = json.loads(out[k]) if out[k] else {}
    if "embedding" in out:
        out.pop("embedding")
    for k in ("enabled",):
        if k in out:
            out[k] = bool(out[k])
    return out


class DB:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        with self._lock:
            return _row(self._conn.execute(sql, params).fetchone())

    def all(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [_row(r) for r in self._conn.execute(sql, params).fetchall()]  # type: ignore[misc]

    # ---- cameras -------------------------------------------------------
    def add_camera(self, name: str, kind: str, url: str, enabled: bool = True) -> dict:
        cur = self.execute(
            "INSERT INTO cameras(name, kind, url, enabled, created_at) VALUES (?,?,?,?,?)",
            (name, kind, url, int(enabled), time.time()),
        )
        return self.camera(cur.lastrowid)  # type: ignore[arg-type]

    def camera(self, cid: int) -> dict | None:
        return self.one("SELECT * FROM cameras WHERE id=?", (cid,))

    def cameras(self) -> list[dict]:
        return self.all("SELECT * FROM cameras ORDER BY id")

    def update_camera(self, cid: int, **fields: Any) -> dict | None:
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            vals = [int(v) if isinstance(v, bool) else v for v in fields.values()]
            self.execute(f"UPDATE cameras SET {cols} WHERE id=?", (*vals, cid))
        return self.camera(cid)

    def delete_camera(self, cid: int) -> None:
        self.execute("DELETE FROM cameras WHERE id=?", (cid,))

    # ---- watches -------------------------------------------------------
    def add_watch(self, camera_id: int, name: str, prompt: str, spec: dict, status: str = "draft") -> dict:
        now = time.time()
        cur = self.execute(
            "INSERT INTO watches(camera_id, name, prompt, spec, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (camera_id, name, prompt, dumps(spec), status, now, now),
        )
        return self.watch(cur.lastrowid)  # type: ignore[arg-type]

    def watch(self, wid: int) -> dict | None:
        return self.one("SELECT * FROM watches WHERE id=?", (wid,))

    def watches(self, camera_id: int | None = None) -> list[dict]:
        if camera_id is None:
            return self.all("SELECT * FROM watches ORDER BY id")
        return self.all("SELECT * FROM watches WHERE camera_id=? ORDER BY id", (camera_id,))

    def update_watch(self, wid: int, **fields: Any) -> dict | None:
        fields["updated_at"] = time.time()
        for k in JSON_FIELDS & fields.keys():
            fields[k] = dumps(fields[k])
        cols = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE watches SET {cols} WHERE id=?", (*fields.values(), wid))
        return self.watch(wid)

    def delete_watch(self, wid: int) -> None:
        self.execute("DELETE FROM watches WHERE id=?", (wid,))

    # ---- samples -------------------------------------------------------
    def add_sample(
        self,
        watch_id: int,
        image_path: str,
        embedding: np.ndarray,
        *,
        ts: float | None = None,
        label: int | None = None,
        source: str = "",
        confidence: float | None = None,
        reason: str = "",
        score: float | None = None,
        origin: str = "",
    ) -> int:
        cur = self.execute(
            "INSERT INTO samples(watch_id, ts, image_path, label, source, confidence, reason, score, origin, embedding)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                watch_id,
                ts or time.time(),
                image_path,
                label,
                source,
                confidence,
                reason,
                score,
                origin,
                embedding.astype(np.float16).tobytes(),
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def sample(self, sid: int) -> dict | None:
        return self.one("SELECT * FROM samples WHERE id=?", (sid,))

    def samples(self, watch_id: int) -> list[dict]:
        return self.all("SELECT * FROM samples WHERE watch_id=? ORDER BY id DESC", (watch_id,))

    def update_sample(self, sid: int, **fields: Any) -> dict | None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE samples SET {cols} WHERE id=?", (*fields.values(), sid))
        return self.sample(sid)

    def delete_sample(self, sid: int) -> None:
        self.execute("DELETE FROM samples WHERE id=?", (sid,))

    def training_set(self, watch_id: int, *, with_origin: bool = False):
        """Return (X, y, sample_ids, sources[, origins]) for all labeled samples of a watch."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, label, source, origin, embedding FROM samples WHERE watch_id=? AND label IS NOT NULL",
                (watch_id,),
            ).fetchall()
        if not rows:
            empty = (np.zeros((0, 0), np.float32), np.zeros(0, np.int64), np.zeros(0, np.int64), [])
            return (*empty, []) if with_origin else empty
        X = np.stack([np.frombuffer(r["embedding"], dtype=np.float16).astype(np.float32) for r in rows])
        y = np.array([r["label"] for r in rows], dtype=np.int64)
        ids = np.array([r["id"] for r in rows], dtype=np.int64)
        out = (X, y, ids, [r["source"] for r in rows])
        return (*out, [r["origin"] for r in rows]) if with_origin else out

    # ---- outbox (messages that can be answered) -------------------------
    def add_outbox(self, event_id: int, channel: str, handle: str) -> None:
        self.execute("INSERT INTO outbox(event_id, channel, handle, ts) VALUES (?,?,?,?)",
                     (event_id, channel, handle, time.time()))

    def latest_outbox(self, handle: str, within_s: float = 48 * 3600) -> dict | None:
        return self.one("SELECT * FROM outbox WHERE handle=? AND ts > ? ORDER BY ts DESC LIMIT 1",
                        (handle, time.time() - within_s))

    # ---- events --------------------------------------------------------
    def add_event(self, watch_id: int, camera_id: int, ts: float, score: float | None, message: str, detail: dict) -> int:
        cur = self.execute(
            "INSERT INTO events(watch_id, camera_id, ts, score, message, detail) VALUES (?,?,?,?,?,?)",
            (watch_id, camera_id, ts, score, message, dumps(detail)),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def event(self, eid: int) -> dict | None:
        return self.one("SELECT * FROM events WHERE id=?", (eid,))

    def events(
        self, *, watch_id: int | None = None, camera_id: int | None = None, limit: int = 100, include_suppressed=True
    ) -> list[dict]:
        where, params = [], []
        if watch_id is not None:
            where.append("watch_id=?")
            params.append(watch_id)
        if camera_id is not None:
            where.append("camera_id=?")
            params.append(camera_id)
        if not include_suppressed:
            where.append("status != 'suppressed'")
        sql = "SELECT * FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ts DESC LIMIT ?"
        return self.all(sql, (*params, limit))

    def update_event(self, eid: int, **fields: Any) -> dict | None:
        for k in JSON_FIELDS & fields.keys():
            fields[k] = dumps(fields[k])
        cols = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE events SET {cols} WHERE id=?", (*fields.values(), eid))
        return self.event(eid)

    # ---- key/value settings --------------------------------------------
    # ---- metrics (one row per watch per minute) ---------------------------
    def add_metric_rows(self, rows: list[dict]) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT INTO metrics (watch_id, ts, sum, n, max, last) VALUES (:watch_id, :ts, :sum, :n, :max, :last) "
                "ON CONFLICT(watch_id, ts) DO UPDATE SET sum = sum + excluded.sum, n = n + excluded.n, "
                "max = MAX(max, excluded.max), last = excluded.last",
                rows,
            )

    def metric_buckets(self, watch_id: int, since: float, bucket_s: float) -> list[dict]:
        """Minute rows rolled up into `bucket_s` buckets: sum, checks, peak, last."""
        return self.all(
            "SELECT CAST(ts / ? AS INTEGER) * ? AS ts, SUM(sum) AS sum, SUM(n) AS n, MAX(max) AS max, "
            "MAX(ts) AS last_ts FROM metrics WHERE watch_id = ? AND ts >= ? GROUP BY 1 ORDER BY 1",
            (bucket_s, bucket_s, watch_id, since),
        )

    def get_kv(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set_kv(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO kv(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, dumps(value)),
        )
