#!/usr/bin/env python3
"""Pull Hamiz sales from Odoo (XML-RPC, read-only) and build the JSON documents
the phone app reads: summary, sellers, products, orders.

Env: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_KEY (API key or password).
Usage: python3 odoo_sync.py --out out_dir [--days 90]
       python3 odoo_sync.py --selftest      (aggregation test on synthetic data, no Odoo)
Writes out_dir/{summary,sellers,products,orders}.json, each under 256 KiB.
"""
import argparse
import json
import os
import random
import socket
import sys
import time
import xmlrpc.client
from collections import defaultdict
from datetime import datetime, timedelta, timezone

DZ = timezone(timedelta(hours=1))  # Africa/Algiers, no DST
BATCH = 1000
MAX_DOC = 250_000

# Labels from the Hamiz sale.order export; matched case-insensitively against fields_get labels.
ORDER_LABELS = {
    "magento_id": ["magento order id"],
    "sellers": ["sellers", "seller"],
    "store": ["store based id", "store"],
    "status": ["order status", "magento status", "order state", "status"],
    "wilaya": ["wilaya", "state", "region"],
}
LINE_LABELS = {
    "seller": ["seller", "sellers", "vendor"],
    "status": ["order status", "order state", "status"],
    "category": ["product category", "category"],
}
ORDER_STD = ["name", "date_order", "amount_total", "state", "invoice_status", "partner_id",
             "user_id", "campaign_id", "source_id", "medium_id"]


# ---------------------------------------------------------------- Odoo access
class Odoo:
    def __init__(self, url, db, user, key):
        socket.setdefaulttimeout(60)
        self.url, self.db, self.key = url.rstrip("/"), db, key
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        self.uid = common.authenticate(db, user, key, {})
        if not self.uid:
            sys.exit("Odoo login failed: check ODOO_USER / ODOO_KEY / ODOO_DB")
        self.m = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)

    def call(self, model, method, *args, **kw):
        for attempt in range(4):
            try:
                return self.m.execute_kw(self.db, self.uid, self.key, model, method, list(args), kw)
            except (OSError, xmlrpc.client.ProtocolError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    def fields(self, model):
        return self.call(model, "fields_get", attributes=["string", "type", "relation"])

    def search_read(self, model, domain, fields, order="id asc"):
        out, offset = [], 0
        while True:
            rows = self.call(model, "search_read", domain, fields=fields, offset=offset, limit=BATCH, order=order)
            out += rows
            if len(rows) < BATCH:
                return out
            offset += BATCH
            time.sleep(0.3)  # be gentle with the ERP

    def names(self, model, ids):
        ids, res = list(ids), {}
        for i in range(0, len(ids), BATCH):
            for r in self.call(model, "read", ids[i:i + BATCH], fields=["display_name"]):
                res[r["id"]] = r["display_name"]
        return res


def pick(fields, wanted, prefer_custom=True):
    """Map logical keys to real field names using the field labels."""
    found = {}
    for key, labels in wanted.items():
        for lab in labels:
            hits = [n for n, f in fields.items() if (f.get("string") or "").strip().lower() == lab]
            if prefer_custom:
                hits.sort(key=lambda n: (not n.startswith("x_"), n))
            if hits:
                found[key] = hits[0]
                break
    return found


# ---------------------------------------------------------------- normalising
def m2o(v):
    return v[1] if isinstance(v, list) and len(v) == 2 else (v or None)


def classify(state, status):
    """Map Odoo state + Magento/custom status text to the app's 5 stages."""
    s = (status or "").lower()
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
    return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(DZ)


# ---------------------------------------------------------------- aggregation (pure)
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

    meta = {"generated_at": now.isoformat(timespec="minutes"), "timezone": "Africa/Algiers",
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
    docs["orders"]["rows"] = docs["orders"]["rows"][:400]
    docs["orders"] = fit(docs["orders"], "rows")
    return docs


# ---------------------------------------------------------------- live pull
def pull(days):
    env = {k: os.environ.get(k) for k in ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_KEY")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        sys.exit("missing env: " + ", ".join(missing))
    od = Odoo(env["ODOO_URL"], env["ODOO_DB"], env["ODOO_USER"], env["ODOO_KEY"])
    of = od.fields("sale.order")
    omap = pick(of, ORDER_LABELS)
    if omap.get("wilaya") and of[omap["wilaya"]]["type"] not in ("many2one", "char", "selection"):
        omap.pop("wilaya")
    ofields = [f for f in ORDER_STD if f in of] + sorted(set(omap.values()))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    raw = od.search_read("sale.order", [["date_order", ">=", since]], ofields, order="date_order asc")

    # resolve many2many seller names
    sellers_field = omap.get("sellers")
    seller_names = {}
    if sellers_field and of[sellers_field]["type"] == "many2many":
        ids = {i for r in raw for i in (r.get(sellers_field) or [])}
        seller_names = od.names(of[sellers_field]["relation"], ids) if ids else {}

    def val(r, key):
        f = omap.get(key)
        if not f:
            return None
        v = r.get(f)
        t = of[f]["type"]
        if t == "many2many":
            return [seller_names.get(i, str(i)) for i in (v or [])]
        if t == "selection":
            return dict(of[f].get("selection") or []).get(v, v) if v else None
        return m2o(v) if v is not False else None

    orders = []
    for r in raw:
        status_raw = val(r, "status")
        s = val(r, "sellers")
        orders.append({
            "id": r["id"], "ref": r["name"], "magento": val(r, "magento_id"),
            "dt": to_local(r["date_order"]), "total": float(r.get("amount_total") or 0),
            "stage": classify(r.get("state"), status_raw if isinstance(status_raw, str) else None),
            "status_raw": status_raw if isinstance(status_raw, str) else r.get("state"),
            "customer": m2o(r.get("partner_id")), "salesperson": m2o(r.get("user_id")),
            "store": val(r, "store"), "sellers": s if isinstance(s, list) else ([s] if s else []),
            "source": m2o(r.get("source_id")), "campaign": m2o(r.get("campaign_id")),
            "wilaya": val(r, "wilaya"),
        })

    # order lines for the last 30 days
    lf = od.fields("sale.order.line")
    lmap = pick(lf, LINE_LABELS)
    recent_ids = [o["id"] for o in orders if o["dt"] >= datetime.now(DZ) - timedelta(days=30)]
    id_ref = {o["id"]: o["ref"] for o in orders}
    lfields = ["order_id", "product_id", "product_uom_qty", "price_total"] + sorted(set(lmap.values()))
    lines = []
    for i in range(0, len(recent_ids), BATCH):
        for l in od.search_read("sale.order.line", [["order_id", "in", recent_ids[i:i + BATCH]]], lfields):
            oid = l["order_id"][0] if l.get("order_id") else None

            def lval(key):
                f = lmap.get(key)
                return m2o(l.get(f)) if f and l.get(f) is not False else None
            lines.append({"order_ref": id_ref.get(oid), "product": m2o(l.get("product_id")),
                          "qty": float(l.get("product_uom_qty") or 0), "amount": float(l.get("price_total") or 0),
                          "seller": lval("seller"), "category": lval("category")})
    mapping = {"order": omap, "line": lmap}
    return orders, lines, mapping


# ---------------------------------------------------------------- self test
def selftest():
    random.seed(7)
    now = datetime(2026, 10, 4, 13, 0, tzinfo=DZ)
    stores = ["Hamiz Web", "Hamiz App", "Facebook"]
    sellers = [f"Seller {i}" for i in range(1, 40)]
    orders, lines = [], []
    for i in range(6000):
        dt = now - timedelta(days=random.random() * 90, hours=random.random() * 3)
        stage = random.choices(["pending", "confirmed", "delivered", "cancelled", "returned"], [5, 15, 50, 22, 8])[0]
        ref = f"S{i:05d}"
        ss = random.sample(sellers, random.choice([1, 1, 1, 2]))
        tot = random.choice([2500, 3900, 4500, 6200, 7900, 12000])
        orders.append({"id": i, "ref": ref, "magento": f"10000{i}", "dt": dt, "total": tot, "stage": stage,
                       "status_raw": stage, "customer": f"Client {i % 900}", "salesperson": None,
                       "store": random.choice(stores), "sellers": ss, "source": random.choice(["Facebook", None]),
                       "campaign": random.choice(["Rentree", "Lampes", None]), "wilaya": None})
        for s in ss:
            lines.append({"order_ref": ref, "product": f"Produit {random.randint(1, 300)}", "qty": 1,
                          "amount": tot / len(ss), "seller": s, "category": "Maison"})
    docs = finalize(aggregate(orders, lines, now, {}))
    for k, v in docs.items():
        size = len(json.dumps(v, ensure_ascii=False).encode())
        assert size <= MAX_DOC, (k, size)
        print(f"{k:9s} {size / 1024:6.1f} KiB")
    k = docs["summary"]["kpis"]["last30"]
    assert 0 < k["confirm_rate"] <= 1 and 0 < k["delivery_rate"] <= 1
    assert abs(sum(r["gmv"] for r in docs["sellers"]["rows"]) - sum(o["total"] for o in orders if o["dt"].date() >= now.date() - timedelta(days=29))) < 50
    print("last30:", {x: k[x] for x in ("orders", "gmv", "aov", "cancel_rate", "confirm_rate", "delivery_rate")})
    print("selftest OK")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="odoo_out")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        return selftest()
    orders, lines, mapping = pull(a.days)
    docs = finalize(aggregate(orders, lines, datetime.now(DZ), mapping))
    os.makedirs(a.out, exist_ok=True)
    for k, v in docs.items():
        with open(os.path.join(a.out, f"{k}.json"), "w", encoding="utf-8") as f:
            json.dump(v, f, ensure_ascii=False, separators=(",", ":"))
    s = docs["summary"]["kpis"]["last30"]
    print(json.dumps({"orders_scanned": len(orders), "lines": len(lines), "fields": mapping,
                      "last30": {x: s[x] for x in ("orders", "gmv", "aov", "cancel_rate", "confirm_rate", "delivery_rate")}},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
