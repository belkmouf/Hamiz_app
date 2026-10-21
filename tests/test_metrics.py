"""Daily order goal and the 5% ad-spend check. Days are Africa/Algiers."""
from datetime import date, timedelta

from pulse.metrics import goods_value, goal_status, snapshot, spend_ok, spend_ratio


def test_goods_value_drops_delivery():
    assert goods_value(4900, [4500.0], 400) == 4500
    assert goods_value(4900, [], 400) == 4500
    assert goods_value(4500, [], 0) == 4500
    assert goods_value(100, [40, 60], 0) == 100


def test_five_percent_uses_merchandise_not_the_order_total():
    # 0.92 USD * 250 = 230 DZD. 230/4500 is over 5%. 230/4900 would sneak under.
    over = spend_ratio(0.92, 4500, 250)
    under = spend_ratio(0.92, 4900, 250)
    assert over > 0.05 and spend_ok(over) is False
    assert under <= 0.05 and spend_ok(under) is True
    assert spend_ratio(10, 0, 250) is None
    assert spend_ok(None) is False


def test_goal_band_is_closed():
    assert goal_status(200) == "on_target"
    assert goal_status(225) == "on_target"
    assert goal_status(250) == "on_target"
    assert goal_status(199.9) == "short"
    assert goal_status(250.1) == "above"
    assert goal_status(None) == "unknown"


def test_snapshot_rates_complete_algiers_days_and_today_spend():
    today = date(2026, 10, 4)
    orders = []
    for i in range(1, 8):
        for _ in range(210):
            orders.append({"date": today - timedelta(days=i), "stage": "confirmed", "total": 1000, "goods": 1000})
    # One order placed today. 0.92 USD is 230 DZD, which is over 5% of 4,500 and under 5% of 4,900.
    orders.append({"date": today, "stage": "confirmed", "total": 4900, "goods": 4500})
    spend = [{"date": today, "spend_usd": 0.92}, {"date": today - timedelta(days=1), "spend_usd": 1}]
    snap = snapshot(today, orders, spend, fx=250)
    assert snap["timezone"] == "Africa/Algiers"
    assert snap["orders_per_day"] == 210
    assert snap["full_days"] == 7
    assert snap["goal_status"] == "on_target"
    assert snap["goal_low"] == 200 and snap["goal_high"] == 250
    today_check = snap["today_check"]
    assert today_check["orders"] == 1
    assert today_check["order_value_dzd"] == 4500
    assert today_check["spend_usd"] == 0.92
    assert today_check["spend_ok"] is False
    assert snap["last7"]["orders"] == 210 * 7
    assert snap["last7"]["spend_usd"] == 1
