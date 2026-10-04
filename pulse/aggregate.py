"""Pure aggregation: normalised orders + lines -> the four report documents (PRD section 6).

Ported from reference/odoo_sync.py without changing the math; tests check parity on the
reference --selftest input. Additions for this build are below the port.
"""
import json
from collections import defaultdict
from datetime import timedelta

from .config import MAX_DOC, ORDERS_KEEP, TZ_NAME


def aggregate(orders, lines, now, mapping):
    """orders: dicts with ref, magento, dt(local datetime), total, stage, customer, store, sellers(list),
    salesperson, source, campaign, wilaya. lines: dicts with order_ref, product, qty, amount, seller, category."""
    today = now.date()
    by_day = defaultdict(lambda: {"o": 0, "g": 0.0, "c": 0, "cg": 0.0, "d": 0})
    for o in orders:
        b = by_day[o["dt"].date()]
        b["o"] += 1
        b["g"] += o["total"]
        if o["stage"] == "cancelled":
            b["c"] += 1
            b["cg"] += o["total"]
        if o["stage"] == "delivered":
            b["d"] += 1

    def window(start, end):  # inclusive dates
        sel = [o for o in orders if start <= o["dt"].date() <= end]
        n = len(sel)
        g = sum(o["total"] for o in sel)
        canc = [o for o in sel if o["stage"] == "cancelled"]
        live = [o for o in sel if o["stage"] != "cancelled"]
        st = defaultdict(int)
        for o in sel:
            st[o["stage"]] += 1
        resolved = n - st["pending"]
        conf = st["confirmed"] + st["delivered"] + st["returned"]
        shipped_done = st["delivered"] + st["returned"]
        return {
            "orders": n, "gmv": round(g), "aov": round(g / n) if n else 0,
            "net_gmv": round(sum(o["total"] for o in live)),
            "cancel_rate": round(len(canc) / n, 4) if n else 0,
            "cancel_rate_value": round(sum(o["total"] for o in canc) / g, 4) if g else 0,
            "stages": dict(st),
            "confirm_rate": round(conf / resolved, 4) if resolved else None,
            "delivery_rate": round(st["delivered"] / shipped_done, 4) if shipped_done else None,
            "orders_per_day": round(n / ((end - start).days + 1), 1),
        }

    d = lambda k: today - timedelta(days=k)
    kpis = {
        "today": window(today, today),
        "yesterday": window(d(1), d(1)),
        "last7": window(d(6), today),
        "prev7": window(d(13), d(7)),
        "last30": window(d(29), today),
        "prev30": window(d(59), d(30)),
    }
    days = [d(k) for k in range(89, -1, -1)]
    daily = [{"date": x.isoformat(), **{k: (round(v) if k in ("g", "cg") else v) for k, v in by_day[x].items()}} for x in days]

    last30 = [o for o in orders if o["dt"].date() >= d(29)]

    def group(key_fn, items, top=None):
        g = defaultdict(lambda: {"orders": 0, "gmv": 0.0, "cancelled": 0, "delivered": 0, "confirmed": 0})
        for o in items:
            for k in key_fn(o):
                r = g[k or "Unknown"]
                r["orders"] += 1
                r["gmv"] += o["total"] / max(1, len(key_fn(o))) if o.get("_split") else o["total"]
                r["cancelled"] += o["stage"] == "cancelled"
                r["delivered"] += o["stage"] == "delivered"
                r["confirmed"] += o["stage"] in ("confirmed", "delivered", "returned")
        rows = [{"name": k, **{kk: (round(vv) if kk == "gmv" else vv) for kk, vv in v.items()}} for k, v in g.items()]
        rows.sort(key=lambda r: -r["gmv"])
        return rows[:top] if top else rows

    hours = [0] * 24
    weekdays = [[0] * 24 for _ in range(7)]
    for o in last30:
        hours[o["dt"].hour] += 1
        weekdays[o["dt"].weekday()][o["dt"].hour] += 1

    summary = {
        "kpis": kpis, "daily": daily,
        "stores": group(lambda o: [o.get("store")], last30, 30),
        "salespeople": group(lambda o: [o.get("salesperson")], last30, 30),
        "utm": group(lambda o: [" / ".join(x for x in (o.get("source"), o.get("campaign")) if x) or None], last30, 60),
        "wilayas": group(lambda o: [o.get("wilaya")], last30, 60) if mapping.get("wilaya") else [],
        "hours": hours, "weekday_hours": weekdays,
        "has_customer": sum(1 for o in last30 if o.get("customer")),
    }

    # sellers: from lines when lines carry a seller, else split order total across order sellers
    ref_stage = {o["ref"]: o["stage"] for o in last30}
    if lines and any(l.get("seller") for l in lines):
        g = defaultdict(lambda: {"orders": set(), "gmv": 0.0, "cancelled": set(), "delivered": set(), "items": 0})
        for l in lines:
            if l["order_ref"] not in ref_stage:
                continue
            r = g[l.get("seller") or "Unknown"]
            st = ref_stage[l["order_ref"]]
            r["orders"].add(l["order_ref"])
            r["gmv"] += l["amount"]
            r["items"] += l["qty"]
            if st == "cancelled":
                r["cancelled"].add(l["order_ref"])
            if st == "delivered":
                r["delivered"].add(l["order_ref"])
        sellers = [{"name": k, "orders": len(v["orders"]), "gmv": round(v["gmv"]), "items": round(v["items"]),
                    "cancelled": len(v["cancelled"]), "delivered": len(v["delivered"])} for k, v in g.items()]
        sellers.sort(key=lambda r: -r["gmv"])
        seller_basis = "order lines"
    else:
        for o in last30:
            o["_split"] = True
        sellers = group(lambda o: o.get("sellers") or [None], last30)
        seller_basis = "order total split evenly across sellers"
    # products
    pg = defaultdict(lambda: {"qty": 0.0, "revenue": 0.0, "orders": set(), "cancelled": set(), "category": None})
    for l in lines:
        if l["order_ref"] not in ref_stage:
            continue
        r = pg[l["product"] or "Unknown"]
        r["qty"] += l["qty"]
        r["revenue"] += l["amount"]
        r["orders"].add(l["order_ref"])
        r["category"] = r["category"] or l.get("category")
        if ref_stage[l["order_ref"]] == "cancelled":
            r["cancelled"].add(l["order_ref"])
    products = [{"name": k, "qty": round(v["qty"]), "revenue": round(v["revenue"]), "orders": len(v["orders"]),
                 "cancelled": len(v["cancelled"]), "category": v["category"]} for k, v in pg.items()]
    products.sort(key=lambda r: -r["revenue"])

    latest = sorted(orders, key=lambda o: o["dt"], reverse=True)
    order_rows = [{"ref": o["ref"], "mg": o.get("magento"), "dt": o["dt"].strftime("%Y-%m-%d %H:%M"),
                   "cu": o.get("customer"), "t": round(o["total"]), "st": o["stage"], "raw": o.get("status_raw"),
                   "so": o.get("store"), "se": ", ".join(o.get("sellers") or [])[:80]} for o in latest]

    meta = {"generated_at": now.isoformat(timespec="minutes"), "timezone": TZ_NAME,
            "orders_scanned": len(orders), "lines_scanned": len(lines), "seller_basis": seller_basis,
            "fields": mapping, "example": False}
    return {
        "summary": {"meta": meta, **summary},
        "sellers": {"meta": meta, "rows": sellers},
        "products": {"meta": meta, "rows": products},
        "orders": {"meta": meta, "rows": order_rows},
    }


def fit(doc, list_key):
    """Trim a document's list until it serialises under MAX_DOC bytes."""
    while len(json.dumps(doc, ensure_ascii=False).encode()) > MAX_DOC and doc[list_key]:
        doc[list_key] = doc[list_key][: int(len(doc[list_key]) * 0.8)]
        doc["meta"] = {**doc["meta"], "trimmed": True}
    return doc


def finalize(docs):
    docs["sellers"] = fit(docs["sellers"], "rows")
    docs["products"] = fit(docs["products"], "rows")
    docs["orders"]["rows"] = docs["orders"]["rows"][:ORDERS_KEEP]
    docs["orders"] = fit(docs["orders"], "rows")
    return docs


def doc_size(doc):
    return len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode())


def attribution(orders, now, days=30):
    """One row per order placed in the last `days` days, for joining Meta spend to Odoo orders.
    `ad` is the order's utm_content (the Meta ad name), `campaign` and `source` its UTM campaign and source."""
    since = now.date() - timedelta(days=days - 1)
    return [{"ref": o["ref"], "date": o["dt"].date().isoformat(), "ad": (o.get("utm_content") or None),
             "campaign": o.get("campaign"), "source": o.get("source"), "stage": o["stage"], "total": round(float(o["total"]), 2)}
            for o in orders if o["dt"].date() >= since]
