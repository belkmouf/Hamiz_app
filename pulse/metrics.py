"""Daily questions: 200–250 orders/day, and ad spend / merchandise value ≤ 5%.

Order value is merchandise in DZD: product lines only, delivery-fee lines left out.
Days are Africa/Algiers calendar days. The goal rate uses the last 7 complete days
so today's partial day does not pull the average down.
"""
from datetime import date, datetime, timedelta

from .config import GOAL_HIGH, GOAL_LOW, SPEND_CAP, TZ_NAME

STAGES = ("pending", "confirmed", "delivered", "returned", "cancelled")


def goods_value(total, product_amounts, delivery_amount=0.0):
    """Merchandise value for one order.

    Product line totals already exclude delivery. When the only lines we have are
    delivery fees, subtract them from the order total (Odoo `amount_total` includes
    shipping). With no line detail, the order total is the only figure available.
    """
    products = [float(a) for a in (product_amounts or [])]
    if products:
        return round(sum(products), 2)
    delivery = float(delivery_amount or 0)
    if delivery:
        return round(max(0.0, float(total or 0) - delivery), 2)
    return round(float(total or 0), 2)


def goal_status(orders_per_day, low=GOAL_LOW, high=GOAL_HIGH):
    """`on_target` only inside the closed band [low, high]."""
    if orders_per_day is None:
        return "unknown"
    if orders_per_day < low:
        return "short"
    if orders_per_day > high:
        return "above"
    return "on_target"


def spend_ratio(spend_usd, order_value_dzd, fx):
    """Ad spend in DZD divided by merchandise order value. None when value is 0."""
    value = float(order_value_dzd or 0)
    if value <= 0:
        return None
    return (float(spend_usd or 0) * float(fx)) / value


def spend_ok(ratio, cap=SPEND_CAP):
    return ratio is not None and ratio <= cap + 1e-9


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _row_goods(o):
    if o.get("goods") is not None:
        return float(o["goods"])
    return float(o.get("total") or 0)


def summarize(orders, spend_rows, fx, cap=SPEND_CAP):
    """One window: order count (every stage), goods value, stage counts, Meta spend, ratio."""
    stages = {s: 0 for s in STAGES}
    for o in orders:
        st = o.get("stage") or "pending"
        if st not in stages:
            st = "pending"
        stages[st] += 1
    value = round(sum(_row_goods(o) for o in orders), 2)
    spend = round(sum(float(r.get("spend_usd") or 0) for r in spend_rows), 2)
    ratio = spend_ratio(spend, value, fx)
    return {
        "orders": len(orders),
        "order_value_dzd": value,
        "stages": stages,
        "spend_usd": spend,
        "spend_dzd": round(spend * float(fx), 2),
        "spend_ratio": None if ratio is None else round(ratio, 6),
        "spend_ok": None if ratio is None else spend_ok(ratio, cap),
    }


def snapshot(today, orders, spend_rows, fx=250.0, low=GOAL_LOW, high=GOAL_HIGH, cap=SPEND_CAP):
    """`today` is an Algiers date. `orders` carry a local `date`. Spend rows carry `date`."""
    if isinstance(today, datetime):
        today = today.date()
    tagged_o = [( _as_date(o["date"]), o) for o in orders]
    tagged_s = [(_as_date(r["date"]), r) for r in spend_rows]

    def on(day):
        return [o for d, o in tagged_o if d == day]

    def spent(day):
        return [r for d, r in tagged_s if d == day]

    full_days = [today - timedelta(days=i) for i in range(1, 8)]
    counts = [len(on(d)) for d in full_days]
    rate = sum(counts) / 7
    status = goal_status(rate, low, high)
    last7_orders = [o for d in full_days for o in on(d)]
    last7_spend = [r for d in full_days for r in spent(d)]
    return {
        "timezone": TZ_NAME,
        "today": today.isoformat(),
        "goal_low": low,
        "goal_high": high,
        "spend_cap": cap,
        "fx": float(fx),
        "orders_per_day": round(rate, 2),
        "full_days": 7,
        "goal_status": status,
        "goal_short": round(low - rate, 2) if status == "short" else 0,
        "today_check": summarize(on(today), spent(today), fx, cap),
        "last7": summarize(last7_orders, last7_spend, fx, cap),
    }
