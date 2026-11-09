from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from .base import GeodataError
from .lvm_geo import LVMGeoProvider
from . import store

provider = LVMGeoProvider()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PreviewIn(StrictModel):
    layer_id: str = Field(min_length=1, max_length=500)
    bbox: list[float] = Field(min_length=4, max_length=4)
    limit: int = Field(default=50, ge=1, le=100)


class ImportIn(StrictModel):
    token: str = Field(min_length=20,max_length=100)
    feature_ids: list[Annotated[str,Field(min_length=1,max_length=300)]] = Field(min_length=1,max_length=25)


class ApplyIn(StrictModel):
    token: str = Field(min_length=20,max_length=100)
    confirmed: Literal[True]


def router(verify_credentials):
    r = APIRouter(prefix='/api/geodata/lvm', tags=['Geodata'], dependencies=[Depends(verify_credentials)])

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except GeodataError as e:
            raise HTTPException(400, str(e)) from e

    # Existing dashboard uses HTTP Basic. Additionally reject cross-origin browser
    # POSTs (including same-site sibling client origins), as ambient Basic auth is
    # not a CSRF token. JSON mutations also require application/json.
    def mutation(request: Request):
        from urllib.parse import urlsplit
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415, 'Geodata mutations require application/json')
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') in {'cross-site','same-site'}:
            raise HTTPException(403, 'Cross-origin geodata mutation rejected')
        if origin:
            parsed = urlsplit(origin)
            if parsed.netloc != request.headers.get('host') or parsed.scheme != request.url.scheme:
                raise HTTPException(403, 'Cross-origin geodata mutation rejected')

    @r.get('/health')
    def health(): return provider.health_check()

    @r.post('/health', dependencies=[Depends(mutation)])
    def refresh(): return provider.health_check(refresh=True)

    @r.get('/capabilities')
    def capabilities(): return provider.get_capabilities()

    @r.get('/services')
    def services(): return provider.list_services()

    @r.get('/layers')
    def layers(): return provider.list_layers()

    @r.get('/layer')
    def layer(layer_id: str = Query(max_length=500)): return call(provider.get_layer_metadata, layer_id)

    @r.get('/map-url')
    def map_url(layer_id: str, bbox: str):
        try: coords = [float(v) for v in bbox.split(',')]
        except ValueError: raise HTTPException(400, 'Invalid bbox')
        return {'url': call(provider.get_map_url,layer_id,coords)}

    @r.post('/preview', dependencies=[Depends(mutation)])
    def preview(body: PreviewIn, actor=Depends(verify_credentials)):
        return call(store.preview, provider, body.layer_id, body.bbox, body.limit, actor)

    @r.post('/import', dependencies=[Depends(mutation)])
    def import_features(body: ImportIn, actor=Depends(verify_credentials)):
        return call(store.import_selected,body.token,body.feature_ids,actor)

    @r.get('/sectors/{sector_id}/source')
    def source(sector_id: int): return call(store.source_info,sector_id)

    @r.post('/sectors/{sector_id}/refresh', dependencies=[Depends(mutation)])
    def refresh_sector(sector_id: int, actor=Depends(verify_credentials)):
        return call(store.refresh_boundary,provider,sector_id,actor)

    @r.post('/apply', dependencies=[Depends(mutation)])
    def apply(body: ApplyIn, actor=Depends(verify_credentials)):
        return call(store.apply_boundary,body.token,actor)

    return r
