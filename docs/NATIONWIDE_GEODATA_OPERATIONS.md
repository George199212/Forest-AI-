# Nationwide VZD + VMD operations

Operational sectors/accounts remain in the existing application SQLite database. National public geodata is a separate immutable release under `data/geodata/nationwide/releases/`. Esri/Leaflet, authentication and the risk engine are unchanged.

## Ingest and resume

Install the archive decoder into the isolated worker dependency directory (not the production Python site-packages):

```bash
python3 -m pip install --target data/geodata/ingest-deps -r requirements-geodata-ingest.txt
nice -n 10 python3 scripts/ingest_nationwide_geodata.py --root data/geodata/nationwide/releases/RELEASE_ID
```

Rerunning the same command resumes `.part` downloads using validated HTTP ranges, reuses CRC/SHA-verified archives and resumes each SHP from its transactional SQLite/SHX row checkpoint. Completed releases are not rebuilt in place. Use a new release ID for new source dates. A file lock prevents concurrent writers. `progress.json`, `validated-sources.json`, SQLite `files`, `rejections` and `duplicate_sources` expose committed progress and exceptions.

The supplied systemd template `deploy/forest-geodata-ingest@.service` resumes an enabled release after worker/host failure. It limits CPU/memory and restricts writes to the national-data directory. Example instance: `forest-geodata-ingest@20261106.service`. No credentials are required for the approved official bulk downloads.

The worker discovers all five VMD archives and all 42 VZD municipal SHP archives from the official catalogue, checks licence IDs, archive sizes and internal CRC, stores SHA256 and publication/export dates, validates polygon/CRS/DBF definitions, and conserves source record counts. Every identifier remains text. Native originals are preserved; display-only repairs are flagged and cannot be automatically imported. Conflicting duplicate identities are retained for review, not overwritten. No synthetic geometry is generated.

## Staging acceptance and publication

```bash
FOREST_PLAYWRIGHT_PATH=/tmp/forest_browser PLAYWRIGHT_BROWSERS_PATH=/tmp/forest_chromium python3 scripts/verify_nationwide_registration.py --manifest data/geodata/nationwide/releases/RELEASE_ID/release.json
python3 scripts/publish_nationwide_geodata.py --manifest data/geodata/nationwide/releases/RELEASE_ID/release.json
python3 scripts/publish_nationwide_geodata.py --manifest data/geodata/nationwide/releases/RELEASE_ID/release.json --activate
```

The acceptance script copies the current production DB into a disposable directory. It finds ten actual independently source-verified land units (two per forestry region), checks original VMD and VZD DBF/SHP records and coordinate transformations, registers sectors with the existing authenticated API, verifies Sektori/Karte and source metadata, prevents duplicates, reloads/restarts the disposable service and checks persistence through a fresh browser context. Its test contacts are never written into production.

Publication refuses missing sources, failed integrity/count/identifier checks or absent/failed ten-unit acceptance. It changes only the geodata pointer `data/geodata/nationwide/active.json`, retaining the previous pointer. Configure the existing application service with `deploy/forest-api-geodata.conf` so missing national data resolves to explicit unavailable states, rather than silently reverting to Centra.

After activation restart only `forest-api.service`; verify the public URL, backend dataset version, index/source counts and production logs. Live acceptance uses previews, not production test-sector writes:

```bash
FOREST_PLAYWRIGHT_PATH=/tmp/forest_browser PLAYWRIGHT_BROWSERS_PATH=/tmp/forest_chromium python3 scripts/verify_nationwide_registration.py --manifest data/geodata/nationwide/releases/RELEASE_ID/release.json --live
```

## API and evidence

- Authenticated `GET /api/geodata/vmd/dataset`: active index counts, version, coverage, source dates/licences and current job.
- Authenticated `GET /api/geodata/vmd/ingestion`: worker progress and national-index readiness.
- Exact `GET /api/geodata/vmd/cadastre?kadastrs=...&limit=100&offset=0&review_offset=0`: authoritative parcel first, indexed exact forestry attributes, independently calculated spatial intersections, separately paginated spatial candidates.
- Existing `POST /api/geodata/vmd/import-selected`: national requests must include `cadastral_designation`, reviewed dataset version, selected IDs, sector name and separate responsible-person fields. Ownership derives from the authenticated account/organization; arbitrary client ownership is rejected.

States: `CADASTRAL_PARCEL_FOUND`, `PARCEL_NOT_FOUND`, `VMD_MATCHES_FOUND`, `NO_VMD_RECORDS`, `SPATIAL_REVIEW_REQUIRED`, `DATASET_NOT_READY`, `SOURCE_ERROR`. Several states may coexist in `states`; `state` describes the overall lookup outcome. `cadastral_validation.state` describes the independent parcel lookup.

Blue is the cadastral polygon; green is verified forestry geometry; orange is review-only. Cadastral and forest compartments are distinct feature roles. Exact VMD source attributes and native-CRS containment are required for automatic import. Spatial intersection alone never establishes cadastral membership or legal ownership. The backend checks the requested cadastral designation again during import.

Full source geometry, source CRS, identifiers, dataset version, source dates/hashes, official VZD geometry reference, account/organization, contact and creation metadata persist through the existing sector system. Existing source IDs are retained for duplicate compatibility. Complex/invalid or boundary-discrepant source geometries remain review-only; they are never flattened, clipped or buffered into a false verified sector. Map WGS84 conversion is not a legal survey accuracy claim.

## Regression checks and rollback

```bash
FOREST_GEODATA_MANIFEST=disabled python3 /tmp/forest_same_thread_tests.py
node tests/test_vmd_production_ui.js
node tests/test_lvm_wms_map.js
node tests/test_vmd_local_ui.js
node tests/test_vmd_test_geojson.js
```

The environment-specific Python adapter avoids the restricted TestClient portal. New unit catalogue fixtures are explicitly synthetic and are not evidence of nationwide coverage. Actual national acceptance is separate and source-backed.

Before publication take an integrity-checked operational DB backup and snapshot protected production rows. Roll back a geodata release by restoring the saved previous active pointer and restarting the existing application service; never reset the operational database or remove newly registered production sectors. Preserve releases referenced by imported-sector provenance. The initial deployment's legacy catalogue and backups remain available; source updates require a new staged release and acceptance run.
