"""Read-only unit contracts; real national/browser acceptance is separate."""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException
from shapely.geometry import box
from services.geodata import forest_map as fm


@pytest.fixture
def catalogue(tmp_path,monkeypatch):
    forest=tmp_path/'forest.sqlite';parcel=tmp_path/'parcel.sqlite';app=tmp_path/'app.sqlite';version='unit-version'
    g=box(24,56.99,24.005,56.995)
    with sqlite3.connect(forest) as c:
        c.executescript('CREATE TABLE compartments(id INTEGER PRIMARY KEY,external_id TEXT,kadastrs TEXT,geometry BLOB,repair TEXT,geometry_valid INTEGER,adm1 TEXT,adm2 TEXT,kvart TEXT,nog TEXT,area_m2 REAL,nog_plat REAL,source_region TEXT); CREATE VIRTUAL TABLE spatial_index USING rtree(id,min_lon,max_lon,min_lat,max_lat);')
        c.execute('INSERT INTO compartments(id,external_id,kadastrs,geometry,repair,geometry_valid) VALUES(1,?,?,?,?,?)',('VMD:unit:1','00000000001',g.wkb,None,1));c.execute('INSERT INTO spatial_index VALUES(1,24,24.005,56.99,56.995)')
    with sqlite3.connect(parcel) as c:
        c.executescript('CREATE TABLE parcels(id INTEGER PRIMARY KEY,designation TEXT,geometry BLOB,geometry_valid INTEGER); CREATE VIRTUAL TABLE spatial_index USING rtree(id,min_lon,max_lon,min_lat,max_lat);')
    with sqlite3.connect(app) as c:
        c.executescript('CREATE TABLE sectors(id INTEGER,name TEXT,boundary_json TEXT,area_ha REAL,organization_id INTEGER,center_lat REAL,center_lon REAL);')
        ring=json.dumps([[y,x] for x,y in g.exterior.coords]);c.execute('INSERT INTO sectors(id,name,boundary_json,area_ha,organization_id) VALUES(1,?,?,1,1)',('Visible',ring));c.execute('INSERT INTO sectors(id,name,boundary_json,area_ha,organization_id) VALUES(2,?,?,1,2)',('Private other organization',ring))
    m={'version':version,'forest_db':str(forest),'parcel_db':str(parcel),'reports':{'vmd':{'indexed':1},'vzd':{'indexed':0}}}
    monkeypatch.setattr(fm.nw,'release',lambda:m);monkeypatch.setattr(fm,'DISPLAY_ROOT',tmp_path);monkeypatch.setattr(fm,'context',lambda actor:{'organization_id':1})
    def connect():
        c=sqlite3.connect('file:'+str(app)+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
    monkeypatch.setattr(fm.data,'_app_connection',connect)
    folder=tmp_path/version;folder.mkdir();scale=2**fm.GRID_ZOOM
    import math
    x=int((24+180)/360*scale);y=int((1-math.asinh(math.tan(math.radians(56.99)))/math.pi)/2*scale)
    np.savez_compressed(folder/'overview.npz',x=np.array([x]),y=np.array([y]),count=np.array([1]),version=version,records=1)
    fm.overview.cache_clear();fm._cache.clear();fm._cache_size=0
    return m,g


def tile_at(lon,lat,z):
    import math
    return z,int((lon+180)/360*2**z),int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)


def test_source_geometry_unchanged_and_tile_geometry_is_display_only(catalogue):
    m,g=catalogue;before=Path(m['forest_db']).read_bytes()
    args=tile_at(24.002,56.992,16);raw,hit=fm.tile('forest',*args);result=json.loads(raw)
    assert result['display_only'] is True and len(result['features'])==1
    assert result['features'][0]['properties']['id']=='VMD:unit:1'
    assert Path(m['forest_db']).read_bytes()==before
    again,cached=fm.tile('forest',*args);assert cached and again==raw


def test_dense_tiles_generalize_instead_of_silently_truncating(catalogue,monkeypatch):
    monkeypatch.setattr(fm,'MAX_FEATURES',0)
    raw,_=fm.tile('forest',*tile_at(24.002,56.992,16));result=json.loads(raw)
    assert result['mode']=='generalized_presence' and result['features']==[]
    assert result['cells']['count']==[1] and result['notice_code']=='density_cells'


def test_below_detail_zoom_returns_true_size_density_cells_without_records(catalogue):
    for z in (7,10,12):
        result=json.loads(fm.tile('forest',*tile_at(24.002,56.992,z))[0])
        cells=result['cells']
        assert result['mode']=='generalized_presence' and result['features']==[]
        assert cells['zoom']==fm.GRID_ZOOM and sum(cells['count'])==1
        assert len(cells['dx'])==len(cells['dy'])==len(cells['count'])==1
        # The cell is reported at its own zoom-14 position, never enlarged to the map zoom.
        assert (cells['x0']+cells['dx'][0])>>(fm.GRID_ZOOM-z)==tile_at(24.002,56.992,z)[1]


def test_detail_zoom_draws_every_record_above_old_600_limit(catalogue):
    m,_=catalogue
    z,tx,ty=tile_at(24.01,56.97,13);w,s,e,n=fm.tile_bounds(z,tx,ty);dx=(e-w)/31;dy=(n-s)/26
    with sqlite3.connect(m['forest_db']) as c:
        for i in range(2,752):
            x=w+dx*(0.1+(i-2)%30);y=s+dy*(0.1+(i-2)//30);g=box(x,y,x+dx*0.8,y+dy*0.8)
            c.execute('INSERT INTO compartments(id,external_id,kadastrs,geometry,repair,geometry_valid,kvart,nog,nog_plat,area_m2) VALUES(?,?,?,?,?,?,?,?,?,?)',(i,f'VMD:unit:{i}','00000000002',g.wkb,None,1,'7',str(i),0 if i==2 else 0.5,6000))
            c.execute('INSERT INTO spatial_index VALUES(?,?,?,?,?)',(i,x,x+dx*0.8,y,y+dy*0.8))
    z,x,y=z,tx,ty;expected={f'VMD:unit:{i}' for i in range(2,752)}
    assert len(expected)==750
    result=json.loads(fm.tile('forest',z,x,y)[0])
    assert result['mode']=='simplified'
    assert {f['properties']['id'] for f in result['features']}>=expected
    p=next(f['properties'] for f in result['features'] if f['properties']['id']=='VMD:unit:3')
    assert (p['kvart'],p['nog'],p['area_ha'],p['area_declared'])==('7','3',0.5,True)
    zero=next(f['properties'] for f in result['features'] if f['properties']['id']=='VMD:unit:2')
    assert zero['area_declared'] is False and zero['area_ha']==0.6


def test_municipality_catalogue_is_exact_bounded_and_read_only(catalogue):
    m,_=catalogue
    with sqlite3.connect(m['forest_db']) as c:c.execute("UPDATE compartments SET adm1='Valmieras novads',area_m2=12345,nog_plat=1.2,source_region='Vidzemes' WHERE id=1")
    before=Path(m['forest_db']).read_bytes()
    result=fm.municipality_catalogue('Valmieras novads',limit=1,offset=0,actor='test')
    assert result['total']==1 and not result['has_more']
    assert result['results'][0]=={'source_id':'VMD:unit:1','kadastrs':'00000000001','kvart':None,'nog':None,'area_ha':1.2,'source_region':'Vidzemes'}
    assert Path(m['forest_db']).read_bytes()==before


def test_parcels_not_loaded_at_low_zoom(catalogue):
    raw,_=fm.tile('parcels',*tile_at(24,57,7));r=json.loads(raw)
    assert not r['features'] and r['mode']=='zoom_required'


def test_sector_overlay_does_not_expose_other_organizations(catalogue):
    r=fm.sectors('test');assert [f['properties']['name'] for f in r['features']]==['Visible']
    assert r['summary']['total']==r['summary']['mapped']==1 and r['summary']['unmapped']==0


def test_ambiguous_identity_fails_closed(catalogue,monkeypatch):
    def blocked(actor):raise fm.data.DatasetError('Organization not verified',503)
    monkeypatch.setattr(fm,'context',blocked)
    with pytest.raises(fm.data.DatasetError):fm.sectors('test')


@pytest.mark.parametrize('z,x,y',[(3,0,0),(20,0,0),(6,-1,0),(6,0,64)])
def test_invalid_tiles_rejected(z,x,y):
    with pytest.raises(HTTPException) as error:fm.tile_bounds(z,x,y)
    assert error.value.status_code==422


def test_missing_overview_fails_explicitly(catalogue):
    with pytest.raises(HTTPException) as error:fm.overview('missing')
    assert error.value.status_code==503


def test_source_input_byte_limit_falls_back_before_decoding(catalogue,monkeypatch):
    monkeypatch.setattr(fm,'MAX_INPUT_BYTES',1)
    raw,_=fm.tile('forest',*tile_at(24.002,56.992,16));assert json.loads(raw)['mode']=='generalized_presence'


def test_private_sector_response_prohibits_shared_caching(catalogue):
    route=next(route for route in fm.router(lambda:'test').routes if route.path.endswith('/sectors'))
    response=route.endpoint(actor='test')
    assert response.headers['cache-control']=='private, no-store'
    assert response.headers['vary']=='Authorization'
    assert 'Private other organization' not in response.body.decode()


def test_tile_work_is_bounded_when_workers_are_busy(catalogue,monkeypatch):
    monkeypatch.setattr(fm,'WORKER_WAIT_SECONDS',0.05)
    for _ in range(3):fm._workers.acquire()
    try:
        with pytest.raises(HTTPException) as error:fm.tile('forest',*tile_at(24,57,12))
        assert error.value.status_code==503
    finally:
        for _ in range(3):fm._workers.release()


def test_invalid_existing_sector_uses_stored_center_without_repair(catalogue):
    path=Path(catalogue[0]['forest_db']).parent/'app.sqlite'
    original=json.dumps([[57,24],[57.01,24.01],[57,24.01],[57.01,24],[57,24]])
    with sqlite3.connect(path) as c:c.execute('INSERT INTO sectors VALUES(3,?,?,1,1,57.005,24.005)',('Legacy invalid boundary',original))
    before=path.read_bytes();result=fm.sectors('test');f=next(f for f in result['features'] if f['properties']['id']==3)
    assert f['geometry']=={'type':'Point','coordinates':[24.005,57.005]}
    assert f['properties']['geometry_status']=='invalid_boundary'
    assert result['summary']['invalid_boundaries']==result['summary']['center_markers']==1
    assert path.read_bytes()==before


def test_foreign_legacy_sector_is_counted_but_not_drawn_on_latvia_map(catalogue):
    path=Path(catalogue[0]['forest_db']).parent/'app.sqlite'
    foreign=box(32.7,58.9,32.71,58.91);ring=json.dumps([[y,x] for x,y in foreign.exterior.coords])
    with sqlite3.connect(path) as c:c.execute('INSERT INTO sectors VALUES(4,?,?,1,1,58.905,32.705)',('Outside Latvia extent',ring))
    result=fm.sectors('test');assert not any(f['properties']['id']==4 for f in result['features'])
    assert result['summary']['outside_map_extent']==result['summary']['unmapped']==1
    assert result['unmapped']==[{'id':4,'name':'Outside Latvia extent','reason':'outside_map_extent','outside_latvia':True}]


def test_every_hidden_sector_has_a_reason_and_drawn_ones_flag_latvia_envelope(catalogue):
    path=Path(catalogue[0]['forest_db']).parent/'app.sqlite'
    north=box(28.71,58.86,28.72,58.87);ring=json.dumps([[y,x] for x,y in north.exterior.coords])
    with sqlite3.connect(path) as c:
        c.execute('INSERT INTO sectors VALUES(5,?,NULL,1,1,NULL,NULL)',('No boundary',))
        c.execute('INSERT INTO sectors VALUES(6,?,?,1,1,58.865,28.715)',('North of Latvia',ring))
    before=path.read_bytes();result=fm.sectors('test')
    assert {u['id']:u['reason'] for u in result['unmapped']}=={5:'no_boundary'}
    flags={f['properties']['id']:f['properties']['outside_latvia'] for f in result['features']}
    assert flags=={1:False,6:True}
    assert result['summary']['mapped']+len(result['unmapped'])==result['summary']['total']
    assert path.read_bytes()==before


def test_feature_properties_never_expose_server_paths():
    m={'root':'/srv/geodata/releases/20261106'}
    p={'cadastral_validation':{'source_file':'/srv/geodata/releases/20261106/sources/vzd/a/KKParcel.shp','other':'/root/private/x.shp'},'kadastrs':'1','list':['/tmp/y.dbf']}
    assert fm._without_server_paths(p,m)=={'cadastral_validation':{'source_file':'sources/vzd/a/KKParcel.shp','other':'x.shp'},'kadastrs':'1','list':['y.dbf']}


def test_identify_returns_language_neutral_notice_codes(catalogue):
    assert fm.identify(57,24,10,'test')['notice_code']=='zoom_in'
    assert fm.identify(58.5,27.5,16,'test')['notice_code']=='none'


def test_tiles_are_gzipped_and_cached_only_for_the_current_version(catalogue):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    m,_=catalogue;app=FastAPI();app.include_router(fm.router(lambda:'test'));client=TestClient(app)
    with sqlite3.connect(m['forest_db']) as c:
        for i in range(2,40):
            x=24.0001+i*0.0001;g=box(x,56.9901,x+0.00008,56.9949)
            c.execute('INSERT INTO compartments(id,external_id,kadastrs,geometry,repair,geometry_valid) VALUES(?,?,?,?,?,?)',(i,f'VMD:unit:{i}','00000000001',g.wkb,None,1))
            c.execute('INSERT INTO spatial_index VALUES(?,?,?,?,?)',(i,x,x+0.00008,56.9901,56.9949))
    z,x,y=tile_at(24.002,56.992,16);url=f'/api/geodata/forest-map/tiles/forest/{z}/{x}/{y}'
    current=client.get(url+'?v='+m['version'],headers={'Accept-Encoding':'gzip'})
    assert current.status_code==200 and current.headers['content-encoding']=='gzip'
    assert current.headers['cache-control']=='private, max-age=86400, immutable'
    assert len(current.json()['features'])==39
    stale=client.get(url+'?v=older',headers={'Accept-Encoding':'identity'})
    assert stale.headers['cache-control']=='private, no-cache' and 'content-encoding' not in stale.headers
