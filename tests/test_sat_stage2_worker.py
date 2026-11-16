"""Satellite Monitoring Stage 2 - worker side: job queue, risk-link carry-forward on redetect, pipeline status
guard, no automatic risks (D3). No network: pipeline.run is stubbed or no acquisitions exist."""
import ast
import hashlib
import json
import sqlite3
import types
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from satellite_monitoring import areas, config, db as sdb, jobs, pipeline, redetect, store

LAT, LON = 57.0, 24.5
DLAT = 400 / 111320.0
DLON = 400 / (111320.0 * np.cos(np.radians(LAT)))
SQUARE = {"type": "Polygon", "coordinates": [[[LON, LAT], [LON + DLON, LAT], [LON + DLON, LAT + DLAT],
                                              [LON, LAT + DLAT], [LON, LAT]]]}
NOW = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SAT_DATA_DIR", str(tmp_path / "sat"))
    monkeypatch.setenv("SAT_DB_PATH", str(tmp_path / "sat" / "satellite.db"))
    monkeypatch.setenv("SAT_RASTER_DIR", str(tmp_path / "sat" / "satellite"))
    forest = tmp_path / "forest.db"
    c = sqlite3.connect(forest)
    c.executescript("CREATE TABLE sectors (id INTEGER PRIMARY KEY, name TEXT, boundary_json TEXT);")
    ring = [[p[1], p[0]] for p in SQUARE["coordinates"][0][:-1]]
    c.execute("INSERT INTO sectors VALUES (7, 'TST-007', ?)", (json.dumps(ring),))
    c.commit()
    c.close()
    monkeypatch.setenv("FOREST_DB_PATH", str(forest))
    conn = sdb.connect()
    yield {"conn": conn, "forest": forest, "tmp": tmp_path}
    conn.close()


def _event(conn, area_id, mask=None, **over):
    v = dict(monitored_area_id=area_id, sensor_basis="S2", detected_at_utc="2026-10-01T00:00:00Z",
             updated_at_utc="2026-10-01T00:00:00Z", before_acq_ids="[]", after_acq_id=1,
             after_acq_history_json="[]", first_after_time_utc="2026-09-20T10:00:00Z",
             last_after_time_utc="2026-10-01T10:00:00Z", changed_area_ha=1.0, changed_area_ha_inside=1.0,
             changed_area_ha_buffer=0.0, n_changed_pixels=100, largest_cluster_ha=1.0,
             change_geojson='{"type":"FeatureCollection","features":[]}', change_mask_path="",
             thresholds_json="{}", confidence="HIGH", evidence_quality="GOOD",
             classification="POTENTIAL_FOREST_LOSS", status="SUSPECTED")
    v.update(over)
    eid = conn.execute(f"INSERT INTO sat_change_events ({','.join(v)}) VALUES ({','.join('?' * len(v))})",
                       tuple(v.values())).lastrowid
    if mask is not None:
        p = config.raster_root() / str(area_id) / "events" / f"event_{eid}_union.npy"
        p.parent.mkdir(parents=True, exist_ok=True)
        np.save(p, mask)
        conn.execute("UPDATE sat_change_events SET change_mask_path=?, union_mask_path=? WHERE id=?",
                     (str(p), str(p), eid))
    conn.commit()
    return eid


def _area(conn):
    aid, _ = areas.create(conn, "LVM_GEO", "LVM-1", "Test area", SQUARE, "test")
    return aid


def _mask(cols):
    m = np.zeros((10, 10), bool)
    m[:, cols] = True
    return m


# ── job queue ────────────────────────────────────────────────────────────────
def test_add_area_job_creates_area_and_queues_120_day_backfill(env, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda trig, **kw: calls.append((trig, kw)) or {"status": "OK", "run_id": 9})
    q = store.queue_add_area("LVM_GEO", "LVM-9", "New stand", SQUARE, "alice")
    assert q["status"] == "QUEUED"
    out = jobs.process(env["conn"], now=NOW)
    assert out["done"] == [q["job_id"]]
    j = env["conn"].execute("SELECT * FROM sat_jobs WHERE id=?", (q["job_id"],)).fetchone()
    res = json.loads(j["result_json"])
    assert j["status"] == "DONE" and res["created"] is True
    a = areas.load(env["conn"], res["area_id"])
    assert a["active"] == 1 and a["added_by"] == "alice" and a["source"] == "LVM_GEO"
    trig, kw = calls[0]
    assert trig == "BACKFILL" and kw["area_ids"] == [res["area_id"]]
    assert (kw["date_from"], kw["date_to"]) == ("2026-07-19", "2026-11-16")       # 120 days


def test_add_sector_area_without_geometry_resolves_polygon_read_only(env, monkeypatch):
    monkeypatch.setattr(pipeline, "run", lambda trig, **kw: {"status": "OK"})
    before = hashlib.sha256(env["forest"].read_bytes()).hexdigest()
    q = store.queue_add_area("SECTOR", "7", "TST-007", None, "bob")
    jobs.process(env["conn"], now=NOW, forest_conn=sdb.forest_ro())
    j = env["conn"].execute("SELECT status, result_json FROM sat_jobs WHERE id=?", (q["job_id"],)).fetchone()
    assert j["status"] == "DONE"
    assert hashlib.sha256(env["forest"].read_bytes()).hexdigest() == before


def test_invalid_polygon_ends_as_failed_job(env, monkeypatch):
    monkeypatch.setattr(pipeline, "run", lambda trig, **kw: pytest.fail("no run for an invalid area"))
    bow = {"type": "Polygon", "coordinates": [[[LON, LAT], [LON + DLON, LAT + DLAT], [LON + DLON, LAT],
                                               [LON, LAT + DLAT], [LON, LAT]]]}
    q = store.queue_add_area("LVM_GEO", "BOW", "Bow tie", bow, "alice")
    out = jobs.process(env["conn"], now=NOW)
    j = env["conn"].execute("SELECT status, error_text FROM sat_jobs WHERE id=?", (q["job_id"],)).fetchone()
    assert out["failed"] == [q["job_id"]] and j["status"] == "FAILED" and j["error_text"]
    assert env["conn"].execute("SELECT COUNT(*) FROM sat_monitored_areas").fetchone()[0] == 0


def test_stop_and_fetch_jobs(env, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda trig, **kw: calls.append((trig, kw)) or {"status": "OK"})
    aid = _area(env["conn"])
    f = store.queue_fetch(aid, False, "alice")
    s = store.queue_stop_area(aid, "alice")
    jobs.process(env["conn"], now=NOW)
    assert calls[0][0] == "MANUAL" and calls[0][1]["area_ids"] == [aid]
    st = {r["id"]: r["status"] for r in env["conn"].execute("SELECT id, status FROM sat_jobs")}
    assert st == {f["job_id"]: "DONE", s["job_id"]: "DONE"}
    a = areas.load(env["conn"], aid)
    assert a["active"] == 0 and a["removed_at_utc"]                       # history kept, row not deleted


def test_locked_run_requeues_job_and_interrupted_job_is_retried(env, monkeypatch):
    aid = _area(env["conn"])

    def locked(trig, **kw):
        raise pipeline.Locked("x")
    monkeypatch.setattr(pipeline, "run", locked)
    f = store.queue_fetch(aid, False, "alice")
    out = jobs.process(env["conn"], now=NOW)
    j = env["conn"].execute("SELECT status, attempts FROM sat_jobs WHERE id=?", (f["job_id"],)).fetchone()
    assert out["deferred_locked"] == [f["job_id"]] and (j["status"], j["attempts"]) == ("QUEUED", 0)
    # a worker that died mid-job leaves RUNNING; the next worker (holding the jobs lock) re-queues it
    env["conn"].execute("UPDATE sat_jobs SET status='RUNNING', attempts=1 WHERE id=?", (f["job_id"],))
    env["conn"].commit()
    monkeypatch.setattr(pipeline, "run", lambda trig, **kw: {"status": "OK"})
    out = jobs.process(env["conn"], now=NOW)
    assert out["requeued_interrupted"] == 1 and out["done"] == [f["job_id"]]


def test_jobs_table_is_append_only(env):
    store.queue_fetch(None, True, "alice")
    with pytest.raises(sqlite3.IntegrityError):
        env["conn"].execute("DELETE FROM sat_jobs")


# ── D3: no automatic risks ───────────────────────────────────────────────────
def _imports(mod):
    tree = ast.parse(Path(mod.__file__).read_text())
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            names |= {(n.module or "")} | {a.name for a in n.names}
    return names


def test_no_automatic_risks_config_and_worker_never_reaches_the_risk_engine(env, monkeypatch):
    assert config.DEFAULTS["auto_risk_enabled"] is False
    for mod in (jobs, pipeline, redetect):
        imp = _imports(mod)
        assert "risk_bridge" not in imp and "database" not in imp and "ai_resolution" not in imp, mod.__name__
    # a worker pass with an eligible HIGH-confidence event leaves the main DB byte-identical
    aid = _area(env["conn"])
    _event(env["conn"], aid)
    before = hashlib.sha256(env["forest"].read_bytes()).hexdigest()
    monkeypatch.setattr(pipeline, "run", lambda trig, **kw: {"status": "OK"})
    store.queue_fetch(aid, False, "alice")
    jobs.process(env["conn"], now=NOW, forest_conn=sdb.forest_ro())
    assert hashlib.sha256(env["forest"].read_bytes()).hexdigest() == before
    assert env["conn"].execute("SELECT COUNT(*) FROM sat_change_events WHERE risk_id IS NOT NULL").fetchone()[0] == 0


# ── risk link carry-forward on redetect (decided 2026-11-16) ─────────────────
def test_carry_risks_best_overlap_one_risk_per_successor(env):
    c = env["conn"]
    aid = _area(c)
    old_a = _event(c, aid, _mask([0, 1, 2, 3]), risk_id=101)       # 40 px
    old_b = _event(c, aid, _mask([2, 3]), risk_id=102)             # overlaps the same successor
    old_c = _event(c, aid, _mask([9]), risk_id=103)                # no successor
    linked = [dict(r) for r in c.execute("SELECT * FROM sat_change_events WHERE risk_id IS NOT NULL ORDER BY id")]
    c.execute("UPDATE sat_change_events SET superseded_at_utc='x', superseded_by_generation=1")
    c.commit()
    new_1 = _event(c, aid, _mask([1, 2, 3, 4, 5]))                 # vs old_a: 30/40 = 0.75; vs old_b: 20/20 = 1.0
    new_2 = _event(c, aid, _mask([6, 7]))                          # no overlap with anything
    new_3 = _event(c, aid, _mask([0, 5, 6, 7, 8]))                 # vs old_a: 10/40 = 0.25 < 0.30
    out = redetect.carry_risks(c, linked, config.DEFAULTS)
    assert out["carried"] == [{"risk_id": 102, "from_event": old_b, "to_event": new_1, "overlap": 1.0}]
    assert {x["risk_id"] for x in out["not_carried"]} == {101, 103}   # 101's best successor already took 102
    rows = {r["id"]: dict(r) for r in c.execute("SELECT id, risk_id, risk_carried_from_event_id, risk_carry_overlap "
                                                "FROM sat_change_events WHERE superseded_at_utc IS NULL")}
    assert rows[new_1]["risk_id"] == 102 and rows[new_1]["risk_carried_from_event_id"] == old_b
    assert rows[new_2]["risk_id"] is None and rows[new_3]["risk_id"] is None
    # each risk id is on at most one CURRENT event
    assert c.execute("SELECT MAX(n) FROM (SELECT COUNT(*) n FROM sat_change_events WHERE risk_id IS NOT NULL AND "
                     "superseded_at_utc IS NULL GROUP BY risk_id)").fetchone()[0] == 1


@pytest.mark.parametrize("succ_cols, carried", [(range(3, 10), True),     # overlap 20 / min(50, 70) = 0.40
                                                 (range(4, 10), False)])   # overlap 10 / min(50, 60) = 0.20
def test_carry_threshold_is_30_percent_of_the_smaller_mask(env, succ_cols, carried):
    c = env["conn"]
    aid = _area(c)
    old = _event(c, aid, _mask(list(range(0, 5))), risk_id=7)      # 50 px
    linked = [dict(c.execute("SELECT * FROM sat_change_events WHERE id=?", (old,)).fetchone())]
    c.execute("UPDATE sat_change_events SET superseded_at_utc='x', superseded_by_generation=1")
    c.commit()
    new = _event(c, aid, _mask(list(succ_cols)))
    out = redetect.carry_risks(c, linked, config.DEFAULTS)
    got = c.execute("SELECT risk_id FROM sat_change_events WHERE id=?", (new,)).fetchone()[0]
    assert (got == 7) is carried and (len(out["carried"]) == 1) is carried
    assert redetect.mask_overlap(_mask([0, 1]), _mask([1])) == 1.0          # a shrunk successor still matches


def test_redetect_supersedes_risk_linked_event_but_refuses_other_human_decisions(env):
    c = env["conn"]
    aid = _area(c)
    cfg = dict(config.DEFAULTS, forest_mask=False)
    e = _event(c, aid, _mask([0, 1]), risk_id=55)
    c.execute("INSERT INTO sat_review_log (event_id, action, actor, old_status, new_status, created_at_utc) "
              "VALUES (?, 'CREATE_RISK', 'alice', 'SUSPECTED', 'SUSPECTED', 'now')", (e,))
    c.commit()
    res = redetect.redetect(c, [aid], "test", cfg=cfg)
    assert res["status"] == "OK"
    # no acquisitions -> no successor; the link stays on the superseded row and is reported
    assert res["risk_links"] == {"carried": [], "not_carried": [{"risk_id": 55, "event": e,
                                                                  "reason": "no successor with overlap >= 0.3"}]}
    assert c.execute("SELECT risk_id, superseded_by_generation FROM sat_change_events WHERE id=?",
                     (e,)).fetchone()[:] == (55, res["generation"])
    e2 = _event(c, aid, _mask([0]))
    c.execute("INSERT INTO sat_review_log (event_id, action, actor, old_status, new_status, created_at_utc) "
              "VALUES (?, 'REJECT', 'alice', 'SUSPECTED', 'REVIEW_REJECTED', 'now')", (e2,))
    c.commit()
    with pytest.raises(redetect.Refused):
        redetect.redetect(c, [aid], "test", cfg=cfg)


# ── pipeline status guard (human review during a run) ───────────────────────
def test_pipeline_update_never_overwrites_a_concurrent_human_status(env):
    c = env["conn"]
    aid = _area(c)
    e = _event(c, aid)
    c.execute("UPDATE sat_change_events SET status='REVIEW_REJECTED', reviewed_by='alice' WHERE id=?", (e,))
    c.commit()
    me = types.SimpleNamespace(conn=c, AUTO_STATUS_KEYS=pipeline.Detector.AUTO_STATUS_KEYS)
    # the run had read SUSPECTED and now wants RECOVERED + new measurements
    pipeline.Detector._update_event(me, e, {"changed_area_ha": 0.1, "status": "RECOVERED",
                                            "recovered_reason": "r", "recovery_json": "{}"}, "SUSPECTED")
    r = c.execute("SELECT status, changed_area_ha, recovered_reason FROM sat_change_events WHERE id=?", (e,)).fetchone()
    assert tuple(r) == ("REVIEW_REJECTED", 0.1, None)
    pipeline.Detector._update_event(me, e, {"changed_area_ha": 0.2}, "REVIEW_REJECTED")
    assert c.execute("SELECT changed_area_ha FROM sat_change_events WHERE id=?", (e,)).fetchone()[0] == 0.2
