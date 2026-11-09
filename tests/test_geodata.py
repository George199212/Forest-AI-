"""Synthetic fixtures only. No production DB writes or live-service claims.

HTTP tests use same-thread ASGITransport: the restricted execution environment
cannot wake TestClient's cross-thread portal. Routing, validation and auth still
run; only FastAPI's threadpool dispatch is inlined for these tests.
"""
import asyncio
import copy
import json
import sqlite3
from unittest.mock import Mock

import pytest
from services.geodata.base import GeodataError
from services.geodata.lvm_geo import LVMGeoProvider, ENDPOINTS, MAX_BYTES, xml, validate_bbox

# Deliberately synthetic dataset/feature names, not LVM service discoveries.
WMS = b'''<WMT_MS_Capabilities version="1.1.1"><Capability><Request><GetMap><Format>image/png</Format></GetMap></Request>
<Layer><SRS>EPSG:4326 EPSG:3857</SRS><Attribution><Title>TEST dataset attribution</Title></Attribution>
<Layer><Name>fixture:polygon</Name><Title>TEST polygon dataset</Title><Abstract>Unit test only</Abstract></Layer>
<Layer><Name>fixture:raster</Name><Title>TEST raster</Title></Layer></Layer></Capability></WMT_MS_Capabilities>'''
WFS = b'''<WFS_Capabilities version="1.0.0"><Capability><Request><GetFeature><ResultFormat><JSON/></ResultFormat></GetFeature></Request></Capability>
<FeatureTypeList><FeatureType><Name>fixture:polygon</Name><SRS>EPSG:4326</SRS></FeatureType></FeatureTypeList></WFS_Capabilities>'''
FEATURE = {'type':'Feature','id':'fixture.1','properties':{'test':True},'geometry':{'type':'Polygon','coordinates':[[[24.1,56.9],[24.11,56.9],[24.11,56.91],[24.1,56.91],[24.1,56.9]]]}}
BBOX = [24.09,56.89,24.12,56.92]


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'test.db'))
    import database
    from services.geodata import store
    monkeypatch.setattr(database,'DB_NAME',str(tmp_path/'test.db'))
    database.init_db()
    return database,store


@pytest.fixture
def provider(monkeypatch):
    p=LVMGeoProvider()
    def request(endpoint,params,kind='xml'):
        if params['request']=='GetCapabilities': return WMS if params['service']=='WMS' else WFS
        if params['request']=='GetFeature': return json.dumps({'type':'FeatureCollection','features':[copy.deepcopy(FEATURE)]}).encode()
        raise AssertionError(params)
    monkeypatch.setattr(p,'_request',request)
    return p


def imported(db,provider):
    database,store=db
    preview=store.preview(provider,'vector/fixture:polygon',BBOX,50,'account-a')
    return store.import_selected(preview['token'],['fixture.1'],'account-a')['sectors'][0]


def test_capabilities_discovery_and_format(provider):
    c=provider.get_capabilities()
    assert c['status']=='CONNECTED' and c['wms'] and c['wfs']
    assert c['layer_count']==4
    layer=provider.get_layer_metadata('vector/fixture:polygon')
    assert layer['importable'] and layer['attribution']=='TEST dataset attribution'
    assert not provider.get_layer_metadata('vector/fixture:raster')['wfs']
    assert len(provider.list_services())==2


def test_wms_url(provider):
    from urllib.parse import urlsplit,parse_qs
    u=provider.get_map_url('vector/fixture:polygon',BBOX)
    assert u.startswith(ENDPOINTS['vector'])
    assert parse_qs(urlsplit(u).query)['bbox']==[','.join(map(str,BBOX))]
    assert parse_qs(urlsplit(u).query)['srs']==['EPSG:4326']


def test_unavailable_does_not_claim_wfs_or_layers(monkeypatch):
    p=LVMGeoProvider()
    monkeypatch.setattr(p,'_request',Mock(side_effect=GeodataError('LVM GEO unavailable')))
    c=p.get_capabilities()
    assert c['status']=='UNAVAILABLE' and not c['wfs'] and not c['wms'] and not c['layers']
    assert p.health_check()['status']=='UNAVAILABLE'


def test_wms_only(monkeypatch):
    p=LVMGeoProvider()
    monkeypatch.setattr(p,'_request',lambda url,params,kind='xml':WMS)
    c=p.get_capabilities()
    assert c['wms'] and not c['wfs']
    assert not any(l['importable'] for l in c['layers'])
    with pytest.raises(GeodataError):p.get_features('maps/fixture:polygon',bbox=BBOX)


def test_capability_cache_and_copy(provider,monkeypatch):
    m=Mock(wraps=provider._request);monkeypatch.setattr(provider,'_request',m)
    provider.get_capabilities()['layers'].clear()
    assert len(provider.list_layers())==4 and m.call_count==4
    provider.health_check(refresh=True)
    assert m.call_count==8


@pytest.mark.parametrize('raw',[b'<!DOCTYPE a [<!ENTITY x "abc">]><a>&x;</a>', '<!DOCTYPE a><a/>'.encode('utf-16'), b'not xml'])
def test_unsafe_xml(raw):
    with pytest.raises(GeodataError):xml(raw)


@pytest.mark.parametrize('bbox',[None,[],[24,56,25,57],[24,56,float('nan'),57],[200,56,201,57],[24,57,23,56]])
def test_bbox_requires_small_latvian_area(bbox):
    with pytest.raises(GeodataError):validate_bbox(bbox)


def test_limited_wfs_and_crs(provider,monkeypatch):
    original=provider._request
    m=Mock(wraps=original);monkeypatch.setattr(provider,'_request',m)
    features=provider.get_features('vector/fixture:polygon',bbox=BBOX,limit=3)
    assert features['features'][0]['id']=='fixture.1'
    args=m.call_args.args[1]
    assert args['maxFeatures']==3 and 'bbox' in args and args['srsName']=='EPSG:4326'
    assert provider.get_feature('vector/fixture:polygon','fixture.1')['id']=='fixture.1'
    assert m.call_args.args[1]['featureID']=='fixture.1'
    assert 'bbox' not in m.call_args.args[1]


def test_wrong_response_crs_rejected(provider,monkeypatch):
    provider.get_capabilities()
    monkeypatch.setattr(provider,'_request',lambda *a:json.dumps({'type':'FeatureCollection','crs':{'properties':{'name':'EPSG:3059'}},'features':[]}).encode())
    with pytest.raises(GeodataError,match='CRS'):provider.get_features('vector/fixture:polygon',BBOX)


@pytest.mark.parametrize('data',[{'type':'FeatureCollection','features':[FEATURE,FEATURE]}, {'type':'Feature','features':[]}, {'type':'FeatureCollection','features':'bad'}])
def test_malformed_or_excess_features(provider,monkeypatch,data):
    provider.get_capabilities()
    monkeypatch.setattr(provider,'_request',lambda *a:json.dumps(data).encode())
    with pytest.raises(GeodataError):provider.get_features('vector/fixture:polygon',BBOX,limit=1)


def test_feature_id_filter_must_be_honored(provider):
    with pytest.raises(GeodataError,match='feature ID'):provider.get_feature('vector/fixture:polygon','different-id')


@pytest.mark.parametrize('patch',[
    {'geometry':None}, {'geometry':{'type':'MultiPolygon','coordinates':[]}},
    {'geometry':{'type':'Polygon','coordinates':[]}},
    {'geometry':{'type':'Polygon','coordinates':[FEATURE['geometry']['coordinates'][0],FEATURE['geometry']['coordinates'][0]]}},
    {'geometry':{'type':'Polygon','coordinates':[[[24,56],[24.1,56.1],[24.1,56],[24,56.1],[24,56]]]}},
    {'geometry':{'type':'Polygon','coordinates':[[[400000,300000]]*4]}},
    {'id':None}, {'id':'first,second'},
])
def test_invalid_geometry_never_imported(db,patch):
    _,store=db;f=copy.deepcopy(FEATURE);f.update(patch)
    with pytest.raises(GeodataError):store.normalize(f)


def test_import_is_normal_local_sector_and_idempotent(db,provider):
    database,store=db
    row=imported(db,provider)
    with sqlite3.connect(database.DB_NAME) as c:
        sector=c.execute('SELECT id,name,boundary_json,data_origin FROM sectors').fetchone()
        assert sector[0]==row['id'] and sector[1].startswith('GEO-') and sector[1]!='fixture.1'
        assert json.loads(sector[2])[0]==[56.9,24.1] and sector[3]=='REAL'
    source=store.source_info(row['id'])
    assert source['provider']=='LVM_GEO' and source['source_feature_id']=='fixture.1'
    assert source['source_attribution']=='TEST dataset attribution'
    assert source['source_properties']=={'test':True} and len(source['history'])==1
    again=store.preview(provider,'vector/fixture:polygon',BBOX,50,'account-a')
    assert again['features'][0]['already_imported']['name']==row['name']
    result=store.import_selected(again['token'],['fixture.1'],'account-a')
    assert result['sectors'][0]['status']=='already_imported'
    with sqlite3.connect(database.DB_NAME) as c: assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==1


def test_tokens_bound_to_account_and_expire(db,provider):
    database,store=db
    p=store.preview(provider,'vector/fixture:polygon',BBOX,50,'account-a')
    with pytest.raises(GeodataError):store.import_selected(p['token'],['fixture.1'],'account-b')
    with sqlite3.connect(database.DB_NAME) as c:c.execute('UPDATE geodata_previews SET expires_at=0')
    with pytest.raises(GeodataError):store.import_selected(p['token'],['fixture.1'],'account-a')


def test_instance_database_isolation(db,provider,tmp_path,monkeypatch):
    database,store=db
    row=imported(db,provider)
    p=store.preview(provider,'vector/fixture:polygon',BBOX,50,'account-a')
    first=database.DB_NAME
    monkeypatch.setattr(database,'DB_NAME',str(tmp_path/'client-b.db'));database.init_db()
    with pytest.raises(GeodataError):store.source_info(row['id'])
    with pytest.raises(GeodataError):store.import_selected(p['token'],['fixture.1'],'account-a')
    other=imported(db,provider)
    assert other['status']=='imported'  # same external feature may belong to a different client
    with sqlite3.connect(first) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==1


def test_missing_attribution_and_outside_bbox_cannot_import(db,provider,monkeypatch):
    _,store=db
    original=provider.get_layer_metadata
    monkeypatch.setattr(provider,'get_layer_metadata',lambda id:{**original(id),'attribution':''})
    p=store.preview(provider,'vector/fixture:polygon',BBOX,50,'account-a')
    assert not p['features'][0]['importable'] and 'attribution' in p['features'][0]['reason']
    with pytest.raises(GeodataError):store.import_selected(p['token'],['fixture.1'],'account-a')


def test_manual_default_and_additive_migration(db):
    database,store=db
    database.add_sector('MANUAL','','Active','',boundary=[[56.9,24.1],[56.9,24.11],[56.91,24.11],[56.91,24.1]])
    database.init_db();database.init_db()
    with sqlite3.connect(database.DB_NAME) as c:
        row=c.execute('SELECT id FROM sectors').fetchone()
        assert c.execute('pragma integrity_check').fetchone()[0]=='ok'
    assert store.source_info(row[0])=={'boundary_source_type':'manual'}


def test_refresh_no_changes_then_confirmed_history(db,provider,monkeypatch):
    database,store=db;row=imported(db,provider)
    assert not store.refresh_boundary(provider,row['id'],'account-a')['changed']
    f=copy.deepcopy(FEATURE)
    f['geometry']['coordinates'][0][1][0]+=0.001
    monkeypatch.setattr(provider,'get_feature',lambda *a:f)
    p=store.refresh_boundary(provider,row['id'],'account-a')
    assert p['changed']
    with sqlite3.connect(database.DB_NAME) as c:old=c.execute('SELECT boundary_json FROM sectors').fetchone()[0]
    assert json.loads(old)==p['old_boundary']
    with pytest.raises(GeodataError):store.apply_boundary(p['token'],'account-b')
    store.apply_boundary(p['token'],'account-a')
    with sqlite3.connect(database.DB_NAME) as c:assert json.loads(c.execute('SELECT boundary_json FROM sectors').fetchone()[0])==p['new_boundary']
    assert len(store.source_info(row['id'])['history'])==2
    with pytest.raises(GeodataError):store.apply_boundary(p['token'],'account-a')


def test_refresh_concurrent_edit_and_unavailable_keep_local(db,provider,monkeypatch):
    database,store=db;row=imported(db,provider)
    f=copy.deepcopy(FEATURE);f['geometry']['coordinates'][0][1][0]+=.001
    monkeypatch.setattr(provider,'get_feature',lambda *a:f)
    p=store.refresh_boundary(provider,row['id'],'account-a')
    with sqlite3.connect(database.DB_NAME) as c:c.execute("UPDATE sectors SET boundary_json=boundary_json||' '")
    with pytest.raises(GeodataError,match='changed since preview'):store.apply_boundary(p['token'],'account-a')
    monkeypatch.setattr(provider,'get_capabilities',Mock(side_effect=GeodataError('unavailable')))
    with pytest.raises(GeodataError):store.refresh_boundary(provider,row['id'],'account-a')
    with sqlite3.connect(database.DB_NAME) as c:assert json.loads(c.execute('SELECT boundary_json FROM sectors').fetchone()[0])==p['old_boundary']


def test_request_limits_content_type_redirects_timeouts(monkeypatch):
    import requests
    p=LVMGeoProvider()
    with pytest.raises(GeodataError,match='allowlisted'):p._request('http://127.0.0.1',{})
    for status,ct,length,body in [(302,'text/xml','0',b''),(200,'text/html','0',b''),(200,'text/xml',str(MAX_BYTES+1),b''),(200,'text/xml','0',b'x'*(MAX_BYTES+1))]:
        response=Mock(status_code=status,headers={'Content-Type':ct,'Content-Length':length},iter_content=lambda *a:[body])
        context=Mock();context.__enter__=Mock(return_value=response);context.__exit__=Mock(return_value=False)
        monkeypatch.setattr(requests,'get',Mock(return_value=context))
        with pytest.raises(GeodataError):p._request(ENDPOINTS['maps'],{'request':'GetCapabilities'})
        assert requests.get.call_args.kwargs['allow_redirects'] is False
    monkeypatch.setattr(requests,'get',Mock(side_effect=requests.Timeout('secret response')))
    with pytest.raises(GeodataError,match='timed out'):p._request(ENDPOINTS['maps'],{'request':'GetCapabilities'})


def test_gps_exit_distance_time_return_using_existing_logic(db,provider,monkeypatch):
    database,store=db;row=imported(db,provider)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-token')
    import bot
    from services import session_track,geo
    monkeypatch.setattr(bot,'DB_NAME',database.DB_NAME)
    # A provider outage cannot be consulted by operational GPS code.
    monkeypatch.setattr(provider,'_request',Mock(side_effect=AssertionError('GPS must not fetch LVM')))
    with sqlite3.connect(database.DB_NAME) as c:
        employee=c.execute('INSERT INTO sector_employees(sector,full_name,telegram_user_id) VALUES(?,?,?)',(row['name'],'TEST worker','123')).lastrowid
        session=c.execute('INSERT INTO work_sessions(employee,employee_id,user_id,sector,check_in_time,approved) VALUES(?,?,?,?,?,?)',('TEST worker',employee,'123',row['name'],'2026-10-30 10:00:00 UTC','YES')).lastrowid
    pts=[(56.905,24.105),(56.905,24.115),(56.906,24.116),(56.905,24.105)]
    expected=[(None,'IN'),('IN','OUT'),('OUT','OUT'),('OUT','IN')]
    for index,((lat,lon),transition) in enumerate(zip(pts,expected)):
        assert bot.upsert_live_location(employee,'123',row['name'],lat,lon,3600)==transition
        session_track.record_point(session,employee,'123',10,row['name'],lat,lon,1,transition[1]=='IN',f'2026-10-30 10:0{index}:00 UTC','2026-10-30 10:05:00 UTC')
    with sqlite3.connect(database.DB_NAME) as c:
        boundary=json.loads(c.execute('SELECT boundary_json FROM sectors').fetchone()[0])
    assert geo.distance_to_polygon_edge_m(*pts[1],boundary)>200
    track=session_track.build_track(session)
    assert track['summary']['outside_s']>60 and track['summary']['inside_s']>0
    risk=database.add_incident(row['name'],'HIGH','TEST exit',entity_type='EMPLOYEE',entity_id=employee,rule_code='SECTOR_EXIT')
    with sqlite3.connect(database.DB_NAME) as c:
        c.execute('UPDATE risks SET session_id=? WHERE id=?',(session,risk))
    database.add_risk_event(risk,'DETECTED',actor='TEST',details='Synthetic GPS exit')
    # Place event at the recorded exit so existing risk route matcher uses it.
    with sqlite3.connect(database.DB_NAME) as c:c.execute("UPDATE risk_events SET created_at='2026-10-30 10:01:00 UTC' WHERE risk_id=?",(risk,))
    route=session_track.exit_route(risk)
    assert route['boundary']==boundary and route['recorded']
    assert route['exit'] and route['returned']
    assert route['outside_s']>60 and route['outside_distance_m']>100


def test_http_auth_validation_isolation_and_existing_pages(db,provider,monkeypatch):
    database,store=db
    monkeypatch.setenv('DASHBOARD_USERNAME','pytest');monkeypatch.setenv('DASHBOARD_PASSWORD','pytest')
    import api,fastapi.routing,fastapi.dependencies.utils,httpx
    from services.geodata import routes
    monkeypatch.setattr(api,'DB_NAME',database.DB_NAME)
    monkeypatch.setattr(routes,'provider',provider)
    # See module docstring: test-only dispatch workaround, no application changes.
    async def inline(fn,*a,**kw):return fn(*a,**kw)
    monkeypatch.setattr(fastapi.routing,'run_in_threadpool',inline)
    monkeypatch.setattr(fastapi.dependencies.utils,'run_in_threadpool',inline)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://test') as c:
            assert (await c.get('/api/geodata/lvm/health')).status_code==401
            c.auth=('pytest','pytest')
            assert (await c.get('/api/geodata/lvm/health')).json()['wms']
            assert (await c.post('/api/geodata/lvm/preview',json={'layer_id':'vector/fixture:polygon','bbox':BBOX,'organization_id':2})).status_code==422
            assert (await c.post('/api/geodata/lvm/health',json={},headers={'Origin':'https://other-client'})).status_code==403
            assert (await c.post('/api/geodata/lvm/apply',json={'token':'x'*30,'confirmed':False})).status_code==422
            p=(await c.post('/api/geodata/lvm/preview',json={'layer_id':'vector/fixture:polygon','bbox':BBOX})).json()
            resp=await c.post('/api/geodata/lvm/import',json={'token':p['token'],'feature_ids':['fixture.1']})
            assert resp.status_code==200,resp.text
            s=resp.json()['sectors'][0]
            for path in ['/','/api/sectors','/api/map','/api/risks','/api/summary','/api/integrations','/api/sectors/'+s['name']]:
                rr=await c.get(path);assert rr.status_code==200,(path,rr.text)
            assert (await c.get('/api/geodata/lvm/sectors/'+str(s['id'])+'/source')).json()['provider']=='LVM_GEO'
    asyncio.run(run())


def test_existing_live_handler_creates_exit_risk_for_imported_sector(db,provider,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    database,store=db;row=imported(db,provider)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-token')
    monkeypatch.delenv('DISPATCHER_CHAT_ID',raising=False)
    import bot
    monkeypatch.setattr(bot,'DB_NAME',database.DB_NAME)
    monkeypatch.setattr(bot,'_track_live_update',AsyncMock())
    monkeypatch.setattr(bot,'generate_incident_recommendation',lambda *a:None)
    with sqlite3.connect(database.DB_NAME) as c:
        emp=c.execute('INSERT INTO sector_employees(sector,full_name,telegram_user_id) VALUES(?,?,?)',(row['name'],'TEST worker','123')).lastrowid
    context=SimpleNamespace(user_data={'active_work_session':{'id':1,'sector':row['name']},'live_track':{'message_id':10,'ll_refreshed':True}},bot=SimpleNamespace(send_message=AsyncMock()))
    bot.upsert_live_location(emp,'123',row['name'],56.905,24.105,3600)
    async def run():
        loop=asyncio.get_running_loop()
        def immediate(executor,fn,*args):
            f=loop.create_future();f.set_result(fn(*args));return f
        monkeypatch.setattr(loop,'run_in_executor',immediate)
        for lat,lon in [(56.905,24.115),(56.906,24.116),(56.905,24.105)]:
            message=SimpleNamespace(message_id=10,location=SimpleNamespace(latitude=lat,longitude=lon,live_period=3600))
            update=SimpleNamespace(edited_message=message,message=None,effective_user=SimpleNamespace(id=123))
            await bot.handle_location(update,context)
    asyncio.run(run())
    with sqlite3.connect(database.DB_NAME) as c:
        risks=c.execute('SELECT sector,rule_code FROM risks').fetchall()
        assert risks==[(row['name'],'SECTOR_EXIT')]
        assert c.execute('SELECT last_status FROM live_locations').fetchone()[0]=='IN'
    assert context.bot.send_message.await_count==1


def test_existing_machine_geofence_uses_imported_local_boundary(db,provider):
    database,_=db;row=imported(db,provider)
    from services.integrations.john_deere_sync import geofence
    with sqlite3.connect(database.DB_NAME) as c:
        assert geofence(c,row['name'],56.905,24.105)=='INSIDE'
        assert geofence(c,row['name'],56.905,24.115)=='OUTSIDE'


def test_old_previews_atomic_import_and_parallel_duplicate(db,provider):
    from concurrent.futures import ThreadPoolExecutor
    database,store=db
    a=store.preview(provider,'vector/fixture:polygon',BBOX,50,'account-a')
    with pytest.raises(GeodataError):store.import_selected(a['token'],['fixture.1','unknown-feature'],'account-a')
    with sqlite3.connect(database.DB_NAME) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==0
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:store.import_selected(a['token'],['fixture.1'],'account-a'),range(2)))
    assert {r['sectors'][0]['status'] for r in results}=={'imported','already_imported'}
    with sqlite3.connect(database.DB_NAME) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==1


@pytest.mark.parametrize('crs',[{'properties':[]},{'properties':{'name':123}},'invalid',False,{}])
def test_malformed_crs_is_safe_error(provider,monkeypatch,crs):
    provider.get_capabilities()
    monkeypatch.setattr(provider,'_request',lambda *a:json.dumps({'type':'FeatureCollection','crs':crs,'features':[]}).encode())
    with pytest.raises(GeodataError,match='CRS'):provider.get_features('vector/fixture:polygon',BBOX)


def test_source_properties_cannot_contain_nonfinite_numbers(provider,monkeypatch):
    provider.get_capabilities()
    raw=b'{"type":"FeatureCollection","features":[],"properties":{"number":1e400}}'
    monkeypatch.setattr(provider,'_request',lambda *a:raw)
    with pytest.raises(GeodataError,match='Malformed'):provider.get_features('vector/fixture:polygon',BBOX)


def test_excessive_xml_nesting_rejected():
    with pytest.raises(GeodataError,match='structural'):xml(b'<a>'*100+b'</a>'*100)


def test_bbox_ignored_by_remote_cannot_import_other_area(db,provider):
    _,store=db
    p=store.preview(provider,'vector/fixture:polygon',[24.2,56.9,24.21,56.91],50,'account-a')
    assert not p['features'][0]['importable']
    assert 'outside' in p['features'][0]['reason']
    with pytest.raises(GeodataError):store.import_selected(p['token'],['fixture.1'],'account-a')


def test_wfs_only_layer_is_discovered(provider,monkeypatch):
    original=provider._request
    monkeypatch.setattr(provider,'_request',lambda url,params,kind='xml':WFS.replace(b'fixture:polygon',b'fixture:vectoronly') if params['service']=='WFS' else original(url,params,kind))
    cap=provider.get_capabilities()
    assert cap['layer_count']==6
    layer=provider.get_layer_metadata('vector/fixture:vectoronly')
    assert layer['wfs'] and not layer['wms']
    with pytest.raises(GeodataError,match='WMS'):provider.get_map_url(layer['id'],BBOX)


def test_last_success_survives_a_later_failed_connection(provider,monkeypatch):
    first=provider.get_capabilities()
    assert first['last_success_at']==first['checked_at']
    def fail(*a,**kw):raise GeodataError('unit test provider unavailable')
    monkeypatch.setattr(provider,'_request',fail)
    failed=provider.get_capabilities(refresh=True)
    assert failed['status']=='UNAVAILABLE' and failed['layer_count']==0
    assert failed['last_success_at']==first['checked_at']


def test_connection_retry_is_bounded_and_does_not_retry_xml_errors(monkeypatch):
    import requests
    from services.geodata.lvm_geo import LVMGeoProvider
    p=LVMGeoProvider();calls=[]
    def fail(*a,**kw):
        calls.append(1)
        raise GeodataError('offline') from requests.ConnectTimeout()
    monkeypatch.setattr(p,'_request_once',fail)
    with pytest.raises(GeodataError):p._request('unused',{'service':'WMS'})
    assert len(calls)==2
    calls.clear()
    def invalid(*a,**kw):calls.append(1);raise GeodataError('invalid response')
    monkeypatch.setattr(p,'_request_once',invalid)
    with pytest.raises(GeodataError):p._request('unused',{'service':'WMS'})
    assert len(calls)==1
