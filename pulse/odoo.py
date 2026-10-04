"""Read-only Odoo 18 access over XML-RPC (PRD section 7). Never calls create/write/unlink."""
import socket
import time
import xmlrpc.client
from datetime import datetime, timedelta, timezone

from .config import DZ, env, line_labels, order_labels
from .stages import classify, to_local

BATCH = 1000
PAUSE = 0.3
TIMEOUT = 60
TRIES = 4
ORDER_STD = ["name", "date_order", "amount_total", "state", "invoice_status", "partner_id",
             "user_id", "campaign_id", "source_id", "medium_id"]
READ_METHODS = {"fields_get", "search_read", "read", "search_count"}


class OdooError(RuntimeError):
    pass


class _TimeoutTransport(xmlrpc.client.Transport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = TIMEOUT
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = TIMEOUT
        return conn


def _proxy(url):
    t = _TimeoutSafeTransport() if url.startswith("https") else _TimeoutTransport()
    return xmlrpc.client.ServerProxy(url, allow_none=True, transport=t)


class Odoo:
    def __init__(self, url, db, user, key, sleep=time.sleep):
        self.url, self.db, self.key, self.sleep = url.rstrip("/"), db, key, sleep
        self.uid = self._retry(lambda: _proxy(f"{self.url}/xmlrpc/2/common").authenticate(db, user, key, {}))
        if not self.uid:
            raise OdooError("Odoo login failed: check ODOO_USER / ODOO_KEY / ODOO_DB")
        self.m = _proxy(f"{self.url}/xmlrpc/2/object")

    def _retry(self, fn):
        for attempt in range(TRIES):
            try:
                return fn()
            except (OSError, socket.timeout, xmlrpc.client.ProtocolError):
                if attempt == TRIES - 1:
                    raise
                self.sleep(2 ** attempt)  # 1, 2, 4 s

    def call(self, model, method, *args, **kw):
        if method not in READ_METHODS:
            raise OdooError(f"refusing non-read Odoo method {method!r}")
        return self._retry(lambda: self.m.execute_kw(self.db, self.uid, self.key, model, method, list(args), kw))

    def fields(self, model):
        return self.call(model, "fields_get", attributes=["string", "type", "relation", "selection"])

    def search_read(self, model, domain, fields, order="id asc"):
        out, offset = [], 0
        while True:
            rows = self.call(model, "search_read", domain, fields=fields, offset=offset, limit=BATCH, order=order)
            out += rows
            if len(rows) < BATCH:
                return out
            offset += BATCH
            self.sleep(PAUSE)  # be gentle with the ERP

    def names(self, model, ids):
        ids, res = list(ids), {}
        for i in range(0, len(ids), BATCH):
            if i:
                self.sleep(PAUSE)
            for r in self.call(model, "read", ids[i:i + BATCH], fields=["display_name"]):
                res[r["id"]] = r["display_name"]
        return res


def pick(fields, wanted, prefer_custom=True):
    """Map logical keys to real field names using the field labels, preferring x_ fields."""
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


def m2o(v):
    return v[1] if isinstance(v, list) and len(v) == 2 else (v or None)


def connect():
    keys = ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_KEY")
    vals = {k: env(k) for k in keys}
    missing = [k for k, v in vals.items() if not v]
    if missing:
        raise OdooError("missing env: " + ", ".join(missing))
    return Odoo(vals["ODOO_URL"], vals["ODOO_DB"], vals["ODOO_USER"], vals["ODOO_KEY"])


def pull(od, days=90, log=print):
    """Return (orders, lines, mapping) normalised for pulse.aggregate."""
    of = od.fields("sale.order")
    omap = pick(of, order_labels())
    if omap.get("wilaya") and of[omap["wilaya"]]["type"] not in ("many2one", "char", "selection"):
        omap.pop("wilaya")
    if omap.get("utm_content") and of[omap["utm_content"]]["type"] not in ("many2one", "char", "selection"):
        omap.pop("utm_content")
    log("sale.order field mapping: " + (", ".join(f"{k}={v}" for k, v in sorted(omap.items())) or "(none)"))
    ofields = [f for f in ORDER_STD if f in of] + sorted(set(omap.values()))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    raw = od.search_read("sale.order", [["date_order", ">=", since]], ofields, order="date_order asc")

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
            "wilaya": val(r, "wilaya"), "utm_content": val(r, "utm_content"),
        })

    lf = od.fields("sale.order.line")
    lmap = pick(lf, line_labels())
    log("sale.order.line field mapping: " + (", ".join(f"{k}={v}" for k, v in sorted(lmap.items())) or "(none)"))
    cutoff = datetime.now(DZ) - timedelta(days=30)
    recent_ids = [o["id"] for o in orders if o["dt"] >= cutoff]
    id_ref = {o["id"]: o["ref"] for o in orders}
    lfields = ["order_id", "product_id", "product_uom_qty", "price_total"] + sorted(set(lmap.values()))
    lines = []
    for i in range(0, len(recent_ids), BATCH):
        if i:
            od.sleep(PAUSE)
        for ln in od.search_read("sale.order.line", [["order_id", "in", recent_ids[i:i + BATCH]]], lfields):
            oid = ln["order_id"][0] if ln.get("order_id") else None

            def lval(key):
                f = lmap.get(key)
                return m2o(ln.get(f)) if f and ln.get(f) is not False else None
            lines.append({"order_ref": id_ref.get(oid), "product": m2o(ln.get("product_id")),
                          "qty": float(ln.get("product_uom_qty") or 0), "amount": float(ln.get("price_total") or 0),
                          "seller": lval("seller"), "category": lval("category")})
    mapping = {"order": omap, "line": lmap}
    return orders, lines, mapping
