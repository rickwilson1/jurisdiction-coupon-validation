# Handover: coupon-reports Cloud Run Service

**Purpose of this handover:** stand up a new Cloud Run service, `coupon-reports`, that lets Agromin accountants search and report on coupon-program transactions by coupon code, jurisdiction, and date, singly or in any combination, with full transaction detail and CSV/Excel export. This document carries all the background a fresh Cowork project needs. It assumes no prior exposure to the coupon-dispatch system.

**Source of truth:** the `sales@agromin.com` shared mailbox. CIMcloud emails every program order ("Pending Approval for Order Number XXXXXX") to that mailbox; Power Automate forwards each to the dispatch service, which parses it and writes a record to Firestore. The reporting service reads Firestore. There is no second database to reconcile.

**Decisions already made (do not re-litigate):**

- Data source is `sales@agromin.com`, captured into Firestore `order_events`. Extend the existing Firestore write rather than adding a parallel store.
- The reporting interface is a new, standalone Cloud Run service, not endpoints bolted onto the dispatch service.
- Accountants need CSV / Excel export of filtered results.

---

## 1. System context

Agromin runs free bulk compost and mulch programs for California jurisdictions under SB 1383 organics-diversion mandates. Residents in a participating jurisdiction order material at `shop.agromin.com` (a CIMcloud storefront) using a jurisdiction-specific coupon code that zeroes out the material cost. The jurisdiction reimburses Agromin. Accountants need to see, per coupon and per jurisdiction over a date range, exactly what was given away and to whom, because that is the basis for billing the municipal programs.

Two Cloud Run services already exist in GCP project `juris-coupon-valid`, region `us-west1`:

- **coupon-validator** (production, live): validates a coupon against a delivery address at checkout. URL `https://coupon-validator-751008504644.us-west1.run.app`. Called by CIMcloud. Do not touch.
- **coupon-dispatch** (the order-routing service): ingests confirmed orders, routes pickup vs. delivery, emails customers and coordinators, generates delivery manifests, writes the transaction record to Firestore. URL `https://coupon-dispatch-751008504644.us-west1.run.app`. Code in `dispatch/main.py`. This is the service whose Firestore write you will extend.

`coupon-reports` becomes the third service. It shares the project and the Firestore database, and is deployed the same way as the others (manual `gcloud run deploy --source .` — there is no auto-deploy on push to main), but it has its own URL and codebase and never writes order data; it reads.

Coupon coverage at handover time: 83 active codes across Orange County (OCWR, 34 cities plus OC Unincorporated), the Ventura County area (Ventura city/county, Oxnard, Camarillo, Fillmore, Ojai), and the City of Sacramento. Code pattern: `CITY[ABB]COM26` is compost, `CITY[ABB]CM26` is cover mulch, and `COU[ABB]...` variants are unincorporated-county codes.

### New service vs. extend the existing app

Build a new `coupon-reports` service rather than adding the accountant interface to the dispatch app. The two have opposite risk and access profiles, and coupling them creates problems that separation avoids.

The dispatch service is on the live order path: every deploy risks the email-routing and Firestore-write logic that customers and coordinators depend on in real time. The reporting service is read-only and internal. Folding a human-facing UI, Excel generation, and ad-hoc query endpoints into the dispatch service means every reporting tweak redeploys the order pipeline, and a reporting bug can take down order processing. They also want different auth: dispatch authenticates machines (CIMcloud, Power Automate) with an `X-API-Key`, while the reporting UI needs human SSO behind Identity-Aware Proxy. And their dependencies differ: dispatch is a heavy image (GeoPandas, GDAL, the 26 MB CDTFA shapefile, reportlab, MSAL) that the reporting service has no use for, so a separate service stays small and fast to build and deploy. The only shared surface is Firestore `order_events`, which both reach independently. The single change that does belong in the dispatch service is the parser-and-write extension in Sections 3 and 3a, because that is where orders are captured; everything the accountants touch lives in the new service.

---

## 2. The transaction pipeline (where data comes from)

The chain from order to queryable record:

1. Customer checks out at `shop.agromin.com` with a coupon code. Material cost goes to zero; delivery orders still pay a separate delivery fee.
2. CIMcloud sends a "Pending Approval for Order Number XXXXXX" email **from** `Sales@agromin.com` **to** the `sales@agromin.com` shared mailbox. Program orders carry a `Coupon Code:` field in the order-summary table; paid orders do not.
3. A Power Automate flow watches that mailbox. Filters: From `Sales@agromin.com`, Subject starts with `Pending Approval for Order Number`, Body contains `Coupon Code:`. It forwards the raw HTML body to the dispatch service at `POST /api/ingest-cimcloud-email` (header `X-API-Key`).
4. The dispatch service parses the email (`parse_cimcloud_email` in `dispatch/main.py`) into an `OrderPayload`, applies routing logic, sends emails, and writes one document to Firestore collection `order_events`, keyed by order number.

Everything the reporting service shows therefore originates in that mailbox and lands in `order_events`. There are two gaps to close, both in `dispatch/main.py`: the **parser** does not extract the order-summary financial block (tax, shipping, coupon amount, totals) or several identity fields, and the **Firestore write** does not persist even the fields the parser already has. Section 3 and 3a cover both.

The CIMcloud `OrderPayload` schema (already implemented, verified against live orders #108852, #108870, #108872):

```json
{
  "order_number": "108852",
  "order_date": "4/16/2026 11:38:23 AM PT",
  "coupon_code": "CITYOJAICM26",
  "payment_method": "No Payment Required",
  "customer_name": "Coline Tabrum",
  "customer_email": "coellii@yahoo.co.nz",
  "customer_phone": "805-640-0650",
  "billing_address": "1242 Anita Ave, Ojai, CA 93023",
  "shipping_address": "1940 E Ojai Ave, Ojai, CA 93023",
  "shipping_method": "Bag Pick Up at Aqua-Flo Ojai",
  "line_items": [
    { "sku": "ES2", "description": "Cover Mulch", "qty": 20, "unit_price": 35.95 }
  ]
}
```

Data realities the accountant app must respect: SKU `ES2` is bulk Cover Mulch and `qty` is cubic yards; delivery orders carry a coupon but a nonzero total because the shipping fee is charged separately, so an order is a program order based on coupon-code presence, never on a $0.00 total; `shipping_method` is the pickup-vs-delivery switch ("Delivery" substring means delivery, otherwise pickup); pickup quantity under 5 cubic yards is self-load and 5 or more is staff-load.

---

## 3. Data model: what to add to Firestore order_events

The dispatch service currently writes this document (`_process_order` in `dispatch/main.py`):

```python
{
  "order_number": ...,        # str, doc ID
  "processed_at": ...,        # datetime (UTC)
  "coupon_code": ...,         # str, normalized upper
  "routing": ...,             # "delivery" | "pickup_self_load" | "pickup_staff_load"
  "region": ...,              # "oc" | "ventura" | "sacramento" | "unknown"
  "customer_name": ...,
  "customer_email": ...,
  "shipping_method": ...,
  "shipping_address": ...,
  "total_qty": ...,           # float, sum of line-item qty
  "material": ...,            # first line-item description only
  "order_date": ...,          # str, raw CIMcloud date string
  "customer_phone": ...,
  "status": "success"
}
```

That covers coupon, jurisdiction-by-proxy (region), date, customer, and quantity, but it loses the financial detail and the full line-item breakdown the accountants asked for. The `OrderPayload` already holds these fields; they are simply not persisted. Extend the write in `_process_order` to add:

- `billing_address` (string) — already on the payload; pickup orders validate against billing address, so it matters for jurisdiction reconciliation.
- `jurisdiction` (string) — the human-readable jurisdiction name (e.g., "City of Ojai"), not just the `region` bucket. The validator already resolves this; capture it here so reports read clean names. If the dispatch service does not currently have the jurisdiction string, derive it from the coupon record (`load_coupons()` exposes a `Jurisdiction` column) keyed by `coupon_code`.
- `line_items` (array) — persist the full list, each with `sku`, `description`, `qty`, `unit_price`, and a computed `line_total` (`qty * unit_price`). The current single `material` string cannot represent multi-material orders, which Greg's master sheet already handles one-row-per-line-item.
- `subtotal` (float) — sum of `line_total` across line items (the gross material value, i.e., the amount the jurisdiction effectively reimburses).
- `delivery_fee` (float) — the separately charged shipping fee on delivery orders; parse from `shipping_method` where a dollar amount is embedded (e.g., "$230 Delivery - Minimum 3 Cubic Yards") or from the order total minus subtotal. Pickup orders are 0.
- `order_total` (float) — what the customer actually paid (0 for pickup program orders, the delivery fee for delivery program orders).
- `payment_method` (string) — already on payload. Do not treat any specific value as the program-order signal: delivery orders show "Credit or Debit Card" (the customer pays tax and shipping) yet are still program orders. Coupon-code presence is the only reliable test. Store the value for the record, but key program status off the coupon.
- `tax` (float) — the Tax line in the order-summary block. Charged on delivery orders even when material is fully couponed (the live email shows $10.47). Not currently parsed; see Section 3a.
- `shipping` (float) — the Shipping line ($135.00 on the live email). Equals the delivery fee. Pickup orders are 0.
- `coupon_amount` (float) — the Coupon line, the dollar value the coupon offsets. This is the authoritative reimbursement basis, equal to the material subtotal on a fully-couponed order ($179.75 on the live email). Capture it directly rather than inferring it from line items.
- `order_comments` (string) — the free-text Order Comments field ("Can dump anytime on the street in front of house"). Operationally important for delivery and worth surfacing in the drill-down.
- `account_id` and `username` (strings) — both appear on every email: account number `02-W033717` / customer code `W033717` and username `rock1998`. Use for dedup and for tying repeat customers together across orders.

Keep `processed_at` as the authoritative timestamp for date-range filtering, and also store a parsed `order_date_iso` (ISO 8601) derived from the raw `order_date` string so the reporting service can filter and sort on order date without re-parsing CIMcloud's "4/16/2026 11:38:23 AM PT" format on every query.

Two backfill notes. First, only orders processed after this change carries the new fields; historical `order_events` documents will have nulls for `subtotal`, `line_items`, etc. If accountants need pre-change history, a one-time backfill job can re-parse the archived CIMcloud emails in the `sales@agromin.com` mailbox or the existing CSV exports (`coupon_orders_CITYSACCOMB26.csv` and the OCWR `.xlsx` logs in the repo root) and upsert into `order_events`. Treat that as a separate, optional task. Second, the reporting service must tolerate missing fields gracefully so old and new documents both render.

---

## 3a. Authoritative field map from the live order email

The fields below are the complete set to store and tabulate, taken directly from a real CIMcloud "Pending Approval" email (order #A110413, placed 6/28/2026, coupon `CITYVCOM26`, a Ventura delivery order). This order is the important edge case: it carries a coupon **and** a credit-card payment **and** a nonzero total, because the coupon zeroes the material but tax and the delivery fee are still charged. Any storage or filtering logic that assumes a couponed order is $0.00 or "No Payment Required" is wrong.

| Email field | Stored field | Example value | Notes |
|---|---|---|---|
| Order number | `order_number` | A110413 | Strip leading `A` for Greg's integer sheet; keep raw on the record. |
| Order placed on | `order_date` / `order_date_iso` | 6/28/2026 8:32:31 AM PT | Parse to ISO for querying. |
| Coupon Code | `coupon_code` | CITYVCOM26 | Program-order key. |
| Payment Method | `payment_method` | Credit or Debit Card | Not a program-status signal; store only. |
| Account | `account_id` | 02-W033717 | Also appears as `W033717` in billing block. |
| Username | `username` | rock1998 | |
| Billing name | `customer_name` | John Ross | |
| Billing address | `billing_address` | 214 S Joanne Ave., Ventura, CA 93003 | |
| Phone | `customer_phone` | 831-600-6459 | |
| Email | `customer_email` | ross4evr@gmail.com | |
| Shipping address | `shipping_address` | 214 S Joanne Ave., Ventura, CA 93003 | |
| Shipping Method | `shipping_method` | $135 Delivery - Minimum 3 Cubic Yards | "Delivery" → delivery routing; embedded `$135` is the fee. |
| Order Comments | `order_comments` | Can dump anytime on the street in front of house. | Free text; surface in drill-down. |
| Line item Qty | `line_items[].qty` | 5 | Cubic yards for bulk. |
| Line item Description | `line_items[].description` | Compost 100 | |
| Line item SKU | `line_items[].sku` | COM | |
| Line item Unit Price | `line_items[].unit_price` | 35.95 | |
| Line item Price | `line_items[].line_total` | 179.75 | qty × unit_price. |
| Subtotal | `subtotal` | 179.75 | Gross material value. |
| Tax | `tax` | 10.47 | |
| Shipping | `shipping` | 135.00 | Delivery fee. |
| Coupon | `coupon_amount` | 179.75 | Reimbursement basis. |
| Total | `order_total` | 145.47 | What the customer actually paid. |

Note the SKU here is `COM` (Compost 100), distinct from the `ES2`/Cover Mulch example in the original handoff. SKUs vary by material and program; do not hard-code them. Material classification should key off the description text (`classify_material` in `dispatch/main.py` already maps "compost"/"mulch"/"bag" substrings).

Parser work this requires: the current `parse_cimcloud_email` extracts coupon code, payment method, contact, addresses, shipping method, and line items, but not the order-summary financial block (Subtotal, Tax, Shipping, Coupon, Total), the Order Comments cell, or the Account/Username pair. Add extraction for these by reading the labeled rows in the order-summary table the same way `_value_after_label` already reads "Coupon Code:" and "Payment Method:". Extend the `OrderPayload` model with `tax`, `shipping`, `coupon_amount`, `order_total`, `subtotal`, `order_comments`, `account_id`, and `username` before the Firestore write can persist them. This is a change to the dispatch service that must land before the reporting service has complete data to read.

---

## 4. coupon-reports service specification

### 4.1 Shape

A single-file FastAPI service, same conventions as `dispatch/main.py`: `main.py`, `requirements.txt`, `Dockerfile`, `.gcloudignore`, deployed to Cloud Run in `juris-coupon-valid` / `us-west1` via a manual `gcloud run deploy --source .` (no push-to-main auto-deploy exists). It is read-only against Firestore. It needs the `Cloud Datastore User` role on its service account (read is sufficient; do not grant write). No ArcGIS, no CDTFA shapefile, no GeoPandas; the image stays light because it never geocodes.

### 4.2 Endpoints

`GET /api/transactions` — the core search. All filters optional and combinable; with no filters it returns the most recent N transactions.

Query parameters:

| Param | Type | Description |
|---|---|---|
| `coupon` | string | Exact coupon code, case-insensitive. |
| `jurisdiction` | string | Jurisdiction name or region bucket; substring match. |
| `date_from` | date (YYYY-MM-DD) | Inclusive lower bound on order date. |
| `date_to` | date (YYYY-MM-DD) | Inclusive upper bound on order date. |
| `routing` | string | Optional: `delivery`, `pickup_self_load`, `pickup_staff_load`. |
| `limit` | int | Page size, default 100, max 1000. |
| `cursor` | string | Firestore pagination cursor. |

Response: JSON array of full transaction records (every field in Section 3) plus a `next_cursor`. Sort by order date descending.

`GET /api/transactions/{order_number}` — single transaction, full line-item detail, billing and shipping addresses, people involved (customer, assigned coordinator by region), routing, financials. This is the drill-down view.

`GET /api/export` — same query parameters as `/api/transactions`, but returns a file. Support `format=xlsx` (default) and `format=csv`. The Excel export should include a header row matching accountant expectations and one row per transaction (or, for invoicing, one row per line item; see note below). Use `openpyxl` for `.xlsx`; do not introduce LibreOffice or pandas-heavy dependencies. Stream the file with `Content-Disposition: attachment`.

`GET /api/summary` — roll-up for billing. Group by `jurisdiction` (and optionally by month) over the date range and return order count, total cubic yards (`sum(total_qty)`), and total material value (`sum(subtotal)`). This is what the accountants hand to whoever invoices the jurisdictions. Even though only CSV export was requested as a hard requirement, this endpoint is cheap to add and directly serves the reimbursement-billing use case; include it.

`GET /health` and `GET /` — health check and a minimal landing page.

### 4.3 Web UI

A single server-rendered HTML page at `/` (or `/app`) with three filter controls (coupon code, jurisdiction dropdown, date-from/date-to), a results table, a row-click drill-down, and an Export button that hits `/api/export` with the current filter state. Keep it dependency-light: a single HTML template with vanilla JS fetch calls against the JSON endpoints is sufficient and matches the existing project's pattern of self-contained HTML mockups. No build step, no SPA framework.

### 4.4 Firestore query strategy

Firestore composite queries are limited: a single inequality range applies to one field per query. Order-date range filtering is the natural inequality, so build the base query on `order_date_iso` (or `processed_at`) range, then apply `coupon_code` and `routing` as equality filters in the same query (these are allowed alongside one range). Jurisdiction substring matching cannot be done server-side in Firestore; resolve it by either filtering in application code after the Firestore fetch, or, if jurisdiction is stored as an exact normalized string, use equality. Create the composite indexes Firestore prompts for on first query. For the volumes here (tens to low hundreds of orders per month) a range-plus-equality query with in-memory jurisdiction filtering is entirely adequate; do not over-engineer.

### 4.5 Auth

The dispatch and validator services use an `X-API-Key` header. For an accountant-facing UI that is the wrong model, because the people using it are humans in a browser, not a machine integration. Put the service behind Google Identity-Aware Proxy (IAP) so only authenticated Agromin Google Workspace accounts can reach it, and keep an `X-API-Key` check on the JSON/export endpoints for any programmatic use. IAP gives you SSO, per-user audit logging, and no password handling in the app. This is a deliberate divergence from the other two services because their callers are CIMcloud and Power Automate, not people.

### 4.6 Environment variables

```
REPORTS_API_KEY=<new key for programmatic export access>
GCP_PROJECT=juris-coupon-valid          # for explicit Firestore client init if needed
FIRESTORE_COLLECTION=order_events
```

No SMTP, no Graph, no ArcGIS keys; the reporting service sends no email and geocodes nothing.

---

## 5. Build sequence

Work in this order; do not advance until the current step returns correct data.

1. Extend the dispatch service in `dispatch/main.py`. First the parser (`parse_cimcloud_email`): extract Subtotal, Tax, Shipping, Coupon, Total from the order-summary block, plus Order Comments, Account, and Username (Section 3a). Add the matching fields to the `OrderPayload` model. Then the Firestore write (`_process_order`): persist all new fields, compute `line_total` per line item, resolve `jurisdiction` from the coupon record, and add `order_date_iso`. Deploy dispatch, fire the live #A110413 email through `POST /api/ingest-cimcloud-email`, and confirm the full document shape in the Firestore console.
2. Scaffold `coupon-reports` as a new directory mirroring `dispatch/` (`main.py`, `requirements.txt` with `fastapi`, `uvicorn`, `google-cloud-firestore`, `openpyxl`; `Dockerfile`; `.gcloudignore`).
3. Implement `GET /api/transactions` with the range-plus-equality Firestore query and in-memory jurisdiction filter. Verify against the test order and any existing `order_events` documents (tolerating null new-fields on old docs).
4. Implement `GET /api/transactions/{order_number}` drill-down.
5. Implement `GET /api/export` (xlsx and csv) with `openpyxl`.
6. Implement `GET /api/summary` jurisdiction roll-up.
7. Build the single-page web UI with filters, table, drill-down, and export button.
8. Deploy a new Cloud Run service `coupon-reports` via `gcloud run deploy --source .` (or, if you want CI, add a GitHub Actions workflow — none exists today); grant its service account `Cloud Datastore User`; enable IAP and restrict to the Agromin Workspace domain.
9. End-to-end test: log in via IAP as an accountant account, search by coupon, by jurisdiction, by date, and by all three combined; export to Excel; confirm the summary totals reconcile against a hand-count of the test orders.

---

## 6. Open questions to resolve with the accountants before or during build

- Should the Excel export be one row per order or one row per line item? One-row-per-line-item matches Greg's existing master-sheet convention and makes multi-material orders sum cleanly; one-row-per-order is friendlier for a quick scan. Confirm which they reconcile against.
- Is `subtotal` (gross material value at list price) the correct reimbursement basis, or does each jurisdiction reimburse at a negotiated rate that differs from the CIMcloud `unit_price`? If rates differ by jurisdiction, the summary endpoint needs a rate table rather than a raw `unit_price` sum.
- Do accountants need pre-change historical orders (the backfill in Section 3), and if so, back to what date? This determines whether the one-time email/CSV backfill job is in scope now or later.
- Should the delivery fee appear as revenue in these reports, or is it tracked separately in QuickBooks and out of scope here? The reporting service can capture it either way; the question is whether to surface it.

---

## 7. Reference files in the existing repo

- `dispatch/main.py` — the order-processing service; `_process_order` is the Firestore write to extend, `parse_cimcloud_email` is the source-of-truth parser, `OrderPayload` is the canonical schema.
- `docs/API_INTEGRATION.md` — endpoint and Power Automate integration detail for the existing services.
- `CURSOR_HANDOFF.md` — the original dispatch build handoff; confirms field provenance and routing rules.
- `README.md` — service overview, coupon-program coverage, deployment summary.
- `coupon_orders_CITYSACCOMB26.csv`, `Agromin Outbound Log- OCWR Material.xlsx`, `Archive_4May26_OCWR-Agromin Deliveries.xlsx` — existing exports; useful as backfill input and as a reference for the column set accountants already work with.
