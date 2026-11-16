"""Worker side of the Stage 2 job queue (decision D2). Runs in the worker venv (timer / CLI), never in the API.

python -m satellite_monitoring.jobs [--daily] [--max-jobs N]

  - Picks up QUEUED sat_jobs rows (FIFO) written by the API: ADD_AREA (validate + create the area, then a
    `area_backfill_days` BACKFILL run), STOP_AREA (active=0, history kept), FETCH (MANUAL run, same code path).
  - --daily: after the queue, the scheduled TIMER run over all active areas (forest-satellite-sync.timer).
  - A run lock held by another run -> the job goes back to QUEUED for the next tick (not failed).
  - Its own jobs lock makes the queue single-consumer; a RUNNING job found while holding it was interrupted
    (worker crash) and is re-queued, up to config max_attempts, then FAILED.
  - Never creates risks (D3) and opens forest_ai.db read-only only (sector polygons, operational context).
"""
import argparse
import json
import os
import sys
from datetime import timedelta

from . import areas, config, db as sdb, pipeline


def jobs_lock_path():
    return config.raster_root() / ".sat-jobs.lock"


def _finish(conn, jid, status, result=None, error=None):
    conn.execute("UPDATE sat_jobs SET status=?, finished_at_utc=?, result_json=?, error_text=? WHERE id=?",
                 (status, sdb.iso(sdb.utcnow()), sdb.dumps(result) if result is not None else None,
                  (error or "")[:500] or None, jid))
    conn.commit()


def _requeue_interrupted(conn, cfg):
    n = 0
    for j in conn.execute("SELECT id, attempts FROM sat_jobs WHERE status='RUNNING'").fetchall():
        if j["attempts"] >= cfg["max_attempts"]:
            _finish(conn, j["id"], "FAILED", error="worker interrupted; max attempts reached")
        else:
            conn.execute("UPDATE sat_jobs SET status='QUEUED', started_at_utc=NULL WHERE id=?", (j["id"],))
            conn.commit()
        n += 1
    return n


def _claim(conn):
    j = conn.execute("SELECT * FROM sat_jobs WHERE status='QUEUED' ORDER BY id LIMIT 1").fetchone()
    if not j:
        return None
    cur = conn.execute("UPDATE sat_jobs SET status='RUNNING', started_at_utc=?, attempts=attempts+1 "
                       "WHERE id=? AND status='QUEUED'", (sdb.iso(sdb.utcnow()), j["id"]))
    conn.commit()
    return dict(j) if cur.rowcount == 1 else None


def _run_job(conn, job, cfg, run_kw):
    p = json.loads(job["payload_json"])
    if job["kind"] == "STOP_AREA":
        return {"area_id": p["area_id"], "stopped": areas.stop(conn, p["area_id"])}
    if job["kind"] == "FETCH":
        ids = None if p.get("all") else [p["area_id"]]
        return pipeline.run("MANUAL", conn=conn, area_ids=ids, cfg=cfg, **run_kw)
    if job["kind"] == "ADD_AREA":
        geometry = p.get("geometry")
        if geometry is None and p["source"] == "SECTOR":
            sec = areas.resolve_sector(p["source_ref"], forest_conn=run_kw.get("forest_conn"))
            geometry = sec["geometry"]
        area_id, created = areas.create(conn, p["source"], p["source_ref"], p["name"], geometry,
                                        p.get("added_by") or job["requested_by"], cfg)
        out = {"area_id": area_id, "created": created}
        if created:
            now = run_kw.get("now") or sdb.utcnow()
            out["backfill"] = pipeline.run(
                "BACKFILL", conn=conn, area_ids=[area_id], cfg=cfg,
                date_from=(now - timedelta(days=cfg["area_backfill_days"])).strftime("%Y-%m-%d"),
                date_to=now.strftime("%Y-%m-%d"), **run_kw)
        return out
    raise ValueError(f"unknown job kind {job['kind']}")


def process(conn, cfg=None, max_jobs=50, lock_file=None, **run_kw):
    """Process queued jobs. run_kw is passed to pipeline.run (provider, decoder, now, lock_file of the run lock,
    forest_conn) - tests inject a fake provider. Returns a summary."""
    cfg = cfg or config.DEFAULTS
    out = {"requeued_interrupted": 0, "done": [], "failed": [], "deferred_locked": []}
    try:
        with pipeline.RunLock(lock_file or jobs_lock_path()):
            out["requeued_interrupted"] = _requeue_interrupted(conn, cfg)
            for _ in range(max_jobs):
                job = _claim(conn)
                if not job:
                    break
                try:
                    res = _run_job(conn, job, cfg, run_kw)
                except pipeline.Locked:
                    conn.execute("UPDATE sat_jobs SET status='QUEUED', started_at_utc=NULL, attempts=attempts-1 "
                                 "WHERE id=?", (job["id"],))
                    conn.commit()
                    out["deferred_locked"].append(job["id"])
                    break                              # another run holds the lock: try again next tick
                except (areas.AreaError, ValueError) as e:
                    _finish(conn, job["id"], "FAILED", error=f"{type(e).__name__}: {e}")
                    out["failed"].append(job["id"])
                    continue
                except Exception as e:
                    _finish(conn, job["id"], "FAILED", error=f"{type(e).__name__}: {str(e)[:300]}")
                    out["failed"].append(job["id"])
                    continue
                status = "FAILED" if isinstance(res, dict) and res.get("status") == "FAILED" else "DONE"
                _finish(conn, job["id"], status, result=res)
                out["done" if status == "DONE" else "failed"].append(job["id"])
    except pipeline.Locked:
        out["skipped"] = "another jobs worker holds the jobs lock"
    return out


def main(argv=None):
    os.umask(0o077)
    if os.path.realpath(sys.prefix) != os.path.realpath(config.WORKER_VENV):
        print(f"WARNING: running in {sys.prefix}, expected worker venv {config.WORKER_VENV}", file=sys.stderr)
    ap = argparse.ArgumentParser(prog="satellite_monitoring.jobs")
    ap.add_argument("--daily", action="store_true", help="after the queue: scheduled TIMER run, all active areas")
    ap.add_argument("--max-jobs", type=int, default=50)
    a = ap.parse_args(argv)
    conn = sdb.connect()
    forest = sdb.forest_ro()
    try:
        res = {"jobs": process(conn, max_jobs=a.max_jobs, forest_conn=forest)}
        code = 0
        if a.daily:
            try:
                res["timer_run"] = pipeline.run("TIMER", conn=conn, forest_conn=forest)
                code = 0 if res["timer_run"]["status"] in ("OK", "PARTIAL", "STOPPED_BY_GUARD") else 1
            except pipeline.Locked:
                res["timer_run"] = {"status": "SKIPPED", "reason": "another run holds the lock"}
                code = 3
        print(json.dumps(res, indent=1, default=str))
        return code
    finally:
        forest.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
