'use strict';
// Forest Map basemap switch: one source of truth for the on-map control and the sidebar select,
// session persistence (localStorage, failure-tolerant) and satellite → map fallback.
const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../assets/forest-map.js'),'utf8');
const grab=name=>{const m=src.match(new RegExp('function '+name+'\\([^)]*\\)\\{.*?\\}\\n','s'));assert.ok(m,name);return m[0];};
const constLine=src.match(/const BASEMAP_KEY=[^\n]*\n/)[0];
const paletteBlock=src.match(/const PALETTE=\{[\s\S]*?\}\};\n/)[0];

function layer(name){const handlers={};return {name,handlers,on(ev,fn){(handlers[ev]=handlers[ev]||[]).push(fn);return this;},fire(ev){(handlers[ev]||[]).forEach(fn=>fn());},
  addTo(map){map.layers.add(this);map.order.push(this.name);return this;},bringToBack(){this.back=true;}};}
function button(kind){const attrs={};return {dataset:{basemap:kind},disabled:false,title:'',attrs,setAttribute(k,v){attrs[k]=v;},classList:{on:new Set(),toggle(c,v){v?this.on.add(c):this.on.delete(c);}}};}
function make({storage,storageThrows=false}={}){
 const store=storage||new Map();
 const localStorage=storageThrows?{getItem(){throw Error('denied');},setItem(){throw Error('denied');}}:{getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,v)};
 const map={layers:new Set(),order:[],hasLayer(l){return this.layers.has(l);},removeLayer(l){this.layers.delete(l);}};
 const satOption={disabled:false},select={value:'satellite',querySelector:()=>satOption};
 const s={map,layers:{satellite:layer('satellite'),standard:layer('standard'),forest:layer('forest')},basemapButtons:[button('satellite'),button('standard')],basemapNote:{hidden:true,textContent:''},stats:{}};
 // Loaded canvas tiles with stored data (as loadTile leaves them) for the repaint path.
 const draws=[],fetches=[];s.layers.forest._tiles={'1:1:14':{el:{_fmData:{features:[]}},coords:{x:1,y:1,z:14}},'2:1:14':{el:{},coords:{x:2,y:1,z:14}}};
 s.layers.parcels={...layer('parcels'),_tiles:{'1:1:14':{el:{_fmData:{features:[]}},coords:{x:1,y:1,z:14}}}};
 const legend=['available','selected','existing','review','parcels'].map(key=>({dataset:{key},style:{v:{},setProperty(k,v){this.v[k]=v;}}}));
 const document={querySelectorAll:sel=>sel==='.forest-map-key[data-key]'?legend:[]};
 const drawTile=(canvas,data,coords,kind)=>draws.push({kind,coords,data,basemap:s.basemap});
 const messages=[];const words={satelliteFailed:'Satelītattēli nav pieejami; rādīta karte. Meža dati paliek redzami.'};
 const api=new Function('s','global','dom','t','message','document','drawTile','fetch',constLine+paletteBlock+[grab('pal'),grab('savedBasemap'),grab('storeBasemap'),grab('redrawCanvases'),grab('restyleOverlays'),grab('syncLegend'),grab('setBasemap'),grab('syncBasemap'),grab('watchSatellite')].join('\n')+';return {savedBasemap,setBasemap,watchSatellite,pal,PALETTE};')
  (s,{localStorage},id=>id==='basemap'?select:null,k=>words[k]||k,m=>messages.push(m),document,drawTile,(...a)=>fetches.push(a));
 return {...api,s,map,select,satOption,store,messages,draws,fetches,legend};
}
const pressed=s=>s.basemapButtons.filter(b=>b.attrs['aria-pressed']==='true').map(b=>b.dataset.basemap);

test('on-map control and sidebar select stay in sync; exactly one basemap is on the map',()=>{
 const m=make();m.setBasemap('satellite',false);
 assert.deepEqual(pressed(m.s),['satellite']);assert.equal(m.select.value,'satellite');
 m.setBasemap('standard');
 assert.ok(m.map.hasLayer(m.s.layers.standard));assert.ok(!m.map.hasLayer(m.s.layers.satellite));
 assert.deepEqual(pressed(m.s),['standard']);assert.equal(m.select.value,'standard');
 assert.ok(m.s.layers.standard.back,'basemap is pushed to the back of the tile pane');
});
test('overlays are untouched when switching the basemap',()=>{
 const m=make();m.s.layers.forest.addTo(m.map);m.setBasemap('satellite',false);m.setBasemap('standard');m.setBasemap('satellite');
 assert.ok(m.map.hasLayer(m.s.layers.forest));
 // Overlays live in custom panes above Leaflet's tilePane (z 200); basemaps never get a pane option.
 for(const [,pane,z] of src.match(/\[\['fmForest',320\].*?\]\]/)[0].matchAll(/'(\w+)',(\d+)/g))assert.ok(Number(z)>200,pane);
 assert.match(src,/makeTiles\(kind\).*pane:kind==='forest'\?'fmForest':'fmParcels'/s);
});
test('choice persists for the session and is restored on reload',()=>{
 const store=new Map();const a=make({storage:store});a.setBasemap('standard');
 assert.equal(store.get('forestMap.basemap'),'standard');
 const b=make({storage:store});assert.equal(b.savedBasemap(),'standard');
 store.set('forestMap.basemap','<script>');assert.equal(make({storage:store}).savedBasemap(),null,'unknown values are ignored');
});
test('blocked localStorage never breaks the switch',()=>{
 const m=make({storageThrows:true});assert.equal(m.savedBasemap(),null);
 assert.doesNotThrow(()=>m.setBasemap('standard'));assert.equal(m.select.value,'standard');
});
test('satellite failure falls back to Karte with a notice, without persisting the fallback',()=>{
 const m=make();m.watchSatellite(m.s.layers.satellite);m.setBasemap('satellite');
 m.s.layers.satellite.fire('tileerror');m.s.layers.satellite.fire('tileerror');
 assert.ok(m.map.hasLayer(m.s.layers.satellite),'two transient errors do not switch');
 m.s.layers.satellite.fire('tileerror');
 assert.ok(m.map.hasLayer(m.s.layers.standard));assert.ok(!m.map.hasLayer(m.s.layers.satellite));
 assert.deepEqual(pressed(m.s),['standard']);assert.equal(m.s.basemapButtons[0].disabled,true);assert.equal(m.satOption.disabled,true);
 assert.equal(m.s.basemapNote.hidden,false);assert.match(m.messages[0],/Satelītattēli nav pieejami/);
 assert.equal(m.store.get('forestMap.basemap'),'satellite','user preference kept for the next session');
 m.setBasemap('satellite');assert.ok(m.map.hasLayer(m.s.layers.standard),'satellite stays unavailable this session');
});
test('errors after satellite tiles loaded do not force a fallback',()=>{
 const m=make();m.watchSatellite(m.s.layers.satellite);m.setBasemap('satellite');
 m.s.layers.satellite.fire('tileload');for(let i=0;i<5;i++)m.s.layers.satellite.fire('tileerror');
 assert.ok(m.map.hasLayer(m.s.layers.satellite));
});
test('control is mounted on the map, top-right, with Latvian labels Satelīts / Karte',()=>{
 assert.match(src,/function basemapControl\(\)\{const Control=L\.Control\.extend\(\{options:\{position:'topright'\}/);
 assert.match(src,/basemapSatellite:'Satelīts',basemapMap:'Karte'/);
 assert.match(src,/watchSatellite\(s\.layers\.satellite\);setBasemap\(savedBasemap\(\)\|\|'satellite',false\);basemapControl\(\);/);
});

// ── Contrast palette per basemap ────────────────────────────────────────────────────────────
test('satellite palette is byte-identical to the previous hard-coded colours',()=>{
 const {PALETTE}=make();assert.deepEqual({...PALETTE.satellite},{forest:'#74c484',forestWidth:1.1,forestFill:'rgba(85,172,107,.17)',review:'#e7a456',reviewFill:'rgba(231,164,86,.16)',parcels:'#62ccf2',parcelsWidth:1,
  presenceFill:'rgba(82,169,105,.38)',cellRgb:'82,169,105',point:'rgba(112,188,123,.78)',legendAvailable:'#70bc7b',selected:'#e2b64b',landUnit:'#62ccf2',transition:'#c9d1d9',casingOpacity:0});
 assert.doesNotMatch(src.slice(src.indexOf('function drawTile'),src.indexOf('function inside(')),/#74c484|#62ccf2|#e7a456|rgba\(8[25],/,'drawTile reads colours only from the palette');
});
test('palette is chosen by the active basemap; Karte uses the darker values',()=>{
 const m=make();m.setBasemap('satellite',false);assert.equal(m.pal().forest,'#74c484');
 m.setBasemap('standard',false);const P=m.pal();
 assert.deepEqual([P.forest,P.forestWidth,P.forestFill,P.review,P.reviewFill,P.parcels,P.parcelsWidth,P.cellRgb],['#1e6b34',1.6,'rgba(30,107,52,.08)','#c0661a','rgba(192,102,26,.12)','#1f6fb2',1.3,'30,107,52']);
 assert.deepEqual([P.selected,P.landUnit,P.transition,P.casingOpacity],['#b8860b','#1f6fb2','#c9d1d9',1]);
});
test('switching repaints loaded canvases from stored tile data, with no new requests',()=>{
 const m=make();m.setBasemap('satellite',false);const before=m.draws.length,repaintsBefore=m.s.stats.repaints;
 m.setBasemap('standard');const repainted=m.draws.slice(before);
 assert.deepEqual(repainted.map(d=>d.kind+':'+d.coords.x),['forest:1','parcels:1'],'only tiles that hold data; the empty canvas is skipped');
 assert.ok(repainted.every(d=>d.basemap==='standard'),'repaint uses the new palette');
 assert.equal(m.fetches.length,0,'no fetch on switch');assert.equal(m.s.stats.repaints-repaintsBefore,2);
 const n=m.draws.length;m.setBasemap('standard');assert.equal(m.draws.length,n,'no repaint when the basemap did not change');
 assert.match(src,/canvas\._fmData=data;drawTile\(canvas,data,coords,kind\)/,'loadTile keeps the parsed tile data');
 assert.doesNotMatch(src.slice(src.indexOf('function setBasemap'),src.indexOf('function syncBasemap')),/redraw\(\)/,'no Leaflet redraw (it would re-request tiles)');
});
test('legend swatches follow the active palette; existing sectors unchanged',()=>{
 const m=make();const v=()=>Object.fromEntries(m.legend.map(n=>[n.dataset.key,n.style.v['--key']]));
 m.setBasemap('satellite',false);assert.deepEqual(v(),{available:'#70bc7b',selected:'#e2b64b',existing:undefined,review:'#e7a456',parcels:'#62ccf2'});
 m.setBasemap('standard');assert.deepEqual(v(),{available:'#1e6b34',selected:'#b8860b',existing:undefined,review:'#c0661a',parcels:'#1f6fb2'});
});
test('vector overlays are restyled on switch (selected, land unit, GPS transitions/gaps + white casing only)',()=>{
 const m=make();const styled=[];const vec=name=>({setStyle(o){styled.push(name+':'+o.color);}});
 const track=[{options:{fmRole:'transition'},setStyle(o){styled.push('transition:'+o.color);}},{options:{fmRole:'gap'},setStyle(o){styled.push('gap:'+o.color);}},{options:{fmRole:'casing'},setStyle(o){styled.push('casing:'+o.opacity);}},{options:{color:'#e5484d'},setStyle(){styled.push('violation');}}];
 m.s.selectionLayer=vec('selected');m.s.parcel=vec('landUnit');m.s.gps={track:{eachLayer(fn){track.forEach(fn);}}};
 m.setBasemap('satellite',false);styled.length=0;m.setBasemap('standard');
 assert.deepEqual(styled,['selected:#b8860b','landUnit:#1f6fb2','transition:#c9d1d9','gap:#c9d1d9','casing:1']);
 styled.length=0;m.setBasemap('satellite');assert.deepEqual(styled,['selected:#e2b64b','landUnit:#62ccf2','transition:#c9d1d9','gap:#c9d1d9','casing:0']);
});
test('GPS transitions and gaps get a white casing drawn below them, invisible on satellite',()=>{
 const i=src.indexOf('for(const tr of r.transitions)');const block=src.slice(i,src.indexOf('trackStart',i));
 assert.ok(block.indexOf("fmRole:'casing'")<block.indexOf("fmRole:'transition'"),'casing is added first (below)');
 assert.ok(block.indexOf("fmRole:'casing',radius:5")<block.indexOf("fmRole:'gap'"),'gap casing below the gap ring');
 assert.match(block,/fmRole:'casing',color:'#fff',weight:6,opacity:pal\(\)\.casingOpacity,interactive:false/);
});
