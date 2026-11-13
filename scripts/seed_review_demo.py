#!/usr/bin/env python3
"""
Seed the read-only review instance (ACCESS_MODE=review) with a synthetic, English-only dataset.

What it creates (all marked as synthetic):
  * object "Demo Forest Block" (manual object, no scan) with sectors DEMO-001, DEMO-002, DEMO-003
    (sectors.data_origin='SIMULATED', illustrative location in a forested area of western Latvia)
  * employees "Demo Operator 01", "Demo Operator 02", "Demo Driver 01" (no phone, id number or Telegram id)
  * equipment DEMO-H01 (HARVESTER), DEMO-F01 (FORWARDER); vehicle DEMO-T01 (timber truck); no brands
  * work sessions with GPS track points generated inside the sectors; one route leaves DEMO-001
  * truck reports and timber movements, one with a volume mismatch
  * five risks (data_origin='DEMO_SCENARIO', is_demo=1) with a stored, hand-written ai_recommendation
    in the existing JSON contract, risk_events history and risk_evidence links
  * two stored ai_inspector_analyses rows (model 'stored-demo')
No photos. No API calls of any kind.

Safety
  * Refuses to run unless ACCESS_MODE=review, DB_PATH is set, and the instance that owns DB_PATH
    (the parent of its data/ directory) has a .env with ACCESS_MODE=review.
  * Refuses DB paths inside /root/forest_ai or /root/forest_ai_rm.
  * Idempotent: every run first deletes the rows it owns (everything tied to the DEMO sectors and
    the demo object), then inserts them again, so repeated runs give identical row counts.

Usage (on the server):
  cd /root/forest_ai_review && set -a && . ./.env && set +a && python3 scripts/seed_review_demo.py [--dry-run]
"""

import argparse
import json
import math
import os
import random
import re
import sqlite3
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FORBIDDEN_ROOTS = ("/root/forest_ai/", "/root/forest_ai_rm/")
OBJECT_NAME = "Demo Forest Block"
SECTORS = ("DEMO-001", "DEMO-002", "DEMO-003")
NOTE = "Synthetic demonstration data — illustrative location"
CONTRACTOR = "Demo Contractor A"
SEED_ACTOR = "demo-seed"
DISPATCHER = "demo-dispatcher"
AI_ACTOR = "stored-demo"
AI_NOTE = "Stored demonstration recommendation, written by hand (no AI call)."
TS = "%Y-%m-%d %H:%M:%S UTC"

# Sector geometry: centre (lat, lon) and vertices as (north_m, east_m) offsets from the centre.
GEOMETRY = {
    "DEMO-001": ((57.3000, 21.9000), [(-300, -420), (320, -380), (360, 150), (120, 430), (-280, 400), (-340, -50)]),
    "DEMO-002": ((57.3160, 21.9320), [(-240, -300), (260, -280), (280, 260), (-200, 320)]),
    "DEMO-003": ((57.2910, 21.9410), [(-220, -260), (200, -300), (240, 200), (-180, 280), (-260, 40)]),
}
SECTOR_META = {
    "DEMO-001": dict(status="Active Logging", approved_volume="450 m3", color="green",
                     tree_species="Scots pine, Norway spruce",
                     cut_plan_notes="Final felling. Strip roads every 20 m. Keep a 15 m buffer along the drainage ditch on the east edge."),
    "DEMO-002": dict(status="Active Logging", approved_volume="280 m3", color="orange",
                     tree_species="Norway spruce, birch",
                     cut_plan_notes="Thinning. Forwarder extraction to the roadside landing in DEMO-003."),
    "DEMO-003": dict(status="Landing / Loading", approved_volume="120 m3", color="blue",
                     tree_species="Mixed: birch, aspen",
                     cut_plan_notes="Roadside landing and loading area for the block. Light clearing only."),
}

EMPLOYEES = [  # (key, full_name, role, sector)
    ("op1", "Demo Operator 01", "Harvester operator", "DEMO-001"),
    ("op2", "Demo Operator 02", "Forwarder operator", "DEMO-002"),
    ("drv", "Demo Driver 01", "Timber truck driver", "DEMO-003"),
]


# ── safety ────────────────────────────────────────────────────────────────────

def _read_env(path):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except OSError:
        pass
    return env


def check_target():
    if os.environ.get("ACCESS_MODE", "").strip().lower() != "review":
        sys.exit("REFUSED: ACCESS_MODE=review is not set in the environment.")
    db_path = os.environ.get("DB_PATH")
    if not db_path:
        sys.exit("REFUSED: DB_PATH is not set (the default path is never used by this script).")
    db_path = os.path.realpath(db_path)
    if any(db_path.startswith(r) for r in FORBIDDEN_ROOTS):
        sys.exit(f"REFUSED: {db_path} belongs to the main or client instance.")
    data_dir = os.path.dirname(db_path)
    if os.path.basename(data_dir) != "data":
        sys.exit(f"REFUSED: {db_path} is not inside an instance data/ directory.")
    instance_env = _read_env(os.path.join(os.path.dirname(data_dir), ".env"))
    if instance_env.get("ACCESS_MODE", "").lower() != "review":
        sys.exit(f"REFUSED: the instance owning {db_path} has no .env with ACCESS_MODE=review.")
    return db_path


# ── geometry ──────────────────────────────────────────────────────────────────

M_PER_DEG_LAT = 111320.0


def to_latlon(center, north_m, east_m):
    lat0, lon0 = center
    return (round(lat0 + north_m / M_PER_DEG_LAT, 6),
            round(lon0 + east_m / (M_PER_DEG_LAT * math.cos(math.radians(lat0))), 6))


def polygon(name):
    center, verts = GEOMETRY[name]
    return [list(to_latlon(center, n, e)) for n, e in verts]


def area_ha(name):
    _, v = GEOMETRY[name]
    s = sum(v[i][1] * v[(i + 1) % len(v)][0] - v[(i + 1) % len(v)][1] * v[i][0] for i in range(len(v)))
    return round(abs(s) / 2 / 10000, 2)


def route(rng, name, start, end, step_s=240, exit_window=None, exit_offset_m=0):
    """Deterministic harvester-like random walk inside the sector polygon.
    exit_window=(t_from, t_to): during that window the route heads east beyond the boundary."""
    from services.geo import point_in_polygon
    center, verts = GEOMETRY[name]
    poly = polygon(name)
    max_east = max(e for _, e in verts)
    n, e = 0.0, 0.0
    heading = rng.uniform(0, 2 * math.pi)
    pts = []
    t = start
    home = (0.0, 0.0)  # last position inside the sector
    while t <= end:
        if exit_window and exit_window[0] <= t <= exit_window[1]:
            target_e = max_east + exit_offset_m
            e += max(-90.0, min(90.0, target_e - e))
            n += rng.uniform(-15, 15)
        elif pts and not pts[-1]["inside"]:
            # walk back towards the last inside position, at most 90 m per step
            dn, de = home[0] - n, home[1] - e
            dist = math.hypot(dn, de)
            k = 1.0 if dist <= 90 else 90 / dist
            n, e = n + dn * k, e + de * k
        else:
            for _ in range(24):
                step = rng.uniform(35, 85)
                nn, ne = n + step * math.cos(heading), e + step * math.sin(heading)
                if point_in_polygon(*to_latlon(center, nn, ne), poly) and \
                        point_in_polygon(*to_latlon(center, nn * 1.15, ne * 1.15), poly):
                    n, e = nn, ne
                    heading += rng.uniform(-0.5, 0.5)
                    break
                heading += rng.uniform(1.0, 2.6)
        lat, lon = to_latlon(center, n, e)
        inside = point_in_polygon(lat, lon, poly)
        if inside and not (exit_window and exit_window[0] <= t <= exit_window[1]):
            home = (n, e)
        pts.append({"t": t, "lat": lat, "lon": lon, "acc": round(rng.uniform(3, 9), 1), "inside": 1 if inside else 0})
        t += timedelta(seconds=step_s)
    return pts


def path_length_m(pts):
    from services.geo import calculate_distance_meters
    return round(sum(calculate_distance_meters(a["lat"], a["lon"], b["lat"], b["lon"])
                     for a, b in zip(pts, pts[1:])), 1)


# ── content (English only) ────────────────────────────────────────────────────

def rec(summary, options, recommended, low, high, basis, period):
    return json.dumps({
        "summary": summary,
        "options": [{"id": i, "label": l, "message_text": m} for i, l, m in options],
        "recommended_option_id": recommended,
        "estimated_exposure_eur_low": low,
        "estimated_exposure_eur_high": high,
        "exposure_basis": basis,
        "exposure_period": period,
    }, ensure_ascii=False)


# ── seed ──────────────────────────────────────────────────────────────────────

def wipe(cur):
    ph = ",".join("?" for _ in SECTORS)
    risk_ids = [r[0] for r in cur.execute(f"SELECT id FROM risks WHERE sector IN ({ph})", SECTORS)]
    sess_ids = [r[0] for r in cur.execute(f"SELECT id FROM work_sessions WHERE sector IN ({ph})", SECTORS)]
    deleted = {}

    def d(table, where, params):
        n = cur.execute(f"DELETE FROM {table} WHERE {where}", params).rowcount
        deleted[table] = deleted.get(table, 0) + n

    if risk_ids:
        rp = ",".join("?" for _ in risk_ids)
        for t in ("risk_events", "risk_evidence", "risk_conclusions", "snapshot_risks"):
            d(t, f"risk_id IN ({rp})", risk_ids)
    if sess_ids:
        sp = ",".join("?" for _ in sess_ids)
        d("session_track_points", f"session_id IN ({sp})", sess_ids)
    for t in ("risks", "work_sessions", "work_photos", "live_locations", "sector_employees",
              "sector_equipment", "sector_vehicles", "timber_movements", "truck_reports", "sector_snapshots"):
        d(t, f"sector IN ({ph})", SECTORS)
    d("ai_inspector_analyses", "model=?", (AI_ACTOR,))
    d("sectors", f"name IN ({ph})", SECTORS)
    d("boundary_plans", "object_name=? AND uploaded_by=?", (OBJECT_NAME, SEED_ACTOR))
    return {k: v for k, v in deleted.items() if v}


def seed(cur):
    rng = random.Random(20261021)
    ids = {}
    created = "2026-10-12 08:00:00 UTC"

    # Organisation shown in the UI
    cur.execute("UPDATE organizations SET name=?, slug=? WHERE id=1", ("Demo Forestry Organization", "demo"))

    # Object + sectors
    cur.execute("INSERT INTO boundary_plans (file_path, document_type, uploaded_at, status, uploaded_by, plan_data_json, object_name) "
                "VALUES ('', 'manual_object', ?, 'uploaded', ?, '{}', ?)", (created, SEED_ACTOR, OBJECT_NAME))
    plan_id = cur.lastrowid
    for name in SECTORS:
        (clat, clon), _ = GEOMETRY[name]
        m = SECTOR_META[name]
        cur.execute(
            "INSERT INTO sectors (name, contractor, status, approved_volume, boundary_json, center_lat, center_lon, area_ha, "
            "color, created_at, updated_at, tree_species, cut_plan_notes, notes, boundary_plan_id, object_name, data_origin) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SIMULATED')",
            (name, CONTRACTOR, m["status"], m["approved_volume"], json.dumps(polygon(name)), clat, clon, area_ha(name),
             m["color"], created, created, m["tree_species"], m["cut_plan_notes"], NOTE, plan_id, OBJECT_NAME))

    # People (no phone, id_number, telegram_user_id)
    for key, full_name, role, sector in EMPLOYEES:
        cur.execute("INSERT INTO sector_employees (sector, full_name, role, phone, id_number, notes, active, created_at, telegram_user_id) "
                    "VALUES (?, ?, ?, NULL, NULL, ?, 1, ?, NULL)", (sector, full_name, role, "Synthetic demonstration person", created))
        ids[key] = cur.lastrowid

    # Machines (no brand/model/registration)
    cur.execute("INSERT INTO sector_equipment (sector, equipment_code, type, brand, model, registration_id, operator_employee_id, status, "
                "current_task, fuel_level_pct, working_hours_today, active, created_at, is_demo) "
                "VALUES ('DEMO-001', 'DEMO-H01', 'HARVESTER', NULL, NULL, NULL, ?, 'ACTIVE', ?, 64, 6.5, 1, ?, 1)",
                (ids["op1"], "Final felling on strip roads 4–6, north-west part of the sector", created))
    ids["h01"] = cur.lastrowid
    cur.execute("INSERT INTO sector_equipment (sector, equipment_code, type, brand, model, registration_id, operator_employee_id, status, "
                "current_task, fuel_level_pct, working_hours_today, active, created_at, is_demo) "
                "VALUES ('DEMO-002', 'DEMO-F01', 'FORWARDER', NULL, NULL, NULL, ?, 'IDLE', ?, 38, 3.0, 1, ?, 1)",
                (ids["op2"], "Waiting for repair: hydraulic hose on the crane replaced, test run pending", created))
    ids["f01"] = cur.lastrowid
    cur.execute("INSERT INTO sector_vehicles (sector, plate, vehicle_type, driver, fuel_capacity_l, fuel_per_100km, total_km, notes, "
                "active, created_at, telegram_user_id, employee_id) "
                "VALUES ('DEMO-003', 'DEMO-T01', 'Timber truck', 'Demo Driver 01', 400, 38, 1840, ?, 1, ?, NULL, ?)",
                ("Synthetic demonstration vehicle", created, ids["drv"]))

    # Work sessions + GPS tracks
    def session(key, full_name, sector, start, end, comment, **route_kw):
        pts = route(rng, sector, start, end, **route_kw)
        cur.execute("INSERT INTO work_sessions (user_id, employee, employee_id, contractor, sector, check_in_time, finish_time, "
                    "latitude, longitude, distance_m, approved, comment, identity_ambiguous, identity_shared_count) "
                    "VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'YES', ?, 0, 1)",
                    (full_name, ids[key], CONTRACTOR, sector, start.strftime(TS), end.strftime(TS),
                     pts[0]["lat"], pts[0]["lon"], path_length_m(pts), comment))
        sid = cur.lastrowid
        first_out = None
        for p in pts:
            cur.execute("INSERT INTO session_track_points (session_id, employee_id, telegram_user_id, live_message_id, sector, latitude, "
                        "longitude, horizontal_accuracy, inside_boundary, recorded_at, received_at) "
                        "VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?)",
                        (sid, ids[key], sector, p["lat"], p["lon"], p["acc"], p["inside"],
                         p["t"].strftime(TS), (p["t"] + timedelta(seconds=2)).strftime(TS)))
            if not p["inside"] and first_out is None:
                first_out = (cur.lastrowid, p)
        return sid, pts, first_out

    D = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M")
    session("op1", "Demo Operator 01", "DEMO-001", D("2026-10-19 07:05"), D("2026-10-19 15:40"), "Shift completed, strip roads 1–3.")
    session("op2", "Demo Operator 02", "DEMO-002", D("2026-10-19 07:20"), D("2026-10-19 16:05"), "Forwarding to the landing, 6 loads.")
    s_exit, pts_exit, first_out = session(
        "op1", "Demo Operator 01", "DEMO-001", D("2026-10-20 07:00"), D("2026-10-20 14:30"),
        "Shift completed. Short trip outside the sector late in the morning (see incident).",
        exit_window=(D("2026-10-20 10:40"), D("2026-10-20 11:04")), exit_offset_m=180)
    session("op2", "Demo Operator 02", "DEMO-002", D("2026-10-20 07:30"), D("2026-10-20 10:10"),
            "Shift ended early: crane hydraulic hose failure (see incident).")
    session("drv", "Demo Driver 01", "DEMO-003", D("2026-10-20 08:00"), D("2026-10-20 12:10"), "Loading at the landing, two trips.")

    # Truck reports and timber movements (one mismatch on 2026-10-20)
    trucks = [("2026-10-14 09:10", 31.5), ("2026-10-14 13:40", 30.8), ("2026-10-15 09:25", 32.0), ("2026-10-16 10:05", 29.6),
              ("2026-10-17 09:50", 31.2), ("2026-10-19 09:15", 30.4), ("2026-10-19 14:05", 31.9), ("2026-10-20 09:40", 24.1),
              ("2026-10-20 12:00", 11.4)]
    truck_ids = []
    for when, vol in trucks:
        note = "Load from the DEMO-003 landing to the demo sawmill yard."
        if when.startswith("2026-10-20 12"):
            note = "Second trip of the day; partial load reported by the driver."
        cur.execute("INSERT INTO truck_reports (sector, truck_number, driver, reported_volume, note, created_at) "
                    "VALUES ('DEMO-003', 'DEMO-T01', 'Demo Driver 01', ?, ?, ?)", (vol, note, D(when).strftime(TS)))
        truck_ids.append(cur.lastrowid)
    timber = [("2026-10-14 18:00", 62.0, 62.3), ("2026-10-15 18:00", 32.0, 32.0), ("2026-10-16 18:00", 30.0, 29.6),
              ("2026-10-17 18:00", 31.0, 31.2), ("2026-10-19 18:00", 62.0, 62.3), ("2026-10-20 18:00", 48.0, 35.5)]
    timber_ids = []
    for when, planned, actual in timber:
        diff = round(planned - actual, 1)
        status = "MISSING_VOLUME" if diff > 2 else ("OVER_VOLUME" if diff < -2 else "REPORTED")
        note = ("Daily reconciliation: landing measurement vs. truck reports." if status == "REPORTED" else
                "Daily reconciliation: 48.0 m3 measured at the landing, 35.5 m3 reported on truck waybills (difference 12.5 m3).")
        cur.execute("INSERT INTO timber_movements (sector, planned_volume, actual_volume, difference_volume, status, note, created_at, is_demo) "
                    "VALUES ('DEMO-003', ?, ?, ?, ?, ?, ?, 1)", (str(planned), actual, diff, status, note, D(when).strftime(TS)))
        timber_ids.append(cur.lastrowid)

    # Risks
    def risk(sector, level, reason, rule, status, occurred, created, entity_type=None, entity_id=None, distance=None,
             duration=None, session_id=None, resolved=None, ai=None, pinned=None):
        cur.execute("INSERT INTO risks (sector, risk_level, reason, created_at, entity_type, entity_id, status, rule_code, ai_recommendation, "
                    "distance_m, duration_min, notified_at, resolved_at, telegram_message_id, photo_path, photo_path_2, is_demo, pinned_order, "
                    "ai_status, ai_attempts, session_id, identity_ambiguous, identity_shared_count, occurred_at, data_origin) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 1, ?, 'DONE', 0, ?, 0, 1, ?, 'DEMO_SCENARIO')",
                    (sector, level, reason, created, entity_type, entity_id, status, rule, ai, distance, duration,
                     created if status != "OPEN" else None, resolved, pinned, session_id, occurred))
        return cur.lastrowid

    def ev(risk_id, etype, actor, details, at):
        cur.execute("INSERT INTO risk_events (risk_id, event_type, actor, details, created_at) VALUES (?, ?, ?, ?, ?)",
                    (risk_id, etype, actor, details, at))

    def evidence(risk_id, provider, etype, summary, ref_table, ref_id, observed):
        cur.execute("INSERT INTO risk_evidence (risk_id, source_provider, data_origin, evidence_type, summary, ref_table, ref_id, "
                    "observed_at, created_at) VALUES (?, ?, 'SIMULATED', ?, ?, ?, ?, ?, ?)",
                    (risk_id, provider, etype, summary, ref_table, ref_id, observed, created))

    # 1. SECTOR_EXIT (DEMO-001, Demo Operator 01)
    from services.geo import distance_to_polygon_edge_m
    out_pts = [p for p in pts_exit if not p["inside"]]
    poly1 = polygon("DEMO-001")
    max_out = round(max(distance_to_polygon_edge_m(p["lat"], p["lon"], poly1) for p in out_pts))
    dur = round((out_pts[-1]["t"] - out_pts[0]["t"]).total_seconds() / 60 + 4)
    t0 = out_pts[0]["t"]
    r1 = risk("DEMO-001", "HIGH",
              f"Demo Operator 01 left the DEMO-001 boundary at {t0:%H:%M} UTC and was up to {max_out} m outside "
              f"for about {dur} minutes, on the east side next to the drainage-ditch buffer.",
              "SECTOR_EXIT", "RESOLVED", t0.strftime(TS), (t0 + timedelta(minutes=1)).strftime(TS),
              entity_type="EMPLOYEE", entity_id=ids["op1"], distance=max_out, duration=dur, session_id=s_exit,
              resolved=(t0 + timedelta(minutes=55)).strftime(TS), pinned=1,
              ai=rec(f"Demo Operator 01 was outside DEMO-001 for about {dur} minutes, up to {max_out} m beyond the east boundary. "
                     "The GPS track returns into the sector afterwards, so this looks like a short excursion rather than work "
                     "outside the permit area, but it crosses the 15 m buffer along the drainage ditch. The cause is not known "
                     "from the data; confirm it with the operator before drawing conclusions.",
                     [("ask", "Ask the operator what happened",
                       f"Hello, the GPS track shows you outside sector DEMO-001 from {t0:%H:%M} UTC for about {dur} minutes. "
                       "Could you tell us the reason? No action is needed if it was a planned trip."),
                      ("remind", "Remind about the boundary and buffer zone",
                       "Reminder: the east edge of DEMO-001 has a 15 m protected buffer along the drainage ditch. "
                       "Please keep machines and felling inside the sector boundary."),
                      ("inspect", "Request a site check of the buffer zone",
                       "Please check the drainage-ditch buffer on the east edge of DEMO-001 for ruts or felled trees "
                       "and send two photos from the spot.")],
                     "ask", 0, 1500,
                     "No damage is known yet; the upper value assumes minor rut repair in the buffer zone if a site check finds any.",
                     "one-off, until the site check is done"))
    ev(r1, "DETECTED", "system", f"Track point outside the boundary at {t0:%H:%M} UTC (session #{s_exit}).", (t0 + timedelta(minutes=1)).strftime(TS))
    ev(r1, "AI_RECOMMENDATION_GENERATED", AI_ACTOR, AI_NOTE, (t0 + timedelta(minutes=2)).strftime(TS))
    ev(r1, "DISPATCHER_MESSAGE", DISPATCHER, "Asked Demo Operator 01 about the reason (option: ask).", (t0 + timedelta(minutes=9)).strftime(TS))
    ev(r1, "WORKER_REPLIED", "employee:demo-operator-01",
       "Reply: \"Went to the forest road to meet the fuel service vehicle; the harvester stayed inside the sector.\"",
       (t0 + timedelta(minutes=21)).strftime(TS))
    ev(r1, "RESOLVED", DISPATCHER, "Explained by the operator; no work outside the sector. Site check of the buffer zone scheduled.",
       (t0 + timedelta(minutes=55)).strftime(TS))
    evidence(r1, "forest_ai_gps", "GPS_TRACK", f"First track point outside DEMO-001 ({max_out} m maximum distance, {dur} min).",
             "session_track_points", first_out[0], t0.strftime(TS))

    # 2. TIMBER_VOLUME_MISMATCH (DEMO-003)
    r2 = risk("DEMO-003", "HIGH",
              "Timber reconciliation for 2026-10-20: 48.0 m3 measured at the DEMO-003 landing, but truck waybills "
              "report 35.5 m3. Difference 12.5 m3 (26%).",
              "TIMBER_VOLUME_MISMATCH", "OPEN", "2026-10-20 18:00:00 UTC", "2026-10-20 18:02:00 UTC", pinned=2,
              ai=rec("The landing measurement and the truck waybills for 2026-10-20 differ by 12.5 m3 (26%). The second trip "
                     "was reported as a partial load, which may explain part of the gap, but the data does not show where the "
                     "remaining volume is. Possible causes include timber still stacked at the landing, a measurement error, "
                     "or an unreported load; none of these is confirmed.",
                     [("recount", "Request a recount at the landing",
                       "Please re-measure the stacks at the DEMO-003 landing today and send the figures with a photo of each stack."),
                      ("driver", "Ask the driver about the second trip",
                       "Hello, the second trip on 20 October was reported as 11.4 m3. Was the truck partly loaded, "
                       "or is part of the load still at the landing?"),
                      ("hold", "Hold further loads until reconciled",
                       "Please do not dispatch further loads from DEMO-003 until today's volume difference has been reconciled.")],
                     "recount", 600, 1100,
                     "12.5 m3 at an assumed 50–90 EUR/m3 roadside value for mixed sawlogs and pulpwood.",
                     "one-off discrepancy; check within 1–2 days"))
    ev(r2, "DETECTED", "system", "Daily reconciliation: landing 48.0 m3 vs. waybills 35.5 m3.", "2026-10-20 18:02:00 UTC")
    ev(r2, "TIMBER_COMPARISON", "system", "Compared timber movement #%d with truck reports #%d and #%d." % (timber_ids[-1], truck_ids[-2], truck_ids[-1]),
       "2026-10-20 18:02:00 UTC")
    ev(r2, "AI_RECOMMENDATION_GENERATED", AI_ACTOR, AI_NOTE, "2026-10-20 18:03:00 UTC")
    evidence(r2, "forest_ai_timber", "TIMBER_RECORD", "Landing measurement 48.0 m3 on 2026-10-20.", "timber_movements", timber_ids[-1], "2026-10-20 18:00:00 UTC")
    evidence(r2, "forest_ai_truck_report", "TRUCK_REPORT", "Waybill 24.1 m3 (first trip).", "truck_reports", truck_ids[-2], "2026-10-20 09:40:00 UTC")
    evidence(r2, "forest_ai_truck_report", "TRUCK_REPORT", "Waybill 11.4 m3 (second trip, partial load).", "truck_reports", truck_ids[-1], "2026-10-20 12:00:00 UTC")

    # 3. EQUIPMENT_BREAKDOWN (DEMO-002, forwarder)
    r3 = risk("DEMO-002", "MEDIUM",
              "Forwarder DEMO-F01 stopped at 10:05 UTC: Demo Operator 02 reported a burst hydraulic hose on the crane. "
              "Forwarding in DEMO-002 is paused.",
              "EQUIPMENT_BREAKDOWN", "NOTIFIED", "2026-10-20 10:05:00 UTC", "2026-10-20 10:06:00 UTC",
              entity_type="EMPLOYEE", entity_id=ids["op2"], pinned=3,
              ai=rec("Forwarder DEMO-F01 is out of service after a hydraulic hose failure on the crane. While it is down, "
                     "felled timber in DEMO-002 is not being moved to the landing. A hose replacement is usually a same-day "
                     "repair, but the actual repair time is not known from the data.",
                     [("service", "Call the service team",
                       "Please send the service team to DEMO-002: forwarder DEMO-F01 has a burst crane hydraulic hose. "
                       "The machine is parked on strip road 2."),
                      ("spill", "Check for hydraulic oil on the ground",
                       "Please check whether hydraulic oil leaked onto the ground and use the spill kit if needed. Send a photo."),
                      ("replan", "Re-plan forwarding",
                       "Forwarding in DEMO-002 is paused. Please plan to move the stacked timber once DEMO-F01 is repaired.")],
                     "service", 300, 900,
                     "Repair parts and labour plus 0.5–1 day of lost forwarding time.",
                     "daily, until the forwarder is repaired"))
    ev(r3, "DETECTED", "worker_report", "Breakdown reported by Demo Operator 02 from the field.", "2026-10-20 10:06:00 UTC")
    ev(r3, "AI_RECOMMENDATION_GENERATED", AI_ACTOR, AI_NOTE, "2026-10-20 10:07:00 UTC")
    ev(r3, "APPROVED", DISPATCHER, "Option approved: call the service team.", "2026-10-20 10:15:00 UTC")
    ev(r3, "DISPATCHER_MESSAGE", DISPATCHER, "Service team requested for DEMO-F01.", "2026-10-20 10:16:00 UTC")
    ev(r3, "WORKER_REPLIED", "employee:demo-operator-02", "Reply: \"No oil on the ground, hose clamped. Waiting for service.\"",
       "2026-10-20 10:31:00 UTC")
    evidence(r3, "forest_ai_equipment", "EQUIPMENT_STATUS", "DEMO-F01 status IDLE: waiting for repair.", "sector_equipment", ids["f01"], "2026-10-20 10:05:00 UTC")

    # 4. ZONE_PROXIMITY_WARNING (DEMO-001)
    r4 = risk("DEMO-001", "LOW",
              "Harvester DEMO-H01 worked within 12 m of the protected drainage-ditch buffer on the east edge of DEMO-001.",
              "ZONE_PROXIMITY_WARNING", "RESOLVED", "2026-10-19 13:20:00 UTC", "2026-10-19 13:21:00 UTC",
              entity_type="EMPLOYEE", entity_id=ids["op1"], distance=12, resolved="2026-10-19 14:00:00 UTC", pinned=4,
              ai=rec("The harvester came close to the protected buffer zone but the track stays inside the sector. "
                     "This is an early warning, not a violation.",
                     [("remind", "Send a short reminder",
                       "Reminder: the buffer along the drainage ditch starts about 15 m from the east boundary. Please keep a safe distance."),
                      ("none", "No action", "")],
                     "remind", 0, 0, "No damage expected; preventive reminder only.", "one-off"))
    ev(r4, "DETECTED", "system", "Distance to buffer zone 12 m.", "2026-10-19 13:21:00 UTC")
    ev(r4, "AI_RECOMMENDATION_GENERATED", AI_ACTOR, AI_NOTE, "2026-10-19 13:22:00 UTC")
    ev(r4, "DISPATCHER_MESSAGE", DISPATCHER, "Reminder sent to Demo Operator 01.", "2026-10-19 13:30:00 UTC")
    ev(r4, "RESOLVED", DISPATCHER, "Operator confirmed; work continued away from the buffer.", "2026-10-19 14:00:00 UTC")

    # 5. TIMBER_MOVEMENT_NO_ACTIVITY (DEMO-003)
    r5 = risk("DEMO-003", "MEDIUM",
              "Truck report on 2026-10-16 (29.6 m3 from DEMO-003) but no work session was recorded in the block that day.",
              "TIMBER_MOVEMENT_NO_ACTIVITY", "OPEN", "2026-10-16 10:05:00 UTC", "2026-10-16 18:05:00 UTC", pinned=5,
              ai=rec("A load left the DEMO-003 landing on a day without any recorded work session. The timber may have been "
                     "felled earlier and only transported that day, which is common; the data does not show any irregularity "
                     "beyond the missing session.",
                     [("confirm", "Ask the driver to confirm the load origin",
                       "Hello, please confirm that the load on 16 October (29.6 m3) came from timber already stacked at the DEMO-003 landing."),
                      ("note", "Record as transport-only day",
                       "Noted: 16 October was a transport-only day at DEMO-003.")],
                     "confirm", 0, 300, "Administrative check only; no volume difference was found for that day.", "one-off"))
    ev(r5, "DETECTED", "system", "Truck report without a matching work session on the same day.", "2026-10-16 18:05:00 UTC")
    ev(r5, "AI_RECOMMENDATION_GENERATED", AI_ACTOR, AI_NOTE, "2026-10-16 18:06:00 UTC")
    evidence(r5, "forest_ai_truck_report", "TRUCK_REPORT", "Waybill 29.6 m3 on 2026-10-16.", "truck_reports", truck_ids[3], "2026-10-16 10:05:00 UTC")

    # Stored AI inspector analyses (hand-written)
    cur.execute("INSERT INTO ai_inspector_analyses (scope, sector, summary_text, risk_breakdown_json, exposure_low, exposure_high, "
                "exposure_basis, model, created_at) VALUES ('overall', NULL, ?, ?, ?, ?, ?, ?, ?)",
                ("Three demonstration sectors are active in the Demo Forest Block. Two incidents are still open: a 12.5 m3 "
                 "difference between the landing measurement and the truck waybills in DEMO-003, and a truck load on a day "
                 "without a recorded work session. The forwarder in DEMO-002 is waiting for a hydraulic repair, so timber is "
                 "accumulating at the stump. The short boundary exit in DEMO-001 has been explained by the operator.\n\n"
                 "Recommendations:\n"
                 "1. Re-measure the stacks at the DEMO-003 landing before the next load leaves.\n"
                 "2. Confirm a repair time for DEMO-F01 and re-plan forwarding in DEMO-002.\n"
                 "3. Schedule a quick site check of the drainage-ditch buffer on the east edge of DEMO-001.",
                 json.dumps({"HIGH": 1, "MEDIUM": 2, "LOW": 0}), 900, 2300,
                 "Sum of the open incident estimates (volume difference and forwarder downtime).", AI_ACTOR, "2026-10-20 18:30:00 UTC"))
    cur.execute("INSERT INTO ai_inspector_analyses (scope, sector, summary_text, risk_breakdown_json, exposure_low, exposure_high, "
                "exposure_basis, model, created_at) VALUES ('sector', 'DEMO-001', ?, ?, ?, ?, ?, ?, ?)",
                ("DEMO-001 is in final felling with harvester DEMO-H01. Two shifts were recorded on 19–20 October. "
                 "The operator came close to the protected buffer on 19 October and was briefly outside the boundary on "
                 "20 October; both incidents are resolved, and no work outside the sector is shown in the data.\n\n"
                 "Recommendations:\n"
                 "1. Check the buffer zone on the east edge for ruts.\n"
                 "2. Mark the buffer line on the ground before work continues on strip roads 5–6.",
                 json.dumps({"HIGH": 0, "MEDIUM": 0, "LOW": 0}), 0, 1500,
                 "Only a possible rut repair in the buffer zone; no confirmed damage.", AI_ACTOR, "2026-10-20 18:35:00 UTC"))

    return {"plan_id": plan_id, "risks": [r1, r2, r3, r4, r5], "exit_session": s_exit, "max_out_m": max_out, "exit_min": dur}


NON_ENGLISH = re.compile(r"[āčēģīķļņšūžĀČĒĢĪĶĻŅŠŪŽЀ-ӿ]")
SEEDED_TEXT = {
    "sectors": ("name IN ('DEMO-001','DEMO-002','DEMO-003')", None),
    "boundary_plans": ("uploaded_by='demo-seed'", None),
    "sector_employees": ("sector LIKE 'DEMO-%'", None),
    "sector_equipment": ("sector LIKE 'DEMO-%'", None),
    "sector_vehicles": ("sector LIKE 'DEMO-%'", None),
    "work_sessions": ("sector LIKE 'DEMO-%'", None),
    "session_track_points": ("sector LIKE 'DEMO-%'", None),
    "timber_movements": ("sector LIKE 'DEMO-%'", None),
    "truck_reports": ("sector LIKE 'DEMO-%'", None),
    "risks": ("sector LIKE 'DEMO-%'", None),
    "risk_events": ("risk_id IN (SELECT id FROM risks WHERE sector LIKE 'DEMO-%')", None),
    "risk_evidence": ("risk_id IN (SELECT id FROM risks WHERE sector LIKE 'DEMO-%')", None),
    "ai_inspector_analyses": ("model='stored-demo'", None),
    "organizations": ("id=1", None),
}


def verify(cur):
    """Row counts and a scan of every text cell of the seeded rows for Latvian/Cyrillic letters."""
    counts, hits = {}, []
    for t, (where, _) in SEEDED_TEXT.items():
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})")]
        rows = cur.execute(f"SELECT * FROM {t} WHERE {where}").fetchall()
        counts[t] = len(rows)
        for row in rows:
            for c, v in zip(cols, row):
                if isinstance(v, str) and NON_ENGLISH.search(v):
                    hits.append((t, c, row[0]))
    pii = {
        "employees with phone/id_number/telegram_user_id": cur.execute(
            "SELECT COUNT(*) FROM sector_employees WHERE sector LIKE 'DEMO-%' AND (COALESCE(phone,'')!='' OR "
            "COALESCE(id_number,'')!='' OR COALESCE(telegram_user_id,'')!='')").fetchone()[0],
        "track points with telegram_user_id": cur.execute(
            "SELECT COUNT(*) FROM session_track_points WHERE sector LIKE 'DEMO-%' AND COALESCE(telegram_user_id,'')!=''").fetchone()[0],
        "sessions with user_id": cur.execute(
            "SELECT COUNT(*) FROM work_sessions WHERE sector LIKE 'DEMO-%' AND COALESCE(user_id,'')!=''").fetchone()[0],
        "equipment with brand/model": cur.execute(
            "SELECT COUNT(*) FROM sector_equipment WHERE sector LIKE 'DEMO-%' AND (COALESCE(brand,'')!='' OR COALESCE(model,'')!='')").fetchone()[0],
    }
    return counts, hits, pii


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="run everything in a transaction and roll it back")
    args = ap.parse_args()
    db_path = check_target()
    import database
    database.DB_NAME = db_path
    database.init_db()  # schema only; idempotent

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=OFF")
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        deleted = wipe(cur)
        info = seed(cur)
        counts, hits, pii = verify(cur)
        if hits or any(pii.values()):
            raise SystemExit(f"ABORTED (rolled back): non-English text {hits} or personal data {pii}")
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()

    print(f"target DB      : {db_path}{'  (DRY RUN, rolled back)' if args.dry_run else ''}")
    print(f"deleted first  : {deleted or 'nothing (first run)'}")
    print(f"object id      : {info['plan_id']}  risks: {info['risks']}  exit session: #{info['exit_session']} "
          f"({info['max_out_m']} m outside, {info['exit_min']} min)")
    print("rows seeded    :")
    for t, n in counts.items():
        print(f"  {t:24} {n}")
    print(f"non-English characters in seeded text: {len(hits)}")
    print(f"personal identifiers: {pii}")
    print(f"integrity_check: {integrity}")
    print("sector coordinates (WGS84):")
    for name in SECTORS:
        poly = polygon(name)
        la = [p[0] for p in poly]; lo = [p[1] for p in poly]
        print(f"  {name}: centre {GEOMETRY[name][0][0]:.4f}N {GEOMETRY[name][0][1]:.4f}E, "
              f"lat {min(la):.4f}–{max(la):.4f}, lon {min(lo):.4f}–{max(lo):.4f}, {area_ha(name)} ha, "
              f"vertices {json.dumps(poly)}")


if __name__ == "__main__":
    main()
