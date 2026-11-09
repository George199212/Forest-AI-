"""Single polling ingress. Tenant envelopes and memberships live only in the tenant's SQLite.
No handler globals, working directories, or existing database settings are switched.
Any routing/storage failure stops the update; it never falls through to legacy writes.

Installed by bot.py only when FOREST_TENANT_ROUTING=1. Tenants come from the tenants file
(FOREST_TELEGRAM_TENANTS_FILE). A worker can join a tenant only when that tenant has an
invite code (FOREST_TENANT_INVITE_<KEY>); such tenants are "joinable".
See docs/TELEGRAM_TENANTS.md.
"""
import json
import os
from telegram_tenants import company_context as companies
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationHandlerStop, TypeHandler

SCHEMA = '''
CREATE TABLE IF NOT EXISTS telegram_tenant_memberships (
 telegram_user_id TEXT PRIMARY KEY, tenant TEXT NOT NULL{tenant_check},
 sector TEXT NOT NULL{sector_check}, employee_id INTEGER NOT NULL,
 registered_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS telegram_update_inbox (
 update_id INTEGER PRIMARY KEY, telegram_user_id TEXT NOT NULL,
 payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 received_at TEXT NOT NULL, processed_at TEXT, error_code TEXT);
CREATE TABLE IF NOT EXISTS telegram_worker_state (
 telegram_user_id TEXT PRIMARY KEY, state_json TEXT NOT NULL);
'''

def _sql_text(value):
    return "'"+str(value).replace("'","''")+"'"

def schema(t, joinable):
    """Joinable tenants pin memberships to their own tenant and sector with CHECK constraints."""
    if not joinable:return SCHEMA.format(tenant_check='',sector_check='')
    return SCHEMA.format(tenant_check=' CHECK(tenant='+_sql_text(t['tenant'])+')',sector_check=' CHECK(sector='+_sql_text(t['sector'])+')')

def joinable_tenants():
    return [key for key in companies.config()['tenants'] if companies.invite_code(key)]

def main_db():
    """The poller's own operational DB (same DB_PATH rule as bot.py)."""
    return os.path.abspath(os.environ.get('DB_PATH','data/forest_ai.db'))

def connect(key):
    c=sqlite3.connect(companies.tenant(key)['database'], timeout=15)
    c.row_factory=sqlite3.Row
    return c

def initialize():
    companies.initialize()
    for key,t in companies.config()['tenants'].items():
        with sqlite3.connect(t['database'],timeout=15) as c:
            c.executescript(schema(t, companies.invite_code(key) is not None))
            cols={r[1] for r in c.execute('PRAGMA table_info(telegram_update_inbox)')}
            if 'routing_epoch' not in cols:c.execute('ALTER TABLE telegram_update_inbox ADD COLUMN routing_epoch INTEGER NOT NULL DEFAULT 0')
            for uid in companies.config()['admin_ids']:
                r=c.execute('SELECT id FROM sector_employees WHERE telegram_user_id=? AND sector=? ORDER BY id LIMIT 1',(str(uid),t['sector'])).fetchone()
                if r:c.execute('INSERT OR IGNORE INTO telegram_tenant_memberships VALUES (?,?,?,?,?)',(str(uid),t['tenant'],t['sector'],r[0],datetime.now(timezone.utc).isoformat()))

def membership(uid):
    """(tenant key, membership row) from the first joinable tenant that knows uid, else None."""
    for key in joinable_tenants():
        with connect(key) as c:
            row=c.execute('SELECT * FROM telegram_tenant_memberships WHERE telegram_user_id=?',(str(uid),)).fetchone()
            if row:return key,dict(row)
    return None

def legacy_dbs(key):
    """Every operational DB except the joining tenant's: the poller's own and the other tenants'."""
    own=os.path.abspath(companies.tenant(key)['database'])
    paths=[main_db()]+[os.path.abspath(t['database']) for k,t in companies.config()['tenants'].items() if k!=key]
    return tuple(dict.fromkeys(p for p in paths if p!=own))

def legacy_identity(uid, key):
    # Existing workers are never silently transferred by a public demo invite.
    for path in legacy_dbs(key):
        with sqlite3.connect('file:'+path+'?mode=ro',uri=True,timeout=10) as c:
            for table,col in [('sector_employees','telegram_user_id'),('sector_vehicles','telegram_user_id'),('work_sessions','user_id'),('live_locations','telegram_user_id')]:
                if c.execute(f'SELECT 1 FROM {table} WHERE {col}=? LIMIT 1',(str(uid),)).fetchone():return True
    return False

def register(uid, name, key):
    if legacy_identity(uid, key):return False
    t=companies.tenant(key)
    now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    with connect(key) as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM telegram_tenant_memberships WHERE telegram_user_id=?',(str(uid),)).fetchone():return True
        assert c.execute('SELECT 1 FROM sectors WHERE name=?',(t['sector'],)).fetchone()
        # Do not take ownership of historical copied employees.
        eid=c.execute('INSERT INTO sector_employees (sector,full_name,role,active,created_at,telegram_user_id) VALUES (?,?,?,?,?,?)',
                      (t['sector'],name[:200],'Field worker',1,now,str(uid))).lastrowid
        c.execute('INSERT INTO telegram_tenant_memberships VALUES (?,?,?,?,?)',(str(uid),t['tenant'],t['sector'],eid,now))
    return True

def enqueue(update,key,epoch=0):
    uid=str(update.effective_user.id)
    if companies.is_admin(uid):
        sel=companies.selection(uid)
        if sel['active_tenant']!=key or sel['routing_epoch']!=epoch:raise ValueError('stale_company')
    else:
        member=membership(uid)
        if not member or member[0]!=key:raise ValueError('not_registered')
    payload=update.to_json()
    if len(payload)>1000000:raise ValueError('update_too_large')
    with sqlite3.connect(companies.tenant(key)['database'],timeout=15) as c:
        c.execute('INSERT OR IGNORE INTO telegram_update_inbox (update_id,telegram_user_id,payload_json,received_at,routing_epoch) VALUES (?,?,?,?,?)',
                  (update.update_id,uid,payload,datetime.now(timezone.utc).isoformat(),epoch))

SWITCH_BUTTON='🏢 Switch Company'

def admin_keyboard():
    return ReplyKeyboardMarkup([['🌲 Sectors','⚠️ Risks'],['📍 GPS Check-in','✅ Finish Work'],['🚛 Vehicle GPS','🪵 Timber Movement'],['🚛 Truck Report','📊 Report'],['📤 Export Report',SWITCH_BUTTON]],resize_keyboard=True)

def company_keyboard(sel):
    return InlineKeyboardMarkup([[InlineKeyboardButton('🌲 '+t['name'],callback_data=f"company:{key}:{sel['routing_epoch']}")] for key,t in companies.config()['tenants'].items()])

async def admin_route(update,context):
    uid=update.effective_user.id
    async with companies.user_lock(uid):
        sel=companies.selection(uid)
        text=(getattr(update.effective_message,'text',None) or '').strip()
        query=update.callback_query;data=query.data if query else ''
        words=text.split();command=words[0].split('@')[0] if words else ''
        target=None
        if command=='/company' and len(words)>1:target=words[1].lower()
        invited=companies.invite_tenant(text)
        if invited:target=invited
        if query and data.startswith('company:'):
            parts=data.split(':')
            if len(parts)!=3 or parts[2]!=str(sel['routing_epoch']):
                await query.answer('This company menu has expired. Send /company.');return
            target=parts[1]
        if target:
            if target not in companies.config()['tenants']:
                await update.effective_message.reply_text('Unknown company. Use /company.');return
            sel=companies.switch(uid,target)
            # The legacy poller must not retain a session/incident context for this admin.
            context.user_data.clear()
            if query:await query.answer()
            await update.effective_message.reply_text(companies.indicator(sel),reply_markup=admin_keyboard())
            return
        if text==SWITCH_BUTTON or command=='/company':
            await update.effective_message.reply_text(companies.indicator(sel),reply_markup=company_keyboard(sel));return
        # Old inline buttons carry their originating company and epoch.
        if query:
            prefix=f"ctx:{sel['active_tenant']}:{sel['routing_epoch']}|"
            if not (data or '').startswith(prefix):
                await query.answer('This button belongs to an earlier company context. Send /start.');return
        msg=update.edited_message or update.message
        if update.edited_message:
            if not companies.message_matches(uid,msg.chat_id,msg.message_id,sel['active_tenant'],sel['routing_epoch']):return
        elif msg and msg.location:
            companies.bind_message(uid,msg.chat_id,msg.message_id,sel['active_tenant'],sel['routing_epoch'])
        enqueue(update,sel['active_tenant'],sel['routing_epoch'])

async def route(update, context):
    user=update.effective_user
    if not user:return
    try:
        text=getattr(update.effective_message,'text',None) or ''
        data=update.callback_query.data if update.callback_query else ''
        admin_control=text.strip()==SWITCH_BUTTON or (text.split() and text.split()[0].split('@')[0]=='/company') or (data or '').startswith('company:')
        if companies.is_admin(user.id):
            if not update.effective_chat or update.effective_chat.type!='private':
                if update.callback_query:await update.callback_query.answer('Use a private chat with the bot.')
                raise ApplicationHandlerStop
            await admin_route(update,context)
            raise ApplicationHandlerStop
        if admin_control:
            if update.callback_query:await update.callback_query.answer('This action is not available.')
            elif update.effective_message:await update.effective_message.reply_text('This action is not available for this account.')
            raise ApplicationHandlerStop
        member=membership(user.id)
        joining=companies.invite_tenant(text)
        if not member and not joining:return
        if not update.effective_chat or update.effective_chat.type!='private':
            if update.callback_query:await update.callback_query.answer('Use a private chat with the bot.')
            raise ApplicationHandlerStop
        if joining and not member:
            if not register(user.id,user.full_name,joining):
                await update.effective_message.reply_text('This Telegram account is already linked to an existing Forest AI workflow. Ask the administrator before changing company.')
                raise ApplicationHandlerStop
            member=(joining,None)
        enqueue(update,member[0])
    except ApplicationHandlerStop:raise
    except Exception:
        logging.exception('Tenant routing failed; legacy handlers blocked')
        try:
            if update.effective_message:await update.effective_message.reply_text('The company connection is temporarily unavailable. Please try again. Your update was not sent to another company.')
        except Exception:pass
    raise ApplicationHandlerStop

def install(app):
    initialize()
    app.add_handler(TypeHandler(Update, route),group=-100)
