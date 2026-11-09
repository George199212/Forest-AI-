import json,sqlite3,random,math,base64,urllib.request,sys
import shapely
from shapely.ops import transform
from pyproj import Transformer,Geod
m=json.load(open('/root/forest_ai/data/geodata/nationwide/active.json'))
c=sqlite3.connect('file:'+m['forest_db']+'?mode=ro',uri=True)
T=Transformer.from_crs(10306,4326,always_xy=True);G=Geod(ellps='WGS84')
AUTH='Basic '+base64.b64encode(b'audit:audit-local-only').decode()
random.seed(20261109);ids=random.sample(range(1,3063410),20)
def maxdist(a,b):
    # max over a's vertices of distance to nearest point of b (directed Hausdorff, metres via geodesic)
    worst=0
    for x,y in shapely.get_coordinates(a):
        p=b.exterior.interpolate(b.exterior.project(shapely.Point(x,y))) if b.geom_type=='Polygon' else shapely.ops.nearest_points(b.boundary,shapely.Point(x,y))[0]
        worst=max(worst,G.inv(x,y,p.x,p.y)[2])
    return worst
out=[]
for i in ids:
    r=c.execute('select external_id,source_crs,native_geometry,geometry,source_region from compartments where id=?',(i,)).fetchone()
    fid,crs,native,disp,reg=r
    nat=shapely.from_wkb(native);ref=transform(T.transform,nat);stored=shapely.from_wkb(disp)
    req=urllib.request.Request(f'http://127.0.0.1:{sys.argv[1]}/api/geodata/forest-map/feature?id={urllib.parse.quote(fid)}',headers={'Authorization':AUTH})
    try:
        api=shapely.geometry.shape(json.load(urllib.request.urlopen(req,timeout=60))['feature']['geometry']);api_err=round(maxdist(api,ref if ref.geom_type=='Polygon' else ref.geoms[0]),3) if ref.geom_type=='Polygon' else round(shapely.hausdorff_distance(api,ref)*111320*0.55,3)
    except Exception as e: api=None;api_err=str(e)[:60]
    st_err=round(shapely.hausdorff_distance(stored,ref),9)
    out.append({'external_id':fid,'region':reg,'source_crs':crs,'vertices':int(shapely.get_num_coordinates(nat)),
      'stored_vs_pyproj_hausdorff_deg':st_err,'stored_vs_pyproj_m_approx':round(st_err*111320,3),'api_vs_pyproj_max_m':api_err,
      'centroid':[round(ref.centroid.y,5),round(ref.centroid.x,5)]})
    print(out[-1],flush=True)
json.dump(out,open(sys.argv[2],'w'),indent=1)
