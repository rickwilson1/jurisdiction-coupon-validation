# coupon-dispatch API Integration Guide

For CIMcloud storefront integrations and Power Automate order dispatch flows.

---

## Service URL

`https://coupon-validator-751008504644.us-west1.run.app`

(Cloud Run service name unchanged from original deployment)

---

## Purpose

Validate whether a coupon code is valid for a customer's delivery address.
Checks coupon status, date validity, and jurisdiction match.

## Endpoint

`GET https://coupon-validator-751008504644.us-west1.run.app/api/validate-coupon`

## Request Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `address` | string | Yes | Full California delivery address |
| `coupon` | string | Yes | Coupon code (case-insensitive) |

## CIMcloud Address Selection

Each CIMcloud transaction has two addresses: Billing and Shipping.
The address sent to the API depends on the customer's delivery option:

- "Ship to my address" -> use SHIPPING address
- "Pick up at our office" -> use BILLING address

Notes:
- Billing address is always present (even for zero-dollar transactions).
- Shipping address is relevant when delivery is selected.

## Example Requests

Valid coupon for Ventura address:

`GET /api/validate-coupon?address=501+Poli+St,+Ventura,+CA+93001&coupon=CITYVCOM26`

Invalid coupon (wrong jurisdiction):

`GET /api/validate-coupon?address=1515+S+St,+Sacramento,+CA+95811&coupon=CITYVCOM26`

## Response Format

Accepted:

```json
{
  "status": "accepted",
  "coupon": "CITYVCOM26",
  "jurisdiction": "City of Ventura",
  "matched_address": "501 Poli St, Ventura, California, 93001",
  "reason": "Address is within coupon jurisdiction"
}
```

Denied - wrong jurisdiction:

```json
{
  "status": "denied",
  "coupon": "CITYVCOM26",
  "jurisdiction": "City of Ventura",
  "actual_jurisdiction": "SACRAMENTO",
  "matched_address": "1515 S St, Sacramento, California, 95811",
  "reason": "Address is in SACRAMENTO, not City of Ventura"
}
```

Denied - coupon not found:

```json
{
  "status": "denied",
  "coupon": "INVALIDCODE",
  "reason": "Coupon code not found"
}
```

Error - address not found:

```json
{
  "status": "error",
  "coupon": "CITYVCOM26",
  "reason": "Address could not be geocoded"
}
```

## Validation Checks (Order)

1. Coupon code exists in the system.
2. Coupon status is `Active`.
3. Current date is within `Start Date` and `End Date`.
4. Jurisdiction rule check:
   - City coupons: address must be in that city.
   - County coupons: address must be in the county and in an unincorporated area.
   - Addresses inside incorporated cities are denied for county coupons.

## Authentication

Public validation endpoints do not require authentication.

Admin upload endpoint requires API key:

- `POST /api/upload-coupons`
- Header: `X-API-Key: <your_upload_api_key>`

## CORS (Browser Clients)

Current allowed origins:

- Explicit:
  - `https://commercial.agromin.com`
  - `https://shop.agromin.com`
- Regex:
  - `https://*.agromin.com`
  - `https://*.agromin.mycimstaging.com`
  - `https://*.agromin.cimstaging.com`

Responses include:

- `Access-Control-Allow-Origin: <matching origin>`
- `Access-Control-Allow-Credentials: true`

If CORS errors persist:

1. Clear browser cache or test in incognito.
2. Confirm frontend calls:
   - `https://coupon-validator-751008504644.us-west1.run.app`
3. Verify `OPTIONS` preflight returns 2xx with CORS headers.

## Legacy Endpoint

`GET /api/validate?address=...&jurisdiction=City+of+Sacramento`

This validates an address against a claimed jurisdiction name.

## Web Interface

Manual validation page:

`https://coupon-validator-751008504644.us-west1.run.app/`

## Updating Coupons (Admin)

Coupon data is stored in Google Cloud Storage and can be updated without redeploying the API.
Changes take effect within 5 minutes.

Alternative admin update:

- `POST /api/upload-coupons` with `X-API-Key`
- Supports multipart upload or raw binary body
- File type auto-detected (`.xlsx` if file starts with `PK`, otherwise `.csv`)

Supported formats:

- Excel (`.xlsx`) recommended
- CSV (`.csv`) supported

Cloud Storage:

- `gs://agromin-coupon-data/coupons.xlsx` (first)
- `gs://agromin-coupon-data/coupons.csv` (fallback)

Required columns:

`Coupon | Program Status | Jurisdiction | Start Date | End Date`

---

## Dispatch Endpoints (New — April 2026)

### POST /api/ingest-order

Receives a parsed order payload from Power Automate. Applies routing logic,
dispatches emails, writes Firestore log, and returns routing decision.

**Auth:** `X-API-Key` header (same key as `/api/upload-coupons`)

**Request body (JSON):**

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

**Routing logic:**
1. Confirm `coupon_code` exists in active coupons (load_coupons()) — else ignore
2. Detect fulfillment type from `shipping_method`:
   - Contains `Delivery` → delivery path
   - Contains `Pick Up` or `Pickup` or `Will Call` → pickup path
3. Pickup path qty threshold (bulk SKU ES2):
   - `qty < 5` → self-loading template
   - `qty >= 5` → staff-loaded template
4. Write order to Firestore `order_events` (doc ID = order_number)
5. Send customer email via SMTP (M365 relay, from sales@agromin.com, CC ofelia@agromin.com)
6. Delivery path only: send alert to greg@agromin.com

**Response:**

```json
{
  "status": "routed",
  "order_number": "108852",
  "routing": "pickup_self_load",
  "coupon": "CITYOJAICM26",
  "jurisdiction": "City of Ojai",
  "actions_taken": ["email_sent_to_customer", "ofelia_cc", "firestore_logged"]
}
```

Routing values: `pickup_self_load`, `pickup_staff_load`, `delivery`, `ignored_not_program_order`

---

### POST /api/generate-manifest

Generates a PDF manifest slip for delivery orders.

**Auth:** `X-API-Key` header

**Request body:** Same `OrderPayload` schema as `/api/ingest-order`

**Response:** `application/pdf` binary

PDF contains: order number, customer name, delivery address, material, quantity,
generated timestamp, hauler signature line.

---

### GET /api/delivery-schedule

Returns next 7 days of delivery orders from Firestore. Called by Cloud Scheduler
every Friday at 4:00 PM PT, which then passes the response to Power Automate
to format and email Ofelia.

**Auth:** `X-API-Key` header

**Response:**

```json
{
  "week_of": "2026-04-20",
  "delivery_count": 4,
  "deliveries": [
    {
      "order_number": "108870",
      "customer_name": "Julian Vanderlinden",
      "delivery_address": "417 Skyhigh Drive, Ventura, CA 93001",
      "material": "Cover Mulch",
      "qty": 20,
      "coupon": "COUVCM26",
      "jurisdiction": "County of Ventura"
    }
  ]
}
```

---

## Power Automate Integration

**Trigger:** When new email arrives in sales@agromin.com shared mailbox

**Filter conditions (all three required):**
- From: `Sales@agromin.com`
- Subject starts with: `Pending Approval for Order Number`
- Body contains: `Coupon Code:`

**Why these filters:**
- `From: Sales@agromin.com` — CIMcloud sends from this address; excludes customer replies
- Subject prefix — CIMcloud's consistent order confirmation subject line
- `Coupon Code:` — only present in program orders; excludes all paid orders

**Fields to parse from email body:**
- Order number (from subject line or Order Information section)
- Coupon Code (from Order Summary table)
- Payment Method (confirm = "No Payment Required")
- Billing name + address
- Shipping address
- Shipping Method
- Line items: Description, SKU, Qty

**POST to:** `https://coupon-validator-751008504644.us-west1.run.app/api/ingest-order`

**Header:** `X-API-Key: <UPLOAD_API_KEY>`

---

## Email Templates (sent by /api/ingest-order)

### Pickup — self-loading (qty < 5 yards)

Subject: `Your Agromin Order #[order_number] — Pickup Instructions`

Customer self-loads using 5-gallon buckets at yard. Include yard address/hours.
Must bring email confirmation + proof of address (ID or utility bill).

### Pickup — staff-loaded (qty >= 5 yards)

Subject: `Your Agromin Order #[order_number] — Pickup Instructions`

Trucks/trailers only. OCWR staff loads with equipment. No cars. No self-loading.
Must bring email confirmation + proof of address.

### Delivery acknowledgment

Subject: `Your Agromin Order #[order_number] — Delivery Scheduled`

Agromin representative will contact customer within 1 business day to schedule.
Delivery fees apply separately.

---

## Environment Variables (full list)

**Existing (already set in Cloud Run):**
```
ARCGIS_API_KEY=
COUPONS_BUCKET=agromin-coupon-data
UPLOAD_API_KEY=
```

**New (add in Cloud Run console):**
```
SMTP_USER=sales@agromin.com
SMTP_PASSWORD=<M365 app password for sales@agromin.com>
OFELIA_EMAIL=ofelia@agromin.com
GREG_EMAIL=greg@agromin.com
```

**M365 SMTP setup (no Azure app registration required):**
1. M365 Admin Center → Users → sales@agromin.com → Mail → Manage email apps
2. Enable: Authenticated SMTP
3. Generate app password if MFA is enabled on the account
4. Store password in GCP Secret Manager, reference as env var in Cloud Run

**SMTP relay settings:**
- Host: `smtp.office365.com`
- Port: `587`
- Encryption: STARTTLS
- Auth: SMTP_USER + SMTP_PASSWORD

---

## New Dependencies (add to requirements.txt)

```
reportlab>=4.0.0
google-cloud-firestore>=2.13.0
```

Both are pure Python — no system dependency impact on Docker build.
