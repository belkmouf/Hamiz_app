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
