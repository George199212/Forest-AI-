"""Explicit synthetic unit catalogue; real nationwide acceptance is a separate script.
No fixture in this module is evidence of official cadastral membership.
"""
import importlib.util,json,sqlite3
from pathlib import Path
import pytest,shapely
from shapely.geometry import shape,mapping
from shapely.affinity import translate
from shapely.ops import transform
from pyproj import Transformer

@pytest.fixture
def national(tmp_path,monkeypatch):
    import database
    from services.geodata import nationwide as nw,vmd_dataset as ds
    spec=importlib.util.spec_from_file_location('forest_ingestion_unit',Path(__file__).resolve().parents[1]/'scripts/ingest_nationwide_geodata.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    job=module.Job(tmp_path/'catalogue');forest=job.db('vmd');parcels=job.db('vzd')
    monkeypatch.setattr(database,'DB_NAME',str(tmp_path/'app.db'));database.init_db()
    f=json.loads((Path(__file__).resolve().parents[1]/'lvm_3_sectors.geojson').read_text())['features'][0]
    projected=transform(Transformer.from_crs(4326,10306,always_xy=True).transform,shape(f['geometry']));extent=None
    for i,code in enumerate(['40940020002','40440040167'],1):
        native=projected if i==1 else translate(projected,xoff=2)
        display=shapely.transform(native,module.to_wgs84);w,s,e,n=display.bounds;props={**f['properties'],'kadastrs':code,'objectid':90000000+i,'kvart':1,'nog':i}
        values=('VMD:unit:'+str(90000000+i),str(90000000+i),'unit',i,code,'1',str(i),'Testa novads','Testa pagasts',.5,display.wkb,json.dumps(props),native.area,1,None,'Unit','unit.shp','2026-11-06','unit-hash','EPSG:10306',native.wkb,None,1,1)
        cur=forest.execute('INSERT INTO compartments(external_id,objectid,source_layer,source_row,kadastrs,kvart,nog,adm1,adm2,nog_plat,geometry,properties,area_m2,importable,repair,source_region,source_file,source_date,archive_sha256,source_crs,native_geometry,original_geometry,geometry_valid,source_verified) VALUES('+','.join('?' for _ in values)+')',values)
        a,b,c,d=native.bounds;forest.execute('INSERT INTO native_index VALUES(?,?,?,?,?)',(cur.lastrowid,a,c,b,d));forest.execute('INSERT INTO spatial_index VALUES(?,?,?,?,?)',(cur.lastrowid,w,e,s,n));extent=[w,s,e,n]
    for code,shift in [('40940020002',0),('01000950031',0),('01000950030',50000)]:
        native=translate(projected.buffer(20),xoff=shift);display=shapely.transform(native,module.to_wgs84)
        parcels.execute('INSERT INTO parcels(designation,geometry,native_geometry,source_crs,source_file,source_row,source_attributes,source_region,source_date,archive_sha256,area_m2,geometry_valid,source_verified) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(code,display.wkb,native.wkb,'EPSG:10306','unit/KKParcel.shp',1,json.dumps({'CODE':code}),'Unit','2026-11-06','unit-parcel-hash',native.area,1,1))
    report={'indexed':2,'dataset_version':'b'*64,'source_crs':'EPSG:10306','extent':extent,'repaired':0,'failed':0,'importable':2,'regions':['Unit'],'layers':[{'layer':'unit','feature_count':2}]}
    forest.execute('INSERT INTO metadata VALUES(?,?)',('report',json.dumps(report)));forest.commit();parcels.commit();forest.close();parcels.close()
    sources=[{'kind':'vmd','id':'unit-vmd-'+str(i),'validated':True,'name':str(i),'source_date':'2026-11-06'} for i in range(5)]+[{'kind':'vzd','id':'unit-vzd-'+str(i),'validated':True,'name':str(i),'source_date':'2026-11-06'} for i in range(42)]
    manifest={'schema':1,'status':'READY','version':'b'*64,'forest_db':str(job.root/'compartments.sqlite'),'parcel_db':str(job.root/'parcels.sqlite'),'sources':sources,'created_at':'2026-11-06','reports':{'vmd':report,'vzd':{'indexed':3}},'licences':{'vmd':'CC0-1.0','vzd':'CC-BY-4.0'}}
    path=job.root/'release.json';path.write_text(json.dumps(manifest));monkeypatch.setenv('FOREST_GEODATA_MANIFEST',str(path));nw._parcel.cache_clear();nw._manifest.cache_clear()
    yield database,nw,ds,job.root,manifest
    job.lock.close()


def test_exact_and_spatial_candidates_are_separate(national):
    _,nw,_,_,_=national;r=nw.search('40940020002')
    assert r['state']=='VMD_MATCHES_FOUND' and 'CADASTRAL_PARCEL_FOUND' in r['states']
    assert len(r['features'])==1 and r['features'][0]['properties']['kadastrs']=='40940020002'
    assert r['features'][0]['properties']['importable']
    assert len(r['spatial_candidates'])==1
    candidate=r['spatial_candidates'][0];assert candidate['properties']['kadastrs']=='40440040167'
    assert candidate['properties']['association_classification']=='spatial_inferred'
    assert not candidate['properties']['importable'] and 'SPATIAL_REVIEW_REQUIRED' in r['states']
    assert r['cadastral_validation']['source_designation']=='40940020002'


def test_explicit_states_and_leading_zeros(national):
    _,nw,_,_,_=national
    assert nw.search('01000950030')['state']=='NO_VMD_RECORDS'
    assert nw.search('01000950030')['cadastral_validation']['source_designation']=='01000950030'
    assert nw.search('01000950031')['state']=='SPATIAL_REVIEW_REQUIRED'
    assert nw.search('99999999999')['state']=='PARCEL_NOT_FOUND'
    with pytest.raises(ValueError):nw.search('0100')


def test_readiness_and_source_errors(national,monkeypatch):
    _,nw,_,root,_=national
    path=root/'missing.json';monkeypatch.setenv('FOREST_GEODATA_MANIFEST',str(path))
    assert nw.search('40940020002')['state']=='DATASET_NOT_READY'
    path.write_text('{bad');assert nw.search('40940020002')['state']=='SOURCE_ERROR'
    path.write_text(json.dumps({'schema':1,'status':'BUILDING'}));assert nw.search('40940020002')['state']=='DATASET_NOT_READY'


def test_national_registration_persists_original_geometry_and_vzd_reference(national):
    db,nw,ds,_,_=national;r=nw.search('40940020002');fid=r['features'][0]['id']
    with pytest.raises(ds.DatasetError):ds.selected_import([fid],'b'*64,'account',True,sector_name='Mežs')
    saved=ds.selected_import([fid],'b'*64,'account',False,responsible_first_name='Testa',responsible_last_name='Persona',sector_name='Mežs',requested_designation='40940020002')
    assert saved['imported']==1
    with sqlite3.connect(db.DB_NAME) as c:
        row=c.execute('SELECT name,organization_id,created_by_account,responsible_first_name,responsible_last_name FROM sectors').fetchone();assert row==('Mežs',1,'account','Testa','Persona')
        source=json.loads(c.execute('SELECT source_properties FROM geodata_sources').fetchone()[0]);assert source['vzd_geometry_reference']['designation']=='40940020002'
        assert source['vzd_geometry_reference']['source_crs']=='EPSG:10306' and source['cadastral_validation']['land_unit_geometry'] is None
        assert source['original_source_geometry'] and source['cadastral_designation']=='40940020002'
    assert ds.selected_import([fid],'b'*64,'second-trusted-account',True,sector_name='Other',requested_designation='40940020002')['already_exists']==1


def test_spatial_candidate_cannot_be_imported_under_requested_parcel(national):
    db,nw,ds,_,_=national;r=nw.search('40940020002');fid=r['spatial_candidates'][0]['id']
    result=ds.selected_import([fid],'b'*64,'account',False,sector_name='Test',requested_designation='40940020002')
    assert result['imported']==0 and result['failed']==1
    with sqlite3.connect(db.DB_NAME) as c:assert c.execute('SELECT count(*) FROM sectors').fetchone()[0]==0


def test_conflicting_source_and_invalid_geometry_are_not_automatically_registrable(national):
    _,nw,_,root,m=national
    with sqlite3.connect(root/'compartments.sqlite') as c:c.execute('UPDATE compartments SET source_verified=0 WHERE kadastrs=?',('40940020002',))
    result=nw.search('40940020002');assert not result['features'][0]['properties']['importable'];assert result['state']=='SPATIAL_REVIEW_REQUIRED'
    with sqlite3.connect(root/'parcels.sqlite') as c:c.execute('UPDATE parcels SET geometry_valid=0')
    nw._parcel.cache_clear();assert nw.search('40940020002')['state']=='SOURCE_ERROR'


def test_independent_review_pagination(national):
    _,nw,_,_,_=national;r=nw.search('01000950031',limit=1)
    assert r['summary']['found']==0 and r['spatial_summary']['found']==2 and r['spatial_summary']['has_more']
    next_page=nw.search('01000950031',limit=1,review_offset=1)
    assert r['spatial_candidates'][0]['id']!=next_page['spatial_candidates'][0]['id']


def test_display_repairs_preserve_native_geometry_and_block_automatic_import(national):
    _,_,_,root,_=national
    import sys
    module=sys.modules.get('forest_ingestion_unit')
    if module is None:
        spec=importlib.util.spec_from_file_location('forest_ingestion_unit',Path(__file__).resolve().parents[1]/'scripts/ingest_nationwide_geodata.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    from shapely.geometry import Polygon
    job=module.Job(root/'repair-test');c=job.db('vmd');native=Polygon([(500000,300000),(500100,300000),(500100,300100),(500000,300100),(500000,300000)])
    invalid_display=Polygon([(24,57),(24.01,57.01),(24.01,57),(24,57.01),(24,57)])
    props={'kadastrs':'40940020002','objectid':90000003,'kvart':1,'nog':1,'nog_plat':1};item={'kind':'vmd','name':'Unit','source_date':'2026-11-06'}
    assert job.store_record(c,root/'unit-extra.shp',{'source_crs':'EPSG:10306'},item,'unit',1,props,native,None,native,True,invalid_display)
    row=c.execute('SELECT native_geometry,importable,repair FROM compartments').fetchone();assert bytes(row[0])==native.wkb and not row[1] and row[2]
    c.close();job.lock.close()


def test_download_resumes_from_committed_partial_bytes(national,monkeypatch):
    import sys
    _,_,_,root,_=national
    spec=importlib.util.spec_from_file_location('forest_download_unit',Path(__file__).resolve().parents[1]/'scripts/ingest_nationwide_geodata.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    job=module.Job(root/'download-test');payload=b'unit-archive-bytes';calls=[]
    class Response:
        status_code=206
        def __init__(self,offset):self.offset=offset;self.headers={'Content-Range':f'bytes {offset}-{len(payload)-1}/{len(payload)}'}
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def raise_for_status(self):pass
        def iter_content(self,size):
            if self.offset==0:
                yield payload[:5];raise module.requests.ConnectionError('Explicit simulated interrupted unit download')
            yield payload[self.offset:]
    def get(url,headers,**kw):
        offset=int(headers['Range'].split('=')[1].split('-')[0]);calls.append(offset);return Response(offset)
    monkeypatch.setattr(module.requests,'get',get);monkeypatch.setattr(module.time,'sleep',lambda *a:None)
    item={'kind':'vmd','id':'unit','size':len(payload),'url':'https://data.gov.lv/unit'};job.download(item)
    assert calls==[0,5] and (job.root/'downloads/unit.7z').read_bytes()==payload
    job.lock.close()


def test_quarantined_exact_source_returns_error_instead_of_false_no_records(national):
    _,nw,_,root,_=national
    with sqlite3.connect(root/'compartments.sqlite') as c:c.execute('INSERT INTO rejections VALUES(?,?,?,?)',('unit.shp',99,'Explicit invalid unit geometry',json.dumps({'kadastrs':'40940020002'})))
    result=nw.search('40940020002');assert result['state']=='SOURCE_ERROR' and result['features']==[]
    with sqlite3.connect(root/'parcels.sqlite') as c:c.execute('INSERT INTO rejections VALUES(?,?,?,?)',('KKParcel.shp',99,'Explicit invalid unit geometry',json.dumps({'CODE':'99999999999'})))
    assert nw.search('99999999999')['state']=='SOURCE_ERROR'
