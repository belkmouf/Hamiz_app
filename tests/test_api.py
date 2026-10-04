import re
import time

import pytest
from fake_odoo import FakeOdoo
from fastapi.testclient import TestClient

from pulse import auth, sync


@pytest.fixture
def client(db_url, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    monkeypatch.setenv("APP_ALLOWED_EMAILS", "belkacem@hamizonline.com, ops@hamizonline.com")
    monkeypatch.delenv("PULSE_DEV_NO_AUTH", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("PULSE_SEED_ON_EMPTY", "0")
    auth._last_request.clear()
    from pulse.api import app
    return TestClient(app)


def login(client, capsys, email="belkacem@hamizonline.com"):
    r = client.post("/auth/request", json={"email": email})
    assert r.status_code == 200
    link = re.search(r"login link for \S+: (\S+)", capsys.readouterr().out).group(1)
    r = client.get(link.replace("http://testserver", ""), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    return link


def test_api_requires_login(client):
    for path in ("/api/reports", "/api/status", "/api/ads"):
        assert client.get(path).status_code == 401
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/login").status_code == 200


def test_magic_link_flow_and_single_use(client, capsys):
    link = login(client, capsys)
    assert client.get("/api/status").status_code == 200
    assert client.get("/").status_code == 200
    # The same link cannot be used twice.
    fresh = TestClient(client.app)
    r = fresh.get(link.replace("http://testserver", ""), follow_redirects=False)
    assert r.headers["location"] == "/login?error=link"
    client.post("/auth/logout")
    client.cookies.clear()
    assert client.get("/api/status").status_code == 401


def test_unknown_email_gets_same_answer_and_no_link(client, capsys):
    a = client.post("/auth/request", json={"email": "stranger@example.com"}).json()
    assert "login link" not in capsys.readouterr().out
    b = client.post("/auth/request", json={"email": "ops@hamizonline.com"}).json()
    assert a == b


def test_expired_and_tampered_tokens(client, monkeypatch):
    tok = auth.make_link_token("ops@hamizonline.com")
    body, mac = tok.split(".")
    assert client.get(f"/auth/verify?token={body}.{mac[:-2]}xx", follow_redirects=False).headers["location"] == "/login?error=link"
    later = time.time() + auth.LINK_TTL + 5
    monkeypatch.setattr(auth.time, "time", lambda: later)
    assert auth.unsign(tok, "link") is None


def test_session_revoked_when_email_leaves_allowlist(client, capsys, monkeypatch):
    login(client, capsys, "ops@hamizonline.com")
    monkeypatch.setenv("APP_ALLOWED_EMAILS", "belkacem@hamizonline.com")
    assert client.get("/api/status").status_code == 401


def test_reports_and_status_states(client, capsys):
    login(client, capsys)
    d = client.get("/api/reports").json()
    assert d["summary"] is None and d["sync"]["state"] == "empty"
    sync.seed(log=lambda *_: None)
    d = client.get("/api/reports").json()
    assert d["sync"]["state"] == "example" and d["summary"]["meta"]["example"] is True
    sync.sync_odoo(od=FakeOdoo(n=400), log=lambda *_: None)
    s = client.get("/api/status").json()
    assert s["state"] == "live" and s["age_minutes"] <= 1
    with pytest.raises(OSError):
        sync.sync_odoo(od=FakeOdoo(fail=True), log=lambda *_: None)
    s = client.get("/api/status").json()
    assert s["state"] == "failed" and s["odoo"]["last"]["error"]
    assert client.get("/api/reports").json()["summary"]["meta"]["orders_scanned"] == 400  # last good data kept


def test_payload_size_with_gzip(client, capsys):
    login(client, capsys)
    sync.sync_odoo(od=FakeOdoo(n=6000), log=lambda *_: None)
    r = client.get("/api/reports", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert int(r.headers.get("content-length", len(r.content))) < 400_000


def test_ads_endpoint_live_join(client, capsys):
    login(client, capsys)
    sync.seed(log=lambda *_: None)
    d = client.get("/api/ads?window=today").json()
    assert d["has_spend"] and d["spend"]["T_lamp_TOFU_demo_v1"] == 12.0
    assert d["groups"]["T_lamp_TOFU_cheap_v1"]["raw"] == 14
    assert d["groups"]["UNATTRIBUTED"]["raw"] == 1
    assert d["days_running"]["T_lamp_TOFU_demo_v1"] == 0
    assert client.get("/api/ads?window=bogus").status_code == 422
    y = client.get("/api/ads?window=yesterday").json()
    assert not y["has_spend"]


def test_security_headers(client):
    r = client.get("/login")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
