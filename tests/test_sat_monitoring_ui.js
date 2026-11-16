'use strict';
// Satellite Monitoring UI (Stage 3): i18n completeness (EN -> LV), gaps never 0, sidebar placement, LVM GEO button.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const ROOT=path.join(__dirname,'..');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8');

function loadI18n(){
 const body={nodeType:1,childNodes:[],querySelectorAll:()=>[],hasAttribute:()=>false};
 const ctx={document:{readyState:'loading',addEventListener(){},body,documentElement:{setAttribute(){}}},
  MutationObserver:function(){this.observe=()=>{};},alert(){},confirm(){return true},prompt(){return ''},Date,console};
 ctx.window=ctx;vm.createContext(ctx);vm.runInContext(read('assets/i18n-lv.js'),ctx);return ctx.window.ForestI18n;
}
function loadSat(extra){
 const ctx={console,Promise,JSON,Math,Date,encodeURIComponent,...(extra||{})};
 ctx.window=ctx;ctx.document=ctx.document||{getElementById:()=>null,querySelector:()=>null,head:{appendChild(){}}};
 vm.createContext(ctx);vm.runInContext(read('assets/sat-monitoring.js'),ctx);return ctx.window.SatMonitoring;
}

test('every static Satellite Monitoring string has a Latvian translation',()=>{
 const I=loadI18n(),T=loadSat()._T,same=new Set(['LVM GEO']);
 const missing=Object.values(T).filter(s=>!same.has(s)&&I.tr(s)===s);
 assert.deepEqual(missing,[]);
});
test('dynamic strings (numbers, names) translate through patterns',()=>{
 const I=loadI18n(),samples=loadSat()._TD_SAMPLES;
 for(const s of samples){const r=I.tr(s);assert.notEqual(r,s,s);assert.doesNotMatch(r,/ (detected|outside the approved|satellite monitoring|recovered \(not)/,r);}
 assert.equal(I.tr('Vegetation/land-cover change detected: 5.97 ha'),'Konstatētas veģetācijas/zemes seguma izmaiņas: 5.97 ha');
 assert.equal(I.tr('0.84 ha outside the approved boundary'),'0.84 ha ārpus apstiprinātās robežas');
 assert.equal(I.tr('Detection generation 1 · code b3c0fd4'),'Noteikšanas paaudze 1 · kods b3c0fd4');
 assert.equal(I.trMessage('Add BIK-001 to satellite monitoring? The last 120 days are fetched first.'),
  'Pievienot BIK-001 satelītu monitoringam? Vispirms tiks ielādētas pēdējās 120 dienas.');
});
test('wording is neutral (D4) in EN and LV',()=>{
 const I=loadI18n(),T=loadSat()._T,all=Object.values(T).concat(Object.values(T).map(s=>I.tr(s)));
 for(const s of all)assert.doesNotMatch(s.toLowerCase(),/illegal|violation|confirmed felling|nelikumīg|pārkāpum/,s);
});
test('time series: no-data stays a gap (null), never 0',()=>{
 const series=loadSat()._series;
 const tl=[{sensor:'S2',status:'OK',sensing_time_utc:'2026-10-01T10:00:00Z',metrics_inside:{NDVI:{median:0.81}}},
  {sensor:'S2',status:'SKIPPED_CLOUD',sensing_time_utc:'2026-10-11T10:00:00Z',metrics_inside:{NDVI:{median:null,null_reason:'SKIPPED_CLOUD'}}},
  {sensor:'S2',status:'OK',sensing_time_utc:'2026-10-21T10:00:00Z',metrics_inside:{}},
  {sensor:'S2',status:'NO_VALID_PIXELS',sensing_time_utc:'2026-10-26T10:00:00Z',metrics_inside:{NDVI:{median:0}}},
  {sensor:'S1',status:'OK',sensing_time_utc:'2026-10-25T05:00:00Z',metrics_inside:{NDVI:{median:0.5}}}];
 const s=series(tl,'S2','NDVI');
 assert.deepEqual(s.map(p=>p.y),[0.81,null,null,null]);
 assert.equal(s.length,4);
});
test('LVM GEO geometry: Polygon kept, single-part MultiPolygon unwrapped, multi-part and missing refused',()=>{
 const g=loadSat()._lvmGeometry,ring=[[24,57],[24.01,57],[24.01,57.01],[24,57]];
 assert.equal(g({geometry:{type:'Polygon',coordinates:[ring]}}).geometry.type,'Polygon');
 assert.deepEqual(JSON.parse(JSON.stringify(g({geometry:{type:'MultiPolygon',coordinates:[[ring]]}}).geometry)),{type:'Polygon',coordinates:[ring]});
 assert.equal(g({geometry:{type:'MultiPolygon',coordinates:[[ring],[ring]]}}).error,'lvmMulti');
 assert.equal(g({}).error,'noPolygon');
});
test('event images: latest S2 after-image, before-image of the same sensor',()=>{
 const p=loadSat()._pickImages({after:[{sensor:'S1',sensing_time_utc:'2026-08-20',quicklook_url:'s1'},{sensor:'S2',sensing_time_utc:'2026-08-11',quicklook_url:'a1'},
  {sensor:'S2',sensing_time_utc:'2026-08-21',quicklook_url:'a2'}],before:[{sensor:'S2',sensing_time_utc:'2026-07-01',quicklook_url:'b1'},
  {sensor:'S1',sensing_time_utc:'2026-07-30',quicklook_url:'bs1'},{sensor:'S2',sensing_time_utc:'2026-07-20',quicklook_url:'b2'}]});
 assert.equal(p.after.quicklook_url,'a2');assert.equal(p.before.quicklook_url,'b2');
});
test('sidebar: one new item right after Sectors under MONITOR; order of existing items unchanged; navMap matches',()=>{
 const html=read('index.html'),nav=html.slice(html.indexOf('<nav>'),html.indexOf('</nav>'));
 const ids=[...nav.matchAll(/class="nav-item[^"]*"[^>]*onclick="(?:objectFilter=undefined;)?nav\('([^']+)'\)"/g)].map(m=>m[1]);
 assert.deepEqual(ids,['overview','objects','sectors','sat-monitoring','risks','gps','trucks','timber','photos','inspector','satellite','lvm-geodata','integrations','forest-map']);
 const groups=[...nav.matchAll(/class="nav-group"[^>]*>([^<]+)</g)].map(m=>m[1]);
 assert.deepEqual(groups,['Monitor','Operations','AI','Admin']);
 assert.ok(nav.indexOf("nav('sat-monitoring')")<nav.indexOf('>Operations<'));
 const navMap=eval('('+html.match(/const navMap = (\{[^}]+\})/)[1]+')');
 ids.forEach((id,i)=>assert.equal(navMap[id],i,id));
 assert.match(html,/<div class="section" id="sec-sat-monitoring"><div id="satm-root"><\/div><\/div>/);
 assert.match(html,/'sat-monitoring': \(\) => window\.SatMonitoring/);
 assert.match(html,/<script src="\/assets\/sat-monitoring\.js"><\/script>/);
});
test('LVM GEO: exactly one hook in the compartment popup; Forest Map untouched',()=>{
 const v=read('assets/vmd-production.js');
 assert.equal((v.match(/SatMonitoring/g)||[]).length,1);
 assert.match(v,/window\.SatMonitoring\?\.lvmButton\?\.\(popup,feature\);/);
 assert.doesNotMatch(read('assets/forest-map.js'),/SatMonitoring|sat-monitoring/);
 assert.doesNotMatch(read('assets/lvm-geodata.js'),/SatMonitoring|sat-monitoring/);
});
test('LVM GEO button: "Already monitored" when an active area exists; one lookup only when shown',async()=>{
 const calls=[],made=[];let ioCb=null;
 const document={getElementById:()=>null,querySelector:()=>null,head:{appendChild(){}},
  createElement:tag=>{const n={tag,disabled:false,textContent:'',type:'',className:''};made.push(n);return n;}};
 const fetch=async(url)=>{calls.push(url);return {ok:true,status:200,json:async()=>({monitored:true,area_id:3,queued_job_id:null})};};
 const IntersectionObserver=function(cb){ioCb=cb;this.observe=()=>{};this.disconnect=()=>{};};
 const sat=loadSat({document,fetch,IntersectionObserver});
 const box={children:[],appendChild(n){this.children.push(n);}};
 const b=sat.lvmButton(box,{id:'vmd-42',geometry:{type:'Polygon',coordinates:[[[24,57],[24.01,57],[24.01,57.01],[24,57]]]},properties:{kvart:5,nog:12,kadastrs:'80480140048'}});
 assert.equal(box.children.length,1);assert.equal(b.textContent,'Add to satellite monitoring');assert.equal(calls.length,0);
 ioCb([{isIntersecting:true}]);await new Promise(r=>setTimeout(r,10));
 assert.deepEqual(calls,['/api/sat-monitoring/lookup?source=LVM_GEO&source_ref=vmd-42']);
 assert.equal(b.textContent,'Already monitored');assert.equal(b.disabled,true);
 const m=sat.lvmButton(box,{id:'x',geometry:{type:'MultiPolygon',coordinates:[[[[24,57]]],[[[25,57]]]]}});
 assert.equal(m.disabled,true);assert.equal(m.textContent,'Multi-part polygon — add the parts separately');
});
