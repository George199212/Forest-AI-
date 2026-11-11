"""Storage: a separate SQLite file (data/satellite.db) so the feature is isolated
and trivially rolled back (stop the worker, move the file away).

Append-only rules are enforced by triggers, not by convention:
  - sat_acquisitions: no DELETE; UPDATE only while status is PENDING (retry path)
  - sat_review_log, sat_request_log, sat_runs: no DELETE; review log no UPDATE
"""
import json
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sat_monitored_areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('SECTOR','LVM_GEO','EVAL_BBOX')),   -- EVAL_BBOX: evaluation/test area
    source_ref TEXT NOT NULL,
    name TEXT NOT NULL,
    geometry_geojson TEXT NOT NULL,          -- GeoJSON Polygon, CRS84 (lon,lat)
    area_ha REAL NOT NULL,
    buffer_m REAL NOT NULL,
    grid_json TEXT NOT NULL,                 -- fixed request grid (bbox, width, height, pixel size)
    added_by TEXT NOT NULL,
    added_at_utc TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    removed_at_utc TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_sat_area_active_ref
    ON sat_monitored_areas (source, source_ref) WHERE active = 1;

CREATE TABLE IF NOT EXISTS sat_acquisitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitored_area_id INTEGER NOT NULL REFERENCES sat_monitored_areas(id),
    sensor TEXT NOT NULL CHECK (sensor IN ('S1','S2')),
    product_id TEXT NOT NULL,
    item_ids_json TEXT,                      -- all catalog items of the same datatake
    sensing_time_utc TEXT NOT NULL,
    platform TEXT,
    orbit_direction TEXT,
    relative_orbit INTEGER,                  -- S1 only; NULL = unknown -> never compared
    scene_cloud_pct REAL,                    -- S2 only
    processing_params_json TEXT,
    fetched_at_utc TEXT,
    status TEXT NOT NULL CHECK (status IN ('PENDING','OK','NO_VALID_PIXELS','SKIPPED_CLOUD','ERROR')),
    attempts INTEGER NOT NULL DEFAULT 0,
    error_text TEXT,
    raster_path TEXT,
    raster_sha256 TEXT,
    quicklook_path TEXT,
    quicklook_sha256 TEXT,
    valid_pct_inside REAL,
    valid_pct_buffer REAL,
    pu_spent REAL,
    pu_is_estimate INTEGER,
    discovered_run_id INTEGER,
    UNIQUE (monitored_area_id, sensor, product_id)
);
CREATE INDEX IF NOT EXISTS ix_sat_acq_area_time ON sat_acquisitions (monitored_area_id, sensor, sensing_time_utc);

CREATE TABLE IF NOT EXISTS sat_area_metrics (
    acquisition_id INTEGER NOT NULL REFERENCES sat_acquisitions(id),
    metric TEXT NOT NULL CHECK (metric IN ('NDVI','NBR','NDMI','VV_DB','VH_DB','VALID_PCT','SNOW_PCT')),
    zone TEXT NOT NULL CHECK (zone IN ('INSIDE','BUFFER')),
    mean REAL, median REAL, p10 REAL, p90 REAL,
    n_valid_pixels INTEGER, n_total_pixels INTEGER,
    null_reason TEXT,                        -- set whenever the statistics are NULL
    PRIMARY KEY (acquisition_id, metric, zone)
);

CREATE TABLE IF NOT EXISTS sat_detections (
    -- one row per (acquisition) once change detection ran on it; idempotency key
    acquisition_id INTEGER PRIMARY KEY REFERENCES sat_acquisitions(id),
    monitored_area_id INTEGER NOT NULL,
    sensor TEXT NOT NULL,
    ran_at_utc TEXT NOT NULL,
    outcome TEXT NOT NULL,                   -- NOT_USABLE | NO_BASELINE | NO_CHANGE | SINGLE_DROP | CANDIDATE_BELOW_MIN | RADAR_ANOMALY | PENDING_CONFIRMATION | UNIFORM_DROP_ATMOSPHERIC | EVENT_CREATED | EVENT_UPDATED
    baseline_acq_ids TEXT,
    n_changed_pixels INTEGER,
    changed_area_ha REAL,
    largest_cluster_ha REAL,
    persisted INTEGER,                       -- S1: drop confirmed by the previous same-geometry acquisition
    event_id INTEGER,
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS sat_change_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitored_area_id INTEGER NOT NULL REFERENCES sat_monitored_areas(id),
    sensor_basis TEXT NOT NULL CHECK (sensor_basis IN ('S1','S2','S1+S2')),
    detected_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    before_acq_ids TEXT NOT NULL,
    after_acq_id INTEGER NOT NULL,
    after_acq_history_json TEXT NOT NULL,
    first_after_time_utc TEXT NOT NULL,
    last_after_time_utc TEXT NOT NULL,
    changed_area_ha REAL NOT NULL,
    changed_area_ha_inside REAL NOT NULL,
    changed_area_ha_buffer REAL NOT NULL,
    pct_of_area_affected REAL,
    max_distance_outside_boundary_m REAL,
    n_changed_pixels INTEGER NOT NULL,
    largest_cluster_ha REAL NOT NULL,
    change_geojson TEXT NOT NULL,
    change_mask_path TEXT NOT NULL,
    thresholds_json TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('LOW','MEDIUM','HIGH')),
    evidence_quality TEXT NOT NULL CHECK (evidence_quality IN ('GOOD','LIMITED','POOR')),
    classification TEXT NOT NULL CHECK (classification IN ('POTENTIAL_FOREST_LOSS',
        'POTENTIAL_CHANGE_OUTSIDE_BOUNDARY','POSSIBLE_SEASONAL_OR_ENVIRONMENTAL','INSUFFICIENT_EVIDENCE')),
    seasonal_caveat TEXT,
    gps_context_json TEXT,
    status TEXT NOT NULL DEFAULT 'SUSPECTED' CHECK (status IN ('SUSPECTED','REVIEW_CONFIRMED',
        'REVIEW_REJECTED','FIELD_CHECK_REQUESTED')),
    risk_id INTEGER,
    reviewed_by TEXT, reviewed_at_utc TEXT, review_note TEXT
);

CREATE TABLE IF NOT EXISTS sat_s2_candidates (
    -- INTERPRETATION (B): an optical change held until the next usable S2 decides.
    -- Never deleted; only PENDING rows change (trigger below).
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitored_area_id INTEGER NOT NULL REFERENCES sat_monitored_areas(id),
    acquisition_id INTEGER NOT NULL REFERENCES sat_acquisitions(id),
    baseline_acq_ids TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    mask_path TEXT NOT NULL,
    n_pixels INTEGER NOT NULL,
    changed_area_ha REAL NOT NULL,
    evidence_quality TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_CONFIRMATION'
        CHECK (status IN ('PENDING_CONFIRMATION','CONFIRMED','TRANSIENT')),
    resolved_by_acq_id INTEGER REFERENCES sat_acquisitions(id),
    resolved_at_utc TEXT,
    event_id INTEGER REFERENCES sat_change_events(id),
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_sat_cand_area ON sat_s2_candidates (monitored_area_id, status);
CREATE TRIGGER IF NOT EXISTS trg_cand_no_delete BEFORE DELETE ON sat_s2_candidates
BEGIN SELECT RAISE(ABORT, 'sat_s2_candidates is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_cand_update_only_pending BEFORE UPDATE ON sat_s2_candidates
WHEN OLD.status <> 'PENDING_CONFIRMATION'
BEGIN SELECT RAISE(ABORT, 'sat_s2_candidates: only PENDING_CONFIRMATION rows may change'); END;

CREATE TABLE IF NOT EXISTS sat_review_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES sat_change_events(id),
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    old_status TEXT, new_status TEXT,
    note TEXT,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sat_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL CHECK (trigger IN ('TIMER','MANUAL','BACKFILL')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,                             -- RUNNING | OK | PARTIAL | STOPPED_BY_GUARD | FAILED
    areas TEXT,
    date_from TEXT, date_to TEXT, sensors TEXT,
    new_acquisitions INTEGER DEFAULT 0,
    requests_made INTEGER DEFAULT 0,
    pu_spent REAL DEFAULT 0,
    pu_includes_estimates INTEGER DEFAULT 0,
    errors_json TEXT,
    stop_reason TEXT
);

CREATE TABLE IF NOT EXISTS sat_request_log (
    -- every HTTP request to Sentinel Hub (Catalog + Process, retries included): quota guard source
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    at_utc TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('CATALOG','PROCESS')),
    sensor TEXT,
    http_status INTEGER,
    pu REAL,
    pu_is_estimate INTEGER
);
CREATE INDEX IF NOT EXISTS ix_sat_req_at ON sat_request_log (at_utc);

CREATE TABLE IF NOT EXISTS sat_provider_status (
    key TEXT PRIMARY KEY,                    -- token | catalog | process
    last_ok_utc TEXT, last_error_utc TEXT, last_error TEXT
);

CREATE TABLE IF NOT EXISTS sat_area_masks (
    -- PROCESSED: F3 forest mask per area and dataset version (VMD compartments, read-only source).
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitored_area_id INTEGER NOT NULL REFERENCES sat_monitored_areas(id),
    kind TEXT NOT NULL CHECK (kind IN ('VMD_FOREST')),
    source_path TEXT NOT NULL,
    source_version TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    mask_path TEXT NOT NULL,
    mask_sha256 TEXT NOT NULL,
    n_compartments INTEGER NOT NULL,
    pixels_analysed INTEGER NOT NULL,         -- INSIDE+BUFFER pixels inside the mask
    forest_share_inside REAL,                 -- NULL when the zone is empty
    forest_share_buffer REAL,
    non_forest_share_zone REAL,               -- share of INSIDE+BUFFER NOT analysed
    details_json TEXT,
    UNIQUE (monitored_area_id, kind, source_version)
);

CREATE TABLE IF NOT EXISTS sat_radar_anomalies (
    -- INTERPRETATION: S1-only persistent VH drop (same geometry, two consecutive passes).
    -- Shown in the timeline; NOT an event and never a risk unless promoted (rules a/b in config).
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitored_area_id INTEGER NOT NULL REFERENCES sat_monitored_areas(id),
    acquisition_id INTEGER NOT NULL UNIQUE REFERENCES sat_acquisitions(id),
    sensing_time_utc TEXT NOT NULL,
    orbit_direction TEXT NOT NULL,
    relative_orbit INTEGER NOT NULL,
    baseline_acq_ids TEXT NOT NULL,
    previous_acq_id INTEGER REFERENCES sat_acquisitions(id),
    created_at_utc TEXT NOT NULL,
    mask_path TEXT NOT NULL,
    n_pixels INTEGER NOT NULL,
    changed_area_ha REAL NOT NULL,
    evidence_quality TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RADAR_ANOMALY' CHECK (status IN ('RADAR_ANOMALY','PROMOTED')),
    promotion_rule TEXT CHECK (promotion_rule IN ('S2_CONFIRMED','S1_PERSISTENT_MULTI_ORBIT')),
    promoted_at_utc TEXT,
    event_id INTEGER REFERENCES sat_change_events(id),
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_sat_radar_area ON sat_radar_anomalies (monitored_area_id, sensing_time_utc);
CREATE TRIGGER IF NOT EXISTS trg_radar_no_delete BEFORE DELETE ON sat_radar_anomalies
BEGIN SELECT RAISE(ABORT, 'sat_radar_anomalies is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_radar_update_only_anomaly BEFORE UPDATE ON sat_radar_anomalies
WHEN OLD.status <> 'RADAR_ANOMALY'
BEGIN SELECT RAISE(ABORT, 'sat_radar_anomalies: only RADAR_ANOMALY rows may change'); END;

CREATE TRIGGER IF NOT EXISTS trg_acq_no_delete BEFORE DELETE ON sat_acquisitions
BEGIN SELECT RAISE(ABORT, 'sat_acquisitions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_acq_update_only_pending BEFORE UPDATE ON sat_acquisitions
WHEN OLD.status <> 'PENDING'
BEGIN SELECT RAISE(ABORT, 'sat_acquisitions: only PENDING rows may change'); END;
CREATE TRIGGER IF NOT EXISTS trg_review_no_delete BEFORE DELETE ON sat_review_log
BEGIN SELECT RAISE(ABORT, 'sat_review_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_review_no_update BEFORE UPDATE ON sat_review_log
BEGIN SELECT RAISE(ABORT, 'sat_review_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_req_no_delete BEFORE DELETE ON sat_request_log
BEGIN SELECT RAISE(ABORT, 'sat_request_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_runs_no_delete BEFORE DELETE ON sat_runs
BEGIN SELECT RAISE(ABORT, 'sat_runs is append-only'); END;
"""


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


AREA_SOURCES = ("SECTOR", "LVM_GEO", "EVAL_BBOX")


def _migrate_area_source_check(conn):
    """2026-11-11: sat_monitored_areas.source gains 'EVAL_BBOX'. SQLite cannot alter a CHECK, so the table
    is rebuilt (documented 12-step procedure: FKs off, copy, drop, rename, FK check). Idempotent."""
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sat_monitored_areas'").fetchone()[0]
    if "'EVAL_BBOX'" in sql:
        return
    new_sql = sql.replace("CHECK (source IN ('SECTOR','LVM_GEO'))",
                          "CHECK (source IN ('SECTOR','LVM_GEO','EVAL_BBOX'))", 1)
    if new_sql == sql:
        raise RuntimeError("sat_monitored_areas: unexpected schema, refusing to migrate")
    n = conn.execute("SELECT COUNT(*) FROM sat_monitored_areas").fetchone()[0]
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN")
        conn.execute(new_sql.replace("CREATE TABLE sat_monitored_areas", "CREATE TABLE sat_monitored_areas_new", 1)
                     .replace("CREATE TABLE IF NOT EXISTS sat_monitored_areas",
                              "CREATE TABLE sat_monitored_areas_new", 1))
        conn.execute("INSERT INTO sat_monitored_areas_new SELECT * FROM sat_monitored_areas")
        conn.execute("DROP TABLE sat_monitored_areas")
        conn.execute("ALTER TABLE sat_monitored_areas_new RENAME TO sat_monitored_areas")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_sat_area_active_ref ON sat_monitored_areas (source, "
                     "source_ref) WHERE active = 1")
        if conn.execute("SELECT COUNT(*) FROM sat_monitored_areas").fetchone()[0] != n:
            raise RuntimeError("row count changed")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("foreign key check failed")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def connect(path=None):
    path = path or config.sat_db_path()
    from pathlib import Path
    config.secure_dir(Path(path).parent)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate_area_source_check(conn)
    for suffix in ("", "-wal", "-shm"):
        config.secure_file(str(path) + suffix)
    return conn


def connect_ro(path=None):
    """Read-only handle (for the API process: it never creates or migrates)."""
    path = path or config.sat_db_path()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def forest_ro(path=None):
    """Main forest_ai.db, strictly read-only."""
    path = path or config.forest_db_path()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def dumps(v):
    return json.dumps(v, ensure_ascii=False, allow_nan=False, sort_keys=True)


def month_usage(conn, now=None):
    """Requests and PU used in the current calendar month (UTC), from the request log."""
    now = now or utcnow()
    prefix = now.strftime("%Y-%m")
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(pu),0) AS pu, COALESCE(MAX(pu_is_estimate),0) AS est "
        "FROM sat_request_log WHERE substr(at_utc,1,7)=?", (prefix,)).fetchone()
    return {"requests": row["n"], "pu": float(row["pu"]), "pu_includes_estimates": bool(row["est"])}


def provider_status(conn, key, ok, error=None):
    now = iso(utcnow())
    conn.execute("INSERT OR IGNORE INTO sat_provider_status (key) VALUES (?)", (key,))
    if ok:
        conn.execute("UPDATE sat_provider_status SET last_ok_utc=? WHERE key=?", (now, key))
    else:
        conn.execute("UPDATE sat_provider_status SET last_error_utc=?, last_error=? WHERE key=?",
                     (now, (error or "")[:300], key))
    conn.commit()
