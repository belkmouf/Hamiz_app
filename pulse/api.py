"""FastAPI app: login, three read endpoints, and the built PWA as static files.

  GET /api/reports          the four report documents + sync status
  GET /api/ads?window=...   Meta spend joined to Odoo orders (today | yesterday | last7)
  GET /api/status           sync status only (cheap; the app polls it)
"""
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
from .config import DZ, STALE_MINUTES, env

WEB = Path(env("PULSE_WEB_DIR", str(Path(__file__).resolve().parent.parent / "web")))
WINDOWS = {"today": (0, 0), "yesterday": (1, 1), "last7": (6, 0)}

@asynccontextmanager
async def lifespan(_app):
    # An empty store shows the example documents (amber "Example data") until the first real sync.
    if env("PULSE_SEED_ON_EMPTY", "1") == "1":
        from .sync import seed
        seed(log=lambda *_: None)
    yield


app = FastAPI(title="Hamiz Pulse", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if env("PULSE_FORCE_HTTPS") == "1" and request.headers.get("x-forwarded-proto", request.url.scheme) == "http":
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if env("PULSE_FORCE_HTTPS") == "1":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def user(request: Request):
    email = auth.session_email(request.cookies.get(auth.COOKIE))
    if not email:
        raise HTTPException(401, "login required")
    return email


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
    return {
        "state": state, "generated_at": meta.get("generated_at"), "age_minutes": age,
        "example": bool(meta.get("example")), "stale_after_minutes": STALE_MINUTES,
        "odoo": runs["odoo"], "meta": runs["meta"],
        "server_time": datetime.now(DZ).isoformat(timespec="seconds"),
    }


@app.get("/api/status")
def api_status(_: str = Depends(user)):
    return sync_status()


@app.get("/api/reports")
def api_reports(_: str = Depends(user)):
    docs = store.load_reports()
    return {**{k: docs.get(k) for k in ("summary", "sellers", "products", "orders")}, "sync": sync_status(docs)}


@app.get("/api/ads")
def api_ads(window: str = Query("today", pattern="^(today|yesterday|last7)$"), _: str = Depends(user)):
    today = datetime.now(DZ).date()
    back, fwd = WINDOWS[window]
    start, end = today - timedelta(days=back), today - timedelta(days=fwd)
    spend_rows = store.spend_between(start, end)
    orders = store.attribution_between(start, end)
    spend, groups, other, members = join(spend_rows, orders)
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


@app.get("/auth/verify")
def auth_verify(token: str = ""):
    p = auth.unsign(token, "link")
    if not p or not auth.is_allowed(p["e"]) or not store.spend_token(p["n"]):
        return RedirectResponse("/login?error=link", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_session(p["e"]), max_age=auth.SESSION_TTL, httponly=True,
                    secure=env("PULSE_FORCE_HTTPS") == "1", samesite="lax", path="/")
    return resp


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


app.mount("/", StaticFiles(directory=WEB), name="web")
