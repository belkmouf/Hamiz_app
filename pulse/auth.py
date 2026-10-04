"""Email magic-link login limited to APP_ALLOWED_EMAILS. Signed, expiring, single-use links; signed session cookie."""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import smtplib
import time
from email.message import EmailMessage

from .config import allowed_emails, env

log = logging.getLogger("pulse.auth")
COOKIE = "hp_session"
LINK_TTL = 15 * 60
SESSION_TTL = 30 * 24 * 3600
_last_request = {}


def _secret():
    s = env("APP_SECRET_KEY")
    if not s:
        if env("PULSE_DEV_NO_AUTH") == "1":
            return b"dev-only-secret"
        raise RuntimeError("APP_SECRET_KEY is not set")
    return s.encode()


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(payload):
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def unsign(token, purpose):
    """Payload dict if the signature is valid, the purpose matches and it has not expired; else None."""
    try:
        body, mac = token.split(".", 1)
        good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(mac, good):
            return None
        p = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if p.get("p") != purpose or p.get("exp", 0) < time.time():
        return None
    return p


def is_allowed(email):
    return (email or "").strip().lower() in allowed_emails()


def make_link_token(email):
    return sign({"p": "link", "e": email.strip().lower(), "n": secrets.token_hex(16), "exp": int(time.time()) + LINK_TTL})


def make_session(email):
    return sign({"p": "session", "e": email, "exp": int(time.time()) + SESSION_TTL})


def session_email(cookie):
    if env("PULSE_DEV_NO_AUTH") == "1":
        return "dev@localhost"
    if not cookie:
        return None
    p = unsign(cookie, "session")
    return p["e"] if p and is_allowed(p["e"]) else None


def throttled(email, seconds=60):
    now = time.time()
    if now - _last_request.get(email, 0) < seconds:
        return True
    _last_request[email] = now
    return False


def send_link(email, url):
    host = env("SMTP_HOST")
    if not host:
        # No mail server configured: print the link to the server log so an admin can pass it on.
        log.warning("SMTP_HOST not set; login link for %s: %s", email, url)
        print(f"[auth] login link for {email}: {url}", flush=True)
        return
    msg = EmailMessage()
    msg["Subject"] = "Your Hamiz Pulse sign-in link"
    msg["From"] = env("SMTP_FROM", env("SMTP_USER", "pulse@localhost"))
    msg["To"] = email
    msg.set_content(f"Tap to sign in to Hamiz Pulse:\n\n{url}\n\nThe link works once and expires in 15 minutes. "
                    "If you did not ask for it, ignore this email.")
    port = int(env("SMTP_PORT", "587"))
    with (smtplib.SMTP_SSL(host, port, timeout=20) if port == 465 else smtplib.SMTP(host, port, timeout=20)) as s:
        if port != 465:
            s.starttls()
        if env("SMTP_USER"):
            s.login(env("SMTP_USER"), env("SMTP_PASSWORD", ""))
        s.send_message(msg)
