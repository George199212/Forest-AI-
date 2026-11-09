"""Bounded display tiles over immutable national SQLite indexes.

Tiles are public-source visualization only. Inspection and registration reread
full source records; no simplified geometry ever enters the import API.
"""
import json, math, os, threading, time
from collections import OrderedDict
from contextlib import closing
from functools import lru_cache
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import box, mapping, Point
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from . import nationwide as nw, vmd_dataset as data
from .registration_identity import context

MAX_FEATURES = 600
MAX_TILE_BYTES = 400_000
MAX_INPUT_BYTES = 4_000_000
CACHE_BYTES = 24_000_000
GRID_ZOOM = 14
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
    xs, ys, counts, _ = overview(version)
    cell_z = min(GRID_ZOOM, z+4)
    shift = GRID_ZOOM-cell_z
    cx, cy = xs >> shift, ys >> shift
    tile_shift = cell_z-z
    if tile_shift < 0:
        # Dense high-zoom fallback: the coarser presence cell is clipped below.
        mask = ((xs << (z-GRID_ZOOM)) <= x) & (((xs+1) << (z-GRID_ZOOM)) > x) & ((ys << (z-GRID_ZOOM)) <= y) & (((ys+1) << (z-GRID_ZOOM)) > y)
    else:
        mask = ((cx >> tile_shift) == x) & ((cy >> tile_shift) == y)
    keys, inv = np.unique(cx[mask].astype(np.int64)*2**cell_z+cy[mask], return_inverse=True)
    totals = np.bincount(inv, weights=counts[mask]).astype(int)
    clip = box(*tile_bounds(z,x,y))
    features=[]
    for key,count in zip(keys,totals):
        px,py=divmod(int(key),2**cell_z)
        g=box(*tile_bounds(cell_z,px,py)).intersection(clip)
        if not g.is_empty and g.area:
            features.append({'type':'Feature','geometry':mapping(g),'properties':{'compartment_count':int(count),'display_only':True}})
    return {'type':'FeatureCollection','features':features,'mode':'generalized_presence','display_only':True,'dataset_version':version,'notice':'Occupied overview cells indicate forest presence, not exact coverage or registrable boundaries.'}


def _encode(payload):
    return json.dumps(payload, separators=(',',':'),allow_nan=False).encode()


def _generate(layer,z,x,y,manifest):
    version=manifest['version'];bounds=tile_bounds(z,x,y);w,s,e,n=bounds
    empty={'type':'FeatureCollection','features':[],'mode':'detail','display_only':True,'dataset_version':version}
    if e<20 or w>29 or n<55 or s>59:return _encode(empty)
    if layer=='forest' and z<=10:return _encode(coverage(version,z,x,y))
    if layer=='parcels' and z<14:return _encode({**empty,'mode':'zoom_required','notice':'Zoom to 14 for parcel boundaries; exact cadastral search is available at every zoom.'})
    table='compartments' if layer=='forest' else 'parcels'
    fields='c.id,c.external_id,c.kadastrs,length(c.geometry) AS geometry_bytes,c.repair,c.geometry_valid' if layer=='forest' else 'c.id,c.designation,length(c.geometry) AS geometry_bytes,c.geometry_valid'
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
            if vertices>20000:return fallback()
            props={'display_only':True,'geometry_valid':bool(row['geometry_valid'])}
            if layer=='forest':props.update(id=row['external_id'],kadastrs=row['kadastrs'],review_required=bool(row['repair']) or not row['geometry_valid'])
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
    if not _workers.acquire(timeout=.05):raise HTTPException(503,'Map is busy; retry this tile')
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
        association=nw.source_association(row,row['kadastrs'])
        validation=nw.parcel_validation(row['kadastrs'],nw.original(row),source_crs=row['source_crs'])
        if row['repair']:validation.update(registration_allowed=False,status='display_review_required' if row['geometry_valid'] else 'geometry_invalid')
        eligible=bool(p['importable'] and row['geometry_valid'] and not row['repair'] and validation['registration_allowed'] and association['status']=='verified_source_attribute')
        p.update(cadastral_association=association,cadastral_validation=validation,geometry_valid=bool(row['geometry_valid']),importable=eligible,display_only=False)
        if not eligible and not p['sector']:p['import_status']='REVIEW REQUIRED'
        return {'feature':f,'dataset_version':m['version'],'geometry_role':'full_source_display','registration_geometry':'reread_from_immutable_native_source_by_existing_import_workflow'}


def identify(lat,lon,zoom,actor):
    if not 55<=lat<=59 or not 20<=lon<=29:raise HTTPException(422,'Coordinates must be in Latvia')
    if zoom<11:return {'feature':None,'notice':'Zoom in to inspect individual compartments.'}
    radius=360/2**zoom/256*6
    with closing(nw.db(nw.release()['forest_db'])) as c:
        sizes=c.execute('SELECT c.id,c.external_id,length(c.geometry) AS bytes FROM spatial_index r JOIN compartments c ON c.id=r.id WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=? LIMIT 129',(lon+radius,lon-radius,lat+radius,lat-radius)).fetchall()
        if len(sizes)>128:return {'feature':None,'notice':'Dense location; zoom in to inspect.'}
        if sum(r['bytes'] for r in sizes)>MAX_INPUT_BYTES:return {'feature':None,'notice':'Complex geometry; use exact cadastral review.'}
        ids=[r['id'] for r in sizes]
        rows=c.execute('SELECT external_id,geometry FROM compartments WHERE id IN ('+','.join('?' for _ in ids)+')',ids).fetchall() if ids else []
    point=Point(lon,lat);hits=[]
    for row in rows:
        g=shapely.from_wkb(row['geometry']);distance=g.distance(point)
        if distance<=radius:hits.append((distance,g.area,row['external_id']))
    return feature(min(hits)[2],actor) if hits else {'feature':None,'notice':'No forest compartment at this location.'}


def sectors(actor):
    identity=context(actor)
    with closing(data._app_connection()) as c:
        rows=c.execute('SELECT id,name,boundary_json,area_ha,center_lat,center_lon FROM sectors WHERE organization_id=? LIMIT 1001',(identity['organization_id'],)).fetchall()
    if len(rows)>1000:raise HTTPException(413,'Too many sectors for this overlay')
    features=[];invalid=markers=outside=0
    for row in rows:
        geometry=None;status='no_boundary';warning=''
        try:
            from shapely.geometry import Polygon
            if row['boundary_json']:
                g=Polygon([(p[1],p[0]) for p in json.loads(row['boundary_json'])])
                if g.is_valid and not g.is_empty:
                    w,s,e,n=g.bounds
                    if 20<=w<=e<=29 and 55<=s<=n<=59:geometry=mapping(g);status='valid_boundary'
                    else:status='outside_map_extent';warning='Stored boundary is outside the Latvia map extent.';outside+=1
                else:status='invalid_boundary';warning=shapely.is_valid_reason(g);invalid+=1
        except (ValueError,TypeError,IndexError,shapely.errors.GEOSException):status='invalid_boundary';warning='Invalid stored sector boundary';invalid+=1
        if geometry is None:
            lat,lon=row['center_lat'],row['center_lon']
            if not isinstance(lat,(int,float)) or not isinstance(lon,(int,float)):continue
            if not (55<=lat<=59 and 20<=lon<=29):
                if status!='outside_map_extent':outside+=1
                continue
            geometry={'type':'Point','coordinates':[lon,lat]};markers+=1
            warning=(warning+' · ' if warning else '')+'Stored sector center; no validated polygon is shown.'
        features.append({'type':'Feature','geometry':geometry,'properties':{'id':row['id'],'name':row['name'],'area_ha':row['area_ha'],'geometry_status':status,'warning':warning}})
    return {'type':'FeatureCollection','features':features,'summary':{'total':len(rows),'mapped':len(features),'unmapped':len(rows)-len(features),'invalid_boundaries':invalid,'center_markers':markers,'outside_map_extent':outside}}


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
    def get_tile(layer:str,z:int,x:int,y:int):
        raw,hit=call(tile,layer,z,x,y)
        return Response(raw,media_type='application/geo+json',headers={'Cache-Control':'private, max-age=120','Vary':'Authorization','X-Forest-Cache':'HIT' if hit else 'MISS'})
    @r.get('/feature')
    def get_feature(id:str=Query(min_length=1,max_length=200),actor=Depends(auth)):return private(call(feature,id,actor))
    @r.get('/identify')
    def get_identify(lat:float,lon:float,zoom:int=Query(ge=4,le=19),actor=Depends(auth)):return private(call(identify,lat,lon,zoom,actor))
    @r.get('/sectors')
    def get_sectors(actor=Depends(auth)):return private(call(sectors,actor))
    return r
