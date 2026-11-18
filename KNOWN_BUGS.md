# Known Bugs / Limitations

- **Refresh / Atjaunot label inconsistent (found 2026-11-18, Sectors Stage 3 review).** The top-bar refresh button is set in
  `index.html` `nav()` (`page-refresh` text): "↻ Atjaunot" only for `lvm-geodata`, `forest-map` and `sat-monitoring`,
  "↻ Refresh" everywhere else — including the Sectors list and sector page, whose content is Latvian. Same page, mixed
  languages; the sector page (`#sectors/{id}`, opened outside `nav()`) keeps whatever label the previous page set. Not fixed.
- **Meža karte sector popup says "atrašanās Latvijā nav pārbaudīta" for sectors inside Latvia (found 2026-11-18, e.g. T-56).**
  `services/geodata/forest_map.py` `sectors()` marks every polygon that passes its Latvia bbox check
  (20 ≤ lon ≤ 29, 55 ≤ lat ≤ 59) as `valid_boundary`, and `assets/forest-map.js` shows `sectorBorderWarning` ("Saglabātā
  robeža ir ģeometriski derīga, bet atrašanās Latvijā nav pārbaudīta") for every `valid_boundary`. So a sector well inside
  Latvia still gets the "not verified" wording. Misleading, not a data error. Not fixed (Meža karte copy decision).

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


### Satellite Monitoring — UI review 2026-11-16 (post-release work on `feature/satellite-monitoring`, NOT deployed)
Status 2026-11-16 evening; :8000 still runs `7bd2bbb` (Stage 4 release). Next deployment needs the owner's "approved release".
1. **Fragmentation rule — done on the branch (`eaac5d4`), NOT applied to the live satellite.db.** Offline re-run on a
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
7. **True / false colour toggle — NOT possible from stored data.** Stored S2 bands: B04, B08, B11, B12, SCL,
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
   Re-verified 2026-11-18 (Stage 0 v3): the 401 banner in the owner's v3 screenshots was this same sandbox state, not
   a production issue — `sat_provider_status` catalog/process OK 2026-11-18 05:33/05:34 UTC, 560 logged CDSE requests,
   0 × HTTP 401 ever; API and both satellite workers load the same EnvironmentFile.

### Satellite Monitoring — backlog (owner decisions D2/D6/D7, 2026-11-18; NOT scheduled, each needs its own approval)

- **Per-polygon clear-pixel check (worker side).** SCL/dataMask are stored per acquisition (6-band GeoTIFF on the
  area grid); the forest-api interpreter cannot read them (no `tifffile`), so the check must run in the worker venv and
  be stored in existing JSON (`after_acq_history_json` entries / `sat_detections.details_json`). Measured 2026-11-18:
  events 60 and 62 polygons 100 % clear on every S2 after-image → the check would not change any current event.
- **Event evidence-quality aggregation (`satellite_monitoring/pipeline.py:901`).** Today: event EQ = best EQ over all
  after-acquisitions across sensors (`max` by `EQ_ORDER`). Effect: event 62 is GOOD only through S1 acq 196
  (2026-07-29) while both S2 after-images are LIMITED. Options (no change made):
  (a) keep the rule, show the basis in the UI ("Laba — no radara (S1) 29.07.2026; optiskie: ierobežota") — owner D2,
  planned for Stage C; (b) per-sensor EQ (`eq_s1`, `eq_s2`) stored in existing JSON, event badge = the sensor of the
  shown evidence; (c) event EQ = EQ of the acquisition that first showed the change (onset), not the best later one;
  (d) best-of only within the same sensor as `sensor_basis` primary, S1 support listed separately. (b)–(d) change
  stored interpretation → new detection generation, separate approval.
- **Transparent no-data in quicklooks.** PNGs are RGB without alpha; swath-edge / no-data pixels are opaque black.
  Needs worker regeneration with alpha from `dataMask` (0 PU, local rasters). Separate approval.
- **LKS-92 (EPSG:3059) coordinate search.** Forest Map search is WGS84 only (decimal comma accepted since D6). LKS-92
  needs a server-side `pyproj` parse.
- Esri World Imagery stays off in satellite views (licence, Stage 0 §8).
