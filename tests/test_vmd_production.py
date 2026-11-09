"""Production-query and import contracts; real-polygon fixtures, isolated DBs only."""
import asyncio,json,sqlite3,hashlib
from pathlib import Path
import pytest,shapely
from shapely.geometry import shape,mapping,box

@pytest.fixture
def env(tmp_path,monkeypatch):
    import database
    from services.geodata import vmd_dataset as ds
    from services.geodata.forestry_io import equal_area
    monkeypatch.setattr(database,'DB_NAME',str(tmp_path/'app.db'));database.init_db()
    monkeypatch.setattr(ds,'DATASET',tmp_path/'catalogue.sqlite');monkeypatch.setattr(ds,'TERRITORIES',tmp_path/'territories.sqlite')
    features=json.loads((Path(__file__).resolve().parents[1]/'lvm_3_sectors.geojson').read_text())['features']
    c=sqlite3.connect(ds.DATASET)
    c.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE compartments(id INTEGER PRIMARY KEY,external_id TEXT UNIQUE,objectid TEXT,source_layer TEXT,source_row INTEGER,kadastrs TEXT,kvart TEXT,nog TEXT,adm1 TEXT,adm2 TEXT,nog_plat REAL,geometry BLOB,properties TEXT,area_m2 REAL,importable INTEGER,repair TEXT);CREATE VIRTUAL TABLE spatial_index USING rtree(id,min_lon,max_lon,min_lat,max_lat);''')
    for index,f in enumerate(features,1):
        g=shape(f['geometry']);p=f['properties'];fid='VMD:nodala2651:'+str(p['objectid']);w,s,e,n=g.bounds
        c.execute('INSERT INTO compartments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(index,fid,str(p['objectid']),'nodala2651',index,p['kadastrs'],p['kvart'],p['nog'],p.get('adm1',''),p.get('adm2',''),p['nog_plat'],g.wkb,json.dumps(p),shapely.transform(g,equal_area).area,1,None));c.execute('INSERT INTO spatial_index VALUES(?,?,?,?,?)',(index,w,e,s,n))
    report={'indexed':3,'source_crs':'EPSG:10306','extent':list(shapely.union_all([shape(f['geometry']) for f in features]).bounds),'dataset_version':'a'*64,'layers':[{'layer':'nodala2651','feature_count':3}],'repaired':0,'failed':0,'importable':3}
    c.execute('INSERT INTO metadata VALUES(?,?)',('report',json.dumps(report)));c.commit();c.close()
    # Explicit unit-test source verifier for the tiny fixture catalogue. Real-file tests below do not mock this.
    def fixture_association(row,report,designation):
        valid=json.loads(row['properties']).get('kadastrs')==row['kadastrs']==designation
        return {'status':'verified_source_attribute' if valid else 'unverified','classification':'authoritative_vmd_attribute' if valid else 'unverified','source_designation':row['kadastrs'],'requested_designation':designation,'source_field':'kadastrs','cadastral_boundary_verified':False}
    monkeypatch.setattr(ds,'_source_association',fixture_association)
    # Explicit synthetic authority for isolated import unit tests, never live verification.
    from services.geodata import cadastral_authority
    monkeypatch.setattr(cadastral_authority,'verify',lambda designation,geometry=None:{'status':'verified','registration_allowed':True})
    return database,ds,features


def test_bbox_identifier_and_exact_territory(env):
    _,ds,features=env;g=shape(features[0]['geometry']);w,s,e,n=g.bounds
    result=ds.search(bbox=[w-1e-6,s-1e-6,e+1e-6,n+1e-6],mode='intersects')
    assert len(result['features'])==1 and result['features'][0]['properties']['kadastrs']=='40940020002'
    assert result['features'][0]['geometry']==json.loads(json.dumps(mapping(g)))
    assert ds.search(filters={'kadastrs':'40440040167'})['summary']['found']==1
    all_inside=ds.search(territory=mapping(box(w-1e-6,s-1e-6,e+1e-6,n+1e-6)),mode='inside')
    assert all_inside['summary']['fully_inside']==1
    half=box(w-1e-6,s-1e-6,(w+e)/2,n+1e-6)
    overlap=ds.search(territory=mapping(half),mode='intersects')
    assert overlap['summary']['found']==1
    assert 0<overlap['features'][0]['properties']['intersection_ratio']<1
    assert not ds.search(territory=mapping(half),mode='inside')['features']
    assert not ds.search(territory=mapping(half),mode='intersects',min_overlap=100)['features']


def test_pagination_and_result_limits(env):
    _,ds,_=env;r=ds.report();bbox=r['extent'];bbox=[bbox[0]-1e-6,bbox[1]-1e-6,bbox[2]+1e-6,bbox[3]+1e-6]
    first=ds.search(bbox=bbox,limit=1,offset=0);second=ds.search(bbox=bbox,limit=1,offset=1)
    assert first['summary']['found']==3 and first['summary']['has_more']
    assert first['features'][0]['id']!=second['features'][0]['id']
    with pytest.raises(ds.DatasetError,match='zoom in'):ds.search(bbox=[20,55.1,28,58])
    with pytest.raises(ds.DatasetError):ds.search()


@pytest.mark.parametrize('geometry',[{'type':'Point','coordinates':[24,56]}, {'type':'Polygon','coordinates':[]}, {'type':'Polygon','coordinates':[[[24,56],[25,56],[24,57]]]}, {'type':'Polygon','coordinates':[[[24,56],[25,57],[25,56],[24,57],[24,56]]]}])
def test_invalid_territories_rejected(env,geometry):
    _,ds,_=env
    with pytest.raises(ds.DatasetError):ds.territory_geometry(geometry)


def test_save_client_territory_is_separate_and_owner_scoped(env):
    db,ds,features=env;g=shape(features[0]['geometry']).buffer(.001)
    item=ds.save_territory(mapping(g),'Client boundary','Any forestry client','DRAWN','alice')
    assert not item['is_sector'] and item['area_ha']>0
    assert ds.list_territories('alice')[0]['id']==item['id']
    assert ds.list_territories('bob')==[]
    with pytest.raises(ds.DatasetError):ds.get_territory(item['id'],'bob')
    with sqlite3.connect(db.DB_NAME) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==0


def test_dry_run_standard_sector_import_and_duplicate(env):
    db,ds,features=env;item=ds.search(filters={'kadastrs':'40940020002'})['features'][0];fid=item['id']
    dry=ds.selected_import([fid],'a'*64,'test',True,sector_name='Testa sektors');assert dry['would_import']==1 and dry['imported']==0
    with sqlite3.connect(db.DB_NAME) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==0
    saved=ds.selected_import([fid],'a'*64,'test',False,sector_name='Testa sektors');assert saved['imported']==1
    again=ds.selected_import([fid],'a'*64,'test',False,sector_name='Testa sektors');assert again['already_exists']==1 and again['results'][0]['id']==saved['results'][0]['id']
    assert ds.search(filters={'kadastrs':'40940020002'})['features'][0]['properties']['import_status']=='ALREADY IMPORTED'
    with sqlite3.connect(db.DB_NAME) as c:
        boundary=json.loads(c.execute('SELECT boundary_json FROM sectors').fetchone()[0]);assert boundary==[[p[1],p[0]] for p in features[0]['geometry']['coordinates'][0]]
        assert c.execute('SELECT provider FROM geodata_sources').fetchone()[0]=='VMD_OPEN_DATA'
        assert c.execute('SELECT count(*) FROM risks').fetchone()[0]==0
    with pytest.raises(ds.DatasetError):ds.selected_import([fid],'b'*64,'test',sector_name='Testa sektors')


def test_prior_real_local_import_is_recognized_without_rewriting(env,monkeypatch,tmp_path):
    db,ds,features=env
    from services.geodata import vmd_local,vmd_test
    original=vmd_test.SOURCE_FILE
    _,items,version=vmd_local.catalogue();legacy=next(iter(items));old=vmd_local.import_features([legacy],version,'test')
    f=ds.search(filters={'kadastrs':features[0]['properties']['kadastrs']})['features'][0]
    assert f['properties']['import_status']=='ALREADY IMPORTED'
    assert ds.selected_import([f['id']],'a'*64,'test',sector_name='Testa sektors')['already_exists']==1
    with sqlite3.connect(db.DB_NAME) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==1


def test_api_auth_bounds_confirmation_and_no_body_bypass(env,monkeypatch):
    db,ds,features=env
    monkeypatch.setenv('DASHBOARD_USERNAME','prod-test');monkeypatch.setenv('DASHBOARD_PASSWORD','prod-test')
    import api,httpx,fastapi.routing,fastapi.dependencies.utils
    monkeypatch.setattr(api,'DB_NAME',db.DB_NAME)
    async def inline(fn,*a,**kw):return fn(*a,**kw)
    monkeypatch.setattr(fastapi.routing,'run_in_threadpool',inline);monkeypatch.setattr(fastapi.dependencies.utils,'run_in_threadpool',inline)
    async def run():
      async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://test') as c:
        assert (await c.get('/api/geodata/vmd/dataset')).status_code==401
        c.auth=('prod-test','prod-test')
        assert (await c.get('/api/geodata/vmd/dataset')).json()['feature_count']==3
        r=await c.get('/api/geodata/vmd/compartments?kadastrs=40940020002');assert r.status_code==200,r.text
        fid=r.json()['features'][0]['id']
        selection=await c.post('/api/geodata/vmd/select-matching',json={'kadastrs':'40940020002','dataset_version':'a'*64})
        assert selection.status_code==200 and selection.json()['selected_count']==1
        assert (await c.post('/api/geodata/vmd/select-matching',json={'kadastrs':'40940020002'},headers={'Origin':'http://other'})).status_code==403
        geometry=mapping(shape(features[0]['geometry']).buffer(.001))
        r=await c.post('/api/geodata/vmd/search-territory',json={'geometry':geometry,'mode':'inside'});assert r.status_code==200,r.text
        assert r.json()['summary']['found']==1
        assert (await c.post('/api/geodata/vmd/search-territory',json={'geometry':geometry},headers={'Origin':'http://other'})).status_code==403
        assert (await c.post('/api/geodata/vmd/search-territory',content=b'x'*(2*1024*1024+1),headers={'Content-Type':'application/json'})).status_code==413
        body={'feature_ids':[fid],'dataset_version':'a'*64,'sector_name':'Testa sektors','responsible_first_name':'Testa','responsible_last_name':'Persona'}
        assert (await c.post('/api/geodata/vmd/import-selected',json=body)).json()['would_import']==1
        assert (await c.post('/api/geodata/vmd/import-selected',json={**body,'dry_run':False})).status_code==400
        saved=(await c.post('/api/geodata/vmd/import-selected',json={**body,'dry_run':False,'confirmed':True})).json()
        assert saved['imported']==1
        assert any(s['name']==saved['results'][0]['name'] for s in (await c.get('/api/sectors')).json())
        assert any(s['name']==saved['results'][0]['name'] for s in (await c.get('/api/map')).json())
        from urllib.parse import quote
        named={**body,'sector_name':'Zaļais mežs <&>','feature_ids':[ds.search(filters={'kadastrs':'40440040167'})['features'][0]['id']],'dry_run':False,'confirmed':True}
        named_result=(await c.post('/api/geodata/vmd/import-selected',json=named)).json();assert named_result['imported']==1
        pdf=await c.get('/api/report/pdf/'+quote(named['sector_name'],safe=''));assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
        assert "filename*=UTF-8''forest_ai_Za%C4%BCais" in pdf.headers['content-disposition']
        assert any(item['sector']==named['sector_name'] for item in (await c.get('/api/satellite-intel/sectors')).json())
        assert (await c.post('/api/geodata/vmd/import-selected',json={k:v for k,v in body.items() if k!='sector_name'})).status_code==422
    asyncio.run(run())


def test_malformed_types_and_nonfinite_source_area_are_safe(env):
    _,ds,features=env
    for value in [{'type':[],'coordinates':[]},{'type':'Polygon','coordinates':[],'crs':{'properties':{'name':[]}}}]:
        with pytest.raises(ds.DatasetError):ds.territory_geometry(value)
    with sqlite3.connect(ds.DATASET) as c:c.execute('UPDATE compartments SET nog_plat=? WHERE id=1',(float('inf'),))
    r=ds.search(filters={'kadastrs':'40940020002'})
    assert 0<r['features'][0]['properties']['area_ha']<10


def test_3059_territory_axis_order_and_multipolygon(env):
    from pyproj import Transformer
    from shapely.ops import transform
    from shapely.geometry import MultiPolygon
    _,ds,features=env
    original=shape(features[0]['geometry'])
    native=transform(Transformer.from_crs(4326,3059,always_xy=True).transform,original)
    value=mapping(native);value['crs']={'type':'name','properties':{'name':'EPSG:3059'}}
    normalized,area=ds.territory_geometry(value)
    assert original.hausdorff_distance(normalized)<1e-8 and area>0
    multi=MultiPolygon([original,shape(features[1]['geometry'])])
    assert ds.territory_geometry(mapping(multi))[0].geom_type=='MultiPolygon'


def test_territory_client_id_persists_and_import_is_owner_scoped(env):
    db,ds,features=env
    item=ds.save_territory(mapping(shape(features[0]['geometry']).buffer(.001)),'Teritorija','Klients','DRAWN','alice','client-42')
    stored=ds.get_territory(item['id'],'alice')
    assert stored['properties']['client_id']=='client-42' and stored['properties']['crs']=='EPSG:4326'
    fid=ds.search(filters={'kadastrs':'40940020002'})['features'][0]['id']
    with pytest.raises(ds.DatasetError):ds.selected_import([fid],'a'*64,'bob',False,item['id'],sector_name='Testa sektors')
    result=ds.selected_import([fid],'a'*64,'alice',False,item['id'],sector_name='Testa sektors')
    with sqlite3.connect(db.DB_NAME) as c:
        metadata=json.loads(c.execute('SELECT source_properties FROM geodata_sources').fetchone()[0])
        assert metadata['organization_id']==1 and metadata['territory_id']==item['id']
        assert metadata['normalized_geometry']==features[0]['geometry']
        assert c.execute('SELECT contractor FROM sectors').fetchone()[0]==''


def test_whole_transaction_rolls_back_after_audit_failure(env,monkeypatch):
    db,ds,_=env
    fid=ds.search(filters={'kadastrs':'40940020002'})['features'][0]['id']
    def fail(*args,**kwargs):raise RuntimeError('unit test injected audit failure')
    monkeypatch.setattr(ds.store,'_history',fail)
    with pytest.raises(RuntimeError):ds.selected_import([fid],'a'*64,'test',False,sector_name='Testa sektors')
    with sqlite3.connect(db.DB_NAME) as c:
        for table in ['sectors','geodata_sources','geodata_boundary_history']:
            assert c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0


def test_cadastral_normalization_preserves_digits_and_requires_explicit_partial_mode(env):
    _,ds,_=env
    assert ds.normalize_cadastral(' 4094 002 0002 ')==('40940020002','exact')
    assert ds.normalize_cadastral('4094-002-0002')==('40940020002','exact')
    assert ds.normalize_cadastral('00010020003')==('00010020003','exact')
    assert ds.normalize_cadastral('40940020002','prefix')==('40940020002','exact')
    assert ds.normalize_cadastral('4094002','prefix')==('4094002','prefix')
    for value in ['4094002','4094%','4094_','40940020002x','409400200020','4e0940020002']:
        with pytest.raises(ds.DatasetError):ds.normalize_cadastral(value)
    for value in ['409%','409','40940020002x']:
        with pytest.raises(ds.DatasetError):ds.normalize_cadastral(value,'prefix')


def test_exact_cadastral_search_never_falls_back_to_prefix_or_unrelated_ids(env):
    _,ds,_=env
    for value in ['40940020002','4094 002 0002','4094-002-0002']:
        result=ds.search(filters={'kadastrs':value})
        assert result['summary']['found']==1
        assert result['summary']['cadastral_search']=={'field':'kadastrs','value':'40940020002','match':'exact'}
        assert all(f['properties']['kadastrs']=='40940020002' for f in result['features'])
    assert ds.search(filters={'kadastrs':'99999999999'})['summary']['found']==0
    # A source OBJECTID must not be used as an alternate cadastral match.
    with sqlite3.connect(ds.DATASET) as c:c.execute("UPDATE compartments SET objectid='99999999999' WHERE id=1")
    assert ds.search(filters={'kadastrs':'99999999999'})['features']==[]
    partial=ds.search(filters={'kadastrs':'4094','kadastrs_match':'prefix'})
    assert partial['summary']['found']==1 and partial['summary']['cadastral_search']['match']=='prefix'
    with pytest.raises(ds.DatasetError):ds.search(filters={'kadastrs':'4094'})
    with pytest.raises(ds.DatasetError):ds.search(filters={'kadastrs_match':'exact'})


def test_multiple_compartments_and_duplicate_identity_are_distinct_concepts(env):
    # Explicit unit fixture: assign a second real polygon a test cadastral attribute.
    _,ds,_=env
    with sqlite3.connect(ds.DATASET) as c:
        row=c.execute('SELECT properties FROM compartments WHERE id=2').fetchone()
        props=json.loads(row[0]);props['kadastrs']='40940020002';props['nog']='99'
        c.execute('UPDATE compartments SET kadastrs=?,nog=?,properties=? WHERE id=2',('40940020002','99',json.dumps(props)))
        with pytest.raises(sqlite3.IntegrityError):c.execute('UPDATE compartments SET external_id=(SELECT external_id FROM compartments WHERE id=1) WHERE id=2')
    result=ds.search(filters={'kadastrs':'40940020002'})
    assert result['summary']['found']==2
    assert len({f['id'] for f in result['features']})==2
    assert {f['properties']['nog'] for f in result['features']}=={'6','99'}
    one=ds.search(filters={'kadastrs':'40940020002'},limit=1)
    two=ds.search(filters={'kadastrs':'40940020002'},limit=1,offset=1)
    assert one['summary']['found']==2 and one['features'][0]['id']!=two['features'][0]['id']


def test_actual_audited_cadastral_snapshot_matches_original_evidence():
    import shapely
    from services.geodata import vmd_dataset as ds
    artifact=Path(__file__).resolve().parents[1]/'data/vmd/cadastral-audit-40940020002/audit.json'
    if not artifact.is_file():pytest.skip('Independent source audit has not been run in this environment')
    audit=json.loads(artifact.read_text())
    assert audit['source_records']==audit['catalogue_records']==10
    assert audit['duplicate_source_ids']==audit['duplicate_compartment_keys']==audit['duplicate_geometries']==0
    assert audit['max_geometry_difference_m']<.01
    assert all(row['cadastral_designation']=='40940020002' and row['geometry_valid'] for row in audit['rows'])
    with ds.connect() as c:
        rows=c.execute('SELECT external_id,geometry FROM compartments WHERE kadastrs=?',('40940020002',)).fetchall()
        current={row['external_id']:shapely.from_wkb(row['geometry']) for row in rows}
    assert set(current)=={row['source_feature_id'] for row in audit['rows']}
    assert all(current[row['source_feature_id']].equals_exact(shape(row['normalized_geometry']),0) for row in audit['rows'])


def test_shared_import_preview_carries_client_area_validity_and_provenance(env):
    db,ds,_=env
    fid=ds.search(filters={'kadastrs':'40940020002'})['features'][0]['id']
    preview=ds.selected_import([fid],'a'*64,'owner',True,responsible_first_name='Testa',responsible_last_name='Persona',sector_name='Testa sektors')
    assert preview['registration_identity']['organization_id']==1 and preview['registration_identity']['authenticated_account']=='owner'
    assert preview['registration_identity']['user_id'] is None
    assert preview['valid_geometry_count']==1 and preview['total_area_ha']>0
    assert preview['results'][0]['geometry_valid'] and preview['results'][0]['kadastrs']=='40940020002'
    saved=ds.selected_import([fid],'a'*64,'owner',False,responsible_first_name='Testa',responsible_last_name='Persona',sector_name='Testa sektors')
    with sqlite3.connect(db.DB_NAME) as c:
        source=json.loads(c.execute('SELECT source_properties FROM geodata_sources').fetchone()[0])
        assert source['organization_id']==1 and source['authenticated_owner']=='owner'
        assert source['responsible_first_name']=='Testa' and source['created_by_user_id'] is None
        assert source['normalized_geometry'] and source['original_crs']=='EPSG:10306'
    duplicate=ds.selected_import([fid],'a'*64,'owner',True,sector_name='Testa sektors')
    assert duplicate['already_exists']==1 and duplicate['valid_geometry_count']==1


def test_select_all_matching_is_explicit_bounded_and_version_checked(env,monkeypatch):
    _,ds,_=env
    result=ds.matching_selection(filters={'kadastrs':'40940020002'},dataset_version='a'*64)
    assert result['selection_scope']=='matching' and result['selected_count']==1 and result['summary']['found']==1
    with pytest.raises(ds.DatasetError,match='version changed'):ds.matching_selection(filters={'kadastrs':'40940020002'},dataset_version='b'*64)
    original=ds.search
    monkeypatch.setattr(ds,'search',lambda **kw:{'dataset_version':'a'*64,'features':[],'summary':{'found':101}})
    with pytest.raises(ds.DatasetError,match='100 nogabaliem'):ds.matching_selection(filters={'kadastrs':'40940020002'})


def test_saved_territory_cannot_change_client_or_owner_during_import(env):
    _,ds,features=env
    item=ds.save_territory(mapping(shape(features[0]['geometry']).buffer(.001)),'Robeža','Klients','DRAWN','owner','client-1')
    fid=ds.search(filters={'kadastrs':'40940020002'})['features'][0]['id']
    with pytest.raises(ds.DatasetError):ds.selected_import([fid],'a'*64,'other',True,item['id'],sector_name='Testa sektors')
    preview=ds.selected_import([fid],'a'*64,'owner',True,item['id'],'Testa','Persona',sector_name='Testa sektors')
    assert preview['registration_identity']['organization_id']==1


def test_registration_route_requires_exact_eleven_digit_land_unit(env,monkeypatch):
    db,ds,_=env
    monkeypatch.setenv('DASHBOARD_USERNAME','registration-test');monkeypatch.setenv('DASHBOARD_PASSWORD','registration-test')
    import api,httpx,fastapi.routing,fastapi.dependencies.utils
    monkeypatch.setattr(api,'DB_NAME',db.DB_NAME)
    async def inline(fn,*a,**kw):return fn(*a,**kw)
    monkeypatch.setattr(fastapi.routing,'run_in_threadpool',inline);monkeypatch.setattr(fastapi.dependencies.utils,'run_in_threadpool',inline)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://test') as c:
            assert (await c.get('/api/geodata/vmd/cadastre?kadastrs=40940020002')).status_code==401
            c.auth=('registration-test','registration-test')
            for value in ['4094','409400200020','4094 002 0002','4094002000X','１２３４５６７８９０１']:
                assert (await c.get('/api/geodata/vmd/cadastre',params={'kadastrs':value})).status_code==422
            good=await c.get('/api/geodata/vmd/cadastre',params={'kadastrs':'40940020002'})
            assert good.status_code==200
            result=good.json();assert result['summary']['found']==1
            assert result['summary']['cadastral_search']['match']=='exact'
            assert result['summary']['bounds']==list(shape(result['features'][0]['geometry']).bounds)
            assert (await c.get('/api/geodata/vmd/cadastre?kadastrs=99999999999')).json()['summary']['found']==0
    asyncio.run(run())


def test_unverified_cadastre_cannot_register_even_with_valid_source_geometry(env,monkeypatch):
    db,ds,_=env
    from services.geodata import cadastral_authority
    monkeypatch.setattr(cadastral_authority,'verify',lambda designation,geometry=None:{'status':'unverified','registration_allowed':False,'message':'Kadastra dati nav pārbaudīti'})
    result=ds.verified_cadastral_search('40940020002')
    assert result['summary']['found']==1
    f=result['features'][0]
    assert f['properties']['geometry_valid'] and not f['properties']['importable']
    with sqlite3.connect(db.DB_NAME) as c:before=c.execute('SELECT count(*) FROM sectors').fetchone()[0]
    result=ds.selected_import([f['id']],'a'*64,'owner',False,responsible_first_name='Testa',responsible_last_name='Persona',sector_name='Testa sektors')
    assert result['imported']==0 and result['failed']==1
    assert result['results'][0]['reason']=='Kadastra dati nav pārbaudīti'
    with sqlite3.connect(db.DB_NAME) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==before


def test_source_attribute_mismatch_fails_closed_separately_from_geometry(env,monkeypatch):
    _,ds,_=env
    monkeypatch.setattr(ds,'_source_association',lambda *a:{'status':'unverified'})
    result=ds.verified_cadastral_search('40940020002')
    assert result['features']==[] and result['cadastral_verification']['unverified_count']==1


def test_organization_and_audit_identity_are_server_controlled(env):
    db,ds,_=env
    from services.geodata.vmd_production import Import
    from pydantic import ValidationError
    body={'feature_ids':['VMD:nodala2651:1'],'dataset_version':'a'*64,'sector_name':'Testa sektors','responsible_first_name':'Testa','responsible_last_name':'Persona'}
    for field in ['organization_id','user_id','created_by_user_id','client_id','client_name']:
        with pytest.raises(ValidationError):Import(**body,**{field:'forged'})
    fid=ds.search(filters={'kadastrs':'40940020002'})['features'][0]['id']
    result=ds.selected_import([fid],'a'*64,'alice',False,responsible_first_name='Testa',responsible_last_name='Persona',sector_name='Testa sektors')
    assert result['imported']==1
    # Trusted actors in the same instance organization share source identities.
    assert ds.selected_import([fid],'a'*64,'bob',True,sector_name='Testa sektors')['already_exists']==1
    with sqlite3.connect(db.DB_NAME) as c:
        row=c.execute('SELECT organization_id,created_by_user_id,created_by_account,responsible_first_name,responsible_last_name,created_at FROM sectors').fetchone()
        assert row[:5]==(1,None,'alice','Testa','Persona') and row[5]
        c.execute("INSERT INTO organizations(id,name) VALUES(2,'Other')")
    with pytest.raises(ds.DatasetError,match='Organizācijas'):ds.selected_import([fid],'a'*64,'alice',True,sector_name='Testa sektors')


@pytest.mark.parametrize('designation,count',[('01000950030',209),('01000950031',6),('40940020002',10)])
def test_real_native_source_exact_designations_geometry_and_cadastral_gate(designation,count):
    from services.geodata import vmd_dataset as ds
    result=ds.verified_cadastral_search(designation)
    assert result['summary']['found']==count
    assert result['cadastral_verification']['verified_count']==count
    assert result['cadastral_validation']['status']=='verified_land_unit'
    for feature in result['features']:
        props=feature['properties']
        assert props['kadastrs']==props['cadastral_association']['source_designation']==designation
        assert props['geometry_valid']
        assert props['cadastral_validation']['status'] in {'verified','boundary_review_required'}
        if props['cadastral_validation']['status']=='boundary_review_required':assert not props['importable']
    artifact=Path(__file__).resolve().parents[1]/f'data/vmd/cadastral-audit-{designation}/audit.json'
    audit=json.loads(artifact.read_text());expected={r['source_feature_id']:r for r in audit['rows']}
    for offset in range(0,count,100):
        page=ds.verified_cadastral_search(designation,offset=offset)
        assert all(f['geometry']==expected[f['id']]['normalized_geometry'] for f in page['features'])


def test_official_parcel_geometry_and_strict_boundary_discrepancies():
    from services.geodata import cadastral_authority as authority,vmd_dataset as ds
    parcel=authority.verify('01000950031')
    assert parcel['land_unit_exists'] and parcel['source_designation']=='01000950031'
    assert shape(parcel['land_unit_geometry']).is_valid
    assert abs(parcel['land_unit_area_ha']-5.179558728)<1e-8
    result=ds.verified_cadastral_search('01000950031')
    states=[f['properties']['cadastral_validation'] for f in result['features']]
    assert sum(s['status']=='verified' for s in states)==1
    assert sum(s['status']=='boundary_review_required' for s in states)==5
    assert min(s['overlap_percent'] for s in states)>99.998
    assert all(not s['registration_allowed'] for s in states if s['outside_area_m2']>0)
    assert authority.verify('99999999999')['registration_allowed'] is False


def test_additive_audit_migration_preserves_production_snapshot(tmp_path,monkeypatch):
    import database
    original=Path(__file__).resolve().parents[1]/'data/forest_ai.db';copy=tmp_path/'migration.db'
    with sqlite3.connect('file:'+str(original)+'?mode=ro',uri=True) as src,sqlite3.connect(copy) as dst:src.backup(dst)
    with sqlite3.connect(copy) as c:
        cols=[r[1] for r in c.execute('PRAGMA table_info(sectors)')]
        before=c.execute('SELECT '+','.join(cols)+' FROM sectors ORDER BY id').fetchall()
        risks=c.execute('SELECT * FROM risks').fetchall()
    monkeypatch.setattr(database,'DB_NAME',str(copy));database.init_db()
    with sqlite3.connect(copy) as c:
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert c.execute('SELECT '+','.join(cols)+' FROM sectors ORDER BY id').fetchall()==before
        assert c.execute('SELECT * FROM risks').fetchall()==risks
        assert {'organization_id','created_by_user_id','created_by_account','responsible_first_name','responsible_last_name'}<={r[1] for r in c.execute('PRAGMA table_info(sectors)')}


def test_required_name_is_persisted_and_existing_named_sector_is_not_overwritten(env):
    db,ds,_=env
    ids=[f['id'] for f in ds.search(bbox=ds.report()['extent'])['features']]
    for name in [None,'','   ','a'*121,'bad/name','bad\\name','bad\nname']:
        with pytest.raises(ds.DatasetError,match='nosaukumu'):ds.selected_import([ids[0]],'a'*64,'owner',True,sector_name=name)
    first=ds.selected_import([ids[0]],'a'*64,'owner',False,responsible_first_name='Anna',responsible_last_name='Liepa',sector_name='  Zaļais mežs  ')
    assert first['imported']==1 and first['results'][0]['name']=='Zaļais mežs'
    second=ds.selected_import([ids[1]],'a'*64,'owner',False,sector_name='Zaļais mežs')
    assert second['imported']==0 and second['failed']==1
    with sqlite3.connect(db.DB_NAME) as c:
        assert c.execute('SELECT name,responsible_first_name,responsible_last_name,organization_id FROM sectors').fetchall()==[('Zaļais mežs','Anna','Liepa',1)]
        source=json.loads(c.execute('SELECT source_properties FROM geodata_sources').fetchone()[0]);assert source['registration_sector_name']==source['sector_name']=='Zaļais mežs'
    assert ds.selected_import([ids[0]],'a'*64,'owner',False,sector_name='Cits nosaukums')['already_exists']==1


def test_multiple_compartment_names_are_distinct_in_preview_and_persistence(env):
    db,ds,_=env
    ids=[f['id'] for f in ds.search(bbox=ds.report()['extent'])['features']][:2]
    preview=ds.selected_import(ids,'a'*64,'owner',True,sector_name='Meža uzraudzība')
    names=[r['name'] for r in preview['results']];assert len(set(names))==2 and all(n.startswith('Meža uzraudzība — ') for n in names)
    saved=ds.selected_import(ids,'a'*64,'owner',False,sector_name='Meža uzraudzība')
    assert saved['imported']==2 and [r['name'] for r in saved['results']]==names
    with sqlite3.connect(db.DB_NAME) as c:assert {r[0] for r in c.execute('SELECT name FROM sectors')}==set(names)


@pytest.mark.parametrize('designation',['80840050013','80600030025','80960030024'])
def test_actual_logged_no_match_reports_limited_source_coverage(designation):
    from services.geodata import vmd_dataset as ds
    result=ds.verified_cadastral_search(designation)
    assert result['summary']['found']==0 and result['features']==[]
    assert result['cadastral_verification']['status']=='not_found'
    assert result['coverage']['complete_national_coverage'] is False
    assert 'nevis visu Latviju' in result['search_message']
    assert result['cadastral_validation']['land_unit_exists'] is True
    assert 'VZD zemes vienība ir pārbaudīta' in result['search_message']


def test_official_outside_parcel_is_coverage_diagnostic_never_a_forest_match():
    # CODE read from original VZD Daugavpils KKParcel row1, not invented input.
    from services.geodata import vmd_dataset as ds
    result=ds.verified_cadastral_search('05000010139')
    assert result['cadastral_validation']['source_designation']=='05000010139'
    assert result['cadastral_validation']['land_unit_exists']
    assert result['coverage']['status']=='outside_loaded_extent'
    assert result['summary']['found']==0 and result['features']==[]
    assert 'ārpus ielādētās VMD' in result['search_message']
