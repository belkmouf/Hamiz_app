#!/usr/bin/env python3
"""Meta ads math for Algerian COD stores, built around a CAC cap as % of order value.

Subcommands:
  cac        the CAC budget: max ad cost per delivered / confirmed / form order,
             daily spend at the volume target, and what the funnel must deliver
  plan       test budget check, decision rules, capacity, scaling schedule
  review     per-ad KILL / WAIT / PROMOTE on CAC % of order value
  economics  margin and breakeven per order (secondary: profit check)

CAC here = ad spend in DA / orders PLACED (form orders), unless --cac-basis says otherwise.
Volume targets (--low/--high) are counted on the same basis unless --volume-basis says otherwise.
"""
import argparse
import csv
import math
import sys
from collections import defaultdict

BASIS_HELP = "what CAC is divided by: raw = orders placed (default), confirmed, or delivered"
LABEL = {"raw": "placed", "confirmed": "confirmed", "delivered": "delivered"}
VOL_HELP = "what the 200-250/day target counts: raw = orders placed (default), confirmed, or delivered"


def to_delivered(t, basis, c, d):
    return {"raw": t * c * d, "confirmed": t * d, "delivered": t}[basis]


def basis_mult(basis, c, d):
    """Multiplier converting a per-<basis> cost into a per-confirmed cost."""
    return {"delivered": d, "confirmed": 1.0, "raw": 1.0 / c}[basis]


def cap_per_confirmed_usd(cac_pct, aov, fx, basis, c, d):
    return cac_pct * aov * basis_mult(basis, c, d) / fx


def cac(a):
    c, d, fx = a.confirm_rate, a.delivery_rate, a.fx
    cap_da = a.cac_pct * a.aov
    # cost allowed per unit, expressed for each stage of the funnel
    per_conf_da = cap_da * basis_mult(a.cac_basis, c, d)
    per_deliv, per_raw = per_conf_da / d, per_conf_da * c
    print(f"Rule: ad spend <= {a.cac_pct:.0%} of order value per {LABEL[a.cac_basis]} order")
    print(f"Assumptions: AOV {a.aov:,.0f} DA, confirm {c:.0%}, delivery {d:.0%}, fx {fx:g} DA per USD of ad spend")
    print()
    print(f"{'Max ad cost per':24s} {'DA':>8s} {'USD':>7s}")
    for label, v in (("delivered order", per_deliv), ("confirmed order", per_conf_da), ("form order (Meta CPA)", per_raw)):
        print(f"{label:24s} {v:8,.0f} {v / fx:7.2f}")
    print()
    print("Daily ad budget allowed at the volume target (scaling + testing):")
    for t in (a.low, a.high):
        td = to_delivered(t, a.volume_basis, c, d)
        spend_da = td * per_deliv
        print(f"  {td / (c * d):4.0f} placed -> ~{td / d:4.0f} confirmed -> ~{td:4.0f} delivered/day: max ${spend_da / fx:,.0f}/day ({spend_da:,.0f} DA)")
    true_pct = per_deliv / a.aov
    if a.cac_basis != "delivered":
        print(f"  Same spend as cost per DELIVERED order: {per_deliv:,.0f} DA = {true_pct:.1%} of order value (the real COD cost)")
    print()
    raw_usd = per_raw / fx
    print(f"What the funnel must deliver to keep Meta CPA <= ${raw_usd:.2f} per form order")
    print("(landing conversion = form orders / link clicks; plug in your real CPM and CTR)")
    cpms = a.cpm or [0.5, 1.0, 1.5, 2.0]
    ctrs = a.ctr or [0.015, 0.025, 0.04]
    print(f"  {'CPM $':>6s} " + " ".join(f"{'CTR ' + format(t, '.1%'):>11s}" for t in ctrs))
    for m in cpms:
        cells = []
        for t in ctrs:
            cpc = m / (1000 * t)
            need = cpc / raw_usd if raw_usd > 0 else float("inf")
            cells.append(f"{need:11.1%}" if need <= 1 else f"{'impossible':>11s}")
        print(f"  {m:6.2f} " + " ".join(cells))
    print("  Cells show the landing conversion rate needed. Above ~10-15% is rare for cold traffic;")
    print("  if your row needs that, raise AOV (bundles) or lower costs before scaling.")
    print()
    print(f"Use --target-cpa {per_conf_da / fx:.2f} (USD per confirmed order) in plan, or pass the same --cac-pct/--aov/--fx.")


def plan(a):
    c, d = a.confirm_rate, a.delivery_rate
    if a.target_cpa is None:
        if not (a.cac_pct and a.aov and a.fx):
            sys.exit("plan needs --target-cpa, or --cac-pct with --aov and --fx")
        a.target_cpa = cap_per_confirmed_usd(a.cac_pct, a.aov, a.fx, a.cac_basis, c, d)
        derived = True
    else:
        derived = False
    cpa = a.target_cpa
    print(f"Target cost per CONFIRMED order: ${cpa:.2f}" + (f"  (= {a.cac_pct:.0%} of {a.aov:,.0f} DA per {LABEL[a.cac_basis]} order)" if derived else ""))
    print()
    print("TESTING CAMPAIGN")
    need = a.creatives * a.min_spend
    if need <= a.test_budget:
        print(f"  {a.creatives} ad sets x ${a.min_spend:g} min = ${need:g} <= ${a.test_budget:g} budget. Test all at once.")
    else:
        per_wave = max(1, int(a.test_budget // a.min_spend))
        print(f"  {a.creatives} ad sets x ${a.min_spend:g} min = ${need:g} > ${a.test_budget:g} budget.")
        print(f"  Raise test budget to ${need:g}/day, or run {math.ceil(a.creatives / per_wave)} waves of {per_wave}.")
    print(f"  Testing spend counts toward CAC. At target volume it should stay under ~10% of total spend.")
    print()
    print("DECISION RULES (per ad, on CONFIRMED orders)")
    print(f"  Judge after 3 days or ${2.5 * cpa:.2f} spend, whichever comes later")
    print(f"  PROMOTE  cost/confirmed <= ${cpa:.2f} with 3+ confirmed")
    print(f"  KILL     cost/confirmed > ${1.5 * cpa:.2f}, or ${2.5 * cpa:.2f} spent with 0 confirmed")
    print(f"  KILL     confirmation under {max(0.0, c - 0.2):.0%} with 10+ resolved orders (junk traffic)")
    print()
    print("TARGET")
    for t in (a.low, a.high):
        td = to_delivered(t, a.volume_basis, c, d)
        print(f"  ~{td / (c * d):.0f} placed, ~{td / d:.0f} confirmed, ~{td:.0f} delivered/day: ~${td / d * cpa:,.0f}/day ad spend")
    hi_deliv = to_delivered(a.high, a.volume_basis, c, d)
    hi_spend = hi_deliv / d * cpa
    ceiling_spend = hi_spend
    if a.call_capacity:
        cap_deliv = a.call_capacity * c * d
        flag = "OK" if cap_deliv >= hi_deliv - 0.5 else "TOO LOW"
        print(f"  Call capacity {a.call_capacity:g}/day [{flag}]: need ~{hi_deliv / (c * d):.0f} calls/day (one per placed order, before retries)")
        ceiling_spend = min(ceiling_spend, a.call_capacity * c * cpa)
    if a.stock:
        print(f"  Stock {a.stock:g} units covers ~{a.stock / (hi_deliv / d):.0f} days at the high target")
    if a.fx:
        print(f"  Cash float: ~{a.remit_days:g} days of ad spend before COD cash returns -> ~${hi_spend * a.remit_days:,.0f} ({hi_spend * a.remit_days * a.fx:,.0f} DA)")
    print()
    print("SCALING SCHEDULE (step only if last 3 days hold cost/confirmed <= target)")
    top = max(ceiling_spend - a.test_budget, a.scale_start)
    for gap in (2, 1):
        budget, day, step = a.scale_start, 1, 0
        print(f"  +{a.step:.0%} every {24 * gap}h")
        print(f"  {'step':>4s} {'day':>5s} {'scale $/day':>11s} {'~placed/day':>11s} {'~conf/day':>10s} {'~deliv/day':>10s}")
        while True:
            conf = budget / cpa
            if step % 3 == 0 or budget >= top:
                print(f"  {step:4d} {day:5d} {budget:11.0f} {conf / c:11.0f} {conf:10.0f} {conf * d:10.0f}")
            if budget >= top or step > 80:
                break
            budget = min(budget * (1 + a.step), top)
            step += 1
            day += gap
        print(f"  -> high target around day {day} (~{day / 7:.1f} weeks)")
        print()
    print("  This assumes CPA holds as spend grows. It usually rises. Under a hard CAC cap, the cap wins:")
    print("  stop scaling where CAC hits the cap, and add products or raise AOV to get more volume.")


def review(a):
    spend = defaultdict(float)
    with open(a.ads, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            spend[r["ad_name"].strip()] += float(r["spend"] or 0)
    st = defaultdict(lambda: defaultdict(int))
    vals = defaultdict(list)
    with open(a.orders, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ad = (r.get("ad_name") or "").strip() or "UNATTRIBUTED"
            status = r["status"].strip().lower()
            st[ad][status] += 1
            v = (r.get("value") or "").strip()
            if v and status in ("confirmed", "delivered", "returned"):
                vals[ad].append(float(v))
    c, d, fx = a.confirm_rate, a.delivery_rate, a.fx
    mult = basis_mult(a.cac_basis, c, d)
    rows = []
    for ad in sorted(set(spend) | set(st)):
        s = st[ad]
        raw = sum(s.values())
        conf = s["confirmed"] + s["delivered"] + s["returned"]
        resolved = raw - s["pending"]
        rate = conf / resolved if resolved else 0
        sp = spend.get(ad, 0.0)
        aov = sum(vals[ad]) / len(vals[ad]) if vals[ad] else a.aov
        cap_conf = cap_per_confirmed_usd(a.cac_pct, aov, fx, a.cac_basis, c, d)
        cpc = sp / conf if conf else float("inf")
        cap_raw = a.cac_pct * aov / fx
        # CAC as % of this ad's own AOV, on the chosen basis
        if a.cac_basis == "raw":
            cac_pct = (sp * fx / raw) / aov if raw else float("inf")
        else:
            cac_pct = (cpc / mult * fx) / aov if conf else float("inf")
        n_basis = raw if a.cac_basis == "raw" else conf
        if ad == "UNATTRIBUTED":
            dec = "FIX TRACKING: orders without utm_content"
        elif raw and s["pending"] / raw > 0.5:
            dec = "WAIT: most orders still pending, quality unknown"
        elif resolved >= 10 and rate < a.min_confirm:
            dec = f"KILL: confirmation {rate:.0%} = junk orders, inflates real CAC"
        elif n_basis >= 3 and conf >= 2 and cac_pct <= a.cac_pct:
            dec = "PROMOTE: under the CAC cap"
        elif n_basis >= 3 and cac_pct > 1.5 * a.cac_pct and sp >= 2.5 * cap_raw:
            dec = f"KILL: CAC {cac_pct:.1%} of order value"
        elif raw == 0 and sp >= 2.5 * cap_raw:
            dec = "KILL: 2.5x the allowed cost per order with no order"
        else:
            dec = "WAIT: not enough data"
        rows.append((ad, sp, raw, s["pending"], conf, rate, cpc, aov, cac_pct, dec))
    rows.sort(key=lambda r: r[8])
    fmt = lambda x, p: (f"{x:.{p}f}" if x != float("inf") else "-")
    print(f"Cap: CAC <= {a.cac_pct:.0%} of order value per {LABEL[a.cac_basis]} order (projected with delivery {d:.0%}, fx {fx:g})")
    print(f"{'ad':30s} {'spend$':>7s} {'raw':>4s} {'pend':>4s} {'conf':>4s} {'conf%':>5s} {'$/conf':>6s} {'AOV DA':>7s} {'CAC%':>6s}  decision")
    for ad, sp, raw, pend, conf, rate, cpc, aov, cp, dec in rows:
        cps = f"{cp:6.1%}" if cp != float("inf") else f"{'-':>6s}"
        print(f"{ad[:30]:30s} {sp:7.2f} {raw:4d} {pend:4d} {conf:4d} {rate:5.0%} {fmt(cpc, 2):>6s} {aov:7,.0f} {cps}  {dec}")
    sp_all = sum(r[1] for r in rows)
    conf_all = sum(r[4] for r in rows)
    val_all = sum(sum(v) for v in vals.values())
    print()
    raw_all = sum(r[2] for r in rows)
    if conf_all:
        units = raw_all if a.cac_basis == "raw" else conf_all / mult
        blended = sp_all * fx / units
        avg = val_all / conf_all if val_all else a.aov
        print(f"Account: ${sp_all:,.2f} spend, {conf_all} confirmed, ~{conf_all * d:.0f} projected delivered")
        print(f"Blended CAC ~{blended:,.0f} DA per {LABEL[a.cac_basis]} order = {blended / avg:.1%} of avg order value {avg:,.0f} DA "
              f"[{'OK' if blended / avg <= a.cac_pct else 'OVER CAP'}]")
        if a.cac_basis != "delivered":
            true = sp_all * fx / (conf_all * d)
            print(f"For reference, projected cost per DELIVERED order: {true:,.0f} DA = {true / avg:.1%} of order value")
    print("Projections apply the delivery rate to confirmed orders. Replace with actual delivered counts weekly.")


def economics(a):
    d, c = a.delivery_rate, a.confirm_rate
    gross = a.price - a.cogs - a.delivery_cost
    per_conf = d * gross - (1 - d) * a.return_cost - a.call_cost / c
    print(f"Gross margin per delivered order: {gross:,.0f} DA")
    print(f"Expected margin per confirmed order before ads: {per_conf:,.0f} DA")
    print(f"Breakeven ad cost per confirmed order: {per_conf:,.0f} DA (${per_conf / a.fx:.2f})")
    if a.cac_pct:
        ad_cost = a.cac_pct * a.price * d
        print(f"At {a.cac_pct:.0%} CAC per delivered order: ad cost {ad_cost:,.0f} DA per confirmed, "
              f"leaving {per_conf - ad_cost:,.0f} DA per confirmed ({(per_conf - ad_cost) / d:,.0f} DA per delivered)")


def add_funnel(p, need_fx=True):
    p.add_argument("--confirm-rate", type=float, required=True)
    p.add_argument("--delivery-rate", type=float, required=True)
    p.add_argument("--fx", type=float, required=need_fx, help="DA actually paid per 1 USD of ad spend")
    p.add_argument("--cac-basis", choices=["raw", "confirmed", "delivered"], default="raw", help=BASIS_HELP)
    p.add_argument("--volume-basis", choices=["raw", "confirmed", "delivered"], default="raw", help=VOL_HELP)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("cac")
    k.add_argument("--aov", type=float, required=True, help="average order value DA")
    k.add_argument("--cac-pct", type=float, default=0.05)
    k.add_argument("--low", type=float, default=200)
    k.add_argument("--high", type=float, default=250)
    k.add_argument("--cpm", type=float, nargs="*", help="CPM values in USD to test")
    k.add_argument("--ctr", type=float, nargs="*", help="link CTR values to test, e.g. 0.02")
    add_funnel(k)

    pl = sub.add_parser("plan")
    pl.add_argument("--target-cpa", type=float, help="USD per confirmed order (or derive from --cac-pct/--aov/--fx)")
    pl.add_argument("--aov", type=float)
    pl.add_argument("--cac-pct", type=float, default=0.05)
    pl.add_argument("--low", type=float, default=200)
    pl.add_argument("--high", type=float, default=250)
    pl.add_argument("--creatives", type=int, default=6)
    pl.add_argument("--test-budget", type=float, default=18)
    pl.add_argument("--min-spend", type=float, default=3)
    pl.add_argument("--scale-start", type=float, default=20)
    pl.add_argument("--step", type=float, default=0.2)
    pl.add_argument("--call-capacity", type=float, default=0, help="confirmation calls per day")
    pl.add_argument("--stock", type=float, default=0)
    pl.add_argument("--remit-days", type=float, default=10)
    add_funnel(pl, need_fx=False)

    r = sub.add_parser("review")
    r.add_argument("--ads", required=True, help="CSV ad_name,spend")
    r.add_argument("--orders", required=True, help="CSV ad_name,status,value")
    r.add_argument("--aov", type=float, required=True, help="fallback AOV DA when an ad's orders have no value")
    r.add_argument("--cac-pct", type=float, default=0.05)
    r.add_argument("--min-confirm", type=float, default=0.5)
    add_funnel(r)

    e = sub.add_parser("economics")
    e.add_argument("--price", type=float, required=True)
    e.add_argument("--cogs", type=float, required=True)
    e.add_argument("--delivery-cost", type=float, default=0)
    e.add_argument("--return-cost", type=float, default=0)
    e.add_argument("--call-cost", type=float, default=0)
    e.add_argument("--cac-pct", type=float)
    add_funnel(e)

    a = p.parse_args()
    for key in ("confirm_rate", "delivery_rate"):
        v = getattr(a, key, None)
        if v is not None and not 0 < v <= 1:
            sys.exit(f"--{key.replace('_', '-')} must be between 0 and 1")
    {"cac": cac, "plan": plan, "review": review, "economics": economics}[a.cmd](a)


if __name__ == "__main__":
    main()
