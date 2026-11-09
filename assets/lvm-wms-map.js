/* Public reference imagery only. No Forest AI records or credentials are sent. */
(function (global) {
  'use strict';
  const ENDPOINT = 'https://geoserver.lvmgeo.lv/wmsvector62531a9bfcfa4015856924e94076a179';
  const LAYERS = Object.freeze([
    Object.freeze({id: 'lvm_blocks', layer: 'pubblock_LVM', title: 'Meža kvartāli (LVM)', description: 'LVM forest blocks', opacity: 0.65}),
    Object.freeze({id: 'lvm_compartments', layer: 'pubcompartments_LVM', title: 'Meža nogabali (LVM)', description: 'LVM forest compartments', opacity: 0.75})
  ]);
  const STORAGE_KEY = 'forest-ai:lvm-wms:enabled:v1';
  const attached = new WeakMap();
  let remembered = new Set();
  try {
    const saved = JSON.parse(global.sessionStorage.getItem(STORAGE_KEY) || '[]');
    if (Array.isArray(saved)) remembered = new Set(saved.filter(id => LAYERS.some(layer => layer.id === id)));
  } catch (_) { /* Storage restrictions must not affect map operations. */ }

  function attach(map) {
    if (attached.has(map)) return attached.get(map);
    const L = global.L;
    // Use a dedicated context pane: OSM tiles=200, LVM=250, sector paths=400,
    // markers=600, tooltips/popups above. Never change operational panes or CRS.
    const pane = map.getPane('lvmGeoContext') || map.createPane('lvmGeoContext');
    pane.style.zIndex = '250';
    pane.style.pointerEvents = 'none';
    const entries = [];
    const failed = new Set();
    const messageControl = L.control({position: 'bottomleft'});
    let messageBox;
    let messageText;
    function renderMessage() {
      messageBox.style.display = failed.size ? '' : 'none';
      messageText.textContent = failed.size ? 'LVM GEO layer temporarily unavailable. Layer disabled; toggle it on to retry.' : '';
    }
    messageControl.onAdd = function () {
      messageBox = L.DomUtil.create('div', 'leaflet-control lvm-wms-message');
      messageBox.setAttribute('role', 'status');
      Object.assign(messageBox.style, {display: 'none', background: '#fff', color: '#333', padding: '8px',
        borderRadius: '4px', maxWidth: '260px', fontSize: '12px'});
      messageText = L.DomUtil.create('span', '', messageBox);
      const dismiss = L.DomUtil.create('button', '', messageBox);
      dismiss.type = 'button'; dismiss.textContent = '×'; dismiss.title = 'Dismiss';
      dismiss.style.marginLeft = '8px';
      dismiss.onclick = function () { failed.clear(); renderMessage(); };
      L.DomEvent.disableClickPropagation(messageBox);
      L.DomEvent.disableScrollPropagation(messageBox);
      return messageBox;
    };
    messageControl.addTo(map);

    function save() {
      remembered = new Set(entries.filter(entry => map.hasLayer(entry.layer)).map(entry => entry.id));
      try { global.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(remembered))); } catch (_) {}
    }
    const overlays = {};
    LAYERS.forEach(config => {
      const layer = L.tileLayer.wms(ENDPOINT, {
        layers: config.layer, version: '1.3.0', format: 'image/png', transparent: true,
        crs: L.CRS.EPSG3857, pane: 'lvmGeoContext', opacity: config.opacity,
        attribution: 'LVM GEO · LVM', updateWhenIdle: true, updateWhenZooming: false,
        keepBuffer: 1, detectRetina: false, zIndex: 1
        // No crossOrigin flag: browser image tiles work without CORS permission.
        // Leaflet supplies viewport-dependent BBOX, CRS, width and height.
      });
      const entry = {id: config.id, layer, generation: 0, failed: false};
      entries.push(entry); overlays[config.title] = layer;
      layer.on('add', function () {
        entry.generation += 1; entry.failed = false; failed.delete(config.id); renderMessage();
      });
      layer.on('tileerror', function () {
        if (entry.failed || !map.hasLayer(layer)) return;
        entry.failed = true; failed.add(config.id); renderMessage();
        const generation = entry.generation;
        // Disable after the first failed image rather than repeatedly retrying
        // on map movement. Leaflet removes/aborts remaining tiles on removal.
        global.setTimeout(function () {
          if (entry.generation === generation && map.hasLayer(layer)) { map.removeLayer(layer); save(); }
        }, 0);
      });
    });
    // The main map currently has no permanent layer selector. Add a separate
    // native control; existing/dynamic controls and operational layers stay intact.
    const control = L.control.layers(null, overlays, {position: 'topright', collapsed: false}).addTo(map);
    const heading = L.DomUtil.create('div', 'lvm-wms-heading');
    heading.textContent = 'LVM GEO'; heading.style.fontWeight = '600'; heading.style.color = '#333';
    control.getContainer().insertBefore(heading, control.getContainer().firstChild);
    const state = Object.freeze({entries, control, messageControl});
    attached.set(map, state);
    const trackChange = event => { if (entries.some(entry => entry.layer === event.layer)) save(); };
    map.on('layeradd layerremove', trackChange);
    // Snapshot before add events save preferences, so both restored layers load.
    const restore = new Set(remembered);
    entries.forEach(entry => { if (restore.has(entry.id)) entry.layer.addTo(map); });
    map.once('unload', function () {
      map.off('layeradd layerremove', trackChange); attached.delete(map);
    });
    return state;
  }
  global.ForestLvmWms = Object.freeze({mode: 'direct_browser_wms', endpoint: ENDPOINT, layers: LAYERS, attach});
})(window);
