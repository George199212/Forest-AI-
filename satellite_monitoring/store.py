"""API-side access to satellite.db (Stage 2, decision D2). Imported by the forest-api process (system python).

Imports only the standard library plus satellite_monitoring.config and .db (both stdlib-only): no numpy, tifffile,
pyproj or shapely, so nothing from the worker venv is needed.

  READ   every GET opens satellite.db with mode=ro (db.connect_ro); the API never creates or migrates it.
  WRITE  the four POST routes write ONLY small rows, in short BEGIN IMMEDIATE transactions with busy_timeout:
         a sat_jobs row (ADD_AREA / STOP_AREA / FETCH) for the worker to pick up, or a review: one
         sat_review_log row plus the event's status/reviewer/risk_id. Heavy work runs only in the worker.

Wording (D4): neutral. "Vegetation/land-cover change detected", "outside the approved boundary", "suspected".
"""
import fcntl
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, db as sdb, display

BUSY_TIMEOUT_MS = 5000
RECENT_DAYS = 14
LATEST_EVENTS = 10                             # /overview "Jaunākās izmaiņas" (current generation, across areas)                               # "with recent observations": last valid S2 or S1 within this
API_AREA_SOURCES = ("SECTOR", "LVM_GEO")       # EVAL_BBOX stays CLI-only
MAX_VERTICES = 5000
REVIEW_DECISIONS = ("CONFIRM", "REJECT", "FIELD_CHECK", "CREATE_RISK", "UNDO")
HUMAN_STATUS = {"CONFIRM": "REVIEW_CONFIRMED", "REJECT": "REVIEW_REJECTED", "FIELD_CHECK": "FIELD_CHECK_REQUESTED"}
AUTO_STATUSES = ("SUSPECTED", "RECOVERED")
RISK_CLASSES = ("POTENTIAL_FOREST_LOSS", "POTENTIAL_CHANGE_OUTSIDE_BOUNDARY")
FORBIDDEN_WORDS = ("illegal", "violation", "confirmed felling")


class StoreError(Exception):
    """status = HTTP status the route returns; message is safe to show."""

    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


# ── connections ──────────────────────────────────────────────────────────────
def ro():
    path = config.sat_db_path()
    if not Path(path).exists():
        raise StoreError(503, "satellite.db not available")
    try:
        conn = sdb.connect_ro(path)
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("SELECT 1 FROM sat_monitored_areas LIMIT 1")
    except sqlite3.Error:
        raise StoreError(503, "satellite.db not readable")
    return conn


def rw():
    """Short-lived read-write handle for the small API writes. No schema creation or migration (the worker owns
    the schema); refuses when the worker has not yet created the Stage 2 table."""
    path = config.sat_db_path()
    if not Path(path).exists():
        raise StoreError(503, "satellite.db not available")
    conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    missing = queue_schema_missing(conn)
    if missing:
        conn.close()
        raise StoreError(503, "satellite.db schema not migrated for Stage 2 (run the worker once)", missing=missing)
    return conn


# What the API's writes (rw) need. The API never creates these: the worker migrates satellite.db on its first run.
QUEUE_REQUIRED_TABLES = ("sat_jobs", "sat_review_log")
QUEUE_REQUIRED_COLUMNS = (("sat_change_events", "risk_carried_from_event_id"),
                          ("sat_change_events", "risk_carry_overlap"))


def queue_schema_missing(conn):
    """['table sat_jobs', 'column sat_change_events.risk_carry_overlap', ...]; empty = the queue schema is ready."""
    out = [f"table {t}" for t in QUEUE_REQUIRED_TABLES if not _has_table(conn, t)]
    for t, c in QUEUE_REQUIRED_COLUMNS:
        if _has_table(conn, t) and c not in _columns(conn, t):
            out.append(f"column {t}.{c}")
    return out


def queue_state(conn):
    """Can THIS API process queue changes?  READY | NOT_MIGRATED (schema missing, listed) | READ_ONLY (no write
    access to satellite.db or its directory for the journal: deployment makes the API read-only)."""
    missing = queue_schema_missing(conn)
    path = Path(config.sat_db_path())
    writable = os.access(path, os.W_OK) and os.access(path.parent, os.W_OK)
    state = "NOT_MIGRATED" if missing else ("READ_ONLY" if not writable else "READY")
    return {"state": state, "missing": missing, "api_can_write": writable}


def provider_state(conn, last_run):
    """Copernicus access as the WORKER last saw it (sat_provider_status + latest sat_runs), never this process's env:
    the worker runs with its own environment. States:
      OK              a provider call succeeded and nothing failed after it
      DEGRADED        the latest token/catalog/process call or the latest run failed after the last success
      NOT_CONFIGURED  the worker itself reported missing credentials (CdseError NOT_CONFIGURED), newest event
      UNKNOWN         no provider status rows and no runs: the worker has not contacted Copernicus yet"""
    rows = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM sat_provider_status")}
    last_ok = max((r["last_ok_utc"] for r in rows.values() if r.get("last_ok_utc")), default=None)
    out = {"state": "UNKNOWN", "last_ok_utc": last_ok, "at_utc": None, "source": None, "error": None,
           "auth_failure": False}
    failures = [(r["last_error_utc"], f"provider:{k}", r.get("last_error"))
                for k, r in rows.items() if r.get("last_error_utc") and r["last_error_utc"] > (r.get("last_ok_utc") or "")]
    if last_run and last_run.get("status") == "FAILED":
        failures.append((last_run.get("finished_at") or last_run.get("started_at"), f"run:{last_run['id']}",
                         last_run.get("stop_reason")))
    failures = [f for f in failures if f[0] and f[0] > (last_ok or "")]
    if failures:
        at, source, err = max(failures, key=lambda f: f[0])
        not_conf = str(err or "").startswith("NOT_CONFIGURED")
        out.update(state="NOT_CONFIGURED" if not_conf else "DEGRADED", at_utc=at, source=source,
                   error=(str(err)[:300] if err else None),
                   auth_failure=str(err or "").startswith(("AUTH", "NOT_CONFIGURED")))
    elif last_ok:
        out.update(state="OK", at_utc=last_ok, source="provider")
    return out


def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _now():
    return sdb.iso(sdb.utcnow())


def _j(v, default=None):
    if v is None or v == "":
        return default
    try:
        return json.loads(v)
    except ValueError:
        return default


# ── wording (D4) ─────────────────────────────────────────────────────────────
def event_summary(ev):
    """Neutral one-line description. Missing values stay 'unknown' (never 0)."""
    def ha(v):
        return "unknown" if v is None else f"{v:.2f} ha"
    parts = [f"Suspected vegetation/land-cover change detected: {ha(ev.get('changed_area_ha'))}"]
    if ev.get("changed_area_ha_buffer"):
        parts.append(f"{ha(ev.get('changed_area_ha_buffer'))} outside the approved boundary")
    if ev.get("classification") == "POSSIBLE_SEASONAL_OR_ENVIRONMENTAL":
        parts.append("possibly seasonal or environmental")
    if ev.get("status") == "RECOVERED":
        parts.append("change no longer visible (recovered)")
    return "; ".join(parts) + "."


# ── lock state (read-only; never creates the lock file) ─────────────────────
def lock_state():
    path = config.raster_root() / ".sat-monitoring.lock"
    if not path.exists():
        return {"locked": False}
    try:
        with open(path, "r") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.flock(fh, fcntl.LOCK_UN)
                return {"locked": False}
            except BlockingIOError:
                info = _j(fh.read(), {}) or {}
                return {"locked": True, **{k: info.get(k) for k in ("pid", "since_utc")}}
    except OSError:
        return {"locked": None, "error": "lock file not readable"}


# ── reads ────────────────────────────────────────────────────────────────────
def _days_between(a, b):
    fa = datetime.strptime(a[:19], "%Y-%m-%dT%H:%M:%S")
    fb = datetime.strptime(b[:19], "%Y-%m-%dT%H:%M:%S")
    return round((fb - fa).total_seconds() / 86400.0, 1)


def _area_public(a):
    return {k: a[k] for k in ("id", "source", "source_ref", "name", "area_ha", "buffer_m", "added_by",
                              "added_at_utc", "removed_at_utc")} | {"active": bool(a["active"])}


def _open_jobs(conn, area=None):
    """Open (QUEUED/RUNNING) jobs; with `area`, only those about it: STOP/FETCH by area id, FETCH all, and the
    ADD_AREA job that created it (matched by source + source_ref; it stays RUNNING during the first backfill)."""
    if not _has_table(conn, "sat_jobs"):
        return []
    rows = [dict(r) for r in conn.execute("SELECT id, kind, payload_json, status, requested_by, requested_at_utc, "
                                          "started_at_utc FROM sat_jobs WHERE status IN ('QUEUED','RUNNING') "
                                          "ORDER BY id")]
    out = []
    for r in rows:
        p = _j(r.pop("payload_json"), {})
        r["payload"] = {k: v for k, v in p.items() if k != "geometry"}
        if (area is None or p.get("area_id") == area["id"] or (r["kind"] == "FETCH" and p.get("all"))
                or (r["kind"] == "ADD_AREA" and (p.get("source"), p.get("source_ref")) == (area["source"],
                                                                                           area["source_ref"]))):
            out.append(r)
    return out


def _area_stats(conn, a, now):
    cfg = config.DEFAULTS
    q = lambda sql, *p: conn.execute(sql, (a["id"], *p)).fetchone()
    s1 = q("SELECT MAX(sensing_time_utc) FROM sat_acquisitions WHERE monitored_area_id=? AND sensor='S1' "
           "AND status='OK'")[0]
    s2 = q("SELECT sensing_time_utc, valid_pct_inside FROM sat_acquisitions WHERE monitored_area_id=? AND sensor='S2' "
           "AND status='OK' AND valid_pct_inside>=? ORDER BY sensing_time_utc DESC LIMIT 1", cfg["min_valid_pct"])
    last_s2_any = q("SELECT sensing_time_utc, status, valid_pct_inside FROM sat_acquisitions WHERE "
                    "monitored_area_id=? AND sensor='S2' ORDER BY sensing_time_utc DESC LIMIT 1")
    n_ok = q("SELECT COUNT(*) FROM sat_acquisitions WHERE monitored_area_id=? AND status='OK'")[0]
    cur = sdb.current_only(conn, "sat_change_events")
    counts = {r[0]: r[1] for r in conn.execute(
        "SELECT status, COUNT(*) FROM sat_change_events WHERE monitored_area_id=?" + cur + " GROUP BY status",
        (a["id"],))}
    since = (now - timedelta(days=cfg["area_backfill_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    times = [r[0] for r in conn.execute(
        "SELECT sensing_time_utc FROM sat_acquisitions WHERE monitored_area_id=? AND sensor='S2' AND status='OK' "
        "AND valid_pct_inside>=? AND sensing_time_utc>=? ORDER BY sensing_time_utc",
        (a["id"], cfg["min_valid_pct"], since))]
    now_s = sdb.iso(now)
    gaps = [_days_between(x, y) for x, y in zip(times, times[1:])]
    jobs = _open_jobs(conn, a)
    if not a["active"]:
        data_status = "STOPPED"
    elif any(j["kind"] == "ADD_AREA" or (j["kind"] == "FETCH" and j["status"] == "RUNNING") for j in jobs):
        data_status = "BACKFILL_OR_FETCH_IN_PROGRESS"
    elif n_ok == 0:
        data_status = "NO_DATA_YET"
    else:
        data_status = "OK"
    recent = [t for t in (s1, s2[0] if s2 else None) if t]
    grid = _j(a.get("grid_json"), {}) or {}
    return {
        **_area_public(a),
        "geometry": _j(a.get("geometry_geojson")),
        "grid_bbox": grid.get("bbox"),
        "data_status": data_status,
        "recent_observation": bool(recent) and min(_days_between(t, now_s) for t in recent) <= RECENT_DAYS,
        "last_s1_utc": s1,
        "last_valid_s2_utc": s2[0] if s2 else None,
        "last_valid_s2_valid_pct": s2[1] if s2 else None,
        "last_s2_any": dict(last_s2_any) if last_s2_any else None,
        "open_suspected_events": counts.get("SUSPECTED", 0) + counts.get("FIELD_CHECK_REQUESTED", 0),
        "recovered_events": counts.get("RECOVERED", 0),            # shown separately, not counted as open
        "reviewed_events": counts.get("REVIEW_CONFIRMED", 0) + counts.get("REVIEW_REJECTED", 0),
        "gaps": {
            "days_since_last_valid_s2": _days_between(s2[0], now_s) if s2 else None,
            "days_since_last_s1": _days_between(s1, now_s) if s1 else None,
            "max_gap_days_valid_s2_window": max(gaps) if gaps else None,
            "window_days": cfg["area_backfill_days"],
        },
        "open_jobs": jobs,
    }


def overview(now=None):
    now = now or sdb.utcnow()
    conn = ro()
    try:
        areas = [dict(r) for r in conn.execute("SELECT * FROM sat_monitored_areas ORDER BY active DESC, id")]
        stats = [_area_stats(conn, a, now) for a in areas]
        known = {(a["source"], a["source_ref"]) for a in areas if a["active"]}
        pending = [j for j in _open_jobs(conn) if j["kind"] == "ADD_AREA"
                   and (j["payload"].get("source"), j["payload"].get("source_ref")) not in known]
        active = [s for s in stats if s["active"]]
        kpis = {
            "monitored_areas": len(active),
            "with_recent_observations": sum(1 for s in active if s["recent_observation"]),
            "awaiting_data": sum(1 for s in active if s["data_status"] in ("NO_DATA_YET",
                                                                            "BACKFILL_OR_FETCH_IN_PROGRESS"))
                             + len(pending),
            "open_suspected_events": sum(s["open_suspected_events"] for s in active),
            "recovered_events": sum(s["recovered_events"] for s in active),
            "recent_days": RECENT_DAYS,
        }
        names = {a["id"]: a["name"] for a in areas}
        latest = []
        for e in conn.execute("SELECT * FROM sat_change_events WHERE 1=1" + sdb.current_only(conn, "sat_change_events")
                              + " ORDER BY detected_at_utc DESC, id DESC LIMIT ?", (LATEST_EVENTS,)):
            e = dict(e)
            latest.append({k: e.get(k) for k in (
                "id", "monitored_area_id", "status", "classification", "confidence", "evidence_quality",
                "changed_area_ha", "changed_area_ha_inside", "changed_area_ha_buffer", "first_after_time_utc",
                "detected_at_utc", "updated_at_utc", "sensor_basis")} | {"area_name": names.get(e["monitored_area_id"])})
        return {"generated_at_utc": sdb.iso(now), "kpis": kpis, "areas": stats, "pending_area_jobs": pending,
                "latest_events": latest,
                "labels": {"interpretation": "automated, suspected change only", "attribution":
                           "Contains modified Copernicus Sentinel data " + str(now.year)}}
    finally:
        conn.close()


def _event_public(ev):
    e = {k: ev.get(k) for k in (
        "id", "monitored_area_id", "sensor_basis", "detected_at_utc", "updated_at_utc", "first_after_time_utc",
        "last_after_time_utc", "changed_area_ha", "changed_area_ha_inside", "changed_area_ha_buffer",
        "pct_of_area_affected", "max_distance_outside_boundary_m", "largest_cluster_ha", "union_area_ha",
        "max_area_ha", "confidence", "evidence_quality", "classification", "seasonal_caveat", "status",
        "recovered_at_utc", "recovered_reason", "risk_id", "risk_carried_from_event_id", "reviewed_by",
        "reviewed_at_utc", "review_note", "superseded_at_utc", "superseded_by_generation")}
    e["compartment_split"] = _j(ev.get("compartment_split_json"))
    e["status_kind"] = "AUTOMATIC" if ev.get("status") in AUTO_STATUSES else "HUMAN"
    e["summary"] = event_summary(ev)
    e["current"] = ev.get("superseded_at_utc") is None
    return e


def _history_fields(e):
    """Onset acquisition + before/after ids from the stored event history (read-only)."""
    hist = _j(e.get("after_acq_history_json"), []) or []
    onset = min(hist, key=lambda h: h.get("time") or "") if hist else None
    return {"onset_acq_id": onset.get("acq_id") if onset else None, "onset_sensor": onset.get("sensor") if onset else None,
            "before_acq_ids": _j(e.get("before_acq_ids"), []) or [], "after_acq_ids": [h.get("acq_id") for h in hist]}


def area_detail(area_id, geometry=True):
    conn = ro()
    try:
        a = conn.execute("SELECT * FROM sat_monitored_areas WHERE id=?", (area_id,)).fetchone()
        if not a:
            raise StoreError(404, "area not found")
        a = dict(a)
        met = {}
        for m in conn.execute("SELECT m.* FROM sat_area_metrics m JOIN sat_acquisitions q ON q.id=m.acquisition_id "
                              "WHERE q.monitored_area_id=? AND m.zone='INSIDE'", (area_id,)):
            met.setdefault(m["acquisition_id"], {})[m["metric"]] = (
                {"median": m["median"], "mean": m["mean"]} if m["median"] is not None
                else {"median": None, "mean": None, "null_reason": m["null_reason"] or "no data"})
        det = {d["acquisition_id"]: d["outcome"] for d in conn.execute(
            "SELECT acquisition_id, outcome FROM sat_detections WHERE monitored_area_id=?"
            + sdb.current_only(conn, "sat_detections"), (area_id,))}
        timeline = []
        for r in conn.execute("SELECT * FROM sat_acquisitions WHERE monitored_area_id=? ORDER BY sensing_time_utc, "
                              "sensor", (area_id,)):
            timeline.append({
                "acq_id": r["id"], "sensor": r["sensor"], "sensing_time_utc": r["sensing_time_utc"],
                "product_id": r["product_id"],
                "status": r["status"], "platform": r["platform"], "orbit_direction": r["orbit_direction"],
                "relative_orbit": r["relative_orbit"], "scene_cloud_pct": r["scene_cloud_pct"],
                "valid_pct_inside": r["valid_pct_inside"], "valid_pct_buffer": r["valid_pct_buffer"],
                # NULL gaps are kept: a metric missing for this acquisition is reported with its reason
                "metrics_inside": met.get(r["id"], {}), "detection": det.get(r["id"]),
                "quicklook_url": (f"/api/sat-monitoring/file/{r['id']}/quicklook" if r["quicklook_path"] else None),
                "truecolor_url": _truecolor_url(r["id"], r["quicklook_path"]),
            })
        events = []
        for e in conn.execute("SELECT * FROM sat_change_events WHERE monitored_area_id=?"
                              + sdb.current_only(conn, "sat_change_events") + " ORDER BY id", (area_id,)):
            pub = _event_public(dict(e))
            pub.update(_history_fields(dict(e)))
            if geometry:                                              # ?geometry=0: map uses the simplified /map-layer
                pub["change_geojson"] = _j(e["change_geojson"])      # CURRENT mask (zone INSIDE / BUFFER)
            events.append(pub)
        radar = []
        if _has_table(conn, "sat_radar_anomalies"):
            radar = [dict(r) for r in conn.execute(
                "SELECT id, acquisition_id, sensing_time_utc, orbit_direction, relative_orbit, changed_area_ha, "
                "evidence_quality, status, promotion_rule, event_id FROM sat_radar_anomalies WHERE monitored_area_id=?"
                + sdb.current_only(conn, "sat_radar_anomalies") + " ORDER BY sensing_time_utc", (area_id,))]
        last_analysis = conn.execute("SELECT MAX(ran_at_utc) FROM sat_detections WHERE monitored_area_id=?"
                                     + sdb.current_only(conn, "sat_detections"), (area_id,)).fetchone()[0]
        geom = _j(a["geometry_geojson"])
        return {"area": _area_stats(conn, a, sdb.utcnow()), "geometry": geom,
                "buffer_ring": display.buffer_ring(geom, a["buffer_m"]) if geom else None,
                "timeline": timeline, "events": events, "radar_anomalies": radar,
                # processing time of the last current-generation detection for this area (NOT an acquisition time)
                "last_successful_analysis_utc": last_analysis,
                "config": {"min_valid_pct": config.DEFAULTS["min_valid_pct"]},
                "attribution": _attribution(timeline)}
    finally:
        conn.close()


def _attribution(items):
    """'Contains modified Copernicus Sentinel data [YEAR]' with the sensing year(s) of the images shown."""
    years = sorted({str(x.get("sensing_time_utc", ""))[:4] for x in items if x.get("sensing_time_utc")})
    years = [y for y in years if y.isdigit()]
    span = (years[0] if len(years) == 1 else f"{years[0]}-{years[-1]}") if years else str(sdb.utcnow().year)
    return f"Contains modified Copernicus Sentinel data {span}"


def _acq_brief(conn, acq_id):
    r = conn.execute("SELECT id, sensor, product_id, platform, orbit_direction, relative_orbit, sensing_time_utc, "
                     "status, valid_pct_inside, quicklook_path FROM sat_acquisitions WHERE id=?", (acq_id,)).fetchone()
    if not r:
        return {"acq_id": acq_id, "missing": True}
    return {"acq_id": r["id"], "sensor": r["sensor"], "product_id": r["product_id"], "platform": r["platform"],
            "orbit_direction": r["orbit_direction"], "relative_orbit": r["relative_orbit"],
            "sensing_time_utc": r["sensing_time_utc"],
            "status": r["status"], "valid_pct_inside": r["valid_pct_inside"],
            "quicklook_url": f"/api/sat-monitoring/file/{r['id']}/quicklook" if r["quicklook_path"] else None,
            "truecolor_url": _truecolor_url(r["id"], r["quicklook_path"])}


def _algorithm(conn, ev):
    """Which detection produced the current row: the detection generation (redetect) whose run covers the event's
    creation time, else a regular pipeline run (no code version recorded for those)."""
    out = {"thresholds": _j(ev.get("thresholds_json"), {}), "generation_id": None, "code_version": None,
           "source": "pipeline run (code version not recorded)"}
    if not _has_table(conn, "sat_detection_generations"):
        return out
    for g in conn.execute("SELECT * FROM sat_detection_generations WHERE status='OK' ORDER BY id DESC"):
        if ev["monitored_area_id"] in (_j(g["area_ids"], []) or []) and g["created_at_utc"] <= ev["detected_at_utc"] \
                <= (g["finished_at_utc"] or "9999"):
            out.update(generation_id=g["id"], code_version=g["code_version"],
                       source=f"detection generation {g['id']} (redetect over stored acquisitions)")
            break
    return out


def event_detail(event_id):
    conn = ro()
    try:
        ev = conn.execute("SELECT * FROM sat_change_events WHERE id=?", (event_id,)).fetchone()
        if not ev:
            raise StoreError(404, "event not found")
        ev = dict(ev)
        out = _event_public(ev)
        out["change_geojson"] = _j(ev["change_geojson"])
        out["operational_context"] = _j(ev["gps_context_json"])
        out["thresholds"] = _j(ev["thresholds_json"])
        out["before"] = [_acq_brief(conn, i) for i in (_j(ev["before_acq_ids"], []) or [])]
        # Per-acquisition evidence quality as stored in the history (owner D2/Q2, read-only): the event-level value is
        # the best over this list (pipeline.py), so the UI can say which acquisition it comes from. None when not stored.
        out["after"] = [dict(_acq_brief(conn, h["acq_id"]), evidence_quality=h.get("evidence_quality"))
                        for h in (_j(ev["after_acq_history_json"], []) or [])]
        out["review_log"] = [dict(r) for r in conn.execute(
            "SELECT id, action, actor, old_status, new_status, note, created_at_utc FROM sat_review_log "
            "WHERE event_id=? ORDER BY id", (event_id,))]
        a = dict(conn.execute("SELECT * FROM sat_monitored_areas WHERE id=?", (ev["monitored_area_id"],)).fetchone())
        geometry = _j(a["geometry_geojson"])
        out["area"] = {**_area_public(a), "geometry": geometry, "grid_bbox": (_j(a["grid_json"], {}) or {}).get("bbox"),
                       "buffer_ring": display.buffer_ring(geometry, a["buffer_m"]) if geometry else None}
        out["algorithm"] = _algorithm(conn, ev)
        out["undo_available"] = _last_undoable(conn, event_id) is not None
        out["attribution"] = _attribution(out["before"] + out["after"])
        return out
    finally:
        conn.close()


def quicklook_file(acq_id, kind):
    """Path for GET /file/{acq_id}/{kind}. Only 'quicklook'; the path is taken from the DB, never from the
    request, and must resolve inside the raster root (symlinks and '..' resolved)."""
    if kind not in ("quicklook", "truecolor"):
        raise StoreError(404, "not found")
    conn = ro()
    try:
        r = conn.execute("SELECT quicklook_path FROM sat_acquisitions WHERE id=?", (acq_id,)).fetchone()
    finally:
        conn.close()
    if not r or not r["quicklook_path"]:
        raise StoreError(404, "not found")
    root = config.raster_root().resolve()
    p = Path(r["quicklook_path"])
    if not p.is_absolute():
        p = Path(os.getcwd()) / p
    if kind == "truecolor":
        p = _tc_path(p)
    p = p.resolve()
    if root not in p.parents or p.suffix.lower() != ".png" or not p.is_file():
        raise StoreError(404, "not found")
    return p


# ── worker installation / timers (read-only, systemd) ───────────────────────
WORKER_UNITS = {"jobs": "forest-satellite-jobs", "sync": "forest-satellite-sync"}
_TIMER_PROPS = ("LoadState", "ActiveState", "UnitFileState", "NextElapseUSecRealtime", "LastTriggerUSec")
_SERVICE_PROPS = ("LoadState", "ActiveState", "Result", "ExecMainStatus", "ExecMainExitTimestamp")


def _systemctl_show(unit, props):
    """{prop: value} from `systemctl show` (read-only), or None if systemd cannot be asked."""
    import subprocess
    try:
        r = subprocess.run(["systemctl", "show", unit, "--timestamp=utc"] + [a for p in props for a in ("-p", p)],
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)


def _utc_iso(v):
    """'Mon 2026-11-16 17:08:16 UTC' -> '2026-11-16T17:08:16Z'; empty/unknown -> None."""
    import re
    m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) UTC", v or "")
    return f"{m.group(1)}T{m.group(2)}Z" if m else None


def worker_state(lock=None):
    """The satellite worker as systemd sees it (UI review item 6): NOT_INSTALLED (no worker units), RUNNING (a run
    holds the lock or a worker service is active), IDLE (installed and both timers active), TIMERS_OFF (installed, a
    timer is not active), UNKNOWN (systemd could not be asked). 'Idle' is never shown for a worker that is not there."""
    lock = lock if lock is not None else lock_state()
    units = {}
    for key, name in WORKER_UNITS.items():
        t, s = _systemctl_show(name + ".timer", _TIMER_PROPS), _systemctl_show(name + ".service", _SERVICE_PROPS)
        if t is None or s is None:
            return {"state": "UNKNOWN", "units": {}, "reason": "systemctl not available"}
        units[key] = {
            "installed": s.get("LoadState") == "loaded",
            "timer_active": t.get("ActiveState") == "active", "timer_enabled": t.get("UnitFileState") == "enabled",
            "next_run_utc": _utc_iso(t.get("NextElapseUSecRealtime")),
            "last_trigger_utc": _utc_iso(t.get("LastTriggerUSec")),
            "service_active": s.get("ActiveState") in ("active", "activating", "reloading"),
            "last_exit_utc": _utc_iso(s.get("ExecMainExitTimestamp")),
            "last_result": s.get("Result") or None, "last_exit_status": s.get("ExecMainStatus") or None}
    if not any(u["installed"] for u in units.values()):
        state = "NOT_INSTALLED"
    elif lock.get("locked") or any(u["service_active"] for u in units.values()):
        state = "RUNNING"
    elif all(u["installed"] and u["timer_active"] for u in units.values()):
        state = "IDLE"
    else:
        state = "TIMERS_OFF"
    return {"state": state, "units": units}


def _tc_path(quicklook_path):
    """Same rule as raster.truecolor_path (raster imports numpy; the API stays stdlib-only)."""
    p = Path(quicklook_path)
    return p.with_name(p.stem + "_tc.png")


def _truecolor_url(acq_id, quicklook_path):
    """URL of the true-colour quicklook (B04/B03/B02) when that file exists; None otherwise (shown as unavailable)."""
    if not quicklook_path:
        return None
    try:
        return f"/api/sat-monitoring/file/{acq_id}/truecolor" if _tc_path(quicklook_path).is_file() else None
    except OSError:
        return None


def health(now=None):
    now = now or sdb.utcnow()
    conn = ro()
    try:
        last = conn.execute("SELECT * FROM sat_runs ORDER BY id DESC LIMIT 1").fetchone()
        last = dict(last) if last else None
        if last:
            last["errors"] = _j(last.pop("errors_json"), [])
        usage = sdb.month_usage(conn, now)
        provider = [dict(r) for r in conn.execute("SELECT * FROM sat_provider_status ORDER BY key")]
        jobs = {}
        failed = []
        if _has_table(conn, "sat_jobs"):
            jobs = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM sat_jobs GROUP BY status")}
            failed = [dict(r) for r in conn.execute(
                "SELECT id, kind, error_text, finished_at_utc FROM sat_jobs WHERE status='FAILED' ORDER BY id DESC "
                "LIMIT 5")]
        cfg = config.DEFAULTS
        ok = conn.execute("SELECT id, trigger, finished_at FROM sat_runs WHERE status IN ('OK','PARTIAL') "
                          "AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1").fetchone()
        g = cfg["guard_stop_fraction"]
        return {
            "last_run": last,
            "last_successful_sync": dict(ok) if ok else None,
            "month": {**usage, "pu_budget": cfg["monthly_pu_budget"], "request_budget": cfg["monthly_request_budget"],
                      "guard_stop_fraction": g, "pu_guard": round(cfg["monthly_pu_budget"] * g, 1),
                      "request_guard": int(cfg["monthly_request_budget"] * g)},
            "provider_status": provider,
            "lock": lock_state(),
            "worker": worker_state(),
            "jobs": jobs, "failed_jobs": jobs.get("FAILED", 0), "recent_failed_jobs": failed,
            "schema_stage2": not queue_schema_missing(conn),
            "queue": queue_state(conn),
            # From the worker's own records, never this process's environment (the worker has its own env).
            "provider": provider_state(conn, last),
            "auto_risk_enabled": bool(cfg["auto_risk_enabled"]),
        }
    finally:
        conn.close()


def _has_polygon(boundary_json):
    v = (boundary_json or "").strip()
    return bool(v) and v not in ("[]", "null", "{}")


def sectors():
    """Sectors from the main forest_ai.db (READ-ONLY) for "Add sector": polygon present?, already monitored?"""
    path = config.forest_db_path()
    if not Path(path).exists():
        raise StoreError(503, "forest_ai.db not available")
    fc = sdb.forest_ro(path)
    try:
        rows = [dict(r) for r in fc.execute("SELECT id, name, boundary_json FROM sectors ORDER BY name")]
    finally:
        fc.close()
    conn = ro()
    try:
        active = {r["source_ref"]: r["id"] for r in conn.execute(
            "SELECT id, source_ref FROM sat_monitored_areas WHERE source='SECTOR' AND active=1")}
        queued = {j["payload"].get("source_ref"): j["id"] for j in _open_jobs(conn)
                  if j["kind"] == "ADD_AREA" and j["payload"].get("source") == "SECTOR"}
    finally:
        conn.close()
    return {"sectors": [{"id": r["id"], "name": r["name"], "has_polygon": _has_polygon(r["boundary_json"]),
                         "monitored_area_id": active.get(str(r["id"])), "queued_job_id": queued.get(str(r["id"]))}
                        for r in rows]}


def lookup(source, source_ref):
    """Is this object monitored? For the LVM GEO button ("Already monitored")."""
    if source not in sdb.AREA_SOURCES or not source_ref:
        raise StoreError(422, "source and source_ref are required")
    conn = ro()
    try:
        a = conn.execute("SELECT id FROM sat_monitored_areas WHERE source=? AND source_ref=? AND active=1",
                         (source, str(source_ref))).fetchone()
        job = next((j for j in _open_jobs(conn) if j["kind"] == "ADD_AREA" and j["payload"].get("source") == source
                    and j["payload"].get("source_ref") == str(source_ref)), None)
    finally:
        conn.close()
    return {"monitored": bool(a), "area_id": a["id"] if a else None, "queued_job_id": job["id"] if job else None}


# ── writes: jobs ─────────────────────────────────────────────────────────────
def _queue(conn, kind, payload, dedup_key, actor):
    """Insert a job unless an open job with the same key exists (then return that one)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT id, status FROM sat_jobs WHERE dedup_key=? AND status IN ('QUEUED','RUNNING')",
                           (dedup_key,)).fetchone()
        if row:
            conn.execute("COMMIT")
            return {"job_id": row["id"], "status": row["status"], "deduplicated": True}
        jid = conn.execute("INSERT INTO sat_jobs (kind, payload_json, dedup_key, requested_by, requested_at_utc) "
                           "VALUES (?,?,?,?,?)", (kind, sdb.dumps(payload), dedup_key, actor, _now())).lastrowid
        conn.execute("COMMIT")
        return {"job_id": jid, "status": "QUEUED", "deduplicated": False}
    except Exception:
        conn.execute("ROLLBACK")
        raise


def validate_geometry(g):
    """Light structural check in the API (no shapely here). Full validity, area limits and the grid are checked
    by the worker (areas.prepare) when it runs the job; an invalid polygon ends as a FAILED job."""
    if not isinstance(g, dict) or g.get("type") not in ("Polygon", "MultiPolygon"):
        raise StoreError(422, "geometry must be a GeoJSON Polygon or MultiPolygon (lon/lat, CRS84)")
    polys = [g.get("coordinates")] if g["type"] == "Polygon" else g.get("coordinates")
    if not isinstance(polys, list) or not polys:
        raise StoreError(422, "geometry has no coordinates")
    lo_x, lo_y, hi_x, hi_y = config.DEFAULTS["latvia_bbox"]
    n = 0
    for poly in polys:
        if not isinstance(poly, list) or not poly:
            raise StoreError(422, "polygon has no rings")
        for ring in poly:
            if not isinstance(ring, list) or len(ring) < 4:
                raise StoreError(422, "each ring needs at least 4 positions")
            for pt in ring:
                if (not isinstance(pt, (list, tuple)) or len(pt) < 2
                        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in pt[:2])
                        or not all(math.isfinite(v) for v in pt[:2])):
                    raise StoreError(422, "positions must be [lon, lat] numbers")
                if not (lo_x <= pt[0] <= hi_x and lo_y <= pt[1] <= hi_y):
                    raise StoreError(422, "geometry is outside Latvia (expects lon/lat, CRS84)")
            if list(ring[0][:2]) != list(ring[-1][:2]):
                raise StoreError(422, "rings must be closed")
            n += len(ring)
    if n > MAX_VERTICES:
        raise StoreError(422, f"geometry has more than {MAX_VERTICES} vertices")
    return g


def queue_add_area(source, source_ref, name, geometry, actor):
    if source not in API_AREA_SOURCES:
        raise StoreError(422, "source must be one of " + ", ".join(API_AREA_SOURCES))
    source_ref = (str(source_ref).strip() if source_ref is not None else "")
    name = (str(name).strip() if name is not None else "")
    if not source_ref or len(source_ref) > 128:
        raise StoreError(422, "source_ref is required (max 128 characters)")
    if not name or len(name) > 200:
        raise StoreError(422, "name is required (max 200 characters)")
    if geometry is None:
        if source != "SECTOR":
            raise StoreError(422, "geometry is required for LVM_GEO")
    else:
        validate_geometry(geometry)
        if geometry["type"] == "MultiPolygon":          # the worker grid accepts one Polygon only
            if len(geometry["coordinates"]) != 1:
                raise StoreError(422, "multi-part polygons are not supported; add each part separately")
            geometry = {"type": "Polygon", "coordinates": geometry["coordinates"][0]}
    conn = rw()
    try:
        ex = conn.execute("SELECT id FROM sat_monitored_areas WHERE source=? AND source_ref=? AND active=1",
                          (source, source_ref)).fetchone()
        if ex:
            raise StoreError(409, "already monitored", area_id=ex["id"])
        return _queue(conn, "ADD_AREA", {"source": source, "source_ref": source_ref, "name": name,
                                         "geometry": geometry, "added_by": actor},
                      f"ADD_AREA:{source}:{source_ref}", actor)
    finally:
        conn.close()


def queue_stop_area(area_id, actor):
    conn = rw()
    try:
        a = conn.execute("SELECT id, active FROM sat_monitored_areas WHERE id=?", (area_id,)).fetchone()
        if not a:
            raise StoreError(404, "area not found")
        if not a["active"]:
            raise StoreError(409, "area already stopped", area_id=area_id)
        return _queue(conn, "STOP_AREA", {"area_id": area_id}, f"STOP_AREA:{area_id}", actor)
    finally:
        conn.close()


def queue_fetch(area_id, all_areas, actor):
    if bool(area_id) == bool(all_areas):
        raise StoreError(422, "give exactly one of area_id or all=true")
    conn = rw()
    try:
        if area_id:
            a = conn.execute("SELECT id, active FROM sat_monitored_areas WHERE id=?", (area_id,)).fetchone()
            if not a:
                raise StoreError(404, "area not found")
            if not a["active"]:
                raise StoreError(409, "area is stopped", area_id=area_id)
            res = _queue(conn, "FETCH", {"area_id": area_id}, f"FETCH:{area_id}", actor)
        else:
            res = _queue(conn, "FETCH", {"all": True}, "FETCH:all", actor)
        res["lock"] = lock_state()
        return res
    finally:
        conn.close()


# ── writes: review ───────────────────────────────────────────────────────────
def load_current_event(event_id):
    conn = ro()
    try:
        ev = conn.execute("SELECT * FROM sat_change_events WHERE id=?", (event_id,)).fetchone()
        if not ev:
            raise StoreError(404, "event not found")
        ev = dict(ev)
        area = dict(conn.execute("SELECT * FROM sat_monitored_areas WHERE id=?", (ev["monitored_area_id"],)).fetchone())
    finally:
        conn.close()
    if ev.get("superseded_at_utc"):
        raise StoreError(409, "event was superseded by a later detection generation",
                         superseded_by_generation=ev.get("superseded_by_generation"))
    return ev, area


def apply_review(event_id, decision, actor, note=None, risk_id=None, expected_status=None):
    """One review row + the event change, atomically. Returns {old_status, new_status, risk_id, undone}.
    Guarded by expected_status (the status the caller looked at), so two reviewers never overwrite each other."""
    if decision not in REVIEW_DECISIONS:
        raise StoreError(422, "decision must be one of " + ", ".join(REVIEW_DECISIONS))
    if not actor:
        raise StoreError(401, "authenticated user required")
    note = (note or "").strip()[:2000] or None
    conn = rw()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            ev = conn.execute("SELECT * FROM sat_change_events WHERE id=?", (event_id,)).fetchone()
            if not ev:
                raise StoreError(404, "event not found")
            if ev["superseded_at_utc"]:
                raise StoreError(409, "event was superseded by a later detection generation")
            if expected_status is not None and ev["status"] != expected_status:
                raise StoreError(409, "event changed meanwhile; reload", status=ev["status"])
            old = ev["status"]
            now = _now()
            undone = None
            if decision == "CREATE_RISK":
                if ev["risk_id"] is not None and ev["risk_id"] != risk_id:
                    raise StoreError(409, "event already linked to a risk", risk_id=ev["risk_id"])
                conn.execute("UPDATE sat_change_events SET risk_id=? WHERE id=?", (risk_id, event_id))
                new, risk = old, risk_id
            elif decision == "UNDO":
                undone = _last_undoable(conn, event_id)
                if not undone:
                    raise StoreError(409, "nothing to undo")
                if undone["new_status"] != old:
                    raise StoreError(409, "status changed since the decision; nothing undone", status=old)
                new = undone["old_status"]
                prev = _previous_human(conn, event_id, undone["id"])
                conn.execute("UPDATE sat_change_events SET status=?, reviewed_by=?, reviewed_at_utc=?, review_note=? "
                             "WHERE id=?", (new, prev["actor"] if prev and new not in AUTO_STATUSES else None,
                                            prev["created_at_utc"] if prev and new not in AUTO_STATUSES else None,
                                            prev["note"] if prev and new not in AUTO_STATUSES else None, event_id))
                risk = ev["risk_id"]
                note = f"undo of review #{undone['id']} ({undone['action']})" + (f": {note}" if note else "")
            else:
                new = HUMAN_STATUS[decision]
                if new == old:
                    raise StoreError(409, f"event is already {old}")
                conn.execute("UPDATE sat_change_events SET status=?, reviewed_by=?, reviewed_at_utc=?, review_note=? "
                             "WHERE id=?", (new, actor, now, note, event_id))
                risk = ev["risk_id"]
            rid = conn.execute("INSERT INTO sat_review_log (event_id, action, actor, old_status, new_status, note, "
                               "created_at_utc) VALUES (?,?,?,?,?,?,?)",
                               (event_id, decision, actor, old, new, note, now)).lastrowid
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return {"review_id": rid, "event_id": event_id, "decision": decision, "old_status": old, "new_status": new,
                "risk_id": risk, "undone_review": undone}
    finally:
        conn.close()


def _status_entries(conn, event_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM sat_review_log WHERE event_id=? AND action IN ('CONFIRM','REJECT','FIELD_CHECK','UNDO') "
        "ORDER BY id", (event_id,))]


def _last_undoable(conn, event_id):
    """Undo works like a stack: each UNDO cancels the most recent not-yet-undone status decision.
    CREATE_RISK is never undone here (the risk follows its own workflow)."""
    stack = []
    for e in _status_entries(conn, event_id):
        if e["action"] == "UNDO":
            if stack:
                stack.pop()
        else:
            stack.append(e)
    return stack[-1] if stack else None


def _previous_human(conn, event_id, before_id):
    stack = []
    for e in _status_entries(conn, event_id):
        if e["id"] >= before_id:
            break
        if e["action"] == "UNDO":
            if stack:
                stack.pop()
        else:
            stack.append(e)
    return stack[-1] if stack else None


# ── Forest Map layer "Satelīta izmaiņas" (read-only) ────────────────────────
# Same bounded-response rule as the other Forest Map overlays: at most MAP_MAX_FEATURES features and MAP_MAX_BYTES
# of JSON. Geometry is simplified here (stdlib Douglas-Peucker, metric tolerance) step by step until it fits; the
# tolerance used is returned. The stored masks are never changed.
MAP_MAX_FEATURES = 600
MAP_MAX_BYTES = 400_000
MAP_AREA_MAX_BYTES = 150_000                  # per monitored area (features of that area, compact JSON)
MAP_TOLERANCES_ALL_M = (10, 20, 40, 80)       # all-areas layer: start coarse (≈2 px at z14)
MAP_TOLERANCES_SINGLE_M = (2, 5, 10, 20, 40, 80)  # one area / one event: start fine, step up until the area fits


def _jsize(obj):
    return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode())
STATUS_GROUP = {"SUSPECTED": "SUSPECTED", "RECOVERED": "RECOVERED"}   # every human status -> REVIEWED


def _dp(pts, tol):
    """Douglas-Peucker on [(x, y)] in metres; keeps the first and last point."""
    if len(pts) < 3 or tol <= 0:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, idx = -1.0, None
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * (x - x1) - dx * (y - y1)) / norm if norm else math.hypot(x - x1, y - y1)
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def _ring(ring, tol, kx, ky):
    pts = [(float(x) * kx, float(y) * ky) for x, y in (c[:2] for c in ring)]
    out = _dp(pts, tol)
    if len(out) < 4:                       # collapsed below a valid ring at this tolerance
        return None
    return [[round(x / kx, 6), round(y / ky, 6)] for x, y in out]


def _simplify(geom, tol):
    if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    lat0 = next((float(p[0][0][1]) for p in polys if p and p[0]), 57.0)
    kx, ky = 111_320.0 * math.cos(math.radians(lat0)), 110_574.0
    out = []
    for poly in polys:
        if not poly:
            continue
        shell = _ring(poly[0], tol, kx, ky)
        if shell is None:
            continue
        out.append([shell] + [h for h in (_ring(r, tol, kx, ky) for r in poly[1:]) if h])
    if not out:
        return None
    return {"type": "Polygon", "coordinates": out[0]} if len(out) == 1 else {"type": "MultiPolygon", "coordinates": out}


def _bbox_of(geoms):
    xs, ys = [], []
    for g in geoms:
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            for ring in poly:
                for x, y in ring:
                    xs.append(x)
                    ys.append(y)
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None


def _bbox_polygon(b):
    w, s, e, n = b
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def map_layer(area_id=None, event_id=None):
    """GeoJSON for the Forest Map layer: current change masks (sat_change_events.change_geojson, current generation
    only) of the requested area / the event's area / every active area, plus each area's observation footprint
    (worker grid bbox). 404 for an unknown or superseded event and an unknown area."""
    conn = ro()
    try:
        focus_event = None
        if event_id is not None:
            ev = conn.execute("SELECT * FROM sat_change_events WHERE id=?" + sdb.current_only(conn, "sat_change_events"),
                              (event_id,)).fetchone()
            if not ev:
                raise StoreError(404, "event not found")
            if area_id is not None and int(area_id) != ev["monitored_area_id"]:
                raise StoreError(422, "event does not belong to this area")
            focus_event, area_id = ev["id"], ev["monitored_area_id"]
        if area_id is not None:
            areas = [dict(r) for r in conn.execute("SELECT * FROM sat_monitored_areas WHERE id=?", (area_id,))]
            if not areas:
                raise StoreError(404, "area not found")
        else:
            areas = [dict(r) for r in conn.execute("SELECT * FROM sat_monitored_areas WHERE active=1 ORDER BY id")]
        names = {a["id"]: a["name"] for a in areas}
        raw = []                                # (props, geometry) before simplification
        for a in areas:
            bbox = (_j(a["grid_json"], {}) or {}).get("bbox")
            if bbox and len(bbox) == 4:
                raw.append(({"kind": "footprint", "area_id": a["id"], "area_name": a["name"]},
                            _bbox_polygon([float(v) for v in bbox])))
        ids = list(names)
        if ids:
            q = ("SELECT * FROM sat_change_events WHERE monitored_area_id IN (%s)" % ",".join("?" * len(ids))
                 + sdb.current_only(conn, "sat_change_events") + " ORDER BY id")
            for ev in conn.execute(q, ids):
                fc = _j(ev["change_geojson"], {}) or {}
                feats = fc.get("features") if fc.get("type") == "FeatureCollection" else (
                    [{"geometry": fc, "properties": {}}] if fc.get("type") in ("Polygon", "MultiPolygon") else [])
                for f in feats or []:
                    p = f.get("properties") or {}
                    raw.append(({
                        "kind": "event", "event_id": ev["id"], "area_id": ev["monitored_area_id"],
                        "area_name": names.get(ev["monitored_area_id"]), "zone": p.get("zone"),
                        "zone_ha": p.get("area_ha"), "area_ha": ev["changed_area_ha"],
                        "onset_utc": ev["first_after_time_utc"], "detected_at_utc": ev["detected_at_utc"],
                        "confidence": ev["confidence"], "classification": ev["classification"],
                        "sensor_basis": ev["sensor_basis"], "status": ev["status"],
                        "status_group": STATUS_GROUP.get(ev["status"], "REVIEWED"),
                        "event_url": f"#sat-monitoring?event={ev['id']}"}, f.get("geometry")))
        # Per area: step the tolerance until that area fits MAP_AREA_MAX_BYTES (one dense area never coarsens the
        # others); then the whole response must still fit MAP_MAX_FEATURES / MAP_MAX_BYTES, else 413.
        steps = MAP_TOLERANCES_SINGLE_M if (area_id is not None) else MAP_TOLERANCES_ALL_M
        feats, tol_by_area = [], {}
        for a in areas:
            mine = [(p, g) for p, g in raw if p["area_id"] == a["id"]]
            for tol in steps:
                part = []
                for props, g in mine:
                    sg = _simplify(g, tol) if props["kind"] == "event" else g
                    if sg:
                        part.append({"type": "Feature", "properties": props, "geometry": sg})
                if _jsize(part) <= MAP_AREA_MAX_BYTES:
                    break
            if _jsize(part) > MAP_AREA_MAX_BYTES:
                raise StoreError(413, "satellite change layer of one area exceeds the map limits",
                                 area_id=a["id"], max_area_bytes=MAP_AREA_MAX_BYTES)
            feats += part
            tol_by_area[a["id"]] = tol
        body = {"type": "FeatureCollection", "features": feats}
        size = _jsize(body)
        if len(feats) > MAP_MAX_FEATURES or size > MAP_MAX_BYTES:
            raise StoreError(413, "satellite change layer exceeds the map limits; open one area",
                             max_features=MAP_MAX_FEATURES, max_bytes=MAP_MAX_BYTES)
        tol = max(tol_by_area.values(), default=steps[0])
        ev_geoms = [f["geometry"] for f in body["features"]
                    if f["properties"]["kind"] == "event" and (focus_event is None or f["properties"]["event_id"] == focus_event)]
        fp_geoms = [f["geometry"] for f in body["features"] if f["properties"]["kind"] == "footprint"]
        body.update({
            "focus": {"event_id": focus_event, "area_id": area_id,
                      "bbox": _bbox_of(ev_geoms if focus_event is not None else (ev_geoms or fp_geoms))
                      or _bbox_of(fp_geoms)},
            "simplified_m": tol, "simplified_m_by_area": {str(k): v for k, v in tol_by_area.items()},
            "bytes": size,
            "limits": {"max_features": MAP_MAX_FEATURES, "max_bytes": MAP_MAX_BYTES,
                       "max_area_bytes": MAP_AREA_MAX_BYTES},
            "counts": {"areas": len(areas), "events": len({f["properties"]["event_id"] for f in body["features"]
                                                           if f["properties"]["kind"] == "event"})},
            "attribution": "Contains modified Copernicus Sentinel data"})
        return body
    finally:
        conn.close()
