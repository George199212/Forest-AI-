"""Read-only independent DBF scan and SHX/SHP geometry audit; never modifies data.
Run: python3 scripts/audit_vmd_cadastre.py 40940020002
"""
import argparse,csv,hashlib,json,mmap,sys
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np,shapely
from shapely.ops import transform
from shapely.geometry import mapping,shape
from pyproj import Transformer
from services.geodata.forestry_io import inspect,original_geometry,to_wgs84
from services.geodata import vmd_dataset as data


def audit(cadastre,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parents[1]
    sources=sorted((root/'data/vmd/source').rglob('nodala*.shp'))
    assert sources,'Original VMD source missing'
    rows=[];schemas=[];raw_ids=[]
    proj=Transformer.from_crs(10306,4326,always_xy=True)
    back=Transformer.from_crs(4326,10306,always_xy=True)
    with closing(data.connect()) as catalog:
        indexed=catalog.execute('SELECT * FROM compartments WHERE kadastrs=?',(cadastre,)).fetchall()
        indexed_by_id={row['external_id']:row for row in indexed}
        for path in sources:
            meta=inspect(path);schemas.append({'file':path.name,'crs':meta['source_crs'],'fields':meta['fields']})
            field=next(f for f in meta['fields'] if f['name']=='kadastrs')
            with path.with_suffix('.dbf').open('rb') as dbf:
                with mmap.mmap(dbf.fileno(),0,access=mmap.ACCESS_READ) as raw:
                    values=np.ndarray((meta['feature_count'],),dtype='S'+str(field['length']),buffer=raw,offset=meta['header_bytes']+field['offset'],strides=(meta['record_bytes'],))
                    matches=np.flatnonzero(np.char.strip(values,b' \x00')==cadastre.encode()).tolist();del values
                for index in matches:
                    dbf.seek(meta['header_bytes']+index*meta['record_bytes']);record=dbf.read(meta['record_bytes'])
                    assert record[:1]!=b'*','Deleted DBF record encountered'
                    props={f['name']:record[f['offset']:f['offset']+f['length']].decode('utf-8').strip(' \0') for f in meta['fields']}
                    fid='VMD:'+path.stem+':'+props['objectid'];raw_ids.append(fid)
                    native=original_geometry(path,index+1);independent=transform(proj.transform,native)
                    row=indexed_by_id[fid];display=shapely.from_wkb(row['geometry'])
                    delta=transform(back.transform,display).hausdorff_distance(native)
                    centroid=independent.centroid
                    assert all(str(row[k])==props[k] for k in ['kadastrs','kvart','nog','objectid'])
                    assert row['source_row']==index+1 and row['source_layer']==path.stem
                    assert delta<.01,'Source/display geometry differs by >1 cm in the same documented datum approximation'
                    assert display.is_valid and native.is_valid
                    rows.append({'source_file':path.name,'source_row':index+1,'source_feature_id':fid,'cadastral_designation':props['kadastrs'],'quarter':props['kvart'],'compartment':props['nog'],'subcompartment':props['anog'],'centroid_lon':round(centroid.x,9),'centroid_lat':round(centroid.y,9),'area_ha':float(props['nog_plat']),'computed_source_area_ha':native.area/10000,'geometry_valid':bool(native.is_valid and display.is_valid),'source_bounds':list(native.bounds),'display_bounds':list(display.bounds),'max_geometry_difference_m':delta,'normalized_geometry':mapping(display),'source_geometry_sha256':hashlib.sha256(native.wkb).hexdigest()})
        assert set(raw_ids)==set(indexed_by_id),'Raw DBF matches and catalogue matches disagree'
    rows.sort(key=lambda row:(int(row['quarter']),int(row['compartment'])))
    hashes=[r['source_geometry_sha256'] for r in rows]
    identities=[(r['cadastral_designation'],r['quarter'],r['compartment'],r['subcompartment']) for r in rows]
    extent=shapely.union_all([shape(r['normalized_geometry']) for r in rows]).bounds
    first=Transformer.from_crs(4326,10306,always_xy=True)
    xy=[first.transform(r['centroid_lon'],r['centroid_lat']) for r in rows]
    span=max(np.hypot(a[0]-b[0],a[1]-b[1]) for a in xy for b in xy) if xy else 0
    result={'cadastre':cadastre,'source_crs':'EPSG:10306','output_crs':'EPSG:4326','axis_order':'longitude,latitude','source_records':len(rows),'catalogue_records':len(indexed),'duplicate_source_ids':len(raw_ids)-len(set(raw_ids)),'duplicate_compartment_keys':len(identities)-len(set(identities)),'duplicate_geometries':len(hashes)-len(set(hashes)),'total_declared_area_ha':round(sum(r['area_ha'] for r in rows),2),'extent':list(extent),'max_centroid_separation_m':span,'max_geometry_difference_m':max((r['max_geometry_difference_m'] for r in rows),default=0),'transform_description':proj.description,'transform_accuracy_m':proj.accuracy,'schemas':schemas,'rows':rows}
    (output/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    columns=['source_file','source_feature_id','cadastral_designation','quarter','compartment','centroid_lon','centroid_lat','area_ha','geometry_valid']
    with (output/'audit.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    lines=['| Source file | Source feature ID | Kadastra apzīmējums | Kvartāls | Nogabals | Centroid lon | Centroid lat | ha | Valid |','|---|---|---|---|---|---|---|---|---|']
    lines+=['| '+' | '.join(str(r[k]) for k in columns)+' |' for r in rows]
    (output/'table.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['schemas','rows']},indent=2));print('\n'.join(lines))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cadastre');p.add_argument('--output',default='data/vmd/cadastral-audit-40940020002');args=p.parse_args();audit(args.cadastre,args.output)
