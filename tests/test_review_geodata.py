"""Review mode for LVM GEO / Meža karte (demo release): server-side blocks, sector exclusion, origin labels.

Run: python3 -m pytest tests/test_review_geodata.py -v
Uses only tmp SQLite files; never data/forest_ai.db and never the national catalogue.
"""
import json
import os
import sqlite3
import tempfile

import pytest

AUTH = ("pytest", "pytest")
os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
os.environ.setdefault("INTEGRATION_CREDENTIALS_KEY", "pytest-test-key-not-for-production")


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", AUTH[0])
    monkeypatch.setenv("DASHBOARD_PASSWORD", AUTH[1])
    import api, database
    from services import review_mode
    from services.geodata import gps_map, gps_violations, vmd_dataset
    db = str(tmp_path / "demo.db")
    monkeypatch.setattr(database, "DB_NAME", db)
    monkeypatch.setattr(api, "DB_NAME", db)
    database.init_db()
    c = sqlite3.connect(db)
    poly = json.dumps([[57.0, 24.0], [57.0, 24.01], [57.01, 24.01], [57.01, 24.0], [57.0, 24.0]])
    poly2 = json.dumps([[57.3, 21.9], [57.3, 21.91], [57.31, 21.91], [57.31, 21.9], [57.3, 21.9]])
    c.execute("INSERT INTO sectors(id,name,boundary_json,center_lat,center_lon,data_origin) VALUES(1,'DEMO-001',?,57.305,21.905,'SIMULATED')", (poly2,))
    c.execute("INSERT INTO sectors(id,name,boundary_json,center_lat,center_lon,data_origin) VALUES(26,'FIELD-TEST-01',?,57.005,24.005,'REAL')", (poly,))
    c.execute("INSERT INTO sector_employees(id,full_name,sector) VALUES(1,'Demo Operator 01','DEMO-001')")
    c.execute("INSERT INTO sector_employees(id,full_name,sector) VALUES(6,'Field Worker 01','FIELD-TEST-01')")
    c.execute("INSERT INTO work_sessions(id,employee,employee_id,sector,check_in_time,finish_time) VALUES(1,'Demo Operator 01',1,'DEMO-001','2026-11-12 07:00:00 UTC','2026-11-12 09:00:00 UTC')")
    c.execute("INSERT INTO work_sessions(id,employee,employee_id,sector,check_in_time,finish_time) VALUES(32,'Field Worker 01',6,'FIELD-TEST-01','2026-11-12 07:00:00 UTC','2026-11-12 09:00:00 UTC')")
    for i in range(3):
        c.execute("INSERT INTO session_track_points(session_id,employee_id,sector,latitude,longitude,horizontal_accuracy,inside_boundary,recorded_at) VALUES(1,1,'DEMO-001',57.305,21.905,5,1,?)", (f"2026-11-12 07:0{i}:00 UTC",))
        c.execute("INSERT INTO session_track_points(session_id,employee_id,sector,latitude,longitude,horizontal_accuracy,inside_boundary,recorded_at) VALUES(32,6,'FIELD-TEST-01',57.005,24.005,5,1,?)", (f"2026-11-12 07:0{i}:00 UTC",))
    c.execute("INSERT INTO live_locations(employee_id,sector,latitude,longitude,started_at,updated_at,expires_at) VALUES(6,'FIELD-TEST-01',57.005,24.005,'2026-11-12 07:00:00 UTC','2026-11-12 07:05:00 UTC','2099-01-01 00:00:00 UTC')")
    c.execute("INSERT INTO risks(id,sector,risk_level,reason,data_origin) VALUES(62,'FIELD-TEST-01','HIGH','r','REAL')")
    c.commit(); c.close()
    monkeypatch.setattr(review_mode, "ENABLED", True)
    monkeypatch.setenv("REVIEW_MAP_EXCLUDED_SECTORS", "FIELD-TEST-01")
    return api, database, review_mode, gps_map, gps_violations, vmd_dataset, db


def _client(api, review_mode):
    from fastapi.testclient import TestClient
    installed = any(m.cls is review_mode.ReviewModeMiddleware for m in api.app.user_middleware)
    return TestClient(api.app if installed else review_mode.ReviewModeMiddleware(api.app))


@pytest.mark.parametrize("path", ["/api/geodata/vmd/import-selected", "/api/geodata/vmd/import", "/api/geodata/vmd/territories",
                                  "/api/geodata/lvm/preview", "/api/geodata/lvm/import", "/api/geodata/lvm/apply",
                                  "/api/geodata/lvm/sectors/1/refresh"])
def test_registration_is_403_with_bilingual_message(mods, path):
    api, _, review_mode, *_ = mods
    with _client(api, review_mode) as c:
        for body in ({"dry_run": True}, {"dry_run": False, "confirmed": True}, {}):
            r = c.post(path, json=body, auth=AUTH)
            assert r.status_code == 403
            assert r.json() == {"detail": "Demo režīmā reģistrācija ir izslēgta (Registration is disabled in demo mode)",
                                "code": "registration_disabled_in_demo"}


def test_incident_creation_is_403(mods):
    api, _, review_mode, *_ = mods
    with _client(api, review_mode) as c:
        r = c.post("/api/geodata/forest-map/gps/violations/incident", json={"session_id": 1, "exit_point_id": 1}, auth=AUTH)
    assert r.status_code == 403 and r.json()["code"] == "incident_creation_disabled_in_demo"


def test_handlers_refuse_even_without_middleware(mods):
    """Defence in depth: the route handlers themselves refuse in review mode."""
    api, database, review_mode, *_ , db = mods
    from fastapi.testclient import TestClient
    with TestClient(api.app) as c:  # api.app without wrapping (middleware may be absent in this process)
        body = {"feature_ids": ["x"], "dataset_version": "a"*64, "sector_name": "S", "responsible_first_name": "A",
                "responsible_last_name": "B", "dry_run": False, "confirmed": True}
        if any(m.cls is review_mode.ReviewModeMiddleware for m in api.app.user_middleware):
            pytest.skip("middleware installed at import; covered by the 403 tests")
        r = c.post("/api/geodata/vmd/import-selected", json=body, auth=AUTH)
        assert r.status_code == 403
        r = c.post("/api/geodata/forest-map/gps/violations/incident", json={"session_id": 1, "exit_point_id": 1}, auth=AUTH)
        assert r.status_code == 403
    assert sqlite3.connect(db).execute("SELECT count(*) FROM sectors").fetchone()[0] == 2
    assert sqlite3.connect(db).execute("SELECT count(*) FROM risks").fetchone()[0] == 1


def test_exclusion_hides_sector_sessions_points_live_and_incidents(mods):
    *_, gps_map, gps_violations, vmd_dataset, db = mods
    c = gps_map._app()
    assert [r[0] for r in c.execute("SELECT name FROM sectors")] == ["DEMO-001"]
    assert [r[0] for r in c.execute("SELECT id FROM work_sessions")] == [1]
    assert c.execute("SELECT count(*) FROM session_track_points WHERE session_id=32").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM live_locations").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM risks").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM main.sectors").fetchone()[0] == 2  # data itself untouched
    v = vmd_dataset._app_connection()
    assert [r[0] for r in v.execute("SELECT name FROM sectors")] == ["DEMO-001"]


def test_exclusion_through_forest_map_functions(mods):
    *_, gps_map, gps_violations, vmd_dataset, db = mods
    from services.geodata import forest_map
    from datetime import datetime, timezone
    payload = json.dumps([
        forest_map.sectors("pytest"),
        gps_map.positions(1, stale_minutes=10**6),
        gps_map.track(1, "worker", 6, datetime(2026, 11, 12, tzinfo=timezone.utc), datetime(2026, 11, 13, tzinfo=timezone.utc)),
        gps_violations.sessions("worker", 6),
        gps_violations.overview(1, days=365, now=datetime(2026, 11, 13, tzinfo=timezone.utc)),
    ], default=str)
    assert "FIELD-TEST-01" not in payload and "57.005" not in payload and "24.005" not in payload
    with pytest.raises(LookupError):
        gps_violations.violations(1, "worker", 6, "32")
    with pytest.raises(LookupError):
        gps_violations.session_violations(1, 32)


def test_seeded_sessions_are_labelled_from_sector_origin(mods):
    *_, gps_map, gps_violations, vmd_dataset, db = mods
    from datetime import datetime, timezone
    t = gps_map.track(1, "worker", 1, datetime(2026, 11, 12, tzinfo=timezone.utc), datetime(2026, 11, 13, tzinfo=timezone.utc))
    assert t["origins"] == ["SIMULATED"] and {p["origin"] for p in t["points"]} == {"SIMULATED"}
    assert gps_violations.violations(1, "worker", 1, "1")["origin"] == "SIMULATED"


def test_nothing_changes_outside_review_mode(mods, monkeypatch):
    api, database, review_mode, gps_map, gps_violations, vmd_dataset, db = mods
    from datetime import datetime, timezone
    monkeypatch.setattr(review_mode, "ENABLED", False)
    assert review_mode.excluded_sectors() == frozenset()
    c = gps_map._app()
    assert c.execute("SELECT count(*) FROM sectors").fetchone()[0] == 2
    t = gps_map.track(1, "worker", 1, datetime(2026, 11, 12, tzinfo=timezone.utc), datetime(2026, 11, 13, tzinfo=timezone.utc))
    assert t["origins"] == ["REAL"]  # production behaviour unchanged
