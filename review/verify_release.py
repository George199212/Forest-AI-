"""Read-only candidate/baseline inventory and minimal-diff check."""
import hashlib,json,difflib
from pathlib import Path
c=Path(__file__).resolve().parents[1]/'releases/forest-api-remove-map-sidebar-20261109'
m=json.loads((c/'release-manifest.json').read_text());b=Path(m['baseline'])
changed=[]
for item in m['inventory']:
 rel=item['path'];before=b/rel;after=c/rel
 assert hashlib.sha256(before.read_bytes()).hexdigest()==item['baseline_sha256'],f'Baseline changed: {rel}'
 assert hashlib.sha256(after.read_bytes()).hexdigest()==item['sha256'],f'Candidate changed: {rel}'
 if item['sha256']!=item['baseline_sha256']:changed.append(rel)
assert changed==['index.html'],changed
assert (c/'data').is_symlink() and (c/'data').readlink()==Path('/root/forest_ai/data')
assert not (c/'.env').exists()
source=(b/'index.html').read_text();target=(c/'index.html').read_text()
removed='      <div class="nav-item" onclick="nav(\'map\')"><span class="nav-icon">◎</span> Map</div>\n'
old="const navMap = {overview:0,objects:1,sectors:2,map:3,risks:4,gps:5,trucks:6,timber:7,photos:8,inspector:9,satellite:10,'lvm-geodata':11,integrations:12,'forest-map':13};"
new="const navMap = {overview:0,objects:1,sectors:2,risks:3,gps:4,trucks:5,timber:6,photos:7,inspector:8,satellite:9,'lvm-geodata':10,integrations:11,'forest-map':12};"
assert source.replace(removed,'').replace(old,new)==target
print(f'PASS: {len(m["inventory"])} runtime files verified; only index.html differs (sidebar removal + navigation offsets); shared data link retained, no environment copied.')
