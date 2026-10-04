"""Hourly sync job: Odoo -> four report documents + order attribution; Meta -> meta_spend.

  python -m pulse.sync              Odoo and Meta (each skipped with a note when its env is missing)
  python -m pulse.sync --odoo       Odoo only
  python -m pulse.sync --meta       Meta only
  python -m pulse.sync --seed       load the example documents (marked example) into an empty store

A failed sync keeps the last good data and records the error in sync_runs.
Only one sync runs at a time (file lock, plus a Postgres advisory lock when on Postgres).
"""
import argparse
import csv
import fcntl
import json
import os
import sys
import traceback
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import sqlalchemy as sa

from . import store
from .aggregate import attribution, doc_size, finalize, aggregate
from .config import MAX_DOC, env

SEED = Path(__file__).parent / "seed"
LOCK_KEY = 74_2026_1004  # arbitrary, stable advisory-lock id


class Busy(RuntimeError):
    pass


@contextmanager
def single_run(url=None):
    path = env("PULSE_LOCK_FILE", "/tmp/hamiz-pulse-sync.lock")
    fh = open(path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        raise Busy("another sync is running (file lock)")
    eng = store.engine(url)
    conn = None
    try:
        if eng.dialect.name == "postgresql":
            conn = eng.connect()
            if not conn.execute(sa.text("select pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar():
                raise Busy("another sync is running (database lock)")
        yield
    finally:
        if conn is not None:
            conn.execute(sa.text("select pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            conn.close()
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def sync_odoo(url=None, days=90, od=None, log=print):
    from . import odoo
    run = store.start_run("odoo", url)
    n = None
    try:
        od = od or odoo.connect()
        orders, lines, mapping = odoo.pull(od, days, log=log)
        n = len(orders)
        now = store.now()
        att = attribution(orders, now)  # before aggregate: it marks orders for the seller split
        docs = finalize(aggregate(orders, lines, now, mapping))
        for k, v in docs.items():
            size = doc_size(v)
            if size > MAX_DOC:
                raise RuntimeError(f"{k} document is {size} bytes, over the {MAX_DOC} limit")
        store.save_reports(docs, att, url)
        k = docs["summary"]["kpis"]["last30"]
        log(json.dumps({"orders_scanned": n, "lines": len(lines), "fields": mapping,
                        "last30": {x: k[x] for x in ("orders", "gmv", "aov", "cancel_rate", "confirm_rate",
                                                     "delivery_rate")}}, ensure_ascii=False))
        store.finish_run(run, True, orders_scanned=n, url=url)
        return docs
    except Exception as e:
        store.finish_run(run, False, error=f"{type(e).__name__}: {e}", orders_scanned=n, url=url)
        raise


def sync_meta(url=None, client=None, log=print):
    from . import meta_ads
    run = store.start_run("meta", url)
    try:
        client = client or meta_ads.connect()
        rows = client.insights("last_30d") + client.insights("today")
        store.save_meta_spend(rows, url)
        store.prune_meta_spend(store.now().date() - timedelta(days=35), url)
        log(f"meta: {len(rows)} ad-day rows, ${sum(r['spend_usd'] for r in rows):,.2f} spend")
        store.finish_run(run, True, url=url)
        return rows
    except Exception as e:
        store.finish_run(run, False, error=f"{type(e).__name__}: {e}", url=url)
        raise


def seed(url=None, force=False, log=print):
    """Load the example documents so every tab has something to show before the first real sync."""
    if store.load_reports(url) and not force:
        log("store already has reports; use --force to overwrite with example data")
        return False
    docs = {k: json.loads((SEED / f"{k}.json").read_text(encoding="utf-8"))
            for k in ("summary", "sellers", "products", "orders")}
    for d in docs.values():
        d["meta"]["example"] = True
    today = store.now().date()
    with open(SEED / "orders.csv", newline="", encoding="utf-8") as f:
        att = [{"ref": f"EX{i:04d}", "date": today.isoformat(), "ad": (r["ad_name"] or None),
                "campaign": "Lampes" if r["ad_name"] else None, "source": "fb" if r["ad_name"] else None, "stage": r["status"], "total": float(r["value"] or 0)}
               for i, r in enumerate(csv.DictReader(f))]
    with open(SEED / "ads.csv", newline="", encoding="utf-8") as f:
        spend = [{"date": today, "ad_id": f"ex{i}", "campaign_id": "ex", "campaign_name": "Lampes",
                  "adset_name": "Testing", "ad_name": r["ad_name"], "spend_usd": float(r["spend"]),
                  "impressions": 0, "clicks": 0, "meta_purchases": 0} for i, r in enumerate(csv.DictReader(f))]
    store.save_reports(docs, att, url)
    store.save_meta_spend(spend, url)
    log("loaded example data")
    return True


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--odoo", action="store_true")
    p.add_argument("--meta", action="store_true")
    p.add_argument("--seed", action="store_true")
    p.add_argument("--force", action="store_true", help="with --seed: overwrite existing reports")
    p.add_argument("--days", type=int, default=90)
    a = p.parse_args(argv)
    if a.seed:
        seed(force=a.force)
        return 0
    both = not (a.odoo or a.meta)
    failed = False
    try:
        with single_run():
            if a.odoo or both:
                if both and not env("ODOO_URL"):
                    print("odoo: skipped, ODOO_URL not set")
                else:
                    try:
                        sync_odoo(days=a.days)
                    except Exception:
                        traceback.print_exc()
                        failed = True
            if a.meta or both:
                if both and not env("META_ACCESS_TOKEN"):
                    print("meta: skipped, META_ACCESS_TOKEN not set")
                else:
                    try:
                        sync_meta()
                    except Exception:
                        traceback.print_exc()
                        failed = True
    except Busy as e:
        print(f"skipped: {e}")
        return 0
    return 1 if failed else 0


if __name__ == "__main__":
    os.environ.setdefault("TZ", "Africa/Algiers")
    sys.exit(main())
