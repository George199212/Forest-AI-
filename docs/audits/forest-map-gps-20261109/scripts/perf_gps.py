"""100 moving SIMULATED entities on the TEMP server (synthetic, /tmp DB copy only). usage: perf_gps.py <port> <db> <out.json>"""
import sys,os,json,time,random,sqlite3,urllib.request,base64
sys.path.insert(0,'/tmp/forest_browser');os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH','/tmp/forest_chromium')
from playwright.sync_api import sync_playwright
PORT,DB,OUT=sys.argv[1],sys.argv[2],sys.argv[3];AUTH='Basic '+base64.b64encode(b'audit:audit-local-only').decode()
assert DB.startswith('/tmp/'),'perf data may only be written to a /tmp copy'
random.seed(11);base=[(57.25+random.uniform(-.06,.06),25.10+random.uniform(-.1,.1)) for _ in range(100)]
def move(step):
    ts=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    with sqlite3.connect(DB) as c:
        for i,(lat,lon) in enumerate(base):
            la,lo=lat+step*0.0015,lon+step*0.002;key=f'PERF-{i:03d}:{step}'
            c.execute("INSERT INTO integration_records(integration_id,organization_id,source_provider,entity_type,external_id,sector,source_timestamp,received_at,raw_payload_json,normalized_payload_json,validation_status,deduplication_key) VALUES(3,1,'fleet_gps_demo','GPSPosition',?,'PERF',?,?,'{}',?,'VALID',?)",
                      (key,ts,ts,json.dumps({'vehicle_id':f'PERF-{i:03d}','sector':'PERF','latitude':la,'longitude':lo,'source_timestamp':ts}),key))
def api():
    t=time.monotonic();b=urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{PORT}/api/geodata/forest-map/gps/positions',headers={'Authorization':AUTH}),timeout=120).read();return time.monotonic()-t,len(b),len(json.loads(b)['entities'])
res={'server':[],'browser':[]}
move(0)
for _ in range(3):dt,size,n=api();res['server'].append({'seconds':round(dt,3),'bytes':size,'entities':n});print('server',res['server'][-1],flush=True)
with sync_playwright() as p:
    b=p.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage','--renderer-process-limit=1','--disable-gpu','--js-flags=--max-old-space-size=256'])
    page=b.new_context(http_credentials={'username':'audit','password':'audit-local-only'},viewport={'width':1366,'height':860}).new_page()
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:m.type=='error' and errors.append(m.text))
    page.add_init_script("window.__lt=0;window.__ltMax=0;new PerformanceObserver(l=>{for(const e of l.getEntries()){window.__lt+=e.duration;window.__ltMax=Math.max(window.__ltMax,e.duration)}}).observe({type:'longtask',buffered:true});")
    page.goto(f'http://127.0.0.1:{PORT}/#forest-map');page.wait_for_function('window.ForestMap&&ForestMap.map',timeout=30000);page.wait_for_timeout(3000)
    page.evaluate("ForestMap.map.setView([57.25,25.10],13,{animate:false})");page.wait_for_timeout(9000)
    for step in (1,2):
        move(step);page.evaluate("window.__lt=0;window.__ltMax=0");page.wait_for_timeout(31500)
        st=page.evaluate('ForestMap.stats');pos=page.evaluate("[...document.querySelectorAll('.leaflet-fmGps-pane .fm-gps')].length")
        res['browser'].append({'poll':step,'markers_in_dom':pos,'gps_markers':st.get('gpsMarkers'),'gps_render_ms':round(st.get('gpsRenderMs') or 0,1),'longtask_ms_during_poll_window':round(page.evaluate('window.__lt')),'longest_task_ms':round(page.evaluate('window.__ltMax'))});print('browser',res['browser'][-1],flush=True)
    t=time.monotonic()
    for _ in range(5):page.evaluate("ForestMap.map.panBy([300,0],{animate:false})");page.wait_for_timeout(300)
    page.wait_for_timeout(4000);res['pan_with_100_markers']={'longtask_ms':round(page.evaluate('window.__lt')),'longest_task_ms':round(page.evaluate('window.__ltMax'))};res['errors']=errors
    print('pan',res['pan_with_100_markers'],'errors',errors[:3])
    b.close()
json.dump(res,open(OUT,'w'),indent=1)
