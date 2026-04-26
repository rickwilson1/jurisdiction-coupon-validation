import requests
import geopandas as gpd
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import FastAPI, Query, Request, UploadFile, File, Header, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from shapely.geometry import Point
import os
import re
import csv
import logging
from functools import lru_cache
from datetime import datetime, date, timedelta
from io import StringIO, BytesIO
from google.cloud import storage as gcs_storage
from google.cloud import firestore as firestore_client
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib import colors

logger = logging.getLogger(__name__)

# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------
SHAPEFILE_PATH = os.path.join(os.path.dirname(__file__), "CDTFA_TaxDistricts.gpkg")
COUPONS_CSV_PATH = os.path.join(os.path.dirname(__file__), "coupons.csv")
COUPONS_XLSX_PATH = os.path.join(os.path.dirname(__file__), "coupons.xlsx")
GEOCODE_URL = "https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
ARCGIS_API_KEY = os.environ.get("ARCGIS_API_KEY")

# Cloud Storage bucket (fallback source for coupon files, accessed via service account)
COUPONS_GCS_BUCKET = os.environ.get("COUPONS_BUCKET", "agromin-coupon-data")

# Simple API key for upload endpoint (set this in Cloud Run environment)
UPLOAD_API_KEY = os.environ.get("UPLOAD_API_KEY", "change-this-secret-key")

app = FastAPI(title="Coupon Validation API", version="2.0.0")

# CORS configuration for browser-based clients (e.g., CIMcloud frontend)
_cors_origins = os.environ.get(
    "CORS_ALLOW_ORIGINS",
    "https://commercial.agromin.com,https://shop.agromin.com"
)
_cors_origin_regex = os.environ.get(
    "CORS_ALLOW_ORIGIN_REGEX",
    r"^https://([a-z0-9-]+\.)?agromin\.com$|^https://([a-z0-9-]+\.)?agromin\.mycimstaging\.com$|^https://([a-z0-9-]+\.)?agromin\.cimstaging\.com$"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _cors_origins.split(",") if origin.strip()],
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------
# DATA LOADING (cached at startup)
# ---------------------------------------------------
@lru_cache(maxsize=1)
def load_tax_districts():
    """Load CDTFA shapefile and convert CRS to WGS84."""
    gdf = gpd.read_file(SHAPEFILE_PATH)
    if gdf.crs is None:
        gdf.set_crs(epsg=3857, inplace=True)
    gdf = gdf.to_crs(epsg=4326)
    return gdf

# ---------------------------------------------------
# COUPON DATA LOADING
# ---------------------------------------------------
_coupon_cache = {}
_coupon_cache_time = None

def load_coupons(force_refresh: bool = False) -> dict:
    """
    Load coupon data from XLSX or CSV (local first, then Cloud Storage).
    Returns dict keyed by coupon code.
    Caches for 5 minutes to allow updates without redeploy.
    Tries xlsx first, then falls back to csv.
    """
    global _coupon_cache, _coupon_cache_time
    
    # Check cache (5 minute TTL)
    if not force_refresh and _coupon_cache and _coupon_cache_time:
        age = (datetime.now() - _coupon_cache_time).seconds
        if age < 300:  # 5 minutes
            return _coupon_cache
    
    df = None
    
    source = None

    # Prefer locally uploaded files so admin uploads take effect immediately.
    if os.path.exists(COUPONS_XLSX_PATH):
        try:
            df = pd.read_excel(COUPONS_XLSX_PATH, engine='openpyxl')
            source = f"local file {COUPONS_XLSX_PATH}"
        except Exception:
            pass
    
    if df is None and os.path.exists(COUPONS_CSV_PATH):
        try:
            df = pd.read_csv(COUPONS_CSV_PATH)
            source = f"local file {COUPONS_CSV_PATH}"
        except Exception:
            pass
    
    # Fall back to Cloud Storage (authenticated via service account)
    if df is None:
        try:
            client = gcs_storage.Client()
            bucket = client.bucket(COUPONS_GCS_BUCKET)
            blob = bucket.blob("coupons.xlsx")
            if blob.exists():
                df = pd.read_excel(BytesIO(blob.download_as_bytes()), engine='openpyxl')
                source = f"GCS gs://{COUPONS_GCS_BUCKET}/coupons.xlsx"
        except Exception:
            pass
    
    if df is None:
        try:
            client = gcs_storage.Client()
            bucket = client.bucket(COUPONS_GCS_BUCKET)
            blob = bucket.blob("coupons.csv")
            if blob.exists():
                df = pd.read_csv(StringIO(blob.download_as_string().decode("utf-8")))
                source = f"GCS gs://{COUPONS_GCS_BUCKET}/coupons.csv"
        except Exception:
            pass
    
    if df is None:
        logger.warning("No coupon data found from any source")
        return {}
    
    # Parse DataFrame to coupons dict
    coupons = {}
    for _, row in df.iterrows():
        code = str(row.get('Coupon', '')).strip().upper()
        if code and code != 'NAN':
            coupons[code] = {
                'code': code,
                'status': str(row.get('Program Status', '')).strip(),
                'jurisdiction': str(row.get('Jurisdiction', '')).strip(),
                'start_date': parse_date(row.get('Start Date')),
                'end_date': parse_date(row.get('End Date')),
            }
    
    _coupon_cache = coupons
    _coupon_cache_time = datetime.now()
    logger.info("Loaded %d coupons from %s", len(coupons), source)
    return coupons


def parse_date(date_val) -> date | None:
    """Parse date from string (M/D/YY) or pandas Timestamp."""
    if date_val is None or (isinstance(date_val, float) and pd.isna(date_val)):
        return None
    
    # Handle pandas Timestamp
    if isinstance(date_val, pd.Timestamp):
        return date_val.date()
    
    # Handle datetime
    if isinstance(date_val, datetime):
        return date_val.date()
    
    # Handle date
    if isinstance(date_val, date):
        return date_val
    
    # Handle string
    try:
        date_str = str(date_val).strip()
        if not date_str or date_str.lower() == 'nan':
            return None
        # Handle M/D/YY format
        return datetime.strptime(date_str, "%m/%d/%y").date()
    except ValueError:
        try:
            # Try M/D/YYYY format
            return datetime.strptime(date_str, "%m/%d/%Y").date()
        except ValueError:
            return None


def validate_coupon_dates(coupon: dict) -> tuple[bool, str]:
    """Check if coupon is within valid date range."""
    today = date.today()
    start = coupon.get('start_date')
    end = coupon.get('end_date')
    
    if start and today < start:
        return False, f"Coupon not yet active (starts {start.strftime('%m/%d/%Y')})"
    
    if end and today > end:
        return False, f"Coupon expired (ended {end.strftime('%m/%d/%Y')})"
    
    return True, "Valid"


# Pre-load on startup
@app.on_event("startup")
async def startup_event():
    load_tax_districts()
    load_coupons()

# ---------------------------------------------------
# HELPERS
# ---------------------------------------------------
def geocode_address(address: str):
    """Use ArcGIS geocoder to get lat/lon and matched address."""
    params = {"f": "json", "singleLine": address, "outFields": "Match_addr", "maxLocations": 1}
    if ARCGIS_API_KEY:
        params["token"] = ARCGIS_API_KEY
    r = requests.get(GEOCODE_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data.get("candidates"):
        return None, None, None
    cand = data["candidates"][0]
    loc = cand["location"]
    match_addr = cand["address"]
    return loc["y"], loc["x"], match_addr


def find_tax_district(lat: float, lon: float, gdf: gpd.GeoDataFrame):
    """Find which CDTFA tax district polygon contains the given point."""
    point = Point(lon, lat)
    match = gdf[gdf.contains(point)]
    if match.empty:
        return None
    row = match.iloc[0]
    return {
        "jurisdiction": row.get("JURIS_NAME"),
        "county": row.get("County_name") or row.get("County_nam"),
        "city": row.get("City_name") or row.get("City_Name_Proper") or row.get("City_Name_"),
        "rate": row.get("RATE"),
    }


def normalize_jurisdiction(name: str) -> str:
    """
    Normalize jurisdiction name by removing prefixes/suffixes.
    'City of Sacramento' -> 'sacramento'
    'Sacramento, City of' -> 'sacramento'
    'Sacramento County' -> 'sacramento'
    """
    if not name:
        return ""
    
    normalized = name.lower().strip()
    
    # Remove common patterns
    patterns = [
        r'\bcity of\b',
        r',\s*city of\b',
        r'\bcity\b',
        r'\bcounty of\b',
        r',\s*county of\b',
        r'\bcounty\b',
    ]
    
    for pattern in patterns:
        normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)
    
    return normalized.strip()


def is_city_claim(jurisdiction: str) -> bool:
    """Check if the claimed jurisdiction is a city (contains 'city' anywhere)."""
    return 'city' in jurisdiction.lower()


def is_unincorporated_area(city_name: str | None) -> bool:
    """
    Return True when the address is in an unincorporated area.
    Empty/missing city is treated as unincorporated.
    """
    if city_name is None:
        return True

    normalized_city = str(city_name).strip().lower()
    if not normalized_city:
        return True

    return "unincorporated" in normalized_city


def jurisdictions_match(claimed: str, actual_city: str, actual_county: str) -> tuple:
    """
    Compare claimed jurisdiction against actual city/county.
    Returns (match: bool, actual_jurisdiction: str)
    """
    normalized_claim = normalize_jurisdiction(claimed)
    
    if is_city_claim(claimed):
        # Must match city
        if actual_city:
            normalized_actual = normalize_jurisdiction(actual_city)
            return normalized_claim == normalized_actual, actual_city
        return False, actual_county or "Unincorporated area"
    else:
        # County coupons are valid only in unincorporated county areas.
        if actual_county:
            normalized_actual = normalize_jurisdiction(actual_county)
            county_matches = normalized_claim == normalized_actual
            if not county_matches:
                return False, actual_county

            if not is_unincorporated_area(actual_city):
                return False, actual_city

            return True, actual_county
        return False, "Unknown"


# ---------------------------------------------------
# API ENDPOINT
# ---------------------------------------------------
@app.get("/api/validate")
async def validate_jurisdiction(
    address: str = Query(..., description="Full California address"),
    jurisdiction: str = Query(..., description="Claimed jurisdiction (include 'City' if city)")
):
    """
    Validate if an address is within the claimed jurisdiction.
    
    Returns:
    - status: "accepted", "denied", or "error"
    - claimed_jurisdiction: what was submitted
    - actual_jurisdiction: what was found
    - matched_address: the geocoded address
    """
    try:
        # Geocode the address
        lat, lon, matched_address = geocode_address(address)
        
        if lat is None or lon is None:
            return {
                "status": "error",
                "message": "Address could not be geocoded"
            }
        
        # Find tax district
        gdf = load_tax_districts()
        district = find_tax_district(lat, lon, gdf)
        
        if not district:
            return {
                "status": "error",
                "message": "Address not found in California tax district data"
            }
        
        # Compare jurisdictions
        match, actual = jurisdictions_match(
            jurisdiction,
            district.get("city"),
            district.get("county")
        )
        
        return {
            "status": "accepted" if match else "denied",
            "claimed_jurisdiction": jurisdiction,
            "actual_jurisdiction": actual,
            "matched_address": matched_address
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# ---------------------------------------------------
# COUPON VALIDATION ENDPOINT
# ---------------------------------------------------
@app.get("/api/validate-coupon")
async def validate_coupon(
    address: str = Query(..., description="Full California address"),
    coupon: str = Query(..., description="Coupon code")
):
    """
    Validate if a coupon is valid for the given address.
    
    Checks:
    1. Coupon exists
    2. Coupon is Active
    3. Current date is within Start/End date range
    4. Address is within the coupon's jurisdiction
    
    Returns:
    - status: "accepted", "denied", or "error"
    - coupon: the coupon code
    - jurisdiction: the coupon's jurisdiction
    - reason: explanation of the result
    """
    try:
        # Normalize coupon code
        coupon_code = coupon.strip().upper()
        
        # Load coupon data
        coupons = load_coupons()
        
        # Check if coupon exists
        if coupon_code not in coupons:
            return {
                "status": "denied",
                "coupon": coupon_code,
                "reason": "Coupon code not found"
            }
        
        coupon_data = coupons[coupon_code]
        
        # Check if coupon is active
        if coupon_data['status'].lower() != 'active':
            return {
                "status": "denied",
                "coupon": coupon_code,
                "jurisdiction": coupon_data['jurisdiction'],
                "reason": f"Coupon is {coupon_data['status']}"
            }
        
        # Check date validity
        date_valid, date_reason = validate_coupon_dates(coupon_data)
        if not date_valid:
            return {
                "status": "denied",
                "coupon": coupon_code,
                "jurisdiction": coupon_data['jurisdiction'],
                "reason": date_reason
            }
        
        # Geocode the address
        lat, lon, matched_address = geocode_address(address)
        
        if lat is None or lon is None:
            return {
                "status": "error",
                "coupon": coupon_code,
                "reason": "Address could not be geocoded"
            }
        
        # Find tax district
        gdf = load_tax_districts()
        district = find_tax_district(lat, lon, gdf)
        
        if not district:
            return {
                "status": "error",
                "coupon": coupon_code,
                "reason": "Address not found in California tax district data"
            }
        
        # Compare jurisdictions
        claimed_jurisdiction = coupon_data['jurisdiction']
        match, actual = jurisdictions_match(
            claimed_jurisdiction,
            district.get("city"),
            district.get("county")
        )
        
        if match:
            return {
                "status": "accepted",
                "coupon": coupon_code,
                "jurisdiction": claimed_jurisdiction,
                "matched_address": matched_address,
                "reason": "Address is within coupon jurisdiction"
            }
        else:
            return {
                "status": "denied",
                "coupon": coupon_code,
                "jurisdiction": claimed_jurisdiction,
                "actual_jurisdiction": actual,
                "matched_address": matched_address,
                "reason": f"Address is in {actual}, not {claimed_jurisdiction}"
            }
        
    except Exception as e:
        return {
            "status": "error",
            "coupon": coupon,
            "reason": str(e)
        }


# ---------------------------------------------------
# WEB FORM (for manual lookups)
# ---------------------------------------------------
HTML_FORM = """
<!DOCTYPE html>
<html>
<head>
    <title>Coupon Validation</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            margin-bottom: 5px;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: 600;
            color: #333;
        }
        input[type="text"] {
            width: 100%;
            padding: 12px;
            margin-bottom: 20px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
            box-sizing: border-box;
        }
        button {
            background: #4CAF50;
            color: white;
            padding: 12px 30px;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            cursor: pointer;
            width: 100%;
        }
        button:hover {
            background: #45a049;
        }
        .result {
            margin-top: 20px;
            padding: 20px;
            border-radius: 5px;
        }
        .accepted {
            background: #d4edda;
            border: 1px solid #c3e6cb;
            color: #155724;
        }
        .denied {
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
        }
        .error {
            background: #fff3cd;
            border: 1px solid #ffeeba;
            color: #856404;
        }
        .result-item {
            margin: 8px 0;
        }
        .result-label {
            font-weight: 600;
        }
        .info {
            margin-top: 30px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 5px;
            font-size: 14px;
        }
        .info h3 {
            margin-top: 0;
            color: #666;
        }
        .info code {
            background: #e9ecef;
            padding: 2px 6px;
            border-radius: 3px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Coupon Validation</h1>
        <p class="subtitle">Verify coupon eligibility for address</p>
        
        <form id="validateForm">
            <label for="coupon">Coupon Code</label>
            <input type="text" id="coupon" name="coupon" placeholder="CITYVCOM26" required>
            
            <label for="address">Address</label>
            <input type="text" id="address" name="address" placeholder="123 Main St, Ventura, CA 93001" required>
            
            <button type="submit">Validate Coupon</button>
        </form>
        
        <div id="result"></div>
        
        <div class="info">
            <h3>What this checks:</h3>
            <ul>
                <li>Coupon code exists</li>
                <li>Coupon is currently active</li>
                <li>Today's date is within the valid period</li>
                <li>Address is within the coupon's jurisdiction</li>
            </ul>
        </div>
    </div>
    
    <script>
        document.getElementById('validateForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const coupon = document.getElementById('coupon').value;
            const address = document.getElementById('address').value;
            
            const resultDiv = document.getElementById('result');
            resultDiv.innerHTML = '<p>Validating...</p>';
            
            try {
                const params = new URLSearchParams({ address, coupon });
                const response = await fetch(`/api/validate-coupon?${params}`);
                const data = await response.json();
                
                let statusClass = data.status;
                let html = `<div class="result ${statusClass}">`;
                html += `<div class="result-item"><span class="result-label">Status:</span> ${data.status.toUpperCase()}</div>`;
                html += `<div class="result-item"><span class="result-label">Coupon:</span> ${data.coupon}</div>`;
                
                if (data.jurisdiction) {
                    html += `<div class="result-item"><span class="result-label">Jurisdiction:</span> ${data.jurisdiction}</div>`;
                }
                if (data.actual_jurisdiction) {
                    html += `<div class="result-item"><span class="result-label">Address Location:</span> ${data.actual_jurisdiction}</div>`;
                }
                if (data.matched_address) {
                    html += `<div class="result-item"><span class="result-label">Matched Address:</span> ${data.matched_address}</div>`;
                }
                if (data.reason) {
                    html += `<div class="result-item"><span class="result-label">Reason:</span> ${data.reason}</div>`;
                }
                
                html += '</div>';
                resultDiv.innerHTML = html;
                
            } catch (error) {
                resultDiv.innerHTML = `<div class="result error">
                    <div class="result-item"><span class="result-label">Error:</span> ${error.message}</div>
                </div>`;
            }
        });
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the web form for manual lookups."""
    return HTML_FORM


# ---------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "healthy"}


# ---------------------------------------------------
# GCS SYNC HELPER
# ---------------------------------------------------
def _sync_to_gcs(content: bytes, blob_name: str):
    """Best-effort upload to GCS so new container instances get the latest data."""
    try:
        client = gcs_storage.Client()
        bucket = client.bucket(COUPONS_GCS_BUCKET)
        blob = bucket.blob(blob_name)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if blob_name.endswith(".xlsx") else "text/csv"
        blob.cache_control = "no-cache, max-age=0"
        blob.upload_from_string(content, content_type=content_type)
        logger.info("Synced %s to GCS bucket %s", blob_name, COUPONS_GCS_BUCKET)
    except Exception as e:
        logger.warning("GCS sync failed (non-fatal): %s", e)


# ---------------------------------------------------
# COUPON FILE UPLOAD ENDPOINT (for Power Automate)
# ---------------------------------------------------
@app.post("/api/upload-coupons")
async def upload_coupons(
    file: UploadFile = File(None),
    x_api_key: str = Header(None, alias="X-API-Key"),
    request: Request = None
):
    """
    Upload a new coupon file (xlsx or csv) directly to the API.
    Saves locally, syncs to GCS, and refreshes cache.
    Requires X-API-Key header for authentication.
    Used by Power Automate to sync from SharePoint.
    
    Accepts both multipart form uploads and raw binary data.
    """
    # Verify API key
    if x_api_key != UPLOAD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    try:
        # Get file content - either from form upload or raw body
        if file and file.filename:
            content = await file.read()
            filename = file.filename.lower()
        else:
            # Raw binary upload from Power Automate
            content = await request.body()
            # Default to xlsx since that's what SharePoint sends
            filename = "coupons.xlsx"
        
        if not content:
            raise HTTPException(status_code=400, detail="No file content received")
        
        # Determine file type from content (Excel files start with PK)
        is_excel = content[:2] == b'PK'
        if is_excel:
            save_path = COUPONS_XLSX_PATH
            gcs_blob_name = "coupons.xlsx"
        else:
            save_path = COUPONS_CSV_PATH
            gcs_blob_name = "coupons.csv"
            
        with open(save_path, 'wb') as f:
            f.write(content)
        
        _sync_to_gcs(content, gcs_blob_name)
        
        # Clear the coupon cache to force reload
        global _coupon_cache, _coupon_cache_time
        _coupon_cache = {}
        _coupon_cache_time = None
        
        # Reload coupons to verify file is valid
        coupons = load_coupons(force_refresh=True)
        
        return {
            "status": "success",
            "message": f"Uploaded and processed coupon file",
            "coupons_loaded": len(coupons)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------
# DISPATCH SERVICE — CONFIGURATION
# ---------------------------------------------------
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
OFELIA_EMAIL = os.environ.get("OFELIA_EMAIL")
GREG_EMAIL = os.environ.get("GREG_EMAIL", "greg@agromin.com")
BRIAN_EMAIL = os.environ.get("BRIAN_EMAIL", "brian@agromin.com")
KENDALL_EMAIL = os.environ.get("KENDALL_EMAIL", "kendall@agromin.com")
CHRIS_EMAIL = os.environ.get("CHRIS_EMAIL", "chris@agromin.com")
ROSA_EMAIL = os.environ.get("ROSA_EMAIL", "rosa@agromin.com")


# ---------------------------------------------------
# YARD LOCATIONS
# Matching uses case-insensitive substring search on match_keys.
# More specific keys should be listed before generic ones within each entry.
# ---------------------------------------------------
YARD_LOCATIONS = {
    "Frank R. Bowerman": {
        "match_keys": ["bowerman"],
        "address": "11002 Bee Canyon Access Rd, Irvine, CA 92602",
        "phone": "(949) 551-7100",
        "hours": "Mon–Sat 8am–4pm",
        "qr_url": "https://forms.office.com/r/Ywy7m8jcwv",
        "qr_deployed": False,
    },
    "Prima Deshecha": {
        "match_keys": ["deshecha"],
        "address": "32250 Avenida La Pata, San Juan Capistrano, CA 92675",
        "phone": "(949) 728-3040",
        "hours": "Mon–Sat 8am–4pm",
        "qr_url": "https://forms.office.com/r/2CsTHP7TjB",
        "qr_deployed": False,
    },
    "Olinda Alpha": {
        "match_keys": ["olinda"],
        "address": "1942 N. Valencia Ave, Brea, CA 92823",
        "phone": "(714) 993-7396",
        "hours": "Mon–Sat 7am–3pm",
        "qr_url": "https://forms.office.com/r/9LWPGvf52e",
        "qr_deployed": False,
    },
    "Aqua-Flo Ojai": {
        "match_keys": ["ojai"],
        "address": "1940 E Ojai Ave, Ojai, CA 93023",
        "phone": "(805) 485-9200",
        "hours": "Mon–Fri 7am–4:30pm | Sat 7am–12pm",
        "qr_url": None,
        "qr_deployed": False,
    },
    "Aqua-Flo Ventura": {
        "match_keys": ["aqua-flo ventura", "portola"],
        "address": "2471 Portola Rd #300, Ventura, CA 93003",
        "phone": "(805) 485-9200",
        "hours": "Mon–Fri 7am–4:30pm | Sat 7am–12pm",
        "qr_url": None,
        "qr_deployed": False,
    },
    "Agromin Kinetic": {
        "match_keys": ["kinetic"],
        "address": "201 Kinetic Drive, Oxnard, CA 93030",
        "phone": "(805) 485-9200",
        "hours": "Mon–Fri 7am–4:30pm | Sat 7am–12pm",
        "qr_url": None,
        "qr_deployed": False,
    },
}


def get_yard_for_order(shipping_method: str) -> dict:
    """Match shipping_method to yard config via case-insensitive substring on match_keys."""
    sm_lower = shipping_method.lower()
    for yard_name, yard_info in YARD_LOCATIONS.items():
        for key in yard_info.get("match_keys", []):
            if key.lower() in sm_lower:
                return {"name": yard_name, **{k: v for k, v in yard_info.items() if k != "match_keys"}}
    return {
        "name": "Agromin",
        "address": "Contact sales@agromin.com",
        "phone": "(805) 485-9200",
        "hours": "Mon–Fri 7am–4:30pm",
        "qr_url": None,
        "qr_deployed": False,
    }


def get_delivery_coordinator_emails(jurisdiction: str) -> list:
    """Return the right coordinator email list based on jurisdiction."""
    j = jurisdiction.lower()
    if "sacramento" in j:
        return [e for e in [ROSA_EMAIL] if e]
    if any(k in j for k in ["ventura", "ojai", "oxnard", "camarillo", "fillmore"]):
        return [e for e in [CHRIS_EMAIL] if e]
    return [e for e in [GREG_EMAIL, BRIAN_EMAIL, KENDALL_EMAIL] if e]


def format_qty(qty: float) -> str:
    return str(int(qty)) if qty == int(qty) else str(qty)


# ---------------------------------------------------
# FIRESTORE CLIENT
# ---------------------------------------------------
_firestore_db = None


def get_firestore():
    global _firestore_db
    if _firestore_db is None:
        _firestore_db = firestore_client.Client()
    return _firestore_db


# ---------------------------------------------------
# EMAIL
# ---------------------------------------------------
def send_email(to: str, subject: str, body: str, cc: list = None):
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured — email skipped (to=%s)", to)
        return
    try:
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
        logger.info("Email sent to %s subject: %s", to, subject)
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to, e)


SB1383_PARAGRAPH = (
    "IMPORTANT — When you arrive: Look for the QR code sign near the material pickup area. "
    "Scanning it takes less than a minute and helps OCWR stay in compliance with "
    "California's SB 1383 organics diversion law. Thank you for participating."
)

PICKUP_SELF_LOAD_TEMPLATE = """\
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

{sb1383_note}
Questions? Email sales@agromin.com or call (805) 485-9200.

Thank you,
Agromin"""

PICKUP_STAFF_LOAD_TEMPLATE = """\
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

{sb1383_note}
Questions? Email sales@agromin.com or call (805) 485-9200.

Thank you,
Agromin"""

DELIVERY_TEMPLATE = """\
Hello {customer_name},

Thank you for your order. An Agromin representative will contact you within
1 business day to schedule your delivery.

Order #: {order_number}
Material: {qty} cubic yards of {material}
Delivery Address: {shipping_address}

Please note: delivery fees apply separately and will be collected at time of delivery.

Questions? Email sales@agromin.com or call (805) 485-9200.

Thank you,
Agromin"""

DELIVERY_ALERT_TEMPLATE = """\
New delivery order received — action required.

Order #:          {order_number}
Date:             {order_date}
Customer:         {customer_name}
Phone:            {customer_phone}
Delivery Address: {shipping_address}
Material:         {qty} cubic yards of {material}
Coupon Code:      {coupon_code}
Jurisdiction:     {jurisdiction}

Please contact the customer within 1 business day to schedule delivery."""


# ---------------------------------------------------
# PYDANTIC MODELS
# ---------------------------------------------------
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


# ---------------------------------------------------
# POST /api/ingest-order
# ---------------------------------------------------
@app.post("/api/ingest-order")
async def ingest_order(
    order: OrderPayload,
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    if x_api_key != UPLOAD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    coupon_code = order.coupon_code.strip().upper()
    coupons = load_coupons()

    if coupon_code not in coupons or coupons[coupon_code].get("status", "").lower() != "active":
        return {"status": "ignored", "reason": "not a program order"}

    coupon_data = coupons[coupon_code]
    jurisdiction = coupon_data.get("jurisdiction", "")

    total_qty = sum(item.qty for item in order.line_items)
    material = order.line_items[0].description if order.line_items else "material"
    qty_str = format_qty(total_qty)

    if "delivery" in order.shipping_method.lower():
        routing = "delivery"
    else:
        routing = "pickup_self_load" if total_qty < 5 else "pickup_staff_load"

    try:
        db = get_firestore()
        db.collection("order_events").document(order.order_number).set({
            "order_number": order.order_number,
            "processed_at": datetime.utcnow(),
            "coupon_code": coupon_code,
            "jurisdiction": jurisdiction,
            "routing": routing,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "shipping_method": order.shipping_method,
            "shipping_address": order.shipping_address,
            "total_qty": total_qty,
            "material": material,
            "order_date": order.order_date,
            "customer_phone": order.customer_phone,
            "status": "success",
        })
    except Exception as e:
        logger.error("Firestore write failed for order %s: %s", order.order_number, e)

    cc_list = [OFELIA_EMAIL] if OFELIA_EMAIL else []

    if routing == "delivery":
        body = DELIVERY_TEMPLATE.format(
            order_number=order.order_number,
            customer_name=order.customer_name,
            qty=qty_str,
            material=material,
            shipping_address=order.shipping_address,
        )
        subject = f"Your Agromin Order #{order.order_number} — Delivery Confirmation"
        send_email(order.customer_email, subject, body, cc=cc_list)

        alert_body = DELIVERY_ALERT_TEMPLATE.format(
            order_number=order.order_number,
            order_date=order.order_date,
            customer_name=order.customer_name,
            customer_phone=order.customer_phone,
            shipping_address=order.shipping_address,
            qty=qty_str,
            material=material,
            coupon_code=coupon_code,
            jurisdiction=jurisdiction,
        )
        alert_subject = f"New Delivery Order #{order.order_number} — Action Required"
        for coordinator in get_delivery_coordinator_emails(jurisdiction):
            send_email(coordinator, alert_subject, alert_body)
    else:
        yard = get_yard_for_order(order.shipping_method)
        sb1383 = SB1383_PARAGRAPH + "\n" if yard.get("qr_url") else ""
        template = PICKUP_SELF_LOAD_TEMPLATE if routing == "pickup_self_load" else PICKUP_STAFF_LOAD_TEMPLATE
        body = template.format(
            order_number=order.order_number,
            customer_name=order.customer_name,
            qty=qty_str,
            material=material,
            yard_name=yard["name"],
            yard_address=yard["address"],
            yard_phone=yard["phone"],
            yard_hours=yard["hours"],
            sb1383_note=sb1383,
        )
        subject = f"Your Agromin Order #{order.order_number} — Pickup Instructions"
        send_email(order.customer_email, subject, body, cc=cc_list)

    return {
        "status": "processed",
        "order_number": order.order_number,
        "routing": routing,
        "total_qty": total_qty,
        "jurisdiction": jurisdiction,
    }


# ---------------------------------------------------
# POST /api/generate-manifest
# ---------------------------------------------------
@app.post("/api/generate-manifest")
async def generate_manifest(
    order: OrderPayload,
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    if x_api_key != UPLOAD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    coupons = load_coupons()
    coupon_code = order.coupon_code.strip().upper()
    jurisdiction = coupons.get(coupon_code, {}).get("jurisdiction", "")
    total_qty = sum(item.qty for item in order.line_items)
    material = order.line_items[0].description if order.line_items else "material"

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
    )
    styles = getSampleStyleSheet()
    story = []

    header_style = styles["Heading1"]
    label_style = styles["Normal"]
    value_style = styles["Normal"]

    story.append(Paragraph("AGROMIN — DELIVERY MANIFEST", header_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black))
    story.append(Spacer(1, 0.15 * inch))

    generated_at = datetime.utcnow().strftime("%B %d, %Y %I:%M %p UTC")
    info_data = [
        ["Order #:", order.order_number, "Generated:", generated_at],
    ]
    info_table = Table(info_data, colWidths=[1.1 * inch, 2.5 * inch, 1.1 * inch, 2.3 * inch])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("<b>CUSTOMER INFORMATION</b>", label_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.1 * inch))

    customer_data = [
        ["Name:", order.customer_name],
        ["Phone:", order.customer_phone or "—"],
        ["Delivery Address:", order.shipping_address],
    ]
    customer_table = Table(customer_data, colWidths=[1.5 * inch, 5.5 * inch])
    customer_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(customer_table)
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("<b>ORDER DETAILS</b>", label_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.1 * inch))

    order_data = [
        ["Material:", material],
        ["Quantity:", f"{format_qty(total_qty)} cubic yards"],
        ["Coupon Code:", coupon_code],
        ["Jurisdiction:", jurisdiction],
    ]
    order_table = Table(order_data, colWidths=[1.5 * inch, 5.5 * inch])
    order_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(order_table)
    story.append(Spacer(1, 0.5 * inch))

    story.append(Paragraph("<b>SIGNATURES</b>", label_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.3 * inch))

    sig_data = [
        ["Hauler Signature:", "_" * 40, "Date:", "_" * 15],
        ["", "", "", ""],
        ["OCWR Staff Signature\nupon material pickup:", "_" * 40, "Date:", "_" * 15],
    ]
    sig_table = Table(sig_data, colWidths=[1.8 * inch, 2.8 * inch, 0.6 * inch, 1.8 * inch])
    sig_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    story.append(sig_table)

    doc.build(story)
    pdf_bytes = buf.getvalue()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=manifest_{order.order_number}.pdf"},
    )


# ---------------------------------------------------
# GET /api/delivery-schedule
# ---------------------------------------------------
@app.get("/api/delivery-schedule")
async def delivery_schedule(
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    if x_api_key != UPLOAD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    try:
        db = get_firestore()
        cutoff = datetime.utcnow() - timedelta(days=7)
        docs = db.collection("order_events").where("routing", "==", "delivery").stream()
        orders = []
        for doc in docs:
            data = doc.to_dict()
            processed_at = data.get("processed_at")
            if processed_at and hasattr(processed_at, "replace"):
                if processed_at.replace(tzinfo=None) >= cutoff:
                    orders.append({
                        "order_number": data.get("order_number"),
                        "order_date": data.get("order_date"),
                        "processed_at": processed_at.isoformat() if hasattr(processed_at, "isoformat") else str(processed_at),
                        "customer_name": data.get("customer_name"),
                        "customer_phone": data.get("customer_phone"),
                        "shipping_address": data.get("shipping_address"),
                        "material": data.get("material"),
                        "total_qty": data.get("total_qty"),
                        "jurisdiction": data.get("jurisdiction"),
                        "coupon_code": data.get("coupon_code"),
                    })
        orders.sort(key=lambda x: x.get("processed_at", ""), reverse=True)
        return {"status": "ok", "count": len(orders), "orders": orders}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
