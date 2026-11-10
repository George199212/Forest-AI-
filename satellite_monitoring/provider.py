"""Thin provider interface + the Sentinel Hub (CDSE) implementation.

A provider does two things:
  discover(sensor, bbox, date_from, date_to) -> [Product]   (one search per sensor per run)
  fetch_area_raster(sensor, product, grid)  -> FetchResult  (one clipped request per area+product)
Another provider (e.g. openEO, commercial) can be added behind the same two calls.
"""
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import cdse, config

COLLECTION = {"S2": "sentinel-2-l2a", "S1": "sentinel-1-grd"}

# Evalscripts return raw values as FLOAT32; every index / dB is computed locally
# so the stored GeoTIFF is the unmodified evidence.
EVALSCRIPT_S2 = """//VERSION=3
function setup() {
  return {input: [{bands: ["B04", "B08", "B11", "B12", "SCL", "dataMask"]}],
          output: {id: "default", bands: 6, sampleType: "FLOAT32"}};
}
function evaluatePixel(s) { return [s.B04, s.B08, s.B11, s.B12, s.SCL, s.dataMask]; }
"""
S2_BANDS = ["B04", "B08", "B11", "B12", "SCL", "dataMask"]

EVALSCRIPT_S1 = """//VERSION=3
function setup() {
  return {input: [{bands: ["VV", "VH", "dataMask"]}],
          output: {id: "default", bands: 3, sampleType: "FLOAT32"}};
}
function evaluatePixel(s) { return [s.VV, s.VH, s.dataMask]; }
"""
S1_BANDS = ["VV", "VH", "dataMask"]


@dataclass
class Product:
    sensor: str
    product_id: str
    sensing_time_utc: str              # ISO-8601 Z
    platform: str = None
    orbit_direction: str = None        # ASCENDING | DESCENDING (S1)
    relative_orbit: int = None         # S1; None = unknown
    scene_cloud_pct: float = None      # S2
    footprint: dict = None             # GeoJSON geometry (CRS84) or None
    item_ids: list = field(default_factory=list)
    relative_orbit_source: str = None  # S1: CATALOG (sat:relative_orbit) | DERIVED_S1A | None (unknown)
    catalog_property_keys: list = None # S1: property names the Catalog item actually carried


@dataclass
class FetchResult:
    raw: bytes
    pu_spent: float
    pu_is_estimate: bool
    params: dict


def parse_time(s):
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def _s1_abs_orbit_from_id(item_id):
    # S1x_IW_GRDH_1SDV_<start>_<stop>_<ABSORBIT 6 digits>_<datatake>_<id>
    m = re.match(r"^S1[A-D]_\w\w_\w{4}_\w{4}_\d{8}T\d{6}_\d{8}T\d{6}_(\d{6})_", item_id or "")
    return int(m.group(1)) if m else None


def s1_relative_orbit(platform, absolute_orbit):
    """ESA relation for Sentinel-1A (175-orbit repeat): ((abs - 73) mod 175) + 1.
    Only Sentinel-1A is derived; for other platforms the catalog value is
    required, otherwise None (and the acquisition is never compared)."""
    if absolute_orbit is None:
        return None
    if (platform or "").lower() in ("sentinel-1a", "s1a"):
        return ((int(absolute_orbit) - 73) % 175) + 1
    return None


def parse_catalog_feature(sensor, f):
    p = f.get("properties") or {}
    item_id = f.get("id")
    platform = p.get("platform")
    if sensor == "S2":
        cloud = p.get("eo:cloud_cover")
        return Product("S2", item_id, p.get("datetime"), platform=platform,
                       scene_cloud_pct=float(cloud) if cloud is not None else None,
                       footprint=f.get("geometry"), item_ids=[item_id])
    mode = p.get("sar:instrument_mode")
    if mode is not None and mode != "IW":
        return None
    pols = p.get("sar:polarizations")
    if pols is not None and not {"VV", "VH"} <= set(pols):
        return None
    if platform is None and item_id:
        platform = {"S1A": "sentinel-1a", "S1B": "sentinel-1b", "S1C": "sentinel-1c",
                    "S1D": "sentinel-1d"}.get(item_id[:3])
    orbit = p.get("sat:orbit_state")
    rel = p.get("sat:relative_orbit")
    source = "CATALOG" if rel is not None else None
    if rel is None:
        rel = s1_relative_orbit(platform, p.get("sat:absolute_orbit") or _s1_abs_orbit_from_id(item_id))
        source = "DERIVED_S1A" if rel is not None else None
    return Product("S1", item_id, p.get("datetime"), platform=platform,
                   orbit_direction=orbit.upper() if orbit else None,
                   relative_orbit=int(rel) if rel is not None else None,
                   footprint=f.get("geometry"), item_ids=[item_id],
                   relative_orbit_source=source, catalog_property_keys=sorted(p.keys()))


def group_datatakes(products, max_gap_s=120):
    """Catalog items of the same pass (S2 tiles / S1 slices of one datatake)
    become ONE acquisition: same sensor, platform, orbit and sensing time within
    max_gap_s. product_id = smallest item id (deterministic); all ids kept."""
    import shapely.geometry
    from shapely.ops import unary_union
    out = []
    for p in sorted(products, key=lambda x: (x.platform or "", x.orbit_direction or "", x.sensing_time_utc)):
        if not p.item_ids:
            p.item_ids = [p.product_id]
        if out:
            q = out[-1]
            if (q.platform == p.platform and q.orbit_direction == p.orbit_direction
                    and q.relative_orbit == p.relative_orbit
                    and abs((parse_time(p.sensing_time_utc) - parse_time(q.sensing_time_utc)).total_seconds()) <= max_gap_s):
                q.item_ids = sorted(set(q.item_ids + p.item_ids))
                q.product_id = q.item_ids[0]
                if q.footprint and p.footprint:
                    q.footprint = shapely.geometry.mapping(unary_union(
                        [shapely.geometry.shape(q.footprint), shapely.geometry.shape(p.footprint)]))
                if p.scene_cloud_pct is not None:
                    q.scene_cloud_pct = max(q.scene_cloud_pct or 0.0, p.scene_cloud_pct)
                continue
        out.append(Product(**{**p.__dict__, "item_ids": list(p.item_ids)}))
    return sorted(out, key=lambda x: x.sensing_time_utc)


def estimate_pu(sensor, width, height, cfg=None):
    """Processing-unit estimate following the Sentinel Hub PU rules
    (https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/ProcessingUnit.html):
      area factor   = width*height / 512^2, minimum 0.01
      bands factor  = input bands / 3 (dataMask not counted)
      FLOAT32 output x2
      S1 orthorectification x2
    One sample per request (single datatake). Used only when the response has
    no x-processingunits-spent header; stored with pu_is_estimate=1."""
    cfg = cfg or config.DEFAULTS
    area = max(width * height / (512.0 * 512.0), 0.01)
    bands = (5 if sensor == "S2" else 2) / 3.0
    pu = area * bands * 2.0
    if sensor == "S1" and cfg["s1_orthorectify"]:
        pu *= 2.0
    return round(pu, 4)


class SentinelHubProvider:
    name = "CDSE Sentinel Hub"

    def __init__(self, client: cdse.Client, cfg=None):
        self.client = client
        self.cfg = cfg or config.DEFAULTS

    def discover(self, sensor, bbox, date_from, date_to, page_limit=100, max_pages=20):
        """One Catalog search over the union bbox; follows `next` paging (each page
        is a counted request). date_from/date_to: 'YYYY-MM-DD' inclusive."""
        body = {
            "bbox": bbox,
            "datetime": f"{date_from}T00:00:00Z/{date_to}T23:59:59Z",
            "collections": [COLLECTION[sensor]],
            "limit": page_limit,
        }
        products, pages = [], 0
        while True:
            r = self.client.post_json("CATALOG", cdse.CATALOG_SEARCH_URL, body, accept="application/geo+json")
            data = r.json()
            for f in data.get("features", []):
                p = parse_catalog_feature(sensor, f)
                if p is not None:
                    products.append(p)
            pages += 1
            nxt = (data.get("context") or {}).get("next")
            if nxt is None or pages >= max_pages:
                break
            body = {**body, "next": nxt}
        self.last_raw_items = [Product(**{**p.__dict__, "item_ids": list(p.item_ids)}) for p in products]
        self.last_pages = pages
        return group_datatakes(products)

    def request_body(self, sensor, product, grid):
        t = parse_time(product.sensing_time_utc)
        t0 = (t - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        t1 = (t + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data_filter = {"timeRange": {"from": t0, "to": t1}, "mosaickingOrder": "mostRecent"}
        source = {"type": COLLECTION[sensor], "dataFilter": data_filter}
        if sensor == "S1":
            data_filter.update({"acquisitionMode": "IW", "polarization": "DV", "resolution": "HIGH"})
            if product.orbit_direction:
                data_filter["orbitDirection"] = product.orbit_direction
            source["processing"] = {"backCoeff": self.cfg["s1_backcoeff"],
                                    "orthorectify": bool(self.cfg["s1_orthorectify"]),
                                    "demInstance": self.cfg["s1_dem_instance"]}
        return {
            "input": {"bounds": {"bbox": grid["bbox"], "properties": {"crs": grid["crs"]}}, "data": [source]},
            "output": {"width": grid["width"], "height": grid["height"],
                       "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
            "evalscript": EVALSCRIPT_S2 if sensor == "S2" else EVALSCRIPT_S1,
        }

    def fetch_area_raster(self, sensor, product, grid):
        body = self.request_body(sensor, product, grid)
        r = self.client.post_json("PROCESS", cdse.PROCESS_URL, body, accept="image/tiff", timeout=120)
        hdr = r.headers.get("x-processingunits-spent")
        try:
            pu, est = float(hdr), False
        except (TypeError, ValueError):
            pu, est = estimate_pu(sensor, grid["width"], grid["height"], self.cfg), True
        params = {k: v for k, v in body.items() if k != "evalscript"}
        params["evalscript_bands"] = S2_BANDS if sensor == "S2" else S1_BANDS
        params["pixel_size_deg"] = [grid["resx_deg"], grid["resy_deg"]]
        params["pixel_size_m"] = [grid["pixel_w_m"], grid["pixel_h_m"]]
        params["provider"] = self.name
        params["process_api"] = cdse.PROCESS_URL
        if sensor == "S1":
            params["backCoeff_used"] = self.cfg["s1_backcoeff"]
            params["dem_used"] = self.cfg["s1_dem_instance"]
        return FetchResult(raw=r.content, pu_spent=pu, pu_is_estimate=est, params=params)
