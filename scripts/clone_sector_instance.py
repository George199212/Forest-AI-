#!/usr/bin/env python3
"""
Create the database for a separate Forest AI instance (client account) that
contains only the selected sector(s) of an existing instance.

Why this exists
---------------
Forest AI is single-tenant: one SQLite DB, one Basic Auth login. A client
account (first: Rīgas meži) is therefore a second instance of the same code in
its own directory, with its own .env, port and data/ folder. This script seeds
that instance's data/ from the main instance, keeping only the chosen sectors.

Safety
------
* The source DB is opened READ-ONLY (sqlite URI mode=ro) and copied with the
  SQLite backup API, so it is consistent even while the main services run.
  The source DB and source files are never modified.
* Default is a dry run: everything is executed on a temporary copy and only a
  report is printed. Nothing is written to the target unless --apply is given.
* --apply refuses to overwrite an existing target DB.
* Every table must be covered by a rule. An unknown table (added to
  database.py later) stops the script instead of being copied unfiltered.
* Dangling references (e.g. a kept photo comparison pointing at a deleted
  photo) are reported; --apply refuses to continue while any exist unless
  --allow-dangling is passed.
* All integration tables are emptied: encrypted credentials and provider
  configuration of the main instance must never travel to a client instance.

Usage (on the server)
---------------------
  # 1. See which sector names exist (exact spelling matters)
  python3 scripts/clone_sector_instance.py --source-root /root/forest_ai --list-sectors

  # 2. Dry run
  python3 scripts/clone_sector_instance.py --source-root /root/forest_ai \
      --target-root /root/forest_ai_rm --sector "BIK-001" \
      --org-name "Rīgas meži" --org-slug rigas-mezi

  # 3. Apply
  ... same arguments ... --apply
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile

DEFAULT_DB_REL = os.path.join("data", "forest_ai.db")

# Tables linked to a sector through a TEXT `sector` column are detected
# automatically. The tables below have no `sector` column and need a rule.
SECTORS_TABLE = "sectors"  # key column is `name`

CHILD_RULES = [
    # (table, WHERE clause selecting rows to DELETE), applied in this order
    ("risk_events",            "risk_id NOT IN (SELECT id FROM risks) OR risk_id IS NULL"),
    ("snapshot_risks",         "snapshot_id NOT IN (SELECT id FROM sector_snapshots) "
                               "OR risk_id NOT IN (SELECT id FROM risks)"),
    ("risk_conclusions",       "risk_id NOT IN (SELECT id FROM risks) OR risk_id IS NULL"),
    ("photo_cmp_points",       "run_id NOT IN (SELECT id FROM photo_cmp_runs) OR run_id IS NULL"),
    ("photo_cmp_point_photos", "run_id NOT IN (SELECT id FROM photo_cmp_runs) OR run_id IS NULL"),
    ("photo_cmp_changes",      "point_id NOT IN (SELECT id FROM photo_cmp_points) OR point_id IS NULL"),
    ("photo_cmp_events",       "run_id NOT IN (SELECT id FROM photo_cmp_runs) OR run_id IS NULL"),
    ("boundary_plans",         "id NOT IN (SELECT boundary_plan_id FROM sectors "
                               "WHERE boundary_plan_id IS NOT NULL)"),
    ("boundary_plan_points",   "plan_id NOT IN (SELECT id FROM boundary_plans) OR plan_id IS NULL"),
]

# Emptied completely, even rows tagged with a kept sector (reported as a warning).
WIPE_TABLES = [
    "integration_credentials",
    "integration_logs",
    "integration_sync_runs",
    "integration_webhook_events",
    "integration_records",
    "weighbridge_records",
    "integrations",
]

ORGANIZATIONS_TABLE = "organizations"

# Columns holding file paths relative to the instance root (e.g. data/work_photos/x.jpg)
FILE_COLUMNS = [
    ("sectors", "image_path"),
    ("sectors", "satellite_file_path"),
    ("sector_snapshots", "image_path"),
    ("work_photos", "image_path"),
    ("risks", "photo_path"),
    ("risks", "photo_path_2"),
    ("boundary_plans", "file_path"),
    ("boundary_plans", "satellite_file_path"),
]

# (description, SQL returning the number of dangling rows) — evaluated after filtering
DANGLING_CHECKS = [
    ("work_photos.session_id not in work_sessions",
     "SELECT COUNT(*) FROM work_photos WHERE session_id IS NOT NULL "
     "AND session_id NOT IN (SELECT id FROM work_sessions)"),
    ("session_track_points.session_id not in work_sessions",
     "SELECT COUNT(*) FROM session_track_points WHERE session_id IS NOT NULL "
     "AND session_id NOT IN (SELECT id FROM work_sessions)"),
    ("work_sessions.employee_id not in sector_employees",
     "SELECT COUNT(*) FROM work_sessions WHERE employee_id IS NOT NULL "
     "AND employee_id NOT IN (SELECT id FROM sector_employees)"),
    ("photo_cmp_point_photos.photo_id not in work_photos",
     "SELECT COUNT(*) FROM photo_cmp_point_photos WHERE photo_id IS NOT NULL "
     "AND photo_id NOT IN (SELECT id FROM work_photos)"),
    ("photo_cmp_point_photos.point_id not in photo_cmp_points",
     "SELECT COUNT(*) FROM photo_cmp_point_photos WHERE point_id IS NOT NULL "
     "AND point_id NOT IN (SELECT id FROM photo_cmp_points)"),
    ("risk_conclusions.run_id not in photo_cmp_runs",
     "SELECT COUNT(*) FROM risk_conclusions WHERE run_id IS NOT NULL "
     "AND run_id NOT IN (SELECT id FROM photo_cmp_runs)"),
    ("live_locations.employee_id not in sector_employees",
     "SELECT COUNT(*) FROM live_locations WHERE employee_id IS NOT NULL "
     "AND employee_id NOT IN (SELECT id FROM sector_employees)"),
    ("sector_vehicles.employee_id not in sector_employees",
     "SELECT COUNT(*) FROM sector_vehicles WHERE employee_id IS NOT NULL "
     "AND employee_id NOT IN (SELECT id FROM sector_employees)"),
]


def tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def columns(conn, table):
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def count(conn, table):
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_source_db(source_db, dest_path):
    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    dst = sqlite3.connect(dest_path)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def list_sectors(source_db):
    conn = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    try:
        print("Sectors table (name):")
        for (name,) in conn.execute("SELECT name FROM sectors ORDER BY name"):
            print(f"  {name!r}")
        print("\nDistinct `sector` values per table (rows):")
        for t in tables(conn):
            if "sector" in columns(conn, t):
                rows = conn.execute(
                    f'SELECT sector, COUNT(*) FROM "{t}" GROUP BY sector ORDER BY sector').fetchall()
                if rows:
                    vals = ", ".join(f"{s!r}:{n}" for s, n in rows)
                    print(f"  {t}: {vals}")
    finally:
        conn.close()


def filter_db(db_path, keep, org_name, org_slug):
    """Delete everything not belonging to `keep` sectors. Returns a report dict."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=OFF")
    report = {"before": {}, "after": {}, "warnings": [], "dangling": {}}
    all_tables = tables(conn)
    report["before"] = {t: count(conn, t) for t in all_tables}

    sector_tables = [t for t in all_tables if t != SECTORS_TABLE and "sector" in columns(conn, t)
                     and t not in WIPE_TABLES]
    child_tables = [t for t, _ in CHILD_RULES]
    covered = set(sector_tables) | set(child_tables) | set(WIPE_TABLES) | {SECTORS_TABLE, ORGANIZATIONS_TABLE}
    unknown = [t for t in all_tables if t not in covered]
    if unknown:
        conn.close()
        raise SystemExit(
            f"ERROR: no copy rule for table(s): {', '.join(unknown)}. "
            "Add a rule to scripts/clone_sector_instance.py before running.")

    missing_child = [t for t in child_tables + WIPE_TABLES if t not in all_tables]
    if missing_child:
        report["warnings"].append(f"tables in rules but not in DB (skipped): {', '.join(missing_child)}")

    keep_list = sorted(keep)
    placeholders = ",".join("?" for _ in keep_list)

    found = [r[0] for r in conn.execute(
        f"SELECT name FROM sectors WHERE name IN ({placeholders})", keep_list)]
    not_found = sorted(set(keep_list) - set(found))
    if not_found:
        report["warnings"].append(f"not present in sectors table: {', '.join(not_found)}")
    if not found:
        conn.close()
        raise SystemExit("ERROR: none of the requested sectors exist in the sectors table. "
                         "Run with --list-sectors to see exact names.")

    with conn:
        conn.execute(f"DELETE FROM sectors WHERE name NOT IN ({placeholders})", keep_list)
        for t in sector_tables:
            conn.execute(f'DELETE FROM "{t}" WHERE sector IS NULL OR sector NOT IN ({placeholders})',
                         keep_list)
        for t, where in CHILD_RULES:
            if t in all_tables:
                conn.execute(f'DELETE FROM "{t}" WHERE {where}')
        for t in WIPE_TABLES:
            if t not in all_tables:
                continue
            if "sector" in columns(conn, t):
                n = conn.execute(f'SELECT COUNT(*) FROM "{t}" WHERE sector IN ({placeholders})',
                                 keep_list).fetchone()[0]
                if n:
                    report["warnings"].append(f"{t}: {n} row(s) of kept sector dropped (integration data is not copied)")
            conn.execute(f'DELETE FROM "{t}"')
        conn.execute(f"DELETE FROM {ORGANIZATIONS_TABLE} WHERE id != 1")
        conn.execute(f"UPDATE {ORGANIZATIONS_TABLE} SET name=?, slug=? WHERE id=1", (org_name, org_slug))
        if conn.execute(f"SELECT COUNT(*) FROM {ORGANIZATIONS_TABLE}").fetchone()[0] == 0:
            conn.execute(f"INSERT INTO {ORGANIZATIONS_TABLE} (id, name, slug, created_at) VALUES (1, ?, ?, ?)",
                         (org_name, org_slug, datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")))

    for desc, sql in DANGLING_CHECKS:
        try:
            n = conn.execute(sql).fetchone()[0]
        except sqlite3.OperationalError as e:
            report["warnings"].append(f"check skipped ({desc}): {e}")
            continue
        if n:
            report["dangling"][desc] = n

    # photo_cmp_runs keeps the photo id lists as JSON text
    if "photo_cmp_runs" in all_tables:
        photo_ids = {str(r[0]) for r in conn.execute("SELECT id FROM work_photos")}
        missing = 0
        for b, f in conn.execute("SELECT baseline_photo_ids, followup_photo_ids FROM photo_cmp_runs"):
            for raw in (b, f):
                try:
                    ids = json.loads(raw) if raw else []
                except (TypeError, ValueError):
                    report["warnings"].append("photo_cmp_runs: unparsable photo id list")
                    continue
                if not isinstance(ids, list):
                    report["warnings"].append("photo_cmp_runs: photo id list is not a JSON array")
                    continue
                missing += sum(1 for i in ids if str(i) not in photo_ids)
        if missing:
            report["dangling"]["photo_cmp_runs photo id lists not in work_photos"] = missing

    files = set()
    for t, c in FILE_COLUMNS:
        if t in all_tables and c in columns(conn, t):
            for (v,) in conn.execute(f'SELECT "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL AND "{c}" != ""'):
                files.add(v)
    report["files"] = sorted(files)

    report["after"] = {t: count(conn, t) for t in all_tables}
    report["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    return report


def resolve_files(paths, source_root, target_root):
    """Return (copy_plan, problems). Only relative paths inside the instance are copied."""
    plan, problems = [], []
    for p in paths:
        if os.path.isabs(p):
            problems.append(f"absolute path stored, not copied (would point outside the instance): {p}")
            continue
        norm = os.path.normpath(p)
        if norm.startswith(".."):
            problems.append(f"path escapes instance root, not copied: {p}")
            continue
        src = os.path.join(source_root, norm)
        if not os.path.isfile(src):
            problems.append(f"file missing in source: {p}")
            continue
        plan.append((src, os.path.join(target_root, norm)))
    return plan, problems


def print_report(report, keep, copy_plan, file_problems):
    print(f"\nKept sector(s): {', '.join(sorted(keep))}\n")
    print(f"{'table':32} {'source':>8} {'kept':>8}")
    for t in sorted(report["before"]):
        b, a = report["before"][t], report["after"][t]
        if b or a:
            print(f"{t:32} {b:>8} {a:>8}")
    print(f"\nSQLite integrity_check: {report['integrity']}")
    print(f"Files to copy: {len(copy_plan)}")
    for w in report["warnings"]:
        print(f"WARNING: {w}")
    for p in file_problems:
        print(f"WARNING: {p}")
    if report["dangling"]:
        print("\nDANGLING REFERENCES (kept rows point at rows that were not kept):")
        for d, n in report["dangling"].items():
            print(f"  {d}: {n}")
    else:
        print("Dangling references: none")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-root", required=True, help="main instance directory, e.g. /root/forest_ai")
    ap.add_argument("--source-db", help=f"default: <source-root>/{DEFAULT_DB_REL}")
    ap.add_argument("--target-root", help="new instance directory, e.g. /root/forest_ai_rm")
    ap.add_argument("--sector", action="append", default=[], help="sector name to keep (repeatable)")
    ap.add_argument("--org-name", default="Client organization")
    ap.add_argument("--org-slug", default="client")
    ap.add_argument("--list-sectors", action="store_true")
    ap.add_argument("--apply", action="store_true", help="write the target DB and copy files")
    ap.add_argument("--allow-dangling", action="store_true")
    args = ap.parse_args()

    source_root = os.path.abspath(args.source_root)
    source_db = os.path.abspath(args.source_db or os.path.join(source_root, DEFAULT_DB_REL))
    if not os.path.isfile(source_db):
        sys.exit(f"ERROR: source DB not found: {source_db}")

    if args.list_sectors:
        list_sectors(source_db)
        return

    if not args.target_root or not args.sector:
        sys.exit("ERROR: --target-root and at least one --sector are required (or use --list-sectors)")
    target_root = os.path.abspath(args.target_root)
    if target_root == source_root:
        sys.exit("ERROR: target root must differ from source root")
    target_db = os.path.join(target_root, DEFAULT_DB_REL)
    if args.apply and os.path.exists(target_db):
        sys.exit(f"ERROR: target DB already exists, refusing to overwrite: {target_db}")

    keep = set(args.sector)
    workdir = tempfile.mkdtemp(prefix="forest_clone_")
    try:
        tmp_db = os.path.join(workdir, "forest_ai.db")
        source_hash_before = sha256(source_db)
        copy_source_db(source_db, tmp_db)
        report = filter_db(tmp_db, keep, args.org_name, args.org_slug)
        copy_plan, file_problems = resolve_files(report["files"], source_root, target_root)
        print_report(report, keep, copy_plan, file_problems)

        if not args.apply:
            print("\nDry run only. Nothing was written. Re-run with --apply to create the target.")
            return
        if report["integrity"] != "ok":
            sys.exit("ERROR: integrity_check failed on the filtered copy; nothing written.")
        if report["dangling"] and not args.allow_dangling:
            sys.exit("ERROR: dangling references found; nothing written. "
                     "Review them, then re-run with --allow-dangling if acceptable.")

        conn = sqlite3.connect(tmp_db)
        conn.execute("VACUUM")
        conn.close()

        os.makedirs(os.path.dirname(target_db), exist_ok=True)
        shutil.copy2(tmp_db, target_db)
        for src, dst in copy_plan:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

        manifest = {
            "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "source_db": source_db,
            "source_db_sha256_at_copy": source_hash_before,
            "kept_sectors": sorted(keep),
            "organization": {"id": 1, "name": args.org_name, "slug": args.org_slug},
            "rows_source": report["before"],
            "rows_kept": report["after"],
            "files_copied": [os.path.relpath(d, target_root) for _, d in copy_plan],
            "warnings": report["warnings"] + file_problems,
            "dangling": report["dangling"],
        }
        with open(os.path.join(target_root, "data", "instance_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        if sha256(source_db) != source_hash_before:
            print("NOTE: the source DB changed while copying (main instance is live). "
                  "The target is a consistent snapshot taken by the SQLite backup API.")
        print(f"\nDone. Target DB: {target_db}")
        print(f"Files copied: {len(copy_plan)}. Manifest: {os.path.join(target_root, 'data', 'instance_manifest.json')}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
