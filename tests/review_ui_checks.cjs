const fs=require('fs'),vm=require('vm'),assert=require('assert');
const root=require('path').resolve(__dirname,'..');
function context(readOnly=false) {
  const c={console,Request,Response,Headers,URL,location:{href:'http://127.0.0.1:8003/',origin:'http://127.0.0.1:8003'},
    window:{alert(){},confirm(){},prompt(){},ForestInstance:{readOnly}},
    document:{readyState:'loading',addEventListener(){},documentElement:{classList:{add(){}}},
      head:{appendChild(){}},createElement(){return {style:{}};}}};
  vm.createContext(c);return c;
}
const c=context();vm.runInContext(fs.readFileSync(root+'/assets/i18n-en.js','utf8'),c);
const tr=c.window.ForestI18n.tr;
const cases=[
 ['R2: nav saistītas foto salīdzināšanas.','R2: no linked photo comparison.'],
 ['vidū pa labi','middle right'],['nav datu','no data'],
 ['\n Foto\n salīdzināšana  ','\n Photo comparison  '],
 ['Bojājumi apstiprināti','Damage confirmed'],['Iespējams bojājums','Possible damage'],
 ['Īslaicīgs objekts (cilvēks, dzīvnieks, transportlīdzeklis)','Transient object (person, animal, vehicle)'],
 ['R0: vispirms jāizskata 3 izmaiņas.','R0: first review 3 changes.'],
 ['R2: salīdzināti 0 no 0 punktiem, daļa nav datu (< 0,5).','R2: compared 0 of 0 points, share no data (< 0.5).'],
 ['09.10.2026 12:30','09 Oct 2026 12:30'],
 ['Salīdzināmajās redzamajās zonās izmaiņas nav konstatētas.','No changes were detected in the comparable visible areas.'],
 ['Tas nenozīmē, ka pārbaudīta visa teritorija vai ka bojājumu noteikti nav.','This does not mean the entire area was checked or that damage is definitely absent.'],
 ['Unrecognized evidence stays unchanged','Unrecognized evidence stays unchanged'],
];
for(const [source,expected] of cases) assert.equal(tr(source),expected);
const rules=[
 'R1: apstiprinātas izmaiņas ar klasi „iespējams bojājums”: 2; aktīvi pārskatītāja novērojumi par iespējamiem bojājumiem: 1.',
 'R2: salīdzināti 3 no 30 punktiem, daļa 0,1 (< 0,5); atkārtotai fotografēšanai atzīmētas izmaiņas: 1.',
 'R3a: salīdzināti 20 no 30 punktiem, daļa 0,67 (≥ 0,5); apstiprinātas iespējamās izmaiņas: 2; aktīvi pārskatītāja novērojumi par iespējamām izmaiņām: 1; bojājumi nav apstiprināti.',
 'R3: salīdzināti 20 no 30 punktiem, daļa 0,67 (≥ 0,5); apstiprinātu izmaiņu, atkārtotas fotografēšanas atzīmju un aktīvu pārskatītāja novērojumu nav.'
];
for(const text of rules) assert(!/[āčēģīķļņšūžĀČĒĢĪĶĻŅŠŪŽ\u0400-\u052f]/.test(tr(text)),tr(text));
const review=context();vm.runInContext(fs.readFileSync(root+'/assets/review-ui.js','utf8'),review);
function button(handler) {return {getAttribute(){return handler;},matches(){return false;}};}
for(const h of ['approveRisk(1,"ask")','pcReview(1,"CONFIRMED")','rcClose(1,false)','rcDraft(true)',
 'sendRiskMessage(1)','createSector()','deleteEmployee(1,"DEMO-001")','downloadPDF()',
 'runSectorAnalysis("DEMO-001")','syncIntegrationAction(1)','connectIntegrationAction("demo",true)',
 'retryRiskAI(1)','newUnknownAction()']) assert(!review.window.ForestReview.allowed(button(h)),h);
for(const h of ['nav("overview")','openSector("FIELD-TEST-01")','pcSetFilter("all")','pcViewerOpen(1,0)',
 'detailTab("map")','history.back()','setIntCategoryFilter(null,this)',
 'photoPage=Math.max(0,photoPage-1);renderPhotos()']) assert(review.window.ForestReview.allowed(button(h)),h);
assert.equal(review.window.ForestReview.displayText('CONNECTED'),'Not configured');
const withFetch=context(true);let outbound=0;
withFetch.window.fetch=async()=>{outbound++;return new Response(JSON.stringify({integrations:[{connection_status:'CONNECTED',confirmed_customer_use:'private customer note'}]}),{headers:{'Content-Type':'application/json'}});};
vm.runInContext(fs.readFileSync(root+'/assets/review-ui.js','utf8'),withFetch);
(async()=>{
 for(const method of ['POST','PUT','PATCH','DELETE']) assert.equal((await withFetch.window.fetch('/api/risks',{method})).status,403);
 assert.equal((await withFetch.window.fetch('/api/report/pdf/FIELD-TEST-01')).status,403);
 assert.equal((await withFetch.window.fetch('/api/inspector/analyze/FIELD-TEST-01')).status,403);
 assert.equal(outbound,0);
 const r=await withFetch.window.fetch('/api/integrations'),d=await r.json();
 assert.equal(d.integrations[0].connection_status,'Not configured');assert.equal(d.integrations[0].confirmed_customer_use,null);
 console.log('English runtime, rule-line, unknown-text preservation, control allowlist and review fetch checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
