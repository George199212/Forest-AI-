import json,sqlite3,math,numpy as np,glob,time,sys
m=json.load(open('/root/forest_ai/data/geodata/nationwide/active.json'))
c=sqlite3.connect('file:'+m['forest_db']+'?mode=ro',uri=True)
g=np.load(glob.glob('/root/forest_ai/data/geodata/forest-map/*/overview.npz')[0]);X,Y,CNT=g['x'],g['y'],g['count']
def b(z,x,y):
    n=2**z;lat=lambda a:math.degrees(math.atan(math.sinh(math.pi*(1-2*a/n))));return x/n*360-180,lat(y+1),(x+1)/n*360-180,lat(y)
out={}
for z in (11,12,13,14,15):
    t=time.time();sh=14-z;keys,inv=np.unique((X>>sh)*(2**z)+(Y>>sh),return_inverse=True);centers=np.bincount(inv,weights=CNT).astype(int)
    hits=[];fb=0;fb_centers=0
    for k,cn in zip(keys,centers):
        w,s,e,n=b(z,int(k//2**z),int(k%2**z))
        h=c.execute('SELECT count(*) FROM (SELECT 1 FROM spatial_index WHERE min_lon<=? AND max_lon>=? AND min_lat<=? AND max_lat>=? LIMIT 601)',(e,w,n,s)).fetchone()[0]
        hits.append(h)
        if h>600:fb+=1;fb_centers+=int(cn)
    hits=np.array(hits)
    out[z]={'occupied_tiles':len(keys),'fallback_tiles_count_rule':fb,'fallback_pct':round(100*fb/len(keys),2),'compartments_centred_in_fallback_tiles':fb_centers,'pct_of_catalogue':round(100*fb_centers/3063409,2),'bbox_hits_p50':int(np.median(hits)),'bbox_hits_max_capped601':int(hits.max()),'seconds':round(time.time()-t,1)}
    print(z,out[z],flush=True)
json.dump(out,open(sys.argv[1],'w'),indent=1)
