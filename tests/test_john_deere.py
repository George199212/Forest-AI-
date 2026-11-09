"""Mocked sandbox flow; isolated DB and no production credentials/network."""
import json
import logging
import sqlite3
import time
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH', str(tmp_path/'deere.db'))
    monkeypatch.setenv('INTEGRATION_CREDENTIALS_KEY', 'test-deere-key')
    monkeypatch.setenv('JOHN_DEERE_CLIENT_ID', 'test-client')
    monkeypatch.setenv('JOHN_DEERE_CLIENT_SECRET', 'test-secret')
    monkeypatch.setenv('JOHN_DEERE_ENV', 'sandbox')
    monkeypatch.setenv('JOHN_DEERE_REDIRECT_URI', 'http://localhost:9090/callback')
    monkeypatch.setenv('DASHBOARD_USERNAME', 'pytest')
    monkeypatch.setenv('DASHBOARD_PASSWORD', 'pytest')
    import database
    from services.integrations import john_deere as jd
    monkeypatch.setattr(database, 'DB_NAME', str(tmp_path/'deere.db'))
    database.init_db()
    # Fail closed if a test forgets to mock an external call.
    monkeypatch.setattr(jd.requests, 'request', Mock(side_effect=AssertionError('Unexpected Deere HTTP request')))
    return jd


@pytest.fixture
def browser(env, monkeypatch):
    import api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(api.risk_ai_worker, 'start', lambda: None)
    with TestClient(api.app, base_url='http://localhost:9090') as client:
        client.auth = ('pytest', 'pytest')
        yield client


def response(payload, status=200):
    return Mock(status_code=status, json=Mock(return_value=payload))


def token(refresh='refresh-private', **kw):
    value = dict(access_token='access-private', token_type='Bearer', expires_in=43200, scope='eq1 offline_access')
    if refresh is not None: value['refresh_token'] = refresh
    value.update(kw)
    return value


def organization(rel='manage_connection', name='Forest <Test>'):
    links = [{'rel':'self','uri':'https://sandboxapi.deere.com/platform/organizations/test'}]
    if rel: links.append({'rel':rel,'uri':'https://connections.deere.com/connections/test/select-organizations'})
    return dict(id='test', name=name, links=links)


def mocked(env, monkeypatch, responses):
    mock = Mock(side_effect=responses)
    monkeypatch.setattr(env.requests, 'request', mock)
    return mock


def connected(env):
    service = env.Client('pytest')
    service.save_tokens(env.parse_tokens(token()))
    return service


def session(browser):
    return browser.get('/api/john-deere/status').json()['csrf_token']


def test_config(env, monkeypatch):
    cfg = env.Config.load()
    assert cfg.environment == 'sandbox'
    assert cfg.redirect_uri == 'http://localhost:9090/callback'
    assert 'test-secret' not in repr(cfg)
    monkeypatch.setenv('JOHN_DEERE_ENV', 'production')
    with pytest.raises(env.DeereError): env.Config.load()


@pytest.mark.parametrize('name', ['JOHN_DEERE_CLIENT_ID','JOHN_DEERE_CLIENT_SECRET','INTEGRATION_CREDENTIALS_KEY'])
def test_missing_config(env, monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(env.DeereError): env.Config.load()


@pytest.mark.parametrize('uri', ['http://example.com/callback','https://example.com/wrong','http://localhost:9090/callback?x=y', 'http://localhost:bad/callback'])
def test_bad_callback_config(env, monkeypatch, uri):
    monkeypatch.setenv('JOHN_DEERE_REDIRECT_URI', uri)
    with pytest.raises(env.DeereError): env.Config.load()


def test_authorization_url_and_state(env):
    cookie, _ = env.new_session('pytest')
    state = env.begin_oauth(cookie, 'pytest')
    assert len(state) >= 40
    params = parse_qs(urlsplit(env.authorization_url(env.Config.load(), state)).query)
    assert params['response_type'] == ['code']
    assert params['scope'] == ['eq1 offline_access']
    assert params['redirect_uri'] == ['http://localhost:9090/callback']
    assert env.consume_state(cookie, 'another-account', state) is False
    assert env.consume_state('another-browser', 'pytest', state) is False
    assert env.consume_state(cookie, 'pytest', 'bad') is False
    assert env.consume_state(cookie, 'pytest', state) is True
    assert env.consume_state(cookie, 'pytest', state) is False


def test_expired_state(env):
    cookie, _ = env.new_session('pytest')
    state = env.begin_oauth(cookie, 'pytest')
    with env._db() as conn: conn.execute('UPDATE john_deere_sessions SET state_expires_at=0')
    assert not env.consume_state(cookie, 'pytest', state)


def test_tokens_encrypted_and_refresh_expiry(env, monkeypatch):
    service = connected(env)
    row = service.row()
    assert 'access-private' not in row['encrypted_tokens']
    assert 'refresh-private' not in row['encrypted_tokens']
    assert row['provider'] == 'john_deere'
    assert not env.expired(service.tokens())
    assert env.expired({'expires_at':time.time()-1})
    mock = mocked(env, monkeypatch, [response(token(refresh=None))])
    new = service.refresh()
    assert new['refresh_token'] == 'refresh-private'
    assert service.row()['connected_at'] == row['connected_at']
    assert mock.call_args.kwargs['data']['grant_type'] == 'refresh_token'
    assert 'access-private' not in json.dumps(service.public_status())


@pytest.mark.parametrize('bad', [{}, {'access_token':'x','token_type':'Bearer','expires_in':'bad'},
    token(expires_in=-1), token(expires_in=float('inf')), token(scope=''),token(token_type='MAC'), token(access_token=123)])
def test_invalid_tokens(env, bad):
    with pytest.raises(env.DeereError): env.parse_tokens(bad)


@pytest.mark.parametrize('payload', [[organization()], {'values':[organization()], 'total':1}])
def test_organization_shapes(env, payload):
    org = env.parse_organizations(payload)[0]
    assert org['id'] == 'test'
    assert org['connection_status'] == 'Connected'
    assert 'manage_connection' in org['links']


def test_connections_unknown_zero_and_no_machine_data(env):
    assert env.parse_organizations({'values':[]}) == []
    assert env.parse_organizations([]) == []
    assert env.parse_organizations([organization('connections')])[0]['connection_status'] == 'Authorization required'
    assert env.parse_organizations([organization(None)])[0]['connection_status'] == 'Unknown'
    # Organizations need neither machines nor telemetry fields.
    assert env.parse_organizations([organization()])[0]['name'] == 'Forest <Test>'


@pytest.mark.parametrize('uri', ['https://api.deere.com/platform/','https://evil.example/',
 'https://sandboxapi.deere.com.evil.example/','http://sandboxapi.deere.com/platform/',
 'https://user:password@sandboxapi.deere.com/platform/','https://sandboxapi.deere.com:444/platform/'])
def test_reject_non_sandbox_links(env, uri):
    with pytest.raises(env.DeereError): env.safe_link(uri)


def test_catalog_pagination_and_connection_links(env, monkeypatch):
    service = connected(env)
    uri = 'https://sandboxapi.deere.com/platform/discovered-organizations'
    next_uri = uri+'?page=2'
    mock = mocked(env, monkeypatch, [response({'links':[{'rel':'organizations','uri':uri}]}),
        response({'values':[organization('connections')], 'links':[{'rel':'nextPage','uri':next_uri}]}),
        response({'values':[dict(organization(),id='another')], 'links':[]})])
    assert len(service.organizations()) == 2
    assert mock.call_args_list[0].args[1] == env.CATALOG_URL
    assert mock.call_args_list[1].args[1] == uri
    assert mock.call_args_list[2].args[1] == next_uri
    data = service.public_status()
    assert data['api_catalog'] == 'OK'
    assert data['can_authorize'] and data['can_manage']
    assert 'links' not in data['organizations_list'][0]
    assert all(c.kwargs['allow_redirects'] is False and c.kwargs['timeout']==(5,25) for c in mock.call_args_list)


def test_empty_organizations(env, monkeypatch):
    service = connected(env)
    mocked(env, monkeypatch,[response({'links':[{'rel':'organizations','uri':env.CATALOG_URL+'orgs'}]}),response({'values':[]})])
    assert service.organizations() == []
    assert service.public_status()['organization_connection'] == 'No organizations'


@pytest.mark.parametrize('status', [302,403,429,500])
def test_safe_api_errors(env, monkeypatch, status, caplog):
    service = connected(env)
    mocked(env, monkeypatch,[response({'error':'access-private refresh-private test-secret'},status)])
    with pytest.raises(env.DeereError) as err: service.organizations()
    assert 'access-private' not in str(err.value)+caplog.text
    assert service.public_status()['api_catalog'] == 'ERROR'


def test_timeout_and_bad_json(env, monkeypatch):
    service = connected(env)
    mocked(env, monkeypatch,[requests.Timeout('refresh-private')])
    with pytest.raises(env.DeereError, match='timed out'): service.get(env.CATALOG_URL)
    bad = response(None); bad.json.side_effect = ValueError('access-private')
    mocked(env, monkeypatch,[bad])
    with pytest.raises(env.DeereError, match='invalid JSON'): service.get(env.CATALOG_URL)


def test_expired_and_401_refresh_retry(env, monkeypatch):
    service = connected(env)
    mock = mocked(env, monkeypatch,[response({},401),response(token(refresh='rotated')),response({'links':[]})])
    assert service.get(env.CATALOG_URL) == {'links':[]}
    assert service.tokens()['refresh_token'] == 'rotated'
    assert mock.call_count == 3
    tokens = service.tokens(); tokens['expires_at'] = time.time()-1; service.save_tokens(tokens)
    mock = mocked(env, monkeypatch,[response(token()),response({'values':[]})])
    service.get(env.CATALOG_URL)
    assert mock.call_args_list[0].args[:2] == ('POST', env.TOKEN_URL)


def test_refresh_failure_diagnostic(env, monkeypatch):
    service = connected(env)
    mocked(env, monkeypatch,[response({},400)])
    with pytest.raises(env.DeereError): service.refresh()
    assert service.public_status()['token'] == 'Refresh failed'


def test_routes_auth_csrf_and_state_rejection(env, browser, caplog):
    assert browser.get('/api/john-deere/status',auth=('bad','bad')).status_code == 401
    assert browser.post('/integrations/john-deere/connect').status_code == 403
    csrf = session(browser)
    assert browser.post('/api/john-deere/refresh',headers={'X-CSRF-Token':csrf,'Origin':'https://evil.example'}).status_code == 403
    with caplog.at_level(logging.WARNING):
        result = browser.get('/callback?state=bad&code=authorization-private')
    assert result.status_code == 400
    assert 'authorization-private' not in result.text+caplog.text
    # The ASGI access-log scope cannot see the original callback query.
    assert result.request.url.query  # client supplied a query


def test_full_browser_flow(env, browser, monkeypatch):
    csrf = session(browser)
    result = browser.post('/integrations/john-deere/connect', data={'csrf_token':csrf},follow_redirects=False)
    assert result.status_code == 303
    state = parse_qs(urlsplit(result.headers['location']).query)['state'][0]
    mock = mocked(env, monkeypatch,[response(token()),
        response({'links':[{'rel':'organizations','uri':env.CATALOG_URL+'orgs'}]}),
        response({'values':[organization('connections')]})])
    result = browser.get('/callback',params={'state':state,'code':'authorization-private'},follow_redirects=False)
    assert result.status_code == 303
    assert result.headers['location'] == '/#integrations'
    assert result.headers['referrer-policy'] == 'no-referrer'
    assert result.headers['cache-control'] == 'no-store'
    assert mock.call_args_list[0].kwargs['data']['code'] == 'authorization-private'
    public = browser.get('/api/john-deere/status')
    assert public.json()['can_authorize']
    assert not any(secret in public.text for secret in ['access-private','refresh-private','authorization-private','test-secret'])
    redirect = browser.get('/integrations/john-deere/organizations/authorize',follow_redirects=False)
    assert redirect.headers['location'] == organization('connections')['links'][1]['uri']
    mock = mocked(env, monkeypatch,[response({'links':[{'rel':'organizations','uri':env.CATALOG_URL+'orgs'}]}),response({'values':[organization()]})])
    result = browser.post('/api/john-deere/refresh',headers={'X-CSRF-Token':csrf})
    assert result.json()['organization_connection'] == 'Connected'
    assert result.json()['can_manage'] and not result.json()['can_authorize']
    assert browser.get('/callback',params={'state':state,'code':'replay'}).status_code == 400


def test_callback_denial(env, browser):
    csrf = session(browser)
    r=browser.post('/integrations/john-deere/connect',headers={'X-CSRF-Token':csrf},follow_redirects=False)
    state=parse_qs(urlsplit(r.headers['location']).query)['state'][0]
    result=browser.get('/callback',params={'state':state,'error':'access_denied','error_description':'sensitive'},follow_redirects=False)
    assert 'authorization_failed' in result.headers['location']
    assert 'sensitive' not in result.text


def test_migration_idempotent_preserves_data(env):
    import database
    with env._db() as conn: conn.execute("INSERT INTO sectors(name) VALUES('KEEP')")
    database.init_db(); database.init_db()
    with env._db() as conn:
        assert conn.execute("SELECT count(*) FROM sectors WHERE name='KEEP'").fetchone()[0] == 1


def test_callback_query_redacted_before_log(env):
    import asyncio
    from services.integrations.john_deere_routes import CallbackPrivacyMiddleware
    scope={'type':'http','path':'/callback','query_string':b'code=secret&state=private'}
    seen=[]
    async def app(scope,receive,send):
        seen.append(scope['query_string'])
        await send({'type':'http.response.start','status':401,'headers':[]})
    async def send(message): seen.append(message)
    asyncio.run(CallbackPrivacyMiddleware(app)(scope,None,send))
    assert seen[0] == b''
    assert (b'cache-control',b'no-store') in seen[1]['headers']


def test_missing_refresh_token(env):
    service = env.Client('pytest')
    service.save_tokens(env.parse_tokens(token(refresh=None)))
    with pytest.raises(env.DeereError, match='No refresh token'):
        service.refresh()
    assert service.public_status()['token'] == 'Expired'


def test_callback_token_failure_is_safe(env, browser, monkeypatch, caplog):
    csrf = session(browser)
    r = browser.post('/integrations/john-deere/connect', data={'csrf_token':csrf},follow_redirects=False)
    state = parse_qs(urlsplit(r.headers['location']).query)['state'][0]
    mocked(env, monkeypatch,[response({'error_description':'test-secret authorization-private'},400)])
    r = browser.get('/callback',params={'state':state,'code':'authorization-private'},follow_redirects=False)
    assert r.headers['location'] == '/?john_deere=token_failed#integrations'
    assert 'authorization-private' not in caplog.text+r.text
    assert env.Client('pytest').row() is None


def test_pagination_refuses_production_link(env, monkeypatch):
    service = connected(env)
    mock = mocked(env, monkeypatch,[response({'links':[{'rel':'organizations','uri':env.CATALOG_URL+'orgs'}]}),
        response({'values':[], 'links':[{'rel':'nextPage','uri':'https://api.deere.com/platform/organizations'}]})])
    with pytest.raises(env.DeereError): service.organizations()
    assert mock.call_count == 2


def test_malformed_links_are_safe(env):
    with pytest.raises(env.DeereError, match='invalid links'):
        env.parse_organizations([dict(id='test', links=None)])
