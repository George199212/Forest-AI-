"""Read-only, versioned national geodata. No operational database migrations.
Exact source attributes and spatial candidates remain independent evidence sets.
"""
import hashlib,json,logging,os,re,sqlite3,time
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import shapely
from shapely.geometry import shape,mapping
BASE=Path(__file__).resolve().parents[2]
ACTIVE=BASE/'data/geodata/nationwide/active.json'
log=logging.getLogger(__name__)
STATES={'CADASTRAL_PARCEL_FOUND','PARCEL_NOT_FOUND','VMD_MATCHES_FOUND','NO_VMD_RECORDS','SPATIAL_REVIEW_REQUIRED','DATASET_NOT_READY','SOURCE_ERROR'}
class SourceError(ValueError):
    def __init__(self,message,state='SOURCE_ERROR'):super().__init__(message);self.state=state

def manifest_path():
    value=os.environ.get('FOREST_GEODATA_MANIFEST')
    if value=='disabled':return None
    if value:return Path(value)
    return ACTIVE if ACTIVE.exists() else None

def configured():return manifest_path() is not None
@lru_cache(maxsize=4)
def _manifest(path,mtime,size):
    data=json.loads(Path(path).read_text())
    if data.get('schema')!=1:raise SourceError('Neatbalstīta valsts datu manifesta versija')
    if data.get('status')!='READY':raise SourceError('Valsts datu kopu indeksēšana vēl nav pabeigta','DATASET_NOT_READY')
    sources=data.get('sources',[])
    if len({x.get('id') for x in sources})!=47:raise SourceError('Valsts avotu saraksts nav unikāls','DATASET_NOT_READY')
    if len(sources)!=47 or sum(x.get('kind')=='vmd' and x.get('validated') is True for x in sources)!=5 or sum(x.get('kind')=='vzd' and x.get('validated') is True for x in sources)!=42:raise SourceError('Valsts avotu validācija nav pilnīga','DATASET_NOT_READY')
    if any(not Path(data.get(k,'')).is_file() for k in ['forest_db','parcel_db']):raise SourceError('Valsts telpiskā indeksa fails nav pieejams')
    return data

def release():
    path=manifest_path()
    if path is None:raise SourceError('Valsts datu indekss nav aktivizēts','DATASET_NOT_READY')
    try:
        stat=path.stat();return _manifest(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
    except FileNotFoundError:raise SourceError('Valsts datu indekss vēl nav gatavs','DATASET_NOT_READY')
    except (OSError,ValueError,KeyError) as e:
        if isinstance(e,SourceError):raise
        raise SourceError('Valsts datu manifesta nolasīšana neizdevās') from e

def db(path):
    c=sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro',uri=True,timeout=5);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');return c

def progress():
    root=BASE/'data/geodata/nationwide/releases'
    paths=sorted(root.glob('*/progress.json'),key=lambda p:p.stat().st_mtime,reverse=True) if root.exists() else []
    if not paths:return {'status':'NOT_STARTED','state':'DATASET_NOT_READY'}
    try:
        value=json.loads(paths[0].read_text());validated=paths[0].parent/'validated-sources.json'
        if validated.exists():value['sources_validated']=len(json.loads(validated.read_text()))
        return value
    except (OSError,ValueError):return {'status':'UNKNOWN','state':'SOURCE_ERROR'}

def status():
    try:
        m=release();r=m['reports']['vmd'];p=m['reports']['vzd']
        return {'name':'VMD meža nogabali','source':'VMD_OPEN_DATA','status':'AVAILABLE','state':'DATASET_READY','feature_count':r['indexed'],'parcel_count':p['indexed'],'dataset_version':m['version'],'crs':'EPSG:4326','source_crs':'EPSG:10306','extent':r['extent'],'source_layers':[{'name':l['layer'],'features':l['feature_count']} for l in r['layers']],'repaired':r['repaired'],'failed':r['failed'],'importable_count':r['importable'],'coverage':'Visa Latvija: validēti 5 VMD reģionu un 42 VZD pašvaldību avoti.','regions':r['regions'],'regions_covered':5,'municipalities_covered':42,'sources_validated':47,'indexed_at':m['created_at'],'source_dates':{x['name']:x['source_date'] for x in m['sources']},'licences':m['licences'],'job':progress()}
    except SourceError as e:return {'status':e.state,'state':e.state,'message':str(e),'job':progress(),'feature_count':0,'parcel_count':0}

@lru_cache(maxsize=128)
def _parcel(path,version,designation):
    with closing(db(path)) as c:
        row=c.execute('SELECT * FROM parcels WHERE designation=?',(designation,)).fetchone()
        return dict(row) if row else None

def parcel_row(designation,m=None):
    m=m or release();return _parcel(m['parcel_db'],m['version'],designation)

def parcel_validation(designation,geometry=None,source_crs='EPSG:10306'):
    m=release();row=parcel_row(designation,m)
    result={'status':'not_found','state':'PARCEL_NOT_FOUND','message':'Kadastra zemes vienība nav atrasta','requested_designation':designation,'registration_allowed':False,'land_unit_exists':False,'land_unit_geometry':None,'compartment_relationship_verified':False,'cadastral_boundary_verified':False,'dataset_version':m['version']}
    if row is None:return result
    valid=bool(row['geometry_valid'] and row['source_verified']);parcel=shapely.from_wkb(row['native_geometry'])
    result.update({'status':'verified_land_unit' if valid else 'unverified','state':'CADASTRAL_PARCEL_FOUND','message':'VZD zemes vienība pārbaudīta' if valid else 'Kadastra dati nav pārbaudīti','registration_allowed':valid,'land_unit_exists':True,'land_unit_geometry':mapping(shapely.from_wkb(row['geometry'])) if valid and geometry is None else None,'land_unit_area_ha':row['area_m2']/10000,'source_designation':row['designation'],'source_field':'CODE','source_file':row['source_file'],'source_record':row['source_row'],'source_region':row['source_region'],'source_date':row['source_date'],'source_crs':row['source_crs'],'archive_sha256':row['archive_sha256'],'dataset_version':m['version'],'retrieved_at':m['created_at'],'reference':{'provider':'VZD','layer':'KKParcel','designation':designation,'source_file':row['source_file'],'source_row':row['source_row'],'source_crs':row['source_crs'],'source_date':row['source_date'],'archive_sha256':row['archive_sha256'],'dataset_version':m['version']},'attribution':'Valsts zemes dienests — Kadastra informācijas sistēmas atvērtie telpiskie dati (CC BY 4.0)','reason':'Precīzs VZD KKParcel.CODE; netiek apstiprinātas īpašumtiesības vai mērniecības precizitāte.'})
    if geometry is None or not valid:return result
    g=shape(geometry)
    if source_crs!='EPSG:10306':
        from pyproj import Transformer
        from shapely.ops import transform
        g=transform(Transformer.from_crs(source_crs,10306,always_xy=True).transform,g)
    if not g.is_valid or g.is_empty or g.area<=0:
        return {**result,'status':'geometry_invalid','registration_allowed':False,'message':'Avota ģeometrija nav derīga'}
    inside=parcel.covers(g);intersection=g.intersection(parcel).area
    result.update({'status':'verified' if inside else 'boundary_review_required','registration_allowed':inside,'compartment_relationship_verified':inside,'fully_inside':inside,'overlap_percent':min(100,intersection/g.area*100),'intersection_area_m2':intersection,'outside_area_m2':g.difference(parcel).area,'message':'VMD un VZD saistība pārbaudīta' if inside else 'Robežu neatbilstība — nepieciešama pārbaude'})
    return result

def source_association(row,designation):
    props=json.loads(row['properties']);valid=bool(row['source_verified'] and props.get('kadastrs')==row['kadastrs']==designation and str(props.get('objectid'))==row['objectid'] and str(props.get('kvart'))==row['kvart'] and str(props.get('nog'))==row['nog'])
    return {'status':'verified_source_attribute' if valid else 'unverified','classification':'authoritative_vmd_attribute' if valid else 'unverified','source_field':'kadastrs','requested_designation':designation,'source_designation':props.get('kadastrs'),'source_feature_id':row['external_id'],'source_file':row['source_file'],'source_record':row['source_row'],'source_region':row['source_region'],'source_date':row['source_date'],'archive_sha256':row['archive_sha256'],'cadastral_boundary_verified':False,'reason':'Sākotnējais DBF atribūts un avota integritāte validēta valsts indeksa izveidē.'}

def source_reference(row):
    m=release();source=next((x for x in m['sources'] if x.get('archive_sha256')==row['archive_sha256'] and x.get('kind')=='vmd'),None)
    return {'source_url':source.get('url') if source else None,'source_licence':'CC0-1.0','source_region':row['source_region'],'source_date':row['source_date'],'source_archive_sha256':row['archive_sha256'],'source_file':row['source_file'],'source_record':row['source_row'],'dataset_version':m['version']}

def original(row):
    data=row['original_geometry'] if row['original_geometry'] is not None else row['native_geometry'];return mapping(shapely.from_wkb(data))

def empty(designation,state,message,version=None):
    return {'type':'FeatureCollection','features':[],'spatial_candidates':[],'state':state,'states':[state],'search_message':message,'dataset_version':version,'cadastral_validation':{'status':'unverified','registration_allowed':False,'land_unit_exists':None,'land_unit_geometry':None},'cadastral_verification':{'status':'unverified','verified_count':0,'unverified_count':0},'summary':{'found':0,'returned':0,'offset':0,'limit':100,'has_more':False,'bounds':None,'total_compartment_area_ha':0,'cadastral_search':{'field':'kadastrs','value':designation,'match':'exact'}}}

def search(designation,limit=100,offset=0,review_offset=0):
    if not re.fullmatch('[0-9]{11}',designation):raise ValueError('Ievadiet precīzu 11 ciparu kadastra apzīmējumu')
    started=time.monotonic()
    try:
        m=release();p=parcel_row(designation,m);validation=parcel_validation(designation)
        if p is None:
            with closing(db(m['parcel_db'])) as rejected:
                bad=rejected.execute("SELECT count(*) FROM rejections WHERE json_extract(properties,'$.CODE')=?",(designation,)).fetchone()[0]
            if bad:return empty(designation,'SOURCE_ERROR','VZD avota ierakstam nepieciešama ģeometrijas pārbaude.',m['version'])
            result=empty(designation,'PARCEL_NOT_FOUND','Zemes vienība nav atrasta valsts VZD indeksā.',m['version']);result['cadastral_validation']=validation;return result
        if not validation['registration_allowed']:
            result=empty(designation,'SOURCE_ERROR','VZD avota ģeometrija vai identifikatora integritāte nav pārbaudīta.',m['version']);result['cadastral_validation']=validation;return result
        from . import vmd_dataset as data
        parcel=shapely.from_wkb(p['native_geometry']);a,b,d,e=parcel.bounds
        with closing(db(m['forest_db'])) as src,closing(data._app_connection()) as app:
            exact_count=src.execute('SELECT count(*) FROM compartments WHERE kadastrs=?',(designation,)).fetchone()[0]
            box_count=src.execute('SELECT count(*) FROM native_index WHERE min_x<=? AND max_x>=? AND min_y<=? AND max_y>=?',(d,a,e,b)).fetchone()[0]
            if exact_count>50000 or box_count>50000:raise SourceError('Teritorijas rezultātu apjoms pārsniedz drošo vaicājuma robežu; dati netiek saīsināti.')
            bad=src.execute("SELECT count(*) FROM rejections WHERE json_extract(properties,'$.kadastrs')=?",(designation,)).fetchone()[0]
            if bad:
                result=empty(designation,'SOURCE_ERROR','VMD avota ierakstiem nepieciešama ģeometrijas pārbaude; nepilna atlase netiek piedāvāta kā apstiprināta.',m['version']);result['cadastral_validation']=validation;return result
            exact=src.execute('SELECT * FROM compartments WHERE kadastrs=? ORDER BY id',(designation,)).fetchall()
            candidates=src.execute('SELECT c.* FROM native_index r JOIN compartments c ON c.id=r.id WHERE r.min_x<=? AND r.max_x>=? AND r.min_y<=? AND r.max_y>=? ORDER BY c.id',(d,a,e,b)).fetchall()
            if len(candidates)>50000 or len(exact)>50000:raise SourceError('Teritorijas rezultātu apjoms pārsniedz drošo vaicājuma robežu; nepieciešama servera apstrāde.')
            rows={r['id']:r for r in exact};rows.update({r['id']:r for r in candidates});exact_descriptors=[];spatial_descriptors=[];verified_count=0;source_count=0;area=0;bounds=shapely.from_wkb(p['geometry']).bounds
            for row in rows.values():
                if time.monotonic()-started>25:raise SourceError('Telpiskās meklēšanas laiks pārsniegts; mēģiniet vēlreiz.')
                g=shapely.from_wkb(row['native_geometry']);is_exact=row['kadastrs']==designation;geometry_valid=g.is_valid and not g.is_empty
                test=g if geometry_valid else shapely.make_valid(g);intersects=test.intersects(parcel)
                if not is_exact and not intersects:continue
                intersection=test.intersection(parcel).area if intersects else 0
                if not is_exact and intersection<=0:continue
                ratio=min(1,intersection/max(test.area,1e-20));inside=geometry_valid and parcel.covers(g)
                association=source_association(row,designation)
                check={**validation,'land_unit_geometry':None,'status':'verified' if inside else 'boundary_review_required','compartment_relationship_verified':inside,'registration_allowed':inside,'geometry_valid':geometry_valid,'fully_inside':inside,'overlap_percent':ratio*100,'intersection_area_m2':intersection,'outside_area_m2':max(0,test.area-intersection)}
                if not geometry_valid:check.update(status='geometry_invalid',registration_allowed=False)
                elif row['repair']:check.update(status='display_review_required',registration_allowed=False)
                if is_exact and association['status']!='verified_source_attribute':check.update(status='source_conflict',registration_allowed=False,compartment_relationship_verified=False)
                if not is_exact:check.update(status='spatial_candidate_only',registration_allowed=False,compartment_relationship_verified=False)
                eligible=is_exact and association['status']=='verified_source_attribute' and check['registration_allowed']
                descriptor=(row,ratio,inside,association,check,eligible)
                if is_exact:
                    exact_descriptors.append(descriptor);source_count+=int(association['status']=='verified_source_attribute');verified_count+=int(eligible);area+=data._area_ha(row)
                else:spatial_descriptors.append(descriptor)
            exact_descriptors.sort(key=lambda value:value[0]['external_id']);spatial_descriptors.sort(key=lambda value:value[0]['external_id'])
            def render(descriptor):
                row,ratio,inside,association,check,eligible=descriptor;feature=data._feature(src,row,ratio,inside,app);props=feature['properties']
                if not eligible and not props.get('sector'):props['import_status']='REVIEW REQUIRED'
                props.update(cadastral_association=association,cadastral_validation=check,geometry_valid=bool(row['geometry_valid']),importable=bool(props['importable'] and eligible),source_region=row['source_region'],source_date=row['source_date'],association_classification='source_attribute_exact' if row['kadastrs']==designation else 'spatial_inferred',geometry_role='vmd_compartment')
                return feature
            exact_features=[render(value) for value in exact_descriptors[offset:offset+limit]];spatial_features=[render(value) for value in spatial_descriptors[review_offset:review_offset+limit]]
        review_count=sum(value[4]['status']!='verified' for value in exact_descriptors)+len(spatial_descriptors)
        state='VMD_MATCHES_FOUND' if verified_count else 'SPATIAL_REVIEW_REQUIRED' if review_count else 'NO_VMD_RECORDS'
        states=['CADASTRAL_PARCEL_FOUND',state]
        if review_count and 'SPATIAL_REVIEW_REQUIRED' not in states:states.append('SPATIAL_REVIEW_REQUIRED')
        messages={'VMD_MATCHES_FOUND':'Atrasti VMD nogabali. Zaļas robežas — pārbaudīti nogabali; zila robeža — VZD zemes vienība.','SPATIAL_REVIEW_REQUIRED':'Atrasti ieraksti pārbaudei. Oranži telpiskie kandidāti nav apstiprināta kadastra saistība un nav reģistrējami.','NO_VMD_RECORDS':'VZD zemes vienība atrasta; valsts VMD atvērto datu indeksā tai nav atrasti precīzi nogabali vai telpiski kandidāti. Tas neapliecina meža neesamību.'}
        features=exact_features;spatial=spatial_features
        return {'type':'FeatureCollection','features':features,'spatial_candidates':spatial,'state':state,'states':states,'search_message':messages[state],'dataset_version':m['version'],'cadastral_validation':validation,'cadastral_verification':{'status':'verified_source_attribute' if source_count==len(exact_descriptors) and exact_descriptors else 'not_found' if not exact_descriptors else 'unverified','verified_count':source_count,'unverified_count':len(exact_descriptors)-source_count,'derived_count':len(spatial_descriptors),'source_field':'kadastrs','requested_designation':designation},'coverage':{'complete_national_coverage':True,'regions_covered':5,'municipalities_covered':42,'sources_validated':47,'description':'Valsts VZD un VMD avoti validēti','status':'nationwide_loaded'},'summary':{'found':len(exact_descriptors),'returned':len(features),'verified_matches':verified_count,'review_required':review_count,'spatial_candidates':len(spatial_descriptors),'offset':offset,'limit':limit,'has_more':offset+len(features)<len(exact_descriptors),'bounds':list(bounds),'total_compartment_area_ha':round(area,4),'cadastral_search':{'field':'kadastrs','value':designation,'match':'exact'},'elapsed_seconds':round(time.monotonic()-started,3)},'spatial_summary':{'found':len(spatial_descriptors),'returned':len(spatial),'offset':review_offset,'limit':limit,'has_more':review_offset+len(spatial)<len(spatial_descriptors)}}
    except (SourceError,sqlite3.Error,OSError,ValueError,shapely.errors.GEOSException) as error:
        state=error.state if isinstance(error,SourceError) else 'SOURCE_ERROR';log.error('event=nationwide_search_error state=%s designation=%s error_type=%s',state,designation,type(error).__name__)
        return empty(designation,state,str(error) if isinstance(error,SourceError) else 'Valsts datu avota nolasīšana neizdevās.')
