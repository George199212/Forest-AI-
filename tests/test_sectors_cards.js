'use strict';
// Sectors cards (Stage 1 prototype): pure rules — status only from stored data, D4 preview selection, NULL never 0,
// suspected vs confirmed kept apart, worst colour imported from the Stage 5 module (never re-implemented), D3 fixture flag.
// Run: node --test tests/test_sectors_cards.js
const {test} = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const ROOT = path.join(__dirname, '..'), read = f => fs.readFileSync(path.join(ROOT, f), 'utf8');
function load(extra) {
  const ctx = {console, Intl, Date, Object, Promise, JSON, Math, setTimeout, clearTimeout, ...(extra || {})}; ctx.window = ctx;
  ctx.document = {getElementById: () => null, querySelector: () => null, querySelectorAll: () => [], head: {appendChild() {}}};
  vm.createContext(ctx); vm.runInContext(read('assets/sectors-cards.js'), ctx); return ctx.SectorCards;
}
const FX = JSON.parse(read('tests/fixtures/sectors_ui/sector_cards.json')).sectors;
const byId = id => FX.find(s => String(s.id) === String(id));
const mon = (o) => Object.assign({area_id: 9, source: 'SECTOR', active: true, removed_at_utc: null, ok_acquisitions: 3, open_suspected: 0,
  confirmed: 0, open_events: [], preview: null, grid_bbox: [24, 56, 24.01, 56.01], min_valid_pct: 60}, o);
const ring = [[24, 56], [24.02, 56], [24.02, 56.01], [24, 56.01], [24, 56]];

test('status is derived only from stored fields', () => {
  const C = load();
  assert.equal(C._deriveStatus({monitoring: null}), 'NOT_MONITORED');
  assert.equal(C._deriveStatus({monitoring: null, queued_job_id: 3}), 'AWAITING_FIRST_DATA');      // ADD_AREA job queued
  assert.equal(C._deriveStatus({monitoring: mon({ok_acquisitions: 0})}), 'AWAITING_FIRST_DATA');
  assert.equal(C._deriveStatus({monitoring: mon({ok_acquisitions: null})}), 'AWAITING_FIRST_DATA');
  assert.equal(C._deriveStatus({monitoring: mon({})}), 'MONITORED');
  assert.equal(C._deriveStatus({monitoring: mon({active: false})}), 'STOPPED');
  assert.equal(C._deriveStatus({monitoring: mon({removed_at_utc: '2026-11-01T00:00:00Z'})}), 'STOPPED');
  // real fixture (DB copy 2026-11-17): BIK-001 + sector 76 monitored, 81 not monitored
  assert.equal(C._deriveStatus(byId(26)), 'MONITORED');
  assert.equal(C._deriveStatus(byId(76)), 'MONITORED');
  assert.equal(C._deriveStatus(byId(81)), 'NOT_MONITORED');
});

test('D4 preview: image only with a stored Sentinel image AND ≥ 64 S2 pixels; otherwise honest polygon states', () => {
  const C = load();
  assert.equal(C.PREVIEW_MIN_PX, 64); assert.equal(C.S2_PIXEL_M, 10);
  const big = {ring, extent_m: {w: 1300, h: 1100}};
  assert.deepEqual(JSON.parse(JSON.stringify(C._previewSource({ring: null}))), {kind: 'none', reason: 'noBoundary'});
  assert.equal(C._previewSource({...big, monitoring: null}).reason, 'noImage');
  assert.equal(C._previewSource({...big, monitoring: mon({preview: null})}).reason, 'noImage');
  const img = C._previewSource({...big, monitoring: mon({preview: {acq_id: 5, kind: 'truecolor', sensing_time_utc: '2026-10-27T09:44:44Z'}})});
  assert.equal(img.kind, 'image'); assert.equal(img.url, '/api/sat-monitoring/file/5/truecolor'); assert.equal(img.composite, 'truecolor');
  const fc = C._previewSource({...big, monitoring: mon({preview: {acq_id: 6, kind: 'falsecolor'}})});
  assert.equal(fc.url, '/api/sat-monitoring/file/6/quicklook'); assert.equal(fc.composite, 'falsecolor');
  // threshold edge: 639 m → 63.9 px → too small; 640 m → 64 px → image
  assert.equal(C._previewSource({ring, extent_m: {w: 639, h: 100}, monitoring: mon({preview: {acq_id: 1, kind: 'truecolor'}})}).reason, 'tooSmall');
  assert.equal(C._previewSource({ring, extent_m: {w: 640, h: 100}, monitoring: mon({preview: {acq_id: 1, kind: 'truecolor'}})}).kind, 'image');
  // real fixture: sector 76 (0.21 ha, ~14 px) has a true-colour image but is too small; BIK-001 (~105 px) shows false colour
  assert.equal(C._previewSource(byId(76)).reason, 'tooSmall');
  assert.equal(C._previewSource(byId(26)).composite, 'falsecolor');
  assert.equal(C._previewSource(byId(81)).reason, 'noImage');
});

test('NULL is never rendered as 0; suspected and confirmed stay separate numbers', () => {
  const C = load();
  assert.deepEqual(JSON.parse(JSON.stringify(C._counts({monitoring: null}))), {suspected: null, confirmed: null});
  assert.deepEqual(JSON.parse(JSON.stringify(C._counts({monitoring: mon({open_suspected: 8, confirmed: 2})}))), {suspected: 8, confirmed: 2});
  assert.deepEqual(JSON.parse(JSON.stringify(C._counts({monitoring: mon({open_suspected: null, confirmed: undefined})}))), {suspected: null, confirmed: null});
  const src = read('assets/sectors-cards.js');
  assert.match(src, /function countHtml\(v\) \{ return isNum\(v\) \? '<b>' \+ v \+ '<\/b>' : na\(\); \}/);
  for (const m of src.matchAll(/suspected: '([^']+)'/g)) assert.doesNotMatch(m[1], /verified|apstiprin/i);   // never "verified"
});

test('worst colour comes from SatWorkspace._worstColour (Stage 5 §4.4), never re-implemented here', () => {
  let called = null;
  const C = load({SatWorkspace: {_worstColour: ev => { called = ev; return {key: 'red', color: '#C94B42'}; }}});
  const card = {monitoring: mon({open_events: [{status: 'SUSPECTED', classification: 'POTENTIAL_FOREST_LOSS', confidence: 'HIGH'}]})};
  assert.equal(C._worstColour(card).key, 'red'); assert.equal(called.length, 1);
  assert.equal(load()._worstColour(card), null);                  // module absent → no dot, not a guessed colour
  assert.equal(C._worstColour({monitoring: mon({open_events: []})}), null);
  assert.doesNotMatch(read('assets/sectors-cards.js'), /#C94B42|#D97736|#D4B23A/);
});

test('search + filter; identifier as stored; D3 fixture card flagged', () => {
  const C = load();
  const c81 = byId(81);
  assert.equal(C._identifierText(c81), '60…(11) · kv. 348 nog. 10');   // cadastral number masked in the fixture
  assert.ok(C._matches(c81, 'nog. 10', 'ALL')); assert.ok(C._matches(c81, 'lg917 k348', 'NOT_MONITORED'));
  assert.ok(!C._matches(c81, 'LG917', 'MONITORED'));
  assert.equal(C._identifierText(byId(26)), null);                 // BIK-001: no registration record → "Nav pieejams"
  const k = byId('fixture-kekava');
  assert.equal(k._fixture_only, true);
  assert.equal(FX.filter(s => s._fixture_only).length, 1);
  assert.equal(FX.filter(s => !s._fixture_only).length, 85);
});

test('routes: #sectors/{id} and #sectors/{id}/{module}', () => {
  const C = load();
  assert.deepEqual(JSON.parse(JSON.stringify(C.routeFromHash('sectors/26/compare'))), {type: 'sectorModule', id: '26', module: 'compare'});
  assert.deepEqual(JSON.parse(JSON.stringify(C.routeFromHash('sectors/26/gps'))), {type: 'sectorModule', id: '26', module: 'gps'});
  assert.equal(C.routeFromHash('sectors/26/satellite'), null);      // legacy satellite tab is not a module route (O2)
  assert.deepEqual(JSON.parse(JSON.stringify(C.routeFromHash('sectors/81'))), {type: 'sectorPage', id: '81'});
  assert.deepEqual(JSON.parse(JSON.stringify(C.routeFromHash('sectors/fixture-kekava'))), {type: 'sectorPage', id: 'fixture-kekava'});
  assert.equal(C.routeFromHash('sectors'), null); assert.equal(C.routeFromHash('sector-BIK-001'), null);
  assert.equal(C.routeFromHash('sectors/%E0%A4%A'), null);
});

test('D11 activity: counters only when > 0; source unavailable → null (not 0); Foto → photo comparison', () => {
  const C = load();
  assert.equal(C._activityCounts(null), null);
  assert.equal(C._activityCounts({error: 'Not found'}), null);
  const bik = {sector: {name: 'BIK-001'}, gps_sessions: [1, 2, 3, 4], risks: [1, 2], truck_reports: [], timber_movements: [],
               comments: [1, 2], photos: new Array(48).fill(0)};
  assert.deepEqual(JSON.parse(JSON.stringify(C._activityCounts(bik))),
    [{module: 'gps', count: 4}, {module: 'risks', count: 2}, {module: 'comments', count: 2}, {module: 'compare', count: 48}]);
  assert.deepEqual(JSON.parse(JSON.stringify(C._activityCounts({sector: {}, gps_sessions: [], photos: []}))), []);
  // the photo line's module is the existing Salīdzināšana tab id used by index.html detailTab('compare')
  assert.match(read('index.html'), /else if \(tab==='compare'\) \{\s*loadPhotoCompare\(s\.name\);/);
});

test('D10/D12: legacy detail + RU table only behind SECTOR_LEGACY_MODULES; nothing deleted', () => {
  const html = read('index.html');
  assert.match(html, /if \(window\.SectorCards && !window\.SECTOR_LEGACY_MODULES && !opts\.module\) return window\.SectorCards\.openByName\(name, push\);/);
  assert.match(html, /if \(window\.SectorCards && !window\.SECTOR_LEGACY_MODULES\) \{\s*if \(objectFilter === undefined\)/);
  for (const keep of ['id="detail-tabs"', 'id="detail-stats"', 'id="detail-score-card"', 'Upload sector satellite', '<th>Сектор</th>'])
    assert.ok(html.includes(keep), 'legacy code kept: ' + keep);
  assert.equal((html.match(/<script src="\/assets\/forest-map\.js\?v=20261107"><\/script>/g) || []).length, 1);
});

test('R3 area: 0 < ha < 0.01 → "<0,01 ha"; stored 0 with a polygon never "0 ha"; NULL → null ("Nav pieejams")', () => {
  const C = load();
  assert.equal(C._haText({area_ha: 0.004, ring}), '<0,01 ha');
  assert.equal(C._haText({area_ha: 0.009, ring}), '<0,01 ha');
  assert.equal(C._haText({area_ha: 0, ring}), '<0,01 ha');
  assert.equal(C._haText({area_ha: 0, ring: null}), null);
  assert.equal(C._haText({area_ha: null, ring}), null);
  assert.equal(C._haText({area_ha: 0.21, ring}), '0,21 ha');
  assert.equal(C._haText(byId(16)), '<0,01 ha');                     // real fixture: stored 0 with a polygon
});

test('R2 small-sector note from pixel size only; R1 no developer text in UI strings', () => {
  const C = load();
  assert.equal(C._isSmallSector(byId(76)), true);
  assert.equal(C._isSmallSector(byId(26)), false);
  assert.equal(C._isSmallSector({ring: null, extent_m: null}), false);
  const src = read('assets/sectors-cards.js');
  const strings = src.slice(src.indexOf('var T = {'), src.indexOf('// ── state'));
  for (const bad of [/Stage\s*\d/i, /SatWorkspace/, /\bD\d+\b/, /mount\(/, /fixture|fiktūr/i])
    assert.doesNotMatch(strings.replace(/fixture: '/g, "x: '"), bad, String(bad));
  assert.match(strings, /smallNote: 'Sektors ir mazs Sentinel-2 izšķirtspējai \(10 m\) — izmaiņu noteikšana var būt neuzticama'/);
});
