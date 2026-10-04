import copy
import json
import random
import subprocess
import sys
from datetime import timedelta

from conftest import REF, load_reference
from synthetic import selftest_input

from pulse.aggregate import MAX_DOC, aggregate, attribution, doc_size, finalize


def test_reference_selftest_runs():
    out = subprocess.run([sys.executable, str(REF / "odoo_sync.py"), "--selftest"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "selftest OK" in out.stdout


def test_same_documents_as_reference_on_selftest_input():
    ref = load_reference("odoo_sync")
    orders, lines, now = selftest_input()
    want = ref.finalize(ref.aggregate(copy.deepcopy(orders), copy.deepcopy(lines), now, {}))
    got = finalize(aggregate(copy.deepcopy(orders), copy.deepcopy(lines), now, {}))
    for k in ("summary", "sellers", "products", "orders"):
        assert json.dumps(got[k], sort_keys=True) == json.dumps(want[k], sort_keys=True), k


def test_kpis_match_reference_split_sellers():
    """Seller basis without line sellers (total split across order sellers)."""
    ref = load_reference("odoo_sync")
    orders, lines, now = selftest_input(n=3000)
    for ln in lines:
        ln["seller"] = None
    want = ref.finalize(ref.aggregate(copy.deepcopy(orders), copy.deepcopy(lines), now, {"wilaya": "x_wilaya"}))
    got = finalize(aggregate(copy.deepcopy(orders), copy.deepcopy(lines), now, {"wilaya": "x_wilaya"}))
    assert got["sellers"]["meta"]["seller_basis"] == "order total split evenly across sellers"
    assert json.dumps(got, sort_keys=True) == json.dumps(want, sort_keys=True)


def test_selftest_assertions_hold():
    orders, lines, now = selftest_input()
    docs = finalize(aggregate(orders, lines, now, {}))
    k = docs["summary"]["kpis"]["last30"]
    assert 0 < k["confirm_rate"] <= 1 and 0 < k["delivery_rate"] <= 1
    last30 = sum(o["total"] for o in orders if o["dt"].date() >= now.date() - timedelta(days=29))
    assert abs(sum(r["gmv"] for r in docs["sellers"]["rows"]) - last30) < 50
    assert len(docs["summary"]["daily"]) == 90
    assert len(docs["summary"]["weekday_hours"]) == 7 and all(len(r) == 24 for r in docs["summary"]["weekday_hours"])


def test_window_definitions():
    orders, lines, now = selftest_input(n=2000)
    docs = aggregate(orders, lines, now, {})
    k = docs["summary"]["kpis"]
    today = now.date()
    n7 = sum(1 for o in orders if today - timedelta(days=6) <= o["dt"].date() <= today)
    assert k["last7"]["orders"] == n7
    assert k["last7"]["orders_per_day"] == round(n7 / 7, 1)
    sel = [o for o in orders if today - timedelta(days=29) <= o["dt"].date() <= today]
    st = {s: sum(1 for o in sel if o["stage"] == s) for s in ("pending", "confirmed", "delivered", "returned", "cancelled")}
    assert k["last30"]["confirm_rate"] == round((st["confirmed"] + st["delivered"] + st["returned"]) / (len(sel) - st["pending"]), 4)
    assert k["last30"]["delivery_rate"] == round(st["delivered"] / (st["delivered"] + st["returned"]), 4)
    assert k["last30"]["net_gmv"] == round(sum(o["total"] for o in sel if o["stage"] != "cancelled"))


def test_size_limit_20000_orders_in_90_days():
    # Many distinct sellers and products so the lists are as long as they can get.
    orders, lines, now = selftest_input(n=20000, seed=11, n_sellers=3000, n_products=20000)
    random.seed(3)
    for o in orders:
        o["customer"] = f"Client with a fairly long name {o['id']}"
        o["wilaya"] = f"Wilaya {random.randint(1, 58)}"
    docs = finalize(aggregate(orders, lines, now, {"wilaya": "x_wilaya"}))
    for k, v in docs.items():
        assert doc_size(v) <= MAX_DOC, (k, doc_size(v))
        assert len(json.dumps(v, ensure_ascii=False).encode()) <= MAX_DOC, k
    assert docs["orders"]["meta"].get("trimmed") is None and len(docs["orders"]["rows"]) == 400
    assert docs["products"]["meta"].get("trimmed") is True


def test_attribution_rows():
    orders, lines, now = selftest_input(n=500)
    orders[0]["utm_content"] = "T_lamp_TOFU_demo_v1"
    rows = attribution(orders, now)
    since = (now.date() - timedelta(days=29)).isoformat()
    assert all(r["date"] >= since for r in rows)
    assert len(rows) == sum(1 for o in orders if o["dt"].date().isoformat() >= since)
