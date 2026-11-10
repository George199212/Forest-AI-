"""Geometry: validation, request grid and INSIDE / BUFFER masks.

All geometry here is real WGS84 / CRS84 (lon, lat). Input conventions:
  - sectors.boundary_json is [[lat, lon], ...] (database.py:14-30, read e.g. at
    services/geodata/forest_map.py:230) -> swapped to lon,lat here.
  - LVM GEO / VMD features are already EPSG:4326 lon,lat, produced server-side
    by services/geodata/forestry_io.to_wgs84 or pyproj.
  - Anything in LKS-92 (EPSG:3059) or LKS-2020 (EPSG:10306) is converted only
    with pyproj (to_crs84). The approximate _lks92_to_wgs84/lks92_to_wgs84
    helpers are never used (off by 150-190 km).

Pixel geometry uses a local equirectangular scale (111 320 m per degree of
latitude, x cos(lat) for longitude) at the area's centre latitude. For areas of
a few km this is within ~0.5 % — documented, and fine for 10 m pixels.
"""
import json
import math

import numpy as np

from . import config

M_PER_DEG = 111320.0


class GeometryError(ValueError):
    pass


def sector_boundary_to_polygon(boundary_json):
    """sectors.boundary_json ([[lat, lon], ...], open or closed) -> GeoJSON Polygon (CRS84)."""
    pts = json.loads(boundary_json) if isinstance(boundary_json, str) else boundary_json
    if not isinstance(pts, list) or len(pts) < 3:
        raise GeometryError("sector has no polygon (needs >= 3 vertices)")
    ring = []
    for p in pts:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise GeometryError("sector boundary vertex is not [lat, lon]")
        lat, lon = float(p[0]), float(p[1])
        ring.append([lon, lat])
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return {"type": "Polygon", "coordinates": [ring]}


def to_crs84(geometry, source_crs):
    """Reproject a GeoJSON Polygon to CRS84 with pyproj (always_xy)."""
    if source_crs in (None, "EPSG:4326", "CRS84", "OGC:CRS84", "urn:ogc:def:crs:OGC:1.3:CRS84"):
        return geometry
    if source_crs not in ("EPSG:3059", "EPSG:10306"):
        raise GeometryError(f"unsupported CRS {source_crs}")
    from pyproj import Transformer
    t = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    rings = []
    for ring in geometry["coordinates"]:
        xs, ys = zip(*[(c[0], c[1]) for c in ring])
        lon, lat = t.transform(xs, ys)
        rings.append([[float(a), float(b)] for a, b in zip(lon, lat)])
    return {"type": "Polygon", "coordinates": rings}


def geodesic_area_ha(geometry):
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    ext = geometry["coordinates"][0]
    area, _ = geod.polygon_area_perimeter([c[0] for c in ext], [c[1] for c in ext])
    total = abs(area)
    for hole in geometry["coordinates"][1:]:
        a, _ = geod.polygon_area_perimeter([c[0] for c in hole], [c[1] for c in hole])
        total -= abs(a)
    return total / 10000.0


def validate(geometry, cfg=None):
    """Returns (geometry, area_ha). Raises GeometryError with a human reason."""
    cfg = cfg or config.DEFAULTS
    import shapely.geometry
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise GeometryError("geometry must be a GeoJSON Polygon (MultiPolygon is not accepted)")
    coords = geometry.get("coordinates")
    if not coords or not isinstance(coords, list) or len(coords[0]) < 4:
        raise GeometryError("polygon needs a closed ring with >= 3 distinct vertices")
    w, s, e, n = cfg["latvia_bbox"]
    for ring in coords:
        if ring[0] != ring[-1]:
            raise GeometryError("polygon ring is not closed")
        for c in ring:
            lon, lat = float(c[0]), float(c[1])
            if not (math.isfinite(lon) and math.isfinite(lat)):
                raise GeometryError("non-finite coordinate")
            if not (w <= lon <= e and s <= lat <= n):
                raise GeometryError(f"coordinate {lon:.5f},{lat:.5f} is outside Latvia (CRS84 lon,lat expected)")
    shp = shapely.geometry.shape(geometry)
    if not shp.is_valid:
        from shapely.validation import explain_validity
        raise GeometryError("invalid polygon: " + explain_validity(shp))
    area = geodesic_area_ha(geometry)
    if not (cfg["min_area_ha"] <= area <= cfg["max_area_ha"]):
        raise GeometryError(f"area {area:.2f} ha outside {cfg['min_area_ha']}–{cfg['max_area_ha']} ha")
    return geometry, round(area, 4)


def make_grid(geometry, buffer_m, pixel_m):
    """Fixed request grid for an area: polygon bbox expanded by buffer_m (plus one
    pixel of margin), snapped to ~pixel_m pixels. Identical for S1 and S2 and for
    every acquisition, so per-pixel comparison needs no resampling."""
    ext = np.asarray(geometry["coordinates"][0], dtype=float)
    lon_min, lat_min = ext.min(axis=0)
    lon_max, lat_max = ext.max(axis=0)
    lat0 = (lat_min + lat_max) / 2.0
    m_per_deg_lon = M_PER_DEG * math.cos(math.radians(lat0))
    resy = pixel_m / M_PER_DEG
    resx = pixel_m / m_per_deg_lon
    pad_lat = (buffer_m + pixel_m) / M_PER_DEG
    pad_lon = (buffer_m + pixel_m) / m_per_deg_lon
    west, south = lon_min - pad_lon, lat_min - pad_lat
    width = int(math.ceil((lon_max + pad_lon - west) / resx))
    height = int(math.ceil((lat_max + pad_lat - south) / resy))
    east, north = west + width * resx, south + height * resy
    return {
        "bbox": [round(west, 9), round(south, 9), round(east, 9), round(north, 9)],
        "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        "width": width, "height": height,
        "resx_deg": resx, "resy_deg": resy,
        "pixel_w_m": resx * m_per_deg_lon, "pixel_h_m": resy * M_PER_DEG,
        "lat0": lat0,
        "pixel_area_ha": (resx * m_per_deg_lon) * (resy * M_PER_DEG) / 10000.0,
        "note": "pixel size from local equirectangular scale at lat0",
    }


def pixel_centres(grid):
    w, s, e, n = grid["bbox"]
    xs = w + (np.arange(grid["width"]) + 0.5) * grid["resx_deg"]
    ys = n - (np.arange(grid["height"]) + 0.5) * grid["resy_deg"]   # row 0 = north (north-up raster)
    return np.meshgrid(xs, ys)


def points_in_polygon(x, y, geometry):
    """Even-odd ray casting on pixel centres (numpy). Holes handled by parity."""
    inside = np.zeros(x.shape, dtype=bool)
    for ring in geometry["coordinates"]:
        r = np.asarray(ring, dtype=float)
        x1, y1 = r[:-1, 0], r[:-1, 1]
        x2, y2 = r[1:, 0], r[1:, 1]
        for a, b, c, d in zip(x1, y1, x2, y2):
            cond = (b > y) != (d > y)
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = a + (y - b) * (c - a) / (d - b)
            inside ^= cond & (x < xint)
    return inside


def masks(geometry, grid, buffer_m):
    """INSIDE: pixel centre inside the polygon. BUFFER: outside, within buffer_m of
    the nearest INSIDE pixel centre (pixel-distance approximation, +-1 pixel).
    Returns (inside, buffer, dist_to_inside_m)."""
    from scipy import ndimage
    x, y = pixel_centres(grid)
    inside = points_in_polygon(x, y, geometry)
    if not inside.any():
        raise GeometryError("polygon smaller than one pixel at this resolution")
    dist = ndimage.distance_transform_edt(~inside, sampling=(grid["pixel_h_m"], grid["pixel_w_m"]))
    buffer = (~inside) & (dist <= buffer_m)
    return inside, buffer, dist


def bbox_polygon(bbox):
    import shapely.geometry
    return shapely.geometry.box(*bbox)


def union_bbox(grids):
    b = np.array([g["bbox"] for g in grids], dtype=float)
    return [float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].max()), float(b[:, 3].max())]


def mask_to_geojson(mask, grid, properties=None):
    """Outline of a boolean pixel mask as a GeoJSON (Multi)Polygon in CRS84.
    Built from row runs of pixel squares, merged with shapely."""
    import shapely.geometry
    from shapely.ops import unary_union
    w, s, e, n = grid["bbox"]
    rx, ry = grid["resx_deg"], grid["resy_deg"]
    boxes = []
    for j in range(mask.shape[0]):
        row = mask[j]
        if not row.any():
            continue
        padded = np.concatenate([[False], row, [False]])
        d = np.diff(padded.astype(np.int8))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        top = n - j * ry
        for a, b in zip(starts, ends):
            boxes.append(shapely.geometry.box(w + a * rx, top - ry, w + b * rx, top))
    if not boxes:
        return None
    geom = unary_union(boxes)
    return {"type": "Feature", "geometry": shapely.geometry.mapping(geom), "properties": properties or {}}
