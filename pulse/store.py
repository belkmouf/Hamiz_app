"""Data store: Postgres in production, SQLite for a single small server or local dev.

Tables
  reports            the four report documents, JSON(B) keyed by name
  meta_spend         one row per ad per day (last 30 days)
  order_attribution  one row per Odoo order of the last 30 days, with its utm_content (ad name)
  sync_runs          one row per sync attempt
  used_login_tokens  magic-link nonces already spent (single use)
"""
from contextlib import contextmanager
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from .config import DZ, database_url

JSONType = sa.JSON().with_variant(JSONB(), "postgresql")
md = sa.MetaData()

reports = sa.Table(
    "reports", md,
    sa.Column("name", sa.String(32), primary_key=True),
    sa.Column("doc", JSONType, nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)
meta_spend = sa.Table(
    "meta_spend", md,
    sa.Column("date", sa.Date, primary_key=True),
    sa.Column("ad_id", sa.String(40), primary_key=True),
    sa.Column("campaign_id", sa.String(40)),
    sa.Column("campaign_name", sa.Text),
    sa.Column("adset_name", sa.Text),
    sa.Column("ad_name", sa.Text, nullable=False),
    sa.Column("spend_usd", sa.Float, nullable=False, default=0),
    sa.Column("impressions", sa.Integer, default=0),
    sa.Column("clicks", sa.Integer, default=0),
    sa.Column("meta_purchases", sa.Integer, default=0),
)
order_attribution = sa.Table(
    "order_attribution", md,
    sa.Column("ref", sa.String(64), primary_key=True),
    sa.Column("date", sa.Date, nullable=False, index=True),
    sa.Column("ad", sa.Text),
    sa.Column("campaign", sa.Text),
    sa.Column("source", sa.Text),
    sa.Column("stage", sa.String(16), nullable=False),
    sa.Column("total", sa.Float, nullable=False),
)
sync_runs = sa.Table(
    "sync_runs", md,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("kind", sa.String(16), nullable=False, default="odoo"),  # odoo | meta
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("ok", sa.Boolean),
    sa.Column("error", sa.Text),
    sa.Column("orders_scanned", sa.Integer),
)
used_login_tokens = sa.Table(
    "used_login_tokens", md,
    sa.Column("nonce", sa.String(64), primary_key=True),
    sa.Column("used_at", sa.DateTime(timezone=True), nullable=False),
)

_engines = {}


def engine(url=None):
    url = url or database_url()
    if url not in _engines:
        kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        _engines[url] = sa.create_engine(url, future=True, **kw)
        md.create_all(_engines[url])
    return _engines[url]


def now():
    return datetime.now(DZ)


@contextmanager
def tx(url=None):
    with engine(url).begin() as conn:
        yield conn


def _upsert_report(conn, name, doc, at):
    if conn.execute(sa.select(reports.c.name).where(reports.c.name == name)).first():
        conn.execute(reports.update().where(reports.c.name == name).values(doc=doc, updated_at=at))
    else:
        conn.execute(reports.insert().values(name=name, doc=doc, updated_at=at))


def save_reports(docs, attribution_rows=None, url=None):
    """Replace the four documents (and the attribution rows) in one transaction."""
    at = now()
    with tx(url) as conn:
        for name, doc in docs.items():
            _upsert_report(conn, name, doc, at)
        if attribution_rows is not None:
            conn.execute(order_attribution.delete())
            if attribution_rows:
                conn.execute(order_attribution.insert(), [
                    {**r, "date": datetime.strptime(r["date"], "%Y-%m-%d").date()} for r in attribution_rows])


def load_reports(url=None):
    with tx(url) as conn:
        return {r.name: r.doc for r in conn.execute(sa.select(reports.c.name, reports.c.doc))}


def save_meta_spend(rows, url=None):
    """Upsert by (date, ad_id): delete the dates we received, then insert."""
    if not rows:
        return
    dates = sorted({r["date"] for r in rows})
    with tx(url) as conn:
        conn.execute(meta_spend.delete().where(meta_spend.c.date.in_(dates)))
        conn.execute(meta_spend.insert(), rows)


def prune_meta_spend(before, url=None):
    with tx(url) as conn:
        conn.execute(meta_spend.delete().where(meta_spend.c.date < before))


def spend_between(start, end, url=None):
    with tx(url) as conn:
        q = sa.select(meta_spend).where(meta_spend.c.date >= start, meta_spend.c.date <= end)
        return [dict(r._mapping) for r in conn.execute(q)]


def first_spend_dates(url=None):
    """Earliest date each ad spent money in the stored window, used as the ad's start date."""
    with tx(url) as conn:
        q = (sa.select(meta_spend.c.ad_name, sa.func.min(meta_spend.c.date))
             .where(meta_spend.c.spend_usd > 0).group_by(meta_spend.c.ad_name))
        return {name: d for name, d in conn.execute(q)}


def attribution_between(start, end, url=None):
    with tx(url) as conn:
        q = sa.select(order_attribution).where(order_attribution.c.date >= start, order_attribution.c.date <= end)
        return [dict(r._mapping) for r in conn.execute(q)]


def start_run(kind, url=None):
    with tx(url) as conn:
        return conn.execute(sync_runs.insert().values(kind=kind, started_at=now())).inserted_primary_key[0]


def finish_run(run_id, ok, error=None, orders_scanned=None, url=None):
    with tx(url) as conn:
        conn.execute(sync_runs.update().where(sync_runs.c.id == run_id).values(
            finished_at=now(), ok=ok, error=(error or None) and str(error)[:2000], orders_scanned=orders_scanned))


def last_runs(url=None):
    """Latest finished run and latest successful run, per kind."""
    out = {}
    with tx(url) as conn:
        for kind in ("odoo", "meta"):
            base = sa.select(sync_runs).where(sync_runs.c.kind == kind, sync_runs.c.finished_at.is_not(None))
            last = conn.execute(base.order_by(sync_runs.c.id.desc()).limit(1)).first()
            good = conn.execute(base.where(sync_runs.c.ok.is_(True)).order_by(sync_runs.c.id.desc()).limit(1)).first()
            out[kind] = {
                "last": _run(last), "last_ok": _run(good),
            }
    return out


def _run(r):
    if not r:
        return None
    m = r._mapping
    return {"started_at": _iso(m["started_at"]), "finished_at": _iso(m["finished_at"]), "ok": m["ok"],
            "error": m["error"], "orders_scanned": m["orders_scanned"]}


def _iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite drops the offset; we always write Algiers time
        dt = dt.replace(tzinfo=DZ)
    return dt.astimezone(DZ).isoformat(timespec="minutes")


def spend_token(nonce, url=None):
    """Mark a magic-link nonce as used. Returns False when it was already used."""
    with tx(url) as conn:
        if conn.execute(sa.select(used_login_tokens.c.nonce).where(used_login_tokens.c.nonce == nonce)).first():
            return False
        conn.execute(used_login_tokens.insert().values(nonce=nonce, used_at=now()))
        return True
