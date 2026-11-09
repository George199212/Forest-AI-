"""Phase 2A fixtures are software tests only, never UI/demo data providers."""
import json
import time
from unittest.mock import Mock

import pytest

from test_john_deere import env, browser, connected, response, token, session, mocked, organization


def xml_response(xml, status=200):
    return Mock(status_code=status, content=xml.encode())


def setup_sequence(env, monkeypatch, orgs, resources=(), fleet='<Fleet xmlns="http://standards.iso.org/iso/15143/-3"/>'):
    service = connected(env)
    responses = [response({'links':[{'rel':'organizations','uri':env.CATALOG_URL+'orgs'}]}),response({'values':orgs}),
                 *resources, xml_response(fleet)]
    mock = mocked(env, monkeypatch, responses)
    return service, mock


def equipment_links(env):
    return {'links':[{'rel':'equipment','uri':env.CATALOG_URL+'org-equipment'}]}


def machine(env, **extra):
    return dict(id='test-only-machine', name='Test fixture only', **{'@type':'Machine'},
                **extra)


def test_zero_organizations_is_success(env, monkeypatch):
    from services.integrations.john_deere_diagnostics import Diagnostics, EMPTY_MESSAGE
    service, mock = setup_sequence(env,monkeypatch,[])
    result = Diagnostics(service).run()
    assert result['api_connection'] == 'WORKING'
    assert result['organizations'] == result['connected_organizations'] == 0
    assert result['equipment'] == result['machines'] == 0
    assert result['fleet']['status'] == 'empty'
    assert result['equipment_status'] == 'Waiting for organization data'
    assert result['machine_data'] == 'WAITING FOR REAL JOHN DEERE ORGANIZATION'
    assert result['message'] == EMPTY_MESSAGE
    assert result['errors'] == {}
    assert mock.call_count == 3
    with env._db() as conn:
        assert conn.execute('SELECT count(*) FROM sector_equipment').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM risks').fetchone()[0] == 0
    assert service.row()['status'] != 'ERROR'


def test_organization_with_equipment(env, monkeypatch):
    from services.integrations.john_deere_diagnostics import Diagnostics
    service, mock = setup_sequence(env,monkeypatch,[organization()],
        [response(equipment_links(env)),response({'values':[machine(env),dict(id='implement', **{'@type':'Implement'})]})])
    result = Diagnostics(service).run()
    assert result['organizations'] == result['connected_organizations'] == 1
    assert result['equipment'] == 2 and result['machines'] == 1
    assert result['equipment_status'] == 'OK'
    assert result['machine_data'] == 'AVAILABLE; TELEMETRY NOT TESTED'
    assert mock.call_count == 5  # no per-machine API calls


def test_organization_without_equipment(env, monkeypatch):
    from services.integrations.john_deere_diagnostics import Diagnostics
    service, mock = setup_sequence(env,monkeypatch,[organization()],
        [response(equipment_links(env)),response({'values':[]})])
    result = Diagnostics(service).run()
    assert result['equipment'] == result['machines'] == 0
    assert result['equipment_status'] == 'OK'
    assert result['errors'] == {}


def test_unconnected_organization_is_not_queried(env, monkeypatch):
    from services.integrations.john_deere_diagnostics import Diagnostics
    service, mock = setup_sequence(env,monkeypatch,[organization('connections')])
    result = Diagnostics(service).run()
    assert result['connected_organizations'] == 0
    assert result['equipment_status'] == 'Waiting for organization data'
    assert mock.call_count == 3


def test_missing_equipment_link_is_distinct_from_empty(env, monkeypatch):
    from services.integrations.john_deere_diagnostics import Diagnostics
    service, mock = setup_sequence(env,monkeypatch,[organization()],[response({'links':[]})])
    assert Diagnostics(service).run()['equipment_status'] == 'No equipment link returned'


def test_machine_with_and_without_location(env):
    from services.integrations.john_deere_machines import normalize
    found = normalize(machine(env,location={'lat':56.0,'lon':24.0,'timestamp':'2026-10-28T00:00:00Z'},
                              engineHours={'reading':{'valueAsDouble':123.5}},operatingHours=23))
    assert found['latitude'] == 56.0 and found['longitude'] == 24.0
    assert found['engine_hours'] == 123.5 and found['operating_hours'] == 23
    missing = normalize(machine(env))
    assert missing['latitude'] is missing['longitude'] is missing['engine_hours'] is None
    assert normalize(machine(env,location={'lat':1000,'lon':0}))['latitude'] is None


@pytest.mark.parametrize('method,relation', [('latest_location','locationHistory'),('location_history','locationHistory'),
    ('breadcrumbs','breadcrumbs'),('engine_hours','engineHours'),('hours_of_operation','hoursOfOperation'),
    ('alerts','alerts'),('device_state_reports','deviceStateReports')])
def test_machine_methods_follow_real_returned_links(env, monkeypatch, method, relation):
    from services.integrations.john_deere_machines import MachineService
    service = connected(env)
    uri = env.CATALOG_URL+'machines/test-only-machine/'+relation
    raw = machine(env,links=[dict(rel=relation,uri=uri)])
    payload = {'values':[{'reading':{'valueAsDouble':12},'definition':{'description':'Test alert only'}}]}
    mock = mocked(env, monkeypatch,[response(payload)])
    result = getattr(MachineService(service),method)(raw)
    assert result['values'] == payload['values']
    assert mock.call_args.args[1].startswith(uri)
    with env._db() as conn: assert conn.execute('SELECT count(*) FROM risks').fetchone()[0] == 0


def test_missing_machine_or_links_makes_no_request(env):
    from services.integrations.john_deere_machines import MachineService
    reader = MachineService(connected(env))
    assert reader.latest_location(machine(env))['status'] == 'unavailable'
    with pytest.raises(env.DeereError):reader.alerts({'links':[]})
    env.requests.request.assert_not_called()


@pytest.mark.parametrize('code', [401,403,429,500])
def test_diagnostic_http_errors_are_not_empty(env, monkeypatch, code):
    from services.integrations.john_deere_diagnostics import Diagnostics
    service = connected(env)
    responses = [response({'links':[dict(rel='organizations',uri=env.CATALOG_URL+'orgs')]}),response({},code)]
    if code == 401:responses += [response(token()),response({},401)]
    responses += [xml_response('',code)]
    if code == 401: responses += [response(token()),xml_response('',401)]
    mocked(env,monkeypatch,responses)
    result = Diagnostics(service).run()
    assert result['organizations'] is None
    assert result['api_connection'] == 'ERROR'
    assert result['fleet']['status'] == 'error'
    assert result['errors']
    assert not any(s in json.dumps(result) for s in ['access-private','refresh-private','test-secret'])


def test_expired_token_refresh_is_reported(env,monkeypatch):
    from services.integrations.john_deere_diagnostics import Diagnostics
    service=connected(env)
    tokens=service.tokens();tokens['expires_at']=time.time()-1;service.save_tokens(tokens)
    mocked(env,monkeypatch,[response(token()),response({'links':[dict(rel='organizations',uri=env.CATALOG_URL+'orgs')]}),
        response({'values':[]}),xml_response('<Fleet/>')])
    assert Diagnostics(service).run()['token'] == 'Refreshed'


def test_fleet_available_pagination_and_connections(env,monkeypatch):
    from services.integrations.john_deere_iso import FleetDiagnostics,FLEET_URL
    service=connected(env)
    mocked(env,monkeypatch,[xml_response('<Fleet xmlns="http://standards.iso.org/iso/15143/-3"><Equipment><EquipmentHeader/></Equipment><Links><rel>next</rel><href>https://sandboxaemp.deere.com/Fleet/2</href></Links><Links><rel>connections</rel><href>https://connections.deere.com/connections/test/select-organizations</href></Links></Fleet>'),xml_response('<Fleet><Equipment/></Fleet>')])
    result, actions=FleetDiagnostics(service).run()
    assert result['status']=='available' and result['machines']==2
    assert result['connection_status']=='Authorization required'
    assert 'connections' in actions


@pytest.mark.parametrize('content', ['<html/>','not xml','<!DOCTYPE Fleet [<!ENTITY x "test">]><Fleet/>'])
def test_fleet_invalid_xml_is_error(env,content):
    from services.integrations.john_deere_iso import parse_fleet
    with pytest.raises(env.DeereError):parse_fleet(content.encode())


def test_fleet_rejects_production_pagination(env):
    from services.integrations.john_deere_iso import parse_fleet
    with pytest.raises(env.DeereError):parse_fleet(b'<Fleet><Links><rel>next</rel><href>https://aemp.deere.com/Fleet/2</href></Links></Fleet>')


def test_fleet_204_is_empty(env,monkeypatch):
    from services.integrations.john_deere_iso import FleetDiagnostics
    mocked(env,monkeypatch,[xml_response('',204)])
    assert FleetDiagnostics(connected(env)).run()[0]['status']=='empty'


def test_fleet_cache_and_duplicate_click_cooldown(env,monkeypatch):
    from services.integrations.john_deere_diagnostics import Diagnostics
    service,mock=setup_sequence(env,monkeypatch,[])
    runner=Diagnostics(service);runner.run();runner.run()
    assert mock.call_count==3
    row=service.row();data=json.loads(row['diagnostics_json']);data['phase2a']['checked_at']-=61
    service.diagnostics(phase2a=data['phase2a'])
    mocked(env,monkeypatch,[response({'links':[dict(rel='organizations',uri=env.CATALOG_URL+'orgs')]}),response({'values':[]})])
    assert runner.run()['fleet']['status']=='empty'
    assert env.requests.request.call_count==2


def test_bind_reuses_existing_equipment_preserves_sector_and_values(env):
    from services.integrations.john_deere_machines import MachineService
    service=MachineService(connected(env))
    with env._db() as conn:
        eq=conn.execute("INSERT INTO sector_equipment(sector,equipment_code,model) VALUES('REAL-SECTOR','EQ-1','Existing model')").lastrowid
    service.bind_existing(eq,'test-org',machine(env,location={'lat':56,'lon':24}))
    with env._db() as conn:
        row=conn.execute('SELECT * FROM sector_equipment WHERE id=?',(eq,)).fetchone()
        assert row['sector']=='REAL-SECTOR' and row['model']=='Existing model'
        assert row['provider']=='john_deere' and row['latitude']==56
        assert conn.execute('SELECT count(*) FROM sector_equipment').fetchone()[0]==1
    with pytest.raises(env.DeereError):service.bind_existing(eq,'test-org',dict(id='other-machine'))


def test_binding_demo_equipment_forbidden(env):
    from services.integrations.john_deere_machines import MachineService
    with env._db() as conn:
        eq=conn.execute("INSERT INTO sector_equipment(sector,is_demo) VALUES('DEMO',1)").lastrowid
    with pytest.raises(env.DeereError):MachineService(connected(env)).bind_existing(eq,'org',machine(env))


def test_endpoint_is_authenticated_csrf_protected_and_secret_free(env,browser,monkeypatch):
    assert browser.post('/api/john-deere/test',auth=('bad','bad')).status_code==401
    assert browser.post('/api/john-deere/test').status_code==403
    service,mock=setup_sequence(env,monkeypatch,[])
    csrf=session(browser)
    result=browser.post('/api/john-deere/test',headers={'X-CSRF-Token':csrf})
    assert result.status_code==200
    assert result.json()['api_connection']=='WORKING'
    status=browser.get('/api/john-deere/status')
    assert status.json()['phase2a']['fleet']['status']=='empty'
    assert not any(s in result.text+status.text for s in ['access-private','refresh-private','test-secret'])


def test_schema_and_risk_mapping_readiness(env):
    import database
    from services.integrations.john_deere_machines import RISK_MAPPING
    database.init_db()
    with env._db() as conn:
        columns={r[1] for r in conn.execute('PRAGMA table_info(sector_equipment)')}
    assert {'provider','external_machine_id','engine_hours','operating_hours','latitude','last_alert'}<=columns
    assert len(RISK_MAPPING)==5 and all(r['entity_type']=='EQUIPMENT' and r['requires'] for r in RISK_MAPPING.values())


def test_snapshot_normalizes_real_linked_readings_without_writes(env,monkeypatch):
    from services.integrations.john_deere_machines import MachineService
    service=connected(env)
    raw=machine(env,links=[{'rel':rel,'uri':env.CATALOG_URL+'machines/test-only-machine/'+rel}
        for rel in ('locationHistory','engineHours','alerts')])
    mocked(env,monkeypatch,[response({'values':[{'location':{'lat':56,'lon':24},'time':'2026-10-28T00:00:00Z'}]}),
        response({'values':[{'reading':{'valueAsDouble':45.5,'unit':'Hours'},'time':'2026-10-28T00:00:00Z'}]}),
        response({'values':[{'id':'test-alert','severity':'WARNING','definition':{'description':'Test fixture only'},'time':'2026-10-28T00:00:00Z'}]})])
    record, resources=MachineService(service).snapshot(raw)
    assert record['latitude']==56 and record['longitude']==24
    assert record['engine_hours']==45.5
    assert json.loads(record['last_alert'])['id']=='test-alert'
    assert record['operating_hours'] is None
    with env._db() as conn:
        assert conn.execute('SELECT count(*) FROM sector_equipment').fetchone()[0]==0


def test_snapshot_without_location_or_links(env):
    from services.integrations.john_deere_machines import MachineService
    record, resources=MachineService(connected(env)).snapshot(machine(env))
    assert record['latitude'] is record['longitude'] is record['engine_hours'] is record['last_alert'] is None
    env.requests.request.assert_not_called()


def test_403_equipment_is_error_but_keeps_successful_connectivity(env,monkeypatch):
    from services.integrations.john_deere_diagnostics import Diagnostics
    service,mock=setup_sequence(env,monkeypatch,[organization()],[response(equipment_links(env)),response({},403)])
    result=Diagnostics(service).run()
    assert result['api_connection']=='WORKING'
    assert result['equipment_status'].startswith('Error')
    assert 'equipment:test' in result['errors']


def test_fleet_only_connection_action_is_safe_and_usable(env,monkeypatch):
    from services.integrations.john_deere_diagnostics import Diagnostics
    xml='<Fleet><Links><rel>connections</rel><href>https://connections.deere.com/connections/test/select-organizations</href></Links></Fleet>'
    service,mock=setup_sequence(env,monkeypatch,[],fleet=xml)
    result=Diagnostics(service).run()
    assert result['fleet']['status']=='empty'
    assert service.public_status()['can_authorize']
    assert service.connection_url('connections').startswith('https://connections.deere.com/')
    assert 'connections.deere.com' not in json.dumps(result)
