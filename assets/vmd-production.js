/* Exact cadastral registration over the existing VMD catalogue and sector API. */
(function(global){
'use strict';
const s={map:null,metadata:null,identity:null,version:null,active:false,entries:new Map(),selected:new Map(),layer:null,parcelLayer:null,spatialLayer:null,spatialSummary:null,selectionLayer:null,control:null,summary:null,cadastre:null,busy:false,controller:null,epoch:0,imported:0,step:1,review:null,initializing:null,lastFailed:null};
const style={color:'#4b9d54',weight:2,fillColor:'#7ab83c',fillOpacity:.15};
function dom(id){return document.getElementById(id);}
function el(tag,text,parent){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(parent)parent.append(n);return n;}
function message(value){dom('lvm-preview-state').textContent=value;}
function progress(step){[1,2,3].forEach(n=>{const node=dom('vmd-step-'+n);if(n===step)node.setAttribute('aria-current','step');else node.removeAttribute?.('aria-current');});}
async function request(path,body,signal){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),35000),abort=()=>controller.abort();signal?.addEventListener('abort',abort,{once:true});
 try{
  const r=await fetch('/api/geodata/vmd/'+path,{credentials:'same-origin',cache:'no-store',signal:controller.signal,...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
  const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Ģeodatu pieprasījums neizdevās.');return data;
 }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}
function sectorNameError(value){const name=typeof value==='string'?value.trim():'';const chars=Array.from(name);return !name||chars.length>120||chars.some(ch=>ch.charCodeAt(0)<32||ch==='/'||ch==='\\')?'Norādiet sektora nosaukumu (1–120 rakstzīmes, bez slīpsvītrām un vadības rakstzīmēm)':'';}
/* Why "Reģistrēt sektorus" is disabled — shown inline next to the button. */
function blockers(current){const r=[];
 if(!s.identity)r.push('Reģistrācijas konteksts nav pieejams (organizācijas konts) — izmantojiet “Mēģināt vēlreiz”.');
 if(s.cadastre&&!current)r.push('Meklēšana ir mainīta — atkārtojiet “Atrast nogabalus”.');
 if(!s.selected.size)r.push('Atlasiet vismaz vienu nogabalu.');
 const nameError=sectorNameError(dom('vmd-sector-name').value);if(nameError)r.push(nameError);
 if(!dom('vmd-responsible-first-name').value.trim()||!dom('vmd-responsible-last-name').value.trim())r.push('Ievadiet atbildīgās personas vārdu un uzvārdu.');
 return r;}
/* Missing area is never shown as 0. */
function haText(values){if(!values.length)return '0.00 ha';return values.some(v=>v===null||v===undefined||v===''||!Number.isFinite(Number(v)))?'platība nav zināma':values.reduce((a,v)=>a+Number(v),0).toFixed(2)+' ha';}
function buttons(){
 const current=dom('vmd-kadastrs').value.trim()===s.cadastre&&!s.lastFailed,reasons=blockers(current),register=dom('lvm-import');dom('vmd-find').disabled=s.busy||!s.metadata;
 register.disabled=s.busy||!!s.review||reasons.length>0;register.textContent=s.busy?'Notiek pārbaude…':'Reģistrēt sektorus ('+s.selected.size+')';
 dom('vmd-submit-reason').textContent=s.busy||s.review?'':reasons.join(' · ');
 dom('vmd-cancel-search').hidden=!s.controller;dom('vmd-prev').disabled=s.busy||!s.summary?.offset;dom('vmd-next').disabled=s.busy||!s.summary?.has_more;
 dom('vmd-selected-summary').textContent='Atlasīti: '+plural(s.selected.size,'nogabals','nogabali')+' · '+haText(Array.from(s.selected.values()).map(f=>f.properties.area_ha));
 dom('vmd-page-label').textContent=s.summary?'Lapa '+(Math.floor(s.summary.offset/s.summary.limit)+1)+' no '+Math.max(1,Math.ceil(s.summary.found/s.summary.limit)):'—';
 dom('vmd-empty').hidden=!!s.entries.size;dom('vmd-empty').textContent=s.summary?'Šim kadastra apzīmējumam nogabali nav atrasti.':'Ievadiet 11 ciparu kadastra apzīmējumu un atrodiet nogabalus.';
 dom('vmd-go-1').disabled=s.busy;dom('vmd-go-2').disabled=s.busy||!s.entries.size;dom('vmd-go-3').disabled=s.busy||!!s.review||reasons.length>0;dom('vmd-back').hidden=s.step!==2;
 syncMaster();progress(s.step);dom('vmd-step-help').textContent=s.step===1?'1. Ievadiet precīzu kadastra apzīmējumu. Iepriekšējie rezultāti un atlase saglabājas.':s.step===2?'2. Pārbaudiet avota identifikatorus, platību un robežas; atlasiet reģistrējamos nogabalus.':'3. Pārbaudiet nosaukumu, atbildīgo personu un reģistrācijas kopsavilkumu.';
}
function associationLabel(p){if(p.cadastral_validation?.status==='display_review_required')return 'Attēlojuma ģeometrijai nepieciešama pārbaude';if(p.cadastral_validation?.status==='geometry_invalid')return 'Avota ģeometrija nav derīga';if(p.cadastral_validation?.status==='source_conflict')return 'Avota identitātes konflikts';if(p.cadastral_validation?.status==='boundary_review_required')return 'Robežu neatbilstība · '+p.cadastral_validation.overlap_percent.toFixed(4)+'% sakritība';if(p.cadastral_validation?.status==='verified')return 'VMD + VZD pārbaudīts';if(!p.cadastral_validation?.registration_allowed)return 'Kadastra dati nav pārbaudīti · '+(p.cadastral_association?.status==='verified_source_attribute'?'VMD atribūts sakrīt':'VMD atribūts nav pārbaudīts');return p.cadastral_association?.status==='verified_source_attribute'?'Pārbaudīts VMD atribūts':p.cadastral_association?.classification==='derived'?'Atvasināta saistība':'Saistība nav pārbaudīta';}
function featureStyle(feature){return {...style,...(feature.properties?.cadastral_validation?.registration_allowed?{}:{color:'#e99c38',fillColor:'#e99c38'})};}
/* Master checkbox: scope = importable rows of the CURRENT page; non-importable rows are never touched.
   headers() rebuilds the thead, so s.master is reassigned on every rebuild and syncMaster() reads it fresh. */
function headers(){const head=dom('lvm-feature-head');head.replaceChildren();const tr=el('tr',undefined,head);const label=el('label',undefined,el('th',undefined,tr));label.className='vmd-master';const master=el('input',undefined,label);master.type='checkbox';master.id='vmd-master';master.setAttribute('aria-label','Atlasīt visus reģistrējamos nogabalus šajā lapā');master.onchange=()=>{if(master.checked)selectAll();else clearPage();};el('span','Atlasīt',label);s.master=master;syncMaster();['Avota kadastra apzīmējums','Kvartāls','Nogabals','VMD nogabala ID','Platība (ha)','Kadastra saistība','Datu avots','Stāvoklis'].forEach(label=>el('th',label,tr));}
/* Selection changes ONLY through explicit controls: row checkbox, popup button, master checkbox,
   "Noņemt atlasi". Clicking a polygon or a row only inspects it (highlight + popup / show on map). */
// Registration outcome labels (this page only; the backend status ALREADY IMPORTED means the source is already a sector).
const OUTCOME={REGISTERED:'Reģistrēts',ALREADY_REGISTERED:'Jau reģistrēts','ALREADY IMPORTED':'Jau reģistrēts'};
function plural(n,one,many){return n%10===1&&n%100!==11?n+' '+one:n+' '+many;}
function statusText(p){return (OUTCOME[p.import_status]||lvmStatus(p.import_status))+(p.sector?' → '+p.sector.name:'');}
function rows(){
 const body=dom('lvm-feature-rows');body.replaceChildren();s.rowNodes=new Map();
 s.entries.forEach((entry,id)=>{const p=entry.feature.properties,tr=el('tr',undefined,body);tr.setAttribute('data-feature-id',id);tr.tabIndex=0;
  const input=el('input',undefined,el('td',undefined,tr));input.type='checkbox';input.setAttribute('aria-label','Atlasīt '+id);input.onclick=event=>event.stopPropagation();input.onchange=()=>toggle(id,input.checked);
  [p.cadastral_association?.source_designation||'—',p.kvart,p.nog,id,area(p),associationLabel(p),'VMD · '+(p.source_layer||'VMD')].forEach(value=>el('td',value??'—',tr));const status=el('td','',tr);
  tr.onclick=()=>{highlight(id,false);focus(id,true);};tr.onkeydown=event=>{if(event.target===tr&&(event.key==='Enter'||event.key===' ')){event.preventDefault();highlight(id,false);focus(id,true);}};
  s.rowNodes.set(id,{tr,input,status});
 });
 syncRows();
}
function area(p){const v=p.area_ha;return v===null||v===undefined||v===''||!Number.isFinite(Number(v))?'—':Number(v).toFixed(2);}
function syncRows(){
 s.rowNodes?.forEach((n,id)=>{const entry=s.entries.get(id);if(!entry)return;const p=entry.feature.properties,on=s.selected.has(id);
  n.input.checked=on;n.input.disabled=s.busy||!p.importable;n.tr.setAttribute('data-selected',String(on));n.status.textContent=statusText(p);});
 s.entries.forEach((entry,id)=>syncPopup(id));
}
function syncPopup(id){
 const entry=s.entries.get(id);if(!entry?.action)return;const p=entry.feature.properties,on=s.selected.has(id);
 entry.action.textContent=on?'Noņemt no atlases':'Atlasīt';entry.action.disabled=s.busy||(!on&&!p.importable);
 entry.reason.textContent=p.importable?'':'Nav reģistrējams: '+(p.sector?statusText(p):associationLabel(p)+' · '+(OUTCOME[p.import_status]||lvmStatus(p.import_status)));entry.reason.hidden=!!p.importable;
}
function highlight(id,scrollTable){
 s.activeId=id;s.rowNodes?.forEach((n,key)=>n.tr.setAttribute('data-active',String(key===id)));
 const tr=s.rowNodes?.get(id)?.tr,box=tr?.closest?.('.vmd-table-scroll');
 if(scrollTable&&box&&typeof tr.offsetTop==='number'){const top=tr.offsetTop,h=tr.offsetHeight||0;if(top<box.scrollTop+h||top+h>box.scrollTop+box.clientHeight)box.scrollTop=Math.max(0,top-box.clientHeight/2);}
}
function paint(){s.entries.forEach((entry,id)=>entry.layer.setStyle({...featureStyle(entry.feature),...(s.selected.has(id)?{color:'#d4a017',weight:3,fillOpacity:.3}:{})}));}
function selectionOverlay(){
 if(s.selectionLayer)s.map.removeLayer(s.selectionLayer);s.selectionLayer=null;
 const features=Array.from(s.selected.values()).filter(f=>!s.entries.has(f.id));
 // Off-page selection: clicking only opens the popup; removal needs the explicit button.
 if(features.length)s.selectionLayer=L.geoJSON({type:'FeatureCollection',features},{style:{color:'#d4a017',weight:3,fillOpacity:.3},onEachFeature:(f,layer)=>{const box=el('div');el('strong','Atlasīts citā lapā',box);el('div','VMD nogabala ID: '+f.id,box);const remove=el('button','Noņemt no atlases',box);remove.type='button';remove.className='btn vmd-popup-action';remove.onclick=event=>{event?.stopPropagation?.();unselectOffPage(f.id);};layer.bindPopup(box);}}).addTo(s.map);
}
function unselectOffPage(id){if(s.busy||s.entries.has(id)||!s.selected.has(id))return;s.selected.delete(id);s.map.closePopup?.();selectionOverlay();buttons();}
function toggle(id,selected){
 const entry=s.entries.get(id);if(s.busy||!entry)return;
 if(selected){if(!entry.feature.properties.importable||s.selected.has(id))return syncRows();if(s.selected.size>=100){message('Vienā reizē var reģistrēt līdz 100 nogabaliem.');return syncRows();}s.selected.set(id,entry.feature);}
 else{if(!s.selected.has(id))return syncRows();s.selected.delete(id);}
 // Exactly one ID changed: restyle, sync rows/popups in place (no tbody rebuild), keep scroll and form fields.
 paint();syncRows();buttons();
}
function focus(id,zoom){
 const entry=s.entries.get(id);if(!entry)return;
 if(zoom){s.map.closePopup?.();s.map.fitBounds(entry.layer.getBounds(),{padding:[35,35],maxZoom:18,animate:false});}
 const popup=entry.layer.getPopup?.(),autoPan=popup?.options.autoPan;if(zoom&&popup)popup.options.autoPan=false;entry.layer.openPopup();if(zoom&&popup)popup.options.autoPan=autoPan;
}
function render(result,designation){
 if(result.type!=='FeatureCollection'||!Array.isArray(result.features))throw Error('Nederīga VMD atbilde.');
 if(result.features.some(f=>f.properties?.kadastrs!==designation))throw Error('VMD atbildes kadastra apzīmējums neatbilst precīzajam pieprasījumam.');
 if(s.cadastre!==designation||s.version!==result.dataset_version||(!result.state&&result.cadastral_verification?.status!=='verified_source_attribute')||['SOURCE_ERROR','DATASET_NOT_READY'].includes(result.state))s.selected.clear();
 s.cadastre=designation;s.version=result.dataset_version;s.summary=result.summary;s.imported=0;s.step=result.summary.found?2:1;
 if(s.parcelLayer){s.map.removeLayer(s.parcelLayer);s.parcelLayer=null;}if(result.cadastral_validation?.land_unit_geometry){s.parcelLayer=L.geoJSON(result.cadastral_validation.land_unit_geometry,{style:{color:'#49c9ef',weight:3,fill:false,dashArray:'7 5'}}).addTo(s.map);s.parcelLayer.bindTooltip?.('VZD zemes vienības robeža');}
 if(s.layer)s.map.removeLayer(s.layer);if(s.control)s.control.remove();s.entries.clear();
 const pane=s.map.getPane('vmdCompartments')||s.map.createPane('vmdCompartments');pane.style.zIndex='350';
 s.layer=L.geoJSON(result,{pane:'vmdCompartments',style:featureStyle,onEachFeature:(feature,layer)=>{
  const p=feature.properties,id=feature.id;if(p.cadastral_association?.status!=='verified_source_attribute'||!p.cadastral_validation?.registration_allowed)p.importable=false;s.entries.set(id,{feature,layer});const popup=el('div');el('strong','Meža nogabals',popup);
  [['Kadastra apzīmējums',p.kadastrs],['Kvartāls',p.kvart],['Nogabals',p.nog],['Platība',Number(p.area_ha||0).toFixed(2)+' ha'],['Datu avots','VMD · '+p.source_layer],['Avota ID',id],['Kadastra saistība',associationLabel(p)],['Ģeometrija',p.geometry_valid?'Derīga':'Nav apstiprināta']].forEach(([key,value])=>el('div',key+': '+value,popup));
  if(p.geometry_repaired)el('p','Normalizējot labota ģeometrija — pārbaudiet pirms reģistrācijas.',popup);
  const reason=el('p','',popup),action=el('button','Atlasīt',popup);action.type='button';action.className='btn vmd-popup-action';action.onclick=event=>{event?.stopPropagation?.();toggle(id,!s.selected.has(id));};s.entries.get(id).action=action;s.entries.get(id).reason=reason;
  // Polygon click = inspect only: Leaflet opens the popup; selection changes only via the popup button.
  layer.bindTooltip?.(el('span','K'+p.kvart+' · N'+p.nog));layer.bindPopup(popup,{maxHeight:240});layer.on('click',()=>highlight(id,true));
 }}).addTo(s.map);
 s.control=L.control.layers(null,{'VMD meža nogabali':s.layer},{collapsed:false}).addTo(s.map);
 paint();selectionOverlay();rows();dom('vmd-selection-actions').hidden=false;
 renderSpatial(result);
 const bounds=s.summary.bounds;
 if(result.state&&result.cadastral_validation?.land_unit_geometry)s.map.fitBounds(L.geoJSON(result.cadastral_validation.land_unit_geometry).getBounds(),{padding:[30,30],maxZoom:18,animate:false});else if(bounds)s.map.fitBounds([[bounds[1],bounds[0]],[bounds[3],bounds[2]]],{padding:[30,30],maxZoom:17,animate:false});else if(s.entries.size)s.map.fitBounds(s.layer.getBounds(),{padding:[30,30],maxZoom:17,animate:false});
 dom('vmd-results-summary').textContent='Pieprasītais apzīmējums: '+designation+' · Atrasti: '+s.summary.found+' nogabali · Šajā lapā: '+s.summary.returned+' · Kopējā platība: '+s.summary.total_compartment_area_ha.toFixed(2)+' ha';
 if(result.cadastral_verification)dom('vmd-results-summary').textContent+=' · VMD atribūts pārbaudīts: '+result.cadastral_verification.verified_count+' · Nepārbaudīti: '+result.cadastral_verification.unverified_count;
 if(result.state){const v=result.cadastral_validation;if(v?.land_unit_exists)dom('vmd-results-summary').textContent+=' · VZD zemes vienība: '+designation+' · Platība: '+Number(v.land_unit_area_ha||0).toFixed(4)+' ha';dom('vmd-results-summary').textContent+=' · Pārbaudīti: '+(s.summary.verified_matches||0)+' · Telpiski kandidāti: '+(s.summary.spatial_candidates||0);message(result.search_message||'');buttons();return;}
 if(!s.summary.found&&result.search_message){message(result.search_message+(result.cadastral_validation?.status==='unverified'?' Kadastra dati nav pārbaudīti.':''));buttons();return;}
 if(result.cadastral_validation&&!result.cadastral_validation.registration_allowed){message('Kadastra dati nav pārbaudīti. Redzamas VMD nogabalu robežas, nevis VZD zemes vienības robeža. Reģistrācija bloķēta līdz VZD ģeometrijas un saistības pārbaudei.');s.selected.clear();buttons();return;}
 if(result.verification_message){message(result.verification_message);buttons();return;}
 message('VMD nogabali: zaļas robežas. VZD zemes vienība: zila pārtraukta robeža. Reģistrācijai pieejami tikai pārbaudīti nogabali bez robežu neatbilstības.');buttons();
}
async function query(designation,offset=0,reviewOffset=0){
 if(s.busy)return;const epoch=++s.epoch;s.controller=new AbortController();s.busy=true;buttons();message('Notiek VMD nogabalu meklēšana…');
 try{const data=await request('cadastre?'+new URLSearchParams({kadastrs:designation,limit:100,offset,review_offset:reviewOffset}),undefined,s.controller.signal);if(epoch===s.epoch){render(data,designation);const failed=['DATASET_NOT_READY','SOURCE_ERROR'].includes(data.state);s.lastFailed=failed?{designation,offset,reviewOffset}:null;dom('vmd-retry').hidden=!failed;}}
 catch(error){if(epoch===s.epoch){s.lastFailed={designation,offset};dom('vmd-retry').hidden=false;message(error.name==='AbortError'?'Meklēšana atcelta vai beidzies tās laiks.':lvmError(error.message));}}
 finally{if(epoch===s.epoch){s.controller=null;s.busy=false;rows();buttons();}}
}
function find(){const value=dom('vmd-kadastrs').value.trim();if(!/^[0-9]{11}$/.test(value)){dom('vmd-kadastrs').setAttribute('aria-invalid','true');message('Ievadiet precīzu 11 ciparu zemes vienības kadastra apzīmējumu.');return;}dom('vmd-kadastrs').removeAttribute?.('aria-invalid');return query(value);}
function page(step){if(s.summary&&s.cadastre)return query(s.cadastre,Math.max(0,s.summary.offset+step*s.summary.limit));}
function cancelSearch(){if(!s.controller)return;++s.epoch;s.controller.abort();s.controller=null;s.busy=false;buttons();message('Meklēšana atcelta.');}
function pageSelectable(){return Array.from(s.entries.values()).map(e=>e.feature).filter(f=>f.properties.importable);}
function syncMaster(){const master=s.master;if(!master)return;const list=pageSelectable(),n=list.filter(f=>s.selected.has(f.id)).length;master.checked=list.length>0&&n===list.length;master.indeterminate=n>0&&n<list.length;master.disabled=s.busy||!list.length;master.title=list.length?'Šajā lapā atlasīti '+n+' no '+list.length+' reģistrējamiem nogabaliem':'Šajā lapā nav reģistrējamu nogabalu';}
function clearPage(){if(s.busy)return;pageSelectable().forEach(f=>s.selected.delete(f.id));paint();syncRows();buttons();}
function selectAll(){if(s.busy)return;const features=Array.from(s.entries.values()).map(e=>e.feature).filter(f=>f.properties.importable&&!s.selected.has(f.id));if(s.selected.size+features.length>100){message('Vienā reizē var reģistrēt līdz 100 nogabaliem.');syncRows();return buttons();}features.forEach(f=>s.selected.set(f.id,f));paint();syncRows();buttons();}
function clearSelection(){if(s.busy)return;s.selected.clear();paint();syncRows();selectionOverlay();buttons();}
function report(result){
 const box=dom('lvm-preview-state'),done=result.results.filter(r=>r.status==='imported'),failed=result.results.filter(r=>r.status==='failed');box.replaceChildren();
 const head=result.imported?(result.imported%10===1&&result.imported%100!==11?'Reģistrēts ':'Reģistrēti ')+plural(result.imported,'sektors','sektori')+' · '+haText(done.map(r=>r.area_ha)):'Neviens sektors netika reģistrēts.';
 el('strong',head,box);el('span',' Jau reģistrēti: '+result.already_exists+' · Neizdevās: '+result.failed+'.',box);
 failed.forEach(r=>el('div',r.external_id+': '+lvmError(r.reason),box));
 if(result.imported||result.already_exists){const link=el('a',' Atvērt sadaļu “Sektori”',box);link.href='#sectors';link.onclick=event=>{event.preventDefault?.();if(typeof nav==='function')nav('sectors');};}
}
function intent(){return {...(/^[0-9]{11}$/.test(s.cadastre||'')?{cadastral_designation:s.cadastre}:{}),feature_ids:Array.from(s.selected.keys()),dataset_version:s.version,sector_name:dom('vmd-sector-name').value.trim(),responsible_first_name:dom('vmd-responsible-first-name').value.trim(),responsible_last_name:dom('vmd-responsible-last-name').value.trim()};}
async function executeImport(dryRun,body){
 if(s.busy||!body.feature_ids.length)return;s.busy=true;syncRows();buttons();
 try{
  const result=await request('import-selected',{...body,dry_run:dryRun,confirmed:!dryRun});
  if(!dryRun){s.imported=result.imported;s.step=result.imported?3:2;result.results.forEach(r=>{if(['imported','already_exists'].includes(r.status)){const feature=s.entries.get(r.external_id)?.feature||s.selected.get(r.external_id);if(feature){feature.properties.importable=false;feature.properties.import_status=r.status==='imported'?'REGISTERED':'ALREADY_REGISTERED';feature.properties.sector={id:r.id,name:r.name};}s.selected.delete(r.external_id);}});if(typeof clearCache==='function')clearCache();if(typeof mapLoaded!=='undefined')mapLoaded=false;report(result);return result;}
  message((dryRun?'Pārbaude: gatavi '+result.would_import:'Reģistrēti: '+result.imported)+' · jau pastāv: '+result.already_exists+' · neizdevās: '+result.failed);return result;
 }catch(error){message(lvmError(error.message));}finally{s.busy=false;paint();selectionOverlay();syncRows();buttons();}
}
async function importSelected(dryRun=false){
 if(!s.selected.size||s.busy||!s.identity||s.review)return;if(dom('vmd-kadastrs').value.trim()!==s.cadastre||s.lastFailed){message('Atkārtojiet precīzu meklēšanu pirms reģistrācijas.');return;}const body=intent(),nameError=sectorNameError(body.sector_name);if(nameError){message(nameError);dom('vmd-sector-name').focus();return;}if(!body.responsible_first_name||!body.responsible_last_name){message('Norādiet atbildīgās personas vārdu un uzvārdu.');return;}const result=await executeImport(true,body);if(!result||dryRun)return result;
 const dialog=el('dialog');dialog.className='vmd-dialog';dialog.setAttribute('aria-label','Nogabalu reģistrācijas priekšskatījums');progress(3);
 s.review=dialog;s.step=3;buttons();el('h3','Sektoru reģistrācijas priekšskatījums',dialog);el('p','Ievadītais sektora nosaukums: '+result.sector_name+' · Tabulā — sektoru nosaukumi tieši tā, kā tos saglabās serveris.',dialog);el('p','Organizācija: '+result.registration_identity.organization_name,dialog);el('p','Atbildīgā persona: '+result.responsible_person.first_name+' '+result.responsible_person.last_name,dialog);el('p','Avots: VMD Meža valsts reģistrs · '+body.dataset_version,dialog);
 const metrics=el('div',undefined,dialog);metrics.className='vmd-preview-metrics';[[result.requested,'nogabali'],[result.total_area_ha.toFixed(2)+' ha','kopējā platība'],[result.valid_geometry_count,'derīgas ģeometrijas'],[result.already_exists,'jau reģistrēti']].forEach(([value,label])=>{const box=el('div',undefined,metrics);el('strong',value,box);el('span',label,box);});
 const wrap=el('div',undefined,dialog);wrap.className='vmd-table-scroll';const table=el('table',undefined,wrap),head=el('tr',undefined,el('thead',undefined,table));['Sektora nosaukums','Avota kadastra apzīmējums','VMD nogabala ID','Platība (ha)','Kadastra saistība','Ģeometrija','Pārbaude'].forEach(label=>el('th',label,head));const tbody=el('tbody',undefined,table);
 result.results.forEach(r=>{const tr=el('tr',undefined,tbody);[r.name||'—',r.kadastrs,r.external_id,Number(r.area_ha||0).toFixed(2),r.cadastral_association?.status==='verified_source_attribute'?'VMD atribūts pārbaudīts':'Nav pārbaudīts',r.geometry_repaired?'Normalizējot labota':r.geometry_valid?'Derīga':'Nav apstiprināta',r.status==='ready'?'Gatavs':r.status==='already_exists'?'Jau reģistrēts':lvmError(r.reason)].forEach(value=>el('td',value??'—',tr));});
 const mapBox=el('div',undefined,dialog);mapBox.style.height='240px';mapBox.setAttribute('aria-label','Reģistrējamo nogabalu precīzās robežas');let geometryMap=null;
 el('p','Tiks saglabāta avota ģeometrija un izcelsmes informācija. Esošie sektori netiks pārrakstīti.',dialog);
 const actions=el('div',undefined,dialog);actions.className='vmd-inline-actions';const closeReview=()=>{geometryMap?.remove();geometryMap=null;s.review=null;s.step=2;dialog.close();dialog.remove();buttons();};dialog.addEventListener?.('cancel',event=>{event.preventDefault();closeReview();});const cancel=el('button','Atpakaļ uz atlasi',actions);cancel.className='btn';cancel.onclick=closeReview;const confirm=el('button','Apstiprināt un reģistrēt ('+result.would_import+')',actions);confirm.className='btn vmd-primary';confirm.disabled=!result.would_import;confirm.onclick=async()=>{if(confirm.disabled)return;confirm.disabled=true;closeReview();await executeImport(false,body);};document.body.append(dialog);dialog.showModal();geometryMap=L.map(mapBox);const geometries=L.geoJSON({type:'FeatureCollection',features:Array.from(s.selected.values())},{style:{color:'#d4a017',weight:2,fillOpacity:.2}}).addTo(geometryMap);geometryMap.fitBounds(geometries.getBounds(),{padding:[15,15]});setTimeout(()=>geometryMap?.invalidateSize(),0);
}
function renderSpatial(result){
 if(s.spatialLayer)s.map.removeLayer(s.spatialLayer);s.spatialLayer=null;s.spatialSummary=result.spatial_summary||null;
 const list=result.spatial_candidates||[],body=dom('vmd-spatial-rows');body.replaceChildren();dom('vmd-spatial-review').hidden=!s.spatialSummary?.found;
 list.forEach(f=>{const p=f.properties,tr=el('tr',undefined,body);[f.id,p.kadastrs,p.kvart,p.nog,Number(p.area_ha||0).toFixed(2),Number(p.cadastral_validation?.overlap_percent||0).toFixed(2)+'%','Telpiski atvasināts — nav reģistrējams'].forEach(v=>el('td',v??'—',tr));});
 if(list.length)s.spatialLayer=L.geoJSON({type:'FeatureCollection',features:list},{style:{color:'#e99c38',weight:2,dashArray:'4 4',fillOpacity:.1},onEachFeature:(f,l)=>{const p=el('div');el('strong',f.id,p);el('p','VMD avota kadastrs: '+f.properties.kadastrs,p);el('p','Telpisks kandidāts. Kadastra saistība nav apstiprināta; reģistrācija bloķēta.',p);l.bindPopup(p);}}).addTo(s.map);
 dom('vmd-spatial-count').textContent=s.spatialSummary?'Kandidāti: '+s.spatialSummary.found+' · Lapā: '+s.spatialSummary.returned:'';
 dom('vmd-review-prev').disabled=!s.spatialSummary?.offset;dom('vmd-review-next').disabled=!s.spatialSummary?.has_more;
}
function reviewPage(step){if(s.spatialSummary&&s.cadastre)return query(s.cadastre,s.summary?.offset||0,Math.max(0,s.spatialSummary.offset+step*s.spatialSummary.limit));}
function activate(){s.active=true;dom('lvm-selected').textContent='VMD meža nogabali';headers();rows();buttons();}
async function initialize(){
 if(s.initializing)return s.initializing;
 s.initializing=(async()=>{try{
  const results=await Promise.allSettled([request('dataset'),request('registration-context')]);
  if(results[0].status==='fulfilled'&&['DATASET_NOT_READY','SOURCE_ERROR'].includes(results[0].value.state))results[0]={status:'rejected',reason:new Error(results[0].value.message||'Valsts dati nav gatavi')};
  if(results[0].status==='fulfilled'){
   s.metadata=results[0].value;s.version=s.metadata.dataset_version;dom('vmd-local-count').textContent=s.metadata.feature_count.toLocaleString();dom('vmd-local-importable').textContent='Avota ģeometrijas';dom('vmd-local-status').textContent='VMD datu kopa pieejama';dom('vmd-coverage').textContent=s.metadata.coverage+' · Versija: '+s.version;dom('vmd-search-coverage').textContent=s.metadata.coverage;
  }else{s.metadata=null;dom('vmd-local-status').textContent='VMD datu kopa nav pieejama';}
  if(results[1].status==='fulfilled'){
   s.identity=results[1].value;
   if(!dom('vmd-responsible-first-name').value)dom('vmd-responsible-first-name').value=s.identity.responsible_first_name||'';
   if(!dom('vmd-responsible-last-name').value)dom('vmd-responsible-last-name').value=s.identity.responsible_last_name||'';
   dom('vmd-profile-note').textContent=s.identity.profile_notice;dom('vmd-organization').textContent='Organizācija: '+s.identity.organization_name;
  }else{s.identity=null;dom('vmd-profile-note').textContent='Konta saistība nav pieejama; reģistrācija bloķēta. Nogabalu meklēšana ir pieejama, ja datu kopa ielādēta.';}
  const failed=results.filter(r=>r.status==='rejected');dom('vmd-retry').hidden=!failed.length;
  if(failed.length)message('Ielāde neizdevās: '+failed.map(r=>lvmError(r.reason.message)).join(' · ')+' Izmantojiet “Mēģināt vēlreiz”.');
  else if(!s.summary)message('Ievadiet 11 ciparu kadastra apzīmējumu.');
 }finally{s.initializing=null;buttons();}})();return s.initializing;
}
async function attach(map){s.map=map;activate();if(!s.metadata||!s.identity)return initialize();}
async function retry(){if(s.busy)return;if(!s.metadata||!s.identity)await initialize();if(s.metadata&&s.lastFailed)return query(s.lastFailed.designation,s.lastFailed.offset,s.lastFailed.reviewOffset||0);}
function inputChanged(){buttons();}
function goStep(step){
 if(s.busy||s.review)return;
 if(step===3){if(!s.selected.size){message('Vispirms atlasiet pārbaudītus nogabalus.');return;}return importSelected();}
 if(step===2&&!s.entries.size){message('Vispirms atrodiet nogabalus pēc precīza kadastra apzīmējuma.');return;}
 if(step!==1&&step!==2)return;s.step=step;buttons();dom(step===1?'vmd-kadastrs':'vmd-results-summary').scrollIntoView?.({block:'nearest'});if(step===1)dom('vmd-kadastrs').focus();
}
global.VmdLocalDataset=Object.freeze({attach,activate,find,page,cancelSearch,selectAll,clearSelection,goStep,reviewPage,retry,inputChanged,importSelected,get active(){return s.active;},get selectedIds(){return Array.from(s.selected.keys());}});
})(window);
