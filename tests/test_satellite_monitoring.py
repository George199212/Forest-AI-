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
    conn = sdb.connect(tmp_path / "sat" / "satellite.db")
    yield {"conn": conn, "forest": forest, "tmp": tmp_path}
    conn.close()


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
    cls, cav = c("GOOD", 11, None, 0.0)
    assert cls == "POSSIBLE_SEASONAL_OR_ENVIRONMENTAL" and "Nov" in cav
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
    f2 = {**f, "id": "S1C_IW_GRDH_1SDV_20261001T160355_20261001T160420_004123_00ABCD_1234"}
    assert prov.parse_catalog_feature("S1", f2).relative_orbit is None   # unknown -> never compared
    f3 = {**f, "properties": {**f["properties"], "sat:relative_orbit": 131}}
    assert prov.parse_catalog_feature("S1", f3).relative_orbit == 131
    ew = {**f, "properties": {**f["properties"], "sar:instrument_mode": "EW"}}
    assert prov.parse_catalog_feature("S1", ew) is None


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
    prods, rasters = s2_series(a, n=4)
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
    prods, rasters = s2_series(a, n=4, cut=cut)
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
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    evs = env["conn"].execute("SELECT * FROM sat_change_events").fetchall()
    assert len(evs) == 1
    hist = json.loads(evs[0]["after_acq_history_json"])
    assert len(hist) >= 2
    assert evs[0]["changed_area_ha"] == pytest.approx(196 * a["grid"]["pixel_area_ha"], rel=1e-6)
    outcomes = [r[0] for r in env["conn"].execute("SELECT outcome FROM sat_detections ORDER BY acquisition_id")]
    assert outcomes.count("EVENT_CREATED") == 1 and "EVENT_UPDATED" in outcomes


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
    prods, rasters = s2_series(a, n=4)
    fp = FakeProvider(prods, rasters)
    r1 = run(env, fp, sensors=("S2",))
    r2 = run(env, fp, sensors=("S2",))
    c = env["conn"]
    assert r1["new_acquisitions"] == 4 and r2["new_acquisitions"] == 0
    assert len(fp.fetch_calls) == 4                                  # nothing fetched twice
    assert c.execute("SELECT COUNT(*) FROM sat_acquisitions").fetchone()[0] == 4
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM sat_detections").fetchone()[0] == 4


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


def test_s1_single_drop_is_not_an_event_persistent_drop_is(env):
    a = make_area(env["conn"])
    prods, rasters = _s1_series(a, [False, False, False, True])
    run(env, FakeProvider(prods, rasters), sensors=("S1",), date_to="2026-07-10")
    c = env["conn"]
    assert c.execute("SELECT COUNT(*) FROM sat_change_events").fetchone()[0] == 0
    assert c.execute("SELECT outcome FROM sat_detections ORDER BY acquisition_id DESC").fetchone()[0] == "SINGLE_DROP"
    # the next same-geometry image confirms the drop -> event (LOW confidence: radar only)
    prods, rasters = _s1_series(a, [False, False, False, True, True])
    run(env, FakeProvider(prods, rasters), sensors=("S1",))
    e = c.execute("SELECT * FROM sat_change_events").fetchall()
    assert len(e) == 1 and e[0]["sensor_basis"] == "S1" and e[0]["confidence"] == "LOW"
    assert c.execute("SELECT persisted FROM sat_detections WHERE event_id=?", (e[0]["id"],)).fetchone()[0] == 1


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
    p2, r2 = s2_series(a, n=4)                                       # S2 cut 2026-07-05
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
    prods, rasters = s2_series(a, n=4)
    prods.append(P("S2", "S2_CLOUD", "2026-07-08T09:50:00Z", scene_cloud_pct=99.0))
    run(env, FakeProvider(prods, rasters), sensors=("S2",))
    md = report.render(env["conn"], areas.load(env["conn"], a["id"]))
    for s in ("**RAW**", "**PROCESSED**", "**INTERPRETATION**", "**HUMAN**", "Contains modified Copernicus Sentinel data",
              "SKIPPED_CLOUD", "NULL (SKIPPED_CLOUD", "suspected change", "EVENT_CREATED → event #1"):
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
