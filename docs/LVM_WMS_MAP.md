# LVM GEO optional reference layers on the Forest AI map

Implemented 2026-10-30 UTC in `/root/forest_ai`.

## Change

Open `/#map` (existing Map / Sector map). The native Leaflet control at the top
right contains **LVM GEO** with two independent checkboxes:

| ID | WMS layer | Label | Opacity |
|---|---|---|---|
| lvm_blocks | pubblock_LVM | Meža kvartāli (LVM) | 0.65 |
| lvm_compartments | pubcompartments_LVM | Meža nogabali (LVM) | 0.75 |

Both are off on first use. Choices persist only in this browser session, using
sessionStorage with an in-memory fallback when storage is denied. Both can be on
simultaneously. Add future layers by adding an entry to the frozen public registry
in `assets/lvm-wms-map.js`; no map rewrite is needed.

Mode: **direct_browser_wms**.
Endpoint supplied and externally verified by the user:
`https://geoserver.lvmgeo.lv/wmsvector62531a9bfcfa4015856924e94076a179`.

Leaflet 1.9.4 native TileLayer.WMS generates WMS 1.3.0 GetMap requests using
EPSG:3857, transparent PNG tiles and its own viewport/zoom/resolution calculations.
There is no manual BBOX, backend proxy, static PNG download, country-wide preload,
capabilities request, GetFeatureInfo, WFS or new backend endpoint in this addition.
Image tiles intentionally omit crossOrigin, because ordinary cross-origin image
display does not require CORS permission. Canvas pixel extraction is not added.

These are external LVM reference layers, not Forest AI sectors. No operational
objects, identifiers, geometry, provenance or risk rules are changed.

## Existing map inspected and preserved

Frontend: vanilla JavaScript SPA, `index.html`.
Main map: `loadMap()`, container `map-container`, default Leaflet EPSG:3857.
Base: existing OpenStreetMap tiles and attribution.
Operational main map: sector polygons and risk-colored center markers;
`renderProviderMachineMap()` manages machinery in its existing layer group.
Worker/session GPS routes, exit/return risk maps, vehicle routes and satellite maps
have their own existing code paths, which were not modified.

The main map previously had no permanent layer selector; the new selector is a
separate native Leaflet control and leaves existing/dynamic controls intact.
LVM's custom pane has z-index 250, above OSM (200) and below operational paths
(400), markers (600), tooltips and popups. Pointer events on the contextual pane
are disabled, retaining sector/marker clicks. Existing satellite views are separate
maps and are unchanged. No operational layer controls were removed or renamed.

A WMS tile error displays a small non-blocking message and disables only that
layer. It does not automatically retry on movement. The user can toggle it on
again explicitly. Existing map layers remain present. Attaching the module twice
to the same map does not create duplicate layers or controls.

## Backup and files

Backup: `/root/forest_ai_backups/lvm_geo_20261030T112557Z/`.
`BACKUP_MANIFEST.txt` records UTC timestamp, modified/new files, database path,
service configuration and pre-change git status.
The backup contains the original `index.html`, a consistent online SQLite backup,
`.env` (mode 0600, within a mode 0700 backup directory), and `forest-api.service`.
Environment values were not printed or included in frontend code.

Only existing application file modified: `index.html` (one script include and one
protected attach hook after the existing base layer).
New files: `assets/lvm-wms-map.js`, `tests/test_lvm_wms_map.js`, this document.
No Python, API, auth, environment, dependency, service or database change was made.
Earlier unrelated/uncommitted changes were preserved.

## Verification

- `node tests/test_lvm_wms_map.js`: **9 tests passed**. Native WMS configuration,
  default-off behavior, independent/simultaneous toggles, stacking, idempotency,
  session restoration, pan/zoom layer reuse, storage failure and isolated tile
  failure handling were checked with a simulated Leaflet map/DOM.
- JavaScript syntax checks passed for the new asset and inline SPA JavaScript.
- An ASGI HTTP smoke test against a temporary copy of this task's fresh database
  backup returned 200 for `/`, the new JS asset, `/api/map`, `/api/map/machines`,
  `/api/sectors`, `/api/risks`, `/api/gps` and `/api/summary`.
  Invalid credentials for the new asset returned 401. No lifecycle/background jobs,
  migrations or provider network requests were run. The test-only same-thread
  dispatch workaround was necessary because this restricted session blocks the
  normal test client's thread portal. This is not a running-service curl test.
- Production database was inspected read-only before/after. All table counts match:

| Table | Before | After |
|---|---:|---:|
| sectors | 17 | 17 |
| risks | 19 | 19 |
| work_sessions | 29 | 29 |
| organizations | 1 | 1 |

Integrity check: `ok`. No rows, columns or tables were changed.

## Live validation limits and service handling

HTTPS HEAD and GetCapabilities curls were attempted as requested; both failed
with curl exit 6 / HTTP 000 due to the execution session's network restrictions.
This does not establish that the actual production host or LVM GEO is unavailable.
No firewall, DNS, routing, VPN or proxy configuration was changed.

`systemctl status forest-api.service` returns `Failed to connect to bus:
Operation not permitted`. Service ACTIVE/FAILED state cannot be established here.
The last 100 readable journal entries contain no startup failure/error/traceback
patterns; the latest observed event was 2026-10-30T11:22:02.492087+00:00.

**No restart is necessary for this frontend-only change:** the existing root
route reads `index.html` on each request and the existing authenticated asset route
serves files from disk. Reloading the existing map page loads the new module,
independently of the earlier backend-gated geodata browser. Restarting would also
activate earlier pending backend changes outside this WMS-only task, so it was
not attempted. No service file was modified.

Actual browser image rendering and the running production map have **not been
live-verified in this session**. Do not mark blocks, compartments, GPS, risks or
service state WORKING/ACTIVE based solely on the simulated map/ASGI tests.
To finish visual verification, open `/#map`, enable each layer and then both,
pan/zoom, verify sector and machinery visibility/clicks, disable both, and check
that a provider failure leaves the operational map usable. No data write is
required for these checks.

Rollback, if needed: restore only `index.html` from this task's backup and reload
the page. The unused new asset may remain. Do not restore the database or overwrite
the existing environment file for a frontend rollback.
