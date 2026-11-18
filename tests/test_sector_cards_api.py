"""Sectors cards API (owner D6/D12/D14, F3): read-only payload, auth on every route, archive filter only when the
column exists, full identifier in the application (masking exists only in fixtures), legacy-modules flag.

Temporary databases only (forest_ai.db via database.init_db, a minimal satellite.db); nothing live is opened.
"""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

import database

USER, PASS = "cards-test-user", "cards-test-pass"
KAD = "1234" + "0010001"          # synthetic 11-digit cadastral test value (not a real parcel)
RING = [[56.9600, 24.1900], [56.9600, 24.2000], [56.9650, 24.2000], [56.9650, 24.1900], [56.9600, 24.1900]]


def _sat_db(path):
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE sat_monitored_areas (id INTEGER PRIMARY KEY, source TEXT, source_ref TEXT, name TEXT, geometry_geojson TEXT,
      area_ha REAL, buffer_m REAL, grid_json TEXT, added_by TEXT, added_at_utc TEXT, active INTEGER, removed_at_utc TEXT);
    CREATE TABLE sat_acquisitions (id INTEGER PRIMARY KEY, monitored_area_id INTEGER, sensor TEXT, sensing_time_utc TEXT,
      status TEXT, valid_pct_inside REAL, quicklook_path TEXT);
    CREATE TABLE sat_change_events (id INTEGER PRIMARY KEY, monitored_area_id INTEGER, status TEXT, classification TEXT,
      confidence TEXT, superseded_at_utc TEXT);
    CREATE TABLE sat_jobs (id INTEGER PRIMARY KEY, kind TEXT, payload_json TEXT, status TEXT);
    """)
    grid = json.dumps({"bbox": [24.18, 56.95, 24.21, 56.97], "width": 120, "height": 90})
    c.execute("INSERT INTO sat_monitored_areas VALUES (1,'SECTOR','1','Mon',NULL,30,100,?, 'x','2026-11-01T00:00:00Z',1,NULL)", (grid,))
    c.execute("INSERT INTO sat_monitored_areas VALUES (2,'LVM_GEO','VMD:nodala1:777','Lvm',NULL,1,100,?, 'x','2026-11-01T00:00:00Z',1,NULL)", (grid,))
    c.execute("INSERT INTO sat_monitored_areas VALUES (3,'SECTOR','3','Stopped',NULL,1,100,?, 'x','2026-11-01T00:00:00Z',0,'2026-11-05T00:00:00Z')", (grid,))
    c.executemany("INSERT INTO sat_acquisitions VALUES (?,?,?,?,?,?,?)", [
        (10, 1, 'S2', '2026-11-04T09:00:00Z', 'OK', 99.0, '/nonexistent/a.png'),
        (11, 1, 'S2', '2026-11-06T09:00:00Z', 'OK', 7.4, '/nonexistent/b.png'),     # below min_valid → not "last valid"
        (12, 1, 'S1', '2026-11-07T04:00:00Z', 'OK', 100.0, '/nonexistent/c.png'),
        (13, 1, 'S2', '2026-11-08T09:00:00Z', 'SKIPPED_CLOUD', None, None)])
    c.executemany("INSERT INTO sat_change_events VALUES (?,?,?,?,?,?)", [
        (20, 1, 'SUSPECTED', 'POTENTIAL_FOREST_LOSS', 'HIGH', None),
        (21, 1, 'REVIEW_CONFIRMED', 'POTENTIAL_FOREST_LOSS', 'HIGH', None),
        (22, 1, 'SUSPECTED', 'POTENTIAL_FOREST_LOSS', 'HIGH', '2026-11-10T00:00:00Z')])   # superseded → not counted
    c.execute("INSERT INTO sat_jobs VALUES (30,'ADD_AREA',?, 'QUEUED')", (json.dumps({"source": "SECTOR", "source_ref": "4"}),))
    c.commit(); c.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    app_db, sat_db = tmp_path / "forest_ai.db", tmp_path / "satellite.db"
    monkeypatch.setattr(database, "DB_NAME", str(app_db)); database.init_db()
    with sqlite3.connect(app_db) as c:
        for sid, name, ha in ((1, "MON-1", 30.0), (2, "LVM-2", 1.08), (3, "STOP-3", 0.4), (4, "QUEUE-4", 0.21), (5, "PLAIN-5", None)):
            c.execute("INSERT INTO sectors(id,name,area_ha,boundary_json,organization_id,data_origin) VALUES(?,?,?,?,1,'REAL')",
                      (sid, name, ha, json.dumps(RING)))
        c.execute("INSERT INTO geodata_sources(sector_id,sector,organization_id,boundary_source_type,provider,source_layer,"
                  "source_feature_id,source_dataset_title,source_attribution,source_properties,source_crs,imported_at,source_last_checked_at) "
                  "VALUES(2,'LVM-2',1,'X','VMD_OPEN_DATA','L','VMD:nodala1:777','T','A',?, 'EPSG:3059','2026-11-17T05:50:14Z','2026-11-17T05:50:14Z')",
                  (json.dumps({"kadastrs": KAD, "kvart": "348", "nog": "10"}),))
    _sat_db(sat_db)
    monkeypatch.setenv("DASHBOARD_USERNAME", USER); monkeypatch.setenv("DASHBOARD_PASSWORD", PASS)
    monkeypatch.setenv("SAT_DB_PATH", str(sat_db))
    import api
    monkeypatch.setattr(api, "DB_NAME", str(app_db))
    return {"api": api, "client": TestClient(api.app), "app_db": app_db, "sat_db": sat_db}


def get(env, path, auth=True):
    return env["client"].get(path, auth=(USER, PASS) if auth else None)


def by_name(payload):
    return {s["name"]: s for s in payload["sectors"]}


def test_auth_on_every_new_route(env):
    for path in ("/api/sectors/cards", "/api/sectors/cards/1"):
        assert get(env, path, auth=False).status_code == 401
        assert env["client"].get(path, auth=(USER, "wrong")).status_code == 401
        assert get(env, path).status_code == 200


def test_cards_stored_values_and_monitoring(env):
    p = get(env, "/api/sectors/cards").json()
    assert p["meta"] == {"satellite_available": True, "detection_min_ha": 0.5, "min_valid_pct": 60.0, "archive_column": False}
    s = by_name(p)
    m = s["MON-1"]["monitoring"]
    assert m["link"] == "SECTOR" and m["ok_acquisitions"] == 3
    assert m["last_valid_s2"]["acq_id"] == 10                    # 7.4 % valid S2 of 11-06 is not "last valid"
    assert m["last_s1"]["sensing_time_utc"] == "2026-11-07T04:00:00Z"
    assert (m["open_suspected"], m["confirmed"]) == (1, 1)        # superseded event 22 not counted
    assert m["preview"] == {"acq_id": 10, "kind": "falsecolor", "sensing_time_utc": "2026-11-04T09:00:00Z", "valid_pct_inside": 99.0}
    assert s["LVM-2"]["monitoring"]["link"] == "LVM_GEO"          # D7: exact source_feature_id match
    assert s["STOP-3"]["monitoring"]["active"] is False
    assert s["QUEUE-4"]["monitoring"] is None and s["QUEUE-4"]["queued_job_id"] == 30
    assert s["PLAIN-5"]["monitoring"] is None and s["PLAIN-5"]["queued_job_id"] is None
    assert s["PLAIN-5"]["area_ha"] is None                        # NULL stays NULL, never 0


def test_identifier_is_the_full_stored_number_F3(env):
    card = by_name(get(env, "/api/sectors/cards").json())["LVM-2"]
    assert card["identifier"] == {"cadastre": KAD, "kvart": "348", "nog": "10", "source_feature_id": "VMD:nodala1:777"}
    from pathlib import Path
    for f in ("services/sector_cards.py", "assets/sectors-cards.js", "api.py"):
        src = Path(f).read_text(encoding="utf-8")
        assert "fixture_redaction" not in src and "mask_cadastre" not in src and "…(" not in src, f


def test_satellite_db_missing_is_unknown_not_unmonitored(env, monkeypatch):
    monkeypatch.setenv("SAT_DB_PATH", str(env["sat_db"]) + ".missing")
    p = get(env, "/api/sectors/cards").json()
    assert p["meta"]["satellite_available"] is False
    assert all(s["monitoring"] is None and s["monitoring_unavailable"] is True for s in p["sectors"])


def test_archive_filter_only_when_column_exists(env):
    assert len(get(env, "/api/sectors/cards").json()["sectors"]) == 5
    assert len(get(env, "/api/sectors").json()) == 5
    with sqlite3.connect(env["app_db"]) as c:                    # what the approved D14 step would add (not in this release)
        c.execute("ALTER TABLE sectors ADD COLUMN archived_at TEXT")
        c.execute("UPDATE sectors SET archived_at='2026-11-18T00:00:00Z' WHERE id IN (3,5)")
    p = get(env, "/api/sectors/cards").json()
    assert p["meta"]["archive_column"] is True
    assert sorted(by_name(p)) == ["LVM-2", "MON-1", "QUEUE-4"]
    assert sorted(x["name"] for x in get(env, "/api/sectors").json()) == ["LVM-2", "MON-1", "QUEUE-4"]
    names = [s["name"] for g in get(env, "/api/objects").json() for s in g.get("sectors", [])]
    assert "STOP-3" not in names and "PLAIN-5" not in names and "MON-1" in names
    one = get(env, "/api/sectors/cards/5").json()                # archived id still opens by direct link
    assert one["sector"]["name"] == "PLAIN-5" and one["sector"]["archived_at"] == "2026-11-18T00:00:00Z"
    assert get(env, "/api/sectors/cards/999").status_code == 404


def test_forest_map_sectors_hide_archived_only_with_column(env, monkeypatch):
    from services.geodata import forest_map as fm

    def conn():
        c = sqlite3.connect(env["app_db"]); c.row_factory = sqlite3.Row; return c
    monkeypatch.setattr(fm, "context", lambda actor: {"organization_id": 1})
    monkeypatch.setattr(fm.data, "_app_connection", conn)
    ids = lambda: sorted(f["properties"]["id"] for f in fm.sectors("t")["features"])
    assert ids() == [1, 2, 3, 4, 5]
    with sqlite3.connect(env["app_db"]) as c:
        c.execute("ALTER TABLE sectors ADD COLUMN archived_at TEXT")
        c.execute("UPDATE sectors SET archived_at='2026-11-18T00:00:00Z' WHERE id=3")
    assert ids() == [1, 2, 4, 5]


def test_legacy_modules_flag_injection(env, monkeypatch):
    monkeypatch.delenv("SECTOR_LEGACY_MODULES", raising=False)
    assert "window.SECTOR_LEGACY_MODULES=true" not in get(env, "/").text
    monkeypatch.setenv("SECTOR_LEGACY_MODULES", "1")
    html = get(env, "/").text
    assert "window.SECTOR_LEGACY_MODULES=true" in html
    assert html.index("window.SECTOR_LEGACY_MODULES=true") < html.index("/assets/sectors-cards.js")
