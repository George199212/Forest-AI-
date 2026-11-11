TASK: Forest AI — build the new section "Satellite Monitoring" (Sentinel-1 + Sentinel-2)
This single prompt replaces ALL earlier satellite prompts (including the ChatGPT "Satellite
Intelligence Engine" prompt and Codex prompts). Where they conflict, this prompt wins.

EXPLICIT NON-GOALS FOR THIS RELEASE (do not build, do not propose as part of this task)
- No multi-tenant / client-isolation work (that program is paused); MAIN instance only.
- No full-scene downloads via OData/S3 and no openEO: per-area clipped Process API requests are
  cheaper for our area sizes and need no scene storage. Keep a thin provider interface
  (discover / fetch_area_raster) so another provider can be added later.
- No object storage: rasters are small per-area files on local disk.
- No editing of API credentials in the UI (credentials stay in .env, set manually by the owner).
- No priority queue infrastructure: one daily discovery call covers all areas; priority only
  orders processing when the quota guard is close to the limit.

ROLE
Senior engineer joining an existing production codebase. Inspect first, smallest safe changes,
tests, no invented files/APIs/capabilities. Every stage ends with STOP and waits for "approved".
Auto mode must be OFF.

======================================================================
1. VERIFIED CURRENT STATE (read-only inspection 2026-11-10, /tmp/grant_readiness_inspection.md)
======================================================================
- Only on-demand Sentinel-2 true-colour/NDVI via Copernicus Process API exists (/api/satellite/*).
  Images go straight to the browser; nothing is persisted.
- Sentinel-1 provider code and the satellite decision engine (satellite_intelligence) have NO callers.
- Stored satellite data: 3 demo rows + 6 manually uploaded snapshots. No real imagery stored.
- No scheduler. Cloud handling = whole-scene cloud limit (30/50%), no per-pixel mask.
- MAIN, RM, Ingka share one Copernicus account (SENTINEL_CLIENT_ID / SENTINEL_CLIENT_SECRET).
- BIK-001 = hand-drawn 4-corner polygon, ~50.4 ha.
- demo_scenarios.py contains a SIMULATED "Sentinel-2 change detection" — must never be shown as real.
- Old LKS-92→WGS84 helper functions (_lks92_to_wgs84 / lks92_to_wgs84) are wrong by 150–190 km.

======================================================================
2. PRODUCT GOAL
======================================================================
For every monitored area, Sentinel-1 and Sentinel-2 acquisitions are discovered and stored
automatically, accumulated over time, changes are detected per pixel (inside the approved area AND
in a buffer ring outside it), correlated with operational evidence (GPS, work sessions, photos,
timber movements, truck reports), shown in a dedicated dashboard section, and turned automatically
into an existing-compatible Risk with an AI explanation — which a human then reviews.
All automated output is "SUSPECTED change" — never "violation", "illegal logging" or "confirmed".
Detection confidence and evidence quality are separate fields; neither states the cause.
Never accuse a contractor automatically.
Keep raw evidence / processed data / interpretation / human decision visibly separate.
Missing data is NULL with a reason — never 0.

Users: operator/dispatcher (daily review), management (status), grant reviewers (evidence).

======================================================================
3. SCOPE AND HARD RULES
======================================================================
- MAIN instance only: /root/forest_ai, port 8000, forest-api.service. RM, Ingka, review untouched.
- Worktree /root/wt/satellite-monitoring, branch feature/satellite-monitoring, based on the commit
  of the ACTIVE production release (identify from systemd WorkingDirectory/drop-ins first).
- Do NOT change: existing /api/satellite/* behaviour, demo_scenarios.py, services/integrations/demo/*,
  other sections' UI, Forest Map page. LVM GEO page: only the single button in 6.B.
- No hardcoded credentials; read SENTINEL_CLIENT_ID/SECRET from env; never print them.
- No network in tests. Copernicus calls only after explicit approval (Stage 1 gate).
- No commit to master, merge, push, service restart, unit install or DB migration without approval.
- Additive changes only. Production forest_ai.db opened READ-ONLY (sqlite URI mode=ro) until Stage 4.
- Do not install packages without approval; list what is missing.
- Never print secret values; refer to variable names only.

======================================================================
4. STAGE 0 — INSPECT (no code). Report with file:line, then STOP.
======================================================================
1. CDSE token code in satellite_intelligence/providers/sentinel.py and api.py — reuse it.
2. Existing satellite tables/functions (satellite_observations, satellite_monitoring_score,
   risk_rules SATELLITE_UNREGISTERED_CHANGE): reuse or not, with reasons.
3. Sector polygon storage: table, column, format, CRS. Confirm BIK-001.
4. LVM GEO page: how a selected compartment/sector polygon is held (structure, identifiers, CRS),
   which code converts LKS-92 → WGS84 correctly (show file:line and the library used), and the
   smallest place to add one button.
5. GPS tables usable for correlation (work_sessions, session_track_points, vehicle_gps_pings,
   live_locations): time and coordinate columns.
6. Sidebar/nav structure in index.html, section routing, i18n mechanism (RU/LV/EN), JS test setup.
7. numpy / tifffile availability, Python version.

======================================================================
5. STAGE 1 — PIPELINE, STORAGE, CHANGE DETECTION (backend only)
======================================================================
5.1 Storage — separate SQLite file data/satellite.db (isolated, easy rollback).
Rasters: data/satellite/<area_id>/<S1|S2>/<YYYY-MM-DD>_<product>.tif + PNG quicklook, sha256 each.

Tables:
- sat_monitored_areas: id, source('SECTOR'|'LVM_GEO'), source_ref, name, geometry_geojson (CRS84),
  area_ha, added_by, added_at_utc, active, removed_at_utc. Created only by explicit user action.
- sat_acquisitions: id, monitored_area_id, sensor('S1'|'S2'), product_id, sensing_time_utc, platform,
  orbit_direction, relative_orbit (S1), scene_cloud_pct (S2), processing_params_json, fetched_at_utc,
  status('OK'|'NO_VALID_PIXELS'|'SKIPPED_CLOUD'|'ERROR'), attempts, error_text, raster_path,
  raster_sha256, quicklook_path, pu_spent, pu_is_estimate.
  UNIQUE(monitored_area_id, sensor, product_id). Append-only (status may change only on retry).
- sat_area_metrics: acquisition_id, metric('NDVI'|'NBR'|'VV_DB'|'VH_DB'|'VALID_PCT'), mean, median,
  p10, p90, n_valid_pixels, n_total_pixels. No valid pixels → NULL + reason.
- sat_change_events: id, monitored_area_id, sensor_basis('S1'|'S2'|'S1+S2'), detected_at_utc,
  before_acq_ids, after_acq_id, changed_area_ha, n_changed_pixels, largest_cluster_ha,
  change_geojson, thresholds_json, confidence('LOW'|'MEDIUM'|'HIGH'), seasonal_caveat,
  gps_context_json, status('SUSPECTED'|'REVIEW_CONFIRMED'|'REVIEW_REJECTED'|'FIELD_CHECK_REQUESTED'),
  risk_id, reviewed_by, reviewed_at_utc, review_note.
- sat_review_log: every review action and undo (append-only audit).
- sat_runs: id, trigger('TIMER'|'MANUAL'|'BACKFILL'), started_at, finished_at, areas, new_acquisitions,
  requests_made, pu_spent, errors_json.

5.2 Geometry
- Must be real WGS84. Sector polygons as stored (verify CRS). LVM GEO polygons converted ONLY with
  the correct converter found in Stage 0. If none exists → LVM GEO areas BLOCKED (report, do not guess).
- Validation: valid polygon, inside Latvia bbox, area 0.1–5000 ha.
- Buffer ring: each request covers the polygon bbox expanded by buffer_m (config, default 100 m).
  Locally rasterize the polygon (numpy point-in-polygon on pixel centres) into an INSIDE mask;
  pixels outside the polygon but within buffer_m = BUFFER mask. Everything else is ignored.
  This lets the engine report changes outside the approved boundary.

5.3 Acquisition (quota-efficient)
- Discovery: Sentinel Hub Catalog API on CDSE (cite the documented endpoint in code comments),
  collections sentinel-2-l2a and sentinel-1-grd. ONE search per collection per run over the union
  bbox of all active areas; intersect footprints with each area locally.
- Fetch only products not yet stored. S2 with scene cloud > 80% (config) → SKIPPED_CLOUD, NULL metrics.
- Process API per (area, product), clipped to the area polygon (GeoJSON, CRS84), ~10 m
  (pixel size in degrees from latitude, recorded), FLOAT32 GeoTIFF.
  * S2 inputs B04, B08, B11, B12, SCL, dataMask → NDVI, NBR, NDMI. Valid pixel = dataMask==1 AND
    SCL in config set (default {4,5}); this excludes cloud shadow (3), clouds (8,9), cirrus (10),
    snow (11), no-data/saturated (0,1). Observation quality: VALID_PCT per INSIDE and BUFFER masks;
    an acquisition with VALID_PCT < min_valid_pct (config, default 60) is stored but never used
    as a baseline or as an "after" image.
  * S1 inputs VV, VH, dataMask, IW mode, orthorectify=true; record backCoeff and DEM actually used;
    dB computed locally.
- Record PUs from the response if provided, else store an estimate with pu_is_estimate=1.
- Guards: monthly PU budget (default 2000) and monthly request budget (default 6000); stop at 80%
  and record in sat_runs. Max 2 requests/second; exponential backoff on 429/5xx; failed product
  retried on next run, max 3 attempts, then ERROR.
- Concurrency lock (one run at a time). Same code path for timer, manual and backfill.

5.4 Change detection v1 (thresholds INITIAL, in config, must be calibrated)
- S2: per-pixel baseline = median of up to 3 previous valid acquisitions within 90 days;
  changed if dNBR <= -0.15 AND dNDVI <= -0.10.
- S1: compare ONLY same orbit_direction + relative_orbit; 3x3 mean filter; baseline = median of up to
  3 previous same-geometry acquisitions; changed if VH drop >= 2.0 dB.
- S2 bare-soil indicator: NDMI drop recorded as a supporting metric (config threshold, default -0.10).
- 8-connected clusters (numpy only). Event if largest cluster >= 0.3 ha. change_geojson = cluster outlines.
- For each event: changed_area_ha_inside, changed_area_ha_buffer, pct_of_area_affected,
  max_distance_outside_boundary_m (pixel-distance approximation, documented).
- Confidence (detection): S1 only LOW; S2 only MEDIUM; S1 and S2 both within 24 days HIGH.
- Evidence quality (separate field): GOOD / LIMITED / POOR from valid %, number of baseline
  acquisitions, and time gap between before and after.
- Classification (one of): POTENTIAL_FOREST_LOSS, POTENTIAL_CHANGE_OUTSIDE_BOUNDARY,
  POSSIBLE_SEASONAL_OR_ENVIRONMENTAL (Nov–Mar, snow, single S1 drop not persisting),
  INSUFFICIENT_EVIDENCE. Rules in config and documented.
- S1 persistence: a radar-only drop must persist in >= 2 consecutive same-geometry acquisitions
  before it can become an event; a single drop is stored as an observation only.
- Sentinel-1 keeps working when Sentinel-2 is cloudy; events never wait for both sensors.
- Ongoing change: a new detection whose change polygon overlaps an existing open event by >= 30%
  within 60 days UPDATES that event (adds the acquisition, recomputes area) instead of creating a new one.
- Operational context for the event window (before .. after), counts and ids only: worker/vehicle/
  equipment GPS points and work sessions inside polygon+buffer, field photos, timber movements and
  truck reports for the sector. No activity → "unregistered change" candidate;
  activity present → "change during registered work". Stored in gps_context_json.

5.5 CLI
- python3 -m satellite_monitoring.backfill --area <id|sector name> --from D --to D --sensors S1,S2 [--dry-run]
  --dry-run lists products that would be fetched and prints, per area: pixels, PU per S2 request,
  PU per S1 request, expected acquisitions per 30 days, PU and requests per 30 days, and how many
  such areas the free quota (10,000 PU + 10,000 requests per month) would allow.
- python3 -m satellite_monitoring.report --area <id> → Markdown timeline + evidence paths.

5.6 Tests (no network)
Cloud → NULL not 0; S1 different orbits never compared; cluster area math; threshold edges;
quota and request guards; idempotent re-run; retry/ERROR logic; GPS window logic; geometry validation;
LKS-92 conversion sanity (a known point lands inside Latvia).

STOP: diff stat, test results, missing dependencies, --dry-run for BIK-001 2026-08-01..2026-11-10
(S1+S2) with PU and request estimates.
After "approved": backfill BIK-001 = NEGATIVE control (no damage was found on the ground after the
2026-10-09/10 storm → expected: no change event) and the POSITIVE-control area I will provide.
Write docs/SATELLITE_STAGE1_REPORT.md (acquisitions per sensor, valid %, events, PU/requests spent,
limitations, raw/processed/interpretation labels). STOP.

======================================================================
6. STAGE 2 — API, SCHEDULER, RISK INTEGRATION
======================================================================
6.A API (Basic Auth like all routes)
- GET  /api/sat-monitoring/overview        per area: source, last S1, last valid S2, valid %, status,
                                           open SUSPECTED events, gaps
- GET  /api/sat-monitoring/areas/{id}      timeline (NULL gaps kept), acquisitions, events
- POST /api/sat-monitoring/areas           {source, source_ref, name, geometry} → validate, dedup
                                           (one active area per source_ref), queue 120-day backfill
- POST /api/sat-monitoring/areas/{id}/stop sets active=0, history kept
- POST /api/sat-monitoring/fetch           {area_id | all} manual "Fetch now" (same code path, lock)
- GET  /api/sat-monitoring/events/{id}     event + before/after quicklooks + change_geojson + GPS context
- GET  /api/sat-monitoring/file/{acq_id}/{kind}  quicklook only; path taken from DB, never from input
                                           (path-traversal tests required)
- AUTOMATIC RISK (existing Risk Engine, no separate alert system):
  when an event has classification POTENTIAL_FOREST_LOSS or POTENTIAL_CHANGE_OUTSIDE_BOUNDARY and
  confidence >= auto_risk_min_confidence (config, default MEDIUM), the engine calls the existing
  add_incident with entity_type='SATELLITE' and rule_code 'SATELLITE_UNREGISTERED_CHANGE' (no
  operational activity) or 'SATELLITE_CHANGE_DURING_WORK' (activity present); existing dedup;
  the AI recommendation is attached like for every new risk (prompt gets only the stored metrics,
  classification, confidence, evidence quality and context — no invented facts; text must say
  "suspected"); risk_event actor='satellite_monitoring'; risk_id stored on the event.
  Ongoing-change updates add a risk_event to the SAME risk instead of a new risk.
  LOW confidence / other classifications → event only, visible in the section, no risk.
  The risk then follows the existing approval / Telegram / AI Inspector workflows unchanged.
- POST /api/sat-monitoring/events/{id}/review {decision: CONFIRM|REJECT|FIELD_CHECK|UNDO, note}
  CONFIRM → event REVIEW_CONFIRMED (creates the risk if none exists yet, e.g. LOW confidence).
  REJECT → event REVIEW_REJECTED and a risk_event on the linked risk (risk status handled by the
  existing workflow, not deleted). FIELD_CHECK → Telegram message to the dispatcher via the existing
  send path. UNDO → previous state per existing undo rules. Everything audited in sat_review_log.
- GET  /api/sat-monitoring/health          last run, PU and requests this month, errors, lock state
6.B Scheduler: repo files for forest-satellite-sync.service (oneshot) + .timer (daily, local morning).
ExecStart uses the isolated worker venv /root/forest_ai_satellite_venv2/bin/python
(config.WORKER_VENV, built from requirements-satellite.lock; decided 2026-11-11).
Prepare only — do NOT install.
Tests: auth required on every route, path traversal, validation, dedup, review/undo, risk creation.
STOP with diff + tests.

======================================================================
7. STAGE 3 — UI
======================================================================
Use existing styles, Leaflet, Chart.js, i18n (RU/LV/EN keys). No other section changes.
7.A New sidebar item "Satellite Monitoring" under MONITOR (existing items unchanged).
1. Overview: KPI strip (monitored areas, with recent observations, awaiting observations, open
   suspected events, risks created, last successful sync, failed fetches); map of all monitored
   areas with boundaries and open change polygons; table of areas (name, source, last S1, last
   valid S2, valid %, status badge: No change / Suspected change / No valid data / Not configured,
   open events) + "Fetch now" + "Add sector" (sectors with a polygon).
2. Area view: map (polygon, buffer ring, selected event change_geojson inside/outside colours);
   timeline chart NDVI, NBR, NDMI (S2) and VH/VV dB (S1) with no-data dates as gaps, never 0,
   event markers; before/after viewer (side-by-side AND swipe, change overlay toggle, dates,
   source, valid %); acquisitions list with product_id, sensing time, valid %, provenance;
   "Stop monitoring".
3. Event panel: classification, sensor basis, changed ha inside / in buffer, % of area, max distance
   outside boundary, confidence and evidence quality as separate badges, seasonal caveat,
   operational context with links (GPS sessions, photos, timber, trucks), linked risk,
   raw/processed/interpretation labels; buttons Confirm, Reject, Request field check, Undo.
   Wording "Suspected change" only.
3b. Processing monitor: runs list (trigger, duration, new acquisitions, requests, PU, errors),
   monthly PU and request usage vs guard, lock state, provider availability (last token/catalog OK).
3c. Settings (read-only display in this release): thresholds, buffer, budgets, schedule.
   Editing thresholds is a later task; credentials are never shown or edited.
4. Empty states: no areas, no polygon, no credentials, no data yet, backfill in progress.
5. Under every satellite image: "Contains modified Copernicus Sentinel data [YEAR]".
7.B LVM GEO — ONE button only: "Add to satellite monitoring" in the selected-object panel →
POST /api/sat-monitoring/areas with source 'LVM_GEO'. Shows "Already monitored" if active.
No other change to LVM GEO layout, styles, logic or API.
Frontend tests if a JS test setup exists. Screenshots of every state. STOP with diff + screenshots.

======================================================================
8. STAGE 4 — RELEASE (only after explicit approval)
======================================================================
Backup DB + release dir; raw .patch for line-by-line review; deploy; install the timer;
restart forest-api.service once; verify with curl (credentials from env, never echoed) and screenshots;
rollback commands ready.
Update CURRENT_STATUS.md, CHANGELOG.md, INTEGRATIONS.md (Sentinel-1/2 → LIVE monitoring), API.md,
DATABASE.md with verified facts only.
Create docs/SATELLITE_DATA_LICENSING.md: Sentinel data licence (free, full, open), CDSE free-quota
terms, attribution requirement, and the open question that large-scale commercial use may require
CDSE commercial terms — to be confirmed with CDSE before paid customers.

======================================================================
ACCEPTANCE CRITERIA
======================================================================
- A sector or LVM GEO polygon can be added; 120-day S1+S2 history is fetched and stored with provenance.
- Daily timer and "Fetch now" add only new products; re-runs are idempotent.
- Cloudy/no-data dates appear as gaps (NULL), never as 0.
- S1 comparisons only within the same orbit geometry.
- BIK-001 negative control produces no event; the positive control produces a SUSPECTED event with
  plausible area and location.
- A MEDIUM/HIGH event automatically creates exactly one risk with evidence links and an AI
  explanation saying "suspected"; repeated detections of the same change update that risk;
  review and undo work; all actions audited; the risk appears in Risks and AI Inspector.
- A change in the buffer ring is reported as "outside approved boundary" with area and distance.
- Quota guards stop runs before the free limits; usage is visible in the UI.
- No demo/simulated data is labelled as real; no secret appears in code, logs or output.
- RM, Ingka, review, Forest Map and the rest of LVM GEO are unchanged.

Start with STAGE 0 now.
