import sqlite3
import json
import os
from datetime import datetime

DB_NAME = os.environ.get("DB_PATH", "data/forest_ai.db")


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sectors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        contractor TEXT,
        status TEXT,
        approved_volume TEXT,
        map_url TEXT,
        image_path TEXT,
        boundary_json TEXT,
        center_lat REAL,
        center_lon REAL,
        area_ha REAL,
        color TEXT DEFAULT 'red',
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS risks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT,
        risk_level TEXT,
        reason TEXT
    )
    """)

    conn.commit()
    conn.close()

    # Safe migrations — add new columns/tables if they don't exist
    _migrate()


def _add_column_if_missing(cur, table, column, definition):
    cur.execute(f"PRAGMA table_info({table})")
    existing = [row[1] for row in cur.fetchall()]
    if column not in existing:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate():
    """Safe ALTER TABLE / CREATE TABLE migrations — never drops data.
    Centralizes ALL table creation (sectors/risks above, plus the field-work
    and boundary-plan tables bot.py used to create ad-hoc), so any entry
    point (api.py or bot.py) can bring up a fresh DB on its own."""
    new_columns = [
        ("sectors", "boundary_json", "TEXT"),
        ("sectors", "center_lat",    "REAL"),
        ("sectors", "center_lon",    "REAL"),
        ("sectors", "area_ha",       "REAL"),
        ("sectors", "color",         "TEXT DEFAULT 'red'"),
        ("sectors", "created_at",    "TEXT"),
        ("sectors", "updated_at",    "TEXT"),
        ("sectors", "tree_species",  "TEXT"),
        ("sectors", "cut_plan_notes","TEXT"),
        ("sectors", "notes",         "TEXT"),
        ("sectors", "boundary_plan_id", "INTEGER"),
        ("sectors", "object_name",   "TEXT"),
        ("sectors", "pixel_boundary_json", "TEXT"),
        ("sectors", "satellite_file_path", "TEXT"),
    ]
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    for table, column, definition in new_columns:
        _add_column_if_missing(cur, table, column, definition)
    _add_column_if_missing(cur, "risks", "created_at", "TEXT")
    for column, definition in [
        ("entity_type",         "TEXT"),
        ("entity_id",           "INTEGER"),
        ("status",              "TEXT DEFAULT 'OPEN'"),
        ("rule_code",           "TEXT"),
        ("ai_recommendation",   "TEXT"),
        ("distance_m",          "REAL"),
        ("duration_min",        "REAL"),
        ("notified_at",         "TEXT"),
        ("resolved_at",         "TEXT"),
        ("telegram_message_id", "TEXT"),
    ]:
        _add_column_if_missing(cur, "risks", column, definition)
    _add_column_if_missing(cur, "risks", "photo_path", "TEXT")
    _add_column_if_missing(cur, "risks", "photo_path_2", "TEXT")
    # Demo scenarios (Rīgas meži presentation): rows created by
    # services/demo_scenarios.py are flagged is_demo=1 so /demo_reset can
    # clear them without ever touching real operational data.
    _add_column_if_missing(cur, "risks", "is_demo", "INTEGER DEFAULT 0")
    # NULL by default (every existing/future risk is unpinned). A small
    # integer sets a fixed presentation order for a handful of rows a
    # presenter wants pinned to the top of GET /api/risks, without
    # affecting relative order among the rest (see get_risks_route()).
    _add_column_if_missing(cur, "risks", "pinned_order", "INTEGER DEFAULT NULL")
    # Background AI analysis state (services/risk_ai_worker.py): NULL for
    # every existing row; the worker sets REQUESTED/RUNNING/DONE/FAILED.
    _add_column_if_missing(cur, "risks", "ai_status", "TEXT")
    _add_column_if_missing(cur, "risks", "ai_attempts", "INTEGER DEFAULT 0")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS risk_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        risk_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        actor TEXT,
        details TEXT,
        created_at TEXT NOT NULL
    )
    """)

    # New tables
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sector_employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT NOT NULL,
        full_name TEXT,
        role TEXT,
        phone TEXT,
        id_number TEXT,
        notes TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)
    _add_column_if_missing(cur, "sector_employees", "telegram_user_id", "TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sector_vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT NOT NULL,
        plate TEXT,
        vehicle_type TEXT,
        driver TEXT,
        fuel_capacity_l REAL,
        fuel_per_100km REAL,
        total_km REAL DEFAULT 0,
        notes TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)
    _add_column_if_missing(cur, "sector_vehicles", "telegram_user_id", "TEXT")
    _add_column_if_missing(cur, "sector_vehicles", "employee_id", "INTEGER")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sector_equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT NOT NULL,
        equipment_code TEXT,
        type TEXT,
        brand TEXT,
        model TEXT,
        registration_id TEXT,
        photo_url TEXT,
        operator_employee_id INTEGER,
        status TEXT DEFAULT 'OFFLINE',
        current_task TEXT,
        fuel_level_pct REAL,
        working_hours_today REAL DEFAULT 0,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)
    _add_column_if_missing(cur, "sector_equipment", "is_demo", "INTEGER DEFAULT 0")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicle_fuel_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        sector TEXT,
        km_start REAL,
        km_end REAL,
        km_driven REAL,
        fuel_added_l REAL,
        fuel_calc_l REAL,
        discrepancy_l REAL,
        note TEXT,
        logged_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicle_gps_pings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER NOT NULL,
        sector TEXT NOT NULL,
        latitude REAL,
        longitude REAL,
        inside_boundary INTEGER,
        recorded_at TEXT
    )
    """)
    for column, definition in [
        ("entity_type",  "TEXT DEFAULT 'VEHICLE'"),
        ("employee_id",  "INTEGER"),
        ("equipment_id", "INTEGER"),
    ]:
        _add_column_if_missing(cur, "vehicle_gps_pings", column, definition)

    # vehicle_gps_pings.vehicle_id was NOT NULL back when this table only
    # carried vehicle pings — employee/equipment pings (entity_type above)
    # have no vehicle_id, so the constraint has to go. ADD COLUMN can't
    # relax a constraint on an existing column, so rebuild the table
    # (SQLite's standard 12-step ALTER pattern). Guarded on the current
    # notnull flag so this only runs once, safe to re-run after that.
    cur.execute("PRAGMA table_info(vehicle_gps_pings)")
    vehicle_id_notnull = next(
        (row[3] for row in cur.fetchall() if row[1] == "vehicle_id"), 0
    )
    if vehicle_id_notnull:
        cur.execute("""
        CREATE TABLE vehicle_gps_pings_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER,
            sector TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            inside_boundary INTEGER,
            recorded_at TEXT,
            entity_type TEXT DEFAULT 'VEHICLE',
            employee_id INTEGER,
            equipment_id INTEGER
        )
        """)
        cur.execute("""
        INSERT INTO vehicle_gps_pings_new
            (id, vehicle_id, sector, latitude, longitude, inside_boundary,
             recorded_at, entity_type, employee_id, equipment_id)
        SELECT id, vehicle_id, sector, latitude, longitude, inside_boundary,
               recorded_at, entity_type, employee_id, equipment_id
        FROM vehicle_gps_pings
        """)
        cur.execute("DROP TABLE vehicle_gps_pings")
        cur.execute("ALTER TABLE vehicle_gps_pings_new RENAME TO vehicle_gps_pings")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS live_locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        telegram_user_id TEXT,
        sector TEXT,
        latitude REAL,
        longitude REAL,
        live_period INTEGER,
        started_at TEXT,
        updated_at TEXT,
        expires_at TEXT,
        last_status TEXT
    )
    """)
    _add_column_if_missing(cur, "live_locations", "last_status", "TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sector_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT NOT NULL,
        image_path TEXT NOT NULL,
        snapshot_date TEXT,
        label TEXT,
        note TEXT,
        source TEXT DEFAULT 'geolatvija',
        uploaded_at TEXT
    )
    """)
    _add_column_if_missing(cur, "sector_snapshots", "risk_level", "TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS snapshot_risks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER NOT NULL,
        risk_id INTEGER NOT NULL
    )
    """)

    # ── Field-work tables (check-ins, photos, timber, trucks) ──────────────
    cur.execute("CREATE TABLE IF NOT EXISTS work_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    for column, definition in [
        ("user_id",       "TEXT"),
        ("employee",      "TEXT"),
        ("employee_id",   "INTEGER"),
        ("contractor",    "TEXT"),
        ("sector",        "TEXT"),
        ("check_in_time", "TEXT"),
        ("finish_time",   "TEXT"),
        ("latitude",      "REAL"),
        ("longitude",     "REAL"),
        ("distance_m",    "REAL"),
        ("approved",      "TEXT"),
        ("comment",       "TEXT"),
    ]:
        _add_column_if_missing(cur, "work_sessions", column, definition)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS work_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER, sector TEXT, photo_type TEXT,
        image_path TEXT, uploaded_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS timber_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT, planned_volume REAL, actual_volume REAL,
        difference_volume REAL, status TEXT, note TEXT, created_at TEXT
    )
    """)
    _add_column_if_missing(cur, "timber_movements", "is_demo", "INTEGER DEFAULT 0")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS truck_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT, truck_number TEXT, driver TEXT,
        reported_volume REAL, note TEXT, created_at TEXT
    )
    """)

    # ── Boundary plan (Robežu Plāns OCR) tables ─────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS boundary_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT, document_type TEXT, uploaded_at TEXT,
        status TEXT DEFAULT 'uploaded', uploaded_by TEXT, plan_data_json TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS boundary_plan_points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER, point_name TEXT, x_coord REAL, y_coord REAL,
        lat REAL, lon REAL, raw_text TEXT
    )
    """)
    # object_name / satellite_file_path used to be added via a separate
    # migration in bot.py's init_plan_tables() — kept here instead.
    _add_column_if_missing(cur, "boundary_plans", "object_name", "TEXT")
    _add_column_if_missing(cur, "boundary_plans", "satellite_file_path", "TEXT")

    # ── AI Inspector streaming analysis history ─────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ai_inspector_analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scope TEXT NOT NULL,
        sector TEXT,
        summary_text TEXT,
        risk_breakdown_json TEXT,
        exposure_low REAL,
        exposure_high REAL,
        exposure_basis TEXT,
        model TEXT,
        created_at TEXT NOT NULL
    )
    """)

    # ── Satellite Intelligence Engine ───────────────────────────────────────
    # Additive to the existing satellite_file_path columns on sectors/
    # boundary_plans (manual uploads) and independent of the risks table's
    # dual-purpose pattern — these are new concepts (tiered acquisitions,
    # commercial requests, a separate satellite risk score, a timeline feed),
    # not a fit for overloading an existing table.

    cur.execute("""
    CREATE TABLE IF NOT EXISTS satellite_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT NOT NULL,
        provider TEXT NOT NULL,
        satellite TEXT,
        tier TEXT NOT NULL,
        acquisition_date TEXT,
        resolution_m REAL,
        cloud_cover_pct REAL,
        bbox_json TEXT,
        image_id TEXT,
        image_ref TEXT,
        source TEXT DEFAULT 'LIVE',
        cost_eur REAL,
        risk_score REAL,
        ai_analysis_ref TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS satellite_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT NOT NULL,
        tier TEXT NOT NULL,
        provider TEXT NOT NULL,
        estimated_cost_eur REAL,
        reason TEXT,
        justification TEXT NOT NULL,
        satellite_risk_score REAL,
        requested_resolution_m REAL,
        aoi_area_ha REAL,
        approval_status TEXT DEFAULT 'PENDING',
        combined_group_id TEXT,
        linked_incident_id INTEGER,
        fulfilled_observation_id INTEGER,
        created_at TEXT NOT NULL,
        fulfilled_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sector_satellite_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT NOT NULL,
        score REAL NOT NULL,
        band TEXT NOT NULL,
        tier_recommended TEXT,
        inputs_json TEXT,
        computed_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS satellite_timeline_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT NOT NULL,
        event_type TEXT NOT NULL,
        label TEXT,
        detail TEXT,
        ref_table TEXT,
        ref_id INTEGER,
        occurred_at TEXT NOT NULL
    )
    """)

    # ── Integration Layer (external systems: machines, fleet GPS, GIS,
    # satellite, timber/weighbridge, workers, ERP, audit) — see
    # services/integrations/. Additive only, mirrors the satellite_*
    # tables above: one metadata table per integration instance, a
    # generic staging/dedup table for normalized records (most domain
    # data still lands in the existing sectors/risks/vehicle_gps_pings/
    # timber_movements tables via the same add_*() functions bot.py and
    # api.py already use), plus sync/log/webhook bookkeeping.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS organizations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT UNIQUE,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS integrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        organization_id INTEGER NOT NULL DEFAULT 1,
        category TEXT NOT NULL,
        provider TEXT NOT NULL,
        integration_type TEXT,
        display_name TEXT,
        connection_status TEXT NOT NULL DEFAULT 'NOT_CONNECTED',
        sync_status TEXT NOT NULL DEFAULT 'IDLE',
        is_demo INTEGER NOT NULL DEFAULT 0,
        credentials_reference TEXT,
        configuration_json TEXT,
        sync_frequency_minutes INTEGER DEFAULT 60,
        last_sync_at TEXT,
        next_sync_at TEXT,
        last_success_at TEXT,
        last_error_at TEXT,
        error_message TEXT,
        records_received INTEGER NOT NULL DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS integration_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        integration_id INTEGER NOT NULL,
        encrypted_value TEXT NOT NULL,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS integration_sync_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        integration_id INTEGER NOT NULL,
        trigger TEXT,
        status TEXT NOT NULL DEFAULT 'RUNNING',
        records_fetched INTEGER DEFAULT 0,
        records_saved INTEGER DEFAULT 0,
        records_deduplicated INTEGER DEFAULT 0,
        error_message TEXT,
        started_at TEXT,
        finished_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS integration_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        integration_id INTEGER NOT NULL,
        sync_run_id INTEGER,
        level TEXT NOT NULL DEFAULT 'INFO',
        message TEXT NOT NULL,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS integration_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        integration_id INTEGER NOT NULL,
        organization_id INTEGER NOT NULL DEFAULT 1,
        source_provider TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        external_id TEXT NOT NULL,
        sector TEXT,
        source_timestamp TEXT,
        received_at TEXT NOT NULL,
        raw_payload_json TEXT,
        normalized_payload_json TEXT,
        validation_status TEXT NOT NULL DEFAULT 'PENDING',
        processing_status TEXT NOT NULL DEFAULT 'PENDING',
        deduplication_key TEXT NOT NULL UNIQUE,
        linked_table TEXT,
        linked_id INTEGER,
        is_demo INTEGER NOT NULL DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS integration_webhook_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        integration_id INTEGER,
        payload_hash TEXT NOT NULL UNIQUE,
        signature_valid INTEGER,
        status TEXT NOT NULL DEFAULT 'RECEIVED',
        received_at TEXT NOT NULL,
        processed_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS weighbridge_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        integration_id INTEGER,
        sector TEXT,
        vehicle_plate TEXT,
        driver TEXT,
        trip_number TEXT,
        destination TEXT,
        species TEXT,
        assortment TEXT,
        weighed_at TEXT,
        weight_gross_kg REAL,
        weight_tare_kg REAL,
        weight_net_kg REAL,
        declared_volume_m3 REAL,
        actual_volume_m3 REAL,
        document_number TEXT,
        photo_path TEXT,
        acceptance_status TEXT DEFAULT 'PENDING',
        is_demo INTEGER NOT NULL DEFAULT 0,
        source_record_id INTEGER,
        created_at TEXT
    )
    """)

    _create_photo_compare_tables(cur)
    _create_risk_conclusion_table(cur)

    # Seed exactly one default organization so every existing (pre-multi-tenant)
    # row and every new integration has somewhere to point organization_id=1 —
    # see services/integrations/registry.py docstring for the tenant-isolation
    # caveat (this app still authenticates with one shared HTTP Basic login).
    cur.execute("SELECT COUNT(*) FROM organizations")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO organizations (id, name, slug, created_at) VALUES (1, ?, ?, ?)",
            ("Default Organization", "default", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")),
        )

    conn.commit()
    conn.close()


def _create_photo_compare_tables(cur):
    """Photo comparison between two dates (services/photo_compare.py). New tables only."""
    cur.execute("""
    CREATE TABLE IF NOT EXISTS photo_cmp_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sector TEXT NOT NULL,
        baseline_date TEXT NOT NULL,
        followup_date TEXT NOT NULL,
        baseline_photo_ids TEXT NOT NULL,
        followup_photo_ids TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'CREATED',
        created_by TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS photo_cmp_points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        seq INTEGER NOT NULL,
        kind TEXT NOT NULL,
        match_confidence TEXT,
        confirmed INTEGER NOT NULL DEFAULT 0,
        confirmed_by TEXT,
        confirmed_at TEXT,
        status TEXT NOT NULL DEFAULT 'UNCONFIRMED',
        same_place TEXT,
        comparability TEXT,
        comparability_reason TEXT,
        detect_limits TEXT,
        check_attempts INTEGER NOT NULL DEFAULT 0,
        detect_attempts INTEGER NOT NULL DEFAULT 0,
        checked_at TEXT,
        detected_at TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS photo_cmp_point_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        point_id INTEGER NOT NULL,
        photo_id INTEGER NOT NULL,
        side TEXT NOT NULL,
        match_confidence TEXT,
        match_reason TEXT,
        UNIQUE(run_id, photo_id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS photo_cmp_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        point_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        cell TEXT NOT NULL,
        class TEXT NOT NULL,
        description TEXT,
        limits TEXT,
        verification TEXT,
        verification_reason TEXT,
        verify_attempts INTEGER NOT NULL DEFAULT 0,
        confidence TEXT,
        discarded INTEGER NOT NULL DEFAULT 0,
        review_status TEXT NOT NULL DEFAULT 'UNREVIEWED',
        reviewer TEXT,
        reviewed_at TEXT,
        created_at TEXT
    )
    """)
    # source: 'system' (found by the pipeline) or 'human' (observation entered by a reviewer)
    _add_column_if_missing(cur, "photo_cmp_changes", "source", "TEXT NOT NULL DEFAULT 'system'")
    _add_column_if_missing(cur, "photo_cmp_changes", "created_by", "TEXT")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS photo_cmp_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER,
        point_id INTEGER,
        change_id INTEGER,
        event_type TEXT NOT NULL,
        actor TEXT,
        purpose TEXT,
        model TEXT,
        input_tokens INTEGER,
        output_tokens INTEGER,
        details TEXT,
        created_at TEXT
    )
    """)


def _create_risk_conclusion_table(cur):
    """Final conclusions of risks (services/risk_conclusion.py). New table only; nothing is overwritten:
    a newer conclusion marks the previous one SUPERSEDED."""
    cur.execute("""
    CREATE TABLE IF NOT EXISTS risk_conclusions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        risk_id INTEGER NOT NULL,
        run_id INTEGER,
        status TEXT NOT NULL,
        rule TEXT,
        recommendation TEXT,
        outcome TEXT,
        rule_line TEXT,
        evidence_json TEXT,
        weather_text TEXT,
        weather_source TEXT,
        ai_draft TEXT,
        model TEXT,
        created_by TEXT,
        created_at TEXT,
        final_text TEXT,
        decision TEXT,
        against_recommendation INTEGER NOT NULL DEFAULT 0,
        override_reason TEXT,
        next_steps TEXT,
        reshoot_points_json TEXT,
        decided_by TEXT,
        decided_at TEXT,
        superseded_by INTEGER,
        superseded_at TEXT
    )
    """)
    # Undo of a decision (status UNDONE keeps the decided row; a new DRAFT row restores the text).
    for column, definition in (("text_at", "TEXT"),             # when the draft text was produced (stale check)
                               ("risk_status_before", "TEXT"),  # risk status before "accept and close"
                               ("undone_by", "TEXT"), ("undone_at", "TEXT"), ("undo_reason", "TEXT"),
                               ("restored_as", "INTEGER")):
        _add_column_if_missing(cur, "risk_conclusions", column, definition)


# ── Geo helpers ───────────────────────────────────────────────────────────────

def calc_centroid(points):
    """Calculate centroid from list of [lat, lon] pairs."""
    if not points:
        return None, None
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    return round(lat, 6), round(lon, 6)


def calc_area_ha(points):
    """Calculate polygon area in hectares using Shoelace formula (approx)."""
    if len(points) < 3:
        return 0.0
    # Convert to approximate meters using lat/lon
    # 1 degree lat ≈ 111320 m, 1 degree lon ≈ 111320 * cos(lat) m
    import math
    avg_lat = sum(p[0] for p in points) / len(points)
    lat_m = 111320.0
    lon_m = 111320.0 * math.cos(math.radians(avg_lat))

    # Shoelace
    n = len(points)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        xi = points[i][1] * lon_m
        yi = points[i][0] * lat_m
        xj = points[j][1] * lon_m
        yj = points[j][0] * lat_m
        area += xi * yj - xj * yi
    return round(abs(area) / 2.0 / 10000, 2)  # m² → ha


def parse_boundary(boundary_str):
    """
    Parse boundary string: '56.9650,24.1800;56.9650,24.1950;56.9550,24.1950;56.9550,24.1800'
    Returns list of [lat, lon] pairs or None on error.
    """
    try:
        points = []
        for part in boundary_str.strip().split(";"):
            lat_s, lon_s = part.strip().split(",")
            lat, lon = float(lat_s.strip()), float(lon_s.strip())
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return None
            points.append([lat, lon])
        if len(points) < 4:
            return None
        return points
    except Exception:
        return None


# ── Sectors ───────────────────────────────────────────────────────────────────

def add_sector(name, contractor, status, approved_volume, map_url="",
               boundary=None, color="red", boundary_plan_id=None, object_name="",
               pixel_boundary=None):
    """
    Add or update a sector.
    boundary: list of [lat, lon] pairs or None
    boundary_plan_id: optional FK to boundary_plans.id — links this sector back
        to the Robežu Plāns scan / OCR session it was created from, so the
        dashboard can group sectors that came from the same object/parcel.
    object_name: optional human-readable name of the object/parcel this
        sector belongs to (e.g. "Mūrnieku Jāņa 0.21ha").
    pixel_boundary: optional list of [pixel_x, pixel_y] pairs locating this
        sector's outline on the ORIGINAL scanned plan image (same pixel space
        as boundary_plans.file_path). Only available when the sector came
        from OCR's geometric reconstruction path. Lets the dashboard draw the
        sector's outline directly on the source scan.
    """
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    boundary_json = None
    center_lat = center_lon = area_ha = None

    if boundary and len(boundary) >= 4:
        boundary_json = json.dumps(boundary)
        center_lat, center_lon = calc_centroid(boundary)
        area_ha = calc_area_ha(boundary)

    pixel_boundary_json = json.dumps(pixel_boundary) if pixel_boundary else None

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Check if sector already exists. Identity is scoped by (name,
    # boundary_plan_id) rather than name alone — otherwise two different
    # plans/objects that happen to produce the same generic sector name
    # (e.g. "S-001") would silently overwrite each other instead of
    # coexisting as distinct sectors.
    if boundary_plan_id is not None:
        cur.execute("SELECT id FROM sectors WHERE name=? AND boundary_plan_id=?", (name, boundary_plan_id))
    else:
        cur.execute("SELECT id FROM sectors WHERE name=? AND boundary_plan_id IS NULL", (name,))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
        UPDATE sectors SET contractor=?, status=?, approved_volume=?, map_url=?,
            boundary_json=COALESCE(?, boundary_json),
            center_lat=COALESCE(?, center_lat),
            center_lon=COALESCE(?, center_lon),
            area_ha=COALESCE(?, area_ha),
            color=?, updated_at=?,
            boundary_plan_id=COALESCE(?, boundary_plan_id),
            object_name=CASE WHEN ? != '' THEN ? ELSE object_name END,
            pixel_boundary_json=COALESCE(?, pixel_boundary_json)
        WHERE id=?
        """, (contractor, status, approved_volume, map_url,
              boundary_json, center_lat, center_lon, area_ha, color, now,
              boundary_plan_id, object_name, object_name, pixel_boundary_json, existing[0]))
    else:
        cur.execute("""
        INSERT INTO sectors
            (name, contractor, status, approved_volume, map_url, image_path,
             boundary_json, center_lat, center_lon, area_ha, color, created_at, updated_at,
             boundary_plan_id, object_name, pixel_boundary_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, contractor, status, approved_volume, map_url, "",
              boundary_json, center_lat, center_lon, area_ha, color, now, now,
              boundary_plan_id, object_name, pixel_boundary_json))

    conn.commit()
    conn.close()


def get_sectors():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    SELECT name, contractor, status, approved_volume, map_url, image_path,
           boundary_json, center_lat, center_lon, area_ha, color, created_at, updated_at
    FROM sectors
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_objects():
    """
    Group sectors by the object/parcel they belong to (boundary_plan_id).
    Sectors with no boundary_plan_id (created manually, e.g. A-004..A-008)
    are returned under a single synthetic "unassigned" bucket so nothing
    gets lost from the dashboard.
    Returns a list of:
        {"boundary_plan_id": int|None, "object_name": str, "sector_names": [str,...]}
    """
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT boundary_plan_id, object_name, name
        FROM sectors
        ORDER BY boundary_plan_id IS NULL, boundary_plan_id, name
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    grouped = {}
    order = []
    for r in rows:
        key = r["boundary_plan_id"]
        if key not in grouped:
            grouped[key] = {
                "boundary_plan_id": key,
                "object_name": r["object_name"] or ("Без объекта" if key is None else f"Plan #{key}"),
                "sector_names": [],
            }
            order.append(key)
        grouped[key]["sector_names"].append(r["name"])
    return [grouped[k] for k in order]


def get_sector_geo(name):
    """Return boundary_json and center for a sector."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM sectors WHERE name=?", (name,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_sector_image(sector_name, image_path):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE sectors SET image_path=? WHERE name=?", (image_path, sector_name))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected


def update_sector_boundary(name, boundary, color="red"):
    """Update just the boundary of an existing sector."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    boundary_json = json.dumps(boundary)
    center_lat, center_lon = calc_centroid(boundary)
    area_ha = calc_area_ha(boundary)
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    UPDATE sectors SET boundary_json=?, center_lat=?, center_lon=?, area_ha=?, color=?, updated_at=?
    WHERE name=?
    """, (boundary_json, center_lat, center_lon, area_ha, color, now, name))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected


# ── Risks ─────────────────────────────────────────────────────────────────────

def add_risk(sector, risk_level, reason):
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO risks (sector, risk_level, reason, created_at)
    VALUES (?, ?, ?, ?)
    """, (sector, risk_level, reason, now))
    conn.commit()
    conn.close()


def get_risks():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT sector, risk_level, reason FROM risks")
    rows = cur.fetchall()
    conn.close()
    return rows


# ── Sector Employees ──────────────────────────────────────────────────────────

def add_employee(sector, full_name, role="", phone="", id_number="", notes="", telegram_user_id=""):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO sector_employees (sector, full_name, role, phone, id_number, notes, active, created_at, telegram_user_id)
    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (sector, full_name, role, phone, id_number, notes, now, telegram_user_id))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def get_employees(sector=None):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if sector:
        cur.execute("SELECT * FROM sector_employees WHERE sector=? ORDER BY full_name", (sector,))
    else:
        cur.execute("SELECT * FROM sector_employees ORDER BY sector, full_name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ── Sector Vehicles ───────────────────────────────────────────────────────────

def add_vehicle(sector, plate, vehicle_type="", driver="", fuel_capacity_l=0, fuel_per_100km=0, notes="", telegram_user_id=""):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO sector_vehicles (sector, plate, vehicle_type, driver, fuel_capacity_l, fuel_per_100km, notes, active, created_at, telegram_user_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (sector, plate, vehicle_type, driver, fuel_capacity_l, fuel_per_100km, notes, now, telegram_user_id))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def get_vehicles(sector=None):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if sector:
        cur.execute("SELECT * FROM sector_vehicles WHERE sector=? ORDER BY plate", (sector,))
    else:
        cur.execute("SELECT * FROM sector_vehicles ORDER BY sector, plate")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def log_fuel(vehicle_id, sector, km_start, km_end, fuel_added_l, fuel_per_100km, note=""):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    km_driven = km_end - km_start
    fuel_calc_l = round(km_driven * fuel_per_100km / 100, 2) if fuel_per_100km else 0
    discrepancy_l = round(fuel_added_l - fuel_calc_l, 2)
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO vehicle_fuel_logs (vehicle_id, sector, km_start, km_end, km_driven, fuel_added_l, fuel_calc_l, discrepancy_l, note, logged_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (vehicle_id, sector, km_start, km_end, km_driven, fuel_added_l, fuel_calc_l, discrepancy_l, note, now))
    # Update total km
    cur.execute("UPDATE sector_vehicles SET total_km = total_km + ? WHERE id=?", (km_driven, vehicle_id))
    conn.commit()
    conn.close()
    return discrepancy_l


# ── Sector Equipment ────────────────────────────────────────────────────────

def add_equipment(sector, equipment_code, type, brand="", model="", registration_id="",
                   photo_url="", operator_employee_id=None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO sector_equipment
        (sector, equipment_code, type, brand, model, registration_id, photo_url,
         operator_employee_id, status, active, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OFFLINE', 1, ?)
    """, (sector, equipment_code, type, brand, model, registration_id, photo_url,
          operator_employee_id, now))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def get_equipment(sector=None):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if sector:
        cur.execute("SELECT * FROM sector_equipment WHERE sector=? ORDER BY equipment_code", (sector,))
    else:
        cur.execute("SELECT * FROM sector_equipment ORDER BY sector, equipment_code")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ── GPS ping history (employees / vehicles / equipment) ────────────────────
# Shared append-only log — vehicle_gps_pings originally only carried vehicle
# pings; entity_type + employee_id/equipment_id (Phase 1 migration) let it
# carry employee and equipment pings too, for route-over-period queries.

def add_gps_ping(entity_type, entity_id, sector, latitude, longitude, inside_boundary):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    vehicle_id = entity_id if entity_type == "VEHICLE" else None
    employee_id = entity_id if entity_type == "EMPLOYEE" else None
    equipment_id = entity_id if entity_type == "EQUIPMENT" else None
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO vehicle_gps_pings
        (vehicle_id, sector, latitude, longitude, inside_boundary, recorded_at,
         entity_type, employee_id, equipment_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (vehicle_id, sector, latitude, longitude, int(bool(inside_boundary)), now,
          entity_type, employee_id, equipment_id))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def get_route(entity_type, entity_id, start, end):
    """GPS pings for one entity within [start, end] (recorded_at strings,
    same '%Y-%m-%d %H:%M:%S UTC' format used everywhere else), oldest first."""
    id_column = {"VEHICLE": "vehicle_id", "EMPLOYEE": "employee_id", "EQUIPMENT": "equipment_id"}[entity_type]
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"""
    SELECT latitude, longitude, inside_boundary, recorded_at
    FROM vehicle_gps_pings
    WHERE {id_column}=? AND recorded_at BETWEEN ? AND ?
    ORDER BY recorded_at ASC
    """, (entity_id, start, end))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ── Incidents (risks, extended with Incident-lifecycle fields) ─────────────

def add_incident(sector, risk_level, reason, entity_type=None, entity_id=None,
                  rule_code=None, distance_m=None, duration_min=None, ai_recommendation=None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO risks
        (sector, risk_level, reason, created_at, entity_type, entity_id, status,
         rule_code, distance_m, duration_min, ai_recommendation)
    VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)
    """, (sector, risk_level, reason, now, entity_type, entity_id,
          rule_code, distance_m, duration_min, ai_recommendation))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def get_incidents(status=None):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if status:
        cur.execute("SELECT * FROM risks WHERE entity_type IS NOT NULL AND status=? ORDER BY created_at DESC", (status,))
    else:
        cur.execute("SELECT * FROM risks WHERE entity_type IS NOT NULL ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def update_incident_status(incident_id, status, telegram_message_id=None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if status == "NOTIFIED":
        cur.execute(
            "UPDATE risks SET status=?, notified_at=?, telegram_message_id=? WHERE id=?",
            (status, now, telegram_message_id, incident_id),
        )
    elif status in ("RESOLVED", "DISMISSED"):
        cur.execute("UPDATE risks SET status=?, resolved_at=? WHERE id=?", (status, now, incident_id))
    else:
        cur.execute("UPDATE risks SET status=? WHERE id=?", (status, incident_id))
    conn.commit()
    conn.close()

def set_telegram_message_id(risk_id, message_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE risks SET telegram_message_id=? WHERE id=?", (str(message_id), risk_id))
    conn.commit()
    conn.close()

def set_ai_recommendation(incident_id, text):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE risks SET ai_recommendation=? WHERE id=?", (text, incident_id))
    conn.commit()
    conn.close()


# ── Risk Events (audit log for risks/incidents) ─────────────────────────────

def add_risk_event(risk_id, event_type, actor=None, details=None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO risk_events (risk_id, event_type, actor, details, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (risk_id, event_type, actor, details, now))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def get_risk_events(risk_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM risk_events WHERE risk_id=? ORDER BY created_at ASC", (risk_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def get_risk_by_telegram_message_id(message_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM risks WHERE telegram_message_id=?", (str(message_id),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def get_active_incident_by_rule(rule_code, entity_type=None, entity_id=None, sector=None):
    """Generalized version of the dedup lookup bot.py's handle_location()
    already does inline for SECTOR_EXIT/EMERGENCY (open incident with the
    same rule_code+entity) — used by services/integrations/risk_rules.py so
    integration-sourced risk events don't spam duplicate incidents on every
    sync the way a naive re-trigger would."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    query = "SELECT * FROM risks WHERE rule_code=? AND status IN ('OPEN','NOTIFIED')"
    params = [rule_code]
    if entity_type is not None:
        query += " AND entity_type=?"
        params.append(entity_type)
    if entity_id is not None:
        query += " AND entity_id=?"
        params.append(entity_id)
    if sector is not None:
        query += " AND sector=?"
        params.append(sector)
    query += " ORDER BY id DESC LIMIT 1"
    cur.execute(query, params)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_active_incident_for_employee(employee_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM risks WHERE entity_type='EMPLOYEE' AND entity_id=? "
        "AND status IN ('OPEN','NOTIFIED') ORDER BY id DESC LIMIT 1",
        (employee_id,)
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# ── Sector Snapshots ──────────────────────────────────────────────────────────

def add_sector_snapshot(sector, image_path, snapshot_date, label="", note="", source="geolatvija", risk_level=""):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO sector_snapshots (sector, image_path, snapshot_date, label, note, source, uploaded_at, risk_level)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (sector, image_path, snapshot_date, label, note, source, now, risk_level))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def get_sector_snapshots(sector):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM sector_snapshots WHERE sector=? ORDER BY snapshot_date, id", (sector,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def add_inspector_analysis(scope, sector, summary_text, risk_breakdown,
                            exposure_low, exposure_high, exposure_basis, model):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    risk_breakdown_json = json.dumps(risk_breakdown) if risk_breakdown is not None else None
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO ai_inspector_analyses
        (scope, sector, summary_text, risk_breakdown_json, exposure_low, exposure_high, exposure_basis, model, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (scope, sector, summary_text, risk_breakdown_json, exposure_low, exposure_high, exposure_basis, model, now))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def get_inspector_analyses(scope=None, sector=None, limit=20):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    query = "SELECT * FROM ai_inspector_analyses WHERE 1=1"
    params = []
    if scope:
        query += " AND scope=?"
        params.append(scope)
    if sector:
        query += " AND sector=?"
        params.append(sector)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def delete_sector_snapshot(id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT image_path FROM sector_snapshots WHERE id=?", (id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    image_path = row[0]
    cur.execute("DELETE FROM sector_snapshots WHERE id=?", (id,))
    conn.commit()
    conn.close()
    if image_path:
        try:
            os.remove(image_path)
        except OSError:
            pass
    return True


# ── Snapshot Risks ────────────────────────────────────────────────────────────

def add_snapshot_risk(snapshot_id, risk_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO snapshot_risks (snapshot_id, risk_id) VALUES (?, ?)", (snapshot_id, risk_id))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def get_snapshot_risks(snapshot_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
    SELECT risks.id AS risk_id, risks.sector, risks.risk_level, risks.reason
    FROM snapshot_risks
    JOIN risks ON risks.id = snapshot_risks.risk_id
    WHERE snapshot_risks.snapshot_id=?
    """, (snapshot_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def remove_snapshot_risk(snapshot_id, risk_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM snapshot_risks WHERE snapshot_id=? AND risk_id=?", (snapshot_id, risk_id))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected > 0


# ── Satellite Intelligence Engine ───────────────────────────────────────────

def add_satellite_observation(sector, provider, tier, satellite=None, acquisition_date=None,
                               resolution_m=None, cloud_cover_pct=None, bbox=None, image_id=None,
                               image_ref=None, source="LIVE", cost_eur=None, risk_score=None,
                               ai_analysis_ref=None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO satellite_observations
        (sector, provider, satellite, tier, acquisition_date, resolution_m, cloud_cover_pct,
         bbox_json, image_id, image_ref, source, cost_eur, risk_score, ai_analysis_ref, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sector, provider, satellite, tier, acquisition_date, resolution_m, cloud_cover_pct,
          json.dumps(bbox) if bbox else None, image_id, image_ref, source, cost_eur, risk_score,
          ai_analysis_ref, now))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def get_satellite_observations(sector=None, provider=None, limit=100):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    query = "SELECT * FROM satellite_observations WHERE 1=1"
    params = []
    if sector:
        query += " AND sector=?"
        params.append(sector)
    if provider:
        query += " AND provider=?"
        params.append(provider)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_latest_satellite_observation(sector, provider=None):
    obs = get_satellite_observations(sector=sector, provider=provider, limit=1)
    return obs[0] if obs else None


def add_satellite_request(sector, tier, provider, justification, estimated_cost_eur=None,
                           reason=None, satellite_risk_score=None, requested_resolution_m=None,
                           aoi_area_ha=None, approval_status="PENDING", combined_group_id=None,
                           linked_incident_id=None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO satellite_requests
        (sector, tier, provider, estimated_cost_eur, reason, justification, satellite_risk_score,
         requested_resolution_m, aoi_area_ha, approval_status, combined_group_id,
         linked_incident_id, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sector, tier, provider, estimated_cost_eur, reason, justification, satellite_risk_score,
          requested_resolution_m, aoi_area_ha, approval_status, combined_group_id,
          linked_incident_id, now))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def update_satellite_request_status(request_id, approval_status, fulfilled_observation_id=None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if approval_status == "FULFILLED":
        cur.execute(
            "UPDATE satellite_requests SET approval_status=?, fulfilled_observation_id=?, fulfilled_at=? WHERE id=?",
            (approval_status, fulfilled_observation_id, now, request_id),
        )
    else:
        cur.execute("UPDATE satellite_requests SET approval_status=? WHERE id=?", (approval_status, request_id))
    conn.commit()
    conn.close()


def link_satellite_request_incident(request_id, incident_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE satellite_requests SET linked_incident_id=? WHERE id=?", (incident_id, request_id))
    conn.commit()
    conn.close()


def get_satellite_requests(sector=None, approval_status=None, limit=100):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    query = "SELECT * FROM satellite_requests WHERE 1=1"
    params = []
    if sector:
        query += " AND sector=?"
        params.append(sector)
    if approval_status:
        query += " AND approval_status=?"
        params.append(approval_status)
    # created_at has 1-second resolution — id DESC breaks ties deterministically
    # (needed because decide_and_request() can insert two requests, e.g. a
    # MEDIUM PlanetScope request followed immediately by a HIGH SkySat one for
    # the same sector, within the same second).
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_satellite_request(request_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM satellite_requests WHERE id=?", (request_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def add_satellite_score(sector, score, band, tier_recommended=None, inputs=None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO sector_satellite_scores (sector, score, band, tier_recommended, inputs_json, computed_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (sector, score, band, tier_recommended, json.dumps(inputs) if inputs is not None else None, now))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def get_latest_satellite_score(sector):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM sector_satellite_scores WHERE sector=? ORDER BY computed_at DESC, id DESC LIMIT 1",
        (sector,)
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_satellite_score_history(sector, limit=20):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM sector_satellite_scores WHERE sector=? ORDER BY computed_at DESC, id DESC LIMIT ?",
        (sector, limit)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_satellite_timeline_event(sector, event_type, label=None, detail=None, ref_table=None,
                                  ref_id=None, occurred_at=None):
    now = occurred_at or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO satellite_timeline_events (sector, event_type, label, detail, ref_table, ref_id, occurred_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (sector, event_type, label, detail, ref_table, ref_id, now))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def get_satellite_timeline(sector, limit=100):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM satellite_timeline_events WHERE sector=? ORDER BY occurred_at ASC, id ASC LIMIT ?",
        (sector, limit)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ── Integration Layer ────────────────────────────────────────────────────────
# Backing store for services/integrations/. Same conventions as the
# satellite_* functions above: one connection per call, sqlite3.Row for
# dict-shaped reads, UTC "%Y-%m-%d %H:%M:%S UTC" timestamps.

def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def create_integration(organization_id, category, provider, integration_type=None,
                        display_name=None, is_demo=False, configuration=None,
                        sync_frequency_minutes=60):
    now = _now()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO integrations
        (organization_id, category, provider, integration_type, display_name,
         connection_status, sync_status, is_demo, configuration_json,
         sync_frequency_minutes, records_received, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, 'NOT_CONNECTED', 'IDLE', ?, ?, ?, 0, ?, ?)
    """, (organization_id, category, provider, integration_type, display_name,
          1 if is_demo else 0, json.dumps(configuration) if configuration else None,
          sync_frequency_minutes, now, now))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def get_integrations(organization_id=None, category=None):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    query = "SELECT * FROM integrations WHERE 1=1"
    params = []
    if organization_id is not None:
        query += " AND organization_id=?"
        params.append(organization_id)
    if category:
        query += " AND category=?"
        params.append(category)
    query += " ORDER BY category, provider"
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_integration(integration_id, organization_id=None):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    query = "SELECT * FROM integrations WHERE id=?"
    params = [integration_id]
    if organization_id is not None:
        query += " AND organization_id=?"
        params.append(organization_id)
    cur.execute(query, params)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_integration_by_provider(provider, organization_id=1):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM integrations WHERE provider=? AND organization_id=? ORDER BY id LIMIT 1",
        (provider, organization_id),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_integration(integration_id, **fields):
    """Generic column-value patch, restricted to a known-safe allowlist so
    callers can't accidentally write to arbitrary columns from user input."""
    allowed = {
        "connection_status", "sync_status", "credentials_reference", "configuration_json",
        "sync_frequency_minutes", "last_sync_at", "next_sync_at", "last_success_at",
        "last_error_at", "error_message", "records_received", "display_name", "integration_type",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(f"UPDATE integrations SET {set_clause} WHERE id=?", (*updates.values(), integration_id))
    conn.commit()
    conn.close()


def increment_integration_records(integration_id, count):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "UPDATE integrations SET records_received = records_received + ?, updated_at=? WHERE id=?",
        (count, _now(), integration_id),
    )
    conn.commit()
    conn.close()


def delete_integration(integration_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM integrations WHERE id=?", (integration_id,))
    cur.execute("DELETE FROM integration_credentials WHERE integration_id=?", (integration_id,))
    conn.commit()
    conn.close()


def set_integration_credential(integration_id, encrypted_value):
    now = _now()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id FROM integration_credentials WHERE integration_id=?", (integration_id,))
    existing = cur.fetchone()
    if existing:
        cur.execute(
            "UPDATE integration_credentials SET encrypted_value=?, updated_at=? WHERE integration_id=?",
            (encrypted_value, now, integration_id),
        )
    else:
        cur.execute(
            "INSERT INTO integration_credentials (integration_id, encrypted_value, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (integration_id, encrypted_value, now, now),
        )
    conn.commit()
    conn.close()


def get_integration_credential(integration_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM integration_credentials WHERE integration_id=?", (integration_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def start_sync_run(integration_id, trigger="manual"):
    now = _now()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO integration_sync_runs (integration_id, trigger, status, started_at) "
        "VALUES (?, ?, 'RUNNING', ?)",
        (integration_id, trigger, now),
    )
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def finish_sync_run(sync_run_id, status, records_fetched=0, records_saved=0,
                     records_deduplicated=0, error_message=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    UPDATE integration_sync_runs
    SET status=?, records_fetched=?, records_saved=?, records_deduplicated=?,
        error_message=?, finished_at=?
    WHERE id=?
    """, (status, records_fetched, records_saved, records_deduplicated, error_message, _now(), sync_run_id))
    conn.commit()
    conn.close()


def get_sync_runs(integration_id, limit=20):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM integration_sync_runs WHERE integration_id=? ORDER BY started_at DESC, id DESC LIMIT ?",
        (integration_id, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def add_integration_log(integration_id, message, level="INFO", sync_run_id=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO integration_logs (integration_id, sync_run_id, level, message, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (integration_id, sync_run_id, level, message, _now()),
    )
    conn.commit()
    conn.close()


def get_integration_logs(integration_id, limit=100):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM integration_logs WHERE integration_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
        (integration_id, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_integration_record(integration_id, organization_id, source_provider, entity_type,
                               external_id, deduplication_key, sector=None, source_timestamp=None,
                               raw_payload=None, normalized_payload=None, validation_status="VALID",
                               processing_status="PROCESSED", linked_table=None, linked_id=None,
                               is_demo=False):
    """Idempotent upsert keyed on deduplication_key (UNIQUE column) — re-running
    a sync never creates duplicate rows for the same
    organization_id/source_provider/external_id/source_timestamp combination.
    Returns (record_id, created: bool)."""
    now = _now()
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id FROM integration_records WHERE deduplication_key=?", (deduplication_key,))
    existing = cur.fetchone()
    raw_json = json.dumps(raw_payload) if raw_payload is not None else None
    norm_json = json.dumps(normalized_payload) if normalized_payload is not None else None
    if existing:
        cur.execute("""
        UPDATE integration_records
        SET raw_payload_json=?, normalized_payload_json=?, validation_status=?,
            processing_status=?, linked_table=?, linked_id=?, received_at=?
        WHERE id=?
        """, (raw_json, norm_json, validation_status, processing_status, linked_table, linked_id,
              now, existing["id"]))
        conn.commit()
        record_id = existing["id"]
        created = False
    else:
        cur.execute("""
        INSERT INTO integration_records
            (integration_id, organization_id, source_provider, entity_type, external_id, sector,
             source_timestamp, received_at, raw_payload_json, normalized_payload_json,
             validation_status, processing_status, deduplication_key, linked_table, linked_id,
             is_demo, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (integration_id, organization_id, source_provider, entity_type, external_id, sector,
              source_timestamp, now, raw_json, norm_json, validation_status, processing_status,
              deduplication_key, linked_table, linked_id, 1 if is_demo else 0, now))
        conn.commit()
        record_id = cur.lastrowid
        created = True
    conn.close()
    return record_id, created


def get_integration_records(integration_id, limit=50):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM integration_records WHERE integration_id=? ORDER BY received_at DESC, id DESC LIMIT ?",
        (integration_id, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def count_integration_records(integration_id, is_demo=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    query = "SELECT COUNT(*) FROM integration_records WHERE integration_id=?"
    params = [integration_id]
    if is_demo is not None:
        query += " AND is_demo=?"
        params.append(1 if is_demo else 0)
    cur.execute(query, params)
    count = cur.fetchone()[0]
    conn.close()
    return count


def delete_demo_integration_records(integration_id):
    """Reset Demo Data for one integration — removes only is_demo=1 rows it
    created, never touches production records or other integrations."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM integration_records WHERE integration_id=? AND is_demo=1", (integration_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


def record_webhook_event(provider, payload_hash, integration_id=None, signature_valid=None):
    """Returns (event_id, is_new). is_new=False means this exact payload was
    already processed — caller should skip re-processing (webhook replay
    protection), relying on payload_hash UNIQUE for atomicity."""
    now = _now()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    try:
        cur.execute("""
        INSERT INTO integration_webhook_events
            (provider, integration_id, payload_hash, signature_valid, status, received_at)
        VALUES (?, ?, ?, ?, 'RECEIVED', ?)
        """, (provider, integration_id, payload_hash, signature_valid, now))
        conn.commit()
        event_id = cur.lastrowid
        conn.close()
        return event_id, True
    except sqlite3.IntegrityError:
        conn.close()
        existing = db1_raw("SELECT id FROM integration_webhook_events WHERE payload_hash=?", (payload_hash,))
        return (existing["id"] if existing else None), False


def mark_webhook_processed(event_id, status="PROCESSED"):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "UPDATE integration_webhook_events SET status=?, processed_at=? WHERE id=?",
        (status, _now(), event_id),
    )
    conn.commit()
    conn.close()


def db1_raw(sql, params=()):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def add_weighbridge_record(sector, vehicle_plate=None, driver=None, trip_number=None,
                            destination=None, species=None, assortment=None, weighed_at=None,
                            weight_gross_kg=None, weight_tare_kg=None, declared_volume_m3=None,
                            actual_volume_m3=None, document_number=None, photo_path=None,
                            acceptance_status="PENDING", integration_id=None, is_demo=False,
                            source_record_id=None):
    weight_net_kg = None
    if weight_gross_kg is not None and weight_tare_kg is not None:
        weight_net_kg = weight_gross_kg - weight_tare_kg
    now = _now()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO weighbridge_records
        (integration_id, sector, vehicle_plate, driver, trip_number, destination, species,
         assortment, weighed_at, weight_gross_kg, weight_tare_kg, weight_net_kg,
         declared_volume_m3, actual_volume_m3, document_number, photo_path, acceptance_status,
         is_demo, source_record_id, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (integration_id, sector, vehicle_plate, driver, trip_number, destination, species,
          assortment, weighed_at, weight_gross_kg, weight_tare_kg, weight_net_kg,
          declared_volume_m3, actual_volume_m3, document_number, photo_path, acceptance_status,
          1 if is_demo else 0, source_record_id, now))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def get_weighbridge_records(sector=None, integration_id=None, limit=100):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    query = "SELECT * FROM weighbridge_records WHERE 1=1"
    params = []
    if sector:
        query += " AND sector=?"
        params.append(sector)
    if integration_id is not None:
        query += " AND integration_id=?"
        params.append(integration_id)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def delete_demo_weighbridge_records(integration_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM weighbridge_records WHERE integration_id=? AND is_demo=1", (integration_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted
