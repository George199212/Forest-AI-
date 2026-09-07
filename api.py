"""
Forest AI — Full Commercial API
Run: uvicorn api:app --host 0.0.0.0 --port 8000
"""

import sqlite3, os, io, math, json, secrets, requests
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, Response, Request, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, RedirectResponse
from pydantic import BaseModel

from database import init_db, get_incidents, get_equipment, update_incident_status, add_risk_event

try:
    from PIL import Image, ImageDraw
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

DB_NAME = os.environ.get("DB_PATH", "data/forest_ai.db")
PHOTOS_DIR = Path(os.environ.get("PHOTOS_DIR", "data/work_photos"))
PLANS_DIR = Path("data/boundary_plans")
OBJECT_SATELLITE_DIR = Path("data/object_satellite")
SECTOR_SATELLITE_DIR = Path("data/sector_satellite")
SECTOR_SNAPSHOTS_DIR = Path("data/sector_snapshots")
PLANS_DIR.mkdir(parents=True, exist_ok=True)
OBJECT_SATELLITE_DIR.mkdir(parents=True, exist_ok=True)
SECTOR_SATELLITE_DIR.mkdir(parents=True, exist_ok=True)
SECTOR_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

_basic_auth = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(_basic_auth)):
    expected_user = os.environ.get("DASHBOARD_USERNAME", "")
    expected_pass = os.environ.get("DASHBOARD_PASSWORD", "")
    user_ok = secrets.compare_digest(credentials.username, expected_user)
    pass_ok = secrets.compare_digest(credentials.password, expected_pass)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


app = FastAPI(title="Forest AI API", dependencies=[Depends(verify_credentials)])


@app.on_event("startup")
def _init_db_on_startup():
    init_db()


# ── DB helpers ────────────────────────────────────────────────────────────────

def db(sql, params=()):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def db1(sql, params=()):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}

def n(sql, params=()):
    return db1(sql, params).get("n", 0)


# ── Risk Score Calculator ─────────────────────────────────────────────────────

def calc_risk_score(sector_name: str) -> dict:
    high_risks   = n("SELECT COUNT(*) AS n FROM risks WHERE sector=? AND risk_level='HIGH'", (sector_name,))
    medium_risks = n("SELECT COUNT(*) AS n FROM risks WHERE sector=? AND risk_level='MEDIUM'", (sector_name,))
    rejected_gps = n("SELECT COUNT(*) AS n FROM work_sessions WHERE sector=? AND approved='NO'", (sector_name,))
    timber_miss  = n("SELECT COUNT(*) AS n FROM timber_movements WHERE sector=? AND status='MISSING_VOLUME'", (sector_name,))
    timber_over  = n("SELECT COUNT(*) AS n FROM timber_movements WHERE sector=? AND status='OVER_VOLUME'", (sector_name,))

    score = (high_risks * 25) + (medium_risks * 10) + (rejected_gps * 15) + (timber_miss * 20) + (timber_over * 15)
    score = min(100, score)

    if score <= 30:
        level, color = "LOW", "green"
    elif score <= 60:
        level, color = "MEDIUM", "yellow"
    else:
        level, color = "HIGH", "red"

    # ── Financial exposure calculator ─────────────────────────────────────────
    # Timber: missing volume → financial loss
    timber_miss_vol = db1(
        "SELECT COALESCE(SUM(ABS(difference_volume)),0) AS v FROM timber_movements WHERE sector=? AND status='MISSING_VOLUME'",
        (sector_name,)
    ).get("v", 0) or 0

    timber_over_vol = db1(
        "SELECT COALESCE(SUM(ABS(difference_volume)),0) AS v FROM timber_movements WHERE sector=? AND status='OVER_VOLUME'",
        (sector_name,)
    ).get("v", 0) or 0

    # Truck discrepancy
    truck_total = db1(
        "SELECT COALESCE(SUM(reported_volume),0) AS v FROM truck_reports WHERE sector=?",
        (sector_name,)
    ).get("v", 0) or 0

    timber_actual = db1(
        "SELECT COALESCE(SUM(actual_volume),0) AS v FROM timber_movements WHERE sector=?",
        (sector_name,)
    ).get("v", 0) or 0

    truck_discrepancy = max(0, float(timber_actual) - float(truck_total))

    # Price per m³ (conservative market estimate for roundwood)
    PRICE_PER_M3_LOW  = 60   # €/m³ conservative
    PRICE_PER_M3_HIGH = 120  # €/m³ premium

    vol_at_risk = float(timber_miss_vol) + truck_discrepancy

    exposure_low  = round(vol_at_risk * PRICE_PER_M3_LOW)
    exposure_high = round(vol_at_risk * PRICE_PER_M3_HIGH)

    # GPS violations add indirect exposure (contractor trust/audit cost)
    if rejected_gps > 0:
        exposure_low  += rejected_gps * 200
        exposure_high += rejected_gps * 500

    # High risks add audit/investigation cost estimate
    if high_risks > 0:
        exposure_low  += high_risks * 500
        exposure_high += high_risks * 1500

    return {
        "score": score,
        "level": level,
        "color": color,
        "exposure_low":  exposure_low,
        "exposure_high": exposure_high,
        "exposure_label": f"€{exposure_low:,}–€{exposure_high:,}" if exposure_low > 0 else "€0",
        "vol_at_risk": round(float(vol_at_risk), 1),
        "timber_miss_vol": round(float(timber_miss_vol), 1),
        "truck_discrepancy": round(truck_discrepancy, 1),
        "rejected_gps": rejected_gps,
    }


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def serve_index():
    p = Path("index.html")
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>Forest AI</h1>")

@app.get("/photos/file/{filename}")
def serve_photo_file(filename: str):
    path = PHOTOS_DIR / filename
    if path.exists():
        return FileResponse(str(path))
    return Response(status_code=404)


# ── Summary ───────────────────────────────────────────────────────────────────

@app.get("/api/summary")
def summary():
    total_vol = db1("SELECT COALESCE(SUM(reported_volume),0) AS v FROM truck_reports").get("v", 0)
    sectors = db("SELECT name FROM sectors")
    risk_scores = [calc_risk_score(s["name"]) for s in sectors]
    red_count    = sum(1 for r in risk_scores if r["color"] == "red")
    yellow_count = sum(1 for r in risk_scores if r["color"] == "yellow")
    total_exp_low  = sum(r["exposure_low"]  for r in risk_scores)
    total_exp_high = sum(r["exposure_high"] for r in risk_scores)
    total_vol_risk = sum(r["vol_at_risk"]   for r in risk_scores)
    return {
        "sectors":          n("SELECT COUNT(*) AS n FROM sectors"),
        "risks":            n("SELECT COUNT(*) AS n FROM risks"),
        "high_risks":       n("SELECT COUNT(*) AS n FROM risks WHERE risk_level='HIGH'"),
        "gps_sessions":     n("SELECT COUNT(*) AS n FROM work_sessions"),
        "photos":           n("SELECT COUNT(*) AS n FROM work_photos"),
        "timber_movements": n("SELECT COUNT(*) AS n FROM timber_movements"),
        "truck_reports":    n("SELECT COUNT(*) AS n FROM truck_reports"),
        "total_volume_m3":  round(float(total_vol), 1),
        "red_sectors":      red_count,
        "yellow_sectors":   yellow_count,
        "exposure_low":     total_exp_low,
        "exposure_high":    total_exp_high,
        "exposure_label":   f"€{total_exp_low:,}–€{total_exp_high:,}" if total_exp_low > 0 else "€0",
        "vol_at_risk":      round(total_vol_risk, 1),
        "active_operations":    n("SELECT COUNT(DISTINCT sector) AS n FROM work_sessions WHERE finish_time='' OR finish_time IS NULL"),
        "field_checkins_today": n("""
            SELECT COUNT(*) AS n FROM work_sessions
            WHERE DATE(REPLACE(check_in_time, ' UTC', '')) = DATE('now')
        """),
        "unverified_work":      n("SELECT COUNT(*) AS n FROM work_sessions WHERE approved != 'YES'"),
    }


# ── Sectors ───────────────────────────────────────────────────────────────────

@app.get("/api/sectors")
def get_sectors():
    sectors = db("""
        SELECT name, contractor, status, approved_volume, map_url,
               boundary_json, center_lat, center_lon, area_ha, color, created_at, updated_at,
               boundary_plan_id, object_name
        FROM sectors ORDER BY name
    """)
    for s in sectors:
        rs = calc_risk_score(s["name"])
        s["risk_score"]   = rs["score"]
        s["risk_level"]   = rs["level"]
        s["risk_color"]   = rs["color"]
        s["exposure_label"] = rs["exposure_label"]
        s["gps_count"]    = n("SELECT COUNT(*) AS n FROM work_sessions WHERE sector=?", (s["name"],))
        s["photo_count"]  = n("SELECT COUNT(*) AS n FROM work_photos WHERE sector=?", (s["name"],))
        s["risk_count"]   = n("SELECT COUNT(*) AS n FROM risks WHERE sector=?", (s["name"],))
        s["truck_count"]  = n("SELECT COUNT(*) AS n FROM truck_reports WHERE sector=?", (s["name"],))
        s["timber_count"] = n("SELECT COUNT(*) AS n FROM timber_movements WHERE sector=?", (s["name"],))
        # Parse boundary_json for frontend convenience
        if s.get("boundary_json"):
            try:
                s["boundary"] = json.loads(s["boundary_json"])
            except Exception:
                s["boundary"] = None
        else:
            s["boundary"] = None
    return sectors


class SectorIn(BaseModel):
    name: str
    contractor: str = ""
    status: str = ""
    approved_volume: str = ""
    boundary: Optional[List[List[float]]] = None
    color: str = "red"


@app.post("/api/sectors")
def create_sector(body: SectorIn):
    from database import add_sector as _add_sector
    if body.boundary and len(body.boundary) < 4:
        return Response(content='{"error":"Boundary must have at least 4 points"}',
                        media_type="application/json", status_code=400)
    _add_sector(
        name=body.name,
        contractor=body.contractor,
        status=body.status,
        approved_volume=body.approved_volume,
        boundary=body.boundary,
        color=body.color,
    )
    return {"ok": True, "name": body.name}


@app.put("/api/sectors/{name}")
def update_sector(name: str, body: SectorIn):
    from database import add_sector as _add_sector
    _add_sector(
        name=name,
        contractor=body.contractor,
        status=body.status,
        approved_volume=body.approved_volume,
        boundary=body.boundary,
        color=body.color,
    )
    return {"ok": True, "name": name}


@app.delete("/api/sectors/{name}")
def delete_sector(name: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM sectors WHERE name=?", (name,))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    if affected == 0:
        return Response(content='{"error":"Not found"}', media_type="application/json", status_code=404)
    return {"ok": True, "deleted": name}


# ── Objects (grouped sectors from the same Robežu Plāns scan) ────────────────

@app.get("/api/objects")
def get_objects():
    """
    Group sectors by the object/parcel (boundary_plan_id) they came from.
    Sectors created manually (no plan behind them, e.g. A-004..A-008) are
    grouped under boundary_plan_id=None so nothing is lost from the view.
    Includes a link to the original plan scan image when available, so the
    dashboard can show the source Robežu Plāns next to its sectors.
    """
    plans = db("SELECT id, file_path, object_name, uploaded_at, status FROM boundary_plans")
    plans_by_id = {p["id"]: p for p in plans}

    sectors = db("""
        SELECT name, contractor, status, area_ha, color, boundary_plan_id, object_name
        FROM sectors ORDER BY boundary_plan_id IS NULL, boundary_plan_id, name
    """)

    grouped = {}
    order = []
    for s in sectors:
        key = s["boundary_plan_id"]
        if key not in grouped:
            plan = plans_by_id.get(key, {})
            grouped[key] = {
                "boundary_plan_id": key,
                "object_name": s["object_name"] or plan.get("object_name")
                    or ("Без объекта" if key is None else f"Plan #{key}"),
                "plan_scan_url": f"/api/boundary-plans/{key}/scan" if key and plan.get("file_path") else None,
                "plan_uploaded_at": plan.get("uploaded_at"),
                "plan_status": plan.get("status"),
                "sectors": [],
            }
            order.append(key)
        grouped[key]["sectors"].append({
            "name": s["name"],
            "contractor": s["contractor"],
            "status": s["status"],
            "area_ha": s["area_ha"],
            "color": s["color"],
        })
    return [grouped[k] for k in order]


@app.get("/api/boundary-plans/{plan_id}/scan")
def get_boundary_plan_scan(plan_id: int):
    """Serve the original uploaded scan of a Robežu Plāns, so the dashboard
    can display the source document next to the sectors created from it."""
    row = db1("SELECT file_path FROM boundary_plans WHERE id=?", (plan_id,))
    file_path = row.get("file_path")
    if not file_path or not Path(file_path).exists():
        return Response(status_code=404)
    return FileResponse(file_path)


# ── Object management: create objects and upload files from the dashboard ────

class ObjectCreate(BaseModel):
    object_name: str


@app.post("/api/objects")
def create_object(body: ObjectCreate):
    """Create a new empty object (no scan yet) directly from the dashboard,
    so a boundary plan / sectors can be added to it afterwards without going
    through the Telegram OCR flow."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO boundary_plans (file_path, document_type, uploaded_at, status, uploaded_by, plan_data_json, object_name)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("", "manual_object", now, "uploaded", "web", "{}", body.object_name))
    plan_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "boundary_plan_id": plan_id}


@app.post("/api/objects/{plan_id}/boundary-plan")
async def upload_boundary_plan(plan_id: int, file: UploadFile = File(...)):
    """Upload or replace the boundary plan scan image for an object."""
    row = db1("SELECT id FROM boundary_plans WHERE id=?", (plan_id,))
    if not row:
        return Response(content='{"error":"Object not found"}', media_type="application/json", status_code=404)
    ext = Path(file.filename or "plan.jpg").suffix or ".jpg"
    dest = PLANS_DIR / f"manual_{plan_id}{ext}"
    with open(dest, "wb") as f:
        f.write(await file.read())
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE boundary_plans SET file_path=? WHERE id=?", (str(dest), plan_id))
    conn.commit()
    conn.close()
    return {"ok": True, "file_path": str(dest)}


@app.post("/api/objects/{plan_id}/satellite")
async def upload_object_satellite(plan_id: int, file: UploadFile = File(...)):
    """Upload a satellite image manually for an object (used when Sentinel
    coverage isn't available/desired for this object)."""
    row = db1("SELECT id FROM boundary_plans WHERE id=?", (plan_id,))
    if not row:
        return Response(content='{"error":"Object not found"}', media_type="application/json", status_code=404)
    ext = Path(file.filename or "satellite.jpg").suffix or ".jpg"
    dest = OBJECT_SATELLITE_DIR / f"{plan_id}{ext}"
    with open(dest, "wb") as f:
        f.write(await file.read())
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE boundary_plans SET satellite_file_path=? WHERE id=?", (str(dest), plan_id))
    conn.commit()
    conn.close()
    return {"ok": True, "file_path": str(dest)}


@app.get("/api/objects/{plan_id}/satellite-image")
def get_object_satellite_image(plan_id: int):
    """Serve the object's satellite image: a manually uploaded one if
    present, otherwise fall back to the live Sentinel-2 fetch."""
    row = db1("SELECT satellite_file_path FROM boundary_plans WHERE id=?", (plan_id,))
    file_path = row.get("satellite_file_path")
    if file_path and Path(file_path).exists():
        return FileResponse(file_path)
    return RedirectResponse(url=f"/api/satellite/object/{plan_id}")


@app.post("/api/sectors/{name}/satellite")
async def upload_sector_satellite(name: str, file: UploadFile = File(...)):
    """Upload a satellite image manually for a specific sector."""
    row = db1("SELECT id FROM sectors WHERE name=?", (name,))
    if not row:
        return Response(content='{"error":"Sector not found"}', media_type="application/json", status_code=404)
    ext = Path(file.filename or "satellite.jpg").suffix or ".jpg"
    safe_name = "".join(c if c.isalnum() else "_" for c in name)
    dest = SECTOR_SATELLITE_DIR / f"{safe_name}{ext}"
    with open(dest, "wb") as f:
        f.write(await file.read())
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE sectors SET satellite_file_path=? WHERE name=?", (str(dest), name))
    conn.commit()
    conn.close()
    return {"ok": True, "file_path": str(dest)}


@app.get("/api/sectors/{name}/satellite-image")
def get_sector_satellite_image(name: str):
    """Serve the sector's satellite image: a manually uploaded one if
    present, otherwise fall back to the live Sentinel-2 fetch."""
    row = db1("SELECT satellite_file_path FROM sectors WHERE name=?", (name,))
    file_path = row.get("satellite_file_path")
    if file_path and Path(file_path).exists():
        return FileResponse(file_path)
    return RedirectResponse(url=f"/api/satellite/image/{name}")


@app.post("/api/sectors/{name}/snapshots")
async def upload_sector_snapshot(
    name: str,
    file: UploadFile = File(...),
    snapshot_date: str = Form(...),
    label: str = Form(""),
    note: str = Form(""),
    risk_level: str = Form(""),
):
    """Upload a dated historical snapshot image for a sector (e.g. from
    geolatvija.lv), building a snapshot history distinct from the live
    Sentinel-2 fetch under the Satellite tab. Each upload is a new row and
    a new file — existing snapshots are never overwritten."""
    if risk_level not in ("", "LOW", "MEDIUM", "HIGH"):
        return Response(content='{"error":"Invalid risk_level"}', media_type="application/json", status_code=400)
    row = db1("SELECT id FROM sectors WHERE name=?", (name,))
    if not row:
        return Response(content='{"error":"Sector not found"}', media_type="application/json", status_code=404)
    ext = Path(file.filename or "snapshot.jpg").suffix or ".jpg"
    safe_name = "".join(c if c.isalnum() else "_" for c in name)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    dest = SECTOR_SNAPSHOTS_DIR / f"{safe_name}_{timestamp}{ext}"
    suffix = 1
    while dest.exists():
        # Two uploads landing in the same second would otherwise collide on
        # this filename and silently overwrite each other on disk.
        dest = SECTOR_SNAPSHOTS_DIR / f"{safe_name}_{timestamp}_{suffix}{ext}"
        suffix += 1
    with open(dest, "wb") as f:
        f.write(await file.read())
    from database import add_sector_snapshot as _add_sector_snapshot
    snap_id = _add_sector_snapshot(name, str(dest), snapshot_date, label, note, risk_level=risk_level)
    return {"ok": True, "id": snap_id, "file_path": str(dest)}


@app.get("/api/sectors/{name}/snapshots")
def get_sector_snapshots_route(name: str):
    from database import get_sector_snapshots as _get_sector_snapshots
    return _get_sector_snapshots(name)


@app.get("/api/sectors/snapshots/{id}/image")
def get_sector_snapshot_image(id: int):
    row = db1("SELECT image_path FROM sector_snapshots WHERE id=?", (id,))
    file_path = row.get("image_path")
    if not file_path or not Path(file_path).exists():
        return Response(status_code=404)
    return FileResponse(file_path)


@app.delete("/api/sectors/snapshots/{id}")
def delete_sector_snapshot_route(id: int):
    from database import delete_sector_snapshot as _delete_sector_snapshot
    ok = _delete_sector_snapshot(id)
    return {"ok": ok}


class SnapshotRiskIn(BaseModel):
    risk_id: int

@app.post("/api/sectors/snapshots/{id}/risks")
def link_snapshot_risk(id: int, body: SnapshotRiskIn):
    from database import add_snapshot_risk as _add_snapshot_risk
    link_id = _add_snapshot_risk(id, body.risk_id)
    return {"ok": True, "id": link_id}

@app.get("/api/sectors/snapshots/{id}/risks")
def get_snapshot_risks_route(id: int):
    from database import get_snapshot_risks as _get_snapshot_risks
    return _get_snapshot_risks(id)

@app.delete("/api/sectors/snapshots/{id}/risks/{risk_id}")
def unlink_snapshot_risk(id: int, risk_id: int):
    from database import remove_snapshot_risk as _remove_snapshot_risk
    ok = _remove_snapshot_risk(id, risk_id)
    return {"ok": ok}


@app.get("/api/sectors/{name}/vehicles/{vehicle_id}/route")
def get_vehicle_route(name: str, vehicle_id: int):
    return db(
        "SELECT latitude, longitude, inside_boundary, recorded_at FROM vehicle_gps_pings WHERE vehicle_id=? ORDER BY recorded_at ASC",
        (vehicle_id,),
    )


class SectorPolygonIn(BaseModel):
    name: str
    pixel_boundary: List[List[float]]
    color: str = "blue"


def _lks92_to_wgs84(x: float, y: float):
    """Same approximate LKS-92 (EPSG:3059) -> WGS84 conversion used in
    services/robez_ocr_vision.py, kept in sync so manually-drawn polygons
    project to the same coordinates as OCR-derived ones."""
    lat = (x - 310000) / 111320 + 56.5
    lon = (y - 300000) / 74500 + 24.0
    return round(lat, 6), round(lon, 6)


def _pixel_polygon_to_latlon(pixel_boundary, georef_scale):
    """Convert a hand-drawn pixel polygon into a real [[lat,lon],...] boundary
    using a plan's previously-solved geo-reference scale (reference point +
    meters-per-pixel), the same way OCR's geometric fallback does it. Returns
    None if the scale is missing or incomplete."""
    if not georef_scale:
        return None
    try:
        ref_real_x = float(georef_scale["ref_real_x"])
        ref_real_y = float(georef_scale["ref_real_y"])
        ref_px = float(georef_scale["ref_px"])
        ref_py = float(georef_scale["ref_py"])
        meters_per_pixel = float(georef_scale["meters_per_pixel"])
    except (KeyError, TypeError, ValueError):
        return None

    boundary = []
    for px, py in pixel_boundary:
        dx_px = float(px) - ref_px
        dy_px = float(py) - ref_py
        dx_m = dx_px * meters_per_pixel
        dy_m = -dy_px * meters_per_pixel
        real_x = ref_real_x + dy_m
        real_y = ref_real_y + dx_m
        lat, lon = _lks92_to_wgs84(real_x, real_y)
        boundary.append([lat, lon])
    if boundary and boundary[0] != boundary[-1]:
        boundary.append(boundary[0])
    return boundary


@app.post("/api/objects/{plan_id}/sectors")
def create_sector_from_drawing(plan_id: int, body: SectorPolygonIn):
    """Create a new sector under this object from a manually-drawn polygon
    (pixel coordinates on the boundary plan image). If this plan already has
    a solved geo-reference scale (from an earlier OCR pass on the same
    image), the drawn polygon is automatically converted into a real GPS
    boundary too — so manually-defined logging sectors work with GPS
    check-in, Map, and Satellite just like OCR-derived ones. If no scale is
    available (e.g. the plan was uploaded manually with no OCR), the sector
    is still created, but only with a pixel-space outline for the plan view."""
    from database import add_sector as _add_sector
    if len(body.pixel_boundary) < 3:
        return Response(content='{"error":"Polygon needs at least 3 points"}', media_type="application/json", status_code=400)
    plan_row = db1("SELECT object_name, plan_data_json FROM boundary_plans WHERE id=?", (plan_id,))
    if not plan_row:
        return Response(content='{"error":"Object not found"}', media_type="application/json", status_code=404)

    georef_scale = None
    if plan_row.get("plan_data_json"):
        try:
            georef_scale = json.loads(plan_row["plan_data_json"]).get("georef_scale")
        except Exception:
            georef_scale = None

    boundary = _pixel_polygon_to_latlon(body.pixel_boundary, georef_scale)

    _add_sector(
        name=body.name, contractor="", status="Draft — manual",
        approved_volume="", boundary=boundary, color=body.color,
        boundary_plan_id=plan_id, object_name=plan_row.get("object_name") or "",
        pixel_boundary=body.pixel_boundary,
    )
    return {"ok": True, "name": body.name, "georeferenced": boundary is not None}


@app.post("/api/sectors/{name}/polygon")
def update_sector_polygon(name: str, body: SectorPolygonIn):
    """Update the pixel-space outline of an existing sector (redraw), and
    recompute its real GPS boundary too if the source plan has a known
    geo-reference scale."""
    if len(body.pixel_boundary) < 3:
        return Response(content='{"error":"Polygon needs at least 3 points"}', media_type="application/json", status_code=400)
    row = db1("SELECT id, boundary_plan_id FROM sectors WHERE name=?", (name,))
    if not row:
        return Response(content='{"error":"Sector not found"}', media_type="application/json", status_code=404)

    boundary_json = None
    plan_id = row.get("boundary_plan_id")
    if plan_id:
        plan_row = db1("SELECT plan_data_json FROM boundary_plans WHERE id=?", (plan_id,))
        georef_scale = None
        if plan_row and plan_row.get("plan_data_json"):
            try:
                georef_scale = json.loads(plan_row["plan_data_json"]).get("georef_scale")
            except Exception:
                georef_scale = None
        boundary = _pixel_polygon_to_latlon(body.pixel_boundary, georef_scale)
        if boundary:
            from database import calc_centroid as _calc_centroid, calc_area_ha as _calc_area_ha
            boundary_json = json.dumps(boundary)
            center_lat, center_lon = _calc_centroid(boundary)
            area_ha = _calc_area_ha(boundary)

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if boundary_json:
        cur.execute(
            "UPDATE sectors SET pixel_boundary_json=?, boundary_json=?, center_lat=?, center_lon=?, area_ha=? WHERE name=?",
            (json.dumps(body.pixel_boundary), boundary_json, center_lat, center_lon, area_ha, name)
        )
    else:
        cur.execute("UPDATE sectors SET pixel_boundary_json=? WHERE name=?", (json.dumps(body.pixel_boundary), name))
    conn.commit()
    conn.close()
    return {"ok": True, "name": name, "georeferenced": boundary_json is not None}


_SECTOR_OUTLINE_COLORS = [
    (255, 80, 80), (80, 190, 255), (255, 200, 60), (140, 255, 110),
    (255, 120, 255), (100, 255, 210), (255, 160, 80), (170, 170, 255),
]


def _draw_sector_polygons(image_path, sectors_with_pixels, highlight_name=None):
    """
    sectors_with_pixels: list of {"name": str, "pixel_boundary": [[x,y],...]}
    Draws each sector's outline in its own color with a name label. If
    highlight_name is given, that one sector is drawn bold/opaque and every
    other sector is dimmed, to focus attention on a single sector within the
    context of the full plan (used for the per-sector crop view).
    Returns a PIL Image (RGB).
    """
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    for i, s in enumerate(sectors_with_pixels):
        pts = s.get("pixel_boundary")
        if not pts or len(pts) < 3:
            continue
        color = _SECTOR_OUTLINE_COLORS[i % len(_SECTOR_OUTLINE_COLORS)]
        is_focus = (highlight_name is None or s.get("name") == highlight_name)
        width = 5 if (highlight_name and is_focus) else 3
        alpha = 255 if is_focus else 80
        fill_alpha = 55 if is_focus else 18
        poly = [(float(p[0]), float(p[1])) for p in pts]
        draw.polygon(poly, fill=color + (fill_alpha,))
        n = len(poly)
        for k in range(n):
            x1, y1 = poly[k]
            x2, y2 = poly[(k + 1) % n]
            draw.line([x1, y1, x2, y2], fill=color + (alpha,), width=width)
        label = s.get("name", "")
        if label and is_focus:
            lx, ly = poly[0]
            text_w = 7 * len(label) + 8
            draw.rectangle([lx, ly - 16, lx + text_w, ly], fill=(0, 0, 0, 190))
            draw.text((lx + 4, ly - 15), label, fill=(255, 255, 255, 255))
    return img


@app.get("/api/boundary-plans/{plan_id}/annotated")
def get_boundary_plan_annotated(plan_id: int):
    """Serve the original plan scan with ALL of its sectors' outlines drawn
    on top, so the whole object can be seen divided into its sectors at a
    glance (used on the Objects page)."""
    if not _PIL_AVAILABLE:
        return Response(content='{"error":"Pillow not installed on server. Run: pip install Pillow --break-system-packages"}',
                        media_type="application/json", status_code=500)
    row = db1("SELECT file_path FROM boundary_plans WHERE id=?", (plan_id,))
    file_path = row.get("file_path")
    if not file_path or not Path(file_path).exists():
        return Response(status_code=404)

    sectors = db("SELECT name, pixel_boundary_json FROM sectors WHERE boundary_plan_id=?", (plan_id,))
    sectors_with_pixels = []
    for s in sectors:
        if s.get("pixel_boundary_json"):
            try:
                sectors_with_pixels.append({"name": s["name"], "pixel_boundary": json.loads(s["pixel_boundary_json"])})
            except Exception:
                pass

    if not sectors_with_pixels:
        return FileResponse(file_path)

    img = _draw_sector_polygons(file_path, sectors_with_pixels)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return Response(content=buf.getvalue(), media_type="image/jpeg")


@app.get("/api/sectors/{name}/plan-crop")
def get_sector_plan_crop(name: str):
    """Serve a cropped view of the source plan scan focused on this specific
    sector's outline (highlighted, with neighboring sectors dimmed for
    context), for the sector detail page."""
    if not _PIL_AVAILABLE:
        return Response(content='{"error":"Pillow not installed on server. Run: pip install Pillow --break-system-packages"}',
                        media_type="application/json", status_code=500)

    sector = db1("SELECT boundary_plan_id, pixel_boundary_json FROM sectors WHERE name=?", (name,))
    plan_id = sector.get("boundary_plan_id")
    pixel_json = sector.get("pixel_boundary_json")
    if not plan_id or not pixel_json:
        return Response(status_code=404)

    plan_row = db1("SELECT file_path FROM boundary_plans WHERE id=?", (plan_id,))
    file_path = plan_row.get("file_path")
    if not file_path or not Path(file_path).exists():
        return Response(status_code=404)

    try:
        this_boundary = json.loads(pixel_json)
    except Exception:
        return Response(status_code=404)
    if len(this_boundary) < 3:
        return Response(status_code=404)

    sectors = db("SELECT name, pixel_boundary_json FROM sectors WHERE boundary_plan_id=?", (plan_id,))
    sectors_with_pixels = []
    for s in sectors:
        if s.get("pixel_boundary_json"):
            try:
                sectors_with_pixels.append({"name": s["name"], "pixel_boundary": json.loads(s["pixel_boundary_json"])})
            except Exception:
                pass

    img = _draw_sector_polygons(file_path, sectors_with_pixels, highlight_name=name)

    xs = [float(p[0]) for p in this_boundary]
    ys = [float(p[1]) for p in this_boundary]
    pad_x = max(30.0, (max(xs) - min(xs)) * 0.25)
    pad_y = max(30.0, (max(ys) - min(ys)) * 0.25)
    left = max(0, int(min(xs) - pad_x))
    top = max(0, int(min(ys) - pad_y))
    right = min(img.width, int(max(xs) + pad_x))
    bottom = min(img.height, int(max(ys) + pad_y))
    cropped = img.crop((left, top, right, bottom))

    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=90)
    return Response(content=buf.getvalue(), media_type="image/jpeg")


# ── Employees ─────────────────────────────────────────────────────────────────

class EmployeeIn(BaseModel):
    sector: str
    full_name: str
    role: str = ""
    phone: str = ""
    id_number: str = ""
    notes: str = ""
    telegram_user_id: str = ""

@app.get("/api/employees")
def get_all_employees():
    return db("SELECT * FROM sector_employees ORDER BY sector, full_name")

@app.get("/api/employees/{sector}")
def get_sector_employees(sector: str):
    return db("SELECT * FROM sector_employees WHERE sector=? ORDER BY full_name", (sector,))

@app.post("/api/employees")
def create_employee(body: EmployeeIn):
    from database import add_employee as _add
    eid = _add(body.sector, body.full_name, body.role, body.phone, body.id_number, body.notes, body.telegram_user_id)
    return {"ok": True, "id": eid}

@app.delete("/api/employees/{eid}")
def delete_employee(eid: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM sector_employees WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    return {"ok": True}

class EmployeePatchIn(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    id_number: Optional[str] = None
    notes: Optional[str] = None
    telegram_user_id: Optional[str] = None
    active: Optional[int] = None

@app.patch("/api/employees/{eid}")
def update_employee(eid: int, body: EmployeePatchIn):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        return {"ok": True}
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    cur.execute(f"UPDATE sector_employees SET {set_clause} WHERE id=?", (*fields.values(), eid))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Vehicles ──────────────────────────────────────────────────────────────────

class VehicleIn(BaseModel):
    sector: str
    plate: str
    vehicle_type: str = ""
    driver: str = ""
    fuel_capacity_l: float = 0
    fuel_per_100km: float = 0
    notes: str = ""
    telegram_user_id: str = ""

class FuelLogIn(BaseModel):
    vehicle_id: int
    sector: str
    km_start: float
    km_end: float
    fuel_added_l: float
    note: str = ""

@app.get("/api/vehicles")
def get_all_vehicles():
    return db("SELECT * FROM sector_vehicles ORDER BY sector, plate")

@app.get("/api/vehicles/{sector}")
def get_sector_vehicles(sector: str):
    vehicles = db("SELECT * FROM sector_vehicles WHERE sector=? ORDER BY plate", (sector,))
    for v in vehicles:
        v["fuel_logs"] = db("SELECT * FROM vehicle_fuel_logs WHERE vehicle_id=? ORDER BY id DESC LIMIT 5", (v["id"],))
    return vehicles

@app.post("/api/vehicles")
def create_vehicle(body: VehicleIn):
    from database import add_vehicle as _add
    vid = _add(body.sector, body.plate, body.vehicle_type, body.driver,
               body.fuel_capacity_l, body.fuel_per_100km, body.notes, body.telegram_user_id)
    return {"ok": True, "id": vid}

@app.post("/api/vehicles/fuel-log")
def add_fuel_log(body: FuelLogIn):
    from database import log_fuel as _log
    # Get vehicle fuel_per_100km
    v = db1("SELECT fuel_per_100km FROM sector_vehicles WHERE id=?", (body.vehicle_id,))
    fper = v.get("fuel_per_100km", 0) or 0
    disc = _log(body.vehicle_id, body.sector, body.km_start, body.km_end,
                body.fuel_added_l, fper, body.note)
    if abs(disc) > 5:
        # Auto-create risk if discrepancy > 5L
        from database import add_risk as _risk
        _risk(body.sector, "MEDIUM",
              f"Fuel discrepancy on vehicle {body.vehicle_id}: added {body.fuel_added_l}L, calculated {round(fper*(body.km_end-body.km_start)/100,1)}L, diff {disc}L")
    return {"ok": True, "discrepancy_l": disc}

@app.delete("/api/vehicles/{vid}")
def delete_vehicle(vid: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM sector_vehicles WHERE id=?", (vid,))
    conn.commit()
    conn.close()
    return {"ok": True}

class VehiclePatchIn(BaseModel):
    plate: Optional[str] = None
    vehicle_type: Optional[str] = None
    driver: Optional[str] = None
    fuel_capacity_l: Optional[float] = None
    fuel_per_100km: Optional[float] = None
    notes: Optional[str] = None
    active: Optional[int] = None

@app.patch("/api/vehicles/{vid}")
def update_vehicle(vid: int, body: VehiclePatchIn):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        return {"ok": True}
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    cur.execute(f"UPDATE sector_vehicles SET {set_clause} WHERE id=?", (*fields.values(), vid))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Sector notes/species update ───────────────────────────────────────────────

class SectorNotesIn(BaseModel):
    tree_species: Optional[str] = None
    cut_plan_notes: Optional[str] = None
    notes: Optional[str] = None

@app.patch("/api/sectors/{name}/notes")
def update_sector_notes(name: str, body: SectorNotesIn):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if body.tree_species is not None:
        cur.execute("UPDATE sectors SET tree_species=?, updated_at=? WHERE name=?", (body.tree_species, now, name))
    if body.cut_plan_notes is not None:
        cur.execute("UPDATE sectors SET cut_plan_notes=?, updated_at=? WHERE name=?", (body.cut_plan_notes, now, name))
    if body.notes is not None:
        cur.execute("UPDATE sectors SET notes=?, updated_at=? WHERE name=?", (body.notes, now, name))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/sectors/{name}")
def get_sector_detail(name: str):
    sector = db1("SELECT * FROM sectors WHERE name=?", (name,))
    if not sector:
        return {"error": "Not found"}
    rs = calc_risk_score(name)
    sector["risk_score"] = rs["score"]
    sector["risk_level"] = rs["level"]
    sector["risk_color"] = rs["color"]
    sector["exposure_low"] = rs["exposure_low"]
    sector["exposure_high"] = rs["exposure_high"]
    sector["exposure_label"] = rs["exposure_label"]
    sector["vol_at_risk"] = rs["vol_at_risk"]
    sector["timber_miss_vol"] = rs["timber_miss_vol"]
    sector["truck_discrepancy"] = rs["truck_discrepancy"]
    sector["rejected_gps"] = rs["rejected_gps"]

    # Parse boundary_json for frontend
    if sector.get("boundary_json"):
        try:
            sector["boundary"] = json.loads(sector["boundary_json"])
        except Exception:
            sector["boundary"] = None

    # Vehicles with fuel stats
    vehicles = db("SELECT * FROM sector_vehicles WHERE sector=? ORDER BY plate", (name,))
    for v in vehicles:
        v["fuel_logs"] = db("SELECT * FROM vehicle_fuel_logs WHERE vehicle_id=? ORDER BY id DESC LIMIT 10", (v["id"],))
        v["total_fuel_added"] = db1("SELECT COALESCE(SUM(fuel_added_l),0) AS s FROM vehicle_fuel_logs WHERE vehicle_id=?", (v["id"],)).get("s", 0)
        v["total_discrepancy"] = db1("SELECT COALESCE(SUM(discrepancy_l),0) AS s FROM vehicle_fuel_logs WHERE vehicle_id=?", (v["id"],)).get("s", 0)

    # Snapshots with their manually-linked risks
    from database import get_snapshot_risks as _get_snapshot_risks
    snapshots = db("SELECT * FROM sector_snapshots WHERE sector=? ORDER BY snapshot_date, id", (name,))
    for sn in snapshots:
        sn["risks"] = _get_snapshot_risks(sn["id"])

    return {
        "sector":           sector,
        "risks":            db("SELECT * FROM risks WHERE sector=? ORDER BY CASE risk_level WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END, id DESC", (name,)),
        "truck_reports":    db("SELECT * FROM truck_reports WHERE sector=? ORDER BY id DESC", (name,)),
        "timber_movements": db("SELECT * FROM timber_movements WHERE sector=? ORDER BY id DESC", (name,)),
        "gps_sessions":     db("SELECT * FROM work_sessions WHERE sector=? ORDER BY id DESC", (name,)),
        "photos":           db("SELECT * FROM work_photos WHERE sector=? ORDER BY id DESC", (name,)),
        "comments":         db("SELECT id, employee, sector, comment, check_in_time FROM work_sessions WHERE sector=? AND comment != '' AND comment IS NOT NULL ORDER BY id DESC", (name,)),
        "employees":        db("SELECT * FROM sector_employees WHERE sector=? ORDER BY full_name", (name,)),
        "vehicles":         vehicles,
        "snapshots":        snapshots,
    }


# ── Risks ─────────────────────────────────────────────────────────────────────

@app.get("/api/risks")
def get_risks():
    return db("SELECT * FROM risks ORDER BY CASE risk_level WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END, id DESC")

@app.get("/api/risks/by-sector")
def risks_by_sector():
    sectors = db("SELECT name FROM sectors ORDER BY name")
    result = []
    for s in sectors:
        result.append({
            "sector": s["name"],
            "high":   n("SELECT COUNT(*) AS n FROM risks WHERE sector=? AND risk_level='HIGH'", (s["name"],)),
            "medium": n("SELECT COUNT(*) AS n FROM risks WHERE sector=? AND risk_level='MEDIUM'", (s["name"],)),
            "low":    n("SELECT COUNT(*) AS n FROM risks WHERE sector=? AND risk_level='LOW'", (s["name"],)),
        })
    return result


# ── Incidents & Equipment (read-only) ──────────────────────────────────────────

@app.get("/api/incidents")
def get_incidents_route(status: str = None):
    return get_incidents(status)

@app.get("/api/equipment")
def get_equipment_route(sector: str = None):
    return get_equipment(sector)

@app.post("/api/incidents/{incident_id}/approve")
def approve_incident(incident_id: int, username: str = Depends(verify_credentials)):
    incident = db1("SELECT * FROM risks WHERE id=?", (incident_id,))
    if not incident or not incident.get("entity_type"):
        return Response(content='{"error":"Not an incident"}', media_type="application/json", status_code=400)

    employee = db1("SELECT telegram_user_id, full_name FROM sector_employees WHERE id=?", (incident["entity_id"],))
    telegram_user_id = employee.get("telegram_user_id") if employee else None
    if not telegram_user_id:
        return Response(content='{"error":"Employee not linked to Telegram"}', media_type="application/json", status_code=400)

    text = (
        f"🚨 FOREST AI — ACTION REQUIRED\n\n"
        f"Risk: {incident['reason']}\n"
        f"Sector: {incident['sector']}\nPriority: {incident['risk_level']}\n\n"
        f"{incident.get('ai_recommendation') or ''}"
    )
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": telegram_user_id,
            "text": text,
            "reply_markup": {"inline_keyboard": [[
                {"text": "✓ I HAVE RETURNED", "callback_data": f"confirm_return:{incident_id}"}
            ]]},
        },
        timeout=10,
    )
    tg_data = tg_response.json()
    if not tg_data.get("ok"):
        return Response(content=f'{{"error":"Telegram send failed: {tg_data.get("description","")}"}}', media_type="application/json", status_code=502)

    message_id = str(tg_data["result"]["message_id"])
    update_incident_status(incident_id, "NOTIFIED", telegram_message_id=message_id)
    add_risk_event(incident_id, "APPROVED", actor=username)
    add_risk_event(incident_id, "TELEGRAM_SENT", actor="system")

    return {"ok": True, "status": "NOTIFIED"}


# ── GPS ───────────────────────────────────────────────────────────────────────

@app.get("/api/gps")
def get_gps():
    return db("SELECT * FROM work_sessions ORDER BY id DESC LIMIT 200")

@app.get("/api/gps/activity")
def gps_activity():
    rows = db("""
        SELECT DATE(REPLACE(check_in_time, ' UTC', '')) as date, COUNT(*) as count
        FROM work_sessions
        WHERE check_in_time != ''
        GROUP BY DATE(REPLACE(check_in_time, ' UTC', ''))
        ORDER BY date DESC LIMIT 30
    """)
    return rows


# ── Timber ────────────────────────────────────────────────────────────────────

@app.get("/api/timber")
def get_timber():
    return db("SELECT * FROM timber_movements ORDER BY id DESC LIMIT 200")

@app.get("/api/timber/volume-by-sector")
def timber_volume():
    return db("""
        SELECT sector,
               COALESCE(SUM(actual_volume), 0) as actual,
               COALESCE(SUM(planned_volume), 0) as planned
        FROM timber_movements
        GROUP BY sector
        ORDER BY actual DESC
    """)


# ── Trucks ────────────────────────────────────────────────────────────────────

@app.get("/api/trucks")
def get_trucks():
    return db("SELECT * FROM truck_reports ORDER BY id DESC LIMIT 200")


# ── Photos ────────────────────────────────────────────────────────────────────

@app.get("/api/photos")
def get_photos(sector: str = None, photo_type: str = None):
    sql = "SELECT * FROM work_photos WHERE 1=1"
    params = []
    if sector:
        sql += " AND sector=?"
        params.append(sector)
    if photo_type:
        sql += " AND photo_type=?"
        params.append(photo_type)
    sql += " ORDER BY id DESC LIMIT 300"
    rows = db(sql, tuple(params))
    for r in rows:
        if r.get("image_path"):
            r["filename"] = Path(r["image_path"]).name
    return rows


# ── Map data ──────────────────────────────────────────────────────────────────

@app.get("/api/map")
def get_map_data():
    sectors = db("SELECT * FROM sectors")
    result = []
    for s in sectors:
        rs = calc_risk_score(s["name"])
        # Use sector center if available, else fall back to last GPS
        lat = s.get("center_lat")
        lon = s.get("center_lon")
        if not lat or not lon:
            gps = db1("SELECT latitude, longitude FROM work_sessions WHERE sector=? AND latitude IS NOT NULL ORDER BY id DESC LIMIT 1", (s["name"],))
            lat = gps.get("latitude")
            lon = gps.get("longitude")
        boundary = None
        if s.get("boundary_json"):
            try:
                boundary = json.loads(s["boundary_json"])
            except Exception:
                pass
        result.append({
            "name":        s["name"],
            "contractor":  s.get("contractor", ""),
            "status":      s.get("status", ""),
            "approved_volume": s.get("approved_volume", ""),
            "risk_score":  rs["score"],
            "risk_color":  rs["color"],
            "risk_level":  rs["level"],
            "latitude":    lat,
            "longitude":   lon,
            "boundary":    boundary,
            "color":       s.get("color") or "red",
            "area_ha":     s.get("area_ha"),
        })
    return result


# ── PDF Report ────────────────────────────────────────────────────────────────

@app.get("/api/report/pdf/{sector_name}")
def generate_pdf(sector_name: str):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        return Response(
            content='{"error":"reportlab not installed. Run: pip3 install reportlab --break-system-packages"}',
            media_type="application/json",
            status_code=500
        )

    data = get_sector_detail(sector_name)
    if "error" in data:
        return Response(content='{"error":"Sector not found"}', media_type="application/json", status_code=404)

    sector = data["sector"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    GREEN  = colors.HexColor("#1D9E75")
    DARK   = colors.HexColor("#0e1208")
    LGRAY  = colors.HexColor("#f5f5f0")
    RED    = colors.HexColor("#c94040")
    AMBER  = colors.HexColor("#d4a017")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", fontSize=22, textColor=DARK, spaceAfter=4, fontName="Helvetica-Bold")
    h2_style    = ParagraphStyle("h2", fontSize=14, textColor=GREEN, spaceAfter=6, spaceBefore=16, fontName="Helvetica-Bold")
    body_style  = ParagraphStyle("body", fontSize=10, textColor=DARK, spaceAfter=4, fontName="Helvetica")
    small_style = ParagraphStyle("small", fontSize=9, textColor=colors.gray, fontName="Helvetica")

    story = []

    # Header
    story.append(Paragraph("Forest AI", ParagraphStyle("logo", fontSize=11, textColor=GREEN, fontName="Helvetica-Bold")))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(f"Sector Report — {sector_name}", title_style))
    story.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", small_style))
    story.append(HRFlowable(width="100%", thickness=1, color=GREEN, spaceAfter=12))

    # Sector Info
    rs = calc_risk_score(sector_name)
    risk_color = RED if rs["color"] == "red" else (AMBER if rs["color"] == "yellow" else GREEN)
    info_data = [
        ["Sector ID", sector.get("name", ""), "Contractor", sector.get("contractor", "—")],
        ["Status", sector.get("status", "—"), "Approved Volume", sector.get("approved_volume", "—")],
        ["Risk Score", str(rs["score"]) + "/100", "Risk Level", rs["level"]],
    ]
    t = Table(info_data, colWidths=[3.5*cm, 5*cm, 3.5*cm, 5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), LGRAY), ("BACKGROUND", (2,0), (2,-1), LGRAY),
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"), ("FONTSIZE", (0,0), (-1,-1), 9),
        ("GRID", (0,0), (-1,-1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.white, colors.HexColor("#fafaf8")]),
        ("PADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(t)

    def section_table(title, headers, rows, col_widths=None):
        story.append(Paragraph(title, h2_style))
        if not rows:
            story.append(Paragraph("No records.", body_style))
            return
        data = [headers] + [[str(r.get(k, "—") or "—") for k in [h.lower().replace(" ","_") for h in headers]] for r in rows]
        tbl = Table(data, colWidths=col_widths)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), GREEN),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LGRAY]),
            ("GRID", (0,0), (-1,-1), 0.3, colors.lightgrey),
            ("PADDING", (0,0), (-1,-1), 5),
        ]))
        story.append(tbl)

    # GPS
    gps_rows = []
    for g in data["gps_sessions"]:
        gps_rows.append({
            "employee": g.get("employee",""), "check_in_time": str(g.get("check_in_time",""))[:16],
            "distance_m": str(round(g.get("distance_m") or 0)), "approved": g.get("approved",""),
        })
    story.append(Paragraph("GPS Sessions", h2_style))
    if gps_rows:
        d = [["Employee","Check-in","Distance m","Approved"]] + [[r["employee"],r["check_in_time"],r["distance_m"],r["approved"]] for r in gps_rows]
        t = Table(d, colWidths=[5*cm, 5*cm, 3*cm, 4*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),GREEN),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LGRAY]),
            ("GRID",(0,0),(-1,-1),0.3,colors.lightgrey),("PADDING",(0,0),(-1,-1),5),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No GPS sessions.", body_style))

    # Risks
    story.append(Paragraph("Risks", h2_style))
    if data["risks"]:
        d = [["Level","Reason"]] + [[r.get("risk_level",""), r.get("reason","")] for r in data["risks"]]
        t = Table(d, colWidths=[3*cm, 14*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),GREEN),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LGRAY]),
            ("GRID",(0,0),(-1,-1),0.3,colors.lightgrey),("PADDING",(0,0),(-1,-1),5),
            ("WORDWRAP",(1,1),(-1,-1),True),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No risks.", body_style))

    # Timber
    story.append(Paragraph("Timber Movements", h2_style))
    if data["timber_movements"]:
        d = [["Planned m³","Actual m³","Diff m³","Status","Note"]] + [
            [str(r.get("planned_volume","")),str(r.get("actual_volume","")),str(r.get("difference_volume","")),r.get("status",""),str(r.get("note",""))[:40]]
            for r in data["timber_movements"]
        ]
        t = Table(d, colWidths=[3*cm,3*cm,3*cm,3.5*cm,4.5*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),GREEN),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LGRAY]),
            ("GRID",(0,0),(-1,-1),0.3,colors.lightgrey),("PADDING",(0,0),(-1,-1),5),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No timber movements.", body_style))

    # Truck Reports
    story.append(Paragraph("Truck Reports", h2_style))
    if data["truck_reports"]:
        d = [["Truck","Driver","Volume m³","Note"]] + [
            [r.get("truck_number",""),r.get("driver",""),str(r.get("reported_volume","")),str(r.get("note",""))[:40]]
            for r in data["truck_reports"]
        ]
        t = Table(d, colWidths=[4*cm,4*cm,3*cm,6*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),GREEN),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LGRAY]),
            ("GRID",(0,0),(-1,-1),0.3,colors.lightgrey),("PADDING",(0,0),(-1,-1),5),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No truck reports.", body_style))

    # Comments
    story.append(Paragraph("Comments", h2_style))
    if data["comments"]:
        for c in data["comments"]:
            story.append(Paragraph(f"<b>{c.get('employee','')}</b> — {str(c.get('check_in_time',''))[:16]}", small_style))
            story.append(Paragraph(c.get("comment",""), body_style))
            story.append(Spacer(1, 0.2*cm))
    else:
        story.append(Paragraph("No comments.", body_style))

    # Photos list
    story.append(Paragraph("Photos", h2_style))
    if data["photos"]:
        story.append(Paragraph(f"{len(data['photos'])} photos uploaded. View in Forest AI dashboard.", body_style))
    else:
        story.append(Paragraph("No photos.", body_style))

    # Footer
    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Paragraph(f"Forest AI Platform · forestai.lv · Confidential", small_style))

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=forest_ai_{sector_name}_{datetime.utcnow().strftime('%Y%m%d')}.pdf"}
    )


# ── Satellite Monitor ─────────────────────────────────────────────────────────

SENTINEL_CLIENT_ID     = os.environ.get("SENTINEL_CLIENT_ID")
SENTINEL_CLIENT_SECRET = os.environ.get("SENTINEL_CLIENT_SECRET")
SENTINEL_TOKEN_URL     = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SENTINEL_API_URL       = "https://sh.dataspace.copernicus.eu/api/v1/process"

import urllib.request
import urllib.parse
import json as _json
import time as _time

_token_cache = {"token": None, "expires": 0}

def get_sentinel_token():
    if _token_cache["token"] and _time.time() < _token_cache["expires"]:
        return _token_cache["token"]
    data = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     SENTINEL_CLIENT_ID,
        "client_secret": SENTINEL_CLIENT_SECRET,
    }).encode()
    req = urllib.request.Request(SENTINEL_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = _json.loads(r.read())
            _token_cache["token"]   = resp["access_token"]
            _token_cache["expires"] = _time.time() + resp.get("expires_in", 3600) - 60
            return _token_cache["token"]
    except Exception as e:
        return None


def query_sentinel_ndvi(bbox, date_from, date_to):
    """Query Sentinel-2 NDVI statistics for a bounding box and date range."""
    token = get_sentinel_token()
    if not token:
        return None

    evalscript = """
//VERSION=3
function setup() {
  return { input: [{ bands: ["B04", "B08", "dataMask"] }], output: { bands: 1 } };
}
function evaluatePixel(sample) {
  if (sample.dataMask === 0) return [NaN];
  let ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04);
  return [ndvi];
}
"""

    payload = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {"from": date_from + "T00:00:00Z", "to": date_to + "T23:59:59Z"},
                    "maxCloudCoverage": 30
                }
            }]
        },
        "evalscript": evalscript,
        "output": {
            "width":  512,
            "height": 512,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}]
        }
    }

    data = _json.dumps(payload).encode()
    req = urllib.request.Request(SENTINEL_API_URL, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except Exception as e:
        return None


@app.get("/api/satellite/token-check")
def satellite_token_check():
    token = get_sentinel_token()
    return {"connected": token is not None, "client_id": (SENTINEL_CLIENT_ID or "")[:20] + "..."}


@app.get("/api/satellite/sectors")
def satellite_sectors():
    """Return satellite analysis summary for all sectors."""
    sectors = db("SELECT name, contractor, status, center_lat, center_lon, boundary_json, area_ha FROM sectors")
    result = []
    for s in sectors:
        rs = calc_risk_score(s["name"])
        lat = s.get("center_lat")
        lon = s.get("center_lon")
        if not lat or not lon:
            gps = db1("SELECT latitude, longitude FROM work_sessions WHERE sector=? AND latitude IS NOT NULL ORDER BY id DESC LIMIT 1", (s["name"],))
            lat = gps.get("latitude", 56.95)
            lon = gps.get("longitude", 24.11)
        boundary = None
        bbox = [lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05]
        if s.get("boundary_json"):
            try:
                boundary = json.loads(s["boundary_json"])
                # Tight bbox from boundary
                lats = [p[0] for p in boundary]
                lons = [p[1] for p in boundary]
                bbox = [min(lons), min(lats), max(lons), max(lats)]
            except Exception:
                pass
        result.append({
            "name":       s["name"],
            "contractor": s.get("contractor", ""),
            "status":     s.get("status", ""),
            "risk_score": rs["score"],
            "risk_color": rs["color"],
            "risk_level": rs["level"],
            "exposure_label": rs["exposure_label"],
            "latitude":   lat,
            "longitude":  lon,
            "bbox":       bbox,
            "boundary":   boundary,
            "area_ha":    s.get("area_ha"),
        })
    return result


@app.get("/api/satellite/image/{sector_name}")
def satellite_image(sector_name: str, date_from: str = "2024-06-01", date_to: str = "2024-06-30"):
    """Fetch Sentinel-2 true color image for a sector."""
    token = get_sentinel_token()
    if not token:
        return Response(content='{"error":"Cannot get Sentinel token"}', media_type="application/json", status_code=500)

    sector_row = db1("SELECT center_lat, center_lon, boundary_json FROM sectors WHERE name=?", (sector_name,))
    lat = sector_row.get("center_lat")
    lon = sector_row.get("center_lon")
    if not lat or not lon:
        gps = db1("SELECT latitude, longitude FROM work_sessions WHERE sector=? AND latitude IS NOT NULL ORDER BY id DESC LIMIT 1", (sector_name,))
        lat = gps.get("latitude", 56.95)
        lon = gps.get("longitude", 24.11)
    bbox = [lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05]
    if sector_row.get("boundary_json"):
        try:
            pts = json.loads(sector_row["boundary_json"])
            lats = [p[0] for p in pts]
            lons = [p[1] for p in pts]
            pad = 0.01
            bbox = [min(lons)-pad, min(lats)-pad, max(lons)+pad, max(lats)+pad]
        except Exception:
            pass

    evalscript = """
//VERSION=3
function setup() {
  return { input: [{ bands: ["B04","B03","B02"] }], output: { bands: 3, sampleType: "AUTO" } };
}
function evaluatePixel(sample) {
  return [2.5*sample.B04, 2.5*sample.B03, 2.5*sample.B02];
}
"""
    payload = {
        "input": {
            "bounds": {"bbox": bbox, "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {
                "timeRange": {"from": date_from + "T00:00:00Z", "to": date_to + "T23:59:59Z"},
                "maxCloudCoverage": 50
            }}]
        },
        "evalscript": evalscript,
        "output": {"width": 512, "height": 512, "responses": [{"identifier": "default", "format": {"type": "image/jpeg"}}]}
    }

    data = _json.dumps(payload).encode()
    req = urllib.request.Request(SENTINEL_API_URL, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            img_data = r.read()
            return Response(content=img_data, media_type="image/jpeg")
    except Exception as e:
        return Response(content=f'{{"error":"{str(e)}"}}', media_type="application/json", status_code=500)


@app.get("/api/satellite/object/{plan_id}")
def satellite_object(plan_id: int, date_from: str = "2024-06-01", date_to: str = "2024-06-30"):
    """Fetch a single Sentinel-2 true color image covering ALL sectors that
    belong to this object/plan, for a whole-object satellite view (as
    opposed to per-sector satellite images, which already exist)."""
    token = get_sentinel_token()
    if not token:
        return Response(content='{"error":"Cannot get Sentinel token"}', media_type="application/json", status_code=500)

    sectors = db("SELECT boundary_json FROM sectors WHERE boundary_plan_id=?", (plan_id,))
    all_lats, all_lons = [], []
    for s in sectors:
        if s.get("boundary_json"):
            try:
                pts = json.loads(s["boundary_json"])
                all_lats += [p[0] for p in pts]
                all_lons += [p[1] for p in pts]
            except Exception:
                pass
    if not all_lats:
        return Response(content='{"error":"No sector boundaries found for this object"}',
                        media_type="application/json", status_code=404)

    pad = 0.01
    bbox = [min(all_lons) - pad, min(all_lats) - pad, max(all_lons) + pad, max(all_lats) + pad]

    evalscript = """
//VERSION=3
function setup() {
  return { input: [{ bands: ["B04","B03","B02"] }], output: { bands: 3, sampleType: "AUTO" } };
}
function evaluatePixel(sample) {
  return [2.5*sample.B04, 2.5*sample.B03, 2.5*sample.B02];
}
"""
    payload = {
        "input": {
            "bounds": {"bbox": bbox, "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {
                "timeRange": {"from": date_from + "T00:00:00Z", "to": date_to + "T23:59:59Z"},
                "maxCloudCoverage": 50
            }}]
        },
        "evalscript": evalscript,
        "output": {"width": 512, "height": 512, "responses": [{"identifier": "default", "format": {"type": "image/jpeg"}}]}
    }
    data = _json.dumps(payload).encode()
    req = urllib.request.Request(SENTINEL_API_URL, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            img_data = r.read()
            return Response(content=img_data, media_type="image/jpeg")
    except Exception as e:
        return Response(content=f'{{"error":"{str(e)}"}}', media_type="application/json", status_code=500)


@app.get("/api/satellite/ndvi/{sector_name}")
def satellite_ndvi(sector_name: str, date_from: str = "2024-06-01", date_to: str = "2024-06-30"):
    """Fetch Sentinel-2 NDVI (vegetation index) image."""
    token = get_sentinel_token()
    if not token:
        return Response(content='{"error":"Cannot get Sentinel token"}', media_type="application/json", status_code=500)

    sector_row = db1("SELECT center_lat, center_lon, boundary_json FROM sectors WHERE name=?", (sector_name,))
    lat = sector_row.get("center_lat")
    lon = sector_row.get("center_lon")
    if not lat or not lon:
        gps = db1("SELECT latitude, longitude FROM work_sessions WHERE sector=? AND latitude IS NOT NULL ORDER BY id DESC LIMIT 1", (sector_name,))
        lat = gps.get("latitude", 56.95)
        lon = gps.get("longitude", 24.11)
    bbox = [lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05]
    if sector_row.get("boundary_json"):
        try:
            pts = json.loads(sector_row["boundary_json"])
            lats = [p[0] for p in pts]
            lons = [p[1] for p in pts]
            pad = 0.01
            bbox = [min(lons)-pad, min(lats)-pad, max(lons)+pad, max(lats)+pad]
        except Exception:
            pass

    evalscript = """
//VERSION=3
function setup() {
  return { input: [{ bands: ["B04","B08","dataMask"] }], output: { bands: 3, sampleType: "AUTO" } };
}
function evaluatePixel(sample) {
  if (sample.dataMask === 0) return [0.1, 0.1, 0.1];
  let ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04 + 0.0001);
  if (ndvi < 0) return [0.8, 0.2, 0.2];
  if (ndvi < 0.2) return [0.9, 0.7, 0.2];
  if (ndvi < 0.4) return [0.6, 0.9, 0.3];
  return [0.1, 0.6, 0.1];
}
"""
    payload = {
        "input": {
            "bounds": {"bbox": bbox, "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {
                "timeRange": {"from": date_from + "T00:00:00Z", "to": date_to + "T23:59:59Z"},
                "maxCloudCoverage": 50
            }}]
        },
        "evalscript": evalscript,
        "output": {"width": 512, "height": 512, "responses": [{"identifier": "default", "format": {"type": "image/jpeg"}}]}
    }

    data = _json.dumps(payload).encode()
    req = urllib.request.Request(SENTINEL_API_URL, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            img_data = r.read()
            return Response(content=img_data, media_type="image/jpeg")
    except Exception as e:
        return Response(content=f'{{"error":"{str(e)}"}}', media_type="application/json", status_code=500)
