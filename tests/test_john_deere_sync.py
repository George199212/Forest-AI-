"""Test-only provider fixtures; no runtime demo adapter exists for Deere."""
import json
import time
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import requests
from test_john_deere import env,browser,connected,response,token,session,mocked,organization


@pytest.fixture(autouse=True)
def sync_settings(monkeypatch):
    monkeypatch.setenv('JOHN_DEERE_SYNC_MIN_INTERVAL_SECONDS','0')


def org(identity='org1'):
    result=organization();result['id']=identity;result['name']='Test organization only'
    result['links'][0]['uri']='https://sandboxapi.deere.com/platform/organizations/'+identity
    return result


def machine(identity='fixture1',relations=(),**fields):
    return dict(id=identity,name='Test fixture only',make='Test make',model='Test model',
                **{'@type':'Machine'},links=[dict(rel=r,uri='https://sandboxapi.deere.com/platform/machines/'+identity+'/'+r) for r in relations],**fields)


def sync_case(env,monkeypatch,orgs,machines,capabilities=(),kind='all'):
    connected(env)
    payloads=[response({'links':[dict(rel='organizations',uri=env.CATALOG_URL+'orgs')]}),response({'values':orgs})]
    for organization in orgs:
        payloads += [response({'links':[dict(rel='machines',uri=env.CATALOG_URL+'orgs/'+organization['id']+'/machines')]}),response({'values':machines})]
        if kind in ('all','telemetry'):payloads += list(capabilities)
    mock=mocked(env,monkeypatch,payloads)
    from services.integrations.john_deere_sync import Sync
    runner=Sync('pytest');result=runner.run(kind)
    return runner,result,mock


def stamp(age=0):return datetime.fromtimestamp(time.time()-age,timezone.utc).isoformat()


def point():return {'point':{'lat':56.95,'lon':24.1},'eventTimestamp':'2026-10-20T12:00:00Z'}


@pytest.mark.parametrize('org_count,machine_count',[(1,0),(1,1),(1,3),(2,1),(2,3),(0,0)])
def test_customer_discovery_and_idempotency(env,monkeypatch,org_count,machine_count):
    from services.integrations.john_deere_sync import public_machines
    orgs=[org(str(i)) for i in range(org_count)]
    machines=[machine(str(i)) for i in range(machine_count)]
    for _ in range(2):
        runner,result,mock=sync_case(env,monkeypatch,orgs,machines,kind='machines')
        assert result['status']==('OK' if org_count and machine_count else 'EMPTY')
    with env._db() as conn:
        assert conn.execute('SELECT count(*) FROM integration_organizations').fetchone()[0]==org_count
        assert conn.execute("SELECT count(*) FROM sector_equipment WHERE provider='john_deere'").fetchone()[0]==(machine_count if org_count else 0)
        assert conn.execute('SELECT count(*) FROM integration_sync_runs').fetchone()[0]==2
    assert len(public_machines())==(machine_count if org_count else 0)
    for row in public_machines():assert row['sector']==''


def test_org_only_sync_does_not_discover_machines(env,monkeypatch):
    runner,result,mock=sync_case(env,monkeypatch,[],[],kind='organizations')
    assert result['status']=='EMPTY' and mock.call_count==2


def test_real_location_reuses_gps_history_and_is_deduplicated(env,monkeypatch):
    from services.integrations.john_deere_sync import public_machines
    raw=machine(relations=['locationHistory'])
    for _ in range(2):
        runner,result,mock=sync_case(env,monkeypatch,[org()],[raw],capabilities=[response({'values':[point()]}),response({'values':[point()]})])
        assert result['status']=='OK'
    row=public_machines()[0]
    assert row['latitude']==56.95 and row['longitude']==24.1
    assert row['geofence_status']=='UNKNOWN'
    with env._db() as conn:
        gps=conn.execute('SELECT * FROM vehicle_gps_pings').fetchall()
        assert len(gps)==1
        assert gps[0]['equipment_id']==row['id'] and gps[0]['provider']==gps[0]['source']=='john_deere'
        assert gps[0]['source_timestamp']==point()['eventTimestamp']
        assert gps[0]['inside_boundary'] is None
        assert conn.execute('SELECT count(*) FROM risks').fetchone()[0]==0


def test_machine_without_gps_never_gets_default_coordinates(env,monkeypatch):
    from services.integrations.john_deere_sync import public_machines
    runner,result,mock=sync_case(env,monkeypatch,[org()],[machine()])
    assert result['status']=='OK'
    row=public_machines()[0]
    assert row['latitude'] is row['longitude'] is None
    assert row['telemetry_health']=='UNKNOWN'


def test_engine_hours_and_partial_failure(env,monkeypatch):
    from services.integrations.john_deere_sync import public_machines
    runner,result,mock=sync_case(env,monkeypatch,[org()],[machine(relations=['engineHours','alerts'])],capabilities=[
        response({'values':[{'reading':{'valueAsDouble':123.5},'time':stamp()}]}),response({},403)])
    assert result['status']=='PARTIAL'
    assert public_machines()[0]['engine_hours']==123.5
    assert result['errors']==[{'stage':'alerts','status':'PERMISSION REQUIRED'}]


def test_alert_risk_identity_survives_replays_and_closed_risk(env,monkeypatch):
    alert={'id':'alert-test1','time':stamp(),'severity':'HIGH','definition':{'description':'Test alert only'}}
    for _ in range(2):
        runner,result,mock=sync_case(env,monkeypatch,[org()],[machine(relations=['alerts'])],capabilities=[response({'values':[alert]})])
        assert result['status']=='OK'
    with env._db() as conn:
        events=conn.execute('SELECT * FROM integration_provider_events').fetchall()
        risks=conn.execute('SELECT * FROM risks').fetchall()
        assert len(events)==len(risks)==1
        assert events[0]['external_event_id']=='alert-test1' and events[0]['risk_id']==risks[0]['id']
        assert risks[0]['entity_type']=='EQUIPMENT' and risks[0]['data_origin']=='REAL'
        conn.execute("UPDATE risks SET status='RESOLVED'")
    runner,result,mock=sync_case(env,monkeypatch,[org()],[machine(relations=['alerts'])],capabilities=[response({'values':[alert]})])
    with env._db() as conn:assert conn.execute('SELECT count(*) FROM risks').fetchone()[0]==1


def test_informational_alert_does_not_fabricate_equipment_risk(env,monkeypatch):
    alert={'id':'info','severity':'INFO','color':'GRAY','definition':{'description':'Information only'}}
    sync_case(env,monkeypatch,[org()],[machine(relations=['alerts'])],capabilities=[response({'values':[alert]})])
    with env._db() as conn:
        assert conn.execute('SELECT count(*) FROM integration_provider_events').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM risks').fetchone()[0]==0


def test_missing_machines_are_not_deleted(env,monkeypatch):
    sync_case(env,monkeypatch,[org()],[machine()],kind='machines')
    runner,result,mock=sync_case(env,monkeypatch,[org()],[],kind='machines')
    assert result['status']=='EMPTY'
    with env._db() as conn:assert conn.execute('SELECT count(*) FROM sector_equipment').fetchone()[0]==1


@pytest.mark.parametrize('code,expected',[(401,'AUTH REQUIRED'),(403,'PERMISSION REQUIRED'),(404,'RESOURCE UNAVAILABLE'),(429,'RATE LIMITED'),(500,'PROVIDER ERROR')])
def test_sync_error_classes(env,monkeypatch,code,expected):
    connected(env)
    payloads=[response({},code)]
    if code==401:payloads += [response(token()),response({},401)]
    if code==429:payloads[0].headers={'Retry-After':'120'}
    mocked(env,monkeypatch,payloads)
    from services.integrations.john_deere_sync import Sync
    result=Sync('pytest').run('all')
    assert result['status']==expected
    assert 'access-private' not in json.dumps(result)
    if code==429:
        assert Sync('pytest').run('all')['status']=='RATE LIMITED'
        assert env.requests.request.call_count==1


def test_expired_token_reuses_existing_refresh(env,monkeypatch):
    service=connected(env);t=service.tokens();t['expires_at']=0;service.save_tokens(t)
    mocked(env,monkeypatch,[response(token()),response({'links':[dict(rel='organizations',uri=env.CATALOG_URL+'orgs')]}),response({'values':[]})])
    from services.integrations.john_deere_sync import Sync
    assert Sync('pytest').run('all')['status']=='EMPTY'
    assert service.tokens()['expires_at']>time.time()
    assert 'access-private' not in service.row()['encrypted_tokens']


def test_refresh_failure_stops_safely(env,monkeypatch):
    service=connected(env);t=service.tokens();t['expires_at']=0;service.save_tokens(t)
    mocked(env,monkeypatch,[response({},400)])
    from services.integrations.john_deere_sync import Sync
    assert Sync('pytest').run('all')['status']=='AUTH REQUIRED'


def test_timeout(env,monkeypatch):
    connected(env);mocked(env,monkeypatch,[requests.Timeout('must not leak access-private')])
    from services.integrations.john_deere_sync import Sync
    result=Sync('pytest').run('all')
    assert result['status']=='TEMPORARY ERROR'
    assert 'access-private' not in json.dumps(result)


def test_later_machine_runs_after_earlier_permission_failure(env,monkeypatch):
    runner,result,mock=sync_case(env,monkeypatch,[org()],[machine('first',['alerts']),machine('second',['engineHours'])],
        capabilities=[response({},403),response({'values':[{'reading':{'valueAsDouble':12}}]})])
    assert result['status']=='PARTIAL'
    assert runner.status()['counts']['machines']==2
    with env._db() as conn:assert conn.execute("SELECT engine_hours FROM sector_equipment WHERE external_machine_id='second'").fetchone()[0]==12


def test_sector_assignment_and_geo_evaluation(env,monkeypatch):
    from services.integrations.john_deere_sync import assign_sector,public_machines
    sync_case(env,monkeypatch,[org()],[machine(relations=['locationHistory'])],capabilities=[response({'values':[point()]}),response({'values':[]})])
    with env._db() as conn:
        conn.execute("INSERT INTO sectors(name,boundary_json,data_origin) VALUES('REAL',?,'REAL')",(json.dumps([[56,23],[56,25],[58,25],[58,23]]),))
    assign_sector('pytest',public_machines()[0]['id'],'REAL')
    assert public_machines()[0]['geofence_status']=='INSIDE'
    assign_sector('pytest',public_machines()[0]['id'],'')
    assert public_machines()[0]['geofence_status']=='UNKNOWN'
    with pytest.raises(env.DeereError):assign_sector('pytest',public_machines()[0]['id'],'invented')


def test_health_configurable_and_unknown(env,monkeypatch):
    from services.integrations.john_deere_sync import health
    assert health(None)=='UNKNOWN'
    assert health(stamp())=='LIVE'
    assert health(stamp(21601))=='STALE'
    assert health(stamp(86401))=='OFFLINE'
    monkeypatch.setenv('JOHN_DEERE_TELEMETRY_STALE_SECONDS','60')
    assert health(stamp(61))=='STALE'


def test_map_objects_and_protected_sync_routes(env,browser,monkeypatch):
    assert browser.post('/api/john-deere/sync/all').status_code==403
    assert browser.get('/api/map/machines',auth=('bad','bad')).status_code==401
    sync_case(env,monkeypatch,[org()],[machine()],kind='machines')
    rows=browser.get('/api/map/machines').json()
    assert rows[0]['provider']=='john_deere'
    assert 'provider_links_json' not in rows[0]
    assert 'external_account_id' not in rows[0]
    assert isinstance(browser.get('/api/objects').json(),list)
    assert isinstance(browser.get('/api/map').json(),list)
    status=browser.get('/api/john-deere/status')
    assert status.json()['phase2b']['counts']['machines']==1
    assert not any(secret in status.text for secret in ['access-private','refresh-private','test-secret'])


def test_empty_sync_endpoint_and_cross_origin_csrf(env,browser,monkeypatch):
    connected(env)
    csrf=session(browser)
    assert browser.post('/api/john-deere/sync/all',headers={'X-CSRF-Token':csrf,'Origin':'https://evil.example'}).status_code==403
    assert browser.post('/api/john-deere/sync/invalid',headers={'X-CSRF-Token':csrf}).status_code==400
    mocked(env,monkeypatch,[response({'links':[dict(rel='organizations',uri=env.CATALOG_URL+'orgs')]}),response({'values':[]})])
    result=browser.post('/api/john-deere/sync/all',headers={'X-CSRF-Token':csrf})
    assert result.status_code==200 and result.json()['status']=='EMPTY'
    assert 'access-private' not in result.text


def test_missing_metadata_does_not_erase_previous_values(env,monkeypatch):
    sync_case(env,monkeypatch,[org()],[machine()],kind='machines')
    sync_case(env,monkeypatch,[org()],[{'id':'fixture1','@type':'Machine','links':[]}],kind='machines')
    with env._db() as conn:
        row=conn.execute('SELECT machine_name,brand,model,status FROM sector_equipment').fetchone()
        assert row['machine_name']=='Test fixture only' and row['brand']=='Test make'
        assert row['status'] is None


def test_older_gps_does_not_replace_newest_location(env,monkeypatch):
    newer={'point':{'lat':57,'lon':24},'eventTimestamp':'2026-10-21T12:00:00Z'}
    sync_case(env,monkeypatch,[org()],[machine(relations=['locationHistory'])],capabilities=[response({'values':[newer]}),response({'values':[point()]})])
    with env._db() as conn:
        assert conn.execute('SELECT latitude FROM sector_equipment').fetchone()[0]==57
        assert conn.execute('SELECT count(*) FROM vehicle_gps_pings').fetchone()[0]==2


def test_auth_failure_mid_machine_stops_later_calls(env,monkeypatch):
    runner,result,mock=sync_case(env,monkeypatch,[org()],[machine('first',['engineHours']),machine('second',['alerts'])],
        capabilities=[response({},401),response({},400)])
    assert result['status']=='AUTH REQUIRED'
    assert mock.call_count==6


def test_telemetry_device_and_operating_events(env,monkeypatch):
    raw=machine(relations=['hoursOfOperation','deviceStateReports'])
    runner,result,mock=sync_case(env,monkeypatch,[org()],[raw],capabilities=[
        response({'values':[{'startDate':stamp(100),'endDate':stamp(),'engineState':1}]}),
        response({'values':[{'time':stamp(),'terminalPowerState':0,'gpsError':0,'wifiSSID':'must-not-store'}]})])
    assert result['status']=='OK'
    with env._db() as conn:
        row=conn.execute('SELECT device_status,operating_hours FROM sector_equipment').fetchone()
        assert row['operating_hours'] is None
        assert json.loads(row['device_status'])['terminalPowerState']==0
        assert 'wifiSSID' not in ''.join(str(r[0]) for r in conn.execute('SELECT normalized_payload_json FROM integration_records'))


def test_restricted_demo_geometry_is_never_used(env,monkeypatch):
    sync_case(env,monkeypatch,[org()],[machine(relations=['locationHistory'])],capabilities=[response({'values':[point()]}),response({'values':[]})])
    with env._db() as conn:assert conn.execute('SELECT restricted_zone_status FROM sector_equipment').fetchone()[0]=='UNKNOWN'


def test_partial_risk_repeated_alert_without_id_is_deduplicated(env,monkeypatch):
    alert={'time':'2026-10-20T12:00:00Z','severity':'MEDIUM','definition':{'description':'No ID fixture alert'}}
    for _ in range(2):sync_case(env,monkeypatch,[org()],[machine(relations=['alerts'])],capabilities=[response({'values':[alert]})])
    with env._db() as conn:
        row=conn.execute('SELECT external_event_id FROM integration_provider_events').fetchone()
        assert row[0] is None
        assert conn.execute('SELECT count(*) FROM risks').fetchone()[0]==1


def test_geofence_outside_and_bad_polygon(env):
    from services.integrations.john_deere_sync import geofence
    with env._db() as conn:
        conn.execute("INSERT INTO sectors(name,boundary_json) VALUES('A',?)",(json.dumps([[56,23],[56,25],[58,25],[58,23]]),))
        assert geofence(conn,'A',55,24)=='OUTSIDE'
        conn.execute("UPDATE sectors SET boundary_json='broken'")
        assert geofence(conn,'A',55,24)=='UNKNOWN'
        assert conn.execute('SELECT count(*) FROM risks').fetchone()[0]==0


def test_latest_measurement_wins_across_out_of_order_responses(env,monkeypatch):
    latest={'reading':{'valueAsDouble':200},'time':'2026-10-21T12:00:00Z'}
    older={'reading':{'valueAsDouble':100},'time':'2026-10-20T12:00:00Z'}
    sync_case(env,monkeypatch,[org()],[machine(relations=['engineHours'])],capabilities=[response({'values':[latest,older]})])
    sync_case(env,monkeypatch,[org()],[machine(relations=['engineHours'])],capabilities=[response({'values':[older]})])
    with env._db() as conn:assert conn.execute('SELECT engine_hours FROM sector_equipment').fetchone()[0]==200


def test_hours_zero_is_a_returned_measurement(env,monkeypatch):
    sync_case(env,monkeypatch,[org()],[machine(relations=['hoursOfOperation'])],capabilities=[response({'values':[{'operatingHours':0,'endDate':stamp()}]})])
    with env._db() as conn:assert conn.execute('SELECT operating_hours FROM sector_equipment').fetchone()[0]==0


def test_successful_empty_org_response_keeps_refs_but_marks_not_seen(env,monkeypatch):
    sync_case(env,monkeypatch,[org()],[machine()],kind='machines')
    runner,result,mock=sync_case(env,monkeypatch,[],[],kind='machines')
    assert result['status']=='EMPTY'
    assert runner.status()['counts']['organizations']==0
    with env._db() as conn:
        assert conn.execute('SELECT count(*) FROM integration_organizations').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM sector_equipment').fetchone()[0]==1


def test_sync_cooldown_is_shared_across_types(env,monkeypatch):
    runner,result,mock=sync_case(env,monkeypatch,[],[],kind='machines')
    monkeypatch.setenv('JOHN_DEERE_SYNC_MIN_INTERVAL_SECONDS','60')
    before=mock.call_count
    assert runner.run('all')['status']=='RATE LIMITED'
    assert mock.call_count==before


def test_sync_migration_is_additive_and_reuses_tables(env):
    import database
    with env._db() as conn:
        conn.execute("INSERT INTO sector_equipment(sector,equipment_code) VALUES('KEEP','EXISTING')")
    database.init_db();database.init_db()
    with env._db() as conn:
        assert conn.execute("SELECT count(*) FROM sector_equipment WHERE equipment_code='EXISTING'").fetchone()[0]==1
        cols={r[1] for r in conn.execute('PRAGMA table_info(vehicle_gps_pings)')}
        assert {'source','provider','equipment_id','source_timestamp'}<=cols
        assert conn.execute('SELECT count(*) FROM integration_provider_events').fetchone()[0]==0
