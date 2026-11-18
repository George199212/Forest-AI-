# Satellite Intelligence Workspace — Stage 0 v3 (read-only inspection)

**Date:** 2026-11-18 ~06:30 UTC. **Host:** NEW 64.225.79.80. **Branch:** `feature/satellite-workspace` (v2 work: Stage 0
`bb49fbb`, read-only API additions `7c5edfe`, prototype B `71d2737`/`3068e99`). No code, DB, unit or service was changed.
Live data read with `?mode=ro` SQLite URIs and authenticated GETs on 127.0.0.1:8000. Secrets: referred to by name only.

## 0. Summary for the owner (what changed vs the v3 prompt's assumptions)

| v3 premise | Verified 2026-11-18 | Consequence |
|---|---|---|
| Copernicus 401 `invalid_client`, last OK 2026-11-11 | **Not current.** catalog OK 05:33:40, process OK 05:34:03 UTC today, no stored error; `sat_request_log` has 560 rows, **0 × 401 ever**. KNOWN_BUGS #8 already closed it (2026-11-16): the banner was a synthetic sandbox state. | A1: nothing to fix. |
| Queue schema missing (`sat_jobs`, `risk_carried_from_event_id`, `risk_carry_overlap`) | **Present** (Stage 4 migration 2026-11-16 15:52). Jobs 1–2 (ADD_AREA) DONE; jobs timer 208 starts since boot, 0 failures. | A2: nothing to run. |
| Swipe uses `<img>`/CSS boxes | **No.** One Leaflet map, two `L.imageOverlay` on the same bounds, after-pane clipped. Image content is pixel-aligned (phase correlation dx=dy=0). Defect is presentation (§3). | A3 is a UI fix, smaller than assumed. |
| Event 62 "Laba" contradicts clouds in the after image | Event EQ = **best** EQ over its after-history (`pipeline.py:901`). Event 62 is GOOD **only via S1 radar acq 196** (2026-07-29); both S2 afters (327, 331) are LIMITED. Per-polygon SCL: **100 % clear** on 327 and 331. | Track B as specified would **not** change event 62. The real defect: UI shows event-level quality next to a specific S2 image. Owner decision D2. |
| Base `bc8c428` | :8000 now runs `b86ebf4` (= `bc8c428` + Integrations page removed, tag `prod-2026-11-18-remove-integrations-page`). Satellite worker units still run `bc8c428` (0521Z folder). | Stage C must merge/rebase on `b86ebf4`; merge test: clean. |

## 1. Copernicus state (A1)

- `sat_provider_status`: `catalog` last_ok `2026-11-18T05:33:40Z`, `process` last_ok `2026-11-18T05:34:03Z`, `last_error` NULL for both.
- `sat_request_log` by day: 2026-11-10 102×200, 11-11 200×200, 11-17 239×200, 11-18 19×200. No request 11-12…11-16 (pre-Stage-4 period
  on OLD; no worker timer then). No 401 in any row. Journal on NEW starts at boot 2026-11-17 12:28 UTC; every 401 in it is dashboard
  Basic Auth (`GET /`), none from CDSE.
- Env names read by the satellite code: `SENTINEL_CLIENT_ID`, `SENTINEL_CLIENT_SECRET` (+ `SAT_DATA_DIR`, `SAT_DB_PATH`,
  `SAT_RASTER_DIR`, `FOREST_DB_PATH`/`DB_PATH`, `SAT_FOREST_DB*`, `SAT_GEODATA_ACTIVE`, `SAT_WORKER_VENV`).
  `forest-api`, `forest-satellite-sync`, `forest-satellite-jobs` all load `EnvironmentFile=/root/forest_ai/.env` (same file).
- Rotation: not needed per evidence. OAuth client expiry date: NOT VERIFIED (not visible without the CDSE dashboard; owner).

## 2. Releases, runs, quota

- :8000 `forest-api` → `/root/forest_ai/releases/forest-api-remove-integrations-page-20261118T0532Z` (`b86ebf4`). Workers →
  `…satellite-monitoring-20261117T0521Z` (`bc8c428`). Satellite code identical in both (api.py and `satellite_monitoring/` unchanged).
  Live `assets/sat-monitoring.js` == `bc8c428`. Drift live-vs-branch: none beyond `index.html` + logo (Integrations removal).
- `sat_runs` since 2026-11-17: #4 TIMER 05:38 (OLD) OK 12 req 21.67 PU · #5 BACKFILL area 3 OK 106 req 2.91 PU · #6 MANUAL redetect gen 2
  0 PU · #7 MANUAL true colour 4 req 12.02 PU · #8 BACKFILL area 4 OK 117 req 3.81 PU · **#9 TIMER 2026-11-18 05:33–05:35 OK, areas 1–4,
  window 11-08…11-18, 39 new acquisitions, 19 requests, 20.83 PU** (first daily run on NEW).
- Month (Nov): 560 requests / 914.03 PU vs guard 4,800 req / 1,600 PU (80 % of 6,000 / 2,000, `config.py:97-100`).
  Run 9 cost 20.8 PU, ~5× the 3.9 PU/day estimated on 2026-11-17 (10-day window × 4 areas; Ķekava 631×624 px dominates).
  At ~21 PU/day the month ends near ~1,165 PU (< guard). NOT VERIFIED whether future runs keep a 10-day window.
- Events after run 9: 59, 63, 64 now `after_acq_id` 711; 65, 66 → 708 (new acquisitions extend open events). 55 superseded (gen 1).

## 3. Swipe root cause (A3) — event 62

Code (`assets/sat-monitoring.js`, live == `bc8c428`): `swipeMap` L986–1005; `pickImages` L839–845; `imgUrl` L920; `focusBounds` L947–954;
CSS `assets/sat-monitoring.css` L49–50.

Measured (headless Chromium 1440×900, live :8000, read-only): before = acq 299 (S2 2026-06-29, true colour), after = acq 331
(S2 2026-08-21, true colour, valid 82.055 %). Both `<img class=leaflet-image-layer>` have **identical** rectangles at 3 zoom levels
(302×298 → 2414×2388 → 19317×19104 px, same x/y). Both PNGs 631×624 on the same area grid; phase correlation of image gradients:
299↔331 dx=0 dy=0 (peak 0.43); true colour vs false colour of the same acquisition dx=dy=0. **Images are georeferenced and aligned.**

What the owner sees, and why:
1. **No divider on the map.** The split is a `<input type=range>` *below* the map (L936); the clip edge is at a fraction of the
   *container* width (L999–1001), not shown by any line/handle. At the initial view the 3,670 ha grid is 302 px wide inside a
   1148 px container, so at 50 % the after image shows only its right 101 px and the before its left 201 px → "different sizes".
2. **Empty dark area.** Outside the request grid there is no basemap in the swipe map; the container background is dark → large
   empty area right/left of the image.
3. **Black wedges inside the image.** Quicklook/true-colour PNGs are RGB without alpha (PNG colour type 2); no-data/swath-edge pixels
   are opaque black instead of transparent.
4. **"Drift" on zoom.** The divider stays at a fixed container x while wheel-zoom scales the image around the cursor, so the split
   moves to a different part of the scene. The clip is recomputed on `move zoom resize` but not during the CSS zoom animation
   (`zoomanim`), so the edge lags during animation.
5. **Initial view = whole grid** for event 62: its change polygons are spread over the box, so the padded bounds contain the grid
   and `focusBounds` returns the full grid (L953).

Evidence: `docs/evidence/satellite-stage5-v3/62-swipe-{page,z0,z1,z2,z2-r80}.png` (not versioned).
Fix (A3, small): draw the divider + handle on the map (drag on the map, clip in container px), clip also on `zoomanim`, start at
event focus / first polygon, transparent no-data (alpha from `dataMask` is not in the PNG → either CSS `mix-blend` workaround —
not exact — or regenerate PNGs with alpha in the worker; owner choice), basemap under the grid. No change to bounds needed.

## 4. Evidence quality and per-polygon clear pixels (Track B)

- Rule: `detection.py:156-166` — GOOD if after `valid_pct_inside` ≥ 80, baseline ≥ 2, gap ≤ 30 d; LIMITED ≥ 60 / ≥ 1 / ≤ 60 d; else
  POOR (`config.py:175-176`). Event value = **max** over `after_acq_history_json` (`pipeline.py:901`). `valid_pct_inside` is
  area-wide.
- Event 62 history: 327 S2 LIMITED, 331 S2 LIMITED, 196 S1 GOOD → event GOOD. Event 60: S1 GOOD ×9, S2 LIMITED ×3 → GOOD.
  Event 55: S1/S2 GOOD (from 366, 370, S1) → GOOD.
- Stored data: every S2 GeoTIFF has 6 float32 bands `B04 B08 B11 B12 SCL dataMask` on the area grid (631×624, 10 m, CRS84 bbox in
  `sat_monitored_areas.grid_json`); S1: `VV VH dataMask`. **Per-polygon sampling is feasible from stored rasters, no provider call.**
- Measured SCL inside event polygons (`change_geojson` rasterised on the grid; clear = SCL 4/5/6):

| event | acquisition | area valid % | polygon clear % | not clear |
|---|---|---|---|---|
| 62 (8.9 ha) | 299 before 06-29 | 99.2 | 100.0 | – |
| 62 | 327 after 08-14 | 99.2 | 100.0 | – |
| 62 | 331 after 08-21 | 82.1 | 100.0 | – (50 m ring: 97.7 %, 2.0 unclassified, 0.3 cloud) |
| 60 (7.1 ha) | 325 after 08-11 | 65.7 | 100.0 | – |
| 60 | 331 after 08-21 | 82.1 | 100.0 | – |
| 55 (162.9 ha, superseded) | 366 after 10-18 | 80.9 | 88.8 | shadow 3.5, cloud 6.2, cirrus 1.5 |
| 55 | 370 after 10-27 | 97.8 | 98.5 | unclassified 1.5 |

  → With any reasonable threshold (e.g. LIMITED < 90 %, POOR < 70 %), **no current event would be downgraded**; only individual S2
  acquisitions like 366 for event 55. SCL is known to miss thin cloud shadow — the owner's visual impression of shadow near 62's
  polygons is NOT confirmed by SCL (not independently verified).
- **Blocker for a read-only API path:** the forest-api interpreter (`/usr/bin/python3`) has no `tifffile`, and PIL cannot open the
  6-band float32 TIFF (verified). Same blocker as v2 `polygon_series`. Without a new dependency the value can only be computed in the
  worker (`/root/forest_ai_satellite_venv2`, has tifffile) and stored. **Existing places, no schema change:** per-entry fields in
  `sat_change_events.after_acq_history_json` (already holds per-acquisition `evidence_quality`) and `sat_detections.details_json`.

## 5. Search / lookup

- `/api/sat-monitoring/lookup` = "is (source, source_ref) monitored?" only (`store.py:614-626`). Not a geocoder.
- Forest Map search (reuse): 11-digit cadastre → `GET /api/geodata/vmd/cadastre?kadastrs=&limit=&offset=`; VMD source id
  (`VMD:…`) → `GET /api/geodata/forest-map/feature?id=`; municipality → `/api/geodata/forest-map/catalogue?municipality=`;
  coordinates → client-side parse (`forest-map.js` `goCoordinates`: split on `[,;\s]`, lat 55–59 / lon 20–29, WGS84 only; a decimal
  comma breaks it) then `GET /api/geodata/forest-map/identify?lat&lon&zoom`. Sector code → `/api/sat-monitoring/sectors`.
  These read the local catalogue (work while LVM GEO is down — verified 2026-11-17).
- **LKS-92 (EPSG:3059): not supported** by any search endpoint. CLAUDE.md allows conversion only with `pyproj` /
  `forestry_io.py` → needs a small server-side read-only parse (gap G7) or "WGS84 only" hint. VMD "kv-nog" free text: not supported
  (only the source id).

## 6. POST /areas (add flow)

- `AreaIn {source, source_ref, name, geometry?}`; API sources `SECTOR` (geometry from the sector) and `LVM_GEO` (geometry required,
  one Polygon; a MultiPolygon with >1 part → 422) — `store.py:679-707`. `EVAL_BBOX` CLI-only. Dedup key `ADD_AREA:{source}:{ref}`; 409 if
  already monitored. Queued → jobs worker → backfill. Several VMD compartments = several areas (or one merged single polygon).
- **No quota pre-check at queue time.** The guard runs before every provider request in the worker (`pipeline.py:127-141, 212-213`);
  a stopped job ends `STOPPED_BY_GUARD`. Current month usage + guard is already in `/health` (`store.py:565-571`).
- PU estimate: per request derivable offline (`provider.estimate_pu(sensor, width, height)`), **total backfill not** (needs a
  Catalog call to count acquisitions). Observed: area 3 (0.53 ha) 106 req / 2.91 PU; area 4 (0.21 ha) 117 req / 3.81 PU.
  Proposal: show "≈ observed for a small area" only as history, or "Nav pieejams" (owner D5).

## 7. Linked Forest AI data (§5.7 block 6)

- Exists: `satellite_monitoring/context.py` computes `operational_context` at detection time from **forest_ai.db opened read-only**
  (`sdb.forest_ro()`), stored in `sat_change_events.gps_context_json`, returned as `operational_context` by `GET /events/{id}`.
  Sources: `session_track_points` (spatial, polygon+buffer), `vehicle_gps_pings` (spatial), `work_sessions` (check-in point or
  sector), `work_photos`, `timber_movements`, `truck_reports` (by sector name; `count: null` + reason when the area is not a SECTOR).
  Three states are distinguishable: `null`+reason → "Nav sasaistes"; `0` → "Nav datu šajā logā"; `>0` → value.
- Gaps vs §5.7: window is the event window (first before … last after), not [last clear − 7 d, first after + 7 d]; snapshot at
  detection time (not live); ids only (no entity names, first/last time); `sector_equipment` (assigned equipment) not included;
  sector link is by **area name == sector name** (`context.py`: `sector = area["name"]`), although SECTOR areas store the sector id in
  `source_ref` — fragile for renamed sectors (area 4's name is a long VMD label). `context_label: "UNREGISTERED_CHANGE_CANDIDATE"` is
  an internal label — must not be shown as a statement.
- forest_ai.db tables (from `database.py`): `sectors, sector_employees, sector_vehicles, sector_equipment, vehicle_gps_pings,
  live_locations, work_sessions, session_track_points, work_photos, timber_movements, truck_reports, risks, …`.

## 8. Basemap (§5.4)

- Esri World Imagery is used by Forest Map (`forest-map.js:118`) and LVM GEO (`lvm-geodata.js:277,281`). Terms (v2 Stage 0, read
  2026-11-17): item licensed under the Esri Master License Agreement; no explicit grant for a commercial non-ArcGIS SaaS → **not
  enabled by default**. Attribution line in Forest Map is shorter than required (KNOWN_BUGS follow-up).
- LĢIA orthophoto: **NOT VERIFIED.** No orthophoto endpoint exists in the code. LVM GEO WMS GetCapabilities timed out today
  (25 s, HTTP 000), as on 2026-11-17. No other endpoint was probed (no new external integration without owner approval).
- Fallback: OSM at low opacity under Sentinel at area zoom.

## 9. Display name (§5.8)

- Field `sat_monitored_areas.name` (area 2 = `Kekava positive control`, source `EVAL_BBOX`, ref `kekava-2026-vmd-clearcuts`).
- **No rename API** (routes: GET overview/areas/events/file/sectors/lookup/map-layer/health; POST areas, areas/{id}/stop, fetch,
  events/{id}/review). Option (a) = one-row `UPDATE sat_monitored_areas SET name=? WHERE id=2` with backup + audit note (no schema
  change; the name is not used as a key by the satellite code — `context.py` uses it as sector name only for SECTOR areas).

## 10. Fixtures (`tests/fixtures/sat_ui/`, gzipped, user fields → `<user>`, no `.env` value in any file — checked)

New today (prefix `v3_20261118_`): `overview`, `health`, `area_1_bik001` (0 events — honest negative), `area_2_kekava`,
`event_55_superseded`, `event_60`, `event_62`. Captured from live :8000 = `bc8c428` API, i.e. **without** the v2 read-only additions
(`7c5edfe`: `last_successful_analysis_utc`, `latest_events`, `compartments`, `successor`). v2 fixtures (2026-11-17) unchanged.

## 11. Gap list (§5 field → source)

| UI field | Source today | Gap / smallest read-only addition |
|---|---|---|
| Area display name | `areas[].name` | G1 rename (D3), no API change |
| Before/after thumbnails per area | events[].before/after quicklook URLs in `/areas/{id}` | G2 `/overview`: thumbnail acq ids per area (§7 allowed) |
| Worst open event per area / initial view | events list | client-side from `/areas` + colour table; `/overview` per-area severity optional |
| Last satellite acquisition | `timeline` in `/areas/{id}` (max OK sensing_time) | client-side |
| Last successful analysis | `last_successful_analysis_utc` (v2 `7c5edfe`, not live) | ship with Stage C |
| Last system check | `/health` provider last_ok | client-side |
| Copernicus state, PU/requests vs guard, worker | `/health` | – |
| Latest 10 events | `latest_events` (v2, not live) | ship with Stage C |
| Search: cadastre / VMD id / municipality / WGS84 | Forest Map endpoints (§5) | reuse |
| Search: LKS-92 | – | G7 server-side pyproj parse, or "WGS84 only" hint (D6) |
| Add flow geometry | POST /areas SECTOR / LVM_GEO single polygon | – ; multi-compartment = one area per polygon |
| Expected PU of an add | – | D5 ("Nav pieejams" or per-request estimate only) |
| Timeline S1/S2, outcomes | `timeline` + acquisitions | – |
| Compare pairs, composites, product id, valid % area | event before/after rows | – |
| Valid % inside event polygon | – | G4 Stage B worker value (D2) |
| Evidence-quality reasons | `after_acq_history_json[].evidence_quality` (per acq) | G5 expose per-acq EQ + basis ("GOOD via S1 2026-07-29") in `/events/{id}` |
| Compartments (VMD) | `compartments` (v2, not live) | ship with Stage C |
| polygon_series | – | blocked (no tifffile in API python) — v2 decision pending |
| Linked Forest AI data | `operational_context` | G6 `/events/{id}/related`: live ±7 d window, names/first-last, `sector_equipment`, sector by id |
| Review history / actions | `review_log`, POST review | – |

## 12. Tests (re-measured today)

- pytest, system python, `feature/satellite-workspace` @ `3068e99`: **9 failed, 454 passed, 5 skipped, 40 errors**; failure+error
  set identical to `bc8c428` (and to `b86ebf4`: 9/448/5/40). Node: 10/10 test files pass.

## 13. Owner decisions needed before Stage A/B/C

- **D1 (A1/A2):** confirm no action (Copernicus OK, schema present).
- **D2 (Track B):** per-polygon SCL would not downgrade 62/60/55. Choose: (a) Stage B as specified (worker-side, stored in existing
  JSON, no schema change; changes nothing today, guards future cloudy events) and/or (b) UI shows **per-image** quality and the basis
  of the event quality ("Laba — no S1 radara 2026-07-29; S2 attēli: ierobežota"). Recommendation: (b) now in A3/C, (a) later.
- **D3 (display name):** option (a) one-row UPDATE — which name? (e.g. "Ķekava — pārbaudes teritorija").
- **D4 (basemap):** Esri off by default (licence); LĢIA unverified — provide the orthophoto service/licence or accept OSM fallback.
- **D5 (PU of an add):** "Nav pieejams" + current month vs guard, or per-request estimate.
- **D6 (LKS-92):** add server-side pyproj parse (G7) or WGS84 only.
- **D7 (A3 scope):** ship the swipe fix as a small release first (divider/handle on map, zoomanim clip, event focus, OSM under grid);
  transparent no-data needs PNG alpha → worker regeneration (separate approval) or leave black and say so.
- **D8 (base):** Stage C on `feature/satellite-workspace` merged with `b86ebf4` (clean merge verified).
- Design references (§ "Design references") are not attached; `docs/design-refs/satellite/` does not exist. `CODING_RULES.md`
  does not exist in the repo.
