"""No-writes walker for the read-only review/demo instance (ACCESS_MODE=review).

Calls every GET route of api.app (including routes of routers added with include_router, which FastAPI
0.136 wraps in _IncludedRouter) and proves that nothing is written:
  * DB CONTENT: per-table row count + SHA-256 over all rows ordered by rowid (or primary key), taken after
    a forced WAL checkpoint; -wal / -shm files are reported;
  * FILES: every path, size and mtime under the instance data/ directory.
Path and query parameters are filled with real IDs read from the instance DB. Routes that cannot be called
meaningfully are reported as SKIPPED with the reason (never silently dropped).

Used by tests/test_review_no_writes.py, and as a CLI against a COPY of a release's data/ directory:
  cp -a <release> <copy> && cd <copy> && ACCESS_MODE=review DB_PATH=<copy>/data/forest_ai.db python3 <repo>/tests/review_no_writes.py .
"""
import hashlib
import inspect
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

EXPECTED_FILE_CHANGES = ()   # no log or cache file under data/ may change during a GET walk


def content_snapshot(db_path):
    """{table: (row_count, sha256)} after a forced WAL checkpoint, plus the -wal/-shm state."""
    db_path = str(db_path)
    with sqlite3.connect(db_path) as c:   # checkpoint needs a writable handle; it moves pages, not content
        mode = c.execute('PRAGMA journal_mode').fetchone()[0]
        checkpoint = c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone() if mode == 'wal' else None
    c = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    tables = {}
    for name, sql in c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"):
        order = 'rowid'
        if sql and 'WITHOUT ROWID' in sql.upper():
            pk = [r[1] for r in c.execute(f'PRAGMA table_info("{name}")') if r[5]]
            order = ','.join(f'"{k}"' for k in pk)
        h, n = hashlib.sha256(), 0
        for row in c.execute(f'SELECT * FROM "{name}" ORDER BY {order}'):
            h.update(repr(row).encode()); n += 1
        tables[name] = (n, h.hexdigest())
    c.close()
    side = {s: (os.path.getsize(db_path + s) if os.path.exists(db_path + s) else None) for s in ('-wal', '-shm', '-journal')}
    return {'journal_mode': mode, 'checkpoint': checkpoint, 'tables': tables, 'side_files': side}


def files_snapshot(data_dir):
    out = {}
    for p in sorted(Path(data_dir).rglob('*')):
        if p.is_file():
            st = p.stat(); out[str(p.relative_to(data_dir))] = (st.st_size, st.st_mtime_ns)
    return out


def get_routes(app):
    """[(path, endpoint, route)] for every GET route, recursing into included routers and mounts."""
    found = []
    def walk(routes, prefix=''):
        for r in routes:
            methods = getattr(r, 'methods', None)
            sub = getattr(getattr(r, 'original_router', None), 'routes', None) or (getattr(r, 'routes', None) if not methods else None)
            if sub is not None and not methods:
                walk(sub, prefix + (getattr(r, 'path', '') or ''))
            elif methods and 'GET' in methods:
                found.append((prefix + r.path, r))
    walk(app.routes)
    return sorted({p: r for p, r in found}.items())


def demo_values(db_path):
    """Real IDs from the instance DB for path/query parameters."""
    c = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    def one(sql):
        try:
            row = c.execute(sql).fetchone(); return None if row is None else str(row[0])
        except sqlite3.Error:
            return None
    sector = one('SELECT name FROM sectors ORDER BY id')
    v = {
        'sector': sector, 'sector_name': sector, 'name': sector, 'key': sector,
        'sector_id': one('SELECT id FROM sectors ORDER BY id'),
        'session_id': one('SELECT session_id FROM session_track_points ORDER BY id') or one('SELECT id FROM work_sessions ORDER BY id'),
        'risk_id': one('SELECT id FROM risks ORDER BY id'), 'incident_id': one('SELECT id FROM risks ORDER BY id'),
        'object_id': one('SELECT id FROM objects ORDER BY id'), 'plan_id': one('SELECT id FROM boundary_plans ORDER BY id'),
        'integration_id': one('SELECT id FROM integrations ORDER BY id'),
        'equipment_id': one('SELECT id FROM sector_equipment ORDER BY id'), 'machine_id': one('SELECT id FROM sector_equipment ORDER BY id'),
        'vehicle_id': one('SELECT id FROM sector_vehicles ORDER BY id'), 'employee_id': one('SELECT id FROM sector_employees ORDER BY id'),
        'filename': (lambda p: os.path.basename(p) if p else None)(one('SELECT image_path FROM work_photos ORDER BY id')),
        'snapshot_id': one('SELECT id FROM sector_snapshots ORDER BY id'), 'analysis_id': one('SELECT id FROM ai_inspector_analyses ORDER BY id'),
        'run_id': one('SELECT id FROM photo_cmp_runs ORDER BY id'), 'point_id': one('SELECT id FROM photo_cmp_points ORDER BY id'),
        'kind': 'image', 'layer': 'forest', 'z': '14', 'x': '9298', 'y': '4949', 'provider': 'fleet_gps_demo',
        # query parameters
        'kadastrs': '01000922053', 'lat': '57.30', 'lon': '21.905', 'zoom': '14', 'municipality': 'Kuldīgas novads',
        'start': '2026-10-19T00:00:00Z', 'end': '2026-10-21T00:00:00Z', 'session': None,
    }
    v['session'] = v['session_id']
    v['id'] = v['sector_id']
    c.close()
    return v


# Route-specific path parameters (same parameter name, different meaning).
ROUTE_PATH = {'/assets/{filename}': {'filename': 'favicon.png'}}

# Route-specific query parameters (the generic map above uses sector ids for "id").
ROUTE_QUERY = {
    '/api/geodata/forest-map/gps/sessions': lambda v: {'kind': 'worker', 'id': v['employee_id']},
    '/api/geodata/forest-map/gps/track': lambda v: {'kind': 'worker', 'id': v['employee_id'], 'start': v['start'], 'end': v['end']},
    '/api/geodata/forest-map/gps/violations': lambda v: {'kind': 'worker', 'id': v['employee_id'], 'session': v['session_id']},
    '/api/geodata/forest-map/feature': lambda v: {'id': 'VMD:nodala2251:50525112'},
}


def _required_query(route):
    dep = getattr(route, 'dependant', None)
    out = []
    def collect(d):
        for f in getattr(d, 'query_params', []):
            req = getattr(f, 'required', None)
            if req is None:
                req = f.field_info.is_required()
            if req:
                out.append(getattr(f, 'alias', None) or f.name)
        for sub in getattr(d, 'dependencies', []):
            collect(sub)
    if dep is not None:
        collect(dep)
    return out


def walk(app, client, db_path, data_dir, auth):
    """Call every GET route; returns dict with called, skipped, writers (per route) and totals."""
    values = demo_values(db_path)
    called, skipped, writers = [], [], []
    for path, route in get_routes(app):
        params = re.findall(r'\{(\w+)(?::\w+)?\}', path)
        pv = {**values, **ROUTE_PATH.get(path, {})}
        missing = [p for p in params if not pv.get(p)]
        if missing:
            skipped.append((path, f'no row in this DB to supply {missing}' if all(p in values for p in missing) else f'no demo value for path parameter(s) {missing}')); continue
        url = re.sub(r'\{(\w+)(?::\w+)?\}', lambda m: str(pv[m.group(1)]), path)
        query = ROUTE_QUERY[path](values) if path in ROUTE_QUERY else {}
        for q in _required_query(route):
            if q not in query:
                if not values.get(q):
                    skipped.append((path, f'no demo value for required query parameter {q!r}')); break
                query[q] = values[q]
        else:
            before_db, before_files = content_snapshot(db_path), files_snapshot(data_dir)
            try:
                status = client.get(url, params=query, auth=auth).status_code
            except Exception as exc:   # a crashing route is reported, the walk continues
                status = 'EXC ' + type(exc).__name__
            after_db, after_files = content_snapshot(db_path), files_snapshot(data_dir)
            called.append((path, status))
            changed_tables = sorted(t for t in set(before_db['tables']) | set(after_db['tables'])
                                    if before_db['tables'].get(t) != after_db['tables'].get(t))
            changed_files = sorted(f for f in set(before_files) | set(after_files)
                                   if before_files.get(f) != after_files.get(f) and not f.startswith(EXPECTED_FILE_CHANGES or ('\0',)))
            if changed_tables or changed_files:
                writers.append({'route': path, 'url': url, 'status': status, 'tables': changed_tables, 'files': changed_files})
    return {'called': called, 'skipped': skipped, 'writers': writers}


if __name__ == '__main__':
    # CLI: run INSIDE a full copy of a release folder (code + data/):  python3 tests/review_no_writes.py .
    root = Path(sys.argv[1]).resolve()
    assert Path.cwd().resolve() == root, 'run from inside the release copy'
    os.environ.setdefault('ACCESS_MODE', 'review')
    assert os.environ['ACCESS_MODE'] == 'review', 'review mode only'
    db = os.environ['DB_PATH']
    assert Path(db).resolve().is_relative_to(root), 'DB_PATH must be inside the instance root (use a COPY)'
    os.environ.setdefault('DASHBOARD_USERNAME', 'walker'); os.environ.setdefault('DASHBOARD_PASSWORD', 'walker')
    sys.path.insert(0, os.getcwd())
    import requests, urllib.request
    def offline(*a, **k):
        raise requests.ConnectionError('walker is offline by design')
    requests.get = requests.post = requests.request = offline
    requests.Session.request = offline
    urllib.request.urlopen = offline
    import api
    from fastapi.testclient import TestClient
    with TestClient(api.app) as client:
        before = content_snapshot(db)
        result = walk(api.app, client, db, root / 'data', (os.environ['DASHBOARD_USERNAME'], os.environ['DASHBOARD_PASSWORD']))
        after = content_snapshot(db)
    result['content_before'], result['content_after'] = before, after
    print(json.dumps(result, indent=1, default=str))
    sys.exit(1 if result['writers'] or before['tables'] != after['tables'] else 0)
