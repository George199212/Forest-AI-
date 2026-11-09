"""Headless check of #forest-map on a TEMP server. usage: browser_audit.py <port> <outdir>"""
import sys,json,time,os
sys.path.insert(0,'/tmp/forest_browser');os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH','/tmp/forest_chromium')
from playwright.sync_api import sync_playwright
PORT,OUT=sys.argv[1],sys.argv[2];os.makedirs(OUT,exist_ok=True)
log={'console':[],'failed':[],'http_errors':[],'steps':{}}
def visible_text(page):
    return page.evaluate("""()=>{const r=document.getElementById('sec-forest-map');const out=new Set();
      const walk=n=>{for(const c of n.childNodes){if(c.nodeType===3){const t=c.textContent.trim();if(t)out.add(t)}else if(c.nodeType===1&&getComputedStyle(c).display!=='none')walk(c)}};
      walk(r);r.querySelectorAll('input[placeholder]').forEach(i=>out.add('placeholder:'+i.placeholder));
      r.querySelectorAll('[aria-label]').forEach(i=>out.add('aria:'+i.getAttribute('aria-label')));
      return [...out]}""")
def modes(page):
    return page.evaluate("()=>{const m={};document.querySelectorAll('#fm-map canvas[data-mode]').forEach(c=>m[c.dataset.mode]=(m[c.dataset.mode]||0)+1);return m}")
def settle(page,ms=9000):
    page.wait_for_timeout(1500)
    try: page.wait_for_function("()=>{const s=document.querySelectorAll('#fm-map .leaflet-tile-container canvas');return s.length>0}",timeout=ms)
    except Exception: pass
    page.wait_for_timeout(ms)
with sync_playwright() as p:
    b=p.chromium.launch(args=['--no-sandbox'])
    ctx=b.new_context(http_credentials={'username':'audit','password':'audit-local-only'},viewport={'width':1366,'height':860})
    page=ctx.new_page()
    page.on('console',lambda m: m.type in ('error','warning') and log['console'].append({'type':m.type,'text':m.text[:300]}))
    page.on('requestfailed',lambda r: log['failed'].append({'url':r.url[:160],'error':r.failure}))
    page.on('response',lambda r: r.status>=400 and log['http_errors'].append({'url':r.url[:160],'status':r.status}))
    page.goto(f'http://127.0.0.1:{PORT}/',wait_until='domcontentloaded');page.wait_for_timeout(3000)
    log['steps']['html_lang']=page.evaluate('document.documentElement.lang')
    log['steps']['dashboard_nav_text']=page.evaluate("()=>[...document.querySelectorAll('nav a, nav .nav-item, .nav-item')].map(e=>e.textContent.trim()).filter(Boolean).slice(0,40)")
    page.goto(f'http://127.0.0.1:{PORT}/#forest-map');settle(page)
    page.screenshot(path=f'{OUT}/z7_default.png')
    log['steps']['default_lang_text']=visible_text(page);log['steps']['zoom7']={'zoom':page.evaluate("ForestMapDebug?.zoom?.()") if False else None,'modes':modes(page),'badge':page.inner_text('#fm-scale'),'sectors_label':page.inner_text('#fm-layer-label-sectors'),'record_count':page.inner_text('#fm-record-count'),'status':page.inner_text('#fm-status')}
    map_js="(args)=>{const m=[...Object.values(window)].find(v=>v&&v._leaflet_id&&v.setView);return m}"
    # Leaflet map instance is internal; drive via coordinates search + mouse wheel
    for z,coords in ((11,'57.25, 25.10'),(13,'57.25, 25.10'),(15,'57.25, 25.10'),(16,'56.9496, 24.1052')):
        page.fill('#fm-coordinates',coords);page.click('#fm-go');settle(page,7000)   # goCoordinates sets zoom 16
        steps=16-z
        for _ in range(steps):
            page.mouse.move(900,430);page.mouse.wheel(0,300);page.wait_for_timeout(900)
        settle(page,9000)
        log['steps'][f'zoom{z}_{coords}']={'modes':modes(page),'badge':page.inner_text('#fm-scale'),'status':page.inner_text('#fm-status')}
        page.screenshot(path=f'{OUT}/z{z}_{coords.replace(", ","_")}.png')
    # click-inspect at current view (Riga area zoom ~16)
    page.fill('#fm-coordinates','57.2500, 25.1000');page.click('#fm-go');settle(page,8000)
    page.mouse.click(900,430);page.wait_for_timeout(6000)
    log['steps']['inspect']={'panel':page.inner_text('#fm-inspect'),'status':page.inner_text('#fm-status'),
        'select_disabled':page.evaluate("()=>document.getElementById('fm-select')?.disabled"),'add_disabled':page.evaluate("()=>document.getElementById('fm-add')?.disabled")}
    page.screenshot(path=f'{OUT}/inspect.png')
    if log['steps']['inspect']['add_disabled'] is False:
        page.click('#fm-add');page.wait_for_timeout(800)
    log['steps']['selection']={'count':page.inner_text('#fm-selected-count'),'import_disabled':page.evaluate("()=>document.getElementById('fm-import').disabled")}
    # cadastral search
    page.fill('#fm-cadastre','40940020002');page.click('#fm-find');page.wait_for_timeout(8000)
    log['steps']['cadastral_search']={'status':page.inner_text('#fm-status'),'panel':page.inner_text('#fm-inspect')[:600]}
    page.screenshot(path=f'{OUT}/cadastral.png')
    page.fill('#fm-coordinates','60.1, 24.1');page.click('#fm-go');page.wait_for_timeout(500)
    log['steps']['bad_coordinates']=page.inner_text('#fm-status')
    page.click('#fm-latvia');settle(page,8000);log['steps']['all_latvia']={'modes':modes(page),'badge':page.inner_text('#fm-scale')}
    # language switch to LV
    page.select_option('#fm-language','lv');settle(page,6000)
    log['steps']['lv_text']=visible_text(page);page.screenshot(path=f'{OUT}/lv.png')
    page.select_option('#fm-language','en');page.wait_for_timeout(3000)
    log['steps']['back_to_en_title']=page.evaluate("document.getElementById('page-title')?.textContent")
    b.close()
json.dump(log,open(f'{OUT}/browser_log.json','w'),indent=1,ensure_ascii=False);print('ok',len(log['console']),len(log['failed']),len(log['http_errors']))
