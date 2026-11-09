**Forest AI national Forest Map — implementation and acceptance, 7 November 2026**

Implemented and **activated in production** as an isolated Forest AI release on 7 November 2026. Open **Forest Map / Meža karte** at `http://164.90.188.136:8000/#forest-map` (dashboard authentication required). The existing cadastral-only LVM GEO workflow remains available.

**Architecture and database integration**

The map reads the existing immutable national `compartments.sqlite` and `parcels.sqlite` selected by `data/geodata/nationwide/active.json`: 3,063,409 VMD compartments and 1,055,666 VZD parcels. SQLite's WGS84 RTree serves viewport queries; exact source IDs use the existing identity index. No source data was downloaded, imported, updated or migrated. Existing operational sectors/accounts were not changed.

SQLite has RTree support but no registered MVT functions; the existing environment has no `mapbox_vector_tile` package. Rather than introduce PostGIS/SpatiaLite, add an encoder/decoder or replace Leaflet, this implementation uses bounded **GeoJSON vector display tiles rendered to canvas by Leaflet GridLayer**. This is not MVT. It reuses the project's current Leaflet, NumPy, Shapely and SQLite infrastructure without additional dependencies.

At zoom 4–10, a derived, versioned overview provides generalized **forest presence cells**, not surveyed forest coverage or parcel boundaries. The builder reads only RTree bounding-box centers and conserves the count of all 3,063,409 compartments. Its zoom-14 atlas has 35,621 occupied cells and is approximately 62 KiB compressed. Initial generation took 9.37 seconds. The atlas is a disposable visualization cache under `data/geodata/forest-map/<dataset-version>/`, separate from source and operational databases.

At zoom 11–16, the server clips and simplifies display polygons using zoom-dependent, topology-preserving tolerances. At zoom 17–19, it clips the full stored display polygon without further simplification. Dense/complex forest tiles fall back explicitly to presence cells; they do not silently truncate a supposedly complete compartment list. VZD parcel tiles start at zoom 14; dense parcel tiles explicitly request a closer zoom. Exact cadastral search and full-source inspection remain available independently of tile generalization.

Server limits are 600 source candidates/features, 400,000 serialized output bytes, 4 MB input WKB, 20,000 display vertices and a bounded query/geometry time budget per tile. BLOB lengths are checked before loading geometry. Three tile workers and a 24 MB / 256-entry process-local LRU bound resource use. Cached public-source tile results are keyed by dataset version, layer and tile; no organization data enters that cache. Private HTTP caching varies by Authorization. Browser URLs also include the dataset version so a release change cannot reuse another release's browser cache entry.

The client draws canvas tiles, loads at most three requests concurrently, retains a small viewport buffer, and aborts unloaded tiles/outdated inspection/search requests. It never requests all national polygons. Tile count/size limits, cold/warm timings and rapid-pan responsiveness were tested; concurrent-user capacity has not been established.

**User workflow**

- Satellite (Esri) and standard (OpenStreetMap) basemaps, independent of LVM WMS/WFS availability.
- Toggles for local VMD boundaries, local VZD boundaries and organization-filtered existing Forest AI sectors.
- Whole-Latvia initial view, zoom/pan, scale control and a return-to-Latvia button.
- Exact 11-digit cadastral search with pagination and an official parcel outline; coordinate search accepts `latitude, longitude` in the Latvia envelope.
- Click a forest compartment to inspect its full source record: cadastral/source ID, municipality, parish, hectares, native validity, display-repair warning and import eligibility.
- Select/add/remove/clear up to 100 eligible compartments, including selections from different cadastral units. Selected full-source boundaries are gold; existing sectors are purple; repaired/review display tiles are orange. The detail panel, not a green tile color, determines legal/source eligibility.
- Sector name, responsible first/last names and authenticated organization context feed the existing registration API. Multi-cadastre selections are grouped into exact cadastral requests. Every group is previewed before an explicit confirmation dialog can send actual registration requests.
- A partial registration response retains failed items and reports errors; successful/existing items are removed from selection. No registration occurs on map load, click, selection or preview.
- EN/LV map controls, navigation title and return-navigation refresh are supported. The surrounding dashboard keeps its existing localization behavior.

The preview dialog freezes the reviewed source IDs, dataset version, cadastral designation and contact/name fields. **No client display geometry is submitted for import.** The existing `/api/geodata/vmd/import-selected` implementation rereads original/native geometry, checks source association and strict VZD containment, enforces geometry compatibility, duplicate/name protection and organization identity, and requires `confirmed:true` for non-dry-run requests. Full original geometry/provenance preservation remains the existing backend's responsibility; visualization tiles never enter that branch.

**Authentication and privacy**

All new routes use the existing dashboard HTTP Basic dependency. The deployment's existing identity adapter supports one verified organization and a shared instance account; it does not implement new multi-organization membership. Ambiguous organization ownership fails closed. The new sector overlay queries `WHERE organization_id=?` and returns only basic map fields, rather than reusing the older global `/api/map` response. Full inspection/identification can include existing-sector state only after identity verification. Those responses and the sector overlay use `Cache-Control: private, no-store` and `Vary: Authorization`.

The current organization has **21 sectors: 12 valid Latvian polygon boundaries, one invalid legacy boundary shown only as a stored-center marker with an explicit warning, two invalid legacy boundaries whose stored centers lie outside the Latvia envelope, one valid legacy polygon outside Latvia, and five sectors without locations**. The overlay shows 13/21 located sectors and never repairs or invents a legacy boundary.

New routes:

| Endpoint | Purpose |
|---|---|
| `GET /api/geodata/forest-map/status` | Active release and derived overview readiness |
| `GET /api/geodata/forest-map/tiles/{forest,parcels}/{z}/{x}/{y}` | Bounded, display-only vector tile |
| `GET /api/geodata/forest-map/identify?lat=...&lon=...&zoom=...` | Bounded click hit test followed by full-source inspection |
| `GET /api/geodata/forest-map/feature?id=...` | Full-source display geometry and revalidated eligibility |
| `GET /api/geodata/forest-map/sectors` | Organization-filtered operational sector overlay |

Existing cadastral, registration-context and import-selected endpoints are reused. The new navigation remains hidden unless the serving backend injects `FOREST_MAP_ENABLED=true`; the already-running old production backend cannot advertise unsupported routes merely because frontend files exist in this shared checkout.

**Local preview — no production deployment**

```bash
python3 scripts/build_forest_map_overview.py
python3 scripts/preview_forest_map.py --port 8767
```

Then open **http://127.0.0.1:8767/#forest-map** on the host running the preview, using the existing dashboard credentials. Loopback on the remote server is not automatically forwarded to a user's device. No public preview forwarding service is configured.

The launcher makes an isolated, consistent operational DB backup in a temporary directory, serves the same updated application with lifespan/background workers disabled, and blocks all writes except `import-selected` requests with `dry_run:true`. Actual import confirmation receives HTTP 403 in preview. Existing accounts are read, never changed. Stop with Ctrl-C; the preview and disposable backup are cleaned up. The browser-test preview was stopped after acceptance; no test server was left running.

**Validation**

The real-data browser acceptance script is `scripts/verify_forest_map.py`. It starts/stops its own isolated preview and verifies Riga plus one previously verified land unit from each requested region:

| Area | Cadastral land unit | Exact forest records | Open / render / search / click / zoom / pan / toggles / selection |
|---|---|---:|---|
| Riga | `01000950031` | 6 | PASS |
| Vidzeme | `96480160030` | 25 | PASS |
| Latgale | `68600020035` | 25 | PASS |
| Kurzeme | `98660020099` | 25 | PASS |
| Zemgale | `46880010410` | 24 | PASS |

Five selected compartments from five cadastral units passed one combined preview. The five HTTP requests contained only source IDs and scalar registration fields; every request had `dry_run:true`, and none contained simplified geometry. Actual-write preview requests were denied with HTTP 403; anonymous metadata access was denied with HTTP 401. Latvian controls and leaving/reopening the map passed. Browser JavaScript and tile-error counts were zero.

During local acceptance before production activation, all table row hashes/counts and source database size/mtime pairs matched before and after. Production activation later rechecked the full sector-row fingerprint and confirmed all 21 existing sectors unchanged; no sector registration, source update, client-account change or database schema change occurred.

The targeted Python regression suite passed **63 tests**: new Forest Map contracts plus national geodata, existing VMD production import/search and deployment delivery checks. Four existing JavaScript test files passed. Syntax checks (`node --check`, Python compilation) and whitespace checks passed. Sandbox ASGI threadpool limitations required running the regression/browser suites outside the restricted sandbox; test databases remained disposable.

Actual browser measurements and zoom-specific tile benchmarks are recorded in `docs/evidence/forest-map-20261107/acceptance.json`; screenshots show the LV national map and multi-cadastre preview. Reported timings are one-host observations, not service-level guarantees. The generated performance table accompanying this document records the final run.

**Remaining limits and release decision**

1. GeoJSON/canvas tiles are the chosen least-disruptive renderer; MVT is not implemented. Before scaling to many concurrent users, measure throughput and consider a persistent MVT encoder/tile service if warranted.
2. Low-zoom cells indicate compartment bounding-box-center presence, not exact forest extent. The map labels this explicitly. Dense medium/high-zoom fallback is also generalized; zoom closer or use cadastral search. Precise national/legal border containment is not claimed.
3. Parcel visualization starts at zoom 14; very dense tiles may require a closer view. Large/complex source inspection is explicitly rejected rather than loading unbounded geometry.
4. Esri/OSM imagery and the project's existing Leaflet CDN need network availability. Local forest/parcel geometry never needs live LVM WMS/WFS. This is not a fully offline basemap bundle.
5. Invalid/repaired native geometry, holes/multipart geometry unsupported by the current sector model, and strict VMD/VZD boundary slivers remain review-only. The existing 1,723 invalid-native / 2,152 repair-flag counts and the historical staging-evidence conflict are not silently fixed by this feature.
6. Permissions inherit the current single-organization/shared-account deployment. This feature adds no account/membership migration and makes no claim of supporting new multi-tenant organizations without that infrastructure.
7. Production activation and authenticated read-only monitoring checks completed. The one production registration preview used `dry_run:true` and reported one eligible compartment, zero imports. No production sector was created. The startup schema matched the verified operational schema; no migration was needed.
8. The overview must exist for the exact active dataset version; missing/mismatched caches return an explicit 503. Future release activation requires building a new derived overview; do not reimport source data.
9. Five existing sectors have no stored location; two invalid legacy boundaries and one valid legacy polygon have locations outside Latvia (approximately 58.904° N, 32.741° E) and are not displayed. One additional invalid legacy boundary is shown only as a warned stored-center marker, not a validated polygon. They need owner review; their original records were preserved.
10. The sector overlay is capped at 1,000 sectors. Large operational organizations would need viewport/pagination work before increasing this bound. Busy tile requests return explicit 503s; the UI offers pan/zoom/refresh retry rather than an unbounded request storm.

**Deployment status: production activation successful.** The isolated release is active under `forest-api.service`; it uses the existing active dataset and overview through the existing data directory. The rollback release and pre-activation database/config/environment backup are retained. Rollback must change application/service configuration only; do not restore an old operational database over live user writes.

Changed implementation files: `api.py`, `index.html`, `assets/forest-map.js`, `assets/forest-map.css`, `services/geodata/forest_map.py`, `scripts/build_forest_map_overview.py`, `scripts/preview_forest_map.py`, `scripts/verify_forest_map.py`, `tests/test_forest_map.py`; this document and the new evidence directory are additive review artifacts. Unrelated pre-existing workspace edits were preserved.

The full 20 previously verified identifiers, with municipality, counts and hectares, remain in [VMD_REAL_WORLD_TEST_20261107.md](VMD_REAL_WORLD_TEST_20261107.md) and are also listed directly in the final task response.

**Final measured performance (single host, one browser session)**

Map open: **1.84 s**. Browser maximum tile: **67,149 bytes / 236 features**. Rapid-pan maximum frame gap: **55.7 ms**; observed maximum long task: **170 ms**. 18 unloaded/outdated requests were cancelled. No JavaScript or tile-response errors.

| Zoom | Runs (cold/warm pairs) | Min ms | Mean ms | Max ms | Max bytes | Max features | Representation |
|---|---:|---:|---:|---:|---:|---:|---|
| 6 | 10 | 0.16 | 6.33 | 48.79 | 41,363 | 147 | generalized_presence |
| 9 | 10 | 0.22 | 27.36 | 77.12 | 74,962 | 256 | generalized_presence |
| 11 | 10 | 0.16 | 9.47 | 20.01 | 19,126 | 64 | generalized_presence |
| 13 | 10 | 0.13 | 36.88 | 138.54 | 208,715 | 454 | simplified |
| 16 | 10 | 0.12 | 2.42 | 9.47 | 16,564 | 29 | simplified |

The pre-activation smoke check confirmed the map flag was absent and its API route returned 404. After activation, production root and map status returned HTTP 200. The API serves deployment `geo-c5801dc23be5` with backend revision `552c46ae547b`. The isolated preview continues to use unique, non-overwriting acceptance output directories.


## Production activation record — 7 November 2026

**Result: PRODUCTION ACTIVATION SUCCESSFUL.** `forest-api.service` is active from `/root/forest_ai/releases/forest-api-meza-karte-20261107T084300Z`, PID recorded in the activation evidence. Only `forest-api.service` was restarted. The service keeps its existing environment file, port 8000 and geodata manifest; the operational `data/` directory is shared by symlink. The changed API file differs from the verified running baseline only by Forest Map route/activation wiring.

The original running API fingerprint `dfbf12feae50` exactly matched `data/backups/nationwide_20261106T164556Z/api.py`; it did not match Git `HEAD` because the live Forest AI baseline included uncommitted application changes already loaded by the process. The isolated baseline and feature releases were constructed from that verified runtime API plus the same pre-existing runtime modules, UI and data. The first package check exposed a missing `lvm_3_sectors.geojson` support file; that package was not left active. The file was included unchanged in both release and rollback packages, and both packages then passed existing-route checks.

**Production checks:** dashboard root, `/api/summary`, existing `/api/map`, `/api/sectors`, GPS, Risks, integrations health and local VMD status returned HTTP 200 with authentication. Anonymous forest-map access returned HTTP 401. VMD search for `01000950031` returned six compartments. Forest detail, forest tiles and VZD parcel tiles returned valid responses. The registration preview returned `dry_run:true`, `would_import:1`, `imported:0`; the confirmation button was not activated. The production browser opened the map, searched, inspected and selected a compartment, toggled layers, ran the dry-run preview and cleared the selection. It observed 107 tile responses, all HTTP 200, with no browser errors.

The operational database passed `PRAGMA integrity_check`. All 45 operational table row counts and fingerprints matched the pre-activation backup; all 21 existing sector rows, including the eight with no usable map locations, match the pre-restart row fingerprint. The database is not restored during code rollback, avoiding loss of new user writes. Active VMD/VZD database metadata/stat pairs remained unchanged. Existing sectors remain 13 located in the map overlay and 8 without usable locations; their data was not edited.

The pre-activation backup is `/root/forest_ai/data/backups/forest_api_meza_activation_20261107T0852Z` (directory mode 0700; environment and database backups mode 0600). It contains a verified SQLite backup, original service/geodata configuration, environment copy, and baseline code archive. Tested rollback release: `/root/forest_ai/releases/forest-api-baseline-20261107T084300Z`. The active drop-in is `/etc/systemd/system/forest-api.service.d/50-meza-karte-release.conf`. To roll back, install the saved `rollback-release.conf` over that drop-in, run `systemctl daemon-reload`, then restart `forest-api.service`; do not restore the database backup unless a separately approved data recovery requires it.

**Satellite status:** Sentinel-1 is inactive. Sentinel-2 is inactive: no Sentinel/satellite systemd units or timers, zero pending satellite requests, zero sector satellite scores, and the three stored Sentinel-2 observations are marked `DEMO`. No satellite endpoint was called as part of activation.

**Remaining warnings:** this host has no local nginx installation; the existing API is directly bound to `0.0.0.0:8000`, so the map URL uses that existing HTTP origin. Esri/OSM basemap tiles require external network access, but VMD/VZD polygon rendering and cadastral lookup use local data. The live LVM WMS/WFS service remains unavailable as previously diagnosed and is not used by the national map. Eight legacy sectors have no usable Latvia map location; three existing legacy boundaries are invalid/outside extent, and their geometry was preserved. The current organization identity remains the existing single-organization configuration.
