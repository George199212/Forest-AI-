"""/api/sat-monitoring/* routes (Stage 2). Mounted by api.py with the app's Basic Auth dependency.

Read routes: satellite.db read-only (store.ro). Write routes: small rows only (store.rw) - jobs for the worker, or
a review. CREATE_RISK is the only path to a risk (no automatic risks, D3). Existing /api/satellite/* and
/api/satellite-intel/* are untouched (D1).
"""
import os
from typing import Optional

import requests
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import risk_bridge, store

TELEGRAM_SEND = "https://api.telegram.org/bot{token}/sendMessage"


class AreaIn(BaseModel):
    source: str
    source_ref: str
    name: str
    geometry: Optional[dict] = None


class FetchIn(BaseModel):
    area_id: Optional[int] = None
    all: bool = False


class ReviewIn(BaseModel):
    decision: str
    note: Optional[str] = None


def _err(e: store.StoreError):
    return JSONResponse(status_code=e.status, content={"error": e.message, **e.extra})


def _center(geojson):
    """Rough centre of the change polygons (bbox middle), for the field-check message. None if unknown."""
    xs, ys = [], []

    def walk(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        elif isinstance(c, (list, tuple)):
            for x in c:
                walk(x)
    for f in (geojson or {}).get("features", []):
        walk((f.get("geometry") or {}).get("coordinates"))
    if not xs:
        return None
    return round((min(ys) + max(ys)) / 2, 6), round((min(xs) + max(xs)) / 2, 6)


def field_check_text(ev, area, actor, note):
    c = _center(store._j(ev.get("change_geojson")))
    lines = ["Forest AI - field check requested (satellite monitoring)",
             f"Area: {area['name']} ({area['source']} {area['source_ref']})",
             store.event_summary(ev),
             f"Observed: {ev['first_after_time_utc'][:10]} .. {ev['last_after_time_utc'][:10]}; "
             f"confidence {ev['confidence']}",
             f"Location (approx.): {c[0]}, {c[1]}" if c else "Location: unknown",
             f"Requested by: {actor}"]
    if note:
        lines.append(f"Note: {note.strip()[:500]}")
    return "\n".join(lines)


def send_dispatcher(text):
    """Existing send path: Bot API sendMessage to DISPATCHER_CHAT_ID (as api.py / bot.py do). Never logs the token.
    Returns (ok, error_message)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("DISPATCHER_CHAT_ID", "").strip()
    if not token or not chat:
        return False, "Telegram dispatcher not configured (TELEGRAM_BOT_TOKEN / DISPATCHER_CHAT_ID)"
    try:
        r = requests.post(TELEGRAM_SEND.format(token=token), json={"chat_id": chat, "text": text}, timeout=10)
        data = r.json()
    except Exception as e:                     # message text of requests errors can contain the URL -> type only
        return False, f"Telegram send failed ({type(e).__name__})"
    if not data.get("ok"):
        return False, f"Telegram send failed: {str(data.get('description', ''))[:200]}"
    return True, None


def router(verify_credentials, sender=None, database=None, recommend=None):
    """sender/database/recommend are injectable for tests (defaults: send_dispatcher, the app's `database`,
    services.ai_resolution)."""
    send = sender or send_dispatcher
    r = APIRouter(prefix="/api/sat-monitoring", dependencies=[Depends(verify_credentials)])

    @r.get("/overview")
    def overview():
        try:
            return store.overview()
        except store.StoreError as e:
            return _err(e)

    @r.get("/areas/{area_id}")
    def area(area_id: int):
        try:
            return store.area_detail(area_id)
        except store.StoreError as e:
            return _err(e)

    @r.post("/areas", status_code=202)
    def add_area(body: AreaIn, username: str = Depends(verify_credentials)):
        try:
            return store.queue_add_area(body.source, body.source_ref, body.name, body.geometry, username)
        except store.StoreError as e:
            return _err(e)

    @r.post("/areas/{area_id}/stop", status_code=202)
    def stop_area(area_id: int, username: str = Depends(verify_credentials)):
        try:
            return store.queue_stop_area(area_id, username)
        except store.StoreError as e:
            return _err(e)

    @r.post("/fetch", status_code=202)
    def fetch(body: FetchIn, username: str = Depends(verify_credentials)):
        try:
            return store.queue_fetch(body.area_id, body.all, username)
        except store.StoreError as e:
            return _err(e)

    @r.get("/events/{event_id}")
    def event(event_id: int):
        try:
            return store.event_detail(event_id)
        except store.StoreError as e:
            return _err(e)

    @r.post("/events/{event_id}/review")
    def review(event_id: int, body: ReviewIn, username: str = Depends(verify_credentials)):
        d = (body.decision or "").strip().upper()
        try:
            if d not in store.REVIEW_DECISIONS:
                raise store.StoreError(422, "decision must be one of " + ", ".join(store.REVIEW_DECISIONS))
            ev, area_row = store.load_current_event(event_id)
            if d == "CREATE_RISK":
                if ev["risk_id"] is not None:
                    raise store.StoreError(409, "event already linked to a risk", risk_id=ev["risk_id"])
                risk_id, created = risk_bridge.create_risk(ev, area_row, username, database=database,
                                                           recommend=recommend)
                res = store.apply_review(event_id, d, username, body.note, risk_id=risk_id)
                return {**res, "risk_created": created}
            if d == "FIELD_CHECK":
                if ev["status"] == "FIELD_CHECK_REQUESTED":
                    raise store.StoreError(409, "field check already requested")
                ok, err = send(field_check_text(ev, area_row, username, body.note))
                if not ok:
                    raise store.StoreError(502, err)
                res = store.apply_review(event_id, d, username, body.note, expected_status=ev["status"])
                return {**res, "telegram_sent": True}
            res = store.apply_review(event_id, d, username, body.note, expected_status=ev["status"])
            if res["risk_id"] is not None:
                if d == "REJECT":
                    risk_bridge.note_review(res["risk_id"], "REJECTED", username, body.note, database=database)
                elif d == "UNDO" and res["undone_review"]["action"] == "REJECT":
                    risk_bridge.note_review(res["risk_id"], "REJECT_UNDONE", username, body.note, database=database)
            return res
        except store.StoreError as e:
            return _err(e)

    @r.get("/file/{acq_id}/{kind}")
    def file(acq_id: int, kind: str):
        try:
            p = store.quicklook_file(acq_id, kind)
        except store.StoreError as e:
            return _err(e)
        return FileResponse(str(p), media_type="image/png",
                            headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})

    @r.get("/health")
    def health():
        try:
            return store.health()
        except store.StoreError as e:
            return _err(e)

    return r
