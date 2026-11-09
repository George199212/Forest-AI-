"""Per-update identity and presentation, independent of customer DB globals."""
from contextvars import ContextVar
from telegram import InlineKeyboardMarkup,InlineKeyboardButton,ReplyKeyboardMarkup
from telegram.ext import ExtBot
from telegram_tenants import company_context as companies
CURRENT=ContextVar('telegram_tenant_update',default=None)
BUTTON='🏢 Switch Company'

def markup(value):
 ctx=CURRENT.get()
 if not ctx or not companies.is_admin(ctx['uid']):return value
 if isinstance(value,InlineKeyboardMarkup):
  rows=[]
  prefix=f"ctx:{ctx['key']}:{ctx['epoch']}|"
  for row in value.inline_keyboard:
   buttons=[]
   for button in row:
    d=button.to_dict()
    if isinstance(d.get('callback_data'),str) and not d['callback_data'].startswith('ctx:'):
     d['callback_data']=prefix+d['callback_data']
     if len(d['callback_data'].encode())>64:raise ValueError('callback_too_long')
    buttons.append(InlineKeyboardButton.de_json(d,None))
   rows.append(buttons)
  return InlineKeyboardMarkup(rows)
 if isinstance(value,ReplyKeyboardMarkup):
  rows=[list(r) for r in value.keyboard]
  if not any(getattr(b,'text','')==BUTTON for row in rows for b in row):rows.append([BUTTON])
  return ReplyKeyboardMarkup(rows,resize_keyboard=True,one_time_keyboard=value.one_time_keyboard)
 return value

class TenantBot(ExtBot):
 async def send_message(self,*args,**kwargs):
  if 'reply_markup' in kwargs:kwargs['reply_markup']=markup(kwargs['reply_markup'])
  return await super().send_message(*args,**kwargs)
 async def edit_message_reply_markup(self,*args,**kwargs):
  if 'reply_markup' in kwargs:kwargs['reply_markup']=markup(kwargs['reply_markup'])
  return await super().edit_message_reply_markup(*args,**kwargs)

def make_bot(token):return TenantBot(token=token)
