"""Positive-control evaluation against known felled stands (WORKER only; reads satellite.db READ-ONLY).

python -m satellite_monitoring.positive_control --area <id|name> --truth F.geojson --truth-sha256 HEX
       --reference-db compartments.sqlite --out-dir DIR [--json OUT.json]

Ground truth = a frozen GeoJSON of felled stands (e.g. VMD p_cirg=2026, p_cirp=11), sha256-checked.
Per stand (interior = stand raster eroded by 1 px):
  TOO_SMALL          interior < min_cluster_ha (cannot be detected by design)
  NO_VALID_OBS       no usable S2 image over the interior (>= min_valid_pct valid)
  CUT_BEFORE_WINDOW  already "cut" in the first usable S2 image, which lies in May-June
  DETECTED_IN_WINDOW an event overlaps the interior by >= 0.1 ha or >= 20 %
  NOT_DETECTED       otherwise
"Cut" in an S2 image = interior median minus reference-forest median (intact VMD forest, zkat 10, no felling
recorded since 2024, age >= 20, within 1 km) is <= s2_dndvi_threshold for NDVI AND <= s2_dnbr_threshold for
NBR. Spring images (eval_spring_months, F4) instead use an absolute bare-soil test on the interior median:
NDVI < eval_bare_ndvi_max AND NBR < eval_bare_nbr_max (see cut_test).
T_cut = first usable image that is cut and still cut in the next usable image.
Events with < 0.1 ha overlap with every stand interior are listed for visual review (quicklooks), with a
pre-tag (not a verdict) when they overlap other VMD fellings of 2025-2026.
This is INTERPRETATION for calibration; it writes only review PNGs and the report files, never the DB.
"""
import argparse
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from . import areas, config, db as sdb, detection as det, evidence, geometry as geo, metrics as met

REF_RADIUS_M = 1000.0
OVERLAP_MIN_HA = 0.1
OVERLAP_MIN_FRAC = 0.20


def wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)


def _raster(geom, grid):
    import shapely
    from shapely.geometry import shape
    x, y = geo.pixel_centres(grid)
    return shapely.contains_xy(shape(geom), x, y)


def _erode(m):
    from scipy import ndimage
    return ndimage.binary_erosion(m, structure=np.ones((3, 3), bool))


def _reference_and_other(grid, ref_db, exclude_ids):
    """Intact VMD forest raster + raster of other 2025-2026 fellings (any type), from the national index."""
    import shapely
    w, s, e, n = grid["bbox"]
    c = sdb.sqlite3.connect(f"file:{ref_db}?mode=ro", uri=True)
    rows = c.execute(
        "SELECT c.external_id, c.geometry, json_extract(c.properties,'$.zkat'), json_extract(c.properties,'$.p_cirg'),"
        " json_extract(c.properties,'$.a10'), json_extract(c.properties,'$.p_cirp') FROM spatial_index s JOIN"
        " compartments c ON c.id=s.id WHERE s.max_lon>? AND s.min_lon<? AND s.max_lat>? AND s.min_lat<?",
        (w, e, s, n)).fetchall()
    ref, other = [], []
    for ext, g, zkat, cirg, a10, cirp in rows:
        if ext in exclude_ids:
            continue
        geom = shapely.from_wkb(g)
        cirg = cirg or 0
        if cirg in (2025, 2026):
            other.append(geom)
        elif str(zkat) == "10" and cirg < 2024 and (a10 or 0) >= 20:
            ref.append(geom)
    x, y = geo.pixel_centres(grid)
    ref_m = shapely.contains_xy(shapely.union_all(ref), x, y) if ref else np.zeros_like(x, bool)
    oth_m = shapely.contains_xy(shapely.union_all(other), x, y) if other else np.zeros_like(x, bool)
    return _erode(ref_m), oth_m, len(ref), len(other)


def cut_test(L, v, rv, rec, spring, cfg):
    """Is the stand interior "cut" in this S2 image? Fills rec with the medians; None = not decidable.
    F4 (2026-11-11): spring images (eval_spring_months) use an ABSOLUTE bare-soil test, interior median
    NDVI < eval_bare_ndvi_max AND NBR < eval_bare_nbr_max, because the leaf-off deciduous reference forest makes
    "stand minus reference" unreliable then. Other months: stand minus reference <= s2_dndvi/dnbr_threshold."""
    if rec["valid_pct"] < cfg["min_valid_pct"]:
        return None
    for k in ("NDVI", "NBR"):
        rec[k] = round(float(np.nanmedian(L[k][v])), 3)
    if spring:
        rec["cut_test"] = "ABSOLUTE_BARE_SOIL"
        return bool(rec["NDVI"] < cfg["eval_bare_ndvi_max"] and rec["NBR"] < cfg["eval_bare_nbr_max"])
    if rv.sum() < 20:
        return None
    for k in ("NDVI", "NBR"):
        rec["ref_" + k] = round(float(np.nanmedian(L[k][rv])), 3)
        rec["d" + k] = round(rec[k] - rec["ref_" + k], 3)
    rec["cut_test"] = "STAND_MINUS_REFERENCE"
    return bool(rec["dNDVI"] <= cfg["s2_dndvi_threshold"] and rec["dNBR"] <= cfg["s2_dnbr_threshold"])


def change_locations(masks, min_overlap=0.30):
    """Distinct change locations: events whose masks overlap by >= min_overlap (of the smaller mask) are joined
    (transitively). Returns a list of groups of indices into masks."""
    n = len(masks)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            small = min(int(masks[i].sum()), int(masks[j].sum()))
            if small and int((masks[i] & masks[j]).sum()) / small >= min_overlap:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values())


def evaluate(conn, area, truth_fc, ref_db, out_dir, cfg=None):
    cfg = cfg or config.DEFAULTS
    g = area["grid"]
    pha = g["pixel_area_ha"]
    stands = []
    for f in truth_fc["features"]:
        full = _raster(f["geometry"], g)
        stands.append({"props": f["properties"], "full": full, "interior": _erode(full)})
    ids = {s["props"]["external_id"] for s in stands}
    ref, other, n_ref, n_other = _reference_and_other(g, ref_db, ids)
    ref &= ~np.logical_or.reduce([det.dilate1(s["full"]) for s in stands])
    rr, cc = np.indices((g["height"], g["width"]))

    acqs = [dict(r) for r in conn.execute("SELECT * FROM sat_acquisitions WHERE monitored_area_id=? AND sensor='S2' "
                                          "AND status='OK' ORDER BY sensing_time_utc", (area["id"],))]
    for s in stands:
        ii = np.argwhere(s["interior"]) if s["interior"].any() else np.argwhere(s["full"])
        r0, c0 = ii.mean(axis=0)
        dist = np.hypot((rr - r0) * g["pixel_h_m"], (cc - c0) * g["pixel_w_m"])
        s["ref"] = ref & (dist <= REF_RADIUS_M)
        s["series"] = []
    for a in acqs:
        L = met.s2_layers(evidence._arr(a, g), cfg)
        spring = int(a["sensing_time_utc"][5:7]) in cfg["eval_spring_months"]
        for s in stands:
            m, n = s["interior"], int(s["interior"].sum())
            rec = {"acq_id": a["id"], "time": a["sensing_time_utc"], "valid_pct": None, "cut": None,
                   "cut_test": None}
            if n:
                v = L["valid"] & m
                rec["valid_pct"] = round(100.0 * v.sum() / n, 1)
                rec["cut"] = cut_test(L, v, L["valid"] & s["ref"], rec, spring, cfg)
            s["series"].append(rec)

    events = [dict(e) for e in conn.execute("SELECT * FROM sat_change_events WHERE monitored_area_id=?"
                                            + sdb.current_only(conn, "sat_change_events") + " ORDER BY id",
                                            (area["id"],))]
    for e in events:
        e["_mask"] = np.load(e["change_mask_path"]).astype(bool)
    anomalies = [dict(r) for r in conn.execute("SELECT * FROM sat_radar_anomalies WHERE monitored_area_id=? "
                                               + sdb.current_only(conn, "sat_radar_anomalies") + " "
                                               "ORDER BY sensing_time_utc", (area["id"],))]
    for r in anomalies:
        r["_mask"] = np.load(r["mask_path"]).astype(bool)

    def overlaps(mask, target):
        ov = int((mask & target).sum())
        return ov * pha >= OVERLAP_MIN_HA or (target.sum() and ov / target.sum() >= OVERLAP_MIN_FRAC), ov

    rows = []
    for s in stands:
        p, m = s["props"], s["interior"]
        usable = [x for x in s["series"] if x["cut"] is not None]
        t_cut = None
        for i, x in enumerate(usable[:-1]):
            if x["cut"] and usable[i + 1]["cut"]:
                t_cut = x["time"]
                break
        if t_cut is None and usable and usable[-1]["cut"]:
            t_cut = usable[-1]["time"] + " (unconfirmed: last image)"
        det_ev = [(e, overlaps(e["_mask"], m)[1]) for e in events if overlaps(e["_mask"], m)[0]]
        det_an = [(r, overlaps(r["_mask"], m)[1]) for r in anomalies if overlaps(r["_mask"], m)[0]]
        row = {"external_id": p["external_id"], "kvart": p["kvart"], "nog": p["nog"], "vmd_ha": p["nog_plat_ha"],
               "interior_ha": round(int(m.sum()) * pha, 2), "usable_s2": len(usable),
               "first_usable": usable[0]["time"] if usable else None,
               "first_usable_cut": usable[0]["cut"] if usable else None, "t_cut": t_cut,
               "events": [{"event_id": e["id"], "overlap_ha": round(ov * pha, 2), "first_after": e["first_after_time_utc"],
                           "last_after": e["last_after_time_utc"], "basis": e["sensor_basis"],
                           "confidence": e["confidence"], "classification": e["classification"]} for e, ov in det_ev],
               "radar_anomalies": [{"id": r["id"], "time": r["sensing_time_utc"], "status": r["status"],
                                    "overlap_ha": round(ov * pha, 2)} for r, ov in det_an]}
        if m.sum() * pha < cfg["min_cluster_ha"]:
            row["status"] = "TOO_SMALL"
        elif not usable:
            row["status"] = "NO_VALID_OBS"
        elif usable[0]["cut"] and usable[0]["time"][5:7] in ("05", "06") and t_cut == usable[0]["time"]:
            row["status"] = "CUT_BEFORE_WINDOW"
        elif det_ev:
            row["status"] = "DETECTED_IN_WINDOW"
        else:
            row["status"] = "NOT_DETECTED"
        if row["status"] == "DETECTED_IN_WINDOW" and t_cut and "unconfirmed" not in t_cut:
            first = min(prov_time(x["first_after"]) for x in row["events"])
            row["delay_days"] = (first - prov_time(t_cut)).days
        else:
            row["delay_days"] = None
        row["series"] = s["series"]
        rows.append(row)

    truth_union = np.logical_or.reduce([det.dilate1(s["interior"]) for s in stands])
    review_dir = Path(out_dir)
    outside = []
    for e in events:
        ov = int((e["_mask"] & truth_union).sum())
        if ov * pha >= OVERLAP_MIN_HA:
            continue
        oth = int((e["_mask"] & other).sum())
        ev = {k: e[k] for k in ("id", "sensor_basis", "classification", "confidence", "evidence_quality",
                                "first_after_time_utc", "last_after_time_utc", "changed_area_ha",
                                "changed_area_ha_inside", "changed_area_ha_buffer")}
        ev["pretag"] = "VMD_OTHER_FELLING_2025_2026" if oth * pha >= OVERLAP_MIN_HA else None
        ev["other_felling_overlap_ha"] = round(oth * pha, 2)
        ev["seasonal_month"] = int(e["first_after_time_utc"][5:7]) in cfg["seasonal_months"]
        ev["review_sheet"] = evidence.event_review(conn, area, e, review_dir)["sheet"]
        outside.append(ev)

    eligible = [r for r in rows if r["status"] in ("DETECTED_IN_WINDOW", "NOT_DETECTED")]
    detected = [r for r in eligible if r["status"] == "DETECTED_IN_WINDOW"]
    delays = [r["delay_days"] for r in detected if r["delay_days"] is not None]
    k1000 = area["area_ha"] / 1000.0

    def metrics(excl_seasonal):
        dets = [r for r in eligible if any(not (excl_seasonal and int(x["first_after"][5:7]) in cfg["seasonal_months"])
                                           for x in r["events"])]
        outs = [o for o in outside if not (excl_seasonal and o["seasonal_month"])]
        dl = [r["delay_days"] for r in dets if r["delay_days"] is not None]
        return {"eligible": len(eligible), "detected": len(dets),
                "recall": round(len(dets) / len(eligible), 3) if eligible else None,
                "recall_wilson95": wilson(len(dets), len(eligible)),
                "outside_events": len(outs),
                "outside_events_per_1000ha_UPPER_BOUND_unreviewed": round(len(outs) / k1000, 2),
                "outside_events_without_pretag_per_1000ha": round(len([o for o in outs if not o["pretag"]]) / k1000, 2),
                "median_delay_days": statistics.median(dl) if dl else None,
                "delay_range_days": [min(dl), max(dl)] if dl else None}

    return {"area": {"id": area["id"], "name": area["name"], "area_ha": area["area_ha"]},
            "reference": {"intact_forest_stands": n_ref, "other_fellings_2025_2026": n_other,
                          "radius_m": REF_RADIUS_M},
            "s2_usable_images": len(acqs), "stands": rows, "outside_events": outside,
            "events_total": len(events),
            "distinct_event_masks": len({e["_mask"].tobytes() for e in events}),
            "change_locations": [[events[i]["id"] for i in grp]
                                 for grp in change_locations([e["_mask"] for e in events])],
            "classifications": {c: sum(1 for e in events if e["classification"] == c)
                                for c in sorted({e["classification"] for e in events})},
            "radar_anomalies_total": len(anomalies),
            "radar_anomalies_promoted": sum(1 for r in anomalies if r["status"] == "PROMOTED"),
            "metrics_all": metrics(False), "metrics_excl_oct_apr": metrics(True)}


def prov_time(s):
    from .provider import parse_time
    return parse_time(s)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="satellite_monitoring.positive_control")
    ap.add_argument("--area", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--truth-sha256", required=True)
    ap.add_argument("--reference-db", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    raw = Path(a.truth).read_bytes()
    if hashlib.sha256(raw).hexdigest() != a.truth_sha256:
        raise SystemExit("ground-truth sha256 mismatch")
    conn = sdb.connect_ro()
    area = areas.find(conn, a.area)
    if not area:
        raise SystemExit(f"area {a.area!r} not found")
    res = evaluate(conn, area, json.loads(raw), a.reference_db, a.out_dir)
    res["truth"] = {"path": a.truth, "sha256": a.truth_sha256}
    res["evaluated_at_utc"] = sdb.iso(sdb.utcnow())
    out = json.dumps(res, indent=1, ensure_ascii=False, default=str)
    if a.json:
        Path(a.json).write_text(out)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
