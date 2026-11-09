import json,re,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/tmp/forest_browser')
from playwright.sync_api import sync_playwright
candidate=Path(__file__).resolve().parents[1]/'releases/forest-api-remove-map-sidebar-20261109'
html=(candidate/'index.html').read_text()
# Parse every shipped inline and external script without executing any API code.
scripts=re.findall(r'<script\b([^>]*)>(.*?)</script>',html,re.S)
count=0
for attrs,body in scripts:
 if 'src=' in attrs or not body.strip():continue
 p=Path('/tmp/remove-map-inline.js');p.write_text(body)
 subprocess.run(['node','--check',str(p)],check=True,capture_output=True);count+=1
for p in sorted((candidate/'assets').glob('*.js')):
 subprocess.run(['node','--check',str(p)],check=True,capture_output=True);count+=1
# Exercise the shipped nav() with actual DOM nodes. Stub loaders explicitly: this
# verifies navigation/selection; backend and registration are tested separately.
start=html.index('function nav(id, push=true)');end=html.index('\nfunction refreshCurrent',start)
nav=html[start:end]
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
 page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 stripped=re.sub(r'<script\b[^>]*>.*?</script>','',html,flags=re.S)
 page.route('**/*',lambda route:route.fulfill(status=200,body=''))
 page.set_content(stripped)
 page.evaluate("window.calls=[];window.titles={};window.localizeGeodataNavigation=()=>{};window.load=id=>calls.push(id);window.ForestMap={deactivate:()=>{}};")
 page.add_script_tag(content=nav)
 # Match backend feature enablement, which unhides this nav item at DOMContentLoaded.
 page.eval_on_selector('#forest-map-nav',"e=>e.style.display=''")
 expected=['overview','objects','sectors','risks','gps','trucks','timber','lvm-geodata','integrations','forest-map']
 visible=page.locator('.sidebar .nav-item:visible')
 actual=visible.evaluate_all("es=>es.map(e=>e.getAttribute('onclick').match(/nav\\('([^']+)'/)[1])")
 assert actual==expected,(actual,expected)
 for item in expected:
  page.locator('.sidebar .nav-item').filter(has=page.locator('no-such-element')) if False else None
  page.locator(f'.sidebar .nav-item[onclick*="nav(\'{item}\')"]').click()
  assert page.locator('#sec-'+item).evaluate("e=>e.classList.contains('active')")
  assert page.locator('.sidebar .nav-item.active').count()==1
  assert item in page.locator('.sidebar .nav-item.active').get_attribute('onclick')
 assert not page.locator('.sidebar .nav-item[onclick*="nav(\'map\')"]').count()
 assert 'Operations Map' not in visible.all_text_contents()
 # Preserved internal route still opens and must not highlight a different item.
 page.evaluate("nav('map')")
 assert page.locator('#sec-map').evaluate("e=>e.classList.contains('active')")
 assert page.locator('.sidebar .nav-item.active').count()==0
 assert not errors,errors
 browser.close()
print(json.dumps({'status':'PASS','visible_navigation_targets':actual,'navigation_clicks_passed':len(expected),'internal_map_route_preserved':True,'javascript_files_syntax_checked':count,'page_errors':errors},indent=2))
