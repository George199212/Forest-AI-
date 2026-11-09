"""Read-only access to the configured local VMD compartment dataset.

No database, provider request, sector import, file upload or caller-supplied path.
"""
import json
import math
from pathlib import Path

SOURCE_FILE = Path(__file__).resolve().parents[2] / 'lvm_3_sectors.geojson'
MAX_BYTES = 32 * 1024 * 1024
MAX_FEATURES = 10000


class VmdTestDataError(ValueError):
    def __init__(self, message, status_code=422):
        super().__init__(message)
        self.status_code = status_code


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Nonfinite number')
    return number


def _nonfinite(_):
    raise ValueError('Nonfinite number')


def read_test_compartments():
    try:
        with SOURCE_FILE.open('rb') as source:
            raw = source.read(MAX_BYTES + 1)
    except OSError as exc:
        raise VmdTestDataError('VMD test data temporarily unavailable', 503) from exc
    if len(raw) > MAX_BYTES:
        raise VmdTestDataError('VMD test GeoJSON exceeds the size limit')
    try:
        data = json.loads(raw, parse_float=_finite_float, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise VmdTestDataError('Invalid VMD test GeoJSON') from exc
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection':
        raise VmdTestDataError('VMD test data must be a GeoJSON FeatureCollection')
    crs = data.get('crs')
    if crs is not None:
        props = crs.get('properties') if isinstance(crs, dict) else None
        name = props.get('name') if isinstance(props, dict) else None
        if name not in {'urn:ogc:def:crs:OGC:1.3:CRS84', 'CRS:84', 'EPSG:4326', 'urn:ogc:def:crs:EPSG::4326'}:
            raise VmdTestDataError('VMD test data must use WGS84 longitude/latitude coordinates')
    features = data.get('features')
    if not isinstance(features, list):
        raise VmdTestDataError('Invalid VMD test feature list')
    if not features:
        raise VmdTestDataError('No VMD test compartments found')
    if len(features) > MAX_FEATURES:
        raise VmdTestDataError('Local VMD dataset exceeds the feature limit; use a filtered dataset')
    from shapely.geometry import Polygon
    for feature in features:
        if not isinstance(feature, dict) or feature.get('type') != 'Feature':
            raise VmdTestDataError('Invalid VMD test feature')
        if not isinstance(feature.get('properties'), dict):
            raise VmdTestDataError('Invalid VMD test feature properties')
        geometry = feature.get('geometry')
        if not isinstance(geometry, dict) or geometry.get('type') != 'Polygon':
            raise VmdTestDataError('VMD test features must all be Polygon geometries')
        rings = geometry.get('coordinates')
        if not isinstance(rings, list) or not rings:
            raise VmdTestDataError('Empty VMD test polygon')
        count = 0
        for ring in rings:
            if not isinstance(ring, list) or len(ring) < 4:
                raise VmdTestDataError('Invalid VMD test polygon ring')
            count += len(ring)
            if count > 10000 or ring[0] != ring[-1]:
                raise VmdTestDataError('VMD test polygon must have bounded, closed rings')
            for position in ring:
                if (not isinstance(position, list) or len(position) != 2 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in position) or
                    not (-180 <= position[0] <= 180 and -90 <= position[1] <= 90)):
                    raise VmdTestDataError('Invalid WGS84 coordinates in VMD test polygon')
        polygon = Polygon(rings[0], rings[1:])
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise VmdTestDataError('Invalid VMD test polygon geometry')
    return data
