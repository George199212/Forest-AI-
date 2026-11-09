#!/usr/bin/env python3
"""Build an atomic, indexed catalogue from ALL extracted nodala SHPs; no app DB writes."""
import argparse,hashlib,json,math,os,sqlite3,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import shapely
from shapely.ops import unary_union
from services.geodata.forestry_io import inspect,records,to_wgs84,equal_area


def surface(g):
    if g.geom_type in {'Polygon','MultiPolygon'}:return g
    if hasattr(g,'geoms'):
        parts=[surface(part) for part in g.geoms];parts=[p for p in parts if not p.is_empty]
        if parts:return unary_union(parts)
    return shapely.geometry.Polygon()


def build(source,output,archive):
    files=sorted(Path(source).rglob('nodala*.shp'))
    if not files:raise ValueError('No real nodala shapefiles found')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    tmp=output.with_suffix('.building.sqlite')
    if tmp.exists():raise ValueError('A build already exists; inspect it before retrying')
    archive_hash=hashlib.file_digest(open(archive,'rb'),'sha256').hexdigest()
    version=hashlib.sha256((archive_hash+':forest-vmd-normalizer-v1').encode()).hexdigest()
    c=sqlite3.connect(tmp);c.execute('PRAGMA journal_mode=DELETE');c.execute('PRAGMA synchronous=NORMAL')
    c.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE compartments(id INTEGER PRIMARY KEY,external_id TEXT UNIQUE NOT NULL,objectid TEXT,source_layer TEXT,source_row INTEGER,kadastrs TEXT,kvart TEXT,nog TEXT,adm1 TEXT,adm2 TEXT,nog_plat REAL,geometry BLOB NOT NULL,properties TEXT NOT NULL,area_m2 REAL NOT NULL,importable INTEGER NOT NULL,repair TEXT);
    CREATE VIRTUAL TABLE spatial_index USING rtree(id,min_lon,max_lon,min_lat,max_lat);
    CREATE TABLE failed_features(source_layer TEXT,source_row INTEGER,objectid TEXT,reason TEXT,properties TEXT);
    ''')
    report={'source_archive':str(archive),'archive_sha256':archive_hash,'dataset_version':version,'source_crs':'EPSG:10306','output_crs':'EPSG:4326','datum_operation':'EPSG:10840 zero-shift approximation (1 metre datum accuracy)','normalizer':'EPSG:9807 GRS80 inverse TM, verified source parameters','layers':[],'total_source_features':0,'indexed':0,'valid':0,'repaired':0,'failed':0,'duplicate_external_ids':0,'geometry_types':{},'extent':None}
    def fail(layer,row,props,reason):
        c.execute('INSERT INTO failed_features VALUES(?,?,?,?,?)',(layer,row,str(props.get('objectid','')),reason,json.dumps(props,ensure_ascii=False,allow_nan=False)))
        report['failed']+=1
    def flush(batch):
        if not batch:return
        geoms=shapely.transform(np.array([r[2] for r in batch],dtype=object),to_wgs84)
        areas=shapely.area(shapely.transform(geoms,equal_area))
        for (layer,row,original,props,repair),g,area in zip(batch,geoms,areas):
            if not g.is_valid:
                reason=shapely.is_valid_reason(g);g=surface(shapely.make_valid(g));repair=(repair+'; ' if repair else '')+'normalized: '+reason
                area=shapely.transform(g,equal_area).area
            if g.is_empty or g.geom_type not in {'Polygon','MultiPolygon'} or not g.is_valid or area<=0:
                fail(layer,row,props,'No valid polygonal geometry after repair');continue
            w,s,e,n=g.bounds
            if not(19<=w<=e<=29 and 55<=s<=n<=59):fail(layer,row,props,'Normalized bounds outside Latvia');continue
            oid=str(props.get('objectid','')).strip();fid='VMD:'+layer+':'+(oid if oid else 'row'+str(row))
            try:
                declared=float(props.get('nog_plat')) if props.get('nog_plat') is not None else None
            except (ValueError,TypeError):declared=None
            if declared is not None and not math.isfinite(declared):declared=None
            importable=g.geom_type=='Polygon' and not len(g.interiors) and len(g.exterior.coords)<=10000
            try:
                cur=c.execute('INSERT INTO compartments(external_id,objectid,source_layer,source_row,kadastrs,kvart,nog,adm1,adm2,nog_plat,geometry,properties,area_m2,importable,repair) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (fid,oid,layer,row,str(props.get('kadastrs','')),str(props.get('kvart','')),str(props.get('nog','')),str(props.get('adm1','')),str(props.get('adm2','')),declared,g.wkb,json.dumps(props,ensure_ascii=False,separators=(',',':'),allow_nan=False),float(area),int(importable),repair))
                c.execute('INSERT INTO spatial_index VALUES(?,?,?,?,?)',(cur.lastrowid,w,e,s,n))
            except sqlite3.IntegrityError:
                report['duplicate_external_ids']+=1;fail(layer,row,props,'Duplicate layer/objectid identity (not overwritten)');continue
            report['indexed']+=1;report['repaired' if repair else 'valid']+=1
            report['geometry_types'][g.geom_type]=report['geometry_types'].get(g.geom_type,0)+1
            ext=report['extent'];report['extent']=[min(w,ext[0]),min(s,ext[1]),max(e,ext[2]),max(n,ext[3])] if ext else [w,s,e,n]
    for file in files:
        meta=inspect(file);report['layers'].append(meta);report['total_source_features']+=meta['feature_count'];batch=[]
        for row,props,g,error in records(file,meta):
            if error:fail(meta['layer'],row,props,error);continue
            repair=None
            if not g.is_valid:
                repair='source: '+shapely.is_valid_reason(g);g=surface(shapely.make_valid(g))
            if g.is_empty:fail(meta['layer'],row,props,'Empty polygon after source validation');continue
            batch.append((meta['layer'],row,g,props,repair))
            if len(batch)>=2000:
                flush(batch);batch=[];c.commit();print(meta['layer'],row,'indexed',report['indexed'],'failed',report['failed'],flush=True)
        flush(batch);c.commit();print('Completed',meta['layer'],meta['feature_count'],flush=True)
    c.executescript('CREATE INDEX objectid_idx ON compartments(objectid); CREATE INDEX cadastre_idx ON compartments(kadastrs,kvart,nog); CREATE INDEX location_idx ON compartments(adm1,adm2);')
    report['global_objectid_duplicate_groups']=c.execute("SELECT count(*) FROM (SELECT objectid FROM compartments WHERE objectid!='' GROUP BY objectid HAVING count(*)>1)").fetchone()[0]
    report['legacy_identifier_duplicate_groups']=c.execute('SELECT count(*) FROM (SELECT kadastrs,kvart,nog FROM compartments GROUP BY kadastrs,kvart,nog HAVING count(*)>1)').fetchone()[0]
    report['importable']=c.execute('SELECT count(*) FROM compartments WHERE importable=1').fetchone()[0]
    assert report['total_source_features']==report['indexed']+report['failed']
    c.execute('INSERT INTO metadata VALUES(?,?)',('report',json.dumps(report,ensure_ascii=False)))
    c.commit();assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';c.execute('ANALYZE');c.close()
    if output.exists():raise ValueError('Refusing to overwrite a published catalogue without explicit archival')
    os.replace(tmp,output);output.with_suffix('.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='layers'},indent=2),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--archive',required=True);a=p.parse_args();build(a.source,a.output,a.archive)
