"""Validate a staged national release and atomically activate only tested releases.
Never mutates the operational Forest AI database. Keeps the previous pointer.
"""
import argparse,hashlib,json,os,sqlite3,sys
from pathlib import Path
from datetime import datetime,timezone,date
ROOT=Path(__file__).resolve().parents[1]

def check(manifest,activate=False):
    manifest=Path(manifest).resolve();m=json.loads(manifest.read_text());folder=Path(m['root']);sources=m['sources']
    assert m['status']=='READY' and m['schema']==1 and len(sources)==47
    assert len({x['id'] for x in sources})==47
    assert sum(x['kind']=='vmd' and x['validated'] for x in sources)==5 and sum(x['kind']=='vzd' and x['validated'] for x in sources)==42
    for source in sources:
        archive=folder/'downloads'/(source['id']+('.7z' if source['kind']=='vmd' else '.zip'))
        assert archive.stat().st_size==source['size']
        with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==source['archive_sha256']
        marker=json.loads((folder/'sources'/source['kind']/source['id']/'archive-verified.json').read_text());assert marker['crc_validated'] is True and marker['sha256']==source['archive_sha256']
    counts={}
    for kind,table,key in [('vmd','compartments','forest_db'),('vzd','parcels','parcel_db')]:
        with sqlite3.connect('file:'+m[key]+'?mode=ro',uri=True) as c:
            assert c.execute('SELECT count(*) FROM files WHERE complete!=1').fetchone()[0]==0
            count=c.execute('SELECT count(*) FROM '+table).fetchone()[0];total=c.execute('SELECT sum(total_rows) FROM files').fetchone()[0];rejected=c.execute('SELECT count(*) FROM rejections').fetchone()[0];duplicates=c.execute('SELECT count(*) FROM duplicate_sources').fetchone()[0]
            assert count==m['reports'][kind]['indexed'] and count+rejected+duplicates==total
            assert c.execute('SELECT count(*) FROM spatial_index').fetchone()[0]==count
            if kind=='vmd':assert c.execute('SELECT count(*) FROM native_index').fetchone()[0]==count
            assert c.execute('SELECT count(*) FROM '+table+' WHERE length('+('kadastrs' if kind=='vmd' else 'designation')+")!=11 OR "+('kadastrs' if kind=='vmd' else 'designation')+" GLOB '*[^0-9]*'").fetchone()[0]==0
            for (raw,) in c.execute('SELECT meta FROM files'):
                metadata=json.loads(raw);assert date.fromisoformat(metadata['export_date'])<=date.today();assert metadata['source_crs'] in ['EPSG:10306','EPSG:3059']
            assert c.execute("SELECT rtreecheck('spatial_index')").fetchone()[0]=='ok'
            if kind=='vmd':assert c.execute("SELECT rtreecheck('native_index')").fetchone()[0]=='ok'
            counts[kind]={'indexed':count,'source_records':total,'quarantined':rejected,'deduplicated':duplicates}
    acceptance=json.loads((folder/'staging-acceptance.json').read_text())
    assert acceptance['status']=='PASSED' and acceptance['dataset_version']==m['version'] and acceptance['tested_units']>=10 and acceptance['registrations']>=10
    assert acceptance['pagination_all_results_verified']>100 and acceptance['pagination_selection_preserved'] and acceptance['explicit_503_recovery_verified']
    assert len(acceptance['regions_tested'])==5 and acceptance['refresh_restart_fresh_login_persistence']
    assert all(c['registration_succeeded'] and c['original_dbf_and_shp_verified'] and c['source_geometry_preserved'] and c['duplicate_prevented'] for c in acceptance['cases'])
    proof={'checked_at':datetime.now(timezone.utc).isoformat(),'dataset_version':m['version'],'sources_validated':47,'counts':counts,'staging_acceptance':'PASSED','activated':activate}
    if activate:
        target=ROOT/'data/geodata/nationwide/active.json';target.parent.mkdir(exist_ok=True,parents=True)
        if target.exists():
            backup=folder/('previous-active-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json');backup.write_bytes(target.read_bytes())
        tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(m,ensure_ascii=False));os.replace(tmp,target)
    (folder/'publication-check.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof,indent=2));return proof

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--activate',action='store_true');a=p.parse_args();check(a.manifest,a.activate)
