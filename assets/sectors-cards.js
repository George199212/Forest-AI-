/*
 * Forest AI — Sectors as the entry point into the satellite workspace (Stage 1 prototype, branch
 * feature/sectors-workspace). NOT deployed.
 *
 * One list request (window.SECTOR_CARDS_URL; Stage 2: GET /api/sectors/cards + sector-summaries, owner D6),
 * cards with an honest preview, a real hash route #sectors/{id}, and a sector page that MOUNTS the Stage 5
 * workspace (SatWorkspace.mount, owner D1 — added by the Stage 5 session; until then a stub with a link-through).
 *
 * Rules: missing = "Nav pieejams", never 0; acquisition time ≠ processing time ≠ page refresh; suspected changes are
 * never called verified; colours come from SatWorkspace._worstColour (not re-implemented); no third-party basemap
 * snapshots on cards (Sentinel quicklook or polygon-only SVG); "Contains modified Copernicus Sentinel data {YEAR}".
 */
(function (global) {
  'use strict';

  // ── constants (owner D4/D5) ───────────────────────────────────────────────────────────────────────────────────
  var PREVIEW_MIN_PX = 64;           // D4: sector's longest side below this many Sentinel-2 pixels → polygon-only preview
  var S2_PIXEL_M = 10;               // Sentinel-2 10 m bands
  var PAGE_SIZE = 100;               // pagination above 100 sectors
  var LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
  var LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
  var OSM = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  var OPEN = ['SUSPECTED', 'FIELD_CHECK_REQUESTED'];
  var STATUSES = ['MONITORED', 'AWAITING_FIRST_DATA', 'NOT_MONITORED', 'STOPPED'];

  var T = {
    lv: {
      title: 'Sektori', search: 'Meklēt pēc nosaukuma vai kadastra / VMD ID', all: 'Visi', na: 'Nav pieejams',
      st_MONITORED: 'Monitorēts', st_AWAITING_FIRST_DATA: 'Gaida pirmos datus', st_NOT_MONITORED: 'Netiek monitorēts',
      st_STOPPED: 'Apturēts', queued: 'Pievienošanas uzdevums {id} gaida apstrādes procesu; satelīta teritorija vēl nav izveidota.', addMon: 'Pievienot monitoringam', adding: 'Pievieno…', added: 'Pievienots — gaida pirmos datus',
      lastS2: 'Pēdējais derīgais S2 uzņēmums', lastS1: 'Pēdējais S1 (radara) uzņēmums', suspected: 'Iespējamas izmaiņas (atvērtas)',
      confirmed: 'Apstiprinātas pārskatīšanā', noImage: 'Satelīta attēls vēl nav pieejams',
      tooSmall: 'Sentinel-2 10 m — sektors par mazu priekšskatījumam', noBoundary: 'Robeža nav saglabāta',
      falseC: 'viltus krāsas', trueC: 'patiesās krāsas', attribution: 'Contains modified Copernicus Sentinel data {year}',
      fixture: 'Testa teritorija, nav sektors (tikai Stage 1 fiktūra)', shown: 'Rādīti {a}–{b} no {n}', prev: '← Iepriekšējie',
      next: 'Nākamie →', none: 'Nav sektoru, kas atbilst filtram.', back: '← Sektori', openMap: 'Atvērt Meža kartē',
      panel: 'Informācija', close: 'Aizvērt', ha: 'ha', haStored: 'saglabātā vērtība', haArea: 'satelīta teritorijas platība',
      cadastre: 'Kadastrs', kvnog: 'kv. {kv} nog. {nog}',
      bSector: 'Sektors', bSat: 'Satelīta monitorings', bChanges: 'Izmaiņas', bRisks: 'Riski', bActivity: 'Aktivitāte',
      name: 'Nosaukums', identifier: 'Identifikators', area: 'Platība', regSource: 'Reģistrācijas avots', regDate: 'Reģistrēts',
      lastAcq: 'Pēdējais satelīta uzņēmums', lastAnalysis: 'Pēdējā veiksmīgā analīze', lastCheck: 'Pēdējā sistēmas pārbaude',
      system: 'sistēma', sensors: 'Izmantotie sensori', obsStatus: 'Novērojuma statuss', noAnalysis: 'Analīze nav veikta',
      noChanges: 'Izmaiņas nav konstatētas', changesNote: 'Automātiska noteikšana, dabā nav pārbaudīts.',
      noRisks: 'Šim sektoram nav saistītu risku.', risksNote: 'Automātiskie satelīta riski ir izslēgti; tikai cilvēka izveidoti.',
      gps: 'GPS sesijas', photos: 'Foto', showOnMap: 'Skatīt Meža kartē', evidence: 'Pierādījumi',
      notMonitored: 'Šis sektors netiek monitorēts', notMonitoredHint: 'Satelīta dati šim sektoram netiek ielādēti. Pievienojiet to monitoringam, lai sāktu Sentinel-1/-2 novērošanu.',
      awaiting: 'Notiek vēsturisko datu ielāde. Darbvieta parādīsies, kad būs pirmais apstrādātais uzņēmums.',
      stopped: 'Monitorings ir apturēts. Vēsturiskie dati saglabāti.',
      mountStub: 'Šeit tiek iemontēta Stage 5 satelīta darbvieta šai teritorijai', mountStubNote: 'SatWorkspace.mount(el, {areaId: {id}}) — pievieno Stage 5 sesija pirms laidiena (D1). Prototipā: saite uz darbvietu.',
      openWs: 'Atvērt satelīta darbvietā →', linkSECTOR: 'saistīts ar sektoru', linkLVM_GEO: 'LVM GEO teritorija (precīza VMD ID sakritība)',
      linkEVAL_BBOX: 'novērtējuma teritorija', dupName: 'Vēl {n} sektors(-i) ar šo nosaukumu — ar nosaukumu saistītie dati (GPS, foto, riski) var piederēt arī tiem.',
      boundaryMismatch: 'Monitoringa robeža atšķiras no sektora robežas.', notFound: 'Sektors nav atrasts.', loading: 'Ielādē…',
      error: 'Kļūda', d_OK: 'Dati kārtībā', d_NO_DATA_YET: 'Vēl nav datu', d_BACKFILL_OR_FETCH_IN_PROGRESS: 'Notiek ielāde',
      d_STOPPED: 'Apturēts', s2: 'S2 optiskais', s1: 'S1 radars', open: 'Atvērt', provider_VMD_OPEN_DATA: 'VMD atvērtie dati (LVM GEO)',
      provider_VMD_LOCAL: 'VMD lokālā kopija (LVM GEO)', provider_BOUNDARY_PLAN: 'Robežu plāns (skenēts)', provider_EVAL_BBOX: 'Novērtējuma teritorija',
      allSectors: 'Visi sektori', lastGps: 'Pēdējās GPS sesijas', m_gps: 'GPS sesijas', m_risks: 'Riski',
      m_trucks: 'Kokvedēju atskaites', m_timber: 'Kokmateriāli', m_comments: 'Komentāri', m_compare: 'Foto',
      photoCompare: 'foto salīdzināšana', allPhotos: 'Visi foto ({n})', backTo: '← {name}',
      objShown: 'Objekts: {name} · {n} sektori', objNone: 'Sektori bez objekta · {n}', viewPlan: 'Skatīt plānu ar sektoriem',
      clearFilter: '✕ Notīrīt filtru', unavailable: 'Dati nav pieejami',
      lang: 'EN'
    },
    en: {
      title: 'Sectors', search: 'Search by name or cadastre / VMD ID', all: 'All', na: 'Not available',
      st_MONITORED: 'Monitored', st_AWAITING_FIRST_DATA: 'Awaiting first data', st_NOT_MONITORED: 'Not monitored',
      st_STOPPED: 'Stopped', queued: 'Add job {id} is waiting for the worker; the satellite area has not been created yet.', addMon: 'Add to monitoring', adding: 'Adding…', added: 'Added — awaiting first data',
      lastS2: 'Last valid S2 acquisition', lastS1: 'Last S1 (radar) acquisition', suspected: 'Suspected changes (open)',
      confirmed: 'Confirmed by review', noImage: 'Satellite image not available yet',
      tooSmall: 'Sentinel-2 10 m — sector too small for a preview', noBoundary: 'No boundary stored',
      falseC: 'false colour', trueC: 'true colour', attribution: 'Contains modified Copernicus Sentinel data {year}',
      fixture: 'Test area, not a sector (Stage 1 fixture only)', shown: 'Showing {a}–{b} of {n}', prev: '← Previous',
      next: 'Next →', none: 'No sectors match the filter.', back: '← Sectors', openMap: 'Open in Forest Map',
      panel: 'Details', close: 'Close', ha: 'ha', haStored: 'stored value', haArea: 'satellite area size',
      cadastre: 'Cadastre', kvnog: 'comp. {kv}-{nog}',
      bSector: 'Sector', bSat: 'Satellite monitoring', bChanges: 'Changes', bRisks: 'Risks', bActivity: 'Activity',
      name: 'Name', identifier: 'Identifier', area: 'Area', regSource: 'Registration source', regDate: 'Registered',
      lastAcq: 'Last satellite acquisition', lastAnalysis: 'Last successful analysis', lastCheck: 'Last system check',
      system: 'system', sensors: 'Sensors used', obsStatus: 'Observation status', noAnalysis: 'No analysis yet',
      noChanges: 'No changes detected', changesNote: 'Automated detection, not verified on the ground.',
      noRisks: 'No risks linked to this sector.', risksNote: 'Automatic satellite risks are off; human-created only.',
      gps: 'GPS sessions', photos: 'Photos', showOnMap: 'Show in Forest Map', evidence: 'Evidence',
      notMonitored: 'This sector is not monitored', notMonitoredHint: 'No satellite data is fetched for this sector. Add it to monitoring to start Sentinel-1/-2 observation.',
      awaiting: 'Backfill in progress. The workspace appears once the first acquisition is processed.',
      stopped: 'Monitoring is stopped. Historical data is kept.',
      mountStub: 'The Stage 5 satellite workspace for this area mounts here', mountStubNote: 'SatWorkspace.mount(el, {areaId: {id}}) — added by the Stage 5 session before its release (D1). Prototype: link-through.',
      openWs: 'Open in the satellite workspace →', linkSECTOR: 'linked to the sector', linkLVM_GEO: 'LVM GEO area (exact VMD ID match)',
      linkEVAL_BBOX: 'evaluation area', dupName: '{n} more sector(s) share this name — name-keyed data (GPS, photos, risks) may belong to them too.',
      boundaryMismatch: 'The monitoring boundary differs from the sector boundary.', notFound: 'Sector not found.', loading: 'Loading…',
      error: 'Error', d_OK: 'Data OK', d_NO_DATA_YET: 'No data yet', d_BACKFILL_OR_FETCH_IN_PROGRESS: 'Fetching',
      d_STOPPED: 'Stopped', s2: 'S2 optical', s1: 'S1 radar', open: 'Open', provider_VMD_OPEN_DATA: 'VMD open data (LVM GEO)',
      provider_VMD_LOCAL: 'VMD local copy (LVM GEO)', provider_BOUNDARY_PLAN: 'Boundary plan (scanned)', provider_EVAL_BBOX: 'Evaluation area',
      allSectors: 'All sectors', lastGps: 'Latest GPS sessions', m_gps: 'GPS sessions', m_risks: 'Risks',
      m_trucks: 'Truck reports', m_timber: 'Timber', m_comments: 'Comments', m_compare: 'Photos',
      photoCompare: 'photo comparison', allPhotos: 'All photos ({n})', backTo: '← {name}',
      objShown: 'Object: {name} · {n} sectors', objNone: 'Sectors without an object · {n}', viewPlan: 'View plan with sectors',
      clearFilter: '✕ Clear filter', unavailable: 'Data not available',
      lang: 'LV'
    }
  };

  // ── state ─────────────────────────────────────────────────────────────────────────────────────────────────────
  function store(k, v) {
    try { if (v === undefined) return global.localStorage.getItem(k); global.localStorage.setItem(k, v); } catch (e) { /* private mode */ }
    return null;
  }
  // Same key as the Stage 5 workspace, so the sector page and the mounted workspace stay in one language.
  var S = {lang: store('satMonitoring.lang') === 'en' ? 'en' : 'lv', cards: null, q: '', status: 'ALL', page: 0,
           scroll: 0, map: null, seq: 0};
  function t(k, vars) {
    var s = (T[S.lang] && T[S.lang][k]) || T.en[k] || k;
    if (vars) Object.keys(vars).forEach(function (n) { s = s.split('{' + n + '}').join(vars[n]); });
    return s;
  }
  function esc(v) { return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function na() { return '<span class="sc-na">' + esc(t('na')) + '</span>'; }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  // ── pure rules (tested in tests/test_sectors_cards.js) ───────────────────────────────────────────────────────
  // Status only from stored data: area row, its active flag, OK acquisitions, an open ADD_AREA job.
  function deriveStatus(card) {
    var m = card && card.monitoring;
    if (!m) return card && card.queued_job_id ? 'AWAITING_FIRST_DATA' : 'NOT_MONITORED';
    if (m.active === false || m.removed_at_utc) return 'STOPPED';
    return isNum(m.ok_acquisitions) && m.ok_acquisitions > 0 ? 'MONITORED' : 'AWAITING_FIRST_DATA';
  }
  function longestSidePx(card) {
    var e = card && card.extent_m;
    return e && isNum(e.w) && isNum(e.h) ? Math.max(e.w, e.h) / S2_PIXEL_M : null;
  }
  // D4: image only when a stored Sentinel image exists AND the sector is at least PREVIEW_MIN_PX across.
  function previewSource(card) {
    if (!card || !card.ring || card.ring.length < 3) return {kind: 'none', reason: 'noBoundary'};
    var m = card.monitoring, p = m && m.preview;
    if (!p || !p.acq_id) return {kind: 'polygon', reason: 'noImage'};
    var px = longestSidePx(card);
    if (px === null || px < PREVIEW_MIN_PX) return {kind: 'polygon', reason: 'tooSmall', px: px};
    var tc = p.kind === 'truecolor';
    return {kind: 'image', composite: tc ? 'truecolor' : 'falsecolor', acq_id: p.acq_id, sensing_time_utc: p.sensing_time_utc,
            url: '/api/sat-monitoring/file/' + encodeURIComponent(p.acq_id) + '/' + (tc ? 'truecolor' : 'quicklook'),
            bbox: m.grid_bbox || null};
  }
  // Counts: a number only when monitoring data exists; otherwise null (rendered "Nav pieejams", never 0).
  function counts(card) {
    var m = card && card.monitoring;
    if (!m) return {suspected: null, confirmed: null};
    return {suspected: isNum(m.open_suspected) ? m.open_suspected : null, confirmed: isNum(m.confirmed) ? m.confirmed : null};
  }
  function worstColour(card) {
    var m = card && card.monitoring, ws = global.SatWorkspace;
    if (!m || !m.open_events || !m.open_events.length || !ws || typeof ws._worstColour !== 'function') return null;
    return ws._worstColour(m.open_events);                     // Stage 5 §4.4 — imported, not re-implemented
  }
  function identifierText(card) {
    var id = card && card.identifier;
    if (!id) return null;
    var parts = [];
    if (id.cadastre) parts.push(id.cadastre);
    if (id.kvart !== null && id.kvart !== undefined && id.nog !== null && id.nog !== undefined) parts.push(t('kvnog', {kv: id.kvart, nog: id.nog}));
    return parts.length ? parts.join(' · ') : (id.source_feature_id || null);
  }
  function matches(card, q, status) {
    if (status && status !== 'ALL' && deriveStatus(card) !== status) return false;
    if (!q) return true;
    var hay = [card.name, identifierText(card), card.identifier && card.identifier.source_feature_id].join(' ').toLowerCase();
    return q.toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) >= 0; });
  }

  // ── time (same display rule as Stage 5: Europe/Riga + UTC; date-only on cards) ──────────────────────────────
  function fmtTime(s) {
    var ws = global.SatWorkspace;
    if (ws && typeof ws._fmtTime === 'function') return ws._fmtTime(s);
    var d = s ? new Date(String(s)) : null;
    return d && !isNaN(d) ? d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC' : null;
  }
  function fmtDate(s) {
    var d = s ? new Date(String(s)) : null;
    if (!d || isNaN(d)) return null;
    return new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Riga', year: 'numeric', month: '2-digit', day: '2-digit'}).format(d);
  }
  function timeHtml(s) { var f = fmtTime(s); return f ? '<span class="sc-time">' + esc(f) + '</span>' : na(); }
  function dateHtml(s) { var f = fmtDate(s); return f ? '<span class="sc-time">' + esc(f) + '</span>' : na(); }
  function haText(card) {
    if (!isNum(card.area_ha)) return null;
    if (card.area_ha > 0 && card.area_ha < 0.005) return (S.lang === 'lv' ? '<0,01' : '<0.01') + ' ha';   // stored value, not rounded to 0
    return card.area_ha.toLocaleString(S.lang === 'lv' ? 'lv-LV' : 'en-GB', {maximumFractionDigits: 2}) + ' ha';
  }

  // ── previews ──────────────────────────────────────────────────────────────────────────────────────────────────
  // Linear lon/lat → box mapping is exact for the CRS84 request grid; for the polygon-only SVG it is a local
  // equirectangular view (display only; extent and scale bar come from the geodesic extent_m).
  function svgPath(ring, bbox, w, h) {
    var x0 = bbox[0], y0 = bbox[1], dx = (bbox[2] - bbox[0]) || 1e-9, dy = (bbox[3] - bbox[1]) || 1e-9;
    return ring.map(function (p, i) {
      return (i ? 'L' : 'M') + ((p[0] - x0) / dx * w).toFixed(1) + ' ' + ((1 - (p[1] - y0) / dy) * h).toFixed(1);
    }).join(' ') + ' Z';
  }
  function fitBox(bbox, aspect) {                  // pad the sector bbox to the card aspect (w/h in metres-ish)
    var cx = (bbox[0] + bbox[2]) / 2, cy = (bbox[1] + bbox[3]) / 2, k = Math.cos(cy * Math.PI / 180);
    var w = (bbox[2] - bbox[0]) * k, h = bbox[3] - bbox[1];
    if (w / h > aspect) h = w / aspect; else w = h * aspect;
    w *= 1.25; h *= 1.25;
    return [cx - w / 2 / k, cy - h / 2, cx + w / 2 / k, cy + h / 2];
  }
  function scaleBar(widthM, boxW) {
    var target = widthM / 4, steps = [5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000], m = steps[0];
    steps.forEach(function (s) { if (s <= target) m = s; });
    return {m: m, px: m / widthM * boxW, label: m >= 1000 ? m / 1000 + ' km' : m + ' m'};
  }
  function polygonPreview(card, reason) {
    var W = 320, H = 180, TOP = 26, BOTTOM = 22, IH = H - TOP - BOTTOM, box = fitBox(card.bbox, W / IH);
    var k = Math.cos((box[1] + box[3]) / 2 * Math.PI / 180), widthM = (box[2] - box[0]) * k * 111320;
    var sb = scaleBar(widthM, W), label = t(reason);
    return '<div class="sc-prev sc-prev-poly" role="img" aria-label="' + esc(label) + '">' +
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none"><path class="sc-poly" transform="translate(0,' + TOP + ')" d="' + svgPath(card.ring, box, W, IH) + '"/>' +
      '<g class="sc-scale" transform="translate(10,' + (H - 12) + ')"><line x1="0" y1="0" x2="' + sb.px.toFixed(1) + '" y2="0"/>' +
      '<text x="' + (sb.px + 5).toFixed(1) + '" y="4">' + esc(sb.label) + '</text></g></svg>' +
      '<span class="sc-prev-label">' + esc(label) + '</span>' +
      (haText(card) ? '<span class="sc-prev-ha">' + esc(haText(card)) + '</span>' : '') + '</div>';
  }
  function imagePreview(card, src) {
    var W = 320, H = 180, bb = src.bbox, aspect = W / H;
    if (bb) aspect = (bb[2] - bb[0]) * Math.cos((bb[1] + bb[3]) / 2 * Math.PI / 180) / ((bb[3] - bb[1]) || 1e-9);
    var overlay = bb ? '<svg class="sc-overlay" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none"><path class="sc-poly sc-poly-img" d="' +
      svgPath(card.ring, bb, W, H) + '"/></svg>' : '';
    var year = src.sensing_time_utc ? String(src.sensing_time_utc).slice(0, 4) : '';
    return '<div class="sc-prev sc-prev-img"><div class="sc-imgbox" style="aspect-ratio:' + aspect.toFixed(4) + '">' +
      '<img loading="lazy" decoding="async" src="' + esc(src.url) + '" alt="" onerror="this.closest(\'.sc-prev\').classList.add(\'sc-img-failed\')">' + overlay + '</div>' +
      '<span class="sc-prev-cap">Sentinel-2 · ' + esc(fmtDate(src.sensing_time_utc) || '—') +
      (src.composite === 'falsecolor' ? ' · ' + esc(t('falseC')) : '') + '</span>' +
      '<span class="sc-prev-attr">' + esc(t('attribution', {year: year})) + '</span></div>';
  }
  function previewHtml(card) {
    var src = previewSource(card);
    if (src.kind === 'image') return imagePreview(card, src);
    if (src.kind === 'polygon') return polygonPreview(card, src.reason);
    return '<div class="sc-prev sc-prev-none"><span class="sc-prev-label">' + esc(t('noBoundary')) + '</span></div>';
  }

  // ── list ──────────────────────────────────────────────────────────────────────────────────────────────────────
  function scroller() { return document.querySelector('.content') || document.scrollingElement; }
  function chip(status) { return '<span class="sc-chip sc-chip-' + status.toLowerCase() + '">' + esc(t('st_' + status)) + '</span>'; }
  function countHtml(v) { return isNum(v) ? '<b>' + v + '</b>' : na(); }
  function cardHtml(card) {
    var st = deriveStatus(card), m = card.monitoring, c = counts(card), wc = worstColour(card), idt = identifierText(card);
    var href = '#sectors/' + encodeURIComponent(card.id);
    var mon = st === 'NOT_MONITORED' ? '' :
      '<dl class="sc-facts">' +
        '<div><dt>' + esc(t('lastS2')) + '</dt><dd>' + dateHtml(m && m.last_valid_s2 && m.last_valid_s2.sensing_time_utc) + '</dd></div>' +
        '<div class="sc-sub"><dt>' + esc(t('lastS1')) + '</dt><dd>' + dateHtml(m && m.last_s1 && m.last_s1.sensing_time_utc) + '</dd></div>' +
        '<div><dt>' + (wc ? '<span class="sc-dot" style="--c:' + esc(wc.color) + '"></span>' : '') + esc(t('suspected')) + '</dt><dd>' + countHtml(c.suspected) + '</dd></div>' +
        '<div><dt>' + esc(t('confirmed')) + '</dt><dd>' + countHtml(c.confirmed) + '</dd></div>' +
      '</dl>';
    return '<li class="sc-card' + (card._fixture_only ? ' sc-fixture' : '') + '">' +
      '<a class="sc-link" href="' + href + '" data-id="' + esc(card.id) + '">' + previewHtml(card) +
        '<div class="sc-body"><div class="sc-name">' + esc(card.name) + '</div>' +
        '<div class="sc-meta">' + (idt ? '<span>' + esc(idt) + '</span>' : na()) + ' · ' + (haText(card) ? esc(haText(card)) : na()) + '</div>' +
        (card._fixture_only ? '<div class="sc-fixture-note">' + esc(t('fixture')) + '</div>' : '') +
        '<div class="sc-status">' + chip(st) + '</div>' + mon + '</div></a>' +
      (st === 'NOT_MONITORED' && !card._fixture_only ? '<button class="sc-btn sc-btn2" data-add="' + esc(card.id) + '">' + esc(t('addMon')) + '</button>' : '') +
      '</li>';
  }
  function filtered() {
    return (S.cards || []).filter(function (c) {
      if (S.plan !== undefined && (c._fixture_only || (c.boundary_plan_id === undefined ? null : c.boundary_plan_id) !== S.plan)) return false;
      return matches(c, S.q, S.status);
    });
  }
  function objectBanner() {
    if (S.plan === undefined) return '';
    var n = filtered().length, o = S.object || {};
    return '<div class="sc-objbar"><span>' + esc(S.plan === null ? t('objNone', {n: n}) : t('objShown', {name: o.name || ('#' + S.plan), n: n})) + '</span>' +
      (o.annotatedUrl ? '<a class="sc-btn sc-ghost" href="' + esc(o.annotatedUrl) + '" target="_blank" rel="noopener">' + esc(t('viewPlan')) + '</a>' : '') +
      '<button class="sc-btn sc-ghost" data-act="clear-object">' + esc(t('clearFilter')) + '</button></div>';
  }
  function toolbar() {
    var n = {ALL: (S.cards || []).length};
    STATUSES.forEach(function (s) { n[s] = (S.cards || []).filter(function (c) { return deriveStatus(c) === s; }).length; });
    return '<div class="sc-toolbar"><input class="sc-search" type="search" value="' + esc(S.q) + '" placeholder="' + esc(t('search')) + '" aria-label="' + esc(t('search')) + '">' +
      '<div class="sc-filters" role="group">' + ['ALL'].concat(STATUSES).map(function (s) {
        return '<button class="sc-filter' + (S.status === s ? ' on' : '') + '" data-status="' + s + '" aria-pressed="' + (S.status === s) + '">' +
          esc(s === 'ALL' ? t('all') : t('st_' + s)) + ' <small>' + n[s] + '</small></button>';
      }).join('') + '</div><button class="sc-btn sc-ghost" data-act="lang">' + esc(t('lang')) + '</button></div>';
  }
  function renderCards(el) {
    var rows = filtered(), pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    if (S.page >= pages) S.page = pages - 1;
    var a = S.page * PAGE_SIZE, slice = rows.slice(a, a + PAGE_SIZE);
    var grid = el.querySelector('.sc-grid-wrap');
    grid.innerHTML = objectBanner() + (rows.length ? '<ul class="sc-grid">' + slice.map(cardHtml).join('') + '</ul>' : '<p class="sc-empty">' + esc(t('none')) + '</p>') +
      (rows.length > PAGE_SIZE ? '<div class="sc-pager"><button class="sc-btn sc-ghost" data-page="-1"' + (S.page ? '' : ' disabled') + '>' + esc(t('prev')) +
        '</button><span>' + esc(t('shown', {a: a + 1, b: a + slice.length, n: rows.length})) + '</span><button class="sc-btn sc-ghost" data-page="1"' +
        (S.page < pages - 1 ? '' : ' disabled') + '>' + esc(t('next')) + '</button></div>' : '');
    grid.querySelectorAll('[data-act=clear-object]').forEach(function (b) { b.onclick = function () { if (global.clearObjectFilter) global.clearObjectFilter(); }; });
    grid.querySelectorAll('[data-add]').forEach(function (b) { b.onclick = function (e) { e.preventDefault(); addToMonitoring(b.getAttribute('data-add'), b); }; });
    grid.querySelectorAll('[data-page]').forEach(function (b) { b.onclick = function () { S.page += +b.getAttribute('data-page'); S.scroll = 0; renderCards(el); scroller().scrollTop = 0; }; });
    grid.querySelectorAll('.sc-link').forEach(function (a) { a.onclick = function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;    // new tab etc. keeps the real href
      e.preventDefault(); S.scroll = scroller().scrollTop; S.cameFromList = true; openSector(a.getAttribute('data-id'), true);
    }; });
  }
  async function loadCards(force) {
    if (S.cards && !force) return S.cards;
    var url = global.SECTOR_CARDS_URL || '/api/sectors/cards';
    var r = await fetch(url, {credentials: 'same-origin', cache: 'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    var d = await r.json();
    S.cards = d.sectors || d;
    return S.cards;
  }
  function hideLegacyCreate(el) {           // O6 behind SECTOR_LEGACY_MODULES (D2/D9); nothing removed
    var sec = el.closest('.section'), first = sec && sec.querySelector('.card');
    if (first && first.querySelector('#create-sector-form')) first.style.display = global.SECTOR_LEGACY_MODULES ? '' : 'none';
  }
  async function renderList(el, opts) {
    if (!el) return;
    hideLegacyCreate(el);
    var pt = document.getElementById('page-title'); if (pt) pt.textContent = t('title');
    var head = el.closest('.card') && el.closest('.card').querySelector('.card-head > span');
    if (head) head.innerHTML = '<span class="dot"></span> ' + esc(t('allSectors'));
    var plan = opts && Object.prototype.hasOwnProperty.call(opts, 'plan') ? opts.plan : undefined;
    if (plan !== S.plan) { S.page = 0; S.scroll = 0; }
    S.plan = plan; S.object = opts && opts.object;
    el.classList.add('sc-root');
    el.innerHTML = '<div class="sc-list">' + toolbar() + '<div class="sc-grid-wrap"><div class="sc-loading">' + esc(t('loading')) + '</div></div></div>';
    bindToolbar(el);
    try { await loadCards(opts && opts.force); } catch (e) {
      el.querySelector('.sc-grid-wrap').innerHTML = '<p class="sc-error">' + esc(t('error')) + ': ' + esc(e.message) + '</p>'; return;
    }
    el.querySelector('.sc-toolbar').outerHTML = toolbar();
    bindToolbar(el);
    renderCards(el);
    if (opts && opts.restore) requestAnimationFrame(function () { scroller().scrollTop = S.scroll; });
  }
  function bindToolbar(el) {
    var q = el.querySelector('.sc-search'), timer = null;
    if (q) q.oninput = function () { clearTimeout(timer); timer = setTimeout(function () { S.q = q.value; S.page = 0; renderCards(el); }, 120); };
    el.querySelectorAll('[data-status]').forEach(function (b) { b.onclick = function () {
      S.status = b.getAttribute('data-status'); S.page = 0;
      el.querySelectorAll('[data-status]').forEach(function (x) { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b); });
      renderCards(el);
    }; });
    el.querySelectorAll('[data-act=lang]').forEach(function (b) { b.onclick = function () { S.lang = S.lang === 'lv' ? 'en' : 'lv'; store('satMonitoring.lang', S.lang); renderList(el); }; });
  }

  // ── add to monitoring (existing POST /api/sat-monitoring/areas — the same flow as LVM GEO / Stage 5) ──────────
  async function addToMonitoring(id, btn) {
    var card = (S.cards || []).filter(function (c) { return String(c.id) === String(id); })[0];
    if (!card || card._fixture_only) return;
    if (btn) { btn.disabled = true; btn.textContent = t('adding'); }
    try {
      var r = await fetch('/api/sat-monitoring/areas', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: 'SECTOR', source_ref: String(card.id), name: card.name})});
      var d = {}; try { d = await r.json(); } catch (e) { d = {}; }
      if (!r.ok) throw new Error(d.error || d.detail || ('HTTP ' + r.status));
      card.queued_job_id = d.job_id || d.id || true;           // shown as "Gaida pirmos datus" until the worker creates the area
      if (btn) btn.textContent = t('added');
      return d;
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = t('addMon') + ' — ' + t('error') + ': ' + e.message; }
      throw e;
    }
  }

  // ── sector page ───────────────────────────────────────────────────────────────────────────────────────────────
  function pageSection() {
    var sec = document.getElementById('sec-sector-page');
    if (!sec) {
      sec = document.createElement('div'); sec.className = 'section'; sec.id = 'sec-sector-page';
      var anchor = document.getElementById('sec-sectors'); anchor.parentNode.insertBefore(sec, anchor.nextSibling);
    }
    return sec;
  }
  function cleanupPage() {
    if (S.map) { try { S.map.remove(); } catch (e) { /* gone */ } S.map = null; }
    var ws = global.SatWorkspace;
    if (S.mounted && ws && typeof ws.unmount === 'function') { try { ws.unmount(); } catch (e) { /* gone */ } }
    S.mounted = false;
  }
  var leafletP = null;
  function leaflet() {
    if (global.L) return Promise.resolve(global.L);
    if (leafletP) return leafletP;
    leafletP = new Promise(function (res, rej) {
      if (!document.querySelector('link[href="' + LEAFLET_CSS + '"]')) { var c = document.createElement('link'); c.rel = 'stylesheet'; c.href = LEAFLET_CSS; document.head.appendChild(c); }
      var s = document.createElement('script'); s.src = LEAFLET_JS; s.onload = function () { res(global.L); }; s.onerror = rej; document.head.appendChild(s);
    });
    return leafletP;
  }
  async function getJson(url) {
    var r = await fetch(url, {credentials: 'same-origin', cache: 'no-store'}), d = null;
    try { d = await r.json(); } catch (e) { d = null; }
    if (!r.ok || (d && d.error === 'Not found')) { var err = new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status)); err.status = r.status; throw err; }
    return d;
  }
  function header(card, st) {
    var idt = identifierText(card), m = card.monitoring;
    var mapHref = m && m.area_id && st !== 'NOT_MONITORED' ? '#forest-map?sat_area=' + m.area_id : '#forest-map';
    return '<header class="sc-head"><a class="sc-back" href="#sectors" data-act="back">' + esc(t('back')) + '</a>' +
      '<h2 class="sc-title">' + esc(card.name) + '</h2>' + (idt ? '<span class="sc-hmeta">' + esc(idt) + '</span>' : '') +
      (haText(card) ? '<span class="sc-hmeta">' + esc(haText(card)) + '</span>' : '') + chip(st) +
      (card._fixture_only ? '<span class="sc-fixture-note">' + esc(t('fixture')) + '</span>' : '') +
      '<span class="sc-hspace"></span><a class="sc-btn sc-ghost" href="' + mapHref + '">' + esc(t('openMap')) + '</a>' +
      '<button class="sc-btn sc-ghost sc-drawer-btn" data-act="drawer" aria-expanded="false">' + esc(t('panel')) + '</button>' +
      '<button class="sc-btn sc-ghost" data-act="lang">' + esc(t('lang')) + '</button></header>';
  }
  function block(title, body) { return '<section class="sc-block"><h3>' + esc(title) + '</h3>' + body + '</section>'; }
  function row(k, v) { return '<div class="sc-row"><span>' + esc(k) + '</span><span>' + v + '</span></div>'; }
  function rowT(k, v) { return '<div class="sc-row sc-row-t"><span>' + esc(k) + '</span><span>' + v + '</span></div>'; }
  function sectorBlock(card, dup) {
    var p = card.provenance || {};
    return block(t('bSector'),
      row(t('name'), esc(card.name)) + row(t('identifier'), identifierText(card) ? esc(identifierText(card)) : na()) +
      row(t('area'), haText(card) ? esc(haText(card)) + ' <small>(' + esc(card.area_ha_source === 'satellite_area' ? t('haArea') : t('haStored')) + ')</small>' : na()) +
      row(t('regSource'), p.provider ? esc(t('provider_' + p.provider)) : na()) +
      rowT(t('regDate'), timeHtml(p.imported_at || card.created_at)) +
      (dup ? '<p class="sc-warn">' + esc(t('dupName', {n: dup})) + '</p>' : ''));
  }
  function satBlock(card, area, health) {
    var m = card.monitoring;
    if (!m) return block(t('bSat'), card.queued_job_id
      ? row(t('obsStatus'), esc(t('st_AWAITING_FIRST_DATA'))) + '<p class="sc-small">' + esc(t('queued', {id: card.queued_job_id === true ? '' : '#' + card.queued_job_id})) + '</p>'
      : '<p class="sc-muted">' + esc(t('st_NOT_MONITORED')) + '</p>');
    var a = area && area.area, tl = (area && area.timeline) || [], last = {};
    var minValid = area && area.config && isNum(area.config.min_valid_pct) ? area.config.min_valid_pct : m.min_valid_pct;
    // D5: S2 = last VALID optical acquisition (valid_pct_inside ≥ min_valid_pct), S1 = last OK radar; never one combined date
    tl.forEach(function (x) {
      if (x.status !== 'OK') return;
      if (x.sensor === 'S2' && !(isNum(x.valid_pct_inside) && isNum(minValid) && x.valid_pct_inside >= minValid)) return;
      if (!last[x.sensor] || x.sensing_time_utc > last[x.sensor]) last[x.sensor] = x.sensing_time_utc;
    });
    var catalog = ((health && health.provider_status) || []).filter(function (p) { return p.key === 'catalog'; })[0];
    var sysCheck = catalog ? [catalog.last_ok_utc, catalog.last_error_utc].filter(Boolean).sort().pop() : null;
    var used = ['S2', 'S1'].filter(function (s) { return last[s]; }).map(function (s) { return t(s.toLowerCase()); });
    var analysis = area ? area.last_successful_analysis_utc : undefined;
    return block(t('bSat'),
      row(t('obsStatus'), a ? esc(t('d_' + a.data_status)) : na()) +
      '<p class="sc-small">' + esc(t('link' + m.link)) + ' · #' + esc(m.area_id) + '</p>' +
      rowT(t('lastS2'), timeHtml(last.S2)) + rowT(t('lastS1'), timeHtml(last.S1)) +
      rowT(t('lastAnalysis'), analysis ? timeHtml(analysis) : (analysis === null ? '<span class="sc-muted">' + esc(t('noAnalysis')) + '</span>' : na())) +
      rowT(t('lastCheck') + ' (' + t('system') + ')', timeHtml(sysCheck)) +
      row(t('sensors'), used.length ? esc(used.join(', ')) : na()));
  }
  function changesBlock(card, area) {
    if (!card.monitoring) return '';
    if (!area) return block(t('bChanges'), na());
    var open = (area.events || []).filter(function (e) { return OPEN.indexOf(e.status) >= 0; });
    var analysed = !!area.last_successful_analysis_utc, ws = global.SatWorkspace;
    if (!open.length) return block(t('bChanges'), '<p class="sc-muted">' + esc(analysed ? t('noChanges') : t('noAnalysis')) + '</p>');
    return block(t('bChanges') + ' · ' + open.length, '<p class="sc-small">' + esc(t('changesNote')) + '</p><ul class="sc-events">' + open.map(function (e) {
      var c = ws && typeof ws._changeColour === 'function' ? ws._changeColour(e) : null;
      var haV = isNum(e.changed_area_ha) ? e.changed_area_ha.toFixed(2) + ' ha' : null;
      return '<li><a href="#sat-monitoring?event=' + encodeURIComponent(e.id) + '" data-event="' + esc(e.id) + '">' +
        (c ? '<span class="sc-dot" style="--c:' + esc(c.color) + '"></span>' : '') + '<b>#' + esc(e.id) + '</b> ' +
        '<span>' + dateHtml(e.first_after_time_utc) + '</span> <span>' + (haV ? esc(haV) : na()) + '</span></a></li>';
    }).join('') + '</ul>');
  }
  function risksBlock(detail) {
    var risks = (detail && detail.risks) || [];
    if (!risks.length) return block(t('bRisks'), '<p class="sc-muted">' + esc(t('noRisks')) + '</p><p class="sc-small">' + esc(t('risksNote')) + '</p>');
    return block(t('bRisks') + ' · ' + risks.length, '<ul class="sc-risks">' + risks.slice(0, 8).map(function (r) {
      return '<li><a href="#risk/' + encodeURIComponent(r.id) + '"><span class="sc-sev sc-sev-' + esc(String(r.risk_level || '').toLowerCase()) + '">' +
        esc(r.risk_level || '—') + '</span> <span class="sc-clamp">' + esc(r.reason || r.rule_code || ('#' + r.id)) + '</span></a><div class="sc-small">' + timeHtml(r.created_at) +
        (r.entity_type ? ' · ' + esc(r.entity_type) : '') + '</div></li>';
    }).join('') + '</ul><p class="sc-small">' + esc(t('risksNote')) + '</p>');
  }
  // D11: last 5 GPS sessions + one-line counters (rendered only when count > 0) with deep links into the existing
  // per-sector module views (#sectors/{id}/{module}); Foto → the existing photo comparison (Salīdzināšana).
  var MODULES = [['gps', 'gps_sessions'], ['risks', 'risks'], ['trucks', 'truck_reports'], ['timber', 'timber_movements'],
                 ['comments', 'comments'], ['compare', 'photos']];
  function activityCounts(detail) {
    if (!detail || !detail.sector) return null;                // source unavailable → caller shows "Nav pieejams"
    var out = [];
    MODULES.forEach(function (m) { var v = detail[m[1]]; if (Array.isArray(v) && v.length > 0) out.push({module: m[0], count: v.length}); });
    return out;
  }
  function activityBlock(detail, card) {
    var counts = activityCounts(detail);
    if (counts === null) return block(t('bActivity'), '<p class="sc-muted">' + esc(t('unavailable')) + '</p>');
    var g = detail.gps_sessions || [];
    if (!counts.length) return '';                            // §5.3: not rendered without data
    var lastG = g.slice().sort(function (a, b) { return String(b.check_in_time).localeCompare(String(a.check_in_time)); }).slice(0, 5);
    var base = '#sectors/' + encodeURIComponent(card.id) + '/';
    return block(t('bActivity'),
      (lastG.length ? '<div class="sc-sublabel">' + esc(t('lastGps')) + '</div><ul class="sc-acts">' + lastG.map(function (x) {
        return '<li>' + timeHtml(x.check_in_time) + (x.employee ? ' <span class="sc-small">· ' + esc(x.employee) + '</span>' : '') + '</li>';
      }).join('') + '</ul>' : '') +
      '<ul class="sc-counters">' + counts.map(function (c) {
        return '<li><a href="' + base + c.module + '" data-module="' + c.module + '"><span>' + esc(t('m_' + c.module)) +
          (c.module === 'compare' ? ' <small>(' + esc(t('photoCompare')) + ')</small>' : '') + '</span><b>' + c.count + '</b></a></li>';
      }).join('') + '</ul>' +
      '<a class="sc-btn sc-ghost" href="#forest-map">' + esc(t('showOnMap')) + '</a>');
  }
  function mapPane(card, st) {
    var m = card.monitoring;
    if (st === 'MONITORED') return '<div class="sc-ws" id="sc-ws-host"></div>';
    var msg = st === 'STOPPED' ? t('stopped') : st === 'AWAITING_FIRST_DATA' ? t('awaiting') : t('notMonitoredHint');
    return '<div class="sc-mapwrap"><div class="sc-map" id="sc-map"></div><div class="sc-empty-card" role="status">' +
      '<h3>' + esc(st === 'NOT_MONITORED' ? t('notMonitored') : t('st_' + st)) + '</h3><p>' + esc(msg) + '</p>' +
      (st === 'NOT_MONITORED' ? '<button class="sc-btn" data-add-page="' + esc(card.id) + '">' + esc(t('addMon')) + '</button>' : '') +
      (m && m.area_id ? '<a class="sc-btn sc-ghost" href="#sat-monitoring?area=' + m.area_id + '">' + esc(t('openWs')) + '</a>' : '') + '</div></div>';
  }
  function mountWorkspace(host, card) {
    var ws = global.SatWorkspace, id = card.monitoring.area_id;
    if (ws && typeof ws.mount === 'function') {                // D1: Stage 5 provides it before its release
      ws.mount(host, {areaId: id, embedded: true, onBack: function () { location.hash = '#sectors'; },
                      eventHref: function (eid) { return '#sectors/' + encodeURIComponent(card.id) + '?event=' + eid; }});
      S.mounted = true; return;
    }
    host.innerHTML = '<div class="sc-stub"><div class="sc-stub-inner"><div class="sc-stub-badge">Stage 5 · SatWorkspace.mount</div>' +
      '<h3>' + esc(t('mountStub')) + ' (#' + esc(id) + ')</h3><p>' + esc(t('mountStubNote', {id: id})) + '</p>' +
      '<a class="sc-btn" href="#sat-monitoring?area=' + encodeURIComponent(id) + '">' + esc(t('openWs')) + '</a></div></div>';
  }
  async function drawPolygonMap(card, detail) {
    var host = document.getElementById('sc-map'); if (!host) return;
    var L = await leaflet(), seq = S.seq;
    if (seq !== S.seq || !document.getElementById('sc-map')) return;
    var ring = null, b = detail && detail.sector && detail.sector.boundary_json;
    try { var pts = typeof b === 'string' ? JSON.parse(b) : b; if (Array.isArray(pts) && pts.length >= 3) ring = pts.map(function (p) { return [+p[0], +p[1]]; }); } catch (e) { ring = null; }
    if (!ring && card.ring) ring = card.ring.map(function (p) { return [p[1], p[0]]; });
    var map = L.map(host, {zoomControl: true, attributionControl: true});
    L.tileLayer(OSM, {maxZoom: 19, attribution: '© OpenStreetMap contributors'}).addTo(map);
    if (ring) { var poly = L.polygon(ring, {color: '#a3d45a', weight: 2, fillOpacity: 0.08}).addTo(map); map.fitBounds(poly.getBounds(), {padding: [60, 60], maxZoom: 17}); }
    else map.setView([56.95, 24.1], 7);
    S.map = map;
  }
  async function openSector(id, push) {
    cleanupPage();
    var seq = ++S.seq, sec = pageSection();
    document.querySelectorAll('.section').forEach(function (s) { s.classList.remove('active'); });
    sec.classList.add('active');
    document.querySelectorAll('.nav-item').forEach(function (n) { n.classList.toggle('active', /nav\('sectors'\)/.test(n.getAttribute('onclick') || '')); });
    if (push) history.pushState({type: 'sectorPage', id: String(id)}, '', '#sectors/' + encodeURIComponent(id));
    var pt = document.getElementById('page-title'); if (pt) pt.textContent = t('title');
    var ps = document.getElementById('page-sub'); if (ps) ps.textContent = new Date().toLocaleString('lv-LV');
    sec.innerHTML = '<div class="sc-loading">' + esc(t('loading')) + '</div>';
    var card;
    try { await loadCards(); card = S.cards.filter(function (c) { return String(c.id) === String(id); })[0]; } catch (e) { card = null; }
    if (seq !== S.seq) return;
    if (!card) { sec.innerHTML = '<div class="sc-page"><header class="sc-head"><a class="sc-back" href="#sectors" data-act="back">' + esc(t('back')) + '</a></header><p class="sc-error">' + esc(t('notFound')) + '</p></div>'; bindPage(sec, null); return; }
    if (pt) pt.textContent = card.name;
    var st = deriveStatus(card), m = card.monitoring;
    var dup = card._fixture_only ? 0 : S.cards.filter(function (c) { return c.name === card.name && c.id !== card.id; }).length;
    sec.innerHTML = '<div class="sc-page sc-root">' + header(card, st) + '<div class="sc-main">' + mapPane(card, st) +
      '<aside class="sc-panel" id="sc-panel">' + sectorBlock(card, dup) + '<div class="sc-loading">' + esc(t('loading')) + '</div></aside></div></div>';
    bindPage(sec, card);
    if (st === 'MONITORED') mountWorkspace(document.getElementById('sc-ws-host'), card);
    var reqs = [card._fixture_only ? Promise.resolve(null) : getJson('/api/sectors/' + encodeURIComponent(card.name)).catch(function () { return null; }),
                m ? getJson('/api/sat-monitoring/areas/' + encodeURIComponent(m.area_id) + '?geometry=0').catch(function () { return null; }) : Promise.resolve(null),
                m ? getJson('/api/sat-monitoring/health').catch(function () { return null; }) : Promise.resolve(null)];
    var res = await Promise.all(reqs);
    if (seq !== S.seq) return;
    var detail = res[0], area = res[1], health = res[2];
    document.getElementById('sc-panel').innerHTML = sectorBlock(card, dup) + satBlock(card, area, health) + changesBlock(card, area) +
      (card._fixture_only ? '' : risksBlock(detail) + activityBlock(detail, card));
    if (st !== 'MONITORED') drawPolygonMap(card, detail);
  }
  function bindPage(sec, card) {
    sec.querySelectorAll('[data-act=back]').forEach(function (a) { a.onclick = function (e) {
      e.preventDefault();
      if (history.state && history.state.type === 'sectorPage' && S.cameFromList) history.back();
      else { history.pushState({type: 'nav', id: 'sectors'}, '', '#sectors'); global.nav ? global.nav('sectors', false) : null; }
    }; });
    sec.querySelectorAll('[data-act=lang]').forEach(function (b) { b.onclick = function () { S.lang = S.lang === 'lv' ? 'en' : 'lv'; store('satMonitoring.lang', S.lang); if (card) openSector(card.id, false); }; });
    sec.querySelectorAll('[data-act=drawer]').forEach(function (b) { b.onclick = function () {
      var open = sec.querySelector('.sc-main').classList.toggle('sc-drawer-open'); b.setAttribute('aria-expanded', open);
      if (S.map) setTimeout(function () { S.map.invalidateSize(); }, 200);
    }; });
    sec.querySelectorAll('[data-add-page]').forEach(function (b) { b.onclick = function () {
      addToMonitoring(b.getAttribute('data-add-page'), b).then(function () { if (card) openSector(card.id, false); }).catch(function () { /* shown on the button */ });
    }; });
  }

  // ── routing glue (index.html calls these; real hash route #sectors/{id}) ─────────────────────────────────────
  var MODULE_IDS = ['gps', 'risks', 'trucks', 'timber', 'comments', 'compare', 'photos'];
  function routeFromHash(h) {
    var m = /^sectors\/([^/?]+)(?:\/([a-z]+))?/.exec(h || '');
    if (!m) return null;
    var id; try { id = decodeURIComponent(m[1]); } catch (e) { return null; }
    if (m[2] && MODULE_IDS.indexOf(m[2]) >= 0) return {type: 'sectorModule', id: id, module: m[2]};
    return m[2] ? null : {type: 'sectorPage', id: id};
  }
  // One existing per-sector module (legacy detail tab) without the tab bar / KPI / gauge (index.html openSectorModule).
  async function openModule(id, module, push) {
    cleanupPage();
    try { await loadCards(); } catch (e) { /* handled below */ }
    var card = (S.cards || []).filter(function (c) { return String(c.id) === String(id); })[0];
    if (!card || card._fixture_only || typeof global.openSectorModule !== 'function') return openSector(id, push);
    if (push) history.pushState({type: 'sectorModule', id: String(id), module: module}, '', '#sectors/' + encodeURIComponent(id) + '/' + module);
    var photos = null;
    return global.openSectorModule(card.name, module, {
      backHref: '#sectors/' + encodeURIComponent(card.id), backText: t('backTo', {name: card.name}),
      title: t('m_' + (module === 'photos' ? 'compare' : module)),
      extraLink: module === 'compare' ? function (detail) {
        photos = detail && Array.isArray(detail.photos) ? detail.photos.length : 0;
        return photos > 0 ? {href: '#sectors/' + encodeURIComponent(card.id) + '/photos', text: t('allPhotos', {n: photos})} : null;
      } : null
    });
  }
  // Legacy openSector(name) callers (GPS/Risks/Trucks/Timber/Objects tables, old #sector-{name} bookmarks).
  async function openByName(name, push) {
    try { await loadCards(); } catch (e) { /* not found below */ }
    var card = (S.cards || []).filter(function (c) { return !c._fixture_only && c.name === name; })[0];
    if (!card) return openSector('name:' + name, push);
    if (!push) history.replaceState({type: 'sectorPage', id: String(card.id)}, '', '#sectors/' + encodeURIComponent(card.id));
    return openSector(card.id, push);
  }
  function enterList(el, opts) {          // nav('sectors') → list; restore filters + scroll when coming back
    cleanupPage();
    var back = S.cameFromList && S.cards;
    S.cameFromList = false;
    var o = {restore: back};
    if (opts && Object.prototype.hasOwnProperty.call(opts, 'plan')) { o.plan = opts.plan; o.object = opts.object; }
    return renderList(el, o);
  }

  global.SectorCards = {
    renderList: enterList, openSector: function (id, push) { if (!push) S.cameFromList = false; return openSector(id, push); },
    openModule: openModule, openByName: openByName,
    routeFromHash: routeFromHash, leave: cleanupPage, addToMonitoring: addToMonitoring,
    // pure rules, exported for tests
    _deriveStatus: deriveStatus, _previewSource: previewSource, _counts: counts, _identifierText: identifierText,
    _matches: matches, _worstColour: worstColour, _longestSidePx: longestSidePx, _activityCounts: activityCounts,
    PREVIEW_MIN_PX: PREVIEW_MIN_PX, S2_PIXEL_M: S2_PIXEL_M, PAGE_SIZE: PAGE_SIZE,
    _state: S, _t: t
  };
})(typeof window !== 'undefined' ? window : globalThis);
