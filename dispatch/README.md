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
- `GET  /health` — Cloud Run health check

All non-health endpoints require `X-API-Key` header matching
`DISPATCH_API_KEY` env var.

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
| `GREG_EMAIL` | No | OC delivery coordinator |
| `BRIAN_EMAIL` | No | OC delivery coordinator |
| `KENDALL_EMAIL` | No | OCWR side, monitors QR logs |
| `CHRIS_EMAIL` | No | Ventura coordinator |
| `ROSA_EMAIL` | No | Sacramento coordinator |

If Graph creds are unset, email sending is skipped with a warning log
(useful for local development).

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
