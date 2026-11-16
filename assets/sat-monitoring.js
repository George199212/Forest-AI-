/*
 * Forest AI — Satellite Monitoring section (Stage 3 UI). Sentinel-1/2 monitored areas, suspected change events,
 * human review. Backend: /api/sat-monitoring/* (satellite_monitoring/api_routes.py).
 *
 * Text: every on-screen string is English here (T / TD); Latvian lives in assets/i18n-lv.js (EXACT + PATTERNS),
 * applied on screen when the instance runs with UI_LANGUAGE=lv. Each translatable string is rendered as its own
 * text node; data (names, product ids, numbers) is marked data-no-i18n. Wording is neutral (D4): "suspected",
 * "vegetation/land-cover change", "outside the approved boundary".
 * Missing data is shown as missing ("—", chart gaps), never as 0.
 */
(function () {
  'use strict';
  var BASE = '/api/sat-monitoring';
  var LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
  var LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
  var OSM = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  var COL = {inside: '#00d5ff', outside: '#ffd400',   // contrast with false-colour quicklooks (bare soil = magenta)
             boundary: '#7ab83c', buffer: '#6fa8dc', footprint: '#c8c8c8',
             ndvi: '#7ab83c', nbr: '#d4a017', ndmi: '#4a9fd4', vv: '#9b8fd9', vh: '#4a9fd4', event: '#e05252',
             radar: '#e0a020'};

  // ── Static UI strings (EN). Every value has a Latvian entry in assets/i18n-lv.js (tested). ──────────────
  var T = {
    title: 'Satellite Monitoring', back: '← Satellite Monitoring', fetchNow: 'Fetch now', addSector: 'Add sector',
    loading: 'Loading…', close: 'Close', error: 'Error', done: 'Done.',
    kMonitored: 'Monitored areas', kRecent: 'With recent observations', kAwaiting: 'Awaiting data',
    kOpen: 'Open suspected events', kLastSync: 'Last successful sync', kFailed: 'Failed jobs', never: 'never',
    hUsage: 'Copernicus usage this month', hPU: 'Processing units (PU)', hReq: 'Requests', hGuard: 'guard',
    hBudget: 'budget', hLock: 'Worker', hRunning: 'Running', hIdle: 'Idle', hAuto: 'Automatic risks',
    hAutoOff: 'Off — risks are created only by a person (Create risk)',
    thArea: 'Monitored area', thSource: 'Source', thHa: 'Area (ha)', thStatus: 'Status', thLastS1: 'Last S1',
    thLastS2: 'Last valid S2', thOpen: 'Open suspected', thRecovered: 'Recovered', thGap: 'Days since valid S2',
    thView: 'Open',
    stOK: 'Data OK', stNoData: 'No data yet', stBackfill: 'Backfill in progress', stStopped: 'Stopped',
    srcSECTOR: 'Sector', srcLVM: 'LVM GEO', srcEVAL: 'Evaluation area',
    emptyAreas: 'No monitored areas yet.',
    emptyHint: 'Add a sector here, or use “Add to satellite monitoring” in LVM GEO.',
    noCreds: 'Copernicus credentials are not configured (SENTINEL_CLIENT_ID / SENTINEL_CLIENT_SECRET). Fetching is disabled.',
    unavailable: 'Satellite monitoring data is unavailable (satellite.db).',
    notMigrated: 'The worker has not prepared the database yet; changes cannot be queued.',
    sectorsTitle: 'Sectors with a polygon', noPolygon: 'No polygon', monitored: 'Monitored', queued: 'Queued',
    add: 'Add', pendingTitle: 'Queued areas', waitingWorker: 'waiting for the worker',
    cFetch: 'Fetch new Sentinel-1/2 observations for all monitored areas now?',
    cStop: 'Stop monitoring this area? Its history is kept.',
    cReject: 'Mark this suspected change as rejected (not a real change)?',
    cField: 'Send a field check request to the dispatcher via Telegram?',
    cRisk: 'Create a risk for this suspected change in the Risk Engine?',
    cUndo: 'Undo the last review decision?', notePrompt: 'Note (optional):',
    layers: 'Map layers', lBoundary: 'Sector boundary', lBuffer: 'Buffer ring', lChange: 'Detected change (current mask)',
    lFootprint: 'Sentinel observation footprint', lImage: 'Sentinel image', footprint: 'Observation footprint',
    legInside: 'Change inside the boundary', legOutside: 'Change outside the boundary',
    eventsTitle: 'Suspected change events', thEvent: 'Event', thOnset: 'Onset', thClass: 'Classification',
    thConf: 'Confidence', thCurrent: 'Current (ha)', thOutside: 'Outside (ha)', noEvents: 'No change events.',
    tsTitle: 'Time series (inside the area, median)', tsS2: 'Sentinel-2 indices', tsS1: 'Sentinel-1 backscatter (dB)',
    tsGaps: 'Gaps = no usable observation (cloud, no valid pixels). Missing values are never shown as 0.',
    evOnset: 'Event onset', radar: 'Radar anomaly',
    acqTitle: 'Acquisitions', thSensor: 'Sensor', thPlatform: 'Platform', thProduct: 'Product ID',
    thTime: 'Sensing time (UTC)', thValid: 'Valid % inside', thDetection: 'Detection', noAcq: 'No acquisitions yet.',
    stopMon: 'Stop monitoring',
    bNoData: 'Monitoring has not produced data yet. The first backfill runs after the worker picks up the job.',
    bBackfill: 'Backfill or fetch in progress.', bStopped: 'Monitoring stopped. History is kept.',
    before: 'Before', after: 'After', change: 'Change (mask over after)', sideBySide: 'Side by side', swipe: 'Swipe',
    suspectedLine: 'Suspected change — automated detection, not verified on the ground.',
    recoveredLine: 'Recovered — the change is no longer visible.', seasonal: 'Seasonal caveat',
    confidence: 'Detection confidence', evidence: 'Evidence quality', classification: 'Classification',
    clsLOSS: 'Potential forest loss', clsOUT: 'Potential change outside the boundary',
    clsSEAS: 'Possible seasonal or environmental change', clsINS: 'Insufficient evidence',
    cHigh: 'High', cMedium: 'Medium', cLow: 'Low', qGood: 'Good', qLimited: 'Limited', qPoor: 'Poor',
    sSUSPECTED: 'Suspected', sRECOVERED: 'Recovered', sCONF: 'Confirmed by review', sREJ: 'Rejected by review',
    sFIELD: 'Field check requested',
    areasTitle: 'Areas', aCurrent: 'Current mask', aInside: 'Inside the boundary', aOutside: 'Outside the boundary (buffer)',
    aUnion: 'Union of all after-images', aMax: 'Largest current area so far', aShare: 'Share of the area',
    aDist: 'Max distance outside the boundary', aCluster: 'Largest cluster',
    zTitle: 'VMD compartment type (current mask)', zStand: 'Forest stand (zkat 10)', zClear: 'Clear-cut land (zkat 14)',
    zOther: 'Other compartments', zNone: 'No compartment', zNA: 'Compartment split unavailable',
    ctxTitle: 'Operational context', ctxWork: 'Registered work in the observation window',
    ctxNone: 'No registered work found in the observation window',
    ctxNote: 'Counts of registered records only. No records does not prove there was no work; records do not explain the change.',
    ctxGps: 'Worker GPS points', ctxVeh: 'Vehicle/equipment GPS pings', ctxSessions: 'Work sessions',
    ctxPhotos: 'Field photos', ctxTrucks: 'Truck reports', ctxTimber: 'Timber movements', unknown: 'unknown',
    inside: 'inside', buffer: 'buffer', goGps: 'Open GPS Sessions', goTrucks: 'Open Truck Reports',
    goTimber: 'Open Timber', goSector: 'Open sector',
    algTitle: 'Algorithm', algPipeline: 'Pipeline run (code version not recorded)', algConfig: 'Configuration (thresholds)',
    reviewTitle: 'Review', reject: 'Reject', fieldCheck: 'Request field check', createRisk: 'Create risk', undo: 'Undo',
    logTitle: 'Review log', noReview: 'No review yet.', thDate: 'Date', thAction: 'Action', thBy: 'By', thNote: 'Note',
    superseded: 'This event was superseded by a later detection generation; review is disabled.',
    noImage: 'No image', validPct: 'Valid %',
    lvmAdd: 'Add to satellite monitoring', lvmMonitored: 'Already monitored', lvmQueued: 'Queued for satellite monitoring',
    lvmMulti: 'Multi-part polygon — add the parts separately', alreadyQueued: 'Already queued.'
  };

  // ── Dynamic strings (EN). Latvian via PATTERNS in assets/i18n-lv.js (tested with these samples). ─────────
  var TD = {
    lastDays: function (n) { return 'last ' + n + ' days'; },
    recoveredNotCounted: function (n) { return '+' + n + ' recovered (not counted)'; },
    changeDetected: function (ha) { return 'Vegetation/land-cover change detected: ' + ha; },
    outside: function (ha) { return ha + ' outside the approved boundary'; },
    eventTitle: function (id) { return 'Event #' + id; },
    generation: function (id) { return 'Detection generation ' + id; },
    code: function (v) { return 'code ' + v; },
    risk: function (id) { return 'Risk #' + id; },
    queuedJob: function (id) { return 'Queued as job #' + id + '.'; },
    confirmAdd: function (name) { return 'Add ' + name + ' to satellite monitoring? The last 120 days are fetched first.'; }
  };
  var TD_SAMPLES = [TD.lastDays(14), TD.recoveredNotCounted(1), TD.changeDetected('5.97 ha'), TD.outside('0.84 ha'),
                    TD.eventTitle(51), TD.generation(1), TD.code('b3c0fd4'), TD.risk(12), TD.queuedJob(3),
                    TD.confirmAdd('BIK-001')];

  var CLS = {POTENTIAL_FOREST_LOSS: 'clsLOSS', POTENTIAL_CHANGE_OUTSIDE_BOUNDARY: 'clsOUT',
             POSSIBLE_SEASONAL_OR_ENVIRONMENTAL: 'clsSEAS', INSUFFICIENT_EVIDENCE: 'clsINS'};
  var STATUS = {SUSPECTED: ['sSUSPECTED', 'b-amber'], RECOVERED: ['sRECOVERED', 'b-gray'],
                REVIEW_CONFIRMED: ['sCONF', 'b-red'], REVIEW_REJECTED: ['sREJ', 'b-green'],
                FIELD_CHECK_REQUESTED: ['sFIELD', 'b-amber']};
  var DATA_STATUS = {OK: ['stOK', 'b-green'], NO_DATA_YET: ['stNoData', 'b-gray'],
                     BACKFILL_OR_FETCH_IN_PROGRESS: ['stBackfill', 'b-amber'], STOPPED: ['stStopped', 'b-gray']};
  var SOURCE = {SECTOR: 'srcSECTOR', LVM_GEO: 'srcLVM', EVAL_BBOX: 'srcEVAL'};

  var S = {view: 'overview', areaId: null, eventId: null, maps: [], charts: [], health: null, imgMode: 'side',
           layers: {boundary: true, buffer: true, change: true, footprint: true, image: false}, selAcq: null,
           area: null, event: null, msg: null};

  // ── helpers ──────────────────────────────────────────────────────────────
  function esc(v) {
    return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function t(k) { return '<span>' + esc(T[k]) + '</span>'; }
  function data(v) { return '<span data-no-i18n>' + esc(v) + '</span>'; }
  function badge(k, cls) { return '<span class="badge ' + cls + '">' + esc(T[k]) + '</span>'; }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function ha(v) { return isNum(v) ? v.toFixed(2) + ' ha' : '—'; }
  function num(v, d) { return isNum(v) ? v.toFixed(d === undefined ? 1 : d) : '—'; }
  function day(s) { return s ? String(s).slice(0, 10) : '—'; }
  function dt(s) { return s ? String(s).slice(0, 16).replace('T', ' ') : '—'; }
  function ms(s) { var v = Date.parse(s); return isNaN(v) ? null : v; }
  function root() { return document.getElementById('satm-root'); }

  function ApiError(status, message, body) { this.status = status; this.message = message; this.body = body || {}; }
  async function req(method, path, body) {
    var r = await fetch(BASE + path, {method: method, credentials: 'same-origin', cache: 'no-store',
                                      headers: body ? {'Content-Type': 'application/json'} : undefined,
                                      body: body ? JSON.stringify(body) : undefined});
    var d = {};
    try { d = await r.json(); } catch (e) { d = {}; }
    if (!r.ok) throw new ApiError(r.status, d.error || d.detail || ('HTTP ' + r.status), d);
    return d;
  }
  function get(p) { return req('GET', p); }
  function post(p, b) { return req('POST', p, b || {}); }

  var leafletPromise = null;
  function ensureLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    if (leafletPromise) return leafletPromise;
    leafletPromise = new Promise(function (resolve, reject) {
      if (!document.querySelector('link[href="' + LEAFLET_CSS + '"]')) {
        var css = document.createElement('link'); css.rel = 'stylesheet'; css.href = LEAFLET_CSS;
        document.head.appendChild(css);
      }
      var s = document.createElement('script'); s.src = LEAFLET_JS;
      s.onload = function () { resolve(window.L); }; s.onerror = reject;
      document.head.appendChild(s);
    });
    return leafletPromise;
  }

  function cleanup() {
    S.maps.forEach(function (m) { try { m.remove(); } catch (e) { /* already gone */ } });
    S.charts.forEach(function (c) { try { c.destroy(); } catch (e) { /* already gone */ } });
    S.maps = []; S.charts = [];
  }

  function banner(kind, html) { return '<div class="satm-banner satm-' + kind + '">' + html + '</div>'; }
  function errorBanner(e) {
    if (e && e.status === 503 && /satellite\.db not/.test(e.message || '')) return banner('err', t('unavailable'));
    if (e && e.status === 503 && /not migrated/.test(e.message || '')) return banner('warn', t('notMigrated'));
    return banner('err', t('error') + ': ' + data(e && e.message ? e.message : e));
  }
  function flash() {
    if (!S.msg) return '';
    var m = S.msg; S.msg = null;
    return m.ok ? banner('ok', m.html) : errorBanner(m.err);
  }
  function attribution(text) { return '<div class="satm-attr" data-no-i18n>' + esc(text) + '</div>'; }

  // ── chart series: no-data stays a GAP (null), never 0 ────────────────────
  function series(timeline, sensor, metric) {
    return timeline.filter(function (a) { return a.sensor === sensor; }).map(function (a) {
      var m = (a.metrics_inside || {})[metric];
      var y = a.status === 'OK' && m && isNum(m.median) ? m.median : null;
      return {x: ms(a.sensing_time_utc), y: y};
    }).filter(function (p) { return p.x !== null; });
  }

  // ── OVERVIEW ─────────────────────────────────────────────────────────────
  async function loadOverview() {
    S.view = 'overview'; cleanup();
    var el = root(); el.innerHTML = '<div class="empty">' + t('loading') + '</div>';
    var ov, h;
    try { var r = await Promise.all([get('/overview'), get('/health')]); ov = r[0]; h = r[1]; }
    catch (e) { el.innerHTML = head(false) + errorBanner(e); return; }
    S.health = h;
    var k = ov.kpis, html = head(true) + flash();
    if (!h.credentials_configured) html += banner('warn', t('noCreds'));
    if (!h.schema_stage2) html += banner('warn', t('notMigrated'));
    html += '<div class="kpis satm-kpis">' +
      kpi('kMonitored', k.monitored_areas, '') +
      kpi('kRecent', k.with_recent_observations, '<span>' + esc(TD.lastDays(k.recent_days)) + '</span>') +
      kpi('kAwaiting', k.awaiting_data, '', k.awaiting_data ? 'amber' : '') +
      kpi('kOpen', k.open_suspected_events,
          k.recovered_events ? '<span>' + esc(TD.recoveredNotCounted(k.recovered_events)) + '</span>' : '',
          k.open_suspected_events ? 'amber' : 'green') +
      kpi('kLastSync', h.last_successful_sync ? day(h.last_successful_sync.finished_at) : null,
          h.last_successful_sync ? data(dt(h.last_successful_sync.finished_at) + ' UTC · ' + h.last_successful_sync.trigger)
                                 : t('never')) +
      kpi('kFailed', h.failed_jobs, '', h.failed_jobs ? 'red' : 'green') + '</div>';
    html += healthStrip(h);
    if (ov.pending_area_jobs.length) {
      html += '<div class="card satm-card"><div class="card-head">' + t('pendingTitle') + '</div>' +
        ov.pending_area_jobs.map(function (j) {
          return '<div class="satm-row">' + data(j.payload.name + ' · ' + j.payload.source + ' ' + j.payload.source_ref) +
                 ' ' + badge('queued', 'b-amber') + ' <span class="satm-muted">' + t('waitingWorker') + '</span></div>';
        }).join('') + '</div>';
    }
    html += '<div id="satm-sectors"></div>';
    if (!ov.areas.length) {
      html += '<div class="card satm-card"><div class="empty">' + t('emptyAreas') + '<br>' + t('emptyHint') + '</div></div>';
      el.innerHTML = html; bindHead(); return;
    }
    html += '<div class="card satm-card"><div id="satm-ov-map" class="satm-map satm-map-ov"></div></div>' +
      '<div class="card satm-card satm-scroll"><table class="tbl"><thead><tr>' +
      ['thArea', 'thSource', 'thHa', 'thStatus', 'thLastS1', 'thLastS2', 'thOpen', 'thRecovered', 'thGap', 'thView']
        .map(function (c) { return '<th>' + t(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      ov.areas.map(function (a) {
        var st = DATA_STATUS[a.data_status] || ['stOK', 'b-gray'];
        return '<tr><td>' + data(a.name) + '</td><td>' + t(SOURCE[a.source] || 'srcSECTOR') + '</td><td class="mono">' +
          data(num(a.area_ha, 1)) + '</td><td>' + badge(st[0], st[1]) + '</td><td class="mono">' + data(day(a.last_s1_utc)) +
          '</td><td class="mono">' + data(day(a.last_valid_s2_utc) + (isNum(a.last_valid_s2_valid_pct) ? ' (' +
          a.last_valid_s2_valid_pct.toFixed(0) + ' %)' : '')) + '</td><td class="mono">' + data(a.open_suspected_events) +
          '</td><td class="mono">' + data(a.recovered_events) + '</td><td class="mono">' +
          data(num(a.gaps.days_since_last_valid_s2, 1)) + '</td><td><a class="tbl-link" data-area="' + a.id + '">' +
          t('thView') + ' →</a></td></tr>';
      }).join('') + '</tbody></table></div>';
    el.innerHTML = html; bindHead();
    el.querySelectorAll('[data-area]').forEach(function (a) {
      a.onclick = function () { openArea(Number(a.getAttribute('data-area'))); };
    });
    var L = await ensureLeaflet();
    var map = L.map('satm-ov-map'); S.maps.push(map);
    L.tileLayer(OSM, {attribution: '&copy; OpenStreetMap contributors', maxZoom: 19}).addTo(map);
    var group = L.featureGroup().addTo(map);
    ov.areas.forEach(function (a) {
      if (!a.geometry) return;
      var st = a.open_suspected_events ? COL.outside : COL.boundary;
      L.geoJSON(a.geometry, {style: {color: a.active ? st : '#888', weight: 2, fillOpacity: 0.12}})
        .bindTooltip(esc(a.name)).on('click', function () { openArea(a.id); }).addTo(group);
    });
    if (group.getLayers().length) map.fitBounds(group.getBounds(), {padding: [20, 20]});
    else map.setView([56.9, 24.6], 7);
  }

  function head(withButtons) {
    var h = S.health, disabled = h && !h.credentials_configured ? ' disabled' : '';
    return '<div class="satm-head"><div class="card-head" style="margin:0">' + t('title') + '</div>' +
      (withButtons ? '<div class="satm-actions"><button class="btn" id="satm-fetch"' + disabled + '>' + t('fetchNow') +
       '</button><button class="btn" id="satm-add-sector">' + t('addSector') + '</button></div>' : '') + '</div>';
  }
  function bindHead() {
    var f = document.getElementById('satm-fetch'), a = document.getElementById('satm-add-sector');
    if (f) f.onclick = function () {
      if (!window.confirm(T.cFetch)) return;
      act(function () { return post('/fetch', {all: true}); }, loadOverview);
    };
    if (a) a.onclick = showSectors;
  }
  function kpi(label, value, sub, cls) {
    return '<div class="kpi"><div class="kpi-label">' + t(label) + '</div><div class="kpi-value ' + (cls || '') + '">' +
      data(value === null || value === undefined ? '—' : value) + '</div><div class="kpi-sub">' + (sub || '') + '</div></div>';
  }
  function healthStrip(h) {
    var m = h.month;
    return '<div class="card satm-card satm-health"><span class="satm-hl">' + t('hUsage') + '</span>' +
      '<span>' + t('hPU') + ': ' + data(num(m.pu, 1) + ' / ' + m.pu_guard) + ' (' + t('hGuard') + '), ' +
      data(m.pu_budget) + ' (' + t('hBudget') + ')</span>' + meter(m.pu, m.pu_guard) +
      '<span>' + t('hReq') + ': ' + data(m.requests + ' / ' + m.request_guard) + ' (' + t('hGuard') + '), ' +
      data(m.request_budget) + ' (' + t('hBudget') + ')</span>' + meter(m.requests, m.request_guard) +
      '<span>' + t('hLock') + ': ' + (h.lock.locked ? badge('hRunning', 'b-amber') : badge('hIdle', 'b-gray')) + '</span>' +
      '<span>' + t('hAuto') + ': ' + t('hAutoOff') + '</span></div>';
  }
  function meter(v, max) {
    var p = isNum(v) && max ? Math.min(100, 100 * v / max) : 0;
    return '<span class="satm-meter"><span style="width:' + p.toFixed(1) + '%;background:' +
      (p >= 100 ? 'var(--red, #c94040)' : p >= 75 ? 'var(--amber)' : 'var(--green)') + '"></span></span>';
  }

  async function showSectors() {
    var box = document.getElementById('satm-sectors');
    if (!box) return;
    if (box.innerHTML) { box.innerHTML = ''; return; }
    box.innerHTML = '<div class="card satm-card"><div class="empty">' + t('loading') + '</div></div>';
    var d;
    try { d = await get('/sectors'); } catch (e) { box.innerHTML = errorBanner(e); return; }
    box.innerHTML = '<div class="card satm-card"><div class="card-head">' + t('sectorsTitle') +
      '<button class="btn" id="satm-sectors-close">' + t('close') + '</button></div><div class="satm-sector-list">' +
      d.sectors.map(function (s) {
        var right = !s.has_polygon ? badge('noPolygon', 'b-gray')
          : s.monitored_area_id ? badge('monitored', 'b-green')
          : s.queued_job_id ? badge('queued', 'b-amber')
          : '<button class="btn" data-sector="' + s.id + '" data-name="' + esc(s.name) + '">' + t('add') + '</button>';
        return '<div class="satm-row' + (s.has_polygon ? '' : ' satm-dim') + '">' + data(s.name) + '<span>' + right +
          '</span></div>';
      }).join('') + '</div></div>';
    document.getElementById('satm-sectors-close').onclick = function () { box.innerHTML = ''; };
    box.querySelectorAll('[data-sector]').forEach(function (b) {
      b.onclick = function () {
        var name = b.getAttribute('data-name');
        if (!window.confirm(TD.confirmAdd(name))) return;
        act(function () {
          return post('/areas', {source: 'SECTOR', source_ref: b.getAttribute('data-sector'), name: name});
        }, loadOverview);
      };
    });
  }

  async function act(fn, reload) {
    try {
      var r = await fn();
      S.msg = {ok: true, html: r && r.job_id ? (r.deduplicated ? t('alreadyQueued') + ' ' : '') +
               '<span>' + esc(TD.queuedJob(r.job_id)) + '</span>' : t('done')};
    } catch (e) { S.msg = {ok: false, err: e}; }
    return reload();
  }

  // ── AREA ─────────────────────────────────────────────────────────────────
  async function openArea(id) {
    S.view = 'area'; S.areaId = id; S.selAcq = null; cleanup();
    var el = root(); el.innerHTML = '<div class="empty">' + t('loading') + '</div>';
    var d;
    try { d = await get('/areas/' + id); } catch (e) { el.innerHTML = backLink() + errorBanner(e); bindBack(); return; }
    S.area = d;
    var a = d.area, st = DATA_STATUS[a.data_status] || ['stOK', 'b-gray'];
    var html = backLink() + flash() + '<div class="satm-title"><h2>' + data(a.name) + '</h2>' + badge(st[0], st[1]) + ' ' +
      '<span class="badge b-gray">' + esc(T[SOURCE[a.source]] || a.source) + '</span> ' +
      data(a.source + ' ' + a.source_ref + ' · ' + num(a.area_ha, 2) + ' ha · buffer ' + num(a.buffer_m, 0) + ' m') + '</div>';
    if (a.data_status === 'NO_DATA_YET') html += banner('info', t('bNoData'));
    if (a.data_status === 'BACKFILL_OR_FETCH_IN_PROGRESS') html += banner('warn', t('bBackfill'));
    if (a.data_status === 'STOPPED') html += banner('info', t('bStopped'));
    html += '<div class="satm-grid"><div class="card satm-card"><div class="card-head">' + t('layers') + '</div>' +
      '<div class="satm-toggles">' +
      [['boundary', 'lBoundary'], ['buffer', 'lBuffer'], ['change', 'lChange'], ['footprint', 'lFootprint'],
       ['image', 'lImage']].map(function (x) {
        return '<label><input type="checkbox" data-layer="' + x[0] + '"' + (S.layers[x[0]] ? ' checked' : '') + '> ' +
          t(x[1]) + '</label>';
      }).join('') + '</div><div id="satm-area-map" class="satm-map"></div>' + legend() +
      '<div class="satm-muted" id="satm-footprint-label"></div>' + attribution(d.attribution) + '</div>' +
      '<div class="card satm-card satm-scroll"><div class="card-head">' + t('eventsTitle') + '</div>' + eventsTable(d.events) +
      '</div></div>';
    html += '<div class="card satm-card"><div class="card-head">' + t('tsTitle') + '</div>' +
      '<div class="satm-chart-title">' + t('tsS2') + '</div><div class="satm-chart"><canvas id="satm-ch-s2"></canvas></div>' +
      '<div class="satm-chart-title">' + t('tsS1') + '</div><div class="satm-chart"><canvas id="satm-ch-s1"></canvas></div>' +
      '<div class="satm-muted">' + t('tsGaps') + '</div></div>';
    html += '<div class="card satm-card"><div class="card-head">' + t('acqTitle') +
      (a.active ? '<button class="btn btn-red" id="satm-stop">' + t('stopMon') + '</button>' : '') + '</div>' +
      acqTable(d.timeline) + '</div>';
    el.innerHTML = html; bindBack();
    el.querySelectorAll('[data-event]').forEach(function (r) {
      r.onclick = function () { openEvent(Number(r.getAttribute('data-event'))); };
    });
    el.querySelectorAll('[data-acq]').forEach(function (r) {
      r.onclick = function () { S.selAcq = Number(r.getAttribute('data-acq')); drawAreaLayers(); };
    });
    el.querySelectorAll('[data-layer]').forEach(function (c) {
      c.onchange = function () { S.layers[c.getAttribute('data-layer')] = c.checked; drawAreaLayers(); };
    });
    var stop = document.getElementById('satm-stop');
    if (stop) stop.onclick = function () {
      if (!window.confirm(T.cStop)) return;
      act(function () { return post('/areas/' + id + '/stop'); }, function () { return openArea(id); });
    };
    drawCharts(d);
    var L = await ensureLeaflet();
    var map = L.map('satm-area-map'); S.maps.push(map); S.areaMap = map;
    L.tileLayer(OSM, {attribution: '&copy; OpenStreetMap contributors', maxZoom: 19}).addTo(map);
    S.areaLayer = L.layerGroup().addTo(map);
    var bb = a.grid_bbox;
    if (bb) map.fitBounds([[bb[1], bb[0]], [bb[3], bb[2]]]); else map.setView([56.9, 24.6], 7);
    drawAreaLayers();
  }

  function legend() {
    return '<div class="satm-legend"><span><i style="background:' + COL.inside + '"></i>' + t('legInside') + '</span>' +
      '<span><i style="background:' + COL.outside + '"></i>' + t('legOutside') + '</span>' +
      '<span><i style="background:transparent;border:2px solid ' + COL.boundary + '"></i>' + t('lBoundary') + '</span>' +
      '<span><i style="background:transparent;border:2px dashed ' + COL.buffer + '"></i>' + t('lBuffer') + '</span></div>';
  }
  function changeLayer(L, geojson) {
    return L.geoJSON(geojson, {style: function (f) {
      var out = f.properties && f.properties.zone === 'BUFFER';
      return {color: out ? COL.outside : COL.inside, weight: 2, fillColor: out ? COL.outside : COL.inside, fillOpacity: 0.3};
    }});
  }
  function latestOk(timeline) {
    for (var i = timeline.length - 1; i >= 0; i--) if (timeline[i].status === 'OK') return timeline[i];
    return null;
  }
  function drawAreaLayers() {
    var L = window.L, d = S.area, g = S.areaLayer;
    if (!L || !g || !d) return;
    g.clearLayers();
    var bb = d.area.grid_bbox, acq = null;
    d.timeline.forEach(function (x) { if (x.acq_id === S.selAcq) acq = x; });
    acq = acq || latestOk(d.timeline);
    if (S.layers.image && acq && acq.quicklook_url && bb) {
      L.imageOverlay(acq.quicklook_url, [[bb[1], bb[0]], [bb[3], bb[2]]], {opacity: 0.85, pane: imagePane(S.areaMap, 'satmImg', 350)}).addTo(g);
    }
    if (S.layers.footprint && bb) {
      L.rectangle([[bb[1], bb[0]], [bb[3], bb[2]]], {color: COL.footprint, weight: 1, dashArray: '2 4', fill: false})
        .bindTooltip(esc(T.footprint) + ' · ' + esc(acq ? acq.sensor + ' ' + dt(acq.sensing_time_utc) : '—')).addTo(g);
    }
    var lab = document.getElementById('satm-footprint-label');
    if (lab) lab.innerHTML = acq ? t('footprint') + ': ' + data(acq.sensor + ' · ' + (acq.platform || '') + ' · ' +
      dt(acq.sensing_time_utc) + ' UTC · ' + acq.product_id) : '';
    if (S.layers.buffer && d.buffer_ring) L.geoJSON(d.buffer_ring, {style: {color: COL.buffer, weight: 1.5,
      dashArray: '5 4', fillColor: COL.buffer, fillOpacity: 0.06}}).addTo(g);
    if (S.layers.boundary && d.geometry) L.geoJSON(d.geometry, {style: {color: COL.boundary, weight: 2.5, fill: false}}).addTo(g);
    if (S.layers.change) d.events.forEach(function (e) {
      if (e.change_geojson) changeLayer(L, e.change_geojson).bindTooltip(esc(TD.eventTitle(e.id)))
        .on('click', function () { openEvent(e.id); }).addTo(g);
    });
  }

  function eventsTable(events) {
    if (!events.length) return '<div class="empty">' + t('noEvents') + '</div>';
    return '<table class="tbl"><thead><tr>' + ['thEvent', 'thOnset', 'thClass', 'thConf', 'thCurrent', 'thOutside', 'thStatus']
      .map(function (c) { return '<th>' + t(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      events.map(function (e) {
        var s = STATUS[e.status] || ['sSUSPECTED', 'b-gray'];
        return '<tr class="satm-click" data-event="' + e.id + '"><td class="mono">' + data('#' + e.id) + '</td><td class="mono">' +
          data(day(e.first_after_time_utc)) + '</td><td>' + t(CLS[e.classification] || 'clsINS') + '</td><td>' +
          confBadge(e.confidence) + '</td><td class="mono">' + data(num(e.changed_area_ha, 2)) + '</td><td class="mono">' +
          data(num(e.changed_area_ha_buffer, 2)) + '</td><td>' + badge(s[0], s[1]) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }
  function confBadge(c) {
    return c === 'HIGH' ? badge('cHigh', 'b-red') : c === 'MEDIUM' ? badge('cMedium', 'b-amber') : badge('cLow', 'b-gray');
  }
  function eqBadge(q) {
    return q === 'GOOD' ? badge('qGood', 'b-green') : q === 'LIMITED' ? badge('qLimited', 'b-amber') : badge('qPoor', 'b-gray');
  }
  function acqTable(timeline) {
    if (!timeline.length) return '<div class="empty">' + t('noAcq') + '</div>';
    var rows = timeline.slice().reverse();
    return '<div class="satm-scroll"><table class="tbl"><thead><tr>' +
      ['thSensor', 'thPlatform', 'thProduct', 'thTime', 'thStatus', 'thValid', 'thDetection']
        .map(function (c) { return '<th>' + t(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      rows.map(function (x) {
        return '<tr class="satm-click" data-acq="' + x.acq_id + '"><td class="mono">' + data(x.sensor) + '</td><td class="mono">' +
          data(x.platform || '—') + '</td><td class="mono satm-pid">' + data(x.product_id) + '</td><td class="mono">' +
          data(dt(x.sensing_time_utc)) + '</td><td class="mono">' + data(x.status) + '</td><td class="mono">' +
          data(num(x.valid_pct_inside, 1)) + '</td><td class="mono">' + data(x.detection || '—') + '</td></tr>';
      }).join('') + '</tbody></table></div>';
  }

  function drawCharts(d) {
    if (typeof window.Chart !== 'function') return;
    var tl = d.timeline;
    var xs = tl.map(function (a) { return ms(a.sensing_time_utc); }).filter(function (v) { return v !== null; });
    var xmin = Math.min.apply(null, xs.length ? xs : [0]), xmax = Math.max.apply(null, xs.length ? xs : [1]);
    var onsets = d.events.map(function (e) { return ms(e.first_after_time_utc); }).filter(function (v) { return v !== null; });
    function opts(ymin, ymax) {
      return {responsive: true, maintainAspectRatio: false, animation: false, spanGaps: false,
        plugins: {legend: {labels: {color: '#8a9e70', font: {size: 11}, boxWidth: 12}},
                  tooltip: {callbacks: {title: function (it) { return it.length ? dt(new Date(it[0].parsed.x).toISOString()) : ''; }}}},
        scales: {x: {type: 'linear', min: xmin, max: xmax, ticks: {color: '#8a9e70', font: {size: 10}, maxTicksLimit: 8,
                   callback: function (v) { return new Date(v).toISOString().slice(0, 10); }},
                   grid: {color: 'rgba(120,180,60,0.07)'}},
                 y: {min: ymin, max: ymax, ticks: {color: '#8a9e70', font: {size: 10}}, grid: {color: 'rgba(120,180,60,0.07)'}}}};
    }
    function line(label, pts, color) {
      return {type: 'line', label: label, data: pts, borderColor: color, backgroundColor: color, pointRadius: 2,
              borderWidth: 1.5, spanGaps: false, tension: 0};
    }
    function marks(label, times, y, color, style) {
      return {type: 'scatter', label: label, data: times.map(function (x) { return {x: x, y: y}; }), borderColor: color,
              backgroundColor: color, pointStyle: style, pointRadius: 6, showLine: false};
    }
    var c2 = document.getElementById('satm-ch-s2'), c1 = document.getElementById('satm-ch-s1');
    if (c2) S.charts.push(new window.Chart(c2.getContext('2d'), {type: 'line', data: {datasets: [
      line('NDVI', series(tl, 'S2', 'NDVI'), COL.ndvi), line('NBR', series(tl, 'S2', 'NBR'), COL.nbr),
      line('NDMI', series(tl, 'S2', 'NDMI'), COL.ndmi), marks(T.evOnset, onsets, 0.95, COL.event, 'triangle')]},
      options: opts(-0.4, 1.0)}));
    var radar = (d.radar_anomalies || []).map(function (r) { return ms(r.sensing_time_utc); }).filter(function (v) { return v !== null; });
    if (c1) S.charts.push(new window.Chart(c1.getContext('2d'), {type: 'line', data: {datasets: [
      line('VV dB', series(tl, 'S1', 'VV_DB'), COL.vv), line('VH dB', series(tl, 'S1', 'VH_DB'), COL.vh),
      marks(T.evOnset, onsets, 1.5, COL.event, 'triangle'), marks(T.radar, radar, 0.5, COL.radar, 'rectRot')]},
      options: opts(-30, 2)}));
  }

  function backLink(toArea) {
    return '<div class="satm-back"><a class="tbl-link" id="satm-back">' +
      (toArea ? '← ' + data(toArea) : t('back')) + '</a></div>';
  }
  function bindBack(areaId) {
    var b = document.getElementById('satm-back');
    if (b) b.onclick = function () { if (areaId) openArea(areaId); else loadOverview(); };
  }

  // ── EVENT ────────────────────────────────────────────────────────────────
  function pickImages(e) {
    var after = e.after.filter(function (x) { return x.quicklook_url; });
    var a = after.filter(function (x) { return x.sensor === 'S2'; }).pop() || after.pop() || null;
    var before = e.before.filter(function (x) { return x.quicklook_url && (!a || x.sensor === a.sensor); });
    before.sort(function (x, y) { return String(x.sensing_time_utc).localeCompare(String(y.sensing_time_utc)); });
    return {before: before.pop() || null, after: a};
  }

  async function openEvent(id) {
    S.view = 'event'; S.eventId = id; cleanup();
    var el = root(); el.innerHTML = '<div class="empty">' + t('loading') + '</div>';
    var e;
    try { e = await get('/events/' + id); } catch (err) { el.innerHTML = backLink() + errorBanner(err); bindBack(); return; }
    S.event = e;
    var st = STATUS[e.status] || ['sSUSPECTED', 'b-gray'], imgs = pickImages(e), ar = e.area;
    var html = backLink(ar.name) + flash() + '<div class="satm-title"><h2><span>' + esc(TD.eventTitle(e.id)) + '</span></h2>' +
      badge(st[0], st[1]) +
      ' <span class="satm-badge-lab">' + t('classification') + '</span> <span class="badge b-gray">' + esc(T[CLS[e.classification] || 'clsINS']) + '</span>' +
      ' <span class="satm-badge-lab">' + t('confidence') + '</span> ' + confBadge(e.confidence) +
      ' <span class="satm-badge-lab">' + t('evidence') + '</span> ' + eqBadge(e.evidence_quality) + '</div>';
    if (!e.current) html += banner('warn', t('superseded'));
    html += '<div class="card satm-card satm-lines">' +
      '<div class="satm-line-big"><span>' + esc(TD.changeDetected(ha(e.changed_area_ha))) + '</span></div>' +
      (isNum(e.changed_area_ha_buffer) && e.changed_area_ha_buffer > 0
        ? '<div class="satm-line-big"><span>' + esc(TD.outside(ha(e.changed_area_ha_buffer))) + '</span></div>' : '') +
      (e.status === 'RECOVERED' ? '<div>' + t('recoveredLine') + ' ' + data(e.recovered_reason || '') + '</div>'
                                : '<div class="satm-muted">' + t('suspectedLine') + '</div>') +
      (e.seasonal_caveat ? '<div>' + badge('seasonal', 'b-amber') + ' ' + data(e.seasonal_caveat) + '</div>' : '') +
      '<div class="satm-muted">' + data(day(e.first_after_time_utc) + ' … ' + day(e.last_after_time_utc) + ' · ' + e.sensor_basis) +
      '</div></div>';
    html += '<div class="card satm-card"><div class="card-head"><span></span><span class="satm-actions">' +
      '<button class="filter-btn' + (S.imgMode === 'side' ? ' active' : '') + '" data-mode="side">' + t('sideBySide') + '</button>' +
      '<button class="filter-btn' + (S.imgMode === 'swipe' ? ' active' : '') + '" data-mode="swipe">' + t('swipe') + '</button>' +
      '</span></div>' + (S.imgMode === 'side' ? sideBySide(imgs) : swipeBox(imgs)) + '</div>';
    html += '<div class="satm-grid">' + areasCard(e) + zkatCard(e) + '</div>';
    html += '<div class="satm-grid">' + contextCard(e) + algorithmCard(e) + '</div>';
    html += reviewCard(e);
    el.innerHTML = html; bindBack(ar.id);
    el.querySelectorAll('[data-mode]').forEach(function (b) {
      b.onclick = function () { S.imgMode = b.getAttribute('data-mode'); openEvent(id); };
    });
    bindReview(e);
    el.querySelectorAll('[data-nav]').forEach(function (a) {
      a.onclick = function () {
        var target = a.getAttribute('data-nav');
        if (target === 'sector' && typeof window.openSector === 'function') window.openSector(a.getAttribute('data-name'));
        else if (typeof window.nav === 'function') window.nav(target);
      };
    });
    el.querySelectorAll('[data-risk]').forEach(function (a) {
      a.onclick = function () { if (typeof window.openRisk === 'function') window.openRisk(Number(a.getAttribute('data-risk'))); };
    });
    var L = await ensureLeaflet();
    var focus = focusBounds(L, ar, e.change_geojson);
    if (S.imgMode === 'side') {
      var ms3 = [imgMap(L, 'satm-img-before', imgs.before, ar, null, focus),
                 imgMap(L, 'satm-img-after', imgs.after, ar, null, focus),
                 imgMap(L, 'satm-img-change', imgs.after, ar, e.change_geojson, focus)].filter(Boolean);
      syncMaps(ms3);
    } else swipeMap(L, imgs, ar, e.change_geojson, focus);
  }

  function imgMeta(x) {
    if (!x) return '<div class="satm-muted">' + t('noImage') + '</div>';
    return '<div class="satm-imgmeta">' + data(dt(x.sensing_time_utc) + ' UTC · ' + x.sensor + (x.platform ? ' · ' + x.platform : '')) +
      '<br>' + t('validPct') + ': ' + data(num(x.valid_pct_inside, 1)) + '<br><span class="satm-pid">' + data(x.product_id) + '</span>' +
      attribution('Contains modified Copernicus Sentinel data ' + String(x.sensing_time_utc).slice(0, 4)) + '</div>';
  }
  function sideBySide(imgs) {
    return '<div class="satm-imgs">' +
      '<div><div class="satm-chart-title">' + t('before') + '</div><div id="satm-img-before" class="satm-img"></div>' + imgMeta(imgs.before) + '</div>' +
      '<div><div class="satm-chart-title">' + t('after') + '</div><div id="satm-img-after" class="satm-img"></div>' + imgMeta(imgs.after) + '</div>' +
      '<div><div class="satm-chart-title">' + t('change') + '</div><div id="satm-img-change" class="satm-img"></div>' + legend() +
      (imgs.after ? attribution('Contains modified Copernicus Sentinel data ' + String(imgs.after.sensing_time_utc).slice(0, 4)) : '') + '</div></div>';
  }
  function swipeBox(imgs) {
    return '<div class="satm-swipe-labels"><span>' + t('before') + '</span><span>' + t('after') + '</span></div>' +
      '<div id="satm-swipe" class="satm-img satm-img-wide"></div><input type="range" id="satm-swipe-range" min="0" max="100" value="50">' +
      '<div class="satm-imgs2">' + imgMeta(imgs.before) + imgMeta(imgs.after) + '</div>';
  }
  // Satellite images go into panes BELOW Leaflet's overlay pane (400): masks and boundaries always draw on top.
  function imagePane(map, name, z) {
    var pane = map.getPane(name) || map.createPane(name);
    pane.style.zIndex = z; pane.style.pointerEvents = 'none';
    return name;
  }
  function bboxBounds(bb) { return [[bb[1], bb[0]], [bb[3], bb[2]]]; }
  // Zoom to the change (padded), not to the whole request grid: a 6 ha felling in a 3,670 ha box is otherwise invisible.
  function focusBounds(L, area, change) {
    var full = L.latLngBounds(bboxBounds(area.grid_bbox || [0, 0, 0, 0]));
    if (!change || !change.features || !change.features.length) return full;
    var b = L.geoJSON(change).getBounds();
    if (!b.isValid()) return full;
    var padded = b.pad(0.35);
    return padded.contains(full) || !full.intersects(padded) ? full : padded;
  }
  function syncMaps(maps) {
    var busy = false;
    maps.forEach(function (m) {
      m.on('moveend', function () {
        if (busy) return; busy = true;
        maps.forEach(function (o) { if (o !== m) o.setView(m.getCenter(), m.getZoom(), {animate: false}); });
        busy = false;
      });
    });
  }
  function imgMap(L, elId, img, area, change, focus) {
    var div = document.getElementById(elId);
    if (!div || !area.grid_bbox) return null;
    var map = L.map(div, {zoomControl: false, attributionControl: false, zoomSnap: 0.25}); S.maps.push(map);
    var b = bboxBounds(area.grid_bbox);
    map.fitBounds(focus || b);                       // view first, then layers (as in the area map)
    if (img && img.quicklook_url) L.imageOverlay(img.quicklook_url, b, {pane: imagePane(map, 'satmImg', 350)}).addTo(map);
    if (area.buffer_ring) L.geoJSON(area.buffer_ring, {style: {color: COL.buffer, weight: 1, dashArray: '5 4', fill: false}}).addTo(map);
    if (area.geometry) L.geoJSON(area.geometry, {style: {color: COL.boundary, weight: 2, fill: false}}).addTo(map);
    if (change) changeLayer(L, change).addTo(map);
    return map;
  }
  function swipeMap(L, imgs, area, change, focus) {
    var div = document.getElementById('satm-swipe');
    if (!div || !area.grid_bbox) return;
    var map = L.map(div, {zoomControl: true, attributionControl: false, zoomSnap: 0.25}); S.maps.push(map);
    var b = bboxBounds(area.grid_bbox);
    if (imgs.before && imgs.before.quicklook_url) L.imageOverlay(imgs.before.quicklook_url, b, {pane: imagePane(map, 'satmImg', 350)}).addTo(map);
    imagePane(map, 'satmAfter', 360);
    var pane = map.getPane('satmAfter');
    if (imgs.after && imgs.after.quicklook_url) L.imageOverlay(imgs.after.quicklook_url, b, {pane: 'satmAfter'}).addTo(map);
    if (change) changeLayer(L, change).addTo(map);
    if (area.geometry) L.geoJSON(area.geometry, {style: {color: COL.boundary, weight: 2, fill: false}}).addTo(map);
    var range = document.getElementById('satm-swipe-range');
    function clip() {
      var v = Number(range.value) / 100, nw = map.containerPointToLayerPoint([0, 0]),
          se = map.containerPointToLayerPoint(map.getSize()), x = nw.x + (se.x - nw.x) * v;
      pane.style.clip = 'rect(' + nw.y + 'px,' + se.x + 'px,' + se.y + 'px,' + x + 'px)';
    }
    range.oninput = clip; map.on('move zoom resize', clip);
    map.fitBounds(focus || b); clip();
  }

  function row(label, value) { return '<tr><td>' + t(label) + '</td><td class="mono">' + data(value) + '</td></tr>'; }
  function areasCard(e) {
    return '<div class="card satm-card"><div class="card-head">' + t('areasTitle') + '</div><table class="tbl">' +
      row('aCurrent', ha(e.changed_area_ha)) + row('aInside', ha(e.changed_area_ha_inside)) +
      row('aOutside', ha(e.changed_area_ha_buffer)) + row('aUnion', ha(e.union_area_ha)) + row('aMax', ha(e.max_area_ha)) +
      row('aShare', isNum(e.pct_of_area_affected) ? e.pct_of_area_affected.toFixed(1) + ' %' : '—') +
      row('aDist', isNum(e.max_distance_outside_boundary_m) ? e.max_distance_outside_boundary_m.toFixed(0) + ' m' : '—') +
      row('aCluster', ha(e.largest_cluster_ha)) + '</table></div>';
  }
  function zkatCard(e) {
    var z = e.compartment_split;
    if (!z || z.unavailable) return '<div class="card satm-card"><div class="card-head">' + t('zTitle') + '</div><div class="empty">' +
      t('zNA') + (z && z.unavailable ? ' ' + data(z.unavailable) : '') + '</div></div>';
    var parts = [['zStand', z.stand_zkat10_ha, '#3f7a2a'], ['zClear', z.clearcut_zkat14_ha, '#c9a227'],
                 ['zOther', z.other_compartments_ha, '#6f8f9f'], ['zNone', z.no_compartment_ha, '#777']];
    var tot = parts.reduce(function (s, p) { return s + (isNum(p[1]) ? p[1] : 0); }, 0);
    return '<div class="card satm-card"><div class="card-head">' + t('zTitle') + '</div><div class="satm-zbar">' +
      parts.map(function (p) {
        return tot > 0 && isNum(p[1]) ? '<span style="width:' + (100 * p[1] / tot).toFixed(2) + '%;background:' + p[2] + '"></span>' : '';
      }).join('') + '</div><table class="tbl">' + parts.map(function (p) {
        return '<tr><td><i class="satm-sw" style="background:' + p[2] + '"></i>' + t(p[0]) + '</td><td class="mono">' + data(ha(p[1])) +
          '</td></tr>';
      }).join('') + '</table></div>';
  }
  function contextCard(e) {
    var c = e.operational_context || {}, s = c.sources || {}, area = e.area;
    function cnt(o, key) {
      if (!o) return data('—');
      if (key === 'pts') return o.inside === null || o.inside === undefined ? t('unknown')
        : data(o.inside) + ' ' + t('inside') + ' · ' + data(o.buffer) + ' ' + t('buffer');
      return o.count === null || o.count === undefined ? t('unknown') + (o.reason ? ' <span class="satm-muted">' + data('(' + o.reason + ')') + '</span>' : '')
        : data(o.count);
    }
    function link(target, label, name) {
      return ' <a class="tbl-link" data-nav="' + target + '"' + (name ? ' data-name="' + esc(name) + '"' : '') + '>' + t(label) + ' →</a>';
    }
    var label = c.context_label === 'CHANGE_DURING_REGISTERED_WORK' ? badge('ctxWork', 'b-amber') : badge('ctxNone', 'b-gray');
    return '<div class="card satm-card"><div class="card-head">' + t('ctxTitle') + '</div><div>' + label + '</div>' +
      '<div class="satm-muted">' + data(day(c.window_from_utc) + ' … ' + day(c.window_to_utc) + ' · buffer ' + num(c.buffer_m, 0) + ' m') + '</div>' +
      '<table class="tbl">' +
      '<tr><td>' + t('ctxGps') + '</td><td>' + cnt(s.worker_gps_track_points, 'pts') + link('gps', 'goGps') + '</td></tr>' +
      '<tr><td>' + t('ctxVeh') + '</td><td>' + cnt(s.vehicle_equipment_gps_pings, 'pts') + '</td></tr>' +
      '<tr><td>' + t('ctxSessions') + '</td><td>' + cnt(s.work_sessions) + link('gps', 'goGps') + '</td></tr>' +
      '<tr><td>' + t('ctxPhotos') + '</td><td>' + cnt(s.field_photos) + '</td></tr>' +
      '<tr><td>' + t('ctxTrucks') + '</td><td>' + cnt(s.truck_reports) + link('trucks', 'goTrucks') + '</td></tr>' +
      '<tr><td>' + t('ctxTimber') + '</td><td>' + cnt(s.timber_movements) + link('timber', 'goTimber') + '</td></tr>' +
      '</table>' + (c.sector_name ? '<div>' + link('sector', 'goSector', c.sector_name) + '</div>'
                                 : area.source === 'SECTOR' ? '<div>' + link('sector', 'goSector', area.name) + '</div>' : '') +
      '<div class="satm-muted">' + t('ctxNote') + '</div></div>';
  }
  function algorithmCard(e) {
    var a = e.algorithm || {}, th = a.thresholds || {};
    var src = a.generation_id ? '<span>' + esc(TD.generation(a.generation_id)) + '</span> · <span>' + esc(TD.code(a.code_version || '?')) + '</span>'
                              : t('algPipeline');
    return '<div class="card satm-card"><div class="card-head">' + t('algTitle') + '</div><div>' + src + '</div>' +
      '<details><summary>' + t('algConfig') + '</summary><table class="tbl satm-small">' + Object.keys(th).sort().map(function (k) {
        return '<tr><td class="mono">' + data(k) + '</td><td class="mono">' + data(JSON.stringify(th[k])) + '</td></tr>';
      }).join('') + '</table></details></div>';
  }
  function reviewCard(e) {
    var dis = !e.current, html = '<div class="card satm-card"><div class="card-head">' + t('reviewTitle') +
      (e.risk_id ? '<a class="tbl-link" data-risk="' + e.risk_id + '"><span>' + esc(TD.risk(e.risk_id)) + '</span> →</a>' : '') + '</div>' +
      '<div class="satm-actions">' +
      btn('reject', 'reject', dis || e.status === 'REVIEW_REJECTED', 'btn-red') +
      btn('field', 'fieldCheck', dis || e.status === 'FIELD_CHECK_REQUESTED') +
      btn('risk', 'createRisk', dis || !!e.risk_id) +
      btn('undo', 'undo', dis || !e.undo_available) + '</div>';
    html += '<div class="card-head" style="margin-top:14px">' + t('logTitle') + '</div>';
    html += e.review_log.length ? '<table class="tbl"><thead><tr>' + ['thDate', 'thAction', 'thBy', 'thStatus', 'thNote']
      .map(function (c) { return '<th>' + t(c) + '</th>'; }).join('') + '</tr></thead><tbody>' + e.review_log.map(function (r) {
        return '<tr><td class="mono">' + data(dt(r.created_at_utc)) + '</td><td class="mono">' + data(r.action) + '</td><td>' + data(r.actor) +
          '</td><td class="mono">' + data((r.old_status || '') + ' → ' + (r.new_status || '')) + '</td><td>' + data(r.note || '') + '</td></tr>';
      }).join('') + '</tbody></table>' : '<div class="empty">' + t('noReview') + '</div>';
    return html + '</div>';
  }
  function btn(action, label, disabled, cls) {
    return '<button class="btn ' + (cls || '') + '" data-review="' + action + '"' + (disabled ? ' disabled' : '') + '>' + t(label) + '</button>';
  }
  var REVIEW = {reject: ['REJECT', 'cReject', true], field: ['FIELD_CHECK', 'cField', true],
                risk: ['CREATE_RISK', 'cRisk', false], undo: ['UNDO', 'cUndo', false]};
  function bindReview(e) {
    root().querySelectorAll('[data-review]').forEach(function (b) {
      b.onclick = function () {
        var r = REVIEW[b.getAttribute('data-review')];
        if (!window.confirm(T[r[1]])) return;
        var note = r[2] ? window.prompt(T.notePrompt, '') : null;
        act(function () { return post('/events/' + e.id + '/review', {decision: r[0], note: note || null}); },
            function () { return openEvent(e.id); });
      };
    });
  }

  // ── LVM GEO: ONE button in the selected-object (compartment) popup ──────
  function lvmGeometry(feature) {
    var g = feature && feature.geometry;
    if (!g) return {error: 'noPolygon'};
    if (g.type === 'Polygon') return {geometry: g};
    if (g.type === 'MultiPolygon') return g.coordinates.length === 1 ? {geometry: {type: 'Polygon', coordinates: g.coordinates[0]}}
                                                                    : {error: 'lvmMulti'};
    return {error: 'noPolygon'};
  }
  function lvmButton(container, feature) {
    if (!container || !feature) return null;
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'btn vmd-popup-action satm-lvm-btn'; b.textContent = T.lvmAdd;
    container.appendChild(b);
    var g = lvmGeometry(feature), ref = String(feature.id), p = feature.properties || {};
    var name = 'VMD ' + (p.kvart !== undefined ? p.kvart + '-' + p.nog : ref) + (p.kadastrs ? ' (' + p.kadastrs + ')' : '');
    function state(key, disabled) { b.textContent = T[key]; b.disabled = !!disabled; }
    if (g.error) { state(g.error, true); return b; }
    function check() {
      get('/lookup?source=LVM_GEO&source_ref=' + encodeURIComponent(ref)).then(function (r) {
        if (r.monitored) state('lvmMonitored', true); else if (r.queued_job_id) state('lvmQueued', true);
      }).catch(function () { /* lookup unavailable: keep the button; the POST reports errors */ });
    }
    // One lookup when the popup is actually shown (not one request per compartment on the page).
    if (typeof window.IntersectionObserver === 'function') {
      var io = new window.IntersectionObserver(function (entries) {
        if (entries.some(function (x) { return x.isIntersecting; })) { io.disconnect(); check(); }
      });
      io.observe(b);
    } else check();
    b.onclick = function (ev) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      if (!window.confirm(TD.confirmAdd(name))) return;
      b.disabled = true;
      post('/areas', {source: 'LVM_GEO', source_ref: ref, name: name, geometry: g.geometry}).then(function () {
        state('lvmQueued', true);
      }).catch(function (e) {
        if (e.status === 409 && e.body && e.body.area_id) state('lvmMonitored', true);
        else { b.disabled = false; window.alert(T.error + ': ' + e.message); }
      });
    };
    return b;
  }

  window.SatMonitoring = {load: loadOverview, openArea: openArea, openEvent: openEvent, lvmButton: lvmButton,
                          _T: T, _TD_SAMPLES: TD_SAMPLES, _series: series, _lvmGeometry: lvmGeometry, _pickImages: pickImages};
})();
