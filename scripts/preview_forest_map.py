"""Run a local, dry-run-only preview against an isolated operational DB backup.

Never restarts production. Stop with Ctrl-C. Existing dashboard credentials are
read from .env; no accounts are changed. No registration writes are allowed.
"""
import argparse,os,sys,sqlite3,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8767);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='forest-map-preview-') as folder:
        target=Path(folder)/'preview.sqlite'
        with sqlite3.connect('file:'+str(ROOT/'data/forest_ai.db')+'?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:src.backup(dst)
        env={**os.environ,'DB_PATH':str(target),'FOREST_MAP_PREVIEW':'1'}
        from dotenv import dotenv_values
        cfg=dotenv_values(ROOT/'.env')
        for key in ['DASHBOARD_USERNAME','DASHBOARD_PASSWORD','UI_LANGUAGE']:
            if key not in env and cfg.get(key):env[key]=cfg[key]
        if not env.get('DASHBOARD_USERNAME') or not env.get('DASHBOARD_PASSWORD'):
            raise RuntimeError('Set the existing dashboard credentials in .env or environment for the local preview')
        print(f'Dry-run preview: http://127.0.0.1:{args.port}/#forest-map',flush=True)
        child=subprocess.Popen([sys.executable,'-m','uvicorn','scripts.preview_forest_map:preview_app','--host','127.0.0.1','--port',str(args.port),'--lifespan','off'],cwd=ROOT,env=env)
        try:return child.wait()
        except KeyboardInterrupt:
            # Both processes receive terminal Ctrl-C; allow uvicorn to close cleanly.
            try:return child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.terminate();return child.wait(timeout=5)


if os.environ.get('FOREST_MAP_PREVIEW')=='1':
    from api import app as preview_app
    from starlette.responses import JSONResponse
    @preview_app.middleware('http')
    async def readonly_preview(request,call_next):
        if request.method not in ('GET','HEAD','OPTIONS'):
            if request.url.path!='/api/geodata/vmd/import-selected':return JSONResponse({'detail':'Preview is read-only'},403)
            try:body=await request.json()
            except ValueError:return JSONResponse({'detail':'Invalid JSON'},422)
            if body.get('dry_run') is not True:return JSONResponse({'detail':'Preview permits dry-run only'},403)
        return await call_next(request)

if __name__=='__main__':raise SystemExit(main())
