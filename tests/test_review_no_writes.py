"""Review mode must never write: every GET route leaves DB content and data/ files unchanged.

Run: python3 -m pytest tests/test_review_no_writes.py -s   (-s prints the called / skipped route lists)

Builds a throw-away review instance in tmp_path: data/forest_ai.db from init_db() + the synthetic seed
(scripts/seed_review_demo.py), index.html and assets/ linked from the repo. Never touches data/forest_ai.db,
never reaches the network (outbound HTTP is replaced by an exception), never uses the national catalogue
unless FOREST_GEODATA_MANIFEST points at it (read-only).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AUTH = ('pytest', 'pytest')
os.environ.setdefault('DB_PATH', tempfile.NamedTemporaryFile(suffix='.db', delete=False).name)
os.environ.setdefault('INTEGRATION_CREDENTIALS_KEY', 'pytest-test-key-not-for-production')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_no_writes as rnw  # noqa: E402


@pytest.fixture
def instance(tmp_path, monkeypatch):
    root = tmp_path / 'instance'
    (root / 'data').mkdir(parents=True)
    (root / '.env').write_text('ACCESS_MODE=review\n')
    (root / 'index.html').symlink_to(REPO / 'index.html')
    (root / 'assets').symlink_to(REPO / 'assets')
    db = root / 'data' / 'forest_ai.db'
    monkeypatch.setenv('DASHBOARD_USERNAME', AUTH[0]); monkeypatch.setenv('DASHBOARD_PASSWORD', AUTH[1])
    monkeypatch.setenv('REVIEW_MAP_EXCLUDED_SECTORS', 'FIELD-TEST-01')
    import api, database
    from services import review_mode
    from services.satellite_intelligence import risk_score
    for mod in (api, database, risk_score):
        monkeypatch.setattr(mod, 'DB_NAME', str(db))
    database.init_db()
    env = {**os.environ, 'ACCESS_MODE': 'review', 'DB_PATH': str(db)}
    seeded = subprocess.run([sys.executable, str(REPO / 'scripts/seed_review_demo.py')], env=env, cwd=root,
                            capture_output=True, text=True)
    assert seeded.returncode == 0, seeded.stderr[-2000:]
    monkeypatch.chdir(root)
    monkeypatch.setattr(review_mode, 'ENABLED', True)
    monkeypatch.setattr(api.risk_ai_worker, 'start', lambda: None)
    # No outbound traffic of any kind (LVM GEO WMS/WFS, Sentinel, Anthropic, John Deere).
    import requests, urllib.request
    def offline(*a, **k):
        raise requests.ConnectionError('offline test')
    for name in ('get', 'post', 'request'):
        monkeypatch.setattr(requests, name, offline)
    monkeypatch.setattr(requests.Session, 'request', offline)
    monkeypatch.setattr(urllib.request, 'urlopen', offline)
    return api, review_mode, db, root


def test_every_get_route_leaves_db_content_and_files_unchanged(instance):
    api, review_mode, db, root = instance
    from fastapi.testclient import TestClient
    installed = any(m.cls is review_mode.ReviewModeMiddleware for m in api.app.user_middleware)
    app = api.app if installed else review_mode.ReviewModeMiddleware(api.app)
    with TestClient(app) as client:
        start_db, start_files = rnw.content_snapshot(db), rnw.files_snapshot(root / 'data')
        result = rnw.walk(api.app, client, db, root / 'data', AUTH)
        end_db, end_files = rnw.content_snapshot(db), rnw.files_snapshot(root / 'data')
    print(f"\nGET routes called: {len(result['called'])}")
    for path, status in result['called']:
        print(f'  {status}  {path}')
    print(f"GET routes SKIPPED: {len(result['skipped'])}")
    for path, why in result['skipped']:
        print(f'  SKIPPED {path}: {why}')
    print('journal:', start_db['journal_mode'], 'side files before/after:', start_db['side_files'], end_db['side_files'])
    called = {p for p, _ in result['called']}
    assert '/api/john-deere/status' in called and '/api/geodata/forest-map/gps/positions' in called
    assert len(called) >= 80, 'walker must reach included-router routes too'
    assert result['writers'] == [], f"GET routes wrote in review mode: {result['writers']}"
    assert start_db['tables'] == end_db['tables']
    assert start_files == end_files
