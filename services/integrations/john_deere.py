"""Operations Center sandbox OAuth and link discovery. No telemetry ingestion.

Official references and manual setup: docs/JOHN_DEERE.md.
Tokens only leave this module in encrypted database writes or HTTPS headers/bodies.
"""
import hashlib
import json
import logging
import math
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from contextlib import contextmanager
from urllib.parse import urlencode, urlsplit

import requests

import database
from services.integrations.crypto import encrypt_credentials, decrypt_credentials

log = logging.getLogger(__name__)
AUTH_URL = 'https://signin.johndeere.com/oauth2/aus78tnlaysMraFhC1t7/v1/authorize'
TOKEN_URL = 'https://signin.johndeere.com/oauth2/aus78tnlaysMraFhC1t7/v1/token'
CATALOG_URL = 'https://sandboxapi.deere.com/platform/'
SCOPES = 'eq1 offline_access'
COOKIE = 'forest_deere_session'
_lock = threading.RLock()  # shared-account refresh rotation, existing single-worker deployment


class DeereError(RuntimeError):
    """Only fixed, credential-free messages may be raised to routes."""


@dataclass(frozen=True)
class Config:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    redirect_uri: str = 'http://localhost:9090/callback'
    environment: str = 'sandbox'

    @classmethod
    def load(cls):
        config = cls(os.getenv('JOHN_DEERE_CLIENT_ID', '').strip(),
                     os.getenv('JOHN_DEERE_CLIENT_SECRET', '').strip(),
                     os.getenv('JOHN_DEERE_REDIRECT_URI', 'http://localhost:9090/callback').strip(),
                     os.getenv('JOHN_DEERE_ENV', 'sandbox').strip())
        if config.environment != 'sandbox':
            raise DeereError('Only the John Deere sandbox is supported.')
        try:
            uri = urlsplit(config.redirect_uri)
            valid = (uri.path == '/callback' and not uri.query and not uri.fragment
                     and not uri.username and not uri.password and bool(uri.hostname)
                     and uri.port in (None, 80, 443, 9090)
                     and (uri.scheme == 'https' or
                          (uri.scheme == 'http' and uri.hostname in ('localhost', '127.0.0.1'))))
        except ValueError:
            valid = False
        if not valid:
            raise DeereError('Configure a valid registered /callback redirect URI.')
        if not config.client_id or not config.client_secret:
            raise DeereError('Set JOHN_DEERE_CLIENT_ID and JOHN_DEERE_CLIENT_SECRET on the server.')
        if not os.getenv('INTEGRATION_CREDENTIALS_KEY', '').strip():
            raise DeereError('Set INTEGRATION_CREDENTIALS_KEY before connecting John Deere.')
        return config


@contextmanager
def _db():
    conn = sqlite3.connect(database.DB_NAME, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def session_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def browser_session(cookie, account):
    with _db() as conn:
        row = conn.execute('SELECT * FROM john_deere_sessions WHERE session_hash=? AND account_id=? AND expires_at>?',
                           (session_hash(cookie or ''), account, time.time())).fetchone()
    return dict(row) if row else None


def new_session(account):
    cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with _db() as conn:
        conn.execute('DELETE FROM john_deere_sessions WHERE expires_at<?', (time.time(),))
        conn.execute('INSERT INTO john_deere_sessions(session_hash,account_id,csrf_token,expires_at) VALUES(?,?,?,?)',
                     (session_hash(cookie), account, csrf, time.time()+3600))
    return cookie, csrf


def begin_oauth(cookie, account):
    state = secrets.token_urlsafe(32)
    with _db() as conn:
        conn.execute('UPDATE john_deere_sessions SET oauth_state=?,state_expires_at=? WHERE session_hash=? AND account_id=?',
                     (state, time.time()+600, session_hash(cookie), account))
    return state


def consume_state(cookie, account, supplied):
    # One-use and atomic across requests. No state values in logs or exceptions.
    with _db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM john_deere_sessions WHERE session_hash=? AND account_id=?',
                           (session_hash(cookie or ''), account)).fetchone()
        valid = bool(row and row['expires_at'] > time.time() and row['oauth_state'] and
                     (row['state_expires_at'] or 0) > time.time() and supplied and
                     secrets.compare_digest(row['oauth_state'], supplied))
        if valid:
            conn.execute('UPDATE john_deere_sessions SET oauth_state=NULL,state_expires_at=NULL WHERE session_hash=?',
                         (row['session_hash'],))
    return valid


def authorization_url(config, state):
    return AUTH_URL + '?' + urlencode(dict(response_type='code', scope=SCOPES,
        client_id=config.client_id, state=state, redirect_uri=config.redirect_uri))


def safe_link(uri, connection=False):
    if not isinstance(uri, str):
        raise DeereError('Deere returned an invalid resource link.')
    try:
        p = urlsplit(uri)
        valid = (p.scheme == 'https' and p.hostname == ('connections.deere.com' if connection else 'sandboxapi.deere.com')
                 and p.port in (None, 443) and not p.username and not p.password and not p.fragment
                 and not any(ord(c) < 32 for c in uri))
    except ValueError:
        valid = False
    if not valid:
        raise DeereError('Deere returned a link outside the permitted sandbox or Connections host.')
    return uri


def links(payload):
    if not isinstance(payload, dict):
        return {}
    values = payload.get('links', [])
    if not isinstance(values, list):
        raise DeereError('Deere returned an invalid links collection.')
    return {v['rel']: v.get('uri', v.get('href')) for v in values
            if isinstance(v, dict) and isinstance(v.get('rel'), str)}


def parse_organizations(payload):
    values = payload if isinstance(payload, list) else payload.get('values', []) if isinstance(payload, dict) else None
    if not isinstance(values, list):
        raise DeereError('Deere returned an invalid organizations response.')
    result = []
    for value in values:
        if not isinstance(value, dict) or 'id' not in value:
            raise DeereError('Deere returned an invalid organization.')
        rels = links(value)
        # Keep only validated links server-side; never return arbitrary API payloads.
        clean = {rel: safe_link(uri, rel in ('connections', 'manage_connection')) for rel, uri in rels.items()
                 if rel in ('connections', 'manage_connection', 'self')}
        status = ('Authorization required' if 'connections' in clean else
                  'Connected' if 'manage_connection' in clean or any(r not in ('self',) for r in rels) else 'Unknown')
        result.append(dict(id=str(value['id']), name=str(value.get('name', value['id'])),
                           connection_status=status, links=clean))
    return result


def parse_tokens(payload, previous=None):
    if not isinstance(payload, dict):
        raise DeereError('Deere returned an invalid token response.')
    access = payload.get('access_token')
    refresh = payload.get('refresh_token') or (previous or {}).get('refresh_token')
    try:
        lifetime = float(payload['expires_in'])
    except (KeyError, ValueError, TypeError):
        raise DeereError('Deere returned an invalid token expiry.') from None
    if (not isinstance(access, str) or not access or not math.isfinite(lifetime) or lifetime <= 0
            or str(payload.get('token_type', '')).lower() != 'bearer'
            or (refresh is not None and not isinstance(refresh, str))):
        raise DeereError('Deere returned an invalid token response.')
    if 'scope' in payload and 'eq1' not in str(payload['scope']).split():
        raise DeereError('Required equipment read permission was not granted. Reconnect and Allow Access.')
    return dict(access_token=access, refresh_token=refresh, expires_at=time.time()+lifetime)


def expired(tokens):
    return tokens.get('expires_at', 0) <= time.time()+60


def _request(method, url, **kwargs):
    try:
        response = requests.request(method, url, timeout=(5, 25), allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise DeereError('John Deere request failed or timed out.') from None
    return response


def _json(response):
    if response.status_code != 200:
        # Do not include upstream response bodies, exception text, URLs, or headers.
        raise DeereError('John Deere API request failed (HTTP %d).' % response.status_code)
    try:
        return response.json()
    except (ValueError, TypeError):
        raise DeereError('John Deere returned invalid JSON.') from None


class Client:
    def __init__(self, account, config=None):
        self.account = account
        self.config = config or Config.load()

    def row(self):
        with _db() as conn:
            row = conn.execute('SELECT * FROM john_deere_oauth WHERE account_id=?', (self.account,)).fetchone()
        return dict(row) if row else None

    def save_tokens(self, tokens):
        now = time.time()
        encrypted = encrypt_credentials(json.dumps(tokens))
        with _db() as conn:
            conn.execute('''INSERT INTO john_deere_oauth(account_id,encrypted_tokens,expires_at,connected_at,updated_at,status)
                VALUES(?,?,?,?,?,'Connected') ON CONFLICT(account_id) DO UPDATE SET
                encrypted_tokens=excluded.encrypted_tokens,expires_at=excluded.expires_at,
                updated_at=excluded.updated_at,status='Connected' ''',
                (self.account, encrypted, tokens['expires_at'], now, now))

    def tokens(self):
        row = self.row()
        if not row:
            raise DeereError('Connect John Deere first.')
        try:
            return json.loads(decrypt_credentials(row['encrypted_tokens']))
        except (ValueError, RuntimeError):
            raise DeereError('Cannot read stored Deere credentials. Check the server encryption key.') from None

    def token_request(self, data, previous=None):
        data.update(client_id=self.config.client_id, client_secret=self.config.client_secret,
                    redirect_uri=self.config.redirect_uri)
        return parse_tokens(_json(_request('POST', TOKEN_URL, data=data,
                            headers={'Accept': 'application/json'})), previous)

    def exchange(self, code):
        with _lock:
            self.save_tokens(self.token_request(dict(grant_type='authorization_code', code=code)))
        self.diagnostics(oauth='OK', token='Valid', api_catalog='Not checked', organizations=0,
                         organization_connection='Not checked', error=None, organizations_list=[], connection_links={})

    def refresh(self):
        previous = self.tokens()
        if not previous.get('refresh_token'):
            self.diagnostics(token='Expired')
            raise DeereError('No refresh token is available. Connect John Deere again.')
        try:
            tokens = self.token_request(dict(grant_type='refresh_token', refresh_token=previous['refresh_token'], scope=SCOPES), previous)
            self.save_tokens(tokens)
            self.diagnostics(token='Valid')
            return tokens
        except DeereError:
            self.diagnostics(token='Refresh failed')
            raise

    def get(self, uri):
        uri = safe_link(uri)
        with _lock:
            tokens = self.tokens()
            if expired(tokens):
                tokens = self.refresh()
            response = _request('GET', uri, headers={'Accept': 'application/vnd.deere.axiom.v3+json',
                                'Authorization': 'Bearer '+tokens['access_token']})
            if response.status_code == 401:
                tokens = self.refresh()
                response = _request('GET', uri, headers={'Accept': 'application/vnd.deere.axiom.v3+json',
                                    'Authorization': 'Bearer '+tokens['access_token']})
            return _json(response)

    def diagnostics(self, **changes):
        with _db() as conn:
            row = conn.execute('SELECT diagnostics_json FROM john_deere_oauth WHERE account_id=?', (self.account,)).fetchone()
            if row:
                data = json.loads(row[0]); data.update(changes)
                status = ('ERROR' if data.get('error') or data.get('token') == 'Refresh failed' else
                          data.get('organization_connection', 'OAuth connected'))
                conn.execute('UPDATE john_deere_oauth SET diagnostics_json=?,updated_at=?,status=? WHERE account_id=?',
                             (json.dumps(data), time.time(), status, self.account))

    def organizations(self):
        stage = 'api_catalog'
        try:
            catalog = self.get(CATALOG_URL)
            uri = links(catalog).get('organizations')
            if not uri:
                raise DeereError('Deere API Catalog did not provide an organizations link.')
            self.diagnostics(api_catalog='OK')
            stage = 'organizations'
            organizations, actions, visited = [], {}, set()
            while uri:
                if uri in visited or len(visited) >= 100:
                    raise DeereError('Deere organization pagination exceeded its safe limit.')
                visited.add(uri)
                page = self.get(uri)
                organizations.extend(parse_organizations(page))
                for rel, link in links(page).items():
                    if rel in ('connections', 'manage_connection'):
                        actions[rel] = safe_link(link, True)
                uri = links(page).get('nextPage')
            for org in organizations:
                for rel, uri in org['links'].items():
                    if rel in ('connections', 'manage_connection'):
                        actions.setdefault(rel, uri)
            connection = ('Authorization required' if 'connections' in actions else
                          'Connected' if any(o['connection_status']=='Connected' for o in organizations) else
                          'No organizations' if not organizations else 'Unknown')
            self.diagnostics(organizations=len(organizations), organizations_list=organizations,
                             connection_links=actions, organization_connection=connection,
                             organizations_status='OK', error=None, checked_at=time.time())
            return organizations
        except DeereError as exc:
            log.warning('John Deere %s failed', stage)
            self.diagnostics(**{stage if stage=='api_catalog' else 'organizations_status': 'ERROR'},
                             error=str(exc), connection_links={}, organization_connection='Not checked')
            raise

    def public_status(self):
        row = self.row()
        if not row:
            return dict(environment='Sandbox', oauth='Not connected', token='Not available',
                        api_catalog='Not checked', organizations=0, organizations_list=[],
                        organization_connection='Not connected', can_authorize=False, can_manage=False)
        data = json.loads(row['diagnostics_json'])
        actions = data.pop('connection_links', {})
        # Links stay on the server; UI only uses fixed authenticated redirect routes.
        data['organizations_list'] = [{k:v for k,v in org.items() if k != 'links'}
                                      for org in data.get('organizations_list', [])]
        token = data.get('token', 'Valid')
        if row['expires_at'] <= time.time()+60 and token != 'Refresh failed': token = 'Expired'
        return dict(data, environment='Sandbox', oauth=data.get('oauth','OK'), token=token,
                    can_authorize='connections' in actions, can_manage='manage_connection' in actions)

    def connection_url(self, relation):
        row = self.row()
        uri = json.loads(row['diagnostics_json']).get('connection_links', {}).get(relation) if row else None
        if not uri:
            raise DeereError('Refresh organizations to discover the Deere connection action.')
        # Keep Deere's returned URL intact. User returns manually and clicks Refresh.
        return safe_link(uri, True)
