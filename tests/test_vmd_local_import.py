"""Local VMD imports use the real sector model; isolated databases only."""
import asyncio
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


@pytest.fixture
def env(tmp_path,monkeypatch):
    import database
    from services.geodata import vmd_test,vmd_local
    monkeypatch.setenv('DB_PATH',str(tmp_path/'local.db'))
    monkeypatch.setattr(database,'DB_NAME',str(tmp_path/'local.db'))
    database.init_db()
    source=tmp_path/'data.geojson'
    source.write_bytes((Path(__file__).resolve().parents[1]/'lvm_3_sectors.geojson').read_bytes())
    monkeypatch.setattr(vmd_test,'SOURCE_FILE',source)
    return database,vmd_local,vmd_test


def one(env):
    _,local,_=env
    data,features,version=local.catalogue()
    return data,next(iter(features)),version


def test_catalogue_and_ready_status_do_not_create_sectors(env):
    db,local,_=env
    status=local.local_status()
    assert status['status']=='READY' and status['source']=='VMD_LOCAL'
    assert status['feature_count']==3 and status['crs']=='EPSG:4326'
    assert all(f['status']=='READY' and f['importable'] for f in status['features'])
    assert status['features'][0]['external_id']=='VMD-40940020002-1-6'
    with sqlite3.connect(db.DB_NAME) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==0


def test_real_polygon_import_ordinary_sector_duplicate_and_geometry(env):
    db,local,_=env;data,fid,version=one(env)
    result=local.import_features([fid],version,'test-actor')
    assert result['imported']==1 and not result['failed']
    r=result['results'][0]
    assert r['name']=='VMD 40940020002 - 1-6'
    with sqlite3.connect(db.DB_NAME) as c:
        sector=c.execute('SELECT boundary_json,area_ha,data_origin FROM sectors WHERE id=?',(r['id'],)).fetchone()
        assert json.loads(sector[0])==[[p[1],p[0]] for p in data['features'][0]['geometry']['coordinates'][0]]
        assert sector[1]==0.18 and sector[2]=='REAL'
        source=c.execute('SELECT provider,source_feature_id,source_properties FROM geodata_sources').fetchone()
        assert source[:2]==('VMD_LOCAL',fid)
        assert json.loads(source[2])['kadastrs']=='40940020002'
        assert c.execute('SELECT actor,action FROM geodata_boundary_history').fetchone()==('test-actor','IMPORT_LOCAL_VMD')
        assert c.execute('SELECT count(*) FROM risks').fetchone()[0]==0
    again=local.import_features([fid],version,'test-actor')
    assert again['already_exists']==1 and again['results'][0]['id']==r['id']
    status=local.local_status()
    assert [f['status'] for f in status['features']]==['IMPORTED','READY','READY']
    from services.geo import point_in_polygon
    from shapely.geometry import shape
    point=shape(data['features'][0]['geometry']).representative_point()
    assert point_in_polygon(point.y,point.x,json.loads(sector[0]))


def test_name_collision_never_overwrites_manual_sector(env):
    db,local,_=env;_,fid,version=one(env)
    db.add_sector('VMD 40940020002 - 1-6','KEEP','Active','100')
    result=local.import_features([fid],version,'test')
    assert result['failed']==1 and not result['imported']
    with sqlite3.connect(db.DB_NAME) as c:
        assert c.execute('SELECT contractor,approved_volume FROM sectors').fetchone()==('KEEP','100')
        assert c.execute('SELECT count(*) FROM geodata_sources').fetchone()[0]==0


def test_concurrent_duplicate_is_serialized(env):
    db,local,_=env;_,fid,version=one(env)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:local.import_features([fid],version,'test'),range(2)))
    assert sorted(r['imported'] for r in results)==[0,1]
    assert sorted(r['already_exists'] for r in results)==[0,1]
    with sqlite3.connect(db.DB_NAME) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==1


def test_dataset_version_blocks_changed_preview(env):
    _,local,reader=env;_,fid,version=one(env)
    data=json.loads(reader.SOURCE_FILE.read_text());data['features'][0]['properties']['nog_plat']=0.19;reader.SOURCE_FILE.write_text(json.dumps(data))
    with pytest.raises(reader.VmdTestDataError,match='changed'):local.import_features([fid],version,'test')


def test_multiple_features_partial_failure_and_no_auto_import(env):
    db,local,_=env;_,fid,version=one(env)
    result=local.import_features([fid,'VMD-999999-1-1'],version,'test')
    assert result['imported']==1 and result['failed']==1
    with sqlite3.connect(db.DB_NAME) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==1


def test_instance_isolation(env,tmp_path,monkeypatch):
    db,local,_=env;_,fid,version=one(env)
    local.import_features([fid],version,'same-user')
    original=db.DB_NAME
    monkeypatch.setattr(db,'DB_NAME',str(tmp_path/'other-client.db'));db.init_db()
    assert all(f['status']=='READY' for f in local.local_status()['features'])
    assert local.import_features([fid],version,'same-user')['imported']==1
    with sqlite3.connect(original) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==1


def test_reader_and_catalogue_support_more_than_three_features(env):
    _,local,reader=env
    data=json.loads(reader.SOURCE_FILE.read_text());extra=copy.deepcopy(data['features'][0]);extra['properties']['nog']='99';data['features'].append(extra)
    reader.SOURCE_FILE.write_text(json.dumps(data))
    assert len(reader.read_test_compartments()['features'])==4
    assert local.local_status()['feature_count']==4


def test_source_duplicate_ids_rejected(env):
    _,local,reader=env
    data=json.loads(reader.SOURCE_FILE.read_text());data['features'].append(copy.deepcopy(data['features'][0]));reader.SOURCE_FILE.write_text(json.dumps(data))
    with pytest.raises(reader.VmdTestDataError,match='Duplicate'):local.catalogue()


def test_http_auth_csrf_import_and_existing_map(env,monkeypatch):
    db,local,_=env
    monkeypatch.setenv('DASHBOARD_USERNAME','local-test');monkeypatch.setenv('DASHBOARD_PASSWORD','local-test')
    import api,httpx,fastapi.routing,fastapi.dependencies.utils
    monkeypatch.setattr(api,'DB_NAME',db.DB_NAME)
    async def inline(fn,*a,**kw):return fn(*a,**kw)
    monkeypatch.setattr(fastapi.routing,'run_in_threadpool',inline);monkeypatch.setattr(fastapi.dependencies.utils,'run_in_threadpool',inline)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://test') as c:
            assert (await c.get('/api/geodata/vmd/local-status')).status_code==401
            c.auth=('local-test','local-test')
            source=await c.get('/api/geodata/vmd/test-sectors');assert source.status_code==200
            status=(await c.get('/api/geodata/vmd/local-status')).json()
            assert source.headers['etag'].strip('"')==status['dataset_version']
            body={'feature_ids':[status['features'][0]['external_id']],'dataset_version':status['dataset_version']}
            assert (await c.post('/api/geodata/vmd/import',json=body,headers={'Origin':'http://other'})).status_code==403
            assert (await c.post('/api/geodata/vmd/import',json={**body,'organization_id':2})).status_code==422
            result=await c.post('/api/geodata/vmd/import',json=body);assert result.status_code==409
            assert 'Kadastra dati nav pārbaudīti' in result.json()['detail']
    asyncio.run(run())
