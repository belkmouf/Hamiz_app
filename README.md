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
| `pulse/api.py` | Password login, magic links, staff admin, `/api/reports`, `/api/ads`, `/api/status`, and the static PWA |
| `pulse/metrics.py` | 200–250 orders/day and the 5% ad-spend check (merchandise DZD, Algiers days) |
| `pulse/reconcile.py` | One-day comparison of stored figures with a live Odoo and Meta query |
| `web/` | The app (9 tabs, French / Arabic / English), login page, manifest, service worker, icons |

## Run locally

```bash
pip install -r requirements-dev.txt
export APP_SECRET_KEY=dev APP_ADMIN_EMAIL=you@example.com APP_ADMIN_PASSWORD=dev-password
uvicorn pulse.api:app --reload        # loads the example data into an empty store
# open http://localhost:8000 and sign in with that email and password
```

The phone UI starts in French. FR / ع / EN in the header switches language and remembers the choice on the device. Arabic lays the page out right to left.

Employees sign in with the password an admin set. Magic-link email still works when `SMTP_HOST` is set. Without it, a requested link is only printed in the server log, which is for local development. See `DEPLOY.md` for Render, the first admin, and how to add staff.

To pull real data, set the Odoo and Meta variables from `.env.example`, then run:

```bash
python -m pulse.sync            # Odoo + Meta (each one is skipped with a note if its env is missing)
python -m pulse.sync --odoo     # Odoo only; prints the field mapping (also stored in meta.fields)
python -m pulse.sync --seed --force   # put the example data back
```

## Deploy (Render)

`render.yaml` creates a web service (starter, so it does not sleep), an hourly cron at :07 UTC, and Postgres. Every secret, the first admin, employee passwords, and the live reconciliation command are in `DEPLOY.md`. Railway or any server works the same way: run `uvicorn pulse.api:app` behind HTTPS, and add a crontab entry for `python -m pulse.sync`.

Accounts to create:
- **Odoo:** a dedicated user with read access to Sales only, plus an API key.
- **Meta:** a Business Manager system user with `ads_read` on the ad account. If an agency or reseller runs the account, they must grant the business access.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/reports` | `summary`, `sellers`, `products`, `orders`, `sync` (including `last_synced_at`), and `pulse` (the 200–250 goal and today's 5% check). About 115 KB raw and 15 KB gzipped at 20,000 orders |
| `GET /api/ads?window=today\|yesterday\|last7` | Spend per ad, order groups per ad, days each ad has run, and the count of orders left out because they came from other channels |
| `GET /api/status` | Sync state: `live`, `example`, `stale` (>150 min), `failed`, `empty`. The app polls this every 5 minutes and on pull-to-refresh |
| `GET /api/me` | The signed-in email, name, and role |
| `GET/POST/DELETE /api/staff` | Admin only. Add, update, or deactivate employees |
| `POST /auth/login` | Email and password. Unknown emails and wrong passwords get the same error |
| `GET /api/admin/reconcile?date=` | Admin only. One Algiers day against live Odoo and Meta |

Sessions last 30 days. The role is read on every request, so deactivating someone or removing them from `APP_ALLOWED_EMAILS` signs them out on the next call. API responses send `Cache-Control: no-store`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
pytest                      # layout and phone tests need Playwright + Chromium and are skipped otherwise
```

These cover the PRD §14 acceptance tests:
- **Aggregation parity:** the documents are byte-identical to `reference/odoo_sync.py` on its `--selftest` input, for both seller bases.
- **Calculator parity:** $0.90 / $1.29 / $1.71 per placed / confirmed / delivered order, and $180 / $225 a day, the same as `dz_cod_calc.py cac`.
- **Ad review parity:** decisions, CAC % and blended CAC match `dz_cod_calc.py review` on the example CSVs for all three bases, in Python and in the browser code.
- **Stage table:** every row, including `refused` → returned and plain `state=cancel` → cancelled.
- **Time zone:** 2026-10-03 23:30 UTC lands on 2026-10-04 at hour 0.
- **Size:** 20,000 orders in 90 days keep every document under 250 KiB.
- **Layout:** no horizontal scroll at 375×812 on all 9 tabs, light and dark (Playwright).
- **Daily questions:** merchandise value excludes delivery fees, the goal is the closed band 200–250 on the last 7 complete Algiers days, and ad spend / that value is at or under 5%.
- **Languages:** every UI key exists in English, French, and Arabic. Arabic renders `dir=rtl` at phone width.

Also covered: password login and staff admin (single-use expiring magic links still, with no hint about which emails are allowed), failed sync keeping the last good data, the sync lock, Odoo batching and backoff, Meta paging and rate-limit retry, overlapping Meta day rows, uncached API responses, concurrent sessions, and the join rules.

`python -m pulse.reconcile --mock` checks the comparison on fake Odoo and Meta. The live check, with real credentials, is in `DEPLOY.md`.

Example files in `pulse/seed/` and `reference/seed_example/` include shop names that look like real sellers, and this repo names `erp.hamizonline.com`. They are example records in a public repo. See `DEPLOY.md`.

## Where this build differs from the reference (on purpose)

- **Accents are folded before stage matching.** The reference left "Expédiée" as *pending* because it did not contain `expedi`. Now it is *confirmed*. Unaccented statuses behave exactly as before.
- **Live Ad review enforces the 3-day rule.** It uses each ad's first day of spend in Meta. A CAC kill or no-order kill before 3 full days shows as "Wait: under 3 full days (would kill: …)". Junk-order kills (10+ resolved orders, under 50% confirmed) still show right away. Upload mode keeps the on-screen note instead.
- **Orders from other channels are left out of live Ad review.** These are orders whose UTM source is not Meta (Google, SMS, …). Orders with no UTM at all are UNATTRIBUTED, as the PRD says.
- **Per-ad scoring needs a `utm_content` field on Odoo orders.** The sync looks for a field labeled "UTM Content" or "Ad name". Until one exists, live Ad review can only match by campaign. See PRD §12, question 1.

## Data checks with real systems

These guard against cases where the math is right but the inputs mislead. The sync logs each one, and the app's **"Odoo field mapping and data checks"** panel (bottom of every tab) opens by itself when something needs attention.

- **Order date.** When a quotation is confirmed, Odoo resets `date_order` to the confirmation time. The sync counts orders whose `date_order` is more than 1 h after `create_date` and warns when that's over 5%. If it is, set `PULSE_ORDER_DATE_FIELD=create_date` (or a custom Magento date field) so days and hours show when the customer actually ordered.
- **Status field.** Odoo's built-in `state` field is also labelled "Status", so it's excluded from label matching. If no custom status field is found, stages come from `state` alone, and the panel lists the status field as not found.
- **Order lines.** Section and note lines, and delivery-fee lines (`is_delivery`), are left out of Products and Sellers. The panel shows how many were skipped. GMV still uses the order total.
- **Meta account.** Each sync records the ad account's currency and time zone. A DZD account is converted to USD with your FX setting. Any other currency, or a time zone other than UTC+1, shows a warning on Ad review.
- **Ad names.** The join to Odoo orders ignores case and extra spaces, and also accepts a `utm_content` that Magento saved still URL-encoded.
- **Daily goal.** The goal gauge and the "orders/day right now" line use complete days only, so today's partial day doesn't drag the number down. The 7-day and 30-day KPI tiles follow the PRD windows, which include today.

## Open items (PRD §12)

1. Check that Magento passes `utm_source`, `utm_campaign` and `utm_content` to Odoo.
2. Run `python -m pulse.sync --odoo` once and check the printed field mapping. If a label differs, override it with `PULSE_ORDER_LABELS` / `PULSE_LINE_LABELS`.
3. Check the real Magento status list against the stage rules.
4. Collect the Meta ad account ID and agency details (these affect token access and the FX value set in the app).
5. Pick hosting and the email allowlist.
