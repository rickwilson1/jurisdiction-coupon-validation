import geopandas as gpd
import pandas as pd
import requests
import streamlit as st
from shapely.geometry import Point

# ---------------------------------------------------
# CONFIG
# ---------------------------------------------------
st.set_page_config(page_title="California Sales & Use Tax District Lookup", layout="centered")
st.title("💰 California Sales & Use Tax District Lookup")
st.write("Enter any California address to find its current CDTFA sales & use tax district(s).")

CDTFA_FILE = (
    "~/Documents/Python_Projects/geocoordinates/tax_districts/"
    "CDTFA_SalesandUseTaxRates.shp"
)
GEOCODE_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"


# ---------------------------------------------------
# LOAD DATA — robust version (no cache)
# ---------------------------------------------------
def load_districts():
    try:
        gdf = gpd.read_file(CDTFA_FILE)
    except Exception as e:
        st.error(f"❌ Could not load shapefile: {e}")
        st.stop()

    # Ensure geometry column is set
    if "geometry" not in gdf.columns:
        st.error("❌ Shapefile has no 'geometry' column — cannot continue.")
        st.stop()
    gdf = gdf.set_geometry("geometry")

    # Ensure CRS exists and is in lat/lon
    if gdf.crs is None:
        st.warning("⚠️ No CRS detected; assuming EPSG:3857.")
        gdf.set_crs(epsg=3857, inplace=True)
    try:
        if gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
    except Exception:
        gdf.set_crs(epsg=4326, inplace=True)

    # Clean column names
    gdf.columns = [c.strip().upper() for c in gdf.columns]

    # Show debug info safely (don’t access crs property directly)
    with st.sidebar:
        st.markdown("### ✅ Shapefile Loaded")
        st.text(f"Rows: {len(gdf)}")
        st.text(f"CRS: {str(gdf.crs)}")
        st.text("Columns:")
        for c in gdf.columns:
            st.text(f"  • {c}")

    field_map = {
        "name": "JURIS_NAME",
        "county": "COUNTY_NAM",
        "city": "CITY_NAME",
        "rate": "RATE",
        "effdate": "START_DATE",
    }

    return gdf, field_map


districts, field_map = load_districts()


# ---------------------------------------------------
# HELPERS
# ---------------------------------------------------
def geocode_address(address: str):
    params = {"f": "json", "singleLine": address, "maxLocations": 1}
    try:
        r = requests.get(GEOCODE_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get("candidates"):
            return None, None
        loc = data["candidates"][0]["location"]
        return loc["y"], loc["x"]
    except Exception as e:
        st.error(f"Geocoding error: {e}")
        return None, None


def lookup_tax_district(lat, lon):
    try:
        point = gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs="EPSG:4326")
        matches = gpd.sjoin(districts, point, predicate="intersects")

        if matches.empty:
            buffered = point.buffer(0.0005)
            buffered_gdf = gpd.GeoDataFrame(geometry=buffered, crs="EPSG:4326")
            matches = gpd.sjoin(districts, buffered_gdf, predicate="intersects")

        if matches.empty:
            return []

        results = []
        for _, row in matches.iterrows():
            results.append({
                "Jurisdiction": row.get(field_map["name"], "Unknown"),
                "County": row.get(field_map["county"], "N/A"),
                "City": row.get(field_map["city"], "N/A"),
                "Tax Rate": row.get(field_map["rate"], "N/A"),
                "Effective Date": row.get(field_map["effdate"], "N/A"),
            })
        return results

    except Exception as e:
        st.error(f"Spatial lookup error: {e}")
        return []


# ---------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------
address = st.text_input("📍 Address:")

if address:
    with st.spinner("Geocoding and checking CDTFA districts..."):
        lat, lon = geocode_address(address)

        if lat is None or lon is None:
            st.error("Could not geocode that address. Please try again.")
        else:
            results = lookup_tax_district(lat, lon)

            if results:
                st.success(f"✅ Found {len(results)} tax district(s)")
                st.markdown(f"**Address:** {address}")
                st.markdown(f"**Coordinates:** {lat:.6f}, {lon:.6f}")

                for i, d in enumerate(results, 1):
                    st.markdown(f"### 🏷️ District {i}")
                    st.markdown(f"**Jurisdiction:** {d['Jurisdiction']}")
                    st.markdown(f"**County:** {d['County']}")
                    st.markdown(f"**City:** {d['City']}")
                    st.markdown(f"**Tax Rate:** {d['Tax Rate']}")
                    st.markdown(f"**Effective Date:** {d['Effective Date']}")

                map_df = pd.DataFrame({"latitude": [lat], "longitude": [lon]})
                st.map(map_df, zoom=11)
            else:
                st.warning("No district polygon found for this location.")