"""Link-based machine reads and explicit binding to existing sector_equipment.

Diagnostics never invokes binding or risk creation. No simulated data source.
"""
import json
import math
import sqlite3
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from services.integrations import john_deere as jd

# Readiness contract only: no rule evaluation or incident creation in Phase 2A.
RISK_MAPPING = {
    'machine_alert': {'rule_code': 'EQUIPMENT_BREAKDOWN', 'entity_type': 'EQUIPMENT', 'requires': ['real alert', 'equipment binding']},
    'stops_reporting': {'rule_code': 'DEERE_TELEMETRY_OFFLINE', 'entity_type': 'EQUIPMENT', 'requires': ['last real report', 'configured expected interval', 'equipment binding']},
    'outside_sector': {'rule_code': 'DEERE_SECTOR_EXIT', 'entity_type': 'EQUIPMENT', 'requires': ['real GPS', 'assigned sector boundary', 'equipment binding']},
    'restricted_zone': {'rule_code': 'DEERE_ZONE_VIOLATION', 'entity_type': 'EQUIPMENT', 'requires': ['real GPS', 'configured restricted zone', 'equipment binding']},
    'unexpected_movement': {'rule_code': 'DEERE_MOVEMENT_ANOMALY', 'entity_type': 'EQUIPMENT', 'requires': ['real track', 'configured movement policy', 'equipment binding']},
}


def values(payload):
    result = payload if isinstance(payload, list) else payload.get('values') if isinstance(payload, dict) else None
    if not isinstance(result, list) or any(not isinstance(v, dict) for v in result):
        raise jd.DeereError('Deere returned an invalid resource collection.')
    return result


def number(value):
    if isinstance(value, dict):
        value = value.get('valueAsDouble', value.get('valueAsInteger'))
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def label(value):
    if isinstance(value, dict):
        value = value.get('name') or value.get('value')
    return str(value) if isinstance(value, (str, int, float)) else None


def normalize(machine):
    identity = machine.get('principalId') or machine.get('id')
    if identity is None or str(identity).strip() == '':
        raise jd.DeereError('A real Deere equipment identifier is required.')
    # Missing telemetry stays NULL, including missing coordinates (never 0,0).
    location = machine.get('location') or {}
    if not isinstance(location, dict): location = {}
    lat, lon = number(location.get('lat')), number(location.get('lon'))
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        lat = lon = None
    reading = machine.get('engineHours') or {}
    return dict(provider='john_deere', external_machine_id=str(identity),
                machine_name=label(machine.get('name')), type=label(machine.get('equipmentType') or machine.get('type')),
                brand=label(machine.get('make') or machine.get('brand')), model=label(machine.get('model')),
                serial_number=label(machine.get('serialNumber')), latitude=lat, longitude=lon,
                location_timestamp=location.get('timestamp') or machine.get('locationTimestamp'),
                engine_hours=number(reading.get('reading', reading)) if isinstance(reading, dict) else number(reading),
                operating_hours=number(machine.get('operatingHours')), machine_status=label(machine.get('status')),
                last_alert=None, last_synchronization_time=None)


class MachineService:
    def __init__(self, client):
        self.client = client

    def collection(self, uri):
        found, seen = [], set()
        while uri:
            if uri in seen or len(seen) >= 100:
                raise jd.DeereError('Deere resource pagination exceeded its safe limit.')
            seen.add(uri)
            page = self.client.get(uri)
            found.extend(values(page))
            uri = jd.links(page).get('nextPage')
        return found

    def read(self, machine, relation, **params):
        normalize(machine)  # Do not call machine-specific APIs without an identifier.
        uri = jd.links(machine).get(relation)
        if not uri:
            return {'status': 'unavailable', 'values': []}
        uri = jd.safe_link(uri)
        if params:
            p = urlsplit(uri)
            query = dict(parse_qsl(p.query)); query.update(params)
            uri = urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), ''))
        return {'status': 'available', 'values': self.collection(uri)}

    def latest_location(self, machine):
        result = self.read(machine, 'locationHistory', lastKnown='true')
        if result['status'] == 'unavailable':
            result = self.read(machine, 'breadcrumbs', lastKnown='true')
        return result

    def location_history(self, machine):
        return self.read(machine, 'locationHistory')

    def breadcrumbs(self, machine):
        return self.read(machine, 'breadcrumbs')

    def engine_hours(self, machine):
        return self.read(machine, 'engineHours')

    def hours_of_operation(self, machine):
        return self.read(machine, 'hoursOfOperation')

    def alerts(self, machine):
        return self.read(machine, 'alerts')

    def device_state_reports(self, machine):
        return self.read(machine, 'deviceStateReports', lastKnown='true')

    def snapshot(self, machine):
        """Read optional linked telemetry for a real machine; no persistence/risks.

        Explicit future synchronization entry point, intentionally not called by
        diagnostic sequence. Missing resources/fields remain unavailable/NULL.
        Hours-of-operation events are not misrepresented as cumulative hours.
        """
        record = normalize(machine)
        resources = {}
        for name, method in [('location', self.latest_location), ('engine_hours', self.engine_hours),
                             ('hours_of_operation', self.hours_of_operation), ('alerts', self.alerts),
                             ('device_state_reports', self.device_state_reports)]:
            resources[name] = method(machine)
        locations = resources['location']['values']
        if locations:
            point = max(locations, key=lambda item: str(item.get('time') or item.get('createTimestamp') or ''))
            loc = point.get('location') or point
            parsed = normalize(dict(id=record['external_machine_id'], location=loc))
            record.update(latitude=parsed['latitude'], longitude=parsed['longitude'],
                          location_timestamp=point.get('time') or point.get('createTimestamp') or loc.get('timestamp'))
        readings = resources['engine_hours']['values']
        if readings:
            latest = max(readings, key=lambda item: str(item.get('time') or ''))
            record['engine_hours'] = number(latest.get('reading'))
        alerts = resources['alerts']['values']
        if alerts:
            alert = max(alerts, key=lambda item: str(item.get('time') or ''))
            definition = alert.get('definition') if isinstance(alert.get('definition'), dict) else {}
            record['last_alert'] = json.dumps({key: value for key, value in {
                'id': label(alert.get('id')), 'time': label(alert.get('time')),
                'severity': label(alert.get('severity')), 'description': label(definition.get('description')),
            }.items() if value is not None})
        record['last_synchronization_time'] = time.time()
        return record, resources

    def bind_existing(self, equipment_id, organization_id, machine):
        """Future explicit mapping action. Never auto-create or infer a sector.

        Call only with a freshly fetched real Deere response. The current UI and
        diagnostic routes intentionally do not expose synchronization writes.
        """
        record = normalize(machine)
        record.update(external_account_id=self.client.account, external_organization_id=str(organization_id))
        record['last_synchronization_time'] = time.time()
        with jd._db() as conn:
            row = conn.execute('SELECT * FROM sector_equipment WHERE id=?', (equipment_id,)).fetchone()
            if not row or row['is_demo'] or not row['sector']:
                raise jd.DeereError('Bind Deere only to existing real equipment assigned to a sector.')
            if row['provider'] and (row['provider'] != 'john_deere' or
                    row['external_account_id'] != self.client.account or
                    row['external_organization_id'] != str(organization_id) or
                    row['external_machine_id'] != record['external_machine_id']):
                raise jd.DeereError('This Forest AI equipment is already bound to another external machine.')
            # Preserve previously known values when optional fields are absent.
            updates = {key: value for key, value in record.items() if value is not None}
            try:
                conn.execute('UPDATE sector_equipment SET '+','.join(key+'=?' for key in updates)+' WHERE id=?',
                             (*updates.values(), equipment_id))
            except sqlite3.IntegrityError:
                raise jd.DeereError('This Deere machine is already bound to Forest AI equipment.') from None
        return equipment_id
