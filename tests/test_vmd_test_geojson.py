"""Read-only VMD visual fixture tests: no production DB, lifecycle or external calls."""
import asyncio
import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source(tmp_path, monkeypatch):
    from services.geodata import vmd_test
    original = json.loads((ROOT / 'lvm_3_sectors.geojson').read_text())
    fixture = tmp_path / 'compartments.geojson'
    fixture.write_text(json.dumps(original))
    monkeypatch.setattr(vmd_test, 'SOURCE_FILE', fixture)
    return vmd_test, fixture, original


def test_real_source_is_returned_unchanged(source):
    module, path, original = source
    assert module.read_test_compartments() == original
    features = module.read_test_compartments()['features']
    assert len(features) == 3
    assert all(f['geometry']['type'] == 'Polygon' for f in features)
    assert [f['properties']['kadastrs'] for f in features] == ['40940020002','32620090044','40440040167']
    assert [f['properties']['nog_plat'] for f in features] == [0.18,0.66,0.82]


def test_missing_source_returns_safe_unavailable(source):
    module, path, _ = source
    path.unlink()
    with pytest.raises(module.VmdTestDataError) as result: module.read_test_compartments()
    assert result.value.status_code == 503
    assert str(path) not in str(result.value)


@pytest.mark.parametrize('case',['malformed','empty','too_many','multipolygon','wrong_crs','open_ring','bad_coordinate','bowtie','oversize'])
def test_invalid_data_rejected_without_repair(source,case):
    module,path,data = source
    data=copy.deepcopy(data)
    if case=='malformed': path.write_text('{bad');
    elif case=='empty': data['features']=[]
    elif case=='too_many': data['features']=data['features']*module.MAX_FEATURES
    elif case=='multipolygon': data['features'][0]['geometry']['type']='MultiPolygon'
    elif case=='wrong_crs': data['crs']['properties']['name']='EPSG:3059'
    elif case=='open_ring': data['features'][0]['geometry']['coordinates'][0].pop()
    elif case=='bad_coordinate': data['features'][0]['geometry']['coordinates'][0][1][0]=999999
    elif case=='bowtie': data['features'][0]['geometry']['coordinates']=[[[24,56],[24.1,56.1],[24.1,56],[24,56.1],[24,56]]]
    elif case=='oversize': path.write_bytes(b' '*(module.MAX_BYTES+1))
    if case not in {'malformed','oversize'}:path.write_text(json.dumps(data))
    with pytest.raises(module.VmdTestDataError) as result:module.read_test_compartments()
    assert result.value.status_code == 422


def test_http_endpoint_auth_exact_collection_and_no_database_or_network(source,tmp_path,monkeypatch):
    module,path,original=source
    monkeypatch.setenv('DASHBOARD_USERNAME','vmd-test')
    monkeypatch.setenv('DASHBOARD_PASSWORD','vmd-test')
    monkeypatch.setenv('DB_PATH',str(tmp_path/'never-open.db'))
    import api,sqlite3,requests,httpx,fastapi.routing,fastapi.dependencies.utils
    def forbidden(*args,**kwargs):raise AssertionError('Visualization endpoint must not use DB or network')
    monkeypatch.setattr(sqlite3,'connect',forbidden)
    monkeypatch.setattr(requests,'get',forbidden)
    monkeypatch.setattr(requests,'request',forbidden)
    async def inline(fn,*args,**kwargs):return fn(*args,**kwargs)
    monkeypatch.setattr(fastapi.routing,'run_in_threadpool',inline)
    monkeypatch.setattr(fastapi.dependencies.utils,'run_in_threadpool',inline)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://test') as client:
            assert (await client.get('/api/geodata/vmd/test-sectors')).status_code==401
            client.auth=('vmd-test','vmd-test')
            response=await client.get('/api/geodata/vmd/test-sectors?path=/etc/passwd')
            assert response.status_code==200,response.text
            assert response.json()==original
            assert response.headers['content-type']=='application/geo+json'
            assert response.headers['cache-control']=='no-store'
            assert len(response.json()['features'])==3
            path.write_text('{bad')
            assert (await client.get('/api/geodata/vmd/test-sectors')).status_code==422
            path.unlink()
            assert (await client.get('/api/geodata/vmd/test-sectors')).status_code==503
    asyncio.run(run())
    assert not (tmp_path/'never-open.db').exists()
