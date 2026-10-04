# Hamiz Pulse: Product Requirements Document

Version 1.0 · 4 October 2026 · Owner: Belkacem Mouffok (HamizOnline)

## 1. Summary

Hamiz Pulse is a phone-first web app that puts HamizOnline's sales and Meta Ads performance in one place. It pulls orders from Odoo and ad spend from Meta Ads every hour. It answers two questions a day:

1. Are we moving **200 to 250 orders placed per day**?
2. Is ad spend per order placed at or under **5% of the order value** (CAC cap)?

A reference implementation exists in `reference/` (a single-page app, an Odoo sync script, and a CLI calculator). Rebuild it as a standalone, deployable product that does not depend on claude.ai. Keep the behavior and the math identical unless this document says otherwise.

## 2. Goals and non-goals

**Goals**
- Live sales KPIs from Odoo on a phone, refreshed hourly, readable in under 10 seconds.
- Live Meta Ads spend per ad, joined to Odoo orders, scored against the 5% CAC cap.
- CAC budget and scaling plan calculators that use real Odoo rates (AOV, confirmation, delivery) by default.
- Read-only access to Odoo and Meta. The app never writes to either system.

**Non-goals (v1)**
- Editing orders, campaigns or budgets from the app.
- Multi-tenant or seller-facing views.
- Push notifications (planned for v2, see section 13).

## 3. Users

| User | Needs |
|---|---|
| Founder / CEO (primary) | Daily pulse on phone: orders/day vs goal, GMV, cancellations, CAC vs cap |
| Media buyer | Which ads to promote, kill or wait on; budget step decisions |
| Ops lead | Confirmation and delivery rates, peak hours for call-center shifts, stock and capacity checks |

All users are internal. Access must require login.

## 4. Key definitions (single source of truth)

All money in DZD (DA) unless marked USD. Time zone: Africa/Algiers (UTC+1, no DST). Odoo stores `date_order` in UTC; convert before bucketing by day or hour.

**Order stages.** Every order maps to exactly one stage using Odoo `state` plus the Magento/custom status text (case-insensitive substring match):

| Stage | Rule, checked in this order |
|---|---|
| cancelled | `state == "cancel"` or status contains cancel / annul / refus / fraud. If the status also contains return / retour / refus, the order is **returned** instead |
| returned | status contains return / retour / rto |
| delivered | status contains deliver / livr / complete / closed |
| confirmed | `state in (sale, done)` or status contains process / confirm / ship / expedi |
| pending | anything else |

Confirmed-or-later = confirmed + delivered + returned.

**Metrics** (for any date window):
- Orders = count of orders placed in the window.
- GMV = sum of `amount_total`.
- AOV = GMV / Orders.
- Net GMV = GMV excluding cancelled orders.
- Cancel rate = cancelled / Orders. Cancel rate by value = cancelled GMV / GMV.
- Confirmation rate = confirmed-or-later / (Orders - pending).
- Delivery rate = delivered / (delivered + returned).
- Orders per day = Orders / days in window.

**CAC** (configurable, defaults shown):
- CAC basis: `placed` (default), `confirmed` or `delivered`.
- CAC cap: 5% of order value per order on the chosen basis.
- CAC % for an ad = (ad spend in DA / orders on the basis) / that ad's own AOV.
- Ad spend in DA = spend in USD × FX, where FX is the DA the business actually pays per 1 USD of ad spend (user-set, default 250). Not the official rate.
- Always show the real cost per delivered order next to any placed-basis CAC, as information only.

**Funnel conversion between bases** (c = confirmation rate, d = delivery rate):
- per-confirmed cost = per-placed cost / c = per-delivered cost × d
- delivered orders from N placed = N × c × d

## 5. Architecture

```
Odoo 18 (erp.hamizonline.com) --XML-RPC, read-only--> sync job (hourly) --> data store --> API --> phone web app (PWA)
Meta Marketing API (Insights) --system user token-----^
```

**Recommended stack** (keep it simple; change only with a reason):
- **Sync job:** Python 3.11+, run hourly by cron (Render cron job, GitHub Actions schedule, or a server crontab). Start from `reference/odoo_sync.py`.
- **Data store:** Postgres (or SQLite for a single small server). Store the four report documents (section 6) as JSONB rows keyed by name, plus a `meta_spend` table.
- **API:** FastAPI with 3 read endpoints and login. Serves the built frontend as static files.
- **Frontend:** single-page PWA (vanilla JS or a light framework such as Preact). Installable with "Add to Home Screen". Start from `reference/index.html`.
- **Auth:** email magic link or Google sign-in limited to an allowlist of addresses. No public access.

**Secrets** (environment variables only, never in code or the frontend):
`ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_KEY` (API key of a dedicated read-only Odoo user), `META_ACCESS_TOKEN` (system user token with `ads_read`), `META_AD_ACCOUNT_ID`, `APP_ALLOWED_EMAILS`.

## 6. Data model

The sync job produces four documents. Each must serialize under 250 KiB; trim the longest list when needed and set `meta.trimmed = true`. Exact shapes are in `reference/seed_example/*.json`.

**Common `meta`**: `generated_at` (ISO, Algiers time), `timezone`, `orders_scanned`, `lines_scanned`, `seller_basis`, `fields` (the Odoo field mapping used), `example` (bool), `trimmed` (bool, optional).

**summary**
- `kpis`: windows `today`, `yesterday`, `last7`, `prev7`, `last30`, `prev30`. Each has `orders, gmv, aov, net_gmv, cancel_rate, cancel_rate_value, stages{pending,confirmed,delivered,returned,cancelled}, confirm_rate, delivery_rate, orders_per_day`.
- `daily`: 90 rows `{date, o (orders), g (GMV), c (cancelled orders), cg (cancelled GMV), d (delivered)}`.
- `stores`, `salespeople`, `utm`, `wilayas`: last 30 days, rows `{name, orders, gmv, cancelled, delivered, confirmed}` sorted by GMV. `utm` name = "source / campaign".
- `hours`: 24 counts (last 30 days). `weekday_hours`: 7 × 24 counts, Monday first.

**sellers**: `rows[] {name, orders, gmv, items, cancelled, delivered}`, last 30 days. Use order-line seller when lines carry one; otherwise split each order's total evenly across its sellers. Record which in `meta.seller_basis`.

**products**: `rows[] {name, qty, revenue, orders, cancelled, category}`, last 30 days, from order lines.

**orders**: latest 400 orders, `rows[] {ref, mg (Magento ID), dt ("YYYY-MM-DD HH:MM" local), cu (customer), t (total), st (stage), raw (original status text), so (store), se (sellers, max 80 chars)}`.

**meta_spend** (new in this build): one row per ad per day `{date, campaign_id, campaign_name, adset_name, ad_id, ad_name, spend_usd, impressions, clicks, meta_purchases}`, last 30 days.

## 7. Odoo integration

- Protocol: XML-RPC (`/xmlrpc/2/common` authenticate, `/xmlrpc/2/object` execute_kw). Server is Odoo 18.
- Models: `sale.order` (last 90 days by `date_order`) and `sale.order.line` (orders from the last 30 days).
- Standard fields: `name, date_order, amount_total, state, invoice_status, partner_id, user_id, campaign_id, source_id, medium_id`.
- Custom fields are found by **field label** through `fields_get`, preferring `x_` fields. Known export labels: Magento Order ID, Sellers, Store based ID, Order status. Lines: Seller, Order status, Product category. Make the label lists configurable.
- many2many sellers: resolve names with one batched `read(display_name)`.
- Batches of 1,000 records, 0.3 s pause between batches, 60 s socket timeout, retry with exponential backoff (4 tries).
- Single-run lock so overlapping cron runs cannot stack.
- Print the field mapping on every run and store it in `meta.fields` so mapping errors are visible in the app.

## 8. Meta Ads integration

- Endpoint: `GET /v{latest}/act_{AD_ACCOUNT_ID}/insights` with `level=ad`, `time_increment=1`, `date_preset=last_30d` (and `today` for the intraday refresh), fields `campaign_id, campaign_name, adset_name, ad_id, ad_name, spend, impressions, clicks, actions`.
- Auth: system user token with `ads_read`, stored server side. If the account is run by an agency or reseller, they must grant the business access to the ad account.
- `meta_purchases` = the `purchase` (or `offsite_conversion.fb_pixel_purchase`) value from `actions`. Display only; never use it for decisions.
- Rate limits: one call per hour per window is enough; respect `x-business-use-case-usage` headers and back off.

**Joining Meta to Odoo (critical).** Every order must carry the ad it came from:
- Ad URLs use `utm_source=fb&utm_campaign={{campaign.name}}&utm_content={{ad.name}}`.
- Magento must save the UTMs and pass them to Odoo (`source_id`, `campaign_id`, and a field for `utm_content`).
- Join on `utm_content == ad_name`. Fallback: join on campaign name and show "matched by campaign" on those rows.
- Orders with no UTM appear as **UNATTRIBUTED** with the action "Fix tracking".

Open question: confirm whether Magento orders reach Odoo with UTMs today (section 12).

## 9. App screens

Phone-first, single column, max width 760 px. Sticky header: app name, sync status chip, and a **Sales | Ads** switch. Below the header, a scrollable row of tab chips. Remember the last section, tab and period on the device.

**Sync status chip**: green "Odoo · 12 min ago"; amber "Example data"; red when the last sync is over 150 minutes old or the data cannot load. If data is example data, show a banner saying so on every tab.

### Sales section

1. **Overview**
   - Period chips: Today, Yesterday, 7 days, 30 days.
   - Six KPI tiles: Orders, GMV, AOV, Cancel rate, Net GMV, Orders per day. Each shows % change vs the comparable prior period (today vs yesterday, 7 vs prior 7, 30 vs prior 30); for cancel rate a decrease is green.
   - Daily orders goal: last-7-day orders/day against the 200 to 250 band, with a pill "On target" or "N short".
   - Order status: stacked bar of the five stages with counts, plus confirmation rate, delivery rate and lost value (cancelled GMV %).
   - Orders by hour (last 30 days, Algiers time) bar chart, peak hour highlighted.
2. **Trend**: daily bars for 7 / 30 / 90 days, toggle Orders or GMV, cancelled overlaid in red, dashed goal line at 200/day on the orders view. Totals: total, daily average, cancelled %. Weekday × hour heatmap.
3. **Sellers**: search, sort by GMV / Orders / Cancel %. Each row: name, GMV, orders, share of total, cancel % pill (green ≤15%, amber ≤30%, red above), share bar. Paginate 25 at a time. Footnote with `seller_basis`.
4. **Products**: same pattern, sort by Revenue / Units / Cancel %.
5. **Channels**: ranked blocks for Stores, Ad source / campaign (UTM), Wilayas (if the field exists), Salespeople. Each row shows GMV, orders, share, delivered %, cancel % pill.
6. **Orders**: search across order ref, Magento ID, customer, seller, store. Stage filter chips. Each row: ref + Magento ID, total, date, customer, sellers, stage pill (raw status as tooltip). Paginate 40 at a time.

### Ads section

7. **CAC budget**
   - Inputs: AOV, FX (DA per $1), confirmation %, delivery %, CAC cap %, CAC basis, goal low and high (orders placed/day). AOV and the two rates default to Odoo last-30-day values, labeled "from Odoo"; any edit overrides and a button restores Odoo values.
   - Outputs: max ad cost per placed, confirmed and delivered order (USD and DA); daily ad budget at the low and high goal with the implied confirmed and delivered counts; the real cost per delivered order as % of AOV; current orders/day.
   - Landing conversion grid: for CPM values × link CTR values (both editable lists), the landing conversion rate needed to keep Meta CPA at or under the cap. Formula: needed = (CPM / (1000 × CTR)) / max cost per placed order in USD. Green ≤5%, amber ≤10%, red above, "impossible" when over 100%.
8. **Scaling plan**
   - Inputs: creatives to test, test budget $/day, min spend per ad set, scaling start $/day, budget step %, confirmation calls/day, units in stock, days until COD cash returns.
   - Target cost per confirmed order = CAC cap × AOV × (1/c for placed basis, 1 for confirmed, d for delivered) / FX.
   - Testing check: creatives × min spend ≤ test budget, else recommend raising the budget or testing in waves of floor(budget / min spend).
   - Decision rules: promote at or under target with 3+ confirmed after 3 full days; kill above 1.5× target, or at 2.5× target spent with no confirmed order, or confirmation under (c - 20 points) with 10+ resolved orders.
   - Capacity at the high goal: ad spend needed, calls needed vs available, days of stock, cash float = spend × days until COD cash.
   - Schedule table with a 48 h / 24 h toggle: start budget, multiply by (1 + step) per step, stop at min(ad spend needed, call-capacity ceiling) minus test budget. Columns: day, budget, placed, confirmed, delivered. Footnote that cost per order usually rises with spend and the cap wins.
9. **Ad review**
   - **Live mode (new):** reads `meta_spend` for the selected day (Today / Yesterday / Last 7 days) and joins Odoo orders by `utm_content`.
   - **Upload mode (kept as fallback):** Meta CSV (ad name + amount spent; accept Ads Manager column names) and optional orders CSV (ad_name, status, value).
   - Per ad: spend, placed, confirmed (and %), AOV, CAC %. Decision pill, evaluated in this order:
     1. UNATTRIBUTED → "Fix tracking".
     2. Over 50% of orders pending → "Wait: most orders still pending".
     3. 10+ resolved orders and confirmation under 50% → "Kill: junk orders".
     4. 3+ orders on the basis, 2+ confirmed, CAC % ≤ cap → "Promote".
     5. 3+ orders, CAC % > 1.5 × cap and spend ≥ 2.5 × allowed cost per placed order → "Kill: CAC X%".
     6. No orders and spend ≥ 2.5 × allowed cost per placed order → "Kill: no orders".
     7. Otherwise → "Wait: not enough data".
   - Sort by CAC % ascending. Account card: total spend (USD and DA), orders, confirmed, blended CAC % with OK / OVER CAP, projected cost per delivered order %.
   - Note on screen: do not kill before 3 full days unless clearly broken. In live mode, use ad start dates from Meta to enforce this instead of a note.

## 10. Design

- Follow the Hamiz design system: orange accent `#f26522` (dark mode `#ff7a3d`), Inter for UI, JetBrains Mono for order IDs, warm neutrals.
- Light and dark themes following the phone setting.
- Semantic colors: good green, warning amber, bad red, info blue, idle grey. Stage colors: pending grey, confirmed blue, delivered green, returned amber, cancelled red.
- Tabular numbers everywhere digits line up. Money formatting: "12.5M DA", "48k DA", "4,500 DA"; USD with 2 decimals for unit costs and 0 for daily budgets.
- Minimum tap target 40 px; no horizontal page scroll at 375 px width; tables scroll inside their own container.
- Planned v1.1: language switch EN / FR / AR with full RTL for Arabic (labels only; field names and numbers unchanged).

## 11. Non-functional requirements

- **Freshness:** sync hourly; Meta "today" refresh every hour; show data age on every screen.
- **Performance:** first screen interactive under 2 s on 4G; API payload under 400 KB total.
- **Security:** read-only Odoo user and API key; Meta token with `ads_read` only; secrets server side; login required; HTTPS only; no customer phone numbers stored or shown.
- **Reliability:** a failed sync keeps the last good data and records the error in a `sync_runs` table `{started_at, finished_at, ok, error, orders_scanned}`; the app shows "Last sync failed" when the latest run failed.
- **Load on Odoo:** batch size and pauses as in section 7; never more than one sync at a time.

## 12. Open questions

1. Do Magento orders arrive in Odoo with UTM source, campaign and content? If not, add them in the Magento to Odoo connector before Ad review can score individual ads.
2. Confirm the exact Odoo field names for Magento status, sellers, store and wilaya. Run the sync once and check `meta.fields`.
3. Which Magento statuses mean delivered, returned and refused? Confirm the stage rules in section 4 against the real list.
4. Meta: ad account ID, and whether ads run through an agency or reseller account (affects token access and the FX value).
5. Hosting choice (Render, Railway, or an existing server) and the allowlist of user emails.

## 13. Milestones

| # | Scope | Done when |
|---|---|---|
| M1 | Sync job + data store + API, Odoo only | 4 documents refresh hourly from real Odoo data; field mapping verified |
| M2 | PWA: all Sales tabs + CAC budget + Scaling plan | Matches the reference app on the same data; installable on iPhone and Android |
| M3 | Meta integration + live Ad review | Spend per ad joined to Odoo orders; decisions match the rules in section 9 |
| M4 | Hardening | Login, sync failure states, data-age warnings, tests below passing |
| v2 | Push alert when orders/day drops below 200 or blended CAC exceeds the cap two days running; EN/FR/AR | |

## 14. Acceptance tests

- Aggregation: run `python3 reference/odoo_sync.py --selftest`; the rebuilt aggregation must give the same KPI values on the same synthetic input.
- Calculator parity: for AOV 4,500, c 0.70, d 0.75, FX 250, cap 5% per placed order, the app shows max cost $0.90 per placed, $1.29 per confirmed, $1.71 per delivered; daily budget $180 at 200 placed and $225 at 250 placed. Same values as `python3 reference/dz_cod_calc.py cac --aov 4500 --confirm-rate 0.7 --delivery-rate 0.75 --fx 250`.
- Ad review: with `reference/examples/ads.csv` and `reference/examples/orders.csv`, decisions match `python3 reference/dz_cod_calc.py review --ads ... --orders ... --aov 4500 --confirm-rate 0.7 --delivery-rate 0.75 --fx 250`.
- Stage mapping: unit tests for each row of the stage table, including "refused" → returned and plain `state=cancel` → cancelled.
- Time zone: an order at 2026-10-03 23:30 UTC lands on 2026-10-04, hour 0, in Algiers time.
- Size: every stored document stays under 250 KiB with 20,000 orders in 90 days.
- Layout: no horizontal scroll at 375 px in light and dark mode on every tab.

## 15. Reference files

| File | What it is |
|---|---|
| `reference/index.html` | Working single-page app (all 9 tabs). Reads the 4 documents; replace its data loading with calls to the new API |
| `reference/odoo_sync.py` | Odoo XML-RPC pull, stage classification, aggregation, size trimming, `--selftest` |
| `reference/dz_cod_calc.py` | CLI for the CAC budget, scaling plan and ad review math |
| `reference/seed_example/*.json` | Example documents in the exact stored shape (made-up data) |
| `reference/examples/*.csv` | Sample Meta and orders CSVs for the Ad review |
| `reference/dz-meta-ads-strategist.md` | Claude Code agent that applies the same rules for planning and reviews |
