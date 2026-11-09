# Local VMD dataset selection and sector import

Implemented 2026-10-30 UTC in the existing `/root/forest_ai` FastAPI/Leaflet app.
The inspected production configuration remains `forest-api.service`, port 8000.
Authentication, WMS implementation, ports and other client instances are unchanged.

## Local data and live services are independent

Open `http://164.90.188.136:8000/#lvm-geodata` after backend activation and hard-refresh.
The existing LVM map is reused. There is no second map or application.

The page distinguishes **LVM GEO Live Service** (which may remain UNAVAILABLE)
from **VMD Forest Compartments — Local Dataset**. The local card reports source
Local GeoJSON, dynamic feature count, EPSG:4326, READY and importability. It never
claims the local file is a live LVM/VMD network API.

The local GeoJSON request uses the existing authenticated same-origin browser
session. Green outlines and light fill identify the local polygons; focus is blue
and checkbox selection is amber. The map fits the dataset bounds after first load.
Polygons remain in a separate Leaflet GeoJSON group/pane below operational paths.
The existing OSM and main-map LVM WMS controls are preserved.

The existing feature-selection area shows Select, Kadastrs, Kvartāls, Nogabals,
Area (ha), Source and Status. Polygon clicks focus/highlight the matching row and
show a text-rendered popup. Row clicks focus/zoom the polygon. Checkbox selection
is independent. Select all selects eligible rows currently listed; Clear selection
clears selection. Imported features are marked IMPORTED with their sector name.

The existing preview button uses the already-loaded local data while local mode
is active. It computes polygon/rectangle intersections client-side, including edge
contact and polygon holes, rather than merely testing bounding boxes. It lists
only intersecting compartments and clears selections hidden by that filter. It
makes no live service request. Choosing a live layer restores the existing live
preview/import behavior; Use local dataset switches back to local mode.

## API routes

All routes retain the existing dashboard Basic Auth.

- Existing `GET /api/geodata/vmd/test-sectors`: still returns the original local
  FeatureCollection. Adds an ETag containing the canonical dataset SHA256.
- New `GET /api/geodata/vmd/local-status`: local source metadata, count, version,
  stable external IDs, READY/IMPORTED/FAILED status, import eligibility and existing
  sector references. Read-only.
- New `POST /api/geodata/vmd/import`: accepts only `feature_ids` and `dataset_version`.
  It requires JSON, rejects extra fields and cross-origin browser mutations, and
  uses the authenticated username for its audit actor. No credentials are embedded
  in JavaScript and no organization, database path, URL or geometry can be supplied.

Identity is `VMD-{kadastrs}-{kvart}-{nog}`. Quarter/compartment numeric text is
canonicalized, with original properties retained in provenance. The server rereads
and validates the source and checks the dataset version before any import; a
changed preview returns 409. The source file itself is never modified.

The reader no longer assumes exactly three features. It supports bounded local
Polygon datasets up to 10,000 features / 32 MiB. Current default GET still returns
exactly the three actual features. Reading, catalogue/identity preparation, status
lookup, rendering and viewport filtering are separated so future indexed/server
filters can replace the file source without rewriting sector storage. Loading all
features into the browser is the current proof-of-concept; indexed territory,
municipality and cadastral search are future work.

## Existing sector storage reused

No new tables, columns or operational object model were introduced. Existing
`sectors` stores the geometry in its normal flat `[latitude, longitude]` ring;
GeoJSON longitude/latitude is swapped exactly once without simplification. Existing
centroid and geometry validation helpers are reused. `area_ha` preserves the source
`nog_plat`. Polygon holes remain viewable but are not importable because current
operational sector/GPS code supports a single ring only.

The existing `database.add_sector()` is an upsert and may overwrite a sector with
the same name. The import deliberately uses an insert-only transaction against
the same sector schema, with an explicit name-collision check. A readable name
such as `VMD 40940020002 - 1-6` avoids slashes, which existing sector URLs cannot
represent as a single path segment.

The existing `geodata_sources` relation stores provider `VMD_LOCAL`, stable source
layer `vmd_local_compartments`, external ID, dataset title, VMD/LVM attribution,
source CRS, original properties, source/ID/version mapping and timestamps. The
existing boundary history records geometry/source/actor with action IMPORT_LOCAL_VMD.
A local sector's data-source block links to the local dataset rather than offering
the unrelated live LVM boundary-refresh action.

The import uses BEGIN IMMEDIATE, source-identity lookup and the existing database
UNIQUE organization/provider/layer/feature constraint. The fixed local layer key
remains stable when the backing file is replaced. Concurrent duplicate imports
return the same existing sector. Existing same-name manual sectors are not adopted
or overwritten. Missing/deleted source mappings require review instead of silently
creating replacements. Each result is imported, already_exists or failed; savepoints
prevent partial sector/provenance writes for a failed item. A request imports at
most 25 selected IDs and never automatically imports unselected features.

Client isolation follows the existing authenticated per-instance database model.
No client database, API or service on ports 8002/8003/8004 was modified.

## Production test actually performed

Exactly one compartment was imported into `/root/forest_ai/data/forest_ai.db` through
the same import service used by the new API (an authorized internal CLI validation,
not an HTTP request to the running listener):

- Source ID: **VMD-40940020002-1-6**
- Ordinary Forest AI sector ID: **30**
- Name: **VMD 40940020002 - 1-6**
- Area: **0.18 ha**
- Status: **Planned**, data_origin REAL
- Audit actor: `system:vmd-local-production-test`

A second call for that same ID returned `already_exists`, sector 30, with zero new
sectors/history. The other two compartments remain READY and were NOT imported:
VMD-32620090044-1-1 and VMD-40440040167-1-4.

| Production table | Before | After |
|---|---:|---:|
| sectors | 17 | 18 |
| risks | 19 | 19 |
| work_sessions | 29 | 29 |
| organizations | 1 | 1 |

Every preexisting row was preserved. Only one sector, one source relation and one
history row were added, plus their normal SQLite sequence counters. No schema
changes occurred. No worker was assigned and no risk/Telegram alert was created.
The source GeoJSON is byte-for-byte unchanged. Database integrity is ok.

The test sector is retained as Planned. Do not remove it automatically.

## Tests

- **227 Python tests passed**, using the existing restricted-environment same-thread
  ASGI runner `/tmp/forest_same_thread_tests.py`. Background lifecycle jobs and real
  provider calls are not run by this test runner.
- **19 JavaScript tests passed**: 7 local UI/intersection tests, 3 LVM/local integration
  tests, and 9 existing WMS regression tests, using simulated Leaflet/DOM.
- Python compilation, SPA inline-JS syntax, JS module syntax and whitespace checks
  passed.
- Tests cover source fidelity, more than three features, version mismatch, manual
  name collision, partial failure, parallel duplicate calls, client database isolation,
  HTTP auth/CSRF, selection, map/table focus, viewport filtering, and imported status.
- In-process ASGI requests against the actual production DB returned 200 for root,
  new asset, source/status, ordinary sectors, main map, risks, GPS, machines and
  summary. Ordinary sector detail also returns sector 30. The main map data contains
  its polygon, area 0.18, and the existing point-in-polygon helper accepts an inside
  point. Test-only auth values were set only in that validation subprocess; live
  credentials were not changed. This is not a live TCP/Chrome test.

## Backup and changed files

Backup: `/root/forest_ai_backups/vmd_local_import_20261030T145626Z/`.
Includes all previous versions of modified files, source-file snapshot, service
unit, online database backup, manifest and a second fresh database backup immediately
before the authorized test import (`forest_ai.before_test_import.db`).
`production_import_test.json` records both real import results and before/after
counts. `production_asgi_smoke.json` records API validation. `implementation.patch`
is the exact diff from this task's backup, preserving earlier unrelated edits.

Existing files changed:

- `api.py`
- `index.html`
- `assets/lvm-geodata.js`
- `services/geodata/vmd_test.py`
- `tests/test_vmd_test_geojson.py`
- `tests/test_vmd_test_geojson.js`

New files:

- `services/geodata/vmd_local.py`
- `assets/vmd-local.js`
- `tests/test_vmd_local_import.py`
- `tests/test_vmd_local_ui.js`
- `docs/VMD_LOCAL_IMPORT.md`

## Deployment limitation

The attempted restart of ONLY `forest-api.service` and its status check were denied:
`Failed to connect to bus: Operation not permitted`. No restart occurred from this
session. Localhost curl of the new status route returned HTTP 000 because this
executor cannot connect to the host network. The last 100 readable journals have
no error/startup-failure/traceback patterns, but that does not verify the new API's
live activation. The prior recorded process started successfully at 14:46 UTC,
before these changes.

A host-shell restart/activation and Chrome verification remain outstanding. Do not
claim the new live import UI/API is deployed solely because the CLI import and
in-process requests passed. The new sector itself IS committed in the production
DB, and the existing operational APIs read it normally.

After activating the reviewed code from a normal host shell, open
`http://164.90.188.136:8000/#lvm-geodata` and hard-refresh. Expect LOCAL DATA / READY /
3 compartments; one IMPORTED and two READY rows. The live-service status may remain
UNAVAILABLE. Use `/#sectors` or `/#map` to find sector 30. Select/preview without
importing the remaining two unless explicitly desired. Keep the source GeoJSON and
all current records; do not restore the entire database as a routine code rollback.
