"""Order stage rules (PRD section 4). Single source of truth for the backend."""
import unicodedata
from datetime import datetime, timezone

from .config import DZ

STAGES = ("pending", "confirmed", "delivered", "returned", "cancelled")
CONFIRMED_OR_LATER = ("confirmed", "delivered", "returned")


def classify(state, status):
    """Map Odoo state + Magento/custom status text to one of the 5 stages."""
    # Accents are folded first so "Expédiée" matches "expedi" (the reference matched raw text only).
    s = "".join(c for c in unicodedata.normalize("NFKD", status or "") if not unicodedata.combining(c)).lower()
    if state == "cancel" or any(k in s for k in ("cancel", "annul", "refus", "fraud")):
        return "returned" if any(k in s for k in ("return", "retour", "refus")) else "cancelled"
    if any(k in s for k in ("return", "retour", "rto")):
        return "returned"
    if any(k in s for k in ("deliver", "livr", "complete", "closed")):
        return "delivered"
    if state in ("sale", "done") or any(k in s for k in ("process", "confirm", "ship", "expedi")):
        return "confirmed"
    return "pending"


def to_local(dt_str):
    """Odoo stores date_order as naive UTC 'YYYY-MM-DD HH:MM:SS'. Return Algiers local time."""
    return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(DZ)
