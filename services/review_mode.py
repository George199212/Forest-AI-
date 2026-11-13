"""
Read-only review mode (ACCESS_MODE=review).

A review instance lets external technical reviewers look at a working Forest AI
with synthetic data. In this mode the server itself guarantees that nothing
can be changed and nothing costs money:

* every request other than GET/HEAD is rejected with 403 read_only_review_mode
* GET routes that call paid APIs (Anthropic, Sentinel Hub) or expose internals
  (OpenAPI/Swagger) are refused
* the webhook sub-application is not reachable at all
* /api/satellite/image|ndvi|object/* are answered only from a local file cache
  (data/satellite_cache/<kind>/<key>.jpg), never from a live Sentinel call
* repeated wrong logins from one IP are answered with 429
* the background risk AI worker is not started (see api.py startup hook)

With ACCESS_MODE unset none of this is installed: api.py adds the middleware
only when ENABLED is true, so MAIN and client instances behave exactly as before.
The UI hides action buttons in review mode, but this module is the real protection.
"""

import json
import hashlib
import os
import re
import time
from pathlib import Path

ENABLED = os.environ.get("ACCESS_MODE", "").strip().lower() == "review"

ALLOWED_METHODS = {"GET", "HEAD"}

# Exact paths and prefixes (matched after collapsing "//" and dropping a trailing "/")
DENY_EXACT = {
    "/api/inspector/analyze-all",   # Anthropic
    "/api/satellite/token-check",   # Sentinel token request
}
DENY_PREFIXES = (
    "/api/inspector/analyze/",      # Anthropic
    "/api/report/pdf/",           # existing report contains untranslated UI text
)
HIDDEN_EXACT = {"/docs", "/redoc", "/openapi.json"}
HIDDEN_PREFIXES = ("/docs/", "/api/webhooks/")
HIDDEN_EXACT_EXTRA = {"/api/webhooks"}

SATELLITE_CACHE_DIR = Path("data/satellite_cache")
SATELLITE_KINDS = ("image", "ndvi", "object")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

AUTH_FAIL_LIMIT = 10
AUTH_FAIL_WINDOW_S = 600
_auth_failures: dict = {}   # ip -> [timestamps]; in-memory, reset on restart


def _normalize(path: str) -> str:
    path = re.sub(r"/{2,}", "/", path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def classify(method: str, path: str):
    """Return (status, detail) for a refused request, or None if it may proceed."""
    p = _normalize(path)
    if p in HIDDEN_EXACT or p in HIDDEN_EXACT_EXTRA or any(p.startswith(x) for x in HIDDEN_PREFIXES):
        return 404, "Not Found"
    if method.upper() not in ALLOWED_METHODS:
        return 403, "read_only_review_mode"
    if p in DENY_EXACT or any(p.startswith(x) for x in DENY_PREFIXES):
        return 403, "not_available_in_review_mode"
    return None


def _recent_failures(ip: str, now: float) -> list:
    ts = [t for t in _auth_failures.get(ip, []) if now - t < AUTH_FAIL_WINDOW_S]
    if ts:
        _auth_failures[ip] = ts
    else:
        _auth_failures.pop(ip, None)
    return ts


def auth_blocked(ip: str) -> bool:
    return len(_recent_failures(ip, time.time())) >= AUTH_FAIL_LIMIT


def record_auth_failure(ip: str) -> None:
    now = time.time()
    _auth_failures[ip] = _recent_failures(ip, now) + [now]
    if len(_auth_failures) > 5000:   # cheap bound on memory
        for k in list(_auth_failures)[:1000]:
            _auth_failures.pop(k, None)


def cached_satellite_file(kind: str, key) -> Path | None:
    """Path of a cached satellite JPEG for /api/satellite/<kind>/<key>, or None."""
    key = str(key)
    if kind not in SATELLITE_KINDS or not _SAFE_KEY.match(key):
        return None
    root = SATELLITE_CACHE_DIR.resolve()
    base = (root / kind).resolve()
    if base.parent != root:
        return None
    path = (base / f"{key}.jpg").resolve()
    if path.parent != base or not path.is_file():
        return None
    return path


def cached_satellite_metadata(kind: str, key):
    """Validated, public sidecar fields only; no network or writes."""
    path = cached_satellite_file(kind, key)
    if not path:
        return None
    sidecar = path.with_suffix(".json").resolve()
    if sidecar.parent != path.parent or not sidecar.is_file():
        return None
    try:
        data = json.loads(sidecar.read_text())
        window = data["date_window"]
        if (data["sector"] != str(key)
                or data["product"] != ("ndvi" if kind == "ndvi" else "true_color")
                or data["source"] != "Copernicus Sentinel-2 L2A"
                or data["resolution_m"] != 10
                or not isinstance(window, dict)
                or not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", window.get(k, "")) for k in ("from", "to"))
                or data["image_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest()):
            return None
        fields = ("sector", "product", "date_window", "acquisition_date", "acquisition_dates",
                  "max_cloud_filter", "cloud_percent", "cloud_basis", "resolution_m", "source",
                  "fetched_at", "width", "height", "attribution", "image_sha256", "valid_pixel_fraction")
        return {k: data[k] for k in fields if k in data}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def satellite_not_cached_body(kind: str, key) -> str:
    return json.dumps({
        "detail": "satellite_not_cached",
        "message": "Satellite image not available in review mode",
    })


async def _send_json(send, status: int, detail: str, extra_headers=()):
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class ReviewModeMiddleware:
    """Pure ASGI middleware; runs before routing, auth and mounted sub-apps."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        ip = (scope.get("client") or ("unknown",))[0]
        if auth_blocked(ip):
            return await _send_json(send, 429, "too_many_failed_logins", [(b"retry-after", str(AUTH_FAIL_WINDOW_S).encode())])

        refused = classify(scope.get("method", "GET"), scope.get("path", "/"))
        if refused:
            return await _send_json(send, *refused)

        has_auth = any(k == b"authorization" for k, _ in scope.get("headers", []))

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and message["status"] == 401 and has_auth:
                record_auth_failure(ip)
            await send(message)

        return await self.app(scope, receive, send_wrapper)
