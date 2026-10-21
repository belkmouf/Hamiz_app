"""Hourly sync is scheduled, a run shows up as new data, and API responses are not cached."""
from datetime import timedelta
from pathlib import Path

from fake_odoo import FakeOdoo

from pulse import store, sync

ROOT = Path(__file__).resolve().parent.parent


def test_render_schedules_hourly_sync():
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert 'schedule: "7 * * * *"' in text
    assert "dockerCommand: python -m pulse.sync" in text
    assert "healthCheckPath: /healthz" in text


def test_sync_job_makes_new_orders_visible(db_url):
    sync.sync_odoo(od=FakeOdoo(n=15), log=lambda *_: None)
    start = store.now().date() - timedelta(days=90)
    end = store.now().date() + timedelta(days=1)
    first = store.attribution_between(start, end)
    sync.sync_odoo(od=FakeOdoo(n=40), log=lambda *_: None)
    second = store.attribution_between(start, end)
    assert len(second) > len(first)
    assert store.last_runs()["odoo"]["last"]["ok"] is True
    assert all(row.get("goods") is not None for row in second)


def test_api_is_not_cached_and_healthz_stays_on_http(client, capsys, monkeypatch):
    from test_api import login

    login(client, capsys)
    r = client.get("/api/reports")
    assert r.headers["cache-control"] == "no-store, max-age=0"
    assert r.headers["pragma"] == "no-cache"
    body = r.json()
    assert "pulse" in body and "last_synced_at" in body["sync"]
    assert body["pulse"]["goal_low"] == 200 and body["pulse"]["goal_high"] == 250
    assert body["pulse"]["spend_cap"] == 0.05
    monkeypatch.setenv("PULSE_FORCE_HTTPS", "1")
    health = client.get("/healthz", headers={"x-forwarded-proto": "http"})
    assert health.status_code == 200 and health.json()["ok"] is True
    redir = client.get("/", headers={"x-forwarded-proto": "http"}, follow_redirects=False)
    assert redir.status_code == 308


def test_service_worker_keeps_api_off_the_cache():
    text = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
    assert 'const VERSION = "pulse-v3"' in text
    assert 'cache: "no-store"' in text
    assert 'url.pathname.startsWith("/api/")' in text
    assert "networkOnly" in text
    assert "/i18n.js" in text
