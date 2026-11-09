"""Bounded display tiles over immutable national SQLite indexes.

Tiles are public-source visualization only. Inspection and registration reread
full source records; no simplified geometry ever enters the import API.
"""
import gzip, json, math, os, threading, time
from collections import OrderedDict
from contextlib import closing
from functools import lru_cache
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import box, mapping, Point
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from . import gps_map as gps, gps_violations as gv, nationwide as nw, vmd_dataset as data
from .registration_identity import context

# Compartment boundaries are drawn from DETAIL_MIN_ZOOM (median compartment about 8 px);
# below it the map shows record-density cells. Limits are about 2x the census maximum over
# all 9,312 occupied zoom-13 tiles (967 records, 333 KB input; 2026-11-09), so no tile at a
# boundary zoom falls back. Responses are gzip-compressed on the wire.
DETAIL_MIN_ZOOM = 13
MAX_FEATURES = 2000
MAX_TILE_BYTES = 1_500_000
MAX_INPUT_BYTES = 4_000_000
MAX_VERTICES = 100_000
CACHE_BYTES = 48_000_000
GRID_ZOOM = 14
WORKER_WAIT_SECONDS = 10
# Coarse bounding envelope of Latvia (west, south, east, north); a warning flag, not a border test.
LATVIA_ENVELOPE = (20.9, 55.6, 28.3, 58.1)
ROOT = Path(__file__).resolve().parents[2]
DISPLAY_ROOT = Path(os.environ.get('FOREST_MAP_CACHE_ROOT', ROOT/'data/geodata/forest-map'))
_cache = OrderedDict()
_cache_size = 0
_lock = threading.Lock()
_workers = threading.BoundedSemaphore(3)


def tile_bounds(z, x, y):
    n = 2**z
    if not 4 <= z <= 19 or not 0 <= x < n or not 0 <= y < n:
        raise HTTPException(422, 'Invalid map tile')
    lat = lambda a: math.degrees(math.atan(math.sinh(math.pi*(1-2*a/n))))
    return (x/n*360-180, lat(y+1), (x+1)/n*360-180, lat(y))


@lru_cache(maxsize=2)
def overview(version):
    path = DISPLAY_ROOT/version/'overview.npz'
    if not path.is_file():
        raise HTTPException(503, 'Forest overview is not prepared; run scripts/build_forest_map_overview.py locally')
    with np.load(path, allow_pickle=False) as grid:
        if str(grid['version']) != version:
            raise HTTPException(503, 'Forest overview version mismatch')
        return grid['x'].copy(), grid['y'].copy(), grid['count'].copy(), int(grid['records'])


def coverage(version, z, x, y):
    """Record density at the overview's own ~1.3 km (zoom-14) cells; no cell is enlarged.

    Cells are keyed by the bbox centre of each catalogue record (scripts/build_forest_map_overview.py),
    so they show where records are, not exact forest area or boundaries.
    """
    xs, ys, counts, _ = overview(version)
    if z <= GRID_ZOOM:
        shift = GRID_ZOOM-z
        mask = ((xs >> shift) == x) & ((ys >> shift) == y)
        origin_x, origin_y = x << shift, y << shift
    else:
        shift = z-GRID_ZOOM
        mask = (xs == x >> shift) & (ys == y >> shift)
        origin_x, origin_y = xs[mask].min() if mask.any() else 0, ys[mask].min() if mask.any() else 0
    cells = {'zoom':GRID_ZOOM,'x0':int(origin_x),'y0':int(origin_y),
             'dx':(xs[mask]-origin_x).astype(int).tolist(),'dy':(ys[mask]-origin_y).astype(int).tolist(),'count':counts[mask].astype(int).tolist()}
    return {'type':'FeatureCollection','features':[],'cells':cells,'mode':'generalized_presence','display_only':True,'dataset_version':version,
            'notice_code':'density_cells','notice':'Record density per ~1.3 km cell (bbox centre of each VMD record); not forest area or boundaries.'}


def _encode(payload):
    return json.dumps(payload, separators=(',',':'),allow_nan=False).encode()


def _generate(layer,z,x,y,manifest):
    version=manifest['version'];bounds=tile_bounds(z,x,y);w,s,e,n=bounds
    empty={'type':'FeatureCollection','features':[],'mode':'detail','display_only':True,'dataset_version':version}
    if e<20 or w>29 or n<55 or s>59:return _encode(empty)
    if layer=='forest' and z<DETAIL_MIN_ZOOM:return _encode(coverage(version,z,x,y))
    if layer=='parcels' and z<14:return _encode({**empty,'mode':'zoom_required','notice':'Zoom to 14 for parcel boundaries; exact cadastral search is available at every zoom.'})
    table='compartments' if layer=='forest' else 'parcels'
    fields='c.id,c.external_id,c.kadastrs,c.kvart,c.nog,c.nog_plat,c.area_m2,length(c.geometry) AS geometry_bytes,c.repair,c.geometry_valid' if layer=='forest' else 'c.id,c.designation,length(c.geometry) AS geometry_bytes,c.geometry_valid'
    path=manifest['forest_db' if layer=='forest' else 'parcel_db']
    def fallback():
        return _encode(coverage(version,z,x,y) if layer=='forest' else {**empty,'mode':'zoom_required','notice':'Dense parcel tile: zoom in for boundaries.'})
    deadline=time.monotonic()+2.5
    with closing(nw.db(path)) as c:
        c.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
        rows=c.execute('SELECT '+fields+' FROM spatial_index r JOIN '+table+' c ON c.id=r.id WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=? LIMIT ?', (e,w,n,s,MAX_FEATURES+1)).fetchall()
        if len(rows)>MAX_FEATURES or sum(r['geometry_bytes'] for r in rows)>MAX_INPUT_BYTES:return fallback()
        ids=[r['id'] for r in rows]
        geometries={r['id']:r['geometry'] for r in c.execute('SELECT id,geometry FROM '+table+' WHERE id IN ('+','.join('?' for _ in ids)+')',ids)} if ids else {}
    clip=box(*bounds);features=[];vertices=0;deadline=time.monotonic()+2.5
    tolerance=(e-w)/256*(1.2 if z<14 else .3)
    for row in rows:
        if time.monotonic()>deadline:return fallback()
        try:
            g=shapely.from_wkb(geometries[row['id']]).intersection(clip)
            if g.is_empty or g.area<=0:continue
            if z<17:g=g.simplify(tolerance,preserve_topology=True)
            if g.geom_type not in ('Polygon','MultiPolygon') or not g.is_valid:continue
            vertices+=shapely.get_num_coordinates(g)
            if vertices>MAX_VERTICES:return fallback()
            props={'display_only':True,'geometry_valid':bool(row['geometry_valid'])}
            if layer=='forest':
                declared=row['nog_plat'] is not None and row['nog_plat']>0
                props.update(id=row['external_id'],kadastrs=row['kadastrs'],kvart=row['kvart'],nog=row['nog'],
                    area_ha=round(row['nog_plat'],4) if declared else (round(row['area_m2']/10000,4) if row['area_m2'] is not None else None),area_declared=declared,
                    review_required=bool(row['repair']) or not row['geometry_valid'])
            else:props.update(designation=row['designation'])
            features.append({'type':'Feature','geometry':mapping(g),'properties':props})
        except shapely.errors.GEOSException:return fallback()
    result=_encode({**empty,'features':features,'mode':'simplified' if z<17 else 'detail'})
    return result if len(result)<=MAX_TILE_BYTES else fallback()


def tile(layer,z,x,y):
    global _cache_size
    tile_bounds(z,x,y)
    if layer not in ('forest','parcels'):raise HTTPException(404,'Unknown map layer')
    manifest=nw.release();key=(manifest['version'],layer,z,x,y)
    with _lock:
        if key in _cache:
            value=_cache.pop(key);_cache[key]=value;return value,True
    # Wait in a bounded queue instead of rejecting at once; a rejected tile used to stay blank.
    if not _workers.acquire(timeout=WORKER_WAIT_SECONDS):raise HTTPException(503,'Map is busy; retry this tile')
    try:
        # Queries and geometry processing have separate finite budgets.
        value=_generate(layer,z,x,y,manifest)
    except Exception as exc:
        if isinstance(exc,(HTTPException,nw.SourceError)):raise
        import sqlite3
        if isinstance(exc,sqlite3.OperationalError):raise HTTPException(503,'Map tile query timed out') from exc
        raise
    finally:_workers.release()
    with _lock:
        previous=_cache.pop(key,None)
        if previous:_cache_size-=len(previous)
        _cache[key]=value;_cache_size+=len(value)
        while _cache_size>CACHE_BYTES or len(_cache)>256:
            _,old=_cache.popitem(last=False);_cache_size-=len(old)
    return value,False


def feature(fid,actor):
    context(actor)  # Fail closed on unsupported/ambiguous organization ownership.
    m=nw.release()
    with closing(nw.db(m['forest_db'])) as c,closing(data._app_connection()) as app:
        sizes=c.execute('SELECT length(geometry),length(native_geometry) FROM compartments WHERE external_id=?',(fid,)).fetchone()
        if sizes is None:raise HTTPException(404,'Forest compartment not found')
        if sizes[0]>2_000_000 or (sizes[1] or 0)>MAX_INPUT_BYTES:raise HTTPException(413,'Source geometry is too complex for direct inspection; use cadastral review')
        row=c.execute('SELECT * FROM compartments WHERE external_id=?',(fid,)).fetchone()
        f=data._feature(c,row,app=app);p=f['properties']
        validation,association=nw.compartment_validation(row,row['kadastrs'])
        eligible=bool(p['importable'] and row['geometry_valid'] and not row['repair'] and validation['registration_allowed'] and association['status']=='verified_source_attribute')
        # Inspection shows the unchanged source geometry transformed only for map coordinates.
        # The display tiles remain simplified separately and are never registration input.
        f['geometry']=nw.original_wgs84(row)
        p.update(cadastral_association=association,cadastral_validation=validation,geometry_valid=bool(row['geometry_valid']),source_crs=row['source_crs'],source_geometry_crs='EPSG:4326',source_region=row['source_region'],source_date=row['source_date'],source_layer=row['source_layer'],source_record=row['source_row'],source_reference=nw.source_reference(row),geometry_role='transformed_original_source',importable=eligible,display_only=False)
        if not eligible and not p['sector']:p['import_status']='REVIEW REQUIRED'
        f['properties']=_without_server_paths(p,m)
        return {'feature':f,'dataset_version':m['version'],'geometry_role':'full_source_display','registration_geometry':'reread_from_immutable_native_source_by_existing_import_workflow'}


def _without_server_paths(value,manifest):
    """Show source files relative to the dataset release; never expose server directories."""
    root=str(manifest.get('root') or '').rstrip('/')
    if isinstance(value,dict):return {k:_without_server_paths(v,manifest) for k,v in value.items()}
    if isinstance(value,list):return [_without_server_paths(v,manifest) for v in value]
    if isinstance(value,str) and value.startswith('/'):
        if root and value.startswith(root+'/'):return value[len(root)+1:]
        return Path(value).name
    return value


def municipality_catalogue(name,limit=100,offset=0,actor=None):
    """Paginated national catalogue navigation by exact VMD municipality value."""
    context(actor)
    name=name.strip()
    if not 1<=len(name)<=254 or not 1<=limit<=100 or not 0<=offset<=50000:
        raise HTTPException(422,'Norādiet pašvaldību, lapas izmēru (1–100) un derīgu nobīdi.')
    m=nw.release()
    with closing(nw.db(m['forest_db'])) as c:
        total=c.execute('SELECT count(*) FROM compartments WHERE adm1=?',(name,)).fetchone()[0]
        rows=c.execute('SELECT external_id,kadastrs,kvart,nog,nog_plat,area_m2,source_region FROM compartments WHERE adm1=? ORDER BY id LIMIT ? OFFSET ?', (name,limit,offset)).fetchall()
    return {'municipality':name,'dataset_version':m['version'],'total':total,'offset':offset,'limit':limit,'has_more':offset+len(rows)<total,
        'results':[{'source_id':r['external_id'],'kadastrs':r['kadastrs'],'kvart':r['kvart'],'nog':r['nog'],'area_ha':r['nog_plat'] if r['nog_plat'] and r['nog_plat']>0 else r['area_m2']/10000,'source_region':r['source_region']} for r in rows]}


def identify(lat,lon,zoom,actor):
    if not 55<=lat<=59 or not 20<=lon<=29:raise HTTPException(422,'Coordinates must be in Latvia')
    if zoom<11:return {'feature':None,'notice_code':'zoom_in','notice':'Zoom in to inspect individual compartments.'}
    radius=360/2**zoom/256*6
    with closing(nw.db(nw.release()['forest_db'])) as c:
        sizes=c.execute('SELECT c.id,c.external_id,length(c.geometry) AS bytes FROM spatial_index r JOIN compartments c ON c.id=r.id WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=? LIMIT 129',(lon+radius,lon-radius,lat+radius,lat-radius)).fetchall()
        if len(sizes)>128:return {'feature':None,'notice_code':'dense','notice':'Dense location; zoom in to inspect.'}
        if sum(r['bytes'] for r in sizes)>MAX_INPUT_BYTES:return {'feature':None,'notice_code':'complex','notice':'Complex geometry; use exact cadastral review.'}
        ids=[r['id'] for r in sizes]
        rows=c.execute('SELECT external_id,geometry FROM compartments WHERE id IN ('+','.join('?' for _ in ids)+')',ids).fetchall() if ids else []
    point=Point(lon,lat);hits=[]
    for row in rows:
        g=shapely.from_wkb(row['geometry']);distance=g.distance(point)
        if distance<=radius:hits.append((distance,g.area,row['external_id']))
    return feature(min(hits)[2],actor) if hits else {'feature':None,'notice_code':'none','notice':'No forest compartment at this location.'}


def sectors(actor):
    identity=context(actor)
    with closing(data._app_connection()) as c:
        rows=c.execute('SELECT id,name,boundary_json,area_ha,center_lat,center_lon FROM sectors WHERE organization_id=? LIMIT 1001',(identity['organization_id'],)).fetchall()
    if len(rows)>1000:raise HTTPException(413,'Too many sectors for this overlay')
    features=[];unmapped=[];invalid=markers=outside=0
    for row in rows:
        geometry=None;status='no_boundary';warning=''
        try:
            from shapely.geometry import Polygon
            if row['boundary_json']:
                g=Polygon([(p[1],p[0]) for p in json.loads(row['boundary_json'])])
                if g.is_valid and not g.is_empty:
                    w,s,e,n=g.bounds
                    if 20<=w<=e<=29 and 55<=s<=n<=59:
                        geometry=mapping(g);status='valid_boundary';warning='Valid stored polygon; membership in Latvia borders is not independently verified.'
                    else:status='outside_map_extent';warning='Stored boundary is outside the Latvia map extent.';outside+=1
                else:status='invalid_boundary';warning=shapely.is_valid_reason(g);invalid+=1
        except (ValueError,TypeError,IndexError,shapely.errors.GEOSException):status='invalid_boundary';warning='Invalid stored sector boundary';invalid+=1
        if geometry is None:
            lat,lon=row['center_lat'],row['center_lon']
            if not isinstance(lat,(int,float)) or not isinstance(lon,(int,float)):
                unmapped.append({'id':row['id'],'name':row['name'],'reason':status});continue
            if not (55<=lat<=59 and 20<=lon<=29):
                if status!='outside_map_extent':outside+=1
                unmapped.append({'id':row['id'],'name':row['name'],'reason':'outside_map_extent' if status=='no_boundary' else status,'outside_latvia':True});continue
            geometry={'type':'Point','coordinates':[lon,lat]};markers+=1
            warning=(warning+' · ' if warning else '')+'Stored sector center; no validated polygon is shown and country-border membership is not verified.'
        w,s_,e,n=shapely.geometry.shape(geometry).bounds
        features.append({'type':'Feature','geometry':geometry,'properties':{'id':row['id'],'name':row['name'],'area_ha':row['area_ha'],'geometry_status':status,'warning':warning,
            'outside_latvia':not (LATVIA_ENVELOPE[0]<=w and e<=LATVIA_ENVELOPE[2] and LATVIA_ENVELOPE[1]<=s_ and n<=LATVIA_ENVELOPE[3])}})
    return {'type':'FeatureCollection','features':features,'unmapped':unmapped,'summary':{'total':len(rows),'mapped':len(features),'unmapped':len(rows)-len(features),'invalid_boundaries':invalid,'center_markers':markers,'outside_map_extent':outside}}


def router(auth):
    r=APIRouter(prefix='/api/geodata/forest-map',tags=['Forest map'],dependencies=[Depends(auth)])
    def call(fn,*args):
        try:return fn(*args)
        except nw.SourceError as exc:raise HTTPException(503,str(exc)) from exc
        except data.DatasetError as exc:raise HTTPException(exc.status,str(exc)) from exc
    def private(payload):return JSONResponse(payload,headers={'Cache-Control':'private, no-store','Vary':'Authorization'})
    @r.get('/status')
    def status():
        m=call(nw.release);_,_,_,records=overview(m['version'])
        if records!=m['reports']['vmd']['indexed']:raise HTTPException(503,'Forest overview source count mismatch')
        return private({'dataset_version':m['version'],'feature_count':m['reports']['vmd']['indexed'],'parcel_count':m['reports']['vzd']['indexed'],'overview_records':records,'crs':'EPSG:4326','max_tile_features':MAX_FEATURES,'max_tile_bytes':MAX_TILE_BYTES,'display_only':True})
    @r.get('/tiles/{layer}/{z}/{x}/{y}')
    def get_tile(request:Request,layer:str,z:int,x:int,y:int,v:str=Query('',max_length=128)):
        raw,hit=call(tile,layer,z,x,y)
        # Tiles of a dataset version never change, so a URL carrying that version may be cached.
        current=v and v==nw.release()['version']
        headers={'Cache-Control':'private, max-age=86400, immutable' if current else 'private, no-cache','Vary':'Authorization, Accept-Encoding','X-Forest-Cache':'HIT' if hit else 'MISS'}
        if 'gzip' in request.headers.get('accept-encoding','') and len(raw)>1024:
            raw=gzip.compress(raw,5);headers['Content-Encoding']='gzip'
        return Response(raw,media_type='application/geo+json',headers=headers)
    @r.get('/feature')
    def get_feature(id:str=Query(min_length=1,max_length=200),actor=Depends(auth)):return private(call(feature,id,actor))
    @r.get('/catalogue')
    def get_catalogue(municipality:str=Query(min_length=1,max_length=254),limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0,le=50000),actor=Depends(auth)):
        return private(call(municipality_catalogue,municipality,limit,offset,actor))
    @r.get('/identify')
    def get_identify(lat:float,lon:float,zoom:int=Query(ge=4,le=19),actor=Depends(auth)):return private(call(identify,lat,lon,zoom,actor))
    @r.get('/sectors')
    def get_sectors(actor=Depends(auth)):return private(call(sectors,actor))
    @r.get('/gps/positions')
    def get_gps_positions(stale_minutes:int=Query(gps.STALE_MINUTES,ge=1,le=1440),actor=Depends(auth)):
        return private(call(gps.positions,context(actor)['organization_id'],stale_minutes))
    @r.get('/gps/track')
    def get_gps_track(kind:str=Query(pattern='^(worker|vehicle|equipment|simulated)$'),id:str=Query(min_length=1,max_length=120),
                      start:str=Query(max_length=40),end:str=Query(max_length=40),actor=Depends(auth)):
        begin,finish=gps._parse(start),gps._parse(end)
        if begin is None or finish is None:raise HTTPException(422,'Invalid time window')
        ident=id
        if kind!='simulated':
            try:ident=int(id)
            except ValueError as exc:raise HTTPException(422,'Invalid entity id') from exc
        try:return private(call(gps.track,context(actor)['organization_id'],kind,ident,begin,finish))
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    def entity(kind,id):
        if kind=='simulated':return id
        try:return int(id)
        except ValueError as exc:raise HTTPException(422,'Invalid entity id') from exc
    def guarded(fn,*args):
        try:return private(call(fn,*args))
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except PermissionError as exc:raise HTTPException(409,str(exc)) from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    KIND=Query(pattern='^(worker|vehicle|equipment|simulated)$')
    @r.get('/gps/sessions')
    def get_gps_sessions(kind:str=KIND,id:str=Query(min_length=1,max_length=120)):
        return guarded(gv.sessions,kind,entity(kind,id))
    @r.get('/gps/violations')
    def get_gps_violations(kind:str=KIND,id:str=Query(min_length=1,max_length=120),session:str=Query(pattern=r'^(\d{1,9}|\d{4}-\d{2}-\d{2})$'),actor=Depends(auth)):
        return guarded(gv.violations,context(actor)['organization_id'],kind,entity(kind,id),session)
    @r.get('/gps/violations/overview')
    def get_gps_violations_overview(days:int=Query(None,ge=1,le=365),actor=Depends(auth)):
        return guarded(gv.overview,context(actor)['organization_id'],days)
    @r.get('/gps/session/{session_id}')
    def get_gps_session(session_id:int,actor=Depends(auth)):
        return guarded(gv.session_violations,context(actor)['organization_id'],session_id)
    @r.post('/gps/violations/incident')
    def post_gps_incident(session_id:int=Body(ge=1),exit_point_id:int=Body(ge=1),actor=Depends(auth)):
        # Human action only: the authenticated dashboard account is recorded as the actor.
        return guarded(gv.create_incident,context(actor)['organization_id'],session_id,exit_point_id,actor)
    gps.start_alert_loop()
    return r
