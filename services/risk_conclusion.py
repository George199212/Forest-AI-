"""
Final conclusion ("Slēdziens") for a risk.

The evidence package is assembled in code and shown as-is. The recommendation (close / keep open) is
decided by fixed rules in code (R0-R3), never by the model. One optional AI call writes the conclusion
text from the evidence and the rule result; a code check rejects text that names a cause, mentions money,
claims full coverage or talks about closing/keeping the risk open (that sentence is written by code).

A human then either accepts and closes the risk (through the existing status mechanism:
database.update_incident_status(..., "RESOLVED") + a RESOLVED risk event) or keeps working on it
(interim conclusion). Drafts and decisions are stored in risk_conclusions; nothing is overwritten:
a newer conclusion marks the older one SUPERSEDED. Every action and paid call is a risk_events row.
"""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import database
from services import photo_compare
from services.ai_resolution import _get_client

# ── Rules / guards ────────────────────────────────────────────────────────────
MIN_COMPARED_SHARE    = 0.5    # R2: compared points below this share of all points -> keep open
MAX_ATTEMPTS_PER_CALL = 2      # paid attempts per generated conclusion text
AI_DEFAULT_MODEL      = "claude-sonnet-4-5"   # override via ANTHROPIC_MODEL
AI_DEFAULT_LANGUAGE   = "lv"                  # override via AI_OUTPUT_LANGUAGE
LANGUAGE_NAMES = {"lv": "Latvian", "ru": "Russian", "en": "English"}
LOCAL_TZ = ZoneInfo("Europe/Riga")
NO_DATA = "nav datu"

CLOSE, KEEP_OPEN = "CLOSE", "KEEP_OPEN"
RECOMMENDATION_LV = {CLOSE: "Slēgt risku", KEEP_OPEN: "Atstāt risku atvērtu"}
OUTCOME = {
    "R1": "Bojājumi apstiprināti",
    "R2": "Pārbaudīts daļēji, nepieciešama atkārtota fotografēšana",
    "R3a": "Izmaiņas konstatētas, bojājumi nav apstiprināti",
    "R3": "Salīdzināmajās zonās izmaiņas nav konstatētas",
}
KIND_LV = {"object_appeared": "Parādījies objekts", "object_disappeared": "Pazudis objekts",
           "fallen_tree": "Nogāzts koks", "broken_tree_part": "Nolūzusi koka daļa",
           "object_moved": "Pārvietots objekts", "ground_damage": "Zemes virsmas bojājums",
           "path_or_structure_change": "Takas vai būves izmaiņas", "transient_object": "Īslaicīgs objekts",
           "other": "Cits"}
CLASS_LV = {"possible_change": "iespējamas izmaiņas", "possible_damage": "iespējams bojājums"}
AGAINST_LABEL = "slēgts pretēji sistēmas ieteikumam"
CLOSED_STATUSES = ("RESOLVED", "DISMISSED")

# Model text: no cause, no percentage (photo_compare's list), no money, no coverage claim, and no
# close/keep-open wording (the recommendation sentence is written by code, so the text cannot contradict it).
MONEY_TEXT = re.compile(r"€|\b(eur|eiro|euro)\b", re.IGNORECASE)
COVERAGE_TEXT = re.compile(r"\bvis\w*\s+(teritorij|sektor|mež|platīb|objekt)\w*|\bpilnīb\w*|\bpilnīg\w*|\b100\b|"
                           r"\b(entire|whole)\b", re.IGNORECASE)
# "No changes" wording, rejected whenever a confirmed change, a re-shoot mark or an active observation exists.
NO_CHANGE_TEXT = re.compile(r"izmaiņ\w*\s+(nav|netika|netiek)\s+(\w+\s+)?konstatēt\w*|(nav|netika)\s+konstatēt\w*\s+(\w+\s+)?izmaiņ\w*|"
                            r"izmaiņu\s+nav\b", re.IGNORECASE)
DECISION_TEXT = re.compile(r"\bslēg\w*|\batvērt\w*|\bclos\w*|\bopen\w*", re.IGNORECASE)

PROMPT = (
    "You write the text of the final conclusion for one forest risk record. Use ONLY the data below.\n\n"
    "Rule result (decided by code, binding, already shown to the reader separately):\n"
    "- outcome: \"{outcome}\"\n- rule: {rule_line}\n\n"
    "Evidence (JSON; \"nav datu\" means the data is not available, it never means zero):\n{evidence}\n\n"
    "Write 4 to 7 sentences of plain text in {language}, covering in this order:\n"
    "1. what was checked: which photos, dates and how many photo points were compared out of how many;\n"
    "2. what was found in the compared points: name every entry of \"confirmed_changes\" and "
    "\"active_observations\" (point and what was seen); if both lists are empty, say no confirmed findings;\n"
    "3. what was not checked or could not be compared (points with one photo only, points that were not "
    "comparable, everything outside the photographed points);\n"
    "4. the next practical step that follows from the outcome.\n\n"
    "Rules:\n"
    "- Use only the data given. If a value is \"nav datu\", say it is not available; never treat it as zero.\n"
    "- Refer to the risk only as \"reģistrētais risks\"; do not describe or quote what the risk is about.\n"
    "- Describe only what was seen. Name no cause of any kind: not weather, season, nature, people, animals, "
    "machines or any event. Do not mention the weather at all; it is shown separately.\n"
    "- No money amounts, no currency, no estimates. No percentages.\n"
    "- Speak only about the photographed points. Do not use the words \"visa teritorija\", \"viss sektors\", "
    "\"viss mežs\", \"pilnībā\" or \"pilnīgi\".\n"
    "- Do not write whether the risk should be closed or kept open; do not use the words \"slēgt\" or "
    "\"atvērt\" in any form. That sentence is added by the system.\n"
    "- Do not contradict the outcome.\n"
    "- In the text call the photos only \"bāzes foto\" and \"pēcfoto\". No English words, no markdown.\n"
    "Return ONLY JSON: {{\"text\": \"...\"}}"
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _conn():
    conn = sqlite3.connect(database.DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse_utc(s):
    """Stored times are UTC: "YYYY-MM-DD HH:MM:SS UTC" or naive ISO ("2026-10-09T01:35:55.231189")."""
    if not s:
        return None
    t = str(s).replace(" UTC", "").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def local(s):
    d = _parse_utc(s)
    return d.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M") if d else NO_DATA


def _local_day(d):
    return f"{d[8:10]}.{d[5:7]}.{d[0:4]}" if d and len(d) == 10 else NO_DATA


def _lv_photo_names(t):
    """Stored model text may name the photos in English; use the Latvian names (same rule as the UI)."""
    def sub(m):
        lv = "bāzes foto" if m.group(1).upper() == "BASELINE" else "pēcfoto"
        before = m.string[:m.start()]
        return lv[0].upper() + lv[1:] if (not before.strip() or re.search(r"[.!?]\s*$", before)) else lv
    return re.sub(r"\b(BASELINE|FOLLOW-UP)(\s+(fotogrāfij|fotoattēl|attēl|foto)\w*)?", sub, t or "", flags=re.IGNORECASE)


def _risk_event(risk_id, event_type, actor, details=None):
    if details is not None and not isinstance(details, str):
        details = json.dumps(details, ensure_ascii=False)
    database.add_risk_event(risk_id, event_type, actor=actor, details=details)


# ── Evidence package ──────────────────────────────────────────────────────────
def _linked_run(conn, risk):
    """Latest photo-comparison run of the risk's sector whose follow-up date is not before the risk."""
    created = _parse_utc(risk["created_at"])
    day = created.strftime("%Y-%m-%d") if created else "0000-00-00"
    r = conn.execute("SELECT id FROM photo_cmp_runs WHERE sector=? AND followup_date>=? ORDER BY id DESC LIMIT 1",
                     (risk["sector"], day)).fetchone()
    return r["id"] if r else None


def build_evidence(risk_id):
    conn = _conn()
    risk = conn.execute("SELECT * FROM risks WHERE id=?", (risk_id,)).fetchone()
    if not risk:
        conn.close()
        return None
    risk = dict(risk)
    events = [{"type": e["event_type"], "actor": e["actor"] or "", "time": local(e["created_at"])}
              for e in conn.execute("SELECT * FROM risk_events WHERE risk_id=? ORDER BY id", (risk_id,))]
    created = _parse_utc(risk["created_at"])

    # Field activity in the sector since the risk was recorded (UTC comparison in code).
    sessions = []
    for s in conn.execute("SELECT id, employee, check_in_time, finish_time FROM work_sessions WHERE sector=? "
                          "ORDER BY id", (risk["sector"],)):
        t = _parse_utc(s["check_in_time"])
        if created and t and t >= created:
            sessions.append({"id": s["id"], "employee": s["employee"] or NO_DATA,
                             "check_in": local(s["check_in_time"]),
                             "finish": local(s["finish_time"]) if s["finish_time"] else "nav pabeigta"})
    photos_by_day = {}
    for p in conn.execute("SELECT uploaded_at FROM work_photos WHERE sector=?", (risk["sector"],)):
        t = _parse_utc(p["uploaded_at"])
        if created and t and t >= created:
            day = t.astimezone(LOCAL_TZ).strftime("%d.%m.%Y")
            photos_by_day[day] = photos_by_day.get(day, 0) + 1
    run_id = _linked_run(conn, risk)
    conn.close()

    ev = {
        "risk": {"id": risk["id"], "sector": risk["sector"], "level": risk["risk_level"] or NO_DATA,
                 "status": risk["status"] or "OPEN", "text": risk["reason"] or NO_DATA,
                 "created": local(risk["created_at"]), "events": events},
        "photo_comparison": NO_DATA,
        "field_activity": {
            "since": local(risk["created_at"]),
            "sessions": sessions if sessions else NO_DATA,
            "session_count": len(sessions) if sessions else NO_DATA,
            "photos_by_day": dict(sorted(photos_by_day.items(), key=lambda kv: kv[0][6:] + kv[0][3:5] + kv[0][:2]))
                             if photos_by_day else NO_DATA,
        },
    }
    if run_id:
        data = photo_compare.get_run(run_id)
        rep, points = data["report"], data["points"]
        system = [c for p in points for c in p["changes"] if c["source"] == "system" and not c["discarded"]]
        human = [c for p in points for c in p["changes"] if c["source"] == "human"]
        by_status = {s: sum(1 for c in system if c["review_status"] == s)
                     for s in ("UNREVIEWED", "CONFIRMED", "REJECTED", "RESHOOT")}
        seq = {c["id"]: f"P{p['seq']}" for p in points for c in p["changes"]}
        ev["photo_comparison"] = {
            "run_id": run_id,
            "photos": {_local_day(data["run"]["baseline_date"]): rep["photos_baseline"],
                       _local_day(data["run"]["followup_date"]): rep["photos_followup"]},
            "baseline_date": _local_day(data["run"]["baseline_date"]),
            "followup_date": _local_day(data["run"]["followup_date"]),
            "points_total": rep["points_total"],
            "points_compared": rep["points_compared"],
            "points_not_comparable": rep["points_not_comparable"],
            "points_one_sided": rep["points_no_followup"] + rep["points_no_baseline"],
            "system_changes_by_review_status": by_status,
            "system_changes_rejected": rep.get("changes_rejected_by_reviewer", 0),
            "system_changes_discarded_by_verification": rep["changes_discarded_by_verification"],
            "confirmed_possible_damage": sum(1 for c in system if c["review_status"] == "CONFIRMED"
                                             and c["class"] == "possible_damage"),
            "reviewer_observations_active": sum(1 for c in human if c["review_status"] != "WITHDRAWN"),
            "reviewer_observations_withdrawn": sum(1 for c in human if c["review_status"] == "WITHDRAWN"),
            "active_observations_possible_damage": sum(1 for c in human if c["review_status"] != "WITHDRAWN"
                                                       and c["class"] == "possible_damage"),
            "points_for_reshoot": [f"P{p['seq']}" for p in points if p["reshoot_needed"]],
            "changes_marked_reshoot": by_status["RESHOOT"],
            "confirmed_changes": [{"point": seq[c["id"]], "class": CLASS_LV.get(c["class"], c["class"]),
                                   "kind": KIND_LV.get(c["kind"], c["kind"]), "cell": c.get("cell_words") or "",
                                   "description": _lv_photo_names(c["description"])}
                                  for c in system if c["review_status"] == "CONFIRMED"],
            "active_observations": [{"point": seq[c["id"]], "class": CLASS_LV.get(c["class"], c["class"]),
                                     "text": c["description"]}
                                    for c in human if c["review_status"] != "WITHDRAWN"],
            "report_lines": rep["summary_lines"],
        }
    return ev


def _share(compared, total):
    return f"{compared / total:.2f}".replace(".", ",") if total else "nav datu"


def decide_rule(ev):
    """R0 -> R1 -> R2 -> R3a -> R3, in code. Returns dict(rule, recommendation, outcome, line, blocked, findings).
    The "no changes" outcome (R3) is reachable only when there is no confirmed change, no re-shoot mark and
    no active reviewer observation."""
    pc = ev["photo_comparison"]
    threshold = str(MIN_COMPARED_SHARE).replace(".", ",")
    if pc == NO_DATA:
        return {"rule": "R2", "recommendation": KEEP_OPEN, "outcome": OUTCOME["R2"], "blocked": False,
                "findings": False, "line": "R2: nav saistītas foto salīdzināšanas."}
    unreviewed = pc["system_changes_by_review_status"]["UNREVIEWED"]
    if unreviewed:
        return {"rule": "R0", "recommendation": None, "outcome": None, "blocked": True, "unreviewed": unreviewed,
                "findings": True, "line": f"R0: vispirms jāizskata {unreviewed} izmaiņas."}
    total, compared, reshoot = pc["points_total"], pc["points_compared"], pc["changes_marked_reshoot"]
    confirmed, observations = pc["confirmed_changes"], pc["active_observations"]
    findings = bool(confirmed or reshoot or observations)
    counts = f"salīdzināti {compared} no {total} punktiem, daļa {_share(compared, total)}"
    dmg = sum(1 for c in confirmed if c["class"] == CLASS_LV["possible_damage"])
    obs_dmg = sum(1 for o in observations if o["class"] == CLASS_LV["possible_damage"])
    if dmg or obs_dmg:
        return {"rule": "R1", "recommendation": KEEP_OPEN, "outcome": OUTCOME["R1"], "blocked": False,
                "findings": True,
                "line": f"R1: apstiprinātas izmaiņas ar klasi „iespējams bojājums”: {dmg}; aktīvi pārskatītāja "
                        f"novērojumi par iespējamiem bojājumiem: {obs_dmg}."}
    low_share = not total or compared < MIN_COMPARED_SHARE * total
    if low_share or reshoot:
        parts = [f"{counts} ({'<' if low_share else '≥'} {threshold})"]
        if reshoot:
            parts.append(f"atkārtotai fotografēšanai atzīmētas izmaiņas: {reshoot}")
        return {"rule": "R2", "recommendation": KEEP_OPEN, "outcome": OUTCOME["R2"], "blocked": False,
                "findings": findings, "line": "R2: " + "; ".join(parts) + "."}
    if confirmed or observations:
        return {"rule": "R3a", "recommendation": CLOSE, "outcome": OUTCOME["R3a"], "blocked": False,
                "findings": True,
                "line": f"R3a: {counts} (≥ {threshold}); apstiprinātas iespējamās izmaiņas: {len(confirmed)}; "
                        f"aktīvi pārskatītāja novērojumi par iespējamām izmaiņām: {len(observations)}; "
                        f"bojājumi nav apstiprināti."}
    return {"rule": "R3", "recommendation": CLOSE, "outcome": OUTCOME["R3"], "blocked": False, "findings": False,
            "line": f"R3: {counts} (≥ {threshold}); apstiprinātu izmaiņu, atkārtotas fotografēšanas atzīmju "
                    f"un aktīvu pārskatītāja novērojumu nav."}


def _check_text(text, findings=False):
    if findings and NO_CHANGE_TEXT.search(text):
        raise ValueError(f"'no changes' wording while changes, re-shoot marks or observations exist: "
                         f"'{NO_CHANGE_TEXT.search(text).group(0)}'")
    for name, rx in (("cause or percentage", photo_compare.FORBIDDEN_TEXT), ("money", MONEY_TEXT),
                     ("coverage claim", COVERAGE_TEXT), ("close/open wording", DECISION_TEXT)):
        m = rx.search(text)
        if m:
            raise ValueError(f"{name}: '{m.group(0)}'")
    if re.search(r"\b(BASELINE|FOLLOW-UP)\b", text):
        raise ValueError("English photo names")


# ── Read side ─────────────────────────────────────────────────────────────────
def _rows(conn, risk_id):
    rows = []
    for r in conn.execute("SELECT * FROM risk_conclusions WHERE risk_id=? ORDER BY id DESC", (risk_id,)):
        d = dict(r)
        d["evidence"] = json.loads(d.pop("evidence_json") or "{}")
        d["reshoot_points"] = json.loads(d.pop("reshoot_points_json") or "[]")
        for k in ("created_at", "decided_at", "superseded_at"):
            d[k + "_local"] = local(d[k]) if d[k] else None
        rows.append(d)
    return rows


def get_conclusion(risk_id):
    """Current evidence and rule (live), the current conclusion and the history."""
    ev = build_evidence(risk_id)
    if ev is None:
        return None
    conn = _conn()
    rows = _rows(conn, risk_id)
    gen = conn.execute("SELECT created_at FROM risk_events WHERE risk_id=? AND event_type='AI_RECOMMENDATION_GENERATED' "
                       "ORDER BY id DESC LIMIT 1", (risk_id,)).fetchone()
    conn.close()
    current = next((r for r in rows if r["status"] != "SUPERSEDED"), None)
    conn = _conn()
    has_run = conn.execute("SELECT 1 FROM photo_cmp_runs WHERE sector=? LIMIT 1", (ev["risk"]["sector"],)).fetchone()
    conn.close()
    return {"evidence": ev, "rule": decide_rule(ev), "current": current, "sector_has_run": bool(has_run),
            "history": [r for r in rows if r is not current],
            "ai_recommendation_generated_at": local(gen["created_at"]) if gen else None,
            "min_compared_share": MIN_COMPARED_SHARE}


# ── Draft (optional paid call) ────────────────────────────────────────────────
def _language():
    code = (os.environ.get("AI_OUTPUT_LANGUAGE") or AI_DEFAULT_LANGUAGE).strip()
    return LANGUAGE_NAMES.get(code.lower(), code)


def _generate_text(risk_id, ev, rule, actor):
    model = os.environ.get("ANTHROPIC_MODEL") or AI_DEFAULT_MODEL
    prompt = PROMPT.format(outcome=rule["outcome"], rule_line=rule["line"], language=_language(),
                           # the risk text is not sent: it may name a cause or a forecast the model must not repeat
                           evidence=json.dumps({"risk": {k: v for k, v in ev["risk"].items() if k not in ("events", "text")},
                                                "photo_comparison": ev["photo_comparison"],
                                                "field_activity": ev["field_activity"]},
                                               ensure_ascii=False, indent=1))
    for attempt in range(1, MAX_ATTEMPTS_PER_CALL + 1):
        usage, text = None, ""
        try:
            resp = _get_client().messages.create(model=model, max_tokens=1200,
                                                 messages=[{"role": "user", "content": prompt}])
            usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            s = text[text.index("{"): text.rindex("}") + 1]
            out = str(json.loads(s).get("text", "")).strip()
            if not out:
                raise ValueError("empty text")
            _check_text(out, rule.get("findings", False))
            _risk_event(risk_id, "CONCLUSION_AI_CALL", actor,
                        dict(attempt=attempt, ok=True, model=model, **(usage or {})))
            return out, model
        except Exception as e:
            _risk_event(risk_id, "CONCLUSION_AI_CALL", actor,
                        dict(attempt=attempt, ok=False, model=model, error=f"{type(e).__name__}: {e}"[:500],
                             answer=text[:2000], **(usage or {})))
    return None, model


def create_draft(risk_id, actor, weather_text="", weather_source="", use_ai=True):
    """Freeze evidence + rule into a DRAFT. With use_ai, one paid call (max MAX_ATTEMPTS_PER_CALL attempts)
    writes the text; without it the reviewer writes the text. Refused while R0 applies."""
    ev = build_evidence(risk_id)
    if ev is None:
        return 404, {"error": "risk not found"}
    if ev["risk"]["status"] in CLOSED_STATUSES:
        return 409, {"error": "risk is already closed"}
    rule = decide_rule(ev)
    if rule["blocked"]:
        return 409, {"error": rule["line"], "rule": rule}
    weather_text, weather_source = (weather_text or "").strip()[:500], (weather_source or "").strip()[:200]
    if weather_source and not weather_text:
        return 400, {"error": "weather source without weather text"}
    ev["observed_weather"] = ({"text": weather_text, "source": weather_source or NO_DATA, "entered_by": actor}
                              if weather_text else NO_DATA)
    text, model = (None, None)
    if use_ai:
        text, model = _generate_text(risk_id, ev, rule, actor)
        if text is None:
            return 502, {"error": "the AI text was rejected or not produced; try again or write it yourself"}
    conn = _conn()
    now = _now()
    for old in conn.execute("SELECT id FROM risk_conclusions WHERE risk_id=? AND status='DRAFT'", (risk_id,)):
        conn.execute("UPDATE risk_conclusions SET status='SUPERSEDED', superseded_at=? WHERE id=?", (now, old["id"]))
    cid = conn.execute(
        "INSERT INTO risk_conclusions (risk_id, run_id, status, rule, recommendation, outcome, rule_line, "
        "evidence_json, weather_text, weather_source, ai_draft, model, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (risk_id, ev["photo_comparison"]["run_id"] if ev["photo_comparison"] != NO_DATA else None, "DRAFT",
         rule["rule"], rule["recommendation"], rule["outcome"], rule["line"], json.dumps(ev, ensure_ascii=False),
         weather_text or None, weather_source or None, text, model, actor, now)).lastrowid
    conn.execute("UPDATE risk_conclusions SET superseded_by=? WHERE risk_id=? AND status='SUPERSEDED' "
                 "AND superseded_by IS NULL AND id<>?", (cid, risk_id, cid))
    conn.commit()
    conn.close()
    _risk_event(risk_id, "CONCLUSION_DRAFTED", actor,
                {"conclusion_id": cid, "rule": rule["rule"], "recommendation": rule["recommendation"],
                 "ai_text": bool(text)})
    return 200, {"ok": True, "conclusion_id": cid}


# ── Human decision ────────────────────────────────────────────────────────────
def _draft(conn, risk_id, cid):
    r = conn.execute("SELECT * FROM risk_conclusions WHERE id=? AND risk_id=?", (cid, risk_id)).fetchone()
    return dict(r) if r else None


def _supersede_previous(conn, risk_id, cid, now):
    conn.execute("UPDATE risk_conclusions SET status='SUPERSEDED', superseded_by=?, superseded_at=? "
                 "WHERE risk_id=? AND id<>? AND status IN ('INTERIM','CLOSED')", (cid, now, risk_id, cid))


def accept_and_close(risk_id, cid, text, actor, override_reason=""):
    text, override_reason = (text or "").strip(), (override_reason or "").strip()
    if len(text) < 10:
        return 400, {"error": "conclusion text is required"}
    conn = _conn()
    d = _draft(conn, risk_id, cid)
    risk = conn.execute("SELECT status FROM risks WHERE id=?", (risk_id,)).fetchone()
    if not d or not risk:
        conn.close()
        return 404, {"error": "conclusion not found"}
    if d["status"] != "DRAFT":
        conn.close()
        return 409, {"error": f"conclusion is {d['status']}"}
    if risk["status"] in CLOSED_STATUSES:
        conn.close()
        return 409, {"error": "risk is already closed"}
    against = d["recommendation"] == KEEP_OPEN
    if against and len(override_reason) < 5:
        conn.close()
        return 400, {"error": "the system recommends keeping the risk open: a reason is required"}
    now = _now()
    _supersede_previous(conn, risk_id, cid, now)
    conn.execute("UPDATE risk_conclusions SET status='CLOSED', final_text=?, decision='CLOSE', "
                 "against_recommendation=?, override_reason=?, decided_by=?, decided_at=? WHERE id=?",
                 (text, 1 if against else 0, override_reason or None, actor, now, cid))
    conn.commit()
    conn.close()
    database.update_incident_status(risk_id, "RESOLVED")          # existing status mechanism
    _risk_event(risk_id, "CONCLUSION_ACCEPTED", actor,
                {"conclusion_id": cid, "rule": d["rule"], "recommendation": d["recommendation"],
                 "against_recommendation": against, "override_reason": override_reason or None,
                 "label": AGAINST_LABEL if against else None})
    _risk_event(risk_id, "RESOLVED", actor, f"conclusion #{cid}" + (f" — {AGAINST_LABEL}" if against else ""))
    return 200, {"ok": True, "status": "RESOLVED", "against_recommendation": against}


def continue_work(risk_id, cid, text, next_steps, actor):
    text, next_steps = (text or "").strip(), (next_steps or "").strip()
    if len(text) < 10:
        return 400, {"error": "conclusion text is required"}
    if len(next_steps) < 5:
        return 400, {"error": "a note on what is to be done next is required"}
    conn = _conn()
    d = _draft(conn, risk_id, cid)
    if not d:
        conn.close()
        return 404, {"error": "conclusion not found"}
    if d["status"] != "DRAFT":
        conn.close()
        return 409, {"error": f"conclusion is {d['status']}"}
    ev = json.loads(d["evidence_json"])
    reshoot = ev["photo_comparison"]["points_for_reshoot"] if ev.get("photo_comparison") != NO_DATA else []
    now = _now()
    _supersede_previous(conn, risk_id, cid, now)
    conn.execute("UPDATE risk_conclusions SET status='INTERIM', final_text=?, decision='CONTINUE', next_steps=?, "
                 "reshoot_points_json=?, decided_by=?, decided_at=? WHERE id=?",
                 (text, next_steps, json.dumps(reshoot), actor, now, cid))
    conn.commit()
    conn.close()
    _risk_event(risk_id, "CONCLUSION_INTERIM", actor,
                {"conclusion_id": cid, "rule": d["rule"], "next_steps": next_steps, "reshoot_points": reshoot})
    return 200, {"ok": True, "status": "INTERIM"}
