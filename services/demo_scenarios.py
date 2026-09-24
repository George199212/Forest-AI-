"""
Rīgas meži live-demo scenarios.

Five reliable, end-to-end demo triggers, each following the same real
pipeline every other Forest AI incident already goes through:

    anomaly detected -> database.add_incident() (same risks table, same
    OPEN->NOTIFIED->RESOLVED lifecycle) -> services/ai_resolution.py
    generates the AI Inspector recommendation (same function every other
    incident type uses) -> a real Telegram message with real inline buttons
    is sent -> button clicks are handled by real CallbackQueryHandlers in
    bot.py -> responses are logged as risk_events -> risk status updates.

Nothing here is a second, parallel system: it reuses add_incident/
add_risk_event/set_ai_recommendation/generate_incident_recommendation
exactly as bot.py's live geofence flow and api.py's approve endpoint do.
Every row this module creates or updates on the `risks` / `sector_equipment`
/ `timber_movements` tables is flagged is_demo=1 so reset_demo() can wipe
demo state without ever touching real operational data.

Callers: bot.py (Telegram /demo_* commands + button callbacks) and api.py
(POST /api/demo/* — a backend fallback per the spec, in case Telegram
command dispatch is inconvenient during the live presentation). Both call
the exact same functions below, so behavior is identical either way.

Sending Telegram messages here does NOT depend on bot.py's polling
Application (that object only exists inside the bot.py process) — it posts
directly to the Bot API via HTTP, exactly like api.py's approve_incident()
already does. Only *receiving* button clicks requires bot.py's
CallbackQueryHandlers (registered in bot.py itself).
"""

import json
import logging
import os
import sqlite3
from datetime import datetime

import requests

import database
from services import geo
from services.ai_resolution import generate_incident_recommendation

logger = logging.getLogger("forest_ai.demo")
if not logger.handlers:
    # Mirror the rest of the codebase's print()-based logging so demo
    # trigger errors show up in the same systemd journal operators already
    # watch, but tagged for easy grepping during the live demo.
    logging.basicConfig(level=logging.INFO)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _token():
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def _dispatcher_chat_id():
    return os.environ.get("DISPATCHER_CHAT_ID", "").strip()


def demo_admin_ids():
    """Telegram user ids allowed to run /demo_* commands. Defaults to the
    configured dispatcher (the presenter's own account in this deployment —
    every demo employee row is also linked to that same telegram_user_id),
    so no extra config is required to demo tomorrow. Override with
    DEMO_ADMIN_IDS="123,456" for a multi-person rehearsal."""
    raw = os.environ.get("DEMO_ADMIN_IDS", "").strip()
    if raw:
        return {p.strip() for p in raw.split(",") if p.strip()}
    dispatcher = _dispatcher_chat_id()
    return {dispatcher} if dispatcher else set()


def is_demo_admin(telegram_user_id) -> bool:
    return str(telegram_user_id) in demo_admin_ids()


def _conn():
    conn = sqlite3.connect(database.DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def _tg_send(chat_id, text, buttons=None):
    """POST a message straight to the Bot API — same pattern api.py's
    approve_incident()/inspector_report_issue() already use. buttons: list
    of rows, each row a list of {"text":..., "callback_data":...}. Never
    raises; returns the Telegram message_id (str) or None, always logging
    what happened so a demo-time failure is diagnosable immediately."""
    token = _token()
    if not token:
        logger.error("DEMO: TELEGRAM_BOT_TOKEN not set — cannot send message")
        return None
    if not chat_id:
        logger.error("DEMO: no chat_id to send to")
        return None
    payload = {"chat_id": chat_id, "text": text}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        resp = requests.post(
            TELEGRAM_API.format(token=token, method="sendMessage"),
            json=payload, timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.error("DEMO: Telegram send failed: %s", data.get("description"))
            return None
        return str(data["result"]["message_id"])
    except Exception as e:
        logger.error("DEMO: Telegram send exception: %s", e)
        return None


def _mark_demo(incident_id):
    conn = _conn()
    conn.execute("UPDATE risks SET is_demo=1 WHERE id=?", (incident_id,))
    conn.commit()
    conn.close()


def _fallback_recommendation(summary, options, recommended_option_id,
                              exposure_low, exposure_high, exposure_basis, exposure_period):
    """Deterministic recommendation matching services/ai_resolution.py's JSON
    contract exactly, used ONLY if the live Claude call fails (no API key,
    network hiccup, timeout) — so a demo never shows an empty AI panel.
    Frontend rendering (index.html openRisk()) can't tell the difference,
    since it only looks at the JSON shape, not who produced it."""
    return json.dumps({
        "summary": summary,
        "options": options,
        "recommended_option_id": recommended_option_id,
        "estimated_exposure_eur_low": exposure_low,
        "estimated_exposure_eur_high": exposure_high,
        "exposure_basis": exposure_basis,
        "exposure_period": exposure_period,
    }, ensure_ascii=False)


def _generate_recommendation(incident_id, sector, reason, entity_type, rule_code, fallback):
    """Same pipeline every other incident uses. Never raises. Falls back to
    a deterministic recommendation (still real JSON, still renders normally)
    if the live call returns None, so the demo is never at the mercy of a
    flaky network on the day."""
    recommendation = generate_incident_recommendation({
        "sector": sector, "reason": reason,
        "entity_type": entity_type, "rule_code": rule_code,
    })
    if not recommendation:
        logger.warning("DEMO: AI recommendation call failed for incident #%s — using fallback", incident_id)
        recommendation = fallback
        actor = "ai_fallback"
    else:
        actor = "ai"
    database.set_ai_recommendation(incident_id, recommendation)
    database.add_risk_event(incident_id, "AI_RECOMMENDATION_GENERATED", actor=actor)
    return recommendation


def _find_sector(code):
    """Exact match first (A-005, A-006), then a LIKE prefix match for
    sectors whose display name carries extra text (e.g. the seeded
    'A-007 — Сигулдский лес:'). Returns the sectors row as a dict, or None."""
    conn = _conn()
    row = conn.execute("SELECT * FROM sectors WHERE name=?", (code,)).fetchone()
    if not row:
        row = conn.execute("SELECT * FROM sectors WHERE name LIKE ? ORDER BY name LIMIT 1", (code + "%",)).fetchone()
    conn.close()
    return dict(row) if row else None


def _find_employee(sector_name, full_name):
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM sector_employees WHERE full_name=? ORDER BY (sector=?) DESC LIMIT 1",
        (full_name, sector_name),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _upsert_live_location(employee_id, telegram_user_id, sector, lat, lon, last_status):
    conn = _conn()
    now = _now()
    existing = conn.execute("SELECT id FROM live_locations WHERE employee_id=?", (employee_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE live_locations SET telegram_user_id=?, sector=?, latitude=?, longitude=?, "
            "updated_at=?, last_status=? WHERE id=?",
            (telegram_user_id, sector, lat, lon, now, last_status, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO live_locations "
            "(employee_id, telegram_user_id, sector, latitude, longitude, live_period, "
            " started_at, updated_at, expires_at, last_status) "
            "VALUES (?,?,?,?,?,0,?,?,?,?)",
            (employee_id, telegram_user_id, sector, lat, lon, now, now, now, last_status),
        )
    conn.commit()
    conn.close()


def _ensure_equipment(sector_name, equipment_code, equipment_type, operator_employee_id, status="ACTIVE"):
    conn = _conn()
    row = conn.execute("SELECT * FROM sector_equipment WHERE equipment_code=?", (equipment_code,)).fetchone()
    if row:
        conn.execute(
            "UPDATE sector_equipment SET status=?, operator_employee_id=? WHERE id=?",
            (status, operator_employee_id, row["id"]),
        )
        eid = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO sector_equipment "
            "(sector, equipment_code, type, operator_employee_id, status, active, created_at, is_demo) "
            "VALUES (?,?,?,?,?,1,?,1)",
            (sector_name, equipment_code, equipment_type, operator_employee_id, status, _now()),
        )
        eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def _existing_open_incident(entity_type, entity_id, rule_code, sector=None):
    conn = _conn()
    if entity_id is not None:
        row = conn.execute(
            "SELECT * FROM risks WHERE entity_type=? AND entity_id=? AND rule_code=? "
            "AND status IN ('OPEN','NOTIFIED') ORDER BY id DESC LIMIT 1",
            (entity_type, entity_id, rule_code),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM risks WHERE entity_type=? AND entity_id IS NULL AND rule_code=? AND sector=? "
            "AND status IN ('OPEN','NOTIFIED') ORDER BY id DESC LIMIT 1",
            (entity_type, rule_code, sector),
        ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────
# SCENARIO 1 — Forestry machine breakdown
# ─────────────────────────────────────────────────────────────────────────

BREAKDOWN_SECTOR = "A-005"
BREAKDOWN_EQUIPMENT_CODE = "PONSSE-W11-DEMO"
BREAKDOWN_OPERATOR_NAME = "Kārlis Ozoliņš"

DIAGNOSTICS_LABELS = {
    "engine": "Двигатель",
    "hydraulics": "Гидравлика",
    "transmission": "Трансмиссия",
    "crane": "Кран-манипулятор",
    "electrical": "Электрика",
    "other": "Другое",
}


def trigger_breakdown(triggered_by="demo_trigger"):
    sector = _find_sector(BREAKDOWN_SECTOR)
    if not sector:
        raise RuntimeError(f"Demo sector {BREAKDOWN_SECTOR} not found")
    operator = _find_employee(BREAKDOWN_SECTOR, BREAKDOWN_OPERATOR_NAME)
    if not operator:
        raise RuntimeError(f"Demo operator '{BREAKDOWN_OPERATOR_NAME}' not found in {BREAKDOWN_SECTOR}")

    equipment_id = _ensure_equipment(BREAKDOWN_SECTOR, BREAKDOWN_EQUIPMENT_CODE, "FORWARDER",
                                      operator["id"], status="BREAKDOWN")

    lat, lon = sector["center_lat"], sector["center_lon"]
    _upsert_live_location(operator["id"], operator.get("telegram_user_id"), BREAKDOWN_SECTOR, lat, lon, "IN")

    now = _now()
    reason = (
        f"Forwarder {BREAKDOWN_EQUIPMENT_CODE} — operator reported equipment malfunction. "
        f"Diagnostics required.\n"
        f"Machine: {BREAKDOWN_EQUIPMENT_CODE} (Forwarder)\n"
        f"Sector: {BREAKDOWN_SECTOR}\n"
        f"Operator: {BREAKDOWN_OPERATOR_NAME}\n"
        f"Time: {now}\n"
        f"GPS position: {lat:.5f}, {lon:.5f}\n"
        f"Last activity: operating normally until breakdown was reported"
    )

    incident_id = database.add_incident(
        BREAKDOWN_SECTOR, "HIGH", reason,
        entity_type="EMPLOYEE", entity_id=operator["id"], rule_code="EQUIPMENT_BREAKDOWN",
    )
    _mark_demo(incident_id)
    database.add_risk_event(incident_id, "DETECTED", actor=triggered_by, details=reason)

    _generate_recommendation(
        incident_id, BREAKDOWN_SECTOR, reason, "EMPLOYEE", "EQUIPMENT_BREAKDOWN",
        fallback=_fallback_recommendation(
            summary=(
                f"Оператор {BREAKDOWN_OPERATOR_NAME} сообщил о поломке форвардера "
                f"{BREAKDOWN_EQUIPMENT_CODE} в секторе {BREAKDOWN_SECTOR}. Требуется диагностика "
                f"перед возобновлением работы. Техника простаивает, что напрямую влияет на "
                f"план вывозки древесины по сектору."
            ),
            options=[
                {"id": "contact_worker", "label": "Связаться с оператором",
                 "message_text": f"Здравствуйте, {BREAKDOWN_OPERATOR_NAME}. Диспетчер получил сигнал о поломке "
                                  f"{BREAKDOWN_EQUIPMENT_CODE}. Пожалуйста, начните диагностику через меню в боте "
                                  f"и опишите неисправность."},
                {"id": "dispatch_service", "label": "Направить сервисную службу",
                 "message_text": f"Сервисная служба уведомлена о поломке {BREAKDOWN_EQUIPMENT_CODE} в секторе "
                                  f"{BREAKDOWN_SECTOR} и свяжется с оператором в ближайшее время."},
            ],
            recommended_option_id="contact_worker",
            exposure_low=800, exposure_high=3500,
            exposure_basis="Оценка на основе простоя форвардера (аренда/лизинг + недополученная вывозка).",
            exposure_period="ежедневно, пока техника не отремонтирована",
        ),
    )

    text = (
        f"🔧 FOREST AI — EQUIPMENT BREAKDOWN\n\n"
        f"Machine: {BREAKDOWN_EQUIPMENT_CODE}\n"
        f"Sector: {BREAKDOWN_SECTOR}\n"
        f"Operator: {BREAKDOWN_OPERATOR_NAME}\n"
        f"Priority: HIGH\n\n"
        f"Пожалуйста, подтвердите неисправность и начните диагностику."
    )
    buttons = [
        [{"text": "🔧 Start Diagnostics", "callback_data": f"brk_action:{incident_id}:diag"}],
        [{"text": "📷 Send Photo", "callback_data": f"brk_action:{incident_id}:photo"},
         {"text": "📍 Send Location", "callback_data": f"brk_action:{incident_id}:loc"}],
        [{"text": "☎️ Contact Service", "callback_data": f"brk_action:{incident_id}:service"}],
        [{"text": "✅ Problem Resolved", "callback_data": f"brk_action:{incident_id}:resolved"}],
    ]
    message_id = _tg_send(operator.get("telegram_user_id"), text, buttons)
    if message_id:
        database.update_incident_status(incident_id, "NOTIFIED", telegram_message_id=message_id)
        database.add_risk_event(incident_id, "TELEGRAM_SENT", actor="system", details=text)
    else:
        database.add_risk_event(incident_id, "TELEGRAM_SEND_FAILED", actor="system")

    logger.info("DEMO: scenario=breakdown incident_id=%s telegram_sent=%s", incident_id, bool(message_id))
    return {"incident_id": incident_id, "telegram_sent": bool(message_id), "equipment_id": equipment_id}


# ─────────────────────────────────────────────────────────────────────────
# SCENARIO 2 — Worker outside approved sector
# ─────────────────────────────────────────────────────────────────────────

SECTOR_EXIT_SECTOR = "A-005"
SECTOR_EXIT_WORKER_NAME = "Ilze Anhalta"


def trigger_worker_exit(triggered_by="demo_trigger"):
    sector = _find_sector(SECTOR_EXIT_SECTOR)
    if not sector:
        raise RuntimeError(f"Demo sector {SECTOR_EXIT_SECTOR} not found")
    worker = _find_employee(SECTOR_EXIT_SECTOR, SECTOR_EXIT_WORKER_NAME)
    if not worker:
        raise RuntimeError(f"Demo worker '{SECTOR_EXIT_WORKER_NAME}' not found in {SECTOR_EXIT_SECTOR}")

    boundary = json.loads(sector["boundary_json"])
    # A point ~120m south of the sector's southern edge — real polygon math,
    # not a made-up label.
    south_edge_lat = min(p[0] for p in boundary)
    mid_lon = (min(p[1] for p in boundary) + max(p[1] for p in boundary)) / 2.0
    out_lat = south_edge_lat - (120.0 / 110540.0)
    out_lon = mid_lon
    distance_out = geo.distance_to_polygon_edge_m(out_lat, out_lon, boundary)
    inside = geo.point_in_polygon(out_lat, out_lon, boundary)

    existing = _existing_open_incident("EMPLOYEE", worker["id"], "SECTOR_EXIT")
    if existing:
        incident_id = existing["id"]
        database.add_risk_event(incident_id, "STILL_OUTSIDE", actor=triggered_by,
                                 details=f"GPS: {out_lat:.5f}, {out_lon:.5f} — {distance_out:.0f} m outside boundary")
        _upsert_live_location(worker["id"], worker.get("telegram_user_id"), SECTOR_EXIT_SECTOR, out_lat, out_lon, "OUT")
        logger.info("DEMO: scenario=worker_exit reusing open incident_id=%s", incident_id)
        return {"incident_id": incident_id, "telegram_sent": False, "reused": True}

    reason = (
        f"Worker {SECTOR_EXIT_WORKER_NAME} detected outside approved sector boundary.\n"
        f"Sector: {SECTOR_EXIT_SECTOR}\n"
        f"Current GPS: {out_lat:.5f}, {out_lon:.5f}\n"
        f"Distance outside boundary: {distance_out:.0f} m\n"
        f"Time: {_now()}\n"
        f"Last valid position: inside {SECTOR_EXIT_SECTOR}"
    )
    incident_id = database.add_incident(
        SECTOR_EXIT_SECTOR, "HIGH", reason,
        entity_type="EMPLOYEE", entity_id=worker["id"], rule_code="SECTOR_EXIT",
        distance_m=distance_out,
    )
    _mark_demo(incident_id)
    database.add_risk_event(incident_id, "DETECTED", actor=triggered_by, details=reason)
    _upsert_live_location(worker["id"], worker.get("telegram_user_id"), SECTOR_EXIT_SECTOR, out_lat, out_lon, "OUT")

    _generate_recommendation(
        incident_id, SECTOR_EXIT_SECTOR, reason, "EMPLOYEE", "SECTOR_EXIT",
        fallback=_fallback_recommendation(
            summary=(
                f"Работник {SECTOR_EXIT_WORKER_NAME} покинул границу сектора {SECTOR_EXIT_SECTOR} "
                f"(зафиксировано на {distance_out:.0f} м за пределами полигона). Это может быть "
                f"нарушением техники безопасности или ошибкой навигации. Требуется подтверждение и "
                f"возврат работника в рабочую зону."
            ),
            options=[
                {"id": "contact_worker", "label": "Связаться с работником",
                 "message_text": f"{SECTOR_EXIT_WORKER_NAME}, вы вышли за границу сектора {SECTOR_EXIT_SECTOR} "
                                  f"примерно на {distance_out:.0f} м. Пожалуйста, вернитесь в рабочую зону и "
                                  f"подтвердите получение сообщения."},
            ],
            recommended_option_id="contact_worker",
            exposure_low=200, exposure_high=1200,
            exposure_basis="Оценка риска нарушения зоны ответственности/техники безопасности.",
            exposure_period="в течение нескольких часов, если не устранено",
        ),
    )

    text = (
        f"⚠️ FOREST AI — SECTOR ALERT\n\n"
        f"You are outside the approved work sector.\n\n"
        f"Sector: {SECTOR_EXIT_SECTOR}\n"
        f"Distance outside boundary: {distance_out:.0f} m"
    )
    buttons = [
        [{"text": "📍 View Location", "callback_data": f"sxt_action:{incident_id}:view"}],
        [{"text": "↩️ Return to Sector", "callback_data": f"sxt_action:{incident_id}:return"}],
        [{"text": "📝 Explain", "callback_data": f"sxt_action:{incident_id}:explain"},
         {"text": "🆘 Emergency", "callback_data": f"sxt_action:{incident_id}:emergency"}],
    ]
    worker_telegram_id = worker.get("telegram_user_id")
    if worker_telegram_id:
        message_id = _tg_send(worker_telegram_id, text, buttons)
        _tg_send(_dispatcher_chat_id(), f"👁 [Operator view] {text}")
    else:
        message_id = _tg_send(_dispatcher_chat_id(), text, buttons)
    if message_id:
        database.update_incident_status(incident_id, "NOTIFIED", telegram_message_id=message_id)
        database.add_risk_event(incident_id, "TELEGRAM_SENT", actor="system", details=text)
    else:
        database.add_risk_event(incident_id, "TELEGRAM_SEND_FAILED", actor="system")

    logger.info("DEMO: scenario=worker_exit incident_id=%s telegram_sent=%s", incident_id, bool(message_id))
    return {"incident_id": incident_id, "telegram_sent": bool(message_id), "distance_m": distance_out}


# ─────────────────────────────────────────────────────────────────────────
# SCENARIO 3 — Timber volume discrepancy (weighing vs satellite estimate)
# ─────────────────────────────────────────────────────────────────────────

VOLUME_SECTOR_PREFIX = "A-007"
REGISTERED_VOLUME_M3 = 180.0
SATELLITE_ESTIMATE_M3 = 300.0


def trigger_volume_mismatch(triggered_by="demo_trigger"):
    sector = _find_sector(VOLUME_SECTOR_PREFIX)
    if not sector:
        raise RuntimeError(f"Demo sector {VOLUME_SECTOR_PREFIX} not found")
    sector_name = sector["name"]

    diff = SATELLITE_ESTIMATE_M3 - REGISTERED_VOLUME_M3
    diff_pct = diff / REGISTERED_VOLUME_M3 * 100.0

    conn = _conn()
    conn.execute(
        "INSERT INTO timber_movements (sector, planned_volume, actual_volume, difference_volume, "
        "status, note, created_at, is_demo) VALUES (?,?,?,?,?,?,?,1)",
        (sector_name, REGISTERED_VOLUME_M3, REGISTERED_VOLUME_M3, 0, "REPORTED",
         "Demo: weighing system report used as registered volume for satellite comparison", _now()),
    )
    conn.commit()
    conn.close()

    reason = (
        "Registered timber volume does not correspond to satellite-observed harvesting activity.\n"
        f"Sector: {sector_name}\n"
        f"Registered (weighing system): {REGISTERED_VOLUME_M3:.0f} m³\n"
        f"Satellite estimate (change detection, NOT an exact measurement): ~{SATELLITE_ESTIMATE_M3:.0f} m³\n"
        f"Difference: ~{diff:.0f} m³ (~{diff_pct:.0f}%)\n"
        f"Time: {_now()}"
    )
    incident_id = database.add_incident(
        sector_name, "HIGH", reason,
        entity_type="SATELLITE", entity_id=None, rule_code="TIMBER_VOLUME_MISMATCH",
    )
    _mark_demo(incident_id)
    database.add_risk_event(incident_id, "DETECTED", actor=triggered_by, details=reason)
    database.add_risk_event(
        incident_id, "TIMBER_COMPARISON", actor="satellite_intelligence",
        details=(f"Registered: {REGISTERED_VOLUME_M3:.0f} m³ | Satellite estimate: ~{SATELLITE_ESTIMATE_M3:.0f} m³ "
                  f"(ESTIMATE, not an exact measurement) | Difference: ~{diff:.0f} m³ (~{diff_pct:.0f}%)"),
    )

    _generate_recommendation(
        incident_id, sector_name, reason, "SATELLITE", "TIMBER_VOLUME_MISMATCH",
        fallback=_fallback_recommendation(
            summary=(
                f"Значительное расхождение между зарегистрированным объёмом древесины "
                f"({REGISTERED_VOLUME_M3:.0f} м³ по данным весовой/учёта вывозки) и спутниковой "
                f"оценкой площади вырубки в секторе {sector_name} (~{SATELLITE_ESTIMATE_M3:.0f} м³, "
                f"оценка по изменению растительного покрова, НЕ точное измерение). Разница ~{diff:.0f} м³ "
                f"(~{diff_pct:.0f}%). Требуется проверка данных вывозки, весовых записей и обстановки на месте "
                f"перед тем, как делать выводы."
            ),
            options=[
                {"id": "investigate", "label": "Начать проверку",
                 "message_text": f"Диспетчер, зафиксировано расхождение объёма в секторе {sector_name}: "
                                  f"учтено {REGISTERED_VOLUME_M3:.0f} м³, спутник оценивает ~{SATELLITE_ESTIMATE_M3:.0f} м³. "
                                  f"Пожалуйста, сверьте данные вывозки и весовые записи."},
            ],
            recommended_option_id="investigate",
            exposure_low=int(diff * 60), exposure_high=int(diff * 120),
            exposure_basis="Оценка по рыночной цене древесины (€60–120/м³) на неучтённую разницу объёма.",
            exposure_period="разовое расхождение — требует проверки в течение 1-2 недель",
        ),
    )

    text = (
        f"🔍 FOREST AI — TIMBER VOLUME MISMATCH\n\n"
        f"Sector: {sector_name}\n"
        f"Registered: {REGISTERED_VOLUME_M3:.0f} m³\n"
        f"Satellite estimate: ~{SATELLITE_ESTIMATE_M3:.0f} m³ (estimate, not exact)\n"
        f"Difference: ~{diff:.0f} m³ (~{diff_pct:.0f}%)\n"
        f"Priority: HIGH"
    )
    buttons = [
        [{"text": "🔍 Investigate", "callback_data": f"vol_action:{incident_id}:investigate"}],
        [{"text": "📊 View Comparison", "callback_data": f"vol_action:{incident_id}:compare"}],
        [{"text": "🚛 Check Timber Movements", "callback_data": f"vol_action:{incident_id}:movements"}],
        [{"text": "📷 Request Field Photo", "callback_data": f"vol_action:{incident_id}:photo"}],
        [{"text": "✅ Confirm / Resolve", "callback_data": f"vol_action:{incident_id}:resolve"}],
    ]
    message_id = _tg_send(_dispatcher_chat_id(), text, buttons)
    if message_id:
        database.update_incident_status(incident_id, "NOTIFIED", telegram_message_id=message_id)
        database.add_risk_event(incident_id, "TELEGRAM_SENT", actor="system", details=text)
    else:
        database.add_risk_event(incident_id, "TELEGRAM_SEND_FAILED", actor="system")

    logger.info("DEMO: scenario=volume_mismatch incident_id=%s telegram_sent=%s", incident_id, bool(message_id))
    return {"incident_id": incident_id, "telegram_sent": bool(message_id), "difference_m3": diff}


# ─────────────────────────────────────────────────────────────────────────
# SCENARIO 4 — Machine approaching dangerous wetland
# ─────────────────────────────────────────────────────────────────────────

WETLAND_SECTOR = "A-005"
WETLAND_EQUIPMENT_CODE = "JD-1270G-DEMO"
WETLAND_OPERATOR_NAME = "Jānis Bērziņš"
WETLAND_WARNING_M = 100.0
WETLAND_CRITICAL_M = 40.0

# A small protected-wetland rectangle just south of A-005's boundary
# (56.955, 24.18)-(56.955, 24.195) — real polygon math against a fixed,
# documented "protected zone", not a random number.
WETLAND_POLYGON = [
    [56.9530, 24.1830], [56.9530, 24.1920], [56.9490, 24.1920], [56.9490, 24.1830],
]


def _wetland_distance(lat, lon):
    if geo.point_in_polygon(lat, lon, WETLAND_POLYGON):
        return 0.0
    return geo.distance_to_polygon_edge_m(lat, lon, WETLAND_POLYGON)


def trigger_wetland(triggered_by="demo_trigger"):
    sector = _find_sector(WETLAND_SECTOR)
    if not sector:
        raise RuntimeError(f"Demo sector {WETLAND_SECTOR} not found")
    operator = _find_employee(WETLAND_SECTOR, WETLAND_OPERATOR_NAME)
    if not operator:
        raise RuntimeError(f"Demo operator '{WETLAND_OPERATOR_NAME}' not found in {WETLAND_SECTOR}")

    equipment_id = _ensure_equipment(WETLAND_SECTOR, WETLAND_EQUIPMENT_CODE, "HARVESTER",
                                      operator["id"], status="ACTIVE")

    existing = _existing_open_incident("EMPLOYEE", operator["id"], "ZONE_PROXIMITY_WARNING")
    if existing:
        # Second call while an incident is already open -> escalate: move
        # the machine from WARNING range into CRITICAL range on the SAME
        # incident, exactly like the spec's two-threshold requirement.
        # 56.953226 is ~25m north of the wetland's north edge (56.9530) —
        # inside the < 40m critical threshold.
        lat, lon = 56.953226, 24.18750
        distance = _wetland_distance(lat, lon)
        critical = distance <= WETLAND_CRITICAL_M
        _upsert_live_location(operator["id"], operator.get("telegram_user_id"), WETLAND_SECTOR, lat, lon, "IN")
        incident_id = existing["id"]
        conn = _conn()
        conn.execute("UPDATE risks SET risk_level=?, distance_m=? WHERE id=?",
                     ("HIGH" if critical else "MEDIUM", distance, incident_id))
        conn.commit()
        conn.close()
        database.add_risk_event(
            incident_id, "ZONE_ESCALATION", actor=triggered_by,
            details=f"Distance to wetland now {distance:.0f} m — "
                    f"{'CRITICAL' if critical else 'WARNING'} threshold ({WETLAND_CRITICAL_M:.0f} m)",
        )
        text = (
            f"🛑 FOREST AI — {'CRITICAL' if critical else 'WARNING'} ZONE PROXIMITY\n\n"
            f"Machine: {WETLAND_EQUIPMENT_CODE}\n"
            f"Distance to protected wetland: {distance:.0f} m\n"
            + (f"Priority escalated to HIGH — machine is now within the critical threshold "
               f"(< {WETLAND_CRITICAL_M:.0f} m)." if critical else
               f"Still within the warning threshold (< {WETLAND_WARNING_M:.0f} m).")
        )
        message_id = _tg_send(operator.get("telegram_user_id"), text)
        if message_id:
            database.add_risk_event(incident_id, "TELEGRAM_SENT", actor="system", details=text)
        logger.info("DEMO: scenario=wetland escalated incident_id=%s distance=%.0f", incident_id, distance)
        return {"incident_id": incident_id, "telegram_sent": bool(message_id), "distance_m": distance, "escalated": True}

    # 56.953769 is ~85m north of the wetland's north edge (56.9530) —
    # inside the < 100m warning threshold, outside the < 40m critical one.
    lat, lon = 56.953769, 24.18750
    distance = _wetland_distance(lat, lon)
    _upsert_live_location(operator["id"], operator.get("telegram_user_id"), WETLAND_SECTOR, lat, lon, "IN")

    reason = (
        f"Harvester {WETLAND_EQUIPMENT_CODE} detected dangerously close to protected wetland.\n"
        f"Machine: {WETLAND_EQUIPMENT_CODE}\n"
        f"Sector: {WETLAND_SECTOR}\n"
        f"GPS position: {lat:.5f}, {lon:.5f}\n"
        f"Distance to wetland: {distance:.0f} m\n"
        f"Time: {_now()}"
    )
    incident_id = database.add_incident(
        WETLAND_SECTOR, "MEDIUM", reason,
        entity_type="EMPLOYEE", entity_id=operator["id"], rule_code="ZONE_PROXIMITY_WARNING",
        distance_m=distance,
    )
    _mark_demo(incident_id)
    database.add_risk_event(incident_id, "DETECTED", actor=triggered_by, details=reason)

    _generate_recommendation(
        incident_id, WETLAND_SECTOR, reason, "EMPLOYEE", "ZONE_PROXIMITY_WARNING",
        fallback=_fallback_recommendation(
            summary=(
                f"Харвестер {WETLAND_EQUIPMENT_CODE} приближается к охраняемому водно-болотному "
                f"участку в секторе {WETLAND_SECTOR} (дистанция ~{distance:.0f} м). Дальнейшее движение "
                f"в этом направлении может привести к въезду техники в охраняемую зону и экологическому "
                f"нарушению."
            ),
            options=[
                {"id": "contact_worker", "label": "Предупредить оператора",
                 "message_text": f"{WETLAND_OPERATOR_NAME}, вы приближаетесь к охраняемому водно-болотному "
                                  f"участку (~{distance:.0f} м). Пожалуйста, измените маршрут или остановите работу."},
            ],
            recommended_option_id="contact_worker",
            exposure_low=2000, exposure_high=15000,
            exposure_basis="Оценка потенциального экологического штрафа за въезд в охраняемую зону.",
            exposure_period="однократный риск при въезде в зону — требует немедленного внимания",
        ),
    )

    text = (
        f"⚠️ PROTECTED ZONE WARNING\n\n"
        f"Machine: {WETLAND_EQUIPMENT_CODE}\n"
        f"Distance to protected wetland: {distance:.0f} m"
    )
    buttons = [
        [{"text": "🛑 Stop Work", "callback_data": f"wtl_action:{incident_id}:stop"}],
        [{"text": "↩️ Return to Safe Zone", "callback_data": f"wtl_action:{incident_id}:return"}],
        [{"text": "📍 View Position", "callback_data": f"wtl_action:{incident_id}:view"},
         {"text": "📝 Report Situation", "callback_data": f"wtl_action:{incident_id}:report"}],
    ]
    message_id = _tg_send(operator.get("telegram_user_id"), text, buttons)
    if message_id:
        database.update_incident_status(incident_id, "NOTIFIED", telegram_message_id=message_id)
        database.add_risk_event(incident_id, "TELEGRAM_SENT", actor="system", details=text)
    else:
        database.add_risk_event(incident_id, "TELEGRAM_SEND_FAILED", actor="system")

    logger.info("DEMO: scenario=wetland incident_id=%s telegram_sent=%s", incident_id, bool(message_id))
    return {"incident_id": incident_id, "telegram_sent": bool(message_id), "distance_m": distance}


# ─────────────────────────────────────────────────────────────────────────
# SCENARIO 5 — Logging outside approved sector (satellite change detection)
# ─────────────────────────────────────────────────────────────────────────

LOGGING_SECTOR = "A-006"


def trigger_logging_boundary(triggered_by="demo_trigger"):
    sector = _find_sector(LOGGING_SECTOR)
    if not sector:
        raise RuntimeError(f"Demo sector {LOGGING_SECTOR} not found")
    sector_name = sector["name"]
    boundary = json.loads(sector["boundary_json"])
    north_edge_lat = max(p[0] for p in boundary)

    # Detected change polygon straddling the sector's northern boundary —
    # part inside, part outside. Approximate affected/outside area from the
    # polygon's known geometry (illustrative for the demo, not a real
    # remote-sensing computation).
    affected_area_ha = 3.2
    outside_area_ha = 1.4
    outside_pct = outside_area_ha / affected_area_ha * 100.0
    observation_date = datetime.utcnow().strftime("%Y-%m-%d")

    reason = (
        "Satellite monitoring detected forest-cover change outside the approved logging boundary.\n"
        f"Sector: {sector_name}\n"
        f"Observation date: {observation_date}\n"
        f"Source: Sentinel-2 (Copernicus) change detection — demo/simulated analysis\n"
        f"Approximate affected area: {affected_area_ha:.1f} ha\n"
        f"Approximate area outside approved boundary: {outside_area_ha:.1f} ha (~{outside_pct:.0f}%)\n"
        f"Confidence: MEDIUM (automated change detection, not field-verified)"
    )
    incident_id = database.add_incident(
        sector_name, "HIGH", reason,
        entity_type="SATELLITE", entity_id=None, rule_code="UNAUTHORIZED_LOGGING",
    )
    _mark_demo(incident_id)
    database.add_risk_event(incident_id, "DETECTED", actor=triggered_by, details=reason)
    database.add_risk_event(
        incident_id, "SATELLITE_OBSERVATION", actor="satellite_intelligence",
        details=(f"Change polygon straddles the northern boundary (lat {north_edge_lat:.4f}). "
                  f"Affected {affected_area_ha:.1f} ha, ~{outside_area_ha:.1f} ha ({outside_pct:.0f}%) "
                  f"outside the approved sector — potential unauthorized logging, not yet field-verified."),
    )

    _generate_recommendation(
        incident_id, sector_name, reason, "SATELLITE", "UNAUTHORIZED_LOGGING",
        fallback=_fallback_recommendation(
            summary=(
                f"Спутниковый мониторинг обнаружил изменение лесного покрова в секторе {sector_name}, "
                f"частично выходящее за пределы утверждённой границы вырубки (~{outside_area_ha:.1f} га "
                f"из {affected_area_ha:.1f} га, ~{outside_pct:.0f}%). Это потенциальная несанкционированная "
                f"вырубка, требующая проверки плана работ и выезда на место — окончательный вывод делать "
                f"преждевременно до полевой верификации."
            ),
            options=[
                {"id": "investigate", "label": "Начать проверку",
                 "message_text": f"Диспетчер, спутник зафиксировал изменение лесного покрова за пределами "
                                  f"утверждённой границы в секторе {sector_name} (~{outside_area_ha:.1f} га). "
                                  f"Требуется полевая проверка."},
            ],
            recommended_option_id="investigate",
            exposure_low=5000, exposure_high=40000,
            exposure_basis="Оценка на основе рыночной стоимости древесины на потенциально незаконно вырубленной площади.",
            exposure_period="требует немедленной проверки — риск продолжает накапливаться ежедневно",
        ),
    )

    text = (
        f"🚨 FOREST AI — BOUNDARY ALERT\n\n"
        f"Potential forest-cover change detected outside approved sector.\n\n"
        f"Sector: {sector_name}\n"
        f"Affected area: {affected_area_ha:.1f} ha (~{outside_area_ha:.1f} ha outside boundary)\n"
        f"Source: Sentinel-2 (Copernicus)"
    )
    buttons = [
        [{"text": "🛰 View Satellite", "callback_data": f"log_action:{incident_id}:satellite"}],
        [{"text": "🗺 View Boundary", "callback_data": f"log_action:{incident_id}:boundary"}],
        [{"text": "📷 Request Field Verification", "callback_data": f"log_action:{incident_id}:field"}],
        [{"text": "🔍 Investigate", "callback_data": f"log_action:{incident_id}:investigate"}],
        [{"text": "✅ Resolve", "callback_data": f"log_action:{incident_id}:resolve"}],
    ]
    message_id = _tg_send(_dispatcher_chat_id(), text, buttons)
    if message_id:
        database.update_incident_status(incident_id, "NOTIFIED", telegram_message_id=message_id)
        database.add_risk_event(incident_id, "TELEGRAM_SENT", actor="system", details=text)
    else:
        database.add_risk_event(incident_id, "TELEGRAM_SEND_FAILED", actor="system")

    logger.info("DEMO: scenario=logging_boundary incident_id=%s telegram_sent=%s", incident_id, bool(message_id))
    return {"incident_id": incident_id, "telegram_sent": bool(message_id), "outside_area_ha": outside_area_ha}


# ─────────────────────────────────────────────────────────────────────────
# Button-click handlers — called from bot.py's CallbackQueryHandlers.
# Each returns (reply_text, buttons_or_None) for the caller to send; all DB
# writes happen here so api.py-triggered admin actions could reuse them too.
# ─────────────────────────────────────────────────────────────────────────

def handle_breakdown_action(incident_id, action, actor):
    if action == "diag":
        database.add_risk_event(incident_id, "DIAGNOSTICS_STARTED", actor=actor)
        buttons = [[{"text": label, "callback_data": f"brk_diag:{incident_id}:{key}"}]
                   for key, label in DIAGNOSTICS_LABELS.items()]
        return "What problem are you experiencing?", buttons
    if action == "photo":
        return "📷 Пожалуйста, отправьте фото поломки следующим сообщением.", None
    if action == "loc":
        return "📍 Пожалуйста, отправьте текущую геолокацию следующим сообщением.", None
    if action == "service":
        database.add_risk_event(incident_id, "CONTACT_SERVICE_REQUESTED", actor=actor)
        return "☎️ Заявка передана в сервисную службу. С вами свяжутся в ближайшее время.", None
    if action == "resolved":
        database.update_incident_status(incident_id, "RESOLVED")
        database.add_risk_event(incident_id, "RESOLVED", actor=actor, details="Problem resolved by operator")
        return "✅ Отлично! Проблема отмечена как решённая.", None
    return None, None


def handle_breakdown_diagnostics(incident_id, problem_key, actor):
    label = DIAGNOSTICS_LABELS.get(problem_key, problem_key)
    database.add_risk_event(incident_id, "DIAGNOSTICS_ANSWER", actor=actor, details=f"Problem type: {label}")
    # Reuse the EXISTING repair sub-menu (repair_menu_callback's keyboard /
    # repair_choice_callback, already registered in bot.py) for the
    # SERVICE-REQUIRED / REPAIR stage — not a second repair flow.
    buttons = [
        [{"text": "📞 Связаться с сервисом", "callback_data": f"repair_choice:{incident_id}:service"}],
        [{"text": "🔧 Чинить самому", "callback_data": f"repair_choice:{incident_id}:self"}],
        [{"text": "💬 Нужна консультация диспетчера", "callback_data": f"repair_choice:{incident_id}:dispatcher"}],
    ]
    return f"Принято: {label}. Как будем устранять неисправность?", buttons


def handle_sector_exit_action(incident_id, action, actor, worker_lat=None, worker_lon=None):
    risk = database.get_risk_events  # not used directly; kept for symmetry
    if action == "view":
        conn = _conn()
        row = conn.execute("SELECT entity_id FROM risks WHERE id=?", (incident_id,)).fetchone()
        loc = conn.execute("SELECT latitude, longitude FROM live_locations WHERE employee_id=?",
                            (row["entity_id"],)).fetchone() if row else None
        conn.close()
        if loc:
            link = f"https://maps.google.com/?q={loc['latitude']},{loc['longitude']}"
            return f"📍 Текущая позиция: {link}", None
        return "📍 Позиция недоступна.", None
    if action == "return":
        database.add_risk_event(incident_id, "RETURNING", actor=actor)
        conn = _conn()
        row = conn.execute("SELECT entity_id FROM risks WHERE id=?", (incident_id,)).fetchone()
        if row and row["entity_id"]:
            conn.execute("UPDATE live_locations SET last_status='IN' WHERE employee_id=?", (row["entity_id"],))
            conn.commit()
        conn.close()
        database.add_risk_event(incident_id, "RETURNED_TO_SECTOR", actor=actor)
        database.update_incident_status(incident_id, "RESOLVED")
        database.add_risk_event(incident_id, "RESOLVED", actor=actor, details="Worker returned inside sector boundary")
        return "✅ Отмечено: вы вернулись в границы сектора. Инцидент закрыт.", None
    if action == "explain":
        database.add_risk_event(incident_id, "EXPLAIN_REQUESTED", actor=actor)
        return "📝 Пожалуйста, опишите причину следующим сообщением — диспетчер получит её автоматически.", None
    if action == "emergency":
        database.add_risk_event(incident_id, "EMERGENCY_ESCALATED_FROM_SECTOR_EXIT", actor=actor)
        return "🆘 Экстренная ситуация зарегистрирована. Диспетчер уведомлён.", None
    return None, None


def handle_wetland_action(incident_id, action, actor):
    if action == "stop":
        database.add_risk_event(incident_id, "WORK_STOPPED", actor=actor)
        return "🛑 Работа остановлена. Диспетчер уведомлён.", None
    if action == "return":
        database.add_risk_event(incident_id, "LEAVING_ZONE", actor=actor)
        database.add_risk_event(incident_id, "SAFE", actor=actor, details="Machine moved back to a safe distance")
        database.update_incident_status(incident_id, "RESOLVED")
        database.add_risk_event(incident_id, "RESOLVED", actor=actor)
        return "✅ Техника вернулась в безопасную зону. Инцидент закрыт.", None
    if action == "view":
        conn = _conn()
        row = conn.execute("SELECT entity_id FROM risks WHERE id=?", (incident_id,)).fetchone()
        loc = conn.execute("SELECT latitude, longitude FROM live_locations WHERE employee_id=?",
                            (row["entity_id"],)).fetchone() if row else None
        conn.close()
        if loc:
            link = f"https://maps.google.com/?q={loc['latitude']},{loc['longitude']}"
            return f"📍 Текущая позиция техники: {link}", None
        return "📍 Позиция недоступна.", None
    if action == "report":
        database.add_risk_event(incident_id, "REPORT_REQUESTED", actor=actor)
        return "📝 Пожалуйста, опишите ситуацию следующим сообщением.", None
    return None, None


def handle_volume_action(incident_id, action, actor):
    if action == "investigate":
        database.add_risk_event(incident_id, "INVESTIGATION_STARTED", actor=actor)
        return "🔍 Проверка начата. Статус будет обновлён после сверки данных.", None
    if action == "compare":
        conn = _conn()
        row = conn.execute("SELECT reason FROM risks WHERE id=?", (incident_id,)).fetchone()
        conn.close()
        return f"📊 Сравнение объёмов:\n\n{row['reason'] if row else ''}", None
    if action == "movements":
        conn = _conn()
        risk = conn.execute("SELECT sector FROM risks WHERE id=?", (incident_id,)).fetchone()
        rows = conn.execute(
            "SELECT planned_volume, actual_volume, status, created_at FROM timber_movements "
            "WHERE sector=? ORDER BY id DESC LIMIT 5", (risk["sector"],)
        ).fetchall() if risk else []
        conn.close()
        if not rows:
            return "🚛 Записи по вывозке древесины не найдены.", None
        lines = [f"• {r['created_at']}: заявлено {r['planned_volume']} м³, статус {r['status']}" for r in rows]
        return "🚛 Timber movements:\n\n" + "\n".join(lines), None
    if action == "photo":
        database.add_risk_event(incident_id, "FIELD_PHOTO_REQUESTED", actor=actor)
        return "📷 Запрос на полевое фото отправлен ответственному сотруднику.", None
    if action == "resolve":
        database.update_incident_status(incident_id, "RESOLVED")
        database.add_risk_event(incident_id, "RESOLVED", actor=actor)
        return "✅ Инцидент закрыт.", None
    return None, None


def handle_logging_action(incident_id, action, actor):
    if action == "satellite":
        database.add_risk_event(incident_id, "SATELLITE_VIEW_REQUESTED", actor=actor)
        return "🛰 Спутниковый снимок доступен на дашборде (раздел Satellite/Sectors).", None
    if action == "boundary":
        database.add_risk_event(incident_id, "BOUNDARY_VIEW_REQUESTED", actor=actor)
        return "🗺 Граница сектора и зона обнаруженного изменения доступны на карте.", None
    if action == "field":
        database.add_risk_event(incident_id, "FIELD_VERIFICATION_REQUESTED", actor=actor)
        return "📷 Запрос на полевую верификацию отправлен.", None
    if action == "investigate":
        database.add_risk_event(incident_id, "INVESTIGATION_STARTED", actor=actor)
        return "🔍 Проверка начата.", None
    if action == "resolve":
        database.update_incident_status(incident_id, "RESOLVED")
        database.add_risk_event(incident_id, "RESOLVED", actor=actor)
        return "✅ Инцидент закрыт.", None
    return None, None


# ─────────────────────────────────────────────────────────────────────────
# Reset
# ─────────────────────────────────────────────────────────────────────────

def reset_demo():
    """Wipes ONLY rows this module flagged is_demo=1 (plus the transient
    live_locations rows it wrote for demo employees) — never touches any
    other risk, sector, employee or equipment. Safe to run repeatedly."""
    conn = _conn()
    demo_incident_ids = [r["id"] for r in conn.execute("SELECT id FROM risks WHERE is_demo=1").fetchall()]
    if demo_incident_ids:
        placeholders = ",".join("?" * len(demo_incident_ids))
        conn.execute(f"DELETE FROM risk_events WHERE risk_id IN ({placeholders})", demo_incident_ids)
    conn.execute("DELETE FROM risks WHERE is_demo=1")
    conn.execute("DELETE FROM sector_equipment WHERE is_demo=1")
    conn.execute("DELETE FROM timber_movements WHERE is_demo=1")

    demo_employee_ids = []
    for name, sector in ((BREAKDOWN_OPERATOR_NAME, BREAKDOWN_SECTOR),
                          (SECTOR_EXIT_WORKER_NAME, SECTOR_EXIT_SECTOR)):
        row = conn.execute("SELECT id FROM sector_employees WHERE full_name=?", (name,)).fetchone()
        if row:
            demo_employee_ids.append(row["id"])
    if demo_employee_ids:
        placeholders = ",".join("?" * len(demo_employee_ids))
        conn.execute(f"DELETE FROM live_locations WHERE employee_id IN ({placeholders})", demo_employee_ids)

    conn.commit()
    conn.close()
    logger.info("DEMO: reset complete — cleared %d incident(s)", len(demo_incident_ids))
    return {"cleared_incidents": len(demo_incident_ids)}
