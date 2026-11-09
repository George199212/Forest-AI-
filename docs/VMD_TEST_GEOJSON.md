# Three real VMD forest compartments — visual test only

Implemented 2026-10-30 UTC in `/root/forest_ai`.

## Scope and inspected application

The application found on disk is **FastAPI**, not Flask. It already uses global
HTTP Basic dashboard authentication. The existing LVM GEO page is the `lvm-geodata`
hash route in `index.html`, with map initialization in `assets/lvm-geodata.js`.
The configured `forest-api.service` launches `uvicorn api:app` on port 8000 with
WorkingDirectory `/root/forest_ai`. The actual live process/template cannot be
independently inspected from this restricted executor; no different client copy
was edited. No second framework or application was introduced.

## Endpoint

`GET /api/geodata/vmd/test-sectors`

The authenticated endpoint reads only the fixed local file
`/root/forest_ai/lvm_3_sectors.geojson`. It returns the existing FeatureCollection
with `Content-Type: application/geo+json`, `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`. There is no upload, arbitrary file path, provider
request, sector import or database access in this path.

The file is validated for maximum size, JSON/CRS, exactly three Polygon features,
finite WGS84 longitude/latitude positions, closed rings and valid polygon geometry.
Missing/unreadable file returns 503; malformed, empty or invalid data returns a
safe 422 response without exposing filesystem paths. Existing authentication is
unchanged. No production database migration is required by this feature.

The source file identifies its CRS as `urn:ogc:def:crs:OGC:1.3:CRS84`, meaning WGS84
longitude/latitude, directly compatible with Leaflet GeoJSON. It is returned
unchanged, including all original coordinates and properties.

Actual source properties verified:

| Cadastre (`kadastrs`) | Quarter (`kvart`) | Compartment (`nog`) | Area (`nog_plat`) |
|---|---:|---:|---:|
| 40940020002 | 1 | 6 | 0.18 ha |
| 32620090044 | 1 | 1 | 0.66 ha |
| 40440040167 | 1 | 4 | 0.82 ha |

The third cadastre in the actual file is **40440040167**, differing from
404400400167 in the request. It was not altered or guessed.

## Map

The existing LVM map loads this fixed local endpoint with `L.geoJSON()` before
external capability discovery, so LVM GEO being offline does not hide this local
visual test. The OSM base and existing Forest AI sector layer remain in place.

The new, initially visible overlay is named **VMD Forest Compartments (test)**.
Polygons have purple dashed outlines and translucent purple fill. A dedicated
pane at z-index 350 keeps them above WMS context and below existing operational
sector paths. They have their own toggle and are not assigned to the sector
import selection or import API. No Sector records are created.

Clicking a polygon opens text-rendered popup fields:

- VMD Forest Compartment
- Cadastre: kadastrs
- Quarter: kvart
- Compartment: nog
- Area: nog_plat ha

The map fits to the combined bounds of all three polygons on successful first
load. Reopening the page does not duplicate the layer, force it back on, or reset
a user's subsequent pan/zoom. Concurrent initial requests are deduplicated.
Endpoint failure, invalid JSON/GeoJSON, empty results and a 10-second timeout are
reported in a small map status control; other map layers remain available.

## Files and backup

Backup: `/root/forest_ai_backups/vmd_test_geojson_20261030T142520Z/`.
Contains original modified files, index/source-file snapshots, consistent SQLite
backup, service unit, manifest and before/after data verification.

Existing files modified:

- `api.py`: one authenticated GET route.
- `assets/lvm-geodata.js`: visual overlay and local-data-before-capabilities order.

New files:

- `services/geodata/vmd_test.py`: bounded, read-only source validation/reader.
- `tests/test_vmd_test_geojson.py`
- `tests/test_vmd_test_geojson.js`
- `docs/VMD_TEST_GEOJSON.md`

`index.html`, the source GeoJSON, WMS implementation, authentication, service
configuration, environments, dependencies and client instances were not modified.

## Verification

- New Python tests: **12 passed**; cover source fidelity, geometry/data failures,
  authentication, status codes and prevention of DB/network calls.
- New JavaScript tests: **6 passed**, using simulated Leaflet/DOM; cover all three
  actual feature properties and popup text, bounds fit, styling/control, safe
  toggles, deduplication and errors without removing the base layer.
- Existing main-map WMS JavaScript tests: **9 passed**.
- Full Python suite: **217 passed** using `/tmp/forest_same_thread_tests.py`, the
  previously documented test-only ASGI workaround for the restricted TestClient
  portal. No production background lifecycle or real provider requests were run.
- A separate local ASGI request using the **actual source file**, not a substitute,
  returned **200 application/geo+json**, exactly three Polygon features and the
  cadastres listed above.
- Python compilation, JavaScript syntax and whitespace checks passed.
- Every production table's row count **and row-content SHA256** matches the backup.
  Database integrity is `ok`. Sectors 17→17, risks 19→19, work_sessions 29→29,
  organizations 1→1. No records were created or modified.
- Source GeoJSON and `index.html` remain byte-for-byte identical to their backups.

## Activation status and browser verification

**Implemented and locally tested; live activation is NOT confirmed.**
The attempted `systemctl restart forest-api.service` and status check returned
`Failed to connect to bus: Operation not permitted`. This is an executor access
failure, not a reported application startup failure. No service restart occurred.
A localhost curl to the new endpoint returned HTTP 000 because the execution
session cannot connect to the host network. The local ASGI test is not a
substitute for a running-production curl or visual browser verification.

The new backend route requires activation of the current API code. From a normal
production host shell, verify the expected unit/PID/working directory and activate
only `forest-api.service`, then check status/logs. Do not restart unrelated client
or bot services. No data migration or test-sector import is part of this feature.

After successful activation:

1. Open `http://164.90.188.136:8000/#lvm-geodata` and hard-refresh to load the updated
   JS asset. Authenticate using the existing dashboard login.
2. Confirm the purple test polygons appear and the map fits their combined bounds.
3. Toggle **VMD Forest Compartments (test)** independently of OSM/LVM context.
4. Click each polygon and verify its cadastre, quarter, compartment and area.
5. Inspect the browser Network request to `/api/geodata/vmd/test-sectors`: HTTP 200
   and exactly three Polygon features. The endpoint may also be opened directly
   in an authenticated browser.
6. Confirm existing operational sectors remain separate. No import action is
   needed or authorized for this visual proof-of-concept.

The endpoint and map have not been falsely described as working on the live
production listener from this restricted session.
