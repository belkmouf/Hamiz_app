import pytest

from pulse.stages import classify, to_local


@pytest.mark.parametrize("state,status,stage", [
    # cancelled row
    ("cancel", None, "cancelled"),
    ("cancel", "", "cancelled"),
    ("draft", "Canceled by customer", "cancelled"),
    ("draft", "Commande annulée", "cancelled"),
    ("sale", "Fraud suspected", "cancelled"),
    # cancelled row, but return words win -> returned
    ("draft", "refused", "returned"),
    ("draft", "Refusé à la livraison", "returned"),
    ("cancel", "Cancelled - return to sender", "returned"),
    ("cancel", "annulé retour", "returned"),
    # returned row
    ("sale", "Returned", "returned"),
    ("sale", "En retour", "returned"),
    ("sale", "RTO", "returned"),
    # delivered row
    ("sale", "Delivered", "delivered"),
    ("sale", "Livrée", "delivered"),
    ("done", "complete", "delivered"),
    ("sale", "closed", "delivered"),
    # confirmed row
    ("sale", None, "confirmed"),
    ("done", None, "confirmed"),
    ("draft", "processing", "confirmed"),
    ("draft", "Confirmed by call center", "confirmed"),
    ("draft", "shipped", "confirmed"),
    ("draft", "Expédiée", "confirmed"),
    # pending
    ("draft", None, "pending"),
    ("sent", "new", "pending"),
    (None, None, "pending"),
])
def test_stage_table(state, status, stage):
    assert classify(state, status) == stage


def test_case_insensitive():
    assert classify("draft", "DELIVERED") == "delivered"


def test_timezone_algiers():
    dt = to_local("2026-10-03 23:30:00")
    assert dt.date().isoformat() == "2026-10-04"
    assert dt.hour == 0
    assert dt.utcoffset().total_seconds() == 3600


def test_js_stage_rules_match_python():
    import json
    import subprocess
    from pathlib import Path
    cases = [("cancel", None), ("draft", "refused"), ("draft", "Refusé"), ("sale", "RTO"), ("sale", "Livrée"),
             ("draft", "Expédiée"), ("draft", None), ("done", None), ("draft", "fraud"), ("cancel", "retour")]
    calc = Path(__file__).resolve().parent.parent / "web" / "calc.js"
    js = f"const C=require({json.dumps(str(calc))});console.log(JSON.stringify({json.dumps(cases)}.map(([a,b])=>C.classify(a,b))))"
    out = json.loads(subprocess.check_output(["node", "-e", js], text=True))
    assert out == [classify(a, b) for a, b in cases]
