"""Read-only indexed forestry catalogue, exact territory queries and safe imports."""
import json,math,re,sqlite3,time,os
from contextlib import closing
from pathlib import Path
import shapely
from shapely.geometry import shape,mapping,box,Polygon
from shapely.ops import unary_union
import database
from . import store
from .base import GeodataError
from .forestry_io import equal_area,to_wgs84

DATASET=Path(os.environ.get('VMD_DATASET_PATH',str(Path(__file__).resolve().parents[2]/'data/vmd/compartments.sqlite')))
_INITIAL_DATASET=DATASET
PROVIDER='VMD_OPEN_DATA'
SOURCE_ROOT=Path(__file__).resolve().parents[2]/'data/vmd/source'
MAX_CANDIDATES=50000


class DatasetError(ValueError):
    def __init__(self,message,status=422):super().__init__(message);self.status=status


def _national_enabled():
    from . import nationwide
    return DATASET==_INITIAL_DATASET and nationwide.configured()

def connect():
    from . import nationwide
    path=Path(nationwide.release()['forest_db']) if _national_enabled() else DATASET
    if not path.is_file():raise DatasetError('VMD local dataset is not available; build the catalogue first',503)
    c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=5);c.row_factory=sqlite3.Row;return c


def report(c=None):
    if c is None:
        with closing(connect()) as c:return report(c)
    row=c.execute("SELECT value FROM metadata WHERE key='report'").fetchone()
    if not row:raise DatasetError('VMD dataset metadata is unavailable',503)
    return json.loads(row[0])


def status():
    if _national_enabled():
        from . import nationwide
        return nationwide.status()
    r=report()
    return {'name':'VMD Forest Compartments','source':PROVIDER,'status':'AVAILABLE','crs':'EPSG:4326','source_crs':r['source_crs'],
            'feature_count':r['indexed'],'extent':r['extent'],'dataset_version':r['dataset_version'],
            'source_layers':[{'name':l['layer'],'features':l['feature_count']} for l in r['layers']],
            'repaired':r['repaired'],'failed':r['failed'],'importable_count':r['importable'],
            'coverage':'Dati aptver piegādāto Centra reģiona arhīvu, nevis visu Latviju.'}


def territory_geometry(data):
    if not isinstance(data,dict):raise DatasetError('Client territory must be GeoJSON')
    crs=data.get('crs');crs_props=crs.get('properties') if isinstance(crs,dict) else None
    name=crs_props.get('name') if isinstance(crs_props,dict) else None
    if crs is not None and (not isinstance(name,str) or name not in {'EPSG:4326','urn:ogc:def:crs:EPSG::4326','CRS:84','urn:ogc:def:crs:OGC:1.3:CRS84','EPSG:10306','EPSG:3059'}):raise DatasetError('Territory CRS is unsupported; upload EPSG:4326 GeoJSON')
    if data.get('type')=='FeatureCollection':
        features=data.get('features');
        if not isinstance(features,list) or not 1<=len(features)<=100:raise DatasetError('Upload 1–100 territory polygons')
        items=[f.get('geometry') for f in features if isinstance(f,dict)]
        if len(items)!=len(features):raise DatasetError('Invalid territory features')
    elif data.get('type')=='Feature':items=[data.get('geometry')]
    else:items=[data]
    count=0
    def coordinates(v,depth=0):
        nonlocal count
        if not isinstance(v,(list,tuple)) or not v or depth>5:raise DatasetError('Invalid territory coordinates')
        if isinstance(v[0],(int,float)):
            count+=1
            if count>20000 or len(v)!=2 or any(isinstance(x,bool) or not isinstance(x,(float,int)) or not (-1e8<=x<=1e8) for x in v):raise DatasetError('Territory exceeds 20,000 vertices or has invalid coordinates')
        else:
            if isinstance(v[0],(list,tuple)) and v[0] and isinstance(v[0][0],(int,float)) and (len(v)<4 or v[0]!=v[-1]):raise DatasetError('Territory polygon rings must be closed with at least four positions')
            for child in v:coordinates(child,depth+1)
    parts=[]
    for item in items:
        if not isinstance(item,dict) or not isinstance(item.get('type'),str) or item.get('type') not in {'Polygon','MultiPolygon'}:raise DatasetError('Territory must be Polygon or MultiPolygon')
        coordinates(item.get('coordinates'))
        try:g=shape(item)
        except (ValueError,TypeError) as exc:raise DatasetError('Invalid territory geometry') from exc
        if g.is_empty or not g.is_valid:raise DatasetError('Client territory is empty or invalid; correct the boundary')
        if name=='EPSG:10306':g=shapely.transform(g,to_wgs84)
        elif name=='EPSG:3059':
            from pyproj import Transformer
            from shapely.ops import transform
            g=transform(Transformer.from_crs('EPSG:3059','EPSG:4326',always_xy=True).transform,g)
        parts.append(g)
    g=unary_union(parts)
    if not g.is_valid or g.is_empty:raise DatasetError('Invalid combined client territory')
    w,s,e,n=g.bounds
    if not(19<=w<e<=29 and 55<=s<n<=59):raise DatasetError('Client territory must be in Latvia with finite EPSG:4326 coordinates')
    area=shapely.transform(g,equal_area).area/10000
    if area>250000:raise DatasetError('Territory exceeds 250,000 ha; split it into smaller search areas',413)
    return g,area


def _app_connection(readonly=True):
    if readonly:c=sqlite3.connect('file:'+str(Path(database.DB_NAME).resolve())+'?mode=ro',uri=True,timeout=5)
    else:c=store.connect()
    c.row_factory=sqlite3.Row
    if readonly:
        from services import review_mode
        review_mode.apply_sector_exclusion(c)   # review-mode display exclusion; no-op otherwise
    return c


def _existing(c,row,g):
    # New catalogue ID is authoritative; a stale mapping never permits overwrite.
    found=c.execute('''SELECT s.id,s.name,g.sector_id FROM geodata_sources g LEFT JOIN sectors s ON s.id=g.sector_id
        WHERE g.organization_id=1 AND g.provider IN ('VMD_OPEN_DATA','VMD') AND g.source_feature_id=?''',(row['external_id'],)).fetchone()
    if found:return {'id':found['id'],'name':found['name'],'stale':found['id'] is None}
    # Preserve the earlier explicitly imported real compartment without migrating
    # or rewriting its source metadata. Require identity AND matching geometry.
    cad,q,n=row['kadastrs'],row['kvart'],row['nog']
    if all(re.fullmatch(r'[0-9]+',str(v or '')) for v in (cad,q,n)):
        legacy='VMD-'+cad+'-'+str(int(q))+'-'+str(int(n))
        previous=c.execute('''SELECT s.id,s.name,s.boundary_json FROM geodata_sources p JOIN sectors s ON s.id=p.sector_id
            WHERE p.organization_id=1 AND p.provider='VMD_LOCAL' AND p.source_feature_id=?''',(legacy,)).fetchone()
        if previous:
            try:
                old=Polygon([(p[1],p[0]) for p in json.loads(previous['boundary_json'])])
                if old.is_valid and old.hausdorff_distance(g)<2e-8 and abs(old.area-g.area)/max(g.area,1e-20)<1e-4:return {'id':previous['id'],'name':previous['name'],'stale':False}
            except (ValueError,TypeError,IndexError):pass
    return None


def _area_ha(row):
    declared=row['nog_plat']
    return declared if isinstance(declared,(int,float)) and math.isfinite(declared) and declared>0 else row['area_m2']/10000


def _feature(c,row,ratio=None,inside=None,app=None):
    g=shapely.from_wkb(row['geometry']);props=json.loads(row['properties'])
    existing=_existing(app,row,g) if app else None
    props.update({'external_id':row['external_id'],'source':PROVIDER,'source_layer':row['source_layer'],'source_record':row['source_row'],
        'area_ha':_area_ha(row),
        'intersection_ratio':ratio,'fully_inside':inside,'geometry_repaired':bool(row['repair']),
        'importable':bool(row['importable']) and not existing,
        'import_status':'ALREADY IMPORTED' if existing and not existing['stale'] else ('REVIEW REQUIRED' if existing else ('READY' if row['importable'] else 'UNSUPPORTED GEOMETRY')),
        'sector':{'id':existing['id'],'name':existing['name']} if existing and not existing['stale'] else None})
    return {'type':'Feature','id':row['external_id'],'geometry':json.loads(shapely.to_geojson(g)),'properties':props}


CADASTRAL_FIELD='kadastrs'
FILTER_FIELDS=('kadastrs','kvart','nog','adm1','adm2')


def normalize_cadastral(value,match='exact'):
    """Normalize display separators only; preserve all digits and leading zeros.

    kadastrs is the VMD land-unit designation, never a property/OBJECTID search.
    An eleven-digit input is always exact, even when prefix mode was selected.
    """
    if match not in {'exact','prefix'}:raise DatasetError('Nederīgs kadastra meklēšanas režīms')
    text=str(value).strip()
    if re.fullmatch(r'[0-9]{4}[ \u00a0-][0-9]{3}[ \u00a0-][0-9]{4}',text):
        text=re.sub(r'[ \u00a0-]','',text)
    if re.fullmatch(r'[0-9]{11}',text):return text,'exact'
    if match=='prefix' and re.fullmatch(r'[0-9]{4,10}',text):return text,'prefix'
    if match=='prefix':raise DatasetError('Prefiksa meklēšanai ievadiet 4–10 ciparus; pilns apzīmējums sastāv no 11 cipariem')
    raise DatasetError('Precīzai meklēšanai ievadiet 11 ciparu zemes vienības kadastra apzīmējumu; daļējai meklēšanai izvēlieties prefiksa režīmu')


def search(territory=None,bbox=None,mode='inside',min_overlap=0,limit=250,offset=0,filters=None):
    start=time.monotonic();filters=filters or {};client=None;territory_area=None
    if not 1<=limit<=1000 or not 0<=offset<=50000 or not 0<=min_overlap<=100:raise DatasetError('Invalid result limit, offset or overlap')
    if mode not in {'inside','intersects'}:raise DatasetError('Invalid spatial matching mode')
    if territory is not None:client,territory_area=territory_geometry(territory);bbox=client.bounds
    if bbox is None and not any(filters.get(key) for key in FILTER_FIELDS):raise DatasetError('Define a client territory, provide a bbox, or search by an identifier')
    params=[];clauses=[]
    if bbox is not None:
        if len(bbox)!=4 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in bbox):raise DatasetError('Invalid bbox')
        w,s,e,n=bbox
        if not(19<=w<e<=29 and 55<=s<n<=59):raise DatasetError('BBox must be in Latvia (EPSG:4326)')
        if territory is None and ((e-w)*(n-s)>.5 or e-w>2 or n-s>2):raise DatasetError('Map area too large; zoom in or search by client territory',413)
        clauses+=['r.min_lon<=?','r.max_lon>=?','r.min_lat<=?','r.max_lat>=?'];params.extend([e,w,n,s])
        if client is None:client=box(w,s,e,n)
    cadastral_search=None
    if filters.get('kadastrs'):
        designation,matching=normalize_cadastral(filters['kadastrs'],filters.get('kadastrs_match','exact'))
        cadastral_search={'field':CADASTRAL_FIELD,'value':designation,'match':matching}
        if matching=='exact':clauses.append('c.kadastrs=?');params.append(designation)
        else:
            # An ASCII-digit range is an indexed prefix search, never substring LIKE.
            clauses.extend(['c.kadastrs>=?','c.kadastrs<?']);params.extend([designation,designation+':'])
    for key in ('kvart','nog','adm1','adm2'):
        if filters.get(key):clauses.append('c.'+key+'=?');params.append(str(filters[key]).strip())
    where=' AND '.join(clauses) or '1=1'
    join='compartments c JOIN spatial_index r ON c.id=r.id' if bbox is not None else 'compartments c'
    with closing(connect()) as c,closing(_app_connection()) as app:
        version=report(c)['dataset_version']
        count=c.execute('SELECT count(*) FROM '+join+' WHERE '+where,params).fetchone()[0]
        if count>MAX_CANDIDATES:raise DatasetError('Too many candidate compartments; use a smaller territory or narrower identifiers',413)
        sql='SELECT c.id,c.geometry,c.area_m2,c.nog_plat FROM '+join+' WHERE '+where+' ORDER BY c.id'
        selected=[];found=inside_count=0;total_area=0;matched_bounds=None
        for row in c.execute(sql,params):
            if time.monotonic()-start>20:raise DatasetError('Spatial query exceeded its time limit; narrow the search',413)
            g=shapely.from_wkb(row['geometry']);inside=client.covers(g) if client is not None else None
            if client is not None:
                if mode=='inside' and territory is not None and not inside:continue
                if not g.intersects(client):continue
                ratio=1.0 if inside else min(1.,max(0.,shapely.transform(g.intersection(client),equal_area).area/row['area_m2']))
                if ratio+1e-10<min_overlap/100:continue
            else:ratio=None
            bounds=g.bounds
            matched_bounds=[min(matched_bounds[0],bounds[0]),min(matched_bounds[1],bounds[1]),max(matched_bounds[2],bounds[2]),max(matched_bounds[3],bounds[3])] if matched_bounds else list(bounds)
            found+=1;inside_count+=int(bool(inside));total_area+=_area_ha(row)
            if offset<found<=offset+limit:selected.append((row['id'],ratio,inside))
        features=[]
        for ident,ratio,inside in selected:
            row=c.execute('SELECT * FROM compartments WHERE id=?',(ident,)).fetchone();features.append(_feature(c,row,ratio,inside,app))
    return {'type':'FeatureCollection','features':features,'dataset_version':version,
            'summary':{'bounds':matched_bounds,'cadastral_search':cadastral_search,'found':found,'returned':len(features),'total_compartment_area_ha':round(total_area,4),'territory_area_ha':territory_area,
                       'fully_inside':inside_count,'boundary_intersections':found-inside_count if client is not None else None,'candidate_count':count,
                       'offset':offset,'limit':limit,'has_more':offset+len(features)<found,'elapsed_seconds':round(time.monotonic()-start,3)}}


def _source_association(row,source_report,designation):
    """Validate native DBF attributes separately from geometry and map position."""
    if 'source_verified' in row.keys():
        from . import nationwide
        return nationwide.source_association(row,designation)
    from .forestry_io import inspect
    layers=[layer for layer in source_report.get('layers',[]) if layer.get('layer')==row['source_layer'] and layer.get('path')]
    result={'status':'unverified','classification':'unverified','source_field':'kadastrs','requested_designation':designation,'source_designation':None,'source_feature_id':row['external_id'],'cadastral_boundary_verified':False}
    if not layers:return {**result,'reason':'Nav pieejama sākotnējā VMD DBF atribūtu izcelsme'}
    path=Path(layers[0]['path']).resolve();root=SOURCE_ROOT.resolve()
    if not path.is_relative_to(root):return {**result,'reason':'Avota fails neatrodas pārbaudītajā VMD glabātuvē'}
    try:
        meta=inspect(path);index=int(row['source_row'])
        if not 1<=index<=meta['feature_count']:raise ValueError('Invalid source row')
        with path.with_suffix('.dbf').open('rb') as dbf:
            dbf.seek(meta['header_bytes']+(index-1)*meta['record_bytes']);raw=dbf.read(meta['record_bytes'])
        if len(raw)!=meta['record_bytes'] or raw[:1]!=b' ':raise ValueError('Invalid DBF record')
        fields={f['name']:f for f in meta['fields']}
        def value(key):
            field=fields[key];return raw[field['offset']:field['offset']+field['length']].decode('utf-8').strip(' \0')
        source=value('kadastrs');result['source_designation']=source
        props=json.loads(row['properties'])
        verified=(source==designation==row['kadastrs']==props.get('kadastrs') and value('objectid')==str(row['objectid']) and value('kvart')==str(row['kvart']) and value('nog')==str(row['nog']))
        if not verified:return {**result,'reason':'Sākotnējais VMD atribūts vai ieraksta identitāte neatbilst pieprasījumam'}
        return {**result,'status':'verified_source_attribute','classification':'authoritative_vmd_attribute','source_file':path.name,'source_record':index,'reason':'Precīzi pārbaudīts sākotnējais VMD kadastrs; tā nav neatkarīga VZD robežu pārbaude'}
    except (OSError,ValueError,KeyError,UnicodeError) as error:
        return {**result,'reason':'Nav iespējams pārbaudīt sākotnējo VMD kadastra atribūtu'}


def verified_cadastral_search(designation,limit=100,offset=0,review_offset=0):
    if _national_enabled():
        from . import nationwide
        return nationwide.search(designation,limit,offset,review_offset)
    designation,matching=normalize_cadastral(designation,'exact')
    result=search(filters={'kadastrs':designation},limit=limit,offset=offset)
    with closing(connect()) as c:
        source_report=report(c)
        rows=c.execute('SELECT * FROM compartments WHERE kadastrs=? ORDER BY id',(designation,)).fetchall()
        associations={row['external_id']:_source_association(row,source_report,designation) for row in rows}
    unverified=[v for v in associations.values() if v['status']!='verified_source_attribute']
    verification={'status':'unverified' if unverified else 'verified_source_attribute' if rows else 'not_found',
                  'classification':'unverified' if unverified or not rows else 'authoritative_vmd_attribute',
                  'source_field':'kadastrs','requested_designation':designation,'candidate_count':len(rows),
                  'verified_count':len(rows)-len(unverified),'unverified_count':len(unverified),'derived_count':0,
                  'cadastral_boundary_verified':False}
    result['cadastral_verification']=verification
    result['coverage']={'description':status()['coverage'],'source_records_found':len(rows),'complete_national_coverage':False,'extent':source_report.get('extent'),'status':'has_exact_records' if rows else 'no_exact_records'}
    if not rows:result['search_message']='Šajā VMD datu kopā precīzs kadastra apzīmējums nav atrasts. Dati aptver Centra reģiona arhīvu, nevis visu Latviju. Tas neapliecina zemes vienības vai meža neesamību.'
    from . import cadastral_authority
    result['cadastral_validation']=cadastral_authority.verify(designation)
    if not rows and result['cadastral_validation'].get('land_unit_exists'):
        result['search_message']='VZD zemes vienība ir pārbaudīta, bet šajā VMD datu kopā tai nav atrasts neviens nogabals ar precīzu kadastra apzīmējumu. Tas neapliecina meža neesamību. Pieejams Centra reģiona arhīvs, nevis visu Latviju aptveroši dati.'
        # An authoritative parcel outside the complete source extent is a coverage
        # diagnostic only. It never supplies or infers VMD associations.
        extent=source_report.get('extent');parcel=result['cadastral_validation'].get('land_unit_geometry')
        if extent and parcel and box(*extent).disjoint(shape(parcel)):
            result['coverage']['status']='outside_loaded_extent'
            result['search_message']='VZD zemes vienība ir pārbaudīta un atrodas ārpus ielādētās VMD datu kopas telpiskā aptvēruma. Nepieciešami attiecīgā reģiona VMD avota dati. Tuvumā esoši nogabali netiek piedāvāti kā precīza atbilstība.'
    if unverified:
        # Fail closed: never draw a partly/unverified collection as exact land-unit results.
        result['features']=[];result['summary'].update({'found':0,'returned':0,'has_more':False,'bounds':None})
        result['verification_message']='Kadastra saistība nav pārbaudīta. Nepieciešams sākotnējais VMD DBF ar uzticamu kadastrs un avota ieraksta identitāti.'
    else:
        for feature in result['features']:
            feature['properties']['cadastral_association']=associations[feature['id']]
            feature['properties']['geometry_valid']=bool(shape(feature['geometry']).is_valid)
            native_row=next(row for row in rows if row['external_id']==feature['id'])
            validation=cadastral_authority.verify(designation,_original_geometry(native_row,source_report))
            feature['properties']['cadastral_validation']=validation
            feature['properties']['importable']=bool(feature['properties']['importable'] and validation['registration_allowed'])
    return result


def matching_selection(geometry=None,bbox=None,mode='intersects',min_overlap=0,filters=None,dataset_version=None):
    """Select the complete bounded search, never silently just its first page."""
    result=search(territory=geometry,bbox=bbox,mode=mode,min_overlap=min_overlap,filters=filters,limit=100)
    if dataset_version and result['dataset_version']!=dataset_version:raise DatasetError('Dataset version changed; repeat your search',409)
    if result['summary']['found']>100:raise DatasetError('Visu rezultātu atlasē atļauti līdz 100 nogabaliem; sašauriniet meklēšanu vai atlasiet vajadzīgos pa lapām',413)
    result['selection_scope']='matching'
    result['selected_count']=sum(bool(f['properties']['importable']) for f in result['features'])
    result['excluded_count']=len(result['features'])-result['selected_count']
    return result


def _original_geometry(row,source_report):
    if 'native_geometry' in row.keys():
        from . import nationwide
        return nationwide.original(row)
    from .forestry_io import original_geometry
    layers=[layer for layer in source_report.get('layers',[]) if layer.get('layer')==row['source_layer'] and layer.get('path')]
    if not layers:
        # Unit-test catalogues may contain normalized fixtures only; never label those original.
        return None
    expected=(Path(__file__).resolve().parents[2]/'data/vmd/source').resolve()
    path=Path(layers[0]['path']).resolve()
    if not path.is_relative_to(expected):raise DatasetError('Source geometry path is outside the dataset storage',503)
    try:return mapping(original_geometry(path,int(row['source_row'])))
    except (OSError,ValueError) as exc:raise DatasetError('Original source geometry is unavailable; import stopped',503) from exc


def selected_import(feature_ids,version,actor,dry_run=True,territory_id=None,responsible_first_name='',responsible_last_name='',sector_name=None,requested_designation=None):
    if not 1<=len(feature_ids)<=100 or len(set(feature_ids))!=len(feature_ids):raise DatasetError('Select 1–100 distinct compartments per import')
    if _national_enabled() and (not isinstance(requested_designation,str) or not re.fullmatch('[0-9]{11}',requested_designation)):raise DatasetError('Valsts reģistrācijai jānorāda precīzais kadastra apzīmējums')
    name_input=sector_name.strip() if isinstance(sector_name,str) else ''
    if not name_input or len(name_input)>120 or any(ord(ch)<32 or ch in '/\\' for ch in name_input):raise DatasetError('Norādiet sektora nosaukumu (1–120 rakstzīmes, bez slīpsvītrām un vadības rakstzīmēm)')
    from .registration_identity import context
    identity=context(actor)
    if territory_id:get_territory(territory_id,actor)  # Existing owner-scoped compatibility; never ownership input.
    first=responsible_first_name.strip();last=responsible_last_name.strip()
    if len(first)>100 or len(last)>100:raise DatasetError('Atbildīgās personas vārds vai uzvārds ir pārāk garš')
    results=[]
    with closing(connect()) as src,closing(_app_connection(dry_run)) as app:
        source_report=report(src)
        if source_report['dataset_version']!=version:raise DatasetError('Dataset version changed; repeat your search',409)
        if not dry_run:app.execute('BEGIN IMMEDIATE')
        try:
            for fid in feature_ids:
                result={'external_id':fid};row=src.execute('SELECT * FROM compartments WHERE external_id=?',(fid,)).fetchone()
                if not row:results.append({**result,'status':'failed','reason':'Compartment is not in the production dataset'});continue
                if requested_designation is not None and row['kadastrs']!=requested_designation:
                    results.append({**result,'status':'failed','reason':'Nogabala avota kadastra apzīmējums neatbilst pārbaudītajai atlasei'});continue
                association=_source_association(row,source_report,row['kadastrs'])
                result['cadastral_association']=association
                if association['status']!='verified_source_attribute':results.append({**result,'status':'failed','reason':'Kadastra saistība nav pārbaudīta; reģistrācija nav atļauta'});continue
                from . import cadastral_authority
                validation=cadastral_authority.verify(row['kadastrs'],_original_geometry(row,source_report),**({'source_crs':row['source_crs']} if 'source_crs' in row.keys() else {}))
                result['cadastral_validation']=validation
                if not validation['registration_allowed']:
                    results.append({**result,'status':'failed','reason':validation.get('message','Kadastra dati nav pārbaudīti')});continue
                g=shapely.from_wkb(row['geometry']);result.update({'area_ha':_area_ha(row),'geometry_valid':bool(g.is_valid),'geometry_repaired':bool(row['repair']),'kadastrs':row['kadastrs'],'kvart':row['kvart'],'nog':row['nog'],'source_layer':row['source_layer']});existing=_existing(app,row,g)
                if existing:
                    results.append({**result,'status':'failed' if existing['stale'] else 'already_exists','id':existing['id'],'name':existing['name']});continue
                if 'native_geometry' in row.keys() and row['repair']:
                    results.append({**result,'status':'failed','reason':'Avota vai attēlojuma ģeometrijai nepieciešama manuāla pārbaude'});continue
                if not row['importable']:results.append({**result,'status':'failed','reason':'Current sectors require one simple Polygon ring; MultiPolygon/holes are not flattened'});continue
                feature=_feature(src,row);props=feature['properties'];feature['id']=fid
                try:boundary=store.normalize(feature)
                except GeodataError as exc:results.append({**result,'status':'failed','reason':str(exc)});continue
                safe=lambda v:re.sub(r'[^\w .:\-]','_',str(v or '?'))[:100]
                name=name_input if len(feature_ids)==1 else f"{name_input} — K{safe(row['kvart'])} N{safe(row['nog'])} [{safe(row['source_layer'])}:{safe(row['objectid'])}]"
                if app.execute('SELECT 1 FROM sectors WHERE name=?',(name,)).fetchone():results.append({**result,'status':'failed','reason':'A sector with this name already exists; no overwrite allowed'});continue
                if dry_run:results.append({**result,'status':'ready','name':name});continue
                encoded=json.dumps(boundary,allow_nan=False);lat,lon=database.calc_centroid(boundary);now=store.stamp()
                national_provenance={}
                if 'native_geometry' in row.keys():
                    from . import nationwide
                    national_provenance=nationwide.source_reference(row)
                metadata={'boundary_source_type':'external_geodata','provider':PROVIDER,'source_layer':row['source_layer'],'source_feature_id':fid,
                    'source_dataset_title':'VMD Meža valsts reģistrs — '+(row['source_region'] if 'source_region' in row.keys() else 'Centra reģions'),'source_attribution':'Valsts meža dienests — Meža valsts reģistra atvērtie dati (CC0 1.0)','source_properties':json.dumps({**json.loads(row['properties']),
                    **national_provenance,'external_id':fid,'registration_sector_name':name_input,'sector_name':name,'source':PROVIDER,'source_archive':row['source_region'] if 'source_region' in row.keys() else 'centra_data.zip','source_archive_sha256':row['archive_sha256'] if 'archive_sha256' in row.keys() else source_report.get('archive_sha256'),'dataset_version':version,'source_record':row['source_row'],'geometry_crs':'EPSG:4326','original_crs':row['source_crs'] if 'source_crs' in row.keys() else 'EPSG:10306','geometry_repair':row['repair'],'normalized_geometry':mapping(g),'original_source_geometry':_original_geometry(row,source_report),'retrieved_at':now,'authenticated_owner':actor,'organization_id':identity['organization_id'],'organization_name':identity['organization_name'],'created_by_user_id':identity['user_id'],'created_by_account':actor,'identity_type':identity['identity_type'],'responsible_first_name':first,'responsible_last_name':last,'cadastral_association':association,'cadastral_validation':validation,'vzd_geometry_reference':validation.get('reference'),'cadastral_designation':row['kadastrs'],'source_region':row['source_region'] if 'source_region' in row.keys() else 'Centra','territory_id':territory_id},ensure_ascii=False,allow_nan=False),
                    'source_crs':row['source_crs'] if 'source_crs' in row.keys() else 'EPSG:10306','imported_at':now,'source_last_checked_at':now}
                app.execute('SAVEPOINT compartment_import')
                try:
                    cur=app.execute('''INSERT INTO sectors(name,contractor,status,approved_volume,map_url,image_path,boundary_json,center_lat,center_lon,area_ha,color,created_at,updated_at,data_origin,organization_id,created_by_user_id,created_by_account,responsible_first_name,responsible_last_name)
                        VALUES(?,?,'Planned','','','',?,?,?,?,'#4b9d54',?,?,'REAL',?,?,?,?,?)''',(name,'',encoded,lat,lon,props['area_ha'],now,now,identity['organization_id'],identity['user_id'],actor,first,last))
                    sector={'id':cur.lastrowid,'name':name};columns=list(metadata)
                    app.execute('INSERT INTO geodata_sources(sector_id,sector,organization_id,'+','.join(columns)+') VALUES('+','.join('?' for _ in range(len(columns)+3))+')',[sector['id'],name,1]+[metadata[k] for k in columns])
                    store._history(app,sector,actor,'IMPORT_VMD_OPEN_DATA',None,encoded,metadata);app.execute('RELEASE compartment_import')
                    results.append({**result,'status':'imported',**sector})
                except sqlite3.IntegrityError:
                    app.execute('ROLLBACK TO compartment_import');app.execute('RELEASE compartment_import');results.append({**result,'status':'failed','reason':'Source identity conflict; nothing overwritten'})
            if not dry_run:app.commit()
        except BaseException:
            if not dry_run:app.rollback()
            raise
    return {'sector_name':name_input,'registration_identity':identity,'responsible_person':{'first_name':first,'last_name':last},'target_client':{'id':str(identity['organization_id']),'name':identity['organization_name'],'account':actor},'total_area_ha':round(sum(r.get('area_ha',0) for r in results),4),'valid_geometry_count':sum(bool(r.get('geometry_valid')) for r in results),'requested':len(feature_ids),'dry_run':dry_run,'imported':sum(r['status']=='imported' for r in results),'already_exists':sum(r['status']=='already_exists' for r in results),
            'failed':sum(r['status']=='failed' for r in results),'would_import':sum(r['status']=='ready' for r in results),'results':results}

# Client onboarding boundaries are separate from both the immutable catalogue
# and operational sectors. Only an explicit save action writes this sidecar.
TERRITORIES=Path(database.DB_NAME).resolve().parent/'vmd/client_territories.sqlite'

def save_territory(geometry,name,client_name,source,owner,client_id=None):
    import uuid,os
    from datetime import datetime,timezone
    if not name.strip():raise DatasetError('Enter a territory name before saving')
    g,area=territory_geometry(geometry);ident=str(uuid.uuid4());created=datetime.now(timezone.utc).isoformat()
    TERRITORIES.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(TERRITORIES,timeout=5)) as c,c:
        os.chmod(TERRITORIES,0o600)
        c.execute('''CREATE TABLE IF NOT EXISTS territories(id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,client_name TEXT,source TEXT NOT NULL,geometry TEXT NOT NULL,area_ha REAL NOT NULL,created_at TEXT NOT NULL)''')
        columns={r[1] for r in c.execute('PRAGMA table_info(territories)')}
        if 'client_id' not in columns:c.execute("ALTER TABLE territories ADD COLUMN client_id TEXT")
        c.execute('INSERT INTO territories(id,owner,name,client_name,source,geometry,area_ha,created_at,client_id) VALUES(?,?,?,?,?,?,?,?,?)',(ident,owner,name.strip(),client_name.strip(),source,json.dumps(mapping(g)),area,created,client_id or owner))
    return {'id':ident,'name':name.strip(),'client_name':client_name.strip(),'source':source,'area_ha':area,'created_at':created,'client_id':client_id or owner,'crs':'EPSG:4326','is_sector':False}


def list_territories(owner):
    if not TERRITORIES.exists():return []
    with closing(sqlite3.connect('file:'+str(TERRITORIES)+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        return [dict(r) for r in c.execute('SELECT id,name,client_name,source,area_ha,created_at FROM territories WHERE owner=? ORDER BY created_at DESC LIMIT 200',(owner,))]


def get_territory(ident,owner):
    if not TERRITORIES.exists():raise DatasetError('Client territory not found',404)
    with closing(sqlite3.connect('file:'+str(TERRITORIES)+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row;row=c.execute('SELECT * FROM territories WHERE id=? AND owner=?',(ident,owner)).fetchone()
    if not row:raise DatasetError('Client territory not found',404)
    props={k:row[k] for k in ['id','name','client_name','source','area_ha','created_at']}
    props.update({'client_id':row['client_id'] if 'client_id' in row.keys() else owner,'crs':'EPSG:4326'})
    return {'type':'Feature','geometry':json.loads(row['geometry']),'properties':{**props,'is_sector':False}}
