/*
 * Forest Map (Meža karte) overlay "Satelīta izmaiņas": suspected change masks of satellite-monitored areas plus each
 * area's Sentinel observation footprint. Read-only: GET /api/sat-monitoring/map-layer (current detection generation,
 * simplified server-side, bounded to <=600 features / <=400 KB and <=150 KB per area).
 *
 * Hooks in assets/forest-map.js: the 'satchanges' layer checkbox calls ForestMapSat.toggle(); ForestMap exposes
 * map / ready / lang / basemap. Deep links (index.html): #forest-map?sat_event=<id> and #forest-map?sat_area=<id>.
 * Own pane fmSatChange (z 380): above VMD/VZD tiles and sectors (360) and the selection (370), below GPS tracks
 * (610) and GPS markers (620), so GPS stays clickable. Works on both basemaps (footprint colour follows the basemap).
 * Wording stays neutral (D4): "suspected change", automated detection, not verified on the ground.
 */
(function (global) {
  'use strict';
  var API = '/api/sat-monitoring/map-layer', PANE = 'fmSatChange';
  var W = {
    en: {event: 'Event', area: 'Monitored area', onset: 'Event onset', changed: 'Changed area', zone: 'Zone',
         inside: 'Inside the boundary', buffer: 'Outside the boundary (buffer)', confidence: 'Detection confidence',
         status: 'Status', SUSPECTED: 'Suspected', RECOVERED: 'Recovered', REVIEW_CONFIRMED: 'Confirmed by review',
         REVIEW_REJECTED: 'Rejected by review', FIELD_CHECK_REQUESTED: 'Field check requested',
         HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low', open: 'Open event page',
         note: 'Automated detection, not verified on the ground. Geometry simplified ±{m} m.',
         loaded: 'Satellite changes: {n} events in {a} monitored areas', none: 'Satellite changes: no current events',
         failed: 'Satellite changes unavailable: ', footprint: 'Sentinel observation footprint'},
    lv: {event: 'Notikums', area: 'Uzraudzītā teritorija', onset: 'Notikuma sākums', changed: 'Izmaiņu platība',
         zone: 'Zona', inside: 'Robežās', buffer: 'Ārpus robežas (buferzonā)', confidence: 'Noteikšanas ticamība',
         status: 'Statuss', SUSPECTED: 'Iespējamas izmaiņas', RECOVERED: 'Atjaunojies',
         REVIEW_CONFIRMED: 'Apstiprināts pārskatīšanā', REVIEW_REJECTED: 'Noraidīts pārskatīšanā',
         FIELD_CHECK_REQUESTED: 'Pieprasīta lauka pārbaude', HIGH: 'Augsta', MEDIUM: 'Vidēja', LOW: 'Zema',
         open: 'Atvērt notikuma lapu',
         note: 'Automātiska noteikšana, nav pārbaudīta dabā. Ģeometrija vienkāršota ±{m} m.',
         loaded: 'Satelīta izmaiņas: {n} notikumi {a} uzraudzītās teritorijās', none: 'Satelīta izmaiņas: nav aktuālu notikumu',
         failed: 'Satelīta izmaiņas nav pieejamas: ', footprint: 'Sentinel novērojuma pārklājums'}
  };
  // status_group -> style. Magenta/grey/blue read on both Esri imagery and OSM.
  var STYLE = {SUSPECTED: {color: '#ff2bd6', dash: null, fill: 0.28},
               RECOVERED: {color: '#9aa0a6', dash: '4 4', fill: 0.10},
               REVIEWED: {color: '#2f7cff', dash: null, fill: 0.20}};
  var st = {map: null, group: null, data: null, byEvent: {}, seq: 0, hooked: null};

  function fm() { return global.ForestMap; }
  function lang() { return fm() && fm().lang === 'en' ? 'en' : 'lv'; }
  function t(k) { return W[lang()][k] || W.en[k] || k; }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function message(text) { var el = document.getElementById('fm-status'); if (el) el.textContent = text; }
  function el(tag, text, parent) {
    var n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (parent) parent.appendChild(n); return n;
  }

  async function ready() {
    for (var i = 0; i < 150; i++) { if (fm() && fm().ready && global.L) return fm().map; await sleep(200); }
    return null;
  }
  function footprintColor() { return fm() && fm().basemap === 'standard' ? '#333333' : '#ffffff'; }
  function style(f) {
    var p = f.properties || {};
    if (p.kind === 'footprint') return {pane: PANE, color: footprintColor(), weight: 1.5, dashArray: '6 6', fill: false};
    var s = STYLE[p.status_group] || STYLE.SUSPECTED;
    return {pane: PANE, color: s.color, weight: 2.5, dashArray: s.dash, fillColor: s.color, fillOpacity: s.fill};
  }

  function popup(p) {
    var box = el('div'); box.className = 'forest-map-popup fm-sat-popup';
    el('strong', t('event') + ' #' + p.event_id, box);
    var dl = el('dl', undefined, box);
    function row(k, v) { el('dt', t(k), dl); el('dd', v === null || v === undefined || v === '' ? '—' : String(v), dl); }
    row('area', p.area_name);
    row('onset', p.onset_utc ? String(p.onset_utc).slice(0, 10) : null);
    row('changed', typeof p.area_ha === 'number' ? p.area_ha.toFixed(2) + ' ha' : null);
    row('zone', (p.zone === 'BUFFER' ? t('buffer') : p.zone === 'INSIDE' ? t('inside') : p.zone) +
        (typeof p.zone_ha === 'number' ? ' · ' + p.zone_ha.toFixed(2) + ' ha' : ''));
    row('confidence', p.confidence ? t(p.confidence) : null);
    row('status', p.status ? t(p.status) : null);
    var note = el('p', t('note').replace('{m}', String((st.data && st.data.simplified_m_by_area &&
      st.data.simplified_m_by_area[String(p.area_id)]) || (st.data && st.data.simplified_m) || 0)), box);
    note.className = 'forest-map-next';
    var a = el('a', t('open'), box); a.href = p.event_url || ('#sat-monitoring?event=' + p.event_id);
    a.className = 'btn fm-sat-open';
    return box;
  }

  function clear() {
    if (st.group && st.map) { try { st.map.removeLayer(st.group); } catch (e) { /* map already removed */ } }
    st.group = null; st.byEvent = {};
  }
  function hook(map) {                       // restyle footprints when the basemap changes (both basemaps)
    if (st.hooked === map) return;
    st.hooked = map;
    map.on('layeradd', function (e) {
      if (st.group && st.map === map && e.layer instanceof global.L.TileLayer) st.group.setStyle(style);
    });
  }
  function draw(map, d) {
    clear();
    if (!map.getPane(PANE)) map.createPane(PANE).style.zIndex = 380;
    hook(map);
    st.map = map; st.data = d;
    st.group = global.L.geoJSON(d, {
      pane: PANE, style: style,
      onEachFeature: function (f, layer) {
        var p = f.properties || {};
        if (p.kind === 'event') {
          layer.bindPopup(function () { return popup(p); }, {maxWidth: 320, autoPanPadding: [24, 24]});
          (st.byEvent[p.event_id] = st.byEvent[p.event_id] || []).push(layer);
        } else {
          layer.bindTooltip(t('footprint') + ' · ' + (p.area_name || ''), {sticky: true});
        }
      }
    }).addTo(map);
    message(d.counts && d.counts.events ? t('loaded').replace('{n}', d.counts.events).replace('{a}', d.counts.areas)
                                        : t('none'));
  }
  async function show(query) {
    var map = await ready();
    if (!map) return null;
    var seq = ++st.seq;
    var r = await fetch(API + (query ? '?' + query : ''), {credentials: 'same-origin', cache: 'no-store'});
    var d = {};
    try { d = await r.json(); } catch (e) { d = {}; }
    if (!r.ok) { var err = new Error(d.error || ('HTTP ' + r.status)); err.status = r.status; throw err; }
    if (seq !== st.seq || fm().map !== map) return null;     // superseded by a newer request / map rebuilt
    draw(map, d);
    return d;
  }
  function checkbox(on) { var c = document.getElementById('fm-layer-satchanges'); if (c) c.checked = on; }
  function focus(d, eventId) {
    if (!d || !st.map) return;
    var b = d.focus && d.focus.bbox;
    if (b) st.map.fitBounds([[b[1], b[0]], [b[3], b[2]]], {padding: [48, 48], maxZoom: 16, animate: false});
    if (eventId) {
      var layers = st.byEvent[eventId] || [];
      // open on the largest part of the event (INSIDE or BUFFER feature)
      layers.sort(function (x, y) { return (y.feature.properties.zone_ha || 0) - (x.feature.properties.zone_ha || 0); });
      if (layers[0]) layers[0].openPopup();
    }
  }

  async function toggle(visible) {
    if (!visible) { st.seq++; clear(); return; }
    try { await show(''); } catch (e) { checkbox(false); message(t('failed') + e.message); }
  }
  async function open(query, eventId) {
    // Same as a GPS session deep link: the violations overview must not re-fit the map away from this target.
    if (fm() && fm().holdView) fm().holdView();
    checkbox(true);
    try { var d = await show(query); focus(d, eventId); return d; }
    catch (e) { message(t('failed') + e.message); return null; }
  }
  global.ForestMapSat = Object.freeze({
    toggle: toggle,
    openEvent: function (id) { return open('event_id=' + encodeURIComponent(id), Number(id)); },
    openArea: function (id) { return open('area_id=' + encodeURIComponent(id), null); },
    get data() { return st.data; }, get visible() { return !!st.group; },
    _style: style, _popup: popup, _W: W
  });
})(window);
