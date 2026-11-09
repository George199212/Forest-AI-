# Production VMD territory discovery and sector import

Implemented 2026-10-30 UTC in `/root/forest_ai`, FastAPI + SQLite + Leaflet.
**The catalogue and implementation are ready and tested. Live service activation
is not verified: this executor cannot access systemd or the host TCP listener.**
No new production sectors were imported during this task.

## 1. Original files and source inspection

Original archive, preserved unchanged: `/root/forest_ai/centra_data.zip` (181 MiB).
SHA256: `089d02c642b44bed8b17cab87cb18c37a322475063407ad001fb8e63e07983fe`.
All 27 entries were listed before extraction. The five SHPs and all matching DBF,
SHX, PRJ and CPG files are permanently extracted beneath:
`/root/forest_ai/data/vmd/source/centra_data/centra/`.

| Source layer | Records | SHP geometry | Attributes |
|---|---:|---|---:|
| nodala2651 | 92,079 | Polygon (2D, multipart supported) | 88 |
| nodala2652 | 79,970 | Polygon | 88 |
| nodala2653 | 114,627 | Polygon | 88 |
| nodala2654 | 116,100 | Polygon | 88 |
| nodala2655 | 111,000 | Polygon | 88 |
| Total | **513,776** | | |

Full per-file schemas, original extents, WKT and encoding are recorded in
`data/vmd/compartments.report.json`. All actual fields are preserved in JSON,
including objectid, adm1/adm2, atvk, kadastrs, kvart/nog/anog, nog_plat, forestry
attributes, formula, codes and Shape_Leng/Shape_Area. Fields are read from the DBF
schema rather than a hardcoded list. UTF-8 encoding is preserved.

The supplied archive is **Centra regional coverage**, not nationwide Latvia.
All available records in this archive are searchable. Areas outside its extent
correctly return no matches; data is never fabricated to fill gaps.

## 2. CRS, normalization and internal store

Every source PRJ declares **LKS-2020 / Latvia TM, EPSG:10306**, not EPSG:3059.
This mapping is documented by [LĢIA](https://www.lgia.gov.lv/lv/lks-2020) and its
[official EPSG code diagram](https://www.lgia.gov.lv/sites/lgia/files/document/Latvijas%20koordin%C4%81tu%20sist%C4%93mas%20EPSG%20kodi%20un%20p%C4%81rejas%20virsma%20LKS92toLKS2020NTv2.pdf).

Normalized dataset: `/root/forest_ai/data/vmd/compartments.sqlite`, approximately
**1.074 GiB**. This is a documented SQLite/WKB spatial catalogue, not a file falsely
labelled GeoPackage. Geometry is EPSG:4326, longitude/latitude. A SQLite RTree stores
per-feature bounding boxes; SQL indexes cover external ID, OBJECTID, cadastral /
quarter / compartment and municipality/parish. Query-plan verification shows an
RTree virtual-table search followed by primary-key feature lookup.

GDAL/ogr2ogr, pyshp and PROJ Python bindings were absent. No new large GIS runtime
or database server was installed. `forestry_io.py` is a bounded streaming reader
specifically for the inspected dBase/2D Polygon source format, using existing
NumPy/Shapely. Unsupported source field/shape/CRS definitions fail closed. All
projection parameters and the GRS80 ellipsoid are checked against the actual PRJ.
Projection uses inverse Transverse Mercator equations and the EPSG:10840 zero-shift
WGS84 approximation. This has metre-level datum limitations and is not a claim of
survey/cadastral legal precision. The projection calculation agrees with the three
independently exported diagnostic features to about 0.0002 m and passes a PROJ
project numerical reference and sub-millimetre forward/inverse roundtrip tests.
The diagnostic file is only a validation reference, never the production source.

All shapefiles are read in bounded batches. The catalogue is built to a temporary
SQLite filename and published atomically only after indexing/integrity checks.
The builder refuses to overwrite an existing published catalogue. Original source
files/attributes and per-feature source row/file lineage remain available.

Builder:

```bash
cd /root/forest_ai
python3 scripts/build_vmd_dataset.py \
  --source data/vmd/source \
  --output data/vmd/compartments.sqlite \
  --archive centra_data.zip
```

That command describes the completed initial build. Do not run it over the existing
catalogue; use a new output filename and review/retain previous versions for updates.

## 3. Validation, repairs and identities

- Source records: **513,776**
- Indexed: **513,776**
- Valid without repair: **513,421**
- Repaired with Shapely make_valid: **355**
- Failed: **0**
- Duplicate external IDs: **0**
- Missing original OBJECTIDs: **0**
- Globally duplicated OBJECTID groups: **0**
- Normalized Polygon: **513,331**; MultiPolygon: **445**

Repair reasons are stored on each affected catalogue record; originals remain in
the source archive/extracted files. The API and popup identify repaired geometries.
No failed feature is silently discarded: the builder has a failed_features audit
table and reconciles source count = indexed + failed (zero failures in this build).

Stable IDs use the original OBJECTID with file lineage, for example:
`VMD:nodala2651:49703942`. File qualification is retained defensively for future
multi-file updates, even though this archive's OBJECTIDs are globally unique.

There are **8,101 repeated kadastrs/kvart/nog groups**. Inspection found distinct
`anog` sub-compartments, distinct OBJECTIDs and different geometries, not records
that should overwrite one another. Those records are retained separately. This is
why the previous cadastral-triplet identity is unsuitable for the full catalogue.

The current operational sector format only supports a simple flat ring. **509,200**
features are eligible for that format; **4,576** remain viewable but are not flattened
for import: 445 MultiPolygons and 4,131 Polygons with holes. No vertex-limit cases
occurred in this archive. 83 records have zero/missing declared nog_plat; their
original value is retained and API area_ha uses computed geometry area instead.

Normalized dataset extent, west/south/east/north:
`22.442701697, 56.252370508, 25.550479494, 57.410061183`.

## 4. Authenticated API

All routes retain existing Basic Auth. POST routes enforce same-origin JSON and a
2 MiB body limit before JSON parsing. No user-supplied filesystem path or remote
URL is fetched.

- `GET /api/geodata/vmd/dataset`: availability, count, extent, source layers/version.
- `GET /api/geodata/vmd/compartments`: bbox min_lon/min_lat/max_lon/max_lat, optional
  limit/offset and kadastrs/kvart/nog/adm1/adm2 filters. Identifiers need no territory.
- `POST /api/geodata/vmd/territory-preview`: validate/normalize a search boundary and
  calculate hectares; does not create a sector.
- `POST /api/geodata/vmd/search-territory`: Polygon/MultiPolygon or GeoJSON boundary,
  mode inside/intersects, minimum overlap %, filters and pagination.
- `POST /api/geodata/vmd/import-selected`: explicit selected IDs + dataset version,
  dry_run (defaults true), confirmed. A real import requires dry_run=false AND
  confirmed=true. Returns requested/imported/already_exists/failed/would_import.
- `GET /api/geodata/vmd/territories`: saved boundaries for the authenticated account.
- `POST /api/geodata/vmd/territories`: explicit save of a named client search boundary.
- `GET /api/geodata/vmd/territories/{id}`: authenticated owner-scoped boundary load.

The old `/test-sectors` endpoint and file remain for diagnostics. Legacy PoC APIs
are not used by the production frontend. Normal UI loads metadata first, then
server-filtered query results; it never loads the three features as the catalogue.

## 5. Client territory and spatial matching

The existing LVM map supports polygon drawing (click corners, Finish), rectangle
(two corners), and GeoJSON upload. Uploads must declare WGS84 or the supported
EPSG:10306 source CRS; unsupported CRS is rejected. Invalid/self-intersecting,
unclosed or oversized boundaries are rejected without guessing/repairing them.
No Leaflet Draw dependency was necessary. KML is not implemented.

A client territory is a blue dashed search boundary, separate from green VMD
compartments and operational sectors. Its area is displayed. It is not evidence of
ownership. Search results show matching full compartment geometry, not clipped
pieces. Explicit Save stores id/name/client_name/source/geometry/area/created_at and
owner in a separate `data/vmd/client_territories.sqlite` sidecar. The sidecar is
created only on an explicit save, not during app startup/search, and is never a
sector database. No production territory was saved during acceptance testing.

SQL RTree filtering selects candidates, followed by exact Shapely intersection.
Inside uses territory.covers(compartment), including coincident boundary coverage.
Intersects includes touching boundaries. Overlap is:
`area(compartment intersection territory) / area(compartment)` using an ellipsoidal
equal-area projection (GRS80 cylindrical equal-area equations). Fully covered
compartments get ratio 1. Original nog_plat and all forestry attributes remain
unchanged. Summary includes total matches, full compartment area, inside/boundary
counts, returned count, offset and next-page state.

Limits: 250 default / 1,000 maximum API results per page; UI requests **100** per
page. Maximum candidate count 50,000, query deadline 20 seconds, client territory
250,000 ha, 20,000 vertices, up to 100 boundary features. Large bbox requests return
an explicit zoom-in response. Searching/changing page clears selection to prevent
hidden selections being imported. Territories above limits must be split/filtered.

## 6. Review, selection and import

Rows and polygons focus each other, with safe text-rendered cadastral, quarter,
compartment, area, adm1/adm2, external ID and overlap popups. anog is also visible.
Selections are amber; focus is blue. Select all (current page), clear selection,
fully inside, overlap >=90% and visible-on-map tools are provided. Selected count
and hectares are shown. Select visible uses Leaflet feature bounds on the current
result page; exact discovery matching remains server-side.

Import requires the explicit button and browser confirmation. At most 100 selected
IDs are accepted per import. Geometry is reread from the indexed server store;
browser coordinates cannot be submitted as sector geometry. Dataset-version mismatch
blocks stale selections. Geometry is preserved, converted to the existing sector
[lat,lon] ring, and stored with its ordinary centroid, area, name and REAL provenance.
No separate operational model or risk engine is introduced.

BEGIN IMMEDIATE, source-ID lookup and the existing source relation's UNIQUE identity
constraint prevent repeated/concurrent imports. Existing sectors are never adopted
by name, updated, deleted or overwritten. Per-feature savepoints prevent orphaned
sector/source writes. Provenance includes VMD_OPEN_DATA, source SHP/record, original
OBJECTID/attributes, external ID, source archive SHA256/version, original and target
CRS, original area, repair reason, timestamps and audit actor.

The earlier real sector 30 is recognized through its VMD_LOCAL identity AND nearly
identical geometry, without rewriting its metadata/geometry. A dry-run check of
`VMD:nodala2651:49703943` returns already_exists, ID 30. Normal production imports
have source VMD_OPEN_DATA and qualified OBJECTID identity.

## 7. Real acceptance and performance

All compartment geometries in these acceptance searches came from the full index.
Search rectangles are test client boundaries, not fabricated forest compartments.

| Territory | Matches | Returned | Time |
|---|---:|---:|---:|
| 3.07 ha | 11 (2 inside, 9 boundary matches) | 11 | 0.012 s |
| 12,295 ha | 8,948 | 100 | 0.954 s |
| 44,274 ha | 23,389 | 100 | 1.728 s |
| 54,645 ha | 29,780 | 100 | 1.563 s |

A production-database dry run validated three selected real records: ready 3,
imported 0. One real record **VMD:nodala2651:49703942** (cadastre 40940020002,
quarter 1, compartment 5) was committed ONLY to a disposable copy of the app DB.
Its normal Sectors and Map API responses contained the preserved boundary, repeated
search marked it ALREADY IMPORTED, and repeating import returned already_exists.
The disposable database was removed. No production import was committed.

Production database: every table's row-content hash matches the pre-task backup.
Sectors **18 -> 18**, risks **19 -> 19**, GPS sessions **29 -> 29**, organizations
**1 -> 1**. Existing source sector 30 remains unchanged. Source archive unchanged.

Tests: **241 Python tests passed** with the documented restricted-environment
same-thread ASGI runner; **25 JavaScript checks passed** (production UI, existing
WMS and prior regression coverage). Additional final targeted geometry/API tests
passed. Python compilation, inline/module JS syntax and whitespace checks passed.
Real ASGI acceptance used the actual full catalogue and a read-only production DB;
committed import tests used only isolated databases. Leaflet UI tests use a simulated
DOM/map. A live Chrome end-to-end test is still outstanding.

## 8. Files and backups

Backup: `/root/forest_ai_backups/vmd_full_dataset_20261030T153108Z/`.
Includes previous versions of every modified existing file, a consistent operational
DB snapshot, service configuration and pre-change status/manifest. Review patch and
acceptance/integrity JSON reports are stored there. No .env/auth/port changes.

Modified application files: `api.py`, `index.html`, `assets/lvm-geodata.js`.
New application modules/assets:
`services/geodata/forestry_io.py`, `services/geodata/vmd_dataset.py`,
`services/geodata/vmd_production.py`, `assets/vmd-production.js`.
New builder: `scripts/build_vmd_dataset.py`.
Tests added: `tests/test_forestry_ingest.py`, `tests/test_vmd_production.py`,
`tests/test_vmd_production_ui.js`. Existing integration test
`tests/test_vmd_test_geojson.js` updated for production labels/module.
This document is new. Old `assets/vmd-local.js` remains as historical PoC code but
is no longer loaded in the production page.

## 9. Deployment state and remaining limits

Only `systemctl restart forest-api.service` was attempted. It and status inspection
were denied with `Failed to connect to bus: Operation not permitted`. No restart
occurred from this session. Localhost GET `/api/geodata/vmd/dataset` returned HTTP
000 because this executor cannot open host network sockets. Recent readable journals
have no startup-failure/error/traceback patterns, but do not establish that the new
code is active. **Service health / live activation cannot be declared verified.**

A normal production host-shell activation of the reviewed code is still required,
followed by authenticated localhost HTTP and Chrome checks. No client/demo service
on ports 8002/8003/8004 was edited or restarted. Live LVM/WMS unreachability did not
block any local indexing, search or acceptance test. WMS remains a separate optional
reference overlay; operational Map/Risks/GPS/Satellite code was preserved.

After activation, hard-refresh `http://164.90.188.136:8000/#lvm-geodata`. Expect
VMD LOCAL DATASET AVAILABLE, 513,776 indexed records and Centra coverage warning.
Define a small territory, Find nogabali, review/select, and use Validate selection
(no import) first. Only the confirmed Import selected action creates sectors.

Remaining source/product limits: regional coverage, metre-level datum approximation,
355 repaired geometries needing review, complex geometries safely non-importable,
83 missing/zero declared areas (computed fallback), bounded query/upload/import
sizes, GeoJSON-only boundary upload, and live activation/browser verification pending.
Do not restore the whole operational database as a routine code rollback.
