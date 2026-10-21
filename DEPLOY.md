# Deploy Hamiz Pulse on Render

This is the path from an empty Render account to a phone dashboard employees can sign in to. The blueprint is `render.yaml`: a web service, an hourly cron, and Postgres.

Live Odoo and Meta credentials are not in this repository. The reconciliation check below is what compares one full Algiers day of stored figures with a direct query. Run it on Render after the secrets are set. A mock of that check (`python -m pulse.reconcile --mock`) runs in CI and locally without credentials.

## 1. Create the services

1. Push this branch and open the pull request, or deploy `main` once it is merged.
2. In Render: **New → Blueprint**, point it at this repo, and apply `render.yaml`.
3. Render creates:
   - Postgres `hamiz-pulse-db` (basic-256mb)
   - Web service `hamiz-pulse` (Docker, starter plan, health check `GET /healthz`)
   - Cron `hamiz-pulse-sync` (Docker, starter plan, `7 * * * *` UTC, command `python -m pulse.sync`)
4. The starter plan keeps the web service awake. A free instance sleeps and the phone app looks empty.
5. `APP_SECRET_KEY` is generated once in the shared env group. Web and cron must share that value. Do not rotate it unless you intend to sign everyone out.

The cron minute is 7 so it does not land on the top of the hour with other jobs. Africa/Algiers is UTC+1 year round, so the job still runs once per clock hour in Algiers.

## 2. Environment variables

Set every `sync: false` value in the Render dashboard (Blueprint → the env group, or each service). Never commit them.

| Variable | Where | What to put |
|---|---|---|
| `ODOO_URL` | blueprint, already `https://erp.hamizonline.com` | Odoo base URL |
| `ODOO_DB` | secret | Odoo database name |
| `ODOO_USER` | secret | Read-only Sales user |
| `ODOO_KEY` | secret | That user's API key (not their password) |
| `META_ACCESS_TOKEN` | secret | System-user token with `ads_read` only |
| `META_AD_ACCOUNT_ID` | secret | Ad account id, with or without the `act_` prefix |
| `META_API_VERSION` | blueprint, `v24.0` | Graph API version |
| `APP_ALLOWED_EMAILS` | secret | Comma-separated extra emails that may request a magic link. Staff rows override this list |
| `APP_ADMIN_EMAIL` | secret | Email of the first admin |
| `APP_ADMIN_PASSWORD` | secret | At least 8 characters. Used once, to create that admin, then ignored |
| `APP_SECRET_KEY` | generated | Shared session secret |
| `APP_BASE_URL` | secret | Public `https://` origin of the web service, no trailing slash. Magic links are built from it |
| `PULSE_FORCE_HTTPS` | blueprint, `1` | Redirect HTTP to HTTPS. `/healthz` stays on HTTP so Render's health check does not fail |
| `PULSE_FX` | blueprint, `250` | DZD the business pays per 1 USD of Meta spend. Change it if the real rate you pay is different |
| `DATABASE_URL` | from the blueprint database | Postgres URL. The app rewrites `postgres://` to `postgresql+psycopg://` |
| `SMTP_HOST` | secret, optional | Mail host. Leave empty to skip magic links |
| `SMTP_PORT` | blueprint, `587` | SMTP port |
| `SMTP_USER` | secret, optional | SMTP username |
| `SMTP_PASSWORD` | secret, optional | SMTP password |
| `SMTP_FROM` | secret, optional | From address on magic-link mail |
| `PULSE_ORDER_LABELS` | optional JSON | Override an Odoo order field label, e.g. `{"wilaya": ["wilaya livraison"]}` |
| `PULSE_LINE_LABELS` | optional JSON | Override a line field label |
| `PULSE_ORDER_DATE_FIELD` | optional | `date_order` (default) or `create_date` if confirmation rewrites the order time |

Odoo account: a dedicated user with read access to Sales only, plus an API key.

Meta account: a Business Manager system user with `ads_read` on this ad account. If an agency runs the account, they grant the business access. The ad account time zone should be UTC+1 so Meta days match Algiers days. Spend is treated as USD and converted with `PULSE_FX`.

## 3. First admin and employee login

On the first boot of the web service, if `APP_ADMIN_EMAIL` and `APP_ADMIN_PASSWORD` are set and that email has no staff row yet, Pulse creates an admin. The password is never written to the logs. A later boot does not reset it. Changing the env password later does nothing until you remove the staff row.

Employees sign in on the phone:

1. Open the site (`APP_BASE_URL`).
2. Enter the email and the password an admin set.
3. The session cookie lasts 30 days, is HttpOnly, and is tied to that browser. Each person has their own cookie. Removing or deactivating them signs them out on the next request.

An admin, signed in, opens **Team** from the footer and can:

- Add an employee: email, name, password (8+ characters), role `staff` or `admin`.
- Change a password by saving the same email with a new password. A blank password leaves the current one.
- Remove an employee. That deactivates the row. An admin cannot remove their own account or the last active admin.

Magic links stay available for addresses on `APP_ALLOWED_EMAILS` or with an active staff row, and only when `SMTP_HOST` is set. Without SMTP, a requested link is printed in the web service log. That is a local-dev fallback, not the way employees should sign in on Render. Give them a password.

An inactive staff row blocks the allowlist too, so removing someone who is also on `APP_ALLOWED_EMAILS` actually signs them out.

## 4. Confirm the hourly sync

After the secrets are saved, trigger the cron once from the Render dashboard (or wait until minute 7). The web log and the cron log should show an Odoo pull and a Meta pull. On the phone, pull down or tap the refresh button. The header chip leaves "Example data" and shows a **last synced** time in Africa/Algiers.

The dashboard asks `/api/reports` and `/api/status` with `cache: no-store`. Those responses send `Cache-Control: no-store`. The service worker (`pulse-v3`) does not put `/api/` or `/auth/` in the Cache API. A refresh shows the latest stored sync, not a cached copy.

The official order goal is **200–250 orders per day** over the last 7 complete Algiers days (today is excluded so a morning does not look like a miss). The ad-spend check is **today's Meta spend in DZD / today's merchandise order value ≤ 5%**. Merchandise value is product lines, with delivery-fee lines left out. GMV tiles still use the order total, matching the reference reports.

## 5. Live reconciliation

On a Render shell for the web service (the cron service has the same Odoo and Meta env), for one full Algiers day:

```bash
python -m pulse.reconcile --date YYYY-MM-DD
```

Exit 0 means the stored orders, merchandise value, stage counts, Meta spend, and spend ratio match a fresh Odoo and Meta query for that day. Exit 1 prints each discrepancy (stored, live, delta). Exit 2 means a credential or a source was unreachable.

Use a day that has already finished in Algiers (yesterday), so the hourly sync and the live query cover the same calendar day. Meta is queried with `time_range` since/until that day. Odoo is queried for that Algiers day converted to UTC.

Locally, without credentials:

```bash
python -m pulse.reconcile --mock
```

The mock order total is 4,900 DZD including a 400 DZD delivery fee. The report must show merchandise value 4,500. The same formula on both sides would hide a bug that used the delivery-inclusive total, so the mock asserts 4,500 specifically.

An admin can also open `GET /api/admin/reconcile?date=YYYY-MM-DD`. It returns 503 when Odoo or Meta cannot be reached.

This check compares stored rows with a live pull through the same client. The unit tests lock the day boundary, the delivery exclusion, the 200–250 band, and the 5% ratio. The live command is still required once, on real credentials, because this environment does not have them.

## 6. Languages and brand

The phone UI defaults to French. The header switches French, Arabic, and English. The choice is stored on the phone (`hp.lang`). Arabic sets `dir=rtl` and mirrors the header. Amounts use `fr-DZ`, `ar-DZ` with Latin digits, or `en-US`, and DZD.

Colours are Hamiz red `#E30613`, hot pink `#FF0050`, and magenta `#E6007E` on `#14080C`. On-target stays green, short of the goal stays gold, over the spend cap stays orange, and above 250 orders stays blue, so status is not the brand red. Buttons use dark ink on the pink so the text stays WCAG AA.

## 7. Public example data

`pulse/seed/` and `reference/seed_example/` ship with the repo so the empty dashboard has something to show. They contain shop names that look like real Algerian sellers (Mode Tlemcen, Sport Atlas, Beauté Kabyle, Maison Nour, TechDZ, Bébé Plus, Électro Oran, Cuisine Pro) and sample customers. The hostname `erp.hamizonline.com` is in this file, `render.yaml`, `.env.example`, and the README. The repo is public. Treat those as example records, and rotate anything that is a real customer export before leaving it on `main`.

## 8. What you still have to provide

- `ODOO_DB`, `ODOO_USER`, `ODOO_KEY`
- `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`
- `APP_ADMIN_EMAIL`, `APP_ADMIN_PASSWORD`
- `APP_BASE_URL` (the Render URL)
- `APP_ALLOWED_EMAILS` if anyone should use magic links in addition to passwords
- `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` only if you want magic links
- `PULSE_FX` if 250 DZD per USD is not the rate you pay
- One live run of `python -m pulse.reconcile --date YYYY-MM-DD` after the first successful sync, and a look at the Odoo field-mapping log
