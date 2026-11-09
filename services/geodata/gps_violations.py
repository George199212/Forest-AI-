"""Presence outside the assigned cutting zone (registered sector) on the Forest Map.

Evidence only, no automatic alerts:
  raw evidence     stored track points (session_track_points / vehicle_gps_pings), unchanged
  processed data   outside segments, distances, compartments, durations (computed here, not stored)
  human decision   an incident is created only by a dashboard user pressing a button
                   (create_incident), through the existing database.add_incident pipeline

Worker sessions use exactly the sector Map tab's inputs and rules (services.session_track):
the inside/outside flag stored with each point by the bot, the straight-line boundary crossing
for the one interval that changes side, and TRACK_GAP_SECONDS for gaps (gap time is neither
inside nor outside). So time inside / outside equals the Map tab. Vehicles have no work
sessions and no stored flag: their "sessions" are local days of stored pings and the flag is
computed against the current sector polygon.

Accuracy: a segment is a VIOLATION only if at least one of its points lies farther from the
sector polygon than its accuracy radius (a missing accuracy counts as the worst accepted
accuracy, FOREST_GPS_MAX_ACCURACY_M). Otherwise it is UNKNOWN: it can be GPS noise.
"""
import json, sqlite3, statistics, threading
from contextlib import closing
from datetime import datetime, timedelta, timezone

import shapely
from shapely.geometry import Point, Polygon
from shapely.ops import transform

import database
from services import session_track
from . import gps_map as gps

EXIT_RULES = ('SECTOR_EXIT', 'WORK_OUTSIDE_REGISTERED_COMPARTMENT')
INCIDENT_RULE = 'SECTOR_EXIT'          # same rule the bot raises for a worker leaving the sector
MATCH_SECONDS = session_track.EXIT_MATCH_SECONDS
VIOLATION = 'VIOLATION'
UNKNOWN = 'UNKNOWN'
_create_lock = threading.Lock()


def _ts(dt):
    return dt.astimezone(timezone.utc).strftime(session_track.TS_FMT) if dt else None


def _local(dt):
    return dt.astimezone(session_track.LOCAL_TZ).strftime('%d.%m.%Y %H:%M:%S') if dt else None


def _sector(conn, name):
    row = conn.execute('SELECT name,boundary_json,center_lat,center_lon FROM sectors WHERE name=?', (name,)).fetchone()
    native = None
    if row and row['boundary_json']:
        try:
            g = Polygon([(p[1], p[0]) for p in json.loads(row['boundary_json'])])
            if g.is_valid and not g.is_empty:native = transform(gps._TO_NATIVE, g)
        except (ValueError, TypeError, IndexError, shapely.errors.GEOSException):native = None
    return row, native


# ── Pure segment detection (unit-tested) ──────────────────────────────────────────────────────

def detect_segments(points, inside_fn, distance_fn, gap_seconds=session_track.TRACK_GAP_SECONDS,
                    max_accuracy_m=gps.MAX_ACCURACY_M):
    """points: ordered dicts {id, latitude, longitude, accuracy, t (aware), inside (bool)}.
    Returns one dict per maximal run of outside points. Time attribution is the Map tab's:
    out-out intervals count fully, the interval that changes side is split at the straight-line
    crossing, intervals longer than gap_seconds count as gap (no positions), never as outside."""
    segments, i, n = [], 0, len(points)
    while i < n:
        if points[i]['inside']:
            i += 1;continue
        j = i
        while j+1 < n and not points[j+1]['inside']:j += 1
        run, prev, nxt = points[i:j+1], points[i-1] if i > 0 else None, points[j+1] if j+1 < n else None
        outside_s = gap_s = 0.0
        lines, line = [], []
        exit_info = reentry = None
        if prev is not None:
            dt = (run[0]['t']-prev['t']).total_seconds()
            if dt > gap_seconds:
                gap_s += dt
                exit_info = {'known':False, 'between':[_ts(prev['t']), _ts(run[0]['t'])]}
            else:
                f = session_track._crossing(prev, run[0], True, inside_fn)
                outside_s += dt*(1-f)
                cross = [prev['latitude']+(run[0]['latitude']-prev['latitude'])*f, prev['longitude']+(run[0]['longitude']-prev['longitude'])*f]
                line.append(cross)
                exit_info = {'known':True, 'estimated_crossing':_ts(prev['t']+timedelta(seconds=dt*f)), 'between':[_ts(prev['t']), _ts(run[0]['t'])]}
            exit_info.update(last_inside_point_id=prev['id'], last_inside_time=_ts(prev['t']))
        for a, b in zip(run, run[1:]):
            line.append([a['latitude'], a['longitude']])
            dt = (b['t']-a['t']).total_seconds()
            if dt > gap_seconds:
                gap_s += dt;lines.append(line);line = []
            else:outside_s += dt
        line.append([run[-1]['latitude'], run[-1]['longitude']])
        if nxt is not None:
            dt = (nxt['t']-run[-1]['t']).total_seconds()
            if dt > gap_seconds:
                gap_s += dt
                reentry = {'known':False, 'between':[_ts(run[-1]['t']), _ts(nxt['t'])]}
            else:
                f = session_track._crossing(run[-1], nxt, False, inside_fn)
                outside_s += dt*f
                line.append([run[-1]['latitude']+(nxt['latitude']-run[-1]['latitude'])*f, run[-1]['longitude']+(nxt['longitude']-run[-1]['longitude'])*f])
                reentry = {'known':True, 'estimated_crossing':_ts(run[-1]['t']+timedelta(seconds=dt*f)), 'between':[_ts(run[-1]['t']), _ts(nxt['t'])]}
            reentry.update(point_id=nxt['id'], time=_ts(nxt['t']), lat=nxt['latitude'], lon=nxt['longitude'])
        lines.append(line)
        dists = [distance_fn(p['latitude'], p['longitude']) for p in run]
        accs = [p['accuracy'] for p in run if p['accuracy'] is not None]
        confirmed = [k for k, (p, d) in enumerate(zip(run, dists)) if d is not None and
                     (p['accuracy'] if p['accuracy'] is not None else max_accuracy_m) <= max_accuracy_m and
                     d > (p['accuracy'] if p['accuracy'] is not None else max_accuracy_m)]
        if confirmed:status, reason = VIOLATION, None
        elif any(d is None for d in dists):status, reason = UNKNOWN, 'no_sector_polygon'
        elif accs and all(a > max_accuracy_m for a in accs) and len(accs) == len(run):status, reason = UNKNOWN, 'accuracy_too_poor'
        else:status, reason = UNKNOWN, 'within_accuracy'
        known = [d for d in dists if d is not None]
        segments.append({
            'index':len(segments), 'status':status, 'unknown_reason':reason,
            'started_outside':prev is None, 'ended_outside':nxt is None,
            'exit_point_id':run[0]['id'], 'start':_ts(run[0]['t']), 'end':_ts(run[-1]['t']),
            'start_local':_local(run[0]['t']), 'end_local':_local(run[-1]['t']),
            'exit':exit_info, 'reentry':reentry,
            'exit_marker':{'lat':run[0]['latitude'], 'lon':run[0]['longitude'], 'time':_ts(run[0]['t'])},
            'outside_s':outside_s, 'gap_s':gap_s, 'points':len(run), 'point_ids':[p['id'] for p in run],
            'max_distance_m':max(known) if known else None,
            'confirmed_points':len(confirmed),
            'median_accuracy_m':statistics.median(accs) if accs else None,
            'accuracy_missing_points':len(run)-len(accs),
            'lines':[l for l in lines if l],
        })
        i = j+1
    return segments


# ── Loading ──────────────────────────────────────────────────────────────────────────────────

def _distance_fn(native):
    if native is None:return lambda lat, lon:None
    return lambda lat, lon:native.distance(Point(*gps._TO_NATIVE(lon, lat)))


def sessions(kind, ident):
    """Session picker rows. Workers: work_sessions (newest first). Vehicles: local days with pings."""
    with closing(gps._app()) as c:
        if kind == 'worker':
            rows = c.execute('SELECT w.*, (SELECT COUNT(*) FROM session_track_points p WHERE p.session_id=w.id) AS n '
                             'FROM work_sessions w WHERE w.employee_id=? ORDER BY w.check_in_time DESC, w.id DESC', (ident,)).fetchall()
            return {'kind':kind, 'id':ident, 'sessions':[{'key':str(r['id']), 'session_id':r['id'], 'sector':r['sector'], 'points':r['n'],
                    'check_in_local':session_track._local(r['check_in_time']), 'finish_local':session_track._local(r['finish_time']),
                    'open':not r['finish_time']} for r in rows]}
        pts = gps._points(c, kind, ident, None, None)
    days = {}
    for p in pts:
        t = gps._parse(p['recorded_at'])
        if t is None or p['latitude'] is None:continue
        day = t.astimezone(session_track.LOCAL_TZ).date().isoformat()
        days[day] = days.get(day, 0)+1
    return {'kind':kind, 'id':ident, 'sessions':[{'key':d, 'session_id':None, 'sector':None, 'points':n, 'check_in_local':d, 'finish_local':None, 'open':False}
                                                 for d, n in sorted(days.items(), reverse=True)]}


def _incidents(c, session_id):
    rows = [dict(r) for r in c.execute(
        f"SELECT id,rule_code,status,risk_level,occurred_at,created_at,entity_type,entity_id FROM risks WHERE rule_code IN ({','.join('?'*len(EXIT_RULES))}) "
        "AND (session_id=? OR id IN (SELECT risk_id FROM risk_evidence WHERE ref_table='work_sessions' AND ref_id=?)) ORDER BY id",
        (*EXIT_RULES, session_id, session_id))]
    for r in rows:
        r['exit_point_ids'] = [e[0] for e in c.execute(
            "SELECT ref_id FROM risk_evidence WHERE risk_id=? AND ref_table='session_track_points' AND evidence_type='GPS_EXIT_POINT'", (r['id'],))]
    return rows


def _match(segments, incidents):
    """Link incidents to exits: an explicit GPS_EXIT_POINT evidence wins; otherwise the incident time
    (occurred_at, else created_at) must fall between the last inside point - MATCH_SECONDS and the
    re-entry (or last outside point + MATCH_SECONDS)."""
    used = set()
    for seg in segments:
        seg['incidents'] = []
    for inc in incidents:
        hits = [s for s in segments if s['exit_point_id'] in inc['exit_point_ids']]   # one incident may hold several exits
        for s in hits:s['incidents'].append(inc)
        if hits:
            used.add(inc['id']);continue
        hit, t = None, gps._parse(inc['occurred_at'] or inc['created_at'])
        for s in segments:
            lo = gps._parse((s['exit'] or {}).get('last_inside_time') or s['start'])-timedelta(seconds=MATCH_SECONDS)
            hi = gps._parse((s['reentry'] or {}).get('time') or s['end'])+timedelta(seconds=MATCH_SECONDS if not s['reentry'] else 0)
            if t and lo <= t <= hi:hit = s;break
        if hit is not None:
            hit['incidents'].append(inc);used.add(inc['id'])
    return [i for i in incidents if i['id'] not in used]


def _compartments(organization_id, assigned, segments, pts_by_id):
    """Compartments entered per segment: other registered sectors and the national VMD index (point only)."""
    others = [(name, g) for name, g in gps.registered_sectors(organization_id) if name != assigned]
    register = gps.Classifier([])
    try:
        for seg in segments:
            seen, out = {}, []
            for pid in seg['point_ids']:
                p = pts_by_id[pid]
                x, y = gps._TO_NATIVE(p['longitude'], p['latitude'])
                other = next((name for name, g in others if g.covers(Point(x, y))), None)
                r = register(p['latitude'], p['longitude'], None)
                if r['class'] == gps.INSIDE_COMPARTMENT:
                    c = r['compartment'];key = ('vmd', c['catalogue_id'])
                    item = {'kind':'compartment', 'kadastrs':c['kadastrs'], 'kvart':c['kvart'], 'nog':c['nog'], 'id':c['id'], 'catalogue_id':c['catalogue_id']}
                elif r['class'] == gps.OUTSIDE_REGISTER:key, item = ('none',), {'kind':'outside_register'}
                else:key, item = ('unknown', r.get('reason')), {'kind':'unknown', 'reason':r.get('reason')}
                if other:item['registered_sector'] = other;key = key+(other,)
                if key not in seen:
                    seen[key] = dict(item, points=0);out.append(seen[key])
                seen[key]['points'] += 1
                p['register'] = item
            seg['compartments'] = out
    finally:register.close()


def violations(organization_id, kind, ident, session_key):
    with closing(gps._app()) as c:
        if kind == 'worker':
            s = c.execute('SELECT * FROM work_sessions WHERE id=? AND employee_id=?', (int(session_key), ident)).fetchone()
            if s is None:raise LookupError('session_not_found')
            sector_row, native = _sector(c, s['sector'])
            pts = [dict(r) for r in c.execute('SELECT id,latitude,longitude,horizontal_accuracy AS accuracy,inside_boundary,recorded_at '
                                                'FROM session_track_points WHERE session_id=? ORDER BY recorded_at,id', (s['id'],))]
            for p in pts:p['inside'] = bool(p['inside_boundary']);p['t'] = gps._parse(p['recorded_at'])
            incidents = _incidents(c, s['id'])
            assigned, origin = s['sector'], 'REAL'
            meta = {'session_id':s['id'], 'employee':s['employee'], 'employee_id':s['employee_id'], 'check_in_local':session_track._local(s['check_in_time']),
                    'finish_local':session_track._local(s['finish_time']), 'open':not s['finish_time']}
            flag_source = 'stored'
        else:
            day = datetime.strptime(session_key, '%Y-%m-%d').date()
            raw = gps._points(c, kind, ident, None, None)
            pts = []
            for p in raw:
                t = gps._parse(p['recorded_at'])
                if t is None or p['latitude'] is None or t.astimezone(session_track.LOCAL_TZ).date() != day:continue
                pts.append({'id':p['id'], 'latitude':p['latitude'], 'longitude':p['longitude'], 'accuracy':p.get('horizontal_accuracy'), 't':t, 'origin':p['origin']})
            assigned = _vehicle_sector(c, kind, ident)
            sector_row, native = _sector(c, assigned) if assigned else (None, None)
            incidents, origin = [], ','.join(sorted({p['origin'] for p in pts})) or None
            meta = {'session_id':None, 'day':session_key}
            flag_source = 'current_polygon'
    pts.sort(key=lambda p:(p['t'], p['id']))
    inside_fn = session_track._inside_test(sector_row) if sector_row else (lambda la, lo:False)
    current = [bool(inside_fn(p['latitude'], p['longitude'])) for p in pts]
    if flag_source == 'current_polygon':
        for p, v in zip(pts, current):p['inside'] = v
    mismatches = [p['id'] for p, v in zip(pts, current) if p['inside'] != v]
    segments = detect_segments(pts, inside_fn, _distance_fn(native))
    by_id = {p['id']:p for p in pts}
    _compartments(organization_id, assigned, segments, by_id)
    unmatched = _match(segments, incidents) if kind == 'worker' else []
    inside_run = []   # drawing: inside runs, same split as the Map tab
    if kind == 'worker':
        track = session_track.build_track(meta['session_id'])
        tab = {k:track['summary'][k] for k in ('points', 'duration_s', 'inside_s', 'outside_s', 'gaps_count', 'gaps_seconds')}
        inside_run = [r['coords'] for r in track['runs'] if r['inside'] and len(r['coords']) > 1]
    else:
        tab = None
        for a, b in zip(pts, pts[1:]):
            if a['inside'] and b['inside'] and (b['t']-a['t']).total_seconds() <= session_track.TRACK_GAP_SECONDS:
                if inside_run and inside_run[-1][-1] == [a['latitude'], a['longitude']]:inside_run[-1].append([b['latitude'], b['longitude']])
                else:inside_run.append([[a['latitude'], a['longitude']], [b['latitude'], b['longitude']]])
    outside_sum = sum(s['outside_s'] for s in segments)
    confirmed = [s for s in segments if s['status'] == VIOLATION]
    dists = [s['max_distance_m'] for s in segments if s['max_distance_m'] is not None]
    entered = {}
    for s in segments:
        for comp in s['compartments']:
            key = json.dumps({k:comp.get(k) for k in ('kind', 'catalogue_id', 'reason', 'registered_sector')}, sort_keys=True)
            entered.setdefault(key, dict(comp, points=0))['points'] += comp['points']
    last = pts[-1] if pts else None
    summary = {
        'points':len(pts), 'flag_source':flag_source,
        'inside_s':tab['inside_s'] if tab else None, 'outside_s':tab['outside_s'] if tab else outside_sum,
        'outside_s_segments':outside_sum, 'duration_s':tab['duration_s'] if tab else None,
        'gaps_count':tab['gaps_count'] if tab else None, 'gaps_seconds':tab['gaps_seconds'] if tab else None,
        'exits':sum(1 for s in segments if not s['started_outside']), 'started_outside':bool(segments and segments[0]['started_outside']),
        'segments':len(segments), 'violations':len(confirmed), 'unknown':len(segments)-len(confirmed),
        'max_distance_m':max(dists) if dists else None, 'compartments':list(entered.values()),
        'flag_mismatch_points':mismatches,
        'matches_map_tab':(abs(outside_sum-tab['outside_s']) < 0.01) if (tab and tab['outside_s'] is not None) else None,
    }
    distance = _distance_fn(native)
    for p in pts:   # distance from the sector polygon, outside points only (inside: not applicable)
        p['distance_m'] = None if p['inside'] else distance(p['latitude'], p['longitude'])
    return {
        'kind':kind, 'id':ident, 'session_key':str(session_key), 'session':meta, 'assigned_sector':assigned,
        'sector_polygon':native is not None, 'origin':origin, 'max_accuracy_m':gps.MAX_ACCURACY_M,
        'gap_seconds':session_track.TRACK_GAP_SECONDS, 'summary':summary, 'segments':segments,
        'inside_lines':inside_run, 'incidents_unmatched':unmatched,
        'points':[{'id':p['id'], 'lat':p['latitude'], 'lon':p['longitude'], 'time':_ts(p['t']), 'accuracy_m':p['accuracy'], 'inside':p['inside'],
                   'distance_m':p['distance_m'], 'register':p.get('register')} for p in pts],
        'last':{'lat':last['latitude'], 'lon':last['longitude'], 'time':_ts(last['t']), 'inside':last['inside']} if last else None,
        'start':{'lat':pts[0]['latitude'], 'lon':pts[0]['longitude'], 'time':_ts(pts[0]['t'])} if pts else None,
        'can_create_incidents':kind == 'worker',
    }


def session_violations(organization_id, session_id):
    """Deep link (#forest-map/session-N): the worker is resolved from the session itself."""
    with closing(gps._app()) as c:
        row = c.execute('SELECT employee_id FROM work_sessions WHERE id=?', (session_id,)).fetchone()
    if row is None or row[0] is None:raise LookupError('session_not_found')
    return violations(organization_id, 'worker', row[0], str(session_id))


def _vehicle_sector(c, kind, ident):
    if kind == 'vehicle':
        r = c.execute('SELECT sector FROM vehicle_gps_pings WHERE vehicle_id=? AND sector IS NOT NULL ORDER BY id DESC LIMIT 1', (ident,)).fetchone()
        return r[0] if r else None
    if kind == 'equipment':
        r = c.execute('SELECT sector FROM sector_equipment WHERE id=?', (ident,)).fetchone()
        return r[0] if r else None
    for r in c.execute("SELECT normalized_payload_json FROM integration_records WHERE source_provider='fleet_gps_demo' AND entity_type='GPSPosition' ORDER BY id DESC"):
        try:p = json.loads(r[0])
        except (TypeError, ValueError):continue
        if str(p.get('vehicle_id')) == str(ident):return p.get('sector')
    return None


# ── Human action: create (or attach to) an incident ─────────────────────────────────────────

def _comp_label(comp):
    if comp['kind'] == 'compartment':text = f"{comp['kadastrs']} · K{comp['kvart']} · N{comp['nog']}"
    elif comp['kind'] == 'outside_register':text = 'outside forest register'
    else:text = f"register unknown ({comp.get('reason')})"
    return text+(f" · registered sector {comp['registered_sector']}" if comp.get('registered_sector') else '')


def create_incident(organization_id, session_id, exit_point_id, actor):
    """Dashboard button. Deduplicated: an incident already linked to this exit is returned; an OPEN /
    NOTIFIED SECTOR_EXIT of the same session (the bot's one-per-session rule) gets this exit as
    evidence; otherwise a new SECTOR_EXIT incident is created via database.add_incident."""
    with _create_lock:
        with closing(gps._app()) as c:
            s = c.execute('SELECT * FROM work_sessions WHERE id=?', (session_id,)).fetchone()
        if s is None or s['employee_id'] is None:raise LookupError('session_not_found')
        v = violations(organization_id, 'worker', s['employee_id'], session_id)
        seg = next((x for x in v['segments'] if x['exit_point_id'] == exit_point_id), None)
        if seg is None:raise LookupError('exit_not_found')
        if seg['status'] != VIOLATION:raise PermissionError('segment_unknown')
        if seg['incidents']:
            return {'result':'existing', 'incident_id':seg['incidents'][0]['id']}
        dist = seg['max_distance_m']
        comps = '; '.join(_comp_label(x)+f" ({x['points']} pt)" for x in seg['compartments']) or '—'
        acc = f"± {seg['median_accuracy_m']:.0f} m" if seg['median_accuracy_m'] is not None else 'unknown'
        period = f"{seg['start_local']} – {(seg['reentry'] or {}).get('time') and _local(gps._parse(seg['reentry']['time'])) or 'no re-entry recorded'}"
        evidence = [
            ('telegram_live_location', 'GPS_EXIT_POINT', f"{seg['exit_marker']['lat']:.6f}, {seg['exit_marker']['lon']:.6f} · first point outside {seg['start_local']}",
             'session_track_points', seg['exit_point_id'], seg['start']),
            ('forest_map', 'OUTSIDE_SEGMENT', f"{period} · {seg['outside_s']:.0f} s outside (Map tab rule) · {seg['points']} points · max {dist:.1f} m from sector boundary · median accuracy {acc}",
             'work_sessions', session_id, seg['start']),
            ('vmd_register', 'COMPARTMENTS_ENTERED', comps, None, None, seg['start']),
            ('forest_map', 'TRACK', f"#forest-map/session-{session_id} · /api/sessions/{session_id}/track", 'work_sessions', session_id, None),
        ]
        if seg['reentry']:
            evidence.insert(1, ('telegram_live_location', 'GPS_REENTRY_POINT', f"{seg['reentry']['lat']:.6f}, {seg['reentry']['lon']:.6f} · first point back inside",
                                'session_track_points', seg['reentry']['point_id'], seg['reentry']['time']))
        details = json.dumps({'source':'forest_map', 'session_id':session_id, 'exit_point_id':exit_point_id, 'start':seg['start'], 'end':seg['end'],
                              'outside_s':round(seg['outside_s'], 1), 'points':seg['points'], 'max_distance_m':round(dist, 1),
                              'median_accuracy_m':seg['median_accuracy_m'], 'compartments':[_comp_label(x) for x in seg['compartments']]}, ensure_ascii=False)
        with closing(sqlite3.connect(database.DB_NAME)) as conn:
            open_row = conn.execute("SELECT id FROM risks WHERE entity_type='EMPLOYEE' AND entity_id=? AND rule_code='SECTOR_EXIT' "
                                    "AND status IN ('OPEN','NOTIFIED') AND sector=? AND session_id=? ORDER BY id DESC LIMIT 1",
                                    (s['employee_id'], s['sector'], session_id)).fetchone()
        if open_row:
            incident, result = open_row[0], 'attached'
            database.add_risk_event(incident, 'STILL_OUTSIDE', actor=actor, details=details)
        else:
            reason = (f"Worker {s['employee']} was outside assigned sector {s['sector']} {period}: {seg['outside_s']/60:.1f} min, "
                      f"{seg['points']} GPS points, up to {dist:.0f} m from the boundary — created by {actor} from recorded data (session #{session_id})")
            incident = database.add_incident(s['sector'], 'HIGH', reason, entity_type='EMPLOYEE', entity_id=s['employee_id'], rule_code=INCIDENT_RULE,
                                             distance_m=round(dist, 1), duration_min=round(seg['outside_s']/60, 1), data_origin='REAL', occurred_at=seg['start'])
            with closing(sqlite3.connect(database.DB_NAME)) as conn:
                conn.execute('UPDATE risks SET session_id=? WHERE id=?', (session_id, incident));conn.commit()
            database.add_risk_event(incident, 'CREATED_FROM_RECORD', actor=actor, details=details)
            result = 'created'
        for source, kind, summary, table, ref, observed in evidence:
            database.add_risk_evidence(incident, source, 'REAL', kind, summary, table, ref, observed)
        return {'result':result, 'incident_id':incident}


# ── Map-load overview: outside segments of every REAL entity's latest session ───────────────

def overview_days():
    return max(1, min(365, gps._env_int('FOREST_GPS_VIOLATIONS_DAYS', 30)))


def _slim(r, name):
    """Overview payload: segments + what the segment popup needs; no full point list / inside lines."""
    out = {k:r[k] for k in ('kind', 'id', 'session_key', 'session', 'assigned_sector', 'sector_polygon', 'origin',
                            'max_accuracy_m', 'gap_seconds', 'summary', 'segments', 'incidents_unmatched', 'can_create_incidents', 'last')}
    out['name'] = name
    return out


def overview(organization_id, days=None, now=None):
    """Latest session (worker) / latest local day (vehicle, REAL pings only) whose last stored point lies
    within the last `days` days, for every entity with REAL data. Read-only; computes nothing new beyond
    violations()."""
    days = days or overview_days()
    now = now or datetime.now(timezone.utc)
    since = now-timedelta(days=days)
    entities = []
    with closing(gps._app()) as c:
        latest = {}
        for r in c.execute('SELECT w.id,w.employee_id,w.employee,MAX(p.recorded_at) AS last FROM work_sessions w '
                           'JOIN session_track_points p ON p.session_id=w.id WHERE w.employee_id IS NOT NULL GROUP BY w.id'):
            t = gps._parse(r['last'])
            if t is None or t < since or t > now+timedelta(minutes=5):continue
            if r['employee_id'] not in latest or t > latest[r['employee_id']][0]:latest[r['employee_id']] = (t, r['id'], r['employee'])
        names = {r[0]:r[1] for r in c.execute('SELECT id,full_name FROM sector_employees')}
        vehicles = []
        for kind, column in (('vehicle', 'vehicle_id'), ('equipment', 'equipment_id')):
            for (ident,) in c.execute(f'SELECT DISTINCT {column} FROM vehicle_gps_pings WHERE {column} IS NOT NULL'):
                real = [t for p in gps._points(c, kind, ident, None, None) if p['origin'] == 'REAL' and (t := gps._parse(p['recorded_at'])) and since <= t <= now]
                if real:vehicles.append((kind, ident, max(real).astimezone(session_track.LOCAL_TZ).date().isoformat()))
        plates = {r[0]:r[1] for r in c.execute('SELECT id,plate FROM sector_vehicles')}
        codes = {r[0]:r[1] for r in c.execute('SELECT id,equipment_code FROM sector_equipment')}
    for employee, (t, sid, name) in sorted(latest.items(), key=lambda kv:kv[1][0], reverse=True):
        entities.append(_slim(violations(organization_id, 'worker', employee, str(sid)), names.get(employee) or name or f'#{employee}'))
    for kind, ident, day in vehicles:
        r = violations(organization_id, kind, ident, day)
        if r['origin'] and 'REAL' in r['origin'].split(','):
            entities.append(_slim(r, (plates if kind == 'vehicle' else codes).get(ident) or f'#{ident}'))
    return {'generated_at':gps._iso(now), 'days':days, 'since':gps._iso(since), 'entities':entities,
            'segments':sum(len(e['segments']) for e in entities), 'violations':sum(e['summary']['violations'] for e in entities)}
