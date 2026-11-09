# Cadastral validation and sector registration — 2026-11-06

Deployed at http://164.90.188.136:8000/#lvm-geodata, frontend `geo-01c0edb28098`.
FastAPI serves `/root/forest_ai/index.html` and `/root/forest_ai/assets/` directly.
`forest-api.service`, `/usr/local/bin/uvicorn api:app --host 0.0.0.0 --port 8000`, working directory `/root/forest_ai`, active PID 2711214 after restart 14:33:05 UTC. No alternate frontend/site deployment.

## Actual cause and source evidence

The search's exact SQL `kadastrs = ?` was not returning nearby polygons. Multiple disconnected VMD compartments genuinely have the same cadastral attribute. The missing distinction was between verified VMD source attributes and independently verified cadastral land-unit geometry. The registration map also displayed pre-existing operational sectors as context; that overlay has been removed from this registration page so unrelated sectors cannot be confused with exact VMD results. The main operational map remains intact.

Original VMD Centra source: https://data.gov.lv/dati/dataset/40014c0a-90f5-42be-afb2-fe3c4b8adf92/resource/392dfb67-eeeb-43c2-b082-35f9cf986128/download/centra.7z . Source verification is recorded in `data/vmd/source-verification-20261106.json`. The original data has not been modified.

Exact original DBF mappings: `kadastrs` (character, width254) land-unit designation, `objectid` source feature ID qualified by SHP filename, `kvart` forest quarter, `nog` compartment, `anog` subcompartment, `nog_plat` declared hectares. No separate cadastral property number is asserted. Leading zeros are preserved. Every exact result is checked against its original DBF record, independently of geometry validity. The source CRS is EPSG:10306; normalized GeoJSON is longitude/latitude EPSG:4326. Transformation agreement against PROJ is algorithmic evidence, not a survey accuracy claim; PROJ's geographic datum operation is ballpark with unknown accuracy.

Authoritative cadastral geometry was obtained from the VZD-published open dataset https://data.gov.lv/dati/dataset/kadastra-informacijas-sistemas-atverti-telpiskie-dati . Official Riga resource `bf88b763-98b8-445d-a51f-b76f45c362c5`, Bauska resource `e1a23379-0513-448a-be76-9a8f97d7c466`. `KKParcel.CODE` is an 11-character land-unit designation; original parcel geometry and VMD geometry are compared directly in EPSG:10306. Archives, hashes, source records, raw attributes, original/normalized parcel geometries and retrieval timestamps are retained under `data/cadastre/`. Licence/attribution: VZD, CC BY4.0. The official WFS endpoint discovered from the catalogue timed out; the official SHP downloads succeeded. No WMS raster was traced or used as vector evidence.

| Designation | Exact VMD records | Strictly contained in matching VZD parcel | Boundary review required | Currently registerable |
|---|---:|---:|---:|---:|
| 01000950030 | 209 | 184 | 25 | 177 |
| 40940020002 | 10 | 2 | 8 | 2 |
| 01000950031 | 6 | 1 | 5 | 1 |

Registerability also respects existing imported sectors and the existing simple-Polygon sector engine. Valid complex polygons are preserved and displayed, never flattened to fit the engine.

`01000950031` is present as exactly one valid VZD parcel (`ExportCadGroup_0100095/KKParcel.shp`, original record168, `CODE=01000950031`), area5.179558728ha. The following six records all occur in original VMD `nodala2653.shp`, have raw `kadastrs=01000950031`, quarter268 and valid geometries:

| Source OBJECTID | Nogabals | Declared ha | VMD centroid longitude | Latitude | VZD containment |
|---|---:|---:|---:|---:|---|
| 70588598 | 15 | 0.50 | 24.129688705 | 57.010752591 | Boundary review |
| 70588599 | 16 | 0.11 | 24.129665219 | 57.006618623 | Fully inside |
| 70588600 | 17 | 1.03 | 24.129865509 | 57.004079364 | Boundary review |
| 70588601 | 18 | 0.56 | 24.131284788 | 57.001419676 | Boundary review |
| 70588602 | 19 | 0.15 | 24.132163601 | 57.000234360 | Boundary review |
| 105553907 | 20 | 0.24 | 24.129762525 | 57.012111592 | Boundary review |

Total VMD declared area2.59ha. Each overlaps the exact VZD parcel by99.998079565%–100%; total source geometry outside that parcel is0.172508858m². Identifiers agree and geometry is consistent at this scale, but five boundaries are not strictly contained. They remain blocked pending review. No tolerance, buffering, clipping, simplification or alteration is applied. Disconnection does not establish a different cadastral identity. Exact identifiers are the primary association evidence; spatial overlap is a separate check, never an identity substitute.

Detailed immutable-source audit tables/geometry comparisons: `data/vmd/cadastral-audit-{01000950030,01000950031,40940020002}/audit.{json,csv}`. Per-record independent cadastral checks: `data/vmd/cadastral-authority-audit.json`.

## Behaviour and ownership

Exact 11 ASCII digits only; no proximity/prefix/alternative-ID fallback in the registration UI/API. Green polygons are VMD forest compartments; blue dashed polygon is the separate VZD land unit. Missing authoritative data shows **Kadastra dati nav pārbaudīti** and registration is disabled and rejected server-side. Source-attribute failure also fails closed. Boundary discrepancies have a separate review status and cannot register. The old `/api/geodata/vmd/import` endpoint is blocked409 to prevent bypassing validation.

Removed client name/ID ownership form. Responsible first/last names are contact fields. Registration context and organization come from the server's existing single-organization instance; caller-supplied organization/user/client ownership fields are rejected. Saved metadata includes organization, contact, authenticated account, timestamp, source IDs, original CRS/native VMD geometry, normalized geometry and cadastral evidence. Duplicate source identities are organization-scoped and transactional; existing sectors are never overwritten.

**Identity limitation:** this deployment has a single shared HTTP Basic account and no individual dashboard users, membership/session IDs or profiles. `created_by_user_id` stays NULL; `created_by_account` records the real authenticated account. Names are not guessed from the username. Previous registration contacts can prefill explicitly as contact history. Individual-profile prefill and actual separate-user/same-organization authentication tests remain BLOCKED until a real identity/profile/membership source is provided. Unit tests simulate trusted same-organization actors and verify shared duplicate visibility and fail-closed behavior for ambiguous organizations; they do not establish deployed multi-user authentication.

## Changed files in this task

`api.py`, `database.py`, `index.html`, `assets/lvm-geodata.js`, `assets/vmd-production.js`, `assets/vmd-workflow.css`, `services/geodata/registration_identity.py`, `services/geodata/cadastral_authority.py`, `services/geodata/vmd_dataset.py`, `services/geodata/vmd_production.py`, `scripts/ingest_vzd_verification.py`, `scripts/verify_vmd_cadastral_registration.py`, `tests/test_vmd_production.py`, `tests/test_vmd_production_ui.js`, `tests/test_vmd_local_import.py`; audit/verification artifacts and this report. The read-only `scripts/audit_vmd_cadastre.py` was used for all three native-source audits. Other pre-existing working-tree changes were not reset or bundled into a commit.

## Tests and deployment evidence

-264 Python tests passed via `/tmp/forest_same_thread_tests.py` (execution-environment workaround for TestClient portal; application source unmodified by workaround). Regression coverage includes native DBF exact matches/leading zeros, actual source geometries/all pages, unknown designation, independent authority gate, strict discrepancy blocking, ownership forgery, same-org duplicates, rollback and migration preservation.
-28 JavaScript tests passed:9 registration controller,9 WMS map,7 legacy VMD UI,3 GeoJSON. Synthetic authority fixtures are explicitly unit-test-only.
-Real Chromium on an isolated production SQLite backup registered2 Riga,2 Bauska and1 strictly-contained `01000950031` compartment; verified native geometry hashes/source CRS, duplicates, main-map availability and persistence after reload, backend restart and new authenticated browser context. `data/vmd/verified-persistence.json`.
-Actual public Chromium verified all209/10/6 polygons across pages against independent audits, source identifiers, selection/deselection, real geometry previews, blocked discrepant registrations, no client fields, unchanged Esri default with HTTP200 tiles, and zero blocking JS errors. `data/vmd/verified-live.json` and `data/vmd/verified-*-live.png`. Production browser checks created **zero sectors**.
-Production `/api/geodata/vmd/dataset`: HTTP200 AVAILABLE,513776 indexed; served JS HTTP200 exactly matches tested file. `/api/geodata/lvm/health`: HTTP200 but statusUNAVAILABLE,0 layers (separate external LVM service blocker). `data/vmd/verified-production-endpoints.json`.
-Backup before migration/restart: `data/backups/cadastral_authority_20261106T143022Z/forest_ai.db`, SQLite integrityok. Additive migration tested on a copy. After restart:21 existing sectors,19 risks,29 work sessions,1 organization,4 source links; all pre-existing sector fields and every risk row exactly preserved against the immediate pre-deploy snapshot. Existing sectors31–33 were created before this deployment and were preserved.
-Only `forest-api.service` restarted. John Deere, satellite/risk engine and other client services were not modified. Esri tiles/default selection and Leaflet preserved.

## Remaining limits and manual verification

Only the three requested official parcel snapshots have been ingested; any other designation remains unverified and blocked until an official exact KKParcel record is ingested using the provenance-preserving script. This is a dated VZD snapshot, not a real-time cadastral or ownership certification. Boundary discrepancies require source review, not automatic correction. Multipart/holes remain unsupported by the existing sector engine and are never approximated. Individual-user identity and external LVM health are blocked as described above.

Open the live URL, confirm version `geo-01c0edb28098`, search `01000950031`: six VMD rows, quarter268/nogabali15–20, separate blue VZD land-unit boundary, one eligible checkbox (nogabals16), five review blocks. Search an unavailable designation: “Kadastra dati nav pārbaudīti”, no registration. Search `01000950030`:209 total and100/100/9 pages; selection remains stable. Enter responsible contact, select a verified eligible compartment and open preview. Confirm registration only for an intended production sector; then check Sektori/Karte and refresh. Production acceptance deliberately stopped at preview for eligible records.
