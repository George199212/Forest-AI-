'use strict';
// Forest Map layer "Satelīta izmaiņas" + satellite deep links: route parsing, auto-refresh exclusion, the
// forest-map.js hook (one checkbox, one toggleLayer branch, nothing else changed), styles per status/basemap, popup.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const ROOT=path.join(__dirname,'..');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8');
const html=read('index.html'),fmSrc=read('assets/forest-map.js');

function routeFromHash(hash){
 const src=html.match(/function routeFromHash\(\) \{[\s\S]*?\n\}\n/)[0];
 const loaders={overview:1,'forest-map':1,'sat-monitoring':1,sectors:1};
 return new Function('location','loaders',src+';return routeFromHash();')({hash},loaders);
}

test('deep links: #forest-map?sat_event / ?sat_area and #sat-monitoring?event / ?area',()=>{
 assert.deepEqual(routeFromHash('#forest-map?sat_event=52'),{type:'nav',id:'forest-map',satEvent:52,satArea:null});
 assert.deepEqual(routeFromHash('#forest-map?sat_area=1'),{type:'nav',id:'forest-map',satEvent:null,satArea:1});
 assert.deepEqual(routeFromHash('#sat-monitoring?event=51'),{type:'nav',id:'sat-monitoring',event:51,area:null});
 assert.deepEqual(routeFromHash('#sat-monitoring?area=2'),{type:'nav',id:'sat-monitoring',event:null,area:2});
 assert.deepEqual(routeFromHash('#forest-map?sat_event=abc'),{type:'nav',id:'forest-map',satEvent:null,satArea:null});
 // existing routes unchanged
 assert.deepEqual(routeFromHash('#forest-map/session-7'),{type:'nav',id:'forest-map',session:7});
 assert.deepEqual(routeFromHash('#sat-monitoring'),{type:'nav',id:'sat-monitoring'});
 assert.deepEqual(routeFromHash('#nope'),{type:'nav',id:'overview'});
});

test('openRoute hands satellite deep links to ForestMapSat / SatMonitoring; script tag present',()=>{
 assert.match(html,/if \(route\.satEvent\) window\.ForestMapSat\?\.openEvent\(route\.satEvent\);/);
 assert.match(html,/else if \(route\.satArea\) window\.ForestMapSat\?\.openArea\(route\.satArea\);/);
 assert.match(html,/if \(route\.event\) window\.SatMonitoring\?\.openEvent\(route\.event\);/);
 assert.ok(html.indexOf('/assets/forest-map-sat.js')>html.indexOf('/assets/forest-map.js'));
});

test('auto-refresh skips Satellite Monitoring (an open event page is not thrown away)',()=>{
 const line=html.match(/setInterval\(\(\)=>\{ if\(currentSection[^\n]*/)[0];
 assert.match(line,/currentSection!=='sat-monitoring'/);
 assert.match(line,/currentSection!=='forest-map'/);
});

test('forest-map.js hook: satchanges checkbox (off by default) only calls ForestMapSat.toggle',()=>{
 assert.match(fmSrc,/\['forest','parcels','sectors','selected','gps','violations','satchanges'\]\.forEach/);
 const checked=fmSrc.match(/check\.checked=([^;]*);/)[1];
 assert.doesNotMatch(checked,/satchanges/);
 const fn=fmSrc.match(/function toggleLayer\(kind,visible\)\{[^\n]*\n/)[0];
 const calls=[],other=[];
 const toggleLayer=new Function('global','s','dom','loadOverview','loadGps',fn+';return toggleLayer;')(
  {ForestMapSat:{toggle:v=>calls.push(v)}},{get gps(){other.push('gps');return {};},get layers(){other.push('layers');return {};}},
  ()=>{other.push('dom');},()=>other.push('ov'),()=>other.push('gps'));
 toggleLayer('satchanges',true);toggleLayer('satchanges',false);
 assert.deepEqual(calls,[true,false]);assert.deepEqual(other,[]);
 assert.match(fmSrc,/get lang\(\)\{return s\.lang\|\|'lv';\},get basemap\(\)\{return s\.basemap;\}/);
 // holdView reuses the GPS session deep-link flag only (violations overview does not re-fit the map)
 assert.match(fmSrc,/holdView\(\)\{s\.gps\.deepLink=true;\}/);
 assert.match(read('assets/forest-map-sat.js'),/fm\(\)\.holdView\(\);\s*\n\s*checkbox\(true\);/);
});

function el(tag){const n={tag,children:[],textContent:'',className:'',href:'',appendChild(c){this.children.push(c);return c;}};return n;}
function text(n){return [n.textContent].concat(n.children.map(text)).join('|');}
function loadSat(fm){
 const ctx={console,Promise,JSON,Math,Number,String,encodeURIComponent,setTimeout,ForestMap:fm,
  document:{createElement:el,getElementById:()=>null}};
 ctx.window=ctx;vm.createContext(ctx);vm.runInContext(read('assets/forest-map-sat.js'),ctx);return ctx.ForestMapSat;
}
const EV={kind:'event',event_id:52,area_id:2,area_name:'Kekava positive control',zone:'INSIDE',zone_ha:3.51,area_ha:3.51,
 onset_utc:'2026-08-11T09:40:00Z',confidence:'HIGH',status:'SUSPECTED',status_group:'SUSPECTED',event_url:'#sat-monitoring?event=52'};

test('styles: by status group; footprint colour follows the basemap; own pane above sectors',()=>{
 const fm={lang:'lv',basemap:'satellite'},S=loadSat(fm);
 const sus=S._style({properties:EV}),rec=S._style({properties:{...EV,status_group:'RECOVERED'}}),
  rev=S._style({properties:{...EV,status_group:'REVIEWED'}});
 assert.equal(sus.pane,'fmSatChange');assert.notEqual(sus.color,rec.color);assert.notEqual(sus.color,rev.color);
 assert.equal(rec.dashArray,'4 4');
 assert.equal(S._style({properties:{kind:'footprint'}}).color,'#ffffff');
 fm.basemap='standard';assert.equal(S._style({properties:{kind:'footprint'}}).color,'#333333');
 assert.match(read('assets/forest-map-sat.js'),/style\.zIndex = 380/);
});

test('popup: id, onset, area, confidence, status, link back to the event page (LV and EN)',()=>{
 const fm={lang:'lv',basemap:'satellite'},S=loadSat(fm);
 const lv=S._popup(EV),t=text(lv);
 for(const s of ['Notikums #52','2026-08-11','3.51 ha','Augsta','Iespējamas izmaiņas','Robežās','Atvērt notikuma lapu'])assert.ok(t.includes(s),s);
 const link=lv.children.find(c=>c.tag==='a');assert.equal(link.href,'#sat-monitoring?event=52');
 fm.lang='en';const en=text(S._popup({...EV,zone:'BUFFER',status:'RECOVERED',confidence:null}));
 for(const s of ['Event #52','Outside the boundary (buffer)','Recovered','—'])assert.ok(en.includes(s),s);
 assert.deepEqual(Object.keys(S._W.lv).sort(),Object.keys(S._W.en).sort());
});

test('"Atvērt Meža kartē" buttons on the area and event pages use the deep links',()=>{
 const src=read('assets/sat-monitoring.js');
 assert.match(src,/fmLink\('sat_area=' \+ a\.id\)/);assert.match(src,/fmLink\('sat_event=' \+ e\.id\)/);
 assert.match(src,/href="#forest-map\?' \+ q \+ '"/);
 assert.match(read('assets/i18n-lv.js'),/'Open in Forest Map': 'Atvērt Meža kartē'/);
});

test('index.html keeps the exact script tags api.py rewrites to enable LVM GEO / Forest Map',()=>{
 const api=read('api.py');
 const tags=[...api.matchAll(/html = html\.replace\('(<script src="[^"]+"><\/script>)'/g)].map(m=>m[1]);
 assert.ok(tags.length>=2,'api.py activation replaces found');
 for(const tag of tags)assert.ok(html.includes(tag),'index.html lost the activation anchor '+tag);
});
