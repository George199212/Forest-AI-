"""Bridge external polygons into the existing sector table.

Tenant boundary: database.DB_NAME is the authenticated instance's own database.
No caller-supplied organization, database path, provider URL or geometry accepted
by import/apply. Org 1 is the sole organization used by current instance auth.
"""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone

import database
from .base import GeodataError


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(boundary_json):
    return hashlib.sha256(boundary_json.encode()).hexdigest()


def init_schema(db_path):
    with closing(sqlite3.connect(db_path, timeout=10)) as c, c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS geodata_sources (
            sector_id INTEGER PRIMARY KEY REFERENCES sectors(id) ON DELETE CASCADE,
            sector TEXT NOT NULL,
            organization_id INTEGER NOT NULL CHECK(organization_id=1),
            boundary_source_type TEXT NOT NULL DEFAULT 'external_geodata',
            provider TEXT NOT NULL,
            source_layer TEXT NOT NULL,
            source_feature_id TEXT NOT NULL,
            source_dataset_title TEXT NOT NULL,
            source_attribution TEXT NOT NULL,
            source_properties TEXT NOT NULL,
            source_crs TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            source_last_checked_at TEXT NOT NULL,
            UNIQUE(organization_id,provider,source_layer,source_feature_id)
        );
        CREATE TABLE IF NOT EXISTS geodata_boundary_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sector TEXT NOT NULL,
            sector_id INTEGER NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            old_boundary_json TEXT,
            new_boundary_json TEXT NOT NULL,
            source_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS geodata_previews (
            token TEXT PRIMARY KEY,
            actor TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            expires_at REAL NOT NULL
        );
        ''')


def connect():
    c = sqlite3.connect(database.DB_NAME, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def normalize(feature):
    """GeoJSON always uses lon/lat. Preserve one simple ring without alteration.

    The existing operational engine supports only a flat lat/lon ring. Reject
    holes and MultiPolygon, never flatten or take the largest polygon silently.
    Only EPSG:4326 GeoJSON reaches this function (enforced by provider).
    """
    if not isinstance(feature, dict) or feature.get('type') != 'Feature':
        raise GeodataError('Invalid GeoJSON feature')
    fid = feature.get('id')
    if isinstance(fid, bool) or not isinstance(fid, (str, int)) or not 1 <= len(str(fid)) <= 300 or any(c in str(fid) for c in ',\r\n\x00'):
        raise GeodataError('Feature has no usable stable external ID')
    geometry = feature.get('geometry')
    if not isinstance(geometry, dict) or geometry.get('type') != 'Polygon':
        raise GeodataError('Only Polygon is supported; MultiPolygon and non-polygons are not imported')
    rings = geometry.get('coordinates')
    if not isinstance(rings, list) or len(rings) != 1:
        raise GeodataError('Polygon holes are not supported by the current GPS engine')
    ring = rings[0]
    if not isinstance(ring, list) or not 4 <= len(ring) <= 10000:
        raise GeodataError('Polygon must contain 4–10000 positions')
    import math
    for p in ring:
        if not isinstance(p, list) or len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p):
            raise GeodataError('Polygon must have finite two-dimensional coordinates')
        if not (20 <= p[0] <= 29 and 55 <= p[1] <= 59):
            raise GeodataError('Polygon coordinates must be EPSG:4326 within Latvia')
    if ring[0] != ring[-1]:
        raise GeodataError('Polygon ring must be closed')
    from shapely.geometry import Polygon
    poly = Polygon(ring)
    if poly.is_empty or not poly.is_valid or poly.area <= 0:
        raise GeodataError('Empty or invalid polygon; no automatic geometry repair applied')
    props = feature.get('properties')
    if props is not None and not isinstance(props, dict):
        raise GeodataError('Invalid source properties')
    return [[p[1], p[0]] for p in ring]


def _duplicate(c, layer_id, feature_id):
    return c.execute('''SELECT s.name, s.id FROM geodata_sources g JOIN sectors s ON s.id=g.sector_id
        WHERE g.organization_id=1 AND g.provider='LVM_GEO' AND g.source_layer=? AND g.source_feature_id=?''',
        (layer_id, str(feature_id))).fetchone()


def _token(c, actor, kind, payload):
    c.execute('DELETE FROM geodata_previews WHERE expires_at<?', (time.time(),))
    if c.execute('SELECT count(*) FROM geodata_previews WHERE actor=?', (actor,)).fetchone()[0] >= 20:
        c.execute('DELETE FROM geodata_previews WHERE token IN (SELECT token FROM geodata_previews WHERE actor=? ORDER BY expires_at LIMIT 1)', (actor,))
    token = secrets.token_urlsafe(32)
    c.execute('INSERT INTO geodata_previews VALUES(?,?,?,?,?)', (token, actor, kind, json.dumps(payload, allow_nan=False), time.time()+900))
    return token


def _payload(c, token, actor, kind):
    row = c.execute('SELECT payload FROM geodata_previews WHERE token=? AND actor=? AND kind=? AND expires_at>?',
                    (token, actor, kind, time.time())).fetchone()
    if row is None:
        raise GeodataError('Preview expired or unavailable for this account; preview again')
    return json.loads(row[0])


def preview(provider, layer_id, bbox, limit, actor):
    layer = provider.get_layer_metadata(layer_id)
    data = provider.get_features(layer_id, bbox=bbox, limit=limit)
    items, trusted = [], {}
    from shapely.geometry import box, Polygon
    aoi = box(*bbox)
    with closing(connect()) as c, c:
        for index, f in enumerate(data['features']):
            item = {'index': index, 'feature_id': str(f.get('id', '')) if isinstance(f, dict) else '', 'importable': False}
            try:
                boundary = normalize(f)
                if not Polygon(f['geometry']['coordinates'][0]).intersects(aoi):
                    raise GeodataError('Feature is outside the requested area')
                dupe = _duplicate(c, layer_id, f['id'])
                item['already_imported'] = dict(dupe) if dupe else None
                item['geometry'] = f['geometry']
                item['properties'] = f.get('properties') or {}
                if not layer.get('attribution'):
                    raise GeodataError('Dataset attribution is missing in capabilities; verify the actual source before importing')
                if str(f['id']) in trusted:
                    raise GeodataError('Duplicate external ID in provider response')
                item['importable'] = not bool(dupe)
                trusted[str(f['id'])] = f
            except GeodataError as e:
                item['reason'] = str(e)
            items.append(item)
        token = _token(c, actor, 'import', {'layer': layer, 'features': trusted})
    return {'token': token, 'features': items, 'found': len(items), 'limit': limit,
            'possibly_truncated': len(items) == limit, 'expires_in_seconds': 900}


def _source(layer, feature):
    t = stamp()
    return {'boundary_source_type': 'external_geodata', 'provider': 'LVM_GEO',
            'source_layer': layer['id'], 'source_feature_id': str(feature['id']),
            'source_dataset_title': layer['title'], 'source_attribution': layer['attribution'],
            'source_properties': json.dumps(feature.get('properties') or {}, ensure_ascii=False, allow_nan=False),
            'source_crs': 'EPSG:4326', 'imported_at': t, 'source_last_checked_at': t}


def _history(c, sector, actor, action, old, new, source):
    c.execute('''INSERT INTO geodata_boundary_history
        (sector,sector_id,actor,action,old_boundary_json,new_boundary_json,source_json,created_at)
        VALUES(?,?,?,?,?,?,?,?)''', (sector['name'], sector['id'], actor, action, old, new, json.dumps(source), stamp()))


def import_selected(token, feature_ids, actor):
    if not 1 <= len(feature_ids) <= 25 or len(set(feature_ids)) != len(feature_ids):
        raise GeodataError('Select between 1 and 25 distinct features')
    with closing(connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        payload = _payload(c, token, actor, 'import')
        results = []
        for fid in feature_ids:
            f = payload['features'].get(fid)
            if f is None:
                raise GeodataError('Feature is not part of this validated preview')
            dupe = _duplicate(c, payload['layer']['id'], fid)
            if dupe:
                results.append({'status': 'already_imported', **dict(dupe)}); continue
            # Clean up metadata left by legacy delete endpoints without FK checks.
            c.execute('DELETE FROM geodata_sources WHERE sector_id NOT IN (SELECT id FROM sectors)')
            boundary = normalize(f)
            encoded = json.dumps(boundary)
            lat, lon = database.calc_centroid(boundary)
            area = database.calc_area_ha(boundary)
            # Names are Forest AI owned. Never use the external feature ID.
            sequence = c.execute("SELECT seq FROM sqlite_sequence WHERE name='sectors'").fetchone()
            next_id = max(c.execute('SELECT COALESCE(MAX(id),0) FROM sectors').fetchone()[0], sequence[0] if sequence else 0)+1
            name = f'GEO-{next_id:04d}'
            while c.execute('SELECT 1 FROM sectors WHERE name=?', (name,)).fetchone():
                next_id += 1; name = f'GEO-{next_id:04d}'
            t = stamp()
            cursor = c.execute('''INSERT INTO sectors
                (name,contractor,status,approved_volume,boundary_json,center_lat,center_lon,area_ha,color,created_at,updated_at,data_origin)
                VALUES(?,'','Planned','',?,?,?,?, 'green',?,?,'REAL')''', (name,encoded,lat,lon,area,t,t))
            sector = {'id': cursor.lastrowid, 'name': name}
            source = _source(payload['layer'], f)
            columns = list(source)
            c.execute('INSERT INTO geodata_sources (sector_id,sector,organization_id,' + ','.join(columns) + ') VALUES(' + ','.join('?' for _ in range(len(columns)+3)) + ')',
                      [sector['id'],name,1] + [source[k] for k in columns])
            _history(c, sector, actor, 'IMPORT', None, encoded, source)
            results.append({'status': 'imported', **sector})
        return {'sectors': results}


def source_info(sector_id):
    with closing(connect()) as c:
        sector = c.execute('SELECT id,name,boundary_json FROM sectors WHERE id=?', (sector_id,)).fetchone()
        if sector is None: raise GeodataError('Sector not found in this account')
        row = c.execute('SELECT * FROM geodata_sources WHERE sector_id=? AND organization_id=1', (sector_id,)).fetchone()
        if row is None: return {'boundary_source_type': 'manual'}
        source = dict(row)
        source['source_properties'] = json.loads(source['source_properties'])
        source['history'] = [dict(r) for r in c.execute('SELECT id,actor,action,created_at FROM geodata_boundary_history WHERE sector_id=? ORDER BY id DESC LIMIT 50', (sector_id,))]
        return source


def refresh_boundary(provider, sector_id, actor):
    source = source_info(sector_id)
    if source.get('provider') != 'LVM_GEO': raise GeodataError('Sector has no LVM GEO source')
    # Re-confirm source service availability; no stale capability authorizes refresh.
    provider.get_capabilities(refresh=True)
    layer = provider.get_layer_metadata(source['source_layer'])
    f = provider.get_feature(source['source_layer'], source['source_feature_id'])
    new = normalize(f)
    from shapely.geometry import Polygon
    with closing(connect()) as c, c:
        current = c.execute('SELECT id,name,boundary_json FROM sectors WHERE id=?', (sector_id,)).fetchone()
        if current is None: raise GeodataError('Sector no longer exists')
        old = json.loads(current['boundary_json'])
        c.execute('UPDATE geodata_sources SET source_last_checked_at=? WHERE sector_id=?', (stamp(),sector_id))
        unchanged = Polygon([(p[1],p[0]) for p in old]).equals(Polygon(f['geometry']['coordinates'][0]))
        if unchanged: return {'changed': False, 'message': 'No changes'}
        if not layer.get('attribution'): raise GeodataError('Dataset attribution missing; local boundary retained')
        proposed = {'sector_id': sector_id, 'old_hash': digest(current['boundary_json']),
                    'new_boundary': new, 'source': _source(layer,f)}
        token = _token(c, actor, 'refresh', proposed)
        return {'changed': True, 'message': 'Boundary update detected. Confirmation required.',
                'token': token, 'old_boundary': old, 'new_boundary': new}


def apply_boundary(token, actor):
    with closing(connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        payload = _payload(c, token, actor, 'refresh')
        sector = c.execute('SELECT id,name,boundary_json FROM sectors WHERE id=?', (payload['sector_id'],)).fetchone()
        if sector is None or digest(sector['boundary_json']) != payload['old_hash']:
            raise GeodataError('Boundary changed since preview; refresh again')
        if c.execute('SELECT 1 FROM geodata_sources WHERE sector_id=? AND organization_id=1', (sector['id'],)).fetchone() is None:
            raise GeodataError('Source no longer belongs to this account')
        b = payload['new_boundary']; encoded = json.dumps(b)
        lat,lon = database.calc_centroid(b)
        c.execute('UPDATE sectors SET boundary_json=?,center_lat=?,center_lon=?,area_ha=?,updated_at=? WHERE id=?',
                  (encoded,lat,lon,database.calc_area_ha(b),stamp(),sector['id']))
        src = payload['source']
        c.execute('UPDATE geodata_sources SET source_properties=?,source_attribution=?,source_dataset_title=?,source_last_checked_at=? WHERE sector_id=?',
                  (src['source_properties'],src['source_attribution'],src['source_dataset_title'],src['source_last_checked_at'],sector['id']))
        _history(c,sector,actor,'CONFIRMED_REFRESH',sector['boundary_json'],encoded,src)
        c.execute('DELETE FROM geodata_previews WHERE token=?', (token,))
        return {'ok': True, 'name': sector['name']}
