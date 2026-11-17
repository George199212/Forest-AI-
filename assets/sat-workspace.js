/*
 * Forest AI — Satellite Intelligence Workspace (Stage 5, prototype variant B, branch feature/satellite-workspace).
 * Map-first workspace on top of the existing /api/sat-monitoring/* API (read-only additions of 2026-11-17).
 * NOT deployed. Mounted into #satm-root (section #sec-sat-monitoring); window.SatMonitoring keeps lvmButton and the
 * other legacy hooks, only load / openArea / openEvent are routed here (see the bottom of this file).
 *
 * Rules (owner): wording "Iespējamas izmaiņas / Suspected change"; raw observation, processed measurement, system
 * interpretation and human decision are separate blocks; missing = "Nav pieejams", never 0; no fabricated imagery or
 * timestamps; "Contains modified Copernicus Sentinel data [YEAR]" under every Sentinel image; processing time is never
 * shown as the event time. Base map = OSM (Esri World Imagery is not offered: licence not clear for commercial use).
 */
(function (global) {
  'use strict';
  var API = '/api/sat-monitoring';
  var OSM = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  var LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
  var LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
  var VMD_TILES = '/api/geodata/forest-map/tiles/forest/{z}/{x}/{y}';
  var DAY = 86400000;

  // ── §4.4 change colour language: ONE table, the legend is generated from it ─────────────────────────────
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

  // ── time: stored UTC → Europe/Riga with an explicit offset ("07:38 EET, 05:38 UTC") ─────────────────────────
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

  // ── acquisitions: timeline state, compare-pair rules ───────────────────────────────────────────────────────────
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
  // VMD p_cirg / p_cirp: stored 0 / 0.0 / NULL mean "not stated" — never a year
  function vmdValue(v) { return v === null || v === undefined || v === '' || Number(v) === 0 ? null : (Number(v) % 1 === 0 ? String(Number(v)) : String(v)); }

  // ── strings ────────────────────────────────────────────────────────────────────────────────────────────────────
  var T = {
    lv: {
      title: 'Satelītu monitorings', refresh: 'Atjaunot', na: 'Nav pieejams', notStated: 'nav norādīts',
      areas: 'Uzraudzītās teritorijas', monitoredHa: 'Uzraudzītā platība', openEvents: 'Atvērtas iespējamās izmaiņas',
      awaitingReview: 'Gaida pārskatīšanu', lastSync: 'Pēdējā veiksmīgā sinhronizācija', usage: 'Copernicus patēriņš šomēnes',
      worker: 'Apstrādes process', latest: 'Jaunākās izmaiņas', allAreas: 'Visas teritorijas', addSector: 'Pievienot sektoru',
      fetchNow: 'Ielādēt tagad', guard: 'drošības robeža', requests: 'pieprasījumi', noAreas: 'Vēl nav uzraudzītu teritoriju.',
      noAreasHint: 'Pievienojiet sektoru vai izmantojiet “Pievienot satelītu monitoringam” sadaļā LVM GEO.',
      noEvents: 'Šajā teritorijā nav iespējamo izmaiņu notikumu.', noEventsHint: 'Uzraudzība darbojas; izmaiņas nav konstatētas.',
      noDataYet: 'Uzraudzība vēl nav sniegusi datus. Pirmā ielāde notiek, kad apstrādes process paņem uzdevumu.',
      backfill: 'Notiek vēsturisko datu ielāde.', degraded: 'Copernicus piekļuves problēma', notConfigured: 'Apstrādes process ziņoja, ka trūkst Copernicus piekļuves datu.',
      unknownProvider: 'Statuss nav zināms: apstrādes process vēl nav ziņojis par Copernicus piekļuvi.',
      dbUnavailable: 'Satelītu monitoringa dati nav pieejami (satellite.db).', error: 'Kļūda',
      lastAcq: 'Pēdējais satelīta uzņēmums', lastAnalysis: 'Pēdējā veiksmīgā analīze', lastCheck: 'Pēdējā sistēmas pārbaude',
      system: 'sistēma', optical: 'S2 Optiskais', radar: 'S1 Radars', trueC: 'Patiesās krāsas', falseC: 'Viltus krāsas',
      compare: 'Salīdzināt', layers: 'Slāņi', theme: 'Tēma', light: 'Gaišā', dark: 'Tumšā', back: '← Visas teritorijas',
      events: 'Izmaiņu notikumi', lBoundary: 'Robeža', lBuffer: 'Buferzona', lChange: 'Izmaiņu poligoni',
      lFootprint: 'Novērojuma pārklājums', lImage: 'Sentinel attēls', lVmd: 'VMD meža nogabali', lBase: 'Fona karte (OSM)',
      inside: 'robežās', outside: 'ārpus robežas', onset: 'sākums',
      cRed: 'Iespējams meža zudums — augsta/vidēja ticamība', cOrange: 'Iespējams meža zudums — zema ticamība',
      cYellow: 'Iespējamas sezonālas vai vides izmaiņas / nepietiekami pierādījumi', cBlueGrey: 'Apstiprināts pārskatīšanā',
      cGrey: 'Noraidīts vai atjaunojies', cUnknown: 'Cits statuss', hatch: 'Svītrots = ārpus robežas',
      clsLOSS: 'Iespējams meža zudums', clsOUT: 'Iespējamas izmaiņas ārpus robežas', clsSEAS: 'Iespējamas sezonālas vai vides izmaiņas',
      clsINS: 'Nepietiekami pierādījumi', shortLOSS: 'meža zudums?', shortOUT: 'ārpus robežas?', shortSEAS: 'sezonāls?', shortINS: 'nepietiek datu',
      sSUSPECTED: 'Iespējamas izmaiņas', sRECOVERED: 'Atjaunojies', sREVIEW_CONFIRMED: 'Apstiprināts pārskatīšanā',
      sREVIEW_REJECTED: 'Noraidīts pārskatīšanā', sFIELD_CHECK_REQUESTED: 'Pieprasīta lauka pārbaude',
      confidence: 'Noteikšanas ticamība', evidence: 'Pierādījumu kvalitāte', HIGH: 'Augsta', MEDIUM: 'Vidēja', LOW: 'Zema',
      GOOD: 'Laba', LIMITED: 'Ierobežota', POOR: 'Vāja',
      story: 'Kas mainījās', storyTpl: 'Starp {before} un {after} satelīts reģistrēja veģetācijas izzušanu {ha} platībā — {cls}, dabā nav pārbaudīts.',
      storyVmd: 'VMD dati: lielākā daļa — {ha} — ir {zkat}.', storyNoBefore: 'Pirms attēla datums nav pieejams',
      zkat14Note: 'VMD šos nogabalus uzskaita kā izcirtumu — iespējams, ciršana ir reģistrēta.',
      observation: 'Novērojums (izejdati)', measurement: 'Mērījums (apstrādāti dati)', interpretation: 'Interpretācija (sistēma)',
      decision: 'Lēmums (cilvēks)', lastClear: 'Pēdējais tīrais uzņēmums bez izmaiņām', firstChange: 'Pirmais uzņēmums ar izmaiņām',
      latestAfter: 'Jaunākais uzņēmums ar izmaiņām', detected: 'Noteikts (apstrādes laiks)',
      curHa: 'Pašreizējā maska', insideHa: 'Robežās', outsideHa: 'Ārpus robežas (buferzonā)', share: 'Teritorijas daļa',
      cluster: 'Lielākais klasteris', maxDist: 'Maks. attālums ārpus robežas', unionHa: 'Visu pēcattēlu apvienojums', maxHa: 'Lielākā platība līdz šim',
      classification: 'Klasifikācija', caveat: 'Sezonāls brīdinājums', vmdTitle: 'VMD nogabali pašreizējā maskā (metadati)',
      vmdNote: 'Metadati no VMD reģistra; tie nemaina klasifikāciju, ticamību vai statusu.', vmdNone: 'Nav VMD nogabalu pašreizējā maskā.',
      vmdUnavailable: 'VMD dati nav pieejami', kvNog: 'kv.–nog.', zkat: 'zkat', haInMask: 'ha maskā', pCirg: 'cirt. gads', pCirp: 'cirt. veids',
      zkat10: 'mežaudze (zkat 10)', zkat14: 'izcirtums (zkat 14)', zkatOther: 'zkat {z}',
      status: 'Statuss', reviewLog: 'Pārskatīšanas žurnāls', noReview: 'Vēl nav pārskatīts.',
      aCompare: 'Salīdzināt pirms/pēc', aField: 'Pieprasīt lauka pārbaudi', aRisk: 'Izveidot risku', aReject: 'Noraidīt', aUndo: 'Atsaukt',
      cField: 'Nosūtīt lauka pārbaudes pieprasījumu dispečeram (Telegram)?', cRisk: 'Izveidot risku šīm iespējamajām izmaiņām?',
      cReject: 'Atzīmēt šīs iespējamās izmaiņas kā noraidītas (nav reālas izmaiņas)?', cUndo: 'Atsaukt pēdējo pārskatīšanas lēmumu?',
      superseded: 'Šis notikums ir aizstāts ar #{id} (jaunāka noteikšanas paaudze).', supersededNone: 'Šis notikums ir aizstāts; pēctecis nav atrasts.',
      openSuccessor: 'Atvērt #{id}', suspectedLine: 'Iespējamas izmaiņas — automātiska noteikšana, dabā nav pārbaudīts.',
      modeA: 'A Pārvilkt', modeB: 'B Blakus', modeC: 'C Pēc + izmaiņas', modeD: 'D Tikai izmaiņas', before: 'Pirms', after: 'Pēc',
      pairMissing: 'Nav derīga pirms/pēc pāra', pairSame: 'Izvēlēts tas pats uzņēmums', pairSensor: 'Salīdzināt var tikai viena sensora uzņēmumus',
      pairGeometry: 'S1 salīdzina tikai vienas orbītas ģeometrijas (virziens + relatīvā orbīta) uzņēmumus', pairNoImage: 'Uzņēmumam nav attēla',
      pairOrder: '“Pirms” jābūt agrākam par “pēc”', compositeNote: 'Patiesās krāsas nav abiem attēliem — abās pusēs rādītas viltus krāsas.',
      s1Label: 'Radara attēls — nav fotogrāfija (VH, −25…−5 dB)', falseNote: 'Viltus krāsas (B11/B08/B04): veselīgs mežs zaļš, izcirtums violets/brūns.',
      trueNote: 'Patiesās krāsas (B04/B03/B02)', validPct: 'Derīgi %', product: 'Produkts', copy: 'Kopēt', copied: 'Nokopēts',
      timeline: 'Uzņēmumu laika josla', days120: '120 d', allDays: 'Viss', s1Filter: 'S1 ģeometrija', allGeom: 'visas',
      stOk: 'Derīgs', stLow: 'Zem derīguma sliekšņa', stCloud: 'Mākoņi — izlaists', stInvalid: 'Nav derīgu pikseļu / kļūda', stPending: 'Gaida',
      cloud: 'Mākoņi', analysis: 'Analīze', analysisNote: 'Teritorijas mediāna. Notikuma poligona līkne — vēlāk.',
      technical: 'Tehniskie dati', thTime: 'Uzņemts', thSensor: 'Sensors', thStatus: 'Statuss', thValid: 'Derīgi %', thOutcome: 'Noteikšana',
      acqCard: 'Uzņēmums', sensing: 'Uzņemts', platform: 'Platforma', geometry: 'Orbīta', metrics: 'Mediāna teritorijā',
      showOnMap: 'Rādīt kartē', setBefore: 'Iestatīt kā “pirms”', shiftHint: 'Klikšķis — rādīt; Shift+klikšķis — “pirms”.',
      attribution: 'Contains modified Copernicus Sentinel data {year}', outcome: 'Noteikšanas rezultāts',
      o_NO_BASELINE: 'Nav bāzes uzņēmuma', o_NO_CHANGE: 'Nav izmaiņu', o_SINGLE_DROP: 'Vienreizējs radara kritums — nav notikums',
      o_RADAR_ANOMALY: 'Radara anomālija (gaida apstiprinājumu)', o_EVENT_UPDATED: 'Notikums atjaunināts', o_EVENT_CREATED: 'Notikums izveidots',
      o_NOT_USABLE: 'Nav izmantojams', o_PENDING_CONFIRMATION: 'Gaida apstiprinājumu', o_CANDIDATE_BELOW_MIN: 'Kandidāts zem minimālās platības',
      o_UNIFORM_DROP_ATMOSPHERIC: 'Vienmērīgs kritums (atmosfēra)', s_SKIPPED_CLOUD: 'Mākoņi — izlaists', s_NO_VALID_PIXELS: 'Nav derīgu pikseļu',
      s_OK: 'Apstrādāts', s_PENDING: 'Gaida', s_ERROR: 'Kļūda', dOK: 'Dati kārtībā', dNO_DATA_YET: 'Vēl nav datu',
      dBACKFILL_OR_FETCH_IN_PROGRESS: 'Notiek ielāde', dSTOPPED: 'Apturēts', srcSECTOR: 'Sektors', srcLVM_GEO: 'LVM GEO', srcEVAL_BBOX: 'Novērtējuma teritorija',
      wIDLE: 'Dīkstāvē', wRUNNING: 'Darbojas', wNOT_INSTALLED: 'Nav uzstādīts', wTIMERS_OFF: 'Taimeri izslēgti', wUNKNOWN: 'Statuss nav zināms',
      nextDaily: 'nākamā ikdienas palaišana', open: 'Atvērt', ha: 'ha', loading: 'Ielādē…', imgLoading: 'Ielādē attēlu…', imgFailed: 'Attēlu neizdevās ielādēt.'
    },
    en: {
      title: 'Satellite Monitoring', refresh: 'Refresh', na: 'Not available', notStated: 'not stated',
      areas: 'Monitored areas', monitoredHa: 'Monitored area', openEvents: 'Open suspected changes', awaitingReview: 'Awaiting review',
      lastSync: 'Last successful sync', usage: 'Copernicus usage this month', worker: 'Worker', latest: 'Latest changes', allAreas: 'All areas',
      addSector: 'Add sector', fetchNow: 'Fetch now', guard: 'guard', requests: 'requests', noAreas: 'No monitored areas yet.',
      noAreasHint: 'Add a sector here, or use “Add to satellite monitoring” in LVM GEO.', noEvents: 'No suspected change events in this area.',
      noEventsHint: 'Monitoring is running; no change detected.', noDataYet: 'Monitoring has not produced data yet. The first fetch runs when the worker picks up the job.',
      backfill: 'Backfill in progress.', degraded: 'Copernicus access problem', notConfigured: 'The worker reported missing Copernicus credentials.',
      unknownProvider: 'Status unknown: the worker has not reported Copernicus access yet.', dbUnavailable: 'Satellite monitoring data is unavailable (satellite.db).',
      error: 'Error', lastAcq: 'Last satellite acquisition', lastAnalysis: 'Last successful analysis', lastCheck: 'Last system check', system: 'system',
      optical: 'S2 Optical', radar: 'S1 Radar', trueC: 'True colour', falseC: 'False colour', compare: 'Compare', layers: 'Layers', theme: 'Theme',
      light: 'Light', dark: 'Dark', back: '← All areas', events: 'Change events', lBoundary: 'Boundary', lBuffer: 'Buffer ring',
      lChange: 'Change polygons', lFootprint: 'Observation footprint', lImage: 'Sentinel image', lVmd: 'VMD forest compartments', lBase: 'Base map (OSM)',
      inside: 'inside', outside: 'outside', onset: 'onset',
      cRed: 'Potential forest loss — high/medium confidence', cOrange: 'Potential forest loss — low confidence',
      cYellow: 'Possible seasonal/environmental change or insufficient evidence', cBlueGrey: 'Confirmed by review', cGrey: 'Rejected or recovered',
      cUnknown: 'Other status', hatch: 'Hatched = outside the boundary',
      clsLOSS: 'Potential forest loss', clsOUT: 'Potential change outside the boundary', clsSEAS: 'Possible seasonal or environmental change',
      clsINS: 'Insufficient evidence', shortLOSS: 'forest loss?', shortOUT: 'outside?', shortSEAS: 'seasonal?', shortINS: 'insufficient',
      sSUSPECTED: 'Suspected', sRECOVERED: 'Recovered', sREVIEW_CONFIRMED: 'Confirmed by review', sREVIEW_REJECTED: 'Rejected by review',
      sFIELD_CHECK_REQUESTED: 'Field check requested', confidence: 'Detection confidence', evidence: 'Evidence quality',
      HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low', GOOD: 'Good', LIMITED: 'Limited', POOR: 'Poor',
      story: 'What changed', storyTpl: 'Between {before} and {after} the satellite recorded vegetation loss on {ha} — {cls}, not verified on the ground.',
      storyVmd: 'VMD data: most of it — {ha} — is {zkat}.', storyNoBefore: 'Before-image date not available',
      zkat14Note: 'VMD lists these compartments as clear-cut land — a felling may be registered.',
      observation: 'Observation (raw)', measurement: 'Measurement (processed)', interpretation: 'Interpretation (system)', decision: 'Decision (human)',
      lastClear: 'Last clear acquisition without change', firstChange: 'First acquisition showing the change', latestAfter: 'Latest acquisition showing the change',
      detected: 'Detected (processing time)', curHa: 'Current mask', insideHa: 'Inside the boundary', outsideHa: 'Outside the boundary (buffer)',
      share: 'Share of the area', cluster: 'Largest cluster', maxDist: 'Max distance outside the boundary', unionHa: 'Union of all after-images',
      maxHa: 'Largest area so far', classification: 'Classification', caveat: 'Seasonal caveat', vmdTitle: 'VMD compartments in the current mask (metadata)',
      vmdNote: 'Metadata from the VMD register; it does not change the classification, confidence or status.', vmdNone: 'No VMD compartment in the current mask.',
      vmdUnavailable: 'VMD data not available', kvNog: 'kv–comp.', zkat: 'zkat', haInMask: 'ha in mask', pCirg: 'felling year', pCirp: 'felling type',
      zkat10: 'forest stand (zkat 10)', zkat14: 'clear-cut land (zkat 14)', zkatOther: 'zkat {z}', status: 'Status', reviewLog: 'Review log',
      noReview: 'Not reviewed yet.', aCompare: 'Compare before/after', aField: 'Request field check', aRisk: 'Create risk', aReject: 'Reject', aUndo: 'Undo',
      cField: 'Send a field check request to the dispatcher (Telegram)?', cRisk: 'Create a risk for this suspected change?',
      cReject: 'Mark this suspected change as rejected (not a real change)?', cUndo: 'Undo the last review decision?',
      superseded: 'This event was superseded by #{id} (newer detection generation).', supersededNone: 'This event was superseded; no successor found.',
      openSuccessor: 'Open #{id}', suspectedLine: 'Suspected change — automated detection, not verified on the ground.',
      modeA: 'A Swipe', modeB: 'B Side by side', modeC: 'C After + change', modeD: 'D Change only', before: 'Before', after: 'After',
      pairMissing: 'No valid before/after pair', pairSame: 'Same acquisition selected', pairSensor: 'Only acquisitions of the same sensor can be compared',
      pairGeometry: 'S1 compares only acquisitions of the same orbit geometry (direction + relative orbit)', pairNoImage: 'No image for this acquisition',
      pairOrder: '“Before” must be earlier than “after”', compositeNote: 'True colour is not available for both images — false colour on both sides.',
      s1Label: 'Radar image — not a photograph (VH, −25…−5 dB)', falseNote: 'False colour (B11/B08/B04): healthy forest green, clear-cut magenta/brown.',
      trueNote: 'True colour (B04/B03/B02)', validPct: 'Valid %', product: 'Product', copy: 'Copy', copied: 'Copied',
      timeline: 'Acquisition timeline', days120: '120 d', allDays: 'All', s1Filter: 'S1 geometry', allGeom: 'all',
      stOk: 'Valid', stLow: 'Below validity threshold', stCloud: 'Clouds — skipped', stInvalid: 'No valid pixels / error', stPending: 'Pending',
      cloud: 'Clouds', analysis: 'Analysis', analysisNote: 'Area median. Event polygon curve — later.',
      technical: 'Technical data', thTime: 'Acquired', thSensor: 'Sensor', thStatus: 'Status', thValid: 'Valid %', thOutcome: 'Detection',
      acqCard: 'Acquisition', sensing: 'Acquired', platform: 'Platform', geometry: 'Orbit', metrics: 'Median in the area', showOnMap: 'Show on map',
      setBefore: 'Set as “before”', shiftHint: 'Click — show; Shift+click — “before”.', attribution: 'Contains modified Copernicus Sentinel data {year}',
      outcome: 'Detection outcome', o_NO_BASELINE: 'No baseline acquisition', o_NO_CHANGE: 'No change', o_SINGLE_DROP: 'Single radar drop — not an event',
      o_RADAR_ANOMALY: 'Radar anomaly (awaiting confirmation)', o_EVENT_UPDATED: 'Event updated', o_EVENT_CREATED: 'Event created', o_NOT_USABLE: 'Not usable',
      o_PENDING_CONFIRMATION: 'Awaiting confirmation', o_CANDIDATE_BELOW_MIN: 'Candidate below minimum area', o_UNIFORM_DROP_ATMOSPHERIC: 'Uniform drop (atmospheric)',
      s_SKIPPED_CLOUD: 'Clouds — skipped', s_NO_VALID_PIXELS: 'No valid pixels', s_OK: 'Processed', s_PENDING: 'Pending', s_ERROR: 'Error',
      dOK: 'Data OK', dNO_DATA_YET: 'No data yet', dBACKFILL_OR_FETCH_IN_PROGRESS: 'Fetching', dSTOPPED: 'Stopped', srcSECTOR: 'Sector',
      srcLVM_GEO: 'LVM GEO', srcEVAL_BBOX: 'Evaluation area', wIDLE: 'Idle', wRUNNING: 'Running', wNOT_INSTALLED: 'Not installed',
      wTIMERS_OFF: 'Timers off', wUNKNOWN: 'Status unknown', nextDaily: 'next daily run', open: 'Open', ha: 'ha', loading: 'Loading…',
      imgLoading: 'Loading image…', imgFailed: 'The image could not be loaded.'
    }
  };
  var CLS = {POTENTIAL_FOREST_LOSS: 'LOSS', POTENTIAL_CHANGE_OUTSIDE_BOUNDARY: 'OUT', POSSIBLE_SEASONAL_OR_ENVIRONMENTAL: 'SEAS', INSUFFICIENT_EVIDENCE: 'INS'};
  var GEOM_COLOURS = ['#4FA3D9', '#9B7BD8', '#3FB39A', '#D98C4F', '#C76C9A', '#8CA34F'];

  // ── state ──────────────────────────────────────────────────────────────────────────────────────────────────────
  function store(k, v) { try { if (v === undefined) return global.localStorage && global.localStorage.getItem(k); global.localStorage.setItem(k, v); } catch (e) { return null; } return null; }
  var S = {lang: store('satMonitoring.lang') === 'en' ? 'en' : 'lv', theme: store('satWorkspace.theme') === 'light' ? 'light' : 'dark',
           view: null, areaId: null, area: null, health: null, layer: null, events: [], byId: {}, sel: null, ev: null, acq: null,
           sensor: 'S2', composite: 'true', compare: null, mode: 'B', window: 120, s1geom: 'all', maps: [], charts: [], drawer: true,
           tech: false, panelLayers: true, seq: 0, rightOpen: false};
  function t(k, vars) {
    var s = (T[S.lang] && T[S.lang][k]) || T.en[k] || k;
    if (vars) Object.keys(vars).forEach(function (n) { s = s.split('{' + n + '}').join(vars[n]); });
    return s;
  }
  function esc(v) { return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function na() { return '<span class="satw-na">' + esc(t('na')) + '</span>'; }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function ha(v, d) { return isNum(v) ? v.toFixed(d === undefined ? 2 : d) + ' ha' : null; }
  function val(v) { return v === null || v === undefined || v === '' ? na() : '<span data-no-i18n>' + esc(v) + '</span>'; }
  function timeHtml(s) { var f = fmtTime(s); return f ? '<span class="satw-time" data-no-i18n>' + esc(f) + '</span>' : na(); }
  function root() { return document.getElementById('satm-root'); }
  function clsLabel(c) { return t('cls' + (CLS[c] || 'INS')); }
  function attribution(iso) { var y = iso ? String(iso).slice(0, 4) : String(new Date().getUTCFullYear()); return '<div class="satw-attr" data-no-i18n>' + esc(t('attribution', {year: y})) + '</div>'; }
  function badge(text, cls) { return '<span class="satw-badge ' + (cls || '') + '">' + esc(text) + '</span>'; }
  function qBadge(kind, v) {
    var c = {HIGH: 'g', GOOD: 'g', MEDIUM: 'a', LIMITED: 'a', LOW: 'r', POOR: 'r'}[v] || '';
    return '<span class="satw-q"><span class="satw-q-l">' + esc(t(kind)) + '</span>' + (v ? badge(t(v), c) : na()) + '</span>';
  }
  function dot(e) { var c = changeColour(e); return '<span class="satw-dot' + (c.dash ? ' dashed' : '') + '" style="--c:' + c.color + '"></span>'; }

  async function get(path) {
    var r = await fetch(API + path, {credentials: 'same-origin', cache: 'no-store'}), d = {};
    try { d = await r.json(); } catch (e) { d = {}; }
    if (!r.ok) { var err = new Error(d.error || ('HTTP ' + r.status)); err.status = r.status; err.body = d; throw err; }
    return d;
  }
  async function post(path, body) {
    var r = await fetch(API + path, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})}), d = {};
    try { d = await r.json(); } catch (e) { d = {}; }
    if (!r.ok) { var err = new Error(d.error || ('HTTP ' + r.status)); err.status = r.status; throw err; }
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
  function cleanup() {
    S.maps.forEach(function (m) { try { m.remove(); } catch (e) { /* gone */ } });
    S.charts.forEach(function (c) { try { c.destroy(); } catch (e) { /* gone */ } });
    S.maps = []; S.charts = []; S.map = null; S.map2 = null;
  }
  function pageHead() {
    var pt = document.getElementById('page-title'), pr = document.getElementById('page-refresh');
    if (pt) pt.textContent = t('title'); if (pr) pr.textContent = '↻ ' + t('refresh');
  }
  function shell(inner) {
    var r = root(); if (!r) return null;
    r.className = 'satw satw-' + S.theme; r.setAttribute('data-lang', S.lang); r.innerHTML = inner; return r;
  }
  function toolbarRight() {
    return '<span class="satw-tools"><button class="satw-btn satw-ghost" data-act="theme" title="' + esc(t('theme')) + '">' +
      (S.theme === 'dark' ? '☀ ' + esc(t('light')) : '☾ ' + esc(t('dark'))) + '</button>' +
      '<button class="satw-btn satw-ghost" data-act="lang" data-no-i18n>' + (S.lang === 'lv' ? 'EN' : 'LV') + '</button></span>';
  }
  function bindTools(rerender) {
    var r = root(); if (!r) return;
    r.querySelectorAll('[data-act=theme]').forEach(function (b) { b.onclick = function () { S.theme = S.theme === 'dark' ? 'light' : 'dark'; store('satWorkspace.theme', S.theme); r.className = 'satw satw-' + S.theme; b.innerHTML = S.theme === 'dark' ? '☀ ' + esc(t('light')) : '☾ ' + esc(t('dark')); }; });
    r.querySelectorAll('[data-act=lang]').forEach(function (b) { b.onclick = function () { S.lang = S.lang === 'lv' ? 'en' : 'lv'; store('satMonitoring.lang', S.lang); rerender(); }; });
  }
  function providerBanner(h) {
    var p = h && h.provider;
    if (!p || p.state === 'OK') return '';
    if (p.state === 'UNKNOWN') return '<div class="satw-banner info">' + esc(t('unknownProvider')) + '</div>';
    if (p.state === 'NOT_CONFIGURED') return '<div class="satw-banner warn">' + esc(t('notConfigured')) + ' ' + timeHtml(p.at_utc) + '</div>';
    return '<div class="satw-banner warn">' + esc(t('degraded')) + ': ' + timeHtml(p.at_utc) + ' <span data-no-i18n>' + esc((p.error || '').slice(0, 160)) + '</span></div>';
  }
  function errorView(e) {
    var msg = e && e.status === 503 ? t('dbUnavailable') : t('error') + ': ' + (e && e.message ? e.message : e);
    shell('<div class="satw-error"><div class="satw-error-card"><h2>' + esc(t('title')) + '</h2><p>' + esc(msg) + '</p></div></div>');
  }

  // ── OVERVIEW ───────────────────────────────────────────────────────────────────────────────────────────────────
  async function loadOverview() {
    var seq = ++S.seq; S.view = 'overview'; S.areaId = null; cleanup(); pageHead();
    shell('<div class="satw-loading">' + esc(t('loading')) + '</div>');
    var ov, h, layer;
    try { var r = await Promise.all([get('/overview'), get('/health'), get('/map-layer').catch(function () { return {features: []}; })]); ov = r[0]; h = r[1]; layer = r[2]; }
    catch (e) { if (seq === S.seq) errorView(e); return; }
    if (seq !== S.seq) return;
    S.health = h;
    var areas = ov.areas.filter(function (a) { return a.active; });
    var evByArea = {};
    (layer.features || []).forEach(function (f) { var p = f.properties || {}; if (p.kind === 'event') (evByArea[p.area_id] = evByArea[p.area_id] || {})[p.event_id] = p; });
    var totalHa = areas.reduce(function (s, a) { return s + (isNum(a.area_ha) ? a.area_ha : 0); }, 0);
    var awaiting = (ov.latest_events || []).filter(function (e) { return e.status === 'SUSPECTED'; }).length;
    var m = h.month || {}, w = (h.worker || {}).state;
    var sync = h.last_successful_sync;
    var html = '<div class="satw-overview"><div id="satw-ov-map" class="satw-map"></div>' +
      '<div class="satw-float satw-summary"><div class="satw-float-head"><b>' + esc(t('title')) + '</b>' + toolbarRight() + '</div>' + providerBanner(h) +
      '<div class="satw-kpis">' +
        kpi(t('areas'), areas.length) + kpi(t('monitoredHa'), ha(totalHa, 1)) +
        kpi(t('openEvents'), ov.kpis.open_suspected_events, ov.kpis.open_suspected_events ? 'amber' : '') + kpi(t('awaitingReview'), awaiting) + '</div>' +
      '<dl class="satw-dl"><dt>' + esc(t('lastSync')) + '</dt><dd>' + (sync ? timeHtml(sync.finished_at) : na()) + '</dd>' +
        '<dt>' + esc(t('usage')) + '</dt><dd data-no-i18n>' + (isNum(m.pu) ? m.pu.toFixed(1) : '—') + ' / ' + esc(m.pu_guard) + ' PU · ' + esc(m.requests) + ' / ' + esc(m.request_guard) + ' ' + esc(t('requests')) + ' (' + esc(t('guard')) + ')</dd>' +
        '<dt>' + esc(t('worker')) + '</dt><dd>' + badge(t('w' + (w || 'UNKNOWN')), w === 'IDLE' ? '' : w === 'RUNNING' ? 'a' : 'a') + workerNext(h) + '</dd></dl>' +
      '<div class="satw-actions"><button class="satw-btn" data-act="add-sector">' + esc(t('addSector')) + '</button><button class="satw-btn" data-act="fetch">' + esc(t('fetchNow')) + '</button></div>' +
      '<div id="satw-sectors"></div></div>';
    html += '<div class="satw-float satw-latest"><div class="satw-float-head"><b>' + esc(t('latest')) + '</b></div>' +
      ((ov.latest_events || []).length ? '<ul class="satw-list">' + ov.latest_events.map(function (e) {
        return '<li><a data-event="' + e.id + '" data-area="' + e.monitored_area_id + '">' + dot(e) + '<span><b data-no-i18n>#' + e.id + '</b> ' + esc(clsLabel(e.classification)) +
          '<br><small><span data-no-i18n>' + esc(e.area_name || '') + ' · ' + esc(ha(e.changed_area_ha) || '—') + ' · ' + esc(fmtDate(e.first_after_time_utc) || '—') + '</span></small></span></a></li>';
      }).join('') + '</ul>' : '<p class="satw-muted">' + esc(t('noEvents')) + '</p>') + '</div>';
    html += '<details class="satw-drawer satw-areas-drawer"' + (areas.length ? '' : ' open') + '><summary>' + esc(t('allAreas')) + ' (' + areas.length + ')</summary>' +
      (areas.length ? '<table class="satw-table"><thead><tr><th>' + esc(t('areas')) + '</th><th>' + esc(t('status')) + '</th><th>ha</th><th>' + esc(t('openEvents')) + '</th><th>' + esc(t('lastAcq')) + '</th><th></th></tr></thead><tbody>' +
        areas.map(function (a) {
          var c = worstColour(Object.values(evByArea[a.id] || {}));
          return '<tr><td>' + (c ? '<span class="satw-dot" style="--c:' + c.color + '"></span>' : '<span class="satw-dot empty"></span>') + '<span data-no-i18n>' + esc(a.name) + '</span> <small>' + esc(t('src' + a.source)) + '</small></td><td>' + esc(t('d' + a.data_status)) + '</td>' +
            '<td data-no-i18n>' + esc(isNum(a.area_ha) ? a.area_ha.toFixed(2) : '—') + '</td><td>' + esc(a.open_suspected_events) + '</td><td>' + (a.last_s1_utc || a.last_valid_s2_utc ? '<span data-no-i18n>' + esc(fmtDate([a.last_s1_utc, a.last_valid_s2_utc].filter(Boolean).sort().pop())) + '</span>' : na()) + '</td>' +
            '<td><button class="satw-btn satw-small" data-area="' + a.id + '">' + esc(t('open')) + '</button></td></tr>';
        }).join('') + '</tbody></table>' : '<div class="satw-empty"><b>' + esc(t('noAreas')) + '</b><p>' + esc(t('noAreasHint')) + '</p></div>') + '</details></div>';
    var r = shell(html); if (!r) return;
    bindTools(loadOverview);
    r.querySelectorAll('[data-area]').forEach(function (b) { b.onclick = function () { var ev = b.getAttribute('data-event'); openArea(+b.getAttribute('data-area'), ev ? +ev : null); }; });
    r.querySelector('[data-act=fetch]').onclick = async function () { if (!global.confirm(S.lang === 'lv' ? 'Ielādēt jaunos Sentinel-1/2 uzņēmumus visām teritorijām tagad?' : 'Fetch new Sentinel-1/2 observations for all areas now?')) return; try { await post('/fetch', {all: true}); loadOverview(); } catch (e) { global.alert(t('error') + ': ' + e.message); } };
    r.querySelector('[data-act=add-sector]').onclick = showSectors;
    var L = await leaflet(); if (seq !== S.seq) return;
    var map = L.map('satw-ov-map', {zoomControl: false}); S.maps.push(map); L.control.zoom({position: 'bottomright', zoomInTitle: S.lang === 'lv' ? 'Tuvināt' : 'Zoom in', zoomOutTitle: S.lang === 'lv' ? 'Tālināt' : 'Zoom out'}).addTo(map);
    L.tileLayer(OSM, {maxZoom: 19, attribution: '© OpenStreetMap contributors'}).addTo(map);
    var g = L.featureGroup().addTo(map);
    areas.forEach(function (a) {
      if (!a.geometry) return;
      var c = worstColour(Object.values(evByArea[a.id] || {}));
      L.geoJSON(a.geometry, {style: {color: c ? c.color : '#3E8E5E', weight: 2.5, fillOpacity: 0.18, fillColor: c ? c.color : '#3E8E5E'}})
        .bindTooltip(esc(a.name), {sticky: true}).on('click', function () { openArea(a.id); }).addTo(g);
    });
    if (g.getLayers().length) map.fitBounds(g.getBounds(), {padding: [60, 60], maxZoom: 13}); else map.setView([56.9, 24.6], 7);
  }
  function kpi(label, v, cls) { return '<div class="satw-kpi ' + (cls || '') + '"><span>' + esc(label) + '</span><b data-no-i18n>' + (v === null || v === undefined ? '—' : esc(v)) + '</b></div>'; }
  function workerNext(h) { var u = h.worker && h.worker.units && h.worker.units.sync; return u && u.next_run_utc ? ' <small>' + esc(t('nextDaily')) + ': ' + timeHtml(u.next_run_utc) + '</small>' : ''; }
  async function showSectors() {
    var box = document.getElementById('satw-sectors'); if (!box) return;
    if (box.innerHTML) { box.innerHTML = ''; return; }
    box.innerHTML = '<p class="satw-muted">' + esc(t('loading')) + '</p>';
    var d; try { d = await get('/sectors'); } catch (e) { box.innerHTML = '<p>' + esc(t('error') + ': ' + e.message) + '</p>'; return; }
    box.innerHTML = '<ul class="satw-list satw-sector-list">' + d.sectors.map(function (s) {
      return '<li><span data-no-i18n>' + esc(s.name) + '</span>' + (s.monitored_area_id ? badge(S.lang === 'lv' ? 'Uzraudzīts' : 'Monitored') :
        s.queued_job_id ? badge(S.lang === 'lv' ? 'Rindā' : 'Queued', 'a') : !s.has_polygon ? badge(S.lang === 'lv' ? 'Nav poligona' : 'No polygon', 'r') :
        '<button class="satw-btn satw-small" data-add="' + s.id + '" data-name="' + esc(s.name) + '">' + esc(S.lang === 'lv' ? 'Pievienot' : 'Add') + '</button>') + '</li>';
    }).join('') + '</ul>';
    box.querySelectorAll('[data-add]').forEach(function (b) {
      b.onclick = async function () {
        if (!global.confirm((S.lang === 'lv' ? 'Pievienot ' : 'Add ') + b.getAttribute('data-name') + (S.lang === 'lv' ? ' satelītu monitoringam? Vispirms tiks ielādētas pēdējās 120 dienas.' : ' to satellite monitoring? The last 120 days are fetched first.'))) return;
        try { await post('/areas', {source: 'SECTOR', source_ref: b.getAttribute('data-add')}); box.innerHTML = ''; showSectors(); } catch (e) { global.alert(t('error') + ': ' + e.message); }
      };
    });
  }

  // ── WORKSPACE ──────────────────────────────────────────────────────────────────────────────────────────────────
  async function openArea(id, eventId) {
    var seq = ++S.seq; S.view = 'area'; S.areaId = id; S.ev = null; S.sel = null; S.compare = null; S.acq = null; cleanup(); pageHead();
    shell('<div class="satw-loading">' + esc(t('loading')) + '</div>');
    var a, h, layer;
    try { var r = await Promise.all([get('/areas/' + id + '?geometry=0'), get('/health').catch(function () { return {}; }), get('/map-layer?area_id=' + id).catch(function () { return {features: []}; })]); a = r[0]; h = r[1]; layer = r[2]; }
    catch (e) { if (seq === S.seq) errorView(e); return; }
    if (seq !== S.seq) return;
    S.area = a; S.health = h; S.layer = layer; S.byId = {};
    a.timeline.forEach(function (x) { S.byId[x.acq_id] = x; });
    var order = function (e) { return (OPEN.indexOf(e.status) >= 0 ? 0 : 1); };
    S.events = a.events.slice().sort(function (x, y) { return order(x) - order(y) || changeColour(y).rank - changeColour(x).rank || (y.changed_area_ha || 0) - (x.changed_area_ha || 0); });
    S.acq = latestValid(S.sensor) || latestValid(S.sensor === 'S2' ? 'S1' : 'S2');
    if (S.acq) S.sensor = S.acq.sensor;
    renderWorkspace(seq);
    var L = await leaflet(); if (seq !== S.seq) return;
    buildMap(L);
    renderTimeline(); renderAnalysis(L);
    if (eventId) selectEvent(eventId, true);
  }
  function minValid() { return S.area && S.area.config ? S.area.config.min_valid_pct : null; }
  function latestValid(sensor) {
    var mv = minValid();
    return S.area.timeline.filter(function (x) { return x.sensor === sensor && x.quicklook_url && acqState(x, mv) === 'ok' && (sensor !== 'S1' || S.s1geom === 'all' || geomKey(x) === S.s1geom); })
      .sort(function (x, y) { return String(y.sensing_time_utc).localeCompare(String(x.sensing_time_utc)); })[0] || null;
  }
  function geomKey(a) { return (a.orbit_direction || '?').slice(0, 3) + ' ' + (a.relative_orbit === null || a.relative_orbit === undefined ? '?' : a.relative_orbit); }
  function lastAcqTimes() {
    var out = {};
    S.area.timeline.forEach(function (x) { if (x.status === 'OK' && (!out[x.sensor] || x.sensing_time_utc > out[x.sensor])) out[x.sensor] = x.sensing_time_utc; });
    return out;
  }
  function renderWorkspace() {
    var a = S.area.area, la = lastAcqTimes(), lastAny = [la.S1, la.S2].filter(Boolean).sort().pop();
    var catalog = ((S.health && S.health.provider_status) || []).filter(function (p) { return p.key === 'catalog'; })[0];
    var sysCheck = catalog && (catalog.last_ok_utc || catalog.last_error_utc) ? [catalog.last_ok_utc, catalog.last_error_utc].filter(Boolean).sort().pop() : null;
    var html = '<div class="satw-ws">' +
      '<header class="satw-top">' +
        '<a class="satw-back" data-act="back">' + esc(t('back')) + '</a>' +
        '<div class="satw-title"><b data-no-i18n>' + esc(a.name) + '</b> ' + badge(t('src' + a.source)) + ' <span data-no-i18n>' + esc(ha(a.area_ha) || '—') + '</span> ' +
          badge(t('d' + a.data_status), a.data_status === 'OK' ? 'g' : 'a') + '</div>' +
        '<div class="satw-times">' +
          '<span title="' + esc('S1: ' + (fmtTime(la.S1) || '—') + ' · S2: ' + (fmtTime(la.S2) || '—')) + '"><small>' + esc(t('lastAcq')) + '</small>' + timeHtml(lastAny) + '</span>' +
          '<span><small>' + esc(t('lastAnalysis')) + '</small>' + timeHtml(S.area.last_successful_analysis_utc) + '</span>' +
          '<span><small>' + esc(t('lastCheck')) + ' (' + esc(t('system')) + ')</small>' + timeHtml(sysCheck) + '</span></div>' +
        '<div class="satw-switches">' +
          seg('sensor', [['S2', t('optical')], ['S1', t('radar')]], S.sensor) +
          '<span id="satw-composite"></span>' +
          '<button class="satw-btn' + (S.compare ? ' on' : '') + '" data-act="compare">' + esc(t('compare')) + '</button>' +
          '<button class="satw-btn' + (S.panelLayers ? ' on' : '') + '" data-act="layers">' + esc(t('layers')) + '</button>' + toolbarRight() + '</div>' +
      '</header>' + providerBanner(S.health) +
      (a.data_status === 'NO_DATA_YET' ? '<div class="satw-banner info">' + esc(t('noDataYet')) + '</div>' : '') +
      (a.data_status === 'BACKFILL_OR_FETCH_IN_PROGRESS' ? '<div class="satw-banner warn">' + esc(t('backfill')) + '</div>' : '') +
      '<div class="satw-stage">' +
        '<div id="satw-maps" class="satw-maps"><div id="satw-map" class="satw-map"></div></div>' +
        '<aside class="satw-left">' + eventList() + layerPanel() + legendHtml() + '</aside>' +
        '<aside id="satw-right" class="satw-right" hidden></aside>' +
        '<div id="satw-compare-bar" class="satw-compare-bar" hidden></div>' +
      '</div>' +
      '<details class="satw-drawer satw-analysis"' + (S.drawer ? ' open' : '') + '><summary>' + esc(t('analysis')) + '</summary><div id="satw-analysis-body"></div></details>' +
      '<section class="satw-timeline"><div class="satw-tl-head"><b>' + esc(t('timeline')) + '</b> <small>' + esc(t('shiftHint')) + '</small>' +
        '<span class="satw-tl-tools">' + seg('window', [['120', t('days120')], ['all', t('allDays')]], String(S.window)) +
        '<label>' + esc(t('s1Filter')) + ' <select id="satw-s1geom"><option value="all">' + esc(t('allGeom')) + '</option>' + geomOptions() + '</select></label></span></div>' +
        '<div id="satw-tl" class="satw-tl"></div><div id="satw-tip" class="satw-tip" hidden></div></section>' +
      '<details class="satw-drawer satw-tech"' + (S.tech ? ' open' : '') + '><summary>' + esc(t('technical')) + '</summary><div id="satw-tech-body"></div></details>' +
      '</div>';
    var r = shell(html); if (!r) return;
    bindTools(function () { openArea(S.areaId, S.sel); });
    r.querySelector('[data-act=back]').onclick = function () { history.pushState({type: 'nav', id: 'sat-monitoring'}, '', '#sat-monitoring'); loadOverview(); };
    r.querySelectorAll('[data-seg=sensor] button').forEach(function (b) { b.onclick = function () { S.sensor = b.getAttribute('data-v'); var x = latestValid(S.sensor); if (x) showAcq(x); syncSeg('sensor', S.sensor); }; });
    r.querySelectorAll('[data-seg=window] button').forEach(function (b) { b.onclick = function () { S.window = b.getAttribute('data-v') === 'all' ? 'all' : 120; syncSeg('window', String(S.window)); renderTimeline(); }; });
    var sel = r.querySelector('#satw-s1geom'); sel.value = S.s1geom; sel.onchange = function () { S.s1geom = sel.value; renderTimeline(); if (S.analysisL) renderAnalysis(S.analysisL); };
    r.querySelector('[data-act=compare]').onclick = function () { toggleCompare(); };
    r.querySelector('[data-act=layers]').onclick = function () { S.panelLayers = !S.panelLayers; r.querySelector('.satw-layers').hidden = !S.panelLayers; this.classList.toggle('on', S.panelLayers); };
    r.querySelectorAll('[data-ev]').forEach(function (li) { li.onclick = function () { selectEvent(+li.getAttribute('data-ev')); }; });
    r.querySelectorAll('.satw-layers input').forEach(function (c) { c.onchange = function () { setLayer(c.getAttribute('data-layer'), c.checked); }; });
    r.querySelector('.satw-analysis').addEventListener('toggle', function (e) { S.drawer = e.target.open; });
    r.querySelector('.satw-tech').addEventListener('toggle', function (e) { S.tech = e.target.open; if (S.tech) renderTech(); });
    renderComposite(); if (S.tech) renderTech();
  }
  function seg(name, opts, cur) {
    return '<span class="satw-seg" data-seg="' + name + '">' + opts.map(function (o) { return '<button class="' + (o[0] === cur ? 'on' : '') + '" data-v="' + o[0] + '">' + esc(o[1]) + '</button>'; }).join('') + '</span>';
  }
  function syncSeg(name, cur) { document.querySelectorAll('[data-seg=' + name + '] button').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-v') === cur); }); }
  function geomOptions() {
    var seen = {};
    S.area.timeline.forEach(function (x) { if (x.sensor === 'S1') seen[geomKey(x)] = 1; });
    return Object.keys(seen).sort().map(function (k) { return '<option value="' + esc(k) + '" data-no-i18n>' + esc(k) + '</option>'; }).join('');
  }
  function geomColour(a) {
    var keys = []; S.area.timeline.forEach(function (x) { if (x.sensor === 'S1' && keys.indexOf(geomKey(x)) < 0) keys.push(geomKey(x)); });
    keys.sort(); return GEOM_COLOURS[keys.indexOf(geomKey(a)) % GEOM_COLOURS.length];
  }
  function eventList() {
    if (!S.events.length) return '<div class="satw-panel"><b>' + esc(t('events')) + '</b><div class="satw-empty"><b>' + esc(t('noEvents')) + '</b><p>' + esc(t('noEventsHint')) + '</p></div></div>';
    return '<div class="satw-panel"><b>' + esc(t('events')) + ' (' + S.events.length + ')</b><ul class="satw-evlist">' + S.events.map(function (e) {
      return '<li data-ev="' + e.id + '" class="' + (S.sel === e.id ? 'sel' : '') + '">' + dot(e) + '<div><div><b data-no-i18n>#' + e.id + '</b> ' + esc(clsLabel(e.classification)) + '</div>' +
        '<small><span data-no-i18n>' + esc(ha(e.changed_area_ha_inside) || '—') + '</span> ' + esc(t('inside')) + ' · <span data-no-i18n>' + esc(ha(e.changed_area_ha_buffer) || '—') + '</span> ' + esc(t('outside')) +
        ' · ' + esc(t('onset')) + ' <span data-no-i18n>' + esc(fmtDate(e.first_after_time_utc) || '—') + '</span></small>' +
        '<div class="satw-evq">' + qBadge('confidence', e.confidence) + qBadge('evidence', e.evidence_quality) + '</div></div></li>';
    }).join('') + '</ul></div>';
  }
  var LAYERS = [['image', 'lImage', true], ['change', 'lChange', true], ['boundary', 'lBoundary', true], ['buffer', 'lBuffer', true],
                ['footprint', 'lFootprint', false], ['vmd', 'lVmd', true], ['base', 'lBase', true]];
  function layerPanel() {
    return '<div class="satw-panel satw-layers"' + (S.panelLayers ? '' : ' hidden') + '><b>' + esc(t('layers')) + '</b>' + LAYERS.map(function (l) {
      return '<label><input type="checkbox" data-layer="' + l[0] + '"' + (layerOn(l[0]) ? ' checked' : '') + '> ' + esc(t(l[1])) + '</label>';
    }).join('') + '</div>';
  }
  S.layersOn = {};
  function layerOn(k) { if (!(k in S.layersOn)) S.layersOn[k] = LAYERS.filter(function (l) { return l[0] === k; })[0][2]; return S.layersOn[k]; }
  function legendHtml() {
    return '<div class="satw-panel satw-legend">' + CHANGE_COLOURS.map(function (c) {
      return '<div><span class="satw-dot' + (c.dash ? ' dashed' : '') + '" style="--c:' + c.color + '"></span>' + esc(t(c.legend)) + '</div>';
    }).join('') + '<div><span class="satw-hatch"></span>' + esc(t('hatch')) + '</div></div>';
  }
  function renderComposite() {
    var box = document.getElementById('satw-composite'); if (!box) return;
    var a = S.acq;
    if (!a) { box.innerHTML = ''; return; }
    if (a.sensor === 'S1') { box.innerHTML = '<span class="satw-note" data-no-i18n>' + esc(t('s1Label')) + '</span>'; return; }
    var tc = !!a.truecolor_url, cur = S.composite === 'true' && tc ? 'true' : 'false';
    box.innerHTML = '<span class="satw-seg" data-seg="composite"><button data-v="true" class="' + (cur === 'true' ? 'on' : '') + '"' + (tc ? '' : ' disabled title="' + esc(t('compositeNote')) + '"') + '>' + esc(t('trueC')) + '</button>' +
      '<button data-v="false" class="' + (cur === 'false' ? 'on' : '') + '">' + esc(t('falseC')) + '</button></span>';
    box.querySelectorAll('button').forEach(function (b) { b.onclick = function () { S.composite = b.getAttribute('data-v'); renderComposite(); drawImage(); }; });
  }

  // ── map ───────────────────────────────────────────────────────────────────────────────────────────────────────
  function buildMap(L) {
    var map = L.map('satw-map', {zoomControl: false, zoomSnap: 0.25, preferCanvas: false}); S.maps.push(map); S.map = map; S.L = L;
    L.control.zoom({position: 'bottomright', zoomInTitle: S.lang === 'lv' ? 'Tuvināt' : 'Zoom in', zoomOutTitle: S.lang === 'lv' ? 'Tālināt' : 'Zoom out'}).addTo(map);
    L.control.scale({imperial: false, position: 'bottomleft'}).addTo(map);
    [['satwImg', 300], ['satwVmd', 360], ['satwBoundary', 420], ['satwChange', 440], ['satwCallout', 650]].forEach(function (p) { map.createPane(p[0]).style.zIndex = p[1]; });
    map.getPane('satwImg').style.pointerEvents = 'none';
    S.base = L.tileLayer(OSM, {maxZoom: 19, attribution: '© OpenStreetMap contributors'});
    if (layerOn('base')) S.base.addTo(map);
    var bb = S.area.area.grid_bbox, bounds = bb ? [[bb[1], bb[0]], [bb[3], bb[2]]] : null;
    S.groups = {boundary: L.layerGroup(), buffer: L.layerGroup(), footprint: L.layerGroup(), change: L.layerGroup(), image: L.layerGroup()};
    if (S.area.geometry) L.geoJSON(S.area.geometry, {pane: 'satwBoundary', style: {color: '#F5F5F0', weight: 2.5, fill: false, opacity: 0.95}}).addTo(S.groups.boundary);
    if (S.area.buffer_ring) L.geoJSON(S.area.buffer_ring, {pane: 'satwBoundary', style: {color: '#9FC3E7', weight: 1.2, dashArray: '5 4', fill: false}}).addTo(S.groups.buffer);
    if (bounds) L.rectangle(bounds, {pane: 'satwBoundary', color: '#C8C8C8', weight: 1, dashArray: '2 4', fill: false}).addTo(S.groups.footprint);
    drawChange(L);
    S.vmd = vmdLayer(L);
    ['boundary', 'buffer', 'footprint', 'change', 'image'].forEach(function (k) { if (layerOn(k)) S.groups[k].addTo(map); });
    if (layerOn('vmd')) S.vmd.addTo(map);
    if (bounds) map.fitBounds(bounds, {padding: [20, 20]}); else map.setView([56.9, 24.6], 7);
    drawImage();
  }
  function setLayer(k, on) {
    S.layersOn[k] = on; var m = S.map; if (!m) return;
    var l = k === 'vmd' ? S.vmd : k === 'base' ? S.base : S.groups[k];
    if (!l) return;
    if (on) l.addTo(m); else m.removeLayer(l);
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
  function drawChange(L) {
    S.groups.change.clearLayers(); S.polys = {};
    var feats = (S.layer && S.layer.features || []).filter(function (f) { return f.properties && f.properties.kind === 'event'; });
    feats.forEach(function (f) {
      var p = f.properties, c = changeColour(p), outside = p.zone === 'BUFFER';
      var lyr = L.geoJSON(f, {pane: 'satwChange', style: {color: c.color, weight: 2, dashArray: c.dash, fillColor: c.color, fillOpacity: outside ? 0.9 : 0.32}});
      lyr.on('add', function () { if (outside) lyr.eachLayer(function (x) { if (x._path) x._path.setAttribute('fill', hatchFill(x._path.ownerSVGElement, c.color)); }); });
      lyr.on('click', function () { selectEvent(p.event_id); });
      lyr.bindTooltip('#' + p.event_id + ' · ' + clsLabel(p.classification) + ' · ' + (ha(p.zone_ha) || '—') + ' ' + (outside ? t('outside') : t('inside')), {sticky: true});
      lyr.addTo(S.groups.change); (S.polys[p.event_id] = S.polys[p.event_id] || []).push(lyr);
    });
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
    if (!d || !d.features || !S.map) return;
    var hl = S.vmdHighlight || {}, n = Math.pow(2, coords.z), dark = S.theme === 'dark';
    function px(lon, lat) {
      var x = (lon + 180) / 360 * n * 256 - coords.x * 256;
      var s = Math.sin(lat * Math.PI / 180), y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n * 256 - coords.y * 256;
      return [x, y];
    }
    d.features.forEach(function (f) {
      var p = f.properties || {}, g = f.geometry; if (!g) return;
      var polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
      var on = hl[p.id];
      ctx.beginPath();
      polys.forEach(function (poly) { poly.forEach(function (ring) { ring.forEach(function (c, i) { var q = px(c[0], c[1]); if (i) ctx.lineTo(q[0], q[1]); else ctx.moveTo(q[0], q[1]); }); ctx.closePath(); }); });
      ctx.lineWidth = on ? 3 : 1; ctx.strokeStyle = on ? '#F2C14E' : (dark ? 'rgba(116,196,132,.85)' : 'rgba(30,107,52,.9)'); ctx.stroke();
      if (coords.z >= 15 && polys[0] && polys[0][0]) {
        var r0 = polys[0][0], sx = 0, sy = 0; r0.forEach(function (c) { var q = px(c[0], c[1]); sx += q[0]; sy += q[1]; });
        var cx = sx / r0.length, cy = sy / r0.length;
        if (cx > 4 && cx < 252 && cy > 4 && cy < 252) { ctx.font = (on ? 'bold ' : '') + '11px Inter, system-ui, sans-serif'; ctx.fillStyle = on ? '#F2C14E' : (dark ? '#D9EBDD' : '#1E3A2A'); ctx.textAlign = 'center'; ctx.fillText((p.kvart || '?') + '-' + (p.nog || '?'), cx, cy); }
      }
    });
  }
  function redrawVmd() {
    if (!S.vmd || !S.vmd._tiles) return;
    Object.keys(S.vmd._tiles).forEach(function (k) { var tl = S.vmd._tiles[k]; if (tl.el && tl.el._satwData) drawVmdTile(tl.el, tl.el._satwData, tl.coords); });
  }
  function imgStatus(div, overlay) {
    if (!div) return overlay;
    var st = document.createElement('div'); st.className = 'satw-img-status'; st.textContent = t('imgLoading'); div.appendChild(st);
    overlay.on('load', function () { st.remove(); div.setAttribute('data-img', 'loaded'); });
    overlay.on('error', function () { st.textContent = t('imgFailed'); st.classList.add('failed'); div.setAttribute('data-img', 'failed'); });
    return overlay;
  }
  function drawImage() {
    var L = S.L, m = S.map; if (!L || !m || S.compare) return;
    S.groups.image.clearLayers();
    var a = S.acq, bb = S.area.area.grid_bbox;
    var lab = document.getElementById('satw-img-label');
    if (lab) lab.remove();
    if (!a || !bb || !a.quicklook_url) return;
    var comp = a.sensor === 'S1' ? 's1' : (S.composite === 'true' && a.truecolor_url ? 'true' : 'false');
    imgStatus(document.getElementById('satw-map'), L.imageOverlay(imageUrl(a, comp), [[bb[1], bb[0]], [bb[3], bb[2]]], {pane: 'satwImg', opacity: 1})).addTo(S.groups.image);
    var box = document.createElement('div'); box.id = 'satw-img-label'; box.className = 'satw-img-label';
    box.innerHTML = acqLabel(a, comp); document.getElementById('satw-map').appendChild(box);
    renderTimeline();
  }
  function acqLabel(a, comp) {
    return '<b data-no-i18n>' + esc(fmtTime(a.sensing_time_utc) || '—') + '</b><br><span data-no-i18n>' + esc(a.sensor + ' · ' + (a.platform || '') + (a.sensor === 'S1' ? ' · ' + geomKey(a) : '')) + '</span> · ' +
      esc(t('validPct')) + ' <span data-no-i18n>' + (isNum(a.valid_pct_inside) ? a.valid_pct_inside.toFixed(1) : '—') + '</span><br><span>' +
      esc(comp === 's1' ? t('s1Label') : comp === 'true' ? t('trueNote') : t('falseNote')) + '</span>' + attribution(a.sensing_time_utc);
  }
  function showAcq(a) { S.acq = a; S.sensor = a.sensor; syncSeg('sensor', S.sensor); renderComposite(); drawImage(); if (!S.sel) openAcqPanel(a); }

  // ── event selection + right panel ──────────────────────────────────────────────────────────────────────────────
  async function selectEvent(id, fromDeepLink) {
    S.sel = id; var seq = S.seq;
    document.querySelectorAll('.satw-evlist li').forEach(function (li) { li.classList.toggle('sel', +li.getAttribute('data-ev') === id); });
    var right = document.getElementById('satw-right'); if (right) { right.hidden = false; right.innerHTML = '<div class="satw-loading">' + esc(t('loading')) + '</div>'; }
    var ev; try { ev = await get('/events/' + id); } catch (e) { if (right) right.innerHTML = '<p>' + esc(t('error') + ': ' + e.message) + '</p>'; return; }
    if (seq !== S.seq || S.sel !== id) return;
    S.ev = ev;
    if (ev.monitored_area_id !== S.areaId) { openArea(ev.monitored_area_id, id); return; }
    S.vmdHighlight = {}; (ev.compartments || []).forEach(function (c) { S.vmdHighlight[c.external_id] = 1; }); redrawVmd();
    highlight(id); callout(ev);
    var pair = defaultPair(ev, S.byId, minValid());
    S.pairDefault = pair;
    if (pair.after) { S.acq = pair.after; S.sensor = pair.after.sensor; syncSeg('sensor', S.sensor); renderComposite(); drawImage(); }
    renderEventPanel(ev);
    var polys = S.polys[id] || [];
    if (polys.length && S.map) { var b = S.L.latLngBounds([]); polys.forEach(function (p) { b.extend(p.getBounds()); }); S.map.fitBounds(b.pad(0.6), {maxZoom: 16}); }
    if (fromDeepLink === true && S.compare === null && global.SAT_WS_COMPARE_ON_DEEPLINK) toggleCompare(true);
  }
  function highlight(id) {
    Object.keys(S.polys || {}).forEach(function (k) { S.polys[k].forEach(function (l) { l.setStyle({weight: +k === id ? 4 : 2, opacity: +k === id || !id ? 1 : 0.55}); }); });
  }
  function callout(ev) {
    if (S.calloutLayer) S.map.removeLayer(S.calloutLayer);
    var polys = S.polys[ev.id] || []; if (!polys.length) return;
    var b = S.L.latLngBounds([]); polys.forEach(function (p) { b.extend(p.getBounds()); });
    var before = lastClearBefore(ev);
    var html = '<b data-no-i18n>' + esc(ha(ev.changed_area_ha) || '—') + '</b> · ' + esc(t('short' + (CLS[ev.classification] || 'INS'))) + ' · <span data-no-i18n>' +
      esc((fmtDate(before && before.sensing_time_utc) || '?') + ' → ' + (fmtDate(ev.first_after_time_utc) || '?')) + '</span> · ' + esc(t(ev.confidence || 'na'));
    S.calloutLayer = S.L.tooltip({permanent: true, direction: 'top', className: 'satw-callout', pane: 'satwCallout', offset: [0, -6]}).setLatLng([b.getNorth(), b.getCenter().lng]).setContent(html).addTo(S.map);
  }
  function lastClearBefore(ev) {
    var mv = minValid(), list = (ev.before || []).map(function (x) { return S.byId[x.acq_id] || x; }).filter(function (x) { return acqState(x, mv) === 'ok'; });
    return list.sort(function (x, y) { return String(y.sensing_time_utc).localeCompare(String(x.sensing_time_utc)); })[0] || null;
  }
  function zkatLabel(z) { return String(z) === '10' ? t('zkat10') : String(z) === '14' ? t('zkat14') : t('zkatOther', {z: z === null || z === undefined ? '?' : z}); }
  function storyHtml(ev) {
    var before = lastClearBefore(ev), cls = clsLabel(ev.classification).toLowerCase();
    var s = t('storyTpl', {before: fmtDate(before && before.sensing_time_utc) || t('storyNoBefore'), after: fmtDate(ev.first_after_time_utc) || t('na'),
      ha: ha(ev.changed_area_ha) || t('na'), cls: cls});
    var split = ev.compartment_split || {}, parts = [['zkat14', split.clearcut_zkat14_ha], ['zkat10', split.stand_zkat10_ha], ['other', split.other_compartments_ha]].filter(function (p) { return isNum(p[1]); });
    parts.sort(function (x, y) { return y[1] - x[1]; });
    var vmd = '';
    if (parts.length && parts[0][1] > 0) vmd = t('storyVmd', {ha: ha(parts[0][1]), zkat: parts[0][0] === 'other' ? (S.lang === 'lv' ? 'citi nogabali' : 'other compartments') : t(parts[0][0])});
    return '<div class="satw-story"><b>' + esc(t('story')) + '</b><p>' + esc(s) + '</p>' + (vmd ? '<p>' + esc(vmd) + '</p>' : '') +
      (parts.length && parts[0][0] === 'zkat14' ? '<p class="satw-muted">' + esc(t('zkat14Note')) + '</p>' : '') + '</div>';
  }
  function trServer(s) { var sm = global.SatMonitoring && (global.SatMonitoring._legacy || global.SatMonitoring); return sm && sm._trServer && S.lang === 'lv' ? sm._trServer(s) : s; }
  function renderEventPanel(ev) {
    var right = document.getElementById('satw-right'); if (!right) return;
    var c = changeColour(ev), before = lastClearBefore(ev);
    var after = (ev.after || []).map(function (x) { return S.byId[x.acq_id] || x; });
    var first = after.slice().sort(function (x, y) { return String(x.sensing_time_utc).localeCompare(String(y.sensing_time_utc)); })[0];
    var latest = after.slice().sort(function (x, y) { return String(y.sensing_time_utc).localeCompare(String(x.sensing_time_utc)); })[0];
    var sup = ev.current === false ? '<div class="satw-banner warn">' + (ev.successor ? esc(t('superseded', {id: ev.successor.event_id})) + ' <a data-goto="' + ev.successor.event_id + '">' + esc(t('openSuccessor', {id: ev.successor.event_id})) + '</a>' : esc(t('supersededNone'))) + '</div>' : '';
    var comps = ev.compartments || [], cst = ev.compartments_status || {};
    var html = '<div class="satw-rp-head"><span class="satw-dot big' + (c.dash ? ' dashed' : '') + '" style="--c:' + c.color + '"></span><div><b data-no-i18n>#' + ev.id + '</b> ' + badge(t('s' + ev.status)) +
      '<div class="satw-muted">' + esc(clsLabel(ev.classification)) + '</div></div><button class="satw-x" data-act="close" aria-label="×">×</button></div>' + sup + storyHtml(ev) +
      '<section class="satw-block raw"><h4>' + esc(t('observation')) + '</h4><dl class="satw-dl">' +
        '<dt>' + esc(t('lastClear')) + '</dt><dd>' + (before ? timeHtml(before.sensing_time_utc) + ' <small data-no-i18n>' + esc(before.sensor + ' · ' + (before.platform || '')) + '</small>' : na()) + '</dd>' +
        '<dt>' + esc(t('firstChange')) + '</dt><dd>' + (first ? timeHtml(first.sensing_time_utc) + ' <small data-no-i18n>' + esc(first.sensor + ' · ' + (first.platform || '')) + '</small>' : timeHtml(ev.first_after_time_utc)) + '</dd>' +
        '<dt>' + esc(t('latestAfter')) + '</dt><dd>' + (latest ? timeHtml(latest.sensing_time_utc) : timeHtml(ev.last_after_time_utc)) + '</dd></dl>' + attribution(ev.first_after_time_utc) + '</section>' +
      '<section class="satw-block proc"><h4>' + esc(t('measurement')) + '</h4><dl class="satw-dl">' +
        dd('curHa', ha(ev.changed_area_ha)) + dd('insideHa', ha(ev.changed_area_ha_inside)) + dd('outsideHa', ha(ev.changed_area_ha_buffer)) +
        dd('share', isNum(ev.pct_of_area_affected) ? ev.pct_of_area_affected.toFixed(1) + ' %' : null) + dd('cluster', ha(ev.largest_cluster_ha)) +
        dd('maxDist', isNum(ev.max_distance_outside_boundary_m) ? Math.round(ev.max_distance_outside_boundary_m) + ' m' : null) + dd('unionHa', ha(ev.union_area_ha)) + dd('maxHa', ha(ev.max_area_ha)) +
        '<dt>' + esc(t('detected')) + '</dt><dd>' + timeHtml(ev.detected_at_utc) + '</dd></dl></section>' +
      '<section class="satw-block interp"><h4>' + esc(t('interpretation')) + '</h4><p>' + esc(t('suspectedLine')) + '</p>' +
        '<div class="satw-evq">' + qBadge('confidence', ev.confidence) + qBadge('evidence', ev.evidence_quality) + '</div>' +
        (ev.seasonal_caveat ? '<p><b>' + esc(t('caveat')) + ':</b> <span data-no-i18n title="' + esc(ev.seasonal_caveat) + '">' + esc(trServer(ev.seasonal_caveat)) + '</span></p>' : '') +
        '<h5>' + esc(t('vmdTitle')) + '</h5>' + (cst.available === false ? '<p>' + na() + ' <small data-no-i18n>' + esc(cst.reason || '') + '</small></p>' : comps.length ?
          '<table class="satw-table satw-small"><thead><tr><th>' + esc(t('kvNog')) + '</th><th>' + esc(t('zkat')) + '</th><th>' + esc(t('haInMask')) + '</th><th>' + esc(t('pCirg')) + '</th><th>' + esc(t('pCirp')) + '</th></tr></thead><tbody>' +
          comps.slice(0, 12).map(function (cp) {
            return '<tr><td data-no-i18n title="' + esc(cp.external_id) + '">' + esc((cp.kvart || '?') + '-' + (cp.nog || '?')) + '</td><td>' + esc(zkatLabel(cp.zkat)) + '</td><td data-no-i18n>' + esc(cp.ha_in_mask.toFixed(2)) + '</td>' +
              '<td>' + (vmdValue(cp.p_cirg) ? '<span data-no-i18n>' + esc(vmdValue(cp.p_cirg)) + '</span>' : '<span class="satw-na">' + esc(t('notStated')) + '</span>') + '</td>' +
              '<td>' + (vmdValue(cp.p_cirp) ? '<span data-no-i18n>' + esc(vmdValue(cp.p_cirp)) + '</span>' : '<span class="satw-na">' + esc(t('notStated')) + '</span>') + '</td></tr>';
          }).join('') + (comps.length > 12 ? '<tr><td colspan="5" class="satw-muted" data-no-i18n>+' + (comps.length - 12) + '</td></tr>' : '') + '</tbody></table>' +
          '<p class="satw-muted">' + esc(t('vmdNote')) + ' <span data-no-i18n>' + esc((cst.dataset_version || '').slice(0, 12)) + '</span></p>' : '<p class="satw-muted">' + esc(t('vmdNone')) + '</p>') + '</section>' +
      '<section class="satw-block human"><h4>' + esc(t('decision')) + '</h4><dl class="satw-dl"><dt>' + esc(t('status')) + '</dt><dd>' + badge(t('s' + ev.status)) + '</dd></dl>' +
        '<h5>' + esc(t('reviewLog')) + '</h5>' + ((ev.review_log || []).length ? '<ul class="satw-log">' + ev.review_log.map(function (r) {
          return '<li><span data-no-i18n>' + esc(fmtTime(r.created_at_utc) || '') + ' · ' + esc(r.action) + ' · ' + esc(r.actor) + (r.note ? ' · ' + esc(r.note) : '') + '</span></li>';
        }).join('') + '</ul>' : '<p class="satw-muted">' + esc(t('noReview')) + '</p>') +
        '<div class="satw-actions">' +
          '<button class="satw-btn primary" data-act="cmp">' + esc(t('aCompare')) + '</button>' +
          (ev.current !== false ? '<button class="satw-btn" data-rv="FIELD_CHECK">' + esc(t('aField')) + '</button>' +
            (ev.risk_id ? '' : '<button class="satw-btn" data-rv="CREATE_RISK">' + esc(t('aRisk')) + '</button>') +
            '<button class="satw-btn" data-rv="REJECT">' + esc(t('aReject')) + '</button>' +
            (ev.undo_available ? '<button class="satw-btn" data-rv="UNDO">' + esc(t('aUndo')) + '</button>' : '') : '') +
        '</div></section>';
    right.innerHTML = html; right.hidden = false; right.setAttribute('data-kind', 'event');
    right.querySelector('[data-act=close]').onclick = function () { right.hidden = true; S.sel = null; S.ev = null; highlight(null); if (S.calloutLayer) S.map.removeLayer(S.calloutLayer); S.vmdHighlight = {}; redrawVmd(); document.querySelectorAll('.satw-evlist li').forEach(function (li) { li.classList.remove('sel'); }); };
    right.querySelector('[data-act=cmp]').onclick = function () { toggleCompare(true); };
    right.querySelectorAll('[data-goto]').forEach(function (a) { a.onclick = function () { location.hash = 'sat-monitoring?event=' + a.getAttribute('data-goto'); }; });
    right.querySelectorAll('[data-rv]').forEach(function (b) {
      b.onclick = async function () {
        var d = b.getAttribute('data-rv'), q = {FIELD_CHECK: 'cField', CREATE_RISK: 'cRisk', REJECT: 'cReject', UNDO: 'cUndo'}[d];
        if (!global.confirm(t(q))) return;
        b.disabled = true;
        try { await post('/events/' + ev.id + '/review', {decision: d}); var id = ev.id; await openArea(S.areaId, id); }
        catch (e) { b.disabled = false; global.alert(t('error') + ': ' + e.message); }
      };
    });
  }
  function dd(k, v) { return '<dt>' + esc(t(k)) + '</dt><dd>' + (v === null || v === undefined ? na() : '<span data-no-i18n>' + esc(v) + '</span>') + '</dd>'; }
  function openAcqPanel(a) {
    var right = document.getElementById('satw-right'); if (!right || S.sel) return;
    var m = a.metrics_inside || {}, keys = a.sensor === 'S2' ? ['NDVI', 'NBR', 'NDMI'] : ['VV_DB', 'VH_DB'];
    var outcome = a.detection ? (T[S.lang]['o_' + a.detection] || a.detection) : null;
    right.innerHTML = '<div class="satw-rp-head"><div><b>' + esc(t('acqCard')) + '</b> <span data-no-i18n>#' + a.acq_id + '</span></div><button class="satw-x" data-act="close">×</button></div>' +
      '<section class="satw-block raw"><dl class="satw-dl"><dt>' + esc(t('sensing')) + '</dt><dd>' + timeHtml(a.sensing_time_utc) + '</dd>' +
        dd('platform', a.sensor + ' · ' + (a.platform || '—')) + (a.sensor === 'S1' ? dd('geometry', geomKey(a)) : dd('cloud', isNum(a.scene_cloud_pct) ? a.scene_cloud_pct.toFixed(1) + ' %' : null)) +
        dd('validPct', isNum(a.valid_pct_inside) ? a.valid_pct_inside.toFixed(1) + ' %' : null) +
        '<dt>' + esc(t('thStatus')) + '</dt><dd title="' + esc(a.status) + '">' + esc(T[S.lang]['s_' + a.status] || a.status) + '</dd>' +
        '<dt>' + esc(t('product')) + '</dt><dd><code data-no-i18n>' + esc(a.product_id) + '</code> <button class="satw-btn satw-small" data-act="copy">' + esc(t('copy')) + '</button></dd></dl>' + attribution(a.sensing_time_utc) + '</section>' +
      '<section class="satw-block proc"><h4>' + esc(t('metrics')) + '</h4><dl class="satw-dl">' + keys.map(function (k) {
        var x = m[k]; return dd(k.replace('_DB', ' dB'), x && isNum(x.median) ? x.median.toFixed(3) : null);
      }).join('') + '<dt>' + esc(t('outcome')) + '</dt><dd title="' + esc(a.detection || '') + '">' + (outcome ? esc(outcome) : na()) + '</dd></dl></section>' +
      '<div class="satw-actions"><button class="satw-btn" data-act="before">' + esc(t('setBefore')) + '</button></div>';
    right.hidden = false; right.setAttribute('data-kind', 'acq');
    right.querySelector('[data-act=close]').onclick = function () { right.hidden = true; };
    right.querySelector('[data-act=copy]').onclick = function () { try { navigator.clipboard.writeText(a.product_id); this.textContent = t('copied'); } catch (e) { /* no clipboard */ } };
    right.querySelector('[data-act=before]').onclick = function () { setCompareBefore(a); };
  }

  // ── compare (A swipe · B side by side (default) · C after + change · D change only) ───────────────────────────
  function toggleCompare(force) {
    var on = force === true ? true : !S.compare;
    var btn = document.querySelector('[data-act=compare]'); if (btn) btn.classList.toggle('on', on);
    if (!on) { S.compare = null; teardownCompare(); drawImage(); return; }
    var pair = S.ev ? defaultPair(S.ev, S.byId, minValid()) : {before: null, after: S.acq};
    if (!pair.before && S.acq) {          // no event: latest valid before the shown acquisition, same sensor/geometry
      pair.after = S.acq;
      pair.before = S.area.timeline.filter(function (x) { return comparePair(x, S.acq).ok && acqState(x, minValid()) === 'ok'; })
        .sort(function (x, y) { return String(y.sensing_time_utc).localeCompare(String(x.sensing_time_utc)); })[0] || null;
    }
    S.compare = {before: pair.before, after: pair.after};
    renderCompare();
  }
  function setCompareBefore(a) {
    if (!S.compare) { S.compare = {before: a, after: S.acq}; } else S.compare.before = a;
    var btn = document.querySelector('[data-act=compare]'); if (btn) btn.classList.add('on');
    renderCompare();
  }
  function teardownCompare() {
    if (S.map2) { try { S.map2.remove(); } catch (e) { /* gone */ } S.maps = S.maps.filter(function (m) { return m !== S.map2; }); S.map2 = null; }
    var wrap = document.getElementById('satw-maps'); if (wrap) wrap.classList.remove('split');
    var p2 = document.getElementById('satw-map2'); if (p2) p2.remove();
    ['satw-swipe', 'satw-cmp-l', 'satw-cmp-r'].forEach(function (id) { var x = document.getElementById(id); if (x) x.remove(); });
    if (S.swipeLayers) { S.swipeLayers.forEach(function (l) { S.map.removeLayer(l); }); S.swipeLayers = null; }
    var bar = document.getElementById('satw-compare-bar'); if (bar) bar.hidden = true;
    var mapEl = document.getElementById('satw-map'); if (mapEl) mapEl.classList.remove('muted');
    if (S.base && S.map && layerOn('base') && !S.map.hasLayer(S.base)) S.base.addTo(S.map);
    if (S.map) { if (layerOn('image') && !S.map.hasLayer(S.groups.image)) S.groups.image.addTo(S.map); setTimeout(function () { S.map.invalidateSize(); }, 50); }
  }
  function renderCompare() {
    var L = S.L, c = S.compare; if (!L || !c) return;
    teardownCompare(); S.groups.image.clearLayers();
    var lab = document.getElementById('satw-img-label'); if (lab) lab.remove();
    var v = comparePair(c.before, c.after), comp = v.ok ? pairComposite(c.before, c.after, S.composite) : null;
    var bar = document.getElementById('satw-compare-bar');
    bar.hidden = false;
    bar.innerHTML = seg('mode', [['A', t('modeA')], ['B', t('modeB')], ['C', t('modeC')], ['D', t('modeD')]], S.mode) +
      (v.ok ? '' : '<span class="satw-banner warn inline">' + esc(t(v.reason)) + '</span>') +
      (v.ok && c.before.sensor === 'S2' && S.composite === 'true' && comp === 'false' ? '<span class="satw-note">' + esc(t('compositeNote')) + '</span>' : '') +
      '<button class="satw-x" data-act="cmp-close">×</button>';
    bar.querySelectorAll('[data-seg=mode] button').forEach(function (b) { b.onclick = function () { S.mode = b.getAttribute('data-v'); renderCompare(); }; });
    bar.querySelector('[data-act=cmp-close]').onclick = function () { toggleCompare(); };
    var bb = S.area.area.grid_bbox, bounds = [[bb[1], bb[0]], [bb[3], bb[2]]];
    var wrap = document.getElementById('satw-maps'), mapEl = document.getElementById('satw-map');
    if (!v.ok) return;
    var side = function (a, cls, id) { var d = document.createElement('div'); d.id = id; d.className = 'satw-cmp-side ' + cls; d.innerHTML = '<b>' + esc(cls === 'l' ? t('before') : t('after')) + '</b><br>' + acqLabel(a, comp) + '<div><small>' + esc(t('product')) + ': <code data-no-i18n>' + esc(a.product_id) + '</code></small></div>'; return d; };
    if (S.mode === 'D') {
      mapEl.classList.add('muted'); S.map.removeLayer(S.groups.image);
      if (layerOn('change') && !S.map.hasLayer(S.groups.change)) S.groups.change.addTo(S.map);
      mapEl.appendChild(side(c.after, 'r', 'satw-cmp-r'));
      return;
    }
    if (S.mode === 'C') {
      imgStatus(mapEl, L.imageOverlay(imageUrl(c.after, comp), bounds, {pane: 'satwImg'})).addTo(S.groups.image);
      if (!S.map.hasLayer(S.groups.change)) S.groups.change.addTo(S.map);
      mapEl.appendChild(side(c.after, 'r', 'satw-cmp-r'));
      return;
    }
    if (S.mode === 'A') {
      var lb = L.imageOverlay(imageUrl(c.before, comp), bounds, {pane: 'satwImg'}), la = L.imageOverlay(imageUrl(c.after, comp), bounds, {pane: 'satwAfter'});
      if (!S.map.getPane('satwAfter')) { S.map.createPane('satwAfter').style.zIndex = 310; S.map.getPane('satwAfter').style.pointerEvents = 'none'; }
      imgStatus(mapEl, lb).addTo(S.map); la.addTo(S.map); S.swipeLayers = [lb, la];
      var sw = document.createElement('input'); sw.type = 'range'; sw.min = 0; sw.max = 100; sw.value = 50; sw.id = 'satw-swipe'; sw.className = 'satw-swipe';
      mapEl.appendChild(sw); mapEl.appendChild(side(c.before, 'l', 'satw-cmp-l')); mapEl.appendChild(side(c.after, 'r', 'satw-cmp-r'));
      var clip = function () {
        var pane = S.map.getPane('satwAfter'), size = S.map.getSize(), x = size.x * sw.value / 100;
        var nw = S.map.containerPointToLayerPoint([x, 0]), se = S.map.containerPointToLayerPoint(size);
        pane.style.clip = 'rect(' + [nw.y, se.x, se.y, nw.x].join('px,') + 'px)';
      };
      sw.oninput = clip; S.map.on('move zoom', clip); setTimeout(clip, 30);
      return;
    }
    // B — side by side, two synced maps
    wrap.classList.add('split');
    var m2el = document.createElement('div'); m2el.id = 'satw-map2'; m2el.className = 'satw-map'; wrap.appendChild(m2el);
    S.map.invalidateSize();
    var m2 = L.map(m2el, {zoomControl: false, attributionControl: true, zoomSnap: 0.25}); S.map2 = m2; S.maps.push(m2);
    m2.createPane('satwImg').style.zIndex = 300; m2.getPane('satwImg').style.pointerEvents = 'none'; m2.createPane('satwChange').style.zIndex = 440; m2.createPane('satwBoundary').style.zIndex = 420;
    if (layerOn('base')) L.tileLayer(OSM, {maxZoom: 19, attribution: '© OpenStreetMap contributors'}).addTo(m2);
    imgStatus(mapEl, L.imageOverlay(imageUrl(c.before, comp), bounds, {pane: 'satwImg'})).addTo(S.groups.image);
    imgStatus(m2el, L.imageOverlay(imageUrl(c.after, comp), bounds, {pane: 'satwImg'})).addTo(m2);
    if (S.area.geometry) L.geoJSON(S.area.geometry, {pane: 'satwBoundary', style: {color: '#F5F5F0', weight: 2.5, fill: false}}).addTo(m2);
    (S.layer.features || []).forEach(function (f) { if (f.properties.kind === 'event') { var cc = changeColour(f.properties); L.geoJSON(f, {pane: 'satwChange', style: {color: cc.color, weight: f.properties.event_id === S.sel ? 3.5 : 2, dashArray: cc.dash, fill: false}}).addTo(m2); } });
    m2.setView(S.map.getCenter(), S.map.getZoom(), {animate: false});
    var busy = false;
    function sync(a, b) { a.on('move', function () { if (busy) return; busy = true; b.setView(a.getCenter(), a.getZoom(), {animate: false}); busy = false; }); }
    sync(S.map, m2); sync(m2, S.map);
    mapEl.appendChild(side(c.before, 'l', 'satw-cmp-l')); m2el.appendChild(side(c.after, 'r', 'satw-cmp-r'));
  }

  // ── timeline ──────────────────────────────────────────────────────────────────────────────────────────────────
  function renderTimeline() {
    var box = document.getElementById('satw-tl'); if (!box || !S.area) return;
    var tl = S.area.timeline, mv = minValid();
    if (!tl.length) { box.innerHTML = '<div class="satw-empty">' + esc(t('noDataYet')) + '</div>'; return; }
    var end = Date.now(), start = S.window === 'all' ? parseUtc(tl[0].sensing_time_utc).getTime() - DAY : end - S.window * DAY;
    var W = Math.max(600, box.clientWidth || 1200), H = 96, x0 = 70, x1 = W - 16;
    var X = function (iso) { var d = parseUtc(iso); return d ? x0 + (d.getTime() - start) / (end - start) * (x1 - x0) : -99; };
    var svg = '<svg width="' + W + '" height="' + H + '" class="satw-tl-svg"><text x="8" y="32" class="lbl">S2</text><text x="8" y="72" class="lbl">S1</text>' +
      '<line x1="' + x0 + '" x2="' + x1 + '" y1="28" y2="28" class="trk"/><line x1="' + x0 + '" x2="' + x1 + '" y1="68" y2="68" class="trk"/>';
    for (var m = new Date(start); m.getTime() <= end; m = new Date(m.getFullYear(), m.getMonth() + 1, 1)) {
      var mx = X(new Date(m.getFullYear(), m.getMonth(), 1).toISOString()); if (mx >= x0) svg += '<line x1="' + mx + '" x2="' + mx + '" y1="12" y2="84" class="tick"/><text x="' + (mx + 3) + '" y="92" class="tlbl" data-no-i18n>' + (m.getFullYear() + '-' + pad(m.getMonth() + 1)) + '</text>';
    }
    (S.events || []).forEach(function (e) {
      var ex = X(e.first_after_time_utc); if (ex < x0) return; var y = e.onset_sensor === 'S1' ? 56 : 16, c = changeColour(e);
      svg += '<path d="M' + ex + ' ' + (y + 6) + ' l-5 -8 h10 z" fill="' + c.color + '" class="onset"><title>#' + e.id + ' ' + esc(clsLabel(e.classification)) + '</title></path>';
    });
    tl.forEach(function (a) {
      var x = X(a.sensing_time_utc); if (x < x0 || x > x1 + 1) return;
      if (a.sensor === 'S1' && S.s1geom !== 'all' && geomKey(a) !== S.s1geom) return;
      var st = acqState(a, mv), y = a.sensor === 'S2' ? 28 : 68, col = a.sensor === 'S1' ? geomColour(a) : '#5DB37E', sel = S.acq && S.acq.acq_id === a.acq_id;
      var inPair = S.compare && ((S.compare.before && S.compare.before.acq_id === a.acq_id) || (S.compare.after && S.compare.after.acq_id === a.acq_id));
      var shape;
      if (st === 'cloud') shape = '<text x="' + x + '" y="' + (y + 4) + '" class="cloud">☁</text>';
      else if (st === 'invalid') shape = '<path d="M' + (x - 4) + ' ' + (y - 4) + ' l8 8 M' + (x + 4) + ' ' + (y - 4) + ' l-8 8" class="cross"/>';
      else if (a.sensor === 'S1') shape = '<path d="M' + x + ' ' + (y - 6) + ' l6 6 l-6 6 l-6 -6 z" fill="' + (st === 'ok' ? col : 'none') + '" stroke="' + col + '" stroke-width="1.6"/>';
      else shape = '<circle cx="' + x + '" cy="' + y + '" r="5.5" fill="' + (st === 'ok' ? col : 'none') + '" stroke="' + col + '" stroke-width="1.6"/>';
      svg += '<g class="acq' + (sel ? ' sel' : '') + (inPair ? ' pair' : '') + '" data-acq="' + a.acq_id + '">' + ((sel || inPair) ? '<circle cx="' + x + '" cy="' + y + '" r="10" class="ring"/>' : '') + shape +
        '<rect x="' + (x - 6) + '" y="' + (y - 10) + '" width="12" height="20" fill="transparent"/></g>';
    });
    box.innerHTML = svg + '</svg>';
    var tip = document.getElementById('satw-tip');
    box.querySelectorAll('[data-acq]').forEach(function (g) {
      var a = S.byId[+g.getAttribute('data-acq')];
      g.onmouseenter = function (ev) {
        var st = acqState(a, mv);
        tip.innerHTML = '<b data-no-i18n>' + esc(fmtTime(a.sensing_time_utc)) + '</b><br><span data-no-i18n>' + esc(a.sensor + ' · ' + (a.platform || '') + (a.sensor === 'S1' ? ' · ' + geomKey(a) : '')) + '</span><br>' +
          esc(t({ok: 'stOk', low: 'stLow', cloud: 'stCloud', invalid: 'stInvalid', pending: 'stPending'}[st])) +
          (a.sensor === 'S2' ? ' · ' + esc(t('cloud')) + ' <span data-no-i18n>' + (isNum(a.scene_cloud_pct) ? a.scene_cloud_pct.toFixed(0) + ' %' : '—') + '</span>' : '') +
          ' · ' + esc(t('validPct')) + ' <span data-no-i18n>' + (isNum(a.valid_pct_inside) ? a.valid_pct_inside.toFixed(1) : '—') + '</span>' +
          (a.detection ? '<br><span title="' + esc(a.detection) + '">' + esc(T[S.lang]['o_' + a.detection] || a.detection) + '</span>' : '') +
          '<br><code data-no-i18n>' + esc(a.product_id) + '</code>';
        tip.hidden = false; var r = box.getBoundingClientRect(), gr = g.getBoundingClientRect();
        tip.style.left = Math.min(r.width - 330, Math.max(0, gr.left - r.left - 150)) + 'px'; tip.style.bottom = (r.bottom - gr.top + 8) + 'px';
      };
      g.onmouseleave = function () { tip.hidden = true; };
      g.onclick = function (ev) {
        if (!a.quicklook_url) return;
        if (ev.shiftKey) { setCompareBefore(a); renderTimeline(); return; }
        if (S.compare) { S.compare.after = a; renderCompare(); renderTimeline(); return; }
        S.sel ? (S.acq = a, S.sensor = a.sensor, syncSeg('sensor', S.sensor), renderComposite(), drawImage()) : showAcq(a);
      };
    });
  }

  // ── analysis drawer (area median; event polygon curve postponed) ───────────────────────────────────────────────
  function renderAnalysis(L) {
    S.analysisL = L;
    var box = document.getElementById('satw-analysis-body'); if (!box || !global.Chart) { if (box) box.innerHTML = '<p class="satw-muted">' + esc(t('analysisNote')) + '</p>'; return; }
    S.charts.forEach(function (c) { try { c.destroy(); } catch (e) { /* gone */ } }); S.charts = [];
    box.innerHTML = '<div class="satw-charts"><div><canvas id="satw-ch-s2"></canvas></div><div><canvas id="satw-ch-s1"></canvas></div></div><p class="satw-muted">' + esc(t('analysisNote')) + '</p>';
    var tl = S.area.timeline, mv = minValid();
    function series(sensor, key) {
      return tl.filter(function (a) { return a.sensor === sensor && (sensor !== 'S1' || S.s1geom === 'all' || geomKey(a) === S.s1geom); }).map(function (a) {
        var m = (a.metrics_inside || {})[key], ok = a.status === 'OK' && acqState(a, mv) !== 'invalid';
        return {x: parseUtc(a.sensing_time_utc).getTime(), y: ok && m && isNum(m.median) ? m.median : null};
      });
    }
    var dark = S.theme === 'dark', grid = dark ? 'rgba(245,245,240,.08)' : 'rgba(16,25,20,.08)', txt = dark ? '#CFD8D2' : '#1F2A24';
    function chart(id, sets, yTitle) {
      var ev = (S.events || []).map(function (e) { return parseUtc(e.first_after_time_utc).getTime(); });
      return new global.Chart(document.getElementById(id), {type: 'line', data: {datasets: sets.map(function (s) { return {label: s[0], data: s[1], borderColor: s[2], backgroundColor: s[2], spanGaps: false, pointRadius: 2, borderWidth: 1.5}; })},
        options: {animation: false, responsive: true, maintainAspectRatio: false, parsing: false,
          scales: {x: {type: 'linear', ticks: {color: txt, callback: function (v) { return fmtDate(new Date(v).toISOString()); }, maxTicksLimit: 6}, grid: {color: grid}},
                   y: {title: {display: true, text: yTitle, color: txt}, ticks: {color: txt}, grid: {color: grid}}},
          plugins: {legend: {labels: {color: txt, boxWidth: 10}}, tooltip: {callbacks: {title: function (it) { return fmtTime(new Date(it[0].parsed.x).toISOString()); }}}}}});
    }
    S.charts.push(chart('satw-ch-s2', [['NDVI', series('S2', 'NDVI'), '#5DB37E'], ['NBR', series('S2', 'NBR'), '#D4B23A'], ['NDMI', series('S2', 'NDMI'), '#4FA3D9']], 'S2'));
    S.charts.push(chart('satw-ch-s1', [['VV dB', series('S1', 'VV_DB'), '#9B7BD8'], ['VH dB', series('S1', 'VH_DB'), '#4FA3D9']], 'S1 dB'));
  }
  function renderTech() {
    var box = document.getElementById('satw-tech-body'); if (!box || !S.area) return;
    var rows = S.area.timeline.slice().reverse();
    box.innerHTML = '<table class="satw-table satw-small"><thead><tr><th>' + esc(t('thTime')) + '</th><th>' + esc(t('thSensor')) + '</th><th>' + esc(t('thStatus')) + '</th><th>' + esc(t('thValid')) + '</th><th>' + esc(t('thOutcome')) + '</th><th>' + esc(t('product')) + '</th></tr></thead><tbody>' +
      rows.map(function (a) {
        return '<tr><td data-no-i18n>' + esc(fmtTime(a.sensing_time_utc)) + '</td><td data-no-i18n>' + esc(a.sensor + (a.sensor === 'S1' ? ' ' + geomKey(a) : '')) + '</td>' +
          '<td title="' + esc(a.status) + '">' + esc(T[S.lang]['s_' + a.status] || a.status) + '</td><td data-no-i18n>' + (isNum(a.valid_pct_inside) ? a.valid_pct_inside.toFixed(1) : '—') + '</td>' +
          '<td title="' + esc(a.detection || '') + '">' + (a.detection ? esc(T[S.lang]['o_' + a.detection] || a.detection) : '—') + '</td><td><code data-no-i18n>' + esc(a.product_id) + '</code></td></tr>';
      }).join('') + '</tbody></table>';
  }

  // ── deep links: superseded ids resolve to their own area with the successor notice ───────────────────────────
  async function openEvent(id) {
    var ev; try { ev = await get('/events/' + id); } catch (e) { errorView(e); return; }
    await openArea(ev.monitored_area_id);
    S.sel = id;
    if (ev.current === false) {
      S.ev = ev; var right = document.getElementById('satw-right'); if (right) renderEventPanel(ev);
      return;
    }
    selectEvent(id);
  }

  var api = {load: loadOverview, openArea: function (id) { return openArea(+id); }, openEvent: function (id) { return openEvent(+id); },
             _changeColour: changeColour, _CHANGE_COLOURS: CHANGE_COLOURS, _worstColour: worstColour, _fmtTime: fmtTime, _rigaParts: rigaParts,
             _acqState: acqState, _comparePair: comparePair, _pairComposite: pairComposite, _defaultPair: defaultPair, _vmdValue: vmdValue, _T: T,
             get state() { return S; }};
  global.SatWorkspace = api;
  // Route the section here; keep every other legacy hook (lvmButton, _trServer, …) of window.SatMonitoring.
  if (global.SatMonitoring && !global.SAT_WORKSPACE_DISABLED) {
    var legacy = global.SatMonitoring;
    global.SatMonitoring = Object.assign({}, legacy, {load: api.load, openArea: api.openArea, openEvent: api.openEvent, _legacy: legacy});
  }
})(window);
