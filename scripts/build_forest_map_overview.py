"""Build disposable visualization cells from the existing RTree; no ingest/migration."""
import json, sys, time, os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from services.geodata import forest_map as fm, nationwide as nw

def build():
    start=time.monotonic();m=nw.release();target=fm.DISPLAY_ROOT/m['version'];target.mkdir(parents=True,exist_ok=True)
    if (target/'overview.npz').exists():
        print('Existing derived overview retained:',target);return
    cells={};records=0;scale=2**fm.GRID_ZOOM
    with nw.db(m['forest_db']) as c:
        cursor=c.execute('SELECT (min_lon+max_lon)/2,(min_lat+max_lat)/2 FROM spatial_index')
        while rows:=cursor.fetchmany(50000):
            a=np.array(rows,dtype=float);x=np.floor((a[:,0]+180)/360*scale).astype(np.int64)
            y=np.floor((1-np.arcsinh(np.tan(np.radians(a[:,1])))/np.pi)/2*scale).astype(np.int64)
            keys,counts=np.unique(x*scale+y,return_counts=True)
            for key,count in zip(keys,counts):cells[int(key)]=cells.get(int(key),0)+int(count)
            records+=len(rows)
    if records!=m['reports']['vmd']['indexed']:raise RuntimeError('RTree/source count mismatch')
    keys=np.array(sorted(cells),dtype=np.int64);counts=np.array([cells[int(k)] for k in keys],dtype=np.int64)
    temp=target/'overview.tmp.npz'
    np.savez_compressed(temp,x=keys//scale,y=keys%scale,count=counts,version=m['version'],records=records)
    os.replace(temp,target/'overview.npz')
    report={'dataset_version':m['version'],'source_records':records,'occupied_cells':len(keys),'cell_zoom':fm.GRID_ZOOM,'seconds':time.monotonic()-start,'source':'read-only WGS84 RTree bounding-box centers','meaning':'generalized forest presence; not exact coverage boundaries'}
    (target/'overview.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':build()
