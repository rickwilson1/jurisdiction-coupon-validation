# Cursor Handoff: Dispatch Build
## coupon-dispatch — Cloud Run Service

**Model:** Claude Sonnet 4.6  
**Project root:** `~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Active_Projects/Agromin/coupon-dispatch/`  
**Deployed service:** `https://coupon-validator-751008504644.us-west1.run.app`

> This repo was previously named `coupon-validator`. Do not refactor or rename
> existing code. Only add new endpoints and dependencies as described below.

---

## Step 0 — First session tasks (do these before any code)

1. **Rename GitHub repo:** Go to `https://github.com/[your-org]/coupon-validator` →
   Settings → General → Repository name → change to `coupon-dispatch`. GitHub
   redirects the old URL automatically. No CI/CD changes needed.

2. **README.md is already updated** — do not overwrite it.

3. **docs/API_INTEGRATION.md is already updated** — do not overwrite it.

4. **Confirm requirements.txt additions** — add these two lines if not already present:
   ```
   reportlab>=4.0.0
   google-cloud-firestore>=2.13.0
   ```
   Both are pure Python — no system dependency impact on Docker build time.

5. **Confirm new env vars are set in Cloud Run console before testing:**
   ```
   SMTP_USER=sales@agromin.com
   SMTP_PASSWORD=<M365 app password>
   OFELIA_EMAIL=ofelia@agromin.com
   GREG_EMAIL=greg@agromin.com
   ```

---

## What Already Exists (Do Not Touch)

Single-file FastAPI service (`main.py`, ~700 lines) deployed on Cloud Run.

**Existing endpoints — leave exactly as-is:**
- `GET  /api/validate-coupon` — coupon + address → jurisdiction match (called by CIMcloud at checkout)
- `GET  /api/validate`        — address → jurisdiction lookup
- `POST /api/upload-coupons`  — admin coupon file upload, writes to GCS, refreshes cache
- `GET  /health`              — health check
- `GET  /`                    — manual validation web form

**Existing infrastructure already wired:**
- GCS bucket: `agromin-coupon-data` (coupons.xlsx, 5-min TTL cache via `_coupon_cache`)
- ArcGIS geocoder via `ARCGIS_API_KEY` env var
- CDTFA shapefile bundled in container: `CDTFA_TaxDistricts.gpkg` (26MB, loaded at startup)
- CORS configured for `shop.agromin.com`, `commercial.agromin.com`, staging domains
- Auth pattern: `UPLOAD_API_KEY` checked via `X-API-Key` header — reuse this for all new endpoints
- Deployed via GitHub Actions (`.github/workflows/`)

**Key existing functions to reuse — do not rewrite:**
- `load_coupons()` — loads coupon dict from GCS/local, 5-min TTL cache
- `geocode_address(address)` — ArcGIS geocode → lat/lon/matched_address
- `find_tax_district(lat, lon, gdf)` — CDTFA shapefile lookup → jurisdiction dict
- `jurisdictions_match(claimed, actual_city, actual_county)` — jurisdiction comparison logic

---

## Coupon Program Context

Agromin runs free bulk compost/mulch programs for California jurisdictions.
Orders are placed at shop.agromin.com using jurisdiction-specific coupon codes.

**83 active coupon codes across:**
- Orange County (OCWR) — 34 OC cities + OC Unincorporated, started 4/15/2026
- Ventura County area — Ventura City/County, Oxnard, Camarillo, Fillmore, Ojai
- Sacramento — City of Sacramento

**Code naming pattern:**
- `CITY[ABB]COM26` = compost variant
- `CITY[ABB]CM26`  = cover mulch variant
- `COU[ABB]COM26`/`COU[ABB]CM26` = county (unincorporated) variants

**Program order identification:**
- CIMcloud sends "Pending Approval for Order Number XXXXXX" email to sales@agromin.com
- Email contains `Coupon Code:` field in Order Summary table (absent on paid orders)
- Payment Method = "No Payment Required" for material cost (delivery orders still charge separate fee)
- Power Automate parses this email and POSTs to `/api/ingest-order`

---

## CIMcloud Order Data — Confirmed Fields

Verified from live order emails (Order #108852, #108870, #108872):

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

**Important notes from real emails:**
- SKU `ES2` = Cover Mulch (bulk). Qty = cubic yards for bulk material.
- Delivery orders still have a coupon BUT total is not $0.00 (shipping fee charged separately).
  Example: material $719 offset by coupon, shipping $135, total = $144.79.
  Do NOT filter on total = $0.00. Filter on coupon_code presence only.
- `shipping_method` is the routing switch. Confirmed patterns:
  - `"Bag Pick Up at Aqua-Flo Ojai"` → pickup
  - `"$230 Delivery - Minimum 3 Cubic Yards"` → delivery
  - `"$135 Delivery - Minimum 3 Cubic Yards"` → delivery
- Customer replies to the confirmation email have `Re:` prefix and come from customer address.
  Power Automate filter handles this — only process emails from `Sales@agromin.com`.

---

## New Endpoints to Build

Add all three to `main.py`. Keep everything in a single file unless it exceeds ~1000 lines.

### 1. POST /api/ingest-order

```python
class LineItem(BaseModel):
    sku: str
    description: str
    qty: float
    unit_price: float

class OrderPayload(BaseModel):
    order_number: str
    order_date: str
    coupon_code: str
    payment_method: str
    customer_name: str
    customer_email: str
    customer_phone: str = ""
    billing_address: str
    shipping_address: str
    shipping_method: str
    line_items: list[LineItem]

@app.post("/api/ingest-order")
async def ingest_order(
    order: OrderPayload,
    x_api_key: str = Header(None, alias="X-API-Key")
):
```

**Routing logic (in order):**

1. Auth check — same pattern as upload-coupons
2. Normalize `coupon_code.strip().upper()`
3. Check `load_coupons()` — if not found or not active: return `{"status": "ignored", "reason": "not a program order"}`
4. Determine fulfillment type from `shipping_method`:
   - `"Delivery"` in shipping_method (case-insensitive) → `routing = "delivery"`
   - else → `routing = "pickup"`
5. For pickup — determine qty threshold:
   - Sum `qty` across all line_items
   - `total_qty < 5` → `routing = "pickup_self_load"`
   - `total_qty >= 5` → `routing = "pickup_staff_load"`
6. Write to Firestore `order_events` collection (doc ID = order_number)
7. Send customer email via SMTP
8. If delivery: send alert to GREG_EMAIL
9. Return routing decision JSON

**Firestore document:**
```python
{
    "order_number": order.order_number,
    "processed_at": datetime.utcnow().isoformat(),
    "coupon_code": order.coupon_code,
    "jurisdiction": coupon_data["jurisdiction"],
    "routing": routing,
    "customer_email": order.customer_email,
    "shipping_method": order.shipping_method,
    "total_qty": total_qty,
    "status": "success"
}
```

---

### 2. POST /api/generate-manifest

```python
@app.post("/api/generate-manifest")
async def generate_manifest(
    order: OrderPayload,
    x_api_key: str = Header(None, alias="X-API-Key")
):
    # Returns PDF bytes as Response(content=pdf_bytes, media_type="application/pdf")
```

Use `reportlab` (already in requirements.txt after this build).
Do NOT use LibreOffice or WeasyPrint.

**PDF content:**
- Header: "AGROMIN — DELIVERY MANIFEST"
- Order #, generated date/time
- Customer name, delivery address, phone
- Material description, quantity (cu yds)
- Coupon code, jurisdiction
- Hauler signature line + date line
- "OCWR staff signature upon material pickup" line

---

### 3. GET /api/delivery-schedule

```python
@app.get("/api/delivery-schedule")
async def delivery_schedule(
    x_api_key: str = Header(None, alias="X-API-Key")
):
```

Query Firestore `order_events` where `routing == "delivery"`.
Return all delivery orders processed in the last 7 days (for weekly schedule context).
Response format documented in `docs/API_INTEGRATION.md`.

---

## Email Dispatch — SMTP via M365 Relay

```python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
OFELIA_EMAIL = os.environ.get("OFELIA_EMAIL")
GREG_EMAIL = os.environ.get("GREG_EMAIL")

def send_email(to: str, subject: str, body: str, cc: list[str] = None):
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.attach(MIMEText(body, "plain"))
    recipients = [to] + (cc or [])
    with smtplib.SMTP("smtp.office365.com", 587) as s:
        s.ehlo()
        s.starttls()
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.sendmail(SMTP_USER, recipients, msg.as_string())
```

**Always CC `OFELIA_EMAIL` on customer emails.**

---

## Email Templates

Store as module-level string constants. No template engine needed.

### PICKUP_SELF_LOAD_TEMPLATE
```
Subject: Your Agromin Order #{order_number} — Pickup Instructions

Hello {customer_name},

Your order for {qty} cubic yards of {material} is ready for self-loading pickup.

PICKUP INSTRUCTIONS:
- Use the 5-gallon buckets provided at the site for measurement
- Bring this email confirmation AND proof of address within the county
  (valid photo ID or utility bill)
- Available during site hours: {yard_hours}

Location: {yard_name}
{yard_address}
{yard_phone}

Order #: {order_number}

Questions? Email sales@agromin.com or call (805) 485-9200.

Thank you,
Agromin
```

### PICKUP_STAFF_LOAD_TEMPLATE
```
Subject: Your Agromin Order #{order_number} — Pickup Instructions

Hello {customer_name},

Your order for {qty} cubic yards of {material} is ready for pickup.
OCWR staff will load your vehicle using heavy equipment.

PICKUP INSTRUCTIONS:
- YOU MUST BRING A TRUCK OR TRAILER — cars and minivans cannot be loaded
- Trailers must have solid sides/floor or customer must provide tarps
- Bring this email confirmation AND proof of address within the county
  (valid photo ID or utility bill)
- Available during site hours: {yard_hours}

Location: {yard_name}
{yard_address}
{yard_phone}

Order #: {order_number}

Questions? Email sales@agromin.com or call (805) 485-9200.

Thank you,
Agromin
```

### DELIVERY_TEMPLATE
```
Subject: Your Agromin Order #{order_number} — Delivery Confirmation

Hello {customer_name},

Thank you for your order. An Agromin representative will contact you within
1 business day to schedule your delivery.

Order #: {order_number}
Material: {qty} cubic yards of {material}
Delivery Address: {shipping_address}

Please note: delivery fees apply separately and will be collected at time of delivery.

Questions? Email sales@agromin.com or call (805) 485-9200.

Thank you,
Agromin
```

---

## Yard Location Config

Hardcode as a dict in `main.py`. Yard assignment: match shipping_method string
to the yard name (case-insensitive substring match).

```python
YARD_LOCATIONS = {
    "Frank R. Bowerman": {
        "address": "11002 Bee Canyon Access Rd, Irvine, CA 92602",
        "phone": "(949) 551-7100",
        "hours": "Mon–Sat 8am–4pm"
    },
    "Olinda Alpha": {
        "address": "1942 N. Valencia Ave, Brea, CA 92823",
        "phone": "(714) 993-7396",
        "hours": "Mon–Sat 7am–3pm"
    },
    "Prima Deshecha": {
        "address": "32250 Avenida La Pata, San Juan Capistrano, CA 92675",
        "phone": "(949) 728-3040",
        "hours": "Mon–Sat 8am–4pm"
    },
    "Aqua-Flo Ojai": {
        "address": "1940 E Ojai Ave, Ojai, CA 93023",
        "phone": "(805) 485-9200",
        "hours": "Mon–Fri 7am–4:30pm | Sat 7am–12pm"
    },
    "Agromin Oxnard": {
        "address": "6859 Arnold Rd, Oxnard, CA 93033",
        "phone": "(805) 485-9200",
        "hours": "Mon–Fri 7am–4:30pm | Sat 7am–12pm"
    }
}

def get_yard_for_order(shipping_method: str) -> dict:
    """Match shipping_method string to yard config. Returns default if no match."""
    sm_lower = shipping_method.lower()
    for yard_name, yard_info in YARD_LOCATIONS.items():
        if any(word.lower() in sm_lower for word in yard_name.split()):
            return {"name": yard_name, **yard_info}
    # Default fallback
    return {"name": "Agromin", "address": "Contact sales@agromin.com",
            "phone": "(805) 485-9200", "hours": "Mon–Fri 7am–4:30pm"}
```

---

## Firestore Setup

Add to `requirements.txt`:
```
google-cloud-firestore>=2.13.0
```

The Cloud Run service account already has GCS access. Add Firestore role:
GCP Console → IAM → service account → Add role: `Cloud Datastore User`

Initialize Firestore client at module level (after existing GCS client pattern):
```python
from google.cloud import firestore as firestore_client
_firestore_db = None

def get_firestore():
    global _firestore_db
    if _firestore_db is None:
        _firestore_db = firestore_client.Client()
    return _firestore_db
```

---

## Build Order

Build and test in this sequence. Do not proceed to next step until current step works.

1. Add `OrderPayload` and `LineItem` Pydantic models
2. Add `send_email()` SMTP function + email template constants
3. Add `POST /api/ingest-order` — routing logic only, return JSON (no email yet)
   - Test with hardcoded sample payload matching Order #108852 structure
4. Add Firestore write to `/api/ingest-order`
5. Add email dispatch to `/api/ingest-order` — test with rickwilson@agromin.com as recipient
6. Add Greg alert email for delivery orders
7. Add `POST /api/generate-manifest` with reportlab PDF
8. Add `GET /api/delivery-schedule` Firestore query
9. Deploy via existing GitHub Actions (push to main)
10. Test end-to-end: use "Resend Confirmation Email" button in CIMcloud Worker Portal
    on a known OCWR order to trigger the Power Automate flow

---

## Power Automate Flow (Rick configures separately)

```
Trigger: "When a new email arrives in a shared mailbox"
  Mailbox: sales@agromin.com
  Filter 1 — From: Sales@agromin.com
  Filter 2 — Subject starts with: Pending Approval for Order Number
  Filter 3 — Body contains: Coupon Code:

Parse: extract fields using HTML body parsing
  order_number  ← from subject line suffix OR Order Information section
  coupon_code   ← from "Coupon Code:" table cell
  customer_name ← from "Billing Information" section, first line
  customer_email← from email link in billing section
  customer_phone← from billing section
  billing_address ← billing address block (lines 3-5)
  shipping_address← shipping address block
  shipping_method ← "Shipping Method" table cell
  sku           ← line item SKU cell
  description   ← line item Description cell
  qty           ← line item Qty cell (numeric)
  unit_price    ← line item Unit Price cell (strip $)
  payment_method← "Payment Method" cell

HTTP POST:
  URL: https://coupon-validator-751008504644.us-west1.run.app/api/ingest-order
  Method: POST
  Headers: X-API-Key: [UPLOAD_API_KEY secret]
  Body: JSON assembled from parsed fields

On response:
  If routing == "delivery": add row to SharePoint OCWR-Agromin Deliveries.xlsx
```

---

## Key Constraints

- Keep all code in `main.py` — do not split into multiple files
- Do not modify existing endpoints — only add new ones
- Do not add new base system dependencies (GeoPandas/GDAL already makes image heavy)
- `reportlab` and `google-cloud-firestore` are safe — pure Python, no system deps
- All secrets via env vars — never hardcode credentials
- SMTP is the email mechanism — no Azure app registration, no Graph API
- Delivery orders are identified by `shipping_method` containing "Delivery" — not by order total
