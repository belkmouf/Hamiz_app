"""Several signed-in employees hitting the API at once keep their own sessions."""
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def api_server(tmp_path):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path}/pulse.db", "APP_SECRET_KEY": "concurrency-secret",
           "APP_ALLOWED_EMAILS": "", "APP_ADMIN_EMAIL": "chef@hamizonline.com", "APP_ADMIN_PASSWORD": "correct-horse",
           "PULSE_SEED_ON_EMPTY": "0", "PULSE_LOCK_FILE": str(tmp_path / "lock")}
    env.pop("PULSE_DEV_NO_AUTH", None)
    port = _port()
    logf = open(tmp_path / "uvicorn.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "pulse.api:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20
    up = False
    while time.time() < deadline:
        try:
            if httpx.get(base + "/healthz", timeout=0.3).status_code == 200:
                up = True
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    if not up:
        proc.kill()
        logf.close()
        pytest.fail("server did not start\n" + (tmp_path / "uvicorn.log").read_text(encoding="utf-8"))
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_parallel_sessions_stay_separate(api_server):
    base = api_server
    admin = httpx.Client(base_url=base, timeout=30)
    logged = admin.post("/auth/login", json={"email": "chef@hamizonline.com", "password": "correct-horse"})
    assert logged.status_code == 200, logged.text
    staff = [("amina@hamizonline.com", "Amina"), ("yacine@hamizonline.com", "Yacine"), ("lina@hamizonline.com", "Lina")]
    for email, name in staff:
        r = admin.post("/api/staff", json={"email": email, "name": name, "password": "staff-pass-1", "role": "staff"})
        assert r.status_code == 200, r.text
    clients = [("chef@hamizonline.com", admin)]
    for email, _name in staff:
        c = httpx.Client(base_url=base, timeout=30)
        r = c.post("/auth/login", json={"email": email, "password": "staff-pass-1"})
        assert r.status_code == 200, r.text
        clients.append((email, c))

    errors = []

    def hit(email, client):
        for _ in range(6):
            me = client.get("/api/me")
            reports = client.get("/api/reports")
            if me.status_code != 200 or reports.status_code != 200:
                errors.append((email, me.status_code, reports.status_code))
                return
            if me.json().get("email") != email:
                errors.append((email, "saw", me.json()))
                return
            if "pulse" not in reports.json():
                errors.append((email, "no pulse"))
                return

    threads = [threading.Thread(target=hit, args=pair) for pair in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert admin.get("/api/me").json()["role"] == "admin"
    assert clients[1][1].get("/api/staff").status_code == 403
