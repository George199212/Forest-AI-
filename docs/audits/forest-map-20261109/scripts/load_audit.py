"""usage: load_audit.py <port> <server_pid> <out.json>"""
import sys,json,math,time,base64,urllib.request,statistics,threading
from concurrent.futures import ThreadPoolExecutor
PORT,PID,OUT=sys.argv[1],int(sys.argv[2]),sys.argv[3]
AUTH='Basic '+base64.b64encode(b'audit:audit-local-only').decode()
def txy(lat,lon,z):n=2**z;return int((lon+180)/360*n),int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
def proc():
    st=open(f'/proc/{PID}/stat').read().split();tck=__import__('os').sysconf('SC_CLK_TCK')
    rss=int([l for l in open(f'/proc/{PID}/status') if l.startswith('VmRSS')][0].split()[1])//1024
    return (int(st[13])+int(st[14]))/tck,rss
def get(z,x,y):
    req=urllib.request.Request(f'http://127.0.0.1:{PORT}/api/geodata/forest-map/tiles/forest/{z}/{x}/{y}',headers={'Authorization':AUTH});t=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=60) as r:b=r.read();d=json.loads(b);return {'s':200,'bytes':len(b),'t':time.monotonic()-t,'mode':d['mode'],'f':len(d['features'])}
    except urllib.error.HTTPError as e:return {'s':e.code,'bytes':0,'t':time.monotonic()-t,'mode':None,'f':0}
def run(tiles,workers=3):
    cpu0,rss0=proc();t0=time.monotonic();peak=[rss0];stop=False
    def sampler():
        while not stop:peak.append(proc()[1]);time.sleep(.2)
    th=threading.Thread(target=sampler);th.start()
    with ThreadPoolExecutor(workers) as ex:res=list(ex.map(lambda k:get(*k),tiles))
    stop=True;th.join();cpu1,_=proc();lat=[r['t'] for r in res if r['s']==200]
    modes={};[modes.__setitem__(r['mode'],modes.get(r['mode'],0)+1) for r in res]
    return {'tiles':len(tiles),'wall_s':round(time.monotonic()-t0,1),'bytes':sum(r['bytes'] for r in res),'status':{str(s):sum(1 for r in res if r['s']==s) for s in {r['s'] for r in res}},
            'p50_s':round(statistics.median(lat),3) if lat else None,'p95_s':round(sorted(lat)[int(.95*len(lat))-1],3) if lat else None,'max_s':round(max(lat),3) if lat else None,
            'modes':modes,'features':sum(r['f'] for r in res),'server_cpu_s':round(cpu1-cpu0,1),'server_rss_mb_peak':max(peak),'server_rss_mb_start':rss0}
out={}
for z in (10,13):
    x0,y0=txy(56.95,20.9,z);x1,_=txy(56.95,28.3,z)
    tiles=[(z,x,y) for x in range(x0-2,x1+4) for y in range(y0-1,y0+3)]
    out[f'pan_z{z}']=run(tiles);print(z,out[f'pan_z{z}'],flush=True)
areas=[(57.55,25.70),(56.50,27.30),(57.10,22.00),(56.55,24.55),(57.75,24.90)]
def user(a):
    x,y=txy(a[0],a[1],13);return run([(13,x+i,y+j) for i in range(-3,3) for j in range(-2,2)],3)
with ThreadPoolExecutor(5) as ex:out['five_users_z13']=list(ex.map(user,areas))
print(json.dumps(out['five_users_z13'])[:1500])
json.dump(out,open(OUT,'w'),indent=1)
