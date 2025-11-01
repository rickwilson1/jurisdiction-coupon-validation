import geopandas as gpd

path = "CDTFA_SalesandUseTaxRates.shp"
gdf = gpd.read_file(path)

print("✅ Loaded:", len(gdf), "rows")
print("Geometry column:", gdf.geometry.name)
print("CRS before:", gdf.crs)

# Repair if necessary
if gdf.crs is None:
    gdf.set_crs(epsg=3857, inplace=True)
gdf = gdf.to_crs(epsg=4326)
print("CRS after:", gdf.crs)

print("Geometry type:", gdf.geom_type.unique()[:5])
print(gdf.head(1))