import sys,os,json
sys.path.insert(0,'/tmp/forest_browser');os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH','/tmp/forest_chromium')
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage','--renderer-process-limit=1','--disable-gpu'])
    page=b.new_context(http_credentials={'username':'audit','password':'audit-local-only'},viewport={'width':1366,'height':860}).new_page()
    page.goto('http://127.0.0.1:8011/#forest-map');page.wait_for_function('window.ForestMap&&ForestMap.map',timeout=30000);page.wait_for_timeout(3000)
    r=page.evaluate("""async()=>{const m=ForestMap.map;m.setView([57.35,27.75],14,{animate:false});await new Promise(r=>setTimeout(r,500));
      const data=await (await fetch('/api/geodata/forest-map/tiles/forest/14/9300/5015')).json();const out={features:data.features.length};
      for(const name of ['svg','canvas']){const times=[];for(let i=0;i<5;i++){const renderer=name==='svg'?L.svg():L.canvas();const t=performance.now();const layer=L.geoJSON(data,{renderer,style:{weight:1}}).addTo(m);await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));times.push(performance.now()-t);m.removeLayer(layer);}
        times.sort((a,b)=>a-b);out[name+'_median_ms']=Math.round(times[2]);}
      out.current_tile_canvas_draw_ms_per_tile=Math.round(ForestMap.stats.drawMs/Math.max(1,ForestMap.stats.tiles));return out}""")
    print(json.dumps(r));json.dump(r,open(sys.argv[1],'w'))
    b.close()
