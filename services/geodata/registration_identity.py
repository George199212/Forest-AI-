"""Server-derived identity adapter for the existing per-instance Basic account.

This deployment has no individual users/memberships/profile session. Do not turn
contact names or a shared Basic login into fictional individual user identities.
"""
from contextlib import closing
import sqlite3
import database


def context(actor):
    from .vmd_dataset import DatasetError
    with closing(sqlite3.connect(database.DB_NAME)) as c:
        organizations=c.execute('SELECT id,name FROM organizations').fetchall()
        if len(organizations)!=1 or organizations[0][0]!=1:
            raise DatasetError('Organizācijas saistība nav pārbaudīta: nepieciešama servera lietotāju un organizāciju autorizācija',503)
        org_id,org_name=organizations[0]
        names=('', '')
        columns={r[1] for r in c.execute('PRAGMA table_info(sectors)')}
        if 'created_by_account' in columns:
            previous=c.execute("SELECT responsible_first_name,responsible_last_name FROM sectors WHERE organization_id=? AND created_by_account=? AND responsible_first_name IS NOT NULL ORDER BY id DESC LIMIT 1",(org_id,actor)).fetchone()
            if previous:names=previous
    return {'organization_id':org_id,'organization_name':org_name,'user_id':None,
            'authenticated_account':actor,'identity_type':'http_basic_shared_account',
            'individual_user_profile_available':False,'responsible_first_name':names[0] or '',
            'responsible_last_name':names[1] or '',
            'prefill_source':'previous_registration_contact' if any(names) else 'none',
            'profile_notice':'Individuāla lietotāja profils šajā kontā nav pieejams. Norādiet atbildīgo personu; kontaktinformācija nepiešķir piekļuves tiesības.'}
