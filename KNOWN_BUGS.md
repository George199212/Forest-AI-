# Known Bugs / Limitations

- Vehicle GPS route (History → Vehicles → click plate → map): the route is built only from
  manual GPS pings sent via the Telegram bot's "🚛 Vehicle GPS" flow, not from a continuous
  live track. Points appear only when a driver explicitly sends a location for that vehicle.

- **P1 — API startup has side effects (found 2026-11-17, NOT fixed).** `api.py` startup hook runs `init_db()`, which
  writes to the DB at `DB_PATH` (default `data/forest_ai.db` → via the release `data` symlink the PRODUCTION DB), and
  `risk_ai_worker.start()`, which picks up risks with `ai_status` NULL/REQUESTED and calls Anthropic when
  `ANTHROPIC_API_KEY` is set. Any extra uvicorn (sandbox, rollback proof) therefore touches prod data and AI spend unless
  the env is stripped (DB copies, no credentials — as done for the rollback8band proof on :8099). Fix: env flags to
  skip `init_db()` writes and to disable `risk_ai_worker`.

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


### Satellite Monitoring — UI review 2026-11-16 (post-release work on `feature/satellite-monitoring`, NOT deployed)
Status 2026-11-16 evening; :8000 still runs `7bd2bbb` (Stage 4 release). Next deployment needs the owner's "approved release".
1. **Fragmentation rule — APPLIED to the live satellite.db on 2026-11-17 (generation 2, events 58–66; Ķekava §13).** Was: done on the branch (`eaac5d4`), first offline only. Offline re-run on a
   copy (0 PU, generation 2): gate MET (recall 3/3, open outside 4 = 105.11 ha, masks identical); 5 events become
   POSSIBLE_SEASONAL_OR_ENVIRONMENTAL / LOW, event 55 (12 %) included. Details `docs/SATELLITE_POSITIVE_CONTROL_KEKAVA.md`
   §12. Open: live redetect (new event ids 58–66; links to 49–57 then open superseded rows) needs approval + backup.
2. **Latvian — done (`2013e7c`).** Root cause: :8000 runs without `UI_LANGUAGE` (serves `<html lang="en">`, no
   `i18n-lv.js`). The section is now Latvian by default (LV/EN switch), dictionaries generated from `i18n-lv.js`.
   Still English on purpose: Copernicus licence line, Leaflet/OSM attribution, and the stored server text kept in
   tooltips (title attribute). Untranslated strings found and fixed: page title/refresh, Leaflet zoom titles, the
   seasonal caveat, recovery reason and operational-context reasons (display-only translation).
3. **Popup #52 → event 52 — no bug.** Popups 51/52/55/57 link to their own event pages; after_10 opened #55 on purpose.
4. **Event 52 images — fixed (`0530225`).** The quicklooks (acq 299, 331) were served 200 every time; the black panels
   were images still loading with no indicator. Now "Ielādē attēlu…" / "Attēlu neizdevās ielādēt.".
5. **"Atvērt Meža kartē" from event 52 — fixed (`714462f`).** The map did load and centre (bbox in view, zoom 15,
   popup open); after_05 was taken 0 s after the click. English "Forest Map" / "Refresh" during loading → Latvian.
6. **Worker status — done (`e5a6826`).** From systemd: Nav uzstādīts / Darbojas / Dīkstāvē / Taimeri izslēgti /
   Statuss nav zināms, plus next daily run and last queue check.
7. **True colour — implemented on the branch (`bc8c428`, not deployed): B03/B02 appended to new S2 requests; existing images of open events need the owner's OK to fetch (dry-run 2026-11-17: scope shown 4 requests ≈ 12.0 PU, scope all 11 ≈ 33.0 PU).** Earlier note: NOT possible from stored data. Stored S2 bands: B04, B08, B11, B12, SCL,
   dataMask. True colour needs B03 + B02. What it would take (owner decision, not done):
   - add B02, B03 to `EVALSCRIPT_S2` / `S2_BANDS` (8 output bands), adapt the raster decode/indices and
     `quicklook_png` (second, true-colour quicklook);
   - only NEW acquisitions get them; history needs re-fetching: ~291 Process requests, ESTIMATE ≈ 1,140 PU
     (852.8 PU × 8/6 bands, not verified with CDSE) — above the remaining November guard (1,600 − 852.8 ≈ 747 PU);
   - every future S2 request costs ≈ +33 % PU (estimate).
   Done instead (`9b91e49`): the event page says the images are false colour (B11/B08/B04) and that true colour is
   not available.
8. **Closed** (2026-11-16): the "HTTP 401 invalid_client" banner was a synthetic sandbox state; live satellite.db has
   no token failure (302 requests, all HTTP 200, last 2026-11-11). A real token request on 2026-11-16 ~15:44 UTC
   returned 200.

- Satellite Monitoring (open, 2026-11-17): links / bookmarks to events 49–57 now open superseded rows (generation 2
  replaced them with 58–66 on the live DB); the page shows the superseded banner and no map button. The Forest Map
  layer returns 404 for superseded ids.
- Satellite worker (observation, 2026-11-17): first daily run peaked at 552 MB (preflight measured 424 MB); limit 2 GB.
