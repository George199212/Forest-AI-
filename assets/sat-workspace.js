/*
 * Forest AI — Satelītu monitorings workspace (Stage C1, owner-approved concept 2026-11-18).
 * One workspace: Teritorija (start) · Izmaiņas (area / event) · Pierādījumi (existing event page, unchanged).
 * Every value comes from /api/sat-monitoring/* (or the reused Forest Map read endpoints); missing = "Nav pieejams",
 * never 0. Wording "Iespējamas izmaiņas / Suspected change"; raw observation, processed measurement, system
 * interpretation and human decision stay separate. "Contains modified Copernicus Sentinel data YEAR" on the map.
 * Base map = faint OSM, labelled "not dated, not Sentinel" (Esri is not offered: licence).
 * Mounted into #satm-root; window.SatMonitoring keeps lvmButton and the legacy event page (Pierādījumi).
 */
(function (global) {
  'use strict';
  var API = '/api/sat-monitoring';
  var OSM = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  var LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
  var LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
  var FONTS_CSS = 'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600;700&display=swap';
  var VMD_TILES = '/api/geodata/forest-map/tiles/forest/{z}/{x}/{y}';
  var GEO = '/api/geodata';
  var DAY = 86400000;
  var BIG_AREA_HA = 20;            // area cards: >= 20 ha before|after thumbnails, smaller areas boundary + NDVI sparkline

  // ── change colour language (v3 §5.5): ONE table, the legend is generated from it ─────────────────────────────────
  var OPEN = ['SUSPECTED', 'FIELD_CHECK_REQUESTED'];
  var LOSS = ['POTENTIAL_FOREST_LOSS', 'POTENTIAL_CHANGE_OUTSIDE_BOUNDARY'];
  var CHANGE_COLOURS = [
    {key: 'red', color: '#C94B42', dash: null, rank: 5, legend: 'cRed',
     test: function (e) { return OPEN.indexOf(e.status) >= 0 && LOSS.indexOf(e.classification) >= 0 && (e.confidence === 'MEDIUM' || e.confidence === 'HIGH'); }},
    {key: 'orange', color: '#D97736', dash: null, rank: 4, legend: 'cOrange',
     test: function (e) { return OPEN.indexOf(e.status) >= 0 && LOSS.indexOf(e.classification) >= 0 && e.confidence === 'LOW'; }},
    {key: 'yellow', color: '#D4B23A', dash: null, rank: 3, legend: 'cYellow',
     test: function (e) { return OPEN.indexOf(e.status) >= 0 && (e.classification === 'POSSIBLE_SEASONAL_OR_ENVIRONMENTAL' || e.classification === 'INSUFFICIENT_EVIDENCE'); }},
    {key: 'bluegrey', color: '#6E8496', dash: null, rank: 2, legend: 'cBlueGrey',
     test: function (e) { return e.status === 'REVIEW_CONFIRMED'; }},
    {key: 'grey', color: '#8A8F8C', dash: '5 4', rank: 1, legend: 'cGrey',
     test: function (e) { return e.status === 'REVIEW_REJECTED' || e.status === 'RECOVERED'; }}
  ];
  var UNKNOWN_COLOUR = {key: 'unknown', color: '#9AA39C', dash: '2 3', rank: 0, legend: 'cUnknown'};
  function changeColour(e) {
    for (var i = 0; i < CHANGE_COLOURS.length; i++) if (CHANGE_COLOURS[i].test(e || {})) return CHANGE_COLOURS[i];
    return UNKNOWN_COLOUR;
  }
  function worstColour(events) {
    var best = null;
    (events || []).forEach(function (e) { var c = changeColour(e); if (!best || c.rank > best.rank) best = c; });
    return best;
  }
  function isOpen(e) { return OPEN.indexOf(e && e.status) >= 0; }
  // "Most severe open event": colour rank (table order), then newest onset.
  function worstOpenEvent(events) {
    return (events || []).filter(isOpen).sort(function (x, y) {
      return changeColour(y).rank - changeColour(x).rank || String(y.first_after_time_utc || '').localeCompare(String(x.first_after_time_utc || ''));
    })[0] || null;
  }

  // ── time: stored UTC → Europe/Riga with an explicit offset ─────────────────────────────────────────────────────────
  function parseUtc(s) { if (!s) return null; var d = new Date(String(s).replace(' UTC', 'Z')); return isNaN(d) ? null : d; }
  function rigaParts(d) {
    var f = new Intl.DateTimeFormat('en-GB', {timeZone: 'Europe/Riga', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false}).formatToParts(d);
    var p = {}; f.forEach(function (x) { p[x.type] = x.value; });
    var local = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute);
    var off = Math.round((local - Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes())) / 3600000);
    return {date: p.year + '-' + p.month + '-' + p.day, time: (+p.hour % 24 < 10 ? '0' : '') + (+p.hour % 24) + ':' + p.minute,
            abbr: off === 3 ? 'EEST' : off === 2 ? 'EET' : 'UTC' + (off >= 0 ? '+' : '') + off, offset: off};
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function fmtTime(s, opts) {
    var d = parseUtc(s); if (!d) return null;
    var r = rigaParts(d), u = pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes());
    var udate = d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
    var utc = (udate !== r.date ? udate + ' ' : '') + u + ' UTC';
    return (opts && opts.timeOnly ? '' : r.date + ' ') + r.time + ' ' + r.abbr + ', ' + utc;
  }
  function fmtDate(s) { var d = parseUtc(s); return d ? rigaParts(d).date : null; }
  // Display date (Riga): LV "21.08.2026", EN "2026-08-21". short=true drops the year ("21.08.").
  function fmtDay(s, lang, short) {
    var d = parseUtc(s); if (!d) return null; var iso = rigaParts(d).date, p = iso.split('-');
    if ((lang || S.lang) === 'lv') return short ? p[2] + '.' + p[1] + '.' : p[2] + '.' + p[1] + '.' + p[0];
    return short ? p[1] + '-' + p[2] : iso;
  }
  // "09:02 EET · 07:02 UTC" (+ Riga date when it is not today's Riga date)
  function fmtClock(s, lang, nowIso) {
    var d = parseUtc(s); if (!d) return null; var r = rigaParts(d);
    var today = rigaParts(nowIso ? parseUtc(nowIso) : new Date()).date;
    return (r.date !== today ? fmtDay(s, lang, true) + ' ' : '') + r.time + ' ' + r.abbr + ' · ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ' UTC';
  }

  // ── acquisitions: timeline state, compare-pair rules ───────────────────────────────────────────────────────────────
  function acqState(a, minValid) {
    if (!a) return 'invalid';
    if (a.status === 'SKIPPED_CLOUD') return 'cloud';
    if (a.status === 'NO_VALID_PIXELS' || a.status === 'ERROR' || a.status === 'FAILED') return 'invalid';
    if (a.status !== 'OK') return 'pending';
    if (typeof a.valid_pct_inside !== 'number') return 'low';
    return a.valid_pct_inside >= (typeof minValid === 'number' ? minValid : 60) ? 'ok' : 'low';
  }
  function sameGeometry(a, b) { return a.orbit_direction === b.orbit_direction && a.relative_orbit === b.relative_orbit; }
  function comparePair(before, after) {
    if (!before || !after) return {ok: false, reason: 'pairMissing'};
    if (before.acq_id === after.acq_id) return {ok: false, reason: 'pairSame'};
    if (before.sensor !== after.sensor) return {ok: false, reason: 'pairSensor'};
    if (before.sensor === 'S1' && !sameGeometry(before, after)) return {ok: false, reason: 'pairGeometry'};
    if (!before.quicklook_url || !after.quicklook_url) return {ok: false, reason: 'pairNoImage'};
    if (String(before.sensing_time_utc) >= String(after.sensing_time_utc)) return {ok: false, reason: 'pairOrder'};
    return {ok: true, reason: null};
  }
  // never mix composites: true colour only when BOTH sides have it
  function pairComposite(before, after, wanted) {
    if (!before || !after || before.sensor !== 'S2') return before && before.sensor === 'S1' ? 's1' : 'false';
    return wanted === 'true' && before.truecolor_url && after.truecolor_url ? 'true' : 'false';
  }
  function singleComposite(a, wanted) { return !a ? null : a.sensor === 'S1' ? 's1' : wanted === 'true' && a.truecolor_url ? 'true' : 'false'; }
  function imageUrl(a, composite) { return composite === 'true' && a.truecolor_url ? a.truecolor_url : a.quicklook_url; }
  // default pair: last clear before + first after of the SAME sensor; S2 when the event has an S2 after-image
  function defaultPair(ev, byId, minValid) {
    var after = (ev.after || []).map(function (x) { return byId[x.acq_id] || x; });
    var before = (ev.before || []).map(function (x) { return byId[x.acq_id] || x; });
    function usable(a) { return a && a.quicklook_url && acqState(a, minValid) === 'ok'; }
    var a2 = after.filter(function (a) { return a.sensor === 'S2' && usable(a); })
                  .sort(function (x, y) { return String(x.sensing_time_utc).localeCompare(String(y.sensing_time_utc)); })[0];
    if (a2) {
      var b2 = before.filter(function (b) { return b.sensor === 'S2' && usable(b) && b.sensing_time_utc < a2.sensing_time_utc; })
                     .sort(function (x, y) { return String(y.sensing_time_utc).localeCompare(String(x.sensing_time_utc)); })[0];
      if (b2) return {before: b2, after: a2};
    }
    var a1 = after.filter(function (a) { return a.sensor === 'S1' && usable(a); })
                  .sort(function (x, y) { return String(x.sensing_time_utc).localeCompare(String(y.sensing_time_utc)); })[0];
    if (a1) {
      var b1 = before.filter(function (b) { return b.sensor === 'S1' && usable(b) && sameGeometry(a1, b) && b.sensing_time_utc < a1.sensing_time_utc; })
                     .sort(function (x, y) { return String(y.sensing_time_utc).localeCompare(String(x.sensing_time_utc)); })[0];
      if (b1) return {before: b1, after: a1};
    }
    return {before: null, after: null};
  }
  // True-colour alternative (owner C1 review): when the default pair cannot be shown in true colour, look for another valid
  // S2 pair of the SAME event (its own before / after lists) with true colour on BOTH sides: latest such baseline before
  // the onset, earliest such after-image. Offered as a hint only — never switched silently.
  function trueColourAlternative(ev, byId, minValid, current) {
    if (!ev) return null;
    if (current && current.before && current.after && pairComposite(current.before, current.after, 'true') === 'true') return null;
    function ok(a) { return a && a.sensor === 'S2' && a.truecolor_url && a.quicklook_url && acqState(a, minValid) === 'ok'; }
    var onset = ev.first_after_time_utc ? parseUtc(ev.first_after_time_utc).toISOString() : null;
    var after = (ev.after || []).map(function (x) { return byId[x.acq_id] || x; }).filter(ok)
      .sort(function (x, y) { return String(x.sensing_time_utc).localeCompare(String(y.sensing_time_utc)); })[0];
    if (!after) return null;
    var before = (ev.before || []).map(function (x) { return byId[x.acq_id] || x; }).filter(function (b) {
      var d = parseUtc(b.sensing_time_utc);
      return ok(b) && b.sensing_time_utc < after.sensing_time_utc && d && (!onset || d.toISOString() < onset);
    }).sort(function (x, y) { return String(y.sensing_time_utc).localeCompare(String(x.sensing_time_utc)); })[0];
    if (!before || !comparePair(before, after).ok) return null;
    if (current && current.before && current.after && current.before.acq_id === before.acq_id && current.after.acq_id === after.acq_id) return null;
    return {before: before, after: after};
  }
  // VMD p_cirg / p_cirp: stored 0 / 0.0 / NULL mean "not stated" — never a year
  function vmdValue(v) { return v === null || v === undefined || v === '' || Number(v) === 0 ? null : (Number(v) % 1 === 0 ? String(Number(v)) : String(v)); }
  // "Last clear acquisition without change" = latest valid baseline strictly before the first after-image.
  function lastClearBeforeOf(ev, byId, mv) {
    var onset = ev.first_after_time_utc ? String(parseUtc(ev.first_after_time_utc).toISOString()) : null;
    var list = (ev.before || []).map(function (x) { return byId[x.acq_id] || x; }).filter(function (x) {
      var d = parseUtc(x.sensing_time_utc);
      return acqState(x, mv) === 'ok' && d && (!onset || d.toISOString() < onset);
    });
    return list.sort(function (x, y) { return String(y.sensing_time_utc).localeCompare(String(x.sensing_time_utc)); })[0] || null;
  }
  // Area events carry before_acq_ids / after_acq_ids (ids only); make them look like /events/{id} lists.
  function eventLists(e) {
    var ids = function (v) { return (v || []).map(function (i) { return {acq_id: i}; }); };
    return {first_after_time_utc: e.first_after_time_utc, before: e.before || ids(e.before_acq_ids), after: e.after || ids(e.after_acq_ids)};
  }

  // D2: event-level evidence quality WITH its source. The event value is the best over its after-images
  // (pipeline.py, unchanged); per-acquisition values come from /events/{id} after[].evidence_quality.
  // → {eq, source: {sensor, time} | null, others: [{sensor, eq}]}  (others = best value of every OTHER sensor)
  var EQ_ORDER = {POOR: 0, LIMITED: 1, GOOD: 2};
  function evidenceSource(ev) {
    var eq = ev && ev.evidence_quality || null;
    var after = ((ev && ev.after) || []).filter(function (a) { return a && a.evidence_quality; });
    if (!eq || !after.length) return {eq: eq, source: null, others: []};
    var src = after.filter(function (a) { return a.evidence_quality === eq; })
                   .sort(function (x, y) { return String(x.sensing_time_utc).localeCompare(String(y.sensing_time_utc)); })[0] || null;
    var others = {};
    after.forEach(function (a) {
      if (src && a.sensor === src.sensor) return;
      if (!(a.sensor in others) || EQ_ORDER[a.evidence_quality] > EQ_ORDER[others[a.sensor]]) others[a.sensor] = a.evidence_quality;
    });
    return {eq: eq, source: src ? {sensor: src.sensor, time: src.sensing_time_utc} : null,
            others: Object.keys(others).sort().map(function (k) { return {sensor: k, eq: others[k]}; })};
  }

  // Coordinate search: an EXACT copy of parseCoordinates() in assets/forest-map.js (owner Q3: copied, not shared, so
  // forest-map.js stays byte-identical). tests/test_sat_workspace.js runs both copies on the same inputs.
  function parseCoordinates(text){const raw=String(text||'').trim();if(!raw)return null;const commas=(raw.match(/,/g)||[]).length;let parts;if(raw.includes(';'))parts=raw.split(';');else if(/,\s/.test(raw))parts=raw.split(/,\s+/);else if(/\s/.test(raw))parts=raw.split(/\s+/);else if(commas===1)parts=raw.split(',');else if(commas===3&&!raw.includes('.')){const c=raw.split(',');parts=[c[0]+'.'+c[1],c[2]+'.'+c[3]];}else return null;parts=parts.map(x=>x.trim().replace(/,$/,'').trim()).filter(Boolean);if(parts.length!==2)return null;const nums=parts.map(x=>{const v=x.replace(',','.');return /^[+-]?\d+(\.\d+)?$/.test(v)?Number(v):NaN;});if(!nums.every(Number.isFinite))return null;const lat=nums[0],lon=nums[1];return {lat,lon,inLatvia:lat>=55&&lat<=59&&lon>=20&&lon<=29};}

  // Point in a GeoJSON Polygon / MultiPolygon (WGS84 lon/lat, ray casting; holes respected). No projection needed.
  function inRing(lon, lat, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function inGeometry(lon, lat, g) {
    if (!g) return false;
    var polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
    return polys.some(function (p) { return p.length && inRing(lon, lat, p[0]) && !p.slice(1).some(function (h) { return inRing(lon, lat, h); }); });
  }

  // ── strings: EN + LV (LV = the i18n-lv.js translation of EN, checked by tests) ────────────────────────────────────
  var T_EN = {
    title: 'Satellite Monitoring', refresh: 'Refresh', na: 'Not available', notStated: 'not stated', loading: 'Loading…', error: 'Error',
    tabTerritory: 'Territory', tabChanges: 'Changes', tabEvidence: 'Evidence', tabsLabel: 'Satellite monitoring views',
    searchPh: 'Coordinates, cadastre no. (11 digits), VMD:… or area name', searchBtn: 'Search', searchLabel: 'Search a place',
    searchHint: 'Coordinates in WGS84 (latitude, longitude); decimal comma is accepted.', searchNone: 'Nothing found.',
    searchCoordsBad: 'Enter latitude, longitude in Latvia (55–59, 20–29).', searchFound: 'Found: {n}', modesLabel: 'Comparison mode',
    modeSwipe: 'Swipe', modeSide: 'Side by side', modeChange: 'Change only', modeOff: 'Choose an event or a "before" acquisition (Shift+click on the timeline) to compare.',
    langSwitch: 'Language',
    areas: 'Territories', areasCount: '{n} areas', areaSelect: 'Monitored area', srcSECTOR: 'Sector', srcLVM_GEO: 'LVM GEO', srcEVAL_BBOX: 'Evaluation area',
    dOK: 'Data OK', dNO_DATA_YET: 'No data yet', dBACKFILL_OR_FETCH_IN_PROGRESS: 'Fetching', dSTOPPED: 'Stopped',
    lastAcq: 'Last acquisition', lastValidS2: 'Last valid S2', lastAnalysis: 'Last analysis', lastCheck: 'System check',
    onMap: 'Acquisition on the map', optical: 'S2 · Optical', radar: 'S1 · Radar', noSensor: 'No processed acquisitions of this sensor.',
    prevAcq: 'Previous acquisition', nextAcq: 'Next acquisition', valid: 'valid {v} %', px10: '10 m/px',
    imageKind: 'Image type', trueC: 'True colour', trueSub: 'B04 · B03 · B02 — as the eye sees it', falseC: 'False colour',
    falseSub: 'Vegetation and clearings in contrast', radarC: 'Radar image (VH)', radarSub: 'Not a photograph',
    compositeNote: 'True colour is not available for both images — false colour on both sides.',
    tcHint: 'A true-colour pair is available: {before} → {after} — show',
    layers: 'Layers', lBoundary: 'Area boundary', lBuffer: 'Buffer zone', lChange: 'Change polygons', lVmd: 'VMD compartments', lBase: 'Background map',
    eventsTitle: 'Changes in the area', eventsCount: '{open} open · {rec} recovered', noEvents: 'No suspected change events in this area.',
    noEventsHint: 'Monitoring is running; no change has been detected.', noDataYet: 'Monitoring has not produced data yet.',
    inside: 'inside the boundary', outside: 'outside the boundary', confShort: 'confidence {c}',
    cRed: 'Potential forest loss — high/medium confidence', cOrange: 'Potential forest loss — low confidence',
    cYellow: 'Possible seasonal/environmental change or insufficient evidence', cBlueGrey: 'Confirmed by review', cGrey: 'Rejected or recovered',
    cUnknown: 'Other status',
    clsLOSS: 'Potential forest loss', clsOUT: 'Potential change outside the boundary', clsSEAS: 'Possible seasonal or environmental change',
    clsINS: 'Insufficient evidence', shortLOSS: 'Pot. forest loss', shortOUT: 'Outside boundary', shortSEAS: 'Seasonal?', shortINS: 'Insufficient',
    sSUSPECTED: 'Suspected change', sRECOVERED: 'Recovered', sREVIEW_CONFIRMED: 'Confirmed by review', sREVIEW_REJECTED: 'Rejected by review',
    sFIELD_CHECK_REQUESTED: 'Field check requested', seasonalTag: 'seasonal caveat',
    HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low', GOOD: 'Good', LIMITED: 'Limited', POOR: 'Poor',
    confidence: 'Confidence', evidence: 'Evidence', eventN: 'EVENT #{id}', story: 'What changed',
    storyTpl: 'Between {before} and {after} the satellite recorded vegetation loss on {ha} — suspected change, not verified on the ground.',
    storyNoBefore: 'Before-image date not available',
    eqFrom: 'from {sensor} {date}', eqOthers: '{sensor}: {eq}', eqNoSource: 'source per image not available',
    sensS1: 'radar (S1)', sensS2: 'optical (S2)', othS1: 'radar', othS2: 'optical',
    pillBefore: 'BEFORE', pillAfter: 'AFTER', pillShown: 'SHOWN',
    aEvidence: 'Open evidence', aField: 'Field check', aRisk: 'Create risk', aReject: 'Reject', aUndo: 'Undo',
    cField: 'Send a field check request to the dispatcher (Telegram)?', cRisk: 'Create a risk for this suspected change?',
    cReject: 'Mark this suspected change as rejected (not a real change)?', cUndo: 'Undo the last review decision?', close: 'Close',
    superseded: 'This event was superseded by #{id} (newer detection generation).', supersededNone: 'This event was superseded; no successor found.',
    toolWhatHere: 'What is here?', toolWhatHereTip: 'Click anywhere on the map: coordinates, cadastre, VMD compartment, whether the place is monitored — and "Add to monitoring".',
    hintDismiss: 'Got it', zoomIn: 'Zoom in', zoomOut: 'Zoom out', copyLink: 'Copy link to this view', copied: 'Copied', copy: 'Copy',
    whCoords: 'Coordinates (WGS84)', whArea: 'Monitored area', whNotMonitored: 'This place is not monitored',
    whCompartment: 'VMD compartment', whCadastre: 'Cadastre', whZoomIn: 'Zoom in to inspect compartments.', whZoomBtn: 'Zoom in',
    whNoForest: 'No forest compartment at this location.', whDense: 'Dense location; zoom in to inspect.', whComplex: 'Complex geometry; use the cadastre search.',
    whAdd: 'Add to monitoring', whQueued: 'Queued for monitoring', whAlready: 'Already monitored', whMulti: 'Multi-part compartment: add each part via LVM GEO',
    whOpenArea: 'Open the area', whLoading: 'Checking…',
    addQ: 'Add “{name}” to satellite monitoring?', addCost: 'Expected Copernicus cost: Not available.',
    addMonth: 'This month: {pu} of {puGuard} PU, {req} of {reqGuard} requests (guard).', addFirst: 'The last 120 days are fetched first.',
    addDone: 'Queued. The worker fetches the data within minutes.',
    analysis: 'Analysis', tsS2: 'Sentinel-2 indices (median inside the area)', tsS1: 'Sentinel-1 backscatter (median inside the area)',
    timeline: 'Time axis', tlS2: 'S2 optical', tlS1: 'S1 radar', days120: '120 days', allDays: 'All time', shiftHint: 'Click — show; Shift+click — set as “before”.',
    stOk: 'Valid', stLow: 'Below validity threshold', stCloud: 'Clouds — skipped', stInvalid: 'No valid pixels / error', stPending: 'Pending',
    cloudPct: 'clouds', validPct: 'valid', orbit: 'orbit',
    copOk: 'Copernicus OK', copDegraded: 'Copernicus problem', copUnknown: 'Copernicus status unknown', reqGuard: 'requests {v} / {g}',
    puGuard: 'PU {v} / {g}', nextRun: 'next fetch {t}', autoRiskOff: 'automatic risks: off', autoRiskOn: 'automatic risks: ON',
    basemapNote: 'Background map: OpenStreetMap (not dated, not Sentinel)', attribution: 'Contains modified Copernicus Sentinel data {year}',
    dbUnavailable: 'Satellite monitoring data is unavailable (satellite.db).', retry: 'Try again',
    latest: 'Latest changes', allAreas: 'All areas', addSector: 'Add sector', fetchNow: 'Fetch now', thArea: 'Territory', thStatus: 'Status',
    thOpen: 'Open events', thLast: 'Last acquisition', open: 'Open', noAreas: 'No monitored areas yet.', firstArea: 'Add the first area',
    noAreasHint: 'Search a place above, or use “Add to satellite monitoring” in LVM GEO.', ndvi: 'NDVI (median)',
    noThumb: 'No image', thumbsNote: 'before | after', evPick: 'Choose an event to open its evidence.', imgLoading: 'Loading image…',
    imgFailed: 'The image could not be loaded.', fetchConfirm: 'Fetch new Sentinel-1/2 observations for all areas now?',
    sectorAddConfirm: 'Add {name} to satellite monitoring? The last 120 days are fetched first.', monitored: 'Monitored', queued: 'Queued',
    noPolygon: 'No polygon', add: 'Add', copLink: 'Link copied'
  };
  var T_LV = {
    title: 'Satelītu monitorings', refresh: 'Atjaunot', na: 'Nav pieejams', notStated: 'nav norādīts', loading: 'Ielādē…', error: 'Kļūda',
    tabTerritory: 'Teritorija', tabChanges: 'Izmaiņas', tabEvidence: 'Pierādījumi', tabsLabel: 'Satelītu monitoringa skati',
    searchPh: 'Koordinātas, kadastra nr. (11 cipari), VMD:… vai teritorijas nosaukums', searchBtn: 'Meklēt', searchLabel: 'Meklēt vietu',
    searchHint: 'Koordinātas WGS84 (platums, garums); decimālais komats ir atļauts.', searchNone: 'Nekas netika atrasts.',
    searchCoordsBad: 'Ievadiet platumu, garumu Latvijā (55–59, 20–29).', searchFound: 'Atrasti: {n}', modesLabel: 'Salīdzināšanas režīms',
    modeSwipe: 'Pārvilkt', modeSide: 'Blakus', modeChange: 'Tikai izmaiņas', modeOff: 'Izvēlieties notikumu vai “pirms” uzņēmumu (Shift+klikšķis laika asī), lai salīdzinātu.',
    langSwitch: 'Valoda',
    areas: 'Teritorijas', areasCount: '{n} teritorijas', areaSelect: 'Uzraudzītā teritorija', srcSECTOR: 'Sektors', srcLVM_GEO: 'LVM GEO', srcEVAL_BBOX: 'Novērtējuma teritorija',
    dOK: 'Dati kārtībā', dNO_DATA_YET: 'Vēl nav datu', dBACKFILL_OR_FETCH_IN_PROGRESS: 'Notiek ielāde', dSTOPPED: 'Apturēts',
    lastAcq: 'Pēdējais uzņēmums', lastValidS2: 'Pēdējais derīgais S2', lastAnalysis: 'Pēdējā analīze', lastCheck: 'Sistēmas pārbaude',
    onMap: 'Uzņēmums kartē', optical: 'S2 · Optiskais', radar: 'S1 · Radars', noSensor: 'Šim sensoram nav apstrādātu uzņēmumu.',
    prevAcq: 'Iepriekšējais uzņēmums', nextAcq: 'Nākamais uzņēmums', valid: 'derīgi {v} %', px10: '10 m/px',
    imageKind: 'Attēla veids', trueC: 'Patiesās krāsas', trueSub: 'B04 · B03 · B02 — kā redz acs', falseC: 'Viltus krāsas',
    falseSub: 'Veģetācija un izcirtumi kontrastā', radarC: 'Radara attēls (VH)', radarSub: 'Nav fotogrāfija',
    compositeNote: 'Patiesās krāsas nav abiem attēliem — abās pusēs rādītas viltus krāsas.',
    tcHint: 'Ir pieejams patiesu krāsu pāris: {before} → {after} — rādīt',
    layers: 'Slāņi', lBoundary: 'Teritorijas robeža', lBuffer: 'Buferzona', lChange: 'Izmaiņu poligoni', lVmd: 'VMD nogabali', lBase: 'Fona karte',
    eventsTitle: 'Izmaiņas teritorijā', eventsCount: '{open} atvērtas · {rec} atjaunojušās', noEvents: 'Šajā teritorijā nav iespējamo izmaiņu notikumu.',
    noEventsHint: 'Uzraudzība darbojas; izmaiņas nav konstatētas.', noDataYet: 'Uzraudzība vēl nav sniegusi datus.',
    inside: 'robežās', outside: 'ārpus robežas', confShort: 'ticamība {c}',
    cRed: 'Iespējams meža zudums — augsta/vidēja ticamība', cOrange: 'Iespējams meža zudums — zema ticamība',
    cYellow: 'Iespējamas sezonālas vai vides izmaiņas / nepietiekami pierādījumi', cBlueGrey: 'Apstiprināts pārskatīšanā', cGrey: 'Noraidīts vai atjaunojies',
    cUnknown: 'Cits statuss',
    clsLOSS: 'Iespējams meža zudums', clsOUT: 'Iespējamas izmaiņas ārpus robežas', clsSEAS: 'Iespējamas sezonālas vai vides izmaiņas',
    clsINS: 'Nepietiekami pierādījumi', shortLOSS: 'Iesp. meža zudums', shortOUT: 'Ārpus robežas', shortSEAS: 'Sezonāls?', shortINS: 'Nepietiek datu',
    sSUSPECTED: 'Iespējamas izmaiņas', sRECOVERED: 'Atjaunojies', sREVIEW_CONFIRMED: 'Apstiprināts pārskatīšanā', sREVIEW_REJECTED: 'Noraidīts pārskatīšanā',
    sFIELD_CHECK_REQUESTED: 'Pieprasīta lauka pārbaude', seasonalTag: 'sezonāls brīdinājums',
    HIGH: 'Augsta', MEDIUM: 'Vidēja', LOW: 'Zema', GOOD: 'Laba', LIMITED: 'Ierobežota', POOR: 'Vāja',
    confidence: 'Ticamība', evidence: 'Pierādījumi', eventN: 'NOTIKUMS #{id}', story: 'Kas mainījās',
    storyTpl: 'Starp {before} un {after} satelīts reģistrēja veģetācijas izzušanu {ha} platībā — iespējamas izmaiņas, dabā nav pārbaudīts.',
    storyNoBefore: 'Pirms attēla datums nav pieejams',
    eqFrom: 'no {sensor} {date}', eqOthers: '{sensor}: {eq}', eqNoSource: 'avots pa attēliem nav pieejams',
    sensS1: 'radara (S1)', sensS2: 'optiskā (S2)', othS1: 'radars', othS2: 'optiskie',
    pillBefore: 'PIRMS', pillAfter: 'PĒC', pillShown: 'KARTĒ',
    aEvidence: 'Atvērt pierādījumus', aField: 'Lauka pārbaude', aRisk: 'Izveidot risku', aReject: 'Noraidīt', aUndo: 'Atsaukt',
    cField: 'Nosūtīt lauka pārbaudes pieprasījumu dispečeram (Telegram)?', cRisk: 'Izveidot risku šīm iespējamajām izmaiņām?',
    cReject: 'Atzīmēt šīs iespējamās izmaiņas kā noraidītas (nav reālas izmaiņas)?', cUndo: 'Atsaukt pēdējo pārskatīšanas lēmumu?', close: 'Aizvērt',
    superseded: 'Šis notikums ir aizstāts ar #{id} (jaunāka noteikšanas paaudze).', supersededNone: 'Šis notikums ir aizstāts; pēctecis nav atrasts.',
    toolWhatHere: 'Kas šeit?', toolWhatHereTip: 'Klikšķis jebkurā kartes vietā: koordinātas, kadastrs, VMD nogabals, vai vieta tiek uzraudzīta — un “Pievienot monitoringam”.',
    hintDismiss: 'Skaidrs', zoomIn: 'Tuvināt', zoomOut: 'Tālināt', copyLink: 'Kopēt saiti uz šo skatu', copied: 'Nokopēts', copy: 'Kopēt',
    whCoords: 'Koordinātas (WGS84)', whArea: 'Uzraudzītā teritorija', whNotMonitored: 'Šī vieta netiek uzraudzīta',
    whCompartment: 'VMD nogabals', whCadastre: 'Kadastrs', whZoomIn: 'Pietuviniet, lai redzētu nogabalus.', whZoomBtn: 'Tuvināt',
    whNoForest: 'Šajā vietā nav meža nogabala.', whDense: 'Blīva vieta; pietuviniet.', whComplex: 'Sarežģīta ģeometrija; izmantojiet kadastra meklēšanu.',
    whAdd: 'Pievienot monitoringam', whQueued: 'Gaida pievienošanu monitoringam', whAlready: 'Jau tiek uzraudzīts', whMulti: 'Daudzdaļu nogabals: pievienojiet katru daļu LVM GEO',
    whOpenArea: 'Atvērt teritoriju', whLoading: 'Pārbauda…',
    addQ: 'Pievienot “{name}” satelītu monitoringam?', addCost: 'Paredzamās Copernicus izmaksas: Nav pieejams.',
    addMonth: 'Šomēnes: {pu} no {puGuard} PU, {req} no {reqGuard} pieprasījumiem (drošības robeža).', addFirst: 'Vispirms tiks ielādētas pēdējās 120 dienas.',
    addDone: 'Ievietots rindā. Apstrādes process ielādēs datus dažu minūšu laikā.',
    analysis: 'Analīze', tsS2: 'Sentinel-2 indeksi (mediāna teritorijā)', tsS1: 'Sentinel-1 atstarošana (mediāna teritorijā)',
    timeline: 'Laika ass', tlS2: 'S2 optiskais', tlS1: 'S1 radars', days120: '120 dienas', allDays: 'Viss', shiftHint: 'Klikšķis — rādīt; Shift+klikšķis — iestatīt kā “pirms”.',
    stOk: 'Derīgs', stLow: 'Zem derīguma sliekšņa', stCloud: 'Mākoņi — izlaists', stInvalid: 'Nav derīgu pikseļu / kļūda', stPending: 'Gaida',
    cloudPct: 'mākoņi', validPct: 'derīgi', orbit: 'orbīta',
    copOk: 'Copernicus OK', copDegraded: 'Copernicus problēma', copUnknown: 'Copernicus statuss nav zināms', reqGuard: 'pieprasījumi {v} / {g}',
    puGuard: 'PU {v} / {g}', nextRun: 'nākamā ielāde {t}', autoRiskOff: 'automātiskie riski: izslēgti', autoRiskOn: 'automātiskie riski: IESLĒGTI',
    basemapNote: 'Fona karte: OpenStreetMap (nav datēta, nav Sentinel)', attribution: 'Contains modified Copernicus Sentinel data {year}',
    dbUnavailable: 'Satelītu monitoringa dati nav pieejami (satellite.db).', retry: 'Mēģināt vēlreiz',
    latest: 'Jaunākās izmaiņas', allAreas: 'Visas teritorijas', addSector: 'Pievienot sektoru', fetchNow: 'Ielādēt tagad', thArea: 'Teritorija', thStatus: 'Statuss',
    thOpen: 'Atvērtas', thLast: 'Pēdējais uzņēmums', open: 'Atvērt', noAreas: 'Vēl nav uzraudzītu teritoriju.', firstArea: 'Pievienojiet pirmo teritoriju',
    noAreasHint: 'Meklējiet vietu augšā vai izmantojiet “Pievienot satelītu monitoringam” sadaļā LVM GEO.', ndvi: 'NDVI (mediāna)',
    noThumb: 'Nav attēla', thumbsNote: 'pirms | pēc', evPick: 'Izvēlieties notikumu, lai atvērtu tā pierādījumus.', imgLoading: 'Ielādē attēlu…',
    imgFailed: 'Attēlu neizdevās ielādēt.', fetchConfirm: 'Ielādēt jaunos Sentinel-1/2 uzņēmumus visām teritorijām tagad?',
    sectorAddConfirm: 'Pievienot {name} satelītu monitoringam? Vispirms tiks ielādētas pēdējās 120 dienas.', monitored: 'Tiek uzraudzīts', queued: 'Rindā',
    noPolygon: 'Nav poligona', add: 'Pievienot', copLink: 'Saite nokopēta'
  };
  var CLS = {POTENTIAL_FOREST_LOSS: 'LOSS', POTENTIAL_CHANGE_OUTSIDE_BOUNDARY: 'OUT', POSSIBLE_SEASONAL_OR_ENVIRONMENTAL: 'SEAS', INSUFFICIENT_EVIDENCE: 'INS'};
  var MONTHS_LV = ['janv.', 'febr.', 'marts', 'apr.', 'maijs', 'jūn.', 'jūl.', 'aug.', 'sept.', 'okt.', 'nov.', 'dec.'];
  var MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var GEOM_COLOURS = ['#8FB4D9', '#B9A2E8', '#6FC7B1', '#E0A36F', '#D98CB5', '#A9C26F'];

  // ── state ────────────────────────────────────────────────────────────────────────────────────────────────────────────
  function store(k, v) { try { if (v === undefined) return global.localStorage && global.localStorage.getItem(k); global.localStorage.setItem(k, v); } catch (e) { return null; } return null; }
  var S = {lang: store('satMonitoring.lang') === 'en' ? 'en' : 'lv', view: null, areaId: null, area: null, ov: null, health: null, layer: null,
           events: [], byId: {}, sel: null, ev: null, acq: null, sensor: 'S2', composite: 'true', compare: null, mode: null, window: 120,
           maps: [], seq: 0, whatHere: false, layersOn: {boundary: true, buffer: true, change: true, vmd: true, base: true}, target: null};
  function T() { return S.lang === 'lv' ? T_LV : T_EN; }
  function t(k, vars) {
    var s = T()[k]; if (s === undefined) s = T_EN[k] === undefined ? k : T_EN[k];
    if (vars) Object.keys(vars).forEach(function (n) { s = s.split('{' + n + '}').join(vars[n]); });
    return s;
  }
  function esc(v) { return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function fmtNum(v, d) {
    if (!isNum(v)) return null;
    return S.lang === 'lv' ? v.toLocaleString('lv-LV', {minimumFractionDigits: d, maximumFractionDigits: d}).replace(/ /g, ' ') : v.toFixed(d);
  }
  function ha(v, d) { var n = fmtNum(v, d === undefined ? 2 : d); return n === null ? null : n + ' ha'; }
  function na() { return '<span class="satw-na">' + esc(t('na')) + '</span>'; }
  function val(v) { return v === null || v === undefined || v === '' ? na() : '<span class="satw-mono" data-no-i18n>' + esc(v) + '</span>'; }
  function clsLabel(c) { return t('cls' + (CLS[c] || 'INS')); }
  function shortCls(c) { return t('short' + (CLS[c] || 'INS')); }
  function root() { return document.getElementById('satm-root'); }
  function dot(e) { var c = changeColour(e); return '<span class="satw-dot' + (c.dash ? ' dashed' : '') + '" style="--c:' + c.color + '" aria-hidden="true"></span>'; }
  function badge(text, cls) { return '<span class="satw-badge ' + (cls || '') + '">' + esc(text) + '</span>'; }
  function qClass(v) { return {HIGH: 'g', GOOD: 'g', MEDIUM: 'a', LIMITED: 'a', LOW: 'r', POOR: 'r'}[v] || ''; }
  function minValid() { return S.area && S.area.config ? S.area.config.min_valid_pct : null; }
  function geomKey(a) { return (a.orbit_direction || '?').slice(0, 3) + ' ' + (a.relative_orbit === null || a.relative_orbit === undefined ? '?' : a.relative_orbit); }

  async function get(path) {
    var r = await fetch(path.charAt(0) === '/' && path.indexOf('/api/') === 0 ? path : API + path, {credentials: 'same-origin', cache: 'no-store'}), d = {};
    try { d = await r.json(); } catch (e) { d = {}; }
    if (!r.ok) { var err = new Error(d.error || d.detail || ('HTTP ' + r.status)); err.status = r.status; err.body = d; throw err; }
    return d;
  }
  async function post(path, body) {
    var r = await fetch(API + path, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})}), d = {};
    try { d = await r.json(); } catch (e) { d = {}; }
    if (!r.ok) { var err = new Error(d.error || d.detail || ('HTTP ' + r.status)); err.status = r.status; err.body = d; throw err; }
    return d;
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
  function fonts() {
    if (document.querySelector('link[href="' + FONTS_CSS + '"]')) return;
    var c = document.createElement('link'); c.rel = 'stylesheet'; c.href = FONTS_CSS; document.head.appendChild(c);
  }
  function cleanup() {
    S.maps.forEach(function (m) { try { m.remove(); } catch (e) { /* gone */ } });
    S.maps = []; S.map = null; S.map2 = null; S.L = null; S.swipe = null;
  }
  function pageHead() {
    var pt = document.getElementById('page-title'), pr = document.getElementById('page-refresh');
    if (pt) pt.textContent = t('title'); if (pr) pr.textContent = '↻ ' + t('refresh');
  }
  function legacy() { var sm = global.SatMonitoring || {}; return sm._legacy || sm; }

  // ── deep links: #sat-monitoring?area=&event=&tab=&acq=&before=&mode=&lat=&lon=&z= ─────────────────────────────────
  function hashParams() {
    var h = String(global.location && global.location.hash || ''), i = h.indexOf('?'), out = {};
    if (h.indexOf('#sat-monitoring') !== 0 || i < 0) return out;
    h.slice(i + 1).split('&').forEach(function (kv) { var p = kv.split('='); if (p[0]) out[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || ''); });
    return out;
  }
  function buildHash(p) {
    var keys = ['area', 'event', 'tab', 'acq', 'before', 'mode', 'lat', 'lon', 'z'].filter(function (k) { return p[k] !== undefined && p[k] !== null && p[k] !== ''; });
    return '#sat-monitoring' + (keys.length ? '?' + keys.map(function (k) { return k + '=' + encodeURIComponent(p[k]); }).join('&') : '');
  }
  function setHash(p, replace) {
    var h = buildHash(p); if (global.location.hash === h) return;
    try { global.history[replace ? 'replaceState' : 'pushState']({type: 'nav', id: 'sat-monitoring'}, '', h); } catch (e) { /* no history */ }
  }
  function viewParams() {
    var p = {area: S.areaId, event: S.sel};
    if (S.view === 'evidence') p.tab = 'evidence';
    if (S.view === 'changes') {
      if (S.acq) p.acq = S.acq.acq_id;
      if (S.compare && S.compare.before && S.mode) { p.before = S.compare.before.acq_id; p.mode = S.mode; }
      if (S.map) { var c = S.map.getCenter(); p.lat = c.lat.toFixed(5); p.lon = c.lng.toFixed(5); p.z = String(Math.round(S.map.getZoom() * 4) / 4); }
    }
    return p;
  }
  // index.html calls nav('sat-monitoring') (→ load) and then openArea / openEvent for the same deep link: open once.
  function claim(key) { var now = Date.now(); if (S.target && S.target.key === key && now - S.target.at < 2000) return false; S.target = {key: key, at: now}; return true; }

  // ── shell: header (tabs · search · compare modes · language) + body ──────────────────────────────────────────────────
  function shell(view, body) {
    var r = root(); if (!r) return null;
    fonts();
    S.view = view; r.className = 'satw'; r.setAttribute('data-view', view); r.setAttribute('data-lang', S.lang);
    var tabs = [['territory', 'tabTerritory'], ['changes', 'tabChanges'], ['evidence', 'tabEvidence']];
    r.innerHTML = '<header class="satw-hdr">' +
      '<div class="satw-brand"><span class="satw-brand-a">Forest AI</span><span class="satw-brand-b">/ ' + esc(t('title')) + '</span></div>' +
      '<nav class="satw-tabs" role="tablist" aria-label="' + esc(t('tabsLabel')) + '">' + tabs.map(function (x) {
        return '<button type="button" role="tab" aria-selected="' + (x[0] === view) + '" class="satw-tab' + (x[0] === view ? ' on' : '') + '" data-tab="' + x[0] + '">' + esc(t(x[1])) + '</button>';
      }).join('') + '</nav>' +
      '<form class="satw-search" role="search"><label class="satw-sr" for="satw-q">' + esc(t('searchLabel')) + '</label>' +
        '<input id="satw-q" type="search" autocomplete="off" placeholder="' + esc(t('searchPh')) + '" title="' + esc(t('searchHint')) + '">' +
        '<span class="satw-search-tag" data-no-i18n>WGS84</span><button type="submit" class="satw-btn">' + esc(t('searchBtn')) + '</button>' +
        '<div id="satw-search-msg" class="satw-search-msg" role="status" hidden></div></form>' +
      '<div class="satw-modes" role="group" aria-label="' + esc(t('modesLabel')) + '">' + [['swipe', 'modeSwipe'], ['side', 'modeSide'], ['change', 'modeChange']].map(function (m) {
        return '<button type="button" class="satw-mode" data-mode="' + m[0] + '" aria-pressed="false" disabled>' + esc(t(m[1])) + '</button>';
      }).join('') + '</div>' +
      '<button type="button" class="satw-btn satw-ghost satw-lang" data-act="lang" aria-label="' + esc(t('langSwitch')) + '" data-no-i18n>' + (S.lang === 'lv' ? 'EN' : 'LV') + '</button>' +
      '</header><div class="satw-body">' + body + '</div>';
    pageHead();
    r.querySelectorAll('[data-tab]').forEach(function (b) { b.onclick = function () { goTab(b.getAttribute('data-tab')); }; });
    r.querySelector('[data-act=lang]').onclick = function () {
      S.lang = S.lang === 'lv' ? 'en' : 'lv'; store('satMonitoring.lang', S.lang);
      var lg = legacy(); if (lg._setLang) { try { lg._setLang(S.lang); } catch (e) { /* legacy page re-renders on open */ } }
      rerender();
    };
    r.querySelector('.satw-search').onsubmit = function (e) { e.preventDefault(); search(document.getElementById('satw-q').value); };
    r.querySelectorAll('[data-mode]').forEach(function (b) { b.onclick = function () { setMode(b.getAttribute('data-mode')); }; });
    return r;
  }
  function rerender() {
    if (S.view === 'changes' && S.areaId) openArea(S.areaId, Object.assign(viewParams(), {force: true}));
    else if (S.view === 'evidence') openEvidence(S.sel, true);
    else loadTerritory(true);
  }
  function goTab(tab) {
    if (tab === 'territory') { S.sel = null; setHash({}); loadTerritory(true); }
    else if (tab === 'changes') {
      var id = S.areaId || (S.ov && defaultAreaId(S.ov.areas, S.ovEvents || {}));
      if (id) { setHash({area: id, event: S.sel}); openArea(id, {event: S.sel, force: true}); } else loadTerritory(true);
    } else { setHash({area: S.areaId, event: S.sel, tab: 'evidence'}); openEvidence(S.sel, true); }
  }
  function errorView(e, retry) {
    var msg = e && e.status === 503 ? t('dbUnavailable') : t('error') + ': ' + (e && e.message ? e.message : e);
    var r = shell(S.view || 'territory', '<div class="satw-error" role="alert"><div class="satw-error-card"><h2>' + esc(t('title')) + '</h2><p>' + esc(msg) + '</p>' +
      '<button type="button" class="satw-btn" data-act="retry">' + esc(t('retry')) + '</button></div></div>');
    if (r) r.querySelector('[data-act=retry]').onclick = retry || function () { loadTerritory(true); };
  }

  // ── status bar (both tabs): Copernicus · requests vs guard · next run · automatic risks · basemap ───────────────────
  function statusBar(h) {
    h = h || {};
    var p = h.provider || {}, m = h.month || {}, u = h.worker && h.worker.units && h.worker.units.sync;
    var cop = p.state === 'OK' ? ['ok', t('copOk')] : p.state === 'UNKNOWN' || !p.state ? ['unk', t('copUnknown')] : ['bad', t('copDegraded')];
    var detail = p.state && p.state !== 'OK' ? (p.error || p.state) : '';
    var num = function (v, d) { return isNum(v) ? fmtNum(v, d) : t('na'); };
    return '<footer class="satw-status" role="contentinfo">' +
      '<button type="button" class="satw-cop ' + cop[0] + '" data-act="cop" aria-expanded="false" title="' + esc(detail) + '"><span class="satw-led" aria-hidden="true"></span>' + esc(cop[1]) + '</button>' +
      '<span data-no-i18n class="satw-mono">' + esc(t('reqGuard', {v: num(m.requests, 0), g: num(m.request_guard, 0)})) + '</span>' +
      '<span data-no-i18n class="satw-mono">' + esc(t('puGuard', {v: num(m.pu, 1), g: num(m.pu_guard, 0)})) + '</span>' +
      '<span>' + esc(t('nextRun', {t: u && u.next_run_utc ? fmtClock(u.next_run_utc).split(' · ')[0] : t('na')})) + '</span>' +
      '<span>' + esc(h.auto_risk_enabled === true ? t('autoRiskOn') : t('autoRiskOff')) + '</span>' +
      '<span class="satw-status-right">' + esc(t('basemapNote')) + '</span>' +
      '<div id="satw-cop-detail" class="satw-cop-detail" hidden><b>' + esc(cop[1]) + '</b><br><span data-no-i18n class="satw-mono">' + esc(detail || '—') + '</span>' +
        (p.at_utc ? '<br>' + esc(fmtClock(p.at_utc)) : '') + '</div></footer>';
  }
  function bindStatus() {
    var b = document.querySelector('.satw-cop'), d = document.getElementById('satw-cop-detail'); if (!b || !d) return;
    b.onclick = function () { d.hidden = !d.hidden; b.setAttribute('aria-expanded', String(!d.hidden)); };
  }

  // ── TERITORIJA ───────────────────────────────────────────────────────────────────────────────────────────────────────
  function defaultAreaId(areas, evByArea) {
    var best = null;
    (areas || []).filter(function (a) { return a.active; }).forEach(function (a) {
      var w = worstOpenEvent(evByArea[a.id] || []); if (!w) return;
      if (!best || changeColour(w).rank > changeColour(best.e).rank ||
          (changeColour(w).rank === changeColour(best.e).rank && String(w.first_after_time_utc) > String(best.e.first_after_time_utc))) best = {id: a.id, e: w};
    });
    return best ? best.id : null;
  }
  async function loadTerritory(force) {
    if (!force && !claim('territory')) return;
    var seq = ++S.seq; cleanup(); S.areaId = null; S.sel = null; S.ev = null; S.area = null;
    shell('territory', '<div class="satw-loading">' + esc(t('loading')) + '</div>');
    var ov, h, layer;
    try { var r = await Promise.all([get('/overview'), get('/health').catch(function () { return {}; }), get('/map-layer').catch(function () { return {features: []}; })]); ov = r[0]; h = r[1]; layer = r[2]; }
    catch (e) { if (seq === S.seq) errorView(e); return; }
    if (seq !== S.seq) return;
    S.ov = ov; S.health = h; S.layer = layer;
    var areas = ov.areas.filter(function (a) { return a.active; });
    var details = await Promise.all(areas.map(function (a) { return get('/areas/' + a.id + '?geometry=0').catch(function () { return null; }); }));
    if (seq !== S.seq) return;
    var det = {}; S.ovEvents = {};
    areas.forEach(function (a, i) { det[a.id] = details[i]; S.ovEvents[a.id] = details[i] ? details[i].events : []; });
    var html = '<div class="satw-work"><aside class="satw-left" aria-label="' + esc(t('areas')) + '">' +
        '<div class="satw-sec"><div class="satw-sec-h"><b>' + esc(t('areas')) + '</b><span class="satw-muted" data-no-i18n>' + areas.length + '</span></div>' +
        (areas.length ? areas.map(function (a) { return areaCard(a, det[a.id]); }).join('') :
          '<div class="satw-empty"><b>' + esc(t('noAreas')) + '</b><p>' + esc(t('noAreasHint')) + '</p><button type="button" class="satw-btn" data-act="focus-search">' + esc(t('firstArea')) + '</button></div>') + '</div>' +
        latestList(ov.latest_events || []) +
        '<details class="satw-sec satw-drawer"><summary>' + esc(t('allAreas')) + ' (' + areas.length + ')</summary>' + areasTable(areas) +
          '<div class="satw-actions"><button type="button" class="satw-btn" data-act="add-sector">' + esc(t('addSector')) + '</button>' +
          '<button type="button" class="satw-btn" data-act="fetch">' + esc(t('fetchNow')) + '</button></div><div id="satw-sectors"></div></details>' +
      '</aside><div class="satw-main"><div id="satw-mapwrap" class="satw-mapwrap"><div id="satw-map" class="satw-map" aria-label="Map"></div></div>' + statusBar(h) + '</div></div>';
    var r = shell('territory', html); if (!r) return;
    bindStatus();
    r.querySelectorAll('[data-area]').forEach(function (b) { b.onclick = function () { var ev = b.getAttribute('data-event'); var id = +b.getAttribute('data-area'); setHash({area: id, event: ev ? +ev : null}); openArea(id, {event: ev ? +ev : null, force: true}); }; });
    var fs = r.querySelector('[data-act=focus-search]'); if (fs) fs.onclick = function () { document.getElementById('satw-q').focus(); };
    r.querySelector('[data-act=fetch]').onclick = async function () { if (!global.confirm(t('fetchConfirm'))) return; try { await post('/fetch', {all: true}); loadTerritory(true); } catch (e) { global.alert(t('error') + ': ' + e.message); } };
    r.querySelector('[data-act=add-sector]').onclick = showSectors;
    var L = await leaflet(); if (seq !== S.seq) return;
    var map = baseMap(L, 'satw-map');
    var g = L.featureGroup().addTo(map), imgs = L.layerGroup().addTo(map);
    areas.forEach(function (a) {
      var d = det[a.id]; if (!a.geometry) return;
      var latest = d && latestValidOf(d.timeline, 'S2', d.config ? d.config.min_valid_pct : null);
      if (latest && a.grid_bbox) {
        var comp = singleComposite(latest, 'true');
        imgStatus(document.getElementById('satw-mapwrap'), L.imageOverlay(imageUrl(latest, comp), bboxBounds(a.grid_bbox), {pane: 'satwImg', opacity: 0.95})).addTo(imgs);
      }
      var c = worstColour((d && d.events || []).filter(isOpen));
      L.geoJSON(a.geometry, {pane: 'satwBoundary', style: {color: '#F5F5F0', weight: 1.6, opacity: 0.9, fill: true, fillOpacity: 0.02, fillColor: c ? c.color : '#7FBF8E'}})
        .bindTooltip(esc(a.name), {sticky: true}).on('click', function () { setHash({area: a.id}); openArea(a.id, {force: true}); }).addTo(g);
    });
    drawPolys(L, map, (layer.features || []).filter(function (f) { return f.properties && f.properties.kind === 'event' && isOpen(f.properties); }), null);
    mapRail(L, map);
    var did = defaultAreaId(areas, S.ovEvents), target = did && areas.filter(function (a) { return a.id === did; })[0];
    if (target && target.grid_bbox) map.fitBounds(bboxBounds(target.grid_bbox), {padding: [24, 24]});
    else if (g.getLayers().length) map.fitBounds(g.getBounds(), {padding: [40, 40], maxZoom: 14});
    else map.setView([56.95, 24.1], 10);                             // no areas: Riga region, never country zoom
    copernicusAttr(map, areas.map(function (a) { var d = det[a.id]; var x = d && latestValidOf(d.timeline, 'S2', null); return x && x.sensing_time_utc; }));
  }
  function latestValidOf(tl, sensor, mv) {
    return (tl || []).filter(function (x) { return x.sensor === sensor && x.quicklook_url && acqState(x, mv) === 'ok'; })
      .sort(function (x, y) { return String(y.sensing_time_utc).localeCompare(String(x.sensing_time_utc)); })[0] || null;
  }
  function areaCard(a, d) {
    var evs = d ? d.events : [], openN = evs.filter(isOpen), c = worstColour(openN);
    var counts = {}; openN.forEach(function (e) { var k = changeColour(e); counts[k.key] = counts[k.key] || {c: k, n: 0}; counts[k.key].n++; });
    // last OK acquisition of either sensor (last_s2_any is an object incl. cloud-skipped attempts — not used here)
    var lastAny = [a.last_s1_utc, a.last_valid_s2_utc].filter(function (x) { return typeof x === 'string' && x; }).sort().pop();
    return '<button type="button" class="satw-card" data-area="' + a.id + '">' +
      '<div class="satw-card-h"><b data-no-i18n>' + esc(a.name) + '</b>' + (c ? '<span class="satw-dot" style="--c:' + c.color + '" aria-hidden="true"></span>' : '') + '</div>' +
      '<div class="satw-muted">' + esc(t('src' + a.source)) + ' · <span data-no-i18n>' + esc(ha(a.area_ha, 1) || t('na')) + '</span></div>' +
      cardVisual(a, d) +
      '<div class="satw-card-f"><span>' + (Object.keys(counts).length ? Object.keys(counts).map(function (k) { return '<span class="satw-cnt" style="--c:' + counts[k].c.color + '" data-no-i18n>' + counts[k].n + '</span>'; }).join('') : '<span class="satw-muted">' + esc(t('thOpen')) + ': <span data-no-i18n>0</span></span>') + '</span>' +
        '<span class="satw-muted">' + esc(t('thLast')) + ': ' + (lastAny ? '<span data-no-i18n>' + esc(fmtDay(lastAny)) + '</span>' : esc(t('na'))) + '</span></div></button>';
  }
  function cardVisual(a, d) {
    if (!d) return '<div class="satw-card-v satw-na">' + esc(t('na')) + '</div>';
    var mv = d.config ? d.config.min_valid_pct : null, by = {};
    d.timeline.forEach(function (x) { by[x.acq_id] = x; });
    if (isNum(a.area_ha) && a.area_ha >= BIG_AREA_HA) {
      var w = worstOpenEvent(d.events), pr = w ? defaultPair(eventLists(w), by, mv) : {before: null, after: null};
      if (!pr.after) {
        var ok = d.timeline.filter(function (x) { return x.sensor === 'S2' && x.quicklook_url && acqState(x, mv) === 'ok'; })
          .sort(function (x, y) { return String(x.sensing_time_utc).localeCompare(String(y.sensing_time_utc)); });
        pr = ok.length >= 2 ? {before: ok[ok.length - 2], after: ok[ok.length - 1]} : {before: null, after: ok[ok.length - 1] || null};
      }
      var comp = pr.before && pr.after ? pairComposite(pr.before, pr.after, 'true') : singleComposite(pr.after, 'true');
      var th = function (x) { return x ? '<span class="satw-thumb" role="img" aria-label="' + esc(fmtDay(x.sensing_time_utc)) + '" style="background-image:url(\'' + esc(imageUrl(x, comp)) + '\')"><span data-no-i18n>' + esc(fmtDay(x.sensing_time_utc, null, true)) + '</span></span>' : '<span class="satw-thumb empty">' + esc(t('noThumb')) + '</span>'; };
      return '<div class="satw-card-v satw-thumbs" title="' + esc(t('thumbsNote')) + '">' + th(pr.before) + th(pr.after) + '</div>';
    }
    return '<div class="satw-card-v satw-mini">' + boundarySvg(a.geometry) + sparkline(d.timeline, mv) + '</div>';
  }
  function boundarySvg(g) {
    if (!g || !g.coordinates) return '<svg class="satw-shape" viewBox="0 0 60 60" aria-hidden="true"></svg>';
    var ring = g.type === 'Polygon' ? g.coordinates[0] : g.coordinates[0][0];
    var lat0 = ring.reduce(function (s, c) { return s + c[1]; }, 0) / ring.length, k = Math.cos(lat0 * Math.PI / 180);
    var xs = ring.map(function (c) { return c[0] * k; }), ys = ring.map(function (c) { return c[1]; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    var s = 52 / Math.max(x1 - x0, y1 - y0 || 1e-9);
    var pts = ring.map(function (c, i) { return (4 + (xs[i] - x0) * s).toFixed(1) + ',' + (4 + (y1 - c[1]) * s).toFixed(1); }).join(' ');
    return '<svg class="satw-shape" viewBox="0 0 60 60" aria-hidden="true"><polygon points="' + pts + '"/></svg>';
  }
  function sparkline(tl, mv) {
    var pts = (tl || []).filter(function (x) { return x.sensor === 'S2' && acqState(x, mv) === 'ok' && x.metrics_inside && x.metrics_inside.NDVI && isNum(x.metrics_inside.NDVI.median); })
      .map(function (x) { return [parseUtc(x.sensing_time_utc).getTime(), x.metrics_inside.NDVI.median]; }).sort(function (a, b) { return a[0] - b[0]; });
    if (pts.length < 2) return '<div class="satw-spark satw-na">' + esc(t('ndvi')) + ': ' + esc(t('na')) + '</div>';
    var x0 = pts[0][0], x1 = pts[pts.length - 1][0], W = 150, H = 44;
    var d = pts.map(function (p, i) { return (i ? 'L' : 'M') + (4 + (p[0] - x0) / (x1 - x0 || 1) * (W - 8)).toFixed(1) + ' ' + (H - 4 - Math.max(0, Math.min(1, p[1])) * (H - 8)).toFixed(1); }).join(' ');
    return '<div class="satw-spark"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(t('ndvi')) + '"><path d="' + d + '"/></svg><small>' + esc(t('ndvi')) + '</small></div>';
  }
  function latestList(list) {
    return '<details class="satw-sec satw-drawer"' + (list.length ? ' open' : '') + '><summary>' + esc(t('latest')) + ' (' + list.length + ')</summary>' +
      (list.length ? '<ul class="satw-list">' + list.map(function (e) {
        return '<li><button type="button" data-event="' + e.id + '" data-area="' + e.monitored_area_id + '">' + dot(e) + '<span><b data-no-i18n>#' + e.id + '</b> ' + esc(clsLabel(e.classification)) +
          '<br><small data-no-i18n>' + esc((e.area_name || '') + ' · ' + (ha(e.changed_area_ha) || '—') + ' · ' + (fmtDay(e.first_after_time_utc) || '—')) + '</small></span></button></li>';
      }).join('') + '</ul>' : '<p class="satw-muted">' + esc(t('noEvents')) + '</p>') + '</details>';
  }
  function areasTable(areas) {
    if (!areas.length) return '<p class="satw-muted">' + esc(t('noAreas')) + '</p>';
    return '<table class="satw-table"><thead><tr><th>' + esc(t('thArea')) + '</th><th>' + esc(t('thStatus')) + '</th><th>ha</th><th>' + esc(t('thOpen')) + '</th><th></th></tr></thead><tbody>' +
      areas.map(function (a) {
        return '<tr><td data-no-i18n>' + esc(a.name) + '</td><td>' + esc(t('d' + a.data_status)) + '</td><td data-no-i18n>' + esc(fmtNum(a.area_ha, 2) || '—') + '</td>' +
          '<td data-no-i18n>' + esc(isNum(a.open_suspected_events) ? a.open_suspected_events : '—') + '</td><td><button type="button" class="satw-btn satw-small" data-area="' + a.id + '">' + esc(t('open')) + '</button></td></tr>';
      }).join('') + '</tbody></table>';
  }
  async function showSectors() {
    var box = document.getElementById('satw-sectors'); if (!box) return;
    if (box.innerHTML) { box.innerHTML = ''; return; }
    box.innerHTML = '<p class="satw-muted">' + esc(t('loading')) + '</p>';
    var d; try { d = await get('/sectors'); } catch (e) { box.innerHTML = '<p>' + esc(t('error') + ': ' + e.message) + '</p>'; return; }
    box.innerHTML = '<ul class="satw-list satw-sector-list">' + d.sectors.map(function (s) {
      return '<li><span data-no-i18n>' + esc(s.name) + '</span>' + (s.monitored_area_id ? badge(t('monitored')) : s.queued_job_id ? badge(t('queued'), 'a') : !s.has_polygon ? badge(t('noPolygon'), 'r') :
        '<button type="button" class="satw-btn satw-small" data-add="' + s.id + '" data-name="' + esc(s.name) + '">' + esc(t('add')) + '</button>') + '</li>';
    }).join('') + '</ul>';
    box.querySelectorAll('[data-add]').forEach(function (b) {
      b.onclick = async function () {
        if (!global.confirm(t('sectorAddConfirm', {name: b.getAttribute('data-name')}))) return;
        try { await post('/areas', {source: 'SECTOR', source_ref: b.getAttribute('data-add'), name: b.getAttribute('data-name')}); box.innerHTML = ''; showSectors(); } catch (e) { global.alert(t('error') + ': ' + e.message); }
      };
    });
  }

  // ── shared map pieces ────────────────────────────────────────────────────────────────────────────────────────────────
  function bboxBounds(bb) { return [[bb[1], bb[0]], [bb[3], bb[2]]]; }
  function baseMap(L, elId) {
    var map = L.map(elId, {zoomControl: false, attributionControl: false, zoomSnap: 0.25}); S.maps.push(map); S.map = map; S.L = L;
    [['satwImg', 300], ['satwAfter', 310], ['satwVmd', 360], ['satwBoundary', 420], ['satwChange', 440], ['satwCallout', 650]].forEach(function (p) { map.createPane(p[0]).style.zIndex = p[1]; });
    map.getPane('satwImg').style.pointerEvents = 'none'; map.getPane('satwAfter').style.pointerEvents = 'none';
    S.base = L.tileLayer(OSM, {maxZoom: 19, opacity: 0.45, className: 'satw-basemap', attribution: '&copy; OpenStreetMap contributors · ' + esc(t('basemapNote'))});
    if (S.layersOn.base) S.base.addTo(map);
    L.control.attribution({prefix: false, position: 'bottomright'}).addTo(map);
    L.control.scale({imperial: false, position: 'bottomleft'}).addTo(map);
    map.on('click', function (e) { if (S.whatHere) whatHere(e.latlng); });
    return map;
  }
  function copernicusAttr(map, isoList) {
    var years = (isoList || []).filter(Boolean).map(function (s) { return String(s).slice(0, 4); }).filter(function (y, i, a) { return a.indexOf(y) === i; }).sort();
    var el = document.getElementById('satw-cop-attr'); if (el) el.remove();
    if (!years.length) return;
    var d = document.createElement('div'); d.id = 'satw-cop-attr'; d.className = 'satw-cop-attr'; d.setAttribute('data-no-i18n', '');
    d.textContent = t('attribution', {year: years.join(', ')});
    document.getElementById('satw-mapwrap').appendChild(d);
  }
  function imgStatus(div, overlay) {
    if (!div) return overlay;
    var st = document.createElement('div'); st.className = 'satw-img-status'; st.textContent = t('imgLoading'); div.appendChild(st);
    overlay.on('load', function () { st.remove(); div.setAttribute('data-img', 'loaded'); });
    overlay.on('error', function () { st.textContent = t('imgFailed'); st.classList.add('failed'); div.setAttribute('data-img', 'failed'); });
    return overlay;
  }
  function drawPolys(L, map, feats, selId) {
    var grp = L.layerGroup(), polys = {};
    feats.forEach(function (f) {
      var p = f.properties, c = changeColour(p), outside = p.zone === 'BUFFER';
      var lyr = L.geoJSON(f, {pane: 'satwChange', style: {color: c.color, weight: p.event_id === selId ? 3.5 : 2, dashArray: c.dash, fillColor: c.color, fillOpacity: outside ? 0.85 : 0.28}});
      lyr.on('add', function () { if (outside) lyr.eachLayer(function (x) { if (x._path) x._path.setAttribute('fill', hatchFill(x._path.ownerSVGElement, c.color)); }); });
      lyr.on('click', function (e) { if (S.whatHere) return; L.DomEvent.stopPropagation(e); if (S.view === 'changes') selectEvent(p.event_id); else { setHash({area: p.area_id, event: p.event_id}); openArea(p.area_id, {event: p.event_id, force: true}); } });
      lyr.bindTooltip('#' + p.event_id + ' · ' + clsLabel(p.classification) + ' · ' + (ha(p.zone_ha) || '—') + ' ' + (outside ? t('outside') : t('inside')), {sticky: true});
      lyr.addTo(grp); (polys[p.event_id] = polys[p.event_id] || []).push(lyr);
    });
    grp.addTo(map);
    return {group: grp, polys: polys};
  }
  function hatchFill(svg, color) {
    var id = 'satw-hatch-' + color.replace('#', '');
    if (svg && !svg.querySelector('#' + id)) {
      var ns = 'http://www.w3.org/2000/svg', defs = svg.querySelector('defs') || svg.insertBefore(document.createElementNS(ns, 'defs'), svg.firstChild);
      var p = document.createElementNS(ns, 'pattern'); p.setAttribute('id', id); p.setAttribute('patternUnits', 'userSpaceOnUse'); p.setAttribute('width', '7'); p.setAttribute('height', '7'); p.setAttribute('patternTransform', 'rotate(45)');
      var l = document.createElementNS(ns, 'line'); l.setAttribute('x1', '0'); l.setAttribute('y1', '0'); l.setAttribute('x2', '0'); l.setAttribute('y2', '7'); l.setAttribute('stroke', color); l.setAttribute('stroke-width', '3');
      p.appendChild(l); defs.appendChild(p);
    }
    return 'url(#' + id + ')';
  }
  // Tool rail: only implemented tools (Kas šeit?, zoom ±, copy link to the current view).
  function mapRail(L, map) {
    var wrap = document.getElementById('satw-mapwrap'); if (!wrap) return;
    var rail = document.createElement('div'); rail.className = 'satw-rail'; rail.setAttribute('role', 'toolbar');
    rail.innerHTML =
      '<button type="button" class="satw-tool" data-tool="what" aria-pressed="' + S.whatHere + '" aria-label="' + esc(t('toolWhatHere')) + '" title="' + esc(t('toolWhatHereTip')) + '">' +
        '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 8v.01M12 11v5"/></svg></button>' +
      '<button type="button" class="satw-tool" data-tool="in" aria-label="' + esc(t('zoomIn')) + '" title="' + esc(t('zoomIn')) + '"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></button>' +
      '<button type="button" class="satw-tool" data-tool="out" aria-label="' + esc(t('zoomOut')) + '" title="' + esc(t('zoomOut')) + '"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/></svg></button>' +
      '<button type="button" class="satw-tool" data-tool="link" aria-label="' + esc(t('copyLink')) + '" title="' + esc(t('copyLink')) + '"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/></svg></button>';
    L.DomEvent.disableClickPropagation(rail); L.DomEvent.disableScrollPropagation(rail);
    wrap.appendChild(rail);
    rail.querySelector('[data-tool=in]').onclick = function () { map.zoomIn(); };
    rail.querySelector('[data-tool=out]').onclick = function () { map.zoomOut(); };
    rail.querySelector('[data-tool=link]').onclick = function () {
      var url = global.location.origin + global.location.pathname + buildHash(viewParams());
      toast(t('copLink')); try { global.navigator.clipboard.writeText(url); } catch (e) { /* no clipboard: the URL is also in the address bar */ }
      setHash(viewParams(), true);
    };
    var w = rail.querySelector('[data-tool=what]');
    w.onclick = function () { S.whatHere = !S.whatHere; w.setAttribute('aria-pressed', String(S.whatHere)); wrap.classList.toggle('satw-picking', S.whatHere); if (!S.whatHere) closeWhat(); };
    wrap.classList.toggle('satw-picking', S.whatHere);
    if (store('satWorkspace.hintWhatHere') !== '1') {
      var hint = document.createElement('div'); hint.className = 'satw-hint'; hint.setAttribute('role', 'note');
      hint.innerHTML = '<b>' + esc(t('toolWhatHere')) + '</b> ' + esc(t('toolWhatHereTip')) + ' <button type="button" class="satw-btn satw-small">' + esc(t('hintDismiss')) + '</button>';
      L.DomEvent.disableClickPropagation(hint); wrap.appendChild(hint);
      hint.querySelector('button').onclick = function () { store('satWorkspace.hintWhatHere', '1'); hint.remove(); };
    }
  }
  function toast(msg) {
    var wrap = document.getElementById('satw-mapwrap') || root(); if (!wrap) return;
    var d = document.createElement('div'); d.className = 'satw-toast'; d.setAttribute('role', 'status'); d.textContent = msg; wrap.appendChild(d);
    setTimeout(function () { d.remove(); }, 2200);
  }

  // ── Kas šeit? (coordinates · monitored? · VMD compartment / cadastre · add to monitoring) ──────────────────────────
  function closeWhat() { if (S.whatPopup && S.map) { S.map.closePopup(S.whatPopup); } S.whatPopup = null; }
  function areasAt(lon, lat) {
    var list = (S.ov && S.ov.areas) || [];
    return list.filter(function (a) { return a.active && inGeometry(lon, lat, a.geometry); });
  }
  async function whatHere(latlng, feature) {
    var L = S.L, map = S.map; if (!L || !map) return;
    var lat = latlng.lat, lon = latlng.lng, coords = lat.toFixed(5) + ', ' + lon.toFixed(5);
    var div = document.createElement('div'); div.className = 'satw-what';
    var inside = areasAt(lon, lat);
    div.innerHTML = '<div class="satw-what-row"><span class="satw-muted">' + esc(t('whCoords')) + '</span><span><code data-no-i18n>' + esc(coords) + '</code> <button type="button" class="satw-btn satw-small" data-act="copy">' + esc(t('copy')) + '</button></span></div>' +
      '<div class="satw-what-row"><span class="satw-muted">' + esc(t('whArea')) + '</span><span>' + (inside.length ? inside.map(function (a) {
        return '<button type="button" class="satw-link" data-open-area="' + a.id + '" data-no-i18n>' + esc(a.name) + '</button>'; }).join(', ') : esc(t('whNotMonitored'))) + '</span></div>' +
      '<div class="satw-what-vmd"><span class="satw-muted">' + esc(t('whLoading')) + '</span></div>';
    S.whatPopup = L.popup({maxWidth: 360, className: 'satw-popup', autoPanPadding: [24, 24]}).setLatLng(latlng).setContent(div).openOn(map);
    div.querySelector('[data-act=copy]').onclick = function () { try { global.navigator.clipboard.writeText(coords); this.textContent = t('copied'); } catch (e) { /* no clipboard */ } };
    div.querySelectorAll('[data-open-area]').forEach(function (b) { b.onclick = function () { var id = +b.getAttribute('data-open-area'); setHash({area: id}); openArea(id, {force: true}); }; });
    var box = div.querySelector('.satw-what-vmd'), res;
    if (feature) res = {feature: feature};
    else {
      try { res = await get(GEO + '/forest-map/identify?lat=' + lat + '&lon=' + lon + '&zoom=' + Math.round(map.getZoom())); }
      catch (e) { box.innerHTML = '<span class="satw-muted">' + esc(t('whCompartment')) + ': ' + esc(t('na')) + '</span>'; return; }
    }
    var f = res.feature;
    if (!f) {
      var msg = {zoom_in: 'whZoomIn', none: 'whNoForest', dense: 'whDense', complex: 'whComplex'}[res.notice_code] || 'na';
      box.innerHTML = '<span class="satw-muted">' + esc(t(msg)) + '</span>' + (res.notice_code === 'zoom_in' ? ' <button type="button" class="satw-btn satw-small" data-act="zoom">' + esc(t('whZoomBtn')) + '</button>' : '');
      var z = box.querySelector('[data-act=zoom]'); if (z) z.onclick = function () { map.setView(latlng, 15); setTimeout(function () { whatHere(latlng); }, 400); };
      return;
    }
    var p = f.properties || {};
    box.innerHTML = '<div class="satw-what-row"><span class="satw-muted">' + esc(t('whCompartment')) + '</span><span data-no-i18n>' + esc((p.kvart || '?') + '-' + (p.nog || '?')) +
        (p.zkat ? ' · zkat ' + esc(p.zkat) : '') + (isNum(p.nog_plat) ? ' · ' + esc(ha(p.nog_plat)) : '') + '</span></div>' +
      '<div class="satw-what-row"><span class="satw-muted">' + esc(t('whCadastre')) + '</span>' + val(p.kadastrs) + '</div>' +
      '<div class="satw-what-add"></div>';
    addButton(box.querySelector('.satw-what-add'), f);
  }
  // "Pievienot monitoringam": existing LVM GEO path (lookup → POST /areas LVM_GEO), D5 confirm (cost "Nav pieejams" + month vs guard).
  function addButton(container, f) {
    var lg = legacy(), g = lg._lvmGeometry ? lg._lvmGeometry(f) : {error: 'noPolygon'}, ref = String(f.id), p = f.properties || {};
    var name = 'VMD ' + (p.kvart !== undefined ? p.kvart + '-' + p.nog : ref) + (p.kadastrs ? ' (' + p.kadastrs + ')' : '');
    var b = document.createElement('button'); b.type = 'button'; b.className = 'satw-btn primary'; b.textContent = t('whLoading'); b.disabled = true; container.appendChild(b);
    if (g.error) { b.textContent = t('whMulti'); return; }
    get('/lookup?source=LVM_GEO&source_ref=' + encodeURIComponent(ref)).then(function (r) {
      if (r.monitored) { b.textContent = t('whAlready'); return; }
      if (r.queued_job_id) { b.textContent = t('whQueued'); return; }
      b.textContent = t('whAdd'); b.disabled = false;
    }).catch(function () { b.textContent = t('whAdd'); b.disabled = false; });
    b.onclick = function () {
      var m = (S.health && S.health.month) || {};
      var msg = t('addQ', {name: name}) + '\n\n' + t('addCost') + '\n' + t('addMonth', {pu: isNum(m.pu) ? fmtNum(m.pu, 1) : t('na'), puGuard: isNum(m.pu_guard) ? fmtNum(m.pu_guard, 0) : t('na'),
        req: isNum(m.requests) ? fmtNum(m.requests, 0) : t('na'), reqGuard: isNum(m.request_guard) ? fmtNum(m.request_guard, 0) : t('na')}) + '\n' + t('addFirst');
      if (!global.confirm(msg)) return;
      b.disabled = true;
      post('/areas', {source: 'LVM_GEO', source_ref: ref, name: name, geometry: g.geometry}).then(function () { b.textContent = t('whQueued'); toast(t('addDone')); })
        .catch(function (e) { if (e.status === 409) b.textContent = t('whAlready'); else { b.disabled = false; global.alert(t('error') + ': ' + e.message); } });
    };
  }

  // ── search: coordinates (WGS84) · 11-digit cadastre · VMD source id · area name ────────────────────────────────────
  function searchMsg(text) { var m = document.getElementById('satw-search-msg'); if (!m) return; m.textContent = text || ''; m.hidden = !text; }
  async function search(q) {
    q = String(q || '').trim(); searchMsg(''); if (!q) return;
    var L = S.L || await leaflet(), map = S.map;
    var c = parseCoordinates(q);
    if (c || /^[+-]?\d+([.,]\d+)?[\s,;]+[+-]?\d+([.,]\d+)?$/.test(q)) {
      if (!c || !c.inLatvia) { searchMsg(t('searchCoordsBad')); return; }
      var hit = areasAt(c.lon, c.lat)[0];
      if (hit && (S.view !== 'changes' || S.areaId !== hit.id)) { setHash({area: hit.id}); await openArea(hit.id, {force: true, lat: c.lat, lon: c.lon, z: 15}); }
      map = S.map; if (!map) return;
      map.setView([c.lat, c.lon], 15); whatHere(L.latLng(c.lat, c.lon)); return;
    }
    var feats = [];
    try {
      if (/^\d{11}$/.test(q)) feats = (await get(GEO + '/vmd/cadastre?kadastrs=' + q + '&limit=100&offset=0')).features || [];
      else if (/^VMD:[A-Za-z0-9:_-]{1,190}$/.test(q)) { var r = await get(GEO + '/forest-map/feature?id=' + encodeURIComponent(q)); if (r && (r.feature || r.geometry)) feats = [r.feature || r]; }
    } catch (e) { searchMsg(t('error') + ': ' + e.message); return; }
    if (!feats.length && !/^\d{11}$/.test(q) && !/^VMD:/.test(q)) {
      var ql = q.toLowerCase(), area = ((S.ov && S.ov.areas) || []).filter(function (a) { return a.active && String(a.name).toLowerCase().indexOf(ql) >= 0; })[0];
      if (area) { setHash({area: area.id}); openArea(area.id, {force: true}); return; }
    }
    if (!feats.length) { searchMsg(t('searchNone')); return; }
    map = S.map; if (!map) return;
    var lay = L.geoJSON({type: 'FeatureCollection', features: feats}, {pane: 'satwCallout', style: {color: '#F2C14E', weight: 2.5, fill: false}});
    if (S.searchLayer) map.removeLayer(S.searchLayer); S.searchLayer = lay.addTo(map);
    var b = lay.getBounds(), ctr = b.getCenter(), hitA = areasAt(ctr.lng, ctr.lat)[0];
    if (hitA && (S.view !== 'changes' || S.areaId !== hitA.id)) { setHash({area: hitA.id}); await openArea(hitA.id, {force: true}); map = S.map; S.searchLayer = L.geoJSON({type: 'FeatureCollection', features: feats}, {pane: 'satwCallout', style: {color: '#F2C14E', weight: 2.5, fill: false}}).addTo(map); }
    map.fitBounds(b, {padding: [60, 60], maxZoom: 16});
    if (feats.length > 1) searchMsg(t('searchFound', {n: feats.length}));
    whatHere(ctr, feats[0]);
  }

  // ── IZMAIŅAS (area workspace) ──────────────────────────────────────────────────────────────────────────────────────
  async function openArea(id, opts) {
    opts = opts || {}; id = +id;
    if (!opts.force && !claim('area:' + id + ':' + (opts.event || ''))) return;
    var seq = ++S.seq; cleanup(); S.areaId = id; S.ev = null; S.sel = null; S.compare = null; S.mode = null; S.acq = null;
    shell('changes', '<div class="satw-loading">' + esc(t('loading')) + '</div>');
    var a, h, layer, ov;
    try {
      var r = await Promise.all([get('/areas/' + id + '?geometry=0'), get('/health').catch(function () { return {}; }),
        get('/map-layer?area_id=' + id).catch(function () { return {features: []}; }), S.ov ? Promise.resolve(S.ov) : get('/overview')]);
      a = r[0]; h = r[1]; layer = r[2]; ov = r[3];
    } catch (e) { if (seq === S.seq) errorView(e, function () { openArea(id, {force: true}); }); return; }
    if (seq !== S.seq) return;
    S.area = a; S.health = h; S.layer = layer; S.ov = ov; S.byId = {};
    a.timeline.forEach(function (x) { S.byId[x.acq_id] = x; });
    S.events = a.events.slice().sort(function (x, y) { return (isOpen(x) ? 0 : 1) - (isOpen(y) ? 0 : 1) || changeColour(y).rank - changeColour(x).rank || String(y.first_after_time_utc).localeCompare(String(x.first_after_time_utc)); });
    var start = opts.acq && S.byId[+opts.acq];
    S.acq = start || latestValid('S2') || latestValid('S1');
    if (S.acq) S.sensor = S.acq.sensor;
    renderChanges();
    var L = await leaflet(); if (seq !== S.seq) return;
    buildAreaMap(L);
    renderTimeline();
    var evId = opts.event ? +opts.event : null;
    if (evId) await selectEvent(evId, {before: opts.before, acq: opts.acq, mode: opts.mode, keepView: opts.lat !== undefined});
    else {
      if (opts.before && S.byId[+opts.before] && S.acq) { S.compare = {before: S.byId[+opts.before], after: S.acq}; S.mode = opts.mode || 'swipe'; }
      renderImagery();
    }
    if (opts.lat !== undefined && opts.lon !== undefined && S.map) S.map.setView([+opts.lat, +opts.lon], +(opts.z || 15), {animate: false});
  }
  function latestValid(sensor) {
    var mv = minValid();
    return S.area.timeline.filter(function (x) { return x.sensor === sensor && x.quicklook_url && acqState(x, mv) === 'ok'; })
      .sort(function (x, y) { return String(y.sensing_time_utc).localeCompare(String(x.sensing_time_utc)); })[0] || null;
  }
  function stepList(sensor) {
    return S.area.timeline.filter(function (x) { return x.sensor === sensor && x.status === 'OK' && x.quicklook_url; })
      .sort(function (x, y) { return String(x.sensing_time_utc).localeCompare(String(y.sensing_time_utc)); });
  }
  function lastAcqOk() {
    var best = null;
    S.area.timeline.forEach(function (x) { if (x.status === 'OK' && (!best || x.sensing_time_utc > best.sensing_time_utc)) best = x; });
    return best;
  }
  function renderChanges() {
    var ar = S.area.area, la = lastAcqOk();
    var catalog = ((S.health && S.health.provider_status) || []).filter(function (p) { return p.key === 'catalog'; })[0];
    var sysCheck = catalog ? [catalog.last_ok_utc, catalog.last_error_utc].filter(Boolean).sort().pop() : null;
    var areas = ((S.ov && S.ov.areas) || []).filter(function (x) { return x.active; });
    var openN = S.events.filter(isOpen).length, recN = S.events.filter(function (e) { return e.status === 'RECOVERED'; }).length;
    var html = '<div class="satw-work"><aside class="satw-left" aria-label="' + esc(t('areaSelect')) + '">' +
      '<div class="satw-sec satw-area-sel"><label class="satw-sr" for="satw-area">' + esc(t('areaSelect')) + '</label>' +
        '<select id="satw-area">' + areas.map(function (x) { return '<option value="' + x.id + '"' + (x.id === S.areaId ? ' selected' : '') + ' data-no-i18n>' + esc(x.name) + '</option>'; }).join('') + '</select>' +
        '<span class="satw-muted">' + esc(t('areasCount', {n: areas.length})) + '</span></div>' +
      '<div class="satw-sec"><div class="satw-muted">' + esc(t('src' + ar.source)) + ' · <span data-no-i18n>' + esc(ha(ar.area_ha, 1) || t('na')) + '</span></div>' +
        '<span class="satw-chip ' + (ar.data_status === 'OK' ? 'g' : 'a') + '">' + esc(t('d' + ar.data_status)) + '</span>' +
        '<dl class="satw-kv">' +
          '<dt>' + esc(t('lastAcq')) + '</dt><dd>' + (la ? '<span class="satw-mono" data-no-i18n>' + esc(fmtDay(la.sensing_time_utc) + ' · ' + la.sensor) + '</span>' : na()) + '</dd>' +
          '<dt>' + esc(t('lastValidS2')) + '</dt><dd>' + (ar.last_valid_s2_utc ? '<span class="satw-mono" data-no-i18n>' + esc(fmtDay(ar.last_valid_s2_utc) + (isNum(ar.last_valid_s2_valid_pct) ? ' · ' + fmtNum(ar.last_valid_s2_valid_pct, 0) + ' %' : '')) + '</span>' : na()) + '</dd>' +
          '<dt>' + esc(t('lastAnalysis')) + '</dt><dd>' + (S.area.last_successful_analysis_utc ? '<span class="satw-mono" data-no-i18n>' + esc(fmtClock(S.area.last_successful_analysis_utc)) + '</span>' : na()) + '</dd>' +
          '<dt>' + esc(t('lastCheck')) + '</dt><dd>' + (sysCheck ? '<span class="satw-mono" data-no-i18n>' + esc(fmtClock(sysCheck)) + '</span>' : na()) + '</dd></dl></div>' +
      '<div class="satw-sec"><div class="satw-sec-h"><b>' + esc(t('onMap')) + '</b></div><div id="satw-acqbox"></div></div>' +
      '<div class="satw-sec"><div class="satw-sec-h"><b>' + esc(t('imageKind')) + '</b></div><div id="satw-composites"></div></div>' +
      '<div class="satw-sec"><div class="satw-sec-h"><b>' + esc(t('layers')) + '</b></div>' + layerPanel() + '</div>' +
      '<div class="satw-sec"><div class="satw-sec-h"><b>' + esc(t('eventsTitle')) + '</b><span class="satw-muted">' + esc(t('eventsCount', {open: openN, rec: recN})) + '</span></div>' + eventList() + '</div>' +
      legendHtml() +
      '</aside><div class="satw-main">' +
        '<div id="satw-mapwrap" class="satw-mapwrap"><div id="satw-maps" class="satw-maps"><div id="satw-map" class="satw-map"></div></div>' +
          '<aside id="satw-card" class="satw-evcard" hidden aria-live="polite"></aside></div>' +
        '<details class="satw-drawer satw-analysis"><summary>' + esc(t('analysis')) + '</summary><div id="satw-analysis-body"></div></details>' +
        '<section class="satw-timeline" aria-label="' + esc(t('timeline')) + '"><div class="satw-tl-head"><b>' + esc(t('timeline')) + '</b><small class="satw-muted">' + esc(t('shiftHint')) + '</small>' +
          '<span class="satw-seg" data-seg="window"><button type="button" data-v="120" class="' + (S.window === 120 ? 'on' : '') + '">' + esc(t('days120')) + '</button><button type="button" data-v="all" class="' + (S.window === 'all' ? 'on' : '') + '">' + esc(t('allDays')) + '</button></span></div>' +
          '<div id="satw-tl" class="satw-tl"></div><div id="satw-tip" class="satw-tip" role="tooltip" hidden></div></section>' +
        statusBar(S.health) +
      '</div></div>';
    var r = shell('changes', html); if (!r) return;
    bindStatus();
    r.querySelector('#satw-area').onchange = function () { var id = +this.value; setHash({area: id}); openArea(id, {force: true}); };
    r.querySelectorAll('[data-ev]').forEach(function (li) { li.onclick = function () { selectEvent(+li.getAttribute('data-ev')); }; });
    r.querySelectorAll('.satw-layers input').forEach(function (c) { c.onchange = function () { setLayer(c.getAttribute('data-layer'), c.checked); }; });
    r.querySelectorAll('[data-seg=window] button').forEach(function (b) { b.onclick = function () { S.window = b.getAttribute('data-v') === 'all' ? 'all' : 120; r.querySelectorAll('[data-seg=window] button').forEach(function (x) { x.classList.toggle('on', x === b); }); renderTimeline(); }; });
    r.querySelector('.satw-analysis').addEventListener('toggle', function (e) { if (e.target.open) renderAnalysis(); });
    renderAcqBox(); renderComposites(); syncModes();
  }
  var LAYERS = [['boundary', 'lBoundary'], ['buffer', 'lBuffer'], ['change', 'lChange'], ['vmd', 'lVmd'], ['base', 'lBase']];
  function layerPanel() {
    return '<div class="satw-layers">' + LAYERS.map(function (l) {
      return '<label class="satw-check"><input type="checkbox" data-layer="' + l[0] + '"' + (S.layersOn[l[0]] ? ' checked' : '') + '> ' + esc(t(l[1])) + '</label>';
    }).join('') + '</div>';
  }
  function legendHtml() {
    return '<details class="satw-sec satw-drawer satw-legend"><summary>' + esc(t('layers')) + ' · ' + esc(t('lChange')) + '</summary>' + CHANGE_COLOURS.map(function (c) {
      return '<div><span class="satw-dot' + (c.dash ? ' dashed' : '') + '" style="--c:' + c.color + '" aria-hidden="true"></span>' + esc(t(c.legend)) + '</div>';
    }).join('') + '</details>';
  }
  function eventList() {
    if (!S.events.length) return '<div class="satw-empty"><b>' + esc(t('noEvents')) + '</b><p>' + esc(t('noEventsHint')) + '</p></div>';
    return '<ul class="satw-evlist">' + S.events.map(function (e) {
      var before = lastClearBeforeOf(eventLists(e), S.byId, minValid());
      var when = before ? fmtDay(before.sensing_time_utc, null, true) + ' → ' + (fmtDay(e.first_after_time_utc) || '?') : fmtDay(e.first_after_time_utc) || '—';
      return '<li><button type="button" data-ev="' + e.id + '" class="' + (S.sel === e.id ? 'sel' : '') + '" aria-pressed="' + (S.sel === e.id) + '">' + dot(e) + '<span class="satw-ev-t">' +
        '<b data-no-i18n>#' + e.id + '</b> ' + esc(clsLabel(e.classification)) + ' <span class="satw-mono" data-no-i18n>' + esc(ha(e.changed_area_ha) || '—') + '</span>' +
        '<small><span data-no-i18n>' + esc(when) + '</span> · ' + esc(e.sensor_basis || '') + ' · ' + esc(t('confShort', {c: t(e.confidence || 'na').toLowerCase()})) +
        (e.seasonal_caveat ? ' · <span class="satw-tag">' + esc(t('seasonalTag')) + '</span>' : '') + '</small></span></button></li>';
    }).join('') + '</ul>';
  }
  function renderAcqBox() {
    var box = document.getElementById('satw-acqbox'); if (!box) return;
    var has = {S2: stepList('S2').length > 0, S1: stepList('S1').length > 0}, a = S.acq, list = stepList(S.sensor);
    var idx = a ? list.map(function (x) { return x.acq_id; }).indexOf(a.acq_id) : -1;
    box.innerHTML = '<div class="satw-seg satw-seg-full" data-seg="sensor">' + [['S2', 'optical'], ['S1', 'radar']].map(function (s) {
        return '<button type="button" data-v="' + s[0] + '" class="' + (S.sensor === s[0] ? 'on' : '') + '"' + (has[s[0]] ? '' : ' disabled title="' + esc(t('noSensor')) + '"') + '>' + esc(t(s[1])) + '</button>'; }).join('') + '</div>' +
      '<div class="satw-stepper"><button type="button" class="satw-btn" data-step="-1" aria-label="' + esc(t('prevAcq')) + '"' + (idx > 0 ? '' : ' disabled') + '>‹</button>' +
        '<span class="satw-mono" data-no-i18n>' + (a ? esc(fmtDay(a.sensing_time_utc) + ' ' + String(a.sensing_time_utc).slice(11, 16) + ' UTC') : esc(t('na'))) + '</span>' +
        '<button type="button" class="satw-btn" data-step="1" aria-label="' + esc(t('nextAcq')) + '"' + (idx >= 0 && idx < list.length - 1 ? '' : ' disabled') + '>›</button></div>' +
      (a ? '<div class="satw-chips">' + (a.platform ? '<span class="satw-chip" data-no-i18n>' + esc(a.platform) + '</span>' : '') +
        (isNum(a.valid_pct_inside) ? '<span class="satw-chip">' + esc(t('valid', {v: fmtNum(a.valid_pct_inside, 1)})) + '</span>' : '') +
        (a.sensor === 'S2' ? '<span class="satw-chip" data-no-i18n>' + esc(t('px10')) + '</span>' : '<span class="satw-chip" data-no-i18n>' + esc(geomKey(a)) + '</span>') + '</div>' : '');
    box.querySelectorAll('[data-seg=sensor] button').forEach(function (b) { b.onclick = function () { var s = b.getAttribute('data-v'); var x = latestValid(s) || stepList(s).pop(); if (x) showAcq(x); }; });
    box.querySelectorAll('[data-step]').forEach(function (b) { b.onclick = function () { var x = list[idx + +b.getAttribute('data-step')]; if (x) showAcq(x); }; });
  }
  // Composite list: only kinds that exist for what is shown (pair: true colour only when BOTH have it). No mask entry (Q4).
  function renderComposites() {
    var box = document.getElementById('satw-composites'); if (!box) return;
    var pair = S.mode && S.mode !== 'change' && S.compare && comparePair(S.compare.before, S.compare.after).ok ? S.compare : null;
    var shown = pair ? pair.after : S.acq;
    if (!shown) { box.innerHTML = na(); return; }
    if (shown.sensor === 'S1') {
      box.innerHTML = '<div class="satw-comp on"><span class="satw-comp-th" style="background-image:url(\'' + esc(shown.quicklook_url) + '\')"></span><span><b>' + esc(t('radarC')) + '</b><small>' + esc(t('radarSub')) + '</small></span></div>';
      return;
    }
    var tcOk = pair ? !!(pair.before.truecolor_url && pair.after.truecolor_url) : !!shown.truecolor_url;
    var cur = tcOk && S.composite === 'true' ? 'true' : 'false';
    var item = function (k, title, sub, url) {
      return '<button type="button" class="satw-comp' + (cur === k ? ' on' : '') + '" data-comp="' + k + '" aria-pressed="' + (cur === k) + '"><span class="satw-comp-th" style="background-image:url(\'' + esc(url) + '\')"></span><span><b>' + esc(t(title)) + '</b><small>' + esc(t(sub)) + '</small></span></button>';
    };
    box.innerHTML = (tcOk ? item('true', 'trueC', 'trueSub', shown.truecolor_url) : '') + item('false', 'falseC', 'falseSub', shown.quicklook_url) +
      (!tcOk && pair && (pair.before.truecolor_url || pair.after.truecolor_url) ? '<p class="satw-note">' + esc(t('compositeNote')) + '</p>' : '');
    box.querySelectorAll('[data-comp]').forEach(function (b) { b.onclick = function () { S.composite = b.getAttribute('data-comp'); renderComposites(); renderImagery(); }; });
  }
  function syncModes() {
    var ok = S.view === 'changes' && S.compare && comparePair(S.compare.before, S.compare.after).ok;
    document.querySelectorAll('[data-mode]').forEach(function (b) {
      var on = !!ok && S.mode === b.getAttribute('data-mode');
      b.disabled = !ok; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on));
      b.title = ok ? '' : t('modeOff');
    });
  }
  function setMode(m) {
    if (!S.compare || !comparePair(S.compare.before, S.compare.after).ok) return;
    S.mode = S.mode === m ? null : m; renderComposites(); renderImagery(); setHash(viewParams(), true);
  }
  function setLayer(k, on) {
    S.layersOn[k] = on; var m = S.map; if (!m) return;
    [m, S.map2].forEach(function (mm) {
      if (!mm) return; var l = k === 'vmd' ? (mm === S.map ? S.vmd : S.vmd2) : k === 'base' ? (mm === S.map ? S.base : S.base2) : (mm === S.map ? S.groups[k] : (S.groups2 || {})[k]);
      if (!l) return; if (on) l.addTo(mm); else mm.removeLayer(l);
    });
  }

  // ── area map: boundary, buffer, polygons, VMD, imagery, compare, callout, selection ring ───────────────────────────
  function buildAreaMap(L) {
    var map = baseMap(L, 'satw-map');
    S.groups = areaLayers(L, map);
    S.vmd = vmdLayer(L); if (S.layersOn.vmd) S.vmd.addTo(map);
    var bb = S.area.area.grid_bbox;
    if (bb) map.fitBounds(bboxBounds(bb), {padding: [20, 20]}); else map.setView([56.95, 24.1], 10);
    mapRail(L, map);
    map.on('moveend', function () { if (S.view === 'changes') setHash(viewParams(), true); });
  }
  function areaLayers(L, map) {
    var g = {boundary: L.layerGroup(), buffer: L.layerGroup(), change: null};
    if (S.area.geometry) L.geoJSON(S.area.geometry, {pane: 'satwBoundary', style: {color: '#F5F5F0', weight: 2.2, fill: false, opacity: 0.95}}).addTo(g.boundary);
    if (S.area.buffer_ring) L.geoJSON(S.area.buffer_ring, {pane: 'satwBoundary', style: {color: '#9FC3E7', weight: 1.2, dashArray: '5 4', fill: false}}).addTo(g.buffer);
    var dp = drawPolys(L, map, (S.layer && S.layer.features || []).filter(function (f) { return f.properties && f.properties.kind === 'event'; }), S.sel);
    g.change = dp.group; if (map === S.map) S.polys = dp.polys;
    if (!S.layersOn.change) map.removeLayer(dp.group);
    ['boundary', 'buffer'].forEach(function (k) { if (S.layersOn[k]) g[k].addTo(map); });
    return g;
  }
  function vmdLayer(L) {
    var GL = L.GridLayer.extend({
      createTile: function (coords, done) {
        var cv = document.createElement('canvas'); cv.width = cv.height = 256;
        if (coords.z < 13) { setTimeout(function () { done(null, cv); }, 0); return cv; }
        var url = VMD_TILES.replace('{z}', coords.z).replace('{x}', coords.x).replace('{y}', coords.y);
        fetch(url, {credentials: 'same-origin'}).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
          cv._satwData = d; drawVmdTile(cv, d, coords); done(null, cv);
        }).catch(function () { done(null, cv); });
        return cv;
      }
    });
    return new GL({pane: 'satwVmd', minZoom: 13, maxZoom: 19});
  }
  function drawVmdTile(cv, d, coords) {
    var ctx = cv.getContext('2d'); ctx.clearRect(0, 0, 256, 256);
    if (!d || !d.features) return;
    var n = Math.pow(2, coords.z);
    function px(lon, lat) {
      var x = (lon + 180) / 360 * n * 256 - coords.x * 256;
      var s = Math.sin(lat * Math.PI / 180), y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n * 256 - coords.y * 256;
      return [x, y];
    }
    d.features.forEach(function (f) {
      var p = f.properties || {}, g = f.geometry; if (!g) return;
      var polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
      ctx.beginPath();
      polys.forEach(function (poly) { poly.forEach(function (ring) { ring.forEach(function (c, i) { var q = px(c[0], c[1]); if (i) ctx.lineTo(q[0], q[1]); else ctx.moveTo(q[0], q[1]); }); ctx.closePath(); }); });
      ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(127,191,142,.8)'; ctx.stroke();
      if (coords.z >= 15 && polys[0] && polys[0][0]) {
        var r0 = polys[0][0], sx = 0, sy = 0; r0.forEach(function (c) { var q = px(c[0], c[1]); sx += q[0]; sy += q[1]; });
        var cx = sx / r0.length, cy = sy / r0.length;
        if (cx > 4 && cx < 252 && cy > 4 && cy < 252) { ctx.font = '11px Inter, system-ui, sans-serif'; ctx.fillStyle = '#E6ECE5'; ctx.textAlign = 'center'; ctx.fillText((p.kvart || '?') + '-' + (p.nog || '?'), cx, cy); }
      }
    });
  }

  // Imagery: single acquisition, or a validated pair in swipe / side-by-side / change-only. Never mixed composites.
  function teardownImagery() {
    var L = S.L;
    if (S.map2) { try { S.map2.remove(); } catch (e) { /* gone */ } S.maps = S.maps.filter(function (m) { return m !== S.map2; }); S.map2 = null; S.vmd2 = null; S.base2 = null; S.groups2 = null; }
    var wrap = document.getElementById('satw-maps'); if (wrap) wrap.classList.remove('split');
    var mw = document.getElementById('satw-mapwrap'); if (mw) mw.classList.remove('satw-muted-map');
    ['satw-map2', 'satw-divider', 'satw-pill-b', 'satw-pill-a', 'satw-pill-s', 'satw-pill-b2', 'satw-pill-a2', 'satw-cmpbar'].forEach(function (id) { var x = document.getElementById(id); if (x) x.remove(); });
    if (S.imgLayers && S.map) S.imgLayers.forEach(function (l) { S.map.removeLayer(l); });
    S.imgLayers = [];
    if (S.swipe && S.map) { S.map.off('move zoom zoomanim viewreset resize moveend zoomend', S.swipe); S.swipe = null; }
    if (S.map) { var p = S.map.getPane('satwAfter'); if (p) p.style.clip = ''; }
    return L;
  }
  // Pill = date · sensor · valid % (owner spec), two short lines so both fit beside the divider. The composite is shown
  // once in the left panel ("Attēla veids") and is the same on both sides (never mixed).
  function pillText(kind, a) {
    var l2 = [a.sensor];
    if (isNum(a.valid_pct_inside)) l2.push(t('valid', {v: fmtNum(a.valid_pct_inside, 1)}));
    return t(kind) + ' · ' + fmtDay(a.sensing_time_utc) + '\n' + l2.join(' · ');
  }
  function pill(id, text, cls, parent) {
    var d = document.createElement('div'); d.id = id; d.className = 'satw-pill ' + (cls || ''); d.setAttribute('data-no-i18n', ''); d.textContent = text;
    (parent || document.getElementById('satw-mapwrap')).appendChild(d); return d;
  }
  function renderImagery() {
    var L = teardownImagery(), map = S.map; if (!L || !map) return;
    var bb = S.area.area.grid_bbox; if (!bb) { syncModes(); return; }
    var bounds = bboxBounds(bb), mw = document.getElementById('satw-mapwrap');
    var pair = S.compare && comparePair(S.compare.before, S.compare.after).ok ? S.compare : null;
    var mode = pair ? S.mode : null;
    if (!mode) {
      var a = S.acq;
      if (a && a.quicklook_url) {
        var comp = singleComposite(a, S.composite);
        S.imgLayers.push(imgStatus(mw, L.imageOverlay(imageUrl(a, comp), bounds, {pane: 'satwImg'})).addTo(map));
        pill('satw-pill-s', pillText('pillShown', a, comp), 'single');
      }
      copernicusAttr(map, [a && a.sensing_time_utc]);
    } else {
      var c = pairComposite(pair.before, pair.after, S.composite);
      if (mode === 'change') {
        mw.classList.add('satw-muted-map');
        pill('satw-pill-s', pillText('pillAfter', pair.after, c), 'single');
      } else if (mode === 'swipe') {
        S.imgLayers.push(imgStatus(mw, L.imageOverlay(imageUrl(pair.before, c), bounds, {pane: 'satwImg'})).addTo(map));
        S.imgLayers.push(L.imageOverlay(imageUrl(pair.after, c), bounds, {pane: 'satwAfter'}).addTo(map));
        swipe(L, map, mw, pillText('pillBefore', pair.before, c), pillText('pillAfter', pair.after, c));
      } else {
        sideBySide(L, map, pair, c, bounds);
      }
      copernicusAttr(map, [pair.before.sensing_time_utc, pair.after.sensing_time_utc]);
      compareBar(pair);
    }
    syncModes(); renderTimeline();
    if (S.ev) renderCard(S.ev);                    // the card always names the acquisitions that are compared
  }
  // Compare bar: offers a true-colour pair of the same event when the shown pair is false colour. Click = explicit switch.
  function compareBar(pair) {
    if (!S.ev || S.mode === 'change') return;
    var alt = trueColourAlternative(S.ev, S.byId, minValid(), pair);
    if (!alt) return;
    var bar = document.createElement('div'); bar.id = 'satw-cmpbar'; bar.className = 'satw-cmpbar';
    var b = document.createElement('button'); b.type = 'button'; b.className = 'satw-btn satw-small'; b.setAttribute('data-act', 'tc-pair');
    b.textContent = t('tcHint', {before: fmtDay(alt.before.sensing_time_utc), after: fmtDay(alt.after.sensing_time_utc)});
    bar.appendChild(b); S.L.DomEvent.disableClickPropagation(bar);
    var mw = document.getElementById('satw-mapwrap'); mw.appendChild(bar);
    bar.style.maxWidth = Math.max(220, visibleRight(mw) - 90) + 'px';          // stays left of the event card
    b.onclick = function () {
      S.compare = {before: alt.before, after: alt.after}; S.composite = 'true'; S.acq = alt.after;
      S.swipeFrac = null;                          // divider back to the middle of the visible map: both pills readable
      renderAcqBox(); renderComposites(); renderImagery(); setHash(viewParams(), true);
    };
  }
  // Swipe (Stage A design): divider + handle + pills are DOM in the map container at a fixed container x; the "after"
  // pane is clipped to the right of it and recomputed on every movement incl. the zoom animation.
  // Right edge of the map part that is not covered by the event card (container px).
  function visibleRight(mw) {
    var card = document.getElementById('satw-card'), w = mw.clientWidth;
    return card && !card.hidden ? Math.max(120, w - card.offsetWidth - 24) : w;
  }
  function swipe(L, map, mw, beforeText, afterText) {
    var pane = map.getPane('satwAfter'), frac = isNum(S.swipeFrac) ? S.swipeFrac : (visibleRight(mw) / 2) / Math.max(1, mw.clientWidth);
    var line = document.createElement('div'); line.id = 'satw-divider'; line.className = 'satw-divider';
    var handle = document.createElement('div'); handle.className = 'satw-handle'; handle.setAttribute('role', 'slider'); handle.setAttribute('tabindex', '0');
    handle.setAttribute('aria-label', t('modeSwipe')); handle.setAttribute('aria-valuemin', '0'); handle.setAttribute('aria-valuemax', '100');
    line.appendChild(handle);
    var pb = pill('satw-pill-b', beforeText, 'before', line), pa = pill('satw-pill-a', afterText, 'after', line);
    L.DomEvent.disableClickPropagation(line); L.DomEvent.disableScrollPropagation(line); mw.appendChild(line);
    function clip() {
      var size = map.getSize(), x = Math.round(size.x * frac);
      var nw = map.containerPointToLayerPoint([x, 0]), se = map.containerPointToLayerPoint([size.x, size.y]);
      pane.style.clip = 'rect(' + nw.y + 'px,' + se.x + 'px,' + se.y + 'px,' + nw.x + 'px)';
      line.style.left = x + 'px'; handle.setAttribute('aria-valuenow', String(Math.round(frac * 100)));
      mw.setAttribute('data-swipe-x', String(x));
      pb.hidden = false; pa.hidden = false;          // a pill is shown only where it fits beside the divider (not under the card)
      var vr = Math.min(size.x, visibleRight(mw));
      pb.hidden = x < pb.offsetWidth + 20 || x > vr; pa.hidden = vr - x < pa.offsetWidth + 20;
    }
    function setFrac(f) { frac = Math.max(0, Math.min(1, f)); S.swipeFrac = frac; clip(); }
    handle.addEventListener('pointerdown', function (ev) { ev.preventDefault(); ev.stopPropagation(); map.dragging.disable(); handle.setPointerCapture(ev.pointerId); mw.classList.add('satw-swiping'); });
    handle.addEventListener('pointermove', function (ev) { if (handle.hasPointerCapture(ev.pointerId)) { var r = mw.getBoundingClientRect(); setFrac((ev.clientX - r.left) / r.width); } });
    function release(ev) { if (handle.hasPointerCapture(ev.pointerId)) handle.releasePointerCapture(ev.pointerId); map.dragging.enable(); mw.classList.remove('satw-swiping'); }
    handle.addEventListener('pointerup', release); handle.addEventListener('pointercancel', release);
    handle.addEventListener('keydown', function (ev) {
      var step = {ArrowLeft: -0.05, ArrowRight: 0.05}[ev.key];
      if (step) { ev.preventDefault(); setFrac(frac + step); } else if (ev.key === 'Home' || ev.key === 'End') { ev.preventDefault(); setFrac(ev.key === 'Home' ? 0 : 1); }
    });
    S.swipe = clip; map.on('move zoom zoomanim viewreset resize moveend zoomend', clip); clip();
  }
  function sideBySide(L, map, pair, c, bounds) {
    var wrap = document.getElementById('satw-maps'); wrap.classList.add('split');
    var m2el = document.createElement('div'); m2el.id = 'satw-map2'; m2el.className = 'satw-map'; wrap.appendChild(m2el);
    map.invalidateSize();
    var mw = document.getElementById('satw-mapwrap');
    S.imgLayers.push(imgStatus(mw, L.imageOverlay(imageUrl(pair.before, c), bounds, {pane: 'satwImg'})).addTo(map));
    var m2 = L.map(m2el, {zoomControl: false, attributionControl: false, zoomSnap: 0.25}); S.map2 = m2; S.maps.push(m2);
    [['satwImg', 300], ['satwVmd', 360], ['satwBoundary', 420], ['satwChange', 440]].forEach(function (p) { m2.createPane(p[0]).style.zIndex = p[1]; });
    m2.getPane('satwImg').style.pointerEvents = 'none';
    S.base2 = L.tileLayer(OSM, {maxZoom: 19, opacity: 0.45, className: 'satw-basemap'}); if (S.layersOn.base) S.base2.addTo(m2);
    imgStatus(m2el, L.imageOverlay(imageUrl(pair.after, c), bounds, {pane: 'satwImg'})).addTo(m2);
    var saved = S.polys; S.groups2 = areaLayers(L, m2); S.polys = saved;
    S.vmd2 = vmdLayer(L); if (S.layersOn.vmd) S.vmd2.addTo(m2);
    m2.setView(map.getCenter(), map.getZoom(), {animate: false});
    var busy = false;
    function sync(a, b) { a.on('move', function () { if (busy) return; busy = true; b.setView(a.getCenter(), a.getZoom(), {animate: false}); busy = false; }); }
    sync(map, m2); sync(m2, map);
    pill('satw-pill-b2', pillText('pillBefore', pair.before, c), 'side', document.getElementById('satw-map'));
    pill('satw-pill-a2', pillText('pillAfter', pair.after, c), 'side', m2el);
  }
  function showAcq(a) {
    if (S.mode && S.compare) { S.compare.after = a; } else { S.acq = a; }
    S.acq = a; S.sensor = a.sensor;
    renderAcqBox(); renderComposites(); renderImagery(); setHash(viewParams(), true);
  }
  function setBefore(a) {
    S.compare = {before: a, after: S.compare && S.compare.after || S.acq};
    if (!S.mode && comparePair(S.compare.before, S.compare.after).ok) S.mode = 'swipe';
    renderComposites(); renderImagery(); setHash(viewParams(), true);
  }

  // ── event selection + right card ───────────────────────────────────────────────────────────────────────────────────
  async function selectEvent(id, o) {
    o = o || {}; S.sel = id; var seq = S.seq;
    document.querySelectorAll('.satw-evlist [data-ev]').forEach(function (b) { var on = +b.getAttribute('data-ev') === id; b.classList.toggle('sel', on); b.setAttribute('aria-pressed', String(on)); });
    var card = document.getElementById('satw-card'); if (card) { card.hidden = false; card.innerHTML = '<div class="satw-loading">' + esc(t('loading')) + '</div>'; }
    var ev; try { ev = await get('/events/' + id); } catch (e) { if (card) card.innerHTML = '<p>' + esc(t('error') + ': ' + e.message) + '</p>'; return; }
    if (seq !== S.seq || S.sel !== id) return;
    if (ev.monitored_area_id !== S.areaId) { setHash({area: ev.monitored_area_id, event: id}); openArea(ev.monitored_area_id, {event: id, force: true}); return; }
    S.ev = ev;
    var pair = defaultPair(ev, S.byId, minValid());
    if (o.before && S.byId[+o.before]) pair.before = S.byId[+o.before];
    if (o.acq && S.byId[+o.acq]) pair.after = S.byId[+o.acq];
    S.compare = pair.before && pair.after ? {before: pair.before, after: pair.after} : null;
    S.mode = S.compare && comparePair(S.compare.before, S.compare.after).ok ? (o.mode || 'swipe') : null;
    if (pair.after) { S.acq = pair.after; S.sensor = pair.after.sensor; }
    highlight(id); renderCard(ev); renderAcqBox(); renderComposites(); renderImagery(); callout(ev);
    if (!o.keepView) fitEvent(id);
    setHash(viewParams(), true);
  }
  function polyBounds(id) {
    var polys = (S.polys || {})[id] || []; if (!polys.length) return null;
    var b = S.L.latLngBounds([]); polys.forEach(function (p) { b.extend(p.getBounds()); }); return b.isValid() ? b : null;
  }
  // The event card covers the right side of the map: keep the polygons in the visible part.
  function fitEvent(id) {
    var b = polyBounds(id), card = document.getElementById('satw-card'); if (!b || !S.map) return;
    var right = card && !card.hidden ? card.offsetWidth + 40 : 70;
    S.map.fitBounds(b, {paddingTopLeft: [80, 70], paddingBottomRight: [right, 70], maxZoom: 16, animate: false});
  }
  function highlight(id) {
    Object.keys(S.polys || {}).forEach(function (k) { S.polys[k].forEach(function (l) { l.setStyle({weight: +k === id ? 3.5 : 2, opacity: +k === id || !id ? 1 : 0.55}); }); });
  }
  function callout(ev) {
    if (S.calloutLayer) { S.map.removeLayer(S.calloutLayer); S.calloutLayer = null; }
    if (S.ringLayer) { S.map.removeLayer(S.ringLayer); S.ringLayer = null; }
    var b = polyBounds(ev.id); if (!b) return;
    S.ringLayer = S.L.rectangle(b.pad(0.08), {pane: 'satwCallout', color: '#F5F5F0', weight: 1.5, dashArray: '6 5', fill: false, interactive: false}).addTo(S.map);
    var before = lastClearBeforeOf(ev, S.byId, minValid());
    var parts = ['#' + ev.id, shortCls(ev.classification)];
    if (isNum(ev.changed_area_ha)) parts.push(ha(ev.changed_area_ha));
    var b1 = before && fmtDay(before.sensing_time_utc, null, true), a1 = fmtDay(ev.first_after_time_utc, null, true);
    if (b1 && a1) parts.push(b1 + ' → ' + a1); else if (a1) parts.push(a1);
    if (ev.confidence) parts.push(t(ev.confidence));
    S.calloutLayer = S.L.tooltip({permanent: true, direction: 'top', className: 'satw-callout', pane: 'satwCallout', offset: [0, -4]})
      .setLatLng([b.pad(0.08).getNorth(), b.getCenter().lng]).setContent('<span data-no-i18n>' + esc(parts.join(' · ')) + '</span>').addTo(S.map);
  }
  function evidenceLine(ev) {
    var src = evidenceSource(ev);
    if (!src.eq) return na();
    var head = badge(t(src.eq), qClass(src.eq));
    if (!src.source) return head + ' <small class="satw-muted">' + esc(t('eqNoSource')) + '</small>';
    var s = t('eqFrom', {sensor: t('sens' + src.source.sensor), date: fmtDay(src.source.time, null, true)});
    var o = src.others.map(function (x) { return t('eqOthers', {sensor: t('oth' + x.sensor), eq: t(x.eq).toLowerCase()}); });
    return head + ' <small>' + esc(s + (o.length ? '; ' + o.join('; ') : '')) + '</small>';
  }
  function storyText(ev) {
    var before = lastClearBeforeOf(ev, S.byId, minValid());
    return t('storyTpl', {before: fmtDay(before && before.sensing_time_utc) || t('storyNoBefore'), after: fmtDay(ev.first_after_time_utc) || t('na'), ha: ha(ev.changed_area_ha) || t('na')});
  }
  function renderCard(ev) {
    var card = document.getElementById('satw-card'); if (!card) return;
    var c = changeColour(ev), pair = S.mode && S.compare && comparePair(S.compare.before, S.compare.after).ok ? S.compare : null;
    var row = function (kind, a) { return a ? '<div class="satw-prod" data-acq="' + a.acq_id + '"><span>' + esc(t(kind)) + '</span><span><span class="satw-mono" data-no-i18n>' + esc(fmtDay(a.sensing_time_utc) + ' · ' + a.sensor) + '</span><code data-no-i18n title="' + esc(a.product_id || '') + '">' + esc(a.product_id || t('na')) + '</code></span><span class="satw-mono" data-no-i18n>' + esc(isNum(a.valid_pct_inside) ? fmtNum(a.valid_pct_inside, 1) + ' %' : t('na')) + '</span></div>' : ''; };
    var sup = ev.current === false ? '<div class="satw-banner warn">' + (ev.successor ? esc(t('superseded', {id: ev.successor.event_id})) : esc(t('supersededNone'))) + '</div>' : '';
    card.innerHTML = '<div class="satw-card-top"><span class="satw-eyebrow" data-no-i18n>' + esc(t('eventN', {id: ev.id})) + '</span><button type="button" class="satw-x" data-act="close" aria-label="' + esc(t('close')) + '">×</button></div>' +
      '<span class="satw-chip st" style="--c:' + c.color + '">' + esc(t('s' + ev.status)) + '</span>' +
      '<h3>' + esc(clsLabel(ev.classification)) + ' · <span data-no-i18n>' + esc(ha(ev.changed_area_ha) || t('na')) + '</span></h3>' + sup +
      '<p class="satw-story"><b>' + esc(t('story')) + '.</b> ' + esc(storyText(ev)) + '</p>' +
      '<dl class="satw-kv"><dt>' + esc(t('confidence')) + '</dt><dd>' + (ev.confidence ? badge(t(ev.confidence), qClass(ev.confidence)) : na()) + '</dd>' +
        '<dt>' + esc(t('evidence')) + '</dt><dd class="satw-eq">' + evidenceLine(ev) + '</dd></dl>' +
      (pair ? row('pillBefore', pair.before) + row('pillAfter', pair.after) : '') +
      '<div class="satw-actions">' +
        '<button type="button" class="satw-btn primary" data-act="evidence">' + esc(t('aEvidence')) + '</button>' +
        (ev.current !== false ? '<button type="button" class="satw-btn" data-rv="FIELD_CHECK">' + esc(t('aField')) + '</button>' +
          (ev.risk_id ? '' : '<button type="button" class="satw-btn" data-rv="CREATE_RISK">' + esc(t('aRisk')) + '</button>') +
          '<button type="button" class="satw-btn" data-rv="REJECT">' + esc(t('aReject')) + '</button>' +
          (ev.undo_available ? '<button type="button" class="satw-btn" data-rv="UNDO">' + esc(t('aUndo')) + '</button>' : '') : '') + '</div>';
    card.hidden = false;
    card.querySelector('[data-act=close]').onclick = function () {
      card.hidden = true; S.sel = null; S.ev = null; S.compare = null; S.mode = null; highlight(null);
      if (S.calloutLayer) { S.map.removeLayer(S.calloutLayer); S.calloutLayer = null; } if (S.ringLayer) { S.map.removeLayer(S.ringLayer); S.ringLayer = null; }
      document.querySelectorAll('.satw-evlist [data-ev]').forEach(function (b) { b.classList.remove('sel'); b.setAttribute('aria-pressed', 'false'); });
      renderComposites(); renderImagery(); setHash(viewParams(), true);
    };
    card.querySelector('[data-act=evidence]').onclick = function () { setHash({area: S.areaId, event: ev.id, tab: 'evidence'}); openEvidence(ev.id, true); };
    card.querySelectorAll('[data-rv]').forEach(function (b) {
      b.onclick = async function () {
        var d = b.getAttribute('data-rv'), q = {FIELD_CHECK: 'cField', CREATE_RISK: 'cRisk', REJECT: 'cReject', UNDO: 'cUndo'}[d];
        if (!global.confirm(t(q))) return;
        b.disabled = true;
        try { await post('/events/' + ev.id + '/review', {decision: d}); await openArea(S.areaId, {event: ev.id, force: true}); }
        catch (e) { b.disabled = false; global.alert(t('error') + ': ' + e.message); }
      };
    });
  }

  // ── timeline (S2 circles · S1 diamonds by orbit geometry · onset markers · before/after rings) ──────────────────────
  function geomColour(a) {
    var keys = []; S.area.timeline.forEach(function (x) { if (x.sensor === 'S1' && keys.indexOf(geomKey(x)) < 0) keys.push(geomKey(x)); });
    keys.sort(); return GEOM_COLOURS[keys.indexOf(geomKey(a)) % GEOM_COLOURS.length];
  }
  function renderTimeline() {
    var box = document.getElementById('satw-tl'); if (!box || !S.area) return;
    var tl = S.area.timeline, mv = minValid();
    if (!tl.length) { box.innerHTML = '<div class="satw-empty">' + esc(t('noDataYet')) + '</div>'; return; }
    var end = Date.now(), start = S.window === 'all' ? parseUtc(tl[0].sensing_time_utc).getTime() - DAY : end - S.window * DAY;
    var W = Math.max(600, box.clientWidth || 1100), H = 78, x0 = 92, x1 = W - 14, yS2 = 22, yS1 = 52;
    var X = function (iso) { var d = parseUtc(iso); return d ? x0 + (d.getTime() - start) / (end - start) * (x1 - x0) : -99; };
    var svg = '<svg width="' + W + '" height="' + H + '" class="satw-tl-svg" role="img" aria-label="' + esc(t('timeline')) + '">' +
      '<text x="6" y="' + (yS2 + 4) + '" class="lbl">' + esc(t('tlS2')) + '</text><text x="6" y="' + (yS1 + 4) + '" class="lbl">' + esc(t('tlS1')) + '</text>' +
      '<line x1="' + x0 + '" x2="' + x1 + '" y1="' + yS2 + '" y2="' + yS2 + '" class="trk"/><line x1="' + x0 + '" x2="' + x1 + '" y1="' + yS1 + '" y2="' + yS1 + '" class="trk"/>';
    for (var m = new Date(start); m.getTime() <= end; m = new Date(m.getFullYear(), m.getMonth() + 1, 1)) {
      var mx = X(new Date(m.getFullYear(), m.getMonth(), 1).toISOString());
      if (mx >= x0) svg += '<line x1="' + mx + '" x2="' + mx + '" y1="8" y2="64" class="tick"/><text x="' + (mx + 3) + '" y="74" class="tlbl" data-no-i18n>' + esc((S.lang === 'lv' ? MONTHS_LV : MONTHS_EN)[m.getMonth()] + (m.getMonth() === 0 ? ' ' + m.getFullYear() : '')) + '</text>';
    }
    var lastLbl = -99;                     // onset labels: skip the text (not the marker) when it would overlap the previous one
    (S.events || []).slice().sort(function (p, q) { return String(p.first_after_time_utc).localeCompare(String(q.first_after_time_utc)); }).forEach(function (e) {
      var ex = X(e.first_after_time_utc); if (ex < x0) return; var c = changeColour(e), lbl = ex - lastLbl > 30;
      if (lbl) lastLbl = ex;
      svg += '<g class="onset"><path d="M' + ex + ' 6 l-5 -6 h10 z" transform="translate(0 4)" fill="' + c.color + '"/>' + (lbl ? '<text x="' + (ex + 6) + '" y="9" class="tlbl" data-no-i18n>#' + e.id + '</text>' : '') + '<title>#' + e.id + ' ' + esc(clsLabel(e.classification)) + '</title></g>';
    });
    var pair = S.mode && S.compare ? S.compare : null;
    tl.forEach(function (a) {
      var x = X(a.sensing_time_utc); if (x < x0 || x > x1 + 1) return;
      var st = acqState(a, mv), y = a.sensor === 'S2' ? yS2 : yS1, col = a.sensor === 'S1' ? geomColour(a) : '#7FBF8E';
      var sel = S.acq && S.acq.acq_id === a.acq_id, isB = pair && pair.before && pair.before.acq_id === a.acq_id, isA = pair && pair.after && pair.after.acq_id === a.acq_id;
      var shape;
      if (st === 'cloud') shape = '<path d="M' + (x - 5) + ' ' + (y + 3) + ' a3 3 0 0 1 2 -6 a4 4 0 0 1 7 1 a2.5 2.5 0 0 1 1 5 z" class="cloud"/>';
      else if (st === 'invalid') shape = '<path d="M' + (x - 4) + ' ' + (y - 4) + ' l8 8 M' + (x + 4) + ' ' + (y - 4) + ' l-8 8" class="cross"/>';
      else if (a.sensor === 'S1') shape = '<path d="M' + x + ' ' + (y - 6) + ' l6 6 l-6 6 l-6 -6 z" fill="' + (st === 'ok' ? col : 'none') + '" stroke="' + col + '" stroke-width="1.6"/>';
      else shape = '<circle cx="' + x + '" cy="' + y + '" r="5" fill="' + (st === 'ok' ? col : 'none') + '" stroke="' + col + '" stroke-width="1.6"/>';
      svg += '<g class="acq' + (sel ? ' sel' : '') + (isB ? ' pb' : '') + (isA ? ' pa' : '') + '" data-acq="' + a.acq_id + '" data-state="' + st + '" tabindex="-1">' +
        ((sel || isB || isA) ? '<circle cx="' + x + '" cy="' + y + '" r="9.5" class="ring' + (isB ? ' b' : '') + '"/>' : '') + shape +
        '<rect x="' + (x - 6) + '" y="' + (y - 10) + '" width="12" height="20" fill="transparent"/></g>';
    });
    box.innerHTML = svg + '</svg>';
    var tip = document.getElementById('satw-tip');
    box.querySelectorAll('[data-acq]').forEach(function (g) {
      var a = S.byId[+g.getAttribute('data-acq')];
      g.onmouseenter = function () {
        var st = acqState(a, mv);
        tip.innerHTML = '<b data-no-i18n>' + esc(fmtTime(a.sensing_time_utc)) + '</b><br><span data-no-i18n>' + esc(a.sensor + ' · ' + (a.platform || '') + (a.sensor === 'S1' ? ' · ' + t('orbit') + ' ' + geomKey(a) : '')) + '</span><br>' +
          esc(t({ok: 'stOk', low: 'stLow', cloud: 'stCloud', invalid: 'stInvalid', pending: 'stPending'}[st])) +
          (a.sensor === 'S2' ? ' · ' + esc(t('cloudPct')) + ' <span data-no-i18n>' + (isNum(a.scene_cloud_pct) ? fmtNum(a.scene_cloud_pct, 0) + ' %' : t('na')) + '</span>' : '') +
          ' · ' + esc(t('validPct')) + ' <span data-no-i18n>' + (isNum(a.valid_pct_inside) ? fmtNum(a.valid_pct_inside, 1) + ' %' : t('na')) + '</span>' +
          '<br><code data-no-i18n>' + esc(a.product_id || t('na')) + '</code>';
        tip.hidden = false; var r = box.getBoundingClientRect(), gr = g.getBoundingClientRect();
        tip.style.left = Math.min(r.width - 340, Math.max(0, gr.left - r.left - 150)) + 'px'; tip.style.bottom = (r.bottom - gr.top + 10) + 'px';
      };
      g.onmouseleave = function () { tip.hidden = true; };
      g.onclick = function (ev) {
        if (!a.quicklook_url || a.status !== 'OK') return;
        if (ev.shiftKey) { setBefore(a); return; }
        showAcq(a);
      };
    });
  }
  // Analysis drawer: the EXISTING index charts (sat-monitoring.js drawCharts, logic unchanged) on the same data.
  function renderAnalysis() {
    var box = document.getElementById('satw-analysis-body'); if (!box || !S.area) return;
    box.innerHTML = '<div class="satw-charts"><div><div class="satw-chart-t">' + esc(t('tsS2')) + '</div><div class="satw-chart"><canvas id="satm-ch-s2"></canvas></div></div>' +
      '<div><div class="satw-chart-t">' + esc(t('tsS1')) + '</div><div class="satw-chart"><canvas id="satm-ch-s1"></canvas></div></div></div>';
    var core = legacy()._core; if (core && core.charts) core.charts(S.area);
  }

  // ── PIERĀDĪJUMI: the existing event page, unchanged, inside the workspace frame ─────────────────────────────────────
  async function openEvidence(id, force) {
    if (!force && !claim('evidence:' + id)) return;
    ++S.seq; cleanup(); S.sel = id ? +id : null;
    if (!S.sel) {
      var list = S.ov ? S.ov.latest_events || [] : [];
      if (!S.ov) { try { S.ov = await get('/overview'); list = S.ov.latest_events || []; } catch (e) { errorView(e); return; } }
      var r0 = shell('evidence', '<div class="satw-pick"><p>' + esc(t('evPick')) + '</p>' + latestList(list) + '</div>'); if (!r0) return;
      r0.querySelectorAll('[data-event]').forEach(function (b) { b.onclick = function () { var e = +b.getAttribute('data-event'); setHash({area: +b.getAttribute('data-area'), event: e, tab: 'evidence'}); openEvidence(e, true); }; });
      return;
    }
    var r = shell('evidence', '<div id="satm-evidence" class="satw-evidence"></div>'); if (!r) return;
    var lg = legacy(); if (lg.openEvent) await lg.openEvent(S.sel);
    syncModes();
  }

  // ── entry points (index.html: nav('sat-monitoring') → load; deep links → openArea / openEvent) ──────────────────────
  function load() {
    var p = hashParams();
    if (p.tab === 'evidence') return openEvidence(p.event ? +p.event : null);
    if (p.event) return openArea(+(p.area || 0) || null, p).catch(function () { /* handled inside */ });
    if (p.area) return openArea(+p.area, p);
    return loadTerritory();
  }
  async function openEventEntry(id) {
    var p = hashParams();
    if (p.tab === 'evidence') return openEvidence(+id);
    if (!claim('area::' + id)) return;
    var ev; try { ev = await get('/events/' + id); } catch (e) { errorView(e); return; }
    return openArea(ev.monitored_area_id, Object.assign({}, p, {event: +id, force: true}));
  }
  // openArea(null, {event}) from load(): resolve the area of the event first.
  var openAreaRaw = openArea;
  openArea = async function (id, opts) {
    if (!id && opts && opts.event) {
      if (!claim('area::' + opts.event)) return;
      var ev; try { ev = await get('/events/' + opts.event); } catch (e) { errorView(e); return; }
      return openAreaRaw(ev.monitored_area_id, Object.assign({}, opts, {force: true}));
    }
    return openAreaRaw(id, opts);
  };

  var api = {load: load, openArea: function (id) { return openArea(+id, hashParams()); }, openEvent: function (id) { return openEventEntry(+id); },
             _changeColour: changeColour, _CHANGE_COLOURS: CHANGE_COLOURS, _worstColour: worstColour, _worstOpenEvent: worstOpenEvent,
             _fmtTime: fmtTime, _fmtDay: fmtDay, _fmtClock: fmtClock, _rigaParts: rigaParts, _acqState: acqState, _comparePair: comparePair,
             _pairComposite: pairComposite, _singleComposite: singleComposite, _defaultPair: defaultPair, _vmdValue: vmdValue,
             _evidenceSource: evidenceSource, _trueColourAlternative: trueColourAlternative, _parseCoordinates: parseCoordinates, _inGeometry: inGeometry, _defaultAreaId: defaultAreaId,
             _T: {lv: T_LV, en: T_EN}, _T_EN: T_EN, _T_LV: T_LV, _hashParams: hashParams, _buildHash: buildHash,
             _lastClearBefore: function (ev, byId, mv) { return lastClearBeforeOf(ev, byId, mv); }, _setLang: function (l) { S.lang = l === 'en' ? 'en' : 'lv'; },
             get state() { return S; }};
  global.SatWorkspace = api;
  // Route the section here; keep every other legacy hook (lvmButton, _trServer, _core, …) of window.SatMonitoring.
  if (global.SatMonitoring && !global.SAT_WORKSPACE_DISABLED) {
    var legacyApi = global.SatMonitoring;
    global.SatMonitoring = Object.assign({}, legacyApi, {load: api.load, openArea: api.openArea, openEvent: api.openEvent, _legacy: legacyApi});
  }
})(window);
