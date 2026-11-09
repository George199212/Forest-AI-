"""Operational GPS layer for the Forest Map.

Only stored positions are shown: nothing is interpolated, and gaps longer than
session_track.TRACK_GAP_SECONDS stay gaps. Every position carries its origin:
  REAL       Telegram live location / bot session points (live_locations, session_track_points)
  SIMULATED  fleet_gps_demo integration records (integration_records)
  SANDBOX    John Deere sandbox telemetry (provider='john_deere')
  UNKNOWN    stored without provenance (vehicle_gps_pings without provider/source); hidden by default
Every point is checked server-side against registered sectors and the read-only national
compartment index (native EPSG:10306 geometry; pyproj for the WGS84 -> EPSG:10306 step).

Compartment alerts (FOREST_GPS_COMPARTMENT_ALERTS=1, default off) only ever use REAL points and
create incidents through the existing database.add_incident / add_risk_event / add_risk_evidence
pipeline; the AI recommendation then follows the existing risk_ai_worker flow.
"""
import json, os, sqlite3, threading, time
from contextlib import closing
from datetime import datetime, timedelta, timezone

import shapely
from pyproj import Transformer
from shapely.geometry import Point, Polygon
from shapely.ops import transform

import database
from services import session_track
from . import nationwide as nw

INSIDE_SECTOR = 'INSIDE_REGISTERED_SECTOR'
INSIDE_COMPARTMENT = 'INSIDE_UNREGISTERED_COMPARTMENT'
OUTSIDE_REGISTER = 'OUTSIDE_FOREST_REGISTER'
UNKNOWN = 'UNKNOWN'
RULE_CODE = 'WORK_OUTSIDE_REGISTERED_COMPARTMENT'

MAX_ACCURACY_M = float(os.environ.get('FOREST_GPS_MAX_ACCURACY_M', '100'))
STALE_MINUTES = int(os.environ.get('FOREST_GPS_STALE_MINUTES', '15'))
MAX_TRACK_POINTS = 5000
_TO_NATIVE = Transformer.from_crs(4326, 10306, always_xy=True).transform


def _env_int(name, default):
    try:return int(os.environ.get(name, default))
    except ValueError:return default


def _parse(ts):
    """Stored timestamps ('YYYY-MM-DD HH:MM:SS UTC', ISO with Z/offset or date) as aware UTC."""
    if not ts:return None
    text = str(ts).strip().replace(' UTC', '').replace('Z', '+00:00')
    for candidate in (text, text.replace(' ', 'T', 1)):
        try:
            value = datetime.fromisoformat(candidate)
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        except ValueError:continue
    return None


def _iso(dt):return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if dt else None


def _app():
    c = sqlite3.connect('file:'+os.path.abspath(database.DB_NAME)+'?mode=ro', uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def registered_sectors(organization_id):
    """(name, native EPSG:10306 polygon) for every valid stored sector boundary; data unchanged."""
    out = []
    with closing(_app()) as c:
        for row in c.execute('SELECT name,boundary_json FROM sectors WHERE organization_id=? AND boundary_json IS NOT NULL AND boundary_json<>""', (organization_id,)):
            try:
                g = Polygon([(p[1], p[0]) for p in json.loads(row['boundary_json'])])
                if g.is_valid and not g.is_empty:out.append((row['name'], transform(_TO_NATIVE, g)))
            except (ValueError, TypeError, IndexError, shapely.errors.GEOSException):continue
    return out


class Classifier:
    """Classifies points against sectors and the national index; one instance per request."""

    def __init__(self, sectors):
        self.sectors = sectors
        try:self.forest_db = nw.release()['forest_db'] if nw.configured() else None
        except Exception:self.forest_db = None
        self.conn = None
        self.cache = {}

    def close(self):
        if self.conn is not None:self.conn.close()

    def __call__(self, lat, lon, accuracy_m=None):
        key = (round(lat, 6), round(lon, 6), accuracy_m) if lat is not None and lon is not None else None
        if key in self.cache:return self.cache[key]
        result = self._classify(lat, lon, accuracy_m)
        if key is not None:self.cache[key] = result
        return result

    def _classify(self, lat, lon, accuracy_m):
        if lat is None or lon is None:return {'class':UNKNOWN, 'reason':'no_position'}
        if accuracy_m is not None and accuracy_m > MAX_ACCURACY_M:
            return {'class':UNKNOWN, 'reason':'accuracy_too_poor', 'accuracy_m':accuracy_m}
        x, y = _TO_NATIVE(lon, lat)
        radius = float(accuracy_m or 0)
        area = Point(x, y).buffer(radius) if radius > 0 else Point(x, y)
        crossing = False
        for name, g in self.sectors:
            if g.covers(area):return {'class':INSIDE_SECTOR, 'sector':name}
            if g.intersects(area):crossing = True
        if crossing:return {'class':UNKNOWN, 'reason':'accuracy_crosses_sector_boundary'}
        if not self.forest_db:return {'class':UNKNOWN, 'reason':'no_geodata'}
        if self.conn is None:self.conn = nw.db(self.forest_db)
        rows = self.conn.execute('SELECT c.id,c.external_id,c.kadastrs,c.kvart,c.nog,c.native_geometry FROM native_index r JOIN compartments c ON c.id=r.id '
                                 'WHERE r.min_x<=? AND r.max_x>=? AND r.min_y<=? AND r.max_y>=? LIMIT 200', (x+radius, x-radius, y+radius, y-radius)).fetchall()
        try:
            hits = [(row, g) for row in rows for g in [shapely.from_wkb(row['native_geometry'])] if g.intersects(area)]
            if not hits:return {'class':OUTSIDE_REGISTER}
            if not shapely.union_all([g for _, g in hits]).covers(area):
                return {'class':UNKNOWN, 'reason':'accuracy_crosses_register_boundary'}
            row = next((row for row, g in hits if g.covers(Point(x, y))), hits[0][0])
        except shapely.errors.GEOSException:
            return {'class':UNKNOWN, 'reason':'invalid_register_geometry'}
        return {'class':INSIDE_COMPARTMENT, 'compartment':{'id':row['external_id'], 'catalogue_id':row['id'], 'kadastrs':row['kadastrs'], 'kvart':row['kvart'], 'nog':row['nog']}}


def assigned_status(polygon, lat, lon, accuracy_m):
    """Position vs the entity's OWN assigned sector: INSIDE / OUTSIDE / UNKNOWN (accuracy radius crosses
    the boundary or is worse than MAX_ACCURACY_M), or None when that sector has no valid polygon."""
    if polygon is None or lat is None or lon is None:return None
    if accuracy_m is not None and accuracy_m > MAX_ACCURACY_M:return UNKNOWN
    x, y = _TO_NATIVE(lon, lat)
    area = Point(x, y).buffer(accuracy_m) if accuracy_m else Point(x, y)
    if polygon.covers(area):return 'INSIDE'
    return UNKNOWN if polygon.intersects(area) else 'OUTSIDE'


def _sandbox_origin():
    return 'REAL' if os.environ.get('JOHN_DEERE_ENV', 'sandbox').strip().lower() == 'production' else 'SANDBOX'


def _ping_origin(row):
    provider = (row['provider'] or '').strip().lower()
    if provider == 'john_deere':return _sandbox_origin()
    return 'UNKNOWN'   # bot pings are stored without provider/source; provenance cannot be proven


def _integration_mirrors(c):
    """Fleet integrations also copy each GPSPosition into vehicle_gps_pings without provenance
    (categories.FleetIntegrationAdapter). A ping with the same vehicle id and identical coordinates
    as a stored integration record is that record: it takes the integration's origin."""
    out = {}
    for r in c.execute("SELECT r.normalized_payload_json,i.is_demo FROM integration_records r JOIN integrations i ON i.id=r.integration_id WHERE r.entity_type='GPSPosition'"):
        try:p = json.loads(r['normalized_payload_json'])
        except (TypeError, ValueError):continue
        if p.get('latitude') is not None and p.get('longitude') is not None:
            out[(str(p.get('vehicle_id')), float(p['latitude']), float(p['longitude']))] = 'SIMULATED' if r['is_demo'] else 'REAL'
    return out


def _mirror_origin(mirrors, row):
    return mirrors.get((str(row['vehicle_id']), float(row['latitude']), float(row['longitude']))) if row['latitude'] is not None else None


def _machine_kind(vehicle_type):
    text = (vehicle_type or '').lower()
    return 'machine' if any(k in text for k in ('harvest', 'forward', 'excavat', 'ekskav', 'harvest', 'forvard')) else 'vehicle'


def _entity(kind, ref, name, sector, lat, lon, at, accuracy, origin, detail, classify, now, stale_minutes):
    t = _parse(at)
    age = (now-t).total_seconds() if t else None
    return {'type':kind, 'track_ref':ref, 'name':name, 'assigned_sector':sector, 'lat':lat, 'lon':lon,
            'recorded_at':_iso(t), 'age_s':round(age) if age is not None else None,
            'stale':age is None or age > stale_minutes*60, 'accuracy_m':accuracy, 'origin':origin,
            'detail':detail, 'spatial':classify(lat, lon, accuracy)}


def positions(organization_id, stale_minutes=STALE_MINUTES, now=None):
    now = now or datetime.now(timezone.utc)
    classify = Classifier(registered_sectors(organization_id))
    out = []
    try:
        with closing(_app()) as c:
            # Workers: Telegram live location (REAL); accuracy from the matching stored track point, if any.
            for r in c.execute('SELECT l.*,e.full_name FROM live_locations l LEFT JOIN sector_employees e ON e.id=l.employee_id'):
                acc = c.execute('SELECT horizontal_accuracy FROM session_track_points WHERE telegram_user_id=? AND latitude=? AND longitude=? ORDER BY id DESC LIMIT 1',
                                (r['telegram_user_id'], r['latitude'], r['longitude'])).fetchone()
                out.append(_entity('worker', {'kind':'worker', 'id':r['employee_id']}, r['full_name'] or ('#'+str(r['employee_id'])), r['sector'],
                                   r['latitude'], r['longitude'], r['updated_at'], acc[0] if acc else None, 'REAL',
                                   {'live_until':_iso(_parse(r['expires_at']))}, classify, now, stale_minutes))
            # Vehicles / equipment pings: newest per entity; origin from stored provenance only.
            # Pings that mirror an integration record are shown once, as that record (below).
            mirrors = _integration_mirrors(c)
            for r in c.execute('''SELECT p.*,v.plate,v.vehicle_type,q.equipment_code,q.type AS equipment_type FROM vehicle_gps_pings p
                    LEFT JOIN sector_vehicles v ON v.id=p.vehicle_id LEFT JOIN sector_equipment q ON q.id=p.equipment_id
                    WHERE p.id IN (SELECT max(id) FROM vehicle_gps_pings GROUP BY COALESCE(equipment_id,-1),COALESCE(vehicle_id,-1),COALESCE(entity_type,''))'''):
                if _mirror_origin(mirrors, r):continue
                equipment = r['equipment_id'] is not None
                kind = 'machine' if equipment else _machine_kind(r['vehicle_type'])
                name = r['equipment_code'] if equipment else (r['plate'] or ('#'+str(r['vehicle_id'])))
                out.append(_entity(kind, {'kind':'equipment' if equipment else 'vehicle', 'id':r['equipment_id'] if equipment else r['vehicle_id']}, name, r['sector'],
                                   r['latitude'], r['longitude'], r['recorded_at'], None, _ping_origin(r),
                                   {'vehicle_type':r['equipment_type'] if equipment else r['vehicle_type'], 'provider':r['provider']}, classify, now, stale_minutes))
            # John Deere machines with a reported location (SANDBOX unless the integration runs in production).
            pinged = {e['track_ref']['id'] for e in out if e['track_ref']['kind']=='equipment'}
            for r in c.execute("SELECT * FROM sector_equipment WHERE provider='john_deere' AND latitude IS NOT NULL AND longitude IS NOT NULL AND COALESCE(is_demo,0)=0"):
                if r['id'] in pinged:continue
                out.append(_entity('machine', {'kind':'equipment', 'id':r['id']}, r['machine_name'] or r['equipment_code'], r['sector'],
                                   r['latitude'], r['longitude'], r['location_timestamp'], None, _sandbox_origin(),
                                   {'vehicle_type':r['type'], 'provider':'john_deere'}, classify, now, stale_minutes))
            # SIMULATED fleet positions (fleet_gps_demo integration records): newest per vehicle.
            latest = {}
            for r in c.execute("SELECT id,normalized_payload_json FROM integration_records WHERE source_provider='fleet_gps_demo' AND entity_type='GPSPosition' ORDER BY id"):
                try:p = json.loads(r['normalized_payload_json'])
                except (TypeError, ValueError):continue
                latest[p.get('vehicle_id')] = p
            for vehicle, p in latest.items():
                out.append(_entity('vehicle', {'kind':'simulated', 'id':vehicle}, vehicle, p.get('sector'), p.get('latitude'), p.get('longitude'),
                                   p.get('source_timestamp'), None, 'SIMULATED', {'provider':'fleet_gps_demo'}, classify, now, stale_minutes))
    finally:classify.close()
    polygons = dict(classify.sectors)
    for e in out:e['assigned_status'] = assigned_status(polygons.get(e['assigned_sector']), e['lat'], e['lon'], e['accuracy_m'])
    return {'generated_at':_iso(now), 'stale_minutes':stale_minutes, 'max_accuracy_m':MAX_ACCURACY_M, 'entities':out}


def _points(c, kind, ident, start, end):
    if kind == 'worker':
        rows = c.execute('SELECT id,session_id,latitude,longitude,horizontal_accuracy,recorded_at FROM session_track_points WHERE employee_id=? ORDER BY recorded_at,id', (ident,)).fetchall()
        return [dict(r, origin='REAL', ref_table='session_track_points') for r in rows]
    if kind in ('vehicle', 'equipment'):
        column = 'equipment_id' if kind == 'equipment' else 'vehicle_id'
        rows = c.execute(f'SELECT id,vehicle_id,latitude,longitude,recorded_at,provider FROM vehicle_gps_pings WHERE {column}=? ORDER BY recorded_at,id', (ident,)).fetchall()
        mirrors = _integration_mirrors(c)
        return [dict(r, horizontal_accuracy=None, session_id=None, origin=_mirror_origin(mirrors, r) or _ping_origin(r), ref_table='vehicle_gps_pings') for r in rows]
    if kind == 'simulated':
        out = []
        for r in c.execute("SELECT id,normalized_payload_json FROM integration_records WHERE source_provider='fleet_gps_demo' AND entity_type='GPSPosition' ORDER BY id"):
            try:p = json.loads(r['normalized_payload_json'])
            except (TypeError, ValueError):continue
            if str(p.get('vehicle_id')) == str(ident):
                out.append({'id':r['id'], 'session_id':None, 'latitude':p.get('latitude'), 'longitude':p.get('longitude'), 'horizontal_accuracy':None,
                            'recorded_at':p.get('source_timestamp'), 'origin':'SIMULATED', 'ref_table':'integration_records'})
        return out
    raise ValueError('unknown track kind')


def track(organization_id, kind, ident, start, end):
    """Stored points of one entity in [start, end]; runs coloured by spatial class; gaps stay gaps."""
    if end <= start or end-start > timedelta(days=31):raise ValueError('invalid_window')
    classify = Classifier(registered_sectors(organization_id))
    try:
        with closing(_app()) as c:
            pts = [p for p in _points(c, kind, ident, start, end) if (t := _parse(p['recorded_at'])) and start <= t <= end and p['latitude'] is not None]
            truncated = len(pts) > MAX_TRACK_POINTS
            pts = pts[:MAX_TRACK_POINTS]
            sessions = sorted({p['session_id'] for p in pts if p['session_id']})
            photos = [dict(r) for r in c.execute('SELECT id,session_id,photo_type,image_path,uploaded_at FROM work_photos WHERE session_id IN (%s) ORDER BY uploaded_at' % ','.join('?'*len(sessions)), sessions)] if sessions else []
        for p in pts:
            p['t'] = _parse(p['recorded_at']);p['spatial'] = classify(p['latitude'], p['longitude'], p['horizontal_accuracy'])
    finally:classify.close()
    runs, transitions, gaps = [], [], []
    for i, p in enumerate(pts):
        coord = [p['latitude'], p['longitude']]
        if i == 0:runs.append({'class':p['spatial']['class'], 'coords':[coord]});continue
        a = pts[i-1];dt = (p['t']-a['t']).total_seconds()
        if dt > session_track.TRACK_GAP_SECONDS:
            gaps.append({'from':[a['latitude'], a['longitude']], 'to':coord, 'from_time':_iso(a['t']), 'to_time':_iso(p['t']), 'seconds':dt})
            runs.append({'class':p['spatial']['class'], 'coords':[coord]});continue
        if p['spatial']['class'] == runs[-1]['class']:runs[-1]['coords'].append(coord)
        else:
            transitions.append({'from':[a['latitude'], a['longitude']], 'to':coord, 'from_class':a['spatial']['class'], 'to_class':p['spatial']['class']})
            runs.append({'class':p['spatial']['class'], 'coords':[coord]})
    placed = []
    for ph in photos:
        t = _parse(ph['uploaded_at'])
        best = min(pts, key=lambda p:abs((p['t']-t).total_seconds())) if (pts and t) else None
        if best is None or abs((best['t']-t).total_seconds()) > session_track.PHOTO_MATCH_SECONDS:continue
        placed.append({'id':ph['id'], 'photo_type':ph['photo_type'], 'url':'/photos/file/'+os.path.basename(ph['image_path'] or ''),
                       'lat':best['latitude'], 'lon':best['longitude'], 'uploaded_at':_iso(t), 'match_seconds':abs((best['t']-t).total_seconds())})
    counts = {}
    for p in pts:counts[p['spatial']['class']] = counts.get(p['spatial']['class'], 0)+1
    marker = lambda p:{'lat':p['latitude'], 'lon':p['longitude'], 'time':_iso(p['t'])} if p else None
    return {'kind':kind, 'id':ident, 'window':{'start':_iso(start), 'end':_iso(end)}, 'origins':sorted({p['origin'] for p in pts}),
            'points':[{'lat':p['latitude'], 'lon':p['longitude'], 'time':_iso(p['t']), 'accuracy_m':p['horizontal_accuracy'], 'origin':p['origin'], 'spatial':p['spatial']} for p in pts],
            'runs':runs, 'transitions':transitions, 'gaps':gaps, 'gap_seconds':session_track.TRACK_GAP_SECONDS, 'start':marker(pts[0] if pts else None),
            'end':marker(pts[-1] if len(pts) > 1 else None), 'photos':placed, 'photo_match_seconds':session_track.PHOTO_MATCH_SECONDS,
            'class_counts':counts, 'truncated':truncated}


# ── Compartment alerts (flag-gated; REAL points only) ───────────────────────────────────────

def alerts_enabled():
    return os.environ.get('FOREST_GPS_COMPARTMENT_ALERTS', '').strip() == '1'


def _open_incident(conn, entity_id, catalogue_id):
    row = conn.execute('''SELECT r.id FROM risks r JOIN risk_evidence e ON e.risk_id=r.id WHERE r.rule_code=? AND r.entity_type='worker'
        AND r.entity_id=? AND r.status IN ('OPEN','NOTIFIED') AND e.evidence_type='COMPARTMENT' AND e.ref_table='vmd_compartments' AND e.ref_id=?
        ORDER BY r.id DESC LIMIT 1''', (RULE_CODE, entity_id, catalogue_id)).fetchone()
    return row[0] if row else None


def evaluate_alerts(organization_id=1, now=None, lookback_minutes=None):
    """Raise WORK_OUTSIDE_REGISTERED_COMPARTMENT for REAL worker points; returns new incident ids."""
    if not alerts_enabled():return []
    now = now or datetime.now(timezone.utc)
    min_points = _env_int('FOREST_GPS_ALERT_MIN_POINTS', 3)
    min_minutes = _env_int('FOREST_GPS_ALERT_MIN_MINUTES', 5)
    lookback = lookback_minutes or _env_int('FOREST_GPS_ALERT_LOOKBACK_MINUTES', 180)
    classify = Classifier(registered_sectors(organization_id))
    created = []
    try:
        with closing(_app()) as c:
            rows = [dict(r) for r in c.execute('''SELECT p.id,p.session_id,p.employee_id,p.latitude,p.longitude,p.horizontal_accuracy,p.recorded_at,
                    w.sector,COALESCE(e.full_name,w.employee) AS name FROM session_track_points p JOIN work_sessions w ON w.id=p.session_id
                    LEFT JOIN sector_employees e ON e.id=p.employee_id ORDER BY p.session_id,p.recorded_at,p.id''')]
        rows = [r for r in rows if (t := _parse(r['recorded_at'])) and now-timedelta(minutes=lookback) <= t <= now]
        runs, current = [], None
        for r in rows:
            r['t'] = _parse(r['recorded_at']);s = classify(r['latitude'], r['longitude'], r['horizontal_accuracy'])
            key = (r['session_id'], s['compartment']['catalogue_id']) if s['class'] == INSIDE_COMPARTMENT else None
            continues = current and key and current['key'] == key and (r['t']-current['points'][-1]['t']).total_seconds() <= session_track.TRACK_GAP_SECONDS
            if continues:current['points'].append(r)
            else:
                current = {'key':key, 'compartment':s.get('compartment'), 'points':[r]} if key else None
                if current:runs.append(current)
        for run in runs:
            first, last = run['points'][0], run['points'][-1]
            minutes = (last['t']-first['t']).total_seconds()/60
            if len(run['points']) < min_points or minutes < min_minutes or first['employee_id'] is None:continue
            created += _raise(run, first, last, minutes)
    finally:classify.close()
    return created


def _raise(run, first, last, minutes):
    comp = run['compartment'];sector = first['sector'];entity = int(first['employee_id'])
    label = f"{comp['kadastrs']} K{comp['kvart']} N{comp['nog']}"
    with closing(sqlite3.connect(database.DB_NAME)) as conn:existing = _open_incident(conn, entity, comp['catalogue_id'])
    evidence = [('vmd_register', 'COMPARTMENT', f"{label} · {comp['id']}", 'vmd_compartments', comp['catalogue_id'], None),
                ('telegram_live_location', 'GPS_FIRST_POINT', f"{first['latitude']:.6f}, {first['longitude']:.6f}", 'session_track_points', first['id'], first['recorded_at']),
                ('telegram_live_location', 'GPS_LAST_POINT', f"{last['latitude']:.6f}, {last['longitude']:.6f} · {len(run['points'])} points · {minutes:.1f} min", 'session_track_points', last['id'], last['recorded_at']),
                ('telegram_live_location', 'TRACK', f"/api/sessions/{first['session_id']}/track", 'work_sessions', first['session_id'], None)]
    if existing:
        for source, kind, summary, table, ref, observed in evidence[2:3]:database.add_risk_evidence(existing, source, 'REAL', kind, summary, table, ref, observed)
        return []
    reason = (f"{first['name'] or 'Worker'} (assigned to {sector}) recorded {len(run['points'])} GPS points over {minutes:.0f} min "
              f"inside VMD compartment {label}, which is not a registered sector.")
    incident = database.add_incident(sector=sector, risk_level='MEDIUM', reason=reason, entity_type='worker', entity_id=entity,
                                     rule_code=RULE_CODE, duration_min=round(minutes, 1), data_origin='REAL', occurred_at=first['recorded_at'])
    database.add_risk_event(incident, 'DETECTED', actor='gps_compartment_check', details=json.dumps(
        {'compartment':comp, 'first_point':first['recorded_at'], 'last_point':last['recorded_at'], 'points':len(run['points']),
         'duration_min':round(minutes, 1), 'session_id':first['session_id']}, ensure_ascii=False))
    for source, kind, summary, table, ref, observed in evidence:database.add_risk_evidence(incident, source, 'REAL', kind, summary, table, ref, observed)
    return [incident]


_alert_thread = None


def start_alert_loop():
    """Background evaluation every FOREST_GPS_ALERT_INTERVAL_SECONDS (default 60); only when the flag is on."""
    global _alert_thread
    if not alerts_enabled() or _alert_thread is not None:return False
    interval = max(15, _env_int('FOREST_GPS_ALERT_INTERVAL_SECONDS', 60))
    def loop():
        while True:
            try:evaluate_alerts()
            except Exception:
                import logging;logging.getLogger(__name__).exception('GPS compartment alert evaluation failed')
            time.sleep(interval)
    _alert_thread = threading.Thread(target=loop, name='gps-compartment-alerts', daemon=True);_alert_thread.start()
    return True
