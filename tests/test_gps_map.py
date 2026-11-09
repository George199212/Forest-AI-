"""GPS control map: spatial classification, origins, gaps and flag-gated compartment alerts.

Temporary databases only. Geometry is built in EPSG:10306 metres and converted with pyproj.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
import shapely
from pyproj import Transformer
from shapely.geometry import box

import database
from services.geodata import gps_map as gps

TO_WGS = Transformer.from_crs(10306, 4326, always_xy=True).transform
TO_NATIVE = Transformer.from_crs(4326, 10306, always_xy=True).transform
X0, Y0 = TO_NATIVE(24.5, 57.0)
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def wgs(x, y):
    lon, lat = TO_WGS(x, y);return lat, lon


def ts(dt):return dt.strftime('%Y-%m-%d %H:%M:%S UTC')


@pytest.fixture
def world(tmp_path, monkeypatch):
    app = tmp_path/'app.db';forest = tmp_path/'forest.sqlite'
    monkeypatch.setattr(database, 'DB_NAME', str(app));database.init_db()
    # Registered sector: 200 m square west of X0. Compartments C1 | C2 share an edge east of X0.
    sector = box(X0-600, Y0-100, X0-400, Y0+100)
    ring = [list(wgs(x, y)) for x, y in sector.exterior.coords]
    with sqlite3.connect(app) as c:
        c.execute("INSERT INTO sectors(name,boundary_json,organization_id,data_origin) VALUES('S-1',?,1,'REAL')", (json.dumps(ring),))
        c.execute("INSERT INTO sector_employees(id,sector,full_name,telegram_user_id) VALUES(7,'S-1','Worker One','700')")
        c.execute("INSERT INTO work_sessions(id,user_id,employee,sector,check_in_time,employee_id) VALUES(70,'700','Worker One','S-1',?,7)", (ts(NOW-timedelta(hours=1)),))
    with sqlite3.connect(forest) as c:
        c.executescript('CREATE TABLE compartments(id INTEGER PRIMARY KEY,external_id TEXT,kadastrs TEXT,kvart TEXT,nog TEXT,native_geometry BLOB);'
                        'CREATE VIRTUAL TABLE native_index USING rtree(id,min_x,max_x,min_y,max_y);')
        for i, g in ((1, box(X0+400, Y0-100, X0+600, Y0+100)), (2, box(X0+600, Y0-100, X0+800, Y0+100))):
            c.execute('INSERT INTO compartments VALUES(?,?,?,?,?,?)', (i, f'VMD:test:{i}', '12340010001', '5', str(i), g.wkb))
            c.execute('INSERT INTO native_index VALUES(?,?,?,?,?)', (i, *g.bounds[0::2], *g.bounds[1::2]))
    monkeypatch.setattr(gps.nw, 'configured', lambda:True)
    monkeypatch.setattr(gps.nw, 'release', lambda:{'forest_db':str(forest), 'version':'test'})
    return app


def classify(dx, dy=0, accuracy=None):
    c = gps.Classifier(gps.registered_sectors(1))
    try:
        lat, lon = wgs(X0+dx, Y0+dy);return c(lat, lon, accuracy)
    finally:c.close()


# ── Step 3: spatial classification ─────────────────────────────────────────

def test_point_inside_registered_sector(world):
    assert classify(-500, accuracy=10) == {'class':gps.INSIDE_SECTOR, 'sector':'S-1'}


def test_point_inside_unregistered_compartment(world):
    r = classify(500, accuracy=5)
    assert r['class'] == gps.INSIDE_COMPARTMENT
    assert {k:r['compartment'][k] for k in ('id', 'kadastrs', 'kvart', 'nog')} == {'id':'VMD:test:1', 'kadastrs':'12340010001', 'kvart':'5', 'nog':'1'}


def test_point_outside_forest_register(world):
    assert classify(2000, accuracy=5) == {'class':gps.OUTSIDE_REGISTER}


def test_accuracy_crossing_register_edge_is_unknown_not_violation(world):
    assert classify(405, accuracy=20) == {'class':gps.UNKNOWN, 'reason':'accuracy_crosses_register_boundary'}
    assert classify(405, accuracy=None)['class'] == gps.INSIDE_COMPARTMENT  # no accuracy: the point itself


def test_accuracy_across_two_unregistered_compartments_stays_unregistered(world):
    r = classify(601, accuracy=20)
    assert r['class'] == gps.INSIDE_COMPARTMENT and r['compartment']['id'] == 'VMD:test:2'


def test_accuracy_crossing_sector_edge_is_unknown(world):
    assert classify(-405, accuracy=20) == {'class':gps.UNKNOWN, 'reason':'accuracy_crosses_sector_boundary'}


def test_poor_accuracy_and_missing_geodata_are_unknown_with_reason(world, monkeypatch):
    assert classify(500, accuracy=150)['reason'] == 'accuracy_too_poor'
    monkeypatch.setattr(gps.nw, 'configured', lambda:False)
    assert classify(500, accuracy=5) == {'class':gps.UNKNOWN, 'reason':'no_geodata'}


# ── Step 1: origins and staleness ──────────────────────────────────────────

def test_positions_carry_origin_from_stored_provenance_only(world):
    lat, lon = wgs(X0+500, Y0)
    with sqlite3.connect(world) as c:
        c.execute("INSERT INTO live_locations(employee_id,telegram_user_id,sector,latitude,longitude,live_period,started_at,updated_at,expires_at,last_status) VALUES(7,'700','S-1',?,?,3600,?,?,?,'OUT')",
                  (lat, lon, ts(NOW-timedelta(minutes=40)), ts(NOW-timedelta(minutes=2)), ts(NOW+timedelta(minutes=50))))
        c.execute("INSERT INTO sector_vehicles(id,sector,plate,vehicle_type) VALUES(4,'S-1','AB-1','Truck')")
        c.execute("INSERT INTO vehicle_gps_pings(vehicle_id,sector,latitude,longitude,inside_boundary,recorded_at) VALUES(4,'S-1',?,?,0,?)", (lat, lon, ts(NOW-timedelta(days=60))))
        c.execute("INSERT INTO sector_equipment(id,sector,equipment_code,type,provider,latitude,longitude,location_timestamp) VALUES(9,'S-1','JD-1','HARVESTER','john_deere',?,?,?)", (lat, lon, ts(NOW-timedelta(minutes=5))))
        c.execute("INSERT INTO integrations(id,organization_id,category,provider,integration_type,display_name,is_demo) VALUES(3,1,'fleet','fleet_gps_demo','api','Fleet demo',1)")
        c.execute("INSERT INTO integration_records(integration_id,organization_id,source_provider,entity_type,external_id,sector,source_timestamp,received_at,raw_payload_json,normalized_payload_json,validation_status,deduplication_key) VALUES(3,1,'fleet_gps_demo','GPSPosition','SIM-1:t','S-1',?,?,'{}',?,'VALID','SIM-1:t')",
                  ('2026-11-09T11:58:00Z', ts(NOW), json.dumps({'vehicle_id':'SIM-1', 'sector':'S-1', 'latitude':lat, 'longitude':lon, 'source_timestamp':'2026-11-09T11:58:00Z'})))
    entities = {(e['type'], e['name']):e for e in gps.positions(1, stale_minutes=15, now=NOW)['entities']}
    worker, truck, machine, sim = entities[('worker', 'Worker One')], entities[('vehicle', 'AB-1')], entities[('machine', 'JD-1')], entities[('vehicle', 'SIM-1')]
    assert (worker['origin'], worker['stale'], worker['age_s']) == ('REAL', False, 120)
    assert worker['spatial']['class'] == gps.INSIDE_COMPARTMENT
    assert (truck['origin'], truck['stale']) == ('UNKNOWN', True)     # no provider/source: provenance not provable
    assert machine['origin'] == 'SANDBOX' and machine['track_ref'] == {'kind':'equipment', 'id':9}
    assert sim['origin'] == 'SIMULATED' and sim['track_ref'] == {'kind':'simulated', 'id':'SIM-1'}


# ── Step 2: tracks — stored points only, gaps stay gaps ────────────────────

def add_points(world, offsets_seconds, dx=500, session=70, accuracy=5):
    lat, lon = wgs(X0+dx, Y0)
    with sqlite3.connect(world) as c:
        for i, s in enumerate(offsets_seconds):
            c.execute('INSERT INTO session_track_points(session_id,employee_id,telegram_user_id,sector,latitude,longitude,horizontal_accuracy,inside_boundary,recorded_at,received_at) VALUES(?,?,?,?,?,?,?,0,?,?)',
                      (session, 7, '700', 'S-1', lat+i*1e-6, lon, accuracy, ts(NOW-timedelta(minutes=30)+timedelta(seconds=s)), ts(NOW)))


def test_track_gap_longer_than_120s_is_a_gap_and_nothing_is_interpolated(world):
    add_points(world, [0, 30, 60, 400, 430])
    t = gps.track(1, 'worker', 7, NOW-timedelta(hours=2), NOW)
    assert len(t['points']) == 5 and len(t['gaps']) == 1 and t['gaps'][0]['seconds'] == 340
    assert sum(len(r['coords']) for r in t['runs']) == 5               # every drawn vertex is a stored point
    assert t['start']['time'] < t['end']['time'] and t['origins'] == ['REAL']
    assert t['class_counts'] == {gps.INSIDE_COMPARTMENT:5}


def test_track_runs_split_by_class_with_explicit_transition(world):
    add_points(world, [0, 30], dx=500);add_points(world, [60, 90], dx=-500)
    t = gps.track(1, 'worker', 7, NOW-timedelta(hours=2), NOW)
    assert [r['class'] for r in t['runs']] == [gps.INSIDE_COMPARTMENT, gps.INSIDE_SECTOR]
    assert t['transitions'][0]['from_class'] == gps.INSIDE_COMPARTMENT and not t['gaps']


def test_track_window_validation(world):
    with pytest.raises(ValueError):gps.track(1, 'worker', 7, NOW, NOW-timedelta(hours=1))
    with pytest.raises(ValueError):gps.track(1, 'worker', 7, NOW-timedelta(days=40), NOW)


# ── Step 4: alerts ─────────────────────────────────────────────────────────

def incidents(world):
    with sqlite3.connect(world) as c:
        return c.execute("SELECT id,rule_code,entity_type,entity_id,sector,data_origin,status FROM risks WHERE rule_code=?", (gps.RULE_CODE,)).fetchall()


def test_flag_off_creates_no_incident(world, monkeypatch):
    monkeypatch.delenv('FOREST_GPS_COMPARTMENT_ALERTS', raising=False)
    add_points(world, range(0, 600, 30))
    assert gps.evaluate_alerts(now=NOW) == [] and incidents(world) == []


def test_flag_on_creates_one_deduplicated_incident_with_evidence(world, monkeypatch):
    monkeypatch.setenv('FOREST_GPS_COMPARTMENT_ALERTS', '1')
    add_points(world, range(0, 600, 30))
    first = gps.evaluate_alerts(now=NOW)
    assert len(first) == 1
    (rid, rule, etype, eid, sector, origin, status), = incidents(world)
    assert (rule, etype, eid, sector, origin, status) == (gps.RULE_CODE, 'worker', 7, 'S-1', 'REAL', 'OPEN')
    with sqlite3.connect(world) as c:
        kinds = {r[0]:r for r in c.execute('SELECT evidence_type,data_origin,ref_table,ref_id FROM risk_evidence WHERE risk_id=?', (rid,))}
        events = [r[0] for r in c.execute('SELECT event_type FROM risk_events WHERE risk_id=?', (rid,))]
    assert set(kinds) == {'COMPARTMENT', 'GPS_FIRST_POINT', 'GPS_LAST_POINT', 'TRACK'}
    assert kinds['COMPARTMENT'][2:] == ('vmd_compartments', 1) and all(v[1] == 'REAL' for v in kinds.values())
    assert events == ['DETECTED']
    add_points(world, range(600, 900, 30))
    assert gps.evaluate_alerts(now=NOW+timedelta(minutes=5)) == [] and len(incidents(world)) == 1


def test_short_runs_and_gapped_runs_do_not_alert(world, monkeypatch):
    monkeypatch.setenv('FOREST_GPS_COMPARTMENT_ALERTS', '1')
    monkeypatch.setenv('FOREST_GPS_ALERT_MIN_MINUTES', '5')
    add_points(world, [0, 30, 60, 90])                  # 1.5 min
    add_points(world, [400, 430, 460])                  # after a gap: separate run, 1 min
    assert gps.evaluate_alerts(now=NOW) == []


def test_ambiguous_accuracy_points_never_alert(world, monkeypatch):
    monkeypatch.setenv('FOREST_GPS_COMPARTMENT_ALERTS', '1')
    add_points(world, range(0, 900, 30), dx=405, accuracy=20)   # radius crosses the register edge
    assert gps.evaluate_alerts(now=NOW) == []


def test_simulated_and_sandbox_points_never_create_incidents(world, monkeypatch):
    monkeypatch.setenv('FOREST_GPS_COMPARTMENT_ALERTS', '1')
    lat, lon = wgs(X0+500, Y0)
    with sqlite3.connect(world) as c:
        c.execute("INSERT INTO integrations(id,organization_id,category,provider,integration_type,display_name,is_demo) VALUES(3,1,'fleet','fleet_gps_demo','api','Fleet demo',1)")
        for i in range(30):
            when = NOW-timedelta(minutes=30)+timedelta(seconds=30*i)
            c.execute("INSERT INTO integration_records(integration_id,organization_id,source_provider,entity_type,external_id,sector,source_timestamp,received_at,raw_payload_json,normalized_payload_json,validation_status,deduplication_key) VALUES(3,1,'fleet_gps_demo','GPSPosition',?,'S-1',?,?,'{}',?,'VALID',?)",
                      (f'SIM:{i}', when.isoformat(), ts(NOW), json.dumps({'vehicle_id':'SIM', 'latitude':lat, 'longitude':lon, 'source_timestamp':when.isoformat()}), f'SIM:{i}'))
            c.execute("INSERT INTO vehicle_gps_pings(equipment_id,sector,latitude,longitude,inside_boundary,recorded_at,provider,entity_type) VALUES(9,'S-1',?,?,0,?,'john_deere','EQUIPMENT')", (lat, lon, ts(when)))
    assert gps.evaluate_alerts(now=NOW) == [] and incidents(world) == []


# ── Endpoints ──────────────────────────────────────────────────────────────

def test_gps_endpoints(world, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.geodata import forest_map as fm
    monkeypatch.setattr(fm, 'context', lambda actor:{'organization_id':1})
    add_points(world, [0, 30])
    app = FastAPI();app.include_router(fm.router(lambda:'test'));client = TestClient(app)
    r = client.get('/api/geodata/forest-map/gps/positions')
    assert r.status_code == 200 and r.headers['cache-control'] == 'private, no-store'
    assert client.get('/api/geodata/forest-map/gps/track', params={'kind':'nope', 'id':'7', 'start':'2026-11-09T00:00:00Z', 'end':'2026-11-09T12:00:00Z'}).status_code == 422
    t = client.get('/api/geodata/forest-map/gps/track', params={'kind':'worker', 'id':'7', 'start':'2026-11-09T00:00:00Z', 'end':'2026-11-09T12:00:00Z'})
    assert t.status_code == 200 and len(t.json()['points']) == 2
