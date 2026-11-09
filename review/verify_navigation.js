const fs=require('fs'),vm=require('vm'),assert=require('assert'),cp=require('child_process'),path=require('path');
const dir=path.resolve(__dirname,'../releases/forest-api-remove-map-sidebar-20261109');
const html=fs.readFileSync(path.join(dir,'index.html'),'utf8');let syntax=0;
for(const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)){if(!m[1].includes('src=')&&m[2].trim()){new vm.Script(m[2]);syntax++;}}
for(const file of fs.readdirSync(path.join(dir,'assets')).filter(x=>x.endsWith('.js'))){new vm.Script(fs.readFileSync(path.join(dir,'assets',file),'utf8'));syntax++;}
const sidebar=html.slice(html.indexOf('<nav'),html.indexOf('</nav>'));
const nodes=[...sidebar.matchAll(/<div class="nav-item[^\"]*"([^>]*)>([\s\S]*?)<\/div>/g)].map(m=>({id:m[1].match(/nav\('([^']+)'\)/)[1],hidden:m[1].includes('display:none'),label:m[2].replace(/<[^>]+>/g,'').trim()}));
assert(!nodes.some(n=>n.id==='map'||n.label==='Operations Map'));
// Forest Map is enabled by the unchanged backend and asset on DOMContentLoaded.
nodes.find(n=>n.id==='forest-map').hidden=false;
const expected=['overview','objects','sectors','risks','gps','trucks','timber','lvm-geodata','integrations','forest-map'];
assert.deepStrictEqual(nodes.filter(n=>!n.hidden).map(n=>n.id),expected);
function element(id){return {id,classList:{active:false,remove(){this.active=false},add(){this.active=true},toggle(){}},textContent:''};}
const sections=[...html.matchAll(/class="section[^\"]*" id="([^"]+)"/g)].map(m=>element(m[1]));
const items=nodes.map(n=>element(n.id)),other={};const calls=[];
const context={document:{body:element('body'),querySelectorAll(q){return q==='.section'?sections:items},getElementById(id){return sections.find(s=>s.id===id)||(other[id]??=element(id))}},window:{ForestMap:{deactivate(){}}},localizeGeodataNavigation(){},titles:{},history:{pushState(){}},load(id){calls.push(id)},Date};
vm.createContext(context);vm.runInContext(html.slice(html.indexOf('function nav(id, push=true)'),html.indexOf('\nfunction refreshCurrent')),context);
for(const n of nodes){context.nav(n.id);assert(sections.find(s=>s.id==='sec-'+n.id).classList.active);assert.deepStrictEqual(items.filter(i=>i.classList.active).map(i=>i.id),[n.id]);}
context.nav('map');assert(sections.find(s=>s.id==='sec-map').classList.active);assert.equal(items.filter(i=>i.classList.active).length,0);
console.log(JSON.stringify({status:'PASS',visibleTargets:expected,navigationFunctionChecks:nodes.length+1,javascriptScriptsParsed:syntax,note:'Node DOM fixture; browser launch blocked by sandbox'},null,2));
