"""Meta Marketing API, Insights at ad level (PRD section 8). Read-only: GET requests with an ads_read token."""
import json
import time
from datetime import datetime

import httpx

from .config import env

FIELDS = "campaign_id,campaign_name,adset_name,ad_id,ad_name,spend,impressions,clicks,actions"
PURCHASE_TYPES = ("purchase", "offsite_conversion.fb_pixel_purchase")
RATE_LIMIT_CODES = {4, 17, 32, 613, 80000, 80004}
TRIES = 4


class MetaError(RuntimeError):
    pass


def purchases(actions):
    """The purchase count from an insights `actions` list. Display only."""
    by = {a.get("action_type"): a.get("value") for a in (actions or [])}
    for t in PURCHASE_TYPES:
        if by.get(t) is not None:
            return int(float(by[t]))
    return 0


def usage_pct(headers):
    """Highest usage % in x-business-use-case-usage (or x-ad-account-usage)."""
    worst = 0.0
    raw = headers.get("x-business-use-case-usage")
    if raw:
        try:
            for entries in json.loads(raw).values():
                for e in entries:
                    worst = max(worst, *(float(e.get(k) or 0) for k in ("call_count", "total_cputime", "total_time")))
        except (ValueError, TypeError, AttributeError):
            pass
    raw = headers.get("x-ad-account-usage")
    if raw:
        try:
            worst = max(worst, float(json.loads(raw).get("acc_id_util_pct") or 0))
        except (ValueError, TypeError, AttributeError):
            pass
    return worst


def normalise(row):
    return {
        "date": datetime.strptime(row["date_start"], "%Y-%m-%d").date(),
        "campaign_id": row.get("campaign_id"), "campaign_name": row.get("campaign_name"),
        "adset_name": row.get("adset_name"), "ad_id": row["ad_id"], "ad_name": (row.get("ad_name") or "").strip(),
        "spend_usd": float(row.get("spend") or 0), "impressions": int(float(row.get("impressions") or 0)),
        "clicks": int(float(row.get("clicks") or 0)), "meta_purchases": purchases(row.get("actions")),
    }


class Meta:
    def __init__(self, token, account_id, version=None, client=None, sleep=time.sleep):
        self.token = token
        self.account = account_id if str(account_id).startswith("act_") else f"act_{account_id}"
        self.version = version or env("META_API_VERSION", "v24.0")
        self.http = client or httpx.Client(timeout=60)
        self.sleep = sleep

    def _get(self, url, params):
        for attempt in range(TRIES):
            try:
                r = self.http.get(url, params=params)
            except httpx.TransportError:
                if attempt == TRIES - 1:
                    raise
                self.sleep(2 ** attempt * 5)
                continue
            if r.status_code == 200:
                if usage_pct(r.headers) >= 75:  # slow down before Meta throttles us
                    self.sleep(60)
                return r.json()
            err = {}
            try:
                err = r.json().get("error", {})
            except ValueError:
                pass
            limited = err.get("code") in RATE_LIMIT_CODES or r.status_code in (429, 500, 502, 503)
            if limited and attempt < TRIES - 1:
                self.sleep(2 ** attempt * 30)
                continue
            raise MetaError(f"Meta API {r.status_code}: {err.get('message') or r.text[:300]}")
        raise MetaError("Meta API: retries exhausted")

    def account_info(self):
        """Currency and time zone of the ad account. Insights report spend in this currency and days in this zone."""
        url = f"https://graph.facebook.com/{self.version}/{self.account}"
        d = self._get(url, {"fields": "currency,timezone_name,timezone_offset_hours_utc", "access_token": self.token})
        return {"currency": d.get("currency"), "timezone_name": d.get("timezone_name"),
                "timezone_offset_hours_utc": d.get("timezone_offset_hours_utc")}

    def insights(self, date_preset):
        """All ad x day rows for a date preset (last_30d, today, yesterday)."""
        url = f"https://graph.facebook.com/{self.version}/{self.account}/insights"
        params = {"level": "ad", "time_increment": 1, "date_preset": date_preset, "fields": FIELDS,
                  "limit": 500, "access_token": self.token}
        rows = []
        while url:
            data = self._get(url, params)
            rows += [normalise(x) for x in data.get("data", [])]
            url = (data.get("paging") or {}).get("next")
            params = None  # the next URL carries every parameter
        return rows


def connect():
    token, account = env("META_ACCESS_TOKEN"), env("META_AD_ACCOUNT_ID")
    if not token or not account:
        raise MetaError("missing env: META_ACCESS_TOKEN / META_AD_ACCOUNT_ID")
    return Meta(token, account)
