#!/usr/bin/env python3
"""READ-ONLY check of a satellite daily run (written for the first NEW-host run, 2026-11-18 ~05:37 UTC).

Run with the worker venv (needs tifffile + numpy):
    /root/forest_ai_satellite_venv2/bin/python -I -B scripts/verify_satellite_daily_run.py
    /root/forest_ai_satellite_venv2/bin/python -I -B scripts/verify_satellite_daily_run.py --since 2026-11-17T08:00:00Z  # dry run

What it does NOT do: no writes (SQLite opened with mode=ro, no bytecode written, no HTTP, no systemctl changes;
note: a mode=ro connection to a WAL database may create an empty satellite.db-wal / -shm pair if none exists —
standard SQLite behaviour, the database file itself is not modified),
no Copernicus requests, no service restarts. It is NOT scheduled; run it by hand.

Checks (each line: OK | PROBLEM | WAIT | INFO):
  1. sat_runs started >= --since: status, trigger, errors, stop_reason; a TIMER run must exist (else WAIT)
  2. PU: per run sat_runs.pu_spent vs SUM(sat_request_log.pu) (pu = x-processingunits-spent header, pu_is_estimate=0)
     and vs SUM(sat_acquisitions.pu_spent); every PROCESS 200 must have a header value (no estimate)
  3. band count of every new S2 raster on disk (expected 8 = B04 B08 B11 B12 SCL dataMask B03 B02), S1 = 3
  4. true colour `<quicklook>_tc.png` exists for every new S2 raster with 8 bands
  5. old 6-band S2 rasters still decode with the ACTIVE release's raster.decode_tiff (sample, read-only)
  6. sat_change_events created/updated since --since (none expected to carry a new risk_id while auto_risk is off)
  7. forest_ai.db risks: count / max id unchanged (default 19 / 62)
  8. journal of forest-satellite-sync, forest-satellite-jobs, forest-api since --since: tracebacks, ERROR, failed units
Exit code: 0 = all OK/INFO, 1 = at least one PROBLEM, 2 = no PROBLEM but at least one WAIT.
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

SAT_DB = os.environ.get("SAT_DB_PATH", "/root/forest_ai_satellite_data/satellite.db")
FOREST_DB = os.environ.get("FOREST_DB_PATH", "/root/forest_ai/data/forest_ai.db")
UNITS = ("forest-satellite-sync", "forest-satellite-jobs", "forest-api")
S2_BANDS_NEW = 8
TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")

results = []


def report(status, item, detail):
    results.append(status)
    print(f"{status:<8} {item:<34} {detail}")


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def active_release():
    out = subprocess.run(["systemctl", "show", "-p", "WorkingDirectory", "--value", "forest-satellite-sync.service"],
                         capture_output=True, text=True).stdout.strip()
    return out or None


def tiff_bands(path):
    import tifffile
    with tifffile.TiffFile(path) as t:
        return t.pages[0].samplesperpixel if len(t.pages) == 1 else len(t.pages)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-11-18T05:00:00Z", help="UTC ISO; runs started at/after this time")
    ap.add_argument("--expect-risks", type=int, default=19)
    ap.add_argument("--expect-max-risk-id", type=int, default=62)
    ap.add_argument("--old-sample", type=int, default=10, help="old 6-band S2 rasters to decode")
    a = ap.parse_args()
    since = a.since
    since_sql = since.replace("T", " ").rstrip("Z")
    print(f"verify_satellite_daily_run  since={since}  sat_db={SAT_DB}  (read-only)\n")

    c = ro(SAT_DB)
    c.row_factory = sqlite3.Row

    # 1. runs ---------------------------------------------------------------------------------------------------------
    runs = c.execute("SELECT * FROM sat_runs WHERE started_at >= ? ORDER BY id", (since,)).fetchall()
    if not runs:
        report("WAIT", "1 runs since --since", "no sat_runs row yet")
    for r in runs:
        errs = json.loads(r["errors_json"]) if r["errors_json"] else []
        st = "OK" if r["status"] == "OK" and not errs else "PROBLEM"
        report(st, f"1 run {r['id']} ({r['trigger']})",
               f"{r['started_at']} -> {r['finished_at']} status={r['status']} areas={r['areas']} "
               f"new_acq={r['new_acquisitions']} requests={r['requests_made']} pu={r['pu_spent']} "
               f"errors={len(errs)} stop_reason={r['stop_reason']}")
        for e in errs[:5]:
            print(f"         error: {json.dumps(e)[:300]}")
    if runs and not any(r["trigger"] == "TIMER" for r in runs):
        report("WAIT", "1 daily TIMER run", "none since --since (only " +
               ",".join(sorted({r['trigger'] for r in runs})) + ")")
    run_ids = [r["id"] for r in runs]
    q = ",".join("?" * len(run_ids)) or "NULL"

    # 2. PU ----------------------------------------------------------------------------------------------------------
    for r in runs:
        log = c.execute("SELECT kind, sensor, http_status, COUNT(*) n, SUM(pu) pu, SUM(COALESCE(pu_is_estimate,0)) est,"
                        " SUM(CASE WHEN kind='PROCESS' AND http_status=200 AND pu IS NULL THEN 1 ELSE 0 END) nohdr"
                        " FROM sat_request_log WHERE run_id=? GROUP BY 1,2,3", (r["id"],)).fetchall()
        log_pu = sum(x["pu"] or 0 for x in log)
        n_req = sum(x["n"] for x in log)
        est = sum(x["est"] for x in log)
        nohdr = sum(x["nohdr"] for x in log)
        non200 = sum(x["n"] for x in log if x["http_status"] != 200)
        acq_pu = c.execute("SELECT COALESCE(SUM(pu_spent),0) FROM sat_acquisitions WHERE discovered_run_id=?",
                           (r["id"],)).fetchone()[0]
        # sat_runs.pu_spent is stored rounded to 4 decimals
        ok = (abs(log_pu - (r["pu_spent"] or 0)) < 5e-4 and n_req == r["requests_made"]
              and est == 0 and nohdr == 0)
        report("OK" if ok else "PROBLEM", f"2 PU run {r['id']}",
               f"sat_runs={r['pu_spent']} header_sum={round(log_pu, 4)} acquisitions_sum={round(acq_pu, 4)} "
               f"requests={n_req}/{r['requests_made']} estimates={est} process_without_header={nohdr} non200={non200}")
        for x in log:
            if x["kind"] == "PROCESS" and x["n"]:
                print(f"         {x['kind']} {x['sensor']} HTTP {x['http_status']}: {x['n']} req, "
                      f"{round(x['pu'] or 0, 4)} PU, {round((x['pu'] or 0) / x['n'], 4)} PU/request")
    month = c.execute("SELECT COUNT(*), COALESCE(SUM(pu),0) FROM sat_request_log WHERE at_utc >= ?",
                      (since[:7] + "-01",)).fetchone()
    report("INFO", "2 PU month to date", f"requests={month[0]} pu={round(month[1], 2)} (budget 2000 PU / 6000 req)")

    # 3 + 4. band count and true colour of new acquisitions ----------------------------------------------------------
    acqs = c.execute(f"SELECT id, monitored_area_id, sensor, status, raster_path, quicklook_path, processing_params_json"
                     f" FROM sat_acquisitions WHERE discovered_run_id IN ({q}) ORDER BY id", run_ids).fetchall()
    by = {}
    tc_missing, bad_bands, missing_files = [], [], []
    for x in acqs:
        if not x["raster_path"]:
            by.setdefault((x["sensor"], x["status"], "no raster"), 0)
            by[(x["sensor"], x["status"], "no raster")] += 1
            continue
        if not os.path.exists(x["raster_path"]):
            missing_files.append(x["id"])
            continue
        nb = tiff_bands(x["raster_path"])
        by.setdefault((x["sensor"], x["status"], nb), 0)
        by[(x["sensor"], x["status"], nb)] += 1
        want = S2_BANDS_NEW if x["sensor"] == "S2" else 3
        if nb != want:
            bad_bands.append((x["id"], nb))
        if x["sensor"] == "S2" and nb >= 8:
            tc = Path(x["quicklook_path"] or "")
            if not x["quicklook_path"] or not tc.with_name(tc.stem + "_tc.png").exists():
                tc_missing.append(x["id"])
    if not acqs:
        report("WAIT" if not runs else "INFO", "3 new acquisitions", "none")
    for k in sorted(by, key=str):
        print(f"         {k[0]} {k[1]:<16} bands={k[2]}: {by[k]}")
    if acqs:
        report("PROBLEM" if bad_bands or missing_files else "OK", "3 band count (S2=8, S1=3)",
               f"{len(acqs)} new rows; wrong band count {bad_bands[:10]}; raster file missing {missing_files[:10]}")
        n_s2_8 = sum(v for k, v in by.items() if k[0] == "S2" and k[2] == 8)
        report("PROBLEM" if tc_missing else "OK", "4 true colour _tc.png",
               f"{n_s2_8 - len(tc_missing)}/{n_s2_8} 8-band S2 rasters have one; missing acq ids {tc_missing[:10]}")

    # 5. old 6-band rasters still readable with the active release code ----------------------------------------------
    rel = active_release()
    try:
        sys.path.insert(0, rel)
        from satellite_monitoring import raster as rr
        assert rr.__file__.startswith(rel), rr.__file__
        old = c.execute("SELECT id, raster_path FROM sat_acquisitions WHERE sensor='S2' AND raster_path IS NOT NULL"
                        " AND processing_params_json NOT LIKE '%\"B03\"%' ORDER BY RANDOM() LIMIT ?",
                        (a.old_sample,)).fetchall()
        fails = []
        for x in old:
            raw = Path(x["raster_path"]).read_bytes()
            try:
                arr = rr.decode_tiff(raw, bands=rr.band_count("S2"))
                if arr.shape[2] != 6:
                    fails.append((x["id"], arr.shape))
            except Exception as e:                           # noqa: BLE001 - report every failure
                fails.append((x["id"], f"{type(e).__name__}: {e}"))
        report("PROBLEM" if fails or not old else "OK", "5 old 6-band S2 readable",
               f"{len(old) - len(fails)}/{len(old)} decoded with {rel}/satellite_monitoring/raster.py; fails {fails[:5]}")
    except Exception as e:                                   # noqa: BLE001
        report("PROBLEM", "5 old 6-band S2 readable", f"could not import release code from {rel}: {e}")
    finally:
        if rel in sys.path:
            sys.path.remove(rel)

    # 6. change events ------------------------------------------------------------------------------------------------
    new_ev = c.execute("SELECT id, monitored_area_id, classification, status, changed_area_ha, risk_id, detected_at_utc"
                       " FROM sat_change_events WHERE detected_at_utc >= ? ORDER BY id", (since,)).fetchall()
    upd_ev = c.execute("SELECT COUNT(*) FROM sat_change_events WHERE updated_at_utc >= ? AND detected_at_utc < ?",
                       (since, since)).fetchone()[0]
    tot = c.execute("SELECT COUNT(*), MAX(id) FROM sat_change_events").fetchone()
    with_risk = [e["id"] for e in new_ev if e["risk_id"] is not None]
    report("PROBLEM" if with_risk else "INFO", "6 sat_change_events",
           f"new={len(new_ev)} updated_existing={upd_ev} total={tot[0]} max_id={tot[1]}; new with risk_id {with_risk}")
    for e in new_ev[:20]:
        print(f"         event {e['id']} area {e['monitored_area_id']} {e['classification']} {e['status']} "
              f"{round(e['changed_area_ha'], 2)} ha detected {e['detected_at_utc']}")

    # 7. risks --------------------------------------------------------------------------------------------------------
    n, mx = ro(FOREST_DB).execute("SELECT COUNT(*), MAX(id) FROM risks").fetchone()
    ok = n == a.expect_risks and mx == a.expect_max_risk_id
    report("OK" if ok else "PROBLEM", "7 risks unchanged",
           f"count={n} max_id={mx} (expected {a.expect_risks} / {a.expect_max_risk_id})")

    # 8. journal ------------------------------------------------------------------------------------------------------
    for u in UNITS:
        out = subprocess.run(["journalctl", "-u", u, "--since", since_sql, "--no-pager", "-o", "cat"],
                             capture_output=True, text=True).stdout
        lines = [TOKEN_RE.sub("bot***", l) for l in out.splitlines()]
        tb = sum("Traceback" in l for l in lines)
        err = [l for l in lines if re.search(r"\bERROR\b|status=[1-9]|Failed with result", l)]
        report("PROBLEM" if tb or err else "OK", f"8 journal {u}", f"{len(lines)} lines, tracebacks={tb}, errors={len(err)}")
        for l in err[:5]:
            print(f"         {l[:240]}")
    show = subprocess.run(["systemctl", "show", "forest-satellite-sync.service", "-p", "Result,ExecMainStatus,"
                           "ExecMainStartTimestamp,ExecMainExitTimestamp,WorkingDirectory"],
                          capture_output=True, text=True).stdout.strip().splitlines()
    report("INFO", "8 forest-satellite-sync unit", " | ".join(show))

    print()
    if "PROBLEM" in results:
        print("RESULT: PROBLEM"); return 1
    if "WAIT" in results:
        print("RESULT: WAIT (run not complete / not found yet)"); return 2
    print("RESULT: OK"); return 0


if __name__ == "__main__":
    sys.exit(main())
