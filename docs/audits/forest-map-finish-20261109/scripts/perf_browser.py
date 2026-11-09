"""usage: perf_browser.py <port> <out.json> — scripted views/pans on #forest-map, temp server only"""
import sys,json,os,time
sys.path.insert(0,'/tmp/forest_browser');os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH','/tmp/forest_chromium')
from playwright.sync_api import sync_playwright
PORT,OUT=sys.argv[1],sys.argv[2];res={}
with sync_playwright() as p:
    b=p.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage','--renderer-process-limit=1','--disable-gpu','--js-flags=--max-old-space-size=256']);ctx=b.new_context(http_credentials={'username':'audit','password':'audit-local-only'},viewport={'width':1366,'height':860})
    page=ctx.new_page();tiles=[]
    page.on('response',lambda r:'/forest-map/tiles/' in r.url and tiles.append({'url':r.url,'status':r.status,'enc':r.headers.get('content-encoding'),'cache':r.headers.get('x-forest-cache')}))
    page.add_init_script("window.__lt=0;new PerformanceObserver(l=>{for(const e of l.getEntries())window.__lt+=e.duration}).observe({type:'longtask',buffered:true});")
    page.goto(f'http://127.0.0.1:{PORT}/#forest-map');page.wait_for_function('window.ForestMap&&window.ForestMap.map',timeout=30000)
    def idle(timeout=60):
        t=time.time()
        while time.time()-t<timeout:
            st=page.evaluate('ForestMap.stats')
            if st['queued']==0 and st['running']==0:
                page.wait_for_timeout(700);st=page.evaluate('ForestMap.stats')
                if st['queued']==0 and st['running']==0:return round(time.time()-t,2)
            page.wait_for_timeout(150)
        return None
    def measure(label,action):
        n0=len(tiles);page.evaluate("performance.clearResourceTimings();window.__lt=0");t=time.time();action();page.wait_for_timeout(400);d=idle()
        r=page.evaluate("performance.getEntriesByType('resource').filter(e=>e.name.includes('/forest-map/tiles/')).map(e=>({t:e.transferSize,b:e.encodedBodySize,d:e.duration}))")
        new=tiles[n0:];lat=sorted(x['d'] for x in r)
        res[label]={'tile_requests':len(new),'status':{str(s):sum(1 for x in new if x['status']==s) for s in {x['status'] for x in new}},'transfer_bytes':sum(x['t'] for x in r),'body_bytes':sum(x['b'] for x in r),
          'gzip':sum(1 for x in new if x['enc']=='gzip'),'latency_p50_ms':round(lat[len(lat)//2]) if lat else None,'latency_max_ms':round(lat[-1]) if lat else None,'idle_s':d,'longtask_ms':round(page.evaluate('window.__lt'))}
        print(label,res[label],flush=True)
    measure('initial_country_view',lambda:None)
    measure('zoom13_view',lambda:page.evaluate("ForestMap.map.setView([57.25,25.10],13,{animate:false})"))
    def pans():
        for i in range(5):page.evaluate("ForestMap.map.panBy([350,0],{animate:false})");page.wait_for_timeout(250)
    measure('zoom13_five_pans',pans)
    measure('zoom12_view',lambda:page.evaluate("ForestMap.map.setView([56.55,24.55],12,{animate:false})"))
    page.screenshot(path=OUT.replace('.json','_z12.png'))
    b.close()
json.dump(res,open(OUT,'w'),indent=1)
