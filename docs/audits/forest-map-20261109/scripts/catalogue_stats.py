import sqlite3,json,time,collections,sys
m=json.load(open('/root/forest_ai/data/geodata/nationwide/active.json'))
c=sqlite3.connect('file:'+m['forest_db']+'?mode=ro',uri=True)
t=time.time()
Q='''SELECT source_region, source_layer, json_extract(properties,'$.zkat'), repair IS NOT NULL AND repair<>'', geometry_valid, importable,
 CASE WHEN nog_plat IS NULL THEN 'null' WHEN nog_plat=0 THEN 'zero' ELSE 'pos' END, area_m2 FROM compartments'''
by=collections.Counter(); zk=collections.Counter(); zka=collections.Counter(); reg=collections.Counter(); lay=collections.Counter()
for r in c.execute(Q):
    region,layer,z,rep,val,imp,np_,area=r
    reg[region]+=1; lay[(region,layer)]+=1; zk[(z,imp)]+=1; zka[z]+=area or 0
    by[('repair',rep)]+=1; by[('valid',val)]+=1; by[('importable',imp)]+=1; by[('nog_plat',np_)]+=1
    by[('region_rep_val',region,rep,val)]+=1
out={'seconds':time.time()-t,'total':sum(reg.values()),'regions':reg,'layers':{f'{a}/{b}':n for (a,b),n in lay.items()},
 'zkat_importable':{f'{z}|{i}':n for (z,i),n in zk.items()},'zkat_area_ha':{str(z):round(a/1e4,1) for z,a in zka.items()},
 'flags':{'|'.join(map(str,k)):v for k,v in by.items()}}
json.dump(out,open(sys.argv[1],'w'),indent=1,default=str); print('done',out['seconds'],out['total'])
