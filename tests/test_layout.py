"""PRD acceptance: no horizontal scroll at 375 px, light and dark, on every tab. Needs Playwright + Chromium."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parent.parent
TABS = {"sales": ["overview", "trend", "sellers", "products", "channels", "orders"], "ads": ["budget", "plan", "review"]}
SHOTS = os.environ.get("PULSE_SHOTS")  # set to a directory to save screenshots


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("srv")
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp}/pulse.db", "APP_SECRET_KEY": "layout-secret",
           "APP_ALLOWED_EMAILS": "belkacem@hamizonline.com", "PULSE_LOCK_FILE": str(tmp / "lock")}
    env.pop("PULSE_DEV_NO_AUTH", None)
    subprocess.run([sys.executable, "-m", "pulse.sync", "--seed"], cwd=ROOT, env=env, check=True, capture_output=True)
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "pulse.api:app", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    os.environ["APP_SECRET_KEY"] = "layout-secret"
    os.environ["APP_ALLOWED_EMAILS"] = "belkacem@hamizonline.com"
    from pulse import auth
    cookie = auth.make_session("belkacem@hamizonline.com")
    yield f"http://127.0.0.1:{port}", cookie
    proc.terminate()
    proc.wait()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_no_horizontal_scroll_at_375(server, scheme):
    base, cookie = server
    problems = []
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, color_scheme=scheme, device_scale_factor=2,
                                  service_workers="block")
        ctx.add_cookies([{"name": "hp_session", "value": cookie, "url": base}])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        page.goto(base + "/")
        page.wait_for_selector(".kpis")
        for section, tabs in TABS.items():
            page.click("#secSales" if section == "sales" else "#secAds")
            for tab in tabs:
                page.click(f'[data-tab="{tab}"]')
                if tab == "review":
                    page.wait_for_selector(".stats")
                page.wait_for_timeout(150)
                sw, cw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
                if sw > cw:
                    problems.append(f"{section}/{tab}: scrollWidth {sw} > {cw}")
                assert "could not render" not in page.inner_text("main"), f"{section}/{tab}"
                if SHOTS:
                    Path(SHOTS).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=f"{SHOTS}/{scheme}-{section}-{tab}.png", full_page=True)
        browser.close()
    assert not errors, errors
    assert not problems, problems
