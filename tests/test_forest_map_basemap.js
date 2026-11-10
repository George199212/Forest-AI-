'use strict';
// Forest Map basemap switch: one source of truth for the on-map control and the sidebar select,
// session persistence (localStorage, failure-tolerant) and satellite → map fallback.
const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../assets/forest-map.js'),'utf8');
const grab=name=>{const m=src.match(new RegExp('function '+name+'\\([^)]*\\)\\{.*?\\}\\n','s'));assert.ok(m,name);return m[0];};
const constLine=src.match(/const BASEMAP_KEY=[^\n]*\n/)[0];

function layer(name){const handlers={};return {name,handlers,on(ev,fn){(handlers[ev]=handlers[ev]||[]).push(fn);return this;},fire(ev){(handlers[ev]||[]).forEach(fn=>fn());},
  addTo(map){map.layers.add(this);map.order.push(this.name);return this;},bringToBack(){this.back=true;}};}
function button(kind){const attrs={};return {dataset:{basemap:kind},disabled:false,title:'',attrs,setAttribute(k,v){attrs[k]=v;},classList:{on:new Set(),toggle(c,v){v?this.on.add(c):this.on.delete(c);}}};}
function make({storage,storageThrows=false}={}){
 const store=storage||new Map();
 const localStorage=storageThrows?{getItem(){throw Error('denied');},setItem(){throw Error('denied');}}:{getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,v)};
 const map={layers:new Set(),order:[],hasLayer(l){return this.layers.has(l);},removeLayer(l){this.layers.delete(l);}};
 const satOption={disabled:false},select={value:'satellite',querySelector:()=>satOption};
 const s={map,layers:{satellite:layer('satellite'),standard:layer('standard'),forest:layer('forest')},basemapButtons:[button('satellite'),button('standard')],basemapNote:{hidden:true,textContent:''}};
 const messages=[];const words={satelliteFailed:'Satelītattēli nav pieejami; rādīta karte. Meža dati paliek redzami.'};
 const api=new Function('s','global','dom','t','message',constLine+[grab('savedBasemap'),grab('storeBasemap'),grab('setBasemap'),grab('syncBasemap'),grab('watchSatellite')].join('\n')+';return {savedBasemap,setBasemap,watchSatellite};')
  (s,{localStorage},id=>id==='basemap'?select:null,k=>words[k]||k,m=>messages.push(m));
 return {...api,s,map,select,satOption,store,messages};
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
