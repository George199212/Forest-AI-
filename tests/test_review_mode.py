"""
Review mode (ACCESS_MODE=review, services/review_mode.py) and file-route containment tests.

Run: python3 -m pytest tests/test_review_mode.py -v

Like test_provenance.py this file imports project modules only inside fixtures, so it does not
change DB_PATH for test_integrations.py. Review mode is normally decided once at import time;
here the middleware is wrapped around api.app explicitly and review_mode.ENABLED is patched,
which exercises the same code paths. test_middleware_installed_only_in_review_mode checks the
import-time switch itself in a subprocess. data/forest_ai.db is never used.
"""

import asyncio
import base64
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

import pytest

AUTH = ("pytest", "pytest")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
api = review_mode = database = None  # bound by the fixture


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    global api, review_mode, database
    if "DB_PATH" not in os.environ:  # running this file alone: never fall back to data/forest_ai.db
        boot = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        boot.close()
        os.environ["DB_PATH"] = boot.name
    os.environ.setdefault("INTEGRATION_CREDENTIALS_KEY", "pytest-test-key-not-for-production")
    os.environ.setdefault("DASHBOARD_USERNAME", AUTH[0])
    os.environ.setdefault("DASHBOARD_PASSWORD", AUTH[1])
    monkeypatch.setenv("DASHBOARD_USERNAME", AUTH[0])
    monkeypatch.setenv("DASHBOARD_PASSWORD", AUTH[1])
    import api as _api
    import database as _database
    from services import review_mode as _review_mode
    api, review_mode, database = _api, _review_mode, _database

    db = str(tmp_path / "review.db")
    monkeypatch.setattr(database, "DB_NAME", db)
    monkeypatch.setattr(api, "DB_NAME", db)
    database.init_db()

    # Isolated file roots: tmp/assets, tmp/data/work_photos, tmp/data/satellite_cache
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "ok.js").write_text("// ok")
    (tmp_path / "data" / "work_photos").mkdir(parents=True)
    (tmp_path / "data" / "work_photos" / "p.jpg").write_bytes(b"\xff\xd8jpeg")
    (tmp_path / "secret.env").write_text("SECRET=1")
    monkeypatch.setattr(api, "ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(api, "PHOTOS_DIR", tmp_path / "data" / "work_photos")
    monkeypatch.setattr(api, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(review_mode, "SATELLITE_CACHE_DIR", tmp_path / "data" / "satellite_cache")
    review_mode._auth_failures.clear()

    # No test may reach a paid or outbound API: block the network layer itself
    import urllib.request
    from services import ai_resolution, photo_compare, risk_conclusion
    def _forbidden(*a, **k):
        raise AssertionError("paid/outbound call attempted")
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)
    for name in ("get", "post", "put", "patch", "delete", "request"):
        monkeypatch.setattr(api.requests, name, _forbidden)
    monkeypatch.setattr(api, "_get_anthropic_client", _forbidden)
    for mod in (ai_resolution, photo_compare, risk_conclusion):
        if hasattr(mod, "_get_client"):
            monkeypatch.setattr(mod, "_get_client", _forbidden)
    monkeypatch.setattr(api, "_token_cache", {"token": None, "expires": 0})
    yield tmp_path


def _installed():
    """True when this pytest process imported api with ACCESS_MODE=review."""
    return any(m.cls is review_mode.ReviewModeMiddleware for m in api.app.user_middleware)


def _review_app():
    return api.app if _installed() else review_mode.ReviewModeMiddleware(api.app)


@pytest.fixture
def review(monkeypatch):
    """TestClient for the app as served with ACCESS_MODE=review (startup hook runs)."""
    from fastapi.testclient import TestClient
    started = []
    monkeypatch.setattr(review_mode, "ENABLED", True)
    monkeypatch.setattr(api.risk_ai_worker, "start", lambda: started.append(1))
    with TestClient(_review_app()) as c:
        c.worker_started = started
        yield c


@pytest.fixture
def anyclient():
    """Plain TestClient on api.app in whatever mode the process was imported (GET-only tests)."""
    from fastapi.testclient import TestClient
    with TestClient(api.app) as c:
        yield c


@pytest.fixture
def normal(monkeypatch):
    """TestClient for the app with ACCESS_MODE unset (no middleware)."""
    from fastapi.testclient import TestClient
    if _installed():
        pytest.skip("this pytest process imported api with ACCESS_MODE=review")
    started = []
    monkeypatch.setattr(review_mode, "ENABLED", False)
    monkeypatch.setattr(api.risk_ai_worker, "start", lambda: started.append(1))
    with TestClient(api.app) as c:
        c.worker_started = started
        yield c


def _fill(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def _routes():
    from fastapi.routing import APIRoute
    return [r for r in api.app.routes if isinstance(r, APIRoute)]


def raw_get(app, path, auth=True):
    """Send a GET exactly as given (no client-side '..' normalisation), the way uvicorn would
    present it: scope['path'] percent-decoded, raw_path as sent. Returns (status, body)."""
    from urllib.parse import unquote
    headers = [(b"host", b"testserver")]
    if auth:
        headers.append((b"authorization", b"Basic " + base64.b64encode(f"{AUTH[0]}:{AUTH[1]}".encode())))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": unquote(path), "raw_path": path.encode(), "root_path": "",
             "query_string": b"", "headers": headers, "client": ("127.0.0.1", 5000),
             "server": ("testserver", 80)}
    out = {"status": None, "body": b""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return out["status"], out["body"]


# ── review mode guard ─────────────────────────────────────────────────────────

def test_every_non_get_route_is_403(review):
    checked = 0
    for r in _routes():
        for m in sorted(r.methods - {"GET", "HEAD"}):
            resp = review.request(m, _fill(r.path), auth=AUTH, json={})
            assert resp.status_code == 403, (m, r.path, resp.status_code)
            assert resp.json() == {"detail": "read_only_review_mode"}
            checked += 1
    assert checked >= 40
    for m in ("OPTIONS", "TRACE", "PROPFIND"):
        assert review.request(m, "/api/sectors", auth=AUTH).status_code == 403


def test_non_get_refused_before_auth(review):
    assert review.post("/api/sectors", json={}).status_code == 403
    assert review.delete("/api/sectors/X").status_code == 403


@pytest.mark.parametrize("path", [
    "/api/inspector/analyze/SEC-1", "/api/inspector/analyze-all", "/api/inspector/analyze-all/",
    "/api/satellite/token-check",
])
def test_paid_gets_are_403(review, path):
    for method in ("GET", "HEAD"):
        resp = review.request(method, path, auth=AUTH)
        assert resp.status_code == 403, (method, path)


@pytest.mark.parametrize("path", ["//api/inspector/analyze-all", "/api//inspector/analyze-all",
                                  "/api/inspector//analyze/SEC-1", "//docs", "//openapi.json"])
def test_double_slash_variants_refused(monkeypatch, path):
    monkeypatch.setattr(review_mode, "ENABLED", True)
    status, _ = raw_get(_review_app(), path)
    assert status in (403, 404), (path, status)


@pytest.mark.parametrize("path", [
    "/docs", "/docs/", "/docs/oauth2-redirect", "/redoc", "/openapi.json",
    "/api/webhooks", "/api/webhooks/docs", "/api/webhooks/openapi.json", "/api/webhooks/redoc",
])
def test_internal_docs_and_webhooks_are_404(review, path):
    assert review.get(path, auth=AUTH).status_code == 404
    assert review.get(path).status_code == 404


def test_webhook_post_is_404_and_writes_nothing(review):
    assert review.post("/api/webhooks/testprovider", content=b"{}").status_code == 404
    conn = sqlite3.connect(database.DB_NAME)
    assert conn.execute("SELECT COUNT(*) FROM integration_webhook_events").fetchone()[0] == 0
    conn.close()


def test_normal_gets_return_200(review):
    deny = re.compile(r"^/api/(inspector/analyze|satellite/token-check)")
    checked = 0
    for r in _routes():
        if "GET" not in r.methods or "{" in r.path or deny.match(r.path):
            continue
        resp = review.get(r.path, auth=AUTH)
        assert resp.status_code == 200, (r.path, resp.status_code)
        checked += 1
    assert checked >= 20


def test_gets_still_require_login(review):
    assert review.get("/api/sectors").status_code == 401
    assert review.get("/api/sectors", auth=AUTH).status_code == 200


@pytest.mark.parametrize("kind,path", [("image", "/api/satellite/image/SEC-1"),
                                       ("ndvi", "/api/satellite/ndvi/SEC-1"),
                                       ("object", "/api/satellite/object/1")])
def test_satellite_served_only_from_cache(review, env, kind, path):
    resp = review.get(path, auth=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "satellite_not_cached"
    key = path.rsplit("/", 1)[1]
    cache = env / "data" / "satellite_cache" / kind
    cache.mkdir(parents=True)
    (cache / f"{key}.jpg").write_bytes(b"\xff\xd8cached")
    resp = review.get(path, auth=AUTH)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == b"\xff\xd8cached"


def test_provider_status_makes_no_copernicus_call(review):
    # Sentinel provider.is_configured() calls get_sentinel_token(); in review mode that must
    # return None without network I/O (urlopen is blocked by the fixture)
    resp = review.get("/api/satellite-intel/providers", auth=AUTH)
    assert resp.status_code == 200
    assert api.get_sentinel_token() is None


def test_satellite_cache_key_cannot_escape(env):
    (env / "data" / "satellite_cache" / "image").mkdir(parents=True)
    assert review_mode.cached_satellite_file("image", "../../secret") is None
    assert review_mode.cached_satellite_file("image", "..") is None
    assert review_mode.cached_satellite_file("bogus", "SEC-1") is None


def test_sector_satellite_redirect_ends_in_cache_404(review):
    # no uploaded file -> redirect to the live route -> cache-only 404, never Sentinel
    resp = review.get("/api/sectors/SEC-1/satellite-image", auth=AUTH)
    assert resp.status_code == 404


def test_worker_not_started_in_review_mode(review):
    assert review.worker_started == []


def test_worker_started_when_access_mode_unset(normal):
    assert normal.worker_started == [1]


def test_failed_login_rate_limit(review):
    for _ in range(review_mode.AUTH_FAIL_LIMIT):
        assert review.get("/api/sectors", auth=("pytest", "wrong")).status_code == 401
    # blocked now, even with the right password
    assert review.get("/api/sectors", auth=AUTH).status_code == 429
    review_mode._auth_failures.clear()
    assert review.get("/api/sectors", auth=AUTH).status_code == 200


def test_requests_without_credentials_do_not_count_as_failures(review):
    for _ in range(review_mode.AUTH_FAIL_LIMIT + 5):
        assert review.get("/api/sectors").status_code == 401
    assert review.get("/api/sectors", auth=AUTH).status_code == 200


# ── ACCESS_MODE unset: nothing changes ────────────────────────────────────────

def test_normal_mode_writes_not_blocked(normal):
    resp = normal.put("/api/sectors/NOPE", auth=AUTH, json={})
    assert resp.status_code != 403
    assert normal.get("/openapi.json").status_code == 200  # unchanged (finding reported, not fixed here)


def test_normal_mode_no_rate_limit(normal):
    for _ in range(15):
        assert normal.get("/api/sectors", auth=("pytest", "wrong")).status_code == 401
    assert normal.get("/api/sectors", auth=AUTH).status_code == 200


@pytest.mark.parametrize("mode,expected", [("review", True), ("", False), ("REVIEW", True), ("demo", False)])
def test_middleware_installed_only_in_review_mode(tmp_path, mode, expected):
    env = {k: v for k, v in os.environ.items() if k != "ACCESS_MODE"}
    if mode:
        env["ACCESS_MODE"] = mode
    env["DB_PATH"] = str(tmp_path / "sub.db")
    code = ("import api; from services.review_mode import ReviewModeMiddleware as M;"
            "print(any(m.cls is M for m in api.app.user_middleware))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == str(expected)


# ── path traversal: file routes (both modes) ──────────────────────────────────

TRAVERSAL = [
    "/assets/../.env", "/assets/..%2F.env", "/assets/%2e%2e/.env", "/assets/%2e%2e%2f.env",
    "/assets/..", "/assets/%2e%2e", "/assets/.", "/assets/%2Fetc%2Fpasswd", "/assets//etc/passwd",
    "/assets/..%5C.env", "/assets/api.py", "/assets/..%2Fapi.py", "/assets/..%2Fsecret.env",
    "/photos/file/..", "/photos/file/%2e%2e", "/photos/file/..%2F..%2Fsecret.env",
    "/photos/file/%2Fetc%2Fpasswd", "/photos/file/.",
]


@pytest.mark.parametrize("mode", ["normal", "review"])
@pytest.mark.parametrize("path", TRAVERSAL)
def test_traversal_urls_never_serve_files(monkeypatch, mode, path):
    monkeypatch.setattr(review_mode, "ENABLED", mode == "review")
    app = _review_app() if mode == "review" else api.app
    status, body = raw_get(app, path)
    assert status in (403, 404), (path, status)
    assert b"SECRET" not in body and b"root:" not in body and b"import " not in body


def test_legit_files_still_served(anyclient):
    assert anyclient.get("/assets/ok.js", auth=AUTH).text == "// ok"
    assert anyclient.get("/photos/file/p.jpg", auth=AUTH).status_code == 200


def test_symlinks_out_of_root_are_refused(anyclient, env):
    normal = anyclient
    (env / "assets" / "link.js").symlink_to(env / "secret.env")
    (env / "data" / "work_photos" / "link.jpg").symlink_to(env / "secret.env")
    (env / "assets" / "inside.js").symlink_to(env / "assets" / "ok.js")
    assert normal.get("/assets/link.js", auth=AUTH).status_code == 404
    assert normal.get("/photos/file/link.jpg", auth=AUTH).status_code == 404
    assert normal.get("/assets/inside.js", auth=AUTH).status_code == 200


@pytest.mark.parametrize("stored", ["ABS_SECRET", "data/../secret.env", "/etc/passwd", "DATA_DIR", "LINK"])
def test_db_stored_paths_must_stay_inside_data(anyclient, env, stored):
    normal = anyclient
    (env / "data" / "evil.jpg").symlink_to(env / "secret.env")
    value = {"ABS_SECRET": str(env / "secret.env"), "DATA_DIR": str(env / "data"),
             "LINK": str(env / "data" / "evil.jpg")}.get(stored, stored)
    conn = sqlite3.connect(database.DB_NAME)
    rid = conn.execute("INSERT INTO risks (sector, risk_level, reason, created_at, status, photo_path, photo_path_2) "
                       "VALUES ('SEC-1', 'LOW', 'x', datetime('now'), 'OPEN', ?, ?)", (value, value)).lastrowid
    pid = conn.execute("INSERT INTO boundary_plans (file_path, satellite_file_path) VALUES (?, ?)",
                       (value, value)).lastrowid
    conn.execute("INSERT INTO sectors (name, contractor, status, approved_volume, satellite_file_path, created_at) "
                 "VALUES ('SEC-X', 'C', 'Active', '1', ?, datetime('now'))", (value,))
    sid = conn.execute("INSERT INTO sector_snapshots (sector, image_path, uploaded_at) VALUES ('SEC-1', ?, datetime('now'))",
                       (value,)).lastrowid
    conn.commit()
    conn.close()
    for url in (f"/api/risks/{rid}/photo", f"/api/risks/{rid}/photo2", f"/api/boundary-plans/{pid}/scan",
                f"/api/sectors/snapshots/{sid}/image"):
        resp = normal.get(url, auth=AUTH)
        assert resp.status_code == 404, (url, stored, resp.status_code)
        assert b"SECRET" not in resp.content and b"root:" not in resp.content
    for url in (f"/api/objects/{pid}/satellite-image", "/api/sectors/SEC-X/satellite-image"):
        resp = normal.get(url, auth=AUTH, follow_redirects=False)
        assert resp.status_code in (307, 404), (url, stored, resp.status_code)  # 307 -> live route, not the file
        assert b"SECRET" not in resp.content


def test_db_stored_path_inside_data_still_served(anyclient, env):
    normal = anyclient
    good = env / "data" / "work_photos" / "p.jpg"
    conn = sqlite3.connect(database.DB_NAME)
    rid = conn.execute("INSERT INTO risks (sector, risk_level, reason, created_at, status, photo_path) "
                       "VALUES ('SEC-1', 'LOW', 'x', datetime('now'), 'OPEN', ?)", (str(good),)).lastrowid
    conn.commit()
    conn.close()
    assert normal.get(f"/api/risks/{rid}/photo", auth=AUTH).content == b"\xff\xd8jpeg"
