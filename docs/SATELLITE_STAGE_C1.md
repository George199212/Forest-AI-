# Satelītu monitorings — Stage C1 (approved concept on real data, sandbox only)

**Date:** 2026-11-18. **Branch:** `feature/satellite-workspace` = v2 work + `b86ebf4` (live :8000, D8) + `feature/swipe-fix`
(Stage A, still pending review — merged as the swipe base, not deployed). **Production:** unchanged.

## What was built

| File | Change |
|---|---|
| `assets/sat-workspace.js` | Rewritten to the concept: header (Teritorija / Izmaiņas / Pierādījumi, WGS84 search, Pārvilkt / Blakus / Tikai izmaiņas, LV/EN), left panel, map with tool rail, pills, swipe, selection ring + callout, event card, analysis drawer, S1/S2 timeline, status bar. |
| `assets/sat-workspace.css` | §4 dark tokens, scoped to `#satm-root.satw`; no global CSS change. Light theme removed (later stage). |
| `assets/sat-monitoring.js` | 3 hooks only: event page renders into `#satm-evidence` (Pierādījumi tab), back link via `window.SatMonitoring`, `_core.charts()` = existing `drawCharts` unchanged. |
| `assets/i18n-lv.js` | 138 EN→LV pairs for the workspace strings (existing mechanism; test: LV = `I.tr(EN)` for every key). |
| `satellite_monitoring/store.py` | Q2: `/events/{id}` `after[]` carries the stored per-acquisition `evidence_quality` (read-only; event value and `pipeline.py:901` untouched). |
| `tests/test_sat_workspace.js`, `tests/test_sat_stage2_api.py` | Prototype tests updated; C1 rule tests added (see below). |
| `scripts/verify_sat_workspace_c1.py` | Headless screenshots + 95 checks (GETs only; the add confirm is dismissed, no review POSTs). |

`forest-map.js` is not changed by C1 (Q3: parser copied). `index.html`: only the two workspace tags from v2;
`<script src="/assets/forest-map.js?v=20261107"></script>` byte-exact.

## Data mapping (every element → API field; missing → "Nav pieejams")

- Area selector / count / name / source / ha / status chip: `/overview` `areas[]`, `/areas/{id}` `area` (`name` as stored — D3 rename pending).
- Pēdējais uzņēmums = max `sensing_time_utc` of `status=OK` timeline rows (+ sensor). Pēdējais derīgais S2 = `last_valid_s2_utc` + `last_valid_s2_valid_pct`.
  Pēdējā analīze = `last_successful_analysis_utc` (7c5edfe). Sistēmas pārbaude = `/health` `provider_status[catalog]` last ok/error. EET/EEST + UTC.
- Sensor switch / stepper / chips: timeline rows of the sensor with `status=OK` and a quicklook; platform, `valid_pct_inside`, "10 m/px" for S2 only.
- Composite list: only kinds that exist (`truecolor_url`, `quicklook_url`; pair: true colour only if BOTH have it, else false colour on both + note). No mask entry (Q4).
- Layers: boundary, buffer, change polygons (`/map-layer`), VMD compartments (Forest Map tile endpoint, read-only), basemap (faint OSM). No GPS toggle.
- Events: `/areas/{id}` events, open first, colour = §5.5 table (`changeColour`), seasonal tag from `seasonal_caveat`.
- Event card: `/events/{id}`: status, class, ha, "Kas mainījās" template (stored fields only), confidence, evidence quality + source (D2, from `after[].evidence_quality`),
  before/after product id + valid %, actions = existing review API.
- Status bar: `/health` provider state, month requests / PU vs guard, `worker.units.sync.next_run_utc`, `auto_risk_enabled`, basemap label.
- Kas šeit?: WGS84 point; monitored = point-in-polygon on `/overview` geometries; compartment / cadastre = `/api/geodata/forest-map/identify`;
  add = `/lookup` + `POST /areas` (LVM_GEO, same as the LVM GEO button) after a confirm with cost "Nav pieejams" + month vs guard.
- Search: coordinates (copied D6 parser), 11-digit cadastre (`/api/geodata/vmd/cadastre`), `VMD:` id (`/forest-map/feature`), area name.

## Owner review 2026-11-18: true-colour pair hint

When the default pair cannot be shown in true colour but the SAME event has another valid S2 pair with true colour on
both sides (`trueColourAlternative`: latest such baseline before the onset → earliest such after-image), the map shows
"Ir pieejams patiesu krāsu pāris: {before} → {after} — rādīt". Nothing switches silently; after the click the pills
(date · sensor · valid %) and the event card rows (date · sensor · product id · valid %) name the compared acquisitions.
#62: default 29.06 (299) → 14.08 (327, false colour) · hint → 29.06 (299) → 21.08 (331, true colour). Screenshot
`15-izmainas-62-truecolour-pair-after-hint-1440x900-lv.png`; 7 more checks (102 total).

## Evidence (`docs/evidence/satellite-stage5-v3/c1/`, not versioned)

48 screenshots (1440×900 and 1920×1080, LV and EN): Teritorija default, #62 swipe at 25/50/75 %, side by side, change only,
BIK-001, Kas šeit? inside / outside, timeline tooltip, acquisition via timeline and via stepper, #60 false colour on both sides
(true colour only on one side), Pierādījumi tab, Copernicus degraded (**SYNTHETIC** `/health` in the browser only), satellite.db 503
(real: second sandbox with a missing `SAT_DB_PATH`). Report: `c1_report.json` (95 checks, 0 failed).

## Tests

- pytest (system python): 9 failed, 455 passed, 5 skipped, 40 errors — failure/error set identical to `bc8c428`. Passed 448 → 455:
  +6 = v2 read-only API tests (7c5edfe, part of the D8 base), +1 = Q2 test.
- node: 11/11 files pass; `test_sat_workspace.js` 21 tests incl. parser parity with `forest-map.js` (25 inputs), D2 source, default
  area, point-in-polygon, EET/EEST display, deep-link round trip, composites never mixed, LV = i18n-lv.js, no dead tools.

## Known limits / NOT verified

- #62 default pair = last clear S2 (29.06) → **first** S2 after-image showing the change (327, 14.08, no true colour) → false colour on
  both sides. The concept shows 21.08 (331, true colour); the user can pick 331 on the timeline/stepper.
- "Kas mainījās" uses the event window of any sensor (#62: 17.07 → 29.07, both S1); the pills show the S2 pair.
- The event callout can run under the tool rail at narrow views.
- Inter / IBM Plex Mono are loaded from Google Fonts by the section (the app already loads its fonts there).
- Side-by-side comparison with the concept screenshot: **not done** — the concept PNG did not arrive; the concept artifact was read as source.
- Review actions (incl. UNDO), real add flow POST, LV text scan beyond "no undefined/NaN" → Stage C3.
- Pierādījumi tab = existing page unchanged (its own styling).
