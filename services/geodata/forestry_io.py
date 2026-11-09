"""Bounded streaming reader for this archive's dBase III / 2D Polygon SHP files.

No generic GIS driver is claimed. Unknown field/shape/CRS definitions fail closed.
Projection: inverse EPSG:9807 using the exact archive LKS-2020/Latvia TM
(EPSG:10306) parameters; GRS80 geographic coordinates to WGS84 use EPSG:10840's
zero-shift approximation (1 m datum accuracy). No LKS-92 shortcut is used.
"""
import json
import math
import re
import struct
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon, MultiPolygon

A = 6378137.0
F = 1 / 298.257222101
E2 = F * (2-F)
EP2 = E2/(1-E2)
K = .9996


def to_wgs84(xy):
    x, y = xy[:, 0], xy[:, 1]
    m = (y+6000000)/K
    mu = m/(A*(1-E2/4-3*E2**2/64-5*E2**3/256))
    e1=(1-math.sqrt(1-E2))/(1+math.sqrt(1-E2))
    p=mu+(3*e1/2-27*e1**3/32)*np.sin(2*mu)+(21*e1**2/16-55*e1**4/32)*np.sin(4*mu)+151*e1**3/96*np.sin(6*mu)+1097*e1**4/512*np.sin(8*mu)
    n=A/np.sqrt(1-E2*np.sin(p)**2);r=A*(1-E2)/(1-E2*np.sin(p)**2)**1.5
    t=np.tan(p)**2;c=EP2*np.cos(p)**2;d=(x-500000)/(n*K)
    lat=p-n*np.tan(p)/r*(d**2/2-(5+3*t+10*c-4*c*c-9*EP2)*d**4/24+(61+90*t+298*c+45*t*t-252*EP2-3*c*c)*d**6/720-(1385+3633*t+4095*t*t+1575*t**3)*d**8/40320)
    lon=np.radians(24)+(d-(1+2*t+c)*d**3/6+(5-2*c+28*t-3*c*c+8*EP2+24*t*t)*d**5/120-(61+662*t+1320*t*t+720*t**3)*d**7/5040)/np.cos(p)
    return np.column_stack((np.degrees(lon), np.degrees(lat)))


def to_source(xy):
    lon,lat=np.radians(xy[:,0]),np.radians(xy[:,1])
    n=A/np.sqrt(1-E2*np.sin(lat)**2);t=np.tan(lat)**2;c=EP2*np.cos(lat)**2;a=np.cos(lat)*(lon-np.radians(24))
    m=A*((1-E2/4-3*E2**2/64-5*E2**3/256)*lat-(3*E2/8+3*E2**2/32+45*E2**3/1024)*np.sin(2*lat)+(15*E2**2/256+45*E2**3/1024)*np.sin(4*lat)-35*E2**3/3072*np.sin(6*lat))
    x=500000+K*n*(a+(1-t+c)*a**3/6+(5-18*t+t*t+72*c-58*EP2)*a**5/120+(61-479*t+179*t*t-t**3)*a**7/5040)
    y=-6000000+K*(m+n*np.tan(lat)*(a*a/2+(5-t+9*c+4*c*c)*a**4/24+(61-58*t+t*t+600*c-330*EP2)*a**6/720+(1385-3111*t+543*t*t-t**3)*a**8/40320))
    return np.column_stack((x,y))


def equal_area(xy):
    """GRS80 ellipsoidal cylindrical equal area (EPSG:6933 equations), metres."""
    lon,lat=np.radians(xy[:,0]),np.radians(xy[:,1]);e=math.sqrt(E2);s=np.sin(lat)
    k0=math.cos(math.pi/6)/math.sqrt(1-E2*.25)
    q=(1-E2)*(s/(1-E2*s*s)-np.log((1-e*s)/(1+e*s))/(2*e))
    return np.column_stack((A*k0*lon,A*q/(2*k0)))


def schema(path):
    path=Path(path)
    with path.open('rb') as f:
        h=f.read(32)
        if len(h)!=32:raise ValueError('Truncated DBF header')
        count=struct.unpack_from('<I',h,4)[0];header,size=struct.unpack_from('<HH',h,8)
        if header<33 or header>65535 or size<2:raise ValueError('Invalid DBF header')
        desc=f.read(header-32)
    fields=[];offset=1
    for start in range(0,len(desc)-31,32):
        if desc[start]==13:break
        b=desc[start:start+32];name=b[:11].split(b'\0')[0].decode('ascii');kind=chr(b[11]);length=b[16]
        if kind not in {'C','N','F','L','D'} or not length:raise ValueError('Unsupported DBF field')
        fields.append({'name':name,'type':kind,'length':length,'decimals':b[17],'offset':offset});offset+=length
    if offset!=size:raise ValueError('DBF record size mismatch')
    if len({f['name'].casefold() for f in fields})!=len(fields):raise ValueError('Duplicate DBF attribute names; refusing attribute loss')
    return {'feature_count':count,'header_bytes':header,'record_bytes':size,'fields':fields}


def inspect(path):
    path=Path(path);meta=schema(path.with_suffix('.dbf'))
    with path.open('rb') as f:h=f.read(100)
    if len(h)!=100 or struct.unpack_from('>I',h)[0]!=9994 or struct.unpack_from('<I',h,28)[0]!=1000:raise ValueError('Invalid SHP header')
    kind=struct.unpack_from('<I',h,32)[0]
    if kind!=5:raise ValueError('This ingest supports the supplied 2D Polygon SHP only')
    prj=path.with_suffix('.prj').read_text();compact=re.sub(r'\s+','',prj)
    ellipsoid=re.search(r'SPHEROID\["[^"]+",([-0-9.]+),([-0-9.]+)\]',compact)
    if not ellipsoid or float(ellipsoid.group(1))!=A or float(ellipsoid.group(2))!=298.257222101:raise ValueError('Unexpected source ellipsoid')
    expected={'False_Easting':500000,'False_Northing':-6000000,'Central_Meridian':24,'Scale_Factor':.9996,'Latitude_Of_Origin':0}
    if 'LKS-2020' not in prj or 'Transverse_Mercator' not in prj or '298.257222101' not in prj:raise ValueError('Unsupported source CRS; refusing a guessed transformation')
    for key,value in expected.items():
        match=re.search(r'PARAMETER\["'+key+r'",([-0-9.]+)\]',compact)
        if not match or float(match.group(1))!=value:raise ValueError('Unexpected source projection parameter')
    encoding=path.with_suffix('.cpg').read_text().strip()
    if encoding.upper() not in {'UTF-8','UTF8','65001'}:raise ValueError('Unexpected DBF encoding')
    shx_records=(path.with_suffix('.shx').stat().st_size-100)//8
    if shx_records!=meta['feature_count']:raise ValueError('SHP/DBF record count mismatch')
    return {**meta,'path':str(path),'layer':path.stem,'geometry_type':'Polygon','source_crs':'EPSG:10306','source_wkt':prj,'encoding':encoding,'extent':struct.unpack_from('<4d',h,36)}


def records(path,meta):
    """Yield source row, all original attributes, geometry or a recorded error."""
    path=Path(path)
    with path.open('rb') as shp,path.with_suffix('.dbf').open('rb') as dbf:
        shp.seek(100);dbf.seek(meta['header_bytes'])
        for index in range(1,meta['feature_count']+1):
            header=shp.read(8)
            if len(header)!=8:raise ValueError('Truncated SHP record header')
            number,words=struct.unpack('>2I',header)
            if number!=index or not 2<=words<=16*1024*1024:raise ValueError('Invalid SHP record length/sequence')
            body=shp.read(words*2);raw=dbf.read(meta['record_bytes'])
            if len(body)!=words*2 or len(raw)!=meta['record_bytes']:raise ValueError('Truncated source record')
            props={}
            for field in meta['fields']:
                value=raw[field['offset']:field['offset']+field['length']].decode('utf-8').strip(' \0')
                if field['type'] in {'N','F'}:
                    try:value=float(value) if '.' in value or 'e' in value.lower() else int(value)
                    except ValueError:value=None if not value else value
                    if isinstance(value,float) and not math.isfinite(value):value=str(value)
                elif field['type']=='L':value=value.upper() in {'Y','T'} if value else None
                props[field['name']]=value
            if raw[:1]==b'*':yield index,props,None,'DBF record is marked deleted';continue
            try:
                g=polygon_record(body)
                yield index,props,g,None
            except (ValueError,struct.error) as exc:yield index,props,None,str(exc)
        if shp.read(1):raise ValueError('Unexpected extra SHP records')


def polygon_record(body):
    if struct.unpack_from('<I',body)[0]!=5:raise ValueError('Null or non-polygon SHP record')
    parts,points=struct.unpack_from('<2I',body,36)
    if parts<1 or points<4 or parts>points or 44+4*parts+16*points>len(body):raise ValueError('Invalid Polygon record')
    starts=list(struct.unpack_from('<'+str(parts)+'I',body,44))+[points]
    if starts[0]!=0 or any(a>=b for a,b in zip(starts,starts[1:])):raise ValueError('Invalid ring offsets')
    xy=np.frombuffer(body,dtype='<f8',count=2*points,offset=44+4*parts).reshape((-1,2))
    if not np.isfinite(xy).all():raise ValueError('Nonfinite source coordinates')
    rings=[xy[a:b] for a,b in zip(starts,starts[1:])]
    if any(len(r)<4 or not np.array_equal(r[0],r[-1]) for r in rings):raise ValueError('Unclosed source ring')
    if len(rings)==1:g=Polygon(rings[0])
    else:
        ring_polys=[Polygon(r) for r in rings];parents={};depth={}
        for i in sorted(range(len(rings)),key=lambda i:ring_polys[i].area,reverse=True):
            candidates=[j for j in depth if ring_polys[j].area>ring_polys[i].area and ring_polys[j].covers(ring_polys[i].representative_point())]
            parent=min(candidates,key=lambda j:ring_polys[j].area) if candidates else None
            parents[i]=parent;depth[i]=depth[parent]+1 if parent is not None else 0
        polygons=[Polygon(rings[i],[rings[j] for j in range(len(rings)) if parents[j]==i and depth[j]%2]) for i in range(len(rings)) if not depth[i]%2]
        g=polygons[0] if len(polygons)==1 else MultiPolygon(polygons)
    return g


def original_geometry(path, row):
    """Read one original SHP record via its SHX offset, without scanning the dataset."""
    path=Path(path)
    if not isinstance(row,int) or row<1:raise ValueError('Invalid source row')
    with path.with_suffix('.shx').open('rb') as index:
        index.seek(100+(row-1)*8);entry=index.read(8)
    if len(entry)!=8:raise ValueError('Missing source geometry index')
    offset,words=struct.unpack('>2I',entry)
    if not 2<=words<=16*1024*1024:raise ValueError('Invalid source geometry size')
    with path.open('rb') as source:
        source.seek(offset*2);header=source.read(8);body=source.read(words*2)
    if len(header)!=8 or struct.unpack('>2I',header)!=(row,words) or len(body)!=words*2:raise ValueError('Source geometry index mismatch')
    return polygon_record(body)
