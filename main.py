import requests
import geopandas as gpd
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from shapely.geometry import Point
import os
import re
from functools import lru_cache

# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------
SHAPEFILE_PATH = os.path.join(os.path.dirname(__file__), "CDTFA_TaxDistricts.gpkg")
GEOCODE_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
LOGO_PATH = os.path.join(os.path.dirname(__file__), "agromin_logo.png")

app = FastAPI(title="Jurisdiction Validation API", version="1.0.0")

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

# Pre-load on startup
@app.on_event("startup")
async def startup_event():
    load_tax_districts()

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
# WEB FORM (for manual lookups)
# ---------------------------------------------------
HTML_FORM = """
<!DOCTYPE html>
<html>
<head>
    <title>Jurisdiction Validation</title>
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
        .examples {
            margin-top: 30px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 5px;
            font-size: 14px;
        }
        .examples h3 {
            margin-top: 0;
            color: #666;
        }
        .examples code {
            background: #e9ecef;
            padding: 2px 6px;
            border-radius: 3px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Jurisdiction Validation</h1>
        <p class="subtitle">Coupon Code Qualification Check</p>
        
        <form id="validateForm">
            <label for="address">Address</label>
            <input type="text" id="address" name="address" placeholder="123 Main St, Sacramento, CA 95814" required>
            
            <label for="jurisdiction">Claimed Jurisdiction</label>
            <input type="text" id="jurisdiction" name="jurisdiction" placeholder="City of Sacramento" required>
            
            <button type="submit">Validate</button>
        </form>
        
        <div id="result"></div>
        
        <div class="examples">
            <h3>Jurisdiction Format Examples</h3>
            <p><strong>Cities:</strong> <code>City of Sacramento</code>, <code>Sacramento, City of</code></p>
            <p><strong>Counties:</strong> <code>Sacramento County</code>, <code>County of Sacramento</code></p>
        </div>
    </div>
    
    <script>
        document.getElementById('validateForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const address = document.getElementById('address').value;
            const jurisdiction = document.getElementById('jurisdiction').value;
            
            const resultDiv = document.getElementById('result');
            resultDiv.innerHTML = '<p>Validating...</p>';
            
            try {
                const params = new URLSearchParams({ address, jurisdiction });
                const response = await fetch(`/api/validate?${params}`);
                const data = await response.json();
                
                let statusClass = data.status;
                let html = `<div class="result ${statusClass}">`;
                html += `<div class="result-item"><span class="result-label">Status:</span> ${data.status.toUpperCase()}</div>`;
                
                if (data.status !== 'error') {
                    html += `<div class="result-item"><span class="result-label">Claimed:</span> ${data.claimed_jurisdiction}</div>`;
                    html += `<div class="result-item"><span class="result-label">Actual:</span> ${data.actual_jurisdiction}</div>`;
                    html += `<div class="result-item"><span class="result-label">Matched Address:</span> ${data.matched_address}</div>`;
                } else {
                    html += `<div class="result-item"><span class="result-label">Error:</span> ${data.message}</div>`;
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
