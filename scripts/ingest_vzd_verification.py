"""Extract exact parcels from a downloaded official VZD archive; preserve provenance.
No VMD files or operational database are modified. Missing/duplicate CODE fails.
"""
import argparse,hashlib,json,sys,zipfile,tempfile,shutil
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import shapely
from shapely.geometry import mapping
from services.geodata.forestry_io import schema,original_geometry,to_wgs84

def ingest(archive,url,designations):
 root=Path(__file__).resolve().parents[1]/'data/cadastre';root.mkdir(exist_ok=True)
 digest=hashlib.sha256(Path(archive).read_bytes()).hexdigest();saved=root/(digest+'.zip')
 if not saved.exists():shutil.copyfile(archive,saved)
 with tempfile.TemporaryDirectory() as temp:
  z=zipfile.ZipFile(archive)
  for name in z.namelist():
   if Path(name).name.startswith('KKParcel.') and Path(name).suffix in {'.dbf','.shp','.shx','.prj','.cpg'}:
    if '..' in Path(name).parts or Path(name).is_absolute():raise ValueError('Invalid archive path')
    z.extract(name,temp)
  matches={d:[] for d in designations}
  for path in Path(temp).rglob('KKParcel.shp'):
   m=schema(path.with_suffix('.dbf'));field=next(f for f in m['fields'] if f['name']=='CODE')
   assert field['type']=='C' and field['length']==11
   with path.with_suffix('.dbf').open('rb') as dbf:
    for i in range(m['feature_count']):
     dbf.seek(m['header_bytes']+i*m['record_bytes']);raw=dbf.read(m['record_bytes'])
     code=raw[field['offset']:field['offset']+field['length']].decode('ascii').strip()
     if raw[:1]==b' ' and code in matches:
      prj=path.with_suffix('.prj').read_text();assert 'AUTHORITY[EPSG,10306]' in prj
      geom=original_geometry(path,i+1);assert geom.is_valid and not geom.is_empty
      props={f['name']:raw[f['offset']:f['offset']+f['length']].decode('utf-8').strip() for f in m['fields']}
      matches[code].append({'designation':code,'source_field':'CODE','source_layer':'KKParcel','source_file':str(path.relative_to(temp)),'source_record':i+1,'source_attributes':props,'source_crs':'EPSG:10306','source_geometry':mapping(geom),'normalized_geometry':mapping(shapely.transform(geom,to_wgs84)),'source_prj':prj,'source_geometry_sha256':hashlib.sha256(geom.wkb).hexdigest(),'archive_sha256':digest,'archive_file':saved.name,'download_url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'attribution':'Valsts zemes dienests — Kadastra informācijas sistēmas atvērtie telpiskie dati, CC BY 4.0'})
  for code,items in matches.items():
   if len(items)!=1:raise ValueError(f'{code}: expected exactly one official CODE, found {len(items)}')
   (root/(code+'.json')).write_text(json.dumps(items[0],ensure_ascii=False));print(code,items[0]['source_geometry_sha256'])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('url');p.add_argument('designation',nargs='+');a=p.parse_args();ingest(a.archive,a.url,a.designation)
