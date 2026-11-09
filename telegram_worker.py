"""Ingka-only consumer. Sends replies but NEVER calls getUpdates/run_polling.
The original poller is the sole receiver for the shared bot identity.
"""
import asyncio,json,logging,os,signal,sqlite3
from datetime import datetime,timezone
from telegram import Update
from telegram.ext import TypeHandler,ApplicationHandlerStop
import telegram_handlers as handlers

DB=os.environ['DB_PATH']  # redacted for git: the instance file hard-codes the Ingka DB path
assert os.environ['DB_PATH']==DB
assert str(handlers.DB_NAME)==DB
log=logging.getLogger(__name__)

def connect():
 c=sqlite3.connect(DB,timeout=15);c.row_factory=sqlite3.Row;return c

def member(uid):
 with connect() as c:
  r=c.execute("SELECT * FROM telegram_tenant_memberships WHERE telegram_user_id=? AND tenant='ingka-investments-latvia' AND sector='ING-001'",(str(uid),)).fetchone()
  return dict(r) if r else None

async def guard(update,context):
 m=member(update.effective_user.id) if update.effective_user else None
 if not m or not update.effective_chat or update.effective_chat.type!='private':raise ApplicationHandlerStop
 # Recover session/state across worker restarts, always from this tenant's DB.
 uid=str(update.effective_user.id)
 if not context.user_data:
  with connect() as c:r=c.execute('SELECT state_json FROM telegram_worker_state WHERE telegram_user_id=?',(uid,)).fetchone()
  if r:context.user_data.update(json.loads(r[0]))
 active=handlers.get_latest_open_session(uid)
 if active:
  context.user_data['active_work_session']={k:active[k] for k in ['id','employee','contractor','sector','check_in_time']}
  context.user_data['active_work_session']['approved']=active['approved']=='YES'
 else:
  context.user_data.pop('active_work_session',None);context.user_data.pop('live_track',None)
 msg=update.effective_message;text=(getattr(msg,'text',None) or '').strip()
 if text==os.environ.get('FOREST_TENANT_INVITE_INGKA','\0') or (text.split() and text.split()[0].split('@')[0] in ('/start','/join')):
  await msg.reply_text('✅ Connected to Ingka Investments Latvia\nSector: ING-001\n\nUse 📍 GPS Check-in, select ING-001, then share your location. For a route, share Telegram Live Location. Finish with /finish.')
  await handlers.start(update,context)
  raise ApplicationHandlerStop
 # Never apply callback employee/sector IDs from another company or old messages.
 if update.callback_query:
  data=update.callback_query.data or ''
  if data.startswith('linkemp:'):
   if data.split(':',1)[1]!=str(m['employee_id']):
    await update.callback_query.answer('Use your assigned worker profile.');raise ApplicationHandlerStop
  if data.startswith(('checkin_sector:','vehgps_sector:')) and data.split(':',1)[1]!='ING-001':
   await update.callback_query.answer('Choose ING-001.');raise ApplicationHandlerStop
 if update.edited_message and update.edited_message.location and not active:raise ApplicationHandlerStop

_original_location=handlers.handle_location
async def location(update,context):
 msg=update.edited_message or update.message
 loc=msg.location
 # Preserve current GPS positions too; the original only records route points for live shares.
 if not update.edited_message and not handlers._live_period_s(loc) and context.user_data.get('active_work_session') and not context.user_data.get('pending_checkin_sector') and not context.user_data.get('demo_brk_loc_incident') and context.user_data.get('pending_vehicle_id') is None:
  active=context.user_data['active_work_session'];uid=str(update.effective_user.id);m=member(uid)
  handlers.upsert_live_location(m['employee_id'],uid,'ING-001',loc.latitude,loc.longitude,0,new_share=True)
  handlers.session_track.record_point(active['id'],m['employee_id'],uid,msg.message_id,'ING-001',loc.latitude,loc.longitude,loc.horizontal_accuracy,handlers._is_inside_sector('ING-001',loc.latitude,loc.longitude),handlers._msg_time_utc(msg),datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
  await msg.reply_text('📍 GPS position recorded for ING-001.');return
 await _original_location(update,context)
 if not update.edited_message and context.user_data.get('active_work_session') and not context.user_data['active_work_session'].get('approved'):
  await msg.reply_text('Your position/session was recorded outside the ING-001 boundary and a risk was created. You can still send field photos or observations.',reply_markup=handlers.work_keyboard())
 if not update.edited_message and not handlers._live_period_s(loc) and context.user_data.get('active_work_session'):
  active=context.user_data['active_work_session'];uid=str(update.effective_user.id);m=member(uid)
  handlers.upsert_live_location(m['employee_id'],uid,'ING-001',loc.latitude,loc.longitude,0,new_share=True)
  handlers.session_track.record_point(active['id'],m['employee_id'],uid,msg.message_id,'ING-001',loc.latitude,loc.longitude,loc.horizontal_accuracy,handlers._is_inside_sector('ING-001',loc.latitude,loc.longitude),handlers._msg_time_utc(msg),datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'))
handlers.handle_location=location

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
    try:
     update=Update.de_json(json.loads(row['payload_json']),app.bot)
     if not update.effective_user or str(update.effective_user.id)!=row['telegram_user_id'] or not member(row['telegram_user_id']):raise ValueError('tenant_mismatch')
     await app.process_update(update)
     if update.update_id in failures:
      failures.discard(update.update_id);raise RuntimeError('handler_failed')
     data=dict(app.user_data.get(update.effective_user.id,{}))
     with connect() as c:
      c.execute('INSERT OR REPLACE INTO telegram_worker_state VALUES (?,?)',(row['telegram_user_id'],json.dumps(data)))
      c.execute("UPDATE telegram_update_inbox SET status='done',payload_json='{}',processed_at=? WHERE update_id=?",(datetime.now(timezone.utc).isoformat(),row['update_id']))
    except Exception:
     log.exception('Ingka update failed; retained for administrator review')
     with connect() as c:c.execute("UPDATE telegram_update_inbox SET status='failed',error_code='processing_failed' WHERE update_id=?",(row['update_id'],))
  finally:await app.stop()
if __name__=='__main__':asyncio.run(run())
