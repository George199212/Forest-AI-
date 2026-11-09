import sys,json,sqlite3,math,time,gzip,io,random,numpy as np,glob
sys.path.insert(0,sys.argv[1])
import shapely,mapbox_vector_tile
from shapely.geometry import box,mapping
from PIL import Image,ImageDraw
m=json.load(open('/root/forest_ai/data/geodata/nationwide/active.json'));c=sqlite3.connect('file:'+m['forest_db']+'?mode=ro',uri=True)
g=np.load(glob.glob('/root/forest_ai/data/geodata/forest-map/*/overview.npz')[0]);X,Y,CNT=g['x'],g['y'],g['count']
def b(z,x,y):
    n=2**z;lat=lambda a:math.degrees(math.atan(math.sinh(math.pi*(1-2*a/n))));return x/n*360-180,lat(y+1),(x+1)/n*360-180,lat(y)
def proj(z,x,y,lon,lat):
    n=2**z;px=((lon+180)/360*n-x)*256;py=((1-np.arcsinh(np.tan(np.radians(lat)))/np.pi)/2*n-y)*256;return px,py
random.seed(3);out=[]
for z in (10,11,12,13):
    sh=14-z;keys,inv=np.unique((X>>sh)*(2**z)+(Y>>sh),return_inverse=True);tot=np.bincount(inv,weights=CNT)
    order=np.argsort(tot);picks=[('densest',keys[order[-1]]),('median',keys[order[len(order)//2]])]+[('random',keys[i]) for i in random.sample(range(len(keys)),2)]
    for label,k in picks:
        x,y=int(k//2**z),int(k%2**z);w,s,e,n=b(z,x,y);clip=box(w,s,e,n)
        t=time.monotonic()
        rows=c.execute('SELECT c.geometry FROM spatial_index r JOIN compartments c ON c.id=r.id WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=?',(e,w,n,s)).fetchall()
        geoms=[shapely.from_wkb(r[0]) for r in rows];t_read=time.monotonic()-t
        # (a) current GeoJSON method, limits removed
        t=time.monotonic();tol=(e-w)/256*(1.2 if z<14 else .3);feats=[]
        for gg in geoms:
            h=gg.intersection(clip)
            if h.is_empty or h.area<=0:continue
            h=h.simplify(tol,preserve_topology=True)
            if h.geom_type in('Polygon','MultiPolygon') and h.is_valid:feats.append({'type':'Feature','geometry':mapping(h),'properties':{}})
        gj=json.dumps({'type':'FeatureCollection','features':feats},separators=(',',':')).encode();t_a=time.monotonic()-t
        # (b) MVT extent 4096, gzip
        t=time.monotonic();tol_b=(e-w)/4096*2
        mf=[{'geometry':gg.intersection(clip).simplify(tol_b,preserve_topology=True),'properties':{}} for gg in geoms]
        mf=[f for f in mf if not f['geometry'].is_empty and f['geometry'].area>0]
        mvt=mapbox_vector_tile.encode([{'name':'forest','features':mf}],default_options={'quantize_bounds':(w,s,e,n),'extents':4096});mvt_gz=gzip.compress(mvt,6);t_b=time.monotonic()-t
        # (c) raster 256px PNG
        t=time.monotonic();im=Image.new('RGBA',(256,256),(0,0,0,0));dr=ImageDraw.Draw(im)
        for gg in geoms:
            for poly in (gg.geoms if gg.geom_type=='MultiPolygon' else [gg]):
                cx,cy=np.array(poly.exterior.coords).T;px,py=proj(z,x,y,cx,cy)
                dr.polygon(list(zip(px.tolist(),py.tolist())),fill=(85,172,107,110),outline=(116,196,132,255) if z>=12 else None)
        bio=io.BytesIO();im.save(bio,'PNG',optimize=True);t_c=time.monotonic()-t
        rec={'z':z,'tile':f'{x}/{y}','sample':label,'compartments_bbox':len(rows),'read_s':round(t_read,2),
             'a_geojson_bytes':len(gj),'a_geojson_gzip':len(gzip.compress(gj,6)),'a_s':round(t_a,2),'b_mvt_gzip_bytes':len(mvt_gz),'b_s':round(t_b,2),'c_png_bytes':bio.tell(),'c_s':round(t_c,2)}
        out.append(rec);print(rec,flush=True)
json.dump(out,open(sys.argv[2],'w'),indent=1)
