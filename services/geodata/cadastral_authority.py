"""Exact VZD CODE verification, separate from VMD attributes and geometry validity.

Only archived official KKParcel records are accepted. Spatial coincidence never
establishes identity. Strict native-CRS containment gates registration without
buffers, clipping, tolerances or modification of either source geometry.
"""
import hashlib,json,re
from pathlib import Path
from functools import lru_cache
from shapely.geometry import shape
CATALOGUE='https://data.gov.lv/dati/dataset/kadastra-informacijas-sistemas-atverti-telpiskie-dati'
ROOT=Path(__file__).resolve().parents[2]/'data/cadastre'

@lru_cache(maxsize=16)
def _archive_hash(path,mtime,size):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
@lru_cache(maxsize=256)
def _load(path,mtime,size):
    source=json.loads(Path(path).read_text());archive=ROOT/source['archive_file'];stat=archive.stat()
    if _archive_hash(str(archive),stat.st_mtime_ns,stat.st_size)!=source['archive_sha256']:raise ValueError('Archive integrity mismatch')
    parcel=shape(source['source_geometry'])
    if hashlib.sha256(parcel.wkb).hexdigest()!=source['source_geometry_sha256']:raise ValueError('Geometry integrity mismatch')
    if source['source_crs']!='EPSG:10306' or source['source_layer']!='KKParcel' or source['source_field']!='CODE':raise ValueError('Unsupported parcel source')
    if source['source_attributes']['CODE']!=source['designation'] or not parcel.is_valid or parcel.is_empty:raise ValueError('Invalid parcel')
    return source,parcel

def verify(designation, geometry=None,source_crs='EPSG:10306'):
    """geometry, when supplied, is unchanged VMD native EPSG:10306 GeoJSON."""
    from . import nationwide
    if nationwide.configured():return nationwide.parcel_validation(designation,geometry,source_crs)
    result={'status':'unverified','message':'Kadastra dati nav pārbaudīti','requested_designation':designation,
            'registration_allowed':False,'land_unit_exists':None,'land_unit_geometry':None,
            'compartment_relationship_verified':False,'source_catalogue':CATALOGUE,
            'reason':'Nav iegūta VZD zemes vienības precīzā ģeometrija. VMD atribūts pats par sevi nav neatkarīga Kadastra pārbaude.'}
    if not re.fullmatch(r'[0-9]{11}',designation):return result
    try:
        path=ROOT/(designation+'.json');stat=path.stat();source,parcel=_load(str(path),stat.st_mtime_ns,stat.st_size)
        if source['designation']!=designation:raise ValueError('Designation mismatch')
        result.update({'status':'verified_land_unit','message':'VZD zemes vienība pārbaudīta','land_unit_exists':True,
                       'source_designation':source['source_attributes']['CODE'],'source_field':'CODE','source_crs':'EPSG:10306',
                       'download_url':source['download_url'],'archive_sha256':source['archive_sha256'],
                       'source_file':source['source_file'],'source_record':source['source_record'],
                       'retrieved_at':source['retrieved_at'],'attribution':source['attribution'],
                       'land_unit_area_ha':parcel.area/10000,'registration_allowed':True,
                       'reason':'Precīzs VZD KKParcel.CODE; netiek apliecinātas īpašumtiesības vai mērniecības precizitāte.'})
        if geometry is None:
            result['land_unit_geometry']=source['normalized_geometry'];return result
        compartment=shape(geometry)
        if not compartment.is_valid or compartment.is_empty or compartment.area<=0:raise ValueError('Invalid compartment geometry')
        inside=parcel.covers(compartment);overlap=compartment.intersection(parcel).area/compartment.area*100
        result.update({'status':'verified' if inside else 'boundary_review_required',
                       'message':'VMD un VZD saistība pārbaudīta' if inside else 'Robežu neatbilstība — nepieciešama pārbaude',
                       'compartment_relationship_verified':inside,'registration_allowed':inside,
                       'overlap_percent':min(100,overlap),'fully_inside':inside,
                       'outside_area_m2':compartment.difference(parcel).area,
                       'reason':'Precīzi sakrīt VMD kadastrs un VZD CODE; nogabals pilnībā atrodas zemes vienībā.' if inside else 'Identifikatori sakrīt, bet avota robežas pilnībā nesakrīt. Bez pielaides, bufera vai robežu labošanas reģistrācija bloķēta.'})
        return result
    except (OSError,ValueError,KeyError,TypeError):return result
