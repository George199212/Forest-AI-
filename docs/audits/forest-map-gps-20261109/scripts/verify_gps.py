"""GPS layer acceptance on the TEMP server. usage: verify_gps.py <port> <outdir>"""
import sys,os,json,re,time
sys.path.insert(0,'/tmp/forest_browser');os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH','/tmp/forest_chromium')
from playwright.sync_api import sync_playwright
PORT,OUT=sys.argv[1],sys.argv[2];os.makedirs(OUT,exist_ok=True)
log={'console':[],'failed':[],'http_errors':[],'checks':{},'positions_requests':0}
def check(name,ok,detail=None):log['checks'][name]={'ok':bool(ok),'detail':detail};print(('PASS ' if ok else 'FAIL ')+name,'' if detail is None else str(detail)[:260],flush=True)
with sync_playwright() as p:
    b=p.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage','--renderer-process-limit=1','--disable-gpu','--js-flags=--max-old-space-size=256'])
    page=b.new_context(http_credentials={'username':'audit','password':'audit-local-only'},viewport={'width':1366,'height':900}).new_page()
    page.on('console',lambda m:m.type in('error','warning') and log['console'].append(m.text[:200]))
    page.on('pageerror',lambda e:log['console'].append('pageerror: '+str(e)[:200]))
    page.on('requestfailed',lambda r:'ERR_ABORTED' not in str(r.failure) and log['failed'].append(r.url[:150]+' '+str(r.failure)))
    def resp(r):
        if r.status>=400:log['http_errors'].append((r.status,r.url[:150]))
        if '/gps/positions' in r.url:log['positions_requests']+=1
    page.on('response',resp)
    page.goto(f'http://127.0.0.1:{PORT}/#forest-map');page.wait_for_function('window.ForestMap&&ForestMap.map',timeout=30000);page.wait_for_timeout(4000)
    markers=lambda:page.evaluate("[...document.querySelectorAll('.leaflet-fmGps-pane .fm-gps')].map(e=>e.className)")
    m=markers();check('default_markers_hide_unknown',len(m)==4 and not any('UNKNOWN' in c for c in m),m)
    check('origins_distinct_classes',sum('fm-o-REAL' in c for c in m)==2 and sum('fm-o-SIMULATED' in c for c in m)==2,m)
    check('stale_workers_marked',sum('fm-stale' in c for c in m)==2,m)
    check('layer_label_count',page.inner_text('#fm-layer-label-gps'),page.inner_text('#fm-layer-label-gps'))
    page.click('.fm-o-label.fm-o-UNKNOWN input');page.wait_for_timeout(300);check('unknown_filter_shows_all',len(markers())==7,len(markers()));page.click('.fm-o-label.fm-o-UNKNOWN input');page.wait_for_timeout(300)
    page.check('#fm-gps-active');page.wait_for_timeout(300);check('only_active',len(markers())==2 and all('SIMULATED' in c for c in markers()),markers());page.uncheck('#fm-gps-active');page.wait_for_timeout(300)
    page.uncheck('#fm-gps-filters .fm-gps-row:first-of-type label:nth-child(2) input');page.wait_for_timeout(300);check('type_filter_vehicles_off',len(markers())==2,markers());page.check('#fm-gps-filters .fm-gps-row:first-of-type label:nth-child(2) input');page.wait_for_timeout(300)
    page.select_option('#fm-gps-sector','BIK-001');page.wait_for_timeout(300);check('sector_filter',len(markers())==1,markers());page.select_option('#fm-gps-sector','');page.wait_for_timeout(300)
    page.screenshot(path=f'{OUT}/1_gps_overview.png')
    # worker popup
    page.evaluate("ForestMap.map.setView([56.964,24.205],15,{animate:false})");page.wait_for_timeout(1500)
    page.click('.leaflet-fmGps-pane [title="Test User"]');page.wait_for_selector('.fm-gps-popup',timeout=10000);pop=page.inner_text('.fm-gps-popup')
    need=['Test User · Darbinieks','Piešķirtais sektors','BIK-001','Pēdējā atjaunošana','pirms','dienām','± 3 m','REĀLS — Telegram','Telpiskais statuss','Reģistrētā sektorā BIK-001','Rādīt maršrutu']
    check('worker_popup_lv',all(n in pop for n in need),[n for n in need if n not in pop] or pop.replace('\n',' | '))
    page.screenshot(path=f'{OUT}/2_worker_popup.png')
    # real track (custom window around 2026-10-11)
    page.select_option('.fm-gps-window select','custom');page.fill('.fm-gps-window input:nth-of-type(1)','2026-10-11T00:00');page.fill('.fm-gps-window input:nth-of-type(2)','2026-10-12T00:00')
    page.click('.fm-gps-popup .forest-map-actions button');page.wait_for_selector('#fm-gps-track strong',timeout=20000);page.wait_for_timeout(800)
    tr=page.inner_text('#fm-gps-track');check('real_track_summary','29 punkti' in tr and '0 pārtraukumi' in tr and 'Reģistrētā sektorā' in tr and 'Ārpus meža reģistra' in tr,tr.replace('\n',' | '))
    canv=page.evaluate("document.querySelectorAll('.leaflet-fmTrack-pane canvas, .leaflet-fmTrack-pane path').length");check('track_drawn_on_track_pane',canv>=1,canv)
    check('track_start_end',page.evaluate("document.querySelectorAll('.fm-track-end').length")==2,None)
    page.screenshot(path=f'{OUT}/3_track.png')
    # simulated popup
    page.evaluate("(async()=>{const r=await (await fetch('/api/geodata/forest-map/gps/positions')).json();const e=r.entities.find(x=>x.name==='DEMO-101'&&x.origin==='SIMULATED');ForestMap.map.setView([e.lat,e.lon],17,{animate:false});})()");page.wait_for_timeout(2000)
    page.evaluate("ForestMap.map.closePopup()");page.wait_for_timeout(300);page.click('.leaflet-fmGps-pane [title="DEMO-101"]');page.wait_for_selector('.fm-gps-popup',timeout=10000);pop=page.inner_text('.fm-gps-popup')
    check('simulated_popup_labelled','SIMULĒTS — Simulēti demonstrācijas dati' in pop and 'Nekad nerada incidentus' in pop,pop.replace('\n',' | '))
    page.screenshot(path=f'{OUT}/4_simulated.png')
    # polling every 30 s
    n0=log['positions_requests'];page.wait_for_timeout(32000);check('polling_30s',log['positions_requests']>n0,{'before':n0,'after':log['positions_requests']})
    # i18n
    lv=page.inner_text('#fm-gps-filters');check('lv_filter_text',not re.search(r'\b(Workers|Vehicles|Machines|Only active|Stale)\b',lv),lv.replace('\n',' | '))
    page.select_option('#fm-language','en');page.wait_for_function('window.ForestMap&&ForestMap.map',timeout=30000);page.wait_for_timeout(4000)
    en=page.inner_text('#fm-gps-filters');check('en_filter_text',not re.search('[āčēģīķļņšūž]',en) and 'Workers' in en,en.replace('\n',' | '))
    page.evaluate("ForestMap.map.setView([56.964,24.205],15,{animate:false})");page.wait_for_timeout(1500);page.click('.leaflet-fmGps-pane [title="Test User"]');page.wait_for_selector('.fm-gps-popup',timeout=10000)
    pop=page.inner_text('.fm-gps-popup');check('en_worker_popup','Inside registered sector BIK-001' in pop and 'REAL — Telegram' in pop and 'days ago' in pop and not re.search('[āčēģīķļņšūž](?![^|]*Bērziņ)',pop.replace('Jānis','')),pop.replace('\n',' | '))
    # regressions: compartments still clickable; Karte page and LVM GEO load cleanly
    page.select_option('#fm-language','lv');page.wait_for_function('window.ForestMap&&ForestMap.map',timeout=30000);page.wait_for_timeout(2500)
    page.evaluate("ForestMap.inspectId('VMD:nodala2251:108690563')");page.wait_for_selector('.forest-map-popup:not(.fm-gps-popup)',timeout=20000);check('compartment_popup_still_works','Kadastra apzīmējums' in page.inner_text('.forest-map-popup:not(.fm-gps-popup)'),None)
    n0=len(log['console']);page.goto(f'http://127.0.0.1:{PORT}/#map');page.wait_for_timeout(5000);check('karte_page_no_errors',len(log['console'])==n0,log['console'][n0:])
    page.goto(f'http://127.0.0.1:{PORT}/#lvm-geodata');page.wait_for_timeout(5000);check('lvm_geodata_no_errors',len(log['console'])==n0,log['console'][n0:])
    b.close()
check('no_console_errors',not log['console'],log['console'][:8]);check('no_failed_requests',not log['failed'],log['failed'][:8]);check('no_http_errors',not log['http_errors'],log['http_errors'][:8])
json.dump(log,open(f'{OUT}/verify_log.json','w'),indent=1,ensure_ascii=False)
