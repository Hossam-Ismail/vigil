"""Accounts for the beta: .edu sign-up, email verification, sessions, onboarding, the user's AI key, feedback.

Gates, in order, before the app opens:
  1. account     an .edu email and a password, plus agreeing to the beta terms
  2. verified    a 6-digit code sent to that email (10 minutes, 5 tries, resend after 30 s)
  3. profile     what Vigil is for: home, business (what kind), enterprise, research or education, and what to watch
  4. ai key      an Anthropic API key, checked against Anthropic before it is accepted
Everything is stored in the local database. Passwords are scrypt hashes; codes and session tokens are stored
hashed, never in plain text.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time

import httpx

from .db import DB

log = logging.getLogger("vigil.accounts")

SESSION_DAYS = 30
CODE_TTL_S = 600
CODE_TRIES = 5
RESEND_AFTER_S = 30
LOGIN_TRIES = 8              # failed sign-ins per email per 15 minutes before a pause
EDU = re.compile(r"^[a-z0-9._%+-]+@([a-z0-9-]+\.)+edu(\.[a-z]{2})?$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    pw_hash TEXT NOT NULL,
    created REAL NOT NULL,
    verified REAL,
    consent REAL,
    profile TEXT NOT NULL DEFAULT '{}',
    ai_provider TEXT,
    ai_key TEXT,
    ai_checked REAL,
    onboarded REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created REAL NOT NULL,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS email_codes (
    email TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    sent REAL NOT NULL,
    expires REAL NOT NULL,
    tries INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS login_fails (
    email TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    ts REAL NOT NULL,
    rating INTEGER,
    kind TEXT,
    text TEXT,
    page TEXT
);
"""


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except ValueError:
        return False


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def check_email(email: str) -> str:
    e = normalize_email(email)
    if not EDU.match(e):
        raise AuthError(400, "Use your school email: the Vigil beta is open to .edu addresses.")
    return e


def check_new_password(pw: str) -> None:
    if len(pw or "") < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise AuthError(400, "Use at least 8 characters with at least one letter and one number.")


def mask_key(key: str | None) -> str:
    return f"…{key[-4:]}" if key else ""


class Accounts:
    def __init__(self, db: DB):
        self.db = db
        db._conn.executescript(SCHEMA)

    # ---- users ----------------------------------------------------------------
    def user(self, uid: int) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE id=?", (uid,))

    def public(self, u: dict) -> dict:
        profile = json.loads(u.get("profile") or "{}")
        return {
            "id": u["id"], "email": u["email"], "verified": bool(u["verified"]),
            "profile": profile, "has_profile": bool(profile.get("use")),
            "ai_provider": u["ai_provider"] or "", "ai_key_hint": mask_key(u["ai_key"]),
            "has_ai_key": bool(u["ai_key"] and u["ai_checked"]),
            "onboarded": bool(u["onboarded"]), "next": self.next_step(u),
        }

    @staticmethod
    def next_step(u: dict) -> str:
        if not u["verified"]:
            return "verify"
        if not json.loads(u.get("profile") or "{}").get("use"):
            return "profile"
        if not (u["ai_key"] and u["ai_checked"]):
            return "ai_key"
        if not u["onboarded"]:
            return "camera"
        return "ready"

    def sign_up(self, email: str, password: str, consent: bool) -> dict:
        e = check_email(email)
        check_new_password(password)
        if not consent:
            raise AuthError(400, "Please agree to the beta terms to continue.")
        existing = self.db.one("SELECT * FROM users WHERE email=?", (e,))
        if existing and existing["verified"]:
            raise AuthError(409, "That email already has an account. Sign in instead.")
        if existing:  # never verified: let them start over with a new password
            self.db.execute("UPDATE users SET pw_hash=?, consent=? WHERE id=?",
                            (hash_password(password), time.time(), existing["id"]))
            return self.user(existing["id"])  # type: ignore[return-value]
        cur = self.db.execute("INSERT INTO users(email, pw_hash, created, consent) VALUES (?,?,?,?)",
                              (e, hash_password(password), time.time(), time.time()))
        return self.user(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def sign_in(self, email: str, password: str) -> dict:
        e = normalize_email(email)
        recent = self.db.one("SELECT COUNT(*) AS n FROM login_fails WHERE email=? AND ts > ?", (e, time.time() - 900))
        if recent and recent["n"] >= LOGIN_TRIES:
            raise AuthError(429, "Too many attempts. Wait 15 minutes and try again.")
        u = self.db.one("SELECT * FROM users WHERE email=?", (e,))
        if not u or not check_password(password, u["pw_hash"]):
            self.db.execute("INSERT INTO login_fails(email, ts) VALUES (?,?)", (e, time.time()))
            raise AuthError(401, "Wrong email or password.")
        self.db.execute("DELETE FROM login_fails WHERE email=?", (e,))
        return u

    # ---- sessions -------------------------------------------------------------
    def new_session(self, uid: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.db.execute("INSERT INTO sessions(token_hash, user_id, created, expires) VALUES (?,?,?,?)",
                        (_sha(token), uid, now, now + SESSION_DAYS * 86400))
        return token

    def session_user(self, token: str | None) -> dict | None:
        if not token:
            return None
        s = self.db.one("SELECT * FROM sessions WHERE token_hash=? AND expires > ?", (_sha(token), time.time()))
        return self.user(s["user_id"]) if s else None

    def end_session(self, token: str | None) -> None:
        if token:
            self.db.execute("DELETE FROM sessions WHERE token_hash=?", (_sha(token),))

    # ---- email verification -----------------------------------------------------
    def send_code(self, u: dict) -> dict:
        from . import mail

        row = self.db.one("SELECT * FROM email_codes WHERE email=?", (u["email"],))
        if row and time.time() - row["sent"] < RESEND_AFTER_S:
            raise AuthError(429, f"A code was just sent. You can ask for a new one in "
                                 f"{int(RESEND_AFTER_S - (time.time() - row['sent'])) + 1} s.")
        code = f"{secrets.randbelow(10**6):06d}"
        now = time.time()
        self.db.execute("INSERT OR REPLACE INTO email_codes(email, code_hash, sent, expires, tries) VALUES (?,?,?,?,0)",
                        (u["email"], _sha(u["email"] + code), now, now + CODE_TTL_S))
        delivery = mail.send(
            u["email"], "Your Vigil verification code",
            f"Your Vigil code is {code}\n\nIt expires in 10 minutes. If you didn't sign up for the Vigil beta, "
            "ignore this email.\n\n— Vigil",
            code_for_log=code)
        return {"delivery": delivery}

    def verify(self, u: dict, code: str) -> dict:
        row = self.db.one("SELECT * FROM email_codes WHERE email=?", (u["email"],))
        if not row or row["expires"] < time.time():
            raise AuthError(400, "That code expired. Ask for a new one.")
        if row["tries"] >= CODE_TRIES:
            raise AuthError(429, "Too many wrong codes. Ask for a new one.")
        if not hmac.compare_digest(_sha(u["email"] + (code or "").strip()), row["code_hash"]):
            self.db.execute("UPDATE email_codes SET tries=tries+1 WHERE email=?", (u["email"],))
            raise AuthError(400, "That code isn't right. Check the email and try again.")
        self.db.execute("DELETE FROM email_codes WHERE email=?", (u["email"],))
        self.db.execute("UPDATE users SET verified=? WHERE id=?", (time.time(), u["id"]))
        return self.user(u["id"])  # type: ignore[return-value]

    # ---- onboarding -----------------------------------------------------------
    def set_profile(self, u: dict, profile: dict) -> dict:
        use = str(profile.get("use") or "").strip()
        if use not in ("home", "business", "enterprise", "research", "education"):
            raise AuthError(400, "Pick what you're using Vigil for.")
        clean = {
            "use": use,
            "business_type": str(profile.get("business_type") or "").strip()[:80],
            "cameras": str(profile.get("cameras") or "").strip()[:40],
            "goals": str(profile.get("goals") or "").strip()[:1000],
            "role": str(profile.get("role") or "").strip()[:80],
            "org": str(profile.get("org") or "").strip()[:120],
        }
        if use in ("business", "enterprise") and not clean["business_type"]:
            raise AuthError(400, "Tell us what kind of business it is.")
        if len(clean["goals"]) < 10:
            raise AuthError(400, "Describe at least one thing you'd like Vigil to watch for.")
        self.db.execute("UPDATE users SET profile=? WHERE id=?", (json.dumps(clean), u["id"]))
        return self.user(u["id"])  # type: ignore[return-value]

    def set_ai_key(self, u: dict, provider: str, key: str) -> dict:
        provider = (provider or "anthropic").strip().lower()
        key = (key or "").strip()
        if provider != "anthropic":
            raise AuthError(400, "Only Anthropic keys are supported in this beta.")
        if not key.startswith("sk-ant-") or len(key) < 30:
            raise AuthError(400, "That doesn't look like an Anthropic API key (it starts with sk-ant-).")
        check_anthropic_key(key)
        self.db.execute("UPDATE users SET ai_provider=?, ai_key=?, ai_checked=? WHERE id=?",
                        (provider, key, time.time(), u["id"]))
        use_key(key)
        return self.user(u["id"])  # type: ignore[return-value]

    def finish(self, u: dict) -> dict:
        if self.next_step(u) not in ("camera", "ready"):
            raise AuthError(400, "Finish the earlier steps first.")
        self.db.execute("UPDATE users SET onboarded=? WHERE id=?", (time.time(), u["id"]))
        return self.user(u["id"])  # type: ignore[return-value]

    def latest_key(self) -> str | None:
        row = self.db.one("SELECT ai_key FROM users WHERE ai_key IS NOT NULL AND ai_checked IS NOT NULL "
                          "ORDER BY ai_checked DESC LIMIT 1")
        return row["ai_key"] if row else None

    # ---- feedback -------------------------------------------------------------
    def add_feedback(self, u: dict | None, rating: int | None, kind: str, text: str, page: str) -> dict:
        text = (text or "").strip()[:4000]
        if not text and rating is None:
            raise AuthError(400, "Add a rating or a few words.")
        if rating is not None and not 1 <= int(rating) <= 5:
            raise AuthError(400, "Ratings go from 1 to 5.")
        cur = self.db.execute("INSERT INTO feedback(user_id, ts, rating, kind, text, page) VALUES (?,?,?,?,?,?)",
                              (u["id"] if u else None, time.time(), rating, (kind or "general")[:30], text,
                               (page or "")[:200]))
        return {"id": cur.lastrowid}

    def feedback(self, limit: int = 200) -> list[dict]:
        return self.db.all("SELECT f.*, u.email FROM feedback f LEFT JOIN users u ON u.id=f.user_id "
                           "ORDER BY f.ts DESC LIMIT ?", (limit,))


def check_anthropic_key(key: str) -> None:
    """Ask Anthropic whether the key works (lists models; costs nothing)."""
    try:
        r = httpx.get("https://api.anthropic.com/v1/models", timeout=10,
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    except httpx.HTTPError as exc:
        raise AuthError(502, f"Couldn't reach Anthropic to check the key ({exc.__class__.__name__}). "
                             "Check your internet connection.") from exc
    if r.status_code in (401, 403):
        raise AuthError(400, "Anthropic didn't accept that key. Check it on console.anthropic.com.")
    if r.status_code >= 400:
        raise AuthError(502, f"Anthropic returned an error ({r.status_code}) while checking the key.")


def use_key(key: str | None) -> None:
    """Make the brain use this key (the Claude client reads it from the environment)."""
    if not key:
        return
    os.environ["ANTHROPIC_API_KEY"] = key
    from . import brain

    b = brain._brains.get("anthropic")
    if b is not None:
        b._client = None  # rebuilt with the new key on its next call
