# LVM GEO / VMD restoration — 2026-11-06

The existing Forest AI application was restored and activated on the main instance. The overall acceptance list is **not fully complete**: external LVM capabilities are unreachable, and the existing operational sector engine cannot import multipart polygons or holes safely. No data was reset, no client credentials changed, and no production test sectors were created.

1. **Original regression.** The running `forest-api.service` process started on October 30 at 14:46, before the production VMD router was added. Its authenticated `/api/geodata/vmd/dataset` returned 404 while the newly served frontend requested that route. The local catalogue was present. Capability discovery had no browser timeout, ran after map/local loading, and performed sequential remote probes. Selection was explicitly cleared by every result render, including pagination.

2. **Previous implementation.** Git history was inspected, including all refs and geodata-related paths/messages. There is no committed earlier VMD polygon implementation: the working integration is uncommitted code, existing source artifacts, and October 30 handoff/backup documents. The three-feature GeoJSON proof of concept, local importer, production catalogue, territory tools and Leaflet components were retained. Existing imported sector 30 was retained. No replacement application or map library was built.

3. **Files changed during this restoration.** `.env.example`, `requirements.txt`, `api.py`, `index.html`, `assets/lvm-geodata.js`, `assets/vmd-production.js`, `services/geodata/lvm_geo.py`, `services/geodata/vmd_dataset.py`, `services/geodata/vmd_production.py`, `services/geodata/forestry_io.py`, `tests/test_geodata.py`, `tests/test_vmd_production.py`, `tests/test_vmd_production_ui.js`, `tests/test_vmd_test_geojson.js`; added `scripts/verify_vmd_integration.py`, `scripts/verify_vmd_browser.py` and this report. Earlier unrelated uncommitted John Deere, bot, database and integration changes were preserved.

   Changes include bounded/cancellable requests, independent capability and map loading, concurrent endpoint checks with one connection retry, manual refresh, last successful connection within the running process, explicit error states, stable cross-page selection and area, selection zoom, import preview/confirmation, client/territory provenance, native original geometry retention, EPSG:3059 uploads through pinned pyproj, map source/client information, Latvian integration content and navigation, and corrected navigation highlighting. Territory storage is derived from the instance database directory and scoped by authenticated owner. A client ID is descriptive metadata; it does not authorize cross-instance access or establish forest ownership.

4. **Activated endpoints.** Existing routes are now served by the running backend:

   - `/api/geodata/vmd/dataset`, `/compartments`, POST `/territory-preview`, `/search-territory`, `/import-selected`, GET/POST `/territories`, GET `/territories/{id}`.
   - `/api/geodata/lvm/health`, `/capabilities`, `/services`, `/layers`, `/layer`, `/map-url`, POST `/preview`, `/import`, `/apply`, sector source/refresh routes.
   - Existing `/api/sectors` and `/api/map` expose imported sectors; map responses now include source and client metadata.

5. **Verified data sources.** The [official VMD publication](https://www.vmd.gov.lv/lv/atvertie-meza-valsts-registra-dati) links the [official open dataset](https://data.gov.lv/dati/lv/dataset/meza-valsts-registra-meza-dati). Its Centra resource is CC0 1.0, describing data prepared on October 7, 2026. The official `centra.7z` was downloaded to temporary storage. All **25 SHP/DBF/SHX/PRJ/CPG files** match the existing extracted source files byte for byte by SHA256. The existing ZIP is a differently compressed container of these same files. Evidence: `data/vmd/source-verification-20261106.json`.

   Official 7z SHA256: `c3097c8afc82eb750a9dcae8db54e364da106811f30607dfb17a479086560153`.
   Existing ZIP SHA256: `089d02c642b44bed8b17cab87cb18c37a322475063407ad001fb8e63e07983fe`.
   Catalogue version: `26bd2653dff6c4c08de2f66c18d9013daa0cfb6bf8c616fa8468816e29ad01d3`.

   Source CRS is **EPSG:10306 (LKS-2020 / Latvia TM)**, not EPSG:3059. The existing catalogue retains its documented metre-level datum approximation. Native original coordinates and normalized geometry are stored in new imports without simplification. No legal/cadastral survey accuracy is claimed. MultiPolygon territories and searches are supported.

   Both candidate LVM endpoints are confirmed by the [official LVM service page](https://www.lvmgeo.lv/en/data/services/coming-soon). Direct host-network WMS/WFS probes and production capability discovery timed out. No live layers or WFS feature types were verified. No authentication challenge was received, so no missing credential can be identified from this evidence. WMS imagery is never treated as downloadable vector geometry.

6. **Indexed records.** Existing catalogue and RTree each contain **513,776** records from five Centra-region layers. No re-ingestion was necessary. The build report records 355 repaired geometries and zero failed records. Coverage is regional, not nationwide. A production territory query returned 11 matches, 2 fully inside, with exact result totals and separate paginated responses. No silent 100-record truncation occurs. Safety limits explicitly reject overly broad queries; they do not return incomplete results as complete.

7. **Tests and evidence.**

   - **246 Python tests passed**, including John Deere regressions, using the documented test-only same-thread ASGI runner. A normal full-suite attempt stalled in this execution environment and was interrupted; it is not reported as passing. Targeted normal execution passed **67 geodata/ingestion tests**, followed by **52 provider tests** including the new retry and last-success checks.
   - **27 JavaScript checks passed**: production UI (8), existing WMS (9), dispatch/labels (3), legacy local UI (7). They use simulated DOM/Leaflet where identified in their source.
   - Real indexed-data ASGI acceptance passed: save/load client territory, spatial search, pagination, import preview, committed import to a disposable DB, duplicate prevention, original and normalized geometry preservation, main-map equality and reopened-connection persistence.
   - Real Chromium end-to-end passed against an isolated DB/backend: mouse drawing, saving territory, real search, selection, preview/confirm/import, main map, browser refresh and backend restart; zero JavaScript errors. Production data was never written by this test.
   - Production Chromium verification displayed 10 real compartments for cadastre `40940020002`, selected a polygon and resolved the LVM failure state; zero JavaScript errors and zero mutations.
   - Python/JavaScript syntax checks and `git diff --check` passed.

   Reproduce real-data acceptance: `python3 scripts/verify_vmd_integration.py`.
   Optional browser runner: `FOREST_PLAYWRIGHT_PATH=/tmp/forest_browser PLAYWRIGHT_BROWSERS_PATH=/tmp/forest_chromium python3 scripts/verify_vmd_browser.py` (requires the installed temporary Playwright/browser, or equivalent normal installation).

   Live evidence: `data/vmd/live-verification-20261106.json`, `data/vmd/live-browser-verification-20261106.json`, `data/vmd/live-integration-20261106.png`. Test logs: `/tmp/geodata_restore_final_tests.log` and `/tmp/geodata_final_ui_*.log`.

8. **Deployment and data safety.** Only `forest-api.service` was restarted. It serves FastAPI/uvicorn from `/root/forest_ai` on port 8000, with its existing EnvironmentFile and SQLite database. No deployment files or credentials were changed. Main API, bot, Rīgas Meži and Ingka services were checked active; client services were not restarted. No nginx sites directory was found; checks exercised the direct existing listener, not an assumed reverse proxy.

   Verified fresh backups: `data/backups/geodata_restore_20261106T092855Z/forest_ai.db` and `data/backups/geodata_activation_20261106T095731Z/forest_ai.db`. Integrity is `ok`. No new operational schema migration was required for activation. The optional territory sidecar adds its client-ID column transactionally when saving an existing territory store.

   Existing production table contents matched the pre-activation backup after activation. Counts remained sectors 18, risks 19, work sessions 29, organizations 1, source relations 1. Existing accounts, manually edited boundaries and sector 30 were preserved. Live root, sectors, map, risks, GPS, machinery, summary, integrations and dataset routes returned 200; invalid authentication returned 401. External Deere credentials/telemetry were not exercised or altered, and no telemetry or incidents were fabricated.

9. **Remaining blockers and limitations.**

   - **BLOCKED — live LVM capabilities and layer display:** both published HTTPS services time out from this host. Required: restored host-to-provider HTTPS reachability/provider response, or an updated endpoint supplied by the provider and verified before configuration. Then use the refresh button. No alternative endpoint or credentials have been invented. Last-success time is process-local; no successful live connection exists to record in this run.
   - **INCOMPLETE — complex operational sector import:** MultiPolygon and polygon holes can be searched/displayed and used as territory boundaries, but cannot be imported into the existing flat-ring sector/GPS model. They are explicitly rejected, never flattened. Completing this requires coordinated changes and migration across sector storage, bot geofencing, track calculations, Deere geofencing and all map/edit consumers. Those working operational components were not replaced during restoration.
   - The available archive covers Centra only. Additional regions require their official archives and separately reviewed ingestion. No fictional national coverage is displayed.
   - Production import testing was deliberately performed on disposable database copies. A user-selected real production import remains a manual acceptance action. No real worker field test, provider-authenticated Deere sync or live satellite acquisition was performed.

10. **Exact manual verification.**

    1. Hard-refresh the main instance at `/#lvm-geodata`. Confirm title “Slāņi”, “VMD meža nogabali”, 513,776 indexed records and the Centra coverage notice. LVM should resolve to the current error instead of loading forever.
    2. Enter Kadastrs `40940020002`, press “Atrast nogabalus”, inspect real polygons and popups; select and deselect eligible polygons. The existing imported nogabals 6 remains marked as already imported.
    3. Draw a rectangle around longitude 24.4145–24.4175, latitude 56.6770–56.6785, or upload an equivalent valid GeoJSON polygon. Set territory/client names and client ID, save, then load it from saved territories.
    4. Choose intersection mode with 0% overlap and search. Expect 11 matches for that exact rectangle; inside mode gives 2. Check area, identifiers, source and selected count. For a larger territory, select on one page, move to the next, and confirm selection/area remain stable. Use “Pietuvināt atlasītos nogabalus”.
    5. Choose intended eligible compartments, press “Pārbaudīt atlasi (bez importēšanas)”, then “Importēt kā sektorus”. Review IDs, areas, target client and duplicate status. **Only confirm if these are intended production sectors.** Confirmation writes ordinary persistent Forest AI sectors.
    6. Open the main map and click the imported sector. Verify boundary, area, source and client, then details. Refresh and log back into the same client instance; the sector must remain. Repeat selection/import to verify it is recognized rather than duplicated.
    7. Once LVM reachability is restored, press “Atjaunot pakalpojuma pārbaudi”; inspect actual advertised layers/CRS/formats. A WMS layer alone must not enable vector import.

Acceptance: local dataset, authentic geometry, selectable maps, saved territories, spatial queries, pagination, simple-polygon transactional imports, persistent sector/map integration, client isolation tests, Latvian integration UI and service activation are verified. Live LVM layer availability and unrestricted complex-sector import remain outstanding, so this report does not claim complete final acceptance.
