"""Settings, read from environment variables only. Secrets never reach the frontend."""
import json
import os
from datetime import timedelta, timezone

DZ = timezone(timedelta(hours=1))  # Africa/Algiers, UTC+1, no DST
TZ_NAME = "Africa/Algiers"

MAX_DOC = 250_000          # bytes per stored report document
ORDERS_KEEP = 400          # rows in the orders document
STALE_MINUTES = 150        # sync older than this shows red
GOAL_LOW = 200             # orders placed per day
GOAL_HIGH = 250
SPEND_CAP = 0.05           # ad spend / merchandise order value

# Labels from the Hamiz sale.order export, matched case-insensitively against fields_get labels.
ORDER_LABELS = {
    "magento_id": ["magento order id"],
    "sellers": ["sellers", "seller"],
    "store": ["store based id", "store"],
    "status": ["order status", "magento status", "order state", "status"],
    "wilaya": ["wilaya", "state", "region"],
    "utm_content": ["utm content", "utm_content", "ad name"],
}
LINE_LABELS = {
    "seller": ["seller", "sellers", "vendor"],
    "status": ["order status", "order state", "status"],
    "category": ["product category", "category"],
}


def _labels(env_key, defaults):
    """Defaults, overridden per key by a JSON object in the env, e.g. {"wilaya": ["wilaya livraison"]}."""
    raw = os.environ.get(env_key)
    if not raw:
        return {k: list(v) for k, v in defaults.items()}
    extra = json.loads(raw)
    out = {k: list(v) for k, v in defaults.items()}
    for k, v in extra.items():
        out[k] = [s.strip().lower() for s in v]
    return out


def order_labels():
    return _labels("PULSE_ORDER_LABELS", ORDER_LABELS)


def line_labels():
    return _labels("PULSE_LINE_LABELS", LINE_LABELS)


def env(key, default=None):
    v = os.environ.get(key)
    return v if v not in (None, "") else default


def database_url():
    url = env("DATABASE_URL", "sqlite:///./pulse.db")
    # Render and Heroku hand out postgres://; SQLAlchemy wants postgresql+psycopg://
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def allowed_emails():
    return {e.strip().lower() for e in (env("APP_ALLOWED_EMAILS", "") or "").split(",") if e.strip()}


def fx():
    """DZD the business pays per 1 USD of Meta spend. Not the official rate."""
    try:
        return float(env("PULSE_FX", "250"))
    except (TypeError, ValueError):
        return 250.0
