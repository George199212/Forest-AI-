# Known Bugs / Limitations

- Vehicle GPS route (History → Vehicles → click plate → map): the route is built only from
  manual GPS pings sent via the Telegram bot's "🚛 Vehicle GPS" flow, not from a continuous
  live track. Points appear only when a driver explicitly sends a location for that vehicle.

- `requirements.txt` is missing `python-multipart`. FastAPI refuses to start without it
  ("Form data requires python-multipart"). Production works only because the package is
  installed system-wide. A clean install from `requirements.txt` fails. Found 2026-10-13.
  **Fixed** (checked 2026-11-09): `python-multipart==0.0.32` is in `requirements.txt`.
- `install.sh` in the repo root is not a Forest AI file: it is the third-party installer of
  `DeusData/codebase-memory-mcp`. It does not install Forest AI. Found 2026-10-13; left in place
  pending the owner's decision. Still present (checked 2026-11-09).
- Before/after photo comparison (`services/photo_compare.py`): sector BIK-001, point P1 was
  marked "same place: yes" for two photos of different marker posts (different symbols,
  different path). False same-place match; 15 of 30 points also unmatched. Seen 2026-10-13
  on a screenshot, root cause not yet investigated.
  Mitigated 2026-10-13 (UI): default filter "Sakrītošās vietas" shows only pairs with both sides,
  same_place=yes, comparability not unsuitable and no reviewer decision against them; reviewer button
  "✗ Nav tā pati vieta" removes a false pair (decision + removed automatic findings kept in the event log).
  The model's same-place judgement itself is unchanged. Geometric matching (SIFT + RANSAC) was tested and
  cannot verify same place for forest photos taken from different positions (parallax), so it is not used.
- `bot.py` hardcodes the dashboard link as `http://164.90.188.136:8000` (3 places). A bot for
  a client instance would send users to the main dashboard. Still present (checked 2026-11-09).

- LVM GEO (fixed on `feature/lvm-geo-finish`, not deployed, 2026-11-10): clicking a compartment polygon to
  read its popup toggled its selection; clicking an off-page selected polygon removed it; a row click
  scrolled the page to the map; every toggle rebuilt the table. Live :8000 (frontend `fd3d2c6`) still has
  the polygon-click toggle until this branch is deployed.
- Forest Map (fixed on `feature/lvm-geo-finish`, not deployed, 2026-11-10): basemap switch only in the
  sidebar, below the fold; no control on the map.
- LVM GEO boundary rule (by design, not changed): compartments with a few cm² outside the VZD land unit
  are blocked as "Robežu neatbilstība" (e.g. 01000920499: 35 of 84 blocked, all < 1 m² outside).
  Needs a product decision on a tolerance.
- Sidebar language switches with the page on :8000: Latvian only while LVM GEO is open
  (`localizeGeodataNavigation`), English elsewhere; header time `lv-LV` only on LVM GEO. Found 2026-11-10.
- Pre-existing test failures on master with the real data catalogues (unrelated to this branch):
  `tests/test_vmd_production.py::test_actual_logged_no_match_reports_limited_source_coverage` (3 params) and
  `::test_official_outside_parcel_is_coverage_diagnostic_never_a_forest_match`. Found 2026-11-10.
- Forest Map on basemap "Karte" (fixed on `feature/forest-map-basemap-contrast`, not deployed, 2026-11-10): VMD
  compartment boundaries (`#74c484`, 1.1 px) were almost invisible on OSM's green woodland; VZD parcels and the
  grey GPS transition line were weak on white. Satellite was fine and is unchanged.
- No GPS session in the production DB has transitions or gaps yet (only session #32 has track points), so the
  white-casing style for them was checked with a clearly labelled synthetic sample only. Found 2026-11-10.

- Satellite Monitoring (fixed on `feature/satellite-monitoring`, not deployed, 2026-11-16): the overview showed
  "Copernicus credentials are not configured" whenever the API process had no SENTINEL_* variables, although the
  worker had synced successfully (root cause: `store.health()` read `os.environ` of the API). Now from
  `sat_provider_status` / `sat_runs`.
- Satellite Monitoring (fixed on the same branch, 2026-11-16): the 30 s dashboard auto-refresh re-rendered the
  overview and threw an open event/area page away (reproduced: event #52 → overview after ~35 s).
- Satellite Monitoring (open, 2026-11-16): "Worker: Idle" is shown although no worker is installed; it only means
  `.sat-monitoring.lock` is not held. Live satellite.db is not migrated for Stage 2, so add/stop/fetch/review return
  503 until the worker's first run (Stage 4).
- Forest Map "Satelīta izmaiņas" (open, 2026-11-16): the focused event is not drawn differently from the other
  events of its area (only its popup is opened); geometry is simplified (±2–80 m, shown in the popup), the event page
  keeps the full mask. Superseded events (e.g. #48) return 404 on `/map-layer?event_id=`.
- `index.html` must keep `<script src="/assets/forest-map.js?v=20261107">` byte-exact: `api.py` enables Forest Map
  by string-replacing that tag (`FOREST_MAP_ENABLED`). Bumping the `?v=` disables the map ("Meža karte gaida servera
  atjauninājumu"). Guarded by `tests/test_forest_map_sat.js` since 2026-11-16.


### Satellite Monitoring — UI review 2026-11-16, open, post-release work (released as is, owner decision)
1. Fragmentation rule missing: when the largest cluster is < 30 % of the event's current area, the event should be
   POSSIBLE_SEASONAL_OR_ENVIRONMENTAL with LOW confidence (config). Needs an offline re-run on a COPY (0 PU) of
   Ķekava + BIK-001 with the gate "recall 3/3, outside events/area not growing" before the live DB is touched.
2. Satellite Monitoring section not fully Latvian in the review sandbox (title, KPIs, banners, tables, event page,
   legends, buttons, empty states). Finding so far: `assets/i18n-lv.js` is injected only when the process runs
   with `UI_LANGUAGE=lv` (`api.py:604-608`); the review sandbox did not pass `UI_LANGUAGE`. Whether production
   :8000 sets it was NOT checked; list of untranslated strings not yet produced.
3. Forest Map popup link: verify that the popup of event #52 opens event 52 (the after_10 screenshot opened #55
   on purpose; not yet checked for #52).
4. Event #52 page: BEFORE / AFTER images reported black. Not investigated yet.
5. "Open in Forest Map" from event #52: screenshot after_05 was captured right after the click (map not loaded,
   English static title "Forest Map" / "Refresh" until `forest-map.js` loads). The English title and nav label
   during loading are real; the final state (after_06) is centred on the event.
6. Worker status shows "Idle" when no worker unit exists; should be "Not installed" (LV "Nav uzstādīts").
7. Event images: add "True colour / False colour" toggle (true colour = B04/B03/B02, default). Stored rasters must
   be checked for the bands first; no new Copernicus calls.
8. Checked 2026-11-16 (closed): the "HTTP 401 invalid_client 2026-11-16 07:30" banner was a SYNTHETIC sandbox state
   (`/root/sat_sandbox/toggle/sat_auth.db`). Live satellite.db (read-only, immutable): no `token` row in
   `sat_provider_status`; catalog last OK 2026-11-11T07:06:56Z, process 2026-11-11T07:13:26Z; `sat_request_log`
   302 rows, all HTTP 200, last 2026-11-11T07:13:26Z. Token requests are not logged in `sat_request_log`.
