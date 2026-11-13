"""Cache-only serving with token/network calls forbidden. Uses temporary JPEGs/sidecars."""
import hashlib
import io
import json
from pathlib import Path

import pytest


@pytest.fixture
def satellite(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'unused.db'))
    import api
    from services import review_mode
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient
    from PIL import Image
    monkeypatch.setenv('DASHBOARD_USERNAME','pytest')
    monkeypatch.setenv('DASHBOARD_PASSWORD','pytest')
    monkeypatch.setattr(review_mode,'ENABLED',True)
    monkeypatch.setattr(review_mode,'SATELLITE_CACHE_DIR',tmp_path/'cache')
    def forbidden(*a,**kw):
        raise AssertionError('Outbound/token path reached in review mode')
    monkeypatch.setattr(api,'get_sentinel_token',forbidden)
    monkeypatch.setattr(api.urllib.request,'urlopen',forbidden)
    for name in ('get','post','request'):
        monkeypatch.setattr(api.requests,name,forbidden)
    app=FastAPI(dependencies=[Depends(api.verify_credentials)])
    app.add_middleware(review_mode.ReviewModeMiddleware)
    app.get('/api/satellite/image/{sector_name}')(api.satellite_image)
    app.get('/api/satellite/ndvi/{sector_name}')(api.satellite_ndvi)
    app.get('/api/review/satellite-cache/{kind}/{key}')(api.review_satellite_metadata)
    buffer=io.BytesIO();Image.new('RGB',(512,512),'green').save(buffer,format='JPEG');image=buffer.getvalue()
    def seed(kind='image'):
        directory=tmp_path/'cache'/kind;directory.mkdir(parents=True,exist_ok=True)
        path=directory/'FIELD-TEST-01.jpg';path.write_bytes(image)
        meta={'sector':'FIELD-TEST-01','product':'ndvi' if kind=='ndvi' else 'true_color',
              'source':'Copernicus Sentinel-2 L2A','date_window':{'from':'2026-09-01','to':'2026-09-30'},
              'acquisition_date':'2026-09-14','resolution_m':10,'max_cloud_filter':50,'cloud_percent':3.2,
              'fetched_at':'2026-10-21T12:00:00Z','image_sha256':hashlib.sha256(image).hexdigest(),
              'private_provider_field':'must not be exposed'}
        path.with_suffix('.json').write_text(json.dumps(meta))
        return path,meta
    with TestClient(app) as client:
        yield client,seed,review_mode,api,image


@pytest.mark.parametrize('kind',['image','ndvi'])
def test_cache_hit_uses_metadata_window_and_no_provider(satellite,kind):
    client,seed,mode,api,image=satellite
    path,meta=seed(kind)
    result=client.get('/api/review/satellite-cache/'+kind+'/FIELD-TEST-01',auth=('pytest','pytest'))
    assert result.status_code==200 and result.json()['available'] is True
    assert 'private_provider_field' not in result.json()
    result=client.get('/api/satellite/'+kind+'/FIELD-TEST-01?date_from=2026-09-01&date_to=2026-09-30',auth=('pytest','pytest'))
    assert result.status_code==200 and result.content==image
    assert result.headers['content-type']=='image/jpeg'
    # Stage 2 legacy lookup (without explicit query dates) still works.
    assert client.get('/api/satellite/'+kind+'/FIELD-TEST-01',auth=('pytest','pytest')).content==image


@pytest.mark.parametrize('kind',['image','ndvi'])
def test_cache_miss_is_neutral_and_never_fetches(satellite,kind):
    client,seed,mode,api,image=satellite
    result=client.get('/api/review/satellite-cache/'+kind+'/FIELD-TEST-01',auth=('pytest','pytest'))
    assert result.status_code==200 and result.json()=={'available':False,'message':'Satellite image not available in review mode'}
    result=client.get('/api/satellite/'+kind+'/FIELD-TEST-01?date_from=2026-09-01&date_to=2026-09-30',auth=('pytest','pytest'))
    assert result.status_code==404
    assert result.json()['message']=='Satellite image not available in review mode'


@pytest.mark.parametrize('query',['date_from=2024-06-01&date_to=2024-06-30','date_from=2026-08-01&date_to=2026-08-31','date_from=2026-09-01'])
def test_wrong_range_never_mislabels_cached_raster(satellite,query):
    client,seed,*_=satellite;seed()
    assert client.get('/api/satellite/image/FIELD-TEST-01?'+query,auth=('pytest','pytest')).status_code==404


def test_corrupt_or_half_written_pair_is_unavailable(satellite):
    client,seed,mode,api,image=satellite;path,meta=seed()
    path.write_bytes(b'different bytes')
    response=client.get('/api/review/satellite-cache/image/FIELD-TEST-01',auth=('pytest','pytest'))
    assert response.json()['available'] is False
    assert client.get('/api/satellite/image/FIELD-TEST-01?date_from=2026-09-01&date_to=2026-09-30',auth=('pytest','pytest')).status_code==404


def test_metadata_paths_cannot_escape_cache(satellite,tmp_path):
    client,seed,mode,api,image=satellite;path,meta=seed()
    outside=tmp_path/'outside.json';outside.write_text(json.dumps(meta))
    path.with_suffix('.json').unlink();path.with_suffix('.json').symlink_to(outside)
    assert mode.cached_satellite_metadata('image','FIELD-TEST-01') is None
    assert mode.cached_satellite_metadata('image','../../outside') is None


def test_metadata_handler_refuses_normal_mode(satellite,monkeypatch):
    client,seed,mode,api,image=satellite
    from fastapi import HTTPException
    monkeypatch.setattr(mode,'ENABLED',False)
    with pytest.raises(HTTPException) as error:api.review_satellite_metadata('image','FIELD-TEST-01')
    assert error.value.status_code==404


def test_satellite_overlay_not_injected_in_normal_mode(monkeypatch):
    import api
    from services import review_mode
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    monkeypatch.delenv('UI_LANGUAGE',raising=False)
    monkeypatch.delenv('INSTANCE_DISPLAY_NAME',raising=False)
    monkeypatch.setattr(review_mode,'ENABLED',False)
    before=Path('index.html').read_bytes()
    assert api.serve_index().body==before
    monkeypatch.setattr(review_mode,'ENABLED',True)
    assert b'/assets/review-satellite.js' in api.serve_index().body


def test_review_satellite_frontend_caption_dates_and_misses():
    import subprocess
    subprocess.run(['node',str(Path(__file__).with_name('review_satellite_checks.cjs'))],check=True,capture_output=True,text=True)
