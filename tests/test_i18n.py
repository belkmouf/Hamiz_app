"""English, French and Arabic share one key set, and brand colours stay readable."""
import colorsys
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def _catalogs():
    script = r"""
const fs = require("fs");
const vm = require("vm");
const ctx = {window: {}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync("web/i18n.js", "utf8"), ctx);
const packs = ctx.window.PULSE_I18N;
const langs = ["en", "fr", "ar"];
const keys = Object.fromEntries(langs.map(l => [l, Object.keys(packs[l] || {}).sort()]));
const out = {langs: Object.keys(packs), counts: {}, missing: {}, empty: [], same: {}};
for (const l of langs) out.counts[l] = keys[l].length;
for (const l of ["fr", "ar"]) {
  out.missing[l] = keys.en.filter(k => !Object.prototype.hasOwnProperty.call(packs[l], k));
  out.missing["en_vs_" + l] = keys[l].filter(k => !Object.prototype.hasOwnProperty.call(packs.en, k));
}
for (const k of keys.en) {
  for (const l of langs) if (!packs[l][k]) out.empty.push(l + ":" + k);
}
for (const k of ["goal.title", "spend.title", "nav.sales", "login.submit"]) {
  out.same[k] = {fr: packs.fr[k] === packs.en[k], ar: packs.ar[k] === packs.en[k]};
}
out.sample = {fr: packs.fr["goal.title"], ar: packs.ar["goal.title"], dzd: {en: packs.en["currency.dzd"], ar: packs.ar["currency.dzd"]}};
console.log(JSON.stringify(out));
"""
    proc = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)


def _literal_keys():
    keys = set()
    for name in ("app.js", "login.html"):
        text = (WEB / name).read_text(encoding="utf-8")
        found = re.findall(r"""(?<![A-Za-z0-9_.])t\(\s*["']([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)["']""", text)
        keys.update(k for k in found if "." in k)
    keys.update({
        "stage.pending", "stage.confirmed", "stage.delivered", "stage.returned", "stage.cancelled",
        "trimmed", "login.bad", "login.throttled", "login.unreachable", "login.linkError",
    })
    return keys


def test_every_language_has_the_same_keys():
    cat = _catalogs()
    assert cat["langs"] == ["en", "fr", "ar"]
    assert cat["counts"]["en"] == cat["counts"]["fr"] == cat["counts"]["ar"]
    assert cat["counts"]["en"] > 100
    assert cat["missing"]["fr"] == [] and cat["missing"]["ar"] == []
    assert cat["missing"]["en_vs_fr"] == [] and cat["missing"]["en_vs_ar"] == []
    assert cat["empty"] == []
    assert cat["same"]["goal.title"] == {"fr": False, "ar": False}
    assert cat["sample"]["dzd"]["ar"] != cat["sample"]["dzd"]["en"]


def test_ui_strings_are_in_every_catalog():
    cat_keys = set(json.loads(subprocess.run(
        ["node", "-e", """
const fs=require('fs');const vm=require('vm');const ctx={window:{}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/i18n.js','utf8'),ctx);
console.log(JSON.stringify(Object.keys(ctx.window.PULSE_I18N.en)));
"""], cwd=ROOT, check=True, capture_output=True, text=True).stdout))
    missing = sorted(_literal_keys() - cat_keys)
    assert missing == []


def test_rtl_is_wired_for_arabic():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    login = (WEB / "login.html").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    for text in (index, login):
        assert '"rtl"' in text and "hp.lang" in text
    assert '"rtl"' in app and 'getItem("hp."' in app
    assert 'localStorage.getItem("hp.lang")||\'"fr"\'' in index
    assert '[dir="rtl"]' in css
    assert "margin-inline-end" in css and "inset-inline-start" in css
    assert "Noto Sans Arabic" in css
    assert "ar-DZ-u-nu-latn" in app


def _lum(hex_color):
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]

    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _hue(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


def test_brand_colours_meet_contrast_and_spare_status():
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    root = re.search(r":root\{(?P<body>.*?)\}", css, re.S).group("body")
    colors = dict(re.findall(r"--([a-z0-9-]+):(#[0-9A-Fa-f]{6})", root))
    assert colors["accent"] == "#FF0050"
    assert colors["brand"] == "#E30613"
    assert colors["accent-2"] == "#E6007E"
    assert colors["bg"] == "#14080C"
    assert _contrast(colors["fg"], colors["bg"]) >= 4.5
    assert _contrast(colors["muted"], colors["bg"]) >= 4.5
    assert _contrast(colors["accent-ink"], colors["accent"]) >= 4.5
    assert _contrast(colors["fg"], colors["surface"]) >= 4.5
    for name in ("good", "warn", "bad", "info"):
        assert _contrast(colors[name], colors["bg"]) >= 4.5
    # Off-target orange must not sit on the brand red / magenta hues.
    assert 15 <= _hue(colors["bad"]) <= 50
    assert _hue(colors["brand"]) >= 330
    manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["theme_color"] == "#E30613"
    assert manifest["background_color"] == "#14080C"
