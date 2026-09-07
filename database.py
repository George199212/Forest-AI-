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

    conn.commit()
    conn.close()


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
