"""Authenticated bounded API over the production spatial catalogue."""
from typing import Literal,Annotated
from fastapi import APIRouter,Depends,HTTPException,Request,Query
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from . import nationwide
from pydantic import BaseModel,ConfigDict,Field
from . import vmd_dataset as data
from .vmd_local import require_json_mutation

class BoundedRoute(APIRoute):
    def get_route_handler(self):
        original=super().get_route_handler()
        async def bounded(request:Request):
            if request.method=='POST':
                body=bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body)>2*1024*1024:raise HTTPException(413,'Territory/request exceeds 2 MiB')
                request._body=bytes(body)
            return await original(request)
        return bounded

class Filters(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kadastrs:str|None=Field(None,max_length=64)
    kadastrs_match:Literal['exact','prefix']='exact'
    kvart:str|None=Field(None,max_length=32)
    nog:str|None=Field(None,max_length=32)
    adm1:str|None=Field(None,max_length=254)
    adm2:str|None=Field(None,max_length=254)

class Search(Filters):
    geometry:dict
    mode:Literal['inside','intersects']='inside'
    min_overlap:float=Field(0,ge=0,le=100)
    limit:int=Field(250,ge=1,le=1000)
    offset:int=Field(0,ge=0,le=50000)

class Selection(Filters):
    geometry:dict|None=None
    bbox:list[float]|None=Field(default=None,min_length=4,max_length=4)
    mode:Literal['inside','intersects']='intersects'
    min_overlap:float=Field(0,ge=0,le=100)
    dataset_version:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$')


class Territory(BaseModel):
    model_config=ConfigDict(extra='forbid')
    geometry:dict
    name:str=Field(min_length=1,max_length=120)
    client_name:str=Field(default='',max_length=200)
    client_id:str|None=Field(default=None,max_length=200)
    source:Literal['DRAWN','UPLOADED_GEOJSON']='DRAWN'

class Import(BaseModel):
    model_config=ConfigDict(extra='forbid')
    feature_ids:list[Annotated[str,Field(min_length=1,max_length=400)]]=Field(min_length=1,max_length=100)
    dataset_version:str=Field(pattern=r'^[a-f0-9]{64}$')
    territory_id:str|None=Field(default=None,max_length=100)
    cadastral_designation:str|None=Field(default=None,pattern=r'^[0-9]{11}$')
    sector_name:str=Field(min_length=1,max_length=120)
    responsible_first_name:str=Field(min_length=1,max_length=100)
    responsible_last_name:str=Field(min_length=1,max_length=100)
    dry_run:bool=True
    confirmed:bool=False


def router(auth):
    r=APIRouter(prefix='/api/geodata/vmd',tags=['VMD production'],dependencies=[Depends(auth)],route_class=BoundedRoute)
    def call(fn,*a,**kw):
        try:return fn(*a,**kw)
        except data.DatasetError as exc:raise HTTPException(exc.status,str(exc)) from exc
        except nationwide.SourceError as exc:return JSONResponse(status_code=503,content={'state':exc.state,'detail':str(exc)})
    @r.get('/registration-context')
    def registration_context(actor=Depends(auth)):
        from .registration_identity import context
        return call(context,actor)
    @r.get('/ingestion')
    def ingestion_status():
        from . import nationwide
        return {'job':nationwide.progress(),'national_index':nationwide.status()}
    @r.get('/dataset')
    def metadata():return call(data.status)
    @r.get('/cadastre')
    def cadastre(kadastrs:str=Query(pattern=r'^[0-9]{11}$'),limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0,le=50000),review_offset:int=Query(0,ge=0,le=50000)):
        return call(data.verified_cadastral_search,kadastrs,limit=limit,offset=offset,review_offset=review_offset)
    @r.get('/compartments')
    def compartments(min_lon:float|None=None,min_lat:float|None=None,max_lon:float|None=None,max_lat:float|None=None,
        limit:int=Query(250,ge=1,le=1000),offset:int=Query(0,ge=0,le=50000),filters:Filters=Depends()):
        values=[min_lon,min_lat,max_lon,max_lat]
        if any(v is not None for v in values) and not all(v is not None for v in values):raise HTTPException(422,'Provide all four bbox coordinates')
        return call(data.search,bbox=values if all(v is not None for v in values) else None,mode='intersects',limit=limit,offset=offset,filters=filters.model_dump())
    @r.post('/territory-preview',dependencies=[Depends(require_json_mutation)])
    def preview(body:Search):
        geometry,area=call(data.territory_geometry,body.geometry)
        return {'type':'Feature','geometry':data.mapping(geometry),'properties':{'area_ha':area,'source':'CLIENT_TERRITORY','is_sector':False}}
    @r.post('/search-territory',dependencies=[Depends(require_json_mutation)])
    def search(body:Search):
        return call(data.search,territory=body.geometry,mode=body.mode,min_overlap=body.min_overlap,limit=body.limit,offset=body.offset,filters={k:getattr(body,k) for k in Filters.model_fields})
    @r.post('/select-matching',dependencies=[Depends(require_json_mutation)])
    def select_matching(body:Selection):
        return call(data.matching_selection,geometry=body.geometry,bbox=body.bbox,mode=body.mode,min_overlap=body.min_overlap,dataset_version=body.dataset_version,filters={k:getattr(body,k) for k in Filters.model_fields})
    @r.post('/import-selected',dependencies=[Depends(require_json_mutation)])
    def import_selected(body:Import,actor=Depends(auth)):
        if not body.dry_run and not body.confirmed:raise HTTPException(400,'Confirm the selected compartment import explicitly')
        if not body.responsible_first_name.strip() or not body.responsible_last_name.strip():raise HTTPException(422,'Norādiet atbildīgās personas vārdu un uzvārdu')
        return call(data.selected_import,body.feature_ids,body.dataset_version,actor,body.dry_run,body.territory_id,body.responsible_first_name,body.responsible_last_name,sector_name=body.sector_name,requested_designation=body.cadastral_designation)
    @r.get('/territories')
    def territories(actor=Depends(auth)):return call(data.list_territories,actor)
    @r.get('/territories/{ident}')
    def territory(ident:str,actor=Depends(auth)):return call(data.get_territory,ident,actor)
    @r.post('/territories',dependencies=[Depends(require_json_mutation)])
    def save(body:Territory,actor=Depends(auth)):return call(data.save_territory,body.geometry,body.name,body.client_name,body.source,actor,body.client_id)
    return r
