"""Phone viewport: three languages, Arabic RTL, refresh shows a new sync. Needs Playwright."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parent.parent
SHOTS = Path(os.environ.get("PULSE_PHONE_SHOTS", "/opt/cursor/artifacts/screenshots"))


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def phone(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("phone")
    db = tmp / "pulse.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "APP_SECRET_KEY": "phone-secret",
           "APP_ALLOWED_EMAILS": "belkacem@hamizonline.com", "PULSE_LOCK_FILE": str(tmp / "lock"),
           "PULSE_SEED_ON_EMPTY": "0"}
    env.pop("PULSE_DEV_NO_AUTH", None)
    subprocess.run([sys.executable, "-m", "pulse.sync", "--seed"], cwd=ROOT, env=env, check=True, capture_output=True)
    port = _port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "pulse.api:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("phone server did not start")
    prev_secret = os.environ.get("APP_SECRET_KEY")
    prev_allow = os.environ.get("APP_ALLOWED_EMAILS")
    os.environ["APP_SECRET_KEY"] = "phone-secret"
    os.environ["APP_ALLOWED_EMAILS"] = "belkacem@hamizonline.com"
    from pulse import auth
    cookie = auth.make_session("belkacem@hamizonline.com")
    if prev_secret is None:
        os.environ.pop("APP_SECRET_KEY", None)
    else:
        os.environ["APP_SECRET_KEY"] = prev_secret
    if prev_allow is None:
        os.environ.pop("APP_ALLOWED_EMAILS", None)
    else:
        os.environ["APP_ALLOWED_EMAILS"] = prev_allow
    yield f"http://127.0.0.1:{port}", cookie, f"sqlite:///{db}"
    proc.terminate()
    proc.wait(timeout=5)


def _open(base, cookie):
    p = pw.sync_playwright().start()
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, device_scale_factor=2,
                              locale="fr-DZ", service_workers="block", color_scheme="dark")
    ctx.add_cookies([{"name": "hp_session", "value": cookie, "url": base}])
    page = ctx.new_page()
    page.goto(base + "/")
    page.wait_for_selector("#dailyGoal")
    return p, browser, page


def test_dashboard_in_three_languages_and_arabic_rtl(phone):
    base, cookie, _db = phone
    SHOTS.mkdir(parents=True, exist_ok=True)
    p, browser, page = _open(base, cookie)
    try:
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        reports = page.request.get(base + "/api/reports", headers={"cookie": f"hp_session={cookie}"})
        assert "no-store" in reports.headers["cache-control"]
        bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert bg in ("rgb(20, 8, 12)", "rgba(20, 8, 12, 1)")
        brand = page.evaluate("""() => {
          const s = getComputedStyle(document.documentElement);
          return {accent: s.getPropertyValue('--accent').trim(), brand: s.getPropertyValue('--brand').trim(),
                  accent2: s.getPropertyValue('--accent-2').trim(), bg: s.getPropertyValue('--bg').trim()};
        }""")
        assert brand == {"accent": "#FF0050", "brand": "#E30613", "accent2": "#E6007E", "bg": "#14080C"}

        expect = {
            "fr": ("Objectif commandes", "ltr", "DZD"),
            "ar": ("هدف الطلبات", "rtl", "دج"),
            "en": ("Daily orders goal", "ltr", "DZD"),
        }
        for lang, (title, direction, money) in expect.items():
            if lang != "fr":
                page.click(f'[data-lang="{lang}"]')
                page.wait_for_function(
                    "(d) => document.documentElement.dir === d && document.querySelector('#dailyGoal')",
                    arg=direction,
                )
            text = page.inner_text("#dailyGoal")
            assert title in text
            assert page.evaluate("document.documentElement.dir") == direction
            assert money in page.inner_text("#spendCheck")
            assert page.locator("#lastSynced").inner_text()
            edges = page.evaluate("""() => {
              const b = document.querySelector('.brand').getBoundingClientRect();
              const l = document.querySelector('#langs').getBoundingClientRect();
              return {brand: b.left, lang: l.left};
            }""")
            if direction == "rtl":
                assert edges["brand"] > edges["lang"]
            else:
                assert edges["brand"] < edges["lang"]
            sw, cw = page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
            assert sw <= cw, f"{lang} scrollWidth {sw} > {cw}"
            page.screenshot(path=str(SHOTS / f"pulse-{lang}-375.png"), full_page=True)
        remembered = page.evaluate("JSON.parse(localStorage.getItem('hp.lang'))")
        assert remembered == "en"
        page.reload()
        page.wait_for_selector("#dailyGoal")
        assert page.evaluate("document.documentElement.lang") == "en"
        assert page.locator("#sync").get_attribute("data-state") == "example"
        from fake_odoo import FakeOdoo
        from pulse import sync
        sync.sync_odoo(url=_db, od=FakeOdoo(n=40), log=lambda *_: None)
        page.click("#refreshBtn")
        page.wait_for_function("() => document.querySelector('#sync')?.dataset.state === 'live'", timeout=15000)
        assert page.locator(".banner").count() == 0
        assert page.locator("#lastSynced").inner_text()
        assert page.locator("#dailyGoal").is_visible() and page.locator("#spendCheck").is_visible()
        assert not errors, errors
    finally:
        browser.close()
        p.stop()
