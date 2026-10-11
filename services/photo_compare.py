"""
Photo comparison between two dates for one sector (MVP).

Unit of comparison is a POINT (one place in the forest): one or more baseline photos
plus the follow-up photo(s) of the same place. Every photo of both dates belongs to
exactly one point; nothing is dropped.

Steps, each started only by an explicit authenticated request (nothing runs on its own):
  1. points   - visual matching pass (or import of an existing one); a human then confirms
                or corrects the points (confirm all / one, re-assign a photo, "not the same place")
  B. check    - per confirmed two-sided point: same_place + comparability; "no"/"unsuitable" ends it
  C. detect   - list of visible changes (possibly empty), on a 3x3 grid of the follow-up photo
  D. verify   - one independent call per change; "no" discards the change (logged)
  E. confidence category computed in code (never a percentage)

Photos on disk are never modified: they are opened read-only and downscaled in memory.
Every human action and every paid call is logged in photo_cmp_events.
"""

import base64
import io
import json
import os
import re
import sqlite3
import threading
from datetime import datetime

from PIL import Image, ImageOps

import database
from services.ai_resolution import _get_client

# ── Guards / parameters ───────────────────────────────────────────────────────
MAX_POINTS_PER_RUN    = 40
MAX_ATTEMPTS_PER_CALL = 2      # per paid call (match, check, detect, verify)
MATCH_WINDOW          = 8      # follow-up candidates per matching call
MATCH_LONG_SIDE       = 512    # px, in memory only
COMPARE_LONG_SIDE     = 1024   # px, in memory only
MATCH_ACCEPTED        = ("high", "medium")
AI_DEFAULT_MODEL      = "claude-sonnet-4-5"   # same default as the risk AI worker; override via ANTHROPIC_MODEL
AI_DEFAULT_LANGUAGE   = "lv"                  # override via AI_OUTPUT_LANGUAGE
LANGUAGE_NAMES = {"lv": "Latvian", "ru": "Russian", "en": "English"}

APP_DIR = os.path.dirname(os.path.abspath(database.__file__))   # work_photos.image_path is relative to it

SAME_PLACE     = ("yes", "partial", "no")
COMPARABILITY  = ("suitable", "partial", "unsuitable")
REASON_CODES   = ("none", "different_viewpoint", "blur", "too_dark", "low_overlap", "obstruction")
CHANGE_KINDS   = ("object_appeared", "object_disappeared", "fallen_tree", "broken_tree_part",
                  "object_moved", "ground_damage", "path_or_structure_change", "transient_object", "other")
TRANSIENT_KIND = "transient_object"   # person, animal or vehicle: always possible_change, never decides "no changes"
CHANGE_CLASSES = ("possible_change", "possible_damage")
CELLS          = tuple(f"r{r}c{c}" for r in (1, 2, 3) for c in (1, 2, 3))
VERDICTS       = ("yes", "no", "unsure")
VIEWPOINT_SHIFT = ("none", "slight", "large")
REVIEW_ACTIONS = {"confirm": "CONFIRMED", "reject": "REJECTED", "reshoot": "RESHOOT"}

# Model text must not name a cause or give a percentage; such an answer counts as invalid.
# Second line of defence only; the prompt itself forbids any cause (COMMON_RULES).
FORBIDDEN_TEXT = re.compile(r"\b(vētr|vēj|brāzm|negais|sezonāl|dabisk|laikapstāk|storm|wind|gust|season|natural|weather)\w*|%",
                            re.IGNORECASE)

# NOT_COMPARABLE_HUMAN: set by the reviewer (e.g. viewpoint differs too much); never sent to a paid call,
# not even with force.
POINT_DONE_STATES = ("NOT_SAME_PLACE", "NOT_COMPARABLE", "NOT_COMPARABLE_HUMAN", "CHECKED", "DONE", "FAILED")
RESHOOT_STATES    = ("NOT_SAME_PLACE", "NOT_COMPARABLE", "NOT_COMPARABLE_HUMAN")

NO_CHANGES_LINES = [
    "Salīdzināmajās redzamajās zonās izmaiņas nav konstatētas.",
    "Tas nenozīmē, ka pārbaudīta visa teritorija vai ka bojājumu noteikti nav.",
]
REJECTED_LINE = "Sistēmas konstatētās izmaiņas, kuras pārskatītājs noraidīja: {n}."
HUMAN_KIND = "human_observation"      # entered by a reviewer; never sent to a paid call, never reviewed
OBSERVATION_MAX_LEN = 500
# A reviewer observation has review_status HUMAN (active) or WITHDRAWN; for WITHDRAWN, reviewer/reviewed_at
# hold who withdrew it and when. Withdrawn observations stay stored and no longer block "no changes".
OBSERVATION_LINE = "Pārskatītāja ievadītie novērojumi: {n}."
OBSERVATION_LINE_WITHDRAWN = "Pārskatītāja ievadītie novērojumi: {n} (atsaukti: {w})."

# ── Prompts ───────────────────────────────────────────────────────────────────
COMMON_RULES = (
    "Rules:\n"
    "- Lighting, shadows, wet ground, leaf colour, leaf fall, moving foliage, blur, perspective and a "
    "shifted camera are not changes by themselves. Leaf litter that clearly differs may be at most a "
    "possible_change.\n"
    "- Similar-looking forest is not the same place. Rely only on stable landmarks: trunk layout, path "
    "forks, kerbs, stones, structures.\n"
    "- Areas outside the shared view or hidden by an object are reported in \"limits\", never guessed.\n"
    "- Describe only what is visible, never why it happened or how it came about. Name no cause of any "
    "kind: not weather, season, nature, people, animals, machines or any event.\n"
    "- Do not use percentages.\n"
    "- If unsure, say so. Never invent a change.\n"
    "- Write every text value in {language}. Keep JSON keys and enumerated values exactly as specified.\n"
    "- In the text, call the photos only \"bāzes foto\" and \"pēcfoto\". Use no English words.\n"
    "- Return ONLY one JSON object, no markdown, no text outside it."
)

MATCH_PROMPT = (
    "The first image is the \"bāzes foto\" of a forest place. The following images are \"pēcfoto\" "
    "candidates taken on a later date, each preceded by its id.\n"
    "Decide which candidate, if any, shows the SAME PLACE from roughly the same position and direction. "
    "Judge only by stable landmarks: path layout and forks, distinctive trunks, stumps, stones, kerbs, "
    "signs, structures. Do not match on generic similarity such as \"both show pine forest\". Do not "
    "reject a match because of differences in light, leaves or season. If no candidate clearly shows "
    "the same place, answer \"none\".\n"
    'Answer ONLY with JSON: {"match": <candidate id as integer, or "none">, '
    '"confidence": "high" | "medium" | "low", "reason": "<one short sentence naming the landmarks compared>"}'
)

CHECK_PROMPT = (
    "The images above are photos of one place in a forest: first the \"bāzes foto\" from {baseline_date}, "
    "then the \"pēcfoto\" from {followup_date}, each preceded by its id.\n"
    "Task: decide whether the \"pēcfoto\" shows the same place as the \"bāzes foto\", and whether "
    "the photos are suitable for detecting visible changes between them. Do not look for changes yet.\n"
    "- same_place: \"yes\" (same place, clearly shared landmarks), \"partial\" (overlapping view of the same "
    "place), \"no\" (different place, or cannot be established).\n"
    "- viewpoint_shift: \"none\" (same position and direction), \"slight\" (camera moved or turned a little), "
    "\"large\" (clearly different position, distance or direction).\n"
    "- comparability: \"suitable\", \"partial\" or \"unsuitable\", with reason_code one of "
    "\"none\", \"different_viewpoint\", \"blur\", \"too_dark\", \"low_overlap\", \"obstruction\".\n\n"
    + COMMON_RULES + "\n\n"
    'JSON: {{"same_place": "...", "viewpoint_shift": "...", "comparability": "...", "reason_code": "...", '
    '"reason": "<one or two sentences: which landmarks match or not, and why the photos are or are not comparable>"}}'
)

DETECT_PROMPT = (
    "The images above are photos of one place in a forest: first the \"bāzes foto\" from {baseline_date}, "
    "then the \"pēcfoto\" from {followup_date}, each preceded by its id. They were already judged to "
    "show the same place.\n"
    "Task: list the changes that are visible in the \"pēcfoto\" and absent in the \"bāzes foto\", or visible "
    "in the \"bāzes foto\" and absent in the \"pēcfoto\". An empty list is a valid and common answer.\n"
    "Per change:\n"
    "- kind: one of " + ", ".join(f'"{k}"' for k in CHANGE_KINDS) + "\n"
    "- cell: position in the \"pēcfoto\" on a 3x3 grid, \"r1c1\" (top left) to \"r3c3\" (bottom right)\n"
    "- class: \"possible_change\" or \"possible_damage\"\n"
    "A person, animal or vehicle visible in only one photo is kind \"transient_object\" with class "
    "\"possible_change\", never \"possible_damage\".\n"
    "- description: one or two sentences, what and where\n"
    "- limits: what could not be compared for this change\n"
    "Also give overall limits: which parts of the scene could not be compared (outside the shared view, "
    "hidden, too dark, blurred).\n\n"
    + COMMON_RULES + "\n\n"
    'JSON: {{"changes": [{{"kind": "...", "cell": "...", "class": "...", "description": "...", "limits": "..."}}], '
    '"limits": "..."}}'
)

VERIFY_PROMPT = (
    "The images above are photos of one place in a forest: first the \"bāzes foto\" from {baseline_date}, "
    "then the \"pēcfoto\" from {followup_date}, each preceded by its id.\n"
    "Someone claims the following change (cell = position on a 3x3 grid of the \"pēcfoto\", r1c1 top "
    "left to r3c3 bottom right):\n"
    "kind: {kind}\ncell: {cell}\nclaim: {description}\n\n"
    "Check this specific claim yourself, strictly:\n"
    "1. Find the exact spot of the claim in BOTH photos, fixed by a stable landmark visible in both "
    "(a named trunk, post, stone, kerb, path fork). Name that landmark.\n"
    "2. Answer \"yes\" only if the object is clearly present at that spot in one photo and clearly absent "
    "at the same spot in the other.\n"
    "3. Answer \"no\" if the object is visible in both photos (possibly at another position in the frame "
    "because the camera moved), or if the difference is only wet, dark, muddy or shaded ground, a puddle, "
    "light, shadow, leaf colour, leaf fall, moving foliage, blur or perspective.\n"
    "4. Answer \"unsure\" if the spot is outside the frame of either photo, partly hidden, at a clearly "
    "different distance, or you cannot fix it with a landmark.\n\n"
    + COMMON_RULES + "\n\n"
    'JSON: {{"verdict": "yes" | "no" | "unsure", "landmark": "<landmark fixing the spot in both photos, or empty>", '
    '"reason": "<one sentence>"}}'
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _conn():
    conn = sqlite3.connect(database.DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def _model():
    return os.environ.get("ANTHROPIC_MODEL") or AI_DEFAULT_MODEL


def _language():
    code = (os.environ.get("AI_OUTPUT_LANGUAGE") or AI_DEFAULT_LANGUAGE).strip()
    return LANGUAGE_NAMES.get(code.lower(), code)


def log_event(event_type, actor=None, run_id=None, point_id=None, change_id=None, purpose=None,
              model=None, input_tokens=None, output_tokens=None, details=None):
    if details is not None and not isinstance(details, str):
        details = json.dumps(details, ensure_ascii=False)
    conn = _conn()
    conn.execute(
        "INSERT INTO photo_cmp_events (run_id, point_id, change_id, event_type, actor, purpose, model, "
        "input_tokens, output_tokens, details, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, point_id, change_id, event_type, actor, purpose, model, input_tokens, output_tokens,
         details, _now()),
    )
    conn.commit()
    conn.close()


def _image_block(rel_path, long_side):
    """Read-only open + in-memory downscale; the file on disk is never touched."""
    with Image.open(os.path.join(APP_DIR, rel_path)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((long_side, long_side), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(buf.getvalue()).decode("ascii")}}


def _parse_json(text):
    s = (text or "").strip()
    if "{" not in s:
        raise ValueError("no JSON object in answer")
    return json.loads(s[s.index("{"): s.rindex("}") + 1])


def _check_text(*values):
    for v in values:
        if v and FORBIDDEN_TEXT.search(str(v)):
            raise ValueError(f"forbidden wording (cause or percentage): {str(v)[:120]}")


def _call_vision(content, purpose, validate, max_tokens, run_id, point_id=None, change_id=None, actor="photo_compare"):
    """One logical call with up to MAX_ATTEMPTS_PER_CALL paid attempts. Each attempt is logged
    as an AI_CALL event (purpose, model, tokens, outcome). Returns the validated dict or None."""
    model = _model()
    for attempt in range(1, MAX_ATTEMPTS_PER_CALL + 1):
        usage_in = usage_out = None
        text = ""
        try:
            resp = _get_client().messages.create(model=model, max_tokens=max_tokens,
                                                 messages=[{"role": "user", "content": content}])
            usage_in, usage_out = resp.usage.input_tokens, resp.usage.output_tokens
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            result = validate(_parse_json(text))
            log_event("AI_CALL", actor, run_id, point_id, change_id, purpose, model, usage_in, usage_out,
                      {"attempt": attempt, "ok": True, "answer": text[:4000]})
            return result
        except Exception as e:
            log_event("AI_CALL", actor, run_id, point_id, change_id, purpose, model, usage_in, usage_out,
                      {"attempt": attempt, "ok": False, "error": f"{type(e).__name__}: {e}"[:1000],
                       "answer": text[:4000]})
    return None


# ── Photos and runs ───────────────────────────────────────────────────────────
def _photos(conn, ids):
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    return [dict(r) for r in conn.execute(
        f"SELECT id, sector, session_id, photo_type, image_path, uploaded_at FROM work_photos "
        f"WHERE id IN ({q}) ORDER BY uploaded_at, id", tuple(ids))]


def _photos_on(conn, sector, date):
    return [r[0] for r in conn.execute(
        "SELECT id FROM work_photos WHERE sector=? AND uploaded_at LIKE ? ORDER BY uploaded_at, id",
        (sector, date + "%"))]


def create_run(sector, baseline_date, followup_date, actor, baseline_photo_ids=None, followup_photo_ids=None):
    """Freeze the two photo sets (by sector + date, or explicit ids). No paid call."""
    try:
        for d in (baseline_date, followup_date):
            datetime.strptime(d, "%Y-%m-%d")
    except (TypeError, ValueError):
        return 400, {"error": "dates must be YYYY-MM-DD"}
    conn = _conn()
    try:
        b_ids = list(baseline_photo_ids) if baseline_photo_ids else _photos_on(conn, sector, baseline_date)
        f_ids = list(followup_photo_ids) if followup_photo_ids else _photos_on(conn, sector, followup_date)
        b, f = _photos(conn, b_ids), _photos(conn, f_ids)
        if len(b) != len(set(b_ids)) or len(f) != len(set(f_ids)):
            return 400, {"error": "unknown photo id"}
        if not b or not f:
            return 400, {"error": "both photo sets must be non-empty"}
        if {p["id"] for p in b} & {p["id"] for p in f}:
            return 400, {"error": "a photo cannot be in both sets"}
        now = _now()
        cur = conn.execute(
            "INSERT INTO photo_cmp_runs (sector, baseline_date, followup_date, baseline_photo_ids, "
            "followup_photo_ids, status, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (sector, baseline_date, followup_date, json.dumps([p["id"] for p in b]),
             json.dumps([p["id"] for p in f]), "CREATED", actor, now, now))
        conn.commit()
        run_id = cur.lastrowid
    finally:
        conn.close()
    log_event("RUN_CREATED", actor, run_id, details={"sector": sector, "baseline_date": baseline_date,
              "followup_date": followup_date, "baseline": len(b), "followup": len(f)})
    return 200, {"ok": True, "run_id": run_id, "baseline": len(b), "followup": len(f)}


def _run(conn, run_id):
    r = conn.execute("SELECT * FROM photo_cmp_runs WHERE id=?", (run_id,)).fetchone()
    if not r:
        return None
    r = dict(r)
    r["baseline_ids"] = json.loads(r["baseline_photo_ids"])
    r["followup_ids"] = json.loads(r["followup_photo_ids"])
    return r


def _set_run_status(run_id, status):
    conn = _conn()
    conn.execute("UPDATE photo_cmp_runs SET status=?, updated_at=? WHERE id=?", (status, _now(), run_id))
    conn.commit()
    conn.close()


# ── Points ────────────────────────────────────────────────────────────────────
def _order_points(points, bpos, fpos):
    """Capture order: points with baseline photos by their first baseline photo; a point with only
    follow-up photo(s) goes right after the point holding the previous follow-up photo (capture order)."""
    with_b = sorted((p for p in points if p["baseline"]), key=lambda p: min(bpos[i] for i in p["baseline"]))
    only_f = sorted((p for p in points if not p["baseline"]), key=lambda p: min(fpos[i] for i in p["followup"]))
    out = list(with_b)
    for p in only_f:
        first = min(fpos[i] for i in p["followup"])
        holder = {fpos[i]: q for q in out for i in q["followup"]}
        prev = max((n for n in holder if n < first), default=None)
        idx = 0 if prev is None else next(n for n, q in enumerate(out) if q is holder[prev]) + 1
        out.insert(idx, p)
    return out


def resequence_run(run_id, actor):
    """Recompute seq of all points of a run with _order_points (no paid call). Logged with old/new order."""
    conn = _conn()
    try:
        run = _run(conn, run_id)
        if not run:
            return 404, {"error": "run not found"}
        members = {}
        for r in conn.execute("SELECT p.id, p.seq, pp.photo_id, pp.side FROM photo_cmp_points p "
                              "JOIN photo_cmp_point_photos pp ON pp.point_id=p.id WHERE p.run_id=?", (run_id,)):
            m = members.setdefault(r["id"], {"id": r["id"], "old_seq": r["seq"], "baseline": [], "followup": []})
            m[r["side"]].append(r["photo_id"])
        bpos = {i: n for n, i in enumerate(run["baseline_ids"])}
        fpos = {i: n for n, i in enumerate(run["followup_ids"])}
        moved = []
        for seq, p in enumerate(_order_points(list(members.values()), bpos, fpos), 1):
            if p["old_seq"] != seq:
                moved.append({"point_id": p["id"], "old": p["old_seq"], "new": seq})
                conn.execute("UPDATE photo_cmp_points SET seq=? WHERE id=?", (seq, p["id"]))
        conn.commit()
    finally:
        conn.close()
    log_event("POINTS_RESEQUENCED", actor, run_id, details={"moved": moved})
    return 200, {"ok": True, "moved": len(moved)}


def _kind(p):
    if p["baseline"] and p["followup"]:
        return "both"
    return "no_followup" if p["baseline"] else "no_baseline"


def _points_from_matches(run, results):
    """results: one dict per baseline photo {baseline_id, match, confidence, reason}."""
    by_b = {r["baseline_id"]: r for r in results}
    groups, points = {}, []
    for bid in run["baseline_ids"]:
        r = by_b[bid]
        accepted = r.get("match") is not None and r.get("confidence") in MATCH_ACCEPTED
        if accepted:
            if r["match"] not in groups:
                groups[r["match"]] = {"baseline": [], "followup": [r["match"]]}
                points.append(groups[r["match"]])
            groups[r["match"]]["baseline"].append(bid)
        else:
            points.append({"baseline": [bid], "followup": []})
    for fid in run["followup_ids"]:
        if fid not in groups:
            points.append({"baseline": [], "followup": [fid]})
    return points


def _store_points(conn, run, points, match_info):
    bpos = {i: n for n, i in enumerate(run["baseline_ids"])}
    fpos = {i: n for n, i in enumerate(run["followup_ids"])}
    members = [i for p in points for i in p["baseline"] + p["followup"]]
    if sorted(members) != sorted(run["baseline_ids"] + run["followup_ids"]):
        raise ValueError("every photo must be in exactly one point")
    if len(points) > MAX_POINTS_PER_RUN:
        raise ValueError(f"{len(points)} points exceed MAX_POINTS_PER_RUN={MAX_POINTS_PER_RUN}")
    now = _now()
    stored = []
    for seq, p in enumerate(_order_points(points, bpos, fpos), 1):
        confs = [match_info.get(b, {}).get("confidence") for b in p["baseline"]] if p["followup"] else []
        point_conf = ("medium" if "medium" in confs else "high") if confs and all(confs) else None
        pid = conn.execute(
            "INSERT INTO photo_cmp_points (run_id, seq, kind, match_confidence, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)", (run["id"], seq, _kind(p), point_conf, "UNCONFIRMED", now, now)).lastrowid
        for b in p["baseline"]:
            mi = match_info.get(b, {})
            conn.execute("INSERT INTO photo_cmp_point_photos (run_id, point_id, photo_id, side, match_confidence, "
                         "match_reason) VALUES (?,?,?,?,?,?)",
                         (run["id"], pid, b, "baseline", mi.get("confidence"), mi.get("reason")))
        for f in p["followup"]:
            conn.execute("INSERT INTO photo_cmp_point_photos (run_id, point_id, photo_id, side) VALUES (?,?,?,?)",
                         (run["id"], pid, f, "followup"))
        stored.append((pid, p))
    return stored


def import_matches(run_id, results, actor, source=""):
    """Build points from an existing matching pass (no paid call)."""
    conn = _conn()
    try:
        run = _run(conn, run_id)
        if not run:
            return 404, {"error": "run not found"}
        if run["status"] != "CREATED":
            return 409, {"error": f"run already has points (status {run['status']})"}
        if sorted(r["baseline_id"] for r in results) != sorted(run["baseline_ids"]):
            return 400, {"error": "results must cover exactly the run's baseline photos"}
        for r in results:
            if r.get("match") is not None and r["match"] not in run["followup_ids"]:
                return 400, {"error": f"match {r['match']} is not a follow-up photo of this run"}
        points = _points_from_matches(run, results)
        _store_points(conn, run, points, {r["baseline_id"]: r for r in results})
        conn.execute("UPDATE photo_cmp_runs SET status='READY', updated_at=? WHERE id=?", (_now(), run_id))
        conn.commit()
    except ValueError as e:
        conn.rollback()
        return 400, {"error": str(e)}
    finally:
        conn.close()
    log_event("MATCHES_IMPORTED", actor, run_id, details={"source": source, "points": len(points)})
    return 200, {"ok": True, "points": len(points)}


def import_human_points(run_id, points, actor, source=""):
    """Points defined by a human reviewer, replacing automatic matching (no paid call).
    points: [{"baseline": [ids], "followup": [ids], "decision": "same_place" | "different_viewpoint" | None}]
    Every point is recorded as confirmed by `actor`. "different_viewpoint" points get comparability
    unsuitable, status NOT_COMPARABLE_HUMAN (re-shoot needed) and are never sent to a paid call."""
    conn = _conn()
    try:
        run = _run(conn, run_id)
        if not run:
            return 404, {"error": "run not found"}
        if run["status"] != "CREATED":
            return 409, {"error": f"run already has points (status {run['status']})"}
        for p in points:
            if p.get("decision") not in (None, "same_place", "different_viewpoint"):
                return 400, {"error": f"bad decision {p.get('decision')!r}"}
            if p.get("decision") and not (p["baseline"] and p["followup"]):
                return 400, {"error": "a decision needs photos on both sides"}
            if set(p["baseline"]) - set(run["baseline_ids"]) or set(p["followup"]) - set(run["followup_ids"]):
                return 400, {"error": f"point {p} has photos outside the run's sets or on the wrong side"}
        stored = _store_points(conn, run, points, {})
        now = _now()
        for pid, p in stored:
            if p.get("decision") == "different_viewpoint":
                conn.execute("UPDATE photo_cmp_points SET confirmed=1, confirmed_by=?, confirmed_at=?, "
                             "status='NOT_COMPARABLE_HUMAN', comparability='unsuitable', "
                             "comparability_reason='different_viewpoint: set by reviewer', updated_at=? WHERE id=?",
                             (actor, now, now, pid))
            else:
                conn.execute("UPDATE photo_cmp_points SET confirmed=1, confirmed_by=?, confirmed_at=?, "
                             "status='CONFIRMED', updated_at=? WHERE id=?", (actor, now, now, pid))
            conn.execute("UPDATE photo_cmp_point_photos SET match_reason='set by reviewer' WHERE point_id=?", (pid,))
        conn.execute("UPDATE photo_cmp_runs SET status='READY', updated_at=? WHERE id=?", (now, run_id))
        conn.commit()
    except ValueError as e:
        conn.rollback()
        return 400, {"error": str(e)}
    finally:
        conn.close()
    log_event("POINTS_SET_BY_REVIEWER", actor, run_id, details={"source": source, "points": len(stored)})
    for pid, p in stored:
        log_event("POINT_NOT_COMPARABLE_HUMAN" if p.get("decision") == "different_viewpoint" else "POINT_CONFIRMED",
                  actor, run_id, pid, details={"baseline": p["baseline"], "followup": p["followup"],
                                               "decision": p.get("decision")})
    return 200, {"ok": True, "points": len(stored)}


def _matching_pass(run_id, actor):
    conn = _conn()
    run = _run(conn, run_id)
    photo = {p["id"]: p for p in _photos(conn, run["baseline_ids"] + run["followup_ids"])}
    conn.close()
    f_ids = run["followup_ids"]
    start, results = 0, []
    for bid in run["baseline_ids"]:
        window = f_ids[start:start + MATCH_WINDOW]
        content = [{"type": "text", "text": f"bāzes foto id={bid}"},
                   _image_block(photo[bid]["image_path"], MATCH_LONG_SIDE)]
        for fid in window:
            content += [{"type": "text", "text": f"pēcfoto kandidāts id={fid}"},
                        _image_block(photo[fid]["image_path"], MATCH_LONG_SIDE)]
        content.append({"type": "text", "text": MATCH_PROMPT})

        def validate(a, window=window):
            m = a.get("match")
            m = int(m) if str(m).strip().isdigit() else None
            if m is not None and m not in window:
                raise ValueError(f"id {m} outside the window")
            c = str(a.get("confidence", "")).lower()
            if c not in ("high", "medium", "low"):
                raise ValueError(f"bad confidence {c!r}")
            return {"match": m, "confidence": c, "reason": str(a.get("reason", ""))}

        r = _call_vision(content, "match", validate, 300, run_id, actor=actor)
        r = dict(r or {"match": None, "confidence": None, "reason": "matching call failed"}, baseline_id=bid)
        if r["match"] is not None and r["confidence"] in MATCH_ACCEPTED:
            start = f_ids.index(r["match"])          # never moves back; the same photo may match again
        results.append(r)
    _set_run_status(run_id, "CREATED")
    return import_matches(run_id, results, actor, source="matching pass")


# ── Human actions on points ───────────────────────────────────────────────────
def _point(conn, point_id):
    r = conn.execute("SELECT * FROM photo_cmp_points WHERE id=?", (point_id,)).fetchone()
    return dict(r) if r else None


def confirm_point(point_id, actor):
    conn = _conn()
    p = _point(conn, point_id)
    if not p:
        conn.close()
        return 404, {"error": "point not found"}
    if p["status"] != "UNCONFIRMED":
        conn.close()
        return 409, {"error": f"point is {p['status']}"}
    now = _now()
    conn.execute("UPDATE photo_cmp_points SET confirmed=1, confirmed_by=?, confirmed_at=?, status='CONFIRMED', "
                 "updated_at=? WHERE id=?", (actor, now, now, point_id))
    conn.commit()
    conn.close()
    log_event("POINT_CONFIRMED", actor, p["run_id"], point_id)
    return 200, {"ok": True}


def confirm_all(run_id, actor):
    conn = _conn()
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM photo_cmp_points WHERE run_id=? AND status='UNCONFIRMED' ORDER BY seq", (run_id,))]
    conn.close()
    for pid in ids:
        confirm_point(pid, actor)
    return 200, {"ok": True, "confirmed": len(ids)}


def _reset_point(conn, point_id):
    conn.execute("DELETE FROM photo_cmp_changes WHERE point_id=? AND source='system'", (point_id,))
    conn.execute("UPDATE photo_cmp_points SET same_place=NULL, comparability=NULL, comparability_reason=NULL, "
                 "detect_limits=NULL, check_attempts=0, detect_attempts=0, checked_at=NULL, detected_at=NULL "
                 "WHERE id=?", (point_id,))


def mark_not_same_place(point_id, actor, force=False):
    conn = _conn()
    p = _point(conn, point_id)
    if not p:
        conn.close()
        return 404, {"error": "point not found"}
    if p["status"] in POINT_DONE_STATES and not force:
        conn.close()
        return 409, {"error": f"point already processed ({p['status']}); use force"}
    _reset_point(conn, point_id)
    now = _now()
    conn.execute("UPDATE photo_cmp_points SET confirmed=1, confirmed_by=?, confirmed_at=?, "
                 "status='NOT_SAME_PLACE_HUMAN', updated_at=? WHERE id=?", (actor, now, now, point_id))
    conn.commit()
    conn.close()
    log_event("POINT_NOT_SAME_PLACE", actor, p["run_id"], point_id, details={"previous_status": p["status"]})
    return 200, {"ok": True}


def reassign_photo(run_id, photo_id, target, actor, force=False):
    """Move one photo to another point of the run (target = point id) or to a new point ("new").
    Both affected points go back to UNCONFIRMED; a point left empty is removed."""
    conn = _conn()
    try:
        run = _run(conn, run_id)
        if not run:
            return 404, {"error": "run not found"}
        if run["status"] in ("RUNNING", "MATCHING"):
            return 409, {"error": "run is busy"}
        row = conn.execute("SELECT * FROM photo_cmp_point_photos WHERE run_id=? AND photo_id=?",
                           (run_id, photo_id)).fetchone()
        if not row:
            return 404, {"error": "photo is not in this run"}
        src = _point(conn, row["point_id"])
        dst = None
        if target != "new":
            dst = _point(conn, int(target))
            if not dst or dst["run_id"] != run_id:
                return 404, {"error": "target point not found in this run"}
            if dst["id"] == src["id"]:
                return 400, {"error": "photo is already in that point"}
        for p in (src, dst):
            if p and p["status"] in POINT_DONE_STATES and not force:
                return 409, {"error": f"point {p['id']} already processed ({p['status']}); use force"}

        # Current membership, modified in memory, then re-ordered and re-stored in place.
        rows = conn.execute("SELECT point_id, photo_id, side FROM photo_cmp_point_photos WHERE run_id=?",
                            (run_id,)).fetchall()
        members = {}
        for r in rows:
            members.setdefault(r["point_id"], {"baseline": [], "followup": []})[r["side"]].append(r["photo_id"])
        members[src["id"]][row["side"]].remove(photo_id)
        new_pid = None
        if dst:
            members[dst["id"]][row["side"]].append(photo_id)
            conn.execute("UPDATE photo_cmp_point_photos SET point_id=?, match_confidence=NULL, match_reason=? "
                         "WHERE id=?", (dst["id"], f"re-assigned by {actor}", row["id"]))
        else:
            now = _now()
            new_pid = conn.execute(
                "INSERT INTO photo_cmp_points (run_id, seq, kind, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)", (run_id, 0, "no_followup", "UNCONFIRMED", now, now)).lastrowid
            members[new_pid] = {"baseline": [], "followup": []}
            members[new_pid][row["side"]].append(photo_id)
            conn.execute("UPDATE photo_cmp_point_photos SET point_id=?, match_confidence=NULL, match_reason=? "
                         "WHERE id=?", (new_pid, f"re-assigned by {actor}", row["id"]))
        touched = [src["id"], dst["id"] if dst else new_pid]
        removed = None
        if not members[src["id"]]["baseline"] and not members[src["id"]]["followup"]:
            if conn.execute("SELECT 1 FROM photo_cmp_changes WHERE point_id=? AND source='human'",
                            (src["id"],)).fetchone():
                return 409, {"error": "the point would be removed but has reviewer observations"}
            conn.execute("DELETE FROM photo_cmp_changes WHERE point_id=?", (src["id"],))
            conn.execute("DELETE FROM photo_cmp_points WHERE id=?", (src["id"],))
            del members[src["id"]]
            removed = src["id"]
        for pid in touched:
            if pid in members:
                _reset_point(conn, pid)
                k = _kind(members[pid])
                conn.execute("UPDATE photo_cmp_points SET kind=?, status='UNCONFIRMED', confirmed=0, "
                             "confirmed_by=NULL, confirmed_at=NULL, match_confidence=NULL, updated_at=? WHERE id=?",
                             (k, _now(), pid))
        bpos = {i: n for n, i in enumerate(run["baseline_ids"])}
        fpos = {i: n for n, i in enumerate(run["followup_ids"])}
        listed = [dict(members[pid], id=pid) for pid in members]
        for seq, p in enumerate(_order_points(listed, bpos, fpos), 1):
            conn.execute("UPDATE photo_cmp_points SET seq=? WHERE id=?", (seq, p["id"]))
        conn.commit()
    finally:
        conn.close()
    log_event("PHOTO_REASSIGNED", actor, run_id, details={
        "photo_id": photo_id, "side": row["side"], "from_point": src["id"],
        "to_point": dst["id"] if dst else new_pid, "removed_empty_point": removed, "force": force})
    return 200, {"ok": True, "to_point": dst["id"] if dst else new_pid, "removed_empty_point": removed}


def review_change(change_id, action, actor):
    if action not in REVIEW_ACTIONS:
        return 400, {"error": "action must be confirm, reject or reshoot"}
    conn = _conn()
    c = conn.execute("SELECT c.*, p.run_id FROM photo_cmp_changes c JOIN photo_cmp_points p ON p.id=c.point_id "
                     "WHERE c.id=?", (change_id,)).fetchone()
    if not c:
        conn.close()
        return 404, {"error": "change not found"}
    if c["discarded"]:
        conn.close()
        return 409, {"error": "change was discarded by verification"}
    if c["source"] == "human":
        conn.close()
        return 409, {"error": "reviewer observations are not reviewed"}
    if c["review_status"] != "UNREVIEWED":
        conn.close()
        return 409, {"error": "change is already reviewed; undo the decision first"}
    new = REVIEW_ACTIONS[action]
    conn.execute("UPDATE photo_cmp_changes SET review_status=?, reviewer=?, reviewed_at=? WHERE id=?",
                 (new, actor, _now(), change_id))
    conn.commit()
    conn.close()
    log_event("CHANGE_REVIEWED", actor, c["run_id"], c["point_id"], change_id,
              details={"old": c["review_status"], "new": new})
    return 200, {"ok": True, "review_status": new}


def _closing_conclusion(conn, run_id):
    """The accepted conclusion that closed a risk on this run's evidence, if any (blocks review undo)."""
    r = conn.execute("SELECT rc.id, rc.risk_id FROM risk_conclusions rc JOIN risks r ON r.id=rc.risk_id "
                     "WHERE rc.run_id=? AND rc.status='CLOSED' AND r.status IN ('RESOLVED','DISMISSED') "
                     "ORDER BY rc.id DESC LIMIT 1", (run_id,)).fetchone()
    return {"conclusion_id": r["id"], "risk_id": r["risk_id"]} if r else None


def undo_review(change_id, actor):
    """Return a reviewed system change to UNREVIEWED. The previous decision is kept in the event log."""
    conn = _conn()
    c = conn.execute("SELECT c.*, p.run_id FROM photo_cmp_changes c JOIN photo_cmp_points p ON p.id=c.point_id "
                     "WHERE c.id=?", (change_id,)).fetchone()
    if not c:
        conn.close()
        return 404, {"error": "change not found"}
    if c["source"] != "system" or c["discarded"]:
        conn.close()
        return 409, {"error": "only reviewed system changes can be undone"}
    if c["review_status"] == "UNREVIEWED":
        conn.close()
        return 409, {"error": "change is not reviewed"}
    lock = _closing_conclusion(conn, c["run_id"])
    if lock:
        conn.close()
        return 409, {"error": "Vispirms jāatceļ slēdziena lēmums", "locked_by": lock}
    conn.execute("UPDATE photo_cmp_changes SET review_status='UNREVIEWED', reviewer=NULL, reviewed_at=NULL WHERE id=?",
                 (change_id,))
    conn.commit()
    conn.close()
    log_event("CHANGE_REVIEW_UNDONE", actor, c["run_id"], c["point_id"], change_id,
              details={"old": c["review_status"], "old_reviewer": c["reviewer"], "old_reviewed_at": c["reviewed_at"]})
    return 200, {"ok": True, "review_status": "UNREVIEWED"}


# ── B / C / D per point ───────────────────────────────────────────────────────
def confidence_category(same_place, comparability, verification):
    # high requires comparability "suitable": a change on a "partial" point can never be high.
    if same_place == "yes" and comparability == "suitable" and verification == "yes":
        return "high"
    if verification == "unsure" or (same_place == "partial" and comparability == "partial"):
        return "low"
    return "medium"


def _validate_check(a):
    sp, vs, cp, rc = (str(a.get(k, "")).lower()
                      for k in ("same_place", "viewpoint_shift", "comparability", "reason_code"))
    if sp not in SAME_PLACE or vs not in VIEWPOINT_SHIFT or cp not in COMPARABILITY or rc not in REASON_CODES:
        raise ValueError(f"bad enum values: {sp!r} {vs!r} {cp!r} {rc!r}")
    reason = str(a.get("reason", "")).strip()
    _check_text(reason)
    # Any camera shift caps comparability at "partial" (never upgraded, never forced to unsuitable).
    if vs != "none" and cp == "suitable":
        cp, reason = "partial", f"{reason} [comparability set to partial in code: viewpoint_shift={vs}]"
        if rc == "none":
            rc = "different_viewpoint"
    return {"same_place": sp, "comparability": cp, "reason_code": rc, "reason": reason, "viewpoint_shift": vs}


def _validate_detect(a):
    changes = a.get("changes")
    if not isinstance(changes, list):
        raise ValueError("changes is not a list")
    out = []
    for c in changes:
        k, cell, cl = str(c.get("kind", "")), str(c.get("cell", "")).lower(), str(c.get("class", ""))
        if k not in CHANGE_KINDS or cell not in CELLS or cl not in CHANGE_CLASSES:
            raise ValueError(f"bad change enums: {k!r} {cell!r} {cl!r}")
        if k == TRANSIENT_KIND:
            cl = "possible_change"            # enforced in code, whatever the model answered
        d, lim = str(c.get("description", "")).strip(), str(c.get("limits", "")).strip()
        if not d:
            raise ValueError("empty description")
        _check_text(d, lim)
        out.append({"kind": k, "cell": cell, "class": cl, "description": d, "limits": lim})
    limits = str(a.get("limits", "")).strip()
    _check_text(limits)
    return {"changes": out, "limits": limits}


def _validate_verify(a):
    v = str(a.get("verdict", "")).lower()
    if v not in VERDICTS:
        raise ValueError(f"bad verdict {v!r}")
    reason, landmark = str(a.get("reason", "")).strip(), str(a.get("landmark", "")).strip()
    _check_text(reason, landmark)
    if v == "yes" and not landmark:      # a "yes" must be anchored to a landmark seen in both photos
        v, reason = "unsure", f"{reason} [verdict set to unsure in code: no landmark given]"
    elif landmark:
        reason = f"{reason} (orientieris: {landmark})"
    return {"verdict": v, "reason": reason}


def _point_content(run, photos, prompt):
    content = []
    for p in photos["baseline"]:
        content += [{"type": "text", "text": f"bāzes foto id={p['id']} ({run['baseline_date']})"},
                    _image_block(p["image_path"], COMPARE_LONG_SIDE)]
    for p in photos["followup"]:
        content += [{"type": "text", "text": f"pēcfoto id={p['id']} ({run['followup_date']})"},
                    _image_block(p["image_path"], COMPARE_LONG_SIDE)]
    content.append({"type": "text", "text": prompt})
    return content


def _process_point(run, point_id, actor, force):
    conn = _conn()
    p = _point(conn, point_id)
    if force:
        _reset_point(conn, point_id)
        conn.execute("UPDATE photo_cmp_points SET status='CONFIRMED' WHERE id=?", (point_id,))
        conn.commit()
        p = _point(conn, point_id)
    ph = {"baseline": [], "followup": []}
    for r in conn.execute("SELECT pp.side, w.id, w.image_path, w.uploaded_at FROM photo_cmp_point_photos pp "
                          "JOIN work_photos w ON w.id=pp.photo_id WHERE pp.point_id=? ORDER BY w.uploaded_at, w.id",
                          (point_id,)):
        ph[r["side"]].append(dict(r))
    conn.close()
    fmt = {"baseline_date": run["baseline_date"], "followup_date": run["followup_date"], "language": _language()}

    def update(sql, params):
        c = _conn()
        c.execute(sql, params)
        c.commit()
        c.close()

    # B: same place + comparability
    if p["checked_at"] is None:
        update("UPDATE photo_cmp_points SET check_attempts=check_attempts+1 WHERE id=?", (point_id,))
        b = _call_vision(_point_content(run, ph, CHECK_PROMPT.format(**fmt)), "check", _validate_check,
                         400, run["id"], point_id, actor=actor)
        if not b:
            update("UPDATE photo_cmp_points SET status='FAILED', updated_at=? WHERE id=?", (_now(), point_id))
            return "failed"
        status = ("NOT_SAME_PLACE" if b["same_place"] == "no"
                  else "NOT_COMPARABLE" if b["comparability"] == "unsuitable" else "CHECKED")
        reason = f"{b['reason_code']}: {b['reason']}"
        update("UPDATE photo_cmp_points SET same_place=?, comparability=?, comparability_reason=?, checked_at=?, "
               "status=?, updated_at=? WHERE id=?",
               (b["same_place"], b["comparability"], reason, _now(), status, _now(), point_id))
        p.update(same_place=b["same_place"], comparability=b["comparability"], status=status)
    if p["status"] in ("NOT_SAME_PLACE", "NOT_COMPARABLE"):
        return p["status"].lower()               # never forced into a comparison

    # C: change detection
    if p["detected_at"] is None:
        update("UPDATE photo_cmp_points SET detect_attempts=detect_attempts+1 WHERE id=?", (point_id,))
        c = _call_vision(_point_content(run, ph, DETECT_PROMPT.format(**fmt)), "detect", _validate_detect,
                         1500, run["id"], point_id, actor=actor)
        if not c:
            update("UPDATE photo_cmp_points SET status='FAILED', updated_at=? WHERE id=?", (_now(), point_id))
            return "failed"
        conn = _conn()
        for ch in c["changes"]:
            conn.execute("INSERT INTO photo_cmp_changes (point_id, kind, cell, class, description, limits, created_at) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (point_id, ch["kind"], ch["cell"], ch["class"], ch["description"], ch["limits"], _now()))
        conn.execute("UPDATE photo_cmp_points SET detect_limits=?, detected_at=?, updated_at=? WHERE id=?",
                     (c["limits"], _now(), _now(), point_id))
        conn.commit()
        conn.close()

    # D: independent verification per change
    conn = _conn()
    pending = [dict(r) for r in conn.execute(
        "SELECT * FROM photo_cmp_changes WHERE point_id=? AND source='system' AND discarded=0 AND verification IS NULL", (point_id,))]
    conn.close()
    failed = False
    for ch in pending:
        update("UPDATE photo_cmp_changes SET verify_attempts=verify_attempts+1 WHERE id=?", (ch["id"],))
        prompt = VERIFY_PROMPT.format(kind=ch["kind"], cell=ch["cell"], description=ch["description"], **fmt)
        v = _call_vision(_point_content(run, ph, prompt), "verify", _validate_verify, 800,
                         run["id"], point_id, ch["id"], actor=actor)
        if not v:
            failed = True
            continue
        if v["verdict"] == "no":
            update("UPDATE photo_cmp_changes SET verification='no', verification_reason=?, discarded=1 WHERE id=?",
                   (v["reason"], ch["id"]))
            log_event("CHANGE_DISCARDED", actor, run["id"], point_id, ch["id"],
                      details={"reason": v["reason"], "description": ch["description"]})
        else:
            conf = confidence_category(p["same_place"], p["comparability"], v["verdict"])
            update("UPDATE photo_cmp_changes SET verification=?, verification_reason=?, confidence=? WHERE id=?",
                   (v["verdict"], v["reason"], conf, ch["id"]))
    update("UPDATE photo_cmp_points SET status=?, updated_at=? WHERE id=?",
           ("FAILED" if failed else "DONE", _now(), point_id))
    return "failed" if failed else "done"


# ── Background execution (one job at a time, one point at a time) ─────────────
_job_lock = threading.Lock()
_job = {"run_id": None, "thread": None}


def _busy():
    t = _job["thread"]
    return t is not None and t.is_alive()


def _start_job(run_id, status, target):
    with _job_lock:
        if _busy():
            return False
        _set_run_status(run_id, status)
        t = threading.Thread(target=target, name=f"photo-compare-{run_id}", daemon=True)
        _job.update(run_id=run_id, thread=t)
        t.start()
        return True


def start_matching(run_id, actor):
    conn = _conn()
    run = _run(conn, run_id)
    conn.close()
    if not run:
        return 404, {"error": "run not found"}
    if run["status"] != "CREATED":
        return 409, {"error": f"run already has points (status {run['status']})"}
    if len(run["baseline_ids"]) > MAX_POINTS_PER_RUN:
        return 400, {"error": f"more than {MAX_POINTS_PER_RUN} baseline photos"}

    def job():
        try:
            code, payload = _matching_pass(run_id, actor)
            if code != 200:
                log_event("MATCHING_FAILED", actor, run_id, details=payload)
                _set_run_status(run_id, "CREATED")
        except Exception as e:
            log_event("MATCHING_FAILED", actor, run_id, details=f"{type(e).__name__}: {e}")
            _set_run_status(run_id, "CREATED")

    log_event("MATCHING_REQUESTED", actor, run_id, details={"calls": len(run["baseline_ids"])})
    if not _start_job(run_id, "MATCHING", job):
        return 409, {"error": "another photo comparison job is running"}
    return 202, {"ok": True, "queued_calls": len(run["baseline_ids"])}


def start_processing(run_id, actor, limit=None, point_ids=None, force=False):
    """Run B/C/D for confirmed two-sided points, in capture order. Already processed points are
    skipped unless force. limit = first N eligible points (pilot)."""
    conn = _conn()
    run = _run(conn, run_id)
    if not run:
        conn.close()
        return 404, {"error": "run not found"}
    if run["status"] in ("CREATED", "MATCHING"):
        conn.close()
        return 409, {"error": f"run has no confirmed points yet (status {run['status']})"}
    states = ("CONFIRMED", "CHECKED", "FAILED") + (("NOT_SAME_PLACE", "NOT_COMPARABLE", "DONE") if force else ())
    q = ",".join("?" * len(states))
    rows = [dict(r) for r in conn.execute(
        f"SELECT id, seq FROM photo_cmp_points WHERE run_id=? AND kind='both' AND confirmed=1 AND status IN ({q}) "
        f"ORDER BY seq", (run_id,) + states)]
    conn.close()
    if point_ids:
        rows = [r for r in rows if r["id"] in set(point_ids)]
    if limit:
        rows = rows[:int(limit)]
    ids = [r["id"] for r in rows]
    if not ids:
        return 400, {"error": "no eligible confirmed two-sided points"}

    def job():
        try:
            for pid in ids:
                try:
                    res = _process_point(run, pid, actor, force)
                except Exception as e:
                    res = f"error {type(e).__name__}: {e}"
                    c = _conn()
                    c.execute("UPDATE photo_cmp_points SET status='FAILED', updated_at=? WHERE id=?", (_now(), pid))
                    c.commit()
                    c.close()
                log_event("POINT_PROCESSED", actor, run_id, pid, details={"result": res})
        finally:
            _set_run_status(run_id, "READY")

    log_event("PROCESS_REQUESTED", actor, run_id, details={"points": ids, "force": force})
    if not _start_job(run_id, "RUNNING", job):
        return 409, {"error": "another photo comparison job is running"}
    return 202, {"ok": True, "points": ids}


# ── Read side ─────────────────────────────────────────────────────────────────
CELL_WORDS = {
    "r1c1": "augšā pa kreisi", "r1c2": "augšā centrā", "r1c3": "augšā pa labi",
    "r2c1": "vidū pa kreisi", "r2c2": "centrā", "r2c3": "vidū pa labi",
    "r3c1": "apakšā pa kreisi", "r3c2": "apakšā centrā", "r3c3": "apakšā pa labi",
}


def build_report(run, points, changes):
    both = [p for p in points if p["kind"] == "both"]
    unmatched_b = sum(len(p["baseline"]) for p in points
                      if p["kind"] == "no_followup" or p["status"] == "NOT_SAME_PLACE_HUMAN")
    unmatched_f = sum(len(p["followup"]) for p in points
                      if p["kind"] == "no_baseline" or p["status"] == "NOT_SAME_PLACE_HUMAN")
    compared = [p for p in both if p["status"] == "DONE"]
    not_comparable = [p for p in both if p["status"] in RESHOOT_STATES]
    human = [c for c in changes if c["source"] == "human"]
    live = [c for c in changes if not c["discarded"] and c["source"] == "system"]
    by_class = {}
    for cl in CHANGE_CLASSES:
        counts = {s: 0 for s in ("UNREVIEWED", "CONFIRMED", "REJECTED", "RESHOOT")}
        for c in live:
            if c["class"] == cl:
                counts[c["review_status"]] += 1
        by_class[cl] = counts
    reshoot_pts = {p["id"] for p in not_comparable} | {c["point_id"] for c in live if c["review_status"] == "RESHOOT"}
    pending = [p for p in both if p["confirmed"] and p["status"] in ("CONFIRMED", "CHECKED", "FAILED")]
    report = {
        "photos_baseline": len(run["baseline_ids"]),
        "photos_followup": len(run["followup_ids"]),
        "points_total": len(points),
        "points_unconfirmed": sum(1 for p in points if p["status"] == "UNCONFIRMED"),
        "points_both_sides": len(both),
        "points_not_same_place_human": sum(1 for p in points if p["status"] == "NOT_SAME_PLACE_HUMAN"),
        "points_compared": len(compared),
        "points_not_comparable": len(not_comparable),
        "points_pending": len(pending),
        "points_no_followup": sum(1 for p in points if p["kind"] == "no_followup"),
        "points_no_baseline": sum(1 for p in points if p["kind"] == "no_baseline"),
        "photos_unmatched_baseline": unmatched_b,
        "photos_unmatched_followup": unmatched_f,
        "possible_change": by_class["possible_change"],
        "possible_damage": by_class["possible_damage"],
        "changes_discarded_by_verification": sum(1 for c in changes if c["discarded"] and c["source"] == "system"),
        "points_needing_reshoot": len(reshoot_pts),
        "summary_lines": [],
    }
    # "No changes" wording: only changes that are not discarded, not rejected by the reviewer and not
    # transient objects count. Unreviewed, confirmed and re-shoot changes still block it.
    rejected = [c for c in live if c["review_status"] == "REJECTED"]
    transient = [c for c in live if c["kind"] == TRANSIENT_KIND]
    human_active = [c for c in human if c["review_status"] != "WITHDRAWN"]
    human_withdrawn = len(human) - len(human_active)
    blocking = [c for c in live if c["review_status"] != "REJECTED" and c["kind"] != TRANSIENT_KIND] + human_active
    report["human_observations"] = dict({cl: sum(1 for c in human_active if c["class"] == cl) for cl in CHANGE_CLASSES},
                                        withdrawn=human_withdrawn)
    report["changes_rejected_by_reviewer"] = len(rejected)
    report["transient_objects"] = len(transient)
    if compared and not blocking:
        report["summary_lines"] = list(NO_CHANGES_LINES)
        if rejected:
            report["summary_lines"].append(REJECTED_LINE.format(n=len(rejected)))
    if human:                                  # own line, separate from system-detected changes
        report["summary_lines"].append(
            OBSERVATION_LINE_WITHDRAWN.format(n=len(human_active), w=human_withdrawn) if human_withdrawn
            else OBSERVATION_LINE.format(n=len(human_active)))
    return report


def get_run(run_id):
    conn = _conn()
    run = _run(conn, run_id)
    if not run:
        conn.close()
        return None
    if run["status"] in ("RUNNING", "MATCHING") and not (_busy() and _job["run_id"] == run_id):
        run["status"] = "INTERRUPTED"          # display only; a new request resumes idempotently
    points = [dict(r) for r in conn.execute("SELECT * FROM photo_cmp_points WHERE run_id=? ORDER BY seq", (run_id,))]
    photos = {}
    for r in conn.execute(
            "SELECT pp.point_id, pp.side, pp.match_confidence, pp.match_reason, w.id, w.sector, w.session_id, "
            "w.photo_type, w.image_path, w.uploaded_at FROM photo_cmp_point_photos pp "
            "JOIN work_photos w ON w.id=pp.photo_id WHERE pp.run_id=? ORDER BY w.uploaded_at, w.id", (run_id,)):
        d = dict(r)
        d["filename"] = os.path.basename(d["image_path"] or "")
        photos.setdefault(d["point_id"], {"baseline": [], "followup": []})[d["side"]].append(d)
    changes = [dict(r) for r in conn.execute(
        "SELECT c.* FROM photo_cmp_changes c JOIN photo_cmp_points p ON p.id=c.point_id WHERE p.run_id=? "
        "ORDER BY p.seq, c.id", (run_id,))]
    history = {}
    for e in conn.execute("SELECT change_id, event_type, actor, details, created_at FROM photo_cmp_events "
                          "WHERE run_id=? AND event_type IN ('CHANGE_REVIEWED','CHANGE_REVIEW_UNDONE') ORDER BY id",
                          (run_id,)):
        d = json.loads(e["details"] or "{}")
        history.setdefault(e["change_id"], []).append({"type": e["event_type"], "actor": e["actor"],
                                                       "at": e["created_at"], "old": d.get("old"), "new": d.get("new")})
    run["locked_by_conclusion"] = _closing_conclusion(conn, run_id)
    conn.close()
    for c in changes:
        c["cell_words"] = CELL_WORDS.get(c["cell"], c["cell"])
        c["history"] = history.get(c["id"], [])
    by_point = {}
    for c in changes:
        by_point.setdefault(c["point_id"], []).append(c)
    for p in points:
        ph = photos.get(p["id"], {"baseline": [], "followup": []})
        p["baseline"], p["followup"] = ph["baseline"], ph["followup"]
        p["changes"] = by_point.get(p["id"], [])
        p["reshoot_needed"] = p["status"] in RESHOOT_STATES or any(
            c["review_status"] == "RESHOOT" and not c["discarded"] for c in p["changes"])
    run.pop("baseline_photo_ids")
    run.pop("followup_photo_ids")
    report = build_report(run, points, changes)
    return {"run": run, "points": points, "report": report}


def add_observation(point_id, text, change_class, actor):
    """A reviewer's own observation on any point (one-sided included). Stored as a human-entered change:
    no cell, no verification, no confidence, no review; never sent to a paid call."""
    text = (text or "").strip()
    if change_class not in CHANGE_CLASSES:
        return 400, {"error": "class must be possible_change or possible_damage"}
    if not 3 <= len(text) <= OBSERVATION_MAX_LEN:
        return 400, {"error": f"text must be 3-{OBSERVATION_MAX_LEN} characters"}
    conn = _conn()
    p = _point(conn, point_id)
    if not p:
        conn.close()
        return 404, {"error": "point not found"}
    cid = conn.execute(
        "INSERT INTO photo_cmp_changes (point_id, kind, cell, class, description, limits, source, created_by, "
        "review_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (point_id, HUMAN_KIND, "", change_class, text, "", "human", actor, "HUMAN", _now())).lastrowid
    conn.commit()
    conn.close()
    log_event("HUMAN_OBSERVATION_ADDED", actor, p["run_id"], point_id, cid,
              details={"class": change_class, "text": text})
    return 200, {"ok": True, "change_id": cid}


def withdraw_observation(change_id, actor):
    """Withdraw a reviewer observation: it stays stored (struck through in the UI), records who and when,
    and no longer blocks the "no changes" wording."""
    conn = _conn()
    c = conn.execute("SELECT c.*, p.run_id FROM photo_cmp_changes c JOIN photo_cmp_points p ON p.id=c.point_id "
                     "WHERE c.id=?", (change_id,)).fetchone()
    if not c:
        conn.close()
        return 404, {"error": "observation not found"}
    if c["source"] != "human":
        conn.close()
        return 409, {"error": "only reviewer observations can be withdrawn"}
    if c["review_status"] == "WITHDRAWN":
        conn.close()
        return 409, {"error": "observation already withdrawn"}
    now = _now()
    conn.execute("UPDATE photo_cmp_changes SET review_status='WITHDRAWN', reviewer=?, reviewed_at=? WHERE id=?",
                 (actor, now, change_id))
    conn.commit()
    conn.close()
    log_event("HUMAN_OBSERVATION_WITHDRAWN", actor, c["run_id"], c["point_id"], change_id,
              details={"class": c["class"], "text": c["description"]})
    return 200, {"ok": True}


def list_runs(sector=None):
    conn = _conn()
    sql, params = "SELECT id, sector, baseline_date, followup_date, status, created_by, created_at, updated_at " \
                  "FROM photo_cmp_runs", ()
    if sector:
        sql, params = sql + " WHERE sector=?", (sector,)
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY id DESC", params)]
    conn.close()
    return rows


def get_events(run_id):
    conn = _conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM photo_cmp_events WHERE run_id=? ORDER BY id", (run_id,))]
    conn.close()
    return rows
