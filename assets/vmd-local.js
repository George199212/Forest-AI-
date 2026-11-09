/* Local GeoJSON catalogue. IDs, selection and rendering are separate from live WMS. */
(function(global){
  'use strict';
  const state={map:null,layer:null,control:null,entries:new Map(),rows:new Map(),selected:new Set(),visible:[],
    focused:null,active:false,version:null,loaded:false,loading:null,importing:false,statusReady:false};
  const baseStyle={color:'#4b9d54',weight:2,fillColor:'#7ab83c',fillOpacity:0.14};
  function element(tag,text,parent){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(parent)parent.append(n);return n;}
  function note(text){document.getElementById('vmd-local-status').textContent=text;}
  function message(text){document.getElementById('lvm-preview-state').textContent=text;}
  function idOf(feature){
    const p=feature.properties||{};
    const part=value=>String(value??'').trim().replace(/^0+(?=\d)/,'');
    return 'VMD-'+String(p.kadastrs??'').trim()+'-'+part(p.kvart)+'-'+part(p.nog);
  }
  async function request(path,body){
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000);
    try{
      const r=await fetch('/api/geodata/vmd/'+path,{credentials:'same-origin',cache:'no-store',signal:controller.signal,
        ...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
      const ct=(r.headers.get('content-type')||'').split(';')[0];
      if(!['application/json','application/geo+json'].includes(ct))throw new Error('Invalid local VMD response');
      const data=await r.json();
      if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'Local VMD request failed (HTTP '+r.status+')');
      return {data,etag:(r.headers.get('etag')||'').replace(/^"|"$/g,'')};
    }finally{clearTimeout(timer);}
  }
  function updateCard(){
    document.getElementById('vmd-local-count').textContent=String(state.entries.size);
    document.getElementById('vmd-local-importable').textContent=state.statusReady&&Array.from(state.entries.values()).some(e=>e.meta.importable)?'YES':'NO';
    note('LOCAL DATA · READY · '+state.entries.size+' compartments'+(state.statusReady?'':' · import status unavailable'));
  }
  function updateButtons(){
    if(!state.active)return;
    document.getElementById('lvm-preview').disabled=!state.loaded||state.importing;
    document.getElementById('lvm-import').disabled=state.importing||!state.statusReady||!Array.from(state.selected).some(id=>state.entries.get(id)?.meta.importable);
  }
  function styleAll(){
    state.entries.forEach((entry,id)=>entry.layer.setStyle({...baseStyle,
      ...(state.selected.has(id)?{color:'#d4a017',weight:3,fillOpacity:0.28}:{}),
      ...(state.focused===id?{color:'#309fe8',weight:4,fillOpacity:0.3}:{})}));
  }
  function activate(){
    if(!state.loaded)return;
    state.active=true;
    document.getElementById('vmd-selection-actions').hidden=false;
    document.getElementById('lvm-selected').textContent='VMD Forest Compartments — Local Dataset';
    document.getElementById('lvm-feature-head').replaceChildren();
    const tr=element('tr',undefined,document.getElementById('lvm-feature-head'));
    ['Select','Kadastrs','Kvartāls','Nogabals','Area (ha)','Source','Status'].forEach(t=>element('th',t,tr));
    renderRows();updateButtons();
  }
  function deactivate(){state.active=false;document.getElementById('vmd-selection-actions').hidden=true;}
  function renderRows(){
    if(!state.active)return;
    const body=document.getElementById('lvm-feature-rows');body.replaceChildren();state.rows.clear();
    state.visible.forEach(id=>{
      const entry=state.entries.get(id);if(!entry)return;
      const p=entry.feature.properties||{},tr=element('tr',undefined,body);state.rows.set(id,tr);
      tr.tabIndex=0;tr.style.cursor='pointer';tr.setAttribute('aria-selected',String(state.focused===id));
      if(state.focused===id)tr.style.background='rgba(122,184,60,0.18)';
      const td=element('td',undefined,tr),box=element('input',undefined,td);box.type='checkbox';box.checked=state.selected.has(id);
      box.disabled=!entry.meta.importable||!state.statusReady||state.importing;box.setAttribute('aria-label','Select '+id);
      box.onclick=e=>e.stopPropagation();
      box.onchange=()=>{if(box.checked)state.selected.add(id);else state.selected.delete(id);styleAll();updateButtons();};
      [p.kadastrs,p.kvart,p.nog,p.nog_plat,'VMD Local',entry.meta.status+(entry.meta.sector?' → '+entry.meta.sector.name:'')].forEach(v=>element('td',String(v??'—'),tr));
      if(entry.meta.reason)tr.title=entry.meta.reason;
      tr.onclick=()=>focus(id,true);
      tr.onkeydown=e=>{if(e.target===tr&&(e.key==='Enter'||e.key===' ')){e.preventDefault();focus(id,true);}};
    });
  }
  function focus(id,zoom){
    const entry=state.entries.get(id);if(!entry)return;
    state.focused=id;if(!state.visible.includes(id))state.visible.push(id);activate();styleAll();
    const row=state.rows.get(id);if(row){row.scrollIntoView?.({block:'nearest'});row.focus?.({preventScroll:true});}
    if(zoom)state.map.fitBounds(entry.layer.getBounds(),{padding:[35,35],maxZoom:18});
    entry.layer.openPopup();
  }
  function selectAll(){state.visible.forEach(id=>{if(state.statusReady&&state.entries.get(id)?.meta.importable)state.selected.add(id);});renderRows();styleAll();updateButtons();}
  function clearSelection(){state.selected.clear();renderRows();styleAll();updateButtons();}
  // Exact planar polygon/viewport intersection in lon/lat; bbox is a fast reject.
  // Includes ring-edge contact and excludes viewports entirely inside a hole.
  function intersects(geometry,b){
    const rings=geometry.coordinates,w=b[0],s=b[1],e=b[2],n=b[3];
    const outer=rings[0];let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
    outer.forEach(p=>{minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);});
    if(maxX<w||minX>e||maxY<s||minY>n)return false;
    const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
    const on=(a,b,p)=>Math.abs(cross(a,b,p))<1e-12&&p[0]>=Math.min(a[0],b[0])-1e-12&&p[0]<=Math.max(a[0],b[0])+1e-12&&p[1]>=Math.min(a[1],b[1])-1e-12&&p[1]<=Math.max(a[1],b[1])+1e-12;
    function hit(a,b,c,d){const abC=cross(a,b,c),abD=cross(a,b,d),cdA=cross(c,d,a),cdB=cross(c,d,b);return (abC*abD<0&&cdA*cdB<0)||on(a,b,c)||on(a,b,d)||on(c,d,a)||on(c,d,b);}
    function inside(p,ring){let yes=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){
      const a=ring[j],b=ring[i];if(on(a,b,p))return true;
      if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])yes=!yes;
    }return yes;}
    const corners=[[w,s],[e,s],[e,n],[w,n]];
    if(outer.some(p=>p[0]>=w&&p[0]<=e&&p[1]>=s&&p[1]<=n))return true;
    if(corners.some(p=>inside(p,outer)&&!rings.slice(1).some(r=>inside(p,r))))return true;
    return rings.some(r=>r.some((p,i)=>i>0&&corners.some((c,j)=>hit(r[i-1],p,c,corners[(j+1)%4]))));
  }
  function preview(){
    if(!state.loaded)return;
    const b=state.map.getBounds(),bbox=[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()];
    state.visible=Array.from(state.entries).filter(([,e])=>intersects(e.feature.geometry,bbox)).map(([id])=>id);
    const visible=new Set(state.visible);state.selected=new Set(Array.from(state.selected).filter(id=>visible.has(id)));
    activate();message('LOCAL DATA · '+state.visible.length+' of '+state.entries.size+' compartments intersect the current map area. No live service request made.');
  }
  async function refreshStatus(){
    const {data}=await request('local-status');
    if(data.dataset_version!==state.version)throw new Error('Local dataset changed; reload the LVM GEO page');
    const meta=new Map(data.features.map(f=>[f.external_id,f]));
    state.entries.forEach((entry,id)=>{entry.meta=meta.get(id)||{status:'FAILED',importable:false,reason:'Missing import status'};if(!entry.meta.importable)state.selected.delete(id);});
    state.statusReady=true;updateCard();renderRows();styleAll();updateButtons();
  }
  async function importSelected(){
    const ids=Array.from(state.selected).filter(id=>state.entries.get(id)?.meta.importable);
    if(!ids.length||state.importing||!state.statusReady)return;
    if(ids.length>25){message('Select at most 25 compartments per import.');return;}
    state.importing=true;renderRows();updateButtons();
    let result;
    try{
      result=(await request('import',{feature_ids:ids,dataset_version:state.version})).data;
      result.results.forEach(r=>{const entry=state.entries.get(r.external_id);if(entry&&(r.status==='imported'||r.status==='already_exists')){
        entry.meta={external_id:r.external_id,status:'IMPORTED',importable:false,sector:{id:r.id,name:r.name}};state.selected.delete(r.external_id);
      }});
      if(typeof clearCache==='function')clearCache();if(typeof mapLoaded!=='undefined')mapLoaded=false;
      message('Imported: '+result.imported+' · already exists: '+result.already_exists+' · failed: '+result.failed+
        result.results.filter(r=>r.status==='failed').map(r=>' · '+r.external_id+': '+r.reason).join(''));
      try{await refreshStatus();}catch(error){state.statusReady=false;console.error('VMD import status refresh failed',error);note('LOCAL DATA · sectors saved; reload import status before another import');}
    }catch(error){console.error('VMD local import failed',error);message('Local VMD import failed: '+error.message);}
    finally{state.importing=false;renderRows();styleAll();updateButtons();}
    return result;
  }
  async function attach(map){
    if(state.loaded&&state.map===map){activate();return;}
    if(state.loading)return state.loading;
    state.map=map;note('LOCAL DATA · loading…');
    state.loading=(async()=>{
      let candidate;
      try{
        const {data,etag}=await request('test-sectors');
        if(!data||data.type!=='FeatureCollection'||!Array.isArray(data.features))throw new Error('Invalid local GeoJSON FeatureCollection');
        if(!data.features.length)throw new Error('Local dataset contains zero features');
        const ids=new Set();data.features.forEach(f=>{
          if(f.type!=='Feature'||f.geometry?.type!=='Polygon'||!f.properties)throw new Error('Invalid local VMD polygon');
          const id=idOf(f);if(!/^VMD-[0-9]+-[0-9]+-[0-9]+$/.test(id)||ids.has(id))throw new Error('Invalid or duplicate local compartment ID');ids.add(id);
        });
        state.entries.clear();state.selected.clear();state.statusReady=false;state.version=etag;
        const pane=map.getPane('vmdLocalCompartments')||map.createPane('vmdLocalCompartments');pane.style.zIndex='350';
        candidate=L.geoJSON(data,{pane:'vmdLocalCompartments',style:baseStyle,attribution:'VMD / LVM open data · Local GeoJSON',
          onEachFeature:(feature,layer)=>{
            const id=idOf(feature),p=feature.properties;state.entries.set(id,{feature,layer,meta:{status:'READY',importable:false}});
            const box=element('div');element('strong','VMD forest compartment',box);
            [['Kadastrs',p.kadastrs],['Kvartāls',p.kvart],['Nogabals',p.nog],['Area',String(p.nog_plat)+' ha']].forEach(([label,value])=>element('div',label+': '+value,box));
            layer.bindPopup(box);layer.on('click',()=>focus(id,false));
          }});
        const bounds=candidate.getBounds();if(!bounds.isValid())throw new Error('Invalid local polygon bounds');
        candidate.addTo(map);state.layer=candidate;
        state.control=L.control.layers(null,{'VMD Forest Compartments — Local Dataset':candidate},{collapsed:false}).addTo(map);
        state.loaded=true;state.visible=Array.from(state.entries.keys());map.fitBounds(bounds,{padding:[30,30],maxZoom:17});
        activate();updateCard();message('LOCAL DATA · '+state.entries.size+' compartments loaded. Select polygons to import as Forest AI sectors.');
        try{
          if(!state.version)throw new Error('Local endpoint requires updated dataset-version headers for safe import');
          await refreshStatus();
        }catch(error){console.error('Local VMD import status unavailable',error);state.statusReady=false;updateCard();updateButtons();}
      }catch(error){
        console.error('Local VMD dataset unavailable',error);state.loaded=false;state.active=false;state.statusReady=false;
        if(candidate&&map.hasLayer(candidate))map.removeLayer(candidate);
        note('Local VMD dataset unavailable');document.getElementById('vmd-local-count').textContent='—';document.getElementById('vmd-local-importable').textContent='NO';
        document.getElementById('lvm-import').disabled=true;
      }finally{state.loading=null;}
    })();return state.loading;
  }
  global.VmdLocalDataset=Object.freeze({attach,activate,deactivate,preview,selectAll,clearSelection,importSelected,intersects,
    get active(){return state.active;}});
})(window);
