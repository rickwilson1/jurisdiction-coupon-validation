import requests
import geopandas as gpd
import pandas as pd
from fastapi import FastAPI, Query, Request, UploadFile, File, Header, HTTPException
from fastapi.responses import HTMLResponse
from shapely.geometry import Point
import os
import re
import csv
from functools import lru_cache
from datetime import datetime, date
from io import StringIO, BytesIO

# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------
SHAPEFILE_PATH = os.path.join(os.path.dirname(__file__), "CDTFA_TaxDistricts.gpkg")
COUPONS_CSV_PATH = os.path.join(os.path.dirname(__file__), "coupons.csv")
COUPONS_XLSX_PATH = os.path.join(os.path.dirname(__file__), "coupons.xlsx")
GEOCODE_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"

# Cloud Storage URLs (for production - allows updating coupons without redeploy)
# API checks xlsx first, then csv
COUPONS_GCS_BUCKET = os.environ.get("COUPONS_BUCKET", "agromin-coupon-data")
COUPONS_GCS_XLSX_URL = os.environ.get("COUPONS_XLSX_URL", f"https://storage.googleapis.com/{COUPONS_GCS_BUCKET}/coupons.xlsx")
COUPONS_GCS_CSV_URL = os.environ.get("COUPONS_CSV_URL", f"https://storage.googleapis.com/{COUPONS_GCS_BUCKET}/coupons.csv")

# Simple API key for upload endpoint (set this in Cloud Run environment)
UPLOAD_API_KEY = os.environ.get("UPLOAD_API_KEY", "change-this-secret-key")

app = FastAPI(title="Coupon Validation API", version="2.0.0")

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
    Load coupon data from XLSX or CSV (Cloud Storage or local).
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
    
    # Try Cloud Storage XLSX first
    if COUPONS_GCS_XLSX_URL:
        try:
            r = requests.get(COUPONS_GCS_XLSX_URL, timeout=10)
            r.raise_for_status()
            df = pd.read_excel(BytesIO(r.content), engine='openpyxl')
        except Exception:
            pass  # Try CSV next
    
    # Try Cloud Storage CSV
    if df is None and COUPONS_GCS_CSV_URL:
        try:
            r = requests.get(COUPONS_GCS_CSV_URL, timeout=10)
            r.raise_for_status()
            df = pd.read_csv(StringIO(r.text))
        except Exception:
            pass  # Fall back to local files
    
    # Fall back to local XLSX
    if df is None and os.path.exists(COUPONS_XLSX_PATH):
        try:
            df = pd.read_excel(COUPONS_XLSX_PATH, engine='openpyxl')
        except Exception:
            pass
    
    # Fall back to local CSV
    if df is None and os.path.exists(COUPONS_CSV_PATH):
        try:
            df = pd.read_csv(COUPONS_CSV_PATH)
        except Exception:
            pass
    
    if df is None:
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
        "county": row.get("County_nam"),
        "city": row.get("City_name") or row.get("City_Name_"),
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
        # Must match county
        if actual_county:
            normalized_actual = normalize_jurisdiction(actual_county)
            return normalized_claim == normalized_actual, actual_county
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
    Saves locally and refreshes cache.
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
        if content[:2] == b'PK':
            save_path = COUPONS_XLSX_PATH
        else:
            save_path = COUPONS_CSV_PATH
            
        with open(save_path, 'wb') as f:
            f.write(content)
        
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
