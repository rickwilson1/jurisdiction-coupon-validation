# coupon-dispatch

FastAPI service for coupon validation and order fulfillment dispatch across
Agromin's multi-jurisdiction free compost and mulch programs.

Previously named `coupon-validator`. Renamed April 2026 to reflect the addition
of full order routing, email dispatch, manifest generation, and delivery scheduling.

## What It Does

**Validation (existing)**
- Geocodes a customer address via ArcGIS.
- Maps address to CDTFA tax district (city + county + unincorporated).
- Validates coupon code existence, active status, date range, and jurisdiction match.
- City coupons require city match. County coupons require unincorporated county area.

**Dispatch (new — April 2026)**
- Ingests order payloads from Power Automate (triggered by CIMcloud confirmation email).
- Routes orders: pickup vs. delivery, qty threshold (<5 yds self-load / ≥5 yds staff-load).
- Sends correct email template to customer via M365 SMTP relay from sales@agromin.com.
- CCs ofelia@agromin.com on every order email.
- Alerts greg@agromin.com on delivery orders; writes row to SharePoint delivery log.
- Generates PDF manifest for delivery haulers (reportlab).
- Logs every processed order to Firestore collection `order_events`.
- Compiles and sends weekly delivery schedule to Ofelia (Cloud Scheduler, Friday 4pm).

## Coupon Programs Served

83 active coupon codes across:
- Orange County (OCWR) — 34 cities + OC Unincorporated, started 4/15/2026
- Ventura County area — City/County of Ventura, Oxnard, Camarillo, Fillmore, Ojai
- Sacramento — City of Sacramento

Code pattern: `CITY[ABB]COM26` = compost, `CITY[ABB]CM26` = cover mulch

## Endpoints

### Existing
- `GET  /api/validate-coupon` — validate coupon + address (called by CIMcloud at checkout)
- `GET  /api/validate`        — address → jurisdiction lookup
- `POST /api/upload-coupons`  — admin coupon file upload (X-API-Key required)
- `GET  /health`              — health check
- `GET  /`                    — manual validation web form

### New (dispatch build)
- `POST /api/ingest-order`       — order intake, routing logic, email dispatch, Firestore log
- `POST /api/generate-manifest`  — PDF manifest for delivery haulers
- `GET  /api/delivery-schedule`  — weekly delivery order summary (Cloud Scheduler trigger)

## Deployment

- Cloud Run URL: `https://coupon-validator-751008504644.us-west1.run.app`
- Region: us-west1
- CI/CD: GitHub Actions → Docker → Artifact Registry → Cloud Run (push to main)
- GCS bucket: `agromin-coupon-data` (coupons.xlsx, 5-min TTL cache)
- Firestore collection: `order_events`
- CDTFA shapefile: bundled in image at `CDTFA_TaxDistricts.gpkg` (26MB)

## GitHub

Rename the GitHub repository from `coupon-validator` to `coupon-dispatch`:
Settings → General → Repository name. GitHub redirects the old URL automatically.

## Documentation

- CIMcloud integration guide: `docs/API_INTEGRATION.md`
- Cursor build handoff: `CURSOR_HANDOFF.md`
