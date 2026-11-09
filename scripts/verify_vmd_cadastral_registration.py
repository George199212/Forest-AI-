"""Real-data Chromium acceptance. Imports only into an isolated production backup.
--live verifies public production discovery, preview and registration guards only.
"""
import argparse,hashlib,json,os,socket,sqlite3,subprocess,sys,tempfile,time,uuid
from pathlib import Path
if os.environ.get('FOREST_PLAYWRIGHT_PATH'):sys.path.insert(0,os.environ['FOREST_PLAYWRIGHT_PATH'])
from playwright.sync_api import sync_playwright
from dotenv import dotenv_values
root=Path(__file__).resolve().parents[1]
REGISTRATION_NAME="Zaļā 'Birzs' <&>"

def run(live=False):
 report={'live':live,'production_sector_writes':0,'cases':{}};temp=tempfile.TemporaryDirectory(prefix='forest-verified-');process=None;log=None
 if live:
  base='http://164.90.188.136:8000';config=dotenv_values(root/'.env');user=config['DASHBOARD_USERNAME'];password=config['DASHBOARD_PASSWORD']
 else:
  db=Path(temp.name)/'app.db'
  with sqlite3.connect('file:'+str(root/'data/forest_ai.db')+'?mode=ro',uri=True) as src,sqlite3.connect(db) as dst:src.backup(dst)
  sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();base='http://127.0.0.1:'+str(port);user='verification-test';password=uuid.uuid4().hex
  env={**os.environ,'DB_PATH':str(db),'DASHBOARD_USERNAME':user,'DASHBOARD_PASSWORD':password}
  subprocess.run([sys.executable,'-c','import database;database.init_db()'],cwd=root,env=env,check=True,capture_output=True)
  log=open('/tmp/cadastral-registration-backend.log','w')
  def start():
   p=subprocess.Popen([sys.executable,'-m','uvicorn','api:app','--host','127.0.0.1','--port',str(port),'--lifespan','off'],cwd=root,env=env,stdout=log,stderr=log)
   for _ in range(100):
    try:
     with socket.create_connection(('127.0.0.1',port),timeout=.2):return p
    except OSError:time.sleep(.1)
   raise RuntimeError('Disposable backend failed')
  process=start()
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,args=['--no-sandbox']);auth={'username':user,'password':password};context=browser.new_context(http_credentials=auth,viewport={'width':1440,'height':1100});page=context.new_page();errors=[];tiles=[];saved=[]
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:tiles.append(r.status) if '/World_Imagery/MapServer/tile/' in r.url else None)
   page.goto(base+'/#lvm-geodata',wait_until='domcontentloaded');page.wait_for_function("document.getElementById('vmd-local-count').textContent==='513,776'",timeout=60000)
   page.wait_for_function("document.getElementById('vmd-basemap').value==='satellite'&&lvmUI.satellite&&lvmUI.map.hasLayer(lvmUI.satellite)",timeout=30000)
   assert page.locator('#vmd-client-id,#vmd-client-name').count()==0
   identity=context.request.get(base+'/api/geodata/vmd/registration-context').json();assert identity['organization_id']==1 and identity['user_id'] is None
   report.update({'url':base+'/#lvm-geodata','version':page.locator('#geodata-build').inner_text(),'esri_default':True,'profile_prefill':'BLOCKED: existing shared Basic account has no individual profile'})
   def find(cad):
    page.locator('#vmd-kadastrs').fill(cad)
    with page.expect_response(lambda r:'/api/geodata/vmd/cadastre?' in r.url) as response:page.locator('#vmd-find').click()
    assert response.value.status==200;page.wait_for_function("!document.getElementById('vmd-find').disabled",timeout=30000);return response.value.json()
   assert page.get_by_role('button',name='Pietuvināt atlasi',exact=True).count()==0
   assert page.locator('#vmd-go-2').is_disabled() and page.locator('#vmd-go-3').is_disabled()
   empty=find('99999999999');assert empty['summary']['found']==0 and empty['cadastral_validation']['status']=='unverified'
   assert 'Kadastra dati nav pārbaudīti' in page.locator('#lvm-preview-state').inner_text()
   for missing in ['80840050013','80600030025','80960030024']:
    absent=find(missing);assert absent['summary']['found']==0 and absent['cadastral_validation']['land_unit_exists'] and 'VZD zemes vienība ir pārbaudīta' in page.locator('#lvm-preview-state').inner_text()
   outside=find('05000010139');assert outside['summary']['found']==0 and outside['coverage']['status']=='outside_loaded_extent'
   assert 'ārpus ielādētās VMD' in page.locator('#lvm-preview-state').inner_text()
   for cad,count in [('01000950030',209),('40940020002',10),('01000950031',6)]:
    data=find(cad);assert data['summary']['found']==count
    audit=json.loads((root/f'data/vmd/cadastral-audit-{cad}/audit.json').read_text());expected={r['source_feature_id']:r for r in audit['rows']};collected={}
    for offset in range(0,count,100):
     if offset:
      with page.expect_response(lambda r:'/api/geodata/vmd/cadastre?' in r.url) as response:page.locator('#vmd-next').click()
      data=response.value.json();page.wait_for_function("!document.getElementById('vmd-find').disabled")
     displayed=page.evaluate("()=>{const out={};lvmUI.map.eachLayer(l=>{if(l.feature?.id)out[l.feature.id]=l.toGeoJSON(false).geometry;});return out;}")
     assert all(displayed[f['id']]==expected[f['id']]['normalized_geometry'] for f in data['features'])
     assert all(f['properties']['cadastral_association']['source_designation']==cad for f in data['features'])
     collected.update({f['id']:f for f in data['features']})
    assert len(collected)==count
    data=find(cad);eligible=[f for f in data['features'] if f['properties']['importable']][:2]
    blocked=[f for f in data['features'] if not f['properties']['cadastral_validation']['registration_allowed']]
    if blocked:
     row=page.locator('#lvm-feature-rows tr[data-feature-id="'+blocked[0]['id']+'"] input');assert row.is_disabled()
     body={'feature_ids':[blocked[0]['id']],'dataset_version':data['dataset_version'],'dry_run':False,'confirmed':True,'sector_name':REGISTRATION_NAME,'responsible_first_name':'Testa','responsible_last_name':'Persona'}
     rejected=context.request.post(base+'/api/geodata/vmd/import-selected',data=body);assert rejected.status==200 and rejected.json()['imported']==0 and rejected.json()['failed']==1
    assert eligible
    page.evaluate("id=>{lvmUI.map.eachLayer(l=>{if(l.feature?.id===id)l.fire('click');});}",eligible[0]['id']);assert 'Atlasīti: 1 ' in page.locator('#vmd-selected-summary').inner_text()
    page.evaluate("id=>{lvmUI.map.eachLayer(l=>{if(l.feature?.id===id)l.fire('click');});}",eligible[0]['id']);assert 'Atlasīti: 0 ' in page.locator('#vmd-selected-summary').inner_text()
    for f in eligible:page.locator('#lvm-feature-rows tr[data-feature-id="'+f['id']+'"] input').check()
    page.locator('#vmd-go-1').click();assert page.locator('#vmd-step-1').get_attribute('aria-current')=='step'
    assert page.locator('#lvm-feature-rows tr').count()==len(data['features'])
    assert 'Atlasīti: '+str(len(eligible))+' ' in page.locator('#vmd-selected-summary').inner_text()
    page.locator('#vmd-go-2').click();assert page.locator('#vmd-step-2').get_attribute('aria-current')=='step'
    page.locator('#vmd-sector-name').fill(REGISTRATION_NAME);page.locator('#vmd-responsible-first-name').fill('Testa');page.locator('#vmd-responsible-last-name').fill('Persona')
    with page.expect_response(lambda r:r.url.endswith('/api/geodata/vmd/import-selected')) as response:page.get_by_role('button',name='Pārbaudīt atlasi',exact=True).click()
    preview=response.value.json();assert preview['would_import']==len(eligible);page.locator('dialog[open]').wait_for();assert page.locator('dialog .leaflet-interactive').count()==len(eligible)
    assert page.locator('#vmd-step-3').get_attribute('aria-current')=='step'
    assert page.get_by_text('Sektora nosaukums: '+REGISTRATION_NAME,exact=True).count()==1
    case={'all_three_steps':True,'selection_preserved_backwards':True,'source_records':count,'exact_source_attributes':True,'all_page_geometries_equal_audit':True,'preview_ready':len(eligible),'cadastral_land_unit_exists':True,'blocked_boundary_discrepancies_current_page':len(blocked)}
    if live:page.screenshot(path=str(root/f'data/vmd/verified-{cad}-live.png'),full_page=True);page.get_by_role('button',name='Atpakaļ uz atlasi',exact=True).click()
    else:
     with page.expect_response(lambda r:r.url.endswith('/api/geodata/vmd/import-selected')) as response:page.get_by_role('button',name='Reģistrēt sektorus',exact=True).click()
     result=response.value.json();assert result['imported']==len(eligible)
     sectors=context.request.get(base+'/api/map').json()
     for r in result['results']:
      f=collected[r['external_id']];item=next(s for s in sectors if s['id']==r['id']);saved.append(item)
      source=context.request.get(base+'/api/geodata/lvm/sectors/'+str(r['id'])+'/source').json()['source_properties']
      assert item['name'].startswith(REGISTRATION_NAME) and source['registration_sector_name']==REGISTRATION_NAME
      assert source['normalized_geometry']==f['geometry'] and source['original_crs']=='EPSG:10306'
      assert source['organization_id']==1 and source['created_by_user_id'] is None and source['created_by_account']==user
      assert source['responsible_first_name']=='Testa' and source['cadastral_validation']['status']=='verified'
      from shapely.geometry import shape
      assert hashlib.sha256(shape(source['original_source_geometry']).wkb).hexdigest()==expected[f['id']]['source_geometry_sha256']
     from urllib.parse import quote
     sector_rows=context.request.get(base+'/api/sectors').json();monitoring=context.request.get(base+'/api/satellite-intel/sectors').json()
     for item in saved:
      assert any(r['name']==item['name'] for r in sector_rows)
      assert any(r['sector']==item['name'] for r in monitoring)
     pdf=context.request.get(base+'/api/report/pdf/'+quote(result['results'][0]['name'],safe=''));assert pdf.status==200 and pdf.body().startswith(b'%PDF')
     page.evaluate("nav('sectors')");named_row=page.locator('#sectors-table tr').filter(has=page.get_by_text(result['results'][0]['name'],exact=True));named_row.wait_for();named_row.get_by_text('details →',exact=True).click();page.wait_for_function('name=>document.getElementById("detail-name").textContent===name',arg=result['results'][0]['name']);page.evaluate("nav('lvm-geodata')")
     case['name_available_in_sector_map_monitoring_report']=True
     case['registered_in_isolated_db']=result['imported']
     duplicate=context.request.post(base+'/api/geodata/vmd/import-selected',data={'feature_ids':[f['id'] for f in eligible],'dataset_version':data['dataset_version'],'dry_run':True,'sector_name':REGISTRATION_NAME,'responsible_first_name':'Testa','responsible_last_name':'Persona'}).json();assert duplicate['already_exists']==len(eligible)
    report['cases'][cad]=case
   if not live:
    page.evaluate("nav('map')");page.wait_for_function('mapLoaded===true',timeout=30000);page.reload(wait_until='domcontentloaded');page.wait_for_function('mapLoaded===true',timeout=30000)
    process.terminate();process.wait(timeout=10);process=start();page.reload(wait_until='domcontentloaded');page.wait_for_function('mapLoaded===true',timeout=30000)
    fresh=browser.new_context(http_credentials=auth);again=fresh.request.get(base+'/api/map').json();assert all(any(r['id']==s['id'] and r['boundary']==s['boundary'] for r in again) for s in saved);fresh.close();report['refresh_restart_new_login_persistence']=True
   assert not errors,errors;report['blocking_javascript_errors']=errors;report['esri_tiles_returned_200']=200 in tiles;browser.close()
 finally:
  if process:process.terminate();process.wait(timeout=10)
  if log:log.close()
  temp.cleanup()
 (root/'data/vmd'/('verified-live.json' if live else 'verified-persistence.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');run(p.parse_args().live)
