#!/usr/bin/env python3
"""Resumable official-source ingestion. Never writes Forest AI's operational DB.
Progress: ROOT/progress.json. Resume by rerunning the same --root command.
A release.json marked READY is produced only after all47 archives pass validation.
"""
import argparse,concurrent.futures,fcntl,hashlib,json,math,os,re,sqlite3,struct,sys,time,zipfile
from pathlib import Path
from datetime import datetime,timezone
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE));sys.path.insert(0,str(BASE/'data/geodata/ingest-deps'))
import requests,numpy as np,shapely,py7zr
from shapely.ops import unary_union
from pyproj import CRS,Transformer
from services.geodata.forestry_io import schema,polygon_record,to_wgs84
VERSION='forest-national-v2'

def stamp():return datetime.now(timezone.utc).isoformat()
def atomic(path,value):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));os.replace(tmp,path)
def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def connect(path):
    c=sqlite3.connect(path,timeout=60);c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=NORMAL');c.execute('PRAGMA cache_size=-32000');return c

def metadata(path,kind):
    m=schema(path.with_suffix('.dbf'));text=path.with_suffix('.prj').read_text();crs=CRS.from_wkt(text);p=crs.to_dict()
    expected={'proj':'tmerc','lat_0':0,'lon_0':24,'k':.9996,'x_0':500000,'y_0':-6000000,'units':'m'}
    for key,value in expected.items():
        if p.get(key)!=value:raise ValueError(f'Unsupported CRS parameter {key}: {path}')
    datum=str(crs.datum)
    if '2020' in datum:epsg='EPSG:10306'
    elif '1992' in datum or '92' in datum:epsg='EPSG:3059'
    else:raise ValueError(f'Unverified datum {datum}')
    if abs(crs.ellipsoid.semi_major_metre-6378137)>1e-6 or abs(crs.ellipsoid.inverse_flattening-298.257222101)>1e-6:raise ValueError('Unsupported ellipsoid')
    with path.open('rb') as f:h=f.read(100)
    if len(h)!=100 or struct.unpack_from('>I',h)[0]!=9994 or struct.unpack_from('<I',h,32)[0]!=5:raise ValueError('Not a 2D polygon SHP')
    if (path.with_suffix('.shx').stat().st_size-100)//8!=m['feature_count']:raise ValueError('SHP/DBF count mismatch')
    encoding=path.with_suffix('.cpg').read_text().strip() if path.with_suffix('.cpg').exists() else 'UTF-8'
    if encoding.upper() not in {'UTF-8','UTF8','65001'}:raise ValueError(f'Unsupported CPG {encoding}')
    field='kadastrs' if kind=='vmd' else 'CODE';f=next((f for f in m['fields'] if f['name']==field),None)
    if not f or f['type']!='C':raise ValueError(f'Expected character cadastral field {field}')
    with path.with_suffix('.dbf').open('rb') as f:h=f.read(32)
    return {**m,'path':str(path.resolve()),'layer':path.stem,'source_crs':epsg,'source_wkt':text,'encoding':encoding,'export_date':f'{1900+h[1]:04}-{h[2]:02}-{h[3]:02}'}

def records(path,m,start):
    with path.open('rb') as shp,path.with_suffix('.dbf').open('rb') as dbf,path.with_suffix('.shx').open('rb') as shx:
        if start>m['feature_count']:return
        shx.seek(100+(start-1)*8);entry=shx.read(8)
        if len(entry)!=8:raise ValueError('Source index missing')
        offset,_=struct.unpack('>II',entry);shp.seek(offset*2);dbf.seek(m['header_bytes']+(start-1)*m['record_bytes'])
        for row in range(start,m['feature_count']+1):
            h=shp.read(8)
            if len(h)!=8:raise ValueError('Truncated source')
            number,words=struct.unpack('>II',h)
            if number!=row or not 2<=words<=16*1024*1024:raise ValueError('Invalid SHP record')
            body=shp.read(words*2);raw=dbf.read(m['record_bytes'])
            if len(body)!=words*2 or len(raw)!=m['record_bytes']:raise ValueError('Truncated source record')
            props={}
            for f in m['fields']:
                value=raw[f['offset']:f['offset']+f['length']].decode('utf-8').strip(' \0')
                if f['type'] in {'N','F'}:
                    try:value=float(value) if '.' in value or 'e' in value.lower() else int(value)
                    except ValueError:value=value or None
                    if isinstance(value,float) and not math.isfinite(value):value=str(value)
                props[f['name']]=value
            try:
                if raw[:1]==b'*':raise ValueError('Deleted DBF record')
                yield row,props,polygon_record(body),None
            except (ValueError,struct.error) as e:yield row,props,None,str(e)

def surface(g):
    if g.geom_type in {'Polygon','MultiPolygon'}:return g
    return unary_union([x for x in getattr(g,'geoms',[]) if x.geom_type in {'Polygon','MultiPolygon'}])

def prepared_records(path,m,start,canonical):
    """Vectorized coordinate normalization; bounded batches, unchanged native WKB."""
    def prepare(batch):
        values=[];sources=[]
        for row,props,original,error in batch:
            native=None;valid=False;display_source=None
            try:
                if not error:
                    native=canonical(original);valid=native.is_valid and not native.is_empty
                    display_source=native if valid else surface(shapely.make_valid(native))
            except (ValueError,shapely.errors.GEOSException) as ex:error=str(ex)
            values.append((row,props,original,error,native,valid));sources.append(display_source)
        projected=shapely.transform(np.array(sources,dtype=object),to_wgs84)
        for value,display in zip(values,projected):yield (*value,display)
    batch=[]
    for record in records(path,m,start):
        batch.append(record)
        if len(batch)>=500:yield from prepare(batch);batch=[]
    if batch:yield from prepare(batch)

class Job:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True);self.progress={'status':'RUNNING','phase':'starting','updated_at':stamp()};self.last_progress=0
        self.lock=(self.root/'job.lock').open('w');fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB);self.lock.write(str(os.getpid()));self.lock.flush()
        for name in ['downloads','sources']: (self.root/name).mkdir(exist_ok=True)
    def update(self,**kw):
        self.progress.update(kw,updated_at=stamp());atomic(self.root/'progress.json',self.progress)
        print(json.dumps(self.progress,ensure_ascii=False),flush=True)
    def catalogue(self):
        path=self.root/'sources.json'
        if path.exists():return json.loads(path.read_text())
        out=[]
        for kind,name,licence in [('vmd','meza-valsts-registra-meza-dati','CC0-1.0'),('vzd','kadastra-informacijas-sistemas-atverti-telpiskie-dati','CC-BY-4.0')]:
            r=requests.get('https://data.gov.lv/dati/api/3/action/package_show',params={'id':name},timeout=(10,60));r.raise_for_status();j=r.json()['result']
            if j['license_id']!=licence:raise ValueError('Source licence changed; review required')
            atomic(self.root/(kind+'-catalogue.json'),j)
            for item in j['resources']:
                if item['format'].upper()!='SHP':continue
                url=item['url']
                if not url.startswith('https://data.gov.lv/dati/dataset/'):raise ValueError('Unapproved source URL')
                out.append({'kind':kind,'name':item['name'],'id':item['id'],'url':url,'size':item['size'],'last_modified':item['last_modified'],'licence':licence,'publisher':j['organization']['title'],'source_date':'2026-10-07' if kind=='vmd' and '07.10.2026' in item.get('description','') else item.get('last_modified','')[:10]})
        if sum(x['kind']=='vmd' for x in out)!=5 or sum(x['kind']=='vzd' for x in out)!=42:raise ValueError('Required national sources not all listed')
        atomic(path,out);return out
    def download(self,item):
        suffix='.7z' if item['kind']=='vmd' else '.zip';path=self.root/'downloads'/(item['id']+suffix);part=path.with_suffix(path.suffix+'.part')
        if path.exists() and path.stat().st_size==item['size']:return
        for attempt in range(5):
            try:
                offset=part.stat().st_size if part.exists() else 0
                if offset>item['size']:part.unlink();offset=0
                if offset==item['size']:os.replace(part,path);return
                with requests.get(item['url'],headers={'Range':f'bytes={offset}-'},stream=True,timeout=(10,45)) as r:
                    r.raise_for_status()
                    if r.status_code==206:
                        if not r.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Invalid resumed range')
                    elif r.status_code==200:offset=0
                    else:raise ValueError('Unexpected download response')
                    with part.open('ab' if offset else 'wb') as f:
                        for data in r.iter_content(1024*1024):f.write(data)
                if part.stat().st_size!=item['size']:raise ValueError('Download size mismatch')
                os.replace(part,path);return
            except Exception:
                if attempt==4:raise
                time.sleep(min(2**attempt,15))
    def extract(self,item):
        folder=self.root/'sources'/item['kind']/item['id'];folder.mkdir(parents=True,exist_ok=True);marker=folder/'archive-verified.json'
        archive=self.root/'downloads'/(item['id']+('.7z' if item['kind']=='vmd' else '.zip'))
        if marker.exists():
            data=json.loads(marker.read_text())
            if data['size']==archive.stat().st_size and data['sha256']==digest(archive):return folder,data['sha256']
        sha=digest(archive)
        self.update(phase='archive_validation',source=item['name'])
        if item['kind']=='vmd':
            with py7zr.SevenZipFile(archive,'r') as z:
                if z.needs_password():raise ValueError('Encrypted archive not permitted')
                names=z.getnames()
                if any(Path(n).is_absolute() or '..' in Path(n).parts for n in names):raise ValueError('Unsafe archive member')
                # Extraction verifies each packed stream/member CRC. Resuming re-extracts a partial archive safely.
                z.extractall(path=folder)
        else:
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    if Path(info.filename).is_absolute() or '..' in Path(info.filename).parts:raise ValueError('Unsafe archive member')
                    if Path(info.filename).name.startswith('KKParcel.') and Path(info.filename).suffix.lower() in {'.shp','.shx','.dbf','.prj','.cpg'}:z.extract(info,folder)
                # Validate all archive members, including non-parcel layers, without retaining irrelevant geometry.
                if z.testzip() is not None:raise ValueError('ZIP CRC validation failed')
        atomic(marker,{'sha256':sha,'size':archive.stat().st_size,'verified_at':stamp(),'crc_validated':True});return folder,sha
    def db(self,kind):
        c=connect(self.root/('compartments.sqlite' if kind=='vmd' else 'parcels.sqlite'))
        c.executescript('''CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,last_row INTEGER NOT NULL DEFAULT 0,total_rows INTEGER NOT NULL,complete INTEGER NOT NULL DEFAULT 0,meta TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rejections(source_file TEXT,source_row INTEGER,reason TEXT,properties TEXT,PRIMARY KEY(source_file,source_row));
        CREATE TABLE IF NOT EXISTS duplicate_sources(source_file TEXT,source_row INTEGER,identity TEXT,identical INTEGER,properties TEXT,geometry BLOB,PRIMARY KEY(source_file,source_row));''')
        if kind=='vmd':c.executescript('''CREATE TABLE IF NOT EXISTS compartments(id INTEGER PRIMARY KEY,external_id TEXT UNIQUE NOT NULL,objectid TEXT,source_layer TEXT,source_row INTEGER,kadastrs TEXT,kvart TEXT,nog TEXT,adm1 TEXT,adm2 TEXT,nog_plat REAL,geometry BLOB NOT NULL,properties TEXT NOT NULL,area_m2 REAL NOT NULL,importable INTEGER NOT NULL,repair TEXT,source_region TEXT,source_file TEXT,source_date TEXT,archive_sha256 TEXT,source_crs TEXT,native_geometry BLOB,original_geometry BLOB,geometry_valid INTEGER,source_verified INTEGER);
        CREATE VIRTUAL TABLE IF NOT EXISTS spatial_index USING rtree(id,min_lon,max_lon,min_lat,max_lat);
        CREATE VIRTUAL TABLE IF NOT EXISTS native_index USING rtree(id,min_x,max_x,min_y,max_y);''')
        else:c.executescript('''CREATE TABLE IF NOT EXISTS parcels(id INTEGER PRIMARY KEY,designation TEXT UNIQUE NOT NULL,geometry BLOB NOT NULL,native_geometry BLOB NOT NULL,original_geometry BLOB,source_crs TEXT,source_file TEXT,source_row INTEGER,source_attributes TEXT,source_region TEXT,source_date TEXT,archive_sha256 TEXT,area_m2 REAL,geometry_valid INTEGER,source_verified INTEGER);
        CREATE VIRTUAL TABLE IF NOT EXISTS spatial_index USING rtree(id,min_lon,max_lon,min_lat,max_lat);''')
        c.commit();return c
    def store_record(self,c,path,m,item,sha,row,props,original,error,native,valid,display,recovering=False):
        key=str(path.resolve())
        code=str(props.get('kadastrs' if item['kind']=='vmd' else 'CODE','')).strip();encoded=json.dumps(props,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        try:
            if error:raise ValueError(error)
            if not re.fullmatch('[0-9]{11}',code):raise ValueError('Cadastral source attribute is not exactly11 digits')
            display_repair=False
            if display is not None and not display.is_valid:
                display=surface(shapely.make_valid(display));display_repair=True
            if display is None or display.is_empty or not display.is_valid or display.geom_type not in {'Polygon','MultiPolygon'}:raise ValueError('No valid display polygon')
            w,s,e,n=display.bounds
            if not (19<=w<=e<=29 and 55<=s<=n<=59):raise ValueError('Bounds outside Latvia')
            source_verified=1;original_blob=original.wkb if m['source_crs']!='EPSG:10306' else None
            if item['kind']=='vmd':
                oid=str(props.get('objectid','')).strip()
                if not oid:raise ValueError('Missing source objectid')
                identity='VMD:'+path.stem+':'+oid;old=c.execute('SELECT id,native_geometry FROM compartments WHERE external_id=?',(identity,)).fetchone()
            else:
                identity=code;old=c.execute('SELECT id,native_geometry FROM parcels WHERE designation=?',(identity,)).fetchone()
            if old:
                identical=bytes(old[1])==native.wkb;c.execute('INSERT OR REPLACE INTO duplicate_sources VALUES(?,?,?,?,?,?)',(key,row,identity,int(identical),encoded,native.wkb))
                if not identical:c.execute('UPDATE '+table+' SET source_verified=0 WHERE id=?',(old[0],))
            elif item['kind']=='vmd':
                declared=props.get('nog_plat');declared=declared if isinstance(declared,(int,float)) and math.isfinite(declared) else None
                importable=valid and not display_repair and display.geom_type=='Polygon' and not len(display.interiors) and len(display.exterior.coords)<=10000
                values=(identity,oid,path.stem,row,code,str(props.get('kvart','')),str(props.get('nog','')),str(props.get('adm1','')),str(props.get('adm2','')),declared,display.wkb,encoded,native.area,int(importable),'Display normalization repair; original preserved' if display_repair else None if valid else 'Source invalid; display-only make_valid',item['name'],key,item['source_date'],sha,m['source_crs'],native.wkb,original_blob,int(valid),source_verified)
                cur=c.execute('INSERT INTO compartments(external_id,objectid,source_layer,source_row,kadastrs,kvart,nog,adm1,adm2,nog_plat,geometry,properties,area_m2,importable,repair,source_region,source_file,source_date,archive_sha256,source_crs,native_geometry,original_geometry,geometry_valid,source_verified) VALUES('+','.join('?' for _ in values)+')',values)
                a,b,d,e2=native.bounds;c.execute('INSERT INTO native_index VALUES(?,?,?,?,?)',(cur.lastrowid,a,d,b,e2));c.execute('INSERT INTO spatial_index VALUES(?,?,?,?,?)',(cur.lastrowid,w,e,s,n))
            else:
                cur=c.execute('INSERT INTO parcels(designation,geometry,native_geometry,original_geometry,source_crs,source_file,source_row,source_attributes,source_region,source_date,archive_sha256,area_m2,geometry_valid,source_verified) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(code,display.wkb,native.wkb,original_blob,m['source_crs'],key,row,encoded,item['name'],m['export_date'],sha,native.area,int(valid),source_verified));c.execute('INSERT INTO spatial_index VALUES(?,?,?,?,?)',(cur.lastrowid,w,e,s,n))
            if recovering:c.execute('DELETE FROM rejections WHERE source_file=? AND source_row=?',(key,row))
            return True
        except (ValueError,shapely.errors.GEOSException) as ex:
            c.execute('INSERT OR REPLACE INTO rejections VALUES(?,?,?,?)',(key,row,str(ex),encoded));return False

    def ingest(self,c,path,item,sha):
        m=metadata(path,item['kind']);key=str(path.resolve());existing=c.execute('SELECT last_row,complete FROM files WHERE path=?',(key,)).fetchone()
        if existing and existing[1]:return
        last=existing[0] if existing else 0;c.execute('INSERT OR IGNORE INTO files(path,total_rows,meta) VALUES(?,?,?)',(key,m['feature_count'],json.dumps({**m,'region':item['name'],'archive_sha256':sha,'source_url':item['url'],'licence':item['licence']})));c.commit()
        native_transform=Transformer.from_crs(m['source_crs'],10306,always_xy=True) if m['source_crs']!='EPSG:10306' else None
        def canonical(g):return shapely.transform(g,lambda a:np.column_stack(native_transform.transform(a[:,0],a[:,1]))) if native_transform else g
        table='compartments' if item['kind']=='vmd' else 'parcels';counter=0;started=time.monotonic()
        for row,props,original,error,native,valid,display in prepared_records(path,m,last+1,canonical):
            self.store_record(c,path,m,item,sha,row,props,original,error,native,valid,display)
            counter+=1;last=row
            if counter%1000==0 or row==m['feature_count']:
                c.execute('UPDATE files SET last_row=? WHERE path=?',(row,key));c.commit()
                if time.monotonic()-self.last_progress>10:
                    self.last_progress=time.monotonic();self.update(phase='indexing',kind=item['kind'],source=item['name'],file=path.name,row=row,total_rows=m['feature_count'],records_per_second=round(counter/max(.001,time.monotonic()-started)))
        c.execute('UPDATE files SET last_row=?,complete=1 WHERE path=?',(last,key));c.commit();c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    def retry_rejections(self,c,kind,sources):
        from services.geodata.forestry_io import original_geometry
        rows=c.execute('SELECT source_file,source_row,properties FROM rejections WHERE reason=?',('No valid display polygon',)).fetchall()
        if not rows:return
        self.update(phase='recovering_display_geometry',kind=kind,records_to_review=len(rows));recovered=0
        for key,row,encoded in rows:
            m=json.loads(c.execute('SELECT meta FROM files WHERE path=?',(key,)).fetchone()[0]);item=next(x for x in sources if x['kind']==kind and x['name']==m['region']);path=Path(key);original=original_geometry(path,row);native=original
            if m['source_crs']!='EPSG:10306':
                transformer=Transformer.from_crs(m['source_crs'],10306,always_xy=True)
                native=shapely.transform(original,lambda a:np.column_stack(transformer.transform(a[:,0],a[:,1])))
            valid=native.is_valid and not native.is_empty;display=shapely.transform(native if valid else surface(shapely.make_valid(native)),to_wgs84)
            recovered+=int(self.store_record(c,path,m,item,m['archive_sha256'],row,json.loads(encoded),original,None,native,valid,display,True))
        c.commit();self.update(phase='display_geometry_review_complete',kind=kind,records_recovered=recovered,records_remaining=len(rows)-recovered)

    def run(self):
        ready=self.root/'release.json'
        if ready.exists() and json.loads(ready.read_text()).get('status')=='READY':
            done=json.loads(ready.read_text());self.update(status='READY',phase='already_complete',version=done['version'],sources_validated=len(done['sources']),vmd_compartments=done['reports']['vmd']['indexed'],vzd_parcels=done['reports']['vzd']['indexed']);return
        sources=self.catalogue();self.update(phase='downloading',sources_total=len(sources))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(self.download,x):x for x in sources};done=0
            for f in concurrent.futures.as_completed(futures):f.result();done+=1;self.update(phase='downloading',sources_downloaded=done,sources_total=47,downloaded_bytes=sum(p.stat().st_size for p in (self.root/'downloads').glob('*') if p.is_file()))
        reports={};validated=[]
        for kind in ['vmd','vzd']:
            c=self.db(kind)
            for item in [s for s in sources if s['kind']==kind]:
                folder,sha=self.extract(item);paths=sorted(folder.rglob('nodala*.shp' if kind=='vmd' else 'KKParcel.shp'))
                if not paths:raise ValueError('Required source layers missing')
                for path in paths:self.ingest(c,path,item,sha)
                validated.append({**item,'archive_sha256':sha,'validated':True,'layers':len(paths)});atomic(self.root/'validated-sources.json',validated)
            self.retry_rejections(c,kind,sources)
            self.update(phase='final_validation',kind=kind)
            if kind=='vmd':c.executescript('CREATE INDEX IF NOT EXISTS cadastre_idx ON compartments(kadastrs,kvart,nog);CREATE INDEX IF NOT EXISTS location_idx ON compartments(adm1,adm2);CREATE INDEX IF NOT EXISTS objectid_idx ON compartments(objectid);')
            field='kadastrs' if kind=='vmd' else 'CODE'
            c.execute("CREATE INDEX IF NOT EXISTS rejection_cadastre_idx ON rejections(json_extract(properties,'$."+field+"'))")
            if kind=='vmd':c.execute('CREATE INDEX IF NOT EXISTS region_idx ON compartments(source_region,kadastrs)')
            table='compartments' if kind=='vmd' else 'parcels';count=c.execute('SELECT count(*) FROM '+table).fetchone()[0];total=c.execute('SELECT sum(total_rows) FROM files').fetchone()[0];reject=c.execute('SELECT count(*) FROM rejections').fetchone()[0];duplicates=c.execute('SELECT count(*) FROM duplicate_sources').fetchone()[0]
            if count+reject+duplicates!=total:raise ValueError(f'Record conservation failed {kind}: {count}+{reject}+{duplicates}!={total}')
            if c.execute('SELECT count(*) FROM files WHERE complete!=1').fetchone()[0]:raise ValueError('Incomplete source file')
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity failure')
            r={'indexed':count,'total_source_features':total,'failed':reject,'duplicate_source_records':duplicates,'conflicts':c.execute('SELECT count(*) FROM duplicate_sources WHERE identical=0').fetchone()[0],'source_crs':'EPSG:10306','output_crs':'EPSG:4326','layers':[json.loads(x[0]) for x in c.execute('SELECT meta FROM files')],'repaired':c.execute('SELECT count(*) FROM '+table+' WHERE geometry_valid=0').fetchone()[0]}
            r['valid']=count-r['repaired'];r['importable']=c.execute('SELECT count(*) FROM compartments WHERE importable=1').fetchone()[0] if kind=='vmd' else count
            ext=c.execute('SELECT min(min_lon),min(min_lat),max(max_lon),max(max_lat) FROM spatial_index').fetchone();r['extent']=list(ext);reports[kind]=r;c.execute('ANALYZE');c.commit();c.close()
        version=hashlib.sha256((VERSION+json.dumps([(s['id'],s['archive_sha256']) for s in validated])).encode()).hexdigest()
        for kind,r in reports.items():
            r.update({'dataset_version':version,'nationwide':True,'source_archive':'official-national-manifest','archive_sha256':version,'regions':[x['name'] for x in sources if x['kind']==kind]})
            with sqlite3.connect(self.root/('compartments.sqlite' if kind=='vmd' else 'parcels.sqlite')) as c:c.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('report',json.dumps(r,ensure_ascii=False)))
            atomic(self.root/(kind+'-report.json'),r)
        manifest={'schema':1,'status':'READY','version':version,'created_at':stamp(),'root':str(self.root),'forest_db':str(self.root/'compartments.sqlite'),'parcel_db':str(self.root/'parcels.sqlite'),'sources':validated,'reports':reports,'licences':{'vmd':'CC0-1.0','vzd':'CC-BY-4.0'},'original_geometry_preserved':True}
        atomic(self.root/'release.json',manifest);self.update(status='READY',phase='complete',version=version,vmd_compartments=reports['vmd']['indexed'],vzd_parcels=reports['vzd']['indexed'],sources_validated=len(validated))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);args=p.parse_args();job=Job(args.root)
    try:job.run()
    except BaseException as ex:job.update(status='ERROR',phase='failed',error_type=type(ex).__name__,error=str(ex));raise
