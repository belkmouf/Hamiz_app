import xmlrpc.client
from datetime import timedelta

import pytest
from fake_odoo import FakeOdoo

from pulse import odoo, store, sync


def test_pull_maps_fields_by_label_preferring_x_fields():
    fake = FakeOdoo(n=300)
    logs = []
    orders, lines, mapping = odoo.pull(fake, days=90, log=logs.append)
    assert mapping["order"] == {"magento_id": "x_magento_id", "sellers": "x_sellers", "store": "x_store",
                                "status": "x_order_status", "wilaya": "x_wilaya", "utm_content": "x_utm_content"}
    assert mapping["line"] == {"seller": "x_seller", "category": "x_category"}
    assert any("field mapping" in m for m in logs)
    o = {x["ref"]: x for x in orders}
    assert o["S00000"]["stage"] == "returned" or o["S00000"]["stage"] == "cancelled"
    assert o["S00001"]["stage"] == "confirmed"  # Expédiée
    assert o["S00003"]["sellers"] == ["Mode Tlemcen", "Sport Atlas"]
    assert o["S00001"]["utm_content"] == "T_lamp_TOFU_demo_v1"
    assert lines and all(ln["seller"] == "Mode Tlemcen" for ln in lines)
    assert ("res.partner", "read") in fake.calls  # one batched many2many name lookup
    assert all(m in odoo.READ_METHODS for _, m in fake.calls)


def test_batches_and_pauses():
    fake = FakeOdoo(n=2500)
    odoo.pull(fake, days=90, log=lambda *_: None)
    reads = [c for c in fake.calls if c == ("sale.order", "search_read")]
    assert len(reads) == 3  # 1000 + 1000 + 500
    assert fake.sleeps and all(s == 0.3 for s in fake.sleeps)


def test_refuses_write_methods():
    o = odoo.Odoo.__new__(odoo.Odoo)
    with pytest.raises(odoo.OdooError):
        o.call("sale.order", "write", [1], {"state": "cancel"})


def test_retry_with_exponential_backoff():
    o = odoo.Odoo.__new__(odoo.Odoo)
    waits = []
    o.sleep = waits.append
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 4:
            raise xmlrpc.client.ProtocolError("x", 502, "bad gateway", {})
        return "ok"
    assert o._retry(flaky) == "ok"
    assert waits == [1, 2, 4]
    attempts.clear()
    waits.clear()

    def down():
        raise OSError("down")
    with pytest.raises(OSError):
        o._retry(down)
    assert waits == [1, 2, 4]


def test_sync_stores_documents_and_run(db_url):
    sync.sync_odoo(od=FakeOdoo(n=1200), log=lambda *_: None)
    docs = store.load_reports()
    assert set(docs) == {"summary", "sellers", "products", "orders"}
    assert docs["summary"]["meta"]["example"] is False
    assert docs["summary"]["meta"]["fields"]["order"]["utm_content"] == "x_utm_content"
    runs = store.last_runs()
    assert runs["odoo"]["last"]["ok"] is True and runs["odoo"]["last"]["orders_scanned"] > 0
    from datetime import date, timedelta
    att = store.attribution_between(date.today() - timedelta(days=40), date.today() + timedelta(days=1))
    assert att and any(a["ad"] == "T_lamp_TOFU_demo_v1" for a in att)


def test_failed_sync_keeps_last_good_data(db_url):
    sync.sync_odoo(od=FakeOdoo(n=500), log=lambda *_: None)
    before = store.load_reports()
    with pytest.raises(OSError):
        sync.sync_odoo(od=FakeOdoo(n=500, fail=True), log=lambda *_: None)
    assert store.load_reports() == before
    runs = store.last_runs()
    assert runs["odoo"]["last"]["ok"] is False and "connection refused" in runs["odoo"]["last"]["error"]
    assert runs["odoo"]["last_ok"]["ok"] is True


def test_single_run_lock(db_url):
    with sync.single_run():
        with pytest.raises(sync.Busy):
            with sync.single_run():
                pass
    with sync.single_run():  # released
        pass


def test_seed_loads_example_data(db_url):
    assert sync.seed(log=lambda *_: None) is True
    docs = store.load_reports()
    assert docs["summary"]["meta"]["example"] is True
    assert sync.seed(log=lambda *_: None) is False  # does not overwrite


def test_status_never_maps_to_odoo_state_field():
    """Odoo's own `state` field is labelled "Status": it must not be taken as the Magento status."""
    orders, _, mapping = odoo.pull(FakeOdoo(n=50, no_custom_status=True), log=lambda *_: None)
    assert "status" not in mapping["order"]
    assert {o["stage"] for o in orders} <= {"confirmed", "cancelled"}  # from state alone


def test_section_note_and_delivery_lines_left_out():
    _, lines, mapping = odoo.pull(FakeOdoo(n=100), log=lambda *_: None)
    assert all(ln["product"] == "Lampe LED" for ln in lines)
    assert mapping["lines_skipped"]["delivery_fee"] > 0 and mapping["lines_skipped"]["section_or_note"] > 0


def test_date_order_moved_on_confirmation_is_reported_and_switchable(monkeypatch):
    logs = []
    fake = FakeOdoo(n=200, confirm_delay_hours=5)
    orders, _, mapping = odoo.pull(fake, log=logs.append)
    assert mapping["date"]["date_order_after_create_1h"] > 100
    assert any("PULSE_ORDER_DATE_FIELD" in m for m in logs)
    by_date_order = {o["ref"]: o["dt"] for o in orders}
    monkeypatch.setenv("PULSE_ORDER_DATE_FIELD", "create_date")
    orders2, _, mapping2 = odoo.pull(fake, log=lambda *_: None)
    assert mapping2["date"]["field"] == "create_date"
    o = next(x for x in orders2 if fake.orders[int(x["ref"][1:])]["state"] == "sale")
    assert by_date_order[o["ref"]] - o["dt"] == timedelta(hours=5)
    monkeypatch.setenv("PULSE_ORDER_DATE_FIELD", "x_store")
    with pytest.raises(odoo.OdooError):
        odoo.pull(fake, log=lambda *_: None)


def test_goods_value_excludes_delivery_fee():
    """amount_total includes shipping; the 5% check uses product lines only."""
    orders, _, _ = odoo.pull(FakeOdoo(n=5, include_delivery_in_total=True), log=lambda *_: None)
    by_ref = {o["ref"]: o for o in orders}
    shipped = by_ref["S00004"]  # id 5: delivery line of 400, and the total includes it
    assert shipped["total"] == 4900
    assert shipped["goods"] == 4500


def test_algiers_day_window_includes_previous_utc_evening():
    """2026-10-03 23:30 UTC is 2026-10-04 00:30 in Algiers, so it belongs to the 4th."""
    from datetime import date

    fake = FakeOdoo(n=1)
    fake.orders[0]["date_order"] = "2026-10-03 23:30:00"
    fake.orders[0]["create_date"] = "2026-10-03 23:30:00"
    on_fourth, _, _ = odoo.pull(fake, start=date(2026, 10, 4), end=date(2026, 10, 4), log=lambda *_: None)
    assert len(on_fourth) == 1
    assert on_fourth[0]["dt"].date() == date(2026, 10, 4)
    assert on_fourth[0]["dt"].hour == 0
    on_third, _, _ = odoo.pull(fake, start=date(2026, 10, 3), end=date(2026, 10, 3), log=lambda *_: None)
    assert on_third == []
