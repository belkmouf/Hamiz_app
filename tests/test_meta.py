import json

import httpx
import pytest

from pulse import meta_ads, store, sync


def test_purchases_display_value():
    assert meta_ads.purchases([{"action_type": "link_click", "value": "40"},
                               {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"}]) == 3
    assert meta_ads.purchases([{"action_type": "purchase", "value": "5"},
                               {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"}]) == 5
    assert meta_ads.purchases(None) == 0


def test_usage_header():
    h = {"x-business-use-case-usage": json.dumps({"123": [{"call_count": 12, "total_cputime": 80, "total_time": 3}]})}
    assert meta_ads.usage_pct(h) == 80


def row(ad, day="2026-10-04", spend="12.34"):
    return {"date_start": day, "date_stop": day, "campaign_id": "c1", "campaign_name": "Lampes", "adset_name": "Testing",
            "ad_id": ad, "ad_name": f"Ad {ad}", "spend": spend, "impressions": "1000", "clicks": "25",
            "actions": [{"action_type": "purchase", "value": "2"}]}


def test_insights_paginates_and_retries_rate_limits():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"code": 17, "message": "User request limit reached"}})
        if "after=" not in str(req.url):
            return httpx.Response(200, json={"data": [row("1")], "paging": {"next": "https://graph.facebook.com/v24.0/act_9/insights?after=abc&access_token=t"}})
        return httpx.Response(200, json={"data": [row("2", spend="1.00")]})
    waits = []
    m = meta_ads.Meta("t", "9", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=waits.append)
    rows = m.insights("last_30d")
    assert [r["ad_id"] for r in rows] == ["1", "2"]
    assert rows[0]["spend_usd"] == 12.34 and rows[0]["meta_purchases"] == 2 and rows[0]["clicks"] == 25
    assert waits == [30]
    assert "level=ad" in calls[1] and "time_increment=1" in calls[1] and "date_preset=last_30d" in calls[1]
    assert "/act_9/insights" in calls[1]


def test_insights_raises_on_auth_error():
    def handler(req):
        return httpx.Response(400, json={"error": {"code": 190, "message": "Invalid OAuth access token"}})
    m = meta_ads.Meta("t", "act_9", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(meta_ads.MetaError, match="Invalid OAuth"):
        m.insights("today")


class FakeMeta:
    def __init__(self, currency="USD", tz=1):
        self.currency, self.tz = currency, tz

    def account_info(self):
        return {"currency": self.currency, "timezone_name": "Africa/Algiers" if self.tz == 1 else "America/Los_Angeles",
                "timezone_offset_hours_utc": self.tz}

    def insights(self, preset):
        d = store.now().date().isoformat() if preset == "today" else "2026-09-20"
        return [meta_ads.normalise(row("1", day=d))]


def test_sync_meta_upserts(db_url):
    sync.sync_meta(client=FakeMeta(), log=lambda *_: None)
    sync.sync_meta(client=FakeMeta(), log=lambda *_: None)  # second run replaces, no duplicates
    today = store.now().date()
    rows = store.spend_between(today, today)
    assert len(rows) == 1 and rows[0]["ad_name"] == "Ad 1"
    assert store.last_runs()["meta"]["last"]["ok"] is True


def test_sync_meta_records_account_currency_and_timezone(db_url):
    logs = []
    sync.sync_meta(client=FakeMeta(currency="DZD", tz=-7), log=logs.append)
    acc = store.load_reports()["meta_account"]
    assert acc["currency"] == "DZD" and acc["timezone_offset_hours_utc"] == -7
    assert any("currency is DZD" in m for m in logs) and any("time zone" in m for m in logs)


def test_account_info_request():
    seen = []

    def handler(req):
        seen.append(req.url)
        return httpx.Response(200, json={"currency": "USD", "timezone_name": "Africa/Algiers", "timezone_offset_hours_utc": 1, "id": "act_9"})
    m = meta_ads.Meta("t", "9", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert m.account_info()["currency"] == "USD"
    assert seen[0].path.endswith("/act_9") and "currency" in seen[0].params["fields"]
