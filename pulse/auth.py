"""Login: staff passwords (works with no email server) and optional magic links.

Sessions are signed cookies. Each request resolves the email to a current staff
row or the allowlist, so removing someone signs them out and two employees never
share a session.
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import smtplib
import time
from email.message import EmailMessage

from . import store
from .config import allowed_emails, env

log = logging.getLogger("pulse.auth")
COOKIE = "hp_session"
LINK_TTL = 15 * 60
SESSION_TTL = 30 * 24 * 3600
PBKDF2_ROUNDS = 210_000
MIN_PASSWORD = 8
_last_request = {}
_login_failures = {}
_dummy_hash = None


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


def _dummy():
    """A real hash so a missing account takes about as long as a wrong password."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("dummy-password-not-used")
    return _dummy_hash


def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${_b64(salt)}${_b64(dk)}"


def verify_password(password, stored):
    try:
        algo, rounds, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(rounds))
        return hmac.compare_digest(_b64(check), digest)
    except (ValueError, TypeError, AttributeError):
        return False


def role_for(email):
    """Active staff role, else allowlist membership. An inactive row blocks the allowlist too."""
    email = (email or "").strip().lower()
    if not email:
        return None
    row = store.get_staff(email)
    if row:
        return row["role"] if row["active"] else None
    if email in allowed_emails():
        admin = (env("APP_ADMIN_EMAIL") or "").strip().lower()
        return "admin" if admin and email == admin else "staff"
    return None


def is_allowed(email):
    return role_for(email) is not None


def session_user(cookie):
    """The signed-in person, or None. The role is read live so a removal applies immediately."""
    if env("PULSE_DEV_NO_AUTH") == "1":
        return {"email": "dev@localhost", "role": "admin", "name": "Dev"}
    if not cookie:
        return None
    p = unsign(cookie, "session")
    if not p:
        return None
    email = (p.get("e") or "").strip().lower()
    role = role_for(email)
    if not role:
        return None
    row = store.get_staff(email)
    return {"email": email, "role": role, "name": (row or {}).get("name") or email}


def make_link_token(email):
    return sign({"p": "link", "e": email.strip().lower(), "n": secrets.token_hex(16), "exp": int(time.time()) + LINK_TTL})


def make_session(email):
    return sign({"p": "session", "e": email, "exp": int(time.time()) + SESSION_TTL})


def session_email(cookie):
    user = session_user(cookie)
    return user["email"] if user else None


def login_throttled(email, limit=8, window=15 * 60):
    now = time.time()
    hits = [t for t in _login_failures.get(email, []) if now - t < window]
    _login_failures[email] = hits
    return len(hits) >= limit


def note_login_failure(email):
    _login_failures.setdefault(email, []).append(time.time())


def clear_login_failures(email):
    _login_failures.pop(email, None)


def check_password(email, password):
    """True, False, or 'throttled'. Unknown and inactive accounts fail the same way."""
    email = (email or "").strip().lower()
    if not email or login_throttled(email):
        if email:
            note_login_failure(email)
        return "throttled" if email and login_throttled(email) else False
    row = store.get_staff(email)
    hashed = row["password_hash"] if row and row["active"] and row.get("password_hash") else _dummy()
    ok = bool(password) and verify_password(password, hashed)
    if row and row["active"] and row.get("password_hash") and ok:
        clear_login_failures(email)
        return True
    note_login_failure(email)
    return False


def bootstrap_admin():
    """Create the first admin from env when that email has no staff row yet. Never logs the password."""
    email = (env("APP_ADMIN_EMAIL") or "").strip().lower()
    password = env("APP_ADMIN_PASSWORD") or ""
    if not email or not password:
        return None
    if len(password) < MIN_PASSWORD:
        log.error("APP_ADMIN_PASSWORD is shorter than %s characters; admin was not created", MIN_PASSWORD)
        return None
    if store.get_staff(email):
        return None
    store.upsert_staff(email, name=email.split("@")[0], role="admin", password_hash=hash_password(password), active=True)
    log.warning("created admin account %s", email)
    return email


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
