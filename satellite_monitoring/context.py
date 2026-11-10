"""Operational context for an event window, from forest_ai.db opened READ-ONLY.

Counts and ids only — no interpretation of who did what. Spatial sources
(session_track_points, vehicle_gps_pings, work_sessions check-in point) are
matched to polygon + buffer; sector-keyed sources (work_sessions.sector,
work_photos, timber_movements, truck_reports) are matched by sector name, which
exists only for SECTOR areas. live_locations is NOT used: it holds only the
latest position (overwritten), so it cannot say where anyone was in a window.

Timestamps in forest_ai.db are TEXT 'YYYY-MM-DD HH:MM:SS UTC'; compared on the
first 19 characters.
"""
import math
import sqlite3

from . import db as sdb

M_PER_DEG = 111320.0


def _to_local_m(lon, lat, lat0):
    return lon * M_PER_DEG * math.cos(math.radians(lat0)), lat * M_PER_DEG


def _local_polygon(geometry, lat0):
    import shapely.geometry
    rings = [[_to_local_m(c[0], c[1], lat0) for c in r] for r in geometry["coordinates"]]
    return shapely.geometry.Polygon(rings[0], rings[1:])


def _ts(dt_iso):
    # '2026-10-01T09:30:00Z' -> '2026-10-01 09:30:00'
    return dt_iso.replace("T", " ").replace("Z", "")[:19]


def _table_exists(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def operational_context(area, window_from_iso, window_to_iso, buffer_m, forest_conn=None):
    """area: dict with source, name, geometry (GeoJSON). Returns the dict stored in gps_context_json."""
    import shapely.geometry
    own = forest_conn is None
    try:
        c = forest_conn or sdb.forest_ro()
    except sqlite3.Error as e:
        return {"available": False, "reason": f"forest_ai.db not readable: {type(e).__name__}"}
    try:
        geom = area["geometry"]
        lat0 = sum(p[1] for p in geom["coordinates"][0]) / len(geom["coordinates"][0])
        poly = _local_polygon(geom, lat0)
        zone = poly.buffer(buffer_m)
        t0, t1 = _ts(window_from_iso), _ts(window_to_iso)
        sector = area["name"] if area["source"] == "SECTOR" else None

        def spatial(rows, lat_key="latitude", lon_key="longitude"):
            inside, buffer_ids = [], []
            for r in rows:
                if r[lat_key] is None or r[lon_key] is None:
                    continue
                p = shapely.geometry.Point(_to_local_m(r[lon_key], r[lat_key], lat0))
                if poly.contains(p):
                    inside.append(r["id"])
                elif zone.contains(p):
                    buffer_ids.append(r["id"])
            return inside, buffer_ids

        out = {"available": True, "window_from_utc": window_from_iso, "window_to_utc": window_to_iso,
               "buffer_m": buffer_m, "sector_name": sector, "sources": {}}

        if _table_exists(c, "session_track_points"):
            rows = c.execute("SELECT id, session_id, latitude, longitude FROM session_track_points "
                             "WHERE substr(recorded_at,1,19) BETWEEN ? AND ?", (t0, t1)).fetchall()
            ins, buf = spatial(rows)
            sess = sorted({r["session_id"] for r in rows if r["id"] in set(ins + buf)})
            out["sources"]["worker_gps_track_points"] = {"inside": len(ins), "buffer": len(buf),
                                                         "point_ids": (ins + buf)[:200], "session_ids": sess}
        if _table_exists(c, "vehicle_gps_pings"):
            rows = c.execute("SELECT id, latitude, longitude, COALESCE(entity_type,'VEHICLE') AS et "
                             "FROM vehicle_gps_pings WHERE substr(recorded_at,1,19) BETWEEN ? AND ?",
                             (t0, t1)).fetchall()
            ins, buf = spatial(rows)
            out["sources"]["vehicle_equipment_gps_pings"] = {"inside": len(ins), "buffer": len(buf),
                                                             "ping_ids": (ins + buf)[:200]}
        if _table_exists(c, "work_sessions"):
            # Session overlaps the window: check-in <= window end AND (open OR finish >= window start)
            rows = c.execute(
                "SELECT id, sector, latitude, longitude FROM work_sessions "
                "WHERE substr(check_in_time,1,19) <= ? "
                "AND (finish_time IS NULL OR finish_time='' OR substr(finish_time,1,19) >= ?)",
                (t1, t0)).fetchall()
            ins, buf = spatial(rows)
            by_sector = [r["id"] for r in rows if sector and r["sector"] == sector]
            ids = sorted(set(ins + buf + by_sector))
            out["sources"]["work_sessions"] = {"count": len(ids), "session_ids": ids[:200],
                                               "matched_by_checkin_point": len(set(ins + buf)),
                                               "matched_by_sector": len(by_sector)}
        for table, key, col in (("work_photos", "field_photos", "uploaded_at"),
                                ("timber_movements", "timber_movements", "created_at"),
                                ("truck_reports", "truck_reports", "created_at")):
            if not _table_exists(c, table):
                continue
            if sector is None:
                out["sources"][key] = {"count": None, "reason": "no sector link for this area (LVM GEO)"}
                continue
            demo = ", COALESCE(is_demo,0) AS is_demo" if table == "timber_movements" else ", 0 AS is_demo"
            rows = c.execute(f"SELECT id{demo} FROM {table} WHERE sector=? AND substr({col},1,19) BETWEEN ? AND ?",
                             (sector, t0, t1)).fetchall()
            out["sources"][key] = {"count": len(rows), "ids": [r["id"] for r in rows][:200],
                                   "demo_rows": sum(1 for r in rows if r["is_demo"])}

        real_activity = 0
        s = out["sources"]
        real_activity += (s.get("worker_gps_track_points", {}).get("inside", 0)
                          + s.get("worker_gps_track_points", {}).get("buffer", 0))
        real_activity += (s.get("vehicle_equipment_gps_pings", {}).get("inside", 0)
                          + s.get("vehicle_equipment_gps_pings", {}).get("buffer", 0))
        real_activity += s.get("work_sessions", {}).get("count", 0)
        for k in ("field_photos", "truck_reports"):
            real_activity += s.get(k, {}).get("count") or 0
        tm = s.get("timber_movements", {})
        real_activity += (tm.get("count") or 0) - (tm.get("demo_rows") or 0)
        out["activity_records"] = real_activity
        out["context_label"] = ("CHANGE_DURING_REGISTERED_WORK" if real_activity > 0
                                else "UNREGISTERED_CHANGE_CANDIDATE")
        out["note"] = ("Counts of registered records only; absence of records does not prove absence "
                       "of work, and presence does not explain the change.")
        return out
    finally:
        if own:
            c.close()
