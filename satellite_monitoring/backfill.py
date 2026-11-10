"""python3 -m satellite_monitoring.backfill --area <id|area name|sector name> --from D --to D
       [--sensors S1,S2] [--dry-run [--discover]] [--create-area [--geometry-file F --source-ref R --name N]]

--dry-run            OFFLINE estimate: no network at all. Pixels, PU per request,
                     expected acquisitions and quota fit (expected counts are
                     planning estimates, config.EXPECTED_PER_30D).
--dry-run --discover Adds ONE Catalog search per sensor (counted in the request
                     log) and lists the products that would be fetched. No
                     Process request, nothing written except the request log.
Run with /root/forest_ai_satellite_venv/bin/python (tifffile).
"""
import argparse
import os
import json
import math
import sys
from datetime import datetime

from . import areas, cdse, config, db as sdb, geometry as geo, pipeline, provider as prov


def _resolve(conn, args):
    a = areas.find(conn, args.area) if conn else None
    if a:
        return a, False
    if args.geometry_file:
        with open(args.geometry_file) as fh:
            g = json.load(fh)
        g = g.get("geometry", g) if g.get("type") == "Feature" else g
        src = {"source": "LVM_GEO", "source_ref": args.source_ref, "name": args.name or args.area,
               "geometry": geo.to_crs84(g, args.geometry_crs)}
        if not src["source_ref"]:
            raise SystemExit("--geometry-file needs --source-ref")
    else:
        src = areas.resolve_sector(args.area)
    return src, True


def dry_run(args, sensors, cfg):
    conn = sdb.connect() if (args.discover or config.sat_db_path().exists()) else None
    target, is_new = _resolve(conn, args)
    p = areas.prepare(target["geometry"], cfg)
    g = p["grid"]
    days = (datetime.strptime(args.to, "%Y-%m-%d") - datetime.strptime(args.from_, "%Y-%m-%d")).days + 1
    pu_req = {s: prov.estimate_pu(s, g["width"], g["height"], cfg) for s in ("S1", "S2")}
    per30 = {s: config.EXPECTED_PER_30D[s] for s in sensors}
    out = {
        "mode": "DRY-RUN (offline estimate)" + (" + Catalog discovery" if args.discover else ""),
        "area": {"name": target["name"], "source": target["source"], "source_ref": target["source_ref"],
                 "already_monitored": not is_new, "area_ha": p["area_ha"]},
        "grid": {"width": g["width"], "height": g["height"], "pixels_total": g["width"] * g["height"],
                 "pixels_inside": p["n_inside"], "pixels_buffer": p["n_buffer"],
                 "pixel_m": [round(g["pixel_w_m"], 3), round(g["pixel_h_m"], 3)],
                 "pixel_deg": [g["resx_deg"], g["resy_deg"]], "buffer_m": cfg["buffer_m"], "bbox": g["bbox"]},
        "pu_per_request_estimate": {s: pu_req[s] for s in sensors},
        "window": {"from": args.from_, "to": args.to, "days": days},
        "expected_acquisitions_per_30d_ESTIMATE": per30,
    }
    req30 = sum(per30.values())
    pu30 = sum(per30[s] * pu_req[s] for s in sensors)
    catalog30 = 30 * len(sensors)            # one search per sensor per daily run, shared by ALL areas
    out["per_area_per_30d"] = {"process_requests": req30, "pu": round(pu30, 3),
                               "shared_catalog_requests_all_areas": catalog30}
    fq, f = config.FREE_QUOTA, cfg["guard_stop_fraction"]
    out["areas_this_size_that_fit"] = {
        "free_quota_10000pu_10000req": int(min((fq["requests"] - catalog30) / req30, fq["pu"] / pu30)),
        "with_guard_budget": int(min((f * cfg["monthly_request_budget"] - catalog30) / req30,
                                     f * cfg["monthly_pu_budget"] / pu30)),
    }
    win = {s: math.ceil(per30[s] * days / 30) for s in sensors}
    out["backfill_window_ESTIMATE"] = {"acquisitions": win, "process_requests": sum(win.values()),
                                       "catalog_requests": len(sensors),
                                       "pu": round(sum(win[s] * pu_req[s] for s in sensors), 3)}
    if args.discover:
        client = cdse.Client(max_rps=cfg["max_requests_per_second"])
        def log(kind, status, resp):
            conn.execute("INSERT INTO sat_request_log (run_id, at_utc, kind, sensor, http_status, pu, pu_is_estimate)"
                         " VALUES (NULL,?,?,?,?,NULL,NULL)", (sdb.iso(sdb.utcnow()), kind, None, status))
            conn.commit()
        client.on_request = log
        sh = prov.SentinelHubProvider(client, cfg)
        stored = set()
        if not is_new:
            stored = {r["product_id"] for r in conn.execute(
                "SELECT product_id FROM sat_acquisitions WHERE monitored_area_id=?", (target["id"],))}
        listed = {}
        footprint = geo.bbox_polygon(g["bbox"])
        import shapely.geometry
        for s in sensors:
            prods = [x for x in sh.discover(s, g["bbox"], args.from_, args.to)
                     if not x.footprint or shapely.geometry.shape(x.footprint).intersects(footprint)]
            if s == "S1":
                check = {}
                for it in getattr(sh, "last_raw_items", []):
                    k = (it.platform or "unknown").upper().replace("SENTINEL-", "S")
                    c = check.setdefault(k, {"catalog_items": 0, "sat:relative_orbit_present": 0,
                                             "derived_from_absolute_orbit_S1A": 0, "unknown": 0,
                                             "sat:orbit_state_present": 0, "property_keys_seen": set()})
                    c["catalog_items"] += 1
                    c["sat:relative_orbit_present"] += it.relative_orbit_source == "CATALOG"
                    c["derived_from_absolute_orbit_S1A"] += it.relative_orbit_source == "DERIVED_S1A"
                    c["unknown"] += it.relative_orbit_source is None
                    c["sat:orbit_state_present"] += it.orbit_direction is not None
                    c["property_keys_seen"] |= set(it.catalog_property_keys or [])
                for c in check.values():
                    c["property_keys_seen"] = sorted(c["property_keys_seen"])
                for plat in ("S1A", "S1C", "S1D"):
                    check.setdefault(plat, {"catalog_items": 0, "note": "no items in this window"})
                out["s1_orbit_field_check"] = check
            rows = []
            for x in prods:
                skip = s == "S2" and x.scene_cloud_pct is not None and x.scene_cloud_pct > cfg["s2_max_scene_cloud_pct"]
                rows.append({"product_id": x.product_id, "sensing_time_utc": x.sensing_time_utc, "platform": x.platform,
                             "orbit": x.orbit_direction, "relative_orbit": x.relative_orbit,
                             "relative_orbit_source": x.relative_orbit_source,
                             "scene_cloud_pct": x.scene_cloud_pct, "items": len(x.item_ids),
                             "action": "already stored" if x.product_id in stored else
                                       ("SKIPPED_CLOUD (no request)" if skip else "would fetch")})
            listed[s] = rows
        out["discovered"] = listed
        fetch = {s: sum(1 for r in listed[s] if r["action"] == "would fetch") for s in sensors}
        out["backfill_window_DISCOVERED"] = {"would_fetch": fetch, "process_requests": sum(fetch.values()),
                                             "pu_estimate": round(sum(fetch[s] * pu_req[s] for s in sensors), 3)}
        sdb.provider_status(conn, "catalog", True)
    return out


def main(argv=None):
    os.umask(0o077)                         # data dir 700 / files 600
    ap = argparse.ArgumentParser(prog="satellite_monitoring.backfill")
    ap.add_argument("--area", required=True)
    ap.add_argument("--from", dest="from_", required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--sensors", default="S1,S2")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--create-area", action="store_true", help="explicitly add the area to monitoring")
    ap.add_argument("--geometry-file")
    ap.add_argument("--geometry-crs", default="EPSG:4326")
    ap.add_argument("--source-ref")
    ap.add_argument("--name")
    ap.add_argument("--added-by", default="cli")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    sensors = [s.strip().upper() for s in args.sensors.split(",") if s.strip()]
    if not set(sensors) <= {"S1", "S2"}:
        ap.error("--sensors must be S1,S2")
    cfg = config.DEFAULTS
    if args.discover and not args.dry_run:
        ap.error("--discover is only valid with --dry-run")
    if args.dry_run:
        out = dry_run(args, sensors, cfg)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    conn = sdb.connect()
    target, is_new = _resolve(conn, args)
    if is_new:
        if not args.create_area:
            print(f"Area {target['name']!r} is not monitored. Re-run with --create-area to add it.", file=sys.stderr)
            return 2
        area_id, _ = areas.create(conn, target["source"], target["source_ref"], target["name"], target["geometry"],
                                  args.added_by, cfg)
    else:
        area_id = target["id"]
    try:
        res = pipeline.run("BACKFILL", conn=conn, area_ids=[area_id], date_from=args.from_, date_to=args.to,
                           sensors=sensors, cfg=cfg)
    except pipeline.Locked:
        print("Another satellite monitoring run holds the lock.", file=sys.stderr)
        return 3
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["status"] in ("OK", "PARTIAL") else 1


if __name__ == "__main__":
    sys.exit(main())
