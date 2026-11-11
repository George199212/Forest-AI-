"""Thin Copernicus Data Space Ecosystem (CDSE) client.

Same OAuth flow, token URL and env variable names as api.get_sentinel_token()
(api.py:2265-2294), which stays untouched. Kept separate so the CLI/timer does
not import the whole FastAPI app and so failures carry a reason for the health
view instead of a bare None.

Never logged, printed or stored: the access token, the Authorization header,
SENTINEL_CLIENT_SECRET. Error texts contain only HTTP status and a short,
server-provided message.
"""
import os
import random
import threading
import time

import requests

# Same values as api.py:2267-2268.
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_BASE = "https://sh.dataspace.copernicus.eu"
# Process API: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process.html
PROCESS_URL = SH_BASE + "/api/v1/process"
# Catalog API (STAC): https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Catalog.html
CATALOG_SEARCH_URL = SH_BASE + "/api/v1/catalog/1.0.0/search"

RETRY_STATUSES = {429, 500, 502, 503, 504}


class CdseError(Exception):
    def __init__(self, kind, message, http_status=None):
        super().__init__(f"{kind}: {message}")
        self.kind = kind            # NOT_CONFIGURED | AUTH | HTTP | NETWORK | PAGINATION
        self.http_status = http_status


def credentials_configured():
    return bool(os.environ.get("SENTINEL_CLIENT_ID")) and bool(os.environ.get("SENTINEL_CLIENT_SECRET"))


def _short_error(resp):
    try:
        body = resp.json()
        msg = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("error_description") or body.get("error")
    except Exception:
        msg = None
    return f"HTTP {resp.status_code}" + (f" — {str(msg)[:200]}" if msg else "")


class Client:
    """HTTP client with an in-process token cache, a request-rate limit and
    exponential backoff on 429/5xx. `on_request(kind, http_status, response)`
    is called for EVERY request sent to Sentinel Hub (retries included), so
    the quota guard counts exactly what was spent."""

    def __init__(self, max_rps=2.0, backoff_base_s=1.0, max_retries=4, session=None, sleep=time.sleep,
                 on_request=None):
        self._session = session or requests.Session()
        self._min_interval = 1.0 / max_rps if max_rps else 0.0
        self._last_sent = 0.0
        self._lock = threading.Lock()
        self._token = None
        self._token_expires = 0.0
        self._backoff = backoff_base_s
        self._max_retries = max_retries
        self._sleep = sleep
        self.on_request = on_request

    # ── auth ────────────────────────────────────────────────────────────────
    def token(self):
        if self._token and time.time() < self._token_expires:
            return self._token
        if not credentials_configured():
            raise CdseError("NOT_CONFIGURED", "SENTINEL_CLIENT_ID / SENTINEL_CLIENT_SECRET not set")
        try:
            r = self._session.post(TOKEN_URL, data={
                "grant_type": "client_credentials",
                "client_id": os.environ["SENTINEL_CLIENT_ID"],
                "client_secret": os.environ["SENTINEL_CLIENT_SECRET"],
            }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
        except requests.RequestException as e:
            raise CdseError("NETWORK", type(e).__name__)
        if r.status_code != 200:
            raise CdseError("AUTH", _short_error(r), r.status_code)
        body = r.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + int(body.get("expires_in", 3600)) - 60
        return self._token

    # ── requests ────────────────────────────────────────────────────────────
    def _throttle(self):
        with self._lock:
            wait = self._last_sent + self._min_interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last_sent = time.monotonic()

    def post_json(self, kind, url, payload, accept="application/json", timeout=60):
        """kind: CATALOG | PROCESS. Returns the requests.Response (status 200)."""
        attempt = 0
        while True:
            headers = {"Authorization": "Bearer " + self.token(), "Content-Type": "application/json",
                       "Accept": accept}
            self._throttle()
            try:
                r = self._session.post(url, json=payload, headers=headers, timeout=timeout)
            except requests.RequestException as e:
                if self.on_request:
                    self.on_request(kind, None, None)
                if attempt >= self._max_retries:
                    raise CdseError("NETWORK", type(e).__name__)
                self._sleep(self._backoff * (2 ** attempt) + random.uniform(0, 0.25))
                attempt += 1
                continue
            if self.on_request:
                self.on_request(kind, r.status_code, r)
            if r.status_code == 401 and attempt == 0:
                self._token = None          # expired early: one fresh token, then give up
                attempt += 1
                continue
            if r.status_code in RETRY_STATUSES and attempt < self._max_retries:
                retry_after = r.headers.get("Retry-After")
                try:
                    delay = float(retry_after)
                except (TypeError, ValueError):
                    delay = self._backoff * (2 ** attempt)
                self._sleep(min(delay, 60.0) + random.uniform(0, 0.25))
                attempt += 1
                continue
            if r.status_code != 200:
                raise CdseError("HTTP", _short_error(r), r.status_code)
            return r
