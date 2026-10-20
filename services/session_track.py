"""
Worker route during a work session.

bot.py appends one row to session_track_points per live-location update it
receives during an active session (record_point). api.py turns those rows into
the Map tab's line, gaps, photo placement and summary (build_track).

Only real recorded positions are used: nothing is created, interpolated or
backfilled. A session without recorded points has no route.
"""

import json
import re
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import database
from services.geo import point_in_polygon, calculate_distance_meters

TRACK_GAP_SECONDS = 120        # longer silence between two points breaks the line
TRACK_MIN_DISTANCE_M = 5       # a point closer than this ...
TRACK_MIN_INTERVAL_S = 10      # ... and sooner than this after the previous one is skipped
PHOTO_MATCH_SECONDS = 60       # a photo is placed only on a point this close in time
LOCAL_TZ = ZoneInfo("Europe/Riga")
TS_FMT = "%Y-%m-%d %H:%M:%S UTC"


def _conn():
    conn = sqlite3.connect(database.DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def _parse(ts):
    if not ts:
        return None
    try:
        return datetime.strptime(ts, TS_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _local(ts):
    """'DD.MM.YYYY HH:MM' in Europe/Riga, or None."""
    d = _parse(ts)
    return d.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M") if d else None


# ── Recording (bot.py) ───────────────────────────────────────────────────────

def record_point(session_id, employee_id, telegram_user_id, live_message_id, sector,
                 latitude, longitude, horizontal_accuracy, inside_boundary,
                 recorded_at, received_at):
    """Append one track point. Skipped (returns False) only when it is both
    closer than TRACK_MIN_DISTANCE_M and sooner than TRACK_MIN_INTERVAL_S after
    the session's previous point. Never updates or deletes a row."""
    conn = _conn()
    try:
        prev = conn.execute(
            "SELECT latitude, longitude, recorded_at FROM session_track_points "
            "WHERE session_id=? ORDER BY recorded_at DESC, id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if prev:
            dist = calculate_distance_meters(prev["latitude"], prev["longitude"], latitude, longitude)
            t_prev, t_now = _parse(prev["recorded_at"]), _parse(recorded_at)
            dt = (t_now - t_prev).total_seconds() if (t_prev and t_now) else None
            if dist < TRACK_MIN_DISTANCE_M and dt is not None and dt < TRACK_MIN_INTERVAL_S:
                return False
        conn.execute(
            "INSERT INTO session_track_points (session_id, employee_id, telegram_user_id, live_message_id, "
            "sector, latitude, longitude, horizontal_accuracy, inside_boundary, recorded_at, received_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, employee_id, telegram_user_id, live_message_id, sector, latitude, longitude,
             horizontal_accuracy, 1 if inside_boundary else 0, recorded_at, received_at),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def point_count(session_id, live_message_id=None):
    conn = _conn()
    try:
        if live_message_id is None:
            row = conn.execute("SELECT COUNT(*) FROM session_track_points WHERE session_id=?",
                               (session_id,)).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM session_track_points WHERE session_id=? AND live_message_id=?",
                               (session_id, live_message_id)).fetchone()
        return row[0]
    finally:
        conn.close()


# ── Display (api.py) ─────────────────────────────────────────────────────────

def _session_meta(s, points):
    """Selector fields for one work_sessions row. Open/close times are the
    stored ones; 'late_finish' marks a session closed on a later local day."""
    t_in, t_out = _parse(s["check_in_time"]), _parse(s["finish_time"])
    late = bool(t_in and t_out and t_out.astimezone(LOCAL_TZ).date() > t_in.astimezone(LOCAL_TZ).date())
    return {
        "id": s["id"], "employee": s["employee"], "employee_id": s["employee_id"], "sector": s["sector"],
        "check_in_time": s["check_in_time"], "finish_time": s["finish_time"] or None,
        "check_in_local": _local(s["check_in_time"]), "finish_local": _local(s["finish_time"]),
        "session_duration_s": (t_out - t_in).total_seconds() if (t_in and t_out) else None,
        "open": not s["finish_time"], "late_finish": late,
        "latitude": s["latitude"], "longitude": s["longitude"], "approved": s["approved"],
        "points": points,
    }


def list_sessions(sector):
    """Sessions of one sector, newest first; default = newest with track points,
    else the newest session."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT ws.*, (SELECT COUNT(*) FROM session_track_points p WHERE p.session_id=ws.id) AS n "
            "FROM work_sessions ws WHERE ws.sector=? ORDER BY ws.check_in_time DESC, ws.id DESC",
            (sector,),
        ).fetchall()
    finally:
        conn.close()
    sessions = [_session_meta(r, r["n"]) for r in rows]
    default = next((s["id"] for s in sessions if s["points"]), sessions[0]["id"] if sessions else None)
    return {"sessions": sessions, "default_session_id": default,
            "gap_seconds": TRACK_GAP_SECONDS, "photo_match_seconds": PHOTO_MATCH_SECONDS}


def _inside_test(sector_row):
    """Same polygon-or-10-km-radius rule bot.py's _is_inside_sector uses."""
    boundary = None
    if sector_row and sector_row["boundary_json"]:
        try:
            boundary = json.loads(sector_row["boundary_json"])
        except Exception:
            boundary = None
    if boundary:
        return lambda la, lo: point_in_polygon(la, lo, boundary)
    clat = (sector_row["center_lat"] if sector_row else None) or 56.9587
    clon = (sector_row["center_lon"] if sector_row else None) or 24.1034
    return lambda la, lo: calculate_distance_meters(la, lo, clat, clon) <= 10000


def _crossing(a, b, a_inside, inside):
    """Fraction 0..1 along a->b where the boundary is crossed (bisection on the
    straight segment). Used only to split the line colour and the inside/outside
    time of that one interval; it is not stored or shown as a point."""
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        la = a["latitude"] + (b["latitude"] - a["latitude"]) * mid
        lo_ = a["longitude"] + (b["longitude"] - a["longitude"]) * mid
        if bool(inside(la, lo_)) == a_inside:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def build_track(session_id):
    conn = _conn()
    try:
        s = conn.execute("SELECT * FROM work_sessions WHERE id=?", (session_id,)).fetchone()
        if not s:
            return None
        sector_row = conn.execute("SELECT boundary_json, center_lat, center_lon FROM sectors WHERE name=?",
                                  (s["sector"],)).fetchone()
        pts = [dict(r) for r in conn.execute(
            "SELECT id, latitude, longitude, horizontal_accuracy, inside_boundary, recorded_at "
            "FROM session_track_points WHERE session_id=? ORDER BY recorded_at, id", (session_id,))]
        photos = [dict(r) for r in conn.execute(
            "SELECT id, session_id, sector, photo_type, image_path, uploaded_at "
            "FROM work_photos WHERE session_id=? ORDER BY uploaded_at, id", (session_id,))]
    finally:
        conn.close()

    for p in pts:
        p["t"] = _parse(p["recorded_at"])
        p["inside"] = bool(p["inside_boundary"])
    inside = _inside_test(sector_row)

    runs, gaps = [], []
    distance = inside_s = outside_s = 0.0
    segments = 0

    def add(is_in, c1, c2):
        if runs and runs[-1]["inside"] == is_in and runs[-1]["coords"][-1] == c1:
            runs[-1]["coords"].append(c2)
        else:
            runs.append({"inside": is_in, "coords": [c1, c2]})

    if pts:
        runs.append({"inside": pts[0]["inside"], "coords": [[pts[0]["latitude"], pts[0]["longitude"]]]})
    for a, b in zip(pts, pts[1:]):
        ca, cb = [a["latitude"], a["longitude"]], [b["latitude"], b["longitude"]]
        dt = (b["t"] - a["t"]).total_seconds()
        d = calculate_distance_meters(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
        if dt > TRACK_GAP_SECONDS:
            gaps.append({"from": ca, "to": cb, "from_time": a["recorded_at"], "to_time": b["recorded_at"],
                         "seconds": dt, "distance_m": d})
            runs.append({"inside": b["inside"], "coords": [cb]})
            continue
        segments += 1
        distance += d
        if a["inside"] == b["inside"]:
            add(a["inside"], ca, cb)
            if a["inside"]:
                inside_s += dt
            else:
                outside_s += dt
        else:
            f = _crossing(a, b, a["inside"], inside)
            cx = [a["latitude"] + (b["latitude"] - a["latitude"]) * f,
                  a["longitude"] + (b["longitude"] - a["longitude"]) * f]
            add(a["inside"], ca, cx)
            add(b["inside"], cx, cb)
            inside_s += dt * (f if a["inside"] else 1 - f)
            outside_s += dt * (1 - f if a["inside"] else f)
    # A run that is a single point and was followed by more of the line is redundant.
    runs = [r for i, r in enumerate(runs) if len(r["coords"]) > 1 or not (
        i + 1 < len(runs) and runs[i + 1]["coords"][0] == r["coords"][0])]

    has_line = segments > 0
    summary = {
        "points": len(pts),
        "duration_s": (pts[-1]["t"] - pts[0]["t"]).total_seconds() if len(pts) >= 2 else None,
        "distance_m": distance if has_line else None,
        "inside_s": inside_s if has_line else None,
        "outside_s": outside_s if has_line else None,
        "gaps_count": len(gaps) if len(pts) >= 2 else None,
        "gaps_seconds": sum(g["seconds"] for g in gaps) if len(pts) >= 2 else None,
        "gaps_distance_m": sum(g["distance_m"] for g in gaps) if len(pts) >= 2 else None,
    }

    placed, unplaced = [], 0
    for ph in photos:
        t = _parse(ph["uploaded_at"])
        best = min(pts, key=lambda p: abs((p["t"] - t).total_seconds())) if (pts and t) else None
        dt = abs((best["t"] - t).total_seconds()) if best else None
        if best is None or dt > PHOTO_MATCH_SECONDS:
            unplaced += 1
            continue
        ph.update({"latitude": best["latitude"], "longitude": best["longitude"], "match_seconds": dt,
                   "point_id": best["id"], "uploaded_local": _local(ph["uploaded_at"])})
        placed.append(ph)

    def marker(p):
        return {"lat": p["latitude"], "lon": p["longitude"], "time": p["recorded_at"],
                "local": _local(p["recorded_at"])} if p else None

    return {
        "session": _session_meta(s, len(pts)),
        "recorded": bool(pts),
        "gap_seconds": TRACK_GAP_SECONDS,
        "runs": runs,
        "gaps": gaps,
        "start": marker(pts[0] if pts else None),
        "end": marker(pts[-1] if len(pts) >= 2 else None),
        "summary": summary,
        "photos": placed,
        "photos_unplaced": unplaced,
        "photo_match_seconds": PHOTO_MATCH_SECONDS,
    }


# ── Route in a sector-exit incident card (read-only) ─────────────────────────

EXIT_MATCH_SECONDS = 120   # the track's IN->OUT point must be this close to the exit event
_COORD_RE = re.compile(r"(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})")


def _coords_in_text(*texts):
    """Exit coordinates written into the incident itself (reason / DETECTED details), if any."""
    for t in texts:
        m = _COORD_RE.search(t or "")
        if m:
            return [float(m.group(1)), float(m.group(2))]
    return None


def exit_route(risk_id):
    """Route around the latest exit of a SECTOR_EXIT incident. The geofence logs a repeat exit
    of an already open incident as STILL_OUTSIDE, so the latest DETECTED/STILL_OUTSIDE event is
    the exit shown; the session is the employee's session open at that moment."""
    conn = _conn()
    try:
        risk = conn.execute("SELECT * FROM risks WHERE id=?", (risk_id,)).fetchone()
        if not risk:
            return None
        if risk["rule_code"] != "SECTOR_EXIT" or risk["entity_type"] != "EMPLOYEE":
            return {"applicable": False}
        events = conn.execute(
            "SELECT event_type, details, created_at FROM risk_events WHERE risk_id=? "
            "AND event_type IN ('DETECTED','STILL_OUTSIDE') ORDER BY created_at, id", (risk_id,)).fetchall()
        exit_at = events[-1]["created_at"] if events else (risk["occurred_at"] or risk["created_at"])
        s = conn.execute("SELECT * FROM work_sessions WHERE id=?", (risk["session_id"],)).fetchone() \
            if risk["session_id"] else None
        s = s or conn.execute(
            "SELECT * FROM work_sessions WHERE employee_id=? AND check_in_time<=? "
            "AND (finish_time IS NULL OR finish_time='' OR finish_time>=?) "
            "ORDER BY check_in_time DESC, id DESC LIMIT 1",
            (risk["entity_id"], exit_at, exit_at)).fetchone()
        sector_name = s["sector"] if s else risk["sector"]
        sector_row = conn.execute("SELECT boundary_json, center_lat, center_lon FROM sectors WHERE name=?",
                                  (sector_name,)).fetchone()
    finally:
        conn.close()

    boundary = None
    if sector_row and sector_row["boundary_json"]:
        try:
            boundary = json.loads(sector_row["boundary_json"])
        except Exception:
            boundary = None
    detected = next((e["details"] for e in events if e["event_type"] == "DETECTED"), None)
    out = {
        "applicable": True, "risk_id": risk_id, "exit_event_time": exit_at, "exit_event_local": _local(exit_at),
        "exits_count": len(events), "sector": sector_name, "boundary": boundary,
        "session": None, "recorded": False, "runs": [], "gaps": [],
        "exit": None, "returned": None, "outside_s": None, "outside_distance_m": None, "outside_gap_s": None,
        "text_coords": _coords_in_text(risk["reason"], detected),
    }
    if not s:
        return out
    track = build_track(s["id"])
    out.update(session=track["session"], recorded=track["recorded"], runs=track["runs"], gaps=track["gaps"])
    if not track["recorded"]:
        return out

    conn = _conn()
    try:
        pts = [dict(r) for r in conn.execute(
            "SELECT latitude, longitude, inside_boundary, recorded_at FROM session_track_points "
            "WHERE session_id=? ORDER BY recorded_at, id", (s["id"],))]
    finally:
        conn.close()
    for p in pts:
        p["t"], p["inside"] = _parse(p["recorded_at"]), bool(p["inside_boundary"])
    t_ev = _parse(exit_at)
    candidates = [i for i, p in enumerate(pts) if not p["inside"] and (i == 0 or pts[i - 1]["inside"])]
    best = min(candidates, key=lambda i: abs((pts[i]["t"] - t_ev).total_seconds()), default=None) if t_ev else None
    if best is None or abs((pts[best]["t"] - t_ev).total_seconds()) > EXIT_MATCH_SECONDS:
        return out  # exit not found on the recorded route: route shown, exit figures stay "nav datu"

    i = best
    j = next((k for k in range(i + 1, len(pts)) if pts[k]["inside"]), None)
    inside = _inside_test(sector_row)
    secs = dist = gap_s = 0.0
    for a, b in zip(pts[max(i - 1, 0):(j + 1 if j is not None else len(pts))],
                    pts[max(i - 1, 0) + 1:(j + 1 if j is not None else len(pts))]):
        dt = (b["t"] - a["t"]).total_seconds()
        if dt > TRACK_GAP_SECONDS:
            gap_s += dt  # no positions: not counted as outside time or distance
            continue
        d = calculate_distance_meters(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
        if not a["inside"] and not b["inside"]:
            frac = 1.0
        elif a["inside"] != b["inside"]:
            f = _crossing(a, b, a["inside"], inside)
            frac = (1 - f) if a["inside"] else f
        else:
            frac = 0.0
        secs += dt * frac
        dist += d * frac
    p = pts[i]
    out["exit"] = {"lat": p["latitude"], "lon": p["longitude"], "time": p["recorded_at"], "local": _local(p["recorded_at"])}
    if j is not None:
        q = pts[j]
        out["returned"] = {"lat": q["latitude"], "lon": q["longitude"], "time": q["recorded_at"], "local": _local(q["recorded_at"])}
    out.update(outside_s=secs, outside_distance_m=dist, outside_gap_s=gap_s)
    return out
