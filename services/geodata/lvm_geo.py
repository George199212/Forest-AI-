"""Read-only OGC provider. No sector/database/GPS dependencies.

Endpoint source (verified 2026-10-30):
https://www.lvmgeo.lv/en/data/services/coming-soon
Only published official WMS URLs are allowlisted. WFS is probed on those same
OGC endpoints; only valid GetCapabilities + GetFeature advertisement enables it.
No guessed WFS URL, remote OnlineResource URL, redirect or user URL is fetched.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import logging
import math
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import requests
from .base import GeodataProvider, GeodataError

log = logging.getLogger(__name__)
ENDPOINTS = {
    'maps': 'https://geoserver.lvmgeo.lv/wms62531a9bfcfa4015856924e94076a178',
    'vector': 'https://geoserver.lvmgeo.lv/wmsvector62531a9bfcfa4015856924e94076a179',
}
MAX_BYTES = 8 * 1024 * 1024
MAX_FEATURES = 100


def now():
    return datetime.now(timezone.utc).isoformat()


def local(tag):
    return tag.rsplit('}', 1)[-1]


def children(node, tag):
    return [e for e in node if local(e.tag) == tag]


def val(node, tag):
    return next((''.join(e.itertext()).strip()[:4000] for e in node if local(e.tag) == tag), '')


def xml(raw):
    # Reject DTD/entity declarations before stdlib parsing, including UTF-16/32.
    compact = raw.replace(b'\x00', b'').upper()
    if b'<!DOCTYPE' in compact or b'<!ENTITY' in compact:
        raise GeodataError('Unsafe XML declaration rejected')
    try:
        root = ET.fromstring(raw)
        pending, count = [(root, 0)], 0
        while pending:
            node, depth = pending.pop(); count += 1
            if depth > 64 or count > 100000:
                raise GeodataError('OGC XML exceeds structural limits')
            pending.extend((child, depth+1) for child in node)
        return root
    except ET.ParseError as e:
        raise GeodataError('Malformed OGC XML response') from e


def validate_bbox(bbox):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise GeodataError('A limited bbox [west,south,east,north] is required')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox):
        raise GeodataError('Invalid bbox coordinates')
    w, s, e, n = bbox
    if not (20 <= w < e <= 29 and 55 <= s < n <= 59):
        raise GeodataError('Select an area in Latvia, in EPSG:4326')
    if (e-w) > 0.2 or (n-s) > 0.2:
        raise GeodataError('Zoom in: selected area must be at most 0.2° by 0.2°')
    return list(bbox)


def is_wgs84(crs):
    return crs.upper() == 'EPSG:4326' or crs.upper().endswith(':4326') or crs.upper().endswith('/4326')


class LVMGeoProvider(GeodataProvider):
    def __init__(self):
        self._cache = None
        self._expires = 0
        self._lock = threading.Lock()
        self._last_success_at = None

    def _request(self, endpoint, params, kind='xml'):
        for attempt in range(2):
            try:return self._request_once(endpoint,params,kind)
            except GeodataError as exc:
                if attempt or not isinstance(exc.__cause__, (requests.Timeout,requests.ConnectionError)):raise
                log.info('geodata_retry service=%s attempt=2',params.get('service'))

    def _request_once(self, endpoint, params, kind='xml'):
        if endpoint not in ENDPOINTS.values():
            raise GeodataError('Endpoint is not allowlisted')
        start = time.monotonic()
        try:
            with requests.get(endpoint, params=params, timeout=(2, 5), stream=True,
                              allow_redirects=False, headers={'Accept': {
                                  'xml': 'application/xml,text/xml',
                                  'json': 'application/json,application/geo+json',
                              }[kind], 'User-Agent': 'ForestAI-Geodata/1.0'}) as r:
                if r.status_code != 200:
                    raise GeodataError(f'LVM GEO returned HTTP {r.status_code}')
                ct = r.headers.get('Content-Type', '').split(';')[0].strip().lower()
                allowed = {'xml': {'application/xml', 'text/xml', 'application/vnd.ogc.wms_xml'},
                           'json': {'application/json', 'application/geo+json', 'application/vnd.geo+json'}}
                if ct not in allowed[kind]:
                    raise GeodataError('Unexpected LVM GEO response content type')
                if int(r.headers.get('Content-Length', '0')) > MAX_BYTES:
                    raise GeodataError('LVM GEO response exceeds size limit')
                result = bytearray()
                for part in r.iter_content(32768):
                    result.extend(part)
                    if len(result) > MAX_BYTES or time.monotonic()-start > 9:
                        raise GeodataError('LVM GEO response exceeds size/time limit')
                return bytes(result)
        except requests.RequestException as e:
            log.warning('LVM GEO %s failed (%s)', params.get('request'), type(e).__name__)
            raise GeodataError('LVM GEO unavailable or request timed out') from e
        except (ValueError, OverflowError) as e:
            if isinstance(e, GeodataError):
                raise
            raise GeodataError('Malformed LVM GEO response') from e

    def _wms(self, endpoint, root, key):
        if local(root.tag) not in {'WMS_Capabilities', 'WMT_MS_Capabilities'}:
            raise GeodataError('WMS GetCapabilities was not confirmed')
        if root.attrib.get('version') != '1.1.1':
            raise GeodataError('WMS 1.1.1 was not confirmed')
        capability = next((e for e in root if local(e.tag) == 'Capability'), None)
        if capability is None:
            raise GeodataError('Missing WMS capability')
        request = next((e for e in capability if local(e.tag) == 'Request'), None)
        if request is None or not children(request, 'GetMap'):
            raise GeodataError('WMS GetMap is unavailable')
        formats = [e.text for e in children(children(request, 'GetMap')[0], 'Format')]
        if 'image/png' not in formats:
            raise GeodataError('WMS PNG format unavailable')
        layers = []

        def walk(node, inherited_crs=(), inherited_attribution=''):
            crs = sorted(set(inherited_crs) | {s for tag in ('SRS', 'CRS') for e in children(node, tag) for s in (e.text or '').split()})
            attribution = val(node, 'Attribution') or inherited_attribution
            name = val(node, 'Name')
            if name:
                layers.append({'id': key + '/' + name, 'name': name, 'title': val(node, 'Title') or name,
                               'abstract': val(node, 'Abstract'), 'attribution': attribution,
                               'crs': crs, 'wms': True, 'wfs': False, 'importable': False,
                               'type': 'WMS', 'endpoint': endpoint, 'service_key': key,
                               'metadata_url': endpoint + '?' + urlencode({'service':'WMS', 'version':'1.1.1', 'request':'GetCapabilities'})})
            for child in children(node, 'Layer'):
                walk(child, crs, attribution)
        for layer in children(capability, 'Layer'):
            walk(layer)
        if len(layers) > 5000:
            raise GeodataError('Too many advertised layers')
        return layers

    def _wfs(self, root):
        if local(root.tag) != 'WFS_Capabilities':
            raise GeodataError('WFS GetCapabilities was not confirmed')
        version = root.attrib.get('version')
        if version not in {'1.0.0', '1.1.0', '2.0.0'}:
            raise GeodataError('Unsupported WFS version')
        formats = set()
        can_get = False
        for e in root.iter():
            if local(e.tag) == 'GetFeature' or (local(e.tag) == 'Operation' and e.attrib.get('name') == 'GetFeature'):
                can_get = True
                for f in e.iter():
                    if local(f.tag) in {'Value', 'Format'} and f.text:
                        formats.add(f.text.strip())
                    if local(f.tag).lower() in {'json', 'geojson'}:
                        formats.add(local(f.tag))
        output = next((f for f in sorted(formats) if f.lower() in {'application/json', 'application/geo+json', 'json', 'geojson'}), None)
        if not can_get:
            raise GeodataError('WFS GetFeature unavailable')
        result = {}
        for e in root.iter():
            if local(e.tag) != 'FeatureType':
                continue
            name = val(e, 'Name')
            crs = [c.text.strip() for c in e if local(c.tag) in {'SRS', 'DefaultSRS', 'OtherSRS', 'DefaultCRS', 'OtherCRS'} and c.text]
            result[name] = {'title': val(e, 'Title') or name, 'abstract': val(e, 'Abstract'),
                            'wfs': True, 'wfs_version': version, 'wfs_format': output,
                            'wfs_crs': crs, 'importable': bool(output and any(is_wgs84(c) for c in crs))}
        return result

    def get_capabilities(self, refresh=False):
        with self._lock:
            if self._cache and time.monotonic() < self._expires and not refresh:
                return copy.deepcopy(self._cache)
            services, layers = [], []
            def discover(item):
                key, endpoint = item
                service = {'id': key, 'endpoint': endpoint, 'wms': False, 'wfs': False, 'errors': []}
                found = []
                try:
                    root = xml(self._request(endpoint, {'service': 'WMS', 'version': '1.1.1', 'request': 'GetCapabilities'}))
                    found = self._wms(endpoint, root, key)
                    service['wms'] = True
                except GeodataError as e:
                    service['errors'].append(str(e)); log.warning('LVM GEO %s WMS: %s', key, e)
                try:
                    root = xml(self._request(endpoint, {'service': 'WFS', 'version': '1.0.0', 'request': 'GetCapabilities'}))
                    vectors = self._wfs(root)
                    service['wfs'] = True
                    advertised_wms = {layer['name'] for layer in found}
                    for layer in found:
                        if layer['name'] in vectors:
                            vector = vectors[layer['name']]
                            # Preserve WMS attribution/title; WFS service-level
                            # provider identity is not a dataset attribution.
                            layer.update({k:v for k,v in vector.items() if k not in {'title','abstract'}})
                            layer['type'] = 'WMS / WFS'
                    for name, vector in vectors.items():
                        if name not in advertised_wms:
                            found.append({**vector, 'id': key+'/'+name, 'name': name,
                                'attribution': '', 'crs': vector['wfs_crs'], 'type': 'WFS',
                                'wms': False, 'endpoint': endpoint, 'service_key': key,
                                'metadata_url': endpoint+'?'+urlencode({'service':'WFS', 'version':vector['wfs_version'], 'request':'GetCapabilities'})})
                except GeodataError as e:
                    service['errors'].append(str(e)); log.warning('LVM GEO %s WFS: %s', key, e)
                return service, found
            with ThreadPoolExecutor(max_workers=len(ENDPOINTS)) as executor:
                for service, found in executor.map(discover, ENDPOINTS.items()):
                    services.append(service); layers.extend(found)
            checked = now()
            if any(s['wms'] or s['wfs'] for s in services): self._last_success_at = checked
            log.info('geodata_capabilities provider=LVM_GEO status=%s layer_count=%d', 'CONNECTED' if layers else 'UNAVAILABLE', len(layers))
            self._cache = {'provider': 'LVM_GEO', 'status': 'CONNECTED' if any(s['wms'] or s['wfs'] for s in services) else 'UNAVAILABLE',
                           'wms': any(s['wms'] for s in services), 'wfs': any(s['wfs'] for s in services),
                           'checked_at': checked, 'last_success_at': self._last_success_at, 'services': services, 'layers': layers,
                           'layer_count': len(layers)}
            self._expires = time.monotonic() + (900 if all(s['wms'] for s in services) else 60)
            return copy.deepcopy(self._cache)

    def health_check(self, refresh=False):
        result = self.get_capabilities(refresh)
        result.pop('layers', None)
        return result

    def list_services(self):
        return self.get_capabilities()['services']

    def list_layers(self):
        return self.get_capabilities()['layers']

    def get_layer_metadata(self, layer_id):
        layer = next((l for l in self.list_layers() if l['id'] == layer_id), None)
        if layer is None:
            raise GeodataError('Layer unavailable or not advertised by live capabilities')
        return layer

    def get_map_url(self, layer_id, bbox, width=512, height=512):
        layer = self.get_layer_metadata(layer_id)
        if not layer['wms']:
            raise GeodataError('This layer is not advertised by WMS')
        if not any(is_wgs84(c) for c in layer['crs']):
            raise GeodataError('Layer does not advertise EPSG:4326')
        bbox = validate_bbox(bbox)
        if not 1 <= width <= 2048 or not 1 <= height <= 2048:
            raise GeodataError('Invalid map dimensions')
        return layer['endpoint'] + '?' + urlencode({'service': 'WMS', 'request': 'GetMap', 'version': '1.1.1',
            'layers': layer['name'], 'styles': '', 'format': 'image/png', 'transparent': 'true',
            'srs': 'EPSG:4326', 'bbox': ','.join(map(str, bbox)), 'width': width, 'height': height})

    def _features(self, layer, *, bbox=None, feature_id=None, limit=50):
        if not layer.get('importable'):
            raise GeodataError('This layer has no confirmed WFS GeoJSON with EPSG:4326 support')
        if not 1 <= limit <= MAX_FEATURES:
            raise GeodataError('Feature limit must be between 1 and 100')
        version = layer['wfs_version']
        params = {'service': 'WFS', 'request': 'GetFeature', 'version': version,
                  'typeNames' if version == '2.0.0' else 'typeName': layer['name'],
                  'outputFormat': layer['wfs_format'], 'srsName': 'EPSG:4326',
                  'count' if version == '2.0.0' else 'maxFeatures': limit}
        if feature_id is not None:
            if not isinstance(feature_id, str) or not 1 <= len(feature_id) <= 300 or any(c in feature_id for c in ',\n\r\x00'):
                raise GeodataError('Unsupported external feature ID')
            params['resourceID' if version == '2.0.0' else 'featureID'] = feature_id
        else:
            w, s, e, n = validate_bbox(bbox)
            coords = [w, s, e, n] if version == '1.0.0' else [s, w, n, e]
            params['bbox'] = ','.join(map(str, coords)) + ',EPSG:4326'
        def finite_float(value):
            parsed = float(value)
            if not math.isfinite(parsed):
                raise ValueError('Nonfinite number')
            return parsed

        try:
            data = json.loads(self._request(layer['endpoint'], params, 'json'), parse_float=finite_float,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
        except (ValueError, UnicodeError, RecursionError) as e:
            if isinstance(e, GeodataError): raise
            raise GeodataError('Malformed WFS GeoJSON response') from e
        if not isinstance(data, dict) or data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list):
            raise GeodataError('Invalid WFS FeatureCollection')
        pending, nodes = [(data, 0)], 0
        while pending:
            value, depth = pending.pop(); nodes += 1
            if depth > 64 or nodes > 1000000:
                raise GeodataError('GeoJSON exceeds structural limits')
            if isinstance(value, dict):
                pending.extend((v, depth+1) for v in value.values())
            elif isinstance(value, list):
                pending.extend((v, depth+1) for v in value)
        crs = data.get('crs')
        if crs is not None:
            props = crs.get('properties') if isinstance(crs, dict) else None
            name = props.get('name') if isinstance(props, dict) else None
            if not isinstance(name, str) or not (is_wgs84(name) or name.upper().endswith('CRS84')):
                raise GeodataError('WFS returned unsupported CRS; no coordinates were converted')
        if len(data['features']) > limit:
            raise GeodataError('WFS exceeded requested feature limit')
        if any(not isinstance(f, dict) for f in data['features']):
            raise GeodataError('Invalid feature in WFS collection')
        if feature_id is not None and any(str(f.get('id')) != feature_id for f in data['features'] if isinstance(f, dict)):
            raise GeodataError('WFS did not honor the requested feature ID')
        return data

    def get_features(self, layer_id, bbox=None, geometry=None, limit=50):
        if geometry is not None:
            raise GeodataError('Use a limited bbox for version 1')
        validate_bbox(bbox)
        return self._features(self.get_layer_metadata(layer_id), bbox=bbox, limit=limit)

    def get_feature(self, layer_id, feature_id):
        data = self._features(self.get_layer_metadata(layer_id), feature_id=feature_id, limit=1)
        if not data['features']:
            raise GeodataError('Source feature no longer available; local boundary retained')
        return data['features'][0]
