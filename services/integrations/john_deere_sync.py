"""Manual sandbox machine pipeline over existing equipment/GPS/risk tables.

No scheduler, sample data, geographic assignment, or OAuth implementation lives here.
"""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import database
from services import geo
from services.integrations import john_deere as jd
from services.integrations.john_deere_machines import MachineService, label, normalize, number

PROVIDER = 'john_deere'
KINDS = ('organizations', 'machines', 'telemetry', 'all')
RELATIONS = ('locationHistory', 'breadcrumbs', 'engineHours', 'hoursOfOperation', 'alerts', 'deviceStateReports')


def utc():
    return datetime.now(timezone.utc).isoformat()


def epoch(value):
    try:
        result = datetime.fromisoformat(str(value).replace(' UTC', '+00:00').replace('Z', '+00:00'))
        return result.replace(tzinfo=result.tzinfo or timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


def setting(name, default, minimum=0):
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except ValueError:
        return default


def health(timestamp):
    t = epoch(timestamp)
    if t is None or t > time.time()+300:
        return 'UNKNOWN'
    stale = setting('JOHN_DEERE_TELEMETRY_STALE_SECONDS', 21600, 60)
    offline = max(stale, setting('JOHN_DEERE_TELEMETRY_OFFLINE_SECONDS', 86400, 60))
    age = time.time()-t
    return 'OFFLINE' if age >= offline else 'STALE' if age >= stale else 'LIVE'


def polygon(value):
    try:
        points = json.loads(value) if isinstance(value, str) else value
        if not isinstance(points, list) or len(points) < 3: return None
        if not all(isinstance(p, (list, tuple)) and len(p)==2 and number(p[0]) is not None
                   and number(p[1]) is not None and -90<=float(p[0])<=90 and -180<=float(p[1])<=180 for p in points):return None
        return [[float(a),float(b)] for a,b in points]
    except (ValueError,TypeError): return None


def geofence(conn, sector, lat, lon):
    if not sector or lat is None or lon is None:return 'UNKNOWN'
    rows = conn.execute('SELECT boundary_json FROM sectors WHERE name=?', (sector,)).fetchall()
    if len(rows)!=1:return 'UNKNOWN'  # ambiguous sector names are not authority
    boundary = polygon(rows[0][0])
    if not boundary:return 'UNKNOWN'
    return 'INSIDE' if geo.point_in_polygon(lat,lon,boundary) else 'OUTSIDE'


class SyncError(jd.DeereError):
    def __init__(self, status, retry_after=0):
        super().__init__(status)
        self.status, self.retry_after = status, retry_after


class SyncClient(jd.Client):
    """Structured resource failures; token exchange/refresh remain inherited."""
    def __init__(self, account):
        super().__init__(account)
        self.calls = 0

    def ensure_auth(self):
        try:
            tokens = self.tokens()
            if jd.expired(tokens):self.refresh()
        except jd.DeereError:
            raise SyncError('AUTH REQUIRED') from None

    def get(self, uri):
        uri = jd.safe_link(uri)
        self.calls += 1
        if self.calls > setting('JOHN_DEERE_SYNC_MAX_REQUESTS', 100, 1):
            raise SyncError('RATE LIMITED',60)
        with jd._lock:
            self.ensure_auth()
            tokens = self.tokens()
            def request():
                try:
                    return jd._request('GET',uri,headers={'Accept':'application/vnd.deere.axiom.v3+json',
                                              'Authorization':'Bearer '+tokens['access_token']})
                except jd.DeereError:raise SyncError('TEMPORARY ERROR') from None
            response = request()
            if response.status_code == 401:
                try:tokens = self.refresh()
                except jd.DeereError:raise SyncError('AUTH REQUIRED') from None
                response = request()
            code = response.status_code
            if code == 401:raise SyncError('AUTH REQUIRED')
            if code == 403:raise SyncError('PERMISSION REQUIRED')
            if code == 404:raise SyncError('RESOURCE UNAVAILABLE')
            if code == 429:
                raw = response.headers.get('Retry-After','60')
                try:delay = max(60,int(raw))
                except (TypeError,ValueError):
                    try:delay=max(60,int(parsedate_to_datetime(raw).timestamp()-time.time()))
                    except (TypeError,ValueError,OverflowError):delay=60
                raise SyncError('RATE LIMITED',delay)
            if code >= 500:raise SyncError('PROVIDER ERROR')
            if code == 204:return {'values':[], 'links':[]}
            try:return jd._json(response)
            except jd.DeereError:raise SyncError('PROVIDER ERROR') from None


def public_machines():
    """Existing equipment IDs are Objects/Map identities, for any future provider."""
    with jd._db() as conn:
        rows = conn.execute('''SELECT e.id,e.sector,e.provider,e.external_machine_id,e.external_organization_id,
            e.machine_name,e.equipment_code,e.type,e.brand,e.model,e.serial_number,e.machine_status,
            e.latitude,e.longitude,e.location_timestamp,e.engine_hours,e.operating_hours,e.device_status,
            e.last_synchronization_time,e.telemetry_timestamp,e.geofence_status,e.restricted_zone_status,
            o.organization_name FROM sector_equipment e LEFT JOIN integration_organizations o
            ON e.provider=o.provider AND e.external_organization_id=o.external_organization_id
            WHERE e.provider IS NOT NULL AND COALESCE(e.is_demo,0)=0 ORDER BY e.id''').fetchall()
        return [dict(dict(row), telemetry_health=health(row['telemetry_timestamp'])) for row in rows]


class Sync:
    def __init__(self, account):
        self.client = SyncClient(account)
        self.account = account
        self.reader = MachineService(self.client)
        self.result = None

    def integration(self):
        row = database.get_integration_by_provider(PROVIDER)
        if row:return row['id']
        return database.create_integration(1,'machine',PROVIDER,display_name='John Deere Operations Center — Sandbox',
                                           configuration={'scheduled_polling_enabled':False})

    def status(self):
        with jd._db() as conn:
            orgs=conn.execute('SELECT count(*) FROM integration_organizations WHERE provider=? AND external_account_id=? AND connection_status=?',
                             (PROVIDER,self.account,'Connected')).fetchone()[0]
            rows=conn.execute('SELECT id,latitude,longitude,engine_hours,telemetry_timestamp FROM sector_equipment WHERE provider=? AND external_account_id=? AND COALESCE(is_demo,0)=0',
                             (PROVIDER,self.account)).fetchall()
            alerts=conn.execute('''SELECT count(*) FROM integration_provider_events v JOIN sector_equipment e ON e.id=v.equipment_id
                WHERE v.provider=? AND e.external_account_id=? AND v.active=1''',(PROVIDER,self.account)).fetchone()[0]
            history=[dict(r) for r in conn.execute('''SELECT id,sync_type,started_at,completed_at,status,organizations_processed,
                    machines_processed,telemetry_records_processed,errors_count,result_json
                    FROM integration_sync_runs WHERE provider=? AND integration_id IN
                    (SELECT id FROM integrations WHERE provider=?) ORDER BY id DESC LIMIT 20''',(PROVIDER,PROVIDER))]
        basic=self.client.public_status()
        last={kind:next((r['completed_at'] for r in history if r['sync_type'] in ({'organizations':KINDS,'machines':('machines','telemetry','all'),'telemetry':('telemetry','all')}[kind]) and r['status'] in ('OK','EMPTY','PARTIAL')),None) for kind in KINDS[:3]}
        gps=sum(r['latitude'] is not None and r['longitude'] is not None for r in rows)
        hours=sum(r['engine_hours'] is not None for r in rows)
        for item in history:
            item['result']=json.loads(item.pop('result_json') or '{}')
        return dict(implementation='IMPLEMENTED',verification='NOT VERIFIED WITH REAL DATA',
            counts=dict(organizations=orgs,machines=len(rows),machines_with_location=gps,machines_with_engine_hours=hours,active_alerts=alerts),
            last_sync=last,history=history,
            readiness={'OAuth':'READY' if basic.get('oauth')=='OK' and basic.get('token')!='Refresh failed' else 'AUTH REQUIRED',
                'API Access':'READY' if basic.get('api_catalog')=='OK' else 'WAITING',
                'Organization':'CONNECTED' if orgs else 'WAITING','Machines':'CONNECTED' if rows else 'WAITING',
                'GPS':'RECEIVING' if gps else 'WAITING','Hours':'RECEIVING' if hours else 'WAITING',
                'Alerts':'RECEIVING' if alerts else 'WAITING','Forest AI Object Mapping':'READY','Risk Mapping':'READY'})

    def fail(self, stage, exc):
        status=exc.status if isinstance(exc,SyncError) else 'RESOURCE UNAVAILABLE'
        if not (status in ('AUTH REQUIRED','RATE LIMITED') and self.result['errors'] and self.result['errors'][-1]['status']==status):
            self.result['errors'].append({'stage':stage,'status':status})
            self.result['errors_count']+=1
        if status in ('AUTH REQUIRED','RATE LIMITED'):
            if status=='RATE LIMITED':
                with jd._db() as conn:
                    conn.execute('UPDATE integrations SET next_sync_at=? WHERE id=?',
                                 (datetime.fromtimestamp(time.time()+getattr(exc,'retry_after',60),timezone.utc).isoformat(),self.integration_id))
            raise SyncError(status,getattr(exc,'retry_after',0))

    def run(self, kind):
        if kind not in KINDS:raise jd.DeereError('Unknown Deere sync type.')
        # Same single-worker lock as the existing token-refresh implementation.
        with jd._lock:
            self.integration_id=self.integration()
            row=database.get_integration(self.integration_id)
            until=epoch(row.get('next_sync_at'))
            if until and until>time.time():return {'status':'RATE LIMITED','retry_after':int(until-time.time())+1}
            with jd._db() as conn:
                last=conn.execute('SELECT completed_at FROM integration_sync_runs WHERE integration_id=? ORDER BY id DESC LIMIT 1',
                                  (self.integration_id,)).fetchone()
            if last and epoch(last[0]) and time.time()-epoch(last[0])<setting('JOHN_DEERE_SYNC_MIN_INTERVAL_SECONDS',60):
                return {'status':'RATE LIMITED','retry_after':setting('JOHN_DEERE_SYNC_MIN_INTERVAL_SECONDS',60)}
            self.result=dict(status='OK',organizations_processed=0,machines_processed=0,telemetry_records_processed=0,errors_count=0,errors=[])
            with jd._db() as conn:
                run=conn.execute('''INSERT INTO integration_sync_runs(integration_id,provider,sync_type,trigger,status,started_at)
                    VALUES(?,?,?,'dashboard','RUNNING',?)''',(self.integration_id,PROVIDER,kind,utc())).lastrowid
            try:
                self.client.ensure_auth()
                orgs=self.organizations()
                if kind!='organizations':
                    for org in orgs:
                        if org['connection_status']!='Connected':continue
                        try:
                            for record,raw in self.discover(org):
                                self.result['machines_processed']+=1
                                if kind in ('telemetry','all'):self.telemetry(record,raw)
                        except jd.DeereError as exc:
                            self.fail('organization equipment',exc)
                if self.result['errors_count']:self.result['status']='PARTIAL'
                elif (not orgs or (kind!='organizations' and not self.result['machines_processed'])):self.result['status']='EMPTY'
            except SyncError as exc:
                if exc.status=='RATE LIMITED':
                    with jd._db() as conn:
                        conn.execute('UPDATE integrations SET next_sync_at=? WHERE id=?',
                                     (datetime.fromtimestamp(time.time()+max(60,exc.retry_after),timezone.utc).isoformat(),self.integration_id))
                self.result['status']=exc.status
                if not self.result['errors'] or self.result['errors'][-1]['status']!=exc.status:
                    self.result['errors_count']+=1;self.result['errors'].append({'stage':'sync','status':exc.status})
            except jd.DeereError:
                self.result['status']='PROVIDER ERROR';self.result['errors_count']+=1
                self.result['errors'].append({'stage':'sync','status':'PROVIDER ERROR'})
            except Exception:
                # Never include exception text, headers, upstream bodies, or credentials.
                self.result['status']='TEMPORARY ERROR';self.result['errors_count']+=1
                self.result['errors'].append({'stage':'storage or parsing','status':'TEMPORARY ERROR'})
            finally:
                with jd._db() as conn:
                    conn.execute('''UPDATE integration_sync_runs SET status=?,completed_at=?,finished_at=?,organizations_processed=?,
                        machines_processed=?,telemetry_records_processed=?,errors_count=?,result_json=? WHERE id=?''',
                        (self.result['status'],utc(),utc(),self.result['organizations_processed'],self.result['machines_processed'],
                         self.result['telemetry_records_processed'],self.result['errors_count'],json.dumps(self.result),run))
            return self.result

    def organizations(self):
        # Reuse catalog-first discovery and safe organization handling.
        orgs=self.client.organizations()
        with jd._db() as conn:
            conn.execute("UPDATE integration_organizations SET connection_status='NOT SEEN' WHERE provider=? AND external_account_id=?",
                         (PROVIDER,self.account))
            for org in orgs:
                conn.execute('''INSERT INTO integration_organizations(provider,external_organization_id,organization_name,
                    external_account_id,connection_status,last_sync_at) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(provider,external_organization_id) DO UPDATE SET organization_name=excluded.organization_name,
                    external_account_id=excluded.external_account_id,connection_status=excluded.connection_status,last_sync_at=excluded.last_sync_at''',
                    (PROVIDER,org['id'],org['name'],self.account,org['connection_status'],utc()))
        self.result['organizations_processed']=len(orgs)
        return orgs

    def discover(self,org):
        detail=self.client.get(org['links']['self']) if org['links'].get('self') else {}
        rels=jd.links(detail);seen=set()
        for rel in ('equipment','machines'):
            if not rels.get(rel):continue
            try:items=self.reader.collection(rels[rel])
            except jd.DeereError as exc:
                self.fail('equipment discovery',exc);continue
            for raw in items:
                try:
                    record=normalize(raw)
                    if record['external_machine_id'] in seen:continue
                    seen.add(record['external_machine_id'])
                    is_machine=(rel=='machines' or any(str(raw.get(k,'')).lower()=='machine' for k in ('@type','equipmentClass','equipmentType','type'))
                                or 'machine' in jd.links(raw))
                    if not is_machine:continue # implements aren't self-propelled machines
                    # Equipment collections may link to a machine detail carrying telemetry relations.
                    machine_link=jd.links(raw).get('machine') or (jd.links(raw).get('self') if not any(r in jd.links(raw) for r in RELATIONS) else None)
                    if machine_link:
                        try:
                            more=self.client.get(machine_link)
                            if isinstance(more,dict):raw=dict(raw,**{k:v for k,v in more.items() if k!='links'},links=list(raw.get('links',[]))+list(more.get('links',[])))
                        except jd.DeereError as exc:self.fail('machine detail',exc)
                    yield self.upsert(org,raw),raw
                except SyncError as exc:
                    if exc.status in ('AUTH REQUIRED','RATE LIMITED'):raise
                    self.fail('machine discovery',exc)
                except (jd.DeereError,ValueError,TypeError):self.fail('machine normalization',jd.DeereError())

    def upsert(self,org,raw):
        record=normalize(raw)
        rels={k:jd.safe_link(v) for k,v in jd.links(raw).items() if k in (*RELATIONS,'self','machine')}
        with jd._db() as conn:
            row=conn.execute('SELECT * FROM sector_equipment WHERE provider=? AND external_machine_id=?',
                             (PROVIDER,record['external_machine_id'])).fetchone()
            if row and row['is_demo']:raise jd.DeereError('Demo equipment cannot receive real provider data.')
            # Initial missing sector is explicitly unassigned, never an invented geographic sector.
            if not row:
                equipment_id=conn.execute('''INSERT INTO sector_equipment(sector,provider,external_machine_id,status,created_at)
                    VALUES('',?,?,NULL,?)''',(PROVIDER,record['external_machine_id'],utc())).lastrowid
            else:equipment_id=row['id']
            updates={k:v for k,v in record.items() if v is not None and k not in ('latitude','longitude','location_timestamp')}
            updates.update(external_account_id=self.account,external_organization_id=org['id'],
                           last_synchronization_time=time.time(),provider_links_json=json.dumps(rels))
            conn.execute('UPDATE sector_equipment SET '+','.join(k+'=?' for k in updates)+' WHERE id=?',(*updates.values(),equipment_id))
            return dict(conn.execute('SELECT * FROM sector_equipment WHERE id=?',(equipment_id,)).fetchone())

    def telemetry(self,record,raw):
        # A caller can only arrive here from fresh organization/equipment discovery.
        if record['is_demo']:return
        self.position(record,raw)
        capabilities=[('latest_location',self.reader.latest_location),('location_history',self.reader.location_history),
                      ('breadcrumbs',self.reader.breadcrumbs),('engine_hours',self.reader.engine_hours),
                      ('hours_of_operation',self.reader.hours_of_operation),('alerts',self.reader.alerts),
                      ('device_state_reports',self.reader.device_state_reports)]
        for capability,method in capabilities:
            try:
                payload=method(raw)
                for item in sorted(payload['values'],key=lambda v:epoch(v.get('time') or v.get('eventTimestamp') or v.get('createTimestamp') or v.get('endDate')) or 0):
                    stamp=item.get('time') or item.get('eventTimestamp') or item.get('createTimestamp') or item.get('endDate')
                    self.store_reading(record,capability,item)
                    if capability in ('latest_location','location_history','breadcrumbs'):self.position(record,item)
                    elif capability=='engine_hours':
                        reading=number(item.get('reading'))
                        if reading is not None:self.measurement(record['id'],'engine_hours',reading,stamp)
                    elif capability=='hours_of_operation':
                        # Never equate an engine-state duration with lifetime cumulative hours.
                        hours=number(item.get('operatingHours') if item.get('operatingHours') is not None else item.get('cumulativeOperatingHours'))
                        if hours is not None:self.measurement(record['id'],'operating_hours',hours,stamp)
                    elif capability=='alerts':self.alert(record,item)
                    elif capability=='device_state_reports':
                        state={k:item[k] for k in ('engineState','terminalPowerState','gpsError') if isinstance(item.get(k),(str,int,float,bool))}
                        if state:self.measurement(record['id'],'device_status',json.dumps(state),stamp)
                    stamp=item.get('time') or item.get('eventTimestamp') or item.get('createTimestamp') or item.get('endDate')
                    if epoch(stamp) is not None:self.advance_timestamp(record['id'],stamp)
            except jd.DeereError as exc:self.fail(capability,exc)
            except (TypeError,ValueError,KeyError):self.fail(capability,jd.DeereError())
        with jd._db() as conn:
            row=conn.execute('SELECT * FROM sector_equipment WHERE id=?',(record['id'],)).fetchone()
            conn.execute('UPDATE sector_equipment SET telemetry_health=?,geofence_status=?,restricted_zone_status=?,last_synchronization_time=? WHERE id=?',
                         (health(row['telemetry_timestamp']),geofence(conn,row['sector'],row['latitude'],row['longitude']),
                          'UNKNOWN',time.time(),record['id']))

    def update_machine(self,equipment_id,**fields):
        # Internal field names only; values are normalized before this call.
        with jd._db() as conn:
            conn.execute('UPDATE sector_equipment SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),equipment_id))

    def measurement(self,equipment_id,field,value,stamp):
        column=field+'_timestamp'
        t=epoch(stamp)
        if t is not None and t>time.time()+300:return
        with jd._db() as conn:
            old=conn.execute('SELECT '+column+' FROM sector_equipment WHERE id=?',(equipment_id,)).fetchone()[0]
            if epoch(old) is None or (t is not None and t>=epoch(old)):
                conn.execute('UPDATE sector_equipment SET '+field+'=?,'+column+'=? WHERE id=?',
                             (value,stamp if t is not None else None,equipment_id))

    def advance_timestamp(self,equipment_id,stamp):
        t=epoch(stamp)
        if t is None or t>time.time()+300:return
        with jd._db() as conn:
            old=conn.execute('SELECT telemetry_timestamp FROM sector_equipment WHERE id=?',(equipment_id,)).fetchone()[0]
            if epoch(old) is None or t>epoch(old):conn.execute('UPDATE sector_equipment SET telemetry_timestamp=? WHERE id=?',(stamp,equipment_id))

    def position(self,record,item):
        loc=item.get('point') or item.get('location') or {}
        if not isinstance(loc,dict):return
        parsed=normalize(dict(id=record['external_machine_id'],location=loc))
        lat,lon=parsed['latitude'],parsed['longitude']
        if lat is None or lon is None:return
        stamp=item.get('eventTimestamp') or item.get('time') or item.get('createTimestamp') or loc.get('timestamp') or item.get('locationTimestamp')
        t=epoch(stamp)
        if t is not None and t>time.time()+300:return
        # A location without a timestamp can be displayed, but never gains a fabricated report time.
        with jd._db() as conn:
            current=conn.execute('SELECT * FROM sector_equipment WHERE id=?',(record['id'],)).fetchone()
            old=epoch(current['location_timestamp'])
            if (old is None and t is None) or (t is not None and (old is None or t>=old)):
                conn.execute('UPDATE sector_equipment SET latitude=?,longitude=?,location_timestamp=? WHERE id=?',
                             (lat,lon,stamp if t is not None else None,record['id']))
            if t is not None and t<=time.time()+300:
                key=hashlib.sha256(json.dumps([stamp,lat,lon]).encode()).hexdigest()
                state=geofence(conn,current['sector'],lat,lon)
                cursor=conn.execute('''INSERT OR IGNORE INTO vehicle_gps_pings(vehicle_id,sector,latitude,longitude,inside_boundary,
                    recorded_at,entity_type,equipment_id,provider,source,source_timestamp,provider_record_key)
                    VALUES(NULL,?,?,?,?,?,'EQUIPMENT',?,?,?,?,?)''',
                    (current['sector'],lat,lon,None if state=='UNKNOWN' else int(state=='INSIDE'),
                     datetime.fromtimestamp(t,timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
                     record['id'],PROVIDER,PROVIDER,stamp,key))
                self.result['telemetry_records_processed']+=cursor.rowcount
        if t is not None:self.advance_timestamp(record['id'],stamp)

    def store_reading(self,record,capability,item):
        # Reuse integration staging for readings, retaining only documented useful fields.
        clean={k:item[k] for k in ('id','time','eventTimestamp','createTimestamp','startDate','endDate','engineState',
            'terminalPowerState','gpsError','severity','color','ignored','invisible','acknowledgementStatus')
            if isinstance(item.get(k),(str,int,float,bool))}
        for k in ('reading','operatingHours','cumulativeOperatingHours'):
            v=number(item.get(k))
            if v is not None:clean[k]=v
        point=item.get('point') or item.get('location')
        if isinstance(point,dict):clean['point']={k:number(point.get(k)) for k in ('lat','lon')}
        definition=item.get('definition')
        if isinstance(definition,dict) and label(definition.get('description')):clean['description']=label(definition['description'])
        if not clean:return
        fingerprint=hashlib.sha256(json.dumps([record['external_machine_id'],capability,clean],sort_keys=True).encode()).hexdigest()
        _,created=database.upsert_integration_record(self.integration_id,1,PROVIDER,'MachineTelemetry',record['external_machine_id'],
            'deere:'+fingerprint,sector=record['sector'],source_timestamp=clean.get('time') or clean.get('eventTimestamp'),
            normalized_payload={'capability':capability,'reading':clean},linked_table='sector_equipment',linked_id=record['id'])
        self.result['telemetry_records_processed']+=int(created)

    def alert(self,record,item):
        definition=item.get('definition') if isinstance(item.get('definition'),dict) else {}
        description=label(definition.get('description')) or label(item.get('description'))
        stamp=label(item.get('time'))
        external_id=label(item.get('id'))
        if not external_id and not (description and stamp):return
        key=external_id or hashlib.sha256(json.dumps([stamp,description,item.get('severity')],sort_keys=True).encode()).hexdigest()
        severity=label(item.get('severity'))
        active=not (str(item.get('ignored')).lower()=='true' or str(item.get('invisible')).lower()=='true' or str(item.get('acknowledgementStatus','')).upper() in ('Y','ACKNOWLEDGED'))
        with jd._db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('''INSERT INTO integration_provider_events(provider,event_key,external_event_id,equipment_id,event_timestamp,
                severity,description,active,last_sync_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(provider,equipment_id,event_key)
                DO UPDATE SET severity=excluded.severity,description=excluded.description,active=excluded.active,last_sync_at=excluded.last_sync_at''',
                (PROVIDER,key,external_id,record['id'],stamp,severity,description,int(active),utc()))
            event=conn.execute('SELECT id,risk_id FROM integration_provider_events WHERE provider=? AND equipment_id=? AND event_key=?',
                               (PROVIDER,record['id'],key)).fetchone()
            level=severity if severity in ('HIGH','MEDIUM','LOW') else ({'RED':'HIGH','YELLOW':'MEDIUM'}.get(item.get('color')) if severity is None else None)
            if active and level:
                reason='John Deere machine alert'+(': '+description if description else '')
                if event['risk_id'] is None:
                    # Same schema/semantics as database.add_incident, in the event transaction
                    # so a crash cannot create an orphan or duplicate risk.
                    risk=conn.execute('''INSERT INTO risks(sector,risk_level,reason,created_at,entity_type,entity_id,status,
                        rule_code,data_origin,occurred_at) VALUES(?,?,?,?,'EQUIPMENT',?,'OPEN','EQUIPMENT_BREAKDOWN','REAL',?)''',
                        (record['sector'],level,reason,utc(),str(record['id']),stamp)).lastrowid
                    conn.execute('UPDATE integration_provider_events SET risk_id=? WHERE id=?',(risk,event['id']))
                    conn.execute('INSERT INTO risk_events(risk_id,event_type,actor,details,created_at) VALUES(?,?,?,?,?)',
                        (risk,'PROVIDER_ALERT','john_deere',json.dumps({'provider':PROVIDER,'provider_event_id':event['id'],'external_alert_id':external_id}),utc()))
                else:
                    conn.execute("UPDATE risks SET reason=?,risk_level=?,sector=? WHERE id=? AND status IN ('OPEN','NOTIFIED')",
                                 (reason,level,record['sector'],event['risk_id']))
            previous=conn.execute('SELECT last_alert FROM sector_equipment WHERE id=?',(record['id'],)).fetchone()[0]
            previous_stamp=json.loads(previous or '{}').get('time')
            if epoch(previous_stamp) is None or (epoch(stamp) is not None and epoch(stamp)>=epoch(previous_stamp)):
                conn.execute('UPDATE sector_equipment SET last_alert=? WHERE id=?',
                             (json.dumps({'id':external_id,'time':stamp,'severity':severity,'description':description}),record['id']))


def assign_sector(account,equipment_id,sector):
    with jd._db() as conn:
        row=conn.execute('SELECT * FROM sector_equipment WHERE id=? AND provider=? AND external_account_id=? AND COALESCE(is_demo,0)=0',
                         (equipment_id,PROVIDER,account)).fetchone()
        if not row:raise jd.DeereError('Real Deere equipment not found.')
        if sector:
            sectors=conn.execute("SELECT name FROM sectors WHERE name=? AND COALESCE(data_origin,'REAL')='REAL'",(sector,)).fetchall()
            if len(sectors)!=1:raise jd.DeereError('Choose one unambiguous real Forest AI sector.')
        conn.execute('UPDATE sector_equipment SET sector=?,geofence_status=? WHERE id=?',
                     (sector,geofence(conn,sector,row['latitude'],row['longitude']),equipment_id))
        conn.execute("UPDATE risks SET sector=? WHERE entity_type='EQUIPMENT' AND entity_id=? AND data_origin='REAL' AND status IN ('OPEN','NOTIFIED')",
                     (sector,str(equipment_id)))
