"""Local dataset catalogue and insert-only bridge into ordinary Forest AI sectors.

The authenticated instance's database is the tenant boundary. Source geometry is
always reread on the server; the browser submits IDs and a dataset version only.
"""
import copy
import hashlib
import json
import logging
import math
import re
import sqlite3
from contextlib import closing
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import database
from . import store, vmd_test
from .base import GeodataError

log = logging.getLogger(__name__)
PROVIDER = 'VMD_LOCAL'
SOURCE_LAYER = 'vmd_local_compartments'
TITLE = 'VMD Forest Compartments — Local Dataset'


class LocalImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    feature_ids: list[Annotated[str, Field(pattern=r'^VMD-[0-9]{1,32}-[0-9]{1,16}-[0-9]{1,16}$')]] = Field(min_length=1, max_length=25)
    dataset_version: str = Field(pattern=r'^[a-f0-9]{64}$')


def dataset_version(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def external_id(feature):
    props = feature.get('properties') or {}
    parts = [str(props.get(k, '')).strip() for k in ('kadastrs', 'kvart', 'nog')]
    if not re.fullmatch(r'[0-9]{1,32}', parts[0]) or any(not re.fullmatch(r'[0-9]{1,16}', p) for p in parts[1:]):
        raise vmd_test.VmdTestDataError('Local VMD features require numeric kadastrs, kvart and nog identifiers')
    return f'VMD-{parts[0]}-{int(parts[1])}-{int(parts[2])}'


def catalogue():
    data = vmd_test.read_test_compartments()
    features = {}
    for feature in data['features']:
        fid = external_id(feature)
        if fid in features:
            raise vmd_test.VmdTestDataError('Duplicate compartment identifiers in local VMD dataset', 409)
        features[fid] = feature
    return data, features, dataset_version(data)


def prepared(feature, fid):
    normalized = copy.deepcopy(feature)
    normalized['id'] = fid
    boundary = store.normalize(normalized)
    area = feature['properties'].get('nog_plat')
    if isinstance(area, bool):
        raise GeodataError('Invalid compartment area')
    try:
        area = float(area)
    except (ValueError, TypeError) as exc:
        raise GeodataError('Compartment area nog_plat is missing or invalid') from exc
    if not math.isfinite(area) or area <= 0:
        raise GeodataError('Compartment area must be finite and positive')
    return boundary, area


def _check_storage(c):
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'sectors', 'geodata_sources', 'geodata_boundary_history'} <= tables:
        raise vmd_test.VmdTestDataError('Geodata storage is not initialized', 503)


def _mappings(c):
    rows = c.execute('''SELECT g.source_feature_id,g.source_layer,g.sector_id,s.name
        FROM geodata_sources g LEFT JOIN sectors s ON s.id=g.sector_id
        WHERE g.organization_id=1 AND g.provider=?''', (PROVIDER,)).fetchall()
    return {r['source_feature_id']: dict(r) for r in rows}


def local_status():
    data, features, version = catalogue()
    with closing(store.connect()) as c:
        _check_storage(c)
        mappings = _mappings(c)
    records = []
    for fid, feature in features.items():
        row = mappings.get(fid)
        reason = None
        try:
            prepared(feature, fid)
        except GeodataError as exc:
            reason = str(exc)
        if row and not row['name']:
            reason = 'Source mapping references a removed sector; administrator review required'
        records.append({'external_id': fid, 'status': 'IMPORTED' if row and row['name'] else ('FAILED' if reason else 'READY'),
                        'importable': not row and reason is None, 'reason': reason,
                        'sector': {'id': row['sector_id'], 'name': row['name']} if row and row['name'] else None})
    return {'name': TITLE, 'source': PROVIDER, 'source_type': 'Local GeoJSON', 'status': 'READY',
            'crs': 'EPSG:4326', 'feature_count': len(features), 'dataset_version': version, 'features': records}


def require_json_mutation(request: Request):
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(415, 'Local VMD imports require application/json')
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') in {'cross-site', 'same-site'}:
        raise HTTPException(403, 'Cross-origin import rejected')
    if origin:
        parsed = urlsplit(origin)
        if parsed.netloc != request.headers.get('host') or parsed.scheme != request.url.scheme:
            raise HTTPException(403, 'Cross-origin import rejected')


def import_features(feature_ids, version, actor):
    if not 1 <= len(feature_ids) <= 25 or len(set(feature_ids)) != len(feature_ids):
        raise vmd_test.VmdTestDataError('Select between 1 and 25 distinct compartments')
    _, features, current_version = catalogue()
    if version != current_version:
        raise vmd_test.VmdTestDataError('Local VMD dataset changed; reload before importing', 409)
    results = []
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        _check_storage(c)
        mappings = _mappings(c)
        for fid in feature_ids:
            result = {'external_id': fid}
            if fid not in features:
                results.append({**result, 'status': 'failed', 'reason': 'Compartment is not in the current local dataset'}); continue
            row = mappings.get(fid)
            if row:
                if row['name']:
                    results.append({**result, 'status': 'already_exists', 'id': row['sector_id'], 'name': row['name']})
                else:
                    results.append({**result, 'status': 'failed', 'reason': 'Source mapping references a removed sector; administrator review required'})
                continue
            feature = features[fid]
            props = feature['properties']
            name = f"VMD {str(props['kadastrs']).strip()} - {int(props['kvart'])}-{int(props['nog'])}"
            # Manual sectors with the same name are never adopted or overwritten.
            if c.execute('SELECT 1 FROM sectors WHERE name=?', (name,)).fetchone():
                results.append({**result, 'status': 'failed', 'reason': 'A sector with this name already exists without this source identity'}); continue
            try:
                boundary, area = prepared(feature, fid)
                encoded = json.dumps(boundary, allow_nan=False)
                lat, lon = database.calc_centroid(boundary)
                t = store.stamp()
                source = {'boundary_source_type': 'external_geodata', 'provider': PROVIDER,
                          'source_layer': SOURCE_LAYER, 'source_feature_id': fid,
                          'source_dataset_title': TITLE, 'source_attribution': 'VMD / LVM open data',
                          'source_properties': json.dumps({**props, 'source': PROVIDER, 'external_id': fid, 'dataset_version': current_version}, ensure_ascii=False, allow_nan=False),
                          'source_crs': 'EPSG:4326', 'imported_at': t, 'source_last_checked_at': t}
            except GeodataError as exc:
                results.append({**result, 'status': 'failed', 'reason': str(exc)}); continue
            c.execute('SAVEPOINT vmd_feature')
            try:
                cursor = c.execute('''INSERT INTO sectors
                    (name,contractor,status,approved_volume,map_url,image_path,boundary_json,center_lat,center_lon,area_ha,color,created_at,updated_at,data_origin)
                    VALUES(?,'','Planned','','','',?,?,?,?, '#4b9d54',?,?,'REAL')''', (name, encoded, lat, lon, area, t, t))
                sector = {'id': cursor.lastrowid, 'name': name}
                columns = list(source)
                c.execute('INSERT INTO geodata_sources (sector_id,sector,organization_id,'+','.join(columns)+') VALUES('+','.join('?' for _ in range(len(columns)+3))+')',
                          [sector['id'], name, 1]+[source[k] for k in columns])
                store._history(c, sector, actor, 'IMPORT_LOCAL_VMD', None, encoded, source)
                c.execute('RELEASE vmd_feature')
            except sqlite3.IntegrityError:
                c.execute('ROLLBACK TO vmd_feature'); c.execute('RELEASE vmd_feature')
                log.warning('Local VMD import conflict for %s', fid)
                results.append({**result, 'status': 'failed', 'reason': 'Sector/source identity conflict; no sector was overwritten'}); continue
            mappings[fid] = {'sector_id': sector['id'], 'name': name}
            results.append({**result, 'status': 'imported', **sector})
    return {'source': PROVIDER, 'results': results,
            'imported': sum(r['status']=='imported' for r in results),
            'already_exists': sum(r['status']=='already_exists' for r in results),
            'failed': sum(r['status']=='failed' for r in results)}
