# Coupon Validator API

FastAPI service for validating coupon eligibility by California address and jurisdiction.

## What It Does

- Geocodes an input address.
- Maps the address to CDTFA tax district data.
- Validates coupon existence, status, and date range.
- Applies jurisdiction rules:
  - City coupons require a city match.
  - County coupons are valid only for unincorporated county areas.

## Main Endpoints

- `GET /api/validate-coupon`
  - Validate coupon eligibility for an address.
- `GET /api/validate`
  - Validate address against a claimed jurisdiction.
- `POST /api/upload-coupons`
  - Admin endpoint for coupon file upload (requires `X-API-Key`).
- `GET /health`
  - Health check.
- `GET /`
  - Manual validation web form.

## Deployment

- Hosted on Google Cloud Run.
- Primary URL:
  - `https://coupon-validator-751008504644.us-west1.run.app`

## Documentation

- Integration guide:
  - `docs/API_INTEGRATION.md`
