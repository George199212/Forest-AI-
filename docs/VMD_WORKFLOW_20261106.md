> Superseded by the cadastral-only scope clarification: see [current registration report](VMD_CADASTRAL_ONLY_20261106.md). The three discovery modes below describe the earlier deployment.

# VMD / LVM GEO workflow simplification — 2026-11-06

The existing Forest AI integration is redesigned and deployed at **http://164.90.188.136:8000/#lvm-geodata**. Final visible frontend version: **geo-48d0b71e2bcd**. It remains the existing FastAPI/SQLite/Leaflet application, with its original navigation and dark green theme. No replacement application, dataset, map library or client deployment was created.

## Three discovery modes, one registration flow

- **PĒC KADASTRA:** exact cadastral land-unit search, validated as 11 digits with accepted display separators. It searches only canonical VMD `kadastrs`. The previously audited `40940020002` still correctly returns ten genuine compartments, not one synthetic parcel. Optional prefix searching is retained under advanced filters and requires an explicit action.
- **KARTĒ:** search the currently visible area, then click genuine source polygons to select/deselect. Multiple selection is supported. Pagination uses the original search bbox even if the user pans afterward.
- **PĒC TERITORIJAS:** draw a polygon or rectangle, upload GeoJSON, or load an owner-scoped saved territory. Default discovery intersects the territory; fully-inside and minimum-overlap options are in **Papildu filtri**. Saving a territory remains available there and is optional for compartment registration.

All three use the same selected-ID set, original server geometries, results table, confirmation dialog and `/api/geodata/vmd/import-selected` API. Selection persists across pages, mode changes, new searches and territory changes until explicitly removed, imported or invalidated by a dataset version change. Previously selected polygons outside the current page remain highlighted. Counts/areas deduplicate by source ID.

The main buttons are **Atrast nogabalus**, **Atlasīt visus**, **Noņemt atlasi**, and **Importēt kā sektorus**. Controls sit on the left, map on the right, results underneath. A compact three-step header tracks discovery, review and registration. Advanced filters, territory persistence and provider diagnostics are collapsed. All new interface text is Latvian; source identifiers and third-party attribution remain technical/source content.

Results show cadastral designation, quarter, compartment, area, source, status and overlap when relevant. Row clicks fit the exact source polygon; popup auto-pan cannot undo that fit. Map clicks toggle selection without scrolling the user away from the map. The existing sidebar remains present; at mobile widths it becomes a narrow icon rail. Chromium checked 390 px width with no horizontal page overflow.

## Selection scope and performance

**Atlasīt visus** has an explicit scope selector: **Šajā lapā** or **Visā meklējumā (līdz 100)**. Complete-search selection uses authenticated POST `/api/geodata/vmd/select-matching`, reuses the frozen query and verifies dataset version. It excludes already imported/unsupported features and reports that count. Above the existing 100-feature import limit it returns a clear 413; it never calls the first page “all results.” Existing selections count toward the limit. Large searches remain paginated, and users can select needed features across pages.

The national/regional catalogue is never downloaded wholesale. Existing RTree and identifier indexes, server paging, bounded query sizes/timeouts and cancellation remain in use. Normal page searches download at most 100 source features. Changing discovery mode cancels pending searches while retaining selection.

## Map bases and accuracy

OpenStreetMap remains the default map. An optional satellite/aerial base uses the verified public [Esri World Imagery service metadata](https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer?f=pjson). The browser checks availability before enabling it. Tile failure returns to the map base; source vectors remain available. Actual imagery tiles returned 200 in the live Chromium check. Imagery dates vary; no real-time imagery or telemetry is claimed.

Base imagery is reference context only. Compartment boundaries continue to come from the unchanged indexed VMD archive. No raster tracing, generated boundary, simplification or fictional relationship was added. Native geometry, original EPSG:10306 CRS, normalized EPSG:4326 geometry, source identifiers, archive/dataset version, attributes and timestamps remain in source provenance. Existing EPSG:3059 territory-upload support and coordinate/area checks remain intact.

The original source mapping is `kadastrs` → cadastral land-unit designation; `kvart` → quarter; `nog` → compartment; `anog` → subcompartment; `objectid` → source feature ID; `nog_plat` → declared hectares. There is no separate property-number field in this archive. See `docs/VMD_CADASTRAL_AUDIT_40940020002.md` for the original-file audit and all ten diagnostic rows. The interface explicitly states that a VMD compartment polygon is not automatically a legally authoritative cadastral boundary, and discovery does not establish ownership.

## Import and client isolation

The same confirmation preview now receives authoritative server data for target client/account, number of compartments, total hectares, geometry validity and duplicate status. It shows a per-feature review table. Confirmation freezes the exact IDs, dataset version and client metadata reviewed; later form changes cannot silently change the import.

Source IDs/geometry are reloaded from the server catalogue at import. Transactions, duplicate constraints, rollback behavior and original-geometry retention are preserved. Ordinary persistent Forest AI sectors are created; existing sectors are not overwritten. Cache invalidation makes them appear in the existing main map and sector workflows.

Client names/IDs label sectors within the **current authenticated application instance**; they are not an account/database selector or proof of land ownership. Saved territories are owner-scoped. A supplied territory ID is checked against the authenticated owner and client. A common territory relation is attached only when all selected features have that same saved discovery context; selections combined from different modes do not receive a false shared territory association. Original source provenance is retained regardless.

## Deployment and changed files

- Frontend: `/root/forest_ai/index.html`, assets beneath `/root/forest_ai/assets/`; directly served by FastAPI, without a separate frontend bundle/publish directory.
- Backend: `forest-api.service`, working directory `/root/forest_ai`, uvicorn port **8000**. Only this service was restarted, at **2026-11-06 11:49:30 UTC**, PID **2705579** at activation.
- Existing no-store HTML, content-hashed asset URLs and visible deployment identity remain in place. CSS is also included in deployment hashing and fingerprinted delivery.
- Main API, bot, Rīgas Meži, Ingka and review services were checked active. Other client code roots, credentials, ports and data stores were not deployed over or replaced. No Netlify site or other hosting account was used.

Changed: `index.html`, `api.py`, `assets/lvm-geodata.js`, `assets/vmd-production.js`, `services/geodata/vmd_dataset.py`, `services/geodata/vmd_production.py`, `tests/test_vmd_production.py`, `tests/test_vmd_production_ui.js`, `scripts/verify_vmd_browser.py`.
Added: `assets/vmd-workflow.css`, `scripts/verify_vmd_workflow_live.py`, and this report.

Backups: `data/backups/workflow_20261106T113312Z/` and fresh pre-activation SQLite backup `data/backups/workflow_activation_20261106T114730Z/forest_ai.db`; backup integrity passed. No operational database migration or VMD ingestion was performed.

## Tests and actual browser evidence

- **255 Python tests passed** using the documented test-only same-thread runner required by this executor. Includes exact search, real source geometry/CRS, spatial overlap, duplicate prevention, transactions, client/instance isolation, Deere regressions, preview metadata and bounded complete-search selection.
- **34 JavaScript checks passed**: production UI 15, existing WMS 9, dispatch 3, legacy local UI 7. Includes shared selection across all three modes, map toggling, pagination with a frozen bbox, selection scope, polygon drawing and frozen import intent.
- Python/inline/module JavaScript syntax and `git diff --check` passed.
- Real-data ASGI acceptance passed on a disposable database: territory persistence, real search, preview, source-preserving import, duplicate prevention and map/persistence checks.
- Real Chromium on a disposable database passed: draw rectangle, save/load territory, search real compartments, preview/confirm import, main map, reload, backend restart and a fresh authenticated browser context. No production sectors or territories were created by these tests.
- **Actual public Chromium** passed at the URL above: three tabs, left/right desktop layout; exact cadastral search → 10 real records; polygon click select/deselect; map-based discovery; selection preserved between modes/pages; original bbox retained after panning; explicit all-matching limit; GeoJSON territory discovery → 11 intersections; shared preview → 2 features, 0.61 ha, 2 valid geometries, 0 duplicates, verified account; bounded all-matching selection; satellite tile delivery; responsive 390 px layout; zero blocking JavaScript exceptions.

Evidence: `data/vmd/workflow-live-verification-20261106.json`, `data/vmd/workflow-desktop-20261106.png`, `data/vmd/workflow-mobile-20261106.png`, `data/vmd/workflow-preview-20261106.png`. Test logs: `/tmp/workflow-python-tests.log`, `/tmp/workflow-ui-tests.log`, `/tmp/workflow-real-data-api.log`.

Production sectors remain **18**, database integrity is **ok**, and sector/monitoring/client/Deere token and telemetry rows match the pre-activation backup. One pre-existing `john_deere_sessions` browser-session row rotated normally after expiry for the same account; it was not rolled back or treated as client data loss. No Deere integration code or credentials were changed. No synthetic GPS, risk, machinery or satellite events were created.

## Remaining limits and blockers

- Live LVM WMS/WFS connectivity remains an external provider/reachability issue. The local VMD workflow operates independently and does not claim live LVM availability when capabilities fail.
- Available VMD coverage remains the verified **Centra** archive, **513,776** records, rather than nationwide coverage.
- Existing operational sectors/GPS require one simple polygon ring. Source MultiPolygons/holes remain discoverable/displayable but are explicitly non-importable; no flattening or boundary approximation was introduced.
- Complete-search selection/import remains bounded to **100** features per transaction, visibly explained. Larger results can be searched and paginated without silent truncation.
- Production import confirmation remains a deliberate user action. Persistence/import/restart acceptance used real features on disposable database copies, preserving existing production sectors.

To verify: open the live URL and confirm version `geo-48d0b71e2bcd`; search `40940020002`; click polygons; switch to **KARTĒ** or **PĒC TERITORIJAS** and confirm the selection survives; review **Importēt kā sektorus**. Confirm only compartments intended for production monitoring.
