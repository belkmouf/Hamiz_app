"""Password sign-in, admin staff management, and session isolation."""
from fastapi.testclient import TestClient

from pulse import auth, store


def test_bootstrap_creates_admin_once(db_url, monkeypatch):
    monkeypatch.setenv("APP_ADMIN_EMAIL", "chef@hamizonline.com")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "short")
    assert auth.bootstrap_admin() is None
    assert store.get_staff("chef@hamizonline.com") is None
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "correct-horse")
    assert auth.bootstrap_admin() == "chef@hamizonline.com"
    row = store.get_staff("chef@hamizonline.com")
    assert row["role"] == "admin" and row["active"] and auth.verify_password("correct-horse", row["password_hash"])
    assert auth.bootstrap_admin() is None
    assert auth.verify_password("correct-horse", store.get_staff("chef@hamizonline.com")["password_hash"])


def test_password_login_staff_admin_and_sessions(client, monkeypatch):
    monkeypatch.setenv("APP_ADMIN_EMAIL", "chef@hamizonline.com")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "correct-horse")
    auth.bootstrap_admin()

    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": "correct-horse"})
    wrong = client.post("/auth/login", json={"email": "chef@hamizonline.com", "password": "nope-nope"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"ok": False, "error": "invalid_login"}

    ok = client.post("/auth/login", json={"email": "chef@hamizonline.com", "password": "correct-horse"})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert "hp_session" in ok.headers["set-cookie"] and "httponly" in ok.headers["set-cookie"].lower()
    assert client.get("/api/me").json() == {"email": "chef@hamizonline.com", "name": "chef", "role": "admin"}

    created = client.post("/api/staff", json={"email": "Amina@HamizOnline.com", "name": "Amina", "password": "amina-pass", "role": "staff"})
    assert created.status_code == 200
    assert client.post("/api/staff", json={"email": "short@hamizonline.com", "password": "tiny"}).status_code == 400
    listed = client.get("/api/staff").json()["staff"]
    assert {s["email"] for s in listed} == {"chef@hamizonline.com", "amina@hamizonline.com"}
    assert all("password_hash" not in s for s in listed)

    amina = TestClient(client.app)
    assert amina.post("/auth/login", json={"email": "amina@hamizonline.com", "password": "amina-pass"}).status_code == 200
    assert amina.get("/api/me").json()["email"] == "amina@hamizonline.com"
    assert amina.get("/api/staff").status_code == 403
    assert amina.get("/api/reports").status_code == 200
    assert client.get("/api/me").json()["email"] == "chef@hamizonline.com"

    assert client.delete("/api/staff/chef@hamizonline.com").status_code == 400
    assert client.post("/api/staff", json={"email": "chef@hamizonline.com", "role": "staff", "password": ""}).status_code == 400
    assert client.delete("/api/staff/amina@hamizonline.com").status_code == 200
    assert amina.get("/api/me").status_code == 401
    assert amina.get("/api/reports").status_code == 401

    # An allowlist address with no staff row can sign in. An inactive row blocks it.
    assert auth.role_for("ops@hamizonline.com") == "staff"
    assert client.delete("/api/staff/ops@hamizonline.com").status_code == 200
    assert auth.role_for("ops@hamizonline.com") is None


def test_login_throttles_after_repeated_failures(db_url, monkeypatch):
    monkeypatch.setenv("APP_ADMIN_EMAIL", "chef@hamizonline.com")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "correct-horse")
    auth.bootstrap_admin()
    auth._login_failures.clear()
    email = "chef@hamizonline.com"
    for _ in range(8):
        assert auth.check_password(email, "wrong-password") is False
    assert auth.check_password(email, "correct-horse") == "throttled"
    auth.clear_login_failures(email)
    assert auth.check_password(email, "correct-horse") is True
