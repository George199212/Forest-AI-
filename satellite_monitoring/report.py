"""python3 -m satellite_monitoring.report --area <id|name>  ->  Markdown timeline + evidence paths."""
import argparse
import json
import sys

from . import areas, db as sdb


def _f(v, nd=3):
    return "NULL" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def render(conn, area):
    L = []
    L.append(f"# Satellite monitoring — {area['name']} (area #{area['id']})\n")
    L.append(f"Source: {area['source']} · ref {area['source_ref']} · {area['area_ha']:.2f} ha · buffer {area['buffer_m']:.0f} m"
             f" · active={area['active']} · added {area['added_at_utc']} by {area['added_by']}\n")
    L.append("Labels: **RAW** = data as delivered by Copernicus (GeoTIFF + sha256) · **PROCESSED** = statistics computed "
             "here · **INTERPRETATION** = automated rules (suspected change only) · **HUMAN** = review decisions.\n")
    L.append("Contains modified Copernicus Sentinel data [2026].\n")
    rows = conn.execute("SELECT * FROM sat_acquisitions WHERE monitored_area_id=? ORDER BY sensing_time_utc, sensor",
                        (area["id"],)).fetchall()
    met = {}
    for m in conn.execute("SELECT m.* FROM sat_area_metrics m JOIN sat_acquisitions a ON a.id=m.acquisition_id "
                          "WHERE a.monitored_area_id=?", (area["id"],)):
        met[(m["acquisition_id"], m["metric"], m["zone"])] = m
    det = {d["acquisition_id"]: d for d in conn.execute("SELECT * FROM sat_detections WHERE monitored_area_id=?",
                                                        (area["id"],))}
    for sensor in ("S2", "S1"):
        sub = [r for r in rows if r["sensor"] == sensor]
        L.append(f"\n## {sensor} timeline ({len(sub)} acquisitions) — PROCESSED\n")
        if sensor == "S2":
            L.append("| sensing (UTC) | status | scene cloud % | valid % in / buf | NDVI med | NBR med | NDMI med | detection |")
            L.append("|---|---|---|---|---|---|---|---|")
        else:
            L.append("| sensing (UTC) | status | orbit | rel. orbit | valid % in / buf | VV dB med | VH dB med | detection |")
            L.append("|---|---|---|---|---|---|---|---|")
        for r in sub:
            g = lambda m: met.get((r["id"], m, "INSIDE"))
            med = lambda m: _f(g(m)["median"]) if g(m) and g(m)["median"] is not None else (
                f"NULL ({g(m)['null_reason']})" if g(m) and g(m)["null_reason"] else "NULL")
            d = det.get(r["id"])
            dtxt = (d["outcome"] + (f" → event #{d['event_id']}" if d["event_id"] else "")) if d else "—"
            vp = f"{_f(r['valid_pct_inside'], 1)} / {_f(r['valid_pct_buffer'], 1)}"
            if sensor == "S2":
                L.append(f"| {r['sensing_time_utc']} | {r['status']} | {_f(r['scene_cloud_pct'], 1)} | {vp} | "
                         f"{med('NDVI')} | {med('NBR')} | {med('NDMI')} | {dtxt} |")
            else:
                L.append(f"| {r['sensing_time_utc']} | {r['status']} | {r['orbit_direction'] or 'NULL'} | "
                         f"{_f(r['relative_orbit'])} | {vp} | {med('VV_DB')} | {med('VH_DB')} | {dtxt} |")
    evs = conn.execute("SELECT * FROM sat_change_events WHERE monitored_area_id=? ORDER BY id", (area["id"],)).fetchall()
    L.append(f"\n## Suspected change events ({len(evs)}) — INTERPRETATION\n")
    if not evs:
        L.append("No change event.\n")
    for e in evs:
        ctx = json.loads(e["gps_context_json"] or "{}")
        L.append(f"### Event #{e['id']} — {e['classification']} (suspected change)\n")
        L.append(f"- Status (HUMAN): {e['status']}{' by ' + e['reviewed_by'] if e['reviewed_by'] else ''}")
        L.append(f"- Sensor basis: {e['sensor_basis']} · detection confidence: {e['confidence']} · "
                 f"evidence quality: {e['evidence_quality']}")
        L.append(f"- After window: {e['first_after_time_utc']} … {e['last_after_time_utc']}; "
                 f"before acquisitions: {e['before_acq_ids']}")
        L.append(f"- Changed: {e['changed_area_ha']:.2f} ha (inside {e['changed_area_ha_inside']:.2f} ha, "
                 f"buffer {e['changed_area_ha_buffer']:.2f} ha), {_f(e['pct_of_area_affected'], 1)} % of area, "
                 f"largest cluster {e['largest_cluster_ha']:.2f} ha, max distance outside boundary "
                 f"{_f(e['max_distance_outside_boundary_m'], 0)} m")
        if e["seasonal_caveat"]:
            L.append(f"- Seasonal caveat: {e['seasonal_caveat']}")
        L.append(f"- Operational context: {ctx.get('context_label', 'unavailable')} "
                 f"({ctx.get('activity_records', 'NULL')} registered records in window)")
        L.append(f"- Thresholds: `{e['thresholds_json']}`\n")
    L.append("\n## Evidence files — RAW\n")
    L.append("| acquisition | product_id | raster (GeoTIFF) | sha256 | quicklook (PNG, PROCESSED) |")
    L.append("|---|---|---|---|---|")
    for r in rows:
        if r["raster_path"]:
            L.append(f"| {r['id']} {r['sensor']} {r['sensing_time_utc'][:10]} | `{r['product_id']}` | "
                     f"`{r['raster_path']}` | `{r['raster_sha256']}` | `{r['quicklook_path']}` |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="satellite_monitoring.report")
    ap.add_argument("--area", required=True)
    args = ap.parse_args(argv)
    conn = sdb.connect_ro()
    a = areas.find(conn, args.area)
    if not a:
        print(f"area {args.area!r} not found", file=sys.stderr)
        return 2
    sys.stdout.write(render(conn, a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
