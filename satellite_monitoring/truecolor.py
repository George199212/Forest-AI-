"""True-colour quicklooks (B04/B03/B02) for EXISTING S2 acquisitions of currently open events (WORKER only).

python -m satellite_monitoring.truecolor [--scope shown|all] --dry-run      # no network: list + request/PU estimate
python -m satellite_monitoring.truecolor [--scope shown|all] --yes          # fetch (needs the owner's OK)

- Owner decision 2026-11-17: new acquisitions get B03/B02 in the normal S2 request (provider.EVALSCRIPT_S2); for
  existing data ONLY the before/after S2 acquisitions of currently open events are fetched. Never the archive.
- open event  = current generation, status not RECOVERED / REVIEW_REJECTED.
- scope shown = the before/after pair the event page shows (latest S2 'before' + last S2 'after' with a quicklook);
  scope all   = every S2 acquisition in the event's before list and after history.
- Display only: one Process request per acquisition (EVALSCRIPT_TRUECOLOR, 3 counted bands), writes <stem>_tc.png
  next to the false-colour quicklook. The stored 6-band evidence raster and its sha256 are never touched.
- Same safety as other runs: run lock, monthly quota guard (stops before 80 %), every request in sat_request_log,
  one sat_runs row (MANUAL), provider_status on success/failure. Acquisitions that already have a *_tc.png are skipped.
"""
import argparse
import json
import sys
from pathlib import Path

from . import cdse, config, db as sdb, pipeline, provider as prov

OPEN_EXCLUDED = ("RECOVERED", "REVIEW_REJECTED")


def _s2(conn, ids):
    if not ids:
        return []
    q = "SELECT * FROM sat_acquisitions WHERE id IN (%s) AND sensor='S2'" % ",".join("?" * len(ids))
    return [dict(r) for r in conn.execute(q, list(ids))]


def select(conn, scope="shown"):
    """[(acquisition row, [event ids])] still without a true-colour quicklook, ordered by id."""
    cur = sdb.current_only(conn, "sat_change_events")
    events = [dict(r) for r in conn.execute(
        "SELECT id, before_acq_ids, after_acq_history_json FROM sat_change_events WHERE status NOT IN (%s)%s ORDER BY id"
        % (",".join("?" * len(OPEN_EXCLUDED)), cur), OPEN_EXCLUDED)]
    want = {}
    for e in events:
        before = _s2(conn, json.loads(e["before_acq_ids"] or "[]"))
        after_ids = [h["acq_id"] for h in json.loads(e["after_acq_history_json"] or "[]")]
        after = _s2(conn, after_ids)
        if scope == "shown":           # same pick as the event page (sat-monitoring.js pickImages)
            after_q = [a for a in sorted(after, key=lambda a: after_ids.index(a["id"])) if a["quicklook_path"]]
            before_q = sorted([b for b in before if b["quicklook_path"]], key=lambda b: b["sensing_time_utc"])
            chosen = ([before_q[-1]] if before_q else []) + ([after_q[-1]] if after_q else [])
        else:
            chosen = [x for x in before + after if x["quicklook_path"]]
        for a in chosen:
            want.setdefault(a["id"], (a, []))[1].append(e["id"])
    from . import raster
    return [v for k, v in sorted(want.items())
            if not raster.truecolor_path(v[0]["quicklook_path"]).is_file() and v[0]["status"] == "OK"]


def estimate(conn, items, cfg=None):
    """PU estimate per acquisition: Sentinel Hub rules with 3 counted bands, and a calibrated value from the PU this
    account was actually charged for the same area's S2 requests (5 counted bands), scaled by 3/5."""
    cfg = cfg or config.DEFAULTS
    out, rule_total, calib_total = [], 0.0, 0.0
    for a, ev in items:
        area = dict(conn.execute("SELECT * FROM sat_monitored_areas WHERE id=?", (a["monitored_area_id"],)).fetchone())
        grid = json.loads(area["grid_json"])
        rule = prov.estimate_pu("S2", grid["width"], grid["height"], cfg, input_bands=3)
        runs = [x["id"] for x in conn.execute("SELECT id, areas FROM sat_runs")
                if json.loads(x["areas"] or "[]") == [area["id"]]]          # single-area runs: PU is per this grid
        row = conn.execute(
            "SELECT AVG(pu), COUNT(*) FROM sat_request_log WHERE kind='PROCESS' AND sensor='S2' AND http_status=200 "
            "AND pu IS NOT NULL AND COALESCE(pu_is_estimate,0)=0 AND run_id IN (%s)" % ",".join("?" * len(runs) or "NULL"),
            runs).fetchone() if runs else None
        calib = round(row[0] * 3 / 5, 4) if row and row[0] else None
        rule_total += rule
        calib_total += calib if calib is not None else rule
        out.append({"acq_id": a["id"], "area_id": area["id"], "area": area["name"], "sensing_time_utc": a["sensing_time_utc"],
                    "product_id": a["product_id"], "events": ev, "grid_px": [grid["width"], grid["height"]],
                    "pu_rule": rule, "pu_calibrated": calib})
    u = sdb.month_usage(conn)
    f = cfg["guard_stop_fraction"]
    return {"requests": len(out), "pu_estimate_rule": round(rule_total, 3), "pu_estimate_calibrated": round(calib_total, 3),
            "month_usage": u, "pu_guard": round(cfg["monthly_pu_budget"] * f, 1),
            "request_guard": int(cfg["monthly_request_budget"] * f), "items": out}


def fetch(conn, items, client=None, cfg=None, lock_file=None, decoder=None):
    from . import raster
    decode = decoder or raster.decode_tiff
    cfg = cfg or config.DEFAULTS
    client = client or cdse.Client(max_rps=cfg["max_requests_per_second"])
    sh = prov.SentinelHubProvider(client, cfg)
    r = pipeline.Runner(conn, sh, "MANUAL", cfg)
    done, failed = [], []
    with pipeline.RunLock(lock_file or pipeline.lock_path()):
        areas = sorted({a["monitored_area_id"] for a, _ in items})
        r.run_id = conn.execute("INSERT INTO sat_runs (trigger, started_at, status, areas, sensors) VALUES "
                                "('MANUAL',?,'RUNNING',?,'S2')", (sdb.iso(sdb.utcnow()), json.dumps(areas))).lastrowid
        conn.commit()
        r._sensor = "S2"
        status, stop = "OK", "true colour quicklooks for open events (display only)"
        try:
            for a, ev in items:
                area = dict(conn.execute("SELECT * FROM sat_monitored_areas WHERE id=?", (a["monitored_area_id"],)).fetchone())
                grid = json.loads(area["grid_json"])
                r._guard(prov.estimate_pu("S2", grid["width"], grid["height"], cfg, input_bands=3))
                p = prov.Product("S2", a["product_id"], a["sensing_time_utc"], a["platform"], a["orbit_direction"],
                                 a["relative_orbit"], a["scene_cloud_pct"])
                try:
                    res = sh.fetch_truecolor(p, grid)
                    sdb.provider_status(conn, "process", True)
                    arr = decode(res.raw, expected_shape=(grid["height"], grid["width"]), bands=4)
                except cdse.CdseError as e:
                    sdb.provider_status(conn, "token" if e.kind in ("NOT_CONFIGURED", "AUTH") else "process", False, str(e))
                    failed.append({"acq_id": a["id"], "error": str(e)[:200]})
                    if e.kind in ("NOT_CONFIGURED", "AUTH"):
                        raise
                    continue
                except Exception as e:
                    failed.append({"acq_id": a["id"], "error": f"{type(e).__name__}: {str(e)[:200]}"})
                    continue
                if res.pu_is_estimate and getattr(r, "_last_request_id", None):
                    conn.execute("UPDATE sat_request_log SET pu=?, pu_is_estimate=1 WHERE id=?", (res.pu_spent, r._last_request_id))
                    r.pu += res.pu_spent
                raster.write_file(raster.truecolor_path(Path(a["quicklook_path"])),
                                  raster.truecolor_png(arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3] == 1))
                done.append(a["id"])
        except pipeline.GuardStop as e:
            status, stop = "STOPPED_BY_GUARD", str(e)
        except cdse.CdseError as e:
            status, stop = "FAILED", str(e)
        if failed and status == "OK":
            status = "PARTIAL"
        conn.execute("UPDATE sat_runs SET finished_at=?, status=?, new_acquisitions=0, requests_made=?, pu_spent=?, "
                     "errors_json=?, stop_reason=? WHERE id=?",
                     (sdb.iso(sdb.utcnow()), status, r.requests, round(r.pu, 4), json.dumps(failed), stop, r.run_id))
        conn.commit()
    return {"run_id": r.run_id, "status": status, "done": done, "failed": failed, "requests": r.requests,
            "pu": round(r.pu, 4)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="satellite_monitoring.truecolor")
    ap.add_argument("--scope", choices=("shown", "all"), default="shown")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="no network: list + request count + PU estimate")
    g.add_argument("--yes", action="store_true", help="fetch (only after the owner's OK)")
    args = ap.parse_args(argv)
    conn = sdb.connect_ro() if args.dry_run else sdb.connect()     # the dry-run never writes
    items = select(conn, args.scope)
    est = estimate(conn, items)
    est["scope"] = args.scope
    if args.dry_run:
        print(json.dumps(est, indent=1))
        return 0
    print(json.dumps({"estimate": {k: est[k] for k in ("requests", "pu_estimate_rule", "pu_estimate_calibrated")},
                      "result": fetch(conn, items)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
