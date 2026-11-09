"""Approved deployment; run on VPS host, not the restricted Codex sandbox.
Fails before mutation unless actual process, HTTP and baseline identity agree.
"""
import hashlib,json,os,re,shutil,subprocess,sys,tarfile,time
from datetime import datetime,timezone
from pathlib import Path
import requests
from dotenv import dotenv_values

W=Path(__file__).resolve().parents[1]
C=W/'releases/forest-api-remove-map-sidebar-20261109'
B=Path('/root/forest_ai/releases/forest-api-forest-map-gps-20261109T1129Z')
UNIT='forest-api.service'
OVERRIDE=Path('/etc/systemd/system/forest-api.service.d/80-remove-map-sidebar-release.conf')
BASE='http://127.0.0.1:8000'

def command(*args):
 return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT).strip()

def running(expected):
 state=command('systemctl','show',UNIT,'-p','MainPID','-p','WorkingDirectory','-p','ActiveState','-p','DropInPaths')
 info=dict(line.split('=',1) for line in state.splitlines() if '=' in line)
 assert info['ActiveState']=='active',f'Service is {info.get("ActiveState")}'
 pid=int(info['MainPID']);assert pid>0,'No service PID'
 actual=Path(f'/proc/{pid}/cwd').resolve(strict=True)
 assert actual==expected,f'Actual process cwd {actual} differs from expected {expected}'
 assert Path(info['WorkingDirectory'])==expected,'Loaded systemd WorkingDirectory differs'
 cmdline=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
 assert b'--port' in cmdline and cmdline[cmdline.index(b'--port')+1]==b'8000','Service is not using port 8000'
 return state

def fingerprint(folder):
 names=['index.html','assets/lvm-geodata.js','assets/vmd-production.js','assets/vmd-workflow.css','assets/forest-map.js','assets/forest-map.css']
 return {p:hashlib.sha256((folder/p).read_bytes()).hexdigest() for p in names}

def get(path):
 r=session.get(BASE+path,timeout=30,headers={'Cache-Control':'no-cache'});r.raise_for_status();return r

def check_http(folder,removed):
 deployed=get('/api/deployment').json()
 assert deployed['assets']==fingerprint(folder),'HTTP frontend hashes do not match expected release'
 assert deployed['backend_revision']==hashlib.sha256((folder/'api.py').read_bytes()).hexdigest()[:12],'HTTP backend differs'
 html=get('/?sidebar_verification='+str(time.time_ns())).text
 sidebar=html[html.index('<nav'):html.index('</nav>')]
 targets=re.findall(r"nav\('([^']+)'\)",sidebar)
 assert ('map' not in targets)==removed,'Unexpected standalone Map entry in served HTML'
 assert 'Operations Map' not in sidebar,'Operations Map entry found'
 for target in ['overview','objects','sectors','risks','gps','trucks','timber','lvm-geodata','integrations','forest-map']:
  assert targets.count(target)==1,f'Missing/duplicate sidebar destination: {target}'
  assert 'id="sec-'+target+'"' in html,f'Missing section: {target}'
 for p in ['/api/sectors','/api/gps','/api/risks','/api/geodata/forest-map/status','/api/geodata/lvm/health']:
  assert p in routes,f'Required route missing: {p}'
  get(p)
 return deployed['version']

try:
 print('Verifying actual host process...',flush=True)
 state=running(B)
 command(sys.executable,str(W/'review/verify_release.py'))
 command('node',str(W/'review/verify_navigation.js'))
 assert not OVERRIDE.exists(),'Deployment override already exists; inspect before proceeding'
 cfg=dotenv_values('/root/forest_ai/.env')
 assert cfg.get('DASHBOARD_USERNAME') and cfg.get('DASHBOARD_PASSWORD'),'Dashboard credentials unavailable'
 session=requests.Session();session.trust_env=False
 session.auth=(cfg['DASHBOARD_USERNAME'],cfg['DASHBOARD_PASSWORD'])
 routes=get('/openapi.json').json()['paths']
 # Require exact existing core routes; never invent a replacement.
 for p in ['/api/sectors','/api/risks','/api/map','/api/geodata/forest-map/status']:
  assert p in routes,f'Required existing route missing: {p}'
 before=check_http(B,False)
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=Path('/root/backups')/('forest-remove-map-'+stamp);backup.mkdir(mode=0o700,parents=True,exist_ok=False)
 os.chmod(backup,0o700)
 shutil.copy2('/etc/systemd/system/forest-api.service',backup/'forest-api.service')
 shutil.copytree('/etc/systemd/system/forest-api.service.d',backup/'drop-ins')
 (backup/'service-before.txt').write_text(state+'\n')
 (backup/'deployment-before.txt').write_text(before+'\n')
 with tarfile.open(backup/'runtime-before.tar.gz','w:gz') as archive:
  for name in ['api.py','database.py','index.html','assets','services','lvm_3_sectors.geojson']:
   archive.add(B/name,arcname=name,recursive=True)
 # Guard again against concurrent activation or code changes after the backup.
 running(B);command(sys.executable,str(W/'review/verify_release.py'));check_http(B,False)
 activated=False
 try:
  with OVERRIDE.open('x') as f:
   activated=True
   f.write('[Service]\nWorkingDirectory='+str(C)+'\n')
  command('systemctl','daemon-reload');command('systemctl','restart',UNIT)
  failure=None
  for _ in range(15):
   try:
    running(C);version=check_http(C,True);failure=None;break
   except Exception as e:failure=e;time.sleep(1)
  if failure:raise failure
  print('DEPLOYED commit 22e84c9 sidebar change; active='+str(C))
  print('HTTP/sidebar verification PASS; service active; version='+version)
  print('Backup='+str(backup))
 except BaseException:
  if activated:
   OVERRIDE.unlink(missing_ok=True)
   command('systemctl','daemon-reload');command('systemctl','restart',UNIT)
   running(B);check_http(B,False)
   print('ROLLED BACK to '+str(B),file=sys.stderr)
  raise
except Exception as e:
 print('BLOCKED/FAILED: '+str(e),file=sys.stderr)
 if isinstance(e,subprocess.CalledProcessError) and e.output:
  print(e.output.strip(),file=sys.stderr)
 sys.exit(1)
