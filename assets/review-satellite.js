/* Cache-only Sentinel imagery. Injected only in ACCESS_MODE=review. No token calls. */
(function () {
  'use strict';
  if (window.ForestInstance?.readOnly !== true) return;
  const MISSING='Satellite image not available in review mode';
  const CONTEXT='Context imagery. Individual tree changes are below Sentinel-2 resolution; the change assessment for this case is based on ground photos.';
  const tokens=new WeakMap();
  const el=id=>document.getElementById(id);
  function caption(meta) {
    const date=meta.acquisition_date || `${meta.date_window.from} – ${meta.date_window.to}`;
    const year=String(meta.acquisition_date || meta.date_window.from).slice(0,4);
    return `Copernicus Sentinel-2 L2A · ${meta.product==='ndvi'?'NDVI':'true colour'} · ${date} · 10 m resolution · contains modified Copernicus Sentinel data ${year}`;
  }
  function missing(target,sector) {
    if(!target)return;
    target.replaceChildren();
    const message=document.createElement('p');message.textContent=MISSING;message.className='empty';target.appendChild(message);
    if(sector==='FIELD-TEST-01') {const note=document.createElement('p');note.textContent=CONTEXT;target.appendChild(note);}
  }
  async function render(target,sector,product='image',datePrefix='') {
    if(!target) return;
    const token={};tokens.set(target,token);
    const current=()=>tokens.get(target)===token && target.isConnected;
    target.style.height='auto';target.style.display='block';
    target.textContent='Loading cached satellite image…';
    if(datePrefix) for(const suffix of ['from','to']) {
      const input=el(datePrefix+'-date-'+suffix);if(input){input.value='';input.disabled=true;}
    }
    try {
      const response=await fetch(`/api/review/satellite-cache/${product}/${encodeURIComponent(sector)}`);
      const meta=response.ok ? await response.json() : null;
      if(!current()) return;
      if(!meta?.available) {missing(target,sector);return;}
      const dates=new URLSearchParams({date_from:meta.date_window.from,date_to:meta.date_window.to});
      const imageURL=`/api/satellite/${product}/${encodeURIComponent(sector)}?${dates}`;
      for(const [suffix,key] of [['from','from'],['to','to']]) {
        const input=el(datePrefix+'-date-'+suffix);
        if(input) {input.value=meta.date_window[key];input.disabled=true;}
      }
      target.replaceChildren();
      const figure=document.createElement('figure');figure.style.margin='0';
      const image=document.createElement('img');image.alt=`${sector} · ${meta.product==='ndvi'?'NDVI':'true colour'}`;
      image.style.cssText='display:block;width:100%;max-height:480px;object-fit:contain;border-radius:var(--r);cursor:zoom-in';
      const text=caption(meta);
      image.addEventListener('click',()=>openLightboxImg(imageURL,sector,text+(sector==='FIELD-TEST-01'?' · '+CONTEXT:'')));
      image.addEventListener('error',()=>{if(current())missing(target,sector);});
      image.src=imageURL;
      const description=document.createElement('figcaption');description.textContent=text;
      description.style.cssText='font-size:12px;line-height:1.6;margin-top:8px;color:var(--text2)';
      figure.append(image,description);target.appendChild(figure);
      if(sector==='FIELD-TEST-01') {
        const note=document.createElement('p');note.textContent=CONTEXT;note.style.cssText='font-size:12px;line-height:1.6;color:var(--text2)';target.appendChild(note);
      }
    } catch {if(current())missing(target,sector);}
  }
  function start() {
    // These assignments occur after index.html installs its ordinary functions.
    // The overlay itself is never loaded for MAIN/RM/default access mode.
    window.loadSatelliteImages=async function () {
      const sector=el('sat-sector')?.value;
      if(!sector) return;
      if(el('sat-map-inner')) el('sat-map-inner').style.display='none';
      if(el('sat-status')) el('sat-status').textContent='Cached imagery only · no live connection';
      if(el('sat-image-meta')) el('sat-image-meta').textContent='';
      return render(el('sat-image-wrap'),sector,satMode==='ndvi'?'ndvi':'image','sat');
    };
    window.loadSatellite=async function () {
      satSectors=await api('/api/satellite/sectors');
      if(el('sat-kpis')) el('sat-kpis').innerHTML='<div class="kpi"><div class="kpi-label">Sentinel-2</div><div class="kpi-value">Cached only</div><div class="kpi-sub">Review instance has no provider credentials</div></div>';
      const select=el('sat-sector');
      if(!select) return;
      const previous=select.value;select.replaceChildren();
      for(const sector of satSectors) {const option=document.createElement('option');option.value=sector.name;option.textContent=sector.name;select.appendChild(option);}
      if(satSectors.some(s=>s.name===previous)) select.value=previous;
      if(el('sat-sectors-list')) {
        el('sat-sectors-list').replaceChildren();
        for(const sector of satSectors) {
          const button=document.createElement('button');button.className='btn';button.textContent=sector.name;
          button.setAttribute('onclick',`selectSatSector(${JSON.stringify(sector.name)})`);
          el('sat-sectors-list').appendChild(button);
        }
      }
      if(satMode==='leaflet') showSatMap();else await window.loadSatelliteImages();
      await loadSatelliteIntel();
    };
    if(typeof loaders!=='undefined') loaders.satellite=window.loadSatellite;
    window.loadDetailSatellite=()=>render(el('ds-image-wrap'),currentSector,dsSatMode==='ndvi'?'ndvi':'image','ds');
    const originalMode=window.setDSMode;
    window.setDSMode=function(mode) {originalMode(mode);return window.loadDetailSatellite();};
    const originalTab=window.detailTab;
    window.detailTab=function(tab) {
      if(tab!=='satellite') return originalTab(tab);
      currentDetailTab=tab;
      document.querySelectorAll('#detail-tabs .tab').forEach((node,index)=>node.classList.toggle('active',index===11));
      const target=el('detail-tab-content');if(!target || !currentDetailData) return;
      target.innerHTML='<div class="card"><div class="card-head">Satellite context</div><div style="display:flex;gap:8px;margin-bottom:12px"><button class="filter-btn active" id="ds-mode-true" onclick="setDSMode(\'true\')">True colour</button><button class="filter-btn" id="ds-mode-ndvi" onclick="setDSMode(\'ndvi\')">NDVI</button></div><div id="ds-image-wrap"></div></div>';
      dsSatMode='true';return window.loadDetailSatellite();
    };
    const originalObjectTab=window.objDetailTab;
    window.objDetailTab=async function(tab) {
      if(tab!=='satellite') return originalObjectTab(tab);
      currentObjectTab=tab;
      document.querySelectorAll('#obj-detail-tabs .tab').forEach((node,index)=>node.classList.toggle('active',index===3));
      const object=await getCurrentObject();const target=el('obj-detail-tab-content');if(!target)return;
      target.replaceChildren();
      if(!object?.sectors?.length) {missing(target,'');return;}
      await Promise.all(object.sectors.map(sector=>{
        const section=document.createElement('section');const heading=document.createElement('h3');heading.textContent=sector.name;
        const image=document.createElement('div');section.append(heading,image);target.appendChild(section);
        return render(image,sector.name);
      }));
    };
    // Initial routing runs before DOMContentLoaded; replace any already-open
    // satellite view immediately so it cannot retain a legacy 2024 default.
    if(typeof currentSection!=='undefined') {
      if(currentSection==='satellite') window.loadSatellite().catch(()=>missing(el('sat-image-wrap'),''));
      else if(currentSection==='detail' && currentDetailTab==='satellite') window.detailTab('satellite');
      else if(currentSection==='object-detail' && currentObjectTab==='satellite') window.objDetailTab('satellite');
    }
  }
  window.ForestReviewSatellite={caption,render};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start);else start();
})();
