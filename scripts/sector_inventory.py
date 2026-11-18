#!/usr/bin/env python3
"""Sector inventory for the archive preview (owner D14). READ-ONLY, on .backup copies only.

For every sector: id, name, created_at, data_origin, provenance, status, area and per-table reference counts.
forest_ai.db references are by free-text name (every table with a `sector` column; exact match) and by id
(`sector_id` columns). satellite.db: monitored areas (SECTOR source_ref = id, or LVM_GEO source_ref =
geodata_sources.source_feature_id), their acquisitions, current events and review log rows.

  python3 -I scripts/sector_inventory.py --forest-db COPY --sat-db COPY --out inventory.json
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict


def ro(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def cols(conn, t):
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--forest-db", required=True)
    ap.add_argument("--sat-db", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    for p in (a.forest_db, a.sat_db):
        if p.startswith("/root/forest_ai/data/") or p.startswith("/root/forest_ai_satellite_data/"):
            sys.exit("refusing to read a live DB path; use a .backup copy")
    fc, sc = ro(a.forest_db), ro(a.sat_db)
    tables = [r[0] for r in fc.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    by_name_tables = [t for t in tables if t != "sectors" and "sector" in cols(fc, t)]
    by_id_tables = [t for t in tables if t != "sectors" and "sector_id" in cols(fc, t)]
    sectors = [dict(r) for r in fc.execute("SELECT id, name, status, created_at, data_origin, area_ha, boundary_plan_id, "
                                           "boundary_json IS NOT NULL AND trim(boundary_json) NOT IN ('','[]','null') AS has_boundary "
                                           "FROM sectors ORDER BY id")]
    names = Counter(s["name"] for s in sectors)
    name_counts = {t: dict(fc.execute(f'SELECT sector, COUNT(*) FROM "{t}" GROUP BY sector').fetchall()) for t in by_name_tables}
    id_counts = {t: dict(fc.execute(f'SELECT sector_id, COUNT(*) FROM "{t}" GROUP BY sector_id').fetchall()) for t in by_id_tables}
    srcs = {r["sector_id"]: dict(r) for r in fc.execute("SELECT sector_id, provider, source_feature_id, imported_at FROM geodata_sources")}
    areas = [dict(r) for r in sc.execute("SELECT id, source, source_ref, name, active FROM sat_monitored_areas")]
    cur = " AND superseded_at_utc IS NULL" if "superseded_at_utc" in cols(sc, "sat_change_events") else ""
    acq = dict(sc.execute("SELECT monitored_area_id, COUNT(*) FROM sat_acquisitions GROUP BY 1").fetchall())
    ev = dict(sc.execute("SELECT monitored_area_id, COUNT(*) FROM sat_change_events WHERE 1=1" + cur + " GROUP BY 1").fetchall())
    rl = dict(sc.execute("SELECT e.monitored_area_id, COUNT(*) FROM sat_review_log r JOIN sat_change_events e ON e.id=r.event_id "
                         "GROUP BY 1").fetchall())
    out = []
    for s in sectors:
        refs = {}
        for t in by_name_tables:
            n = name_counts[t].get(s["name"], 0)
            if n:
                refs[t] = n
        for t in by_id_tables:
            n = id_counts[t].get(s["id"], 0)
            if n:
                refs[t + " (id)"] = n
        src = srcs.get(s["id"])
        sat = [x for x in areas if (x["source"] == "SECTOR" and x["source_ref"] == str(s["id"])) or
               (src and x["source"] == "LVM_GEO" and x["source_ref"] == src["source_feature_id"])]
        out.append({**{k: s[k] for k in ("id", "name", "status", "created_at", "data_origin", "area_ha", "boundary_plan_id")},
                    "has_boundary": bool(s["has_boundary"]), "duplicate_name": names[s["name"]] > 1,
                    "provider": src["provider"] if src else None, "refs": refs,
                    "refs_total": sum(v for k, v in refs.items()),
                    "sat_areas": [{"area_id": x["id"], "source": x["source"], "active": bool(x["active"]),
                                   "acquisitions": acq.get(x["id"], 0), "current_events": ev.get(x["id"], 0),
                                   "review_log": rl.get(x["id"], 0)} for x in sat]})
    known = {s["name"] for s in sectors}
    orphans = {t: {k: v for k, v in name_counts[t].items() if k not in known} for t in by_name_tables}
    doc = {"by_name_tables": by_name_tables, "by_id_tables": by_id_tables, "sectors": out,
           "orphan_names": {t: v for t, v in orphans.items() if v}}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, default=str)
    print(f"{len(out)} sectors, {len(by_name_tables)} name-keyed tables, {len(by_id_tables)} id-keyed tables -> {a.out}")


if __name__ == "__main__":
    main()
