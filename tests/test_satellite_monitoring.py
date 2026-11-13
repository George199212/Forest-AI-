"""Satellite Monitoring Stage 1 — no network. Synthetic rasters through a fake provider."""
import io
import json
import sqlite3
from datetime import datetime, timezone

import numpy as np
import pytest

from satellite_monitoring import areas, cdse, config, context, db as sdb, detection as det, geometry as geo
from satellite_monitoring import metrics as met, pipeline, provider as prov

# ~400 x 400 m square near 57.0N 24.5E (inside Latvia)
LAT, LON = 57.0, 24.5
DLAT = 400 / 111320.0
DLON = 400 / (111320.0 * np.cos(np.radians(LAT)))
SQUARE = {"type": "Polygon", "coordinates": [[[LON, LAT], [LON + DLON, LAT], [LON + DLON, LAT + DLAT],
                                              [LON, LAT + DLAT], [LON, LAT]]]}


# ── fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SAT_DATA_DIR", str(tmp_path / "sat"))
    monkeypatch.setenv("SAT_RASTER_DIR", str(tmp_path / "sat" / "satellite"))
    forest = tmp_path / "forest.db"
    c = sqlite3.connect(forest)
    c.executescript("""
    CREATE TABLE sectors (id INTEGER PRIMARY KEY, name TEXT, boundary_json TEXT);
    CREATE TABLE session_track_points (id INTEGER PRIMARY KEY, session_id INTEGER, latitude REAL, longitude REAL, recorded_at TEXT);
    CREATE TABLE vehicle_gps_pings (id INTEGER PRIMARY KEY, latitude REAL, longitude REAL, entity_type TEXT, recorded_at TEXT);
    CREATE TABLE work_sessions (id INTEGER PRIMARY KEY, sector TEXT, latitude REAL, longitude REAL, check_in_time TEXT, finish_time TEXT);
    CREATE TABLE work_photos (id INTEGER PRIMARY KEY, sector TEXT, uploaded_at TEXT);
    CREATE TABLE timber_movements (id INTEGER PRIMARY KEY, sector TEXT, created_at TEXT, is_demo INTEGER DEFAULT 0);
    CREATE TABLE truck_reports (id INTEGER PRIMARY KEY, sector TEXT, created_at TEXT);
    """)
    ring = [[p[1], p[0]] for p in SQUARE["coordinates"][0][:-1]]
    c.execute("INSERT INTO sectors VALUES (1, 'TST-001', ?)", (json.dumps(ring),))
    c.commit()
    c.close()
    monkeypatch.setenv("FOREST_DB_PATH", str(forest))
    # F3 forest mask: by default one VMD compartment covers the whole test area + buffer (all pixels analysed)
    vmd = tmp_path / "compartments.sqlite"
    make_vmd(vmd, [{"type": "Polygon", "coordinates": [[[LON - 0.05, LAT - 0.05], [LON + 0.05, LAT - 0.05],
                                                         [LON + 0.05, LAT + 0.05], [LON - 0.05, LAT + 0.05],
                                                         [LON - 0.05, LAT - 0.05]]]}])
    monkeypatch.setenv("SAT_FOREST_DB", str(vmd))
    monkeypatch.setenv("SAT_FOREST_DB_VERSION", "test-vmd")
    conn = sdb.connect(tmp_path / "sat" / "satellite.db")
    yield {"conn": conn, "forest": forest, "tmp": tmp_path}
    conn.close()


def make_vmd(path, polygons, zkat="10"):
    """Minimal stand-in for the nationwide VMD index (compartments + rtree), WGS84 WKB geometries."""
    import shapely
    from shapely.geometry import shape
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE compartments (id INTEGER PRIMARY KEY, geometry BLOB NOT NULL, properties TEXT);"
                    "CREATE VIRTUAL TABLE spatial_index USING rtree(id, min_lon, max_lon, min_lat, max_lat);")
    for i, p in enumerate(polygons, 1):
        p, z = p if isinstance(p, tuple) else (p, zkat)          # (polygon, zkat) overrides the default zkat
        g = shape(p)
        w, s, e, n = g.bounds
        c.execute("INSERT INTO compartments VALUES (?,?,?)", (i, shapely.to_wkb(g), json.dumps({"zkat": z})))
        c.execute("INSERT INTO spatial_index VALUES (?,?,?,?,?)", (i, w, e, s, n))
    c.commit()
    c.close()


def make_area(conn, geometry=SQUARE, name="TST-001", ref="1"):
    aid, created = areas.create(conn, "SECTOR", ref, name, geometry, "test")
    return areas.load(conn, aid)


def npy(arr):
    b = io.BytesIO()
    np.save(b, arr)
    return b.getvalue()


def decoder(raw, expected_shape=None, bands=None):
    arr = np.load(io.BytesIO(raw))
    assert arr.shape[:2] == tuple(expected_shape) and arr.shape[2] == bands
    return arr


class FakeResp:
    def __init__(self, pu):
        self.headers = {"x-processingunits-spent": str(pu)}


class FakeProvider:
    """products: list[Product]; rasters: product_id -> ndarray | Exception"""
    def __init__(self, products, rasters):
        self.products, self.rasters = products, rasters
        self.on_request = None
        self.fetch_calls, self.discover_calls = [], []

    def discover(self, sensor, bbox, date_from, date_to):
        self.discover_calls.append(sensor)
        self.on_request("CATALOG", 200, None)
        return [p for p in self.products if p.sensor == sensor and date_from <= p.sensing_time_utc[:10] <= date_to]

    def fetch_area_raster(self, sensor, product, grid):
        self.fetch_calls.append(product.product_id)
        r = self.rasters[product.product_id]
        if isinstance(r, Exception):
            self.on_request("PROCESS", getattr(r, "http_status", 500), None)
            raise r
        self.on_request("PROCESS", 200, FakeResp(0.1))
        return prov.FetchResult(raw=npy(r), pu_spent=0.1, pu_is_estimate=False, params={"fake": True})


def s2_arr(grid, cut_mask=None, scl=4.0):
    h, w = grid["height"], grid["width"]
    a = np.zeros((h, w, 6), dtype=np.float32)
    a[..., 0], a[..., 1], a[..., 2], a[..., 3], a[..., 4], a[..., 5] = 0.03, 0.30, 0.15, 0.07, scl, 1
    if cut_mask is not None:
        a[cut_mask, 0], a[cut_mask, 1], a[cut_mask, 2], a[cut_mask, 3] = 0.08, 0.18, 0.25, 0.18
    return a


def s1_arr(grid, drop_mask=None):
    h, w = grid["height"], grid["width"]
    a = np.zeros((h, w, 3), dtype=np.float32)
    a[..., 0], a[..., 1], a[..., 2] = 0.08, 0.02, 1
    if drop_mask is not None:
        a[drop_mask, 1] = 0.007
    return a


def P(sensor, pid, t, **kw):
    return prov.Product(sensor, pid, t, platform=kw.pop("platform", "sentinel-2b" if sensor == "S2" else "sentinel-1a"),
                        **kw)


def block(area, r0, c0, n):
    m = np.zeros((area["grid"]["height"], area["grid"]["width"]), dtype=bool)
    m[r0:r0 + n, c0:c0 + n] = True
    return m


def run(env, provider, **kw):
    kw.setdefault("date_from", "2026-05-01")
    kw.setdefault("date_to", "2026-10-31")
    return pipeline.run("BACKFILL", conn=env["conn"], provider=provider, decoder=decoder,
                        lock_file=env["tmp"] / "lock", **kw)


def centre_block(area, n=10):
    g = area["grid"]
    return block(area, g["height"] // 2 - n // 2, g["width"] // 2 - n // 2, n)


# ── geometry ────────────────────────────────────────────────────────────────
def test_geometry_validation():
    geo.validate(SQUARE)
    with pytest.raises(geo.GeometryError, match="outside Latvia"):
        geo.validate({"type": "Polygon", "coordinates": [[[32.74, 58.90], [32.75, 58.90], [32.75, 58.91], [32.74, 58.90]]]})
    with pytest.raises(geo.GeometryError, match="MultiPolygon"):
        geo.validate({"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]})
    tiny = {"type": "Polygon", "coordinates": [[[LON, LAT], [LON + 1e-5, LAT], [LON + 1e-5, LAT + 1e-5], [LON, LAT]]]}
    with pytest.raises(geo.GeometryError, match="area"):
        geo.validate(tiny)
    bow = {"type": "Polygon", "coordinates": [[[LON, LAT], [LON + DLON, LAT + DLAT], [LON + DLON, LAT],
                                               [LON, LAT + DLAT], [LON, LAT]]]}
    with pytest.raises(geo.GeometryError, match="invalid"):
        geo.validate(bow)
    with pytest.raises(geo.GeometryError, match="not closed"):
        geo.validate({"type": "Polygon", "coordinates": [SQUARE["coordinates"][0][:-1] + [[LON, LAT + 1e-3]]]})


def test_sector_boundary_is_lat_lon_and_swapped():
    g = geo.sector_boundary_to_polygon([[56.968, 24.1958], [56.965, 24.213], [56.9615, 24.213], [56.9617, 24.1988]])
    assert g["coordinates"][0][0] == [24.1958, 56.968] and g["coordinates"][0][-1] == g["coordinates"][0][0]
    _, ha = geo.validate(g)
    assert 49 < ha < 52


def test_lks92_conversion_sanity_lands_in_latvia():
    # Riga, Freedom Monument ~ 24.1133E 56.9514N <-> LKS-92 (EPSG:3059) E 506892, N 311982
    pt = {"type": "Polygon", "coordinates": [[[506892, 311982], [507092, 311982], [507092, 312182], [506892, 311982]]]}
    g = geo.to_crs84(pt, "EPSG:3059")
    lon, lat = g["coordinates"][0][0]
    assert abs(lon - 24.1133) < 1e-4 and abs(lat - 56.9514) < 1e-4
    w, s, e, n = config.DEFAULTS["latvia_bbox"]
    assert w <= lon <= e and s <= lat <= n
    geo.validate(g)


def test_inside_buffer_mask_rasterization():
    import shapely.geometry
    grid = geo.make_grid(SQUARE, 100, 10)
    inside, buffer, dist = geo.masks(SQUARE, grid, 100)
    x, y = geo.pixel_centres(grid)
    shp = shapely.geometry.shape(SQUARE)
    ref = np.vectorize(lambda a, b: shp.contains(shapely.geometry.Point(a, b)))(x, y)
    assert (inside == ref).mean() > 0.995           # boundary pixels may differ on exact edges
    assert not (inside & buffer).any()
    assert (dist[buffer] <= 100).all() and (dist[buffer] > 0).all()
    # 400 m square at 10 m -> ~1600 inside pixels; ring of 100 m -> ~ (600^2 - 400^2)/100 minus corners
    assert 1500 < inside.sum() < 1700
    assert 1800 < buffer.sum() < 2100
    outside_far = ~(inside | buffer)
    assert outside_far.any() and (dist[outside_far] > 100).all()


def test_point_in_polygon_handles_holes():
    outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    x, y = np.array([[1.0, 5.0, 11.0]]), np.array([[1.0, 5.0, 5.0]])
    r = geo.points_in_polygon(x, y, {"type": "Polygon", "coordinates": [outer, hole]})
    assert r.tolist() == [[True, False, False]]


# ── metrics: missing data is NULL, never 0 ──────────────────────────────────
def test_cloud_gives_null_not_zero(env):
    a = make_area(env["conn"])
    cloudy_pixels = s2_arr(a["grid"], scl=9.0)                    # every pixel cloud (SCL 9)
    prods = [P("S2", "S2_CLOUDSCENE", "2026-06-05T09:50:00Z", scene_cloud_pct=95.0),
             P("S2", "S2_CLOUDPIX", "2026-06-10T09:50:00Z", scene_cloud_pct=40.0)]
    fp = FakeProvider(prods, {"S2_CLOUDPIX": cloudy_pixels})
    res = run(env, fp, sensors=("S2",))
    c = env["conn"]
    assert fp.fetch_calls == ["S2_CLOUDPIX"]                       # cloudy scene never requested
    st = {r["product_id"]: dict(r) for r in c.execute("SELECT * FROM sat_acquisitions")}
    assert st["S2_CLOUDSCENE"]["status"] == "SKIPPED_CLOUD" and st["S2_CLOUDSCENE"]["raster_path"] is None
    assert st["S2_CLOUDPIX"]["status"] == "NO_VALID_PIXELS"
    assert st["S2_CLOUDPIX"]["valid_pct_inside"] == 0.0            # a real measured percentage
    for pid in ("S2_CLOUDSCENE", "S2_CLOUDPIX"):
        rows = c.execute("SELECT * FROM sat_area_metrics WHERE acquisition_id=? AND metric IN ('NDVI','NBR','NDMI')",
                         (st[pid]["id"],)).fetchall()
        assert rows and all(r["mean"] is None and r["median"] is None and r["null_reason"] for r in rows)
    assert "SKIPPED_CLOUD" in c.execute("SELECT null_reason FROM sat_area_metrics WHERE acquisition_id=? AND metric='NDVI'",
                                        (st["S2_CLOUDSCENE"]["id"],)).fetchone()[0]
    assert res["status"] == "OK"


def test_zone_stats_empty_is_null():
    v = np.full((3, 3), np.nan)
    s = met.zone_stats(v, np.zeros((3, 3), bool), np.ones((3, 3), bool))
    assert s["mean"] is None and s["n_valid_pixels"] == 0 and s["null_reason"] == "NO_VALID_PIXELS"


# ── detection primitives ────────────────────────────────────────────────────
def test_cluster_area_math_and_8_connectivity():
    grid = {"pixel_area_ha": 0.01}
    m = np.zeros((20, 20), bool)
    m[0:5, 0:6] = True                        # 30 px = 0.30 ha
    m[10, 10] = m[11, 11] = m[12, 12] = True  # diagonal chain -> one 8-connected cluster
    labels, sizes = det.clusters(m, 0.01)
    assert sorted(sizes.tolist()) == [3, 30]
    kept = det.keep_large_clusters(m, grid, 0.3)
    assert kept.sum() == 30
    assert det.keep_large_clusters(m, grid, 0.31).sum() == 0


def test_s2_threshold_edges():
    cfg = config.DEFAULTS
    one = lambda v: np.full((1, 1), v, dtype=np.float64)
    base = {"NDVI": one(0.80), "NBR": one(0.60), "NDMI": one(0.30)}
    zone = np.ones((1, 1), bool)
    def changed(dndvi, dnbr):
        after = {"NDVI": one(0.80 + dndvi), "NBR": one(0.60 + dnbr), "NDMI": one(0.30)}
        return bool(det.s2_change(after, [base], zone, cfg)[0][0, 0])
    assert changed(-0.11, -0.16)
    assert changed(-0.1000001, -0.1500001)
    assert not changed(-0.0999, -0.20)        # NDVI drop just short
    assert not changed(-0.30, -0.1499)        # NBR drop just short
    # S1 edge: exactly 2 dB drop counts, 1.9 dB does not
    lin = lambda db: np.full((5, 5), 10 ** (db / 10.0))
    z5 = np.ones((5, 5), bool)
    assert det.s1_drop(lin(-19.0001), [lin(-17.0)], z5, cfg)[0][2, 2]
    assert not det.s1_drop(lin(-18.9), [lin(-17.0)], z5, cfg)[0][2, 2]


def test_inside_vs_buffer_area_split():
    grid = geo.make_grid(SQUARE, 100, 10)
    inside, buffer, dist = geo.masks(SQUARE, grid, 100)
    cols = np.where(inside.any(axis=0))[0]
    rows = np.where(inside.any(axis=1))[0]
    r0, c_edge = rows[len(rows) // 2], cols[-1]
    m = np.zeros_like(inside)
    m[r0:r0 + 6, c_edge - 4:c_edge + 6] = True    # 5 columns inside, 5 columns in the buffer
    s = det.event_stats(m, inside, buffer, dist, grid, 16.0)
    pa = grid["pixel_area_ha"]
    assert s["changed_area_ha_inside"] == pytest.approx(30 * pa, abs=1e-6)
    assert s["changed_area_ha_buffer"] == pytest.approx(30 * pa, abs=1e-6)
    assert 40 <= s["max_distance_outside_boundary_m"] <= 60   # 5th pixel beyond the edge, +-1 pixel
    assert s["pct_of_area_affected"] == pytest.approx(100 * 30 * pa / 16.0, rel=1e-3)


def test_classification_rules():
    c = det.classify
    assert c("POOR", 7, None, 5.0)[0] == "INSUFFICIENT_EVIDENCE"
    for month in (10, 11, 12, 1, 2, 3, 4):
        cls, cav = c("GOOD", month, None, 0.0)
        assert cls == "POSSIBLE_SEASONAL_OR_ENVIRONMENTAL" and "Oct–Apr" in cav
    for month in (5, 6, 7, 8, 9):
        assert c("GOOD", month, None, 0.0)[0] == "POTENTIAL_FOREST_LOSS"
    assert c("GOOD", 6, 25.0, 0.0)[0] == "POSSIBLE_SEASONAL_OR_ENVIRONMENTAL"
    assert c("LIMITED", 6, 0.0, 0.3)[0] == "POTENTIAL_CHANGE_OUTSIDE_BOUNDARY"
    assert c("LIMITED", 6, 0.0, 0.29)[0] == "POTENTIAL_FOREST_LOSS"
    assert c("POOR", 1, None, 0.0)[1] is not None      # caveat still recorded


def test_confidence_and_evidence_quality_are_independent():
    assert det.confidence({"S1": ["2026-06-01T00:00:00Z"]}) == "LOW"
    assert det.confidence({"S2": ["2026-06-01T00:00:00Z"]}) == "MEDIUM"
    assert det.confidence({"S1": ["2026-06-01T00:00:00Z"], "S2": ["2026-06-20T00:00:00Z"]}) == "HIGH"
    assert det.confidence({"S1": ["2026-06-01T00:00:00Z"], "S2": ["2026-07-01T00:00:00Z"]}) == "MEDIUM"
    # quality depends only on the inputs, not on which sensors agree
    assert det.evidence_quality(95, 3, 10) == "GOOD"
    assert det.evidence_quality(65, 1, 50) == "LIMITED"
    assert det.evidence_quality(50, 3, 10) == "POOR"
    assert det.evidence_quality(None, 3, 10) == "POOR"
    combos = {(det.confidence(t), det.evidence_quality(*q))
              for t in ({"S1": ["2026-06-01T00:00:00Z"]}, {"S1": ["2026-06-01T00:00:00Z"], "S2": ["2026-06-02T00:00:00Z"]})
              for q in ((95, 3, 10), (50, 0, 99))}
    assert {("LOW", "GOOD"), ("HIGH", "POOR")} <= combos


def test_s1_different_orbits_never_compared():
    a = {"orbit_direction": "ASCENDING", "relative_orbit": 58}
    assert det.same_geometry(a, {"orbit_direction": "ASCENDING", "relative_orbit": 58})
    assert not det.same_geometry(a, {"orbit_direction": "ASCENDING", "relative_orbit": 131})
    assert not det.same_geometry(a, {"orbit_direction": "DESCENDING", "relative_orbit": 58})
    assert not det.same_geometry({"orbit_direction": "ASCENDING", "relative_orbit": None},
                                 {"orbit_direction": "ASCENDING", "relative_orbit": None})


def test_s1_relative_orbit_parsing():
    f = {"id": "S1A_IW_GRDH_1SDV_20261001T160355_20261001T160420_060123_077ABC_1234",
         "properties": {"datetime": "2026-10-01T16:03:55Z", "sat:orbit_state": "ascending",
                        "sar:instrument_mode": "IW", "sar:polarizations": ["VV", "VH"]}}
    p = prov.parse_catalog_feature("S1", f)
    assert p.orbit_direction == "ASCENDING" and p.relative_orbit == ((60123 - 73) % 175) + 1
    assert p.relative_orbit_source == "DERIVED_S1A"
    f2 = {**f, "id": "S1C_IW_GRDH_1SDV_20261001T160355_20261001T160420_004123_00ABCD_1234"}
    p2 = prov.parse_catalog_feature("S1", f2)
    assert p2.relative_orbit is None and p2.relative_orbit_source is None   # unknown -> never compared
    assert p2.platform == "sentinel-1c"
    f3 = {**f, "properties": {**f["properties"], "sat:relative_orbit": 131}}
    p3 = prov.parse_catalog_feature("S1", f3)
    assert p3.relative_orbit == 131 and p3.relative_orbit_source == "CATALOG"
    assert "sat:relative_orbit" in p3.catalog_property_keys
    ew = {**f, "properties": {**f["properties"], "sar:instrument_mode": "EW"}}
    assert prov.parse_catalog_feature("S1", ew) is None


class _PagedCatalog:
    """Mocked CDSE client: returns the given Catalog pages in order, records request bodies."""
    def __init__(self, pages):
        self.pages, self.bodies = list(pages), []

    def post_json(self, kind, url, payload, accept="application/json", timeout=60):
        assert kind == "CATALOG" and url == cdse.CATALOG_SEARCH_URL
        self.bodies.append(json.loads(json.dumps(payload)))
        page = self.pages.pop(0)
        return type("R", (), {"json": lambda _self: page})()


def _s2_item(i, t):
    return {"id": f"S2C_item_{i}", "geometry": None,
            "properties": {"datetime": t, "platform": "sentinel-2c", "eo:cloud_cover": 10.0}}


def test_catalog_discovery_follows_pagination_until_exhausted():
    page1 = {"features": [_s2_item(1, "2026-06-01T09:50:00Z"), _s2_item(2, "2026-06-03T09:50:00Z")],
             "context": {"next": "100", "limit": 2, "returned": 2}}
    page2 = {"features": [_s2_item(3, "2026-06-05T09:50:00Z")],
             "context": {"limit": 2, "returned": 1}}                    # no "next" -> exhausted
    client = _PagedCatalog([page1, page2])
    sh = prov.SentinelHubProvider(client, config.DEFAULTS)
    prods = sh.discover("S2", [24.1, 56.8, 24.2, 56.9], "2026-06-01", "2026-06-30", page_limit=2)
    assert [p.product_id for p in prods] == ["S2C_item_1", "S2C_item_2", "S2C_item_3"]   # page-2 item kept
    assert sh.last_pages == 2 and client.pages == []
    assert "next" not in client.bodies[0] and client.bodies[1]["next"] == "100"
    assert {k: v for k, v in client.bodies[1].items() if k != "next"} == client.bodies[0]  # same query


def test_catalog_discovery_never_truncates_silently(monkeypatch):
    loop = {"features": [_s2_item(1, "2026-06-01T09:50:00Z")], "context": {"next": "100"}}
    with pytest.raises(cdse.CdseError) as e:                             # repeated token
        prov.SentinelHubProvider(_PagedCatalog([loop, loop, loop])).discover("S2", [24, 56, 25, 57], "2026-06-01", "2026-06-30")
    assert e.value.kind == "PAGINATION"
    monkeypatch.setattr(prov, "CATALOG_MAX_PAGES", 2)                     # safety cap raises, not truncates
    pages = [{"features": [], "context": {"next": str(n)}} for n in (1, 2, 3)]
    with pytest.raises(cdse.CdseError) as e:
        prov.SentinelHubProvider(_PagedCatalog(pages)).discover("S2", [24, 56, 25, 57], "2026-06-01", "2026-06-30")
    assert e.value.kind == "PAGINATION"


def test_datatake_grouping_merges_tiles():
    a = P("S2", "S2B_T35VLC", "2026-06-05T09:50:10Z", scene_cloud_pct=10.0)
    b = P("S2", "S2B_T34VFH", "2026-06-05T09:50:30Z", scene_cloud_pct=30.0)
    c = P("S2", "S2B_T35VLC_2", "2026-06-10T09:50:10Z", scene_cloud_pct=5.0)
    g = prov.group_datatakes([a, b, c])
    assert len(g) == 2 and g[0].item_ids == ["S2B_T34VFH", "S2B_T35VLC"] and g[0].scene_cloud_pct == 30.0


def test_pu_estimate():
    assert prov.estimate_pu("S2", 512, 512) == pytest.approx(5 / 3 * 2, rel=1e-3)
    assert prov.estimate_pu("S1", 512, 512) == pytest.approx(2 / 3 * 2 * 2, rel=1e-3)
    assert prov.estimate_pu("S2", 10, 10) == pytest.approx(0.01 * 5 / 3 * 2, rel=1e-3)   # minimum area factor


# ── pipeline ────────────────────────────────────────────────────────────────
def s2_series(area, cut_from_index=3, n=5, cut=None):
    cut = cut if cut is not None else centre_block(area)
    times = ["2026-06-05", "2026-06-15", "2026-06-25", "2026-07-05", "2026-07-15", "2026-07-25"][:n]
    prods, rasters = [], {}
    for i, t in enumerate(times):
        pid = f"S2_{t}"
        prods.append(P("S2", pid, t + "T09:50:00Z", scene_cloud_pct=5.0))
        rasters[pid] = s2_arr(area["grid"], cut if i >= cut_from_index else None)
    return prods, rasters


def test_s2_change_creates_one_suspected_event(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=5)                               # cut 07-05, confirmed by 07-15 (B)
    res = run(env, FakeProvider(prods, rasters), sensors=("S2",))
    evs = env["conn"].execute("SELECT * FROM sat_change_events").fetchall()
    assert res["status"] == "OK" and len(evs) == 1
    e = evs[0]
    assert e["status"] == "SUSPECTED" and e["classification"] == "POTENTIAL_FOREST_LOSS"
    assert e["confidence"] == "MEDIUM" and e["sensor_basis"] == "S2" and e["evidence_quality"] == "GOOD"
    assert e["changed_area_ha"] == pytest.approx(100 * a["grid"]["pixel_area_ha"], rel=1e-6)
    assert e["changed_area_ha_buffer"] == 0 and e["max_distance_outside_boundary_m"] is None
    gj = json.loads(e["change_geojson"])
    assert gj["features"][0]["properties"]["zone"] == "INSIDE"
    ctx = json.loads(e["gps_context_json"])
    assert ctx["context_label"] == "UNREGISTERED_CHANGE_CANDIDATE"
    th = json.loads(e["thresholds_json"])
    assert th["s2_dnbr_threshold"] == -0.15
    # raw evidence stored with matching sha256
    acq = env["conn"].execute("SELECT * FROM sat_acquisitions WHERE id=?", (e["after_acq_id"],)).fetchone()
    from satellite_monitoring import raster
    assert raster.sha256_bytes(open(acq["raster_path"], "rb").read()) == acq["raster_sha256"]
    assert acq["quicklook_path"].endswith(".png")


def test_change_in_buffer_reported_outside_boundary(env):
    a = make_area(env["conn"])
    inside = a["_inside"] if "_inside" in a else geo.masks(a["geometry"], a["grid"], 100)[0]
    rows = np.where(inside.any(axis=1))[0]
    cols = np.where(inside.any(axis=0))[0]
    cut = block(a, rows[len(rows) // 2], cols[-1] + 2, 7)           # entirely in the buffer ring
    prods, rasters = s2_series(a, n=5, cut=cut)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    e = env["conn"].execute("SELECT * FROM sat_change_events").fetchone()
    assert e["classification"] == "POTENTIAL_CHANGE_OUTSIDE_BOUNDARY"
    assert e["changed_area_ha_inside"] == 0 and e["changed_area_ha_buffer"] >= 0.3
    assert e["max_distance_outside_boundary_m"] >= 60


def test_ongoing_change_updates_same_event(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=6)
    grown = centre_block(a, 14)                                     # later images: bigger, overlapping cut
    rasters["S2_2026-07-25"] = s2_arr(a["grid"], grown)
    prods.append(P("S2", "S2_2026-08-04", "2026-08-04T09:50:00Z", scene_cloud_pct=5.0))
    rasters["S2_2026-08-04"] = s2_arr(a["grid"], grown)              # confirms the growth (B)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    evs = env["conn"].execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1
    hist = json.loads(evs[0]["after_acq_history_json"])
    assert len(hist) >= 3
    assert evs[0]["changed_area_ha"] == pytest.approx(196 * a["grid"]["pixel_area_ha"], rel=1e-6)
    st = [r[0] for r in env["conn"].execute("SELECT status FROM sat_s2_candidates ORDER BY id")]
    assert st.count("CONFIRMED") >= 2 and "TRANSIENT" not in st
    assert {r[0] for r in env["conn"].execute("SELECT event_id FROM sat_s2_candidates WHERE status='CONFIRMED'")} == {evs[0]["id"]}
    # F6 growth: the grown ring is changed in 2 of the last 3 images -> current = union = 196 px
    e = evs[0]
    assert np.load(e["change_mask_path"]).sum() == 196 and np.load(e["union_mask_path"]).sum() == 196
    assert e["union_area_ha"] == pytest.approx(1.96) and e["max_area_ha"] == pytest.approx(1.96)


def test_separate_change_is_a_separate_event(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=6)
    g = a["grid"]
    rows = np.where(geo.masks(a["geometry"], g, 100)[0].any(axis=1))[0]
    cols = np.where(geo.masks(a["geometry"], g, 100)[0].any(axis=0))[0]
    far = block(a, rows[0] + 1, cols[0] + 1, 6)                      # corner, far from the centre cut
    for pid in ("S2_2026-07-15", "S2_2026-07-25"):
        rasters[pid] = s2_arr(g, centre_block(a) | far)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    assert env["conn"].execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 2


def test_idempotent_rerun(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=5)
    fp = FakeProvider(prods, rasters)
    r1 = run(env, fp, sensors=("S2",))
    r2 = run(env, fp, sensors=("S2",))
    c = env["conn"]
    assert r1["new_acquisitions"] == 5 and r2["new_acquisitions"] == 0
    assert len(fp.fetch_calls) == 5                                  # nothing fetched twice
    assert c.execute("SELECT COUNT(*) FROM sat_acquisitions").fetchone()[0] == 5
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM sat_detections").fetchone()[0] == 5
    assert c.execute("SELECT COUNT(*) FROM sat_s2_candidates").fetchone()[0] == 2   # 07-05 confirmed, 07-15 pending


def test_retry_then_error_after_three_attempts(env):
    a = make_area(env["conn"])
    prods = [P("S2", "S2_BAD", "2026-06-05T09:50:00Z", scene_cloud_pct=5.0)]
    fp = FakeProvider(prods, {"S2_BAD": cdse.CdseError("HTTP", "HTTP 500", 500)})
    c = env["conn"]
    for i in range(1, 4):
        res = run(env, fp, sensors=("S2",))
        row = c.execute("SELECT * FROM sat_acquisitions").fetchone()
        assert row["attempts"] == i and res["status"] == "PARTIAL"
        assert row["status"] == ("ERROR" if i == 3 else "PENDING")
    run(env, fp, sensors=("S2",))
    assert len(fp.fetch_calls) == 3                                  # no 4th attempt
    m = c.execute("SELECT null_reason FROM sat_area_metrics WHERE metric='NDVI' AND zone='INSIDE'").fetchone()
    assert "FETCH_ERROR" in m[0]


def test_auth_failure_does_not_burn_attempts(env):
    a = make_area(env["conn"])
    prods = [P("S2", "S2_X", "2026-06-05T09:50:00Z", scene_cloud_pct=5.0)]
    fp = FakeProvider(prods, {"S2_X": cdse.CdseError("AUTH", "HTTP 401", 401)})
    res = run(env, fp, sensors=("S2",))
    assert res["status"] == "FAILED"
    assert env["conn"].execute("SELECT attempts, status FROM sat_acquisitions").fetchone()[:] == (0, "PENDING")


def _fill_request_log(conn, n, pu_each=None):
    now = sdb.iso(sdb.utcnow())
    conn.executemany("INSERT INTO sat_request_log (at_utc, kind, http_status, pu) VALUES (?,?,?,?)",
                     [(now, "PROCESS", 200, pu_each)] * n)
    conn.commit()


def test_request_guard_stops_before_limit(env):
    a = make_area(env["conn"])
    _fill_request_log(env["conn"], int(0.8 * config.DEFAULTS["monthly_request_budget"]))
    prods, rasters = s2_series(a, n=2)
    fp = FakeProvider(prods, rasters)
    res = run(env, fp, sensors=("S2",))
    assert res["status"] == "STOPPED_BY_GUARD" and "request guard" in res["stop_reason"]
    assert fp.discover_calls == [] and fp.fetch_calls == []
    row = env["conn"].execute("SELECT * FROM sat_runs ORDER BY id DESC").fetchone()
    assert row["status"] == "STOPPED_BY_GUARD" and row["stop_reason"]


def test_pu_guard_stops_fetching(env):
    a = make_area(env["conn"])
    budget = config.DEFAULTS["monthly_pu_budget"] * config.DEFAULTS["guard_stop_fraction"]
    _fill_request_log(env["conn"], 1, pu_each=budget - 0.01)        # PU almost exhausted
    prods, rasters = s2_series(a, n=2)
    fp = FakeProvider(prods, rasters)
    res = run(env, fp, sensors=("S2",))
    assert res["status"] == "STOPPED_BY_GUARD" and "PU guard" in res["stop_reason"]
    assert fp.discover_calls == ["S2"] and fp.fetch_calls == []      # discovery allowed, no Process request
    assert env["conn"].execute("SELECT COUNT(*) FROM sat_acquisitions WHERE status='PENDING'").fetchone()[0] == 2


def _s1_series(a, drops, orbits=None):
    """drops: list of bools per acquisition (12-day repeat on one geometry unless orbits given)."""
    days = ["2026-06-01", "2026-06-13", "2026-06-25", "2026-07-07", "2026-07-19", "2026-07-31"]
    m = centre_block(a, 10)
    prods, rasters = [], {}
    for i, d in enumerate(drops):
        pid = f"S1_{d and 'drop' or 'ok'}_{days[i]}"
        o = orbits[i] if orbits else 58
        prods.append(P("S1", pid, days[i] + "T16:03:00Z", orbit_direction="ASCENDING", relative_orbit=o))
        rasters[pid] = s1_arr(a["grid"], m if d else None)
    return prods, rasters


def test_s1_single_drop_is_not_an_event_persistent_drop_is_a_radar_anomaly(env):
    a = make_area(env["conn"])
    prods, rasters = _s1_series(a, [False, False, False, True])
    run(env, FakeProvider(prods, rasters), sensors=("S1",), date_to="2026-07-10")
    c = env["conn"]
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0
    assert c.execute("SELECT outcome FROM sat_detections ORDER BY acquisition_id DESC").fetchone()[0] == "SINGLE_DROP"
    # the next same-geometry image repeats the drop -> RADAR_ANOMALY (timeline only), still no event
    prods, rasters = _s1_series(a, [False, False, False, True, True])
    run(env, FakeProvider(prods, rasters), sensors=("S1",))
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0
    d = c.execute("SELECT * FROM sat_detections ORDER BY acquisition_id DESC").fetchone()
    assert d["outcome"] == "RADAR_ANOMALY" and d["persisted"] == 1 and d["event_id"] is None
    an = c.execute("SELECT * FROM sat_radar_anomalies").fetchall()
    assert len(an) == 1 and an[0]["status"] == "RADAR_ANOMALY" and an[0]["event_id"] is None
    assert an[0]["acquisition_id"] == d["acquisition_id"] and an[0]["relative_orbit"] == 58
    from satellite_monitoring import report
    md = report.render(c, areas.load(c, a["id"]))
    assert "## Radar anomalies (1)" in md and "RADAR_ANOMALY" in md


def _s1_multi(a, plan, mask=None):
    """plan: {(direction, rel_orbit): (first_day 'YYYY-MM-DD', [drop bools])}, 12-day repeat per geometry."""
    from datetime import date, timedelta as td
    m = mask if mask is not None else centre_block(a, 10)
    prods, rasters = [], {}
    for (dirn, ro), (start, drops) in plan.items():
        d0 = date.fromisoformat(start)
        for i, dr in enumerate(drops):
            day = (d0 + td(days=12 * i)).isoformat()
            pid = f"S1_{dirn[0]}{ro}_{day}"
            prods.append(P("S1", pid, day + "T16:03:00Z", orbit_direction=dirn, relative_orbit=ro))
            rasters[pid] = s1_arr(a["grid"], m if dr else None)
    return prods, rasters


THREE_ORBITS = {("ASCENDING", 58): ("2026-06-01", [0, 0, 0, 1, 1]),       # anomaly 07-19
                ("DESCENDING", 80): ("2026-06-04", [0, 0, 0, 1, 1]),      # anomaly 07-22
                ("ASCENDING", 131): ("2026-06-07", [0, 0, 0, 1, 1])}      # anomaly 07-25 -> rule b met


def test_s1_promoted_when_persistent_in_3_acquisitions_on_3_distinct_orbits(env):
    a = make_area(env["conn"])                       # 10x10 px block = 1 ha >= 0.5 ha
    prods, rasters = _s1_multi(a, THREE_ORBITS)
    run(env, FakeProvider(prods, rasters), sensors=("S1",))
    c = env["conn"]
    evs = c.execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1 and evs[0]["sensor_basis"] == "S1" and evs[0]["confidence"] == "LOW"
    hist = json.loads(evs[0]["after_acq_history_json"])
    assert len(hist) == 3                            # all three contributing anomalies are in the event
    an = c.execute("SELECT status, promotion_rule, event_id FROM sat_radar_anomalies ORDER BY sensing_time_utc").fetchall()
    assert [tuple(r) for r in an] == [("PROMOTED", "S1_PERSISTENT_MULTI_ORBIT", evs[0]["id"])] * 3
    last = c.execute("SELECT d.outcome, d.event_id FROM sat_detections d JOIN sat_acquisitions s ON "
                     "s.id=d.acquisition_id WHERE s.sensor='S1' ORDER BY s.sensing_time_utc DESC").fetchone()
    assert tuple(last) == ("EVENT_UPDATED", evs[0]["id"])      # the 3rd anomaly promotes; event built oldest-first


def test_s1_not_promoted_on_only_2_distinct_orbits(env):
    # F3: 3 anomalies within 60 d but on 2 relative orbits -> stays RADAR_ANOMALY (was promoted at min_orbits=2)
    a = make_area(env["conn"])
    prods, rasters = _s1_multi(a, {("ASCENDING", 58): ("2026-06-01", [0, 0, 0, 1, 1, 1]),     # anomalies 07-19, 07-31
                                   ("DESCENDING", 80): ("2026-06-04", [0, 0, 0, 1, 1])})      # anomaly 07-22
    run(env, FakeProvider(prods, rasters), sensors=("S1",))
    c = env["conn"]
    assert c.execute("SELECT COUNT(*) FROM sat_radar_anomalies WHERE status='RADAR_ANOMALY'").fetchone()[0] == 3
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0


def test_rule_b_does_not_duplicate_an_event_from_already_promoted_anomalies(env):
    # F1: after the event exists, a later anomaly elsewhere re-evaluates rule b over the window. The old code
    # started a NEW event from the (already PROMOTED) contributors with the same mask.
    a = make_area(env["conn"])
    prods, rasters = _s1_multi(a, THREE_ORBITS)
    far = block(a, a["grid"]["height"] // 2 - 4, 3, 8)   # 0.64 ha west of the centre block, disjoint
    p4, r4 = _s1_multi(a, {("DESCENDING", 7): ("2026-06-10", [0, 0, 0, 1, 1])}, mask=far)   # anomaly 07-28
    run(env, FakeProvider(prods + p4, {**rasters, **r4}), sensors=("S1",))
    c = env["conn"]
    evs = c.execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1
    masks = {np.load(e["change_mask_path"]).tobytes() for e in evs}
    assert len(masks) == len(evs)                    # no two events with the same mask
    an = c.execute("SELECT relative_orbit, status FROM sat_radar_anomalies ORDER BY sensing_time_utc").fetchall()
    assert [tuple(r) for r in an] == [(58, "PROMOTED"), (80, "PROMOTED"), (131, "PROMOTED"), (7, "RADAR_ANOMALY")]


def test_rule_b_updates_an_open_s2_event_instead_of_creating_a_duplicate(env, monkeypatch):
    # F1: rule-b mask overlapping an open S2 event (outside the 24-day rule-a window) must update that event.
    monkeypatch.setitem(config.DEFAULTS, "s1_anomaly_s2_confirm_days", 1)
    a = make_area(env["conn"])
    p2, r2 = s2_series(a, n=5)                       # S2 event 07-05 / 07-15 on the centre block
    p1, r1 = _s1_multi(a, THREE_ORBITS)
    run(env, FakeProvider(p2 + p1, {**r2, **r1}), sensors=("S1", "S2"))
    c = env["conn"]
    evs = c.execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1 and evs[0]["sensor_basis"] == "S1+S2"
    rules = [r[0] for r in c.execute("SELECT promotion_rule FROM sat_radar_anomalies WHERE status='PROMOTED'")]
    assert "S1_PERSISTENT_MULTI_ORBIT" in rules
    assert {r[0] for r in c.execute("SELECT event_id FROM sat_radar_anomalies")} == {evs[0]["id"]}


def test_s1_not_promoted_on_one_orbit(env, monkeypatch):
    # Within the 60-day window a single geometry yields 2 anomalies (a 3rd pass has the drop in its baseline
    # median), so the orbit condition is isolated with min_acq=2: 2 anomalies on ONE geometry -> no event.
    monkeypatch.setitem(config.DEFAULTS, "s1_promote_min_acq", 2)
    a = make_area(env["conn"])
    prods, rasters = _s1_multi(a, {("ASCENDING", 58): ("2026-06-01", [0, 0, 0, 1, 1, 1])})
    run(env, FakeProvider(prods, rasters), sensors=("S1",))
    c = env["conn"]
    assert c.execute("SELECT COUNT(*) FROM sat_radar_anomalies WHERE status='RADAR_ANOMALY'").fetchone()[0] == 2
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0


def test_s1_not_promoted_below_min_area(env):
    a = make_area(env["conn"])
    small = centre_block(a, 6)                       # 36 px = 0.36 ha: >= min_cluster_ha 0.3, < 0.5 ha
    prods, rasters = _s1_multi(a, THREE_ORBITS, mask=small)
    run(env, FakeProvider(prods, rasters), sensors=("S1",))
    c = env["conn"]
    assert c.execute("SELECT COUNT(*) FROM sat_radar_anomalies WHERE status='RADAR_ANOMALY'").fetchone()[0] == 3
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0


def test_s1_promotion_rules_are_config_driven(env, monkeypatch):
    monkeypatch.setitem(config.DEFAULTS, "s1_promote_min_orbits", 1)          # same series as the test above
    monkeypatch.setitem(config.DEFAULTS, "s1_promote_min_acq", 2)
    a = make_area(env["conn"])
    prods, rasters = _s1_multi(a, {("ASCENDING", 58): ("2026-06-01", [0, 0, 0, 1, 1, 1])})
    run(env, FakeProvider(prods, rasters), sensors=("S1",))
    evs = env["conn"].execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1 and evs[0]["sensor_basis"] == "S1"
    assert json.loads(evs[0]["thresholds_json"])["s1_promote_min_orbits"] == 1


def test_s1_anomaly_before_s2_is_promoted_when_s2_confirms_within_24_days(env):
    a = make_area(env["conn"])
    p1, r1 = _s1_series(a, [False, False, False, True, True])         # anomaly 07-19 (S2 not yet confirmed)
    p2, r2 = s2_series(a, n=6, cut_from_index=4)                      # S2 cut 07-15, confirmed 07-25
    run(env, FakeProvider(p2 + p1, {**r2, **r1}), sensors=("S1", "S2"))
    c = env["conn"]
    evs = c.execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1 and evs[0]["sensor_basis"] == "S1+S2" and evs[0]["confidence"] == "HIGH"
    an = c.execute("SELECT status, promotion_rule, event_id FROM sat_radar_anomalies").fetchone()
    assert tuple(an) == ("PROMOTED", "S2_CONFIRMED", evs[0]["id"])


def test_s1_anomaly_not_promoted_by_s2_more_than_24_days_away(env, monkeypatch):
    monkeypatch.setitem(config.DEFAULTS, "s1_anomaly_s2_confirm_days", 3)   # 07-19 vs S2 07-05/07-15
    a = make_area(env["conn"])
    p2, r2 = s2_series(a, n=5)
    p1, r1 = _s1_series(a, [False, False, False, True, True])
    run(env, FakeProvider(p2 + p1, {**r2, **r1}), sensors=("S1", "S2"))
    c = env["conn"]
    evs = c.execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1 and evs[0]["sensor_basis"] == "S2"
    assert c.execute("SELECT status FROM sat_radar_anomalies").fetchone()[0] == "RADAR_ANOMALY"


def test_s1_drop_on_other_orbit_is_not_compared(env):
    a = make_area(env["conn"])
    # orbit 58 normal x3, then two drops on orbit 131 which has no own history
    prods, rasters = _s1_series(a, [False, False, False, True, True], orbits=[58, 58, 58, 131, 131])
    run(env, FakeProvider(prods, rasters), sensors=("S1",))
    c = env["conn"]
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0
    outs = [r[0] for r in c.execute("SELECT outcome FROM sat_detections ORDER BY acquisition_id")]
    assert outs[3] == "NO_BASELINE"                                  # first image on orbit 131
    assert outs[4] in ("SINGLE_DROP", "NO_CHANGE")                   # compared only with orbit 131


def test_s1_plus_s2_within_24_days_is_high(env):
    a = make_area(env["conn"])
    p2, r2 = s2_series(a, n=5)                                       # S2 cut 07-05, confirmed 07-15
    p1, r1 = _s1_series(a, [False, False, False, True, True])         # S1 persistent 07-07/07-19
    run(env, FakeProvider(p2 + p1, {**r2, **r1}), sensors=("S1", "S2"))
    evs = env["conn"].execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1 and evs[0]["sensor_basis"] == "S1+S2" and evs[0]["confidence"] == "HIGH"


def test_low_valid_pct_never_used_as_after_or_baseline(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=4)
    half = s2_arr(a["grid"], centre_block(a))
    half[: a["grid"]["height"] * 3 // 4, :, 4] = 9.0                  # 75 % cloud pixels
    rasters["S2_2026-07-05"] = half
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    c = env["conn"]
    out = c.execute("SELECT d.outcome FROM sat_detections d JOIN sat_acquisitions s ON s.id=d.acquisition_id "
                    "WHERE s.product_id='S2_2026-07-05'").fetchone()[0]
    assert out == "NOT_USABLE"
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0


def test_report_markdown_labels_layers_and_nulls(env):
    from satellite_monitoring import report
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=5)
    prods.append(P("S2", "S2_CLOUD", "2026-07-08T09:50:00Z", scene_cloud_pct=99.0))
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    md = report.render(env["conn"], areas.load(env["conn"], a["id"]))
    for s in ("**RAW**", "**PROCESSED**", "**INTERPRETATION**", "**HUMAN**", "Contains modified Copernicus Sentinel data",
              "SKIPPED_CLOUD", "NULL (SKIPPED_CLOUD", "suspected change", "PENDING_CONFIRMATION → candidate #1",
              "Optical change candidates (2)", "| CONFIRMED |"):
        assert s in md, s
    assert "violation" not in md.lower() and "illegal" not in md.lower()


def test_append_only_triggers(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=1)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    c = env["conn"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        c.execute("DELETE FROM sat_acquisitions")
    with pytest.raises(sqlite3.IntegrityError, match="only PENDING"):
        c.execute("UPDATE sat_acquisitions SET status='ERROR'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        c.execute("DELETE FROM sat_request_log")


def test_concurrent_run_is_locked(env):
    with pipeline.RunLock(env["tmp"] / "lock"):
        assert pipeline.lock_state(env["tmp"] / "lock")["locked"] is True
        with pytest.raises(pipeline.Locked):
            run(env, FakeProvider([], {}))
    assert pipeline.lock_state(env["tmp"] / "lock")["locked"] is False


def test_area_dedup_and_stop_keeps_history(env):
    c = env["conn"]
    a1, new1 = areas.create(c, "SECTOR", "1", "TST-001", SQUARE, "test")
    a2, new2 = areas.create(c, "SECTOR", "1", "TST-001", SQUARE, "test")
    assert new1 and not new2 and a1 == a2
    assert areas.stop(c, a1)
    a3, new3 = areas.create(c, "SECTOR", "1", "TST-001", SQUARE, "test")
    assert new3 and a3 != a1
    assert c.execute("SELECT COUNT(*) FROM sat_monitored_areas").fetchone()[0] == 2
    with pytest.raises(areas.AreaError, match="outside Latvia"):
        areas.create(c, "SECTOR", "9", "S-001", geo.sector_boundary_to_polygon(
            [[58.903753, 32.740448], [58.90377, 32.740485], [58.9038, 32.7404]]), "test")


# ── operational context window ──────────────────────────────────────────────
def test_gps_context_window_and_zones(env):
    f = sqlite3.connect(env["forest"])
    cy, cx = LAT + DLAT / 2, LON + DLON / 2                          # centre of the square
    buf_lon = LON + DLON + 50 / (111320 * np.cos(np.radians(LAT)))     # 50 m east of the boundary
    far_lon = LON + DLON + 500 / (111320 * np.cos(np.radians(LAT)))
    f.executemany("INSERT INTO session_track_points (id, session_id, latitude, longitude, recorded_at) VALUES (?,?,?,?,?)", [
        (1, 7, cy, cx, "2026-06-20 10:00:00 UTC"),      # inside, in window
        (2, 7, cy, buf_lon, "2026-06-20 10:05:00 UTC"),  # buffer, in window
        (3, 8, cy, far_lon, "2026-06-20 10:05:00 UTC"),  # too far
        (4, 9, cy, cx, "2026-05-01 10:00:00 UTC"),       # before window
    ])
    f.executemany("INSERT INTO work_sessions (id, sector, latitude, longitude, check_in_time, finish_time) VALUES (?,?,?,?,?,?)", [
        (11, "TST-001", None, None, "2026-06-19 06:00:00 UTC", "2026-06-19 15:00:00 UTC"),
        (12, "OTHER", None, None, "2026-06-19 06:00:00 UTC", ""),                 # other sector, far
        (13, "TST-001", None, None, "2026-04-01 06:00:00 UTC", "2026-04-01 15:00:00 UTC"),  # ended before window
        (14, "OTHER", cy, cx, "2026-06-01 06:00:00 UTC", "2026-06-25 06:00:00 UTC"),  # other sector, checked in inside
    ])
    f.execute("INSERT INTO timber_movements (id, sector, created_at, is_demo) VALUES (1, 'TST-001', '2026-06-21 08:00:00 UTC', 1)")
    f.commit()
    f.close()
    area = {"source": "SECTOR", "name": "TST-001", "geometry": SQUARE}
    ctx = context.operational_context(area, "2026-06-10T00:00:00Z", "2026-07-01T00:00:00Z", 100)
    s = ctx["sources"]
    assert s["worker_gps_track_points"]["inside"] == 1 and s["worker_gps_track_points"]["buffer"] == 1
    assert s["worker_gps_track_points"]["session_ids"] == [7]
    assert s["work_sessions"]["session_ids"] == [11, 14]
    assert s["timber_movements"]["count"] == 1 and s["timber_movements"]["demo_rows"] == 1
    assert ctx["context_label"] == "CHANGE_DURING_REGISTERED_WORK"
    quiet = context.operational_context(area, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z", 100)
    assert quiet["context_label"] == "UNREGISTERED_CHANGE_CANDIDATE" and quiet["activity_records"] == 0
    lvm = context.operational_context({**area, "source": "LVM_GEO"}, "2026-06-10T00:00:00Z", "2026-07-01T00:00:00Z", 100)
    assert lvm["sources"]["field_photos"]["count"] is None and lvm["sources"]["field_photos"]["reason"]


# ── CDSE client: backoff, counting, no secret leakage ───────────────────────
class _R:
    def __init__(self, status, body=None, headers=None, content=b""):
        self.status_code, self._body, self.headers, self.content = status, body or {}, headers or {}, content
    def json(self):
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.responses.pop(0)


def test_cdse_backoff_counts_every_request_and_hides_secrets(monkeypatch):
    monkeypatch.setenv("SENTINEL_CLIENT_ID", "id-value")
    monkeypatch.setenv("SENTINEL_CLIENT_SECRET", "SECRET-VALUE-XYZ")
    s = _Session([_R(200, {"access_token": "TOKEN-ABC", "expires_in": 3600}),
                  _R(429, headers={"Retry-After": "0"}), _R(503), _R(200, content=b"tif")])
    seen, sleeps = [], []
    c = cdse.Client(session=s, sleep=sleeps.append, on_request=lambda k, st, r: seen.append((k, st)))
    r = c.post_json("PROCESS", cdse.PROCESS_URL, {"x": 1})
    assert r.content == b"tif" and seen == [("PROCESS", 429), ("PROCESS", 503), ("PROCESS", 200)]
    assert len([x for x in sleeps if x >= 0]) >= 2
    s2 = _Session([_R(400, {"error": {"message": "bad bbox"}})])
    c._session = s2
    with pytest.raises(cdse.CdseError) as ei:
        c.post_json("PROCESS", cdse.PROCESS_URL, {})
    msg = str(ei.value)
    assert "bad bbox" in msg and "TOKEN-ABC" not in msg and "SECRET-VALUE-XYZ" not in msg


def test_cdse_not_configured(monkeypatch):
    monkeypatch.delenv("SENTINEL_CLIENT_ID", raising=False)
    monkeypatch.delenv("SENTINEL_CLIENT_SECRET", raising=False)
    with pytest.raises(cdse.CdseError) as ei:
        cdse.Client(session=_Session([])).token()
    assert ei.value.kind == "NOT_CONFIGURED"


def test_request_body_is_clipped_grid_and_records_s1_processing():
    grid = geo.make_grid(SQUARE, 100, 10)
    sh = prov.SentinelHubProvider(client=None)
    b = sh.request_body("S1", P("S1", "x", "2026-06-01T16:03:00Z", orbit_direction="ASCENDING", relative_orbit=58), grid)
    src = b["input"]["data"][0]
    assert b["input"]["bounds"]["bbox"] == grid["bbox"] and b["output"]["width"] == grid["width"]
    assert src["processing"] == {"backCoeff": "GAMMA0_ELLIPSOID", "orthorectify": True, "demInstance": "COPERNICUS_30"}
    assert src["dataFilter"]["orbitDirection"] == "ASCENDING" and src["dataFilter"]["acquisitionMode"] == "IW"
    assert "FLOAT32" in b["evalscript"] and b["output"]["responses"][0]["format"]["type"] == "image/tiff"


def test_decode_tiff_roundtrip():
    tifffile = pytest.importorskip("tifffile")      # worker venv only
    from satellite_monitoring import raster
    arr = np.random.default_rng(1).random((7, 9, 6)).astype(np.float32)
    b = io.BytesIO()
    tifffile.imwrite(b, arr, photometric="minisblack", planarconfig="contig")
    out = raster.decode_tiff(b.getvalue(), expected_shape=(7, 9), bands=6)
    assert np.allclose(out, arr)
    b2 = io.BytesIO()
    tifffile.imwrite(b2, np.moveaxis(arr, -1, 0), photometric="minisblack", planarconfig="separate")
    assert np.allclose(raster.decode_tiff(b2.getvalue(), expected_shape=(7, 9), bands=6), arr)


def test_data_files_are_private(env):
    import os
    import stat
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=4)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    root = env["tmp"] / "sat"
    mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)
    assert mode(root) == 0o700
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        assert mode(dirpath) == 0o700, dirpath
        for f in filenames:
            assert mode(os.path.join(dirpath, f)) == 0o600, f
            seen += 1
    assert seen >= 9          # db (+wal/shm), 4 tif, 4 png, event mask, lock


# ── Stage 1 fixes: A (cloud dilation), B (confirm/transient), F (exclusion), G (uniform drop) ─────
def test_cloud_mask_is_dilated_by_three_pixels():
    from satellite_monitoring import config as cfgmod
    g = {"height": 30, "width": 30}
    a = s2_arr(g)
    a[15, 15, 4] = 9.0                                               # one cloud pixel
    L = met.s2_layers(a, cfgmod.DEFAULTS)
    assert not L["valid"][12:19, 12:19].any()                        # 3 px ring (7x7) invalid
    assert L["valid"][11, 15] and L["valid"][15, 19]                 # 4th pixel out is valid again
    assert int(L["cloud_ring"].sum()) == 48
    L0 = met.s2_layers(a, {**cfgmod.DEFAULTS, "s2_cloud_dilate_px": 0})
    assert L0["valid"][14, 15] and not L0["valid"][15, 15]


def test_drop_at_cloud_edge_is_masked_not_detected(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=5, cut_from_index=99)            # no real change
    c = centre_block(a, 6)
    edge = det.dilate1(det.dilate1(c)) & ~c                          # 2-px halo around a cloud
    for pid in ("S2_2026-07-05",):
        x = s2_arr(a["grid"], edge)
        x[c, 4] = 9.0
        rasters[pid] = x
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    cc = env["conn"]
    assert cc.execute("SELECT COUNT(*) FROM sat_s2_candidates").fetchone()[0] == 0
    assert cc.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0


def test_single_date_dip_becomes_transient_not_event(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=5, cut_from_index=99)
    rasters["S2_2026-07-05"] = s2_arr(a["grid"], centre_block(a))    # dip on one date only
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    cc = env["conn"]
    cand = cc.execute("SELECT * FROM sat_s2_candidates").fetchall()
    assert len(cand) == 1 and cand[0]["status"] == "TRANSIENT"
    res = json.loads(cand[0]["details_json"])["resolution"]
    assert res["decision"] == "TRANSIENT" and res["persist_fraction"] == 0
    assert cc.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0
    with pytest.raises(sqlite3.DatabaseError):                       # recorded, never rewritten/deleted
        cc.execute("UPDATE sat_s2_candidates SET status='CONFIRMED' WHERE id=?", (cand[0]["id"],))
    with pytest.raises(sqlite3.DatabaseError):
        cc.execute("DELETE FROM sat_s2_candidates")


def test_candidate_waits_while_next_image_is_cloudy_there(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=6)                               # cut 07-05 ...
    x = s2_arr(a["grid"], centre_block(a))
    x[centre_block(a, 4), 4] = 9.0                                   # 07-15: cloud (+3 px) over the cut
    rasters["S2_2026-07-15"] = x
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    cc = env["conn"]
    first = cc.execute("SELECT * FROM sat_s2_candidates ORDER BY id").fetchone()
    assert first["status"] == "CONFIRMED"
    assert first["resolved_by_acq_id"] == cc.execute(
        "SELECT id FROM sat_acquisitions WHERE product_id='S2_2026-07-25'").fetchone()[0]
    assert cc.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 1


def test_uniform_drop_is_atmospheric_and_never_baseline_or_after(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=5, cut_from_index=99)
    haze = s2_arr(a["grid"])
    haze[..., 0], haze[..., 1], haze[..., 3] = 0.06, 0.22, 0.12      # whole scene darker in NIR
    rasters["S2_2026-07-05"] = haze
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    cc = env["conn"]
    d = cc.execute("SELECT d.* FROM sat_detections d JOIN sat_acquisitions s ON s.id=d.acquisition_id "
                   "WHERE s.product_id='S2_2026-07-05'").fetchone()
    assert d["outcome"] == "UNIFORM_DROP_ATMOSPHERIC"
    det_ = json.loads(d["details_json"])
    assert det_["classification"] == "POSSIBLE_SEASONAL_OR_ENVIRONMENTAL" and det_["uniform_drop"]["is_uniform"]
    assert cc.execute("SELECT COUNT(*) FROM sat_s2_candidates").fetchone()[0] == 0
    assert cc.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0
    hazy_id = d["acquisition_id"]
    for (b,) in cc.execute("SELECT baseline_acq_ids FROM sat_detections WHERE baseline_acq_ids IS NOT NULL"):
        assert hazy_id not in json.loads(b)


def test_local_cut_is_not_uniform():
    g = {"height": 40, "width": 40}
    zone = np.ones((40, 40), dtype=bool)
    base = met.s2_layers(s2_arr(g))
    m = np.zeros((40, 40), dtype=bool); m[5:25, 5:25] = True         # 25 % of the area cut
    ch, comp, d = det.s2_change(met.s2_layers(s2_arr(g, m)), [base], zone)
    u = det.uniform_drop(ch, comp, d)
    assert u["drop_fraction"] == pytest.approx(0.25) and not u["is_uniform"]


def test_evidence_series_nulls_and_review_sheet(env, monkeypatch):
    from satellite_monitoring import evidence
    monkeypatch.setattr(evidence.raster, "decode_tiff", decoder)        # stored fake rasters are .npy bytes
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=5)
    cloudy = s2_arr(a["grid"])
    cloudy[centre_block(a, 16), 4] = 9.0                                 # cloud over the (later) cut only
    rasters["S2_2026-06-15"] = cloudy
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    c = env["conn"]
    ev = dict(c.execute("SELECT * FROM sat_change_events").fetchone())
    out = evidence.event_review(c, areas.load(c, a["id"]), ev, env["tmp"] / "review")
    by_day = {r["time"][:10]: r for r in out["S2"]}
    assert by_day["2026-06-15"]["NDVI"] is None and by_day["2026-06-15"]["valid_pct"] == 0.0   # NULL, not 0
    assert by_day["2026-06-05"]["NDVI"] > by_day["2026-07-15"]["NDVI"]
    assert [r for r, _ in out["roles"]][-1] == "after" and out["roles"][0][0] in ("baseline", "last clear")
    p = env["tmp"] / "review" / f"event_{ev['id']}_review.png"
    assert p.exists() and p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and (p.stat().st_mode & 0o777) == 0o600


def test_area_source_migration_adds_eval_bbox(tmp_path):
    """An old DB (CHECK only SECTOR/LVM_GEO) is rebuilt on connect; rows, ids and FKs survive."""
    old = SCHEMA_OLD = sdb.SCHEMA.replace("CHECK (source IN ('SECTOR','LVM_GEO','EVAL_BBOX'))",
                                          "CHECK (source IN ('SECTOR','LVM_GEO'))")
    assert SCHEMA_OLD != sdb.SCHEMA
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.executescript(old)
    c.execute("INSERT INTO sat_monitored_areas (id, source, source_ref, name, geometry_geojson, area_ha, buffer_m,"
              " grid_json, added_by, added_at_utc) VALUES (7,'SECTOR','26','BIK-001','{}',50,100,'{}','t','x')")
    c.execute("INSERT INTO sat_acquisitions (monitored_area_id, sensor, product_id, sensing_time_utc, status)"
              " VALUES (7,'S2','P1','2026-08-01T00:00:00Z','PENDING')")
    c.commit()
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO sat_monitored_areas (source, source_ref, name, geometry_geojson, area_ha, buffer_m,"
                  " grid_json, added_by, added_at_utc) VALUES ('EVAL_BBOX','k','K','{}',1,100,'{}','t','x')")
    c.close()
    conn = sdb.connect(p)                                                # migrates
    assert "'EVAL_BBOX'" in conn.execute("SELECT sql FROM sqlite_master WHERE name='sat_monitored_areas'").fetchone()[0]
    assert conn.execute("SELECT id, name FROM sat_monitored_areas").fetchall()[0][:] == (7, "BIK-001")
    assert conn.execute("SELECT monitored_area_id FROM sat_acquisitions").fetchone()[0] == 7
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    aid, created = areas.create(conn, "EVAL_BBOX", "kekava-test", "Kekava test", SQUARE, "test")
    assert created and areas.load(conn, aid)["source"] == "EVAL_BBOX"
    conn.close()
    sdb.connect(p).close()                                               # idempotent


def test_positive_control_helpers():
    from satellite_monitoring import positive_control as pc
    assert pc.wilson(0, 0) == (None, None)
    lo, hi = pc.wilson(9, 18)
    assert lo < 0.5 < hi and 0.25 < lo and hi < 0.75
    assert pc.wilson(18, 18)[1] == 1.0
    m = np.zeros((7, 7), bool)
    m[1:6, 1:6] = True                                                   # 5x5 -> interior 3x3 (-1 px = -10 m)
    assert int(pc._erode(m).sum()) == 9
    g = geo.make_grid(SQUARE, 0, 10.0)
    r = pc._raster(SQUARE, g)
    assert r.dtype == bool and 0.8 < r.mean() <= 1.0


# ── F2: classification on the onset month ─────────────────────────────────
def _s2_dates(area, dates, cut_from):
    prods, rasters = [], {}
    for i, t in enumerate(dates):
        pid = f"S2_{t}"
        prods.append(P("S2", pid, t + "T09:50:00Z", scene_cloud_pct=5.0))
        rasters[pid] = s2_arr(area["grid"], centre_block(area) if i >= cut_from else None)
    return prods, rasters


def test_class_from_onset_month_latest_month_only_a_caveat(env):
    a = make_area(env["conn"])
    prods, rasters = _s2_dates(a, ["2026-08-26", "2026-09-05", "2026-09-15", "2026-09-25", "2026-10-05"], 3)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    evs = env["conn"].execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1
    e = evs[0]
    assert e["first_after_time_utc"].startswith("2026-09-25") and e["last_after_time_utc"].startswith("2026-10-05")
    assert e["classification"] == "POTENTIAL_FOREST_LOSS"          # was POSSIBLE_SEASONAL (latest month = Oct)
    assert e["seasonal_caveat"].startswith("Latest after-image 2026-10-05 (not used for the class)")


def test_onset_in_october_is_seasonal(env):
    a = make_area(env["conn"])
    prods, rasters = _s2_dates(a, ["2026-09-05", "2026-09-15", "2026-09-25", "2026-10-05", "2026-10-15"], 3)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    e = env["conn"].execute("SELECT * FROM sat_change_events").fetchone()
    assert e["classification"] == "POSSIBLE_SEASONAL_OR_ENVIRONMENTAL"
    assert e["seasonal_caveat"].startswith("After-image is from Oct")
    assert "Latest after-image" in e["seasonal_caveat"]            # 10-15 also seasonal, noted separately


# ── F3: forest mask ─────────────────────────────────────────────────────────
def _west_half_vmd(env, monkeypatch, a):
    w, s, e, n = a["grid"]["bbox"]
    mid = (w + e) / 2
    p = env["tmp"] / "vmd_west.sqlite"
    make_vmd(p, [{"type": "Polygon", "coordinates": [[[w - 0.01, s - 0.01], [mid, s - 0.01], [mid, n + 0.01],
                                                      [w - 0.01, n + 0.01], [w - 0.01, s - 0.01]]]}])
    monkeypatch.setenv("SAT_FOREST_DB", str(p))
    monkeypatch.setenv("SAT_FOREST_DB_VERSION", "test-vmd-west")


def test_forest_mask_excludes_non_forest_pixels_and_stores_share(env, monkeypatch):
    a = make_area(env["conn"])
    _west_half_vmd(env, monkeypatch, a)
    g = a["grid"]
    east = block(a, g["height"] // 2 - 5, g["width"] - 14, 10)        # cut on non-forest land (east half)
    prods, rasters = s2_series(a, n=5, cut=east)
    res = run(env, FakeProvider(prods, rasters), sensors=("S2",))
    c = env["conn"]
    assert res["status"] == "OK"
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0
    m = c.execute("SELECT * FROM sat_area_masks").fetchone()
    assert m["kind"] == "VMD_FOREST" and m["n_compartments"] == 1
    assert 0.35 < m["non_forest_share_zone"] < 0.65                   # about half of INSIDE+BUFFER is not forest
    assert m["pixels_analysed"] > 0 and m["source_version"].startswith("test-vmd-west")
    assert res["forest_mask"][a["id"]]["non_forest_share_zone"] == m["non_forest_share_zone"]


def test_forest_mask_keeps_changes_inside_forest(env, monkeypatch):
    a = make_area(env["conn"])
    _west_half_vmd(env, monkeypatch, a)
    g = a["grid"]
    west = block(a, g["height"] // 2 - 5, 4, 10)
    prods, rasters = s2_series(a, n=5, cut=west)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    assert env["conn"].execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 1


def test_forest_mask_unavailable_area_not_analysed(env, monkeypatch):
    monkeypatch.setenv("SAT_FOREST_DB", str(env["tmp"] / "missing.sqlite"))
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=5)
    res = run(env, FakeProvider(prods, rasters), sensors=("S2",))
    c = env["conn"]
    assert res["status"] == "PARTIAL"
    assert any("forest mask unavailable" in e["error"] for e in res["errors"])
    assert c.execute("SELECT COUNT(*) FROM sat_detections").fetchone()[0] == 0     # never "all pixels"
    assert c.execute("SELECT COUNT(*) FROM sat_acquisitions WHERE status='OK'").fetchone()[0] == 5


def test_forest_mask_is_config_driven(env, monkeypatch):
    monkeypatch.setitem(config.DEFAULTS, "forest_mask", False)
    a = make_area(env["conn"])
    _west_half_vmd(env, monkeypatch, a)
    g = a["grid"]
    east = block(a, g["height"] // 2 - 5, g["width"] - 14, 10)
    prods, rasters = s2_series(a, n=5, cut=east)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    c = env["conn"]
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM sat_area_masks").fetchone()[0] == 0


def test_forest_mask_cached_and_sha_checked(env, monkeypatch):
    a = make_area(env["conn"])
    _west_half_vmd(env, monkeypatch, a)
    inside, buffer, _ = geo.masks(a["geometry"], a["grid"], a["buffer_m"])
    from satellite_monitoring import forest_mask
    m1, meta1 = forest_mask.get(env["conn"], a, inside, buffer)
    m2, meta2 = forest_mask.get(env["conn"], a, inside, buffer)
    assert (m1 == m2).all() and meta1["mask_sha256"] == meta2["mask_sha256"]
    assert env["conn"].execute("SELECT COUNT(*) FROM sat_area_masks").fetchone()[0] == 1


# ── F4: positive-control spring test ────────────────────────────────────────
def test_eval_spring_uses_absolute_bare_soil_test():
    from satellite_monitoring import positive_control as pc
    cfg = config.DEFAULTS
    v = np.ones((5, 5), bool)
    ref = np.ones((5, 5), bool)
    bare = {"NDVI": np.full((5, 5), 0.35), "NBR": np.full((5, 5), 0.05)}
    rec = {"valid_pct": 100.0}
    assert pc.cut_test(bare, v, ref, rec, True, cfg) is True and rec["cut_test"] == "ABSOLUTE_BARE_SOIL"
    forest = {"NDVI": np.full((5, 5), 0.75), "NBR": np.full((5, 5), 0.45)}
    rec = {"valid_pct": 100.0}
    assert pc.cut_test(forest, v, ref, rec, True, cfg) is False
    # summer: the same bare stand vs a (here identical) reference is NOT cut -> relative test is used
    rec = {"valid_pct": 100.0}
    assert pc.cut_test(bare, v, ref, rec, False, cfg) is False and rec["cut_test"] == "STAND_MINUS_REFERENCE"
    rec = {"valid_pct": 10.0}
    assert pc.cut_test(bare, v, ref, rec, True, cfg) is None


def test_change_locations_merge_overlapping_masks():
    from satellite_monitoring import positive_control as pc
    m = [np.zeros((10, 10), bool) for _ in range(4)]
    m[0][0:4, 0:4] = m[1][0:4, 0:4] = True               # identical
    m[2][2:5, 2:5] = True                                # overlaps m0 by 4/9 >= 30 %
    m[3][8:10, 8:10] = True
    assert pc.change_locations(m) == [[0, 1, 2], [3]]


# ── F6: current mask vs union (history) ─────────────────────────────────────
def _s2_masks(area, plan):
    """plan: [(date, mask or None)]"""
    prods, rasters = [], {}
    for t, m in plan:
        pid = f"S2_{t}"
        prods.append(P("S2", pid, t + "T09:50:00Z", scene_cloud_pct=5.0))
        rasters[pid] = s2_arr(area["grid"], m)
    return prods, rasters


def _core_and_edge(a):
    core = centre_block(a, 10)
    edge = np.roll(core, 10, axis=1) & ~core
    edge[:, :] &= np.roll(core, 10, axis=1)
    edge &= np.cumsum(edge, axis=1) <= 4                              # 4 px wide strip right of the core
    return core, edge


def test_f6_recovered_pixels_drop_out_of_the_current_mask(env):
    a = make_area(env["conn"])
    core, edge = _core_and_edge(a)
    assert edge.sum() == 40
    prods, rasters = _s2_masks(a, [("2026-06-05", None), ("2026-06-15", None), ("2026-06-25", None),
                                   ("2026-07-05", core | edge), ("2026-07-15", core | edge),
                                   ("2026-07-25", core), ("2026-08-04", core)])
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    e = env["conn"].execute("SELECT * FROM sat_change_events").fetchone()
    cur, uni = np.load(e["change_mask_path"]), np.load(e["union_mask_path"])
    assert uni.sum() == 140 and (cur == core).all()                   # edge: changed only 1 of the last 3
    assert e["changed_area_ha"] == pytest.approx(1.0) and e["n_changed_pixels"] == 100
    assert e["union_area_ha"] == pytest.approx(1.4) and e["max_area_ha"] == pytest.approx(1.4)
    info = json.loads(e["current_mask_json"])
    assert info["S2"]["keep_px"] == 100 and info["S2"]["drop_px"] == 40
    assert json.loads(e["change_geojson"])["features"][0]["properties"]["area_ha"] == pytest.approx(1.0)


def test_f6_full_recovery_leaves_zero_current_area_but_keeps_history(env):
    a = make_area(env["conn"])
    core = centre_block(a, 10)
    prods, rasters = _s2_masks(a, [("2026-06-05", None), ("2026-06-15", None), ("2026-06-25", None),
                                   ("2026-07-05", core), ("2026-07-15", core),
                                   ("2026-07-25", None), ("2026-08-04", None)])
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    e = env["conn"].execute("SELECT * FROM sat_change_events").fetchone()
    assert e["changed_area_ha"] == 0 and e["n_changed_pixels"] == 0 and np.load(e["change_mask_path"]).sum() == 0
    assert e["union_area_ha"] == pytest.approx(1.0) and e["max_area_ha"] == pytest.approx(1.0)
    assert json.loads(e["current_mask_json"])["evaluated_up_to"].startswith("2026-08-04")


def test_f6_pixels_without_enough_observations_are_kept(env):
    # confirmed change, then only cloudy images: undecided pixels stay in the current mask (missing != recovered)
    a = make_area(env["conn"])
    core = centre_block(a, 10)
    prods, rasters = _s2_masks(a, [("2026-06-05", None), ("2026-06-15", None), ("2026-06-25", None),
                                   ("2026-07-05", core), ("2026-07-15", core)])
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    e = env["conn"].execute("SELECT * FROM sat_change_events").fetchone()
    assert e["n_changed_pixels"] == 100


def test_f6_mixed_sensors_radar_keeps_what_optics_call_recovered(env):
    # S2: cut on the block 07-05/07-15, recovered 07-25/08-04 (e.g. green regrowth or a mown field).
    # S1: persistent VH drop on the LEFT half 07-07/07-19/07-31 -> attached by rule a (S1+S2 event).
    a = make_area(env["conn"])
    blk = centre_block(a, 10)
    left = blk & (np.cumsum(blk, axis=1) <= 5)
    p2, r2 = _s2_masks(a, [("2026-06-05", None), ("2026-06-15", None), ("2026-06-25", None),
                           ("2026-07-05", blk), ("2026-07-15", blk), ("2026-07-25", None), ("2026-08-04", None)])
    p1, r1 = _s1_multi(a, {("ASCENDING", 58): ("2026-06-01", [0, 0, 0, 1, 1, 1])}, mask=left)
    run(env, FakeProvider(p2 + p1, {**r2, **r1}), sensors=("S1", "S2"))
    evs = env["conn"].execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1 and evs[0]["sensor_basis"] == "S1+S2"
    cur = np.load(evs[0]["change_mask_path"])
    right = blk & ~left
    assert not (cur & right).any()                                    # right half: S1 never, S2 recovered -> out
    assert not (cur & ~left).any() and (cur & left).sum() >= 40       # left half kept by S1 (speckle filter
    info = json.loads(evs[0]["current_mask_json"])                    # softens the block edge by a few px)
    assert info["S1"]["keep_px"] == int(cur.sum()) and info["S2"]["keep_px"] == 0 and info["S2"]["drop_px"] == 100


def test_f6_columns_migrate_on_an_existing_db(tmp_path):
    p = tmp_path / "old.db"
    c = sdb.connect(p)
    for col, _ in sdb.EVENT_F6_COLUMNS:
        c.execute(f"ALTER TABLE sat_change_events DROP COLUMN {col}")
    c.commit()
    c.close()
    c = sdb.connect(p)                                                # re-open: columns added back, idempotent
    have = {r[1] for r in c.execute("PRAGMA table_info(sat_change_events)")}
    assert {col for col, _ in sdb.EVENT_F6_COLUMNS} <= have
    c.close()
    sdb.connect(p).close()


# ── detection generations (redetect, supersede, append-only) ────────────────
def _event_run(env):
    a = make_area(env["conn"])
    prods, rasters = s2_series(a, n=5)
    p1, r1 = _s1_series(a, [False, False, False, True, True])
    run(env, FakeProvider(prods + p1, {**rasters, **r1}), sensors=("S1", "S2"))
    return a


def test_redetect_supersedes_old_rows_and_creates_a_new_generation(env):
    from satellite_monitoring import redetect, report
    a = _event_run(env)
    c = env["conn"]
    before = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in sdb.DETECTION_TABLES}
    acq_before = c.execute("SELECT COUNT(*), SUM(attempts) FROM sat_acquisitions").fetchone()
    req_before = c.execute("SELECT COUNT(*) FROM sat_request_log").fetchone()[0]
    res = redetect.redetect(c, [a["id"]], "test", "abc123", decoder=decoder, lock_file=env["tmp"] / "lock")
    assert res["status"] == "OK" and res["requests"] == 0 and res["pu"] == 0
    assert res["superseded"] == before
    for t in sdb.DETECTION_TABLES:                                    # old rows kept, new rows added
        old = c.execute(f"SELECT COUNT(*) FROM {t} WHERE superseded_by_generation=?", (res["generation"],)).fetchone()[0]
        cur = c.execute(f"SELECT COUNT(*) FROM {t} WHERE superseded_at_utc IS NULL").fetchone()[0]
        assert old == before[t] and cur == before[t], t              # same inputs -> same number of rows
    assert c.execute("SELECT COUNT(*), SUM(attempts) FROM sat_acquisitions").fetchone() == acq_before
    assert c.execute("SELECT COUNT(*) FROM sat_request_log").fetchone()[0] == req_before
    g = c.execute("SELECT * FROM sat_detection_generations").fetchone()
    assert g["status"] == "OK" and g["code_version"] == "abc123" and json.loads(g["superseded_counts_json"]) == before
    md = report.render(c, areas.load(c, a["id"]))
    assert md.count("### Event #") == 1                               # only the current generation is reported
    # idempotent detection: a normal run afterwards does not re-detect anything
    n = c.execute("SELECT COUNT(*) FROM sat_detections").fetchone()[0]
    run(env, FakeProvider([], {}), sensors=("S1", "S2"))
    assert c.execute("SELECT COUNT(*) FROM sat_detections").fetchone()[0] == n


def test_superseded_rows_are_frozen_and_nothing_can_be_deleted(env):
    from satellite_monitoring import redetect
    a = _event_run(env)
    c = env["conn"]
    redetect.redetect(c, [a["id"]], "test", decoder=decoder, lock_file=env["tmp"] / "lock")
    for t in sdb.DETECTION_TABLES:
        rid = c.execute(f"SELECT {'id'} FROM {t} WHERE superseded_at_utc IS NOT NULL LIMIT 1").fetchone()
        if rid is None:
            continue
        with pytest.raises(sqlite3.IntegrityError, match="frozen|only PENDING|only RADAR_ANOMALY"):
            c.execute(f"UPDATE {t} SET monitored_area_id=monitored_area_id WHERE id=?", (rid[0],))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            c.execute(f"DELETE FROM {t} WHERE id=?", (rid[0],))
    # a CONFIRMED candidate still cannot be edited (only superseded)
    cid = c.execute("SELECT id FROM sat_s2_candidates WHERE status='CONFIRMED' AND superseded_at_utc IS NULL").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="only PENDING"):
        c.execute("UPDATE sat_s2_candidates SET event_id=NULL WHERE id=?", (cid,))


def test_redetect_refuses_when_a_human_decided(env):
    from satellite_monitoring import redetect
    a = _event_run(env)
    c = env["conn"]
    c.execute("UPDATE sat_change_events SET status='REVIEW_CONFIRMED', reviewed_by='owner'")
    c.commit()
    with pytest.raises(redetect.Refused, match="human decision"):
        redetect.redetect(c, [a["id"]], "test", decoder=decoder, lock_file=env["tmp"] / "lock")
    assert c.execute("SELECT COUNT(*) FROM sat_change_events WHERE superseded_at_utc IS NOT NULL").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM sat_detection_generations").fetchone()[0] == 0


def test_redetect_cli_needs_yes():
    from satellite_monitoring import redetect
    assert redetect.main(["--area", "1", "--reason", "x"]) == 2


OLD_DET = """CREATE TABLE sat_detections (acquisition_id INTEGER PRIMARY KEY REFERENCES sat_acquisitions(id),
    monitored_area_id INTEGER NOT NULL, sensor TEXT NOT NULL, ran_at_utc TEXT NOT NULL, outcome TEXT NOT NULL,
    baseline_acq_ids TEXT, n_changed_pixels INTEGER, changed_area_ha REAL, largest_cluster_ha REAL, persisted INTEGER,
    event_id INTEGER, details_json TEXT)"""


def test_supersede_migration_on_an_old_schema_db(env):
    # Build the pre-2026-11-11 shape (sat_detections PK acquisition_id, radar acquisition_id UNIQUE, old triggers),
    # with real rows, then re-open: tables rebuilt, rows and ids kept, partial unique indexes + triggers in place.
    _event_run(env)
    p = env["tmp"] / "sat" / "satellite.db"
    c = env["conn"]
    det_rows = [tuple(r) for r in c.execute("SELECT acquisition_id, outcome, event_id FROM sat_detections ORDER BY 1")]
    rad = [tuple(r) for r in c.execute("SELECT id, acquisition_id, status FROM sat_radar_anomalies ORDER BY id")]
    cols = "acquisition_id, monitored_area_id, sensor, ran_at_utc, outcome, baseline_acq_ids, n_changed_pixels, " \
           "changed_area_ha, largest_cluster_ha, persisted, event_id, details_json"
    c.execute("PRAGMA foreign_keys=OFF")
    c.executescript(f"""
      DROP TRIGGER trg_det_no_delete;
      CREATE TABLE d_old AS SELECT {cols} FROM sat_detections; DROP TABLE sat_detections;
      {OLD_DET}; INSERT INTO sat_detections SELECT * FROM d_old; DROP TABLE d_old;
      CREATE TRIGGER trg_cand_update_only_pending BEFORE UPDATE ON sat_s2_candidates
      WHEN OLD.status <> 'PENDING_CONFIRMATION' BEGIN SELECT RAISE(ABORT, 'old'); END;""")
    old_radar = sdb._table_sql("sat_radar_anomalies").replace(
        "acquisition_id INTEGER NOT NULL REFERENCES", "acquisition_id INTEGER NOT NULL UNIQUE REFERENCES").replace(
        ",\n    superseded_at_utc TEXT,\n    superseded_by_generation INTEGER\n)", "\n)")
    assert "superseded" not in old_radar and "UNIQUE" in old_radar
    rcols = [r[1] for r in c.execute("PRAGMA table_info(sat_radar_anomalies)") if not r[1].startswith("superseded")]
    c.executescript(f"""
      DROP TABLE IF EXISTS r_old; CREATE TABLE r_old AS SELECT {', '.join(rcols)} FROM sat_radar_anomalies;
      DROP TABLE sat_radar_anomalies; {old_radar.replace('IF NOT EXISTS ', '')};
      INSERT INTO sat_radar_anomalies SELECT * FROM r_old; DROP TABLE r_old;""")
    c.commit()
    c.close()
    c = sdb.connect(p)
    env["conn"] = c
    assert [tuple(r) for r in c.execute("SELECT acquisition_id, outcome, event_id FROM sat_detections ORDER BY 1")] == det_rows
    assert [tuple(r) for r in c.execute("SELECT id, acquisition_id, status FROM sat_radar_anomalies ORDER BY id")] == rad
    idx = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('index','trigger')")}
    assert {"ux_sat_det_current", "ux_sat_radar_current", "trg_cand_update_only_pending_v2", "trg_det_no_delete",
            "trg_radar_update_only_anomaly_v2", "trg_radar_no_delete", "ix_sat_radar_area"} <= idx
    assert "trg_cand_update_only_pending" not in idx
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and not c.execute("PRAGMA foreign_key_check").fetchall()
    sdb.connect(p).close()                                            # idempotent


# ── Remnant rule (RECOVERED) and compartment-type split (2026-11-13) ────────
_CUT_THEN_GONE = [("2026-06-05", None), ("2026-06-15", None), ("2026-06-25", None),
                  ("2026-07-05", "core"), ("2026-07-15", "core"), ("2026-07-25", None), ("2026-08-04", None)]


def _plan(a, plan):
    core = centre_block(a, 10)
    return _s2_masks(a, [(t, core if m == "core" else m) for t, m in plan])


def test_one_below_min_evaluation_does_not_recover_the_event(env):
    a = make_area(env["conn"])
    prods, rasters = _plan(a, _CUT_THEN_GONE)                       # current area 0 only from 08-04 (1 evaluation)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    e = env["conn"].execute("SELECT * FROM sat_change_events").fetchone()
    assert e["changed_area_ha"] == 0 and e["status"] == "SUSPECTED" and e["recovered_at_utc"] is None
    assert json.loads(e["recovery_json"])["streak"] == {"S2": 1}


def test_two_consecutive_below_min_evaluations_recover_the_event_and_keep_it(env):
    a = make_area(env["conn"])
    prods, rasters = _plan(a, _CUT_THEN_GONE + [("2026-08-14", None)])
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    c = env["conn"]
    e = c.execute("SELECT * FROM sat_change_events").fetchone()
    assert e["status"] == "RECOVERED" and e["recovered_at_utc"].startswith("2026-08-14")
    assert "2 consecutive valid S2 acquisitions" in e["recovered_reason"] and "< min_cluster_ha 0.3" in e["recovered_reason"]
    hist = json.loads(e["recovery_json"])["history"]
    assert [h["to"] for h in hist] == ["RECOVERED"]
    assert e["union_area_ha"] == pytest.approx(1.0) and e["max_area_ha"] == pytest.approx(1.0)   # history kept
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 1                # kept, not deleted
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("DELETE FROM sat_change_events")


def test_recovered_event_reopens_when_it_grows_again(env):
    a = make_area(env["conn"])
    prods, rasters = _plan(a, _CUT_THEN_GONE + [("2026-08-14", None), ("2026-08-24", "core"), ("2026-09-03", "core")])
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    evs = env["conn"].execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1                                             # the same event is reopened, no new one
    e = evs[0]
    assert e["status"] == "SUSPECTED" and e["recovered_at_utc"] is None and e["recovered_reason"] is None
    assert e["changed_area_ha"] >= 0.3
    assert [h["to"] for h in json.loads(e["recovery_json"])["history"]] == ["RECOVERED", "SUSPECTED"]


def test_remnant_rule_never_changes_a_human_status(env):
    a = make_area(env["conn"])
    c = env["conn"]
    plan = _CUT_THEN_GONE + [("2026-08-14", None)]
    p1, r1 = _plan(a, plan[:5])
    run(env, FakeProvider(p1, r1), sensors=("S2",))
    c.execute("UPDATE sat_change_events SET status='FIELD_CHECK_REQUESTED'")
    c.commit()
    p2, r2 = _plan(a, plan)
    run(env, FakeProvider(p2, r2), sensors=("S2",))
    e = c.execute("SELECT * FROM sat_change_events").fetchone()
    assert e["status"] == "FIELD_CHECK_REQUESTED" and e["recovered_at_utc"] is None
    assert e["changed_area_ha"] == 0                                 # the area itself is still recomputed


def test_redetect_treats_recovered_as_automatic_not_human(env):
    from satellite_monitoring import redetect
    a = make_area(env["conn"])
    prods, rasters = _plan(a, _CUT_THEN_GONE + [("2026-08-14", None)])
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    c = env["conn"]
    assert c.execute("SELECT status FROM sat_change_events").fetchone()[0] == "RECOVERED"
    redetect.redetect(c, [a["id"]], "test", decoder=decoder, lock_file=env["tmp"] / "lock")   # no Refused
    cur = c.execute("SELECT status FROM sat_change_events WHERE superseded_at_utc IS NULL").fetchall()
    assert [r[0] for r in cur] == ["RECOVERED"]                      # same result in the new generation


def test_recovered_status_migrates_on_an_old_schema_db(env):
    c = env["conn"]
    a = make_area(c)
    prods, rasters = _plan(a, _CUT_THEN_GONE)
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    old_sql = sdb._table_sql("sat_change_events").replace(",'RECOVERED'", "")
    assert "'RECOVERED'" not in old_sql
    sdb._rebuild(c, "sat_change_events", old_sql, [r[1] for r in c.execute("PRAGMA table_info(sat_change_events)")])
    rows = c.execute("SELECT * FROM sat_change_events ORDER BY id").fetchall()
    c.close()
    c = sdb.connect(env["tmp"] / "sat" / "satellite.db")             # migration runs on connect
    sql = c.execute("SELECT sql FROM sqlite_master WHERE name='sat_change_events'").fetchone()[0]
    assert "'RECOVERED'" in sql
    assert [tuple(r) for r in c.execute("SELECT * FROM sat_change_events ORDER BY id")] == [tuple(r) for r in rows]
    trg = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"trg_events_no_delete", "trg_sat_change_events_frozen_when_superseded"} <= trg
    c.execute("UPDATE sat_change_events SET status='RECOVERED'")      # now allowed
    sdb.connect(env["tmp"] / "sat" / "satellite.db").close()          # idempotent
    env["conn"] = c


def test_compartment_split_is_metadata_and_sums_to_the_current_area(env, monkeypatch):
    a = make_area(env["conn"])
    w, s, e, n = a["grid"]["bbox"]
    mid = (w + e) / 2
    big = {"type": "Polygon", "coordinates": [[[w - 0.01, s - 0.01], [e + 0.01, s - 0.01], [e + 0.01, n + 0.01],
                                               [w - 0.01, n + 0.01], [w - 0.01, s - 0.01]]]}
    west = {"type": "Polygon", "coordinates": [[[w - 0.01, s - 0.01], [mid, s - 0.01], [mid, n + 0.01],
                                                [w - 0.01, n + 0.01], [w - 0.01, s - 0.01]]]}
    p = env["tmp"] / "vmd_classes.sqlite"
    make_vmd(p, [(big, "10"), (west, "14")])                         # west half = clear-cut land, east = stand
    monkeypatch.setenv("SAT_FOREST_DB", str(p))
    monkeypatch.setenv("SAT_FOREST_DB_VERSION", "test-vmd-classes")
    prods, rasters = _plan(a, _CUT_THEN_GONE[:5])                    # centre block straddles the two halves
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    ev = env["conn"].execute("SELECT * FROM sat_change_events").fetchone()
    split = json.loads(ev["compartment_split_json"])
    assert split["source_version"].startswith("test-vmd-classes")
    total = split["stand_zkat10_ha"] + split["clearcut_zkat14_ha"] + split["other_compartments_ha"] + split["no_compartment_ha"]
    assert total == pytest.approx(ev["changed_area_ha"])
    assert split["stand_zkat10_ha"] > 0 and split["clearcut_zkat14_ha"] > 0 and split["other_compartments_ha"] == 0


def test_compartment_split_does_not_change_detection(env, monkeypatch):
    a = make_area(env["conn"])
    prods, rasters = _plan(a, _CUT_THEN_GONE[:5])
    from satellite_monitoring import forest_mask
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    with_split = [tuple(r) for r in env["conn"].execute(
        "SELECT changed_area_ha, n_changed_pixels, classification, confidence FROM sat_change_events")]
    def broken(area):
        raise forest_mask.ForestMaskUnavailable("test: classes off")
    monkeypatch.setattr(forest_mask, "get_classes", broken)
    from satellite_monitoring import redetect
    redetect.redetect(env["conn"], [a["id"]], "test", decoder=decoder, lock_file=env["tmp"] / "lock")
    ev = env["conn"].execute("SELECT * FROM sat_change_events WHERE superseded_at_utc IS NULL").fetchone()
    assert (ev["changed_area_ha"], ev["n_changed_pixels"], ev["classification"], ev["confidence"]) == with_split[0]
    assert json.loads(ev["compartment_split_json"]) == {"unavailable": "test: classes off"}

