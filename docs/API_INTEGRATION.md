# Coupon Validation API Integration Guide

For CIMcloud and storefront integrations.

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
