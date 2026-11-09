"""Tenant metadata only. No GPS, photos, comments, or customer records live here.

Paths and identities come from the environment (see docs/TELEGRAM_TENANTS.md):
  FOREST_TELEGRAM_TENANTS_FILE  tenant config JSON   (default data/telegram/tenants.json)
  FOREST_TELEGRAM_ROUTING_DB    admin routing SQLite (default data/telegram/routing.db)
  FOREST_TELEGRAM_LOCK_DIR      per-user lock files  (default /run/forest-ai-telegram-locks)
  FOREST_TELEGRAM_ADMIN_IDS     admin Telegram user ids, comma/space separated
                                (unset: "admin_ids" from the tenants file, else none)
  FOREST_TENANT_INVITE_<KEY>    invite code that lets a worker join tenant <key>
Relative paths resolve against the code root (the directory above this package).
"""
import asyncio,fcntl,json,os,re,sqlite3
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from pathlib import Path
CODE_ROOT=Path(__file__).resolve().parents[1]

def _path(name,default):
 p=Path(os.environ.get(name) or default)
 return p if p.is_absolute() else CODE_ROOT/p

CONFIG=_path('FOREST_TELEGRAM_TENANTS_FILE','data/telegram/tenants.json')
REGISTRY=_path('FOREST_TELEGRAM_ROUTING_DB','data/telegram/routing.db')
LOCK_DIR=_path('FOREST_TELEGRAM_LOCK_DIR','/run/forest-ai-telegram-locks')

def config():
 cfg=json.loads(CONFIG.read_text())
 ids=os.environ.get('FOREST_TELEGRAM_ADMIN_IDS','').replace(',',' ').split()
 if ids:cfg['admin_ids']=[int(i) for i in ids]
 else:cfg.setdefault('admin_ids',[])
 return cfg
def is_admin(uid):return int(uid) in config()['admin_ids']
def tenant(key):return config()['tenants'][key]

def invite_code(key):
 """Invite code for tenant <key>, or None when joining that tenant is disabled."""
 return os.environ.get('FOREST_TENANT_INVITE_'+re.sub(r'[^A-Z0-9]','_',key.upper()),'').strip() or None
def invite_tenant(text):
 """Tenant key whose invite the text is ("CODE", "/start CODE" or "/join CODE"), else None."""
 parts=(text or '').strip().split()
 if not parts:return None
 for key in config()['tenants']:
  code=invite_code(key)
  if code and (parts==[code] or (parts[0].split('@')[0] in ('/start','/join') and len(parts)==2 and parts[1]==code)):return key
 return None

def connection(readonly=False):
 c=sqlite3.connect('file:'+str(REGISTRY)+'?mode=ro',uri=True,timeout=15) if readonly else sqlite3.connect(REGISTRY,timeout=15)
 c.row_factory=sqlite3.Row;return c

def initialize():
 LOCK_DIR.mkdir(mode=0o700,exist_ok=True)
 with connection() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS admin_company_context (
   telegram_user_id TEXT PRIMARY KEY, active_tenant TEXT NOT NULL,
   active_sector TEXT NOT NULL, admin_mode INTEGER NOT NULL DEFAULT 1,
   routing_epoch INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS telegram_message_bindings (
   telegram_user_id TEXT NOT NULL, chat_id TEXT NOT NULL, message_id INTEGER NOT NULL,
   tenant TEXT NOT NULL, routing_epoch INTEGER NOT NULL,
   PRIMARY KEY(telegram_user_id,chat_id,message_id));''')
  cfg=config();key=cfg['default_admin_tenant'];t=cfg['tenants'][key]
  for uid in cfg['admin_ids']:
   c.execute('INSERT OR IGNORE INTO admin_company_context VALUES (?,?,?,?,?,?)',(str(uid),key,t['sector'],1,1,datetime.now(timezone.utc).isoformat()))
 os.chmod(REGISTRY,0o600)

def selection(uid):
 if not is_admin(uid):return None
 with connection(True) as c:
  row=c.execute('SELECT * FROM admin_company_context WHERE telegram_user_id=?',(str(uid),)).fetchone()
 if not row:raise RuntimeError('admin_context_missing')
 d=dict(row)
 if d['active_tenant'] not in config()['tenants'] or not d['admin_mode']:raise RuntimeError('invalid_admin_context')
 return d

def switch(uid,key):
 if not is_admin(uid):raise PermissionError('admin_only')
 t=tenant(key)
 with connection() as c:
  c.execute('UPDATE admin_company_context SET active_tenant=?,active_sector=?,routing_epoch=routing_epoch+1,updated_at=? WHERE telegram_user_id=?',
            (key,t['sector'],datetime.now(timezone.utc).isoformat(),str(uid)))
 return selection(uid)

@asynccontextmanager
async def user_lock(uid):
 f=open(LOCK_DIR/(str(int(uid))+'.lock'),'a');os.chmod(f.name,0o600)
 try:
  while True:
   try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);break
   except BlockingIOError:await asyncio.sleep(.05)
  yield
 finally:fcntl.flock(f,fcntl.LOCK_UN);f.close()

def bind_message(uid,chat,mid,key,epoch):
 with connection() as c:c.execute('INSERT OR IGNORE INTO telegram_message_bindings VALUES (?,?,?,?,?)',(str(uid),str(chat),mid,key,epoch))
def message_matches(uid,chat,mid,key,epoch):
 with connection(True) as c:r=c.execute('SELECT tenant,routing_epoch FROM telegram_message_bindings WHERE telegram_user_id=? AND chat_id=? AND message_id=?',(str(uid),str(chat),mid)).fetchone()
 return bool(r and r['tenant']==key and r['routing_epoch']==epoch)

def indicator(sel):
 t=tenant(sel['active_tenant'])
 return f"🏢 Active company: {t['name']}\n📍 Sector: {sel['active_sector']}\n🛠 Admin/Test mode"
