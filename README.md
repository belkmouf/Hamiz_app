# Hamiz Pulse

A phone-first web app (PWA) with HamizOnline's Odoo sales and Meta Ads spend in one place. It answers two questions every day:

1. Are we moving **200 to 250 orders placed per day**?
2. Is ad spend per order placed at or under **5% of order value**?

This is the standalone build of `docs/PRD.md`. The claude.ai reference app, sync script and calculator are kept in `reference/`. The math matches them, and the tests check that.

```
Odoo 18 --XML-RPC, read-only--> pulse.sync (hourly cron) --> Postgres/SQLite --> FastAPI --> PWA
Meta Insights API --ads_read----^
```

## Layout

| Path | What it is |
|---|---|
| `pulse/stages.py` | Order stage rules (PRD §4) and the UTC → Algiers conversion |
| `pulse/aggregate.py` | The four report documents, ported line for line from `reference/odoo_sync.py`, plus per-order attribution rows |
| `pulse/odoo.py` | Read-only XML-RPC client: label-based field mapping, batches of 1,000, 0.3 s pauses, 60 s timeout, 4 tries with backoff. It refuses any non-read method |
| `pulse/meta_ads.py` | Insights at ad level, one row per ad per day. Follows paging and backs off on rate-limit headers and errors |
| `pulse/adjoin.py` | Joins Meta spend to Odoo orders on `utm_content == ad name`, falls back to the campaign name, and puts orders with no UTM in UNATTRIBUTED |
| `pulse/calc.py`, `web/calc.js` | CAC budget and Ad review rules (Python and browser copies, tested against each other and against `reference/dz_cod_calc.py`) |
| `pulse/sync.py` | The hourly job: single-run lock, `sync_runs` log, keeps the last good data when a run fails |
| `pulse/api.py` | Magic-link login, `/api/reports`, `/api/ads`, `/api/status`, and the static PWA |
| `web/` | The app (9 tabs), login page, manifest, service worker, icons |

## Run locally

```bash
pip install -r requirements-dev.txt
export APP_SECRET_KEY=dev APP_ALLOWED_EMAILS=you@example.com
uvicorn pulse.api:app --reload        # loads the example data into an empty store
# open http://localhost:8000, enter your email; with no SMTP_HOST the sign-in link prints in this terminal
```

To pull real data, set the Odoo and Meta variables from `.env.example`, then run:

```bash
python -m pulse.sync            # Odoo + Meta (each one is skipped with a note if its env is missing)
python -m pulse.sync --odoo     # Odoo only; prints the field mapping (also stored in meta.fields)
python -m pulse.sync --seed --force   # put the example data back
```

## Deploy (Render)

`render.yaml` creates a web service, an hourly cron at :07, and Postgres. Fill in the secrets marked `sync: false` in the dashboard: Odoo user and API key, Meta system-user token and ad account, allowed emails, base URL and SMTP. Without SMTP, sign-in links appear in the web service log. Railway or any server works the same way: run `uvicorn pulse.api:app` behind HTTPS, and add a crontab entry for `python -m pulse.sync`.

Accounts to create:
- **Odoo:** a dedicated user with read access to Sales only, plus an API key.
- **Meta:** a Business Manager system user with `ads_read` on the ad account. If an agency or reseller runs the account, they must grant the business access.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/reports` | `summary`, `sellers`, `products`, `orders` documents + `sync` status. About 115 KB raw and 15 KB gzipped at 20,000 orders |
| `GET /api/ads?window=today\|yesterday\|last7` | Spend per ad, order groups per ad, days each ad has run, and the count of orders left out because they came from other channels |
| `GET /api/status` | Sync state: `live`, `example`, `stale` (>150 min), `failed`, `empty`. The app polls this every 5 minutes |

All three need a session. Sessions last 30 days, and removing an email from `APP_ALLOWED_EMAILS` signs that person out on their next request.

## Tests

```bash
pytest                      # 80 tests; the layout test needs Playwright + Chromium and is skipped otherwise
```

These cover the PRD §14 acceptance tests:
- **Aggregation parity:** the documents are byte-identical to `reference/odoo_sync.py` on its `--selftest` input, for both seller bases.
- **Calculator parity:** $0.90 / $1.29 / $1.71 per placed / confirmed / delivered order, and $180 / $225 a day, the same as `dz_cod_calc.py cac`.
- **Ad review parity:** decisions, CAC % and blended CAC match `dz_cod_calc.py review` on the example CSVs for all three bases, in Python and in the browser code.
- **Stage table:** every row, including `refused` → returned and plain `state=cancel` → cancelled.
- **Time zone:** 2026-10-03 23:30 UTC lands on 2026-10-04 at hour 0.
- **Size:** 20,000 orders in 90 days keep every document under 250 KiB.
- **Layout:** no horizontal scroll at 375 px on all 9 tabs, light and dark (Playwright).

Also covered: login (single-use and expiring links, no hint about which emails are allowed), failed sync keeping the last good data, the sync lock, Odoo batching and backoff, Meta paging and rate-limit retry, and the join rules.

## Where this build differs from the reference (on purpose)

- **Accents are folded before stage matching.** The reference left "Expédiée" as *pending* because it did not contain `expedi`. Now it is *confirmed*. Unaccented statuses behave exactly as before.
- **Live Ad review enforces the 3-day rule.** It uses each ad's first day of spend in Meta. A CAC kill or no-order kill before 3 full days shows as "Wait: under 3 full days (would kill: …)". Junk-order kills (10+ resolved orders, under 50% confirmed) still show right away. Upload mode keeps the on-screen note instead.
- **Orders from other channels are left out of live Ad review.** These are orders whose UTM source is not Meta (Google, SMS, …). Orders with no UTM at all are UNATTRIBUTED, as the PRD says.
- **Per-ad scoring needs a `utm_content` field on Odoo orders.** The sync looks for a field labeled "UTM Content" or "Ad name". Until one exists, live Ad review can only match by campaign. See PRD §12, question 1.

## Open items (PRD §12)

1. Check that Magento passes `utm_source`, `utm_campaign` and `utm_content` to Odoo.
2. Run `python -m pulse.sync --odoo` once and check the printed field mapping. If a label differs, override it with `PULSE_ORDER_LABELS` / `PULSE_LINE_LABELS`.
3. Check the real Magento status list against the stage rules.
4. Collect the Meta ad account ID and agency details (these affect token access and the FX value set in the app).
5. Pick hosting and the email allowlist.
