"""Sectors list cards (owner D6/D12): one read-only payload for the Sectors page.

forest_ai.db (sectors + geodata_sources) and the isolated satellite.db are both opened READ-ONLY (sqlite mode=ro).
Only stored values are returned; missing stays None (never 0). The monitoring status is NOT derived here — the client
derives it (assets/sectors-cards.js deriveStatus) from the raw fields, so the rule lives in one tested place.

Archive (owner D14, not applied yet): when the column sectors.archived_at exists, archived sectors are left out of the
list; a single card is still returned by id (audit/evidence links). No migration is done here.
"""
import json
import os
import sqlite3
from pathlib import Path

OPEN_STATUSES = ("SUSPECTED", "FIELD_CHECK_REQUESTED")       # satellite workspace §4.4 "open"
MAX_RING_VERTICES = 64                                        # card outline only; the map uses the full geometry
DETECTION_MIN_HA_DEFAULT = 0.5                                # owner F1: small-sector note below this stored area


def detection_min_ha():
    try:
        v = float(os.environ.get("DETECTION_MIN_HA", DETECTION_MIN_HA_DEFAULT))
        return v if v >= 0 else DETECTION_MIN_HA_DEFAULT
    except ValueError:
        return DETECTION_MIN_HA_DEFAULT


def ro(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def _j(v, default=None):
    try:
        return json.loads(v) if v else default
    except (TypeError, ValueError):
        return default


def has_column(conn, table, column):
    return column in {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def thin(ring, n=MAX_RING_VERTICES):
    if len(ring) <= n:
        return ring
    k = -(-len(ring) // n)
    out = ring[::k]
    return out if out[-1] == ring[-1] else out + [ring[-1]]


_GEOD = None


def extent_m(ring):
    """Width/height of the lon/lat bbox in metres (geodesic, pyproj) + the bbox."""
    global _GEOD
    if _GEOD is None:
        from pyproj import Geod
        _GEOD = Geod(ellps="WGS84")
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    w0, e0, s0, n0 = min(lons), max(lons), min(lats), max(lats)
    mid = (s0 + n0) / 2
    _, _, w = _GEOD.inv(w0, mid, e0, mid)
    _, _, h = _GEOD.inv(w0, s0, w0, n0)
    return {"w": round(w, 1), "h": round(h, 1)}, [w0, s0, e0, n0]


def sector_ring(boundary_json):
    """sectors.boundary_json is [[lat, lon], ...] -> [[lon, lat], ...]; None when absent/invalid."""
    pts = _j(boundary_json)
    if not isinstance(pts, list) or len(pts) < 3:
        return None
    try:
        return [[float(p[1]), float(p[0])] for p in pts]
    except (TypeError, ValueError, IndexError):
        return None


def identifier(src):
    """Cadastral / VMD identifier exactly as stored (the full number; no masking in the application)."""
    if not src:
        return None
    props = _j(src["source_properties"], {}) or {}
    kv, nog = props.get("kvart"), props.get("nog")
    return {"cadastre": props.get("kadastrs") or None,
            "kvart": kv if kv not in (None, "") else None,
            "nog": nog if nog not in (None, "") else None,
            "source_feature_id": src["source_feature_id"]}


def _sector_rows(fc, sector_id=None, include_archived=False):
    archived = has_column(fc, "sectors", "archived_at")
    cols = "id, name, status, area_ha, boundary_json, created_at, data_origin, boundary_plan_id" + \
           (", archived_at" if archived else ", NULL AS archived_at")
    where, args = [], []
    if sector_id is not None:
        where.append("id=?"); args.append(sector_id)
    if archived and not include_archived:
        where.append("archived_at IS NULL")
    sql = f"SELECT {cols} FROM sectors" + (" WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY name COLLATE NOCASE, id"
    return [dict(r) for r in fc.execute(sql, args)]


def build_sectors(fc, sector_id=None, include_archived=False):
    srcs = {}
    if fc.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='geodata_sources'").fetchone():
        srcs = {r["sector_id"]: r for r in fc.execute(
            "SELECT sector_id, provider, source_feature_id, source_properties, imported_at FROM geodata_sources")}
    out = []
    for s in _sector_rows(fc, sector_id, include_archived):
        ring = sector_ring(s["boundary_json"])
        ext, bbox = extent_m(ring) if ring else (None, None)
        src = srcs.get(s["id"])
        out.append({
            "id": s["id"], "name": s["name"], "status_text": s["status"], "data_origin": s["data_origin"],
            "area_ha": s["area_ha"], "area_ha_source": "stored" if s["area_ha"] is not None else None,
            "created_at": s["created_at"], "archived_at": s["archived_at"],
            "identifier": identifier(src),
            "provenance": ({"provider": src["provider"], "source_feature_id": src["source_feature_id"],
                            "imported_at": src["imported_at"]} if src else
                           ({"provider": "BOUNDARY_PLAN", "boundary_plan_id": s["boundary_plan_id"]}
                            if s["boundary_plan_id"] else None)),
            "boundary_plan_id": s["boundary_plan_id"],
            "ring": thin(ring) if ring else None, "bbox": bbox, "extent_m": ext,
        })
    return out


def area_monitoring(sc, a, min_valid, raster_exists=None):
    exists = raster_exists or (lambda p: Path(p).is_file())
    aid = a["id"]
    acq = [dict(r) for r in sc.execute(
        "SELECT id, sensor, sensing_time_utc, status, valid_pct_inside, quicklook_path FROM sat_acquisitions "
        "WHERE monitored_area_id=?", (aid,))]
    ok = [x for x in acq if x["status"] == "OK"]
    s2v = sorted((x for x in ok if x["sensor"] == "S2" and isinstance(x["valid_pct_inside"], (int, float))
                  and x["valid_pct_inside"] >= min_valid), key=lambda x: x["sensing_time_utc"])
    s1 = sorted((x for x in ok if x["sensor"] == "S1"), key=lambda x: x["sensing_time_utc"])
    last_s2, last_s1 = (s2v[-1] if s2v else None), (s1[-1] if s1 else None)
    preview = None
    for x in reversed(s2v):                                   # latest VALID S2 with a stored image
        if not x["quicklook_path"]:
            continue
        p = Path(x["quicklook_path"])
        tc = exists(str(p.with_name(p.stem + "_tc.png")))      # same rule as satellite_monitoring.store._tc_path
        preview = {"acq_id": x["id"], "kind": "truecolor" if tc else "falsecolor",
                   "sensing_time_utc": x["sensing_time_utc"], "valid_pct_inside": x["valid_pct_inside"]}
        break
    cur = " AND superseded_at_utc IS NULL" if has_column(sc, "sat_change_events", "superseded_at_utc") else ""
    ev = [dict(r) for r in sc.execute("SELECT id, status, classification, confidence FROM sat_change_events "
                                      "WHERE monitored_area_id=?" + cur + " ORDER BY id", (aid,))]
    grid = _j(a["grid_json"], {}) or {}
    return {
        "area_id": aid, "source": a["source"], "source_ref": a["source_ref"], "active": bool(a["active"]),
        "removed_at_utc": a["removed_at_utc"], "added_at_utc": a["added_at_utc"],
        "ok_acquisitions": len(ok), "min_valid_pct": min_valid,
        "last_valid_s2": ({"acq_id": last_s2["id"], "sensing_time_utc": last_s2["sensing_time_utc"],
                           "valid_pct_inside": last_s2["valid_pct_inside"]} if last_s2 else None),
        "last_s1": ({"acq_id": last_s1["id"], "sensing_time_utc": last_s1["sensing_time_utc"]} if last_s1 else None),
        "open_suspected": sum(1 for e in ev if e["status"] in OPEN_STATUSES),
        "confirmed": sum(1 for e in ev if e["status"] == "REVIEW_CONFIRMED"),
        "open_events": [{"id": e["id"], "status": e["status"], "classification": e["classification"],
                         "confidence": e["confidence"]} for e in ev if e["status"] in OPEN_STATUSES],
        "preview": preview, "grid_bbox": grid.get("bbox"),
    }


def _open_add_jobs(sc):
    if not sc.execute("SELECT 1 FROM sqlite_master WHERE name='sat_jobs'").fetchone():
        return {}
    out = {}
    for r in sc.execute("SELECT id, payload_json FROM sat_jobs WHERE kind='ADD_AREA' AND status IN ('QUEUED','RUNNING')"):
        p = _j(r["payload_json"], {}) or {}
        out[(p.get("source"), str(p.get("source_ref")))] = r["id"]
    return out


def attach_monitoring(sc, sectors, min_valid, raster_exists=None):
    """SECTOR link (source_ref = sector id) or, owner D7, an exact LVM GEO match (source_ref = source_feature_id).
    Active row wins; otherwise the newest stopped row ("Apturēts")."""
    by_key = {}
    for a in (dict(r) for r in sc.execute("SELECT * FROM sat_monitored_areas ORDER BY active DESC, id DESC")):
        by_key.setdefault((a["source"], a["source_ref"]), a)
    jobs = _open_add_jobs(sc)
    for s in sectors:
        fid = (s["provenance"] or {}).get("source_feature_id")
        a, link = by_key.get(("SECTOR", str(s["id"]))), "SECTOR"
        if not a and fid:
            a, link = by_key.get(("LVM_GEO", fid)), "LVM_GEO"
        s["monitoring"] = area_monitoring(sc, a, min_valid, raster_exists) if a else None
        if s["monitoring"]:
            s["monitoring"]["link"] = link
        s["queued_job_id"] = jobs.get(("SECTOR", str(s["id"]))) or (jobs.get(("LVM_GEO", fid)) if fid else None)
    return sectors


def cards(forest_db, sat_db, min_valid, sector_id=None, include_archived=False):
    """The payload of GET /api/sectors/cards (and /cards/{id}). satellite.db missing → monitoring None + flag."""
    fc = ro(forest_db)
    try:
        sectors = build_sectors(fc, sector_id, include_archived)
        archive_column = has_column(fc, "sectors", "archived_at")
    finally:
        fc.close()
    sat_ok = bool(sat_db) and Path(sat_db).exists()
    if sat_ok:
        sc = ro(sat_db)
        try:
            attach_monitoring(sc, sectors, min_valid)
        finally:
            sc.close()
    else:
        for s in sectors:
            s["monitoring"], s["queued_job_id"], s["monitoring_unavailable"] = None, None, True
    return {"sectors": sectors,
            "meta": {"satellite_available": sat_ok, "detection_min_ha": detection_min_ha(),
                     "min_valid_pct": min_valid, "archive_column": archive_column}}
