import csv
import json
import re
import subprocess
import sys

import pytest

from conftest import REF, ROOT

from pulse import calc

ADS, ORDERS = REF / "examples" / "ads.csv", REF / "examples" / "orders.csv"
FUNNEL = ["--confirm-rate", "0.7", "--delivery-rate", "0.75", "--fx", "250"]


def cli(*args):
    out = subprocess.run([sys.executable, str(REF / "dz_cod_calc.py"), *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


def node(js):
    calc_js = ROOT / "web" / "calc.js"
    return json.loads(subprocess.check_output(["node", "-e", f"const C=require({json.dumps(str(calc_js))});{js}"], text=True))


# ---------------------------------------------------------------- CAC budget
def test_prd_acceptance_values():
    b = calc.cac_budget(aov=4500, c=0.70, d=0.75, fx=250, cac_pct=0.05, basis="raw", low=200, high=250)
    assert f"{b['per_placed_usd']:.2f}" == "0.90"
    assert f"{b['per_confirmed_usd']:.2f}" == "1.29"
    assert f"{b['per_delivered_usd']:.2f}" == "1.71"
    assert f"{b['daily'][0]['spend_usd']:,.0f}" == "180"
    assert f"{b['daily'][1]['spend_usd']:,.0f}" == "225"


def test_cac_matches_reference_cli():
    out = cli("cac", "--aov", "4500", *FUNNEL)
    b = calc.cac_budget(aov=4500, c=0.7, d=0.75, fx=250)
    rows = dict(re.findall(r"^(delivered order|confirmed order|form order \(Meta CPA\))\s+[\d,]+\s+([\d.]+)$", out, re.M))
    assert rows["form order (Meta CPA)"] == f"{b['per_placed_usd']:.2f}"
    assert rows["confirmed order"] == f"{b['per_confirmed_usd']:.2f}"
    assert rows["delivered order"] == f"{b['per_delivered_usd']:.2f}"
    daily = re.findall(r"max \$([\d,]+)/day", out)
    assert daily == [f"{d['spend_usd']:,.0f}" for d in b["daily"]]


@pytest.mark.parametrize("basis", ["raw", "confirmed", "delivered"])
def test_cac_js_matches_python(basis):
    b = calc.cac_budget(aov=6100, c=0.66, d=0.81, fx=262, cac_pct=0.05, basis=basis, low=200, high=250)
    j = node(f"console.log(JSON.stringify(C.cacBudget({{aov:6100,c:.66,d:.81,fx:262,cac:.05,basis:{json.dumps(basis)},low:200,high:250}})))")
    assert j["perRaw"] == pytest.approx(b["per_placed_da"])
    assert j["perConf"] == pytest.approx(b["per_confirmed_da"])
    assert j["perDeliv"] == pytest.approx(b["per_delivered_da"])
    assert [d["spend"] for d in j["daily"]] == pytest.approx([d["spend_da"] for d in b["daily"]])


def test_landing_grid_matches_cli():
    out = cli("cac", "--aov", "4500", *FUNNEL, "--cpm", "0.5", "2", "--ctr", "0.015", "0.04")
    per_placed = calc.cac_budget(aov=4500, c=0.7, d=0.75, fx=250)["per_placed_usd"]
    grid = re.findall(r"^\s+(0\.50|2\.00)\s+(.+)$", out, re.M)
    for cpm_s, cells in grid:
        want = cells.split()
        got = []
        for ctr in (0.015, 0.04):
            need = calc.landing_needed(float(cpm_s), ctr, per_placed)
            got.append(f"{need:.1%}" if need <= 1 else "impossible")
        assert got == want
    j = node("console.log(JSON.stringify(C.landingNeeded(2,1.5,0.9)))")
    assert j == pytest.approx(calc.landing_needed(2, 0.015, 0.9))


# ---------------------------------------------------------------- Ad review
def _cli_review(basis="raw"):
    out = cli("review", "--ads", str(ADS), "--orders", str(ORDERS), "--aov", "4500", *FUNNEL, "--cac-basis", basis)
    rows = {}
    for line in out.splitlines():
        m = re.match(r"^(\S+)\s+[\d.]+\s+\d+\s+\d+\s+\d+\s+\d+%\s+\S+\s+[\d,]+\s+(\S+)\s+(\w+(?: \w+)?):", line)
        if m:
            rows[m.group(1)] = (m.group(3).split()[0], m.group(2))
    blended = re.search(r"= ([\d.]+)% of avg order value [\d,]+ DA \[(OK|OVER CAP)\]", out)
    return rows, blended.groups(), out


def _ours(basis="raw"):
    with open(ADS, newline="", encoding="utf-8-sig") as f:
        spend = {}
        for r in csv.DictReader(f):
            spend[r["ad_name"].strip()] = spend.get(r["ad_name"].strip(), 0) + float(r["spend"])
    with open(ORDERS, newline="", encoding="utf-8-sig") as f:
        groups = calc.groups_from_csv_rows(list(csv.DictReader(f)))
    return calc.review(spend, groups, aov=4500, fx=250, cac_pct=0.05, basis=basis, c=0.7, d=0.75)


CODE = {"PROMOTE": "promote", "KILL": "kill", "WAIT": "wait", "FIX TRACKING": "fix", "FIX": "fix"}


@pytest.mark.parametrize("basis", ["raw", "confirmed", "delivered"])
def test_review_decisions_match_reference_cli(basis):
    want, (blended_pct, ok), out = _cli_review(basis)
    rows, account = _ours(basis)
    assert len(want) == len(rows) == 6, out
    for r in rows:
        assert CODE[want[r["ad"][:30]][0]] == r["decision"], (r["ad"], want[r["ad"][:30]], r["label"])
        cps = want[r["ad"][:30]][1]
        assert cps == ("-" if r["cac_pct"] == float("inf") else f"{r['cac_pct']:.1%}")
    assert [r["ad"] for r in rows] == [line.split()[0] for line in out.splitlines()
                                       if line.split() and line.split()[0] in {x["ad"] for x in rows}]
    assert f"{account['blended_cac_pct']:.1%}" == f"{blended_pct}%"
    assert ("OK" if account["ok"] else "OVER CAP") == ok


def test_review_expected_decisions():
    rows, _ = _ours()
    got = {r["ad"]: r["label"] for r in rows}
    assert got["UNATTRIBUTED"] == "Fix tracking"
    assert got["T_lamp_MOFU_compare_v1"] == "Wait: most orders still pending"
    assert got["T_lamp_TOFU_cheap_v1"] == "Kill: junk orders"
    assert got["T_lamp_BOFU_bundle_v1"] == "Kill: CAC 10.3%"
    assert got["T_lamp_TOFU_demo_v1"] == "Kill: CAC 11.1%"
    assert got["T_lamp_MOFU_ugc_v1"] == "Kill: CAC 12.2%"


@pytest.mark.parametrize("basis", ["raw", "confirmed", "delivered"])
def test_review_js_matches_python(basis):
    rows, account = _ours(basis)
    js = (f"const fs=require('fs');const sp=C.spendFromCsv(fs.readFileSync({json.dumps(str(ADS))},'utf8'));"
          f"const g=C.groupsFromCsv(fs.readFileSync({json.dumps(str(ORDERS))},'utf8'));"
          f"const r=C.review(sp,g,{{aov:4500,c:.7,d:.75,fx:250,cac:.05,basis:{json.dumps(basis)}}},null);"
          "console.log(JSON.stringify({rows:r.rows.map(x=>[x.n,x.code,x.label,isFinite(x.cac)?x.cac:null]),blended:r.account.blended,ok:r.account.ok}))")
    j = node(js)
    assert [x[0] for x in j["rows"]] == [r["ad"] for r in rows]
    assert [x[1] for x in j["rows"]] == [r["decision"] for r in rows]
    assert [x[2] for x in j["rows"]] == [r["label"] for r in rows]
    for x, r in zip(j["rows"], rows):
        assert (x[3] is None) == (r["cac_pct"] == float("inf"))
        if x[3] is not None:
            assert x[3] == pytest.approx(r["cac_pct"])
    assert j["blended"] == pytest.approx(account["blended_cac_pct"])
    assert j["ok"] == account["ok"]


def test_young_ads_hold_cac_kills_but_not_junk_kills():
    g = calc.new_group()
    for st in ["confirmed"] * 3:
        calc.add_order(g, st, 4500)
    # $40 for 3 orders at 4,500 DA = 74% CAC: a kill after 3 days, a wait before.
    code, label, *_ = calc.decide("ad", g, 40, 4500, 250, 0.05, "raw", 0.7, 0.75, days_running=1)
    assert code == "wait" and label.startswith("Wait: under 3 full days")
    code, *_ = calc.decide("ad", g, 40, 4500, 250, 0.05, "raw", 0.7, 0.75, days_running=3)
    assert code == "kill"
    junk = calc.new_group()
    for st in ["cancelled"] * 8 + ["confirmed"] * 2:
        calc.add_order(junk, st, 4500)
    code, label, *_ = calc.decide("ad", junk, 5, 4500, 250, 0.05, "raw", 0.7, 0.75, days_running=0)
    assert label == "Kill: junk orders"


def test_ads_manager_column_names_in_js():
    text = '"Ad name","Amount spent (USD)","Reporting starts"\n"Ad A","12.50","2026-10-04"\n"Ad A","1,000.00","2026-10-03"\n'
    j = node(f"console.log(JSON.stringify(C.spendFromCsv({json.dumps(text)})))")
    assert j == {"Ad A": pytest.approx(1012.5)}
