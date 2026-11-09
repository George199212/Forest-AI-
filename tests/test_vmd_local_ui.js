'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../assets/vmd-local.js'),'utf8');
const data=JSON.parse(fs.readFileSync(path.join(__dirname,'../lvm_3_sectors.geojson'),'utf8'));
const id=f=>'VMD-'+f.properties.kadastrs+'-'+f.properties.kvart+'-'+f.properties.nog;
class Node{constructor(){this.style={};this.children=[];this.textContent='';this.hidden=true;this.disabled=false;}append(...n){this.children.push(...n);}replaceChildren(...n){this.children=n;}setAttribute(k,v){this[k]=v;}focus(){this.focused=true;}scrollIntoView(){this.scrolled=true;}}
function bounds(points){const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);return {isValid:()=>true,getWest:()=>Math.min(...xs),getSouth:()=>Math.min(...ys),getEast:()=>Math.max(...xs),getNorth:()=>Math.max(...ys)};}
function setup(payload=data,fail=false){
 const nodes=new Map(),requests=[],layers=[],imported=new Set();let cacheCleared=0;
 const doc={getElementById(id){if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);},createElement(){return new Node();}};
 const map={panes:{},layers:new Set(),fits:[],area:bounds([[24.4,56.4],[24.9,56.7]]),getPane(n){return this.panes[n];},createPane(n){return this.panes[n]={style:{}};},getBounds(){return this.area;},fitBounds(b){this.area=b;this.fits.push(b);},hasLayer(l){return this.layers.has(l);},removeLayer(l){this.layers.delete(l);}};
 const base={osm:true};map.layers.add(base);
 const L={control:{layers(base,overlays,options){return {overlays,options,addTo(){return this;}};}},geoJSON(d,options){
  const group={options,children:[],getBounds:()=>bounds(d.features.flatMap(f=>f.geometry.coordinates[0])),addTo(m){m.layers.add(this);return this;}};
  d.features.forEach(f=>{const layer={feature:f,style:null,handlers:{},setStyle(s){this.style=s;},bindPopup(p){this.popup=p;return this;},on(event,fn){this.handlers[event]=fn;},getBounds:()=>bounds(f.geometry.coordinates[0]),openPopup(){this.popupOpen=true;}};group.children.push(layer);options.onEachFeature(f,layer);});layers.push(group);return group;
 }};
 const window={};const ctx=vm.createContext({window,L,document:doc,AbortController,setTimeout,clearTimeout,console:{error(){}},clearCache(){cacheCleared++;},mapLoaded:true,fetch:async(url,options)=>{
  requests.push({url,options});let value,status=200;
  if(url.endsWith('/test-sectors')){value=payload;if(fail){status=503;value={detail:'offline'};}}
  else if(url.endsWith('/local-status'))value={dataset_version:'a'.repeat(64),features:data.features.map(f=>({external_id:id(f),status:imported.has(id(f))?'IMPORTED':'READY',importable:!imported.has(id(f)),sector:imported.has(id(f))?{id:18,name:'VMD test sector'}:null}))};
  else if(url.endsWith('/import')){const body=JSON.parse(options.body);assert.equal(body.dataset_version,'a'.repeat(64));body.feature_ids.forEach(fid=>imported.add(fid));value={results:body.feature_ids.map(fid=>({external_id:fid,status:'imported',id:18,name:'VMD test sector'})),imported:body.feature_ids.length,already_exists:0,failed:0};}
  else throw Error('No external requests allowed');
  return {ok:status===200,status,headers:{get:k=>k==='etag'?'"'+'a'.repeat(64)+'"':'application/geo+json'},json:async()=>value};
 }});vm.runInContext(script,ctx);
 return {api:window.VmdLocalDataset,map,base,nodes,doc,requests,layers,imported,cacheCleared:()=>cacheCleared,ctx};
}
test('three green polygons fit existing map, show local READY card and 3 selectable rows',async()=>{
 const e=setup();await e.api.attach(e.map);
 assert.equal(e.layers.length,1);assert.equal(e.layers[0].children.length,3);assert.equal(e.map.fits.length,1);
 assert.equal(e.nodes.get('lvm-feature-rows').children.length,3);assert.equal(e.nodes.get('vmd-local-count').textContent,'3');
 assert.match(e.nodes.get('vmd-local-status').textContent,/LOCAL DATA · READY/);assert.equal(e.nodes.get('vmd-local-importable').textContent,'YES');
 assert.equal(e.layers[0].options.style.color,'#4b9d54');assert.equal(e.map.panes.vmdLocalCompartments.style.zIndex,'350');assert(e.map.layers.has(e.base));
 assert.equal(e.nodes.get('lvm-import').disabled,true);assert(!e.requests.some(r=>r.options.method==='POST'));
});
test('polygon focuses table and popup without selecting checkbox; row click zooms to polygon',async()=>{
 const e=setup();await e.api.attach(e.map);const layer=e.layers[0].children[0];layer.handlers.click();
 let row=e.nodes.get('lvm-feature-rows').children[0];assert(row.focused&&row.scrolled);assert.equal(row.children[0].children[0].checked,false);
 assert.equal(layer.style.color,'#309fe8');assert(layer.popupOpen);assert.equal(layer.popup.children[0].textContent,'VMD forest compartment');
 assert.equal(layer.popup.children[1].textContent,'Kadastrs: '+data.features[0].properties.kadastrs);
 row.onclick();assert.equal(e.map.fits.length,2);
});
test('checkboxes independent; select all / clear selection control import enablement',async()=>{
 const e=setup();await e.api.attach(e.map);let check=e.nodes.get('lvm-feature-rows').children[0].children[0].children[0];
 check.checked=true;check.onchange();assert.equal(e.nodes.get('lvm-import').disabled,false);
 e.api.clearSelection();assert.equal(e.nodes.get('lvm-import').disabled,true);
 e.api.selectAll();assert.equal(e.nodes.get('lvm-feature-rows').children.filter(r=>r.children[0].children[0].checked).length,3);
 e.api.clearSelection();assert.equal(e.nodes.get('lvm-feature-rows').children.filter(r=>r.children[0].children[0].checked).length,0);
});
test('viewport preview uses only loaded local data and filters table',async()=>{
 const e=setup();await e.api.attach(e.map);const count=e.requests.length;e.map.area=bounds(data.features[0].geometry.coordinates[0]);e.api.preview();
 assert.equal(e.requests.length,count);assert.equal(e.nodes.get('lvm-feature-rows').children.length,1);
 assert.match(e.nodes.get('lvm-preview-state').textContent,/No live service request/);
});
test('one selected import sends only its stable ID, updates status and invalidates main map cache',async()=>{
 const e=setup();await e.api.attach(e.map);const check=e.nodes.get('lvm-feature-rows').children[0].children[0].children[0];check.checked=true;check.onchange();
 await e.api.importSelected();const post=e.requests.find(r=>r.options.method==='POST');
 assert.deepEqual(JSON.parse(post.options.body).feature_ids,[id(data.features[0])]);assert.equal(e.imported.size,1);
 const rows=e.nodes.get('lvm-feature-rows').children;assert.match(rows[0].children[6].textContent,/IMPORTED/);assert(rows[0].children[0].children[0].disabled);
 assert.equal(rows[1].children[6].textContent,'READY');assert.equal(rows[2].children[6].textContent,'READY');assert.equal(e.nodes.get('lvm-import').disabled,true);
 assert.equal(e.cacheCleared(),1);assert.equal(e.ctx.mapLoaded,false);
});
test('endpoint unavailable and empty data retain base map without claiming ready',async()=>{
 for(const [payload,fail] of [[data,true],[{type:'FeatureCollection',features:[]},false]]){
  const e=setup(payload,fail);await e.api.attach(e.map);assert(e.map.layers.has(e.base));assert.equal(e.nodes.get('vmd-local-status').textContent,'Local VMD dataset unavailable');assert.equal(e.layers.length,0);
 }
});
test('polygon/viewport intersection excludes bounding-box false positives and holes, includes contact',()=>{
 const e=setup(),hit=e.api.intersects;
 const triangle={coordinates:[[[0,0],[10,0],[0,10],[0,0]]]};assert.equal(hit(triangle,[8,8,9,9]),false);assert.equal(hit(triangle,[1,1,2,2]),true);
 const hole={coordinates:[[[0,0],[10,0],[10,10],[0,10],[0,0]],[[3,3],[7,3],[7,7],[3,7],[3,3]]]};
 assert.equal(hit(hole,[4,4,6,6]),false);assert.equal(hit(hole,[2,2,4,4]),true);assert.equal(hit(hole,[10,1,11,2]),true);
});
