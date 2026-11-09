'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../assets/lvm-wms-map.js'), 'utf8');
class Events {
  constructor() { this.handlers = {}; }
  on(names, fn) { names.split(' ').forEach(n => (this.handlers[n] ||= []).push(fn)); return this; }
  once(name, fn) { const wrap = e => { this.off(name, wrap); fn(e); }; return this.on(name, wrap); }
  off(names, fn) { names.split(' ').forEach(n => {this.handlers[n]=(this.handlers[n]||[]).filter(h=>h!==fn);}); return this; }
  fire(name, data={}) { (this.handlers[name]||[]).slice().forEach(fn=>fn(data)); }
}
function node() {
  return {style:{},children:[],setAttribute(k,v){this[k]=v;},append(n){this.children.push(n);},
    insertBefore(n){this.children.unshift(n);},get firstChild(){return this.children[0];}};
}
class MapStub extends Events {
  constructor() {super();this.panes={};this.layers=new Set();this.controls=[];this.options={crs:'original-map-crs'};}
  getPane(n){return this.panes[n];}
  createPane(n){return this.panes[n]=node();}
  hasLayer(l){return this.layers.has(l);}
  addLayer(l){if(this.hasLayer(l))return this;this.layers.add(l);l.fire?.('add');this.fire('layeradd',{layer:l});return this;}
  removeLayer(l){if(this.layers.delete(l))this.fire('layerremove',{layer:l});return this;}
}
function environment(saved=[], storageBlocked=false) {
  const tiles=[],timers=[],storage={value:JSON.stringify(saved),getItem(){if(storageBlocked)throw Error('storage blocked');return this.value;},setItem(k,v){if(storageBlocked)throw Error('storage blocked');this.value=v;}};
  function control(options) {return {options,box:node(),addTo(map){map.controls.push(this);if(this.onAdd)this.box=this.onAdd(map);return this;},getContainer(){return this.box;}};}
  control.layers=(base,overlays,options)=>Object.assign(control(options),{base,overlays});
  const L={CRS:{EPSG3857:{code:'EPSG:3857'}},control,
    DomUtil:{create(tag,cls,parent){const n=node();n.tag=tag;n.className=cls;if(parent)parent.append(n);return n;}},
    DomEvent:{disableClickPropagation(){},disableScrollPropagation(){}},
    tileLayer:{wms(url,options){const l=Object.assign(new Events(),{url,options,addTo(map){map.addLayer(this);return this;}});tiles.push(l);return l;}}};
  const window={L,sessionStorage:storage,setTimeout(fn){timers.push(fn);},fetch(){throw Error('No backend, WFS, discovery or fetch allowed');}};
  vm.runInNewContext(source,{window});
  return {api:window.ForestLvmWms,L,tiles,timers,storage,map:new MapStub()};
}
test('two supplied public layers use native WMS 1.3.0 EPSG:3857; default off',()=>{
  const e=environment();const s=e.api.attach(e.map);
  assert.equal(e.api.mode,'direct_browser_wms');assert.equal(e.tiles.length,2);assert.equal(e.map.layers.size,0);
  assert.deepEqual(e.tiles.map(l=>l.options.layers),['pubblock_LVM','pubcompartments_LVM']);
  assert.equal(s.control.getContainer().firstChild.textContent,'LVM GEO');
  for(const tile of e.tiles){
    assert.equal(tile.url,'https://geoserver.lvmgeo.lv/wmsvector62531a9bfcfa4015856924e94076a179');
    assert.equal(tile.options.version,'1.3.0');assert.equal(tile.options.crs,e.L.CRS.EPSG3857);
    assert.equal(tile.options.format,'image/png');assert.equal(tile.options.transparent,true);
    assert.equal(tile.options.bbox,undefined);assert.equal(tile.options.crossOrigin,undefined);
    assert.equal(tile.options.attribution,'LVM GEO · LVM');
  }
});
test('both overlays toggle independently without affecting base/operational objects',()=>{
  const e=environment();const base={type:'OSM'},sector={type:'sector'},gps={type:'GPS'},machine={type:'machine'},risk={type:'risk'};
  [base,sector,gps,machine,risk].forEach(l=>e.map.addLayer(l));e.api.attach(e.map);
  e.tiles.forEach(l=>l.addTo(e.map));assert.equal(e.map.layers.size,7);
  e.map.removeLayer(e.tiles[0]);assert.equal(e.map.layers.size,6);assert(e.map.hasLayer(e.tiles[1]));
  e.map.removeLayer(e.tiles[1]);assert.equal(e.map.layers.size,5);
  [base,sector,gps,machine,risk].forEach(l=>assert(e.map.hasLayer(l)));
});
test('context pane stays below default sector paths, markers and risks; CRS unchanged',()=>{
  const e=environment();e.api.attach(e.map);
  assert.equal(e.map.panes.lvmGeoContext.style.zIndex,'250');assert.equal(e.map.panes.lvmGeoContext.style.pointerEvents,'none');
  assert.equal(e.map.options.crs,'original-map-crs');
  assert.deepEqual(e.tiles.map(l=>l.options.opacity),[0.65,0.75]);
});
test('attaching twice creates no duplicate controls or tile layers',()=>{
  const e=environment();const first=e.api.attach(e.map);assert.equal(e.api.attach(e.map),first);
  assert.equal(e.tiles.length,2);assert.equal(e.map.controls.length,2);
});
test('pan/zoom uses existing native layers without rebuilding/re-fetching discovery',()=>{
  const e=environment();e.api.attach(e.map);e.tiles.forEach(l=>l.addTo(e.map));
  for(let i=0;i<10;i++){e.map.fire('moveend');e.map.fire('zoomend');}
  assert.equal(e.tiles.length,2);assert.equal(e.map.layers.size,2);
  for(const l of e.tiles){assert.equal(l.options.updateWhenIdle,true);assert.equal(l.options.updateWhenZooming,false);assert.equal(l.options.keepBuffer,1);}
});
test('both choices restore in the same browser session, including map recreation',()=>{
  const e=environment(['lvm_blocks','lvm_compartments','unknown-layer']);e.api.attach(e.map);
  assert.equal(e.map.layers.size,2);
  const next=new MapStub();e.map.fire('unload');e.api.attach(next);assert.equal(next.layers.size,2);
  next.removeLayer(e.tiles[2]);
  assert.deepEqual(JSON.parse(e.storage.value),['lvm_compartments']);
});
test('one failed WMS layer is disabled once; base, second overlay and operational objects survive',()=>{
  const e=environment();const base={},risk={};e.map.addLayer(base);e.map.addLayer(risk);
  const s=e.api.attach(e.map);e.tiles.forEach(l=>l.addTo(e.map));
  for(let i=0;i<10;i++)e.tiles[0].fire('tileerror');assert.equal(e.timers.length,1);
  e.timers.shift()();assert(!e.map.hasLayer(e.tiles[0]));assert(e.map.hasLayer(e.tiles[1]));assert(e.map.hasLayer(base));assert(e.map.hasLayer(risk));
  assert.equal(s.messageControl.box.style.display,'');
  assert.match(s.messageControl.box.children[0].textContent,/temporarily unavailable/);
  e.map.fire('moveend');assert.equal(e.timers.length,0);
  e.tiles[0].addTo(e.map);assert.equal(s.messageControl.box.style.display,'none');
});
test('disabled sessionStorage does not prevent initialization or toggles',()=>{
  const e=environment([],true);e.api.attach(e.map);e.tiles[0].addTo(e.map);e.map.removeLayer(e.tiles[0]);assert.equal(e.map.layers.size,0);
});
test('main map integration is independent of backend feature flag and preserves rendering calls',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  assert.match(html,/<script src="\/assets\/lvm-wms-map.js\?v=1"><\/script>/);
  const main=html.slice(html.indexOf('async function loadMap()'),html.indexOf('async function renderProviderMachineMap'));
  assert.match(main,/window.ForestLvmWms.attach\(map\)/);assert(!main.includes('FOREST_GEODATA_ENABLED'));
  assert.match(main,/L\.polygon\(s.boundary/);assert.match(main,/renderProviderMachineMap\(map\)/);assert.match(main,/tile.openstreetmap.org/);
});
