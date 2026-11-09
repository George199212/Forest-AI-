"""Real-catalogue acceptance using a disposable app DB; never writes production data.
Run from the existing project root: python3 scripts/verify_vmd_integration.py
"""
import asyncio,json,sqlite3,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import database,api,httpx,fastapi.routing,fastapi.dependencies.utils
from shapely.geometry import box,mapping,shape
from services.geodata import vmd_dataset as data

async def inline(fn,*a,**kw):return fn(*a,**kw)

async def verify():
    result={}
    with tempfile.TemporaryDirectory(prefix='forest-vmd-acceptance-') as directory:
        target=Path(directory)/'app.db'
        with sqlite3.connect('file:'+str(Path(database.DB_NAME).resolve())+'?mode=ro',uri=True) as source,sqlite3.connect(target) as dest:source.backup(dest)
        with patch.object(database,'DB_NAME',str(target)),patch.object(api,'DB_NAME',str(target)),patch.object(data,'TERRITORIES',Path(directory)/'territories.sqlite'),patch.object(fastapi.routing,'run_in_threadpool',inline),patch.object(fastapi.dependencies.utils,'run_in_threadpool',inline):
            # Explicit dependency override applies only inside this disposable ASGI process.
            api.app.dependency_overrides[api.verify_credentials]=lambda:'acceptance-user'
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://test') as client:
                    metadata=(await client.get('/api/geodata/vmd/dataset')).json()
                    result['indexed']=metadata['feature_count']
                    territory=mapping(box(24.4145,56.677,24.4175,56.6785))
                    r=await client.post('/api/geodata/vmd/territories',json={'geometry':territory,'name':'Pārbaudes teritorija','client_name':'Pārbaudes klients','client_id':'acceptance-client','source':'DRAWN'})
                    assert r.status_code==200,r.text
                    tid=r.json()['id']
                    assert (await client.get('/api/geodata/vmd/territories/'+tid)).json()['properties']['client_id']=='acceptance-client'
                    search={'geometry':territory,'mode':'intersects','limit':1}
                    first=(await client.post('/api/geodata/vmd/search-territory',json=search)).json()
                    second=(await client.post('/api/geodata/vmd/search-territory',json={**search,'offset':1})).json()
                    assert first['summary']['found']>1 and first['features'][0]['id']!=second['features'][0]['id']
                    all_found=(await client.post('/api/geodata/vmd/search-territory',json={**search,'limit':100})).json()
                    selected=next(f for f in all_found['features'] if f['properties']['importable'])
                    body={'feature_ids':[selected['id']],'dataset_version':metadata['dataset_version'],'territory_id':tid}
                    preview=(await client.post('/api/geodata/vmd/import-selected',json=body)).json()
                    assert preview['would_import']==1 and preview['imported']==0
                    imported=(await client.post('/api/geodata/vmd/import-selected',json={**body,'dry_run':False,'confirmed':True})).json()
                    assert imported['imported']==1,imported
                    sid=imported['results'][0]['id']
                    again=(await client.post('/api/geodata/vmd/import-selected',json={**body,'dry_run':False,'confirmed':True})).json()
                    assert again['already_exists']==1
                    on_map=next(s for s in (await client.get('/api/map')).json() if s['id']==sid)
                    assert on_map['boundary']==[[y,x] for x,y in selected['geometry']['coordinates'][0]]
                    assert on_map['source']['client_id']=='acceptance-client'
                    source=(await client.get('/api/geodata/lvm/sectors/'+str(sid)+'/source')).json()['source_properties']
                    assert source['original_source_geometry'] and source['normalized_geometry']==selected['geometry']
                    assert source['territory_id']==tid and source['original_crs']=='EPSG:10306'
                    # Independent connection verifies committed persistence after request/connection closure.
                    with sqlite3.connect(target) as reopened:
                        assert reopened.execute('SELECT boundary_json FROM sectors WHERE id=?',(sid,)).fetchone()[0]
                        assert reopened.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                    result.update({'matches':first['summary']['found'],'source_feature':selected['id'],'preview':preview['would_import'],'imported_in_disposable_db':1,'duplicate_prevented':True,'original_geometry_preserved':True,'main_map_geometry_matches':True,'persistence':True})
            finally:api.app.dependency_overrides.clear()
    return result

if __name__=='__main__':print(json.dumps(asyncio.run(verify()),ensure_ascii=False,indent=2))
