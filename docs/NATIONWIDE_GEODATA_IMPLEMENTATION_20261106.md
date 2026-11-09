# Nationwide VZD + VMD implementation — 2026-11-06

## Delivered data and source verification

The former catalogue contained only Centra (513,776 compartments), while cadastral verification exposed seven individually extracted VZD parcels. Exact searches outside those subsets could not work. The replacement is a separate immutable public-data catalogue; the operational database and existing sector IDs are preserved.

All five official VMD archives and all 42 VZD municipal archives have been downloaded and validated. Source archive sizes, SHA256, CRC, schemas, source dates, licences, CRS, record conservation and SQLite/RTree integrity were checked.

- VMD: **3,063,409** compartments; five regions; zero failed records or conflicting IDs.
- VZD: **1,055,666** unique parcels from 1,059,766 source records; 4,100 identical duplicate records retained in provenance; zero conflicting IDs.
- VMD publication: 2026-10-07; SHP/DBF export: 2026-10-08. VZD export: 2026-10-31.
- VMD CC0-1.0; VZD CC BY 4.0. Individual source URLs, hashes and dates are retained in release.json/sources.json.
- Source CRS is EPSG:10306 (LKS-2020 Latvia TM), confirmed from PRJ. Original coordinates are retained; display is EPSG:4326. EPSG:3059 input is supported without mislabelling the current source datum.
- 1,723 invalid source/display-repaired forest geometries remain preserved and unavailable for automatic registration.

## Query, map and registration

VZD KKParcel.CODE is the exact 11-character land-unit designation. VMD kadastrs is its reported cadastral designation; objectid qualified by layer is the feature identity; kvart and nog are quarter and compartment. No property-number association is fabricated. Leading zeros remain strings.

The indexed lookup resolves the official VZD parcel first, then separately evaluates exact VMD attributes and native-CRS intersections. Only exact source associations with valid fully-contained geometry can be automatically registered. Different-code spatial candidates and boundary discrepancies remain nonselectable review records. Intersection alone establishes neither cadastral membership nor ownership.

Blue cadastral boundaries, green verified forest compartments and orange review geometries share the existing Leaflet/Esri map. Search fits the cadastral polygon. Pagination and selection persist. The existing three-step registration stores the required sector name, separate responsible-person names, source/native geometries, CRS, immutable VZD geometry reference, source metadata, authenticated account/organization and timestamps. Existing duplicate and transaction protection remain in force.

## Changes

- New services/geodata/nationwide.py: read-only national indexes, parcel validation, explicit result states and provenance.
- Updated services/geodata/{vmd_dataset,cadastral_authority,vmd_production}.py: national routing, secure import verification, status/progress endpoint.
- Updated assets/vmd-production.js and index.html: official parcel boundary, independent spatial review, pagination and request scope.
- New scripts/ingest_nationwide_geodata.py: resumable downloads, archive checks, transactional row checkpoints, spatial indexes and immutable releases.
- New scripts/publish_nationwide_geodata.py: integrity/acceptance-gated atomic activation.
- New scripts/verify_nationwide_registration.py and tests/test_nationwide_geodata.py; expanded registration-controller tests.
- deploy/forest-geodata-ingest@.service, deploy/forest-api-geodata.conf; requirements-geodata-ingest.txt and numpy requirement.
- No operational database migration. Separate national SQLite files and active.json select the release.

## Tests

280 Python tests and 35 JavaScript tests passed; syntax/build checks passed. National unit coverage includes leading zeros, unavailable/error states, spatial candidates, foreign-candidate import rejection, source geometry preservation, duplicate protection, ownership and resumable downloads.

Chromium staging acceptance used an isolated consistent production database backup. Each positive case was independently checked against original VZD and VMD DBF/SHP records and PROJ transformation. All ten searches, selections, reviews and registrations passed; the ten sectors appeared in Sektori and Karte and survived browser refresh, backend restart and a fresh login. Original source geometries and organization ownership matched. Duplicate attempts were blocked.

| Region | Land unit | Exact VMD records | Automatically registrable | Spatial review candidates | Staging registration |
|---|---|---:|---:|---:|---|
| Austrumu | 36680080065 | 435 | 365 | 87 | Passed |
| Austrumu | 36680010022 | 8 | 7 | 11 | Passed |
| Centra | 01000950031 | 6 | 1 | 7 | Passed |
| Centra | 32900020043 | 25 | 15 | 3 | Passed |
| Dienvidu | 32920120011 | 11 | 4 | 9 | Passed |
| Dienvidu | 32960090079 | 7 | 2 | 11 | Passed |
| Kurzemes | 64960030075 | 144 | 122 | 37 | Passed |
| Kurzemes | 64960010131 | 298 | 245 | 54 | Passed |
| Vidzemes | 42680030058 | 47 | 28 | 18 | Passed |
| Vidzemes | 42560060473 | 15 | 7 | 4 | Passed |

The 435-record query traversed every page with selection preserved. An explicit staging-only HTTP 503 injection blocked stale imports and recovered on retry. Bulk preview: 83 compartments, 221,975 bytes, 0.281 seconds. Sample national queries took roughly 0.04–0.53 seconds. Interrupted ingestion resumed from committed checkpoints without changing already indexed sample geometries.

## Deployment

Deployed at **http://164.90.188.136:8000/#lvm-geodata**. Frontend files are `/root/forest_ai/index.html` and `/root/forest_ai/assets/vmd-production.js`, served by the existing FastAPI service (no replacement host/site). Frontend version: **geo-cac1a48e954b**. Dataset version: `15b2ef2b3e6b4bba295c309fa237ac49bd06772b36440c10d38d8a0b47eeb13a`.

Only `forest-api.service` was restarted (2026-11-06 19:20:02 UTC, PID 2722711), using its established `/usr/local/bin/uvicorn api:app` configuration. The added `/etc/systemd/system/forest-api.service.d/geodata.conf` points to the atomic national manifest. The enabled ingestion instance `forest-geodata-ingest@20261106.service` successfully exited with status 0 after confirming the release was already complete; it resumes/checks on boot. An inactive successfully completed worker is expected.

Production `/api/geodata/vmd/dataset` returned HTTP 200 / DATASET_READY with all 47 sources and the expected counts/version. `/api/geodata/vmd/ingestion` returned HTTP 200. The public JavaScript matched the local deployed bytes (SHA256 `494fefb9351ae723d32934ac88aa6aca3b23da66468b53baca0624269a1941ee`). Chromium verified all ten tabled parcels on the actual URL after restart, including blue cadastral bounds, Esri default, exact forest geometry, selection, all 435 result records across pages and registration previews. No browser errors were recorded. Production acceptance deliberately created **zero** test sectors; the ten full registrations/restart-persistence checks were staged.

The pre-cutover database backup `data/backups/national_cutover_20261106T191323Z/forest_ai.db` passed integrity_check. All 21 existing sectors, 19 risks, one organization, 29 work sessions and four source links matched their pre-cutover rows after restart and live checks. Eighteen protected satellite/risk/John Deere files retained their prior hashes. No operational schema migration or credentials change occurred. Production warning logs since restart contained no entries.

Evidence: release-local `publication-check.json`, `staging-acceptance.json`, `live-acceptance.json`, `live-api-status.json`, `resume-verification.json`, `release.json`, `validated-sources.json` and per-source archive integrity markers.

## Limits

National coverage describes the complete published archives, not every physical forest or a live cadastral survey. Source snapshots can lag changes. Invalid, multipart/holed geometries unsupported by the existing sector engine and boundary discrepancies remain review-only, rather than flattened or approximated. Exact source association is publisher-backed; spatial-only candidates are explicitly inferred and blocked from automatic registration. Neither establishes legal ownership. No Sentinel, risk-engine, satellite, John Deere or production-sector replacement is included. The separate live LVM service health endpoint returns HTTP 200 with status UNAVAILABLE; national VZD/VMD bulk-data lookup does not depend on it.

See NATIONWIDE_GEODATA_OPERATIONS.md for checkpoints, jobs, future releases and rollback.

## Manual verification

1. Sign into the existing account at the public URL above; confirm frontend version geo-cac1a48e954b and nationwide dataset counts.
2. Search a tabled designation, for example 36680010022 or 01000950031. Confirm blue VZD boundary, source identifiers and green eligible compartments; orange review records must remain unavailable for automatic registration.
3. Select a green compartment, review its geometry/source and enter the real sector name and responsible person. Confirm registration under the authenticated organization.
4. Open Sektori and Karte, verify the saved source identity/name/geometry, refresh and sign in again. Repeat registration should be rejected as a duplicate.
5. For operational restart checks, restart only forest-api.service and repeat step 4. Do not create test sectors in production with fictional responsible-person details.
