"""Deployment delivery contracts, with temporary frontend files only."""
import hashlib
from pathlib import Path


def test_served_frontend_is_versioned_and_cannot_reuse_stale_html(tmp_path,monkeypatch):
    import api
    root=Path(__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path);monkeypatch.delenv('UI_LANGUAGE',raising=False)
    Path('assets').mkdir()
    Path('index.html').write_text((root/'index.html').read_text())
    Path('assets/lvm-geodata.js').write_text('/* isolated delivery fixture */')
    Path('assets/vmd-production.js').write_text('/* isolated VMD fixture */')
    expected=hashlib.sha256(Path('assets/vmd-production.js').read_bytes()).hexdigest()[:12]
    first=api.serve_index();html=first.body.decode();version=api.frontend_deployment()['version']
    assert first.headers['cache-control']=='no-store, max-age=0'
    assert first.headers['x-forest-deployment']==version
    assert 'FOREST_GEODATA_ENABLED=true' in html
    assert '/assets/vmd-production.js?v='+expected in html
    assert 'Versija: '+version in html
    assert '<meta name="forest-deployment" content="'+version+'">' in html
    Path('assets/vmd-production.js').write_text('/* changed isolated VMD fixture */')
    second=api.serve_index()
    assert second.headers['x-forest-deployment']!=version
    assert '/assets/vmd-production.js?v='+expected not in second.body.decode()
    assert api.frontend_deployment()['backend_revision']==api._BACKEND_REVISION


def test_script_responses_require_revalidation(tmp_path,monkeypatch):
    import api
    monkeypatch.chdir(tmp_path);Path('assets').mkdir();Path('assets/test.js').write_text('// unit test')
    response=api.serve_asset('test.js')
    assert response.headers['cache-control']=='private, no-cache, must-revalidate'
