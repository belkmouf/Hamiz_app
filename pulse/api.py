"""FastAPI app: login, read endpoints, staff admin, and the built PWA as static files.

  GET /api/reports          the four report documents + sync status + daily pulse
  GET /api/ads?window=...   Meta spend joined to Odoo orders (today | yesterday | last7)
  GET /api/status           sync status only (cheap; the app polls it)
  GET /api/me               the signed-in employee
"""
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, store
from .adjoin import join
from .config import DZ, STALE_MINUTES, env, fx
from .metrics import snapshot

log = logging.getLogger("pulse.api")

WEB = Path(env("PULSE_WEB_DIR", str(Path(__file__).resolve().parent.parent / "web")))
WINDOWS = {"today": (0, 0), "yesterday": (1, 1), "last7": (6, 0)}

@asynccontextmanager
async def lifespan(_app):
    try:
        auth.bootstrap_admin()
    except Exception:
        log.exception("admin bootstrap failed")
    # An empty store shows the example documents (amber "Example data") until the first real sync.
    if env("PULSE_SEED_ON_EMPTY", "1") == "1":
        from .sync import seed
        seed(log=lambda *_: None)
    yield


app = FastAPI(title="Hamiz Pulse", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Render's health check hits the container over HTTP and does not follow a redirect to https.
    forwarded = request.headers.get("x-forwarded-proto", request.url.scheme)
    if (env("PULSE_FORCE_HTTPS") == "1" and forwarded == "http" and request.url.path != "/healthz"):
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if env("PULSE_FORCE_HTTPS") == "1":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/auth/") or path in ("/", "/login"):
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


def user(request: Request):
    person = auth.session_user(request.cookies.get(auth.COOKIE))
    if not person:
        raise HTTPException(401, "login required")
    return person


def admin(person: dict = Depends(user)):
    if person["role"] != "admin":
        raise HTTPException(403, "admin required")
    return person


def _session_cookie(resp, email):
    resp.set_cookie(auth.COOKIE, auth.make_session(email), max_age=auth.SESSION_TTL, httponly=True,
                    secure=env("PULSE_FORCE_HTTPS") == "1", samesite="lax", path="/")
    return resp


# ---------------------------------------------------------------- status
def _age_minutes(iso):
    if not iso:
        return None
    return round((datetime.now(DZ) - datetime.fromisoformat(iso)).total_seconds() / 60)


def sync_status(reports=None):
    runs = store.last_runs()
    reports = reports if reports is not None else store.load_reports()
    meta = (reports.get("summary") or {}).get("meta") or {}
    odoo_last = runs["odoo"]["last"]
    age = _age_minutes(meta.get("generated_at"))
    if not meta:
        state = "empty"
    elif meta.get("example"):
        state = "example"
    elif odoo_last and odoo_last["ok"] is False:
        state = "failed"
    elif age is not None and age > STALE_MINUTES:
        state = "stale"
    else:
        state = "live"
    odoo_ok = (runs["odoo"].get("last_ok") or {}) if runs.get("odoo") else {}
    meta_ok = (runs["meta"].get("last_ok") or {}) if runs.get("meta") else {}
    return {
        "state": state, "generated_at": meta.get("generated_at"), "age_minutes": age,
        "example": bool(meta.get("example")), "stale_after_minutes": STALE_MINUTES,
        "odoo": runs["odoo"], "meta": runs["meta"],
        "last_synced_at": meta.get("generated_at"),
        "odoo_synced_at": odoo_ok.get("finished_at"),
        "meta_synced_at": meta_ok.get("finished_at"),
        "server_time": datetime.now(DZ).isoformat(timespec="seconds"),
    }


def build_pulse():
    """Official daily answers: 7 full Algiers days for the order goal, today for the spend ratio."""
    today = datetime.now(DZ).date()
    start = today - timedelta(days=7)
    return snapshot(today, store.attribution_between(start, today), store.spend_between(start, today), fx=fx())


@app.get("/api/me")
def api_me(person: dict = Depends(user)):
    return {"email": person["email"], "name": person["name"], "role": person["role"]}


@app.get("/api/status")
def api_status(_: dict = Depends(user)):
    return sync_status()


@app.get("/api/reports")
def api_reports(_: dict = Depends(user)):
    docs = store.load_reports()
    return {**{k: docs.get(k) for k in ("summary", "sellers", "products", "orders")},
            "sync": sync_status(docs), "pulse": build_pulse()}


@app.get("/api/ads")
def api_ads(window: str = Query("today", pattern="^(today|yesterday|last7)$"), _: dict = Depends(user)):
    today = datetime.now(DZ).date()
    back, fwd = WINDOWS[window]
    start, end = today - timedelta(days=back), today - timedelta(days=fwd)
    spend_rows = store.spend_between(start, end)
    orders = store.attribution_between(start, end)
    spend, groups, other, members = join(spend_rows, orders)
    account = store.load_reports().get("meta_account") or {}
    first = store.first_spend_dates()
    days_running = {}
    for name in set(spend) | set(groups):
        ads = members.get(name) or [name]
        starts = [first[a] for a in ads if a in first]
        if starts:
            d0 = min(starts)
            d0 = d0 if isinstance(d0, date) else date.fromisoformat(str(d0))
            days_running[name] = (today - d0).days  # full days before today
    return {
        "window": window, "start": start.isoformat(), "end": end.isoformat(),
        "spend": {k: round(v, 2) for k, v in spend.items()}, "groups": groups,
        "days_running": days_running, "other_channels": other,
        "has_spend": bool(spend_rows), "has_orders": bool(orders),
        "currency": account.get("currency"), "timezone_name": account.get("timezone_name"),
        "timezone_offset_hours_utc": account.get("timezone_offset_hours_utc"),
        "sync": sync_status(),
    }


# ---------------------------------------------------------------- auth
@app.get("/login")
def login_page():
    return FileResponse(WEB / "login.html", headers={"Cache-Control": "no-store"})


@app.post("/auth/request")
async def auth_request(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    email = str((body or {}).get("email") or "").strip().lower()
    if email and auth.is_allowed(email) and not auth.throttled(email):
        base = env("APP_BASE_URL") or str(request.base_url).rstrip("/")
        auth.send_link(email, f"{base}/auth/verify?token={quote(auth.make_link_token(email))}")
    # Same answer either way, so the page cannot be used to test which addresses are allowed.
    return {"ok": True, "message": "If this address is on the list, a sign-in link is on its way."}


@app.post("/auth/login")
async def auth_login(request: Request):
    """Password sign-in. Same error for an unknown email and a wrong password."""
    try:
        body = await request.json()
    except ValueError:
        body = {}
    email = str((body or {}).get("email") or "").strip().lower()
    password = str((body or {}).get("password") or "")
    result = auth.check_password(email, password)
    if result is not True:
        code = "throttled" if result == "throttled" else "invalid_login"
        return JSONResponse({"ok": False, "error": code}, status_code=401)
    return _session_cookie(JSONResponse({"ok": True}), email)


@app.get("/auth/verify")
def auth_verify(token: str = ""):
    p = auth.unsign(token, "link")
    if not p or not auth.is_allowed(p["e"]) or not store.spend_token(p["n"]):
        return RedirectResponse("/login?error=link", status_code=303)
    return _session_cookie(RedirectResponse("/", status_code=303), p["e"])


@app.post("/auth/logout")
def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


# ---------------------------------------------------------------- app shell
@app.get("/")
def index(request: Request):
    if not auth.session_email(request.cookies.get(auth.COOKIE)):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def service_worker():
    return FileResponse(WEB / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _clean_email(value):
    email = str(value or "").strip().lower()
    if "@" not in email or len(email) > 255:
        raise HTTPException(400, "invalid_email")
    return email


@app.get("/api/staff")
def staff_list(_: dict = Depends(admin)):
    return {"staff": [s for s in store.list_staff() if s["active"]]}


@app.post("/api/staff")
async def staff_save(request: Request, _: dict = Depends(admin)):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    body = body or {}
    email = _clean_email(body.get("email"))
    role = body.get("role") or "staff"
    if role not in ("admin", "staff"):
        raise HTTPException(400, "invalid_role")
    password = str(body.get("password") or "")
    existing = store.get_staff(email)
    if existing and existing["active"] and existing["role"] == "admin" and role != "admin" and store.count_active_admins() <= 1:
        raise HTTPException(400, "last_admin")
    if password and len(password) < auth.MIN_PASSWORD:
        raise HTTPException(400, "password_too_short")
    if not existing and len(password) < auth.MIN_PASSWORD:
        raise HTTPException(400, "password_too_short")
    store.upsert_staff(email, name=str(body.get("name") or ""), role=role,
                       password_hash=auth.hash_password(password) if password else None, active=True)
    return {"ok": True}


@app.delete("/api/staff/{email}")
def staff_remove(email: str, person: dict = Depends(admin)):
    email = _clean_email(email)
    if email == person["email"]:
        raise HTTPException(400, "cannot_remove_self")
    row = store.get_staff(email)
    if row and row["active"] and row["role"] == "admin" and store.count_active_admins() <= 1:
        raise HTTPException(400, "last_admin")
    if not row:
        # Block an allowlist-only address by recording an inactive row.
        store.upsert_staff(email, name="", role="staff", active=False)
        return {"ok": True}
    if row["active"] and row["role"] == "admin" and store.count_active_admins() <= 1:
        raise HTTPException(400, "last_admin")
    store.deactivate_staff(email)
    return {"ok": True}


@app.get("/api/admin/reconcile")
def api_reconcile(day: str = Query(..., alias="date"), _: dict = Depends(admin)):
    """One Algiers day, stored figures against a live Odoo and Meta query. Admin only."""
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    from .reconcile import reconcile
    try:
        diffs, report = reconcile(parsed, log=lambda *_: None)
    except Exception as e:
        raise HTTPException(503, f"cannot reach Odoo or Meta: {type(e).__name__}: {e}")
    return {"date": parsed.isoformat(), "ok": not diffs, "discrepancies": diffs, "report": report}


app.mount("/", StaticFiles(directory=WEB), name="web")
