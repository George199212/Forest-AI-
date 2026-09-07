import math
import csv
import json
import os
import zipfile
import sqlite3
import re
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ApplicationHandlerStop
from database import init_db, add_sector, get_sectors, add_risk, get_risks, parse_boundary, calc_centroid, calc_area_ha, add_incident, add_risk_event, set_ai_recommendation, get_risk_by_telegram_message_id
from services.robez_ocr_vision import analyze_robez_plan_ocr_vision
from services.ai_resolution import generate_incident_recommendation

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
DB_NAME = os.environ.get("DB_PATH", "data/forest_ai.db")
PHOTOS_DIR = Path("data/work_photos")
EXPORT_DIR = Path("data/exports")
PLANS_DIR  = Path("data/boundary_plans")
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
PLANS_DIR.mkdir(parents=True, exist_ok=True)


# ── DB helpers ────────────────────────────────────────────────────────────────

def db_execute(sql, params=()):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def db_fetchone(sql, params=()):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return row

def db_fetchall(sql, params=()):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows

def init_work_tables():
    """Table creation now lives in database.init_db() so api.py can bring up
    a fresh DB without depending on the bot having run first. Kept as a thin
    delegate since main() still calls it."""
    init_db()


# ── Geo ───────────────────────────────────────────────────────────────────────

def point_in_polygon(lat, lon, polygon):
    """
    Ray casting algorithm.
    polygon: list of [lat, lon] pairs.
    Returns True if point is inside polygon.
    """
    x, y = lon, lat
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][1], polygon[i][0]
        xj, yj = polygon[j][1], polygon[j][0]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

def calculate_distance_meters(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_sector_from_db(name):
    """Return sector row as dict."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM sectors WHERE name=?", (name,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# ── Keyboards ─────────────────────────────────────────────────────────────────

# ── Tesseract OCR — Robežu Plāns Analysis ────────────────────────────────────

def analyze_robez_plan_ocr(image_path: str) -> dict:
    """
    Extract coordinates from robežu plāns using Tesseract OCR.
    Parses LKS-92 coordinate tables and converts to WGS84.
    """
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        return {"error": "pytesseract or Pillow not installed"}

    try:
        img = Image.open(image_path)

        # Enhance image for better OCR
        img = img.convert("L")  # grayscale
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        img = img.filter(ImageFilter.SHARPEN)

        # OCR with Latvian + English
        text = pytesseract.image_to_string(img, lang="lav+eng", config="--psm 6")

    except Exception as e:
        return {"error": f"OCR failed: {str(e)}"}

    # ── Parse coordinate table ─────────────────────────────────────────────
    raw_points = []
    lines = text.split("\n")

    # Look for patterns like: "Atm-1  310280  504908" or "1  310280.10  504908.82"
    coord_pattern = re.compile(
        r"([A-Za-z]*[\-]?\d+)\s+(\d{5,7}[\.,]?\d*)\s+(\d{5,7}[\.,]?\d*)"
    )
    # Also try just two big numbers on a line
    two_nums = re.compile(r"(\d{5,7}[\.,]\d{1,3})\s+(\d{5,7}[\.,]\d{1,3})")

    for line in lines:
        line = line.strip()
        m = coord_pattern.search(line)
        if m:
            name = m.group(1)
            try:
                x = float(m.group(2).replace(",", "."))
                y = float(m.group(3).replace(",", "."))
                # Validate LKS-92 range
                if 200000 < x < 800000 and 200000 < y < 800000:
                    lat, lon = lks92_to_wgs84(x, y)
                    raw_points.append({"name": name, "x": x, "y": y, "lat": lat, "lon": lon})
            except ValueError:
                pass
        else:
            m2 = two_nums.search(line)
            if m2:
                try:
                    x = float(m2.group(1).replace(",", "."))
                    y = float(m2.group(2).replace(",", "."))
                    if 200000 < x < 800000 and 200000 < y < 800000:
                        lat, lon = lks92_to_wgs84(x, y)
                        raw_points.append({"name": f"P{len(raw_points)+1}", "x": x, "y": y, "lat": lat, "lon": lon})
                except ValueError:
                    pass

    # ── Extract area ───────────────────────────────────────────────────────
    area_match = re.search(r"(\d+[\.,]\d+)\s*ha", text, re.IGNORECASE)
    total_ha = float(area_match.group(1).replace(",", ".")) if area_match else 0.0

    # ── Extract title ──────────────────────────────────────────────────────
    title_lines = [l.strip() for l in lines[:8] if len(l.strip()) > 5]
    plan_title = " ".join(title_lines[:2]) if title_lines else "Robežu Plāns"

    # ── Build proposed sectors ─────────────────────────────────────────────
    proposed_sectors = []

    if len(raw_points) >= 4:
        # Use all points as one sector boundary
        boundary = [[p["lat"], p["lon"]] for p in raw_points]
        # Close polygon
        if boundary[0] != boundary[-1]:
            boundary.append(boundary[0])

        clat, clon = calc_centroid([[p["lat"], p["lon"]] for p in raw_points])
        area = calc_area_ha([[p["lat"], p["lon"]] for p in raw_points])

        proposed_sectors.append({
            "suggested_name": "S-001",
            "description": f"Main boundary from plan ({len(raw_points)} points)",
            "area_ha": area or total_ha,
            "boundary": boundary
        })

        # If many points — try splitting into 2 sectors (first half / second half)
        if len(raw_points) >= 8:
            mid = len(raw_points) // 2
            b1 = [[p["lat"], p["lon"]] for p in raw_points[:mid+1]]
            b2 = [[p["lat"], p["lon"]] for p in raw_points[mid:]]
            if len(b1) >= 4 and len(b2) >= 4:
                proposed_sectors.append({
                    "suggested_name": "S-002",
                    "description": f"Sub-sector A (points 1-{mid+1})",
                    "area_ha": round(area/2, 2) if area else 0,
                    "boundary": b1
                })
                proposed_sectors.append({
                    "suggested_name": "S-003",
                    "description": f"Sub-sector B (points {mid+1}-{len(raw_points)})",
                    "area_ha": round(area/2, 2) if area else 0,
                    "boundary": b2
                })

    notes = f"OCR extracted {len(raw_points)} coordinate points from plan. "
    if len(raw_points) == 0:
        notes += "No coordinates found — plan may be unclear or in unsupported format. Try better lighting."
    elif len(raw_points) < 4:
        notes += f"Only {len(raw_points)} points found — need minimum 4 for polygon."

    return {
        "plan_title": plan_title[:100],
        "coordinate_system": "LKS-92 → WGS84",
        "total_area_ha": total_ha,
        "raw_points": raw_points,
        "proposed_sectors": proposed_sectors,
        "notes": notes,
        "ocr_text_preview": text[:300]
    }


def lks92_to_wgs84(x: float, y: float):
    """
    Approximate LKS-92 (EPSG:3059) to WGS84 conversion for Latvia.
    X = northing (up), Y = easting (right)
    Accurate to ~100m — good enough for sector planning.
    """
    # LKS-92 origin offsets for Latvia
    lat = (x - 310000) / 111320 + 56.5
    lon = (y - 300000) / 74500  + 24.0
    return round(lat, 6), round(lon, 6)


def save_plan_to_db(plan_data: dict, file_path: str, user_id: str) -> int:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO boundary_plans (file_path, document_type, uploaded_at, status, uploaded_by, plan_data_json)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (file_path, "robez_plans", now, "draft_created", user_id, json.dumps(plan_data)))
    plan_id = cur.lastrowid
    for pt in plan_data.get("raw_points", []):
        cur.execute("""
        INSERT INTO boundary_plan_points (plan_id, point_name, x_coord, y_coord, lat, lon, raw_text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (plan_id, pt.get("name",""), pt.get("x",0), pt.get("y",0),
              pt.get("lat",0), pt.get("lon",0), json.dumps(pt)))
    conn.commit()
    conn.close()
    return plan_id


def init_plan_tables():
    """Table creation now lives in database.init_db(). Kept as a thin
    delegate since main() still calls it."""
    init_db()


def get_plan_object_name(plan_id: int) -> str:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT object_name FROM boundary_plans WHERE id=?", (plan_id,))
    row = cur.fetchone()
    conn.close()
    return (row[0] if row and row[0] else "")


def set_plan_object_name(plan_id: int, object_name: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE boundary_plans SET object_name=? WHERE id=?", (object_name, plan_id))
    conn.commit()
    conn.close()


# ── Robežu Plāns Bot Handlers ─────────────────────────────────────────────────

async def ask_robez_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_robez_plan"] = True
    await update.message.reply_text(
        "📄 Robežu Plāns — OCR анализ\n\n"
        "📸 Сфотографируй план и отправь фото.\n\n"
        "Система извлечёт:\n"
        "• Координаты точек (LKS-92)\n"
        "• Конвертирует в WGS84\n"
        "• Предложит разбивку на сектора\n\n"
        "⚠️ Для лучшего результата:\n"
        "• Координатная таблица должна быть чётко видна\n"
        "• Хорошее освещение, без бликов\n"
        "• Весь план в кадре\n\n"
        "Отправь фото 👇",
        reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
    )

async def handle_robez_plan_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    await update.message.reply_text(
        "🔍 OCR анализ...\n\nТесseract читает координаты из плана. 5-15 секунд.",
        reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
    )

    photo = update.message.photo[-1]
    file = await photo.get_file()
    image_path = PLANS_DIR / f"plan_{user_id}_{timestamp}.jpg"
    await file.download_to_drive(str(image_path))

    # Run OCR in thread (blocking)
    import asyncio
    loop = asyncio.get_event_loop()
    plan_data = await loop.run_in_executor(None, analyze_robez_plan_ocr_vision, str(image_path))

    context.user_data.pop("waiting_robez_plan", None)

    if "error" in plan_data:
        await update.message.reply_text(
            f"⚠️ OCR не удался:\n{plan_data['error']}\n\n"
            "Попробуй лучше освещение или введи координаты вручную.",
            reply_markup=main_keyboard()
        )
        return

    plan_id = save_plan_to_db(plan_data, str(image_path), user_id)
    context.user_data["pending_plan_id"] = plan_id
    context.user_data["pending_plan_data"] = plan_data

    sectors = plan_data.get("proposed_sectors", [])
    points_count = len(plan_data.get("raw_points", []))
    total_ha = plan_data.get("total_area_ha", 0)
    notes = plan_data.get("notes", "")

    msg = (
        f"✅ OCR анализ завершён\n\n"
        f"📋 {plan_data.get('plan_title','Robežu Plāns')[:60]}\n"
        f"📍 Точек координат: {points_count}\n"
        f"📐 Площадь: {total_ha} ha\n"
        f"🗂 Предложено секторов: {len(sectors)}\n"
    )

    if notes:
        msg += f"💬 {notes}\n"

    for i, s in enumerate(sectors):
        boundary = s.get("boundary", [])
        msg += (
            f"\n━━━━━━━━━━━━━━━\n"
            f"🌲 {s.get('suggested_name','S-00'+str(i+1))}: {s.get('description','')}\n"
            f"📐 {s.get('area_ha',0)} ha · {len(boundary)} точек\n"
        )

    if points_count == 0:
        msg += (
            "\n⚠️ Координаты не найдены.\n"
            "Убедись что таблица с X/Y координатами видна на фото.\n"
            "Или введи вручную через 🗺 Add Sector Boundary"
        )
        await update.message.reply_text(msg, reply_markup=main_keyboard())
        return

    msg += f"\n━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg)

    # Ask for the object/parcel name before letting the user create sectors,
    # so every sector created from this plan can be grouped together in the
    # dashboard under one object instead of a flat, unlinked list.
    context.user_data["waiting_object_name"] = True
    await update.message.reply_text(
        "🏷 Как назвать этот объект/участок?\n"
        "(например: Mūrnieku Jāņa 0.21ha)\n\n"
        "Это имя будет использовано, чтобы сгруппировать секторы этого плана "
        "в дашборде.",
        reply_markup=ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
    )


def build_plan_action_buttons(plan_id, sectors) -> InlineKeyboardMarkup:
    buttons = []
    if sectors:
        buttons.append([InlineKeyboardButton(
            f"✅ Создать все {len(sectors)} сектора", callback_data=f"plan_approve_all:{plan_id}"
        )])
        for i, s in enumerate(sectors):
            buttons.append([InlineKeyboardButton(
                f"✅ Только {s.get('suggested_name','S-'+str(i+1))}",
                callback_data=f"plan_approve_one:{plan_id}:{i}"
            )])
    buttons.append([InlineKeyboardButton("❌ Отклонить", callback_data=f"plan_reject:{plan_id}")])
    buttons.append([InlineKeyboardButton("📋 Открыть дашборд", url="http://164.90.188.136:8000")])
    return InlineKeyboardMarkup(buttons)


async def handle_object_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    context.user_data.pop("waiting_object_name", None)

    plan_id = context.user_data.get("pending_plan_id")
    plan_data = context.user_data.get("pending_plan_data", {}) or {}

    if text == "❌ Cancel" or not plan_id:
        context.user_data.pop("pending_plan_id", None)
        context.user_data.pop("pending_plan_data", None)
        await update.message.reply_text("Отменено.", reply_markup=main_keyboard())
        return

    object_name = text[:200]
    set_plan_object_name(plan_id, object_name)
    context.user_data["pending_object_name"] = object_name

    sectors = plan_data.get("proposed_sectors", [])
    await update.message.reply_text(
        f"🏷 Объект: {object_name}\n\n━━━━━━━━━━━━━━━\nЧто делаем?",
        reply_markup=build_plan_action_buttons(plan_id, sectors)
    )


async def plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    def load_plan(plan_id):
        pd = context.user_data.get("pending_plan_data")
        if pd:
            return pd
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT plan_data_json FROM boundary_plans WHERE id=?", (plan_id,))
        row = cur.fetchone()
        conn.close()
        return json.loads(row[0]) if row else {}

    if data.startswith("plan_approve_all:"):
        plan_id = int(data.split(":")[1])
        plan_data = load_plan(plan_id)
        sectors = plan_data.get("proposed_sectors", [])
        object_name = get_plan_object_name(plan_id)
        created = []
        for i, s in enumerate(sectors):
            boundary = s.get("boundary", [])
            if len(boundary) >= 4:
                base_name = s.get("suggested_name") or f"S-{plan_id:03d}-{i+1}"
                name = f"{base_name} — {object_name}" if object_name else f"{base_name} (plan #{plan_id})"
                add_sector(name=name, contractor="", status="Draft — needs review",
                           approved_volume="", boundary=boundary, color="orange",
                           boundary_plan_id=plan_id, object_name=object_name,
                           pixel_boundary=s.get("pixel_boundary"))
                created.append(name)
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE boundary_plans SET status='approved' WHERE id=?", (plan_id,))
        conn.commit()
        conn.close()
        context.user_data.pop("pending_plan_data", None)
        await query.message.reply_text(
            f"✅ Создано {len(created)} секторов:\n" + "\n".join(f"• {n}" for n in created) +
            "\n\nСтатус: Draft — needs review (оранжевый на карте)\n"
            "Открой дашборд → Sectors для проверки.\n\n🗺 http://164.90.188.136:8000",
            reply_markup=main_keyboard()
        )

    elif data.startswith("plan_approve_one:"):
        parts = data.split(":")
        plan_id, idx = int(parts[1]), int(parts[2])
        plan_data = load_plan(plan_id)
        sectors = plan_data.get("proposed_sectors", [])
        object_name = get_plan_object_name(plan_id)
        if idx < len(sectors):
            s = sectors[idx]
            boundary = s.get("boundary", [])
            base_name = s.get("suggested_name") or f"S-{plan_id:03d}-{idx+1}"
            name = f"{base_name} — {object_name}" if object_name else f"{base_name} (plan #{plan_id})"
            if len(boundary) >= 4:
                add_sector(name=name, contractor="", status="Draft — needs review",
                           approved_volume="", boundary=boundary, color="orange",
                           boundary_plan_id=plan_id, object_name=object_name,
                           pixel_boundary=s.get("pixel_boundary"))
                await query.message.reply_text(
                    f"✅ Сектор {name} создан\n"
                    f"Площадь: {s.get('area_ha',0)} ha · {len(boundary)} точек\n\n"
                    f"🗺 http://164.90.188.136:8000",
                    reply_markup=main_keyboard()
                )
            else:
                await query.message.reply_text("⚠️ Недостаточно точек для полигона (нужно ≥4).", reply_markup=main_keyboard())

    elif data.startswith("plan_reject:"):
        plan_id = int(data.split(":")[1])
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE boundary_plans SET status='rejected' WHERE id=?", (plan_id,))
        conn.commit()
        conn.close()
        context.user_data.pop("pending_plan_data", None)
        await query.message.reply_text(
            "❌ Отклонено.\nПопробуй снова с лучшим фото или введи координаты вручную:\n🗺 Add Sector Boundary",
            reply_markup=main_keyboard()
        )

def main_keyboard():
    return ReplyKeyboardMarkup([
        ["🌲 Sectors", "⚠️ Risks"],
        ["📍 GPS Check-in", "✅ Finish Work"],
        ["🚛 Vehicle GPS", "🪵 Timber Movement"],
        ["➕ Add Timber", "🚛 Truck Report"],
        ["➕ Add Truck", "➕ Add Sector"],
        ["🗺 Add Sector Boundary", "📄 Robežu Plāns — OCR"],
        ["📊 Report", "📤 Export Report"],
        ["⚙️ Settings"],
    ], resize_keyboard=True)

def work_keyboard():
    return ReplyKeyboardMarkup([
        ["📷 Upload Site Photo"],
        ["🚜 Upload Equipment Photo"],
        ["🪵 Upload Timber Photo"],
        ["📝 Add Comment"],
        ["✅ Finish Work"],
    ], resize_keyboard=True)

def sectors_checkin_keyboard(sectors_list):
    """Build inline keyboard for sector selection at check-in."""
    buttons = []
    for s in sectors_list:
        name = s[0]
        contractor = s[1] or ""
        label = f"{name} — {contractor}" if contractor else name
        buttons.append([InlineKeyboardButton(label, callback_data=f"checkin_sector:{name}")])
    return InlineKeyboardMarkup(buttons)


# ── Export ────────────────────────────────────────────────────────────────────

def write_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

def build_export_zip():
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    export_folder = EXPORT_DIR / f"forest_ai_export_{timestamp}"
    export_folder.mkdir(parents=True, exist_ok=True)

    sessions = db_fetchall("SELECT id,user_id,employee,contractor,sector,check_in_time,finish_time,latitude,longitude,distance_m,approved,comment FROM work_sessions ORDER BY id DESC")
    photos   = db_fetchall("SELECT id,session_id,sector,photo_type,image_path,uploaded_at FROM work_photos ORDER BY id DESC")
    timber   = db_fetchall("SELECT id,sector,planned_volume,actual_volume,difference_volume,status,note,created_at FROM timber_movements ORDER BY id DESC")
    trucks   = db_fetchall("SELECT id,sector,truck_number,driver,reported_volume,note,created_at FROM truck_reports ORDER BY id DESC")
    sectors  = db_fetchall("SELECT name,contractor,status,approved_volume,boundary_json,center_lat,center_lon,area_ha,color,created_at,updated_at FROM sectors")
    risks    = get_risks()

    write_csv(export_folder / "work_sessions.csv",
              ["id","user_id","employee","contractor","sector","check_in_time","finish_time","latitude","longitude","distance_m","approved","comment"],
              sessions)
    write_csv(export_folder / "work_photos.csv",
              ["id","session_id","sector","photo_type","image_path","uploaded_at"], photos)
    write_csv(export_folder / "timber_movements.csv",
              ["id","sector","planned_volume","actual_volume","difference_volume","status","note","created_at"], timber)
    write_csv(export_folder / "truck_reports.csv",
              ["id","sector","truck_number","driver","reported_volume","note","created_at"], trucks)
    write_csv(export_folder / "sectors.csv",
              ["name","contractor","status","approved_volume","boundary_json","center_lat","center_lon","area_ha","color","created_at","updated_at"],
              sectors)
    write_csv(export_folder / "risks.csv", ["sector","risk_level","reason"], risks)

    with open(export_folder / "summary.txt", "w", encoding="utf-8") as f:
        f.write(f"Forest AI Export Report\nGenerated: {timestamp} UTC\n")
        f.write(f"Sectors: {len(sectors)}\nRisks: {len(risks)}\n")
        f.write(f"GPS sessions: {len(sessions)}\nPhotos: {len(photos)}\n")
        f.write(f"Timber movements: {len(timber)}\nTruck reports: {len(trucks)}\n")

    zip_path = EXPORT_DIR / f"forest_ai_report_{timestamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for fp in export_folder.iterdir():
            zipf.write(fp, arcname=fp.name)
    return zip_path


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    employee_row = db_fetchone(
        "SELECT full_name FROM sector_employees WHERE telegram_user_id=?",
        (str(update.effective_user.id),)
    )
    intro = f"🌲 Forest AI\n\nС возвращением, {employee_row[0]}!\n\n" if employee_row \
        else "🌲 Forest AI\n\nAutonomous Forest Oversight Platform\n\n"
    await update.message.reply_text(
        intro +
        "Main modules:\n🌲 Sectors\n⚠️ Risks\n📍 GPS Check-in\n"
        "🪵 Timber Movement\n🚛 Truck Report\n📊 Report\n📤 Export Report",
        reply_markup=main_keyboard()
    )

async def check_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sectors_list = get_sectors()
    if not sectors_list:
        # No sectors — ask location directly for default sector
        keyboard = [[KeyboardButton("📍 Send Location", request_location=True)], ["🌲 Sectors"]]
        await update.message.reply_text(
            "📍 GPS Check-in\n\nNo sectors found. Send location for default check-in.",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        context.user_data["pending_checkin_sector"] = "A-004"
        return

    await update.message.reply_text(
        "📍 GPS Check-in\n\nSelect sector:",
        reply_markup=sectors_checkin_keyboard(sectors_list)
    )

async def sector_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("checkin_sector:"):
        return
    sector_name = query.data.split(":", 1)[1]
    context.user_data["pending_checkin_sector"] = sector_name

    already_linked = db_fetchone(
        "SELECT id FROM sector_employees WHERE telegram_user_id=?",
        (str(update.effective_user.id),)
    )
    if not already_linked:
        candidates = db_fetchall(
            "SELECT id, full_name FROM sector_employees WHERE sector=? AND active=1 "
            "AND (telegram_user_id IS NULL OR telegram_user_id='')",
            (sector_name,)
        )
        if candidates:
            buttons = [[InlineKeyboardButton(name, callback_data=f"linkemp:{eid}")] for eid, name in candidates]
            buttons.append([InlineKeyboardButton("Меня нет в списке", callback_data="linkemp:skip")])
            await query.message.reply_text(
                f"👤 Сектор {sector_name}\n\nЭто вы?",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return

    keyboard = [[KeyboardButton("📍 Send Location", request_location=True)], ["🌲 Sectors"]]
    await query.message.reply_text(
        f"✅ Sector selected: {sector_name}\n\nNow send your GPS location:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )

async def link_employee_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("linkemp:"):
        return
    choice = query.data.split(":", 1)[1]

    if choice == "skip":
        sector_name = context.user_data.get("pending_checkin_sector", "A-004")
        keyboard = [[KeyboardButton("📍 Send Location", request_location=True)], ["🌲 Sectors"]]
        await query.message.reply_text(
            f"✅ Sector selected: {sector_name}\n\nNow send your GPS location:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return

    db_execute(
        "UPDATE sector_employees SET telegram_user_id=? WHERE id=?",
        (str(update.effective_user.id), int(choice))
    )

    keyboard = [[KeyboardButton("📍 Send Location", request_location=True)], ["🌲 Sectors"]]
    await query.message.reply_text(
        "✅ Привязано\n\nNow send your GPS location:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )

async def vehicle_gps_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sectors_list = get_sectors()
    if not sectors_list:
        await update.message.reply_text("🚛 Vehicle GPS\n\nNo sectors found.", reply_markup=main_keyboard())
        return

    buttons = []
    for s in sectors_list:
        name = s[0]
        contractor = s[1] or ""
        label = f"{name} — {contractor}" if contractor else name
        buttons.append([InlineKeyboardButton(label, callback_data=f"vehgps_sector:{name}")])
    await update.message.reply_text(
        "🚛 Vehicle GPS\n\nSelect sector:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def vehicle_sector_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("vehgps_sector:"):
        return
    sector_name = query.data.split(":", 1)[1]

    vehicles = db_fetchall("SELECT id, plate FROM sector_vehicles WHERE sector=? AND active=1", (sector_name,))
    if not vehicles:
        await query.message.reply_text(f"🚛 Vehicle GPS\n\nNo active vehicles in {sector_name}.", reply_markup=main_keyboard())
        return

    context.user_data["pending_vehicle_sector"] = sector_name
    buttons = [[InlineKeyboardButton(plate or f"Vehicle #{vid}", callback_data=f"vehgps_vehicle:{vid}")] for vid, plate in vehicles]
    await query.message.reply_text(
        f"🚛 Vehicle GPS — {sector_name}\n\nSelect vehicle:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def vehicle_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("vehgps_vehicle:"):
        return
    vehicle_id = int(query.data.split(":", 1)[1])
    context.user_data["pending_vehicle_id"] = vehicle_id

    keyboard = [[KeyboardButton("📍 Send Location", request_location=True)], ["🌲 Sectors"]]
    await query.message.reply_text(
        "✅ Vehicle selected\n\nNow send GPS location for this vehicle:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )

def _calc_expiry(started_at: str, live_period: int) -> str:
    started = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S UTC")
    return (started + timedelta(seconds=live_period or 0)).strftime("%Y-%m-%d %H:%M:%S UTC")

def _is_inside_sector(sector, latitude, longitude):
    """Same polygon-or-radius-fallback geo-check handle_location's check-in
    flow uses, reused here so live-location tracking agrees with it."""
    sector_row = get_sector_from_db(sector)
    if sector_row and sector_row.get("boundary_json"):
        try:
            boundary = json.loads(sector_row["boundary_json"])
            return point_in_polygon(latitude, longitude, boundary)
        except Exception:
            return False
    sector_lat = (sector_row.get("center_lat") if sector_row else None) or 56.9587
    sector_lon = (sector_row.get("center_lon") if sector_row else None) or 24.1034
    return calculate_distance_meters(latitude, longitude, sector_lat, sector_lon) <= 10000

def upsert_live_location(employee_id, telegram_user_id, sector, latitude, longitude, live_period):
    """One row per person — UPSERT by telegram_user_id so live-location edits
    (sent every few seconds by Telegram) update the same row instead of
    piling up history. Returns (old_status, new_status) — 'IN'/'OUT' —
    so the caller can detect an IN->OUT transition and alert.
    old_status is None on the very first report (nothing to transition from)."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    new_status = "IN" if _is_inside_sector(sector, latitude, longitude) else "OUT"
    existing = db_fetchone(
        "SELECT id, started_at, live_period, last_status FROM live_locations WHERE telegram_user_id=?",
        (telegram_user_id,)
    )
    if existing:
        row_id, started_at, existing_period, old_status = existing
        period = live_period if live_period is not None else existing_period
        expires_at = _calc_expiry(started_at, period)
        db_execute("""
        UPDATE live_locations SET employee_id=?, sector=?, latitude=?, longitude=?,
            live_period=?, updated_at=?, expires_at=?, last_status=?
        WHERE id=?
        """, (employee_id, sector, latitude, longitude, period, now, expires_at, new_status, row_id))
    else:
        old_status = None
        period = live_period or 0
        expires_at = _calc_expiry(now, period)
        db_execute("""
        INSERT INTO live_locations
            (employee_id, telegram_user_id, sector, latitude, longitude, live_period, started_at, updated_at, expires_at, last_status)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (employee_id, telegram_user_id, sector, latitude, longitude, period, now, now, expires_at, new_status))
    return old_status, new_status

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_edit = update.edited_message is not None
    msg = update.edited_message or update.message
    loc = msg.location

    if is_edit:
        # Live-location update (Telegram edits the original message every
        # few seconds) — only refresh live_locations, never re-run the
        # check-in flow or it would insert a new work_session each time.
        employee_row = db_fetchone(
            "SELECT id, full_name, sector FROM sector_employees WHERE telegram_user_id=?",
            (str(update.effective_user.id),)
        )
        if not employee_row:
            return
        employee_id, employee_name, employee_sector = employee_row
        sector_name = context.user_data.get("pending_checkin_sector") \
            or (context.user_data.get("active_work_session") or {}).get("sector") \
            or employee_sector
        telegram_user_id = str(update.effective_user.id)
        old_status, new_status = upsert_live_location(
            employee_id, telegram_user_id, sector_name,
            loc.latitude, loc.longitude, loc.live_period
        )

        if old_status == "IN" and new_status == "OUT":
            incident_reason = f"Worker {employee_name} left sector boundary"

            existing = db_fetchone(
                "SELECT id FROM risks WHERE entity_type='EMPLOYEE' AND entity_id=? "
                "AND status IN ('OPEN','NOTIFIED') ORDER BY id DESC LIMIT 1",
                (employee_id,)
            )
            if existing:
                incident_id = existing[0]
                add_risk_event(incident_id, "STILL_OUTSIDE", actor="system")
            else:
                incident_id = add_incident(
                    sector_name, "HIGH", incident_reason,
                    entity_type="EMPLOYEE", entity_id=employee_id, rule_code="SECTOR_EXIT"
                )
                add_risk_event(incident_id, "DETECTED", actor="system")

                import asyncio
                loop = asyncio.get_event_loop()
                recommendation = await loop.run_in_executor(
                    None, generate_incident_recommendation,
                    {"sector": sector_name, "reason": incident_reason,
                     "entity_type": "EMPLOYEE", "rule_code": "SECTOR_EXIT"}
                )
                if recommendation:
                    set_ai_recommendation(incident_id, recommendation)
                    add_risk_event(incident_id, "AI_RECOMMENDATION_GENERATED", actor="ai")

            try:
                await context.bot.send_message(
                    chat_id=int(telegram_user_id),
                    text=(
                        "⚠️ Похоже, вы вышли за границу рабочего участка.\n\n"
                        "Пожалуйста, вернитесь в зону сектора. Диспетчер уже уведомлён."
                    )
                )
            except Exception:
                pass  # e.g. user blocked the bot — don't break tracking over it

            dispatcher_chat_id = os.environ.get("DISPATCHER_CHAT_ID", "").strip()
            if dispatcher_chat_id:
                maps_link = f"https://maps.google.com/?q={loc.latitude},{loc.longitude}"
                try:
                    await context.bot.send_message(
                        chat_id=int(dispatcher_chat_id),
                        text=(
                            "🚨 Сотрудник покинул границу сектора\n\n"
                            f"Сотрудник: {employee_name}\n"
                            f"Сектор: {sector_name}\n"
                            f"Координаты: {loc.latitude:.6f}, {loc.longitude:.6f}\n"
                            f"Карта: {maps_link}"
                        )
                    )
                except Exception:
                    pass
            else:
                print("DISPATCHER_CHAT_ID not set — skipping dispatcher alert")
        return

    # ── Vehicle GPS ping (separate flow — does not touch employee check-in) ──
    pending_vehicle_id = context.user_data.get("pending_vehicle_id")
    if pending_vehicle_id is not None:
        sector_name = context.user_data.pop("pending_vehicle_sector", "A-004")
        context.user_data.pop("pending_vehicle_id", None)

        vehicle_row = db_fetchone(
            "SELECT plate FROM sector_vehicles WHERE telegram_user_id=?",
            (str(update.effective_user.id),)
        )
        if not vehicle_row:
            await update.message.reply_text(
                "❌ Вы не зарегистрированы в Forest AI. Обратитесь к администратору.",
                reply_markup=main_keyboard()
            )
            return
        plate = vehicle_row[0]

        recorded_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        sector_row = get_sector_from_db(sector_name)
        inside = 0
        if sector_row and sector_row.get("boundary_json"):
            try:
                boundary = json.loads(sector_row["boundary_json"])
                inside = 1 if point_in_polygon(loc.latitude, loc.longitude, boundary) else 0
            except Exception:
                inside = 0

        db_execute("""
        INSERT INTO vehicle_gps_pings (vehicle_id, sector, latitude, longitude, inside_boundary, recorded_at)
        VALUES (?,?,?,?,?,?)
        """, (pending_vehicle_id, sector_name, loc.latitude, loc.longitude, inside, recorded_at))

        if inside:
            await update.message.reply_text(f"✅ {plate}: GPS recorded — inside sector boundary.", reply_markup=main_keyboard())
        else:
            await update.message.reply_text(f"⚠ {plate}: Вы за пределами границы сектора", reply_markup=main_keyboard())
        return

    sector_name = context.user_data.get("pending_checkin_sector", "A-004")

    employee_row = db_fetchone(
        "SELECT id, full_name FROM sector_employees WHERE telegram_user_id=?",
        (str(update.effective_user.id),)
    )
    if employee_row:
        employee_id, employee = employee_row
    else:
        employee_id, employee = None, update.effective_user.full_name or str(update.effective_user.id)

    checked_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Get sector from DB
    sector_row = get_sector_from_db(sector_name)
    contractor = sector_row.get("contractor", "") if sector_row else ""

    # ── Geo check ─────────────────────────────────────────────────────────────
    approved = False
    distance = None

    if sector_row and sector_row.get("boundary_json"):
        try:
            boundary = json.loads(sector_row["boundary_json"])
            approved = point_in_polygon(loc.latitude, loc.longitude, boundary)
            # Distance to centroid for reporting
            clat = sector_row.get("center_lat", boundary[0][0])
            clon = sector_row.get("center_lon", boundary[0][1])
            distance = calculate_distance_meters(loc.latitude, loc.longitude, clat, clon)
        except Exception:
            approved = False
    else:
        # Fallback: radius check using center or hardcoded.
        # sector_row is a dict(sqlite3.Row), so a NULL column is present
        # with value None — .get(key, default) would not catch that.
        sector_lat = (sector_row.get("center_lat") if sector_row else None) or 56.9587
        sector_lon = (sector_row.get("center_lon") if sector_row else None) or 24.1034
        allowed_radius = 10000
        distance = calculate_distance_meters(loc.latitude, loc.longitude, sector_lat, sector_lon)
        approved = distance <= allowed_radius

    session_id = db_execute("""
    INSERT INTO work_sessions
    (user_id,employee,employee_id,contractor,sector,check_in_time,finish_time,latitude,longitude,distance_m,approved,comment)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (str(update.effective_user.id), employee, employee_id, contractor, sector_name, checked_at, "",
          loc.latitude, loc.longitude, distance, "YES" if approved else "NO", ""))

    if loc.live_period:
        upsert_live_location(
            employee_id, str(update.effective_user.id), sector_name,
            loc.latitude, loc.longitude, loc.live_period
        )

    context.user_data["active_work_session"] = {
        "id": session_id, "employee": employee, "contractor": contractor,
        "sector": sector_name, "check_in_time": checked_at,
        "distance": distance, "approved": approved,
    }
    context.user_data.pop("pending_checkin_sector", None)

    if not approved:
        reason = "Worker outside approved polygon boundary" if (sector_row and sector_row.get("boundary_json")) \
                 else f"Worker outside approved zone. Distance: {distance:.0f} m"
        add_risk(sector_name, "HIGH", reason)

    dist_str = f"{distance:.0f} m" if distance else "N/A"
    method = "polygon boundary" if (sector_row and sector_row.get("boundary_json")) else "radius check"

    await update.message.reply_text(
        f"{'✅ Check-in approved' if approved else '❌ Check-in rejected'}\n\n"
        f"Employee: {employee}\nContractor: {contractor}\nSector: {sector_name}\n"
        f"Distance to center: {dist_str}\nMethod: {method}\nTime: {checked_at}\n\n"
        f"{'Now upload field data.' if approved else '⚠️ Risk created automatically.'}",
        reply_markup=work_keyboard() if approved else main_keyboard()
    )


# ── Photo, comment, finish ────────────────────────────────────────────────────

async def ask_photo(update, context, photo_type):
    if not context.user_data.get("active_work_session"):
        await update.message.reply_text("⚠️ First use 📍 GPS Check-in.", reply_markup=main_keyboard())
        return
    context.user_data["waiting_photo_type"] = photo_type
    await update.message.reply_text(f"📸 Send {photo_type} photo now.", reply_markup=work_keyboard())

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Route to robez plan OCR handler
    if context.user_data.get("waiting_robez_plan"):
        await handle_robez_plan_photo(update, context)
        return

    session = context.user_data.get("active_work_session")
    photo_type = context.user_data.get("waiting_photo_type")
    if not session:
        await update.message.reply_text("⚠️ First use 📍 GPS Check-in.", reply_markup=main_keyboard())
        return
    if not photo_type:
        await update.message.reply_text("First choose: 📷 Site / 🚜 Equipment / 🪵 Timber", reply_markup=work_keyboard())
        return
    photo = update.message.photo[-1]
    file = await photo.get_file()
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    sector_safe = session["sector"].replace("/","_").replace(" ","_")
    image_path = PHOTOS_DIR / f"{sector_safe}_{photo_type}_{timestamp}.jpg"
    await file.download_to_drive(str(image_path))
    db_execute("INSERT INTO work_photos (session_id,sector,photo_type,image_path,uploaded_at) VALUES (?,?,?,?,?)",
               (session["id"], session["sector"], photo_type, str(image_path),
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")))
    context.user_data.pop("waiting_photo_type", None)
    await update.message.reply_text(f"✅ Photo saved\nSector: {session['sector']}\nType: {photo_type}", reply_markup=work_keyboard())

async def ask_comment(update, context):
    if not context.user_data.get("active_work_session"):
        await update.message.reply_text("⚠️ First use 📍 GPS Check-in.", reply_markup=main_keyboard())
        return
    context.user_data["waiting_comment"] = True
    await update.message.reply_text("📝 Send comment now.", reply_markup=work_keyboard())

async def save_comment_text(update, context):
    session = context.user_data.get("active_work_session")
    comment = update.message.text.strip()
    db_execute("UPDATE work_sessions SET comment=? WHERE id=?", (comment, session["id"]))
    context.user_data.pop("waiting_comment", None)
    await update.message.reply_text(f"✅ Comment saved\nSector: {session['sector']}\n{comment}", reply_markup=work_keyboard())

async def finish_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = context.user_data.get("active_work_session")
    if not session:
        await update.message.reply_text("⚠️ No active session. Use 📍 GPS Check-in first.", reply_markup=main_keyboard())
        return
    finished_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    db_execute("UPDATE work_sessions SET finish_time=? WHERE id=?", (finished_at, session["id"]))
    photos_total = db_fetchone("SELECT COUNT(*) FROM work_photos WHERE session_id=?", (session["id"],))
    photos_total = photos_total[0] if photos_total else 0
    await update.message.reply_text(
        f"✅ Work session finished\n\nEmployee: {session['employee']}\nContractor: {session['contractor']}\n"
        f"Sector: {session['sector']}\nCheck-in: {session['check_in_time']}\nFinish: {finished_at}\n"
        f"Approved: {'YES' if session['approved'] else 'NO'}\nPhotos: {photos_total}",
        reply_markup=main_keyboard()
    )
    context.user_data.clear()


# ── Add Sector ────────────────────────────────────────────────────────────────

async def add_sector_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("/add_sector", "").strip()
    parts = [p.strip() for p in text.split("|")]

    if len(parts) < 4:
        await update.message.reply_text(
            "Format (basic):\n/add_sector A-004 | Baltic Forest | Active Logging | 300 m3\n\n"
            "Format (with polygon boundary):\n"
            "/add_sector A-004 | Baltic Forest | Active Logging | 300 m3 | 56.9650,24.1800;56.9650,24.1950;56.9550,24.1950;56.9550,24.1800"
        )
        return

    name, contractor, status, approved_volume = parts[0], parts[1], parts[2], parts[3]
    boundary = None

    if len(parts) >= 5:
        boundary_str = parts[4].strip()
        boundary = parse_boundary(boundary_str)
        if boundary is None:
            await update.message.reply_text(
                "⚠️ Invalid boundary format.\n\n"
                "Use: lat,lon;lat,lon;lat,lon;lat,lon (minimum 4 points)\n"
                "Example: 56.9650,24.1800;56.9650,24.1950;56.9550,24.1950;56.9550,24.1800"
            )
            return

    add_sector(name, contractor, status, approved_volume, boundary=boundary)

    if boundary:
        clat, clon = calc_centroid(boundary)
        area = calc_area_ha(boundary)
        await update.message.reply_text(
            f"✅ Sector added with boundary\n\n"
            f"Sector: {name}\nContractor: {contractor}\nStatus: {status}\n"
            f"Approved volume: {approved_volume}\nBoundary points: {len(boundary)}\n"
            f"Center: {clat}, {clon}\nArea: {area} ha"
        )
    else:
        await update.message.reply_text(
            f"✅ Sector added\n\nSector: {name}\nContractor: {contractor}\n"
            f"Status: {status}\nApproved volume: {approved_volume}\nBoundary: NO"
        )

async def show_add_sector_boundary_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🗺 Add Sector with Polygon Boundary\n\n"
        "Copy and edit this command:\n\n"
        "/add_sector A-004 | Baltic Forest | Active Logging | 300 m3 | "
        "56.9650,24.1800;56.9650,24.1950;56.9550,24.1950;56.9550,24.1800\n\n"
        "Boundary format: lat,lon;lat,lon;lat,lon;lat,lon\n"
        "Minimum 4 points required.\n"
        "Use [lat, lon] order (WGS84).\n\n"
        "You can get coordinates from Google Maps → right click → coordinates."
    )


# ── Other commands ────────────────────────────────────────────────────────────

async def add_risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("/add_risk", "").strip()
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 3:
        await update.message.reply_text("/add_risk A-004 | HIGH | Logging exceeded approved volume")
        return
    add_risk(*parts)
    await update.message.reply_text("⚠️ Risk added")

async def add_timber_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("/add_timber", "").strip()
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 4:
        await update.message.reply_text("/add_timber A-004 | 300 | 280 | 20 m3 missing from truck report")
        return
    sector, planned, actual, note = parts
    try:
        planned_volume = float(planned.replace("m3","").strip())
        actual_volume  = float(actual.replace("m3","").strip())
    except ValueError:
        await update.message.reply_text("⚠️ Volume must be a number.")
        return
    difference = planned_volume - actual_volume
    status = "OK" if difference == 0 else ("MISSING_VOLUME" if difference > 0 else "OVER_VOLUME")
    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    db_execute("INSERT INTO timber_movements (sector,planned_volume,actual_volume,difference_volume,status,note,created_at) VALUES (?,?,?,?,?,?,?)",
               (sector, planned_volume, actual_volume, difference, status, note, created_at))
    if status != "OK":
        add_risk(sector, "HIGH", f"Timber volume mismatch. Planned: {planned_volume} m3, actual: {actual_volume} m3, diff: {difference} m3")
    await update.message.reply_text(
        f"🪵 Timber movement saved\n\nSector: {sector}\nPlanned: {planned_volume} m3\n"
        f"Actual: {actual_volume} m3\nDifference: {difference} m3\nStatus: {status}\nNote: {note}\n\n"
        f"{'⚠️ Risk created.' if status != 'OK' else '✅ No mismatch.'}",
        reply_markup=main_keyboard()
    )

async def add_truck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("/add_truck", "").strip()
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 5:
        await update.message.reply_text("/add_truck A-004 | TRUCK-22 | John Driver | 280 | first truck report")
        return
    sector, truck_number, driver, volume, note = parts
    try:
        reported_volume = float(volume.replace("m3","").strip())
    except ValueError:
        await update.message.reply_text("⚠️ Reported volume must be a number.")
        return
    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    db_execute("INSERT INTO truck_reports (sector,truck_number,driver,reported_volume,note,created_at) VALUES (?,?,?,?,?,?)",
               (sector, truck_number, driver, reported_volume, note, created_at))
    timber_total = (db_fetchone("SELECT SUM(actual_volume) FROM timber_movements WHERE sector=?", (sector,)) or (0,))[0] or 0
    truck_total  = (db_fetchone("SELECT SUM(reported_volume) FROM truck_reports WHERE sector=?", (sector,)) or (0,))[0] or 0
    difference = timber_total - truck_total
    if abs(difference) > 0:
        add_risk(sector, "MEDIUM", f"Truck report mismatch. Timber: {timber_total} m3, trucks: {truck_total} m3, diff: {difference} m3")
    await update.message.reply_text(
        f"🚛 Truck report saved\n\nSector: {sector}\nTruck: {truck_number}\nDriver: {driver}\n"
        f"Volume: {reported_volume} m3\nNote: {note}\n\nTimber total: {timber_total} m3\n"
        f"Truck total: {truck_total} m3\nDifference: {difference} m3\n\n"
        f"{'⚠️ Risk created.' if abs(difference) > 0 else '✅ Match OK.'}",
        reply_markup=main_keyboard()
    )

async def timber_movement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db_fetchall("SELECT sector,planned_volume,actual_volume,difference_volume,status,note,created_at FROM timber_movements ORDER BY id DESC LIMIT 10")
    if not rows:
        await update.message.reply_text("🪵 No timber movement records yet.\n\n/add_timber A-004 | 300 | 280 | note")
        return
    msg = "🪵 Timber Movement\n\n"
    for sector, planned, actual, diff, status, note, ts in rows:
        msg += f"Sector: {sector}\nPlanned: {planned} m3\nActual: {actual} m3\nDiff: {diff} m3\nStatus: {status}\nNote: {note}\nTime: {ts}\n\n"
    await update.message.reply_text(msg, reply_markup=main_keyboard())

async def truck_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db_fetchall("SELECT sector,truck_number,driver,reported_volume,note,created_at FROM truck_reports ORDER BY id DESC LIMIT 10")
    if not rows:
        await update.message.reply_text("🚛 No truck reports yet.\n\n/add_truck A-004 | TRUCK-22 | Driver | 280 | note")
        return
    msg = "🚛 Truck Reports\n\n"
    for sector, truck, driver, volume, note, ts in rows:
        msg += f"Sector: {sector}\nTruck: {truck}\nDriver: {driver}\nVolume: {volume} m3\nNote: {note}\nTime: {ts}\n\n"
    await update.message.reply_text(msg, reply_markup=main_keyboard())

async def sectors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_sectors()
    if not rows:
        await update.message.reply_text("/add_sector A-004 | Baltic Forest | Active Logging | 300 m3")
        return
    msg = "🌲 Sectors\n\n"
    for row in rows:
        name, contractor, status, approved_volume = row[0], row[1], row[2], row[3]
        boundary_json = row[6] if len(row) > 6 else None
        center_lat    = row[7] if len(row) > 7 else None
        center_lon    = row[8] if len(row) > 8 else None
        has_boundary  = "YES" if boundary_json else "NO"
        msg += f"Sector: {name}\nContractor: {contractor}\nStatus: {status}\nApproved volume: {approved_volume}\n"
        msg += f"Boundary: {has_boundary}\n"
        if center_lat and center_lon:
            msg += f"Center: {center_lat:.4f}°N {center_lon:.4f}°E\n"
        msg += "\n"
    await update.message.reply_text(msg)

async def risks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_risks()
    if not rows:
        await update.message.reply_text("⚠️ No risks yet.")
        return
    msg = "⚠️ Risks\n\n"
    for sector, risk_level, reason in rows:
        msg += f"Sector: {sector}\nRisk level: {risk_level}\nReason: {reason}\n\n"
    await update.message.reply_text(msg)

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sectors_rows = get_sectors()
    risks_rows   = get_risks()
    sessions_count = (db_fetchone("SELECT COUNT(*) FROM work_sessions") or (0,))[0]
    photos_count   = (db_fetchone("SELECT COUNT(*) FROM work_photos") or (0,))[0]
    timber_count   = (db_fetchone("SELECT COUNT(*) FROM timber_movements") or (0,))[0]
    trucks_count   = (db_fetchone("SELECT COUNT(*) FROM truck_reports") or (0,))[0]
    sectors_with_boundary = sum(1 for s in sectors_rows if len(s) > 6 and s[6])
    active_session = context.user_data.get("active_work_session")
    await update.message.reply_text(
        f"📊 Forest AI Report\n\nSectors: {len(sectors_rows)} ({sectors_with_boundary} with boundary)\n"
        f"Risks: {len(risks_rows)}\nGPS sessions: {sessions_count}\nPhotos: {photos_count}\n"
        f"Timber movements: {timber_count}\nTruck reports: {trucks_count}\n"
        f"Active session: {'YES' if active_session else 'NO'}"
    )

async def export_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    zip_path = build_export_zip()
    await update.message.reply_text("📤 Export report created. Sending file...")
    with open(zip_path, "rb") as f:
        await update.message.reply_document(document=f, filename=zip_path.name, caption="📊 Forest AI Export Report")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ Settings\n\nDatabase: SQLite\nExport: CSV ZIP\n"
        "Sectors: ON (polygon boundary support)\nRisks: ON\n"
        "GPS Check-in: ON (polygon-aware)\nPhoto upload: ON\n"
        "Comments: ON\nTimber Movement: ON\nTruck Report: ON"
    )


# ── Menu router ───────────────────────────────────────────────────────────────

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if context.user_data.get("waiting_object_name"):
        await handle_object_name_input(update, context)
        return
    if context.user_data.get("waiting_comment"):
        await save_comment_text(update, context)
        return
    dispatch = {
        "🌲 Sectors":              sectors_command,
        "⚠️ Risks":               risks_command,
        "📍 GPS Check-in":        check_in,
        "🚛 Vehicle GPS":         vehicle_gps_start,
        "✅ Finish Work":         finish_work,
        "🪵 Timber Movement":     timber_movement,
        "➕ Add Timber":          lambda u,c: u.message.reply_text("/add_timber A-004 | 300 | 280 | note"),
        "🚛 Truck Report":        truck_report,
        "➕ Add Truck":           lambda u,c: u.message.reply_text("/add_truck A-004 | TRUCK-22 | Driver | 280 | note"),
        "➕ Add Sector":          lambda u,c: u.message.reply_text("/add_sector A-004 | Baltic Forest | Active Logging | 300 m3"),
        "🗺 Add Sector Boundary": show_add_sector_boundary_help,
        "📄 Robežu Plāns — OCR": ask_robez_plan,
        "📷 Upload Site Photo":   lambda u,c: ask_photo(u, c, "site"),
        "🚜 Upload Equipment Photo": lambda u,c: ask_photo(u, c, "equipment"),
        "🪵 Upload Timber Photo": lambda u,c: ask_photo(u, c, "timber"),
        "📝 Add Comment":         ask_comment,
        "📊 Report":              report,
        "📤 Export Report":       export_report,
        "⚙️ Settings":           settings,
    }
    handler = dispatch.get(text)
    if handler:
        await handler(update, context)
    else:
        await update.message.reply_text("Choose action from menu or type /start.")

async def handle_worker_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.reply_to_message or not msg.text:
        return
    risk = get_risk_by_telegram_message_id(msg.reply_to_message.message_id)
    if not risk:
        return  # reply to something unrelated to a risk alert — ignore, don't interfere with menu flow
    add_risk_event(risk["id"], "WORKER_REPLIED", actor=f"employee:{update.effective_user.id}", details=msg.text)
    try:
        await msg.reply_text("✅ Ваш ответ передан диспетчеру.")
    except Exception:
        pass
    raise ApplicationHandlerStop

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("BOT ERROR:", context.error)
    if update and hasattr(update, "effective_message") and update.effective_message:
        await update.effective_message.reply_text(f"⚠️ Error:\n{context.error}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_db()
    init_work_tables()
    init_plan_tables()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_worker_reply), group=-1)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("checkin", check_in))
    app.add_handler(CommandHandler("finish", finish_work))
    app.add_handler(CommandHandler("add_sector", add_sector_command))
    app.add_handler(CommandHandler("add_risk", add_risk_command))
    app.add_handler(CommandHandler("add_timber", add_timber_command))
    app.add_handler(CommandHandler("add_truck", add_truck_command))
    app.add_handler(CommandHandler("sectors", sectors_command))
    app.add_handler(CommandHandler("risks", risks_command))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("export_report", export_report))

    app.add_handler(CallbackQueryHandler(sector_selected_callback, pattern="^checkin_sector:"))
    app.add_handler(CallbackQueryHandler(link_employee_callback, pattern="^linkemp:"))
    app.add_handler(CallbackQueryHandler(vehicle_sector_callback, pattern="^vehgps_sector:"))
    app.add_handler(CallbackQueryHandler(vehicle_selected_callback, pattern="^vehgps_vehicle:"))
    app.add_handler(CallbackQueryHandler(plan_callback, pattern="^plan_"))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
    app.add_error_handler(error_handler)

    print("🌲 Forest AI Bot started...")
    # Explicit allowed_updates so edited_message (Telegram Live Location
    # updates arrive as message edits) is guaranteed to be delivered,
    # regardless of any previously-set restriction on this bot token.
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
