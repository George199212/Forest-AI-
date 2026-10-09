"""
Background AI analysis for risks created without one.

Risks are inserted from many places (bot.py add_risk/add_incident, api.py,
services/*, ad-hoc scripts calling database.add_risk directly). Instead of
hooking every creator, one daemon thread inside forest-api polls `risks` and
generates the missing analysis, so creating a risk never waits on — or fails
because of — the Anthropic API.

State lives in risks.ai_status (NULL | REQUESTED | RUNNING | DONE | FAILED)
and risks.ai_attempts. Every paid call is logged as an AI_ANALYSIS_REQUESTED
risk_event (this is also what the daily cap and stale-RUNNING recovery read),
every failure as AI_ANALYSIS_FAILED. Existing AI output is never overwritten.
"""

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import database
from services.ai_resolution import generate_incident_recommendation

# ── Cost guards / timing ──────────────────────────────────────────────────────
AI_WORKER_INTERVAL_S  = 60    # polling period; one risk analysed per cycle at most
AI_WORKER_MIN_AGE_S   = 120   # let inline generators and post-insert is_demo flips finish first
AI_RUNNING_STALE_S    = 600   # RUNNING longer than this goes back to the queue (attempt stays used)
AI_MAX_ATTEMPTS       = 2     # per risk; after that the risk is FAILED until a manual Retry
AI_MAX_PER_UTC_DAY    = 30    # paid calls per UTC day, retries included
AI_AUTO_FIRST_RISK_ID = 60    # first risk id created after this feature shipped; older risks only on explicit request
AI_DEFAULT_MODEL      = "claude-sonnet-4-5"   # same model the existing incident pipeline uses; override via ANTHROPIC_MODEL

EXTRA_BLOCK_TEMPLATE = (
    "\n\nAdditional context:\n"
    "Risk level: {risk_level}\n"
    "Recorded at (UTC): {created_at}\n"
    "Current date (UTC): {today}\n\n"
    "Strict rules — these take precedence over any other instruction in this prompt:\n"
    "1. Use only the data given in this prompt. In the summary, state explicitly which data is "
    "missing (for example: no timber volume, no price basis, no confirmed damage, no worker or "
    "equipment involved).\n"
    "2. If the data contains no volume or price basis, set estimated_exposure_eur_low and "
    "estimated_exposure_eur_high to null and make exposure_basis say why no estimate is possible. "
    "Never estimate money without a stated basis taken from the data.\n"
    "3. If the event text describes a forecast, a warning or an unconfirmed event, say so explicitly "
    "and do not describe damage as having occurred."
)

_started = False
_start_lock = threading.Lock()


def _conn():
    conn = sqlite3.connect(database.DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.utcnow()


def _parse_ts(s):
    """risks.created_at comes in two formats: add_risk() ISO ('2026-10-09T01:35:55.231189')
    and add_incident()/add_risk_event() ('2026-10-09 01:35:55 UTC')."""
    if not s:
        return None
    s = str(s).replace(" UTC", "").replace("T", " ")[:19]
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _has_ai(r):
    return bool(r["ai_recommendation"])


def _excluded(r):
    return bool(r["is_demo"]) or (r["sector"] or "").startswith("TEST") or (r["reason"] or "").startswith("[TEST]")


def ai_state(r):
    """What the risk card shows: done | in_progress | failed | none (not eligible for auto analysis)."""
    if _has_ai(r):
        return "done"
    if _excluded(r) or r["status"] != "OPEN":
        return "none"
    status = r["ai_status"]
    if status == "FAILED":
        return "failed"
    if status in ("REQUESTED", "RUNNING"):
        return "in_progress"
    if status is None and r["id"] >= AI_AUTO_FIRST_RISK_ID and (r["ai_attempts"] or 0) < AI_MAX_ATTEMPTS:
        return "in_progress"
    return "none"


def calls_today():
    today = _now().strftime("%Y-%m-%d")
    conn = _conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM risk_events WHERE event_type='AI_ANALYSIS_REQUESTED' AND created_at LIKE ?",
        (today + "%",),
    ).fetchone()[0]
    conn.close()
    return n


def recover_stale_running():
    """RUNNING for longer than AI_RUNNING_STALE_S (restart/crash mid-call) goes back to the
    queue; the attempt was already counted when the risk was claimed."""
    conn = _conn()
    rows = conn.execute(
        "SELECT r.id, r.ai_attempts, "
        "  (SELECT MAX(e.created_at) FROM risk_events e "
        "   WHERE e.risk_id=r.id AND e.event_type='AI_ANALYSIS_REQUESTED') AS requested_at "
        "FROM risks r WHERE r.ai_status='RUNNING'"
    ).fetchall()
    conn.close()
    for row in rows:
        started = _parse_ts(row["requested_at"])
        if started and (_now() - started).total_seconds() <= AI_RUNNING_STALE_S:
            continue
        new_status = "FAILED" if (row["ai_attempts"] or 0) >= AI_MAX_ATTEMPTS else None
        conn = _conn()
        cur = conn.execute("UPDATE risks SET ai_status=? WHERE id=? AND ai_status='RUNNING'", (new_status, row["id"]))
        conn.commit()
        changed = cur.rowcount
        conn.close()
        if changed:
            database.add_risk_event(row["id"], "AI_ANALYSIS_FAILED", actor="ai_worker",
                                    details=f"stale RUNNING since {row['requested_at'] or 'unknown'}; requeued")


def _candidates():
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM risks WHERE status='OPEN' AND COALESCE(is_demo,0)=0 "
        "AND substr(COALESCE(sector,''),1,4) != 'TEST' AND substr(COALESCE(reason,''),1,6) != '[TEST]' "
        "AND (ai_recommendation IS NULL OR ai_recommendation='') "
        "AND COALESCE(ai_attempts,0) < ? "
        "AND (ai_status IS NULL OR ai_status='REQUESTED') "
        "AND (id >= ? OR ai_status='REQUESTED') ORDER BY id",
        (AI_MAX_ATTEMPTS, AI_AUTO_FIRST_RISK_ID),
    ).fetchall()
    conn.close()
    now = _now()
    return [r for r in rows
            if (_parse_ts(r["created_at"]) or now) <= now - timedelta(seconds=AI_WORKER_MIN_AGE_S)]


def _valid_recommendation(text):
    try:
        rec = json.loads(text)
    except Exception:
        return False
    return isinstance(rec, dict) and bool(rec.get("summary")) and isinstance(rec.get("options"), list) and bool(rec["options"])


def analyse_risk(risk_id):
    """Idempotent: generates and stores the analysis for one risk. Does nothing if the risk
    already has one, is not eligible, is already claimed, or the daily cap is reached.
    Returns a short status string."""
    conn = _conn()
    r = conn.execute("SELECT * FROM risks WHERE id=?", (risk_id,)).fetchone()
    conn.close()
    if not r:
        return "not_found"
    if _has_ai(r):
        return "exists"
    if _excluded(r) or r["status"] != "OPEN":
        return "ineligible"
    if r["ai_status"] not in (None, "REQUESTED") or (r["ai_attempts"] or 0) >= AI_MAX_ATTEMPTS:
        return "skipped"
    if calls_today() >= AI_MAX_PER_UTC_DAY:
        return "daily_cap"

    conn = _conn()
    cur = conn.execute(
        "UPDATE risks SET ai_status='RUNNING', ai_attempts=COALESCE(ai_attempts,0)+1 "
        "WHERE id=? AND (ai_status IS NULL OR ai_status='REQUESTED') "
        "AND (ai_recommendation IS NULL OR ai_recommendation='') AND COALESCE(ai_attempts,0) < ?",
        (risk_id, AI_MAX_ATTEMPTS),
    )
    conn.commit()
    claimed = cur.rowcount
    attempts = conn.execute("SELECT ai_attempts FROM risks WHERE id=?", (risk_id,)).fetchone()[0]
    conn.close()
    if not claimed:
        return "skipped"

    model = os.environ.get("ANTHROPIC_MODEL") or AI_DEFAULT_MODEL
    database.add_risk_event(risk_id, "AI_ANALYSIS_REQUESTED", actor="ai_worker",
                            details=f"attempt {attempts}/{AI_MAX_ATTEMPTS}, model {model}")
    created = _parse_ts(r["created_at"])
    text = generate_incident_recommendation({
        "sector": r["sector"], "reason": r["reason"],
        "entity_type": r["entity_type"], "rule_code": r["rule_code"],
        "extra_prompt_block": EXTRA_BLOCK_TEMPLATE.format(
            risk_level=r["risk_level"] or "unknown",
            created_at=created.strftime("%Y-%m-%d %H:%M") if created else "unknown",
            today=_now().strftime("%Y-%m-%d"),
        ),
    }, model=model)

    if text and _valid_recommendation(text):
        conn = _conn()
        cur = conn.execute(
            "UPDATE risks SET ai_recommendation=?, ai_status='DONE' "
            "WHERE id=? AND (ai_recommendation IS NULL OR ai_recommendation='')",
            (text, risk_id),
        )
        conn.commit()
        saved = cur.rowcount
        if not saved:
            conn.execute("UPDATE risks SET ai_status='DONE' WHERE id=? AND ai_status='RUNNING'", (risk_id,))
            conn.commit()
        conn.close()
        if saved:
            database.add_risk_event(risk_id, "AI_RECOMMENDATION_GENERATED", actor="ai")
        return "done"

    reason = "no response from model (see forest-api log)" if not text else "model output is not a valid recommendation JSON"
    new_status = "FAILED" if attempts >= AI_MAX_ATTEMPTS else None
    conn = _conn()
    conn.execute("UPDATE risks SET ai_status=? WHERE id=? AND ai_status='RUNNING'", (new_status, risk_id))
    conn.commit()
    conn.close()
    database.add_risk_event(risk_id, "AI_ANALYSIS_FAILED", actor="ai_worker",
                            details=f"attempt {attempts}/{AI_MAX_ATTEMPTS}: {reason}")
    return "failed"


def request_retry(risk_id):
    """Manual Retry / explicit request: queue the risk for the worker (no AI call here).
    The daily cap still applies when the worker picks it up. Returns (http_status, payload)."""
    conn = _conn()
    r = conn.execute("SELECT * FROM risks WHERE id=?", (risk_id,)).fetchone()
    if not r:
        conn.close()
        return 404, {"error": "Not found"}
    if _has_ai(r):
        conn.close()
        return 409, {"error": "AI analysis already exists"}
    if _excluded(r):
        conn.close()
        return 400, {"error": "Demo and TEST risks are not analysed"}
    if r["status"] != "OPEN":
        conn.close()
        return 400, {"error": "Only OPEN risks are analysed"}
    cur = conn.execute(
        "UPDATE risks SET ai_status='REQUESTED', ai_attempts=0 "
        "WHERE id=? AND (ai_status IS NULL OR ai_status IN ('FAILED','REQUESTED'))",
        (risk_id,),
    )
    conn.commit()
    queued = cur.rowcount
    conn.close()
    if not queued:
        return 409, {"error": "AI analysis is already running"}
    used = calls_today()
    payload = {"ok": True, "queued": True, "calls_today": used, "daily_cap": AI_MAX_PER_UTC_DAY}
    if used >= AI_MAX_PER_UTC_DAY:
        payload["note"] = "Daily AI cap reached; the analysis will run after 00:00 UTC."
    return 200, payload


def tick():
    recover_stale_running()
    if calls_today() >= AI_MAX_PER_UTC_DAY:
        return None
    for r in _candidates():
        return analyse_risk(r["id"])
    return None


def _loop():
    while True:
        try:
            tick()
        except Exception as e:
            print(f"risk_ai_worker tick failed: {e}")
        time.sleep(AI_WORKER_INTERVAL_S)


def start():
    """Start the worker thread once per process (called from api.py's startup hook)."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="risk-ai-worker", daemon=True).start()
