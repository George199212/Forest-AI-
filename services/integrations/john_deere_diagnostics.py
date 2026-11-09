"""Phase 2A read-only diagnostic orchestration; OAuth implementation is unchanged."""
import json
import time

from services.integrations import john_deere as jd
from services.integrations.john_deere_iso import FleetDiagnostics
from services.integrations.john_deere_machines import MachineService, normalize

EMPTY_MESSAGE = ('No John Deere organizations are available for this account.\n'
                 'OAuth and API connectivity are working correctly.\n'
                 'Connect a John Deere Operations Center organization with machine data to test telemetry.')


def initial_status(client):
    basic = client.public_status()
    count = basic.get('organizations', 0)
    connected = sum(o['connection_status'] == 'Connected' for o in basic.get('organizations_list', []))
    working = basic.get('oauth') == 'OK' and basic.get('api_catalog') == 'OK' and basic.get('organizations_status') == 'OK'
    return dict(oauth='OK' if basic.get('oauth') == 'OK' else 'ERROR', token=basic.get('token', 'Error'),
                api_catalog=basic.get('api_catalog', 'Not checked'), organizations=count,
                connected_organizations=connected, equipment=0, machines=0,
                equipment_status='Waiting for organization data' if not connected else 'Not tested',
                fleet={'status': 'not tested', 'machines': None}, errors={},
                api_connection='WORKING' if working else 'NOT VERIFIED',
                organization_data='AVAILABLE' if connected else 'WAITING',
                machine_data='WAITING FOR REAL JOHN DEERE ORGANIZATION' if not connected else 'NOT TESTED',
                message=EMPTY_MESSAGE if working and count == 0 else '', checked_at=None)


class Diagnostics:
    def __init__(self, client):
        self.client = client

    def status(self):
        row = self.client.row()
        data = json.loads(row['diagnostics_json']).get('phase2a') if row else None
        result = data or initial_status(self.client)
        # Token validity is evaluated now, not only at the last diagnostic run.
        token = self.client.public_status().get('token')
        result['token'] = ('Error' if token == 'Refresh failed' else token if token in ('Expired', 'Valid') else 'Error') if not (result.get('token') == 'Refreshed' and token == 'Valid') else 'Refreshed'
        if result['token'] in ('Error', 'Expired'):
            result['api_connection'] = 'NOT VERIFIED'
        return result

    def run(self):
        with jd._lock:
            return self._run()

    def _run(self):
        previous = self.client.row()
        if previous:
            cached = json.loads(previous['diagnostics_json']).get('phase2a', {})
            if cached.get('checked_at') and time.time()-cached['checked_at'] < 60:
                return self.status()  # avoid duplicate clicks and unnecessary rate consumption
        result = initial_status(self.client)
        result.update(checked_at=time.time(), message='', equipment=0, machines=0,
                      equipment_status='Waiting for organization data', errors={},
                      machine_api_status={rel:'Waiting for real machine data' for rel in
                        ('locationHistory', 'breadcrumbs', 'engineHours', 'hoursOfOperation', 'alerts', 'deviceStateReports')})
        organizations = None
        try:
            organizations = self.client.organizations()
            result.update(api_catalog='OK', organizations=len(organizations),
                          connected_organizations=sum(o['connection_status']=='Connected' for o in organizations),
                          api_connection='WORKING', organization_data='WAITING')
            if not organizations:
                result['message'] = EMPTY_MESSAGE
        except jd.DeereError as exc:
            current = self.client.public_status()
            result.update(api_catalog=current.get('api_catalog', 'ERROR'), organizations=None,
                          connected_organizations=None, api_connection='ERROR', organization_data='NOT VERIFIED',
                          machine_data='NOT VERIFIED', equipment_status='Not tested: organizations request failed')
            result['errors']['organizations'] = str(exc)

        machines, equipment = {}, {}
        if organizations:
            reader = MachineService(self.client)
            connected = [o for o in organizations if o['connection_status']=='Connected']
            result['organization_data'] = 'AVAILABLE' if connected else 'WAITING'
            result['equipment_status'] = 'No equipment link returned' if connected else 'Waiting for organization data'
            for org in connected:
                try:
                    detail = self.client.get(org['links']['self']) if org['links'].get('self') else {}
                    rels = jd.links(detail)
                    for relation in ('equipment', 'machines'):
                        if not rels.get(relation): continue
                        for raw in reader.collection(rels[relation]):
                            rec = normalize(raw)
                            key = (org['id'], rec['external_machine_id'])
                            equipment[key] = rec
                            is_machine = (relation == 'machines' or str(raw.get('@type','')).lower() == 'machine'
                                          or any(str(raw.get(key,'')).lower() == 'machine' for key in ('equipmentClass', 'equipmentType', 'type'))
                                          or 'machine' in jd.links(raw))
                            if is_machine:
                                machines[key] = rec
                                discovered = jd.links(raw)
                                for rel in result['machine_api_status']:
                                    if rel in discovered: result['machine_api_status'][rel] = 'Link discovered; telemetry not requested'
                        result['equipment_status'] = 'OK'  # an empty returned collection is success
                except jd.DeereError as exc:
                    result['errors']['equipment:'+org['id']] = str(exc)
            result.update(equipment=len(equipment), machines=len(machines))
            if any(k.startswith('equipment:') for k in result['errors']):
                result['equipment_status'] = 'Error (counts may be incomplete)'
                result['machine_data'] = 'NOT VERIFIED'
            elif machines:
                result['machine_data'] = 'AVAILABLE; TELEMETRY NOT TESTED'
            else:
                result['machine_data'] = 'WAITING FOR REAL JOHN DEERE MACHINE DATA'
        elif organizations == []:
            result['machine_data'] = 'WAITING FOR REAL JOHN DEERE ORGANIZATION'

        # ISO is a separate service, but the approved eq1 token can authenticate it.
        # Cache successful Fleet diagnostics for one hour, per Deere polling guidance.
        old_fleet = json.loads(previous['diagnostics_json']).get('phase2a', {}).get('fleet', {}) if previous else {}
        try:
            if old_fleet.get('status') in ('available', 'empty') and time.time()-old_fleet.get('checked_at', 0) < 3600:
                result['fleet'] = old_fleet
            elif previous:
                result['fleet'], actions = FleetDiagnostics(self.client).run()
                if actions:
                    row = self.client.row()
                    current_actions = json.loads(row['diagnostics_json']).get('connection_links', {})
                    for relation, uri in actions.items():
                        current_actions['manage_connection' if relation == 'manage_connections' else relation] = uri
                    self.client.diagnostics(connection_links=current_actions)
            else:
                result['fleet'] = {'status':'not tested', 'machines':None}
        except jd.DeereError as exc:
            result['fleet'] = {'status':'error', 'machines':None}
            result['errors']['fleet'] = str(exc)

        current = self.client.row()
        token_status = self.client.public_status().get('token')
        result['token'] = ('Error' if token_status == 'Refresh failed' else 'Expired' if token_status == 'Expired' else
                           'Refreshed' if previous and current and previous['encrypted_tokens'] != current['encrypted_tokens'] else
                           'Valid' if current else 'Error')
        self.client.diagnostics(phase2a=result)
        return result
