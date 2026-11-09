import json,sys,statistics as st,collections
R=json.load(open(sys.argv[1]))
tiles={}
for r in R:tiles[(r['z'],r['x'],r['y'])]=r
print('distinct tiles',len(tiles),'status',collections.Counter(t['status'] for t in tiles.values()))
print('zoom | tiles | detail | presence(fallback) | other | completeness% min | median | tiles 100% | max index_exact in a 100% tile | bytes p50/max | latency s p50/max')
for z in range(7,18):
    T=[t for t in tiles.values() if t['z']==z and t['status']==200]
    if not T:continue
    md=collections.Counter(t['mode'] for t in T);comp=[t['completeness'] for t in T if t.get('completeness') is not None]
    full=[t for t in T if t.get('completeness')==100.0];mx=max([t.get('index_exact',0) for t in full],default=0)
    print(f"{z:>4} | {len(T):>5} | {md.get('simplified',0)+md.get('detail',0):>6} | {md.get('generalized_presence',0):>18} | {sum(v for k,v in md.items() if k not in ('simplified','detail','generalized_presence')):>5} | {min(comp) if comp else '-':>17} | {st.median(comp) if comp else '-':>6} | {len(full):>4}/{len(T):<4} | {mx:>8} | {int(st.median(t['bytes'] for t in T))}/{max(t['bytes'] for t in T)} | {st.median(t['seconds'] for t in T):.2f}/{max(t['seconds'] for t in T):.2f}")
# by category at zoom 11..14
print('\ncategory x zoom: fraction of sampled tiles that render individual compartments (detail mode)')
cats=sorted({r['category'] for r in R})
print('zoom | '+' | '.join(cats))
for z in range(10,18):
    row=[]
    for c in cats:
        T=[r for r in R if r['z']==z and r['category']==c and r['status']==200]
        row.append(f"{sum(1 for t in T if t['mode'] in ('simplified','detail'))}/{len(T)}")
    print(f'{z:>4} | '+' | '.join(row))
# detail tiles with completeness < 100: why
print('\ndetail tiles with completeness<100:')
for t in sorted(tiles.values(),key=lambda t:(t['z'],t['x'])):
    if t.get('mode') in ('simplified','detail') and t.get('completeness') is not None and t['completeness']<100:
        print(' z%d %d/%d exact=%s returned=%s extra=%s compl=%s missing=%s'%(t['z'],t['x'],t['y'],t['index_exact'],t['returned_ids'],t['extra_ids'],t['completeness'],t['missing_sample'][:3]))
print('\nbbox hits of fallback tiles at z11-16 (why fallback):')
for z in range(11,17):
    F=[t for t in tiles.values() if t['z']==z and t.get('mode')=='generalized_presence']
    if F:print(f' z{z}: {len(F)} tiles, index_bbox_hits min/median/max = {min(t["index_bbox_hits"] for t in F)}/{int(st.median(t["index_bbox_hits"] for t in F))}/{max(t["index_bbox_hits"] for t in F)}')
D=[t for t in tiles.values() if t.get('mode') in ('simplified','detail')]
print('detail tiles: index_bbox_hits max',max(t['index_bbox_hits'] for t in D),' features max',max(t['features'] for t in D))
