"""Telegram multi-tenant routing: tenant selection, callback stamping, admin checks, invites,
schema initialisation, and bot.py behaviour with FOREST_TENANT_ROUTING off/on.

Every test uses temporary files only (tenants file, routing DB, lock dir, tenant DBs).
"""
import asyncio
import importlib
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

ADMIN = 111
OPERATIONAL_TABLES = '''
CREATE TABLE sectors (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE sector_employees (id INTEGER PRIMARY KEY AUTOINCREMENT, sector TEXT, full_name TEXT,
  role TEXT, active INTEGER, created_at TEXT, telegram_user_id TEXT);
CREATE TABLE sector_vehicles (id INTEGER PRIMARY KEY, telegram_user_id TEXT);
CREATE TABLE work_sessions (id INTEGER PRIMARY KEY, user_id TEXT);
CREATE TABLE live_locations (id INTEGER PRIMARY KEY, telegram_user_id TEXT);
'''


def _db(path, sector):
    with sqlite3.connect(path) as c:
        c.executescript(OPERATIONAL_TABLES)
        if sector:
            c.execute('INSERT INTO sectors (name) VALUES (?)', (sector,))
    return str(path)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """alpha: not joinable (no invite). beta: joinable via FOREST_TENANT_INVITE_BETA."""
    dbs = {'main': _db(tmp_path / 'main.db', None), 'alpha': _db(tmp_path / 'alpha.db', 'AL-001'),
           'beta': _db(tmp_path / 'beta.db', 'BE-001')}
    tenants = {'default_admin_tenant': 'alpha', 'tenants': {
        'alpha': {'name': 'Alpha Client', 'tenant': 'alpha-client', 'sector': 'AL-001', 'project': str(tmp_path), 'database': dbs['alpha']},
        'beta': {'name': 'Beta Client', 'tenant': 'beta-client', 'sector': 'BE-001', 'project': str(tmp_path), 'database': dbs['beta']}}}
    (tmp_path / 'tenants.json').write_text(json.dumps(tenants))
    monkeypatch.setenv('FOREST_TELEGRAM_TENANTS_FILE', str(tmp_path / 'tenants.json'))
    monkeypatch.setenv('FOREST_TELEGRAM_ROUTING_DB', str(tmp_path / 'routing.db'))
    monkeypatch.setenv('FOREST_TELEGRAM_LOCK_DIR', str(tmp_path / 'locks'))
    monkeypatch.setenv('FOREST_TELEGRAM_ADMIN_IDS', str(ADMIN))
    monkeypatch.setenv('FOREST_TENANT_INVITE_BETA', 'JOIN-BETA')
    monkeypatch.delenv('FOREST_TENANT_INVITE_ALPHA', raising=False)
    monkeypatch.setenv('DB_PATH', dbs['main'])
    cc = importlib.reload(importlib.import_module('telegram_tenants.company_context'))
    rt = importlib.reload(importlib.import_module('telegram_tenants.tenant_runtime'))
    router = importlib.reload(importlib.import_module('telegram_tenant_router'))
    return {'tmp': tmp_path, 'dbs': dbs, 'cc': cc, 'rt': rt, 'router': router}


def _update(uid, text=None, chat_type='private', update_id=1, callback=None):
    user = {'id': uid, 'is_bot': False, 'first_name': 'Worker', 'last_name': str(uid)}
    chat = {'id': uid, 'type': chat_type}
    if callback is not None:
        msg = {'message_id': 5, 'date': 0, 'chat': chat, 'text': 'menu'}
        data = {'update_id': update_id, 'callback_query': {'id': 'q', 'from': user, 'chat_instance': 'c', 'data': callback, 'message': msg}}
    else:
        data = {'update_id': update_id, 'message': {'message_id': 5, 'date': 0, 'chat': chat, 'from': user, 'text': text}}
    return Update.de_json(data, None)


def _inbox(path):
    with sqlite3.connect(path) as c:
        return c.execute('SELECT update_id, telegram_user_id, status, routing_epoch FROM telegram_update_inbox ORDER BY update_id').fetchall()


# ── configuration ──────────────────────────────────────────────────────────────

def test_path_defaults_and_relative_resolution(monkeypatch):
    for name in ('FOREST_TELEGRAM_TENANTS_FILE', 'FOREST_TELEGRAM_ROUTING_DB', 'FOREST_TELEGRAM_LOCK_DIR'):
        monkeypatch.delenv(name, raising=False)
    cc = importlib.reload(importlib.import_module('telegram_tenants.company_context'))
    assert cc.CONFIG == REPO / 'data/telegram/tenants.json'
    assert cc.REGISTRY == REPO / 'data/telegram/routing.db'
    assert cc.LOCK_DIR == Path('/run/forest-ai-telegram-locks')
    monkeypatch.setenv('FOREST_TELEGRAM_TENANTS_FILE', 'conf/t.json')
    cc = importlib.reload(cc)
    assert cc.CONFIG == REPO / 'conf/t.json'


def test_admin_ids_env_overrides_file_and_file_is_fallback(env, monkeypatch):
    cfg = json.loads(Path(os.environ['FOREST_TELEGRAM_TENANTS_FILE']).read_text())
    cfg['admin_ids'] = [222]
    Path(os.environ['FOREST_TELEGRAM_TENANTS_FILE']).write_text(json.dumps(cfg))
    cc = env['cc']
    assert cc.is_admin(ADMIN) and not cc.is_admin(222)
    monkeypatch.setenv('FOREST_TELEGRAM_ADMIN_IDS', ' 333, 444 ')
    assert cc.is_admin(333) and cc.is_admin(444) and not cc.is_admin(ADMIN)
    monkeypatch.delenv('FOREST_TELEGRAM_ADMIN_IDS')
    assert cc.is_admin(222) and not cc.is_admin(ADMIN)
    del cfg['admin_ids']
    Path(os.environ['FOREST_TELEGRAM_TENANTS_FILE']).write_text(json.dumps(cfg))
    assert cc.config()['admin_ids'] == [] and not cc.is_admin(222)


def test_invite_codes_select_tenant(env, monkeypatch):
    cc = env['cc']
    assert cc.invite_code('beta') == 'JOIN-BETA' and cc.invite_code('alpha') is None
    for text in ('JOIN-BETA', '/start JOIN-BETA', '/join JOIN-BETA', '/start@ForestBot JOIN-BETA', '  JOIN-BETA  '):
        assert cc.invite_tenant(text) == 'beta', text
    for text in ('', None, '/start', 'JOIN-BETA now', '/help JOIN-BETA', 'join-beta', '/start JOIN-BETA x'):
        assert cc.invite_tenant(text) is None, text
    monkeypatch.setenv('FOREST_TENANT_INVITE_MY_CLIENT', 'X')
    assert cc.invite_code('my-client') == 'X'


# ── admin tenant selection ─────────────────────────────────────────────────────

def test_admin_selection_switch_and_non_admin(env):
    cc = env['cc']
    cc.initialize()
    sel = cc.selection(ADMIN)
    assert (sel['active_tenant'], sel['active_sector'], sel['routing_epoch']) == ('alpha', 'AL-001', 1)
    sel = cc.switch(ADMIN, 'beta')
    assert (sel['active_tenant'], sel['active_sector'], sel['routing_epoch']) == ('beta', 'BE-001', 2)
    assert 'Beta Client' in cc.indicator(sel) and 'BE-001' in cc.indicator(sel)
    assert cc.selection(999) is None
    with pytest.raises(PermissionError):
        cc.switch(999, 'beta')
    with pytest.raises(KeyError):
        cc.switch(ADMIN, 'unknown')
    assert oct(os.stat(cc.REGISTRY).st_mode & 0o777) == '0o600'


def test_message_binding_matches_tenant_and_epoch(env):
    cc = env['cc']
    cc.initialize()
    cc.bind_message(ADMIN, 10, 20, 'beta', 3)
    assert cc.message_matches(ADMIN, 10, 20, 'beta', 3)
    assert not cc.message_matches(ADMIN, 10, 20, 'beta', 4)
    assert not cc.message_matches(ADMIN, 10, 20, 'alpha', 3)
    assert not cc.message_matches(ADMIN, 10, 21, 'beta', 3)


# ── callback stamping ctx:<tenant>:<epoch>| ─────────────────────────────────────

def test_admin_callbacks_are_stamped_with_tenant_and_epoch(env):
    rt = env['rt']
    token = rt.CURRENT.set({'uid': str(ADMIN), 'key': 'beta', 'epoch': 2})
    try:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton('A', callback_data='checkin_sector:BE-001'),
                                        InlineKeyboardButton('B', callback_data='ctx:beta:2|already'),
                                        InlineKeyboardButton('Web', url='https://example.org')]])
        out = rt.markup(markup)
        data = [b.callback_data for b in out.inline_keyboard[0]]
        assert data == ['ctx:beta:2|checkin_sector:BE-001', 'ctx:beta:2|already', None]
        assert out.inline_keyboard[0][2].url == 'https://example.org'
        with pytest.raises(ValueError, match='callback_too_long'):
            rt.markup(InlineKeyboardMarkup([[InlineKeyboardButton('L', callback_data='x' * 60)]]))
        reply = rt.markup(ReplyKeyboardMarkup([['🌲 Sectors']]))
        assert [[b.text for b in r] for r in reply.keyboard] == [['🌲 Sectors'], [rt.BUTTON]]
        again = rt.markup(reply)
        assert sum(1 for r in again.keyboard for b in r if b.text == rt.BUTTON) == 1
    finally:
        rt.CURRENT.reset(token)


def test_non_admin_and_no_context_markup_unchanged(env):
    rt = env['rt']
    markup = InlineKeyboardMarkup([[InlineKeyboardButton('A', callback_data='checkin_sector:BE-001')]])
    assert rt.markup(markup) is markup
    token = rt.CURRENT.set({'uid': '999', 'key': 'beta', 'epoch': 2})
    try:
        assert rt.markup(markup) is markup
    finally:
        rt.CURRENT.reset(token)


# ── router: schema, registration, enqueue, routing ─────────────────────────────

def test_initialize_creates_tenant_tables_additively_and_idempotently(env):
    router, dbs = env['router'], env['dbs']
    with sqlite3.connect(dbs['beta']) as c:
        c.execute("INSERT INTO sector_employees (sector, full_name, telegram_user_id) VALUES ('BE-001','Admin',?)", (str(ADMIN),))
    before = {p: {r[0] for r in sqlite3.connect(p).execute("SELECT name FROM sqlite_master")} for p in (dbs['alpha'], dbs['beta'], dbs['main'])}
    router.initialize()
    router.initialize()
    new = {'telegram_tenant_memberships', 'telegram_update_inbox', 'telegram_worker_state'}
    for p in (dbs['alpha'], dbs['beta']):
        names = {r[0] for r in sqlite3.connect(p).execute("SELECT name FROM sqlite_master")}
        assert {n for n in names - before[p] if not n.startswith('sqlite_autoindex_')} == new
        cols = [r[1] for r in sqlite3.connect(p).execute('PRAGMA table_info(telegram_update_inbox)')]
        assert cols[-1] == 'routing_epoch'
    assert {r[0] for r in sqlite3.connect(dbs['main']).execute("SELECT name FROM sqlite_master")} == before[dbs['main']]
    beta_sql = sqlite3.connect(dbs['beta']).execute("SELECT sql FROM sqlite_master WHERE name='telegram_tenant_memberships'").fetchone()[0]
    alpha_sql = sqlite3.connect(dbs['alpha']).execute("SELECT sql FROM sqlite_master WHERE name='telegram_tenant_memberships'").fetchone()[0]
    assert "CHECK(tenant='beta-client')" in beta_sql and "CHECK(sector='BE-001')" in beta_sql
    assert 'CHECK' not in alpha_sql
    assert sqlite3.connect(dbs['beta']).execute('SELECT telegram_user_id, tenant FROM telegram_tenant_memberships').fetchall() == [(str(ADMIN), 'beta-client')]
    assert sqlite3.connect(dbs['alpha']).execute('SELECT count(*) FROM telegram_tenant_memberships').fetchone()[0] == 0


def test_register_membership_and_legacy_identity_block(env):
    router, dbs = env['router'], env['dbs']
    router.initialize()
    assert router.joinable_tenants() == ['beta']
    assert router.register(555, 'New Worker', 'beta') is True
    key, row = router.membership(555)
    assert key == 'beta' and row['tenant'] == 'beta-client' and row['sector'] == 'BE-001'
    assert router.register(555, 'New Worker', 'beta') is True  # idempotent
    with sqlite3.connect(dbs['main']) as c:
        c.execute("INSERT INTO sector_employees (sector, telegram_user_id) VALUES ('X', '666')")
    with sqlite3.connect(dbs['alpha']) as c:
        c.execute("INSERT INTO work_sessions (user_id) VALUES ('777')")
    assert router.legacy_dbs('beta') == (os.path.abspath(dbs['main']), os.path.abspath(dbs['alpha']))
    assert router.register(666, 'Main Worker', 'beta') is False
    assert router.register(777, 'Alpha Worker', 'beta') is False
    assert router.membership(666) is None and router.membership(777) is None


def test_enqueue_requires_membership_of_that_tenant(env):
    router, dbs = env['router'], env['dbs']
    router.initialize()
    router.register(555, 'W', 'beta')
    router.enqueue(_update(555, 'hello', update_id=41), 'beta')
    assert _inbox(dbs['beta']) == [(41, '555', 'pending', 0)]
    with pytest.raises(ValueError, match='not_registered'):
        router.enqueue(_update(555, 'x', update_id=42), 'alpha')
    with pytest.raises(ValueError, match='not_registered'):
        router.enqueue(_update(888, 'x', update_id=43), 'beta')
    assert _inbox(dbs['alpha']) == []


def test_admin_enqueue_requires_current_tenant_and_epoch(env):
    router, cc, dbs = env['router'], env['cc'], env['dbs']
    router.initialize()
    router.enqueue(_update(ADMIN, 'x', update_id=50), 'alpha', 1)
    with pytest.raises(ValueError, match='stale_company'):
        router.enqueue(_update(ADMIN, 'x', update_id=51), 'beta', 1)
    cc.switch(ADMIN, 'beta')
    with pytest.raises(ValueError, match='stale_company'):
        router.enqueue(_update(ADMIN, 'x', update_id=52), 'beta', 1)
    router.enqueue(_update(ADMIN, 'x', update_id=53), 'beta', 2)
    assert [r[0] for r in _inbox(dbs['alpha'])] == [50] and [(r[0], r[3]) for r in _inbox(dbs['beta'])] == [(53, 2)]


def test_route_unknown_user_falls_through_to_legacy_handlers(env):
    router, dbs = env['router'], env['dbs']
    router.initialize()
    assert asyncio.run(router.route(_update(999, 'hello'), None)) is None
    assert asyncio.run(router.route(_update(999, '/start'), None)) is None
    assert _inbox(dbs['alpha']) == [] and _inbox(dbs['beta']) == []


def test_route_invite_registers_and_member_updates_are_queued(env):
    router, dbs = env['router'], env['dbs']
    router.initialize()
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(router.route(_update(555, '/start JOIN-BETA', update_id=60), None))
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(router.route(_update(555, 'any text', update_id=61), None))
    assert [r[0] for r in _inbox(dbs['beta'])] == [60, 61]
    with pytest.raises(ApplicationHandlerStop):  # group chats are never routed or queued
        asyncio.run(router.route(_update(555, 'group text', chat_type='group', update_id=62), None))
    assert [r[0] for r in _inbox(dbs['beta'])] == [60, 61]


def test_route_admin_switch_by_command_and_invite(env):
    router, cc, dbs = env['router'], env['cc'], env['dbs']
    router.initialize()
    sent = []

    async def reply_text(self, text, **kw):
        sent.append(text)
    import telegram
    original = telegram.Message.reply_text
    telegram.Message.reply_text = reply_text
    try:
        with pytest.raises(ApplicationHandlerStop):
            asyncio.run(router.route(_update(ADMIN, '/company beta', update_id=70), type('C', (), {'user_data': {}})()))
        assert cc.selection(ADMIN)['active_tenant'] == 'beta' and 'Beta Client' in sent[-1]
        with pytest.raises(ApplicationHandlerStop):
            asyncio.run(router.route(_update(ADMIN, '/company alpha', update_id=71), type('C', (), {'user_data': {}})()))
        with pytest.raises(ApplicationHandlerStop):
            asyncio.run(router.route(_update(ADMIN, 'JOIN-BETA', update_id=72), type('C', (), {'user_data': {}})()))
        sel = cc.selection(ADMIN)
        assert (sel['active_tenant'], sel['routing_epoch']) == ('beta', 4)
        with pytest.raises(ApplicationHandlerStop):
            asyncio.run(router.route(_update(ADMIN, 'field note', update_id=73), type('C', (), {'user_data': {}})()))
        assert [(r[0], r[3]) for r in _inbox(dbs['beta'])] == [(73, 4)]
        with pytest.raises(ApplicationHandlerStop):
            asyncio.run(router.route(_update(999, '/company beta', update_id=74), None))
        assert sent[-1] == 'This action is not available for this account.'
    finally:
        telegram.Message.reply_text = original


# ── bot.py: FOREST_TENANT_ROUTING off = legacy behaviour; on = router first ────

BOT_PROBE = textwrap.dedent('''
    import json, os, sys, types
    sys.path.insert(0, sys.argv[1])
    import telegram.ext as te
    calls = []
    class FakeApp:
        def add_handler(self, handler, group=0):
            calls.append(['handler', type(handler).__name__, getattr(handler.callback, '__name__', None), group])
        def add_error_handler(self, callback):
            calls.append(['error', callback.__name__])
        def run_polling(self, **kw):
            calls.append(['run_polling', sorted(kw)])
    class FakeBuilder:
        def token(self, token):
            return self
        def build(self):
            return FakeApp()
    te.Application.builder = staticmethod(lambda: FakeBuilder())
    if os.environ.get('PROBE_STUB_ROUTER'):
        stub = types.ModuleType('telegram_tenant_router')
        stub.install = lambda app: calls.append(['install'])
        sys.modules['telegram_tenant_router'] = stub
    import bot
    bot.main()
    print('PROBE' + json.dumps({'calls': calls, 'router_imported': 'telegram_tenant_router' in sys.modules,
                                'tenants_imported': any(m.startswith('telegram_tenants') for m in sys.modules)}))
''')


def _probe_bot(tmp_path, extra_env):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('FOREST_', 'PROBE_'))}
    env.update({'DB_PATH': str(tmp_path / 'bot.db'), 'TELEGRAM_BOT_TOKEN': '0:probe', 'PYTHONDONTWRITEBYTECODE': '1'})
    env.update(extra_env)
    script = tmp_path / 'probe.py'
    script.write_text(BOT_PROBE)
    out = subprocess.run([sys.executable, str(script), str(REPO)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    line = [l for l in out.stdout.splitlines() if l.startswith('PROBE')][-1]
    return json.loads(line[5:])


def test_bot_flag_off_never_imports_tenant_routing(tmp_path):
    for value in (None, '', '0', 'true', 'yes'):
        result = _probe_bot(tmp_path, {} if value is None else {'FOREST_TENANT_ROUTING': value})
        assert not result['router_imported'] and not result['tenants_imported'], value
        assert ['install'] not in result['calls']
        assert result['calls'][-1] == ['run_polling', ['allowed_updates']]


def test_bot_flag_on_installs_router_first_and_keeps_legacy_handlers(tmp_path):
    off = _probe_bot(tmp_path, {})['calls']
    on = _probe_bot(tmp_path, {'FOREST_TENANT_ROUTING': '1', 'PROBE_STUB_ROUTER': '1'})['calls']
    assert on[0] == ['install'] and on[1:] == off


# ── worker import bootstrap ───────────────────────────────────────────────────

WORKER_PROBE = textwrap.dedent('''
    import json, runpy, sys
    worker = sys.argv[1]
    sys.path[0] = __import__('os').path.dirname(worker)  # exactly as "python3 <path>/worker.py"
    ns = runpy.run_path(worker, run_name='worker_probe')
    import telegram_handlers, tenant_runtime, telegram_tenants.tenant_runtime as pkg_rt
    print('PROBE' + json.dumps({
        'handlers_from_cwd': telegram_handlers.__file__.startswith(sys.argv[2]),
        'single_runtime': tenant_runtime is pkg_rt and telegram_handlers.H_CURRENT is pkg_rt.CURRENT,
        'location_wrapped': telegram_handlers.handle_location is ns['location'],
        'key': ns['KEY'], 'sector': ns['SECTOR']}))
''')

FAKE_HANDLERS = textwrap.dedent('''
    import os
    from tenant_runtime import make_bot, CURRENT as H_CURRENT
    DB_NAME = os.environ['DB_PATH']
    async def handle_location(update, context):
        pass
''')


def test_worker_bootstrap_uses_instance_handlers_and_one_runtime(env):
    tmp = env['tmp']
    instance = tmp / 'instance'
    instance.mkdir()
    (instance / 'telegram_handlers.py').write_text(FAKE_HANDLERS)
    (tmp / 'wprobe.py').write_text(WORKER_PROBE)
    run_env = dict(os.environ, FOREST_TENANT_KEY='beta', DB_PATH=env['dbs']['beta'], PYTHONDONTWRITEBYTECODE='1')
    out = subprocess.run([sys.executable, str(tmp / 'wprobe.py'), str(REPO / 'telegram_tenants' / 'worker.py'), str(instance)],
                         cwd=instance, env=run_env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    result = json.loads([l for l in out.stdout.splitlines() if l.startswith('PROBE')][-1][5:])
    assert result == {'handlers_from_cwd': True, 'single_runtime': True, 'location_wrapped': True, 'key': 'beta', 'sector': 'BE-001'}
