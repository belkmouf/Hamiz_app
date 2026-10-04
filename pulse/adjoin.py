"""Join Meta spend to Odoo orders for the live Ad review (PRD section 8).

1. Orders whose utm_content equals a Meta ad name count for that ad.
2. Fallback: a Meta campaign whose ads have no utm_content-matched orders in the window is scored as one row,
   keyed by campaign name, using orders whose UTM campaign equals the campaign name ("matched by campaign").
3. Orders with no UTM at all go to UNATTRIBUTED ("Fix tracking").
4. Orders with a UTM from another channel (not Meta) are left out and counted in `other_channels`.

Group shape matches web/calc.js: {raw, pending, conf, deliv, val[], approx}.
"""
from collections import defaultdict

META_SOURCES = ("fb", "facebook", "ig", "instagram", "meta", "an", "msg", "messenger")
UNATTRIBUTED = "UNATTRIBUTED"


def _norm(s):
    return " ".join(str(s or "").split()).lower()


def _is_meta(source):
    s = _norm(source)
    return any(s == m or s.startswith(m + " ") or s.startswith(m + ".") for m in META_SOURCES) or "facebook" in s


def _group():
    return {"raw": 0, "pending": 0, "conf": 0, "deliv": 0, "val": [], "approx": False}


def _add(g, o):
    g["raw"] += 1
    st = o["stage"]
    if st == "pending":
        g["pending"] += 1
    if st in ("confirmed", "delivered", "returned"):
        g["conf"] += 1
        if o.get("total"):
            g["val"].append(float(o["total"]))
    if st == "delivered":
        g["deliv"] += 1


def join(spend_rows, orders):
    ad_spend = defaultdict(float)
    ad_campaign = {}
    for r in spend_rows:
        ad_spend[r["ad_name"]] += float(r["spend_usd"] or 0)
        ad_campaign.setdefault(r["ad_name"], r.get("campaign_name"))
    by_ad_name = {_norm(a): a for a in ad_spend}
    campaign_ads = defaultdict(list)
    for a, c in ad_campaign.items():
        campaign_ads[_norm(c)].append(a)

    groups = defaultdict(_group)
    campaign_orders = defaultdict(list)
    other = 0
    for o in orders:
        ad, camp, src = o.get("ad"), o.get("campaign"), o.get("source")
        if ad:
            _add(groups[by_ad_name.get(_norm(ad), ad)], o)  # keep Meta's spelling when the names match
        elif camp and _norm(camp) in campaign_ads:
            campaign_orders[_norm(camp)].append(o)
        elif not (ad or camp or src):
            _add(groups[UNATTRIBUTED], o)
        elif src and not _is_meta(src):
            other += 1
        else:
            _add(groups[UNATTRIBUTED], o)  # Meta traffic we cannot tie to an ad or campaign

    spend = dict(ad_spend)
    for ck, ads in campaign_ads.items():
        if any(groups.get(a, {}).get("raw") for a in ads):
            # The campaign tracks ads: its campaign-only orders are a tracking gap.
            for o in campaign_orders.get(ck, []):
                _add(groups[UNATTRIBUTED], o)
            continue
        if not campaign_orders.get(ck):
            continue
        name = ad_campaign[ads[0]] or ck
        g = groups[name]
        g["approx"] = True
        for o in campaign_orders[ck]:
            _add(g, o)
        spend[name] = spend.get(name, 0.0) + sum(spend.pop(a, 0.0) for a in ads)
    members = {ad_campaign[a[0]] or ck: a for ck, a in campaign_ads.items()}
    return spend, dict(groups), other, members
