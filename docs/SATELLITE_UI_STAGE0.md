# Satellite Intelligence Workspace — Stage 0 inspection (read-only)

**Date:** 2026-11-17 ~08:50–09:20 UTC. **Branch:** `feature/satellite-workspace` from `origin/feature/satellite-monitoring`
@ `af4e97d` (`origin/master` does not contain the satellite code). **Nothing was changed** in production, satellite.db,
workers or timers. Fixtures: `tests/fixtures/sat_ui/` (read-only GETs on :8000, user fields redacted, secret values
checked absent).

## 0. Prompt facts that are out of date (verified now)

| Prompt says | Verified 2026-11-17 |
|---|---|
| Fragmentation rule NOT applied; live = generation 1, events 49–57 | **Applied** (owner-approved redetect 06:02–06:18 UTC): live = **generation 2**, current events **58–66**; 49–57 kept as superseded rows. Event 51 → successor **60** (same mask, POTENTIAL_FOREST_LOSS / HIGH). |
| "Did the first daily sync run?" | Yes: run 4 (TIMER) 05:38:50–05:40:08, OK, 14 new acquisitions, 12 requests, 21.67 PU, no errors, provider OK. |
| True colour only for NEW acquisitions | 41 acquisitions have `*_tc.png`: 4 fetched on purpose for open events (run 7, 12.02 PU) + 37 new 8-band S2 of area 4. |
| 2 monitored areas | **4**: BIK-001, Ķekava, area 3 (LVM_GEO "VMD 348-21", added 05:53 via LVM GEO, job #1), area 4 (SECTOR 76, added 08:01 via "Pievienot sektoru", job #2). Both real user actions. |
| Follow `CODING_RULES.md` | **Does not exist** in the repo. `CLAUDE.md` = `AGENTS.md` (identical) and `docs/DEPLOY_RELEASES.md` exist. |
| Design references V1/V2 + screenshots attached | **Not attached in this session.** `docs/design-refs/satellite/` not created. Also needed: the prototype canvas "Forest AI — Satellite Workspace prototypes A/B" (§6a) — not available to me. |

## 1. Active release vs tag, drift

- :8000 `forest-api` and both worker units run `/root/forest_ai/releases/forest-api-satellite-monitoring-20261117T0521Z`.
- 97 runtime files byte-identical to tag `prod-2026-11-17-satellite-monitoring` (`bc8c428`) **and** to branch HEAD
  (`git hash-object`); differ: none; not in git: `pre-activation-check.sh` (release helper), `data` symlink.
- Branch vs tag: 5 docs files only (CHANGELOG, CURRENT_STATUS, KNOWN_BUGS, DEPLOY_RELEASES, Ķekava report). **No drift.**
- Rollback target: `…-rollback8band-20261117T0831Z` (reads 6|8-band S2).

## 2. Live data (read-only, 08:52 UTC)

- `/health`: queue READY, provider OK (last OK 08:04:12), worker IDLE (timers active; next daily run 2026-11-18 05:35 UTC),
  auto_risk false. November: 541 requests / ≈ 893 PU (guard 1,600).
- Runs 1–8: all OK (backfills 1, 2, 5, 8; TIMER 4; MANUAL 3 = redetect gen 1, 6 = redetect gen 2, 7 = true-colour display).
- Counts: acquisitions 691 (S1 OK 367; S2 OK 110, NO_VALID_PIXELS 42, SKIPPED_CLOUD 172), detections 1,146, events 66
  (9 current), radar anomalies 287, candidates 85, jobs 2 (DONE), review log 0, linked risks 0.
- Current events (all area 2 Ķekava): 58 RECOVERED; 59, 63–66 SUSPECTED POSSIBLE_SEASONAL / LOW; 60, 61, 62 SUSPECTED
  POTENTIAL_FOREST_LOSS / HIGH. BIK-001, area 3, area 4: no events.
- Rasters: S1 quicklooks exist for **all 367** S1 acquisitions (`raster.quicklook_png`: VH backscatter dB, grey −25…−5 dB).
  S2: 152 with a false-colour quicklook (B11/B08/B04); 115 rasters 6-band, 37 8-band.

## 3. Context basemap (§4.3 / §6a)

- Forest Map uses **Esri World Imagery** (`server.arcgisonline.com/.../World_Imagery/MapServer/tile`), label "Tiles © Esri".
- Item `10df2279f9684e4a9f6a7f08febac2a9` (arcgis.com, read 2026-11-17): *"This work is licensed under the Esri Master
  License Agreement"*; attribution *"Esri, Vantor, Earthstar Geographics, and the GIS User Community"*. Nothing there grants
  commercial SaaS use without an Esri agreement; third-party sources disagree (free developer account with limits vs
  "requires an ArcGIS license"). **Verdict: not clearly allowed → owner decision. Keep off by default.**
- Side finding: Forest Map's attribution ("Tiles © Esri") is shorter than the item's required attribution line.
- Alternative (LĢIA orthophoto via a service reachable from LVM GEO): the only Latvian services in code are LVM GEO WMS
  `geoserver.lvmgeo.lv` (two endpoints). GetCapabilities **timed out** (15 s) at 09:1x UTC and also at 05:52 in the
  forest-api log → layer list and terms **NOT verified**. Fallback per prompt: OSM.

## 4. Gap list — every §4 / §6a UI field

Legend: ✅ existing field · 🟡 derivable client-side from existing payloads · ❌ missing (smallest read-only addition)

| UI element | Source | Status |
|---|---|---|
| Area name, source, ha, status chip | `/areas/{id}.area` (`name`, `source`, `area_ha`, `data_status`) | ✅ |
| Pēdējais satelīta uzņēmums (per sensor) | `area.last_s1_utc`, `area.last_valid_s2_utc`; or max OK `timeline[].sensing_time_utc` | ✅ |
| Pēdējā veiksmīgā analīze (per area) | `sat_detections.ran_at_utc` (current generation), e.g. area 2 = 06:18:03 | ❌ → `last_successful_analysis_utc` in `/areas/{id}` (MAX of current detections; exact, not approximated) |
| Pēdējā sistēmas pārbaude | catalog search is ONE per run over the union bbox → system-wide: `/health.provider_status` (catalog `last_ok_utc`) + `last_run` | ✅ (global by nature; the UI must say "sistēma", not per area). Optional ❌ `last_system_check_utc` in `/areas/{id}` = start of the last run that included the area |
| Sensor switch S2/S1, per-acquisition composites | `timeline[].sensor`, `quicklook_url`, `truecolor_url` | ✅ (quicklook_kinds derivable → no §6 addition needed) |
| Composite "NDVI-Δ maska" | **no stored raster** of an index difference; only change polygons/masks | ❌ not available → propose: drop the option or map it to compare mode D (polygons only). No image is fabricated. |
| Timeline states | `timeline[].status`, `valid_pct_inside`, `scene_cloud_pct` | 🟡 except the threshold: `min_valid_pct` is only in event `thresholds` (missing for areas without events, e.g. BIK-001) → ❌ add `config.min_valid_pct` to `/areas/{id}` |
| S1 orbit geometry colour / filter | `timeline[].orbit_direction`, `relative_orbit` | ✅ |
| Event onset markers on the right track | area `events[]` has `first_after_time_utc` + `sensor_basis` ("S1+S2" is ambiguous) | ❌ add `onset_acq_id`, `onset_sensor`, `before_acq_ids`, `after_acq_ids` to area `events[]` (from stored history) — or 🟡 one `/events/{id}` call per event |
| Event list: colour dot, class, ha in/out, onset, badges | area `events[]` (`status`, `classification`, `confidence`, `evidence_quality`, `changed_area_ha_inside/_buffer`, `first_after_time_utc`) | ✅ |
| Colour language §4.4 | stored `status`, `classification`, `confidence` | ✅ (one JS function + test) |
| Event card: last clear before / first with change / detected | `/events/{id}.before[]` (max `sensing_time_utc`), `first_after_time_utc`, `detected_at_utc` | 🟡/✅ |
| Compare defaults + pickable pairs | `/events/{id}.before[]`, `after[]`; same-sensor / same S1 geometry from `timeline[]` | ✅ |
| Side metadata (date UTC/local, sensor, platform, product id, valid %, composite) | `before[]`/`after[]`/`timeline[]` | ✅ (Europe/Riga conversion client-side) |
| Contains modified Copernicus Sentinel data [YEAR] | `attribution` (area/event) | ✅ |
| Overview: areas, monitored ha, open, awaiting review | `kpis` + `areas[].area_ha` (sum), `open_suspected_events`, `reviewed_events` | 🟡 |
| Overview: area colour by worst open event | `/map-layer` features (`status`, `classification`, `confidence`) | 🟡 (352 KB; acceptable) |
| Overview: "Jaunākās izmaiņas" (last 10 across areas) | not in `/overview` | ❌ add `latest_events` (10) to `/overview` |
| Overview: last sync, usage vs guard, worker state | `/health` | ✅ |
| §6a story block "Kas mainījās" | `before[]`, `first_after_time_utc`, `changed_area_ha`, `classification`, `compartment_split` | 🟡 (template only, no free text) |
| §6a VMD compartments layer (same as Forest Map) | Forest Map tile endpoint `/api/geodata/forest-map/tiles/forest/{z}/{x}/{y}` (canvas tiles) | ✅ reuse (z ≥ 13 detail; generalized below) |
| §6a `compartments` in `/events/{id}` | VMD `compartments.sqlite` (active release 20261106) has `external_id`, `kvart`, `nog`, `properties.zkat`, `p_cirg`, `p_cirp`; current mask = `change_geojson` (DB) / `event_<id>_mask.npy` | ❌ feasible **API-side** (forest-api Python has shapely, pyproj, numpy): intersect current mask polygons with compartments in the area bbox, ha via pyproj (LKS-92). In-memory cache per (event, generation, dataset version) — the API must not write satellite.db. NOTE: `p_cirg` stores **0.0** for "none" (not NULL): pass as stored, never render as year 0. |
| §6a `polygon_series` in `/events/{id}` | needs stored GeoTIFFs; **forest-api Python has NO `tifffile`** (worker venv2 has it, but no fastapi) | ❌ **blocked as specified** → owner decision, options below |
| On-map callout | event fields | ✅ |
| "Tehniskie dati" drawer + outcome labels | `timeline[].detection` / acquisition `status` codes (NO_BASELINE, SINGLE_DROP, …) | ✅ (label table in JS) |
| Analysis drawer charts (area median) | `timeline[].metrics_inside` (NULL gaps kept) | ✅ |

**Payload size finding:** `/areas/2` (Ķekava) = **2.3 MB** because every event carries the full-resolution
`change_geojson`; `/events/64` = 0.9 MB. For a map-first workspace use the simplified `/map-layer?area_id=` (≤ 150 KB per
area) for the map and fetch the full mask only for the selected event. Optional ❌: `?geometry=0` on `/areas/{id}` to omit
`change_geojson` (read-only flag).

### Decisions needed before Stage 1

1. **`polygon_series`** (tifffile not in the API interpreter). Options:
   a. API spawns the worker venv (`/root/forest_ai_satellite_venv2/bin/python`, read-only computation, existing
      `evidence.mask_series`) on demand + in-memory/JSON cache — no system pip, no worker/timer change; first call for a
      Ķekava event may take tens of seconds (not measured yet).
   b. Install `tifffile` into the forest-api interpreter (system Python) — dependency change; note the 2026-11-10 aider
      incident.
   c. Precompute in the worker after each run (JSON sidecar next to the mask) — **touches the worker, OUT of scope** per §3.
   d. Postpone `polygon_series`; show only the area median in the analysis drawer.
   Recommendation: **a** (behind a timeout, "Nav pieejams" on failure), or d for Stage 1 prototypes.
2. **Context basemap:** Esri World Imagery not clearly licensed for commercial SaaS → off by default / OSM; LĢIA via LVM GEO
   unverified (service timed out).
3. **"NDVI-Δ maska" composite:** no such stored image → drop it or show polygons only.
4. **Design references:** V1, V2, current screenshots and the A/B prototype canvas are needed (not attached).
5. **Fixture size:** 4.1 MB JSON (Ķekava area 2.3 MB). Keep in git as is, or store gzipped?

## 5. Test baseline (this commit, read-only namespace)

`pytest tests/`: **9 failed, 448 passed, 5 skipped, 40 errors** (= the prompt's baseline). All outside the satellite code:
`test_integrations.py` 30, `test_nationwide_geodata.py` 10, `test_vmd_production.py` 8 (worktree lacks
`data/vmd/compartments.sqlite`), `test_john_deere_sync.py` 1. All 9 JS test files pass. Exact failure list kept in the
session scratchpad; Stage 3 compares against it.

## 6. Fixtures (`tests/fixtures/sat_ui/`, 4.1 MB)

`overview`, `health`, `area_1_bik001` (negative control, no events), `area_2_kekava`, `event_51_superseded`,
`event_60_current_successor_of_51`, `event_61`, `event_64` (fragmented, SEASONAL / LOW), `event_58_recovered`,
`map_layer_all`, `map_layer_event_60`. User fields → `<user>`. Areas 3 and 4 (real customer areas added today) are NOT
stored as fixtures; they appear in `overview` / `map_layer_all` only as returned by the API.
