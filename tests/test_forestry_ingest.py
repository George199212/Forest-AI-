"""Projection/reader checks against real source and an independent PROJ reference."""
from pathlib import Path
import json,numpy as np,pytest,shapely
from shapely.geometry import shape
from services.geodata.forestry_io import to_wgs84,to_source,equal_area,inspect,records

def test_independent_proj_transverse_mercator_reference():
    # PROJ project mailing-list reference: lon=13.100962,lat=55.600783,
    # lon_0=15, GRS80, k=.9996 -> 380351.08,6163285.60.
    # Translate central meridian to 24 and false northing to -6000000.
    result=to_wgs84(np.array([[380351.08,163285.60]]))[0]
    assert abs(result[0]-22.100962)<1e-7 and abs(result[1]-55.600783)<1e-7

def test_projection_roundtrip_and_equal_area():
    points=np.array([[405229,234180],[500000,300000],[594509,363287]],dtype=float)
    assert np.max(np.abs(to_source(to_wgs84(points))-points))<.001
    p=shape({'type':'Polygon','coordinates':[[[24,56],[24.01,56],[24.01,56.01],[24,56.01],[24,56]]]})
    assert 600000<shapely.transform(p,equal_area).area<800000

def test_actual_source_header_attributes_and_independent_export():
    root=Path(__file__).resolve().parents[1];files=sorted((root/'data/vmd/source').rglob('nodala*.shp'))
    if not files:pytest.skip('Original source archive is not installed')
    assert len(files)==5
    meta=inspect(files[0]);row,props,g,error=next(records(files[0],meta))
    assert meta['source_crs']=='EPSG:10306' and len(meta['fields'])==88
    assert row==1 and not error and props['kadastrs']=='40940020002'
    reference=json.loads((root/'lvm_3_sectors.geojson').read_text())['features'][0]
    assert shapely.transform(g,to_wgs84).hausdorff_distance(shape(reference['geometry']))<2e-8
