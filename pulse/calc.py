"""CAC budget and Ad review math (PRD sections 4 and 9), mirrored in web/calc.js.

Same formulas as reference/dz_cod_calc.py. Basis names: "raw" = orders placed, "confirmed", "delivered".
"""
from collections import defaultdict

from .stages import classify

INF = float("inf")
LABEL = {"raw": "placed", "confirmed": "confirmed", "delivered": "delivered"}


def basis_mult(basis, c, d):
    """Multiplier converting a per-<basis> cost into a per-confirmed cost."""
    return {"delivered": d, "confirmed": 1.0, "raw": 1.0 / c}[basis]


def to_delivered(t, basis, c, d):
    return {"raw": t * c * d, "confirmed": t * d, "delivered": t}[basis]


def cap_per_confirmed_usd(cac_pct, aov, fx, basis, c, d):
    return cac_pct * aov * basis_mult(basis, c, d) / fx


def cac_budget(aov, c, d, fx, cac_pct=0.05, basis="raw", low=200, high=250):
    per_conf = cac_pct * aov * basis_mult(basis, c, d)
    per_deliv, per_raw = per_conf / d, per_conf * c
    daily = []
    for t in (low, high):
        td = to_delivered(t, "raw", c, d)
        daily.append({"placed": td / (c * d), "confirmed": td / d, "delivered": td,
                      "spend_da": td * per_deliv, "spend_usd": td * per_deliv / fx})
    return {
        "per_placed_da": per_raw, "per_confirmed_da": per_conf, "per_delivered_da": per_deliv,
        "per_placed_usd": per_raw / fx, "per_confirmed_usd": per_conf / fx, "per_delivered_usd": per_deliv / fx,
        "delivered_pct_of_aov": per_deliv / aov, "daily": daily,
    }


def landing_needed(cpm, ctr, per_placed_usd):
    """Landing conversion rate needed to keep Meta CPA <= the cap. ctr as a fraction (0.025)."""
    return (cpm / (1000 * ctr)) / per_placed_usd if per_placed_usd > 0 else INF


def new_group():
    return {"raw": 0, "pending": 0, "conf": 0, "deliv": 0, "val": []}


def add_order(g, stage, value=None):
    """Add one order (stage in the 5-stage vocabulary) to an ad's group."""
    g["raw"] += 1
    if stage == "pending":
        g["pending"] += 1
    if stage in ("confirmed", "delivered", "returned"):
        g["conf"] += 1
        if value:
            g["val"].append(float(value))
    if stage == "delivered":
        g["deliv"] += 1


def decide(name, g, sp, aov_default, fx, cac_pct, basis, c, d, min_confirm=0.5, days_running=None):
    """Score one ad. Returns (decision_code, label, cac_pct_of_aov, aov, confirm_rate).

    Rules in the PRD order. days_running (live mode) holds back CAC and no-order kills before 3 full days.
    """
    raw, pend, conf = g["raw"], g["pending"], g["conf"]
    resolved = raw - pend
    rate = conf / resolved if resolved else 0
    aov = sum(g["val"]) / len(g["val"]) if g["val"] else aov_default
    cap_raw = cac_pct * aov / fx
    if basis == "raw":
        cac = (sp * fx / raw) / aov if raw else INF
    else:
        cac = (sp / conf / basis_mult(basis, c, d)) * fx / aov if conf else INF
    n_basis = raw if basis == "raw" else conf
    young = days_running is not None and days_running < 3
    if name == "UNATTRIBUTED":
        code, label = "fix", "Fix tracking"
    elif raw and pend / raw > 0.5:
        code, label = "wait", "Wait: most orders still pending"
    elif resolved >= 10 and rate < min_confirm:
        code, label = "kill", "Kill: junk orders"
    elif n_basis >= 3 and conf >= 2 and cac <= cac_pct:
        code, label = "promote", "Promote"
    elif n_basis >= 3 and cac > 1.5 * cac_pct and sp >= 2.5 * cap_raw:
        code, label = "kill", f"Kill: CAC {cac:.1%}"
    elif raw == 0 and sp >= 2.5 * cap_raw:
        code, label = "kill", "Kill: no orders"
    else:
        code, label = "wait", "Wait: not enough data"
    if young and code == "kill" and not label.startswith("Kill: junk"):
        code, label = "wait", "Wait: under 3 full days (would " + label.replace("Kill: ", "kill: ") + ")"
    return code, label, cac, aov, rate


def review(spend, groups, aov, fx, cac_pct=0.05, basis="raw", c=0.7, d=0.75, days_running=None):
    """spend: {ad: usd}; groups: {ad: group}. Returns rows sorted by CAC % ascending, plus the account card."""
    days_running = days_running or {}
    rows = []
    for ad in sorted(set(spend) | set(groups)):
        g = groups.get(ad) or new_group()
        sp = spend.get(ad, 0.0)
        code, label, cac, ad_aov, rate = decide(ad, g, sp, aov, fx, cac_pct, basis, c, d,
                                                days_running=days_running.get(ad))
        rows.append({"ad": ad, "spend": sp, "placed": g["raw"], "pending": g["pending"], "confirmed": g["conf"],
                     "confirm_rate": rate, "aov": ad_aov, "cac_pct": cac, "decision": code, "label": label})
    rows.sort(key=lambda r: r["cac_pct"])
    sp_all = sum(r["spend"] for r in rows)
    raw_all = sum(r["placed"] for r in rows)
    conf_all = sum(r["confirmed"] for r in rows)
    vals = [v for g in groups.values() for v in g["val"]]
    avg = sum(vals) / len(vals) if vals else aov
    if basis == "raw":
        blended = sp_all * fx / raw_all / avg if raw_all else INF
    else:
        blended = sp_all * fx / (conf_all / basis_mult(basis, c, d)) / avg if conf_all else INF
    account = {"spend_usd": sp_all, "spend_da": sp_all * fx, "placed": raw_all, "confirmed": conf_all,
               "blended_cac_pct": blended, "ok": blended <= cac_pct,
               "per_delivered_pct": (sp_all * fx / (conf_all * d) / avg) if conf_all else None}
    return rows, account


def groups_from_csv_rows(order_rows):
    """order_rows: dicts with ad_name, status, value (the upload-mode orders CSV)."""
    groups = defaultdict(new_group)
    for r in order_rows:
        ad = (r.get("ad_name") or "").strip() or "UNATTRIBUTED"
        add_order(groups[ad], classify(None, r.get("status")), (r.get("value") or "").strip() or None)
    return dict(groups)
