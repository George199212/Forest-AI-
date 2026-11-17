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
 assert.equal(box.children.length,1);assert.equal(b.textContent,'Pievienot satelītu monitoringam');assert.equal(calls.length,0);
 ioCb([{isIntersecting:true}]);await new Promise(r=>setTimeout(r,10));
 assert.deepEqual(calls,['/api/sat-monitoring/lookup?source=LVM_GEO&source_ref=vmd-42']);
 assert.equal(b.textContent,sat._T_LV.lvmMonitored);assert.equal(b.disabled,true);
 const m=sat.lvmButton(box,{id:'x',geometry:{type:'MultiPolygon',coordinates:[[[[24,57]]],[[[25,57]]]]}});
 assert.equal(m.disabled,true);assert.equal(m.textContent,sat._T_LV.lvmMulti);
});

test('Latvian is the default; T_LV / TD_LV are exactly the i18n-lv.js translations (no drift); EN on request',()=>{
 const I=loadI18n(),sat=loadSat();
 assert.equal(sat.lang,'lv');
 for(const [k,v] of Object.entries(sat._T)){const want=v==='LVM GEO'?v:I.tr(v);assert.equal(sat._T_LV[k],want,k);}
 const TD=sat._TD_LV,samples=sat._TD_SAMPLES;
 const lv=[TD.lastDays(14),TD.recoveredNotCounted(1),TD.changeDetected('5.97 ha'),TD.outside('0.84 ha'),TD.eventTitle(51),
  TD.generation(1),TD.code('b3c0fd4'),TD.risk(12),TD.queuedJob(3),TD.confirmAdd('BIK-001')];
 samples.forEach((s,i)=>assert.equal(lv[i],I.trMessage?I.trMessage(s):I.tr(s),s));
 sat._setLang('en');assert.equal(sat.lang,'en');
});

test('stored server sentences (caveats, recovery, context reasons) are shown in Latvian; unknown text unchanged',()=>{
 const sat=loadSat(),tr=sat._trServer;
 assert.equal(tr('Snow on 12% of the area in the after-image.'),'Pēcattēlā sniegs klāj 12% teritorijas.');
 assert.equal(tr('no sector link for this area (source is not SECTOR)'),'teritorijai nav sasaistes ar sektoru (avots nav SECTOR)');
 assert.equal(tr('current mask 0.08 ha < min_cluster_ha 0.3 ha in 2 consecutive valid S2 acquisitions (last 2026-11-08)'),
  'pašreizējā maska 0.08 ha < min_cluster_ha 0.3 ha 2 secīgos derīgos S2 uzņēmumos (pēdējais 2026-11-08)');
 const cav='After-image is from Oct–Apr: leaf fall/leaf-off, frozen or wet ground and snow change optical indices and radar backscatter without any felling.';
 const lv=tr('Latest after-image 2026-11-08 (not used for the class): '+cav+' | Fragmented change: the largest cluster (2.00 ha) is 20% of the current area (10.00 ha), below 30%.');
 assert.match(lv,/^Jaunākais pēcattēls 2026-11-08 \(klasei netiek izmantots\): Pēcattēls ir no oktobra–aprīļa/);
 assert.match(lv,/ \| Sadrumstalotas izmaiņas: lielākais klasteris \(2\.00 ha\) ir 20% no pašreizējās platības \(10\.00 ha\), mazāk nekā 30%\.$/);
 assert.equal(tr('Some new server text'),'Some new server text');
 sat._setLang('en');assert.equal(tr('Snow on 12% of the area in the after-image.'),'Snow on 12% of the area in the after-image.');
});

test('event images show a loading state, removed on load, and a visible message on error (no silent black box)',()=>{
 const src=read('assets/sat-monitoring.js');
 assert.equal((src.match(/imgStatus\(div, L\.imageOverlay\(/g)||[]).length,3);
 assert.match(src,/overlay\.on\('load'[^\n]*removeChild\(st\)/);
 assert.match(src,/overlay\.on\('error'[^\n]*t\('imgFailed'\)/);
 const sat=loadSat();assert.equal(sat._T_LV.imgLoading,'Ielādē attēlu…');assert.equal(sat._T_LV.imgFailed,'Attēlu neizdevās ielādēt.');
});

test('worker badge: Not installed / Running / Idle / Timers off / Status unknown (LV), never Idle without a worker',()=>{
 const src=read('assets/sat-monitoring.js'),sat=loadSat();
 assert.match(src,/NOT_INSTALLED: \['wNotInstalled', 'b-gray'\], RUNNING: \['hRunning', 'b-amber'\], IDLE: \['hIdle', 'b-gray'\],/);
 assert.match(src,/t\('hLock'\) \+ ': ' \+ workerBadge\(h\.worker, h\.lock\)/);
 assert.equal(sat._T_LV.wNotInstalled,'Nav uzstādīts');assert.equal(sat._T_LV.hIdle,'Dīkstāvē');
 assert.equal(sat._T_LV.wTimersOff,'Taimeri izslēgti');assert.equal(sat._T_LV.wUnknown,'Statuss nav zināms');
});

test('event images: true colour (default) only when both images have it; false colour otherwise, with a note',()=>{
 const src=read('assets/sat-monitoring.js'),prov=read('satellite_monitoring/provider.py'),sat=loadSat();
 assert.match(prov,/S2_BANDS = \["B04", "B08", "B11", "B12", "SCL", "dataMask", "B03", "B02"\]/);   // B03/B02 appended
 assert.match(src,/function hasTrue\(imgs\) \{ return !!\(imgs\.before && imgs\.before\.truecolor_url && imgs\.after && imgs\.after\.truecolor_url\); \}/);
 assert.match(src,/colour: 'true'\}/);
 assert.equal((src.match(/L\.imageOverlay\(imgUrl\(/g)||[]).length,3);
 assert.match(src,/bandNote\(imgs\) \+ '<\/div>';/);
 assert.equal(sat._T_LV.colourTrue,'Patiesās krāsas');assert.equal(sat._T_LV.colourFalse,'Viltus krāsas');
 assert.match(sat._T_LV.bandNoTrue,/^Patiesās krāsas \(B04 \/ B03 \/ B02\) šiem attēliem nav ielādētas/);
 assert.match(sat._T_LV.bandS2,/^Sentinel-2 viltus krāsas \(B11 \/ B08 \/ B04\)/);
});
