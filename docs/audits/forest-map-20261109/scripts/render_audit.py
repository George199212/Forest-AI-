"""Rendering completeness: request the frontend's tiles, compare with exact index intersections.
usage: render_audit.py <port> <out.json>   (read-only national index; temp server only)"""
import json,math,sqlite3,sys,time,base64,urllib.request
import shapely
from shapely.geometry import box
PORT=int(sys.argv[1]);OUT=sys.argv[2]
AUTH='Basic '+base64.b64encode(b'audit:audit-local-only').decode()
m=json.load(open('/root/forest_ai/data/geodata/nationwide/active.json'))
c=sqlite3.connect('file:'+m['forest_db']+'?mode=ro',uri=True)
P=[('riga','Riga centre',56.9496,24.1052),('riga','Riga Mežaparks',56.995,24.145),('riga','Riga Imanta',56.945,23.98),('riga','Riga Purvciems',56.955,24.20),
('coastal','Jūrmala',56.968,23.77),('coastal','Saulkrasti',57.26,24.41),('coastal','Kolka',57.75,22.59),('coastal','Pāvilosta',56.89,21.19),('coastal','Liepāja',56.51,21.01),
('coastal','Ventspils',57.39,21.56),('coastal','Ainaži',57.86,24.36),('coastal','Engure',57.16,23.22),('coastal','Roja',57.50,22.80),
('border','Bauska–LT',56.35,24.20),('border','Rucava–LT',56.17,21.17),('border','Valka–EE',57.78,26.02),('border','Zilupe–RU',56.38,28.12),('border','Piedruja–BY',55.80,27.45),('border','Ape–EE',57.54,26.69),
('dense','Ķemeri',56.90,23.45),('dense','Slītere',57.63,22.30),('dense','Gauja NP',57.25,25.10),('dense','Taurkalne',56.50,24.90),('dense','Kurzeme forest',57.10,22.00),
('dense','Zilaiskalns',57.55,25.70),('dense','Vecumnieki',56.55,24.55),('dense','Lubāna',56.85,26.90),('dense','Aloja',57.75,24.90),('dense','Dundaga',57.50,22.35),
('dense','Kalsnava',56.70,25.95),('dense','Ogre forest',56.80,24.90),('dense','Kuldīga woods',56.90,21.80),
('sparse','Jelgava fields',56.55,23.80),('sparse','Dobele',56.62,23.28),('sparse','Bauska fields',56.42,24.05),('sparse','Eleja',56.43,23.70),('sparse','Rēzekne fields',56.50,27.30),
('sparse','Daugavpils',55.87,26.53),('sparse','Jēkabpils',56.50,25.86),('sparse','Valmiera',57.54,25.42),('sparse','Madona',56.85,26.22),('sparse','Gulbene',57.17,26.75),
('sparse','Alūksne',57.42,27.05),('sparse','Ludza',56.55,27.72),('sparse','Preiļi',56.29,26.72),('sparse','Saldus',56.66,22.49),('sparse','Tukums',56.97,23.15),
('sparse','Talsi',57.24,22.59),('water','Gulf of Riga',57.30,23.80),('water','Lake Lubāns',56.77,26.85)]
def tile_xy(lat,lon,z):
    n=2**z;x=int((lon+180)/360*n);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n);return x,y
def bounds(z,x,y):
    n=2**z;lat=lambda a:math.degrees(math.atan(math.sinh(math.pi*(1-2*a/n))))
    return (x/n*360-180,lat(y+1),(x+1)/n*360-180,lat(y))
def region(lat,lon):
    for r in (0.01,0.05,0.2):
        row=c.execute('SELECT c.source_region FROM spatial_index s JOIN compartments c ON c.id=s.id WHERE s.min_lon<=? AND s.max_lon>=? AND s.min_lat<=? AND s.max_lat>=? LIMIT 1',(lon+r,lon-r,lat+r,lat-r)).fetchone()
        if row:return row[0]
    return None
def truth(z,x,y):
    w,s,e,n=bounds(z,x,y)
    bbox=c.execute('SELECT count(*) FROM spatial_index WHERE min_lon<=? AND max_lon>=? AND min_lat<=? AND max_lat>=?',(e,w,n,s)).fetchone()[0]
    if bbox>20000:return bbox,None
    clip=box(w,s,e,n);ids=set()
    for fid,g in c.execute('SELECT c.external_id,c.geometry FROM spatial_index r JOIN compartments c ON c.id=r.id WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=?',(e,w,n,s)):
        geom=shapely.from_wkb(g)
        try:
            if geom.intersection(clip).area>0:ids.add(fid)
        except shapely.errors.GEOSException:
            if geom.intersects(clip):ids.add(fid)
    return bbox,ids
def fetch(z,x,y):
    req=urllib.request.Request(f'http://127.0.0.1:{PORT}/api/geodata/forest-map/tiles/forest/{z}/{x}/{y}',headers={'Authorization':AUTH})
    t=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=60) as r:body=r.read();status=r.status;cache=r.headers.get('X-Forest-Cache')
    except urllib.error.HTTPError as e:body=e.read();status=e.code;cache=None
    return status,body,time.monotonic()-t,cache
results=[];seen={}
for cat,name,lat,lon in P:
    reg=region(lat,lon)
    for z in range(7,18):
        x,y=tile_xy(lat,lon,z);key=(z,x,y)
        if key not in seen:
            status,body,dt,cache=fetch(z,x,y)
            rec={'z':z,'x':x,'y':y,'status':status,'bytes':len(body),'seconds':round(dt,3),'cache':cache}
            if status==200:
                d=json.loads(body);rec['mode']=d.get('mode');rec['features']=len(d['features'])
                got={f['properties'].get('id') for f in d['features'] if f['properties'].get('id')}
                bbox,ids=truth(z,x,y);rec['index_bbox_hits']=bbox
                if ids is not None:
                    rec['index_exact']=len(ids);rec['returned_ids']=len(got&ids);rec['extra_ids']=len(got-ids)
                    rec['missing_sample']=sorted(ids-got)[:5]
                    rec['completeness']=round(100*len(got&ids)/len(ids),2) if ids else None
                else:rec['completeness']=0.0 if rec['mode']=='generalized_presence' else None
                rec['limit_hit']=rec['mode']=='generalized_presence' and z>10
            seen[key]=rec
        results.append({'category':cat,'name':name,'lat':lat,'lon':lon,'region':reg,**seen[key]})
    print(name,reg,flush=True)
json.dump(results,open(OUT,'w'),indent=1,ensure_ascii=False)
