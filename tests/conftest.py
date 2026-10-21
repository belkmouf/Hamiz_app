import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REF = ROOT / "reference"


def load_reference(name):
    spec = importlib.util.spec_from_file_location(f"ref_{name}", REF / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/pulse.db"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PULSE_LOCK_FILE", str(tmp_path / "sync.lock"))
    return url


@pytest.fixture
def client(db_url, monkeypatch):
    from fastapi.testclient import TestClient

    from pulse import auth

    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    monkeypatch.setenv("APP_ALLOWED_EMAILS", "belkacem@hamizonline.com, ops@hamizonline.com")
    monkeypatch.delenv("PULSE_DEV_NO_AUTH", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("PULSE_SEED_ON_EMPTY", "0")
    auth._last_request.clear()
    auth._login_failures.clear()
    from pulse.api import app
    return TestClient(app)
