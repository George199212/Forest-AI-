"""Presence outside the assigned sector: segment detection, Map-tab equality, accuracy ambiguity,
compartments entered, incident button (dedup + evidence) and the marker's assigned status.

Temporary databases only. Geometry is built in EPSG:10306 metres and converted with pyproj.
Optional: FOREST_TEST_PROD_COPY=/tmp/... (a COPY of the production DB) runs the session #32 check.
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from pyproj import Transformer
from shapely.geometry import box

import database
from services import session_track
from services.geodata import gps_map as gps, gps_violations as gv

TO_WGS = Transformer.from_crs(10306, 4326, always_xy=True).transform
TO_NATIVE = Transformer.from_crs(4326, 10306, always_xy=True).transform
X0, Y0 = TO_NATIVE(24.5, 57.0)
T0 = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)
SECTOR = box(X0-600, Y0-100, X0-400, Y0+100)     # east edge at X0-400


def wgs(x, y):
    lon, lat = TO_WGS(x, y);return lat, lon


def ts(dt):return dt.strftime('%Y-%m-%d %H:%M:%S UTC')


@pytest.fixture
def world(tmp_path, monkeypatch):
    app = tmp_path/'app.db';forest = tmp_path/'forest.sqlite'
    monkeypatch.setattr(database, 'DB_NAME', str(app));database.init_db()
    ring = [list(wgs(x, y)) for x, y in SECTOR.exterior.coords]
    with sqlite3.connect(app) as c:
        c.execute("INSERT INTO sectors(name,boundary_json,organization_id,data_origin) VALUES('S-1',?,1,'REAL')", (json.dumps(ring),))
        c.execute("INSERT INTO sector_employees(id,sector,full_name,telegram_user_id) VALUES(7,'S-1','Worker One','700')")
        c.execute("INSERT INTO work_sessions(id,user_id,employee,sector,check_in_time,employee_id) VALUES(70,'700','Worker One','S-1',?,7)", (ts(T0),))
    with sqlite3.connect(forest) as c:
        c.executescript('CREATE TABLE compartments(id INTEGER PRIMARY KEY,external_id TEXT,kadastrs TEXT,kvart TEXT,nog TEXT,native_geometry BLOB);'
                        'CREATE VIRTUAL TABLE native_index USING rtree(id,min_x,max_x,min_y,max_y);')
        g = box(X0+400, Y0-100, X0+600, Y0+100)
        c.execute('INSERT INTO compartments VALUES(1,?,?,?,?,?)', ('VMD:test:1', '12340010001', '5', '1', g.wkb))
        c.execute('INSERT INTO native_index VALUES(1,?,?,?,?)', (*g.bounds[0::2], *g.bounds[1::2]))
    monkeypatch.setattr(gps.nw, 'configured', lambda:True)
    monkeypatch.setattr(gps.nw, 'release', lambda:{'forest_db':str(forest), 'version':'test'})
    return app


def add_points(app, track, session=70):
    """track: [(seconds from T0, dx metres from X0, accuracy)]. The inside flag is computed exactly as the
    bot stores it (services.geo.point_in_polygon on the sector ring)."""
    with sqlite3.connect(app) as c:
        row = c.execute("SELECT boundary_json,center_lat,center_lon FROM sectors WHERE name='S-1'").fetchone()
    inside = session_track._inside_test({'boundary_json':row[0], 'center_lat':row[1], 'center_lon':row[2]})
    ids = []
    with sqlite3.connect(app) as c:
        for sec, dx, acc in track:
            lat, lon = wgs(X0+dx, Y0)
            cur = c.execute('INSERT INTO session_track_points(session_id,employee_id,telegram_user_id,live_message_id,sector,latitude,longitude,'
                            'horizontal_accuracy,inside_boundary,recorded_at,received_at) VALUES(?,7,"700",1,"S-1",?,?,?,?,?,?)',
                            (session, lat, lon, acc, 1 if inside(lat, lon) else 0, ts(T0+timedelta(seconds=sec)), ts(T0+timedelta(seconds=sec))))
            ids.append(cur.lastrowid)
    return ids


def run():return gv.violations(1, 'worker', 7, '70')


def assert_equals_map_tab(r):
    tab = session_track.build_track(70)['summary']
    assert r['summary']['inside_s'] == tab['inside_s']
    assert r['summary']['outside_s'] == tab['outside_s']
    assert sum(s['outside_s'] for s in r['segments']) == pytest.approx(tab['outside_s'], abs=1e-6)
    assert r['summary']['matches_map_tab'] is True


# ── Segment detection ────────────────────────────────────────────────────────

def test_exit_and_reentry(world):
    ids = add_points(world, [(0, -500, 3), (30, -450, 3), (60, -300, 3), (90, -250, 3), (120, -320, 3), (150, -450, 3), (180, -500, 3)])
    r = run();assert_equals_map_tab(r)
    assert r['summary']['exits'] == 1 and r['summary']['violations'] == 1 and r['summary']['unknown'] == 0
    (seg,) = r['segments']
    assert seg['status'] == gv.VIOLATION and seg['points'] == 3 and seg['exit_point_id'] == ids[2]
    assert seg['exit']['last_inside_point_id'] == ids[1] and seg['exit']['known']
    assert seg['reentry']['point_id'] == ids[5] and seg['reentry']['known']
    assert seg['max_distance_m'] == pytest.approx(150, abs=1)   # X0-250 is 150 m east of the edge
    assert seg['median_accuracy_m'] == 3
    # crossing estimate lies inside the interval that changes side
    assert seg['exit']['between'][0] < seg['exit']['estimated_crossing'] < seg['exit']['between'][1]
    assert seg['incidents'] == [] and r['last']['inside'] is True


def test_two_exits(world):
    add_points(world, [(0, -500, 3), (30, -300, 3), (60, -500, 3), (90, -300, 3), (120, -500, 3)])
    r = run();assert_equals_map_tab(r)
    assert r['summary']['exits'] == 2 and len(r['segments']) == 2


def test_gap_inside_outside_segment_is_not_counted(world):
    add_points(world, [(0, -500, 3), (30, -300, 3), (330, -280, 3), (360, -500, 3)])
    r = run();assert_equals_map_tab(r)
    (seg,) = r['segments']
    assert seg['gap_s'] == 300 and len(seg['lines']) == 2          # no line drawn across the gap
    assert seg['outside_s'] < 60                                      # only the two crossing parts


def test_exit_across_gap_has_unknown_time(world):
    add_points(world, [(0, -500, 3), (300, -300, 3), (330, -300, 3), (360, -500, 3)])
    r = run();assert_equals_map_tab(r)
    seg = r['segments'][0]
    assert seg['exit']['known'] is False and 'estimated_crossing' not in seg['exit']
    assert seg['exit']['between'] == [ts(T0), ts(T0+timedelta(seconds=300))]


def test_started_and_ended_outside(world):
    add_points(world, [(0, -300, 3), (30, -500, 3), (60, -300, 3)])
    r = run();assert_equals_map_tab(r)
    first, last = r['segments']
    assert first['started_outside'] and first['exit'] is None
    assert last['ended_outside'] and last['reentry'] is None
    assert r['summary']['exits'] == 1 and r['summary']['started_outside'] is True
    assert r['last']['inside'] is False


# ── Accuracy ambiguity ───────────────────────────────────────────────────────

def test_within_accuracy_is_unknown_not_violation(world):
    add_points(world, [(0, -500, 3), (30, -395, 10), (60, -397, 10), (90, -500, 3)])   # 5 m / 3 m outside, ± 10 m
    r = run()
    (seg,) = r['segments']
    assert seg['status'] == gv.UNKNOWN and seg['unknown_reason'] == 'within_accuracy'
    assert r['summary']['violations'] == 0 and r['summary']['unknown'] == 1


def test_missing_accuracy_counts_as_worst_accepted(world):
    add_points(world, [(0, -500, 3), (30, -350, None), (60, -500, 3)])       # 50 m out, no accuracy
    assert run()['segments'][0]['status'] == gv.UNKNOWN
    with sqlite3.connect(world) as c:c.execute('DELETE FROM session_track_points')
    add_points(world, [(0, -500, 3), (30, -250, None), (60, -500, 3)])       # 150 m out > 100 m
    seg = run()['segments'][0]
    assert seg['status'] == gv.VIOLATION and seg['accuracy_missing_points'] == 1 and seg['median_accuracy_m'] is None


def test_accuracy_too_poor_is_unknown(world):
    add_points(world, [(0, -500, 3), (30, 0, 150), (60, -500, 3)])
    seg = run()['segments'][0]
    assert seg['status'] == gv.UNKNOWN and seg['unknown_reason'] == 'accuracy_too_poor'


# ── Compartments entered ─────────────────────────────────────────────────────

def test_compartments_entered(world):
    add_points(world, [(0, -500, 3), (30, 500, 3), (60, 2000, 3), (90, -500, 3)])
    comps = run()['segments'][0]['compartments']
    assert {'kind':'compartment', 'kadastrs':'12340010001', 'kvart':'5', 'nog':'1', 'id':'VMD:test:1', 'catalogue_id':1, 'points':1} in comps
    assert {'kind':'outside_register', 'points':1} in comps


# ── Incident button ──────────────────────────────────────────────────────────

def evidence(app, risk):
    with sqlite3.connect(app) as c:
        return {r[0]:r for r in c.execute('SELECT evidence_type,summary,ref_table,ref_id,data_origin FROM risk_evidence WHERE risk_id=?', (risk,))}


def test_create_incident_dedup_and_evidence(world):
    ids = add_points(world, [(0, -500, 3), (30, -300, 3), (60, -250, 3), (90, -500, 3)])
    res = gv.create_incident(1, 70, ids[1], 'alice')
    assert res['result'] == 'created'
    with sqlite3.connect(world) as c:
        c.row_factory = sqlite3.Row
        risk = c.execute('SELECT * FROM risks WHERE id=?', (res['incident_id'],)).fetchone()
        events = c.execute('SELECT event_type,actor,details FROM risk_events WHERE risk_id=?', (res['incident_id'],)).fetchall()
    assert (risk['rule_code'], risk['entity_type'], risk['entity_id'], risk['session_id'], risk['status'], risk['data_origin']) == ('SECTOR_EXIT', 'EMPLOYEE', 7, 70, 'OPEN', 'REAL')
    assert risk['occurred_at'] == ts(T0+timedelta(seconds=30)) and risk['distance_m'] == pytest.approx(150, abs=1)
    assert [(e['event_type'], e['actor']) for e in events] == [('CREATED_FROM_RECORD', 'alice')]
    details = json.loads(events[0]['details'])
    assert details['points'] == 2 and details['exit_point_id'] == ids[1]
    ev = evidence(world, res['incident_id'])
    assert set(ev) == {'GPS_EXIT_POINT', 'GPS_REENTRY_POINT', 'OUTSIDE_SEGMENT', 'COMPARTMENTS_ENTERED', 'TRACK'}
    assert ev['GPS_EXIT_POINT'][2:4] == ('session_track_points', ids[1]) and ev['GPS_REENTRY_POINT'][3] == ids[3]
    assert 'max 150' in ev['OUTSIDE_SEGMENT'][1] and '2 points' in ev['OUTSIDE_SEGMENT'][1]
    assert '#forest-map/session-70' in ev['TRACK'][1] and all(e[4] == 'REAL' for e in ev.values())
    # second press: same incident, nothing new
    assert gv.create_incident(1, 70, ids[1], 'bob') == {'result':'existing', 'incident_id':res['incident_id']}
    with sqlite3.connect(world) as c:assert c.execute('SELECT COUNT(*) FROM risks').fetchone()[0] == 1
    seg = run()['segments'][0]
    assert [i['id'] for i in seg['incidents']] == [res['incident_id']]


def test_second_exit_attaches_to_open_session_incident(world):
    ids = add_points(world, [(0, -500, 3), (30, -300, 3), (60, -500, 3), (90, -300, 3), (120, -500, 3)])
    first = gv.create_incident(1, 70, ids[1], 'alice')
    second = gv.create_incident(1, 70, ids[3], 'alice')
    assert second == {'result':'attached', 'incident_id':first['incident_id']}
    with sqlite3.connect(world) as c:
        assert c.execute('SELECT COUNT(*) FROM risks').fetchone()[0] == 1
        assert c.execute("SELECT actor FROM risk_events WHERE event_type='STILL_OUTSIDE'").fetchone()[0] == 'alice'
    assert all([i['id'] for i in s['incidents']] == [first['incident_id']] for s in run()['segments'])


def test_existing_bot_incident_is_matched_not_duplicated(world):
    ids = add_points(world, [(0, -500, 3), (30, -300, 3), (60, -500, 3)])
    bot = database.add_incident('S-1', 'HIGH', 'Worker One left sector boundary', entity_type='EMPLOYEE', entity_id=7, rule_code='SECTOR_EXIT', occurred_at=ts(T0+timedelta(seconds=30)))
    with sqlite3.connect(world) as c:c.execute('UPDATE risks SET session_id=70 WHERE id=?', (bot,))
    assert [i['id'] for i in run()['segments'][0]['incidents']] == [bot]
    assert gv.create_incident(1, 70, ids[1], 'alice') == {'result':'existing', 'incident_id':bot}


def test_unknown_segment_cannot_create_incident(world):
    ids = add_points(world, [(0, -500, 3), (30, -397, 10), (60, -500, 3)])
    with pytest.raises(PermissionError):gv.create_incident(1, 70, ids[1], 'alice')
    with pytest.raises(LookupError):gv.create_incident(1, 70, ids[0], 'alice')     # not an exit point
    with sqlite3.connect(world) as c:assert c.execute('SELECT COUNT(*) FROM risks').fetchone()[0] == 0


def test_sessions_picker(world):
    add_points(world, [(0, -500, 3), (30, -300, 3)])
    (row,) = gv.sessions('worker', 7)['sessions']
    assert (row['session_id'], row['sector'], row['points'], row['open']) == (70, 'S-1', 2, True)


# ── Marker: current position vs the assigned sector ──────────────────────────

def test_assigned_status(world):
    poly = gps.registered_sectors(1)[0][1]
    assert gps.assigned_status(poly, *wgs(X0-500, Y0), 5) == 'INSIDE'
    assert gps.assigned_status(poly, *wgs(X0-300, Y0), 5) == 'OUTSIDE'
    assert gps.assigned_status(poly, *wgs(X0-395, Y0), 10) == gps.UNKNOWN
    assert gps.assigned_status(poly, *wgs(X0-300, Y0), 500) == gps.UNKNOWN
    assert gps.assigned_status(None, *wgs(X0-300, Y0), 5) is None


# ── Real data (optional; COPY of production DB) ──────────────────────────────

@pytest.mark.skipif(not os.environ.get('FOREST_TEST_PROD_COPY'), reason='FOREST_TEST_PROD_COPY not set')
def test_session_32_equals_sector_map_tab(monkeypatch):
    monkeypatch.setattr(database, 'DB_NAME', os.environ['FOREST_TEST_PROD_COPY'])
    r = gv.violations(1, 'worker', 2, '32');tab = session_track.build_track(32)['summary']
    assert (r['summary']['inside_s'], r['summary']['outside_s']) == (tab['inside_s'], tab['outside_s'])
    assert round(tab['inside_s']) == 660 and round(tab['outside_s']) == 201      # 11 min 0 s / 3 min 21 s
    assert r['summary']['exits'] == 1 and r['summary']['violations'] == 1 and r['summary']['matches_map_tab']
    assert [i['id'] for i in r['segments'][0]['incidents']] == [62]
