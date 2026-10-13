"""Rich BIK-001-like DB for UI language checks. Usage: make_fixture.py <app_dir> <db_path> [empty]"""
import sys, os, json, sqlite3, importlib
app, db = sys.argv[1], sys.argv[2]; empty = len(sys.argv) > 3
os.environ['DB_PATH'] = db; sys.path.insert(0, app); os.chdir(app)
import database; database.init_db()
if empty: sys.exit()
from PIL import Image
c = sqlite3.connect(db)
def ins(t, **kw):
    for cid,name,typ,notnull,dflt,pk in c.execute(f"pragma table_info({t})"):
        if notnull and dflt is None and not pk and name not in kw:
            kw[name] = 0 if any(x in (typ or '').upper() for x in ('INT','REAL')) else 'x'
    cur = c.execute(f"insert into {t}({','.join(kw)}) values({','.join('?'*len(kw))})", list(kw.values())); return cur.lastrowid
poly = [[56.9655,24.2010],[56.9668,24.2070],[56.9640,24.2095],[56.9628,24.2030]]
ins('sectors', name='BIK-001', contractor='Rigas Mezi', status='ACTIVE', approved_volume=None,
    boundary_json=json.dumps([[p[0],p[1]] for p in poly]), center_lat=56.965, center_lon=24.205, area_ha=12.4,
    color='#82b96a', created_at='2026-10-09 08:00:00', updated_at='2026-10-10 09:00:00', object_name='Biķernieku mežs')
e = ins('sector_employees', sector='BIK-001', full_name='Jevgenijs Popkovs', role='Mežsargs', active=1, created_at='2026-10-09', telegram_user_id='854929401')
os.makedirs('data/work_photos', exist_ok=True)
pid = []
for day, hour in (('2026-10-09', 14), ('2026-10-10', 8)):
    s = ins('work_sessions', user_id=854929401, employee='Jevgenijs Popkovs', employee_id=e, contractor='Rigas Mezi', sector='BIK-001',
            check_in_time=f'{day} {hour:02d}:00:00', finish_time=f'{day} {hour+1:02d}:10:00', latitude=56.965, longitude=24.205, distance_m=12, approved=1)
    for i in range(4):
        fn = f'BIK-001_site_{day}_{i}.jpg'; Image.new('RGB', (64, 48), (40+i*30, 90, 50)).save(f'data/work_photos/{fn}')
        pid.append(ins('work_photos', session_id=s, sector='BIK-001', photo_type='site', image_path=f'data/work_photos/{fn}', uploaded_at=f'{day} {hour:02d}:{10+i}:00'))
    for k in range(6):
        ins('session_track_points', session_id=s, employee_id=e, telegram_user_id=854929401, sector='BIK-001',
            latitude=56.963+k*0.0006, longitude=24.203+k*0.0007, inside_boundary=1 if k<5 else 0, recorded_at=f'{day} {hour:02d}:{5+k*5:02d}:00', received_at=f'{day} {hour:02d}:{5+k*5:02d}:01')
rec = {"summary":"Darbinieks atstāja sektora robežu uz 12 minūtēm.","options":[{"id":"A","label":"Pieprasīt paskaidrojumu","message":"Lūdzu paskaidrojiet."},{"id":"B","label":"Ignorēt","message":"OK"}],
       "recommended_option_id":"A","estimated_exposure_eur_low":500,"estimated_exposure_eur_high":1500,"exposure_basis":"novērtējums","exposure_period":"vienreizējs"}
r1 = ins('risks', sector='BIK-001', risk_level='HIGH', reason='Worker Test User left sector boundary — izveidots automātiski', created_at='2026-10-10 08:40:00',
         entity_type='EMPLOYEE', entity_id=e, status='OPEN', rule_code='SECTOR_EXIT', ai_recommendation=json.dumps(rec, ensure_ascii=False), distance_m=85, duration_min=12, ai_status='DONE')
r2 = ins('risks', sector='BIK-001', risk_level='MEDIUM', reason='Vētras risks (prognoze, bojājumi nav apstiprināti)', created_at='2026-10-09 09:00:00',
         status='OPEN', ai_recommendation='Pēc vētras veikt atkārtotu fotografēšanu.', ai_status='DONE')
for r in (r1, r2):
    ins('risk_events', risk_id=r, event_type='CREATED', actor='system', details='', created_at='2026-10-10 08:41:00')
run = ins('photo_cmp_runs', sector='BIK-001', baseline_date='2026-10-09', followup_date='2026-10-10', baseline_photo_ids=json.dumps(pid[:4]),
          followup_photo_ids=json.dumps(pid[4:]), status='DONE', created_by='dashboard', created_at='2026-10-10 10:00:00', updated_at='2026-10-10 10:05:00')
for i in range(4):
    p = ins('photo_cmp_points', run_id=run, seq=i+1, kind='pair' if i<3 else 'baseline_only', match_confidence='high', status='CHECKED' if i<3 else 'ONE_SIDE',
            same_place='yes' if i<2 else 'partial', comparability='suitable' if i<2 else 'partial', comparability_reason='none' if i<2 else 'different_viewpoint',
            created_at='2026-10-10 10:00:00', updated_at='2026-10-10 10:00:00')
    ins('photo_cmp_point_photos', run_id=run, point_id=p, photo_id=pid[i], side='baseline', match_confidence='high')
    if i<3: ins('photo_cmp_point_photos', run_id=run, point_id=p, photo_id=pid[4+i], side='followup', match_confidence='high')
    if i==0: ins('photo_cmp_changes', point_id=p, kind='fallen_tree', cell='r2c2', **{'class':'possible_change'}, description='Iespējams nokritis koks', confidence='medium', review_status='PENDING', created_at='2026-10-10 10:01:00')
ins('risk_conclusions', risk_id=r2, run_id=run, status='DRAFT', rule='no_change', recommendation='close', ai_draft='Izmaiņas nav konstatētas.', created_by='system', created_at='2026-10-10 11:00:00')
ins('timber_movements', sector='BIK-001', planned_volume=None, actual_volume=None, status='PLANNED', note='', created_at='2026-10-10')
ins('ai_inspector_analyses', scope='sector', sector='BIK-001', summary_text='Sektorā nav mežizstrādes.', risk_breakdown_json='{}', model='m', created_at='2026-10-10 12:00:00')
c.commit(); print('fixture ok', len(pid), 'photos')
