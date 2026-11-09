"""Isolated tenant consumer. Sends replies but NEVER calls getUpdates/run_polling.
The original poller is the sole receiver for the shared bot identity.
"""
import asyncio,json,logging,os,signal,sqlite3
from datetime import datetime,timezone
from telegram import Update
from telegram.ext import TypeHandler,ApplicationHandlerStop
import sys
from pathlib import Path
_CODE_ROOT=str(Path(__file__).resolve().parents[1])
# Run by path (python3 .../telegram_tenants/worker.py): the package directory must not act
# as a top-level module directory; its modules are imported as telegram_tenants.* only.
if __package__ in (None,'') and sys.path and Path(sys.path[0]).resolve()==Path(__file__).resolve().parent:sys.path.pop(0)
if _CODE_ROOT not in sys.path:sys.path.append(_CODE_ROOT)
# The instance working directory stays first: telegram_handlers, database and services
# must come from the tenant instance, never from this code root.
sys.path.insert(0,str(Path.cwd()))
from telegram_tenants import install_module_aliases
install_module_aliases()
from telegram_tenants import company_context as companies
from telegram_tenants.tenant_runtime import CURRENT
KEY=os.environ['FOREST_TENANT_KEY']
TENANT=companies.tenant(KEY)
import telegram_handlers as handlers

DB=TENANT['database']
SECTOR=TENANT['sector']
assert os.environ['DB_PATH']==DB
assert str(handlers.DB_NAME)==DB
log=logging.getLogger(__name__)

def connect():
 c=sqlite3.connect(DB,timeout=15);c.row_factory=sqlite3.Row;return c

def member(uid):
 with connect() as c:
  if companies.is_admin(uid):
   sel=companies.selection(uid)
   if sel['active_tenant']!=KEY:return None
   r=c.execute('SELECT id,full_name FROM sector_employees WHERE telegram_user_id=? AND sector=? ORDER BY id LIMIT 1',(str(uid),SECTOR)).fetchone()
   if not r:return None
   return {'telegram_user_id':str(uid),'tenant':TENANT['tenant'],'sector':SECTOR,'employee_id':r['id']}
  r=c.execute('SELECT * FROM telegram_tenant_memberships WHERE telegram_user_id=? AND tenant=? AND sector=?',(str(uid),TENANT['tenant'],SECTOR)).fetchone()
  return dict(r) if r else None

async def guard(update,context):
 uid=str(update.effective_user.id) if update.effective_user else ''
 m=member(uid) if uid else None
 if not m or not update.effective_chat or update.effective_chat.type!='private':raise ApplicationHandlerStop
 ctx=CURRENT.get()
 if not ctx:raise RuntimeError('missing_routing_context')
 if not context.user_data:
  with connect() as c:r=c.execute('SELECT state_json FROM telegram_worker_state WHERE telegram_user_id=?',(uid,)).fetchone()
  if r:context.user_data.update(json.loads(r[0]))
 if companies.is_admin(uid) and context.user_data.get('_routing_epoch')!=ctx['epoch']:
  context.user_data.clear()
  context.user_data['_routing_epoch']=ctx['epoch']
 # Normal workers retain restart recovery; admin contexts do not revive an old-company flow.
 active=handlers.get_latest_open_session(uid)
 if active and (not companies.is_admin(uid) or context.user_data.get('active_work_session',{}).get('id')==active['id']):
  context.user_data['active_work_session']={k:active[k] for k in ['id','employee','contractor','sector','check_in_time']}
  context.user_data['active_work_session']['approved']=active['approved']=='YES'
 else:
  context.user_data.pop('active_work_session',None);context.user_data.pop('live_track',None)
 msg=update.effective_message;text=(getattr(msg,'text',None) or '').strip()
 invite=companies.invite_code(KEY)
 if (invite is not None and text==invite) or (text.split() and text.split()[0].split('@')[0] in ('/start','/join')):
  if companies.is_admin(uid):await msg.reply_text(companies.indicator(companies.selection(uid)))
  else:await msg.reply_text(f"✅ Connected to {TENANT['name']}\nSector: {SECTOR}\n\nUse 📍 GPS Check-in, select your sector, then share your location. For a route, share Telegram Live Location. Finish with /finish.")
  await handlers.start(update,context)
  raise ApplicationHandlerStop
 if update.callback_query:
  data=update.callback_query.data or ''
  if data.startswith('linkemp:') and data.split(':',1)[1]!=str(m['employee_id']):
   await update.callback_query.answer('Use your assigned worker profile.');raise ApplicationHandlerStop
  if data.startswith(('checkin_sector:','vehgps_sector:')) and data.split(':',1)[1]!=SECTOR:
   await update.callback_query.answer('Choose your assigned sector.');raise ApplicationHandlerStop
 if update.edited_message and update.edited_message.location and not context.user_data.get('active_work_session'):raise ApplicationHandlerStop

_original_location=handlers.handle_location
async def location(update,context):
 msg=update.edited_message or update.message
 loc=msg.location
 # Preserve current GPS positions too; the original only records route points for live shares.
 if not update.edited_message and not handlers._live_period_s(loc) and context.user_data.get('active_work_session') and not context.user_data.get('pending_checkin_sector') and not context.user_data.get('demo_brk_loc_incident') and context.user_data.get('pending_vehicle_id') is None:
  active=context.user_data['active_work_session'];uid=str(update.effective_user.id);m=member(uid)
  handlers.upsert_live_location(m['employee_id'],uid,SECTOR,loc.latitude,loc.longitude,0,new_share=True)
  handlers.session_track.record_point(active['id'],m['employee_id'],uid,msg.message_id,SECTOR,loc.latitude,loc.longitude,loc.horizontal_accuracy,handlers._is_inside_sector(SECTOR,loc.latitude,loc.longitude),handlers._msg_time_utc(msg),datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
  await msg.reply_text(f'📍 GPS position recorded for {SECTOR}.');return
 await _original_location(update,context)
 if not update.edited_message and context.user_data.get('active_work_session') and not context.user_data['active_work_session'].get('approved'):
  await msg.reply_text(f'Your position/session was recorded outside the {SECTOR} boundary and a risk was created. You can still send field photos or observations.',reply_markup=handlers.work_keyboard())
 if not update.edited_message and not handlers._live_period_s(loc) and context.user_data.get('active_work_session'):
  active=context.user_data['active_work_session'];uid=str(update.effective_user.id);m=member(uid)
  handlers.upsert_live_location(m['employee_id'],uid,SECTOR,loc.latitude,loc.longitude,0,new_share=True)
  handlers.session_track.record_point(active['id'],m['employee_id'],uid,msg.message_id,SECTOR,loc.latitude,loc.longitude,loc.horizontal_accuracy,handlers._is_inside_sector(SECTOR,loc.latitude,loc.longitude),handlers._msg_time_utc(msg),datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
handlers.handle_location=location

async def process_envelope(app,row,failures):
 try:
  async with companies.user_lock(row['telegram_user_id']):
   uid=row['telegram_user_id'];admin=companies.is_admin(uid)
   sel=companies.selection(uid) if admin else None
   if admin and (sel['active_tenant']!=KEY or sel['routing_epoch']!=row['routing_epoch']):
    with connect() as c:c.execute("UPDATE telegram_update_inbox SET status='skipped',error_code='stale_company',payload_json='{}' WHERE update_id=?",(row['update_id'],))
    return
   ctx={'uid':uid,'key':KEY,'epoch':row['routing_epoch']}
   token=CURRENT.set(ctx)
   try:
    payload=json.loads(row['payload_json'])
    if admin and 'callback_query' in payload:
     prefix=f"ctx:{KEY}:{row['routing_epoch']}|"
     data=payload['callback_query'].get('data','')
     if not data.startswith(prefix):raise ValueError('stale_callback')
     payload['callback_query']['data']=data[len(prefix):]
    update=Update.de_json(payload,app.bot)
    if not update.effective_user or str(update.effective_user.id)!=uid or not member(uid):raise ValueError('tenant_mismatch')
    await app.process_update(update)
    if update.update_id in failures:
     failures.discard(update.update_id);raise RuntimeError('handler_failed')
    data=dict(app.user_data.get(update.effective_user.id,{}))
    if admin:data['_routing_epoch']=ctx['epoch']
    with connect() as c:
     c.execute('INSERT OR REPLACE INTO telegram_worker_state VALUES (?,?)',(uid,json.dumps(data)))
     c.execute("UPDATE telegram_update_inbox SET status='done',payload_json='{}',processed_at=? WHERE update_id=?",(datetime.now(timezone.utc).isoformat(),row['update_id']))
   finally:CURRENT.reset(token)
 except Exception:
  log.exception('Tenant update failed; retained for administrator review')
  with connect() as c:c.execute("UPDATE telegram_update_inbox SET status='failed',error_code='processing_failed' WHERE update_id=?",(row['update_id'],))

async def run():
 app=handlers.build_application();app.add_handler(TypeHandler(Update,guard),group=-100)
 failures=set()
 async def record_error(update,context):
  if update:failures.add(update.update_id)
 app.add_error_handler(record_error)
 # Crash-interrupted writes require review rather than blindly duplicating a session/photo.
 with connect() as c:c.execute("UPDATE telegram_update_inbox SET status='failed',error_code='interrupted_review_required' WHERE status='processing'")
 stop=asyncio.Event();loop=asyncio.get_running_loop()
 for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stop.set)
 async with app:
  await app.start()
  try:
   while not stop.is_set():
    with connect() as c:
     row=c.execute("SELECT * FROM telegram_update_inbox WHERE status='pending' ORDER BY update_id LIMIT 1").fetchone()
     if row:c.execute("UPDATE telegram_update_inbox SET status='processing' WHERE update_id=?",(row['update_id'],))
    if not row:
     try:await asyncio.wait_for(stop.wait(),timeout=.5)
     except asyncio.TimeoutError:pass
     continue
    await process_envelope(app,row,failures)
  finally:await app.stop()
if __name__=='__main__':asyncio.run(run())
