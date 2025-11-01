import requests
import geopandas as gpd
import streamlit as st
from shapely.geometry import Point

# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------
SHAPEFILE_PATH = "CDTFA_SalesandUseTaxRates.shp"  # Adjust if needed
GEOCODE_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"

# ---------------------------------------------------
# HELPERS
# ---------------------------------------------------
@st.cache_resource
def load_tax_districts():
    """Load CDTFA shapefile and convert CRS to WGS84."""
    gdf = gpd.read_file(SHAPEFILE_PATH)
    if gdf.crs is None:
        gdf.set_crs(epsg=3857, inplace=True)  # CDTFA file default
    gdf = gdf.to_crs(epsg=4326)
    return gdf


def geocode_address(address: str):
    """Use ArcGIS geocoder to get lat/lon and formatted postal city."""
    params = {"f": "json", "singleLine": address, "outFields": "Match_addr", "maxLocations": 1}
    r = requests.get(GEOCODE_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data.get("candidates"):
        return None, None, None
    cand = data["candidates"][0]
    loc = cand["location"]
    match_addr = cand["address"]
    postal_city = match_addr.split(",")[1].strip() if "," in match_addr else None
    return loc["y"], loc["x"], postal_city


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

# ---------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------
st.set_page_config(page_title="Agromin Coupon Code Validation", layout="wide")
st.title("🏙️ Coupon Code Qualification - Jurisdiction Identification")

address = st.text_input("Enter a California address:")

if address:
    with st.spinner("Geocoding and matching district..."):
        try:
            gdf = load_tax_districts()
            lat, lon, postal_city = geocode_address(address)
            if not lat or not lon:
                st.error("Could not geocode that address. Please try again.")
            else:
                district = find_tax_district(lat, lon, gdf)
                if not district:
                    st.warning("Address not found (likely unincorporated).")
                else:
                    st.success("✅ Match found")
                    st.markdown(f"**📍 Address:** {address}")
                    st.markdown(f"**🌐 Coordinates:** {lat:.5f}, {lon:.5f}")
                    st.markdown(f"**🏛️ Jurisdiction:** {district['jurisdiction']}")
                    st.markdown(f"**🏙️ City Name:** {district['city'] or '—'}")
                    st.markdown(f"**📡 County:** {district['county']}")
        except Exception as e:
            st.error(f"Error: {e}")