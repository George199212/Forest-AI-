"""Satellite Monitoring Stage 2 - /api/sat-monitoring/* (D1-D5). No network: Telegram and the AI call are faked.
Risks are written only to a TEST COPY of forest_ai.db (database.DB_NAME -> tmp)."""
import base64
import hashlib
import json
import os
import sqlite3

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI, HTTPException                       # noqa: E402
from fastapi.security import HTTPBasic, HTTPBasicCredentials            # noqa: E402
from fastapi.testclient import TestClient                                # noqa: E402

from satellite_monitoring import api_routes, config, db as sdb, risk_bridge, store   # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
GOOD = {"type": "Polygon", "coordinates": [[[24.5, 57.0], [24.51, 57.0], [24.51, 57.01], [24.5, 57.01],
                                            [24.5, 57.0]]]}
AUTH = {"Authorization": "Basic " + base64.b64encode(b"alice:pw").decode()}
_basic = HTTPBasic()


def verify(c: HTTPBasicCredentials = Depends(_basic)):
    if (c.username, c.password) != ("alice", "pw"):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
    return c.username


@pytest.fixture
def sat(tmp_path, monkeypatch):
    root = tmp_path / "sat"
    monkeypatch.setenv("SAT_DATA_DIR", str(root))
    monkeypatch.setenv("SAT_DB_PATH", str(root / "satellite.db"))
    monkeypatch.setenv("SAT_RASTER_DIR", str(root / "satellite"))
    conn = sdb.connect()
    aid = conn.execute(
        "INSERT INTO sat_monitored_areas (source, source_ref, name, geometry_geojson, area_ha, buffer_m, grid_json, "
        "added_by, added_at_utc) VALUES ('LVM_GEO','LVM-1','Stand A',?,12.5,100,'{}','cli','2026-11-01T00:00:00Z')",
        (json.dumps(GOOD),)).lastrowid
    ql = root / "satellite" / str(aid) / "ql_1.png"
    ql.parent.mkdir(parents=True, exist_ok=True)
    ql.write_bytes(PNG)
    acq = {}
    for i, (sensor, t, status, vp, path) in enumerate([
            ("S2", "2026-10-01T10:00:00Z", "OK", 95.0, str(ql)),
            ("S2", "2026-10-11T10:00:00Z", "SKIPPED_CLOUD", None, None),
            ("S2", "2026-10-21T10:00:00Z", "OK", 88.0, None),
            ("S1", "2026-10-25T05:00:00Z", "OK", 100.0, None)]):
        acq[i] = conn.execute("INSERT INTO sat_acquisitions (monitored_area_id, sensor, product_id, sensing_time_utc,"
                              " status, valid_pct_inside, quicklook_path) VALUES (?,?,?,?,?,?,?)",
                              (aid, sensor, f"P{i}", t, status, vp, path)).lastrowid
    conn.execute("INSERT INTO sat_area_metrics (acquisition_id, metric, zone, mean, median) VALUES (?, 'NDVI', "
                 "'INSIDE', 0.8, 0.81)", (acq[0],))
    conn.execute("INSERT INTO sat_area_metrics (acquisition_id, metric, zone, null_reason) VALUES (?, 'NDVI', "
                 "'INSIDE', 'SKIPPED_CLOUD')", (acq[1],))

    def event(**over):
        v = dict(monitored_area_id=aid, sensor_basis="S2", detected_at_utc="2026-10-21T11:00:00Z",
                 updated_at_utc="2026-10-21T11:00:00Z", before_acq_ids=json.dumps([acq[0]]), after_acq_id=acq[2],
                 after_acq_history_json=json.dumps([{"acq_id": acq[2], "sensor": "S2", "time": "2026-10-21T10:00:00Z",
                                                     "evidence_quality": "GOOD"}]),
                 first_after_time_utc="2026-10-21T10:00:00Z", last_after_time_utc="2026-10-21T10:00:00Z",
                 changed_area_ha=2.5, changed_area_ha_inside=2.0, changed_area_ha_buffer=0.5, n_changed_pixels=250,
                 largest_cluster_ha=2.0, change_mask_path="x.npy", thresholds_json="{}", confidence="HIGH",
                 evidence_quality="GOOD", classification="POTENTIAL_FOREST_LOSS", status="SUSPECTED",
                 change_geojson=json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature",
                     "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[[24.5, 57.0], [24.502, 57.0],
                                                                                      [24.502, 57.002], [24.5, 57.0]]]}}]}),
                 gps_context_json=json.dumps({"context_label": "UNREGISTERED_CHANGE_CANDIDATE",
                                              "activity_records": 0}))
        v.update(over)
        eid = conn.execute(f"INSERT INTO sat_change_events ({','.join(v)}) VALUES ({','.join('?' * len(v))})",
                           tuple(v.values())).lastrowid
        conn.commit()
        return eid

    e_open = event()
    e_rec = event(status="RECOVERED", changed_area_ha=0.08, changed_area_ha_inside=0.08, changed_area_ha_buffer=0.0,
                  recovered_reason="below min")
    e_old = event(superseded_at_utc="2026-11-13T14:19:29Z", superseded_by_generation=1)
    conn.commit()
    conn.close()
    yield {"area": aid, "acq": acq, "open": e_open, "rec": e_rec, "old": e_old, "root": root, "event": None,
           "db": root / "satellite.db", "make_event": None}


@pytest.fixture
def forest(tmp_path, monkeypatch):
    """TEST COPY of the main DB (schema from database.init_db) - never the production file."""
    import database
    p = tmp_path / "forest_ai_test.db"
    monkeypatch.setattr(database, "DB_NAME", str(p))
    database.init_db()
    assert "forest_ai_test.db" in database.DB_NAME
    return database


@pytest.fixture
def client(sat, forest):
    sent, recs = [], []

    def sender(text):
        sent.append(text)
        return sender.ok, (None if sender.ok else "Telegram send failed: test")
    sender.ok = True

    def recommend(inc):
        recs.append(inc)
        return json.dumps({"summary": "verify first", "options": [], "recommended_option_id": None})
    app = FastAPI()
    app.include_router(api_routes.router(verify, sender=sender, database=forest, recommend=recommend))
    c = TestClient(app)
    c.sent, c.recs, c.sender = sent, recs, sender
    return c


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _review(client, eid, decision, note=None):
    return client.post(f"/api/sat-monitoring/events/{eid}/review", json={"decision": decision, "note": note},
                       headers=AUTH)


# ── auth ─────────────────────────────────────────────────────────────────────
def test_every_sat_monitoring_route_in_the_real_app_requires_basic_auth(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "u")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "p")
    import api
    # FastAPI >= 0.14x nests included routers (_IncludedRouter), so enumerate via the OpenAPI schema
    spec = api.app.openapi()["paths"]
    found = {(p, m.upper()) for p, ops in spec.items() if p.startswith("/api/sat-monitoring") for m in ops}
    assert found == {
        ("/api/sat-monitoring/overview", "GET"), ("/api/sat-monitoring/areas/{area_id}", "GET"),
        ("/api/sat-monitoring/areas", "POST"), ("/api/sat-monitoring/areas/{area_id}/stop", "POST"),
        ("/api/sat-monitoring/fetch", "POST"), ("/api/sat-monitoring/events/{event_id}", "GET"),
        ("/api/sat-monitoring/events/{event_id}/review", "POST"),
        ("/api/sat-monitoring/file/{acq_id}/{kind}", "GET"), ("/api/sat-monitoring/health", "GET"),
        ("/api/sat-monitoring/sectors", "GET"), ("/api/sat-monitoring/lookup", "GET")}
    c = TestClient(api.app)
    bad = {"Authorization": "Basic " + base64.b64encode(b"u:wrong").decode()}
    for p, m in found:
        path = (p + ("?source=SECTOR&source_ref=1" if p.endswith("/lookup") else "")).replace("{area_id}", "1").replace("{event_id}", "1").replace("{acq_id}", "1") \
                .replace("{kind}", "quicklook")
        assert c.request(m, path, json={}).status_code == 401, (m, path)
        assert c.request(m, path, json={}, headers=bad).status_code == 401, (m, path)
    # D1: the existing satellite routes are still there, unchanged paths
    assert {"/api/satellite/sectors", "/api/satellite-intel/providers"} <= set(spec)


def test_test_router_rejects_missing_credentials(client):
    assert client.get("/api/sat-monitoring/overview").status_code == 401


# ── reads ────────────────────────────────────────────────────────────────────
def test_overview_counts_recovered_separately_and_reports_gaps(client, sat):
    r = client.get("/api/sat-monitoring/overview", headers=AUTH)
    assert r.status_code == 200
    a = r.json()["areas"][0]
    assert a["open_suspected_events"] == 1 and a["recovered_events"] == 1     # superseded event not counted
    assert a["last_valid_s2_utc"] == "2026-10-21T10:00:00Z" and a["last_s1_utc"] == "2026-10-25T05:00:00Z"
    assert a["gaps"]["max_gap_days_valid_s2_window"] is None or a["gaps"]["max_gap_days_valid_s2_window"] >= 0
    assert a["data_status"] == "OK"
    assert "Copernicus Sentinel" in r.json()["labels"]["attribution"]


def test_area_detail_keeps_null_gaps_and_lists_current_events(client, sat):
    r = client.get(f"/api/sat-monitoring/areas/{sat['area']}", headers=AUTH).json()
    tl = {x["acq_id"]: x for x in r["timeline"]}
    assert tl[sat["acq"][0]]["metrics_inside"]["NDVI"]["median"] == 0.81
    assert tl[sat["acq"][1]]["metrics_inside"]["NDVI"] == {"median": None, "mean": None, "null_reason": "SKIPPED_CLOUD"}
    assert tl[sat["acq"][2]]["metrics_inside"] == {}                     # missing stays missing, never 0
    assert tl[sat["acq"][0]]["quicklook_url"] == f"/api/sat-monitoring/file/{sat['acq'][0]}/quicklook"
    assert {e["id"] for e in r["events"]} == {sat["open"], sat["rec"]}
    assert client.get("/api/sat-monitoring/areas/999", headers=AUTH).status_code == 404


def test_event_detail_neutral_summary_and_quicklooks(client, sat):
    e = client.get(f"/api/sat-monitoring/events/{sat['open']}", headers=AUTH).json()
    assert e["summary"] == ("Suspected vegetation/land-cover change detected: 2.50 ha; 0.50 ha outside the approved "
                            "boundary.")
    assert e["before"][0]["quicklook_url"] and e["after"][0]["acq_id"] == sat["acq"][2]
    assert e["change_geojson"]["type"] == "FeatureCollection" and e["status_kind"] == "AUTOMATIC"
    old = client.get(f"/api/sat-monitoring/events/{sat['old']}", headers=AUTH).json()
    assert old["current"] is False


def test_reads_never_modify_satellite_db(client, sat):
    before = _sha(sat["db"])
    for p in ("/overview", f"/areas/{sat['area']}", f"/events/{sat['open']}", "/health",
              f"/file/{sat['acq'][0]}/quicklook"):
        assert client.get("/api/sat-monitoring" + p, headers=AUTH).status_code == 200, p
    assert _sha(sat["db"]) == before
    conn = store.ro()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO sat_jobs (kind, payload_json, dedup_key, requested_by, requested_at_utc) "
                     "VALUES ('FETCH','{}','k','x','t')")
    conn.close()


def test_missing_db_is_503(client, sat, monkeypatch):
    monkeypatch.setenv("SAT_DB_PATH", str(sat["root"] / "nope.db"))
    assert client.get("/api/sat-monitoring/overview", headers=AUTH).status_code == 503
    assert not (sat["root"] / "nope.db").exists()                       # the API never creates it


def test_health(client):
    h = client.get("/api/sat-monitoring/health", headers=AUTH).json()
    assert h["auto_risk_enabled"] is False and h["schema_stage2"] is True
    assert h["lock"] == {"locked": False} and h["month"]["pu_budget"] == config.DEFAULTS["monthly_pu_budget"]


# ── file route: path from the DB only, inside the raster root ───────────────
def test_quicklook_file_served(client, sat):
    r = client.get(f"/api/sat-monitoring/file/{sat['acq'][0]}/quicklook", headers=AUTH)
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"


@pytest.mark.parametrize("bad_path", ["/etc/passwd", "{root}/../outside.png", "{root}/1/link.png", "{root}/1/x.txt",
                                      "{root}/1/missing.png"])
def test_quicklook_path_traversal_is_404(client, sat, bad_path):
    root = sat["root"] / "satellite"
    (sat["root"] / "outside.png").write_bytes(PNG)
    (root / "1").mkdir(parents=True, exist_ok=True)
    os.symlink(sat["root"] / "outside.png", root / "1" / "link.png")
    (root / "1" / "x.txt").write_text("secret")
    conn = sdb.connect()
    acq = conn.execute("INSERT INTO sat_acquisitions (monitored_area_id, sensor, product_id, sensing_time_utc, status,"
                       " quicklook_path) VALUES (?, 'S2', 'BAD', '2026-10-30T00:00:00Z', 'OK', ?)",
                       (sat["area"], bad_path.format(root=root))).lastrowid
    conn.commit()
    conn.close()
    assert client.get(f"/api/sat-monitoring/file/{acq}/quicklook", headers=AUTH).status_code == 404


@pytest.mark.parametrize("url", ["/api/sat-monitoring/file/{a}/raster", "/api/sat-monitoring/file/{a}/..%2f..%2fetc",
                                 "/api/sat-monitoring/file/..%2f/quicklook", "/api/sat-monitoring/file/999/quicklook"])
def test_file_route_rejects_other_kinds_and_ids(client, sat, url):
    assert client.get(url.format(a=sat["acq"][0]), headers=AUTH).status_code in (404, 422)


# ── POST: jobs ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("body, msg", [
    ({"source": "EVAL_BBOX", "source_ref": "x", "name": "n", "geometry": GOOD}, "source"),
    ({"source": "LVM_GEO", "source_ref": "x", "name": "n"}, "geometry is required"),
    ({"source": "LVM_GEO", "source_ref": " ", "name": "n", "geometry": GOOD}, "source_ref"),
    ({"source": "LVM_GEO", "source_ref": "x", "name": "", "geometry": GOOD}, "name"),
    ({"source": "LVM_GEO", "source_ref": "x", "name": "n", "geometry": {"type": "Point", "coordinates": [24, 57]}},
     "Polygon"),
    ({"source": "LVM_GEO", "source_ref": "x", "name": "n", "geometry": {"type": "Polygon", "coordinates": [[[506000,
      312000], [507000, 312000], [507000, 313000], [506000, 312000]]]}}, "outside Latvia"),
    ({"source": "LVM_GEO", "source_ref": "x", "name": "n", "geometry": {"type": "Polygon", "coordinates": [[[24.5, 57],
      [24.6, 57], [24.6, 57.1], [24.5, 57.1]]]}}, "closed"),
    ({"source": "LVM_GEO", "source_ref": "x", "name": "n", "geometry": {"type": "Polygon", "coordinates": [[[True, 57],
      [24.6, 57], [24.6, 57.1], [True, 57]]]}}, "numbers"),
    ({"source": "LVM_GEO", "source_ref": "x", "name": "n", "geometry": {"type": "Polygon", "coordinates": [
      [[24.5, 57.0]] + [[24.5 + i * 1e-5, 57.001] for i in range(5001)] + [[24.5, 57.0]]]}}, "vertices"),
])
def test_add_area_validation(client, body, msg):
    r = client.post("/api/sat-monitoring/areas", json=body, headers=AUTH)
    assert r.status_code == 422 and msg in r.json()["error"]


def test_add_area_queues_one_job_and_dedups(client, sat):
    body = {"source": "LVM_GEO", "source_ref": "LVM-2", "name": "Stand B", "geometry": GOOD}
    r1 = client.post("/api/sat-monitoring/areas", json=body, headers=AUTH)
    r2 = client.post("/api/sat-monitoring/areas", json=body, headers=AUTH)
    assert r1.status_code == 202 and r1.json()["deduplicated"] is False
    assert r2.json() == {**r1.json(), "deduplicated": True}
    r3 = client.post("/api/sat-monitoring/areas", json={**body, "source_ref": "LVM-1"}, headers=AUTH)
    assert r3.status_code == 409 and r3.json()["area_id"] == sat["area"]      # one active area per source_ref
    conn = sdb.connect_ro()
    j = conn.execute("SELECT kind, requested_by, payload_json FROM sat_jobs").fetchall()
    assert len(j) == 1 and j[0]["kind"] == "ADD_AREA" and j[0]["requested_by"] == "alice"
    assert conn.execute("SELECT COUNT(*) FROM sat_monitored_areas").fetchone()[0] == 1   # the API never adds it
    conn.close()


def test_stop_and_fetch_routes(client, sat):
    assert client.post("/api/sat-monitoring/areas/999/stop", headers=AUTH).status_code == 404
    r = client.post(f"/api/sat-monitoring/areas/{sat['area']}/stop", headers=AUTH)
    assert r.status_code == 202 and r.json()["status"] == "QUEUED"
    assert client.post("/api/sat-monitoring/fetch", json={}, headers=AUTH).status_code == 422
    assert client.post("/api/sat-monitoring/fetch", json={"area_id": sat["area"], "all": True},
                       headers=AUTH).status_code == 422
    f1 = client.post("/api/sat-monitoring/fetch", json={"all": True}, headers=AUTH).json()
    f2 = client.post("/api/sat-monitoring/fetch", json={"all": True}, headers=AUTH).json()
    assert f1["job_id"] == f2["job_id"] and f2["deduplicated"] and f1["lock"] == {"locked": False}
    conn = sdb.connect()
    conn.execute("UPDATE sat_monitored_areas SET active=0 WHERE id=?", (sat["area"],))
    conn.commit()
    conn.close()
    assert client.post(f"/api/sat-monitoring/areas/{sat['area']}/stop", headers=AUTH).status_code == 409
    assert client.post("/api/sat-monitoring/fetch", json={"area_id": sat["area"]}, headers=AUTH).status_code == 409


def test_writes_refused_until_the_worker_migrated_the_schema(client, sat, tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    sqlite3.connect(old).executescript(sdb.SCHEMA.split("CREATE TABLE IF NOT EXISTS sat_jobs")[0])
    monkeypatch.setenv("SAT_DB_PATH", str(old))
    r = client.post("/api/sat-monitoring/fetch", json={"all": True}, headers=AUTH)
    assert r.status_code == 503 and "not migrated" in r.json()["error"]


# ── POST: review ─────────────────────────────────────────────────────────────
def test_review_confirm_reject_undo_stack_and_audit(client, sat):
    e = sat["open"]
    assert _review(client, e, "confirm", "looks real").json()["new_status"] == "REVIEW_CONFIRMED"
    assert _review(client, e, "CONFIRM").status_code == 409
    assert _review(client, e, "REJECT", "shadow").json()["new_status"] == "REVIEW_REJECTED"
    u1 = _review(client, e, "UNDO").json()
    assert (u1["old_status"], u1["new_status"]) == ("REVIEW_REJECTED", "REVIEW_CONFIRMED")
    d = client.get(f"/api/sat-monitoring/events/{e}", headers=AUTH).json()
    assert d["reviewed_by"] == "alice" and d["review_note"] == "looks real" and d["status_kind"] == "HUMAN"
    assert _review(client, e, "UNDO").json()["new_status"] == "SUSPECTED"
    d = client.get(f"/api/sat-monitoring/events/{e}", headers=AUTH).json()
    assert d["reviewed_by"] is None and d["status_kind"] == "AUTOMATIC"
    assert _review(client, e, "UNDO").status_code == 409
    assert [x["action"] for x in d["review_log"]] == ["CONFIRM", "REJECT", "UNDO", "UNDO"]
    conn = sdb.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE sat_review_log SET note='x'")
    conn.close()


def test_review_errors(client, sat):
    assert _review(client, sat["open"], "DELETE").status_code == 422
    assert _review(client, 999, "CONFIRM").status_code == 404
    assert _review(client, sat["old"], "CONFIRM").status_code == 409            # superseded rows are frozen
    assert _review(client, sat["open"], "UNDO").status_code == 409


def test_field_check_sends_neutral_message_and_failure_changes_nothing(client, sat):
    client.sender.ok = False
    r = _review(client, sat["open"], "FIELD_CHECK", "please check")
    assert r.status_code == 502
    d = client.get(f"/api/sat-monitoring/events/{sat['open']}", headers=AUTH).json()
    assert d["status"] == "SUSPECTED" and d["review_log"] == []
    client.sender.ok = True
    r = _review(client, sat["open"], "FIELD_CHECK", "please check")
    assert r.status_code == 200 and r.json()["new_status"] == "FIELD_CHECK_REQUESTED" and r.json()["telegram_sent"]
    text = client.sent[-1]
    assert "Suspected vegetation/land-cover change detected: 2.50 ha" in text and "Stand A" in text
    assert "Location (approx.): 57.001, 24.501" in text and "Requested by: alice" in text
    assert not any(w in text.lower() for w in store.FORBIDDEN_WORDS)
    assert _review(client, sat["open"], "FIELD_CHECK").status_code == 409


# ── CREATE_RISK (human only, test copy of forest_ai.db) ─────────────────────
def _risk_rows(database, rid):
    c = sqlite3.connect(database.DB_NAME)
    c.row_factory = sqlite3.Row
    risk = dict(c.execute("SELECT * FROM risks WHERE id=?", (rid,)).fetchone())
    ev = [dict(r) for r in c.execute("SELECT * FROM risk_events WHERE risk_id=? ORDER BY id", (rid,))]
    evid = [dict(r) for r in c.execute("SELECT * FROM risk_evidence WHERE risk_id=?", (rid,))]
    n = c.execute("SELECT COUNT(*) FROM risks").fetchone()[0]
    c.close()
    return risk, ev, evid, n


def test_create_risk_uses_existing_incident_and_evidence(client, sat, forest):
    r = _review(client, sat["open"], "CREATE_RISK", "needs follow-up")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["risk_created"] is True and body["new_status"] == "SUSPECTED"     # a risk is not a review verdict
    risk, events, evid, n = _risk_rows(forest, body["risk_id"])
    assert n == 1
    assert (risk["entity_type"], risk["entity_id"], risk["rule_code"], risk["data_origin"], risk["status"],
            risk["risk_level"]) == ("SATELLITE", f"sat_event:{sat['open']}", "SATELLITE_UNREGISTERED_CHANGE", "REAL",
                                    "OPEN", "HIGH")
    assert risk["sector"] == "Stand A" and risk["occurred_at"] == "2026-10-21T10:00:00Z"
    assert risk["reason"].startswith("Suspected vegetation/land-cover change detected: 2.50 ha; 0.50 ha outside the "
                                     "approved boundary.")
    assert not any(w in risk["reason"].lower() for w in store.FORBIDDEN_WORDS)
    assert [e["event_type"] for e in events] == ["SATELLITE_RISK_CREATED", "AI_RECOMMENDATION_GENERATED"]
    assert events[0]["actor"] == "alice" and json.loads(events[0]["details"])["event_id"] == sat["open"]
    assert len(evid) == 1 and (evid[0]["source_provider"], evid[0]["data_origin"], evid[0]["ref_table"],
                               evid[0]["ref_id"]) == ("SATELLITE", "REAL", "sat_change_events", sat["open"])
    assert json.loads(risk["ai_recommendation"])["summary"] == "verify first"
    rec = client.recs[-1]
    assert rec["entity_type"] == "SATELLITE" and "suspected" in rec["satellite_context"].lower()
    assert "Do not call it illegal" in rec["extra_prompt_block"]
    d = client.get(f"/api/sat-monitoring/events/{sat['open']}", headers=AUTH).json()
    assert d["risk_id"] == body["risk_id"] and d["review_log"][-1]["action"] == "CREATE_RISK"
    again = _review(client, sat["open"], "CREATE_RISK")
    assert again.status_code == 409 and again.json()["risk_id"] == body["risk_id"]
    assert _risk_rows(forest, body["risk_id"])[3] == 1
    assert _review(client, sat["open"], "UNDO").status_code == 409             # CREATE_RISK is not undone here


def test_create_risk_during_registered_work_uses_the_other_rule_code(client, sat, forest):
    conn = sdb.connect()
    conn.execute("UPDATE sat_change_events SET gps_context_json=? WHERE id=?",
                 (json.dumps({"context_label": "CHANGE_DURING_REGISTERED_WORK", "activity_records": 4}), sat["open"]))
    conn.commit()
    conn.close()
    rid = _review(client, sat["open"], "CREATE_RISK").json()["risk_id"]
    assert _risk_rows(forest, rid)[0]["rule_code"] == "SATELLITE_CHANGE_DURING_WORK"


def test_create_risk_retry_after_failed_link_reuses_the_same_risk(sat, forest):
    ev, area = store.load_current_event(sat["open"])
    rec = lambda inc: None                                                   # AI unavailable -> fallback text
    rid1, created1 = risk_bridge.create_risk(ev, area, "alice", database=forest, recommend=rec)
    # the link write to satellite.db "failed": the event still has no risk_id; a retry must not duplicate
    rid2, created2 = risk_bridge.create_risk(ev, area, "alice", database=forest, recommend=rec)
    assert (rid1, created1, created2) == (rid2, True, False)
    risk, events, _, n = _risk_rows(forest, rid1)
    assert n == 1 and events[-1]["actor"] == "ai_fallback" and json.loads(risk["ai_recommendation"])["options"] == []


def test_reject_on_linked_risk_adds_risk_event_and_keeps_risk_status(client, sat, forest):
    rid = _review(client, sat["open"], "CREATE_RISK").json()["risk_id"]
    assert _review(client, sat["open"], "REJECT", "tractor track").status_code == 200
    _review(client, sat["open"], "UNDO")
    risk, events, _, _ = _risk_rows(forest, rid)
    assert risk["status"] == "OPEN"                                          # the existing workflow decides
    assert [e["event_type"] for e in events][-2:] == ["SATELLITE_REVIEW_REJECTED", "SATELLITE_REVIEW_REJECT_UNDONE"]
    assert events[-2]["details"] == "tractor track"


def test_confirm_never_creates_a_risk(client, sat, forest):
    _review(client, sat["open"], "CONFIRM")
    c = sqlite3.connect(forest.DB_NAME)
    assert c.execute("SELECT COUNT(*) FROM risks").fetchone()[0] == 0
    c.close()


# ── D4 wording ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ev", [
    {"changed_area_ha": 5.0, "changed_area_ha_buffer": 1.2, "classification": "POTENTIAL_CHANGE_OUTSIDE_BOUNDARY"},
    {"changed_area_ha": None, "changed_area_ha_buffer": None, "classification": "POTENTIAL_FOREST_LOSS"},
    {"changed_area_ha": 0.1, "changed_area_ha_buffer": 0, "classification": "POSSIBLE_SEASONAL_OR_ENVIRONMENTAL",
     "status": "RECOVERED"}])
def test_wording_is_neutral(ev):
    s = store.event_summary(ev)
    assert s.startswith("Suspected vegetation/land-cover change detected: ")
    assert not any(w in s.lower() for w in store.FORBIDDEN_WORDS + ("felling", "logging"))
    if ev["changed_area_ha"] is None:
        assert "unknown" in s                                                 # missing never becomes 0


# ── Stage 3 additions: UI fields, sectors, lookup ───────────────────────────
def test_overview_kpis_geometry_and_pending_area_jobs(client, sat):
    client.post("/api/sat-monitoring/areas", json={"source": "LVM_GEO", "source_ref": "NEW", "name": "New",
                                                   "geometry": GOOD}, headers=AUTH)
    o = client.get("/api/sat-monitoring/overview", headers=AUTH).json()
    k = o["kpis"]
    assert (k["monitored_areas"], k["open_suspected_events"], k["recovered_events"]) == (1, 1, 1)
    assert k["awaiting_data"] == 1                                   # the queued ADD_AREA job
    assert [j["payload"]["source_ref"] for j in o["pending_area_jobs"]] == ["NEW"]
    assert "geometry" not in o["pending_area_jobs"][0]["payload"]
    assert o["areas"][0]["geometry"]["type"] == "Polygon"


def test_add_area_job_marks_its_area_as_backfill_in_progress(client, sat):
    conn = sdb.connect()
    conn.execute("INSERT INTO sat_jobs (kind, payload_json, dedup_key, status, requested_by, requested_at_utc) VALUES "
                 "('ADD_AREA', ?, 'ADD_AREA:LVM_GEO:LVM-1', 'RUNNING', 'alice', 'now')",
                 (json.dumps({"source": "LVM_GEO", "source_ref": "LVM-1", "name": "Stand A"}),))
    conn.commit()
    conn.close()
    a = client.get("/api/sat-monitoring/overview", headers=AUTH).json()["areas"][0]
    assert a["data_status"] == "BACKFILL_OR_FETCH_IN_PROGRESS"


def test_area_detail_has_map_layers_and_radar(client, sat):
    conn = sdb.connect()
    conn.execute("UPDATE sat_monitored_areas SET grid_json=? WHERE id=?",
                 (json.dumps({"bbox": [24.49, 56.99, 24.52, 57.02]}), sat["area"]))
    conn.execute("INSERT INTO sat_radar_anomalies (monitored_area_id, acquisition_id, sensing_time_utc, orbit_direction,"
                 " relative_orbit, baseline_acq_ids, created_at_utc, mask_path, n_pixels, changed_area_ha, "
                 "evidence_quality) VALUES (?, ?, '2026-10-25T05:00:00Z', 'ASCENDING', 58, '[]', 'now', 'm', 5, 0.05, "
                 "'GOOD')", (sat["area"], sat["acq"][3]))
    conn.commit()
    conn.close()
    d = client.get(f"/api/sat-monitoring/areas/{sat['area']}", headers=AUTH).json()
    assert d["area"]["grid_bbox"] == [24.49, 56.99, 24.52, 57.02]
    assert d["buffer_ring"]["type"] == "Polygon" and len(d["buffer_ring"]["coordinates"]) == 2   # ring with a hole
    assert d["radar_anomalies"][0]["relative_orbit"] == 58
    assert d["events"][0]["change_geojson"]["type"] == "FeatureCollection"
    assert {x["product_id"] for x in d["timeline"]} == {"P0", "P1", "P2", "P3"}
    assert d["attribution"] == "Contains modified Copernicus Sentinel data 2026"


def test_event_detail_area_algorithm_and_undo_flag(client, sat):
    conn = sdb.connect()
    conn.execute("INSERT INTO sat_detection_generations (created_at_utc, finished_at_utc, area_ids, code_version, reason,"
                 " status) VALUES ('2026-10-21T10:30:00Z', '2026-10-21T12:00:00Z', ?, 'abc1234', 't', 'OK')",
                 (json.dumps([sat["area"]]),))
    conn.commit()
    conn.close()
    e = client.get(f"/api/sat-monitoring/events/{sat['open']}", headers=AUTH).json()
    assert e["algorithm"]["generation_id"] == 1 and e["algorithm"]["code_version"] == "abc1234"
    assert e["area"]["name"] == "Stand A" and e["area"]["geometry"]["type"] == "Polygon"
    assert e["before"][0]["product_id"] == "P0" and e["undo_available"] is False
    _review(client, sat["open"], "REJECT")
    assert client.get(f"/api/sat-monitoring/events/{sat['open']}", headers=AUTH).json()["undo_available"] is True


def test_health_reports_credentials_by_name_only(client, monkeypatch):
    monkeypatch.delenv("SENTINEL_CLIENT_ID", raising=False)
    monkeypatch.delenv("SENTINEL_CLIENT_SECRET", raising=False)
    h = client.get("/api/sat-monitoring/health", headers=AUTH).json()
    assert h["credentials_configured"] is False and h["failed_jobs"] == 0 and h["month"]["pu_guard"] == 1600.0
    monkeypatch.setenv("SENTINEL_CLIENT_ID", "id-value")
    monkeypatch.setenv("SENTINEL_CLIENT_SECRET", "secret-value")
    r = client.get("/api/sat-monitoring/health", headers=AUTH)
    assert r.json()["credentials_configured"] is True and "secret-value" not in r.text and "id-value" not in r.text


def test_sectors_list_reads_main_db_read_only(client, sat, tmp_path, monkeypatch):
    f = tmp_path / "main.db"
    c = sqlite3.connect(f)
    c.executescript("CREATE TABLE sectors (id INTEGER PRIMARY KEY, name TEXT, boundary_json TEXT);"
                    "INSERT INTO sectors VALUES (1, 'A-1', '[[57,24],[57,24.1],[57.1,24.1]]'), (2, 'B-2', '[]'),"
                    " (3, 'C-3', NULL);")
    c.commit()
    c.close()
    monkeypatch.setenv("FOREST_DB_PATH", str(f))
    before = _sha(f)
    conn = sdb.connect()
    conn.execute("INSERT INTO sat_monitored_areas (source, source_ref, name, geometry_geojson, area_ha, buffer_m, "
                 "grid_json, added_by, added_at_utc) VALUES ('SECTOR','1','A-1','{}',1,100,'{}','x','now')")
    conn.commit()
    conn.close()
    s = {x["name"]: x for x in client.get("/api/sat-monitoring/sectors", headers=AUTH).json()["sectors"]}
    assert s["A-1"]["has_polygon"] and s["A-1"]["monitored_area_id"]
    assert not s["B-2"]["has_polygon"] and not s["C-3"]["has_polygon"]
    assert _sha(f) == before


def test_lookup_for_the_lvm_geo_button(client, sat):
    r = client.get("/api/sat-monitoring/lookup?source=LVM_GEO&source_ref=LVM-1", headers=AUTH).json()
    assert r == {"monitored": True, "area_id": sat["area"], "queued_job_id": None}
    client.post("/api/sat-monitoring/areas", json={"source": "LVM_GEO", "source_ref": "vmd-9", "name": "VMD 1-2",
                                                   "geometry": GOOD}, headers=AUTH)
    r = client.get("/api/sat-monitoring/lookup?source=LVM_GEO&source_ref=vmd-9", headers=AUTH).json()
    assert r["monitored"] is False and r["queued_job_id"]
    assert client.get("/api/sat-monitoring/lookup?source=NOPE&source_ref=1", headers=AUTH).status_code == 422


def test_single_part_multipolygon_is_unwrapped_and_multi_part_refused(client, sat):
    one = {"type": "MultiPolygon", "coordinates": [GOOD["coordinates"]]}
    r = client.post("/api/sat-monitoring/areas", json={"source": "LVM_GEO", "source_ref": "M1", "name": "m",
                                                       "geometry": one}, headers=AUTH)
    assert r.status_code == 202
    conn = sdb.connect_ro()
    assert json.loads(conn.execute("SELECT payload_json FROM sat_jobs").fetchone()[0])["geometry"]["type"] == "Polygon"
    conn.close()
    two = {"type": "MultiPolygon", "coordinates": [GOOD["coordinates"], GOOD["coordinates"]]}
    r = client.post("/api/sat-monitoring/areas", json={"source": "LVM_GEO", "source_ref": "M2", "name": "m",
                                                       "geometry": two}, headers=AUTH)
    assert r.status_code == 422 and "multi-part" in r.json()["error"]
