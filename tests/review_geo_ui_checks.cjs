// LVM GEO / Meža karte review UI: scoped English, untouched source values, demo-blocked actions.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const root=require('path').resolve(__dirname,'..');
function context(readOnly=false,lang='en') {
  const c={console,Request,Response,Headers,URL,location:{href:'http://127.0.0.1:8003/',origin:'http://127.0.0.1:8003'},
    window:{alert(){},confirm(){},prompt(){},ForestInstance:{readOnly}},
    document:{readyState:'loading',addEventListener(){},documentElement:{lang,classList:{add(){}}},
      head:{appendChild(){}},createElement(){return {style:{}};}}};
  vm.createContext(c);return c;
}
const c=context();vm.runInContext(fs.readFileSync(root+'/assets/i18n-en.js','utf8'),c);
const {trGeo,tr}=c.window.ForestI18n;
const cases=[
 ['Kadastra apzīmējums','Cadastral designation (kadastra apzīmējums)'],
 ['Forest compartment','Forest compartment (nogabals)'],
 ['Reģistrēt sektorus (3)','Register sectors (3)'],
 ['Atlasīti: 2 nogabali · 4.10 ha','Selected: 2 compartments · 4.10 ha'],
 ['Pieprasītais apzīmējums: 01000922053 · Atrasti: 5 nogabali · Šajā lapā: 5 · Kopējā platība: 12.34 ha · VZD zemes vienība: 01000922053 · Platība: 13.0000 ha · Pārbaudīti: 4 · Telpiski kandidāti: 1',
  'Requested designation (apzīmējums): 01000922053 · Found: 5 compartments · On this page: 5 · Total area: 12.34 ha · VZD land unit (zemes vienība): 01000922053 · Area: 13.0000 ha · Verified: 4 · Spatial candidates: 1'],
 ['Robežu neatbilstība · 97.1234% sakritība','Boundary discrepancy · 97.1234% overlap'],
 ['Norādiet sektora nosaukumu (1–120 rakstzīmes, bez slīpsvītrām un vadības rakstzīmēm) · Ievadiet atbildīgās personas vārdu un uzvārdu.',
  'Enter a sector name (1–120 characters, no slashes or control characters) · Enter the responsible person\'s first and last name.'],
 ['VMD · nodala2653','VMD · nodala2653'],
];
for(const [source,expected] of cases) assert.equal(trGeo(source),expected,source);
// Source values (VMD/VZD attributes, cadastral numbers, place names) are never rewritten in geodata areas,
// even when the global phrase pass would touch them.
for(const v of ['01000922053','VMD:nodala2251:50525112','Ķekavas pagasts','Priede · 2. stāva','Mežaparks 12','Rīgas valstspilsētas pašvaldība'])
  assert.equal(trGeo(v),v,v);
const review=context(true);vm.runInContext(fs.readFileSync(root+'/assets/review-ui.js','utf8'),review);
const R=review.window.ForestReview;
function el(sel,inGeo,handler='') {return {getAttribute:()=>handler,matches:s=>s.split(',').includes(sel),closest:s=>inGeo&&s.includes('#sec-')?{}:null};}
assert(R.allowed(el('#vmd-find',true)),'search button in LVM GEO is a read');
assert(R.allowed(el('#fm-layer-forest',true)),'Forest Map controls are reads');
for(const sel of ['#lvm-import','#vmd-go-3','#fm-import','#fm-confirm','.fm-create-incident']) assert(!R.allowed(el(sel,true)),sel);
assert(!R.allowed(el('button',false,'createSector()')),'outside geo sections the allowlist still applies');
assert.equal(R.demoApiBlocked('/api/geodata/vmd/import-selected'),'registration');
assert.equal(R.demoApiBlocked('/api/geodata/forest-map/gps/violations/incident'),'incident');
assert.equal(R.demoApiBlocked('/api/geodata/vmd/cadastre'),null);

// Regression: process() must not rewrite already-applied state. The MutationObserver watches 'disabled',
// so an unconditional el.disabled=true / setAttribute loops forever (froze the AI Inspector page).
function fakeButton(handler,sel) {
  const attrs={'aria-disabled':'true','data-review-action':'','onclick':handler};let writes=0;
  const el={nodeType:1,_disabled:true,get disabled(){return this._disabled;},set disabled(v){writes++;this._disabled=v;},
    getAttribute:k=>k in attrs?attrs[k]:null,hasAttribute:k=>k in attrs,setAttribute:(k,v)=>{writes++;attrs[k]=v;},
    matches:s=>s.split(',').some(x=>x.trim()==='button'||x.trim()===sel),closest:()=>null,querySelectorAll:()=>[],
    get title(){return attrs.title||'';},set title(v){writes++;attrs.title=v;},nextElementSibling:{classList:{contains:()=>true}},after(){writes++;}};
  return {el,writes:()=>writes};
}
for (const [handler,sel] of [['createSector()','x'],['','#lvm-import']]) {
  const f=fakeButton(handler,sel);if(sel==='#lvm-import'){f.el.setAttribute('data-review-read','');f.el.setAttribute('data-review-demo-blocked','registration');f.el.title=R.demoApiBlocked&&'Registration is disabled in demo mode (Demo režīmā reģistrācija ir izslēgta)';}
  const before=f.writes();R.process(f.el);R.process(f.el);
  assert.equal(f.writes(),before,'process() rewrote unchanged state for '+(handler||sel));
}
review.window.fetch=async()=>{throw Error('no network')};
const withFetch=context(true);let outbound=0;withFetch.window.fetch=async()=>{outbound++;return new Response('{}');};
vm.runInContext(fs.readFileSync(root+'/assets/review-ui.js','utf8'),withFetch);
(async()=>{
  let r=await withFetch.window.fetch('/api/geodata/vmd/import-selected',{method:'POST',body:'{"dry_run":true}'});
  assert.equal(r.status,403);assert.match((await r.json()).detail,/Registration is disabled in demo mode \(Demo režīmā reģistrācija ir izslēgta\)/);
  r=await withFetch.window.fetch('/api/geodata/forest-map/gps/violations/incident',{method:'POST'});
  assert.equal(r.status,403);assert.match((await r.json()).detail,/Incident creation is disabled/);
  assert.equal(outbound,0);
  await withFetch.window.fetch('/api/geodata/vmd/cadastre?kadastrs=01000922053');assert.equal(outbound,1);
  console.log('Geodata review UI checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
