# coupon-dispatch

FastAPI service that processes Agromin program orders after CIMcloud
checkout. Receives orders via Power Automate, routes by shipping method,
sends customer + coordinator emails, persists to Firestore, and produces
PDF delivery manifests.

## Architecture

This is a separate Cloud Run service from `coupon-validator`. The two
services are deployed and versioned independently so dispatch changes
cannot affect the live coupon validation flow.

```
shop.agromin.com checkout
        ↓
coupon-validator  (validates coupon at checkout — STABLE)
        ↓
CIMcloud sends "Pending Approval" email to sales@agromin.com
        ↓
Power Automate parses email → POST /api/ingest-order
        ↓
coupon-dispatch  (this service — FREQUENTLY UPDATED)
  - Routes pickup vs delivery, self-load vs staff-load
  - Sends customer email from dispatch@agromin.com
  - Alerts coordinator (Greg/Brian/Kendall, Chris, or Rosa)
  - Writes to Firestore order_events collection
```

## Endpoints

- `POST /api/ingest-order` — primary entry, called by Power Automate
- `POST /api/generate-manifest` — returns delivery PDF
- `GET  /api/delivery-schedule` — last 7 days of delivery orders
- `GET  /api/weekly-coupon-report` — Monday 7am PT coupon activity email (see below)
- `GET  /health` — Cloud Run health check

All non-health endpoints require `X-API-Key` header matching
`DISPATCH_API_KEY` env var.

## Weekly coupon activity report

`weekly_report.py` builds the Monday-morning OCWR summary from Firestore
`order_events`: the prior Monday-to-Sunday week, a trailing series of up to
eight weeks (never reaching back before the launch week), program-to-date by
jurisdiction, a monthly rollup, and material/site splits. The email body is
table-layout HTML with inline CSS (Outlook-safe) plus a plain-text
alternative, and an `.xlsx` with order-level detail is attached. The
attachment carries customer contact fields; recipients are internal only.

Scope rules:

- **OCWR only.** Documents whose `region` is not `oc` are dropped
  (`WEEKLY_REPORT_REGION`; set to an empty string to include all regions).
- **Launch anchor.** The OCWR program launched 2026-08-28. Orders dated
  earlier are soft-launch or test activity: they collapse into one
  "Pre-launch (before Aug 28)" row in the monthly table and appear nowhere
  else, including the attachment (`WEEKLY_REPORT_PROGRAM_START`).
- **Test orders.** Order numbers in `WEEKLY_REPORT_EXCLUDE` (default `A1`)
  are dropped entirely.

Orders are dated by the CIMcloud order date (Pacific `processed_at` date as
fallback). Jurisdiction names come from `coupons.xlsx` in the
`agromin-coupon-data` bucket; if that read fails the code abbreviation table
in `weekly_report.py` is used (the `send=false` JSON reports which).
The coupon-value column appears in the jurisdiction table once any order in
scope carries a `coupon_amount`, which `_process_order` persists for orders
ingested after the 2026-09-14 deploy.

Query parameters on `GET /api/weekly-coupon-report`:

| Param | Effect |
|---|---|
| `preview=true` | Return the HTML body for viewing in a browser; nothing is sent |
| `send=false` | Build the report, return summary JSON, nothing is sent |
| `week_ending=YYYY-MM-DD` | Re-run for a past week; must be a Sunday |
| `to=a@x,b@x` | Override the recipient list for a test send |

Cloud Scheduler job (create once; the service account needs no special
role because the endpoint authenticates with the API key header). As of
2026-09-14 the Cloud Scheduler API had never been enabled on
`juris-coupon-valid`, so enable it first:

```bash
gcloud services enable cloudscheduler.googleapis.com --project juris-coupon-valid

gcloud scheduler jobs create http weekly-coupon-report \
  --project juris-coupon-valid --location us-west1 \
  --schedule "0 7 * * 1" --time-zone "America/Los_Angeles" \
  --uri "https://coupon-dispatch-751008504644.us-west1.run.app/api/weekly-coupon-report" \
  --http-method GET \
  --headers "X-API-Key=$DISPATCH_API_KEY" \
  --attempt-deadline 300s
```

Firestore reads the whole `order_events` collection on each run, which is
fine at current volume (tens of documents); revisit with a date-indexed query
if it grows past a few thousand.

## Environment variables

Email is sent via the Microsoft Graph API using app-only authentication
(client-credentials flow). The app registration "Agromin Coupon Dispatch"
is scoped via Exchange RBAC to send only as `dispatch@agromin.com`.

| Variable | Required | Notes |
|---|---|---|
| `DISPATCH_API_KEY` | Yes | Auth secret shared with Power Automate |
| `GRAPH_TENANT_ID` | For email | Entra directory (tenant) ID |
| `GRAPH_CLIENT_ID` | For email | App registration's application (client) ID |
| `GRAPH_CLIENT_SECRET` | For email | Client secret value (rotate every 24 mo) |
| `MAIL_SENDER` | No | Defaults to `dispatch@agromin.com` |
| `OFELIA_EMAIL` | No | CC'd on customer emails |
| `GREG_EMAIL` | No | OC delivery coordinator; also CC'd on delivery confirmations |
| `BRIAN_EMAIL` | No | OC delivery coordinator |
| `KENDALL_EMAIL` | No | OCWR side, monitors QR logs |
| `CHRIS_EMAIL` | No | Ventura coordinator |
| `ROSA_EMAIL` | No | Sacramento coordinator |
| `CONFIRMATION_BCC` | No | Comma-separated internal BCC on every customer confirmation. Defaults to `KENDALL_EMAIL`. Set to an empty string to disable. |
| `WEEKLY_REPORT_TO` | No | Comma-separated recipients of the Monday coupon report. Defaults to the 13-address internal list in `weekly_report.py`. |
| `WEEKLY_REPORT_EXCLUDE` | No | Comma-separated order numbers to drop from the report as test orders. Defaults to `A1`. |
| `WEEKLY_REPORT_PROGRAM_START` | No | ISO date; orders before it are shown only as a pre-launch row. Defaults to `2026-08-28`. |
| `WEEKLY_REPORT_REGION` | No | Firestore `region` value to include. Defaults to `oc`; empty string means all regions. |

If Graph creds are unset, email sending is skipped with a warning log
(useful for local development).

## Customer email content

Customer emails are sent as HTML because the approved copy depends on
hyperlinks (the OCWR Bookings appointment link, the compost tips page, and a
printable site map per greenery). A plain-text alternative is built alongside
every HTML body and is what gets sent if HTML is ever disabled.

Body copy is transcribed from Kendall's Word templates, with her July 28
revisions applied: greenery hours are M-Sat (not M-F), the Valencia address
omits the "N." so it points at the greenery rather than the landfill gate, and
the delivery receipt states the cubic-yard conversion in text instead of
embedding the truck-bed graphic.

`GREENERIES` is the single source of truth for customer-facing greenery details.
`YARD_LOCATIONS` is only consulted for yard-name matching and delivery-alert
region routing; its address, phone and hours fields are not sent to customers.

The three greenery site-map URLs were verified by opening each PDF and
confirming the heading names the same greenery as the block it sits under. The
source templates had these three links rotated by one position, which a test
now guards against.

## Deploy

```bash
cd dispatch
gcloud run deploy coupon-dispatch \
  --source . \
  --region us-west1 \
  --project juris-coupon-valid \
  --allow-unauthenticated
```

## Coupon validation

This service does not validate coupons. By the time an order reaches
`/api/ingest-order`, the coupon was already validated by
`coupon-validator` at checkout, and Power Automate filters on the
presence of `Coupon Code:` in the email body so only program orders are
forwarded.
