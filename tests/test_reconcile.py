"""Mock reconciliation must agree on merchandise value, not the delivery-inclusive total."""
from pulse.reconcile import run_mock


def test_mock_reconcile_matches_on_goods_value():
    report = run_mock(log=lambda *_: None)
    assert "4500" in report
    assert "4900" not in report
    assert "OK: no discrepancies" in report
    assert "Africa/Algiers" in report
