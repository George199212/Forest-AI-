'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../assets/vmd-production.js'),'utf8');
const original=JSON.parse(fs.readFileSync(path.join(__dirname,'../lvm_3_sectors.geojson'),'utf8'));
// Synthetic multi-compartment unit attributes, reusing real geometry shapes. Never production source evidence.
const features=original.features.map((f,i)=>({...f,id:'VMD:nodala2651:'+f.properties.objectid,properties:{...f.properties,kadastrs:'40940020002',external_id:'VMD:nodala2651:'+f.properties.objectid,source:'VMD_OPEN_DATA',area_ha:f.properties.nog_plat,intersection_ratio:i===2?.75:1,fully_inside:i!==2,import_status:'READY',importable:true,geometry_valid:true,cadastral_validation:{registration_allowed:true},cadastral_association:{status:'verified_source_attribute',source_designation:'40940020002'}}}));
class Node{constructor(){this.style={};this.children=[];this.value='';this.textContent='';this.hidden=true;}append(...n){this.children.push(...n);}replaceChildren(...n){this.children=n;}setAttribute(k,v){this[k]=v;}removeAttribute(k){delete this[k];}focus(){this.focused=true;}scrollIntoView(){this.scrolled=true;}showModal(){this.open=true;}close(){this.open=false;}remove(){this.removed=true;}}
function bounds(points){const x=points.map(p=>p[0]),y=points.map(p=>p[1]);return {isValid:()=>!!points.length,getWest:()=>Math.min(...x),getEast:()=>Math.max(...x),getSouth:()=>Math.min(...y),getNorth:()=>Math.max(...y),intersects:()=>true};}
function setup(fail=false,paginate=false){
 const nodes=new Map(),requests=[],groups=[],events={},imported=new Set();let consent=false,cache=0,identityFailure=false,searchFailure=false,nationalMode=false,nationalState='VMD_MATCHES_FOUND';
 const document={body:new Node(),createElement:()=>new Node(),getElementById(id){if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);}};
 document.getElementById('vmd-sector-name').value='Testa sektors';document.getElementById('vmd-mode').value='intersects';document.getElementById('vmd-overlap').value='0';
 const map={panes:{},layers:new Set(),fits:[],fitOptions:[],area:bounds([[24.414,56.676],[24.418,56.679]]),getPane(k){return this.panes[k];},createPane(k){return this.panes[k]={style:{}};},getBounds(){return this.area;},fitBounds(b,options){this.fits.push(b);this.fitOptions.push(options);},hasLayer(l){return this.layers.has(l);},removeLayer(l){this.layers.delete(l);},on(k,f){events[k]=f;},off(k){delete events[k];}};const base={osm:true};map.layers.add(base);
 const L={map:()=>({...map,layers:new Set(),remove(){},invalidateSize(){}}),control:{layers(base,overlays){return {overlays,addTo(){return this;},remove(){}};}},
  geoJSON(data,options={}){const list=data.type==='FeatureCollection'?data.features:[data.type==='Feature'?data:{type:'Feature',geometry:data,properties:{}}];
   const group={options,children:[],addTo(m){m.layers.add(this);return this;},getBounds:()=>bounds(list.flatMap(f=>f.geometry.coordinates[0]))};
   list.forEach(f=>{const layer={feature:f,handlers:{},bindPopup(p){this.popup=p;this.popupState={options:{autoPan:true}};},getPopup(){return this.popupState;},on(k,fn){this.handlers[k]=fn;},openPopup(){this.open=true;this.autoPanDuringOpen=this.popupState?.options.autoPan;},setStyle(v){this.style=v;},getBounds:()=>bounds(f.geometry.coordinates[0])};group.children.push(layer);options.onEachFeature?.(f,layer);});groups.push(group);return group;},
  polyline(points){return {addTo(m){m.layers.add(this);return this;}};},
  rectangle(points){const [a,b]=points;return {toGeoJSON:()=>({type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[[[a.lng,a.lat],[b.lng,a.lat],[b.lng,b.lat],[a.lng,b.lat],[a.lng,a.lat]]]}})};},
  polygon(points){return {toGeoJSON:()=>({type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[points.map(p=>[p.lng,p.lat]).concat([[points[0].lng,points[0].lat]])]}})};}
 };
 const window={confirm:()=>consent};
 const ctx=vm.createContext({window,L,document,AbortController,URLSearchParams,setTimeout,clearTimeout,console:{error(){}},clearCache(){cache++;},mapLoaded:true,fetch:async(url,options)=>{
  requests.push({url,options});let data,status=200;
  if(url.endsWith('/dataset')){if(fail){status=503;data={detail:'Catalogue unavailable'};}else data={feature_count:513776,source_layers:Array(5).fill({}),dataset_version:'a'.repeat(64),extent:[22.44,56.25,25.55,57.41],repaired:355,failed:0,coverage:'Supplied Centra archive coverage',...(nationalMode?{regions_covered:5,municipalities_covered:42,parcel_count:3}:{})};}
  else if(url.endsWith('/registration-context')&&identityFailure){status=503;data={detail:'Account unavailable'};}
  else if(url.endsWith('/registration-context'))data={organization_id:1,organization_name:'Testa organizācija',user_id:null,responsible_first_name:'Testa',responsible_last_name:'Persona',profile_notice:'Nav individuāla profila'};
  else if(url.endsWith('/territories'))data=[];
  else if(url.endsWith('/territory-preview')){const v=JSON.parse(options.body).geometry;data={type:'Feature',geometry:v.type==='Feature'?v.geometry:v,properties:{area_ha:3.07}};}
  else if(url.includes('/cadastre?')&&searchFailure){status=503;data={detail:'Source unavailable'};}
  else if(url.includes('/cadastre?'))data={cadastral_verification:{status:'verified_source_attribute',verified_count:3,unverified_count:0},type:'FeatureCollection',dataset_version:'a'.repeat(64),features:!url.includes('kadastrs=40940020002')?[]:paginate?[features[url.includes('offset=1')?1:0]]:features,summary:{found:!url.includes('kadastrs=40940020002')?0:3,returned:!url.includes('kadastrs=40940020002')?0:paginate?1:3,total_compartment_area_ha:1.66,territory_area_ha:3.07,fully_inside:2,boundary_intersections:1,offset:paginate&&url.includes('offset=1')?1:0,limit:paginate?1:100,has_more:paginate}};
  else if(url.endsWith('/select-matching'))data={type:'FeatureCollection',dataset_version:'a'.repeat(64),features,selected_count:3,excluded_count:0,summary:{found:3,offset:0,limit:100}};
  else if(url.endsWith('/import-selected')){const body=JSON.parse(options.body);if(!body.dry_run)body.feature_ids.forEach(id=>imported.add(id));data={sector_name:body.sector_name,registration_identity:{organization_id:1,organization_name:'Testa organizācija'},responsible_person:{first_name:body.responsible_first_name,last_name:body.responsible_last_name},target_client:{id:body.client_id||'unit-account',name:body.client_name||'',account:'unit-account'},total_area_ha:.61,valid_geometry_count:body.feature_ids.length,requested:body.feature_ids.length,dry_run:body.dry_run,would_import:body.dry_run?body.feature_ids.length:0,imported:body.dry_run?0:body.feature_ids.length,already_exists:0,failed:0,results:body.feature_ids.map(id=>({external_id:id,kadastrs:'40940020002',kvart:'1',nog:'1',area_ha:.18,geometry_valid:true,status:body.dry_run?'ready':'imported',id:31,name:'VMD real source sector'}))};}
  else throw Error('Unexpected API / any live geoserver request prohibited');
  if(nationalMode&&url.includes('/cadastre?')){data.state=nationalState;data.search_message=nationalState==='SOURCE_ERROR'?'Datu avota kļūda':'Valsts avoti pārbaudīti';data.cadastral_validation={registration_allowed:true,land_unit_exists:true,source_designation:'40940020002',land_unit_area_ha:1,land_unit_geometry:features[0].geometry};data.spatial_candidates=[{...features[1],id:'unit:spatial',properties:{...features[1].properties,kadastrs:'40440040167',importable:false,cadastral_validation:{registration_allowed:false,status:'spatial_candidate_only',overlap_percent:50}}}];data.spatial_summary={found:1,returned:1,offset:0,limit:100,has_more:false};if(nationalState==='SOURCE_ERROR'){data.features=[];data.spatial_candidates=[];data.spatial_summary.found=0;data.summary={...data.summary,found:0,returned:0};}}
  return {ok:status===200,status,headers:{get:()=> 'application/json'},json:async()=>JSON.parse(JSON.stringify(data))};
 }});vm.runInContext(fs.readFileSync(path.join(__dirname,'../assets/lvm-geodata.js'),'utf8'),ctx);vm.runInContext(script,ctx);
 return {api:window.VmdLocalDataset,map,base,nodes,document,requests,groups,events,imported,consent(v){consent=v;},cache:()=>cache,ctx,setFailure(v){fail=v;},failIdentity(v){identityFailure=v;},failSearch(v){searchFailure=v;},national(v=true){nationalMode=v;},nationalState(v){nationalState=v;}};
}

test('initial page loads catalogue metadata, no national geometry or territory requests',async()=>{
 const e=setup();await e.api.attach(e.map);assert.equal(e.groups.length,0);assert.equal(e.nodes.get('vmd-local-count').textContent,'513,776');assert.equal(e.nodes.get('lvm-import').disabled,true);assert(e.requests.every(r=>!r.url.includes('territor')&&!r.url.includes('compartments')));
});
test('only eleven ASCII digits can start a search',async()=>{
 const e=setup();await e.api.attach(e.map);const before=e.requests.length;
 for(const value of ['4094','409400200020','4094 002 0002','4094002000X','１２３４５６７８９０１']){e.document.getElementById('vmd-kadastrs').value=value;await e.api.find();assert.equal(e.requests.length,before);}
 assert.match(e.nodes.get('lvm-preview-state').textContent,/11 ciparu/);
});
test('exact search renders source geometries and automatically fits their bounds',async()=>{
 const e=setup();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();assert.match(e.requests.at(-1).url,/\/cadastre\?kadastrs=40940020002/);assert.equal(e.groups[0].children.length,3);assert(e.map.fits.length>0);assert.equal(e.nodes.get('lvm-feature-rows').children.length,3);
});
const sel=e=>[...e.api.selectedIds];
const pageLayers=e=>e.groups.filter(g=>g.options.pane==='vmdCompartments').at(-1).children;
const popupButton=layer=>layer.popup.children.find(n=>n.className==='btn vmd-popup-action');
const rowInput=(e,i)=>e.nodes.get('lvm-feature-rows').children[i].children[0].children[0];
test('polygon click only inspects; popup button selects and deselects; row click zooms without popup pan',async()=>{
 const e=setup();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();const layer=e.groups[0].children[0];
 layer.handlers.click();assert.deepEqual(sel(e),[]);assert.equal(e.nodes.get('lvm-feature-rows').children[0]['data-active'],'true');
 assert.equal(popupButton(layer).textContent,'Atlasīt');popupButton(layer).onclick();assert.deepEqual(sel(e),[layer.feature.id]);assert.equal(layer.style.color,'#d4a017');assert.equal(popupButton(layer).textContent,'Noņemt no atlases');assert.equal(rowInput(e,0).checked,true);
 layer.handlers.click();assert.deepEqual(sel(e),[layer.feature.id],'second polygon click does not deselect');
 popupButton(layer).onclick();assert.deepEqual(sel(e),[]);
 e.nodes.get('lvm-feature-rows').children[0].onclick();assert.equal(e.map.fitOptions.at(-1).animate,false);assert.equal(layer.autoPanDuringOpen,false);assert.deepEqual(sel(e),[]);
 assert.equal(e.document.getElementById('lvm-map').scrolled,undefined,'row click never scrolls the page to the map');
});
test('invariant: one action changes exactly one ID; clicks on rows and polygons change none',async()=>{
 const e=setup();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();
 const ids=e.groups[0].children.map(l=>l.feature.id),diff=(a,b)=>[...a.filter(x=>!b.includes(x)),...b.filter(x=>!a.includes(x))];
 e.document.getElementById('vmd-responsible-first-name').value='Anna';e.document.getElementById('vmd-sector-name').value='Mežs A';
 const body=e.nodes.get('lvm-feature-rows'),rowsBefore=[...body.children];
 for(const [i,action] of [[0,()=>{rowInput(e,0).checked=true;rowInput(e,0).onchange();}],[1,()=>popupButton(e.groups[0].children[1]).onclick()],[0,()=>{rowInput(e,0).checked=false;rowInput(e,0).onchange();}],[2,()=>{rowInput(e,2).checked=true;rowInput(e,2).onchange();}]]){
  const before=sel(e);action();assert.deepEqual(diff(before,sel(e)),[ids[i]]);}
 for(const action of [()=>e.groups[0].children.forEach(l=>l.handlers.click()),()=>body.children.forEach(tr=>tr.onclick()),()=>body.children.forEach(tr=>tr.onkeydown({target:tr,key:'Enter',preventDefault(){}}))]){
  const before=sel(e);action();assert.deepEqual(sel(e),before);}
 assert.deepEqual(body.children,rowsBefore,'toggling never rebuilds the table body (scroll and focus survive)');
 assert.equal(e.document.getElementById('vmd-responsible-first-name').value,'Anna');assert.equal(e.document.getElementById('vmd-sector-name').value,'Mežs A');
});
test('off-page selection: clicking the overlay polygon keeps it; only its popup button removes exactly that ID',async()=>{
 const e=setup(false,true);await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();popupButton(pageLayers(e)[0]).onclick();const first=sel(e)[0];
 await e.api.page(1);popupButton(pageLayers(e)[0]).onclick();assert.equal(sel(e).length,2);
 const overlay=e.groups.find(g=>g.children.some(l=>l.feature.id===first)&&g.options.style?.color==='#d4a017');const layer=overlay.children.find(l=>l.feature.id===first);
 assert.equal(layer.handlers.click,undefined,'no click handler that could change selection');
 const remove=layer.popup.children.find(n=>n.className==='btn vmd-popup-action');assert.equal(remove.textContent,'Noņemt no atlases');remove.onclick();
 assert.equal(sel(e).length,1);assert(!sel(e).includes(first));
});
test('non-importable compartments are never selected by any control',async()=>{
 const saved=features[1].properties.cadastral_validation;features[1].properties.cadastral_validation={status:'boundary_review_required',registration_allowed:false,overlap_percent:99.9999};
 try{const e=setup();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();const layer=e.groups[0].children[1];
  assert.equal(rowInput(e,1).disabled,true);assert.equal(popupButton(layer).disabled,true);assert.match(layer.popup.children.find(n=>n.tagName===undefined&&/Nav reģistrējams/.test(n.textContent))?.textContent||'',/Robežu neatbilstība/);
  rowInput(e,1).checked=true;rowInput(e,1).onchange();popupButton(layer).onclick();assert.deepEqual(sel(e),[]);
  e.api.selectAll();assert.equal(sel(e).length,2);assert(!sel(e).includes(layer.feature.id));}
 finally{features[1].properties.cadastral_validation=saved;}
});
test('selection persists through pagination within the same designation',async()=>{
 const e=setup(false,true);await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();e.api.selectAll();await e.api.page(1);assert.match(e.nodes.get('vmd-selected-summary').textContent,/Atlasīti: 1/);e.api.selectAll();assert.match(e.nodes.get('vmd-selected-summary').textContent,/Atlasīti: 2/);assert.equal((await e.api.importSelected(true)).requested,2);
});
test('new designation clears the old selection; no match is explicit',async()=>{
 const e=setup();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();e.api.selectAll();e.document.getElementById('vmd-kadastrs').value='99999999999';await e.api.find();assert.equal(e.nodes.get('lvm-feature-rows').children.length,0);assert.match(e.nodes.get('vmd-selected-summary').textContent,/Atlasīti: 0/);assert.match(e.nodes.get('vmd-empty').textContent,/nav atrasti/);
});
test('preview is required and confirmation retains reviewed identifiers and responsible contact',async()=>{
 const e=setup();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();popupButton(e.groups[0].children[0]).onclick();e.document.getElementById('vmd-responsible-first-name').value='Pārbaudīts';await e.api.importSelected();assert.equal(e.imported.size,0);const dialog=e.document.body.children.at(-1);assert(dialog.open);e.document.getElementById('vmd-responsible-first-name').value='Mainīts';e.api.clearSelection();await dialog.children.at(-1).children.at(-1).onclick();assert.equal(e.imported.size,1);const body=JSON.parse(e.requests.at(-1).options.body);assert.equal(body.responsible_first_name,'Pārbaudīts');assert.equal(body.feature_ids.length,1);assert.equal(e.cache(),1);
});
test('simplified controller exposes no map, prefix or territory search actions',()=>{
 const e=setup();for(const name of ['setMode','findPartial','draw','upload','selectScope'])assert.equal(e.api[name],undefined);
});

test('unverified cadastral relationship cannot be selected or registered',async()=>{
 const saved=features.map(f=>f.properties.cadastral_validation);features.forEach(f=>f.properties.cadastral_validation={status:'unverified',registration_allowed:false});
 try{const e=setup();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();e.api.selectAll();e.groups[0].children[0].handlers.click();popupButton(e.groups[0].children[0]).onclick();assert.match(e.nodes.get('vmd-selected-summary').textContent,/Atlasīti: 0/);assert.equal(e.nodes.get('lvm-import').disabled,true);assert.equal(await e.api.importSelected(),undefined);}
 finally{features.forEach((f,i)=>f.properties.cadastral_validation=saved[i]);}
});

test('all three steps navigate without losing results or selection and guard invalid progression',async()=>{
 const e=setup();await e.api.attach(e.map);e.api.goStep(2);assert.equal(e.nodes.get('vmd-step-1')['aria-current'],'step');assert(e.nodes.get('vmd-go-3').disabled);
 e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();const count=e.requests.length;popupButton(e.groups[0].children[0]).onclick();
 e.api.goStep(1);assert.equal(e.nodes.get('vmd-step-1')['aria-current'],'step');assert.equal(e.nodes.get('lvm-feature-rows').children.length,3);
 e.api.goStep(2);assert.equal(e.nodes.get('vmd-step-2')['aria-current'],'step');assert.match(e.nodes.get('vmd-selected-summary').textContent,/Atlasīti: 1/);assert.equal(e.requests.length,count);
 await e.api.goStep(3);assert.equal(e.nodes.get('vmd-step-3')['aria-current'],'step');const dialog=e.document.body.children.at(-1);assert(dialog.open);dialog.children.at(-1).children[0].onclick();assert.equal(e.nodes.get('vmd-step-2')['aria-current'],'step');assert.match(e.nodes.get('vmd-selected-summary').textContent,/Atlasīti: 1/);
 assert.equal(e.api.zoomSelected,undefined);
});

test('required sector name prevents preview; confirmation uses the reviewed name',async()=>{
 const e=setup();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();e.api.selectAll();e.document.getElementById('vmd-sector-name').value='  ';const before=e.requests.length;await e.api.goStep(3);assert.equal(e.requests.length,before);assert.match(e.nodes.get('lvm-preview-state').textContent,/sektora nosaukumu/);
 e.document.getElementById('vmd-sector-name').value='Meža sektors';await e.api.goStep(3);e.document.getElementById('vmd-sector-name').value='Mainīts';const dialog=e.document.body.children.at(-1);await dialog.children.at(-1).children.at(-1).onclick();assert.equal(JSON.parse(e.requests.at(-1).options.body).sector_name,'Meža sektors');
});

test('initial catalogue failure resolves to error and a working retry',async()=>{
 const e=setup(true);await e.api.attach(e.map);assert(e.nodes.get('vmd-find').disabled);assert.equal(e.nodes.get('vmd-retry').hidden,false);e.setFailure(false);await e.api.retry();assert.equal(e.nodes.get('vmd-find').disabled,false);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();assert.equal(e.nodes.get('lvm-feature-rows').children.length,3);
});

test('account loading failure does not disable cadastral discovery and can recover',async()=>{
 const e=setup();e.failIdentity(true);await e.api.attach(e.map);assert.equal(e.nodes.get('vmd-find').disabled,false);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();e.api.selectAll();assert.equal(e.nodes.get('lvm-import').disabled,true);e.failIdentity(false);await e.api.retry();assert.equal(e.nodes.get('lvm-import').disabled,false);
});

test('failed query blocks stale selection; retry restores the exact query',async()=>{
 const e=setup();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();e.api.selectAll();e.failSearch(true);await e.api.find();assert(e.nodes.get('lvm-import').disabled);assert.equal(e.nodes.get('vmd-retry').hidden,false);e.failSearch(false);await e.api.retry();assert.match(e.requests.at(-1).url,/kadastrs=40940020002/);assert.equal(e.nodes.get('lvm-import').disabled,false);
 e.document.getElementById('vmd-kadastrs').value='01000950031';e.api.inputChanged();assert(e.nodes.get('lvm-import').disabled);
});

test('national results fit the cadastral polygon and keep spatial candidates out of selection',async()=>{
 const e=setup();e.national();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();assert.equal(e.nodes.get('vmd-spatial-rows').children.length,1);assert.equal(e.nodes.get('vmd-spatial-review').hidden,false);assert.match(e.nodes.get('vmd-results-summary').textContent,/VZD zemes vienība: 40940020002/);assert(e.map.fits.length);
 e.api.selectAll();assert.match(e.nodes.get('vmd-selected-summary').textContent,/Atlasīti: 3/);await e.api.importSelected(true);const body=JSON.parse(e.requests.at(-1).options.body);assert.equal(body.cadastral_designation,'40940020002');assert.equal(body.feature_ids.length,3);assert(!body.feature_ids.includes('unit:spatial'));
});

test('explicit source error clears stale selection and offers a retry',async()=>{
 const e=setup();e.national();await e.api.attach(e.map);e.document.getElementById('vmd-kadastrs').value='40940020002';await e.api.find();e.api.selectAll();e.nationalState('SOURCE_ERROR');await e.api.find();assert.match(e.nodes.get('vmd-selected-summary').textContent,/Atlasīti: 0/);assert.equal(e.nodes.get('lvm-import').disabled,true);assert.equal(e.nodes.get('vmd-retry').hidden,false);assert.match(e.nodes.get('lvm-preview-state').textContent,/Datu avota kļūda/);
});
