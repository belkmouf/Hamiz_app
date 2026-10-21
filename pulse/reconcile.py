"""Compare one Algiers day of stored figures with a fresh Odoo and Meta query.

  python -m pulse.reconcile --date 2026-10-20
  python -m pulse.reconcile --mock          # no credentials; proves the comparison on fakes

Exit 0 when stored and live agree, 1 when they do not, 2 when a source cannot be reached.
Real Odoo and Meta credentials are read from the environment, the same ones the hourly sync uses.
"""
import argparse
import sys
from datetime import date, datetime, timedelta, timezone

from .config import DZ, fx as env_fx
from .metrics import summarize


def _day_rows(orders):
    return [{"date": o["dt"].date() if hasattr(o.get("dt"), "date") else o["date"], "stage": o["stage"],
             "total": o["total"], "goods": o.get("goods")} for o in orders]


def _spend_rows(rows):
    return [{"date": r["date"], "spend_usd": r.get("spend_usd") or 0} for r in rows]


def _num_delta(stored, live):
    if isinstance(stored, (int, float)) and isinstance(live, (int, float)):
        return round(float(live) - float(stored), 4)
    return None


def _compare(stored, live, tol_money=0.05):
    diffs = []
    fields = ("orders", "order_value_dzd", "spend_usd", "spend_dzd", "spend_ratio")
    for field in fields:
        s, lv = stored.get(field), live.get(field)
        if s is None and lv is None:
            continue
        if field == "spend_ratio":
            tol = 1e-4
        elif field == "orders":
            tol = 0
        else:
            tol = tol_money
        if s is None or lv is None or abs(float(s) - float(lv)) > tol:
            diffs.append({"field": field, "stored": s, "live": lv, "delta": _num_delta(s or 0, lv or 0)})
    for stage in ("pending", "confirmed", "delivered", "returned", "cancelled"):
        s = (stored.get("stages") or {}).get(stage, 0)
        lv = (live.get("stages") or {}).get(stage, 0)
        if s != lv:
            diffs.append({"field": f"stage.{stage}", "stored": s, "live": lv, "delta": lv - s})
    return diffs


def format_report(day, diffs, stored, live):
    lines = [
        f"Hamiz Pulse reconciliation {day.isoformat()} (Africa/Algiers)",
        f"orders: stored {stored['orders']}  live {live['orders']}",
        f"order value DZD (excl. delivery): stored {stored['order_value_dzd']}  live {live['order_value_dzd']}",
        f"stages stored {stored['stages']}",
        f"stages live   {live['stages']}",
        f"Meta spend USD: stored {stored['spend_usd']}  live {live['spend_usd']}",
        f"ad spend / order value: stored {stored['spend_ratio']}  live {live['spend_ratio']}  (cap 5%)",
    ]
    if diffs:
        lines.append(f"DISCREPANCIES: {len(diffs)}")
        for d in diffs:
            lines.append(f"  {d['field']}: stored {d['stored']}  live {d['live']}  delta {d['delta']}")
    else:
        lines.append("OK: no discrepancies")
    return "\n".join(lines)


def reconcile(day, od=None, meta=None, url=None, fx=None, log=print):
    """Return (discrepancies, report). `day` is an Africa/Algiers date."""
    from . import meta_ads, odoo, store

    if isinstance(day, str):
        day = date.fromisoformat(day)
    fx = env_fx() if fx is None else float(fx)
    od = od or odoo.connect()
    meta = meta or meta_ads.connect()
    live_orders, _, _ = odoo.pull(od, start=day, end=day, line_scope="all", log=log)
    live_spend = meta.insights(since=day.isoformat(), until=day.isoformat())
    stored_orders = store.attribution_between(day, day, url)
    stored_spend = store.spend_between(day, day, url)
    stored = summarize(stored_orders, stored_spend, fx)
    live = summarize(_day_rows(live_orders), _spend_rows(live_spend), fx)
    diffs = _compare(stored, live)
    report = format_report(day, diffs, stored, live)
    log(report)
    return diffs, report


class _MockOdoo:
    """One confirmed order whose total includes a 400 DA delivery fee. Enough for pull()."""

    def __init__(self, stamp):
        self.stamp = stamp
        self.sleep = lambda *_: None
        self._order_fields = {
            "name": {"string": "Order Reference", "type": "char"},
            "date_order": {"string": "Order Date", "type": "datetime"},
            "amount_total": {"string": "Total", "type": "monetary"},
            "state": {"string": "Status", "type": "selection"},
            "invoice_status": {"string": "Invoice Status", "type": "selection"},
            "partner_id": {"string": "Customer", "type": "many2one"},
            "user_id": {"string": "Salesperson", "type": "many2one"},
            "campaign_id": {"string": "Campaign", "type": "many2one"},
            "source_id": {"string": "Source", "type": "many2one"},
            "medium_id": {"string": "Medium", "type": "many2one"},
            "create_date": {"string": "Created on", "type": "datetime"},
            "x_order_status": {"string": "Order Status", "type": "char"},
            "x_utm_content": {"string": "UTM Content", "type": "char"},
        }
        self._line_fields = {
            "order_id": {"string": "Order", "type": "many2one"},
            "product_id": {"string": "Product", "type": "many2one"},
            "product_uom_qty": {"string": "Quantity", "type": "float"},
            "price_total": {"string": "Total", "type": "monetary"},
            "display_type": {"string": "Display Type", "type": "selection"},
            "is_delivery": {"string": "Is a Delivery", "type": "boolean"},
        }

    def fields(self, model):
        return self._order_fields if model == "sale.order" else self._line_fields

    def search_read(self, model, domain, fields, order="id asc"):
        if model == "sale.order":
            row = {"id": 1, "name": "S100", "date_order": self.stamp, "create_date": self.stamp,
                   "amount_total": 4900.0, "state": "sale", "invoice_status": "no",
                   "partner_id": [1, "Amina"], "user_id": False, "campaign_id": [1, "Lampes"],
                   "source_id": [1, "fb"], "medium_id": False, "x_order_status": "processing",
                   "x_utm_content": "Ad 1"}
            return [{k: row[k] for k in fields if k in row} | {"id": 1}]
        return [
            {"order_id": [1, "S100"], "product_id": [7, "Lampe"], "product_uom_qty": 1.0,
             "price_total": 4500.0, "display_type": False, "is_delivery": False},
            {"order_id": [1, "S100"], "product_id": [8, "Livraison"], "product_uom_qty": 1.0,
             "price_total": 400.0, "display_type": False, "is_delivery": True},
        ]


def run_mock(log=print):
    """Sync a fake day into a throwaway database and reconcile it against the same fakes."""
    import os
    import tempfile

    from . import meta_ads, store, sync

    tmp = tempfile.TemporaryDirectory()
    url = "sqlite:///" + os.path.join(tmp.name, "pulse.db")
    day = datetime.now(DZ).date() - timedelta(days=1)
    stamp = datetime.combine(day, datetime.min.time(), tzinfo=DZ).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    fake = _MockOdoo(stamp)

    class Meta:
        def insights(self, date_preset=None, since=None, until=None):
            return [meta_ads.normalise({
                "date_start": day.isoformat(), "date_stop": day.isoformat(), "campaign_id": "c1",
                "campaign_name": "Lampes", "adset_name": "Testing", "ad_id": "1", "ad_name": "Ad 1",
                "spend": "10.00", "impressions": "100", "clicks": "5", "actions": [],
            })]

        def account_info(self):
            return {"currency": "USD", "timezone_name": "Africa/Algiers", "timezone_offset_hours_utc": 1}

    try:
        sync.sync_odoo(url=url, od=fake, log=lambda *_: None)
        sync.sync_meta(url=url, client=Meta(), log=lambda *_: None)
        diffs, report = reconcile(day, od=fake, meta=Meta(), url=url, fx=250, log=log)
    finally:
        eng = store._engines.pop(url, None)
        if eng is not None:
            eng.dispose()
        tmp.cleanup()
    if diffs:
        raise SystemExit("mock reconciliation found unexpected discrepancies")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", help="Africa/Algiers day YYYY-MM-DD to compare")
    p.add_argument("--mock", action="store_true", help="run against in-memory Odoo and Meta fakes")
    p.add_argument("--fx", type=float, default=None, help="DZD per 1 USD (default PULSE_FX or 250)")
    a = p.parse_args(argv)
    if a.mock:
        run_mock()
        return 0
    if not a.date:
        p.error("--date YYYY-MM-DD is required (or pass --mock)")
    try:
        day = date.fromisoformat(a.date)
    except ValueError:
        print("date must be YYYY-MM-DD")
        return 2
    try:
        diffs, _ = reconcile(day, fx=a.fx)
    except Exception as e:
        print(f"cannot reach Odoo or Meta: {type(e).__name__}: {e}")
        print("Set ODOO_URL, ODOO_DB, ODOO_USER, ODOO_KEY, META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, and DATABASE_URL.")
        return 2
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
