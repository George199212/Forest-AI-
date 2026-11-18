#!/usr/bin/env python3
"""Sectors Stage 1: build the card-list fixture (one payload for all sectors) from DB COPIES, read-only.

This is the reference shape for the D6 read-only endpoints (Stage 2):
  GET /api/sectors/cards                      -> "sector" part (forest_ai.db)
  GET /api/sat-monitoring/sector-summaries    -> "monitoring" part (satellite.db)
Only stored values; missing stays None (never 0). Status is NOT derived here: the client derives it
(assets/sectors-cards.js deriveStatus) from the raw fields, so the rule lives in one tested place.

Usage (never on the live DBs; copies made with sqlite3 .backup):
  python3 -I scripts/sector_cards_fixture.py --forest-db COPY --sat-db COPY --out tests/fixtures/sectors_ui/sector_cards.json
  [--with-kekava-fixture]   adds the Ķekava EVAL_BBOX area as a Stage 1-only card (owner D3: never in Stage 2 / release)
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from pyproj import Geod

GEOD = Geod(ellps="WGS84")
OPEN_STATUSES = ("SUSPECTED", "FIELD_CHECK_REQUESTED")       # Stage 5 §4.4 "open"
MIN_VALID_PCT_DEFAULT = 60.0                                  # satellite_monitoring/config.py DEFAULTS["min_valid_pct"]
MAX_RING_VERTICES = 64                                        # card outline only; the map uses the full geometry


def ro(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def j(v, default=None):
    try:
        return json.loads(v) if v else default
    except (TypeError, ValueError):
        return default


def thin(ring, n=MAX_RING_VERTICES):
    """Keep every k-th vertex (plus the last) so a card outline stays small. Display only."""
    if len(ring) <= n:
        return ring
    k = -(-len(ring) // n)
    out = ring[::k]
    return out if out[-1] == ring[-1] else out + [ring[-1]]


def extent_m(ring):
    """Width/height of the lon/lat bbox in metres (geodesic, pyproj). Used for the D4 preview threshold."""
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    w0, e0, s0, n0 = min(lons), max(lons), min(lats), max(lats)
    mid = (s0 + n0) / 2
    _, _, w = GEOD.inv(w0, mid, e0, mid)
    _, _, h = GEOD.inv(w0, s0, w0, n0)
    return {"w": round(w, 1), "h": round(h, 1)}, [w0, s0, e0, n0]


def sector_ring(boundary_json):
    """sectors.boundary_json is [[lat, lon], ...] -> [[lon, lat], ...]; None when absent/invalid."""
    pts = j(boundary_json)
    if not isinstance(pts, list) or len(pts) < 3:
        return None
    try:
        return [[float(p[1]), float(p[0])] for p in pts]
    except (TypeError, ValueError, IndexError):
        return None


def identifier(src):
    """Cadastral / VMD identifier exactly as stored in geodata_sources (no formatting of numbers)."""
    if not src:
        return None
    props = j(src["source_properties"], {}) or {}
    kv, nog = props.get("kvart"), props.get("nog")
    return {"cadastre": props.get("kadastrs") or None,
            "kvart": kv if kv not in (None, "") else None,
            "nog": nog if nog not in (None, "") else None,
            "source_feature_id": src["source_feature_id"]}


def build_sectors(fc):
    srcs = {r["sector_id"]: r for r in fc.execute(
        "SELECT sector_id, provider, source_feature_id, source_properties, imported_at FROM geodata_sources")}
    out = []
    for s in fc.execute("SELECT id, name, status, area_ha, boundary_json, created_at, data_origin, boundary_plan_id "
                        "FROM sectors ORDER BY name COLLATE NOCASE, id"):
        ring = sector_ring(s["boundary_json"])
        ext, bbox = extent_m(ring) if ring else (None, None)
        src = srcs.get(s["id"])
        out.append({
            "id": s["id"], "name": s["name"], "status_text": s["status"], "data_origin": s["data_origin"],
            "area_ha": s["area_ha"], "area_ha_source": "stored" if s["area_ha"] is not None else None,
            "created_at": s["created_at"],
            "identifier": identifier(src),
            "provenance": ({"provider": src["provider"], "source_feature_id": src["source_feature_id"],
                            "imported_at": src["imported_at"]} if src else
                           ({"provider": "BOUNDARY_PLAN", "boundary_plan_id": s["boundary_plan_id"]}
                            if s["boundary_plan_id"] else None)),
            "boundary_plan_id": s["boundary_plan_id"],
            "ring": thin(ring) if ring else None, "bbox": bbox, "extent_m": ext,
        })
    return out


def area_monitoring(sc, a, min_valid):
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
    for x in reversed(s2v):                                  # latest VALID S2 that has an image file reference
        if not x["quicklook_path"]:
            continue
        p = Path(x["quicklook_path"])
        tc = p.with_name(p.stem + "_tc.png").is_file()       # same rule as satellite_monitoring.store._tc_path
        preview = {"acq_id": x["id"], "kind": "truecolor" if tc else "falsecolor",
                   "sensing_time_utc": x["sensing_time_utc"], "valid_pct_inside": x["valid_pct_inside"]}
        break
    cur = " AND superseded_at_utc IS NULL" if "superseded_at_utc" in {
        r[1] for r in sc.execute("PRAGMA table_info(sat_change_events)")} else ""
    ev = [dict(r) for r in sc.execute("SELECT id, status, classification, confidence FROM sat_change_events "
                                      "WHERE monitored_area_id=?" + cur + " ORDER BY id", (aid,))]
    grid = j(a["grid_json"], {}) or {}
    geom = j(a["geometry_geojson"], {}) or {}
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
        "geometry_ring": thin(geom["coordinates"][0]) if geom.get("type") == "Polygon" else None,
    }


def open_add_jobs(sc):
    if not sc.execute("SELECT 1 FROM sqlite_master WHERE name='sat_jobs'").fetchone():
        return {}
    out = {}
    for r in sc.execute("SELECT id, payload_json FROM sat_jobs WHERE kind='ADD_AREA' AND status IN ('QUEUED','RUNNING')"):
        p = j(r["payload_json"], {}) or {}
        out[(p.get("source"), str(p.get("source_ref")))] = r["id"]
    return out


def build_monitoring(sc, sectors, min_valid):
    areas = [dict(r) for r in sc.execute("SELECT * FROM sat_monitored_areas ORDER BY active DESC, id DESC")]
    jobs = open_add_jobs(sc)
    by_key = {}
    for a in areas:                                    # active row wins; otherwise the newest stopped row
        by_key.setdefault((a["source"], a["source_ref"]), a)
    for s in sectors:
        link, a = None, by_key.get(("SECTOR", str(s["id"])))
        if a:
            link = "SECTOR"
        else:                                          # D7: exact LVM GEO match only
            fid = (s["provenance"] or {}).get("source_feature_id")
            a = by_key.get(("LVM_GEO", fid)) if fid else None
            link = "LVM_GEO" if a else None
        s["monitoring"] = area_monitoring(sc, a, min_valid) if a else None
        if s["monitoring"]:
            s["monitoring"]["link"] = link
        fid = (s["provenance"] or {}).get("source_feature_id")
        s["queued_job_id"] = jobs.get(("SECTOR", str(s["id"]))) or (jobs.get(("LVM_GEO", fid)) if fid else None)
    return areas


def kekava_card(sc, areas, min_valid):
    a = next((x for x in areas if x["source"] == "EVAL_BBOX" and x["active"]), None)
    if not a:
        return None
    m = area_monitoring(sc, a, min_valid)
    m["link"] = "EVAL_BBOX"
    ring = m["geometry_ring"]
    ext, bbox = extent_m(ring) if ring else (None, None)
    return {"id": "fixture-kekava", "_fixture_only": True, "name": a["name"], "status_text": None, "data_origin": None,
            "area_ha": a["area_ha"], "area_ha_source": "satellite_area", "created_at": a["added_at_utc"],
            "identifier": None, "provenance": {"provider": "EVAL_BBOX", "source_feature_id": a["source_ref"],
                                               "imported_at": a["added_at_utc"]},
            "ring": ring, "bbox": bbox, "extent_m": ext, "monitoring": m, "queued_job_id": None}


def _redaction():
    """scripts/fixture_redaction.py, loaded by path (python3 -I does not put the script dir on sys.path)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fixture_redaction", Path(__file__).with_name("fixture_redaction.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--forest-db", required=True)
    ap.add_argument("--sat-db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-kekava-fixture", action="store_true")
    ap.add_argument("--min-valid-pct", type=float, default=MIN_VALID_PCT_DEFAULT)
    ap.add_argument("--redact-terms-file", help="untracked terms file for scripts/fixture_redaction.py; client and "
                    "property names are also read from --forest-db. Redaction is always applied.")
    a = ap.parse_args(argv)
    for p in (a.forest_db, a.sat_db):
        if p.startswith("/root/forest_ai/data/") or p.startswith("/root/forest_ai_satellite_data/"):
            sys.exit("refusing to read a live DB path; use a .backup copy")
    fc, sc = ro(a.forest_db), ro(a.sat_db)
    try:
        sectors = build_sectors(fc)
        areas = build_monitoring(sc, sectors, a.min_valid_pct)
        if a.with_kekava_fixture:
            k = kekava_card(sc, areas, a.min_valid_pct)
            if k:
                sectors.append(k)
    finally:
        fc.close()
        sc.close()
    red = _redaction()
    sectors = red.redact_json(sectors, red.compile_rules(red.load_terms(a.forest_db, a.redact_terms_file)))
    doc = {"_captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "_source": "scripts/sector_cards_fixture.py on .backup copies (read-only); no personal fields; client/property names, surname and cadastral numbers redacted (scripts/fixture_redaction.py)",
           "_note": "Shape of the planned GET /api/sectors/cards + /api/sat-monitoring/sector-summaries (D6). "
                    "Cards with _fixture_only are Stage 1 fixtures (D3) and never part of Stage 2 or a release.",
           "sectors": sectors}
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(sectors)} cards -> {a.out}")


if __name__ == "__main__":
    main()
