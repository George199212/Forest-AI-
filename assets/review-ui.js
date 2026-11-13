/* Instance presentation and read-only review controls. Server middleware is authoritative. */
(function () {
  'use strict';
  const config=window.ForestInstance || {};
  const readOnly=config.readOnly === true;
  // Only known read/navigation actions stay available. Unknown controls fail closed.
  const reads=new Set(['nav','refreshCurrent','openObject','objDetailTab','openSector','detailTab',
    'clearObjectFilter','openRisk','openFinancialBreakdown','filterPhotos','openPhotoViewer',
    'showLightboxPhoto','stepLightbox','closeLightbox','openLightboxImg','toggleSnapshotSelection',
    'setSatMode','onSatSectorChange','showSatMap','selectSatSector','setDSMode','focusGpsOnMap',
    'showVehicleRoute','trkLoad','trkShow','trkOpenOnMap','pcSetFilter','pcRender','pcViewerOpen',
    'pcViewerShow','pcViewerStep','pcViewerClose','pcHi','openIntegration','setIntCategoryFilter',
    'rcGoReview','_toggleInspBox','closeSnapshotRisksModal','renderPhotos','Math.max','Math.min']);
  // LVM GEO and Meža karte: every control issues GET requests only (server middleware refuses the rest),
  // except these registration / incident actions, which stay visible, disabled and explained.
  const GEO_SECTIONS='#sec-lvm-geodata,#sec-forest-map';
  const DEMO_BLOCKED={'#lvm-import,#vmd-go-3,#fm-import,#fm-confirm':'registration','.fm-create-incident':'incident'};
  const DEMO_TEXT={registration:{lv:'Demo režīmā reģistrācija ir izslēgta',en:'Registration is disabled in demo mode (Demo režīmā reģistrācija ir izslēgta)'},
    incident:{lv:'Demo režīmā incidentu izveide ir izslēgta',en:'Incident creation is disabled in demo mode (Demo režīmā incidentu izveide ir izslēgta)'}};
  const STEP3_INPUTS='#vmd-sector-name,#vmd-responsible-first-name,#vmd-responsible-last-name';
  function demoText(kind) { return DEMO_TEXT[kind][(document.documentElement.lang||'').startsWith('lv')?'lv':'en']; }
  function demoBlocked(el) { return Object.keys(DEMO_BLOCKED).find(sel=>el.matches?.(sel)); }
  function demoApiBlocked(path) {
    if (/^\/api\/geodata\/forest-map\/gps\/violations\/incident\/?$/.test(path)) return 'incident';
    if (/^\/api\/geodata\/(vmd\/(import-selected|import|territories)|lvm\/(preview|import|apply|sectors\/))/.test(path)) return 'registration';
    return null;
  }
  function blockDemoAction(el, selector) {
    const kind=DEMO_BLOCKED[selector], text=demoText(kind);
    // Every write below happens only on change (the observer watches 'disabled'; no write loops).
    if (!el.hasAttribute('data-review-read')) el.setAttribute('data-review-read','');   // keep it visible
    if (el.getAttribute('data-review-demo-blocked')!==kind) el.setAttribute('data-review-demo-blocked',kind);
    if ('disabled' in el && !el.disabled) el.disabled=true;
    if (el.getAttribute('aria-disabled')!=='true') el.setAttribute('aria-disabled','true');
    if (el.title!==text) el.title=text;
    const next=el.nextElementSibling;
    if (!(next && next.classList.contains('review-demo-note'))) {
      const note=document.createElement('span');note.className='review-demo-note';note.textContent=text;note.setAttribute('role','note');
      el.after(note);
    }
  }
  function allowed(el) {
    if (demoBlocked(el)) return false;
    if (el.closest?.(GEO_SECTIONS)) return true;
    const handler=el.getAttribute('onclick') || '';
    if (!handler) return el.matches('select,input[type=search],input[type=date],input[type=range],.leaflet-control-zoom-in,.leaflet-control-zoom-out');
    // Inline event housekeeping is allowed; every actual call must be a known read.
    const calls=[...handler.matchAll(/([\w.]+)\s*\(/g)].map(m=>m[1]);
    return calls.length > 0 && calls.every(name=>reads.has(name) || ['history.back','event.stopPropagation','event.preventDefault'].includes(name));
  }
  function displayText(value) {
    if (typeof value !== 'string') return value;
    // Catalog remains unchanged. Review display must not imply an active connection.
    const map={CONNECTED:'Not configured',Connected:'Not configured',connected:'Not configured',
      'KRAUZERS Fleet GPS':'Fleet GPS (vendor unconfirmed)',
      'KRAUZERS (exact vendor TBD)':'Vendor unconfirmed',
      'Pieslēgts':'Not configured','Подключено':'Active connections',
      'Already live in production via bot.py — this catalog entry documents it, it is not managed through the generic adapter sync pipeline.':
        'Catalog capability only. Telegram is disabled in this review environment.',
      'Live token-check already exists via /api/satellite/token-check.':
        'Live satellite checks are disabled in this review environment.',
      'Do not mark Connected until the actual vendor/API is confirmed.':
        'Vendor/API confirmation required before configuration.',
      'TIMBRO is confirmed to use or be developing a forest audit system (LiDAR + GNSS + camera photofixation + estimation algorithms). No API/data contract is confirmed yet — do not mark Connected.':
        'TIMBRO uses or is developing a forest audit system (LiDAR, GNSS, camera imagery and estimation algorithms). No API or data contract is confirmed.'};
    return map[value] || value;
  }
  function sanitizeCatalog(data) {
    if (typeof data === 'string') return displayText(data);
    if (Array.isArray(data)) return data.map(sanitizeCatalog);
    if (data && typeof data === 'object') return Object.fromEntries(Object.entries(data).map(([key,value])=>[
      key,key==='confirmed_customer_use' ? null : sanitizeCatalog(value)]));
    return data;
  }
  if (readOnly) {
    document.documentElement.classList.add('forest-review');
    const style=document.createElement('style');
    style.textContent='.forest-review [data-review-action],.forest-review input[type=file],.forest-review label:has(input[type=file]),.forest-review a[href*="/api/report/pdf/"],.forest-review button:not([data-review-read]),.forest-review input[type=submit]{display:none!important}.forest-review body{padding-top:44px}.forest-review-banner{position:fixed;top:0;left:0;right:0;z-index:10000;padding:12px 16px;background:#22382c;color:#fff;border-bottom:1px solid #55745e;font:12px/20px system-ui}.forest-review .sidebar{top:44px;height:calc(100vh - 44px)}.forest-review [data-review-demo-blocked]{opacity:.55;cursor:not-allowed}.review-demo-note{display:block;margin-top:4px;font-size:12px;color:var(--text3,#6b7a70)}';
    document.head.appendChild(style);
    const originalFetch=window.fetch;
    window.fetch=async function(input,init) {
      const req=input instanceof Request ? input : null;
      const method=String(init?.method || req?.method || 'GET').toUpperCase();
      const url=new URL(req ? req.url : String(input),location.href);
      const forbidden=!['GET','HEAD'].includes(method) || /^\/api\/(report\/pdf\/|inspector\/analyze|satellite\/token-check)/.test(url.pathname);
      const demoKind=!['GET','HEAD'].includes(method) && demoApiBlocked(url.pathname);
      if (forbidden) return new Response(JSON.stringify({detail:demoKind?demoText(demoKind):'This action is disabled in the read-only review environment.'}),{status:403,headers:{'Content-Type':'application/json'}});
      const response=await originalFetch.call(this,input,init);
      if (url.origin===location.origin && /^\/api\/integrations(?:\/|$)/.test(url.pathname) && response.ok && response.headers.get('content-type')?.includes('application/json')) {
        const headers=new Headers(response.headers);
        headers.delete('content-length');headers.delete('content-encoding');
        return new Response(JSON.stringify(sanitizeCatalog(await response.json())),{status:response.status,headers});
      }
      return response;
    };
  }
  function process(root) {
    if (!root || root.nodeType!==1) return;
    const elements=[root,...root.querySelectorAll('button,[onclick],[role=button],input,textarea,[contenteditable]')];
    for (const el of elements) {
      if (!readOnly) continue;
      const blocked=demoBlocked(el);
      if (blocked) { blockDemoAction(el, blocked); continue; }
      if (el.closest?.(GEO_SECTIONS)) {
        if (el.matches(STEP3_INPUTS)) el.readOnly=true;
        else if (el.matches('button,[role=button],[onclick],input[type=button],input[type=submit]') && !el.hasAttribute('data-review-read')) el.setAttribute('data-review-read','');
        continue;
      }
      if (el.matches('textarea')) { el.readOnly=true; continue; }
      if (el.hasAttribute('contenteditable')) el.setAttribute('contenteditable','false');
      if (el.matches('button,[role=button],[onclick],input[type=button],input[type=submit],input[type=file]')) {
        if (allowed(el)) { if(!el.hasAttribute('data-review-read')) el.setAttribute('data-review-read',''); }
        else {
          if(!el.hasAttribute('data-review-action')) el.setAttribute('data-review-action','');
          // Write only on change: the observer watches 'disabled', so an unconditional write would loop.
          if ('disabled' in el && !el.disabled) el.disabled=true;
          if (el.getAttribute('aria-disabled')!=='true') el.setAttribute('aria-disabled','true');
        }
      } else if (el.matches('input:not([type=search]):not([type=date]):not([type=range])')) el.readOnly=true;
    }
  }
  function start() {
    if (config.displayName) {
      document.title=config.displayName;
      const logo=document.querySelector('.logo-name');
      if(logo) { logo.textContent=config.displayName;logo.style.cssText='white-space:normal;font-size:12px;line-height:16px'; }
      const brand=document.createElement('div');brand.textContent=config.displayName;brand.className='instance-display-name';
      brand.style.cssText='font-size:12px;color:var(--text3);margin-bottom:4px';
      document.querySelector('.topbar-left')?.prepend(brand);
    }
    if (!readOnly) return;
    const banner=document.createElement('div');banner.className='forest-review-banner';banner.setAttribute('role','note');
    banner.textContent='Demonstration environment · read-only · synthetic data (one anonymized real field test)';
    document.body.prepend(banner);
    process(document.body);
    // Capture protects controls before the observer processes dynamically added markup.
    document.addEventListener('click',event=>{
      const el=event.target.closest('button,[onclick],[role=button],input[type=submit],input[type=file]');
      if (el && !allowed(el)) {event.preventDefault();event.stopImmediatePropagation();}
    },true);
    // Forms are refused, except the LVM GEO cadastral search (it issues a GET).
    document.addEventListener('submit',event=>{if(event.target.closest?.('#sec-lvm-geodata')&&!event.target.querySelector(STEP3_INPUTS))return;event.preventDefault();event.stopImmediatePropagation();},true);
    new MutationObserver(list=>{
      for (const mutation of list) {
        if(mutation.type==='childList') mutation.addedNodes.forEach(process);
        else if(mutation.target.nodeType===1) process(mutation.target);
      }
    }).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['onclick','disabled']});
    // The current PDF generator embeds untranslated labels. Hide and refuse it in review.
    window.downloadPDF=()=>undefined;
  }
  window.ForestReview={allowed,displayText,demoApiBlocked,process};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start);else start();
})();
