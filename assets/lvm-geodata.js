function lvmError(value) {
 const text=String(value||'');
 const known={
 'Not Found':'Adrese nav atrasta. Atjauniniet serveri un pārlādējiet lapu.',
 'Failed to fetch':'Neizdevās sasniegt serveri.',
 'LVM GEO unavailable or request timed out':'LVM GEO nav sasniedzams vai iestājies noildzes limits.',
 'WMS GetCapabilities was not confirmed':'WMS iespējas nav apstiprinātas.',
 'WFS GetCapabilities was not confirmed':'WFS iespējas nav apstiprinātas.',
 'VMD local dataset is not available; build the catalogue first':'VMD datu kopa nav pieejama; nepieciešama indeksēšana.',
 'Dataset version changed; repeat your search':'Datu kopas versija ir mainījusies; atkārtojiet meklēšanu.',
 'Client territory not found':'Klienta teritorija nav atrasta.',
 'Enter a territory name before saving':'Pirms saglabāšanas ievadiet teritorijas nosaukumu.',
 'Client territory is empty or invalid; correct the boundary':'Klienta teritorija ir tukša vai nederīga; izlabojiet robežu.',
 'Territory polygon rings must be closed with at least four positions':'Daudzstūra gredzeniem jābūt slēgtiem un ar vismaz četrām koordinātām.',
 'Territory must be Polygon or MultiPolygon':'Teritorijai jābūt Polygon vai MultiPolygon.',
 'Territory CRS is unsupported; upload EPSG:4326 GeoJSON':'Teritorijas CRS nav atbalstīts; augšupielādējiet EPSG:4326 GeoJSON.',
 'Too many candidate compartments; use a smaller territory or narrower identifiers':'Pārāk daudz nogabalu; samaziniet teritoriju vai precizējiet filtrus.',
 'Spatial query exceeded its time limit; narrow the search':'Meklēšanas laiks beidzies; precizējiet apgabalu.',
 'Map area too large; zoom in or search by client territory':'Kartes apgabals ir pārāk liels; pietuviniet vai meklējiet klienta teritorijā.',
 'Current sectors require one simple Polygon ring; MultiPolygon/holes are not flattened':'Sektoriem nepieciešams viens vienkāršs daudzstūris; daudzdaļu ģeometrija un caurumi netiek pārveidoti.',
 'Compartment is not in the production dataset':'Nogabals nav datu kopā.',
 'A sector with this name already exists; no overwrite allowed':'Sektors ar šādu nosaukumu jau pastāv; pārrakstīšana nav atļauta.',
 'Source identity conflict; nothing overwritten':'Avota identifikatoru konflikts; dati nav pārrakstīti.'};
 if(known[text])return known[text];
 if(/[āčēģīķļņšūžĀČĒĢĪĶĻŅŠŪŽ]/.test(text))return text;
 if(/^LVM GEO returned HTTP \d+$/.test(text))return 'LVM GEO atbilde: HTTP '+text.match(/\d+$/)[0];
 if(/^WMS|^WFS/.test(text))return 'Pakalpojuma iespēju atbilde nav derīga. Pārbaudiet servera žurnālu.';
 console.error('Geodata error',text);
 return 'Ģeodatu pieprasījums neizdevās. Pārbaudiet ievaddatus un servera žurnālu.';
}
function lvmStatus(value){return ({'READY':'Gatavs','ALREADY IMPORTED':'Jau importēts','REVIEW REQUIRED':'Jāpārbauda','UNSUPPORTED GEOMETRY':'Neatbalstīta ģeometrija','CONNECTED':'Savienojums izveidots','UNAVAILABLE':'Nav pieejams'})[value]||value;}
/* External metadata is untrusted: render it as text, never as HTML. */
const lvmUI = {layers: [], selected: null, map: null, overlay: null, controls: null,
  vectors: null, preview: null, version: 0, refreshToken: null, compareMap: null};
async function lvmRequest(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 45000);
  try {
    const r = await fetch('/api/geodata/lvm' + path, {signal: controller.signal, cache:'no-store',
      ...(body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})});
    const data = await r.json();
    if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Ģeodatu pieprasījums neizdevās');
    return data;
  } catch (error) {
    if(error.name === 'AbortError') throw new Error('Pakalpojuma pārbaudes laiks ir beidzies. Mēģiniet vēlreiz.');
    throw error;
  } finally { clearTimeout(timer); }
}
function lvmText(tag, text, parent) {
  const n = document.createElement(tag); n.textContent = text; if (parent) parent.append(n); return n;
}
function lvmButton(text, fn, parent) {
  const b = lvmText('button', text, parent); b.className = 'btn';
  b.onclick = async () => { b.disabled = true; try { await fn(); } catch (e) { alert(lvmError(e.message)); } finally { b.disabled = false; } };
  return b;
}
async function loadLvmStatus(force=false) {
  if (!window.FOREST_GEODATA_ENABLED) return;
  document.getElementById("lvm-status").style.display="";
  const box = document.getElementById('lvm-status');
  try {
    const s = await lvmRequest('/health', force ? {} : undefined);
    box.replaceChildren();
    lvmText('h3', 'LVM GEO', box);
    lvmText('p', 'Latvijas valsts atvērtie ģeotelpiskie dati', box);
    lvmText('p', `${lvmStatus(s.status)} · WMS: ${s.wms ? 'pieejams' : 'nav pieejams'} · WFS: ${s.wfs ? 'pieejams' : 'nav pieejams'}`, box);
    lvmText('p', 'Pēdējā pārbaude: ' + new Date(s.checked_at).toLocaleString('lv-LV'), box);
    lvmText('p', 'Importētās robežas glabājas vietēji. GPS un risku darbība turpinās arī datu avota pārtraukumu laikā.', box);
    lvmButton('Atvērt slāņus', () => nav('lvm-geodata'), box);
    lvmButton('Atjaunot savienojumu', () => loadLvmStatus(true), box);
  } catch (e) { box.replaceChildren(); lvmText('p','LVM GEO nav pieejams: ' + lvmError(e.message),box); lvmButton('Mēģināt vēlreiz',()=>loadLvmStatus(true),box); }
}
let lvmLeafletPromise;
function lvmLeaflet() {
  if (window.L) return Promise.resolve();
  if (!lvmLeafletPromise) lvmLeafletPromise = new Promise((resolve,reject) => {
    const css=document.createElement('link'); css.rel='stylesheet'; css.href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'; document.head.append(css);
    const timer=setTimeout(()=>{lvmLeafletPromise=null;reject(new Error('Kartes bibliotēkas ielādes laiks ir beidzies'));},15000);
    const js=document.createElement('script'); js.src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    js.onload=()=>{clearTimeout(timer);resolve();}; js.onerror=()=>{clearTimeout(timer); lvmLeafletPromise=null; reject(new Error('Neizdevās ielādēt Leaflet')); }; document.head.append(js);
  });
  return lvmLeafletPromise;
}
async function refreshLvmCapabilities(force=false) {
  const state=document.getElementById('lvm-layer-state');if(!state)return;
  state.textContent='Notiek pakalpojuma iespēju pārbaude…';
  try {
    if(force) await lvmRequest('/health',{});
    const cap=await lvmRequest('/capabilities');lvmUI.layers=cap.layers;
    state.textContent=`${cap.status==='CONNECTED'?'Savienojums izveidots':'Pakalpojums nav pieejams'} · ${cap.layer_count} slāņi · pārbaudīts ${new Date(cap.checked_at).toLocaleString('lv-LV')}`;
    if(cap.last_success_at) state.textContent+=' · pēdējais veiksmīgais savienojums '+new Date(cap.last_success_at).toLocaleString('lv-LV');
    (cap.services||[]).forEach(service=>{if(service.errors.length) state.textContent+=' · '+service.id+': '+service.errors.map(lvmError).join('; ');});
    renderLvmLayers();
  }catch(error){state.textContent='Pakalpojums nav pieejams: '+lvmError(error.message);}
}
async function loadLvmLayers() {
  // Discovery must resolve even if the map CDN, sectors or local catalogue fail.
  // Cadastral registration uses the local authoritative-source catalogue.
  try {
    await lvmLeaflet();
    if(!lvmUI.map){
      lvmUI.map=L.map('lvm-map').setView([56.95,24.1],13);
      lvmUI.baseMap=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap',maxZoom:19}).addTo(lvmUI.map);
      setupLvmImagery();
      // Show only verified VMD search results here; operational sectors stay on the main map.
    }
    if(lvmUI.satellite)lvmSetBasemap('satellite');
    setTimeout(()=>lvmUI.map.invalidateSize(),100);
    await loadVmdTestCompartments(lvmUI.map);
  }catch(error){document.getElementById('lvm-preview-state').textContent='Kartes ielāde neizdevās: '+lvmError(error.message);}
}
function renderLvmLayers() {
  const tbody=document.getElementById('lvm-layer-rows');if(!tbody)return;tbody.replaceChildren();
  const q=document.getElementById('lvm-search').value.toLocaleLowerCase();
  const wfsOnly=document.getElementById('lvm-wfs-only').checked;
  lvmUI.layers.filter(l=>(!wfsOnly||l.wfs)&&[l.name,l.title,l.abstract,l.attribution].join(' ').toLocaleLowerCase().includes(q)).forEach(l=>{
    const tr=document.createElement('tr'); tbody.append(tr);
    [l.name,l.title,l.attribution||'Pakalpojums nenorāda',l.type,l.wms?'Jā':'Nē',l.wfs?'Jā':'Nē',l.crs.join(', '),
      l.importable&&l.attribution?'Priekšskatiet ģeometrijas pārbaudei':'Nē', 'Pakalpojums apstiprina'].forEach(x=>lvmText('td',x,tr));
    const td=document.createElement('td');tr.append(td);lvmButton('Atvērt',()=>chooseLvmLayer(l),td);
  });
}
function lvmWmsOptions(layer) {
  if(!layer.wms) throw new Error("Šis slānis nav pieejams WMS. WFS objektu priekšskatījums ir atsevišķs.");
  const codes=layer.crs.map(c=>c.toUpperCase());
  const crs=codes.includes('EPSG:3857')?L.CRS.EPSG3857:
    codes.some(c=>c==='EPSG:4326'||c.endsWith(':4326')||c.endsWith('/4326'))?L.CRS.EPSG4326:null;
  if(!crs) throw new Error('WMS priekšskatījumam nepieciešams EPSG:3857 vai EPSG:4326. Slāņa CRS netiek atbalstīts.');
  return {layers:layer.name,version:'1.1.1',format:'image/png',transparent:true,crs,
    attribution:lvmText('span',layer.attribution||'LVM GEO: avota norāde nav pieejama').innerHTML,opacity:0.65};
}
async function chooseLvmLayer(layer) {
  if(window.VmdLocalDataset) window.VmdLocalDataset.deactivate?.();
  const head=document.getElementById('lvm-feature-head');
  if(head) head.innerHTML='<tr><th>Atlasīt</th><th>Avota ID</th><th>Stāvoklis</th><th>Atribūti</th></tr>';
  await lvmLeaflet();
  if (!lvmUI.map) throw new Error('Karte nav gatava; atveriet slāņus vēlreiz');
  lvmUI.version++; lvmUI.selected=layer; lvmUI.preview=null;
  document.getElementById('lvm-selected').textContent=layer.title+' · '+(layer.attribution||'Avota norāde nav pieejama');
  document.getElementById('lvm-feature-rows').replaceChildren();
  document.getElementById('lvm-preview-state').textContent='Pietuviniet vajadzīgo apgabalu un priekšskatiet līdz 100 objektiem.';
  document.getElementById('lvm-import').disabled=true;
  document.getElementById('lvm-preview').disabled=!layer.importable;
  if(lvmUI.vectors) lvmUI.map.removeLayer(lvmUI.vectors);
  if(lvmUI.overlay) lvmUI.map.removeLayer(lvmUI.overlay);
  if(lvmUI.controls) lvmUI.controls.remove();
  let options;
  try {options=lvmWmsOptions(layer);} catch(e) {document.getElementById('lvm-preview-state').textContent=lvmError(e.message);return;}
  lvmUI.overlay=L.tileLayer.wms(layer.endpoint,options);
  lvmUI.overlay.on('tileerror',()=>{document.getElementById('lvm-preview-state').textContent='WMS attēls nav pieejams. Importētie vietējie sektori joprojām ir pieejami.';});
  lvmUI.overlay.addTo(lvmUI.map);
  lvmUI.controls=L.control.layers(null,{'LVM GEO slānis ieslēgts/izslēgts':lvmUI.overlay}).addTo(lvmUI.map);
  document.getElementById('lvm-map').scrollIntoView({block:'center',behavior:'smooth'});
}
async function previewLvmFeatures() {
  if(window.VmdLocalDataset?.active) return window.VmdLocalDataset.find();
  if(!lvmUI.selected) throw new Error('Izvēlieties slāni');
  const version=lvmUI.version, layer=lvmUI.selected;
  const b=lvmUI.map.getBounds(); const bbox=[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()];
  document.getElementById('lvm-preview-state').textContent='Notiek apgabala datu ielāde…';
  document.getElementById('lvm-preview').disabled=true;
  document.getElementById('lvm-import').disabled=true;
  lvmUI.preview=null;
  try {
    const p=await lvmRequest('/preview',{layer_id:layer.id,bbox,limit:100});
    if(version!==lvmUI.version) return;
    lvmUI.preview=p;
    const rows=document.getElementById('lvm-feature-rows');rows.replaceChildren();
    if(lvmUI.vectors) lvmUI.map.removeLayer(lvmUI.vectors);
    lvmUI.vectors=L.featureGroup().addTo(lvmUI.map);
    p.features.forEach(f=>{
      const tr=document.createElement('tr');rows.append(tr);
      const td=document.createElement('td');tr.append(td);
      const cb=document.createElement('input');cb.type='checkbox';cb.dataset.index=f.index;cb.disabled=!f.importable;td.append(cb);
      cb.onchange=()=>{document.getElementById('lvm-import').disabled=!rows.querySelector('input:checked');};
      lvmText('td',f.feature_id||'(nav pastāvīga ID)',tr);
      lvmText('td',f.already_imported?'Jau importēts → '+f.already_imported.name:(f.reason?lvmError(f.reason):'Gatavs importēšanai'),tr);
      if(f.geometry) L.geoJSON(f.geometry,{style:{color:f.already_imported?'#999':'#299dd6',fillOpacity:0.2}}).bindTooltip(lvmText('span',f.feature_id)).addTo(lvmUI.vectors);
      const prop=document.createElement('td');tr.append(prop);
      const details=document.createElement('details');prop.append(details);lvmText('summary','Avota atribūti',details);lvmText('pre',JSON.stringify(f.properties||{},null,2),details);
    });
    document.getElementById('lvm-preview-state').textContent=`Atrasti: ${p.found}. ${p.possibly_truncated?'Sasniegts limits; pietuviniet pilnai atlasei. ':''}Priekšskatījums derīgs 15 minūtes. Atlasiet līdz 25 daudzstūriem.`;
  } catch(e) {document.getElementById('lvm-preview-state').textContent=lvmError(e.message);}
  finally {if(version===lvmUI.version) document.getElementById('lvm-preview').disabled=false;}
}
async function importLvmFeatures() {
  if(window.VmdLocalDataset?.active) return window.VmdLocalDataset.importSelected();
  const p=lvmUI.preview;if(!p) throw new Error('Vispirms atveriet priekšskatījumu');
  const ids=Array.from(document.querySelectorAll('#lvm-feature-rows input:checked')).map(n=>p.features[Number(n.dataset.index)].feature_id);
  if(ids.length>25) throw new Error('Atlasiet līdz 25 daudzstūriem');
  const b=document.getElementById('lvm-import');b.disabled=true;
  try {
    const result=await lvmRequest('/import',{token:p.token,feature_ids:ids});
    clearCache();mapLoaded=false;
    document.getElementById('lvm-preview-state').textContent=result.sectors.map(s=>(s.status==='imported'?'Importēts → ':'Jau importēts → ')+s.name).join('; ');
    document.querySelectorAll('#lvm-feature-rows input').forEach(n=>{n.checked=false;n.disabled=true;});
    lvmUI.preview=null;
  } catch(e) {document.getElementById('lvm-preview-state').textContent=lvmError(e.message); b.disabled=false;}
}
async function lvmOnForestMap() {
  const layer=lvmUI.selected;if(!layer) throw new Error('Vispirms izvēlieties slāni');
  nav('map');
  for(let i=0;i<100&&(!forestMap||!mapLoaded);i++) await new Promise(r=>setTimeout(r,100));
  if(!forestMap||!mapLoaded) throw new Error('Karte vēl ielādējas; mēģiniet vēlreiz');
  if(lvmUI.forestOverlay) forestMap.removeLayer(lvmUI.forestOverlay);
  if(lvmUI.forestControls) lvmUI.forestControls.remove();
  lvmUI.forestOverlay=L.tileLayer.wms(layer.endpoint,lvmWmsOptions(layer)).addTo(forestMap);
  lvmUI.forestControls=L.control.layers(null,{'LVM GEO slānis ieslēgts/izslēgts':lvmUI.forestOverlay}).addTo(forestMap);
  forestMap.fitBounds(lvmUI.map.getBounds());
}
async function loadLvmSource(sector) {
  if (!window.FOREST_GEODATA_ENABLED) return;
  const target=document.getElementById('lvm-sector-source'); target.replaceChildren();
  target.style.display='none';
  if(lvmUI.compareMap) {lvmUI.compareMap.remove();lvmUI.compareMap=null;}
  const sectorId=sector.id;
  try {
    const s=await lvmRequest(`/sectors/${sectorId}/source`);
    if(currentDetailData?.sector?.id!==sectorId) return;
    if(s.boundary_source_type==='manual') return;
    target.style.display='';
    lvmText('h3','DATU AVOTS — ārējā ģeodatu robeža',target);
    [['Pakalpojuma sniedzējs',s.provider],['Sākotnējā datu kopa',s.source_dataset_title],['Avota norāde',s.source_attribution],['Avota ID',s.source_feature_id],['Importēts',s.imported_at],['Pēdējā pārbaude',s.source_last_checked_at]].forEach(([k,v])=>lvmText('p',k+': '+v,target));
    const details=document.createElement('details');target.append(details);lvmText('summary','Skatīt avota datus',details);lvmText('pre',JSON.stringify(s.source_properties,null,2),details);
    lvmText('p','Robežu vēsture: '+s.history.map(h=>h.action+' · '+h.created_at+' · '+h.actor).join('; '),target);
    if(s.provider==='LVM_GEO') lvmButton('Atjaunot robežu',()=>lvmRefreshBoundary(sectorId,target),target);
    if(['VMD_LOCAL','VMD_OPEN_DATA'].includes(s.provider)) lvmButton('Atvērt vietējo datu kopu',()=>nav('lvm-geodata'),target);
  } catch(e) {lvmText('p','Avota informācija nav pieejama: '+lvmError(e.message),target);}
}
async function lvmRefreshBoundary(sectorId,target) {
  const p=await lvmRequest(`/sectors/${sectorId}/refresh`,{});
  if(currentDetailData?.sector?.id!==sectorId) return;
  if(!p.changed) {alert('Izmaiņu nav'); await loadLvmSource(currentDetailData.sector);return;}
  // Remove any previous proposal before creating a new confirmation control.
  if(lvmUI.compareMap) {lvmUI.compareMap.remove();lvmUI.compareMap=null;}
  target.querySelectorAll('.lvm-proposal').forEach(n=>n.remove());
  const box=document.createElement('div');box.className='lvm-proposal';target.append(box);
  lvmText('p','Robeža ir mainījusies. Iepriekšējā robeža: oranža. Jaunā: zila.',box);
  const canvas=document.createElement('div');canvas.style.height='350px';box.append(canvas);
  await lvmLeaflet();
  const map=L.map(canvas);lvmUI.compareMap=map;
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors'}).addTo(map);
  const old=L.polygon(p.old_boundary,{color:'#e69535',fillOpacity:0.15}).addTo(map);
  const next=L.polygon(p.new_boundary,{color:'#299dd6',fillOpacity:0.15}).addTo(map);
  map.fitBounds(old.getBounds().extend(next.getBounds()));
  lvmButton('Apstiprināt un atjaunot robežu',async()=>{
    if(!confirm('Lietot parādīto robežas atjauninājumu šim sektoram? GPS pārbaudes izmantos jauno robežu.'))return;
    await lvmRequest('/apply',{token:p.token,confirmed:true});
    map.remove();lvmUI.compareMap=null;clearCache();mapLoaded=false;await openSector(currentSector,false);
  },box);
}


// Local vector data is independent of live LVM capabilities and WFS.
async function loadVmdTestCompartments(map) {
  if(window.VmdLocalDataset) await window.VmdLocalDataset.attach(map);
}

// Optional reference imagery; cadastral/compartment geometry always comes from VMD.
async function setupLvmImagery(){
 const option=document.getElementById('vmd-satellite-option');
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
 try{
  const response=await fetch('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer?f=json',{signal:controller.signal});
  if(!response.ok)throw Error('imagery unavailable');
  const metadata=await response.json();
  if(!metadata.tileInfo||metadata.error)throw Error('imagery unavailable');
  lvmUI.satellite=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{attribution:lvmText('span',metadata.copyrightText||'© Esri').innerHTML,maxZoom:19});
  lvmUI.satellite.on('tileerror',()=>{lvmSetBasemap('map');option.disabled=true;option.textContent='Satelīts nav pieejams';document.getElementById('vmd-basemap-status').textContent='Satelītattēli nav pieejami. Karte un īstās VMD robežas paliek pieejamas.';});
  option.disabled=false;option.textContent='Satelīts';lvmSetBasemap('satellite');
 }catch(error){option.disabled=true;option.textContent='Satelīts nav pieejams';lvmSetBasemap('map');}
 finally{clearTimeout(timer);}
}
function lvmSetBasemap(kind){
 if(!lvmUI.map||!lvmUI.baseMap)return;
 const satellite=kind==='satellite'&&lvmUI.satellite;
 if(lvmUI.satellite)lvmUI.map.removeLayer(lvmUI.satellite);
 lvmUI.map.removeLayer(lvmUI.baseMap);
 (satellite?lvmUI.satellite:lvmUI.baseMap).addTo(lvmUI.map);
 document.getElementById('vmd-basemap').value=satellite?'satellite':'map';
 document.getElementById('vmd-basemap-status').textContent=satellite?'Esri satelītattēli un aerofotogrāfijas; uzņemšanas laiks atšķiras. Nogabalu robežas: VMD.':'Robežu avots: VMD. Pamatkartes attēli neaizstāj avota ģeometriju.';
}
