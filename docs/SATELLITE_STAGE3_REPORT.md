# Satellite Monitoring — Stage 3 (UI) report

Date: 2026-11-16. Branch `feature/satellite-monitoring`. **Not deployed:**
- no restart, no production write;
- the UI was run from the worktree on 127.0.0.1:8020–8024 against COPIES of `forest_ai.db` and `satellite.db` (scratchpad);
- all sandbox servers were stopped afterwards.

## What was built

| Part | Where |
|---|---|
| Sidebar item "Satellite Monitoring" under MONITOR, right after Sectors. Existing items, order and styles are unchanged; `navMap` is shifted (tested) | `index.html` |
| Section, styles, all views | `assets/sat-monitoring.js`, `assets/sat-monitoring.css` (new) |
| A. Overview: | |
| — KPIs: monitored, recent observations (≤ 14 d), awaiting data, open suspected (+ RECOVERED shown separately), last successful sync, failed jobs | |
| — map of all areas; table with status badges | |
| — health strip: PU and requests vs the 80 % guard and the budget; worker lock; "automatic risks: off" | |
| — "Fetch now"; "Add sector" (sectors with a polygon; "No polygon" otherwise; "Monitored" / "Queued") | |
| B. Area view: | |
| — map toggles: sector boundary, buffer ring, current change mask (inside cyan / outside yellow), Sentinel observation footprint + date, Sentinel image | |
| — charts: S2 NDVI/NBR/NDMI and S1 VV/VH dB. No-data is a GAP (`null`, `spanGaps: false`), never 0. Markers for event onsets and radar anomalies | |
| — acquisitions list; "Stop monitoring" | |
| C. Event view: | |
| — BEFORE / AFTER / CHANGE (mask over AFTER) side by side, zoomed to the change and synced; swipe mode | |
| — per image: date, sensor, platform, valid %, product id, attribution | |
| — neutral lines; classification, confidence and evidence quality as separate badges; seasonal caveat; RECOVERED with reason | |
| — area table; zkat split (stand / clear-cut / other / none); operational context with links (GPS Sessions, Truck Reports, Timber, sector) | |
| — algorithm: detection generation + code version, and the thresholds | |
| — review: Reject / Request field check / Create risk / Undo, each with a confirm dialog (Reject and field check also ask for an optional note) | |
| D. LVM GEO: ONE button "Add to satellite monitoring" in the compartment popup (selected-object panel). One line in `vmd-production.js` | `window.SatMonitoring?.lvmButton?.(popup,feature)` |
| — states: "Already monitored", "Queued for satellite monitoring", "No polygon", "Multi-part polygon …" | |
| — the lookup runs only when the popup is shown | |
| E. Empty and error states: no areas, no polygon, no credentials (names only), no data yet, backfill in progress, satellite.db unavailable (503), schema not migrated | |
| F. "Contains modified Copernicus Sentinel data [YEAR]" under every satellite image and under the area map. It is kept in English (required wording, `data-no-i18n`) | |

**Backend additions for the UI** (all read-only except the existing job/review writes):
- `overview`: KPIs, area geometry and grid bbox, pending ADD_AREA jobs. An ADD_AREA job now marks its own area "backfill in progress".
- `areas/{id}`: buffer ring (`display.py`: shapely, the worker's equirectangular scale, display only), radar anomalies, product ids, change masks.
- `events/{id}`: area context, product ids, algorithm (generation / code version), `undo_available`.
- `health`: last successful sync, failed jobs, guard limits, `credentials_configured` (env var names only).
- New `GET /sectors` and `GET /lookup`.
- A single-part MultiPolygon is unwrapped to a Polygon. A multi-part one is refused with 422, because the worker accepts Polygon only.

**Fixes found while running the UI:**
- Leaflet image overlays (z-index 1) hid the vector masks. Images now sit in panes below the overlay pane.
- A red mask was invisible on false-colour quicklooks, where bare soil is already magenta. Masks are now cyan (inside) / yellow (outside) with an outline.
- A 6 ha change in the 3,670 ha Ķekava box was invisible at full extent. Event maps zoom to the change.

## Screenshots (local, not versioned: `docs/evidence/satellite-stage3/`)

| File | State |
|---|---|
| 01_overview | Overview: BIK-001 + Ķekava, KPIs, health strip, map, table |
| 02_area_bik001 | BIK-001 area (no events), charts with gaps, radar anomalies |
| 03_area_kekava | Ķekava area: current masks, charts with event and radar markers, acquisitions |
| 04_event51_side | Event 51 (real felling): BEFORE 06-29 forest → AFTER 08-21 bare soil, mask over AFTER, zkat 4.75 ha clear-cut land |
| 05_event51_swipe | Event 51 swipe mode |
| 06_event55_side | Event 55 (autumn, standing forest): 123.71 ha, 6.74 ha outside, seasonal caveat, 107.19 ha on zkat 10 |
| 07_event49_recovered | Event 49 RECOVERED with reason (S1 images) |
| 08_event50_fieldcheck_502 | Field check with Telegram not configured → error, no state change |
| 09_event50_risk_created / 10_event50_rejected / 11_event50_undo | Create risk (risk #63 in the COPY), reject with note, undo stack |
| 12_overview_add_sector / 13_overview_fetch_queued | Sector picker (No polygon / Monitored / Add); "Fetch now" deduplicated job |
| 14_overview_nodata_backfill / 15_area_no_data_yet / 16_area_backfill_in_progress | Awaiting data |
| 17_overview_no_credentials / 18_overview_no_areas / 19_overview_503_unavailable | Empty and error states |
| 20_lvm_geo_button / 21_lvm_geo_queued / 22_lvm_geo_already_monitored | LVM GEO popup button states (cadastre 80480140048) |
| 23_lv_overview / 24_lv_area_kekava / 25_lv_event51 | Latvian (`UI_LANGUAGE=lv`) |

In the LV sandbox, an in-browser scan of every visible text node in the section found no English UI text left (only "LVM GEO").

## Tests

| Run | Result |
|---|---|
| JS (`node --test tests/*.js`, incl. new `test_sat_monitoring_ui.js`) | 78 pass, 0 fail |
| Satellite tests, system python | 146 passed, 1 skipped |
| Satellite tests, venv2 | 98 passed, 1 skipped (the API file skips there: no fastapi in venv2) |
| Full suite, system python | 9 failed, 434 passed, 4 skipped, 40 errors. The failure set is identical to the pre-Stage-2 baseline (VMD dataset, py7zr, John Deere, integrations) |

## New i18n strings (165 exact + 10 patterns in `assets/i18n-lv.js`; 9 more reuse existing entries)

Reused existing entries: Close, Date, Error, Loading…, Note, Sector, Status, Timber movements, Truck reports.

| EN | LV |
|---|---|
| Satellite Monitoring | Satelītu monitorings |
| ← Satellite Monitoring | ← Satelītu monitorings |
| Fetch now | Ielādēt tagad |
| Add sector | Pievienot sektoru |
| Done. | Gatavs. |
| Monitored areas | Uzraudzītās teritorijas |
| With recent observations | Ar neseniem novērojumiem |
| Awaiting data | Gaida datus |
| Open suspected events | Atvērtie iespējamo izmaiņu notikumi |
| Last successful sync | Pēdējā veiksmīgā sinhronizācija |
| Failed jobs | Neizdevušies uzdevumi |
| never | nekad |
| Copernicus usage this month | Copernicus patēriņš šomēnes |
| Processing units (PU) | Apstrādes vienības (PU) |
| Requests | Pieprasījumi |
| guard | drošības robeža |
| budget | budžets |
| Worker | Apstrādes process |
| Running | Darbojas |
| Idle | Dīkstāvē |
| Automatic risks | Automātiskie riski |
| Off — risks are created only by a person (Create risk) | Izslēgti — riskus izveido tikai cilvēks (Izveidot risku) |
| Monitored area | Uzraudzītā teritorija |
| Source | Avots |
| Area (ha) | Platība (ha) |
| Last S1 | Pēdējais S1 |
| Last valid S2 | Pēdējais derīgais S2 |
| Open suspected | Atvērtie iespējamie |
| Recovered | Atjaunojies |
| Days since valid S2 | Dienas kopš derīgā S2 |
| Open | Atvērt |
| Data OK | Dati kārtībā |
| No data yet | Vēl nav datu |
| Backfill in progress | Notiek vēsturisko datu ielāde |
| Stopped | Apturēts |
| LVM GEO | LVM GEO |
| Evaluation area | Novērtējuma teritorija |
| No monitored areas yet. | Vēl nav uzraudzītu teritoriju. |
| Add a sector here, or use “Add to satellite monitoring” in LVM GEO. | Pievienojiet sektoru šeit vai izmantojiet “Pievienot satelītu monitoringam” sadaļā LVM GEO. |
| Copernicus credentials are not configured (SENTINEL_CLIENT_ID / SENTINEL_CLIENT_SECRET). Fetching is disabled. | Copernicus piekļuves dati nav konfigurēti (SENTINEL_CLIENT_ID / SENTINEL_CLIENT_SECRET). Datu ielāde ir atspējota. |
| Satellite monitoring data is unavailable (satellite.db). | Satelītu monitoringa dati nav pieejami (satellite.db). |
| The worker has not prepared the database yet; changes cannot be queued. | Apstrādes process vēl nav sagatavojis datubāzi; izmaiņas nevar ierindot. |
| Sectors with a polygon | Sektori ar poligonu |
| No polygon | Nav poligona |
| Monitored | Tiek uzraudzīts |
| Queued | Rindā |
| Add | Pievienot |
| Queued areas | Rindā esošās teritorijas |
| waiting for the worker | gaida apstrādes procesu |
| Fetch new Sentinel-1/2 observations for all monitored areas now? | Ielādēt jaunus Sentinel-1/2 novērojumus visām uzraudzītajām teritorijām tagad? |
| Stop monitoring this area? Its history is kept. | Apturēt šīs teritorijas monitoringu? Vēsture tiek saglabāta. |
| Mark this suspected change as rejected (not a real change)? | Atzīmēt šīs iespējamās izmaiņas kā noraidītas (nav reālas izmaiņas)? |
| Send a field check request to the dispatcher via Telegram? | Nosūtīt dispečeram lauka pārbaudes pieprasījumu Telegram? |
| Create a risk for this suspected change in the Risk Engine? | Izveidot risku risku sistēmā par šīm iespējamajām izmaiņām? |
| Undo the last review decision? | Atsaukt pēdējo pārskatīšanas lēmumu? |
| Note (optional): | Piezīme (nav obligāta): |
| Map layers | Kartes slāņi |
| Sector boundary | Sektora robeža |
| Buffer ring | Buferzona |
| Detected change (current mask) | Konstatētās izmaiņas (pašreizējā maska) |
| Sentinel observation footprint | Sentinel novērojuma pārklājums |
| Sentinel image | Sentinel attēls |
| Observation footprint | Novērojuma pārklājums |
| Change inside the boundary | Izmaiņas robežās |
| Change outside the boundary | Izmaiņas ārpus robežas |
| Suspected change events | Iespējamo izmaiņu notikumi |
| Event | Notikums |
| Onset | Sākums |
| Classification | Klasifikācija |
| Confidence | Ticamība |
| Current (ha) | Pašlaik (ha) |
| Outside (ha) | Ārpus robežas (ha) |
| No change events. | Nav izmaiņu notikumu. |
| Time series (inside the area, median) | Laika rinda (teritorijā, mediāna) |
| Sentinel-2 indices | Sentinel-2 indeksi |
| Sentinel-1 backscatter (dB) | Sentinel-1 atpakaļizkliede (dB) |
| Gaps = no usable observation (cloud, no valid pixels). Missing values are never shown as 0. | Pārtraukumi = nav izmantojama novērojuma (mākoņi, nav derīgu pikseļu). Trūkstošas vērtības nekad netiek rādītas kā 0. |
| Event onset | Notikuma sākums |
| Radar anomaly | Radara anomālija |
| Acquisitions | Uzņēmumi |
| Sensor | Sensors |
| Platform | Platforma |
| Product ID | Produkta ID |
| Sensing time (UTC) | Uzņemšanas laiks (UTC) |
| Valid % inside | Derīgi % teritorijā |
| Detection | Noteikšana |
| No acquisitions yet. | Vēl nav uzņēmumu. |
| Stop monitoring | Apturēt monitoringu |
| Monitoring has not produced data yet. The first backfill runs after the worker picks up the job. | Monitorings vēl nav devis datus. Pirmā vēsturisko datu ielāde notiks, kad apstrādes process paņems uzdevumu. |
| Backfill or fetch in progress. | Notiek vēsturisko vai jauno datu ielāde. |
| Monitoring stopped. History is kept. | Monitorings apturēts. Vēsture saglabāta. |
| Before | Pirms |
| After | Pēc |
| Change (mask over after) | Izmaiņas (maska virs “pēc” attēla) |
| Side by side | Blakus |
| Swipe | Pārvilkt |
| Suspected change — automated detection, not verified on the ground. | Iespējamas izmaiņas — automātiska noteikšana, dabā nav pārbaudīts. |
| Recovered — the change is no longer visible. | Atjaunojies — izmaiņas vairs nav redzamas. |
| Seasonal caveat | Sezonāls brīdinājums |
| Detection confidence | Noteikšanas ticamība |
| Evidence quality | Pierādījumu kvalitāte |
| Potential forest loss | Iespējams meža zudums |
| Potential change outside the boundary | Iespējamas izmaiņas ārpus robežas |
| Possible seasonal or environmental change | Iespējamas sezonālas vai vides izmaiņas |
| Insufficient evidence | Nepietiekami pierādījumi |
| High | Augsta |
| Medium | Vidēja |
| Low | Zema |
| Good | Laba |
| Limited | Ierobežota |
| Poor | Vāja |
| Suspected | Iespējamas izmaiņas |
| Confirmed by review | Apstiprināts pārskatīšanā |
| Rejected by review | Noraidīts pārskatīšanā |
| Field check requested | Pieprasīta lauka pārbaude |
| Areas | Platības |
| Current mask | Pašreizējā maska |
| Inside the boundary | Robežās |
| Outside the boundary (buffer) | Ārpus robežas (buferzonā) |
| Union of all after-images | Visu “pēc” attēlu apvienojums |
| Largest current area so far | Lielākā pašreizējā platība līdz šim |
| Share of the area | Daļa no teritorijas |
| Max distance outside the boundary | Maks. attālums ārpus robežas |
| Largest cluster | Lielākais klasteris |
| VMD compartment type (current mask) | VMD nogabala veids (pašreizējā maska) |
| Forest stand (zkat 10) | Mežaudze (zkat 10) |
| Clear-cut land (zkat 14) | Izcirtums (zkat 14) |
| Other compartments | Citi nogabali |
| No compartment | Ārpus nogabaliem |
| Compartment split unavailable | Nogabalu sadalījums nav pieejams |
| Operational context | Darbību konteksts |
| Registered work in the observation window | Novērojuma periodā reģistrēti darbi |
| No registered work found in the observation window | Novērojuma periodā reģistrēti darbi nav atrasti |
| Counts of registered records only. No records does not prove there was no work; records do not explain the change. | Tikai reģistrēto ierakstu skaits. Ierakstu trūkums nepierāda, ka darbi nav notikuši; ieraksti neizskaidro izmaiņas. |
| Worker GPS points | Darbinieku GPS punkti |
| Vehicle/equipment GPS pings | Transporta/tehnikas GPS signāli |
| Work sessions | Darba sesijas |
| Field photos | Lauka foto |
| unknown | nav zināms |
| inside | teritorijā |
| buffer | buferzonā |
| Open GPS Sessions | Atvērt GPS sesijas |
| Open Truck Reports | Atvērt kokvedēju atskaites |
| Open Timber | Atvērt kokmateriālus |
| Open sector | Atvērt sektoru |
| Algorithm | Algoritms |
| Pipeline run (code version not recorded) | Apstrādes palaišana (koda versija nav reģistrēta) |
| Configuration (thresholds) | Konfigurācija (sliekšņi) |
| Review | Pārskatīšana |
| Reject | Noraidīt |
| Request field check | Pieprasīt lauka pārbaudi |
| Create risk | Izveidot risku |
| Undo | Atsaukt |
| Review log | Pārskatīšanas žurnāls |
| No review yet. | Vēl nav pārskatīts. |
| Action | Darbība |
| By | Kas |
| This event was superseded by a later detection generation; review is disabled. | Šo notikumu aizstāja vēlākas noteikšanas paaudzes rezultāts; pārskatīšana ir atspējota. |
| No image | Nav attēla |
| Valid % | Derīgi % |
| Add to satellite monitoring | Pievienot satelītu monitoringam |
| Already monitored | Jau tiek uzraudzīts |
| Queued for satellite monitoring | Rindā satelītu monitoringam |
| Multi-part polygon — add the parts separately | Vairākdaļu poligons — pievienojiet daļas atsevišķi |
| Already queued. | Jau rindā. |

| Pattern (EN) | LV |
|---|---|
| `/^last (\d+) days$/` | pēdējās $1 dienās |
| `/^\+(\d+) recovered \(not counted\)$/` | +$1 atjaunojies (netiek skaitīts kā atvērts) |
| `/^Vegetation\/land-cover change detected: (.+)$/` | Konstatētas veģetācijas/zemes seguma izmaiņas: $1 |
| `/^(.+ ha) outside the approved boundary$/` | $1 ārpus apstiprinātās robežas |
| `/^Event #(\d+)$/` | Notikums #$1 |
| `/^Detection generation (\d+)$/` | Noteikšanas paaudze $1 |
| `/^code (\S+)$/` | kods $1 |
| `/^Risk #(\d+)$/` | Risks #$1 |
| `/^Queued as job #(\d+)\.$/` | Ierindots kā uzdevums #$1. |
| `/^Add (.+) to satellite monitoring\? The last 120 days are fetched first\.$/` | Pievienot $1 satelītu monitoringam? Vispirms tiks ielādētas pēdējās 120 dienas. |

## Not verified

- **No real worker:** the sandbox never ran the queued jobs (0 network, 0 PU). "Queued" and "Already monitored" were produced by completing the job by hand in the COPY.
- **Telegram and the AI recommendation were not configured** in the sandbox: field check → 502; Create risk used the AI fallback text.
- **Not tested on mobile or narrow screens.** There is one breakpoint at 1100 px, untested.
- **Browser:** Chromium headless only.
- **Quicklooks** are drawn with Leaflet's linear image placement over the CRS84 grid (no reprojection); the error is negligible at these extents, but it is not measured.
- **The buffer ring** is an approximation for display (the worker classifies buffer pixels on the 10 m grid).
- **Production:** `index.html` / assets are not released; Stage 4 needs the 97- drop-in (`SAT_DB_PATH`, `SAT_RASTER_DIR`) and a migrated live `satellite.db`.
