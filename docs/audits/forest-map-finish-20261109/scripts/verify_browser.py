"""Acceptance run of #forest-map on the TEMP server. usage: verify_browser.py <port> <outdir> <records.json>"""
import sys,json,os,re,time
sys.path.insert(0,'/tmp/forest_browser');os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH','/tmp/forest_chromium')
from playwright.sync_api import sync_playwright
PORT,OUT=sys.argv[1],sys.argv[2];REC=json.load(open(sys.argv[3]));os.makedirs(OUT,exist_ok=True)
log={'console':[],'failed':[],'http_errors':[],'checks':{}}
def check(name,ok,detail=None):log['checks'][name]={'ok':bool(ok),'detail':detail};print(('PASS ' if ok else 'FAIL ')+name,'' if detail is None else str(detail)[:300],flush=True)
with sync_playwright() as p:
    b=p.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage','--renderer-process-limit=1','--disable-gpu','--js-flags=--max-old-space-size=256']);ctx=b.new_context(http_credentials={'username':'audit','password':'audit-local-only'},viewport={'width':1366,'height':860})
    page=ctx.new_page()
    page.on('console',lambda m:m.type in('error','warning') and log['console'].append(m.text[:200]))
    page.on('pageerror',lambda e:log['console'].append('pageerror: '+str(e)[:200]))
    page.on('requestfailed',lambda r:'ERR_ABORTED' not in str(r.failure) and log['failed'].append(r.url[:150]+' '+str(r.failure)))
    page.on('response',lambda r:r.status>=400 and log['http_errors'].append((r.status,r.url[:150])))
    page.goto(f'http://127.0.0.1:{PORT}/#forest-map');page.wait_for_function('window.ForestMap&&ForestMap.map',timeout=30000)
    def idle():
        for _ in range(400):
            st=page.evaluate('ForestMap.stats')
            if st['queued']==0 and st['running']==0:
                page.wait_for_timeout(600)
                if page.evaluate('ForestMap.stats.queued+ForestMap.stats.running')==0:return
            page.wait_for_timeout(150)
    def view(lat,lon,z):page.evaluate(f"ForestMap.map.setView([{lat},{lon}],{z},{{animate:false}})");page.wait_for_timeout(500);idle()
    def modes():return page.evaluate("()=>{const m={};document.querySelectorAll('#fm-map canvas[data-mode]').forEach(c=>m[c.dataset.mode]=(m[c.dataset.mode]||0)+1);return m}")
    def px(lat,lon):
        pt=page.evaluate(f"(()=>{{const p=ForestMap.map.latLngToContainerPoint([{lat},{lon}]),r=document.getElementById('fm-map').getBoundingClientRect();return [r.left+p.x,r.top+p.y]}})()");return pt
    idle()
    # country zoom: density cells, LV hint, no blanket squares
    m=modes();check('country_view_density_cells',set(m)=={'generalized_presence'},m)
    check('country_hint_lv',page.inner_text('#fm-scale').startswith('Ierakstu blīvums'),page.inner_text('#fm-scale'))
    page.screenshot(path=f'{OUT}/1_country.png')
    # completeness at boundary zooms: dense area, zoom 13
    for name,(lat,lon) in {'dense_gauja':(57.25,25.10),'densest_z13':(57.35,27.75),'riga':(56.95,24.11)}.items():
        view(lat,lon,13);m=modes();check('z13_no_fallback_'+name,'generalized_presence' not in m and m.get('simplified',0)>0,m)
    page.screenshot(path=f'{OUT}/2_z13.png')
    check('no_tile_errors',page.evaluate('ForestMap.stats.errors')==0,page.evaluate('ForestMap.stats'))
    # hover tooltip and click popup on an importable compartment
    r=REC['importable'];view(r['lat'],r['lon'],15);x,y=px(r['lat'],r['lon'])
    page.mouse.move(x-3,y);page.mouse.move(x,y);page.wait_for_timeout(500)
    tip=page.evaluate("document.querySelector('.forest-map-hover')?.textContent||''");check('hover_tooltip',re.search(r'\d{11} · K\S+ N\S+ · [\d.]+ ha',tip),tip)
    page.mouse.click(x,y);page.wait_for_selector('.forest-map-popup',timeout=20000);page.wait_for_timeout(500)
    pop=page.inner_text('.forest-map-popup')
    fields=['Kadastra apzīmējums','Kvartāls','Nogabals','Platība','Datu avots','Avota ID','Kadastra saistība','Ģeometrija','Reģistrācijas iespēja']
    check('popup_fields_lv',all(f in pop for f in fields),[f for f in fields if f not in pop] or pop.replace('\n',' | ')[:300])
    page.screenshot(path=f'{OUT}/3_popup.png')
    btns=page.evaluate("[...document.querySelectorAll('.forest-map-popup button')].map(b=>[b.textContent,b.disabled])");check('popup_select_add_enabled',len(btns)==2 and not any(d for _,d in btns),btns)
    page.click('.forest-map-popup button:nth-of-type(2)');page.wait_for_timeout(300)
    check('added_to_selection',page.evaluate('ForestMap.selectedCount')==1,page.inner_text('#fm-selected-count'))
    # review-only compartments: reason + next step
    for key in ('review','invalid'):
        page.evaluate(f"ForestMap.inspectId('{REC[key]['id']}')");page.wait_for_selector('.forest-map-popup .forest-map-next',timeout=20000)
        txt=page.inner_text('.forest-map-popup');check('review_reason_'+key,'Ko darīt:' in txt,txt.split('\n')[-4:])
    page.screenshot(path=f'{OUT}/4_review.png')
    # sectors: every hidden sector listed with a reason
    lst=page.inner_text('#fm-sector-list') if page.query_selector('#fm-sector-list') else ''
    check('sector_reasons_listed',lst.count('—')>=8 and 'nav robežas' in lst,lst.replace('\n',' | '))
    check('sector_label',re.search(r'\(\d+/\d+\)',page.inner_text('#fm-layer-label-sectors')),page.inner_text('#fm-layer-label-sectors'))
    # registration on the /tmp DB copy: result dialog with created sector link
    page.click('#fm-import');page.wait_for_selector('dialog.forest-map-review',timeout=5000)
    page.fill('#fm-reg-name','DEMO Meža karte '+time.strftime('%H%M%S'));page.fill('#fm-reg-first','Audit');page.fill('#fm-reg-last','Test')
    page.check('dialog.forest-map-review input[type=checkbox]');page.click('dialog.forest-map-review button:has-text("Pārbaudīt importu")')
    page.wait_for_selector('#fm-review',timeout=30000);page.click('#fm-confirm');page.wait_for_selector('#fm-result',timeout=60000)
    res=page.inner_text('#fm-result');check('registration_result_dialog','Izveidotie sektori · 1' in res and page.query_selector('#fm-result a[href="#sectors"]') is not None,res.replace('\n',' | '))
    page.screenshot(path=f'{OUT}/5_result.png')
    page.click('#fm-result a[href="#sectors"]');page.wait_for_timeout(1500)
    check('result_link_opens_sectors',page.evaluate("document.getElementById('sec-sectors')?.classList.contains('active')||location.hash.includes('sectors')"),page.evaluate('location.hash'))
    # i18n: LV page has no English UI strings; EN page has no Latvian UI strings
    page.goto(f'http://127.0.0.1:{PORT}/#forest-map');page.wait_for_function('window.ForestMap&&ForestMap.map',timeout=30000);idle()
    def ui_text():return page.evaluate("()=>{const r=document.getElementById('sec-forest-map');const out=[];const w=n=>{for(const c of n.childNodes){if(c.nodeType===3){const t=c.textContent.trim();if(t)out.push(t)}else if(c.nodeType===1&&!c.closest('#fm-sector-list li')&&!c.closest('.leaflet-control-attribution'))w(c)}};w(r);r.querySelectorAll('[title],[aria-label]').forEach(e=>out.push((e.title||'')+' '+(e.getAttribute('aria-label')||'')));out.push(document.getElementById('page-refresh').textContent,document.getElementById('page-title').textContent);return out}")
    lv=ui_text();english=[t for t in lv if re.search(r'\b(the|Zoom|Refresh|Forest|Select|Import|records?|cell|Layer|Find|Search)\b',t) and t!='Language / Valoda' and 'Forest AI' not in t]
    check('lv_no_english_ui',not english,english)
    page.select_option('#fm-language','en');page.wait_for_function('window.ForestMap&&ForestMap.map',timeout=30000);idle();page.wait_for_timeout(800)
    en=ui_text();latvian=[t for t in en if re.search('[āčēģīķļņšūž]',t) and not re.search(r'novads|pagasts|Rīg|Mežaparks|Mūrnieku|Ķemeri',t) and t!='Language / Valoda']
    check('en_no_latvian_ui',not latvian,latvian)
    page.screenshot(path=f'{OUT}/6_en.png')
    # LVM GEO page loads without errors
    n0=len(log['console']);page.goto(f'http://127.0.0.1:{PORT}/#lvm-geodata');page.wait_for_timeout(5000)
    check('lvm_geodata_no_console_errors',len(log['console'])==n0,log['console'][n0:])
    page.screenshot(path=f'{OUT}/7_lvm.png')
    b.close()
check('no_console_errors',not log['console'],log['console'][:10])
check('no_failed_non_tile_requests',not log['failed'],log['failed'][:10])
check('no_http_errors',not log['http_errors'],log['http_errors'][:10])
json.dump(log,open(f'{OUT}/verify_log.json','w'),indent=1,ensure_ascii=False)
