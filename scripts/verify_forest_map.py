"""Real-data acceptance in the owned, dry-run-only local preview. No deployment."""
import sys,os,json,time,subprocess,socket,sqlite3,hashlib,math,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
if os.environ.get('FOREST_PLAYWRIGHT_PATH'):sys.path.insert(0,os.environ['FOREST_PLAYWRIGHT_PATH'])
from playwright.sync_api import sync_playwright
from dotenv import dotenv_values
from shapely.geometry import shape
from services.geodata import nationwide as nw,forest_map as fm

def snapshot():
    with sqlite3.connect('file:'+str(ROOT/'data/forest_ai.db')+'?mode=ro',uri=True) as c:
        return {t:{'count':c.execute('SELECT count(*) FROM "'+t+'"').fetchone()[0],'hash':hashlib.sha256(repr(c.execute('SELECT * FROM "'+t+'" ORDER BY rowid').fetchall()).encode()).hexdigest()} for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()}

def run():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args()
    # Keep completed acceptance proof immutable across subsequent runs.
    out=Path(args.output or '/tmp/forest-map-acceptance-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
    out.mkdir(parents=True,exist_ok=False)
    report={'status':'RUNNING','cases':[],'errors':[],'tile_errors':[],'production_sector_writes':0,'production_before':snapshot()}
    m=nw.release();report['source_stats_before']={p:[Path(p).stat().st_size,Path(p).stat().st_mtime_ns] for p in [m['forest_db'],m['parcel_db']]}
    cfg=dotenv_values(ROOT/'.env');log=(out/'preview.log').open('w')
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();base='http://127.0.0.1:'+str(port)
    process=subprocess.Popen([sys.executable,'scripts/preview_forest_map.py','--port',str(port)],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
    try:
        for _ in range(150):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.2):break
            except OSError:time.sleep(.2)
        else:raise RuntimeError('Preview did not start')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--no-sandbox']);ctx=browser.new_context(http_credentials={'username':cfg['DASHBOARD_USERNAME'],'password':cfg['DASHBOARD_PASSWORD']},viewport={'width':1600,'height':1100});page=ctx.new_page()
            page.on('pageerror',lambda e:report['errors'].append(str(e)))
            report['import_requests']=[]
            def record_import(request):
                if request.method=='POST' and request.url.endswith('/api/geodata/vmd/import-selected'):
                    body=request.post_data_json
                    report['import_requests'].append({'dry_run':body.get('dry_run'),'feature_ids':body.get('feature_ids'),'geometry_submitted':'geometry' in body,'cadastral_designation':body.get('cadastral_designation')})
            page.on('request',record_import)
            page.on('response',lambda r:report['tile_errors'].append({'url':r.url,'status':r.status}) if '/forest-map/tiles/' in r.url and r.status>=400 else None)
            page.add_init_script("window.__fmLongTasks=[];if(window.PerformanceObserver){try{new PerformanceObserver(list=>window.__fmLongTasks.push(...list.getEntries().map(e=>e.duration))).observe({entryTypes:['longtask']});}catch(e){}}")
            started=time.perf_counter();page.goto(base+'/#forest-map',wait_until='domcontentloaded');page.wait_for_function("window.ForestMap?.map && (document.querySelector('#fm-status')?.textContent.includes('gatava') || document.querySelector('#fm-status')?.textContent.includes('ready'))",timeout=60000)
            page.wait_for_function('ForestMap.stats.tiles>0',timeout=30000);report['open_seconds']=time.perf_counter()-started;report['preview_url']=base+'/#forest-map'
            assert page.locator('#forest-map-nav').is_visible();assert page.locator('#fm-find').inner_text()=='Atrast zemes vienību'
            assert ctx.request.get(base+'/api/geodata/forest-map/status').json()['overview_records']==3063409
            report['national_initial_features']=page.evaluate("[...document.querySelectorAll('#fm-map canvas[data-mode]')].length")
            anonymous=pw.request.new_context();assert anonymous.get(base+'/api/geodata/forest-map/status').status==401;anonymous.dispose()
            protected=ctx.request.post(base+'/api/geodata/vmd/import-selected',data={'dry_run':False});assert protected.status==403;report['preview_write_guard']=403
            sample=json.loads((ROOT/'docs/evidence/vmd-real-world-20261107/selection.json').read_text())
            cases=[{'region':'RIGA','designation':'01000950031','preferred_id':'VMD:nodala2653:70588599'}]+[next(x for x in sample if x['region']==reg) for reg in ['VIDZEME','LATGALE','KURZEME','ZEMGALE']]
            for case in cases:
                cad=case['designation'];fid=case['preferred_id'];page.locator('#fm-cadastre').fill(cad)
                with page.expect_response(lambda r:'/api/geodata/vmd/cadastre?' in r.url) as pending:page.locator('#fm-find').click()
                response=pending.value;assert response.status==200;result=response.json();assert result['summary']['found']>0;assert page.evaluate('ForestMap.matchCount')==len(result['features'])+len(result.get('spatial_candidates',[]))
                page.locator('[data-feature-id="'+fid+'"]').wait_for();page.locator('[data-feature-id="'+fid+'"]').click();page.wait_for_selector('#fm-add')
                assert cad in page.locator('#fm-inspect').inner_text()
                detail=ctx.request.get(base+'/api/geodata/forest-map/feature',params={'id':fid}).json();f=detail['feature'];assert f['properties']['importable'] and f['properties']['display_only'] is False
                point=shape(f['geometry']).representative_point();page.evaluate('p=>ForestMap.map.setView(p,16,{animate:false})',[point.y,point.x]);page.wait_for_timeout(700)
                click=page.evaluate('p=>{const v=ForestMap.map.latLngToContainerPoint(p);return {x:v.x,y:v.y};}',[point.y,point.x]);page.locator('#fm-map').click(position=click);page.wait_for_selector('#fm-add');assert cad in page.locator('#fm-inspect').inner_text()
                page.locator('#fm-add').click();assert page.evaluate('ForestMap.selectedCount')>=1
                before_zoom=page.evaluate('ForestMap.map.getZoom()');page.locator('#fm-map .leaflet-control-zoom-in').click();page.wait_for_timeout(400);assert page.evaluate('ForestMap.map.getZoom()')>before_zoom
                center=page.evaluate('ForestMap.map.getCenter().lng');page.evaluate('ForestMap.map.panBy([100,0],{animate:false})');assert page.evaluate('ForestMap.map.getCenter().lng')!=center
                page.locator('#fm-layer-parcels').check();page.wait_for_timeout(400);page.locator('#fm-layer-parcels').uncheck();page.locator('#fm-layer-selected').uncheck();page.locator('#fm-layer-selected').check()
                page.locator('#fm-layer-forest').uncheck();page.locator('#fm-layer-forest').check();page.locator('#fm-layer-sectors').uncheck();page.locator('#fm-layer-sectors').check()
                page.locator('#fm-basemap').select_option('standard');page.locator('#fm-basemap').select_option('satellite')
                report['cases'].append({'region':case['region'],'designation':cad,'forest_records':result['summary']['found'],'status':'PASS','click':True,'pan':True,'zoom':True,'layers':True,'selection':True});print('MAP',case['region'],cad,'PASS',flush=True)
            assert page.evaluate('ForestMap.selectedCount')==5
            page.locator('#fm-source-search').fill(cases[1]['preferred_id']);page.locator('#fm-findSource').click();page.wait_for_function("document.querySelector('#fm-inspect')?.textContent.includes('VMD:nodala2255:98895536')")
            page.locator('#fm-municipality-search').fill('Valmieras novads')
            with page.expect_response(lambda r:'/api/geodata/forest-map/catalogue?' in r.url) as catalogue_pending:page.locator('#fm-findMunicipality').click()
            catalogue_response=catalogue_pending.value;assert catalogue_response.status==200;catalogue=catalogue_response.json();assert catalogue['total']>0 and catalogue['has_more'];assert len(catalogue['results'])==100 and all(x['source_id'].startswith('VMD:') for x in catalogue['results'])
            page.locator('#fm-import').click();page.locator('.forest-map-review[open]').wait_for(timeout=5000);page.locator('#fm-reg-name').fill('National map diagnostic');page.locator('#fm-reg-first').fill('Diagnostic');page.locator('#fm-reg-last').fill('Preview');page.locator('.forest-map-review input[type=checkbox]').check();page.locator('.forest-map-review button').last.click();page.locator('#fm-review[open]').wait_for(timeout=60000)
            assert not page.locator('#fm-confirm').is_disabled();report['multi_cadastre_preview']={'groups':5,'compartments':5,'status':'PASS'}
            page.screenshot(path=str(out/'selection-preview.png'));page.locator('#fm-review button').first.click();page.locator('#fm-clear').click();assert page.evaluate('ForestMap.selectedCount')==0
            page.locator('#fm-coordinates').fill('57.2, 25.2');page.locator('#fm-go').click();assert abs(page.evaluate('ForestMap.map.getCenter().lat')-57.2)<1e-5
            # Wide national views and rapid camera changes must stay bounded/responsive.
            page.locator('#fm-latvia').click();page.wait_for_timeout(1000)
            page.evaluate("async()=>{window.__fmFrameGaps=[];let previous=performance.now();for(let i=0;i<40;i++){await new Promise(requestAnimationFrame);const now=performance.now();window.__fmFrameGaps.push(now-previous);previous=now;if(i%5===0)ForestMap.map.panBy([60,0],{animate:false});}}")
            page.wait_for_function('ForestMap.stats.running===0 && ForestMap.stats.queued===0',timeout=45000)
            report['frame_max_ms']=page.evaluate('Math.max(...window.__fmFrameGaps)');report['long_task_max_ms']=page.evaluate('Math.max(0,...window.__fmLongTasks)');report['stats']=page.evaluate('ForestMap.stats')
            assert report['stats']['maxFeatures']<=600 and report['stats']['maxBytes']<=400000 and report['stats']['running']<=3
            assert report['frame_max_ms']<2000,'Map unresponsive for over two seconds'
            page.locator('#fm-language').select_option('lv');page.wait_for_selector('#fm-find');page.wait_for_function("document.getElementById('forest-map-nav-label').textContent==='Meža karte'")
            page.locator('#fm-latvia').click();page.wait_for_timeout(1000)
            page.evaluate("nav('overview');nav('forest-map');")
            page.wait_for_function("document.getElementById('page-title').textContent==='Meža karte'")
            report['navigation_return']='PASS'
            page.screenshot(path=str(out/'national-map-lv.png'));report['latvian_ui']='PASS'
            assert not report['errors'],report['errors']
            assert not report['tile_errors'],report['tile_errors']
            assert len(report['import_requests'])==5 and all(r['dry_run'] is True and not r['geometry_submitted'] for r in report['import_requests'])
            browser.close()
        # Cold/cache-warm tile timings at multiple scales, independent of basemap network.
        report['tile_benchmarks']=[]
        for z in [6,9,11,13,16]:
            times=[];sizes=[];counts=[];modes=[]
            for case in cases:
                if case['region']=='RIGA':lat,lon=56.99,24.1
                else:lat,lon=case['latitude'],case['longitude']
                x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
                for _ in range(2):
                    start=time.perf_counter();raw,hit=fm.tile('forest',z,x,y);times.append(time.perf_counter()-start);payload=json.loads(raw);sizes.append(len(raw));counts.append(len(payload['features']));modes.append(payload['mode']);assert len(raw)<=fm.MAX_TILE_BYTES and len(payload['features'])<=fm.MAX_FEATURES
            report['tile_benchmarks'].append({'zoom':z,'runs':len(times),'min_seconds':min(times),'mean_seconds':statistics.mean(times),'max_seconds':max(times),'max_bytes':max(sizes),'max_features':max(counts),'modes':sorted(set(modes))})
        report['production_after']=snapshot();report['source_stats_after']={p:[Path(p).stat().st_size,Path(p).stat().st_mtime_ns] for p in report['source_stats_before']}
        assert report['production_before']==report['production_after'];assert report['source_stats_before']==report['source_stats_after'];report['production_unchanged']=True;report['status']='PASS'
    except BaseException as exc:report['status']='FAIL';report['error']=repr(exc);raise
    finally:
        import signal
        try:os.killpg(process.pid,signal.SIGINT)
        except ProcessLookupError:pass
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=5)
        log.close();(out/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('ACCEPTANCE',report['status'],out,flush=True)

if __name__=='__main__':run()
