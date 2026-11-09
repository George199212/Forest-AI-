"""Real national acceptance; ten official parcels, two per VMD region.
Default registers only in a disposable production DB backup. --live is read/preview only.
Requires completed --manifest. No fabricated cadastral identifiers or geometries.
"""
import argparse,hashlib,json,os,socket,sqlite3,subprocess,sys,tempfile,time,uuid
from pathlib import Path
from contextlib import closing
if os.environ.get('FOREST_PLAYWRIGHT_PATH'):sys.path.insert(0,os.environ['FOREST_PLAYWRIGHT_PATH'])
from playwright.sync_api import sync_playwright
from dotenv import dotenv_values
import shapely
from shapely.geometry import shape
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def samples(manifest):
    from services.geodata import nationwide as nw
    os.environ['FOREST_GEODATA_MANIFEST']=str(manifest);m=nw.release();selected=[];seen=set()
    with closing(nw.db(m['forest_db'])) as c:
        for region in m['reports']['vmd']['regions']:
            picked=[]
            # Include an independently audited leading-zero unit for Centra.
            if region=='Centra':
                for leading_zero in ['01000950031','01000950030']:
                    r=nw.search(leading_zero);eligible=[f for f in r['features'] if f['properties']['importable']]
                    if eligible:
                        picked.append({'region':region,'designation':leading_zero,'preferred_id':eligible[0]['id']});seen.add(leading_zero);break
            layers=[x['layer'] for x in m['reports']['vmd']['layers'] if x.get('region')==region]
            for layer in layers:
                if len(picked)>=2:break
                prefix='VMD:'+layer+':'
                rows=c.execute('SELECT external_id,kadastrs,native_geometry FROM compartments WHERE external_id>=? AND external_id<? AND importable=1 AND source_verified=1 LIMIT 10000',(prefix,prefix+'~'))
                for row in rows:
                    cad=row['kadastrs']
                    if cad in seen:continue
                    parcel=nw.parcel_row(cad,m)
                    if not parcel or not parcel['source_verified'] or not parcel['geometry_valid']:continue
                    if not shapely.from_wkb(parcel['native_geometry']).covers(shapely.from_wkb(row['native_geometry'])):continue
                    r=nw.search(cad);eligible=[f for f in r['features'] if f['properties']['importable']]
                    if not eligible:continue
                    picked.append({'region':region,'designation':cad,'preferred_id':eligible[0]['id']});seen.add(cad)
                    if len(picked)>=2:break
            if len(picked)!=2:raise RuntimeError('Two verified independent source units not found for '+region)
            selected+=picked
    assert len(selected)==10 and len(seen)==10
    return selected

def raw_source_check(path,row_number,field,designation,expected_geometry):
    from services.geodata.forestry_io import schema,original_geometry
    path=Path(path);meta=schema(path.with_suffix('.dbf'));attribute=next(f for f in meta['fields'] if f['name']==field)
    assert attribute['type']=='C'
    with path.with_suffix('.dbf').open('rb') as f:
        f.seek(meta['header_bytes']+(row_number-1)*meta['record_bytes']);raw=f.read(meta['record_bytes'])
    assert raw[:1]==b' ' and raw[attribute['offset']:attribute['offset']+attribute['length']].decode('utf-8').strip(' \0')==designation
    source=original_geometry(path,row_number);assert source.is_valid and source.wkb==bytes(expected_geometry)
    return source

def run(manifest,live=False):
    os.environ['FOREST_GEODATA_MANIFEST']=str(Path(manifest).resolve())
    from services.geodata import nationwide as nw
    release=nw.release();chosen=samples(manifest);artifact=Path(release['root'])/('live-acceptance.json' if live else 'staging-acceptance.json')
    report={'status':'RUNNING','live':live,'production_sector_writes':0,'dataset_version':release['version'],'source_count':47,'vmd_compartments':release['reports']['vmd']['indexed'],'vzd_parcels':release['reports']['vzd']['indexed'],'cases':[]};process=None;temp=tempfile.TemporaryDirectory(prefix='forest-national-e2e-');log=None
    artifact.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if live:
        base='http://164.90.188.136:8000';cfg=dotenv_values(ROOT/'.env');user=cfg['DASHBOARD_USERNAME'];password=cfg['DASHBOARD_PASSWORD']
    else:
        appdb=Path(temp.name)/'app.db'
        with sqlite3.connect('file:'+str(ROOT/'data/forest_ai.db')+'?mode=ro',uri=True) as src,sqlite3.connect(appdb) as dst:src.backup(dst)
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();base='http://127.0.0.1:'+str(port);user='national-acceptance';password=uuid.uuid4().hex
        env={**os.environ,'DB_PATH':str(appdb),'DASHBOARD_USERNAME':user,'DASHBOARD_PASSWORD':password}
        subprocess.run([sys.executable,'-c','import database;database.init_db()'],env=env,cwd=ROOT,check=True,capture_output=True)
        log=open('/tmp/forest-national-staging.log','w')
        def start():
            p=subprocess.Popen([sys.executable,'-m','uvicorn','api:app','--host','127.0.0.1','--port',str(port),'--lifespan','off'],cwd=ROOT,env=env,stdout=log,stderr=log)
            for _ in range(150):
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.2):return p
                except OSError:time.sleep(.1)
            raise RuntimeError('Staging backend failed to start')
        process=start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--no-sandbox']);auth={'username':user,'password':password};context=browser.new_context(http_credentials=auth,viewport={'width':1600,'height':1100});page=context.new_page();errors=[];network=[];saved=[]
            page.on('pageerror',lambda error:errors.append(str(error)));page.on('request',lambda request:network.append(request.url))
            page.goto(base+'/#lvm-geodata',wait_until='domcontentloaded');page.wait_for_function("!document.getElementById('vmd-find').disabled",timeout=60000)
            metadata=context.request.get(base+'/api/geodata/vmd/dataset').json();assert metadata['regions_covered']==5 and metadata['municipalities_covered']==42 and metadata['sources_validated']==47
            page.wait_for_function("document.getElementById('vmd-basemap').value==='satellite'&&lvmUI.satellite&&lvmUI.map.hasLayer(lvmUI.satellite)",timeout=30000)
            report.update(url=base+'/#lvm-geodata',frontend_version=page.locator('#geodata-build').inner_text(),esri_satellite_preserved=True)
            # Invalid identifier never reaches the source lookup.
            before=len([u for u in network if '/cadastre?' in u]);page.locator('#vmd-kadastrs').fill('123');page.locator('#vmd-find').click();assert len([u for u in network if '/cadastre?' in u])==before
            for case in chosen:
                cad=case['designation'];page.locator('#vmd-kadastrs').fill(cad)
                with page.expect_response(lambda r:'/api/geodata/vmd/cadastre?' in r.url) as response:page.locator('#vmd-find').click()
                r=response.value;assert r.status==200,r.text();data=r.json();page.wait_for_function("!document.getElementById('vmd-find').disabled",timeout=30000)
                assert data['dataset_version']==release['version'] and data['state']=='VMD_MATCHES_FOUND' and data['cadastral_validation']['source_designation']==cad
                assert all(f['properties']['kadastrs']==cad for f in data['features']);assert all(not f['properties']['importable'] for f in data['spatial_candidates'])
                validation=data['cadastral_validation'];official=nw.parcel_row(cad,release);raw_source_check(official['source_file'],official['source_row'],'CODE',cad,official['original_geometry'] or official['native_geometry']);parcel=shape(validation['land_unit_geometry']);assert parcel.is_valid
                b=parcel.bounds;assert page.evaluate('b=>lvmUI.map.getBounds().contains(L.latLngBounds([[b[1],b[0]],[b[3],b[2]]]))',list(b))
                fid=case['preferred_id'];feature=next(f for f in data['features'] if f['id']==fid);assert feature['properties']['importable']
                with closing(nw.db(release['forest_db'])) as source_db:
                    source_row=source_db.execute('SELECT * FROM compartments WHERE external_id=?',(fid,)).fetchone()
                    raw_source_check(source_row['source_file'],source_row['source_row'],'kadastrs',cad,source_row['original_geometry'] or source_row['native_geometry'])
                    from pyproj import Transformer
                    from shapely.ops import transform
                    independent=transform(Transformer.from_crs(source_row['source_crs'],4326,always_xy=True).transform,shape(nw.original(source_row)))
                    assert independent.hausdorff_distance(shape(feature['geometry']))<2e-8
                rendered=page.evaluate("id=>{let out=null;lvmUI.map.eachLayer(l=>{if(l.feature?.id===id)out=l.toGeoJSON(false).geometry;});return out;}",fid);assert rendered==feature['geometry']
                row=page.locator('#lvm-feature-rows tr[data-feature-id="'+fid+'"]');row.locator('input').check();row.locator('input').uncheck();row.locator('input').check()
                if not report['cases']:
                    collected={f['id'] for f in data['features']};current=data;pages=0
                    while current['summary']['has_more']:
                        with page.expect_response(lambda response:'/api/geodata/vmd/cadastre?' in response.url) as next_response:page.locator('#vmd-next').click()
                        current=next_response.value.json();page.wait_for_function("!document.getElementById('vmd-find').disabled")
                        assert all(f['properties']['kadastrs']==cad for f in current['features']);collected.update(f['id'] for f in current['features']);pages+=1
                        assert 'Atlasīti: 1 ' in page.locator('#vmd-selected-summary').inner_text()
                    assert len(collected)==data['summary']['found']
                    for _ in range(pages):
                        with page.expect_response(lambda response:'/api/geodata/vmd/cadastre?' in response.url):page.locator('#vmd-prev').click()
                        page.wait_for_function("!document.getElementById('vmd-find').disabled")
                    assert page.locator('#lvm-feature-rows tr[data-feature-id="'+fid+'"] input').is_checked()
                    report['pagination_all_results_verified']=len(collected);report['pagination_selection_preserved']=True
                    if not live:
                        # Explicit service-failure injection only; official source data is never mocked.
                        pattern='**/api/geodata/vmd/cadastre?*'
                        page.route(pattern,lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'state':'SOURCE_ERROR','detail':'Pārbaudes pagaidu servera kļūda'})))
                        page.locator('#vmd-find').click();page.wait_for_function("!document.getElementById('vmd-find').disabled")
                        assert page.locator('#vmd-retry').is_visible() and page.locator('#lvm-import').is_disabled();page.unroute(pattern)
                        with page.expect_response(lambda response:'/api/geodata/vmd/cadastre?' in response.url) as recovered:page.locator('#vmd-retry').click()
                        assert recovered.value.status==200;page.wait_for_function("!document.getElementById('vmd-find').disabled")
                        assert 'Atlasīti: 1 ' in page.locator('#vmd-selected-summary').inner_text();report['explicit_503_recovery_verified']=True
    
                page.locator('#vmd-go-1').click();assert 'Atlasīti: 1 ' in page.locator('#vmd-selected-summary').inner_text();page.locator('#vmd-go-2').click()
                if not report['cases']:
                    bulk_ids=[f['id'] for f in data['features'] if f['properties']['importable']];began=time.monotonic()
                    bulk=context.request.post(base+'/api/geodata/vmd/import-selected',data={'feature_ids':bulk_ids,'dataset_version':data['dataset_version'],'cadastral_designation':cad,'sector_name':'Apjoma pārbaude','responsible_first_name':'Testa','responsible_last_name':'Persona','dry_run':True})
                    assert bulk.status==200 and bulk.json()['would_import']==len(bulk_ids) and bulk.json()['failed']==0
                    report['bulk_preview']={'compartments':len(bulk_ids),'seconds':round(time.monotonic()-began,3),'bytes':len(bulk.body())}
                    assert len(bulk.body())<2*1024*1024
                sector_name='Valsts pārbaude '+case['region']+' '+cad;page.locator('#vmd-sector-name').fill(sector_name);page.locator('#vmd-responsible-first-name').fill('Testa');page.locator('#vmd-responsible-last-name').fill('Persona')
                with page.expect_response(lambda r:r.url.endswith('/api/geodata/vmd/import-selected')) as response:page.locator('#vmd-go-3').click()
                preview=response.value.json();assert preview['would_import']==1 and preview['failed']==0;page.locator('dialog[open]').wait_for();assert page.locator('dialog .leaflet-interactive').count()==1
                result={**case,'parcel_found':True,'authoritative_geometry_retrieved':True,'exact_vmd_count':data['summary']['found'],'verified_vmd_count':data['summary']['verified_matches'],'spatial_candidate_count':data['spatial_summary']['found'],'association':'exact_original_vmd_attribute_and_vzd_code_with_native_containment','geometry_valid':True,'original_dbf_and_shp_verified':True,'coordinate_transform_verified':True,'search_seconds':data['summary']['elapsed_seconds'],'preview_passed':True}
                if live:page.get_by_role('button',name='Atpakaļ uz atlasi',exact=True).click()
                else:
                    with page.expect_response(lambda r:r.url.endswith('/api/geodata/vmd/import-selected')) as response:page.get_by_role('button',name='Reģistrēt sektorus',exact=True).click()
                    imported=response.value.json();assert imported['imported']==1 and imported['failed']==0
                    sector=next(s for s in context.request.get(base+'/api/map').json() if s['id']==imported['results'][0]['id']);assert sector['name']==sector_name
                    details=context.request.get(base+'/api/geodata/lvm/sectors/'+str(sector['id'])+'/source').json()['source_properties'];assert details['cadastral_designation']==cad and details['vzd_geometry_reference']['designation']==cad
                    assert details['organization_id']==1 and details['created_by_account']==user and details['responsible_first_name']=='Testa';assert details['normalized_geometry']==feature['geometry']
                    with closing(nw.db(release['forest_db'])) as c:original=c.execute('SELECT native_geometry,original_geometry FROM compartments WHERE external_id=?',(fid,)).fetchone();expected=original['original_geometry'] or original['native_geometry']
                    assert shape(details['original_source_geometry']).wkb==bytes(expected)
                    assert context.request.post(base+'/api/geodata/vmd/import-selected',data={'feature_ids':[fid],'dataset_version':data['dataset_version'],'cadastral_designation':cad,'sector_name':sector_name,'responsible_first_name':'Testa','responsible_last_name':'Persona','dry_run':True}).json()['already_exists']==1
                    page.evaluate("nav('sectors')");listed=page.locator('#sectors-table tr').filter(has=page.get_by_text(sector_name,exact=True));listed.wait_for();listed.get_by_text('details →',exact=True).click();page.wait_for_function('name=>document.getElementById("detail-name").textContent===name',arg=sector_name);page.evaluate("nav('lvm-geodata')")
                    saved.append(sector);result.update(registration_succeeded=True,sector_id=sector['id'],sector_name=sector_name,source_geometry_preserved=True,duplicate_prevented=True)
                report['cases'].append(result);artifact.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True)
            # No-result and review-only responses never borrow neighbouring geometry.
            unknown=context.request.get(base+'/api/geodata/vmd/cadastre?kadastrs=99999999999').json();assert unknown['state']=='PARCEL_NOT_FOUND' and not unknown['features']
            if not live:
                page.evaluate("nav('map')");page.wait_for_function('mapLoaded===true',timeout=30000);page.reload(wait_until='domcontentloaded');page.wait_for_function('mapLoaded===true',timeout=30000)
                process.terminate();process.wait(timeout=15);process=start();page.reload(wait_until='domcontentloaded');page.wait_for_function('mapLoaded===true',timeout=30000)
                fresh=browser.new_context(http_credentials=auth);rows=fresh.request.get(base+'/api/map').json();assert all(any(r['id']==s['id'] and r['name']==s['name'] and r['boundary']==s['boundary'] for r in rows) for s in saved);fresh.close();report.update(registrations=len(saved),refresh_restart_fresh_login_persistence=True)
            assert not errors,errors;report.update(status='PASSED',browser_errors=errors,tested_units=len(chosen),regions_tested=sorted({x['region'] for x in chosen}));browser.close()
    finally:
        if process:process.terminate();process.wait(timeout=15)
        if log:log.close()
        temp.cleanup()
    artifact.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--live',action='store_true');a=p.parse_args();run(Path(a.manifest).resolve(),a.live)
