"""Outgoing email (verification codes). Configure one sender in the environment (vigil/.env):

  SMTP (e.g. a Gmail account with an app password):
    VIGIL_SMTP_HOST=smtp.gmail.com  VIGIL_SMTP_PORT=587  VIGIL_SMTP_USER=you@gmail.com  VIGIL_SMTP_PASS=<app password>
  or Resend (https://resend.com):
    RESEND_API_KEY=re_...  VIGIL_MAIL_FROM="Vigil <verify@yourdomain.com>"

With neither set, nothing is emailed: the code is written to the server log so the team can test locally.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

import httpx

log = logging.getLogger("vigil.mail")


def configured() -> str:
    if os.environ.get("VIGIL_SMTP_HOST") and os.environ.get("VIGIL_SMTP_USER") and os.environ.get("VIGIL_SMTP_PASS"):
        return "smtp"
    if os.environ.get("RESEND_API_KEY") and os.environ.get("VIGIL_MAIL_FROM"):
        return "resend"
    return "log"


def send(to: str, subject: str, text: str, *, code_for_log: str = "") -> str:
    """Send an email. Returns how it went out: smtp | resend | log."""
    how = configured()
    if how == "smtp":
        msg = EmailMessage()
        msg["From"] = os.environ.get("VIGIL_MAIL_FROM") or os.environ["VIGIL_SMTP_USER"]
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        port = int(os.environ.get("VIGIL_SMTP_PORT") or 587)
        with smtplib.SMTP(os.environ["VIGIL_SMTP_HOST"], port, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(os.environ["VIGIL_SMTP_USER"], os.environ["VIGIL_SMTP_PASS"])
            s.send_message(msg)
    elif how == "resend":
        r = httpx.post("https://api.resend.com/emails", timeout=20,
                       headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                       json={"from": os.environ["VIGIL_MAIL_FROM"], "to": [to], "subject": subject, "text": text})
        r.raise_for_status()
    else:
        log.warning("email is not configured; verification code for %s is %s", to, code_for_log or "(none)")
    return how
