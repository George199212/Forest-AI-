#!/usr/bin/env python3
"""
Copy one real field case (one sector) from another Forest AI instance into the read-only review
instance (ACCESS_MODE=review): anonymized, translated to English, photos without metadata.

Source safety
  * The source DB is opened read-only (sqlite URI mode=ro) and copied with the SQLite backup API;
    source photo files are only read. sha256 of the source DB and of every source file is taken
    before and after; the run fails if anything changed.
Target safety
  * Same guard as scripts/seed_review_demo.py: ACCESS_MODE=review, DB_PATH set, the owning
    instance's .env has ACCESS_MODE=review, never /root/forest_ai or /root/forest_ai_rm.
  * Explicit table allowlist (ALLOWLIST). Everything else in the source is ignored.
  * Idempotent: rows of a previous import of the same target sector are removed first.
Ids
  * Source ids are kept where they are free in the target, so ids inside JSON and free text stay
    consistent. Tables in REMAP (ids that collide with the seeded demo data) get new ids, and every
    reference to them (columns, {EMP:n}/{TP:n} placeholders in translations) is rewritten.
Text
  * Every text value (JSON parsed and walked, nested JSON too) goes through: mask known names ->
    manual translation pairs (--translations, longest first) -> placeholders -> anonymization ->
    sector code. The run fails if any Latvian/Cyrillic letter, any masked name or any name from
    --names-file remains anywhere in the target DB or in the copied file names.
  * Translations are supplied as a private file (not part of the repository): pairs of masked source
    text and English. No API call of any kind is made.

Usage
  cd /root/forest_ai_review && set -a && . ./.env && set +a && python3 scripts/import_case_anonymized.py \
     --source-root <source instance root> --sector <SOURCE-SECTOR> --new-sector FIELD-TEST-01 \
     --object-name "<object name shown in the review UI>" \
     --translations <private translations.json> \
     [--names-file /path/private_names.txt] [--report-csv out.csv] [--dry-run]
"""

import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scripts.seed_review_demo import check_target  # same target guard as the seed

WORKER_NAME = "Field Worker 01"
WORKER_ACTOR = "field-worker-01"
TEAM_ACTOR = "forest-ai-team"
TEAM_NAME = "Forest AI team"
IMPORT_ACTOR = "review-import"
PROVENANCE = ("Real field test performed by the Forest AI team (own photos, Oct 2026). "
              "Anonymized and translated from Latvian for demonstration.")
STATUS_MAP = {"Monitorings": "Monitoring"}

# table -> how rows are selected from the (filtered) source; order = insert order
ALLOWLIST = [
    ("sectors", "name = :sector"),
    ("sector_employees", "sector = :sector"),
    ("work_sessions", "sector = :sector"),
    ("session_track_points", "session_id IN (SELECT id FROM work_sessions WHERE sector = :sector)"),
    ("live_locations", "sector = :sector"),
    ("work_photos", "sector = :sector"),
    ("risks", "sector = :sector"),
    ("risk_events", "risk_id IN (SELECT id FROM risks WHERE sector = :sector)"),
    ("photo_cmp_runs", "sector = :sector"),
    ("photo_cmp_points", "run_id IN (SELECT id FROM photo_cmp_runs WHERE sector = :sector)"),
    ("photo_cmp_point_photos", "run_id IN (SELECT id FROM photo_cmp_runs WHERE sector = :sector)"),
    ("photo_cmp_changes", "point_id IN (SELECT p.id FROM photo_cmp_points p JOIN photo_cmp_runs r "
                          "ON r.id = p.run_id WHERE r.sector = :sector)"),
    ("photo_cmp_events", "run_id IN (SELECT id FROM photo_cmp_runs WHERE sector = :sector)"),
    ("risk_conclusions", "risk_id IN (SELECT id FROM risks WHERE sector = :sector)"),
]
REMAP = {"sector_employees", "session_track_points"}
# columns that reference a remapped table
FK = {
    ("work_sessions", "employee_id"): "sector_employees",
    ("session_track_points", "employee_id"): "sector_employees",
    ("live_locations", "employee_id"): "sector_employees",
    ("risks", "entity_id"): "sector_employees",  # only when entity_type = EMPLOYEE
}
NULL_COLUMNS = {  # personal identifiers / Telegram linkage
    "sector_employees": ("phone", "id_number", "telegram_user_id", "notes"),
    "work_sessions": ("user_id",),
    "session_track_points": ("telegram_user_id",),
    "live_locations": ("telegram_user_id",),
    "risks": ("telegram_message_id",),
}
ACTOR_COLUMNS = {
    "risk_events": ("actor",), "risk_conclusions": ("created_by", "decided_by", "undone_by"),
    "photo_cmp_runs": ("created_by",), "photo_cmp_points": ("confirmed_by",),
    "photo_cmp_changes": ("reviewer",), "photo_cmp_events": ("actor",),
}
ACTOR_KEYS = {"actor", "old_reviewer", "reviewer", "created_by", "confirmed_by", "decided_by", "undone_by"}
SYSTEM_ACTORS = {"ai", "ai_worker", "ai_fallback", "system", "photo_compare", "risk_conclusion", "worker_sos", None, ""}
FILE_COLUMNS = {("work_photos", "image_path"), ("sectors", "satellite_file_path"), ("sectors", "image_path"),
                ("risks", "photo_path"), ("risks", "photo_path_2")}

NON_ENGLISH = re.compile(r"[āčēģīķļņšūžĀČĒĢĪĶĻŅŠŪŽЀ-ӿ]")
LV_WORDS = re.compile(r"\b(nav|ir|un|vai|uz|ar|kas|bet|tikai|pēc|koks|koku|zonā|redzams|redzami|izmaiņas|"
                      r"sektorā|sektora|lūdzu|darbinieks|darbinieku|sesija|apsekot|fotogrāfijā)\b", re.I)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_fingerprint(source_root):
    files = {}
    for sub in ("data/forest_ai.db", "data/work_photos", "data/sector_satellite", "data/object_satellite",
                "data/sector_snapshots", "data/boundary_plans"):
        p = os.path.join(source_root, sub)
        if os.path.isfile(p):
            files[sub] = sha256(p)
        elif os.path.isdir(p):
            for d, _, fs in os.walk(p):
                for f in fs:
                    fp = os.path.join(d, f)
                    files[os.path.relpath(fp, source_root)] = sha256(fp)
    return files


# ── metadata stripping (lossless: segments/chunks are dropped, image data is not re-encoded) ──

def strip_jpeg(data):
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    out, i = bytearray(b"\xff\xd8"), 2
    while i < len(data):
        if data[i] != 0xFF:
            raise ValueError("bad JPEG marker")
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: copy the rest verbatim
            out += data[i:]
            break
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        seg = data[i:i + 2 + seg_len]
        keep = marker in (0xE0, 0xEE) or not (0xE1 <= marker <= 0xEF or marker == 0xFE)  # APP0 JFIF, APP14 Adobe
        if keep:
            out += seg
        i += 2 + seg_len
    return bytes(out)


def strip_png(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    out, i = bytearray(data[:8]), 8
    while i < len(data):
        length = int.from_bytes(data[i:i + 4], "big")
        ctype = data[i + 4:i + 8]
        chunk = data[i:i + 12 + length]
        if ctype not in (b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"):
            out += chunk
        i += 12 + length
    return bytes(out)


def copy_stripped(src, dst):
    with open(src, "rb") as f:
        data = f.read()
    low = src.lower()
    clean = strip_png(data) if low.endswith(".png") else strip_jpeg(data)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f:
        f.write(clean)


def exif_report(path):
    from PIL import Image
    with Image.open(path) as im:
        ex = im.getexif()
        gps = ex.get_ifd(0x8825) if ex else {}
        info_keys = [k for k in (im.info or {}) if k.lower() in ("exif", "xmp", "comment", "gps")]
    with open(path, "rb") as f:
        raw = f.read()
    return {"exif_tags": len(ex), "gps": bool(gps), "info": info_keys, "exif_marker": b"Exif\x00\x00" in raw}


# ── text pipeline ─────────────────────────────────────────────────────────────

def fold(s):
    """ASCII variant of a name (diacritics removed), so both spellings are masked/checked."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def client_patterns(names):
    """Regexes for the source organisation's names (taken from the source DB at run time)."""
    out = []
    for n in {n for n in names if n and len(n) > 2}:
        for v in {n, fold(n)}:
            out.append(re.compile(r"\s*".join(re.escape(w) for w in re.split(r"[\s-]+", v) if w), re.I))
    return out


class Text:
    def __init__(self, pairs, employee_names, old_sector, new_sector, idmap, extra_names, client_names=()):
        self.pairs = sorted(pairs, key=lambda p: len(p["src"]), reverse=True)
        tokens = sorted({t for n in employee_names for t in re.split(r"\s+", n) if len(t) > 2} | set(employee_names),
                        key=len, reverse=True)
        self.mask = [(re.compile(re.escape(t), re.I), "[[PERSON]]") for t in tokens]
        self.clients = client_patterns(client_names)
        self.mask += [(rx, "[[CLIENT]]") for rx in self.clients]
        self.old_sector, self.new_sector = old_sector, new_sector
        self.old_sector_us, self.new_sector_us = old_sector.replace("-", "_"), new_sector.replace("-", "_")
        self.idmap = idmap
        self.extra_names = [n for n in extra_names if n]

    def text(self, s):
        if s is None:
            return None
        out = s
        for rx, rep in self.mask:
            out = rx.sub(rep, out)
        for p in self.pairs:
            if p["src"] in out:
                out = out.replace(p["src"], p["en"])
        out = re.sub(r"\{EMP:(\d+)\}", lambda m: str(self.idmap["sector_employees"][int(m.group(1))]), out)
        out = re.sub(r"\{TP:(\d+)\}", lambda m: str(self.idmap["session_track_points"][int(m.group(1))]), out)
        out = out.replace("[[PERSON]] [[PERSON]]", WORKER_NAME).replace("[[PERSON]]", WORKER_NAME)
        out = out.replace("[[CLIENT]]", TEAM_NAME).replace("Test User", WORKER_NAME)
        out = out.replace(self.old_sector, self.new_sector).replace(self.old_sector_us, self.new_sector_us)
        return STATUS_MAP.get(out, out)

    def value(self, v, key=None):
        if isinstance(v, str):
            st = v.strip()
            if st[:1] in "{[":
                try:
                    return json.dumps(self.value(json.loads(st)), ensure_ascii=False)
                except ValueError:
                    pass
            if key in ACTOR_KEYS:
                return actor(v)
            return self.text(v)
        if isinstance(v, dict):
            return {k: (self._json_leaf(x, k)) for k, x in v.items()}
        if isinstance(v, list):
            return [self._json_leaf(x, None) for x in v]
        return v

    def _json_leaf(self, x, k):
        if isinstance(x, str):
            st = x.strip()
            if st[:1] in "{[":
                try:
                    return self.value(json.loads(st))
                except ValueError:
                    pass
            return actor(x) if k in ACTOR_KEYS else self.text(x)
        return self.value(x, k)


def actor(v):
    if v in SYSTEM_ACTORS or v is None:
        return v
    if re.match(r"^(employee|telegram):", v or ""):
        return WORKER_ACTOR
    return TEAM_ACTOR  # dashboard Basic-auth usernames (admin, client login, ...)


# ── import ────────────────────────────────────────────────────────────────────

def columns(conn, table):
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def wipe_previous(cur, new_sector):
    s = {"s": new_sector}
    d = {}

    def rm(t, where):
        n = cur.execute(f"DELETE FROM {t} WHERE {where}", s).rowcount
        if n:
            d[t] = d.get(t, 0) + n
    rm("risk_conclusions", "risk_id IN (SELECT id FROM risks WHERE sector=:s)")
    rm("risk_evidence", "risk_id IN (SELECT id FROM risks WHERE sector=:s)")
    rm("risk_events", "risk_id IN (SELECT id FROM risks WHERE sector=:s)")
    rm("photo_cmp_events", "run_id IN (SELECT id FROM photo_cmp_runs WHERE sector=:s)")
    rm("photo_cmp_changes", "point_id IN (SELECT p.id FROM photo_cmp_points p JOIN photo_cmp_runs r ON r.id=p.run_id WHERE r.sector=:s)")
    rm("photo_cmp_point_photos", "run_id IN (SELECT id FROM photo_cmp_runs WHERE sector=:s)")
    rm("photo_cmp_points", "run_id IN (SELECT id FROM photo_cmp_runs WHERE sector=:s)")
    rm("photo_cmp_runs", "sector=:s")
    rm("session_track_points", "session_id IN (SELECT id FROM work_sessions WHERE sector=:s)")
    for t in ("risks", "work_photos", "live_locations", "work_sessions", "sector_employees"):
        rm(t, "sector=:s")
    rm("boundary_plans", "id IN (SELECT boundary_plan_id FROM sectors WHERE name=:s) AND uploaded_by='review-import'")
    rm("sectors", "name=:s")
    return d


def run(args):
    target_db = check_target()
    source_root = os.path.realpath(args.source_root)
    source_db = os.path.join(source_root, "data", "forest_ai.db")
    target_root = os.path.dirname(os.path.dirname(target_db))
    if os.path.realpath(target_root) == source_root:
        sys.exit("REFUSED: source and target are the same instance")
    with open(args.translations, encoding="utf-8") as f:
        pairs = json.load(f)["pairs"]
    extra_names = []
    if args.names_file:
        with open(args.names_file, encoding="utf-8") as f:
            extra_names = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    fp_before = source_fingerprint(source_root)
    work = tempfile.mkdtemp(prefix="forest_import_")
    snap = os.path.join(work, "source.db")
    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    dst = sqlite3.connect(snap)
    src.backup(dst)
    src.close()
    dst.close()

    s = sqlite3.connect(snap)
    s.row_factory = sqlite3.Row
    t = sqlite3.connect(target_db)
    t.row_factory = sqlite3.Row
    t.execute("PRAGMA foreign_keys=OFF")
    cur = t.cursor()
    table_rows = {}
    report = []  # (table, column, row_id, translated, anonymized)
    files_copied = []
    try:
        cur.execute("BEGIN")
        wiped = wipe_previous(cur, args.new_sector)
        params = {"sector": args.sector}
        src_rows = {tb: [dict(r) for r in s.execute(f"SELECT * FROM {tb} WHERE {where} ORDER BY id", params)]
                    for tb, where in ALLOWLIST}
        if not src_rows["sectors"]:
            raise SystemExit(f"ERROR: sector {args.sector!r} not found in the source")
        employee_names = [r["full_name"] for r in src_rows["sector_employees"] if r.get("full_name")]
        client_names = [v for row in s.execute("SELECT name, slug FROM organizations") for v in row]
        client_names += [r.get("contractor") for r in src_rows["sectors"] + src_rows["work_sessions"]]

        # id collisions for kept ids
        idmap = {tb: {} for tb, _ in ALLOWLIST}
        for tb, _ in ALLOWLIST:
            if tb in REMAP:
                continue
            ids = [r["id"] for r in src_rows[tb]]
            if ids:
                q = ",".join("?" for _ in ids)
                clash = [r[0] for r in cur.execute(f"SELECT id FROM {tb} WHERE id IN ({q})", ids)]
                if clash:
                    raise SystemExit(f"ERROR: id collision in {tb}: {clash[:10]} (add {tb} to REMAP)")
            idmap[tb] = {i: i for i in ids}
        # remapped tables get their new ids when inserted; pre-compute employee ids first (texts refer to them)
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        cur.execute("INSERT INTO boundary_plans (file_path, document_type, uploaded_at, status, uploaded_by, plan_data_json, object_name) "
                    "VALUES ('', 'manual_object', ?, 'uploaded', ?, '{}', ?)", (now, IMPORT_ACTOR, args.object_name))
        plan_id = cur.lastrowid
        tcols = {tb: columns(t, tb) for tb, _ in ALLOWLIST}
        for r in src_rows["sector_employees"]:
            cur.execute("INSERT INTO sector_employees (sector, full_name, role, phone, id_number, notes, active, created_at, telegram_user_id) "
                        "VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?, NULL)",
                        (args.new_sector, WORKER_NAME, r.get("role"), r.get("active", 1), r.get("created_at")))
            idmap["sector_employees"][r["id"]] = cur.lastrowid
            report.append(("sector_employees", "full_name", cur.lastrowid, "n/a", "yes"))
            for c in NULL_COLUMNS["sector_employees"]:
                if r.get(c):
                    report.append(("sector_employees", c, cur.lastrowid, "n/a", "yes (NULL)"))
        # track point ids are referenced in texts as well: insert them before translating anything
        sess_ids = {r["id"] for r in src_rows["work_sessions"]}
        for r in src_rows["session_track_points"]:
            cur.execute("INSERT INTO session_track_points (session_id, employee_id, telegram_user_id, live_message_id, sector, "
                        "latitude, longitude, horizontal_accuracy, inside_boundary, recorded_at, received_at) "
                        "VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (r["session_id"] if r["session_id"] in sess_ids else None,
                         idmap["sector_employees"].get(r.get("employee_id")), r.get("live_message_id"), args.new_sector,
                         r["latitude"], r["longitude"], r.get("horizontal_accuracy"), r.get("inside_boundary"),
                         r["recorded_at"], r.get("received_at")))
            idmap["session_track_points"][r["id"]] = cur.lastrowid
            if r.get("telegram_user_id"):
                report.append(("session_track_points", "telegram_user_id", cur.lastrowid, "n/a", "yes (NULL)"))

        tx = Text(pairs, employee_names, args.sector, args.new_sector, idmap, extra_names, client_names)

        for tb, _ in ALLOWLIST:
            if tb in REMAP:
                table_rows[tb] = len(src_rows[tb])
                continue
            for r in src_rows[tb]:
                row = {k: v for k, v in r.items() if k in tcols[tb]}
                rid = row["id"]
                for c in NULL_COLUMNS.get(tb, ()):
                    if row.get(c) not in (None, ""):
                        report.append((tb, c, rid, "n/a", "yes (NULL)"))
                    row[c] = None
                for c, ref in FK.items():
                    if c[0] == tb and row.get(c[1]) is not None:
                        if tb == "risks" and row.get("entity_type") != "EMPLOYEE":
                            continue
                        row[c[1]] = idmap[ref].get(row[c[1]])
                for c in ACTOR_COLUMNS.get(tb, ()):
                    if c in row:
                        new = actor(row[c])
                        if new != row[c]:
                            report.append((tb, c, rid, "n/a", "yes"))
                        row[c] = new
                for c, v in list(row.items()):
                    if not isinstance(v, str) or c in ACTOR_COLUMNS.get(tb, ()):
                        continue
                    new = tx.value(v)
                    if (tb, c) in FILE_COLUMNS and new:
                        new = new.replace(args.sector, args.new_sector)
                    if new != v:
                        foreign = bool(NON_ENGLISH.search(v)) or len(LV_WORDS.findall(v)) >= 2
                        anon = any(rx.search(v) for rx, _ in tx.mask) or "Test User" in v
                        if foreign or anon:
                            report.append((tb, c, rid, "yes" if foreign else "no (English source)",
                                           "yes" if anon else "no"))
                    row[c] = new
                if tb == "work_sessions":
                    row["employee"] = WORKER_NAME
                    row["contractor"] = TEAM_NAME
                if tb == "sectors":
                    row.update(name=args.new_sector, contractor=TEAM_NAME, object_name=args.object_name,
                               boundary_plan_id=plan_id, notes=(row.get("notes") or "").rstrip() + " " + PROVENANCE)
                    if "data_origin" in tcols[tb]:
                        row["data_origin"] = "REAL"
                if tb == "risks":
                    row.setdefault("is_demo", 0)
                    if "data_origin" in tcols[tb]:
                        row["data_origin"] = "REAL"
                # files
                for c in ("image_path", "satellite_file_path", "photo_path", "photo_path_2"):
                    if (tb, c) in FILE_COLUMNS and r.get(c):
                        src_file = os.path.join(source_root, os.path.normpath(r[c]))
                        if not os.path.normpath(r[c]).startswith("data/") or not os.path.isfile(src_file):
                            raise SystemExit(f"ERROR: unexpected file path in {tb}.{c} #{rid}")
                        rel = os.path.normpath(row[c])
                        staged = os.path.join(work, "files", rel)
                        copy_stripped(src_file, staged)
                        files_copied.append((staged, os.path.join(target_root, rel)))
                cols = list(row)
                cur.execute(f"INSERT INTO {tb} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                            [row[c] for c in cols])
            table_rows[tb] = len(src_rows[tb])

        for r in src_rows["risks"]:
            cur.execute("INSERT INTO risk_events (risk_id, event_type, actor, details, created_at) VALUES (?, 'IMPORTED_CASE', ?, ?, ?)",
                        (r["id"], IMPORT_ACTOR, PROVENANCE, now))

        problems = verify(cur, tx, target_root, files_copied, args)
        if problems:
            raise SystemExit("ABORTED (rolled back):\n  " + "\n  ".join(problems[:40]))
        exif = [exif_report(staged) for staged, _ in files_copied]
        bad = [d for (st, d), e in zip(files_copied, exif) if e["exif_tags"] or e["gps"] or e["exif_marker"] or e["info"]]
        if bad:
            raise SystemExit(f"ABORTED (rolled back): metadata left in {len(bad)} file(s)")
        if args.dry_run:
            t.rollback()
        else:
            t.commit()
            for staged, final in files_copied:  # only after the DB commit
                os.makedirs(os.path.dirname(final), exist_ok=True)
                shutil.move(staged, final)
    except BaseException:
        t.rollback()
        raise
    finally:
        s.close()
        integrity = t.execute("PRAGMA integrity_check").fetchone()[0]
        t.close()
        shutil.rmtree(work, ignore_errors=True)

    fp_after = source_fingerprint(source_root)
    changed = sorted(k for k in set(fp_before) | set(fp_after) if fp_before.get(k) != fp_after.get(k))

    if args.report_csv:
        with open(args.report_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["table", "column", "row_id", "translated", "anonymized"])
            w.writerows(report)
    if not args.dry_run:
        exif = [exif_report(final) for _, final in files_copied]
    print(f"target DB       : {target_db}{'  (DRY RUN, rolled back)' if args.dry_run else ''}")
    print(f"previous import : {wiped or 'none'}")
    print(f"object id       : {plan_id}; sector {args.sector} -> {args.new_sector}")
    print("rows imported   :", table_rows, "+ risk_events IMPORTED_CASE:", len(src_rows["risks"]))
    print("id remap        :", {k: v for k, v in idmap.items() if k in REMAP})
    print(f"fields changed  : {len(report)} (translated {sum(1 for x in report if x[3]=='yes')}, "
          f"anonymized {sum(1 for x in report if x[4].startswith('yes'))})")
    print(f"files copied    : {len(files_copied)} (metadata stripped)")
    if exif:
        print(f"EXIF check      : files with EXIF tags {sum(1 for e in exif if e['exif_tags'])}, with GPS {sum(1 for e in exif if e['gps'])}, "
              f"with Exif marker {sum(1 for e in exif if e['exif_marker'])}")
    print(f"integrity_check : {integrity}")
    print(f"source changed  : {changed or 'nothing (DB and all files byte-identical)'}")
    if changed:
        sys.exit(1)


def verify(cur, tx, target_root, files_copied, args):
    """Whole target DB + copied file names: no Latvian/Cyrillic letters, no masked/known names, no client name."""
    problems = []
    names = [rx for rx, _ in tx.mask] + [re.compile(re.escape(n), re.I) for n in tx.extra_names]
    names += [re.compile(re.escape(fold(n)), re.I) for n in tx.extra_names]
    names.append(re.compile(r"\bRM\b"))  # short client code
    names.append(re.compile(re.escape(tx.old_sector), re.I))
    names.append(re.compile(re.escape(re.sub(r"[-_\s]", "", tx.old_sector)), re.I))  # e.g. in file names
    names.append(re.compile(r"/root/|/home/"))  # internal server paths
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for tb in tables:
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{tb}")')]
        for row in cur.execute(f'SELECT * FROM "{tb}"'):
            for c, v in zip(cols, row):
                if not isinstance(v, str):
                    continue
                if NON_ENGLISH.search(v):
                    problems.append(f"non-English letters: {tb}.{c} #{row[0]}")
                if len(LV_WORDS.findall(v)) >= 3:
                    problems.append(f"possible Latvian words: {tb}.{c} #{row[0]}")
                if any(rx.search(v) for rx in names) or "[[PERSON]]" in v or "[[CLIENT]]" in v:
                    problems.append(f"name/client hit: {tb}.{c} #{row[0]}")
                if v == "admin" or re.search(r'"admin"', v):  # dashboard login left in an actor field
                    problems.append(f"login name 'admin': {tb}.{c} #{row[0]}")
    for _, d in files_copied:
        rel = os.path.relpath(d, target_root)  # final (published) path
        if any(rx.search(rel) for rx in names) or NON_ENGLISH.search(rel):
            problems.append(f"name hit in file name: {rel}")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--sector", required=True)
    ap.add_argument("--new-sector", required=True)
    ap.add_argument("--object-name", required=True)
    ap.add_argument("--translations", required=True, help="private JSON file {pairs:[{src,en}]}")
    ap.add_argument("--names-file", help="private list of original names (one per line) that must not appear")
    ap.add_argument("--report-csv")
    ap.add_argument("--dry-run", action="store_true")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
