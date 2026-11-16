"""Re-run change detection over STORED acquisitions as a new detection generation (WORKER only).

python -m satellite_monitoring.redetect --area ID [--area ID ...] --reason TEXT [--code-version SHA] --yes

- No network: the provider raises on any call, so 0 requests and 0 PU. The stored RAW GeoTIFFs are read with
  their sha256 checked (Detector._layers).
- Append-only: the current rows of sat_detections, sat_change_events, sat_s2_candidates and sat_radar_anomalies of
  the areas are kept and marked superseded_at_utc / superseded_by_generation (frozen by triggers); nothing is
  deleted. Acquisitions, metrics, request log and runs are untouched.
- Refuses when a human acted on an event in scope (status other than SUSPECTED/RECOVERED (both automatic), a reviewer,
  or a review log entry other than CREATE_RISK): such a decision must not be superseded silently.
- Risk links (decided 2026-11-16): an event whose only human trace is a CREATE_RISK link is superseded, and its
  risk_id moves to the successor event whose union mask overlaps it by >= risk_carry_min_overlap of the smaller
  mask (best overlap wins; a successor takes at most one risk). Links that find no successor stay on the
  superseded row and are listed in the result, so one physical change never gets two risks unnoticed.
- Takes the same run lock as TIMER/MANUAL/BACKFILL runs and records a sat_runs row (MANUAL) plus a
  sat_detection_generations row.
"""
import argparse
import json
import os
import sys

from . import areas as areas_mod, config, db as sdb, pipeline


class NoNetwork:
    on_request = None

    def discover(self, *a, **k):
        raise RuntimeError("redetect: network not allowed")

    def fetch_area_raster(self, *a, **k):
        raise RuntimeError("redetect: network not allowed")


class Refused(Exception):
    pass


def redetect(conn, area_ids, reason, code_version=None, cfg=None, decoder=None, forest_conn=None, lock_file=None):
    cfg = cfg or config.DEFAULTS
    area_ids = sorted(set(int(x) for x in area_ids))
    if not area_ids or not reason:
        raise ValueError("area ids and a reason are required")
    q = ",".join("?" * len(area_ids))
    with pipeline.RunLock(lock_file or pipeline.lock_path()):
        al = areas_mod.active(conn, area_ids)
        if sorted(a["id"] for a in al) != area_ids:
            raise Refused(f"not all areas are active: {area_ids}")
        human = conn.execute(
            f"SELECT id FROM sat_change_events WHERE monitored_area_id IN ({q}) AND superseded_at_utc IS NULL AND "
            "(status NOT IN ('SUSPECTED','RECOVERED') OR reviewed_by IS NOT NULL OR "
            " id IN (SELECT event_id FROM sat_review_log WHERE action <> 'CREATE_RISK'))", area_ids).fetchall()
        if human:
            raise Refused(f"events with a human decision: {[r[0] for r in human]}")
        linked = [dict(r) for r in conn.execute(
            f"SELECT id, monitored_area_id, risk_id, change_mask_path, union_mask_path FROM sat_change_events "
            f"WHERE monitored_area_id IN ({q}) AND superseded_at_utc IS NULL AND risk_id IS NOT NULL ORDER BY id",
            area_ids)]
        now = sdb.iso(sdb.utcnow())
        run_id = conn.execute("INSERT INTO sat_runs (trigger, started_at, status, areas, sensors) VALUES "
                              "('MANUAL', ?, 'RUNNING', ?, 'S1,S2')", (now, sdb.dumps(area_ids))).lastrowid
        gen = conn.execute("INSERT INTO sat_detection_generations (created_at_utc, run_id, area_ids, code_version, "
                           "reason) VALUES (?,?,?,?,?)", (now, run_id, sdb.dumps(area_ids), code_version, reason)).lastrowid
        counts = {}
        for t in sdb.DETECTION_TABLES:
            counts[t] = conn.execute(f"UPDATE {t} SET superseded_at_utc=?, superseded_by_generation=? WHERE "
                                     f"monitored_area_id IN ({q}) AND superseded_at_utc IS NULL",
                                     (now, gen, *area_ids)).rowcount
        conn.commit()
        r = pipeline.Runner(conn, NoNetwork(), "MANUAL", cfg, decoder, forest_conn=forest_conn)
        r.run_id = run_id
        prepared = [pipeline._prepare_area(a, cfg, conn) for a in al]
        r.detect(prepared, ("S1", "S2"))
        carry = carry_risks(conn, linked, cfg)
        status = "OK" if not r.errors else "FAILED"
        end = sdb.iso(sdb.utcnow())
        conn.execute("UPDATE sat_runs SET finished_at=?, status=?, new_acquisitions=0, requests_made=?, pu_spent=?, "
                     "errors_json=?, stop_reason=? WHERE id=?",
                     (end, "OK" if status == "OK" else "PARTIAL", r.requests, round(r.pu, 4),
                      sdb.dumps(r.errors) if r.errors else None, f"redetect generation {gen}", run_id))
        conn.execute("UPDATE sat_detection_generations SET finished_at_utc=?, status=?, superseded_counts_json=? "
                     "WHERE id=?", (end, status, sdb.dumps(counts), gen))
        conn.commit()
        return {"generation": gen, "run_id": run_id, "status": status, "superseded": counts,
                "requests": r.requests, "pu": r.pu, "errors": r.errors, "risk_links": carry}


def _union_mask(ev):
    import numpy as np
    return np.load(ev.get("union_mask_path") or ev["change_mask_path"]).astype(bool)


def mask_overlap(a, b):
    """Share of the smaller mask covered by the other (robust to an event that grew or shrank)."""
    n = min(int(a.sum()), int(b.sum()))
    return 0.0 if n == 0 else float((a & b).sum()) / n


def carry_risks(conn, linked, cfg):
    """Move each superseded event's risk link to its best-overlapping successor (>= risk_carry_min_overlap)."""
    out = {"carried": [], "not_carried": []}
    if not linked:
        return out
    thr = cfg["risk_carry_min_overlap"]
    cands = []
    for old in linked:
        om = _union_mask(old)
        for new in conn.execute("SELECT id, change_mask_path, union_mask_path FROM sat_change_events WHERE "
                                "monitored_area_id=? AND superseded_at_utc IS NULL AND risk_id IS NULL",
                                (old["monitored_area_id"],)):
            ov = mask_overlap(om, _union_mask(dict(new)))
            if ov >= thr:
                cands.append((ov, old["id"], new["id"]))
    used_old, used_new = set(), set()
    by_old = {o["id"]: o for o in linked}
    for ov, oid, nid in sorted(cands, key=lambda c: (-c[0], c[1], c[2])):
        if oid in used_old or nid in used_new:
            continue
        conn.execute("UPDATE sat_change_events SET risk_id=?, risk_carried_from_event_id=?, risk_carry_overlap=? "
                     "WHERE id=? AND risk_id IS NULL", (by_old[oid]["risk_id"], oid, round(ov, 4), nid))
        used_old.add(oid)
        used_new.add(nid)
        out["carried"].append({"risk_id": by_old[oid]["risk_id"], "from_event": oid, "to_event": nid,
                               "overlap": round(ov, 4)})
    for o in linked:
        if o["id"] not in used_old:
            out["not_carried"].append({"risk_id": o["risk_id"], "event": o["id"],
                                       "reason": f"no successor with overlap >= {thr}"})
    conn.commit()
    return out


def main(argv=None):
    os.umask(0o077)
    ap = argparse.ArgumentParser(prog="satellite_monitoring.redetect")
    ap.add_argument("--area", action="append", required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--code-version")
    ap.add_argument("--yes", action="store_true", help="required: confirms the live database is backed up")
    a = ap.parse_args(argv)
    if not a.yes:
        print("refusing without --yes (back up satellite.db first)", file=sys.stderr)
        return 2
    conn = sdb.connect()
    ids = []
    for x in a.area:
        ar = areas_mod.find(conn, x)
        if not ar:
            print(f"area {x!r} not found", file=sys.stderr)
            return 2
        ids.append(ar["id"])
    res = redetect(conn, ids, a.reason, a.code_version, forest_conn=sdb.forest_ro())
    print(json.dumps(res, indent=1, default=str))
    return 0 if res["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
