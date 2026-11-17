'use strict';
// Satellite Workspace (Stage 5, prototype B): pure rules — colour table, time formatting (UTC ↔ Europe/Riga incl. DST),
// timeline states, compare-pair validity, composites never mixed, VMD values never shown as a year, AA contrast.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),zlib=require('node:zlib');
const ROOT=path.join(__dirname,'..'),read=f=>fs.readFileSync(path.join(ROOT,f),'utf8');
function load(){
 const ctx={console,Intl,Date,Object,Promise,JSON,Math,setTimeout};ctx.window=ctx;
 ctx.document={getElementById:()=>null,querySelector:()=>null,querySelectorAll:()=>[],head:{appendChild(){}}};
 ctx.SatMonitoring={lvmButton(){},load(){},_trServer:s=>s};
 vm.createContext(ctx);vm.runInContext(read('assets/sat-workspace.js'),ctx);return ctx;
}
const fx=n=>JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(__dirname,'fixtures/sat_ui',n+'.json.gz'))).toString());

test('§4.4 colour table: every rule, one table, legend generated from it',()=>{
 const W=load().SatWorkspace,c=e=>W._changeColour(e).key;
 for(const st of ['SUSPECTED','FIELD_CHECK_REQUESTED'])for(const cls of ['POTENTIAL_FOREST_LOSS','POTENTIAL_CHANGE_OUTSIDE_BOUNDARY']){
  assert.equal(c({status:st,classification:cls,confidence:'HIGH'}),'red');assert.equal(c({status:st,classification:cls,confidence:'MEDIUM'}),'red');
  assert.equal(c({status:st,classification:cls,confidence:'LOW'}),'orange');}
 for(const cls of ['POSSIBLE_SEASONAL_OR_ENVIRONMENTAL','INSUFFICIENT_EVIDENCE'])assert.equal(c({status:'SUSPECTED',classification:cls,confidence:'HIGH'}),'yellow');
 assert.equal(c({status:'REVIEW_CONFIRMED',classification:'POTENTIAL_FOREST_LOSS',confidence:'HIGH'}),'bluegrey');
 assert.equal(c({status:'REVIEW_REJECTED'}),'grey');assert.equal(c({status:'RECOVERED',classification:'POTENTIAL_FOREST_LOSS'}),'grey');
 assert.equal(W._changeColour({status:'RECOVERED'}).dash,'5 4');
 assert.equal(c({}),'unknown');
 assert.deepEqual(JSON.parse(JSON.stringify(W._CHANGE_COLOURS.map(x=>x.color))),['#C94B42','#D97736','#D4B23A','#6E8496','#8A8F8C']);
 const src=read('assets/sat-workspace.js');assert.match(src,/function legendHtml\(\) \{\s*return '<div class="satw-panel satw-legend">' \+ CHANGE_COLOURS\.map/);
 for(const x of W._CHANGE_COLOURS){assert.ok(W._T.lv[x.legend]&&W._T.en[x.legend],x.legend);}
 // worst colour per area (overview)
 assert.equal(W._worstColour([{status:'RECOVERED'},{status:'SUSPECTED',classification:'POTENTIAL_FOREST_LOSS',confidence:'LOW'}]).key,'orange');
 assert.equal(W._worstColour([]),null);
});

test('real fixtures: Ķekava events 60–62 red, 59/63–66 yellow, 58 grey; BIK-001 has no events',()=>{
 const W=load().SatWorkspace,a=fx('area_2_kekava'),k={};
 a.events.forEach(e=>k[e.id]=W._changeColour(e).key);
 assert.deepEqual(k,{58:'grey',59:'yellow',60:'red',61:'red',62:'red',63:'yellow',64:'yellow',65:'yellow',66:'yellow'});
 assert.deepEqual(fx('area_1_bik001').events,[]);
});

test('time: Europe/Riga with offset, DST both ways, UTC date shown when it differs',()=>{
 const W=load().SatWorkspace;
 assert.equal(W._fmtTime('2026-11-17T05:38:50Z'),'2026-11-17 07:38 EET, 05:38 UTC');
 assert.equal(W._fmtTime('2026-07-01T09:44:00Z'),'2026-07-01 12:44 EEST, 09:44 UTC');
 assert.equal(W._fmtTime('2026-10-25T23:30:00Z'),'2026-10-26 01:30 EET, 2026-10-25 23:30 UTC');   // after the switch back
 assert.equal(W._fmtTime('2026-03-29T00:30:00Z'),'2026-03-29 02:30 EET, 00:30 UTC');            // before 01:00 UTC switch
 assert.equal(W._fmtTime('2026-03-29T01:30:00Z'),'2026-03-29 04:30 EEST, 01:30 UTC');
 assert.equal(W._fmtTime('2026-09-18 09:44:00 UTC'),'2026-09-18 12:44 EEST, 09:44 UTC');      // forest_ai.db text format
 assert.equal(W._fmtTime(null),null);assert.equal(W._fmtTime(''),null);assert.equal(W._fmtTime('not a date'),null);
});

test('timeline state mapping: valid / below threshold / clouds / invalid; never a number for missing',()=>{
 const W=load().SatWorkspace,s=(a,m)=>W._acqState(a,m);
 assert.equal(s({status:'OK',valid_pct_inside:99},60),'ok');assert.equal(s({status:'OK',valid_pct_inside:59.9},60),'low');
 assert.equal(s({status:'OK',valid_pct_inside:null},60),'low');assert.equal(s({status:'SKIPPED_CLOUD'},60),'cloud');
 assert.equal(s({status:'NO_VALID_PIXELS'},60),'invalid');assert.equal(s({status:'ERROR'},60),'invalid');
 assert.equal(s({status:'PENDING'},60),'pending');assert.equal(s({status:'OK',valid_pct_inside:70},null),'ok');   // default 60
 const a=fx('area_2_kekava'),counts={};a.timeline.forEach(x=>{const k=x.sensor+':'+W._acqState(x,a.config?a.config.min_valid_pct:60);counts[k]=(counts[k]||0)+1;});
 assert.ok(counts['S2:cloud']>0&&counts['S1:ok']>0,JSON.stringify(counts));
});

test('compare pairs: same sensor, same S1 geometry, ordered, both with images; composites never mixed',()=>{
 const W=load().SatWorkspace,p=W._comparePair;
 const s2a={acq_id:1,sensor:'S2',sensing_time_utc:'2026-06-29T09:44:00Z',quicklook_url:'/q1',truecolor_url:'/t1'};
 const s2b={acq_id:2,sensor:'S2',sensing_time_utc:'2026-08-21T09:44:00Z',quicklook_url:'/q2',truecolor_url:null};
 const s1a={acq_id:3,sensor:'S1',orbit_direction:'ASCENDING',relative_orbit:58,sensing_time_utc:'2026-07-01T16:00:00Z',quicklook_url:'/q3'};
 const s1b={acq_id:4,sensor:'S1',orbit_direction:'ASCENDING',relative_orbit:131,sensing_time_utc:'2026-08-01T16:00:00Z',quicklook_url:'/q4'};
 const s1c={...s1b,acq_id:5,relative_orbit:58};
 assert.equal(p(s2a,s2b).ok,true);assert.equal(p(s2a,s1a).reason,'pairSensor');assert.equal(p(s1a,s1b).reason,'pairGeometry');
 assert.equal(p(s1a,s1c).ok,true);assert.equal(p(s2b,s2a).reason,'pairOrder');assert.equal(p(s2a,s2a).reason,'pairSame');
 assert.equal(p(s2a,{...s2b,quicklook_url:null}).reason,'pairNoImage');assert.equal(p(null,s2b).reason,'pairMissing');
 assert.equal(W._pairComposite(s2a,s2b,'true'),'false');                         // only one side has true colour
 assert.equal(W._pairComposite(s2a,{...s2b,truecolor_url:'/t2'},'true'),'true');
 assert.equal(W._pairComposite(s2a,{...s2b,truecolor_url:'/t2'},'false'),'false');
 assert.equal(W._pairComposite(s1a,s1c,'true'),'s1');                             // radar is never presented as optical
});

test('default pair for real event 60 (successor of 51): last clear S2 06-29 → FIRST valid S2 after 08-11 (acq 325); no true colour on 325 → false colour on both',()=>{
 const W=load().SatWorkspace,a=fx('area_2_kekava'),e=fx('event_60_current_successor_of_51'),by={};a.timeline.forEach(x=>by[x.acq_id]=x);
 const pr=W._defaultPair(e,by,a.config?a.config.min_valid_pct:60);
 assert.equal(pr.before.acq_id,299);assert.equal(pr.after.acq_id,325);assert.equal(pr.before.sensor,'S2');
 assert.equal(W._comparePair(pr.before,pr.after).ok,true);
 assert.equal(W._pairComposite(pr.before,pr.after,'true'),'false');                // 299 has true colour, 325 not
 assert.equal(W._pairComposite(by[299],by[331],'true'),'true');                     // user-picked 299 → 331 can be true colour
});

test('VMD p_cirg / p_cirp: 0, 0.0, "0", NULL are "not stated", never a year; years shown without .0',()=>{
 const W=load().SatWorkspace;
 for(const v of [0,0.0,'0',null,undefined,''])assert.equal(W._vmdValue(v),null,String(v));
 assert.equal(W._vmdValue(2026.0),'2026');assert.equal(W._vmdValue('11'),'11');
 assert.match(read('assets/sat-workspace.js'),/vmdValue\(cp\.p_cirg\) \? .* : '<span class="satw-na">' \+ esc\(t\('notStated'\)\)/);
});

test('every LV string has an EN twin and vice versa; key product wording present',()=>{
 const T=load().SatWorkspace._T;
 assert.deepEqual(Object.keys(T.lv).sort(),Object.keys(T.en).sort());
 assert.equal(T.lv.sSUSPECTED,'Iespējamas izmaiņas');assert.equal(T.lv.na,'Nav pieejams');
 assert.match(T.lv.analysisNote,/Notikuma poligona līkne — vēlāk/);assert.match(T.lv.s1Label,/nav fotogrāfija/);
 assert.equal(T.lv.attribution,'Contains modified Copernicus Sentinel data {year}');
 for(const bad of [/nelikumīg/i,/pārkāpum/i,/illegal/i,/violation/i,/harvest/i,/storm/i])for(const v of Object.values(T.lv).concat(Object.values(T.en)))assert.doesNotMatch(v,bad,v);
});

test('legacy hooks kept: lvmButton and _trServer stay; only load/openArea/openEvent are routed to the workspace',()=>{
 const ctx=load();
 assert.equal(typeof ctx.SatMonitoring.lvmButton,'function');assert.equal(typeof ctx.SatMonitoring._trServer,'function');
 assert.equal(ctx.SatMonitoring.load,ctx.SatWorkspace.load);assert.equal(typeof ctx.SatMonitoring._legacy.load,'function');
 const html=read('index.html');assert.ok(html.indexOf('/assets/sat-workspace.js')>html.indexOf('/assets/sat-monitoring.js'));
 assert.match(html,/<script src="\/assets\/forest-map\.js\?v=20261107"><\/script>/);   // activation anchor untouched
});

test('no Esri / commercial basemap offered; OSM base only',()=>{
 const src=read('assets/sat-workspace.js');assert.doesNotMatch(src,/arcgisonline|World_Imagery/);assert.match(src,/tile\.openstreetmap\.org/);
});

function lum(hex){const c=hex.replace('#','').match(/../g).map(x=>parseInt(x,16)/255).map(v=>v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4));return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2];}
function ratio(a,b){const [x,y]=[lum(a),lum(b)].sort((p,q)=>q-p);return (x+0.05)/(y+0.05);}
test('WCAG AA (4.5:1) for text on panels in both themes (values read from the CSS)',()=>{
 const css=read('assets/sat-workspace.css');
 const block=sel=>{const m=css.match(new RegExp(sel.replace(/[.#]/g,'\\$&')+'\\{([^}]*)\\}'));return Object.fromEntries([...m[1].matchAll(/--([a-zA-Z0-9]+):(#[0-9A-Fa-f]{6})/g)].map(x=>[x[1],x[2]]));};
 const dark=block('#satm-root.satw'),light={...dark,...block('#satm-root.satw.satw-light')};
 const solid={dark:{panel:'#101914',panel2:dark.panel2},light:{panel:'#FFFFFC',panel2:light.panel2}};   // rgba panels over their bg
 for(const [name,v] of [['dark',dark],['light',light]])for(const fg of ['text','muted','amber','red','green','accent'])for(const bg of ['panel','panel2']){
  if(fg==='accent'&&name==='dark'&&bg==='panel2')continue;                       // accent is not used as text on panel2 in dark
  const r=ratio(v[fg],solid[name][bg]);assert.ok(r>=4.5,`${name}: --${fg} ${v[fg]} on ${bg} ${solid[name][bg]} = ${r.toFixed(2)}`);}
 assert.ok(ratio('#F5F5F0','#245B43')>=4.5,'chip text on brand');
});

test('"last clear acquisition without change" is strictly before the onset (event 60: not the 08-04 baseline)',()=>{
 const W=load().SatWorkspace,a=fx('area_2_kekava'),e=fx('event_60_current_successor_of_51'),by={};a.timeline.forEach(x=>by[x.acq_id]=x);
 const b=W._lastClearBefore(e,by,60);
 assert.ok(b,'found');assert.ok(new Date(b.sensing_time_utc)<new Date(e.first_after_time_utc),b.sensing_time_utc+' < '+e.first_after_time_utc);
 assert.ok(e.before.some(x=>new Date(x.sensing_time_utc)>=new Date(e.first_after_time_utc)),'fixture really contains a later baseline');
 assert.equal(W._lastClearBefore({before:[],first_after_time_utc:null},by,60),null);
});
