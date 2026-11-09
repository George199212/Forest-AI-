# LVM GEO implementation and production handoff

Date: 2026-10-30 UTC.

**Status: implemented and tested on isolated databases; NOT activated or verified
on the live production process. Do not describe this as a completed production
integration until the live checks below pass.**

## 1. Existing architecture inspected

Application root `/root/forest_ai`: FastAPI (`api.py`), SQLite via raw sqlite3
(`database.py`), database `/root/forest_ai/data/forest_ai.db`, single-file SPA
(`index.html`), Leaflet 1.9.4 and OpenStreetMap tiles. No PostGIS dependency.

`sectors.id` is the internal integer primary key; `sectors.name` is the operational
reference used by sessions, incidents and reports. `boundary_json` contains a
single WGS84 ring of `[latitude, longitude]` pairs, unlike GeoJSON's longitude /
latitude order. The import bridge uses the existing centroid/area helpers and
writes the same sector table in one transaction with provenance.

Inspected sector CRUD/detail/map routes, sector rendering and Leaflet setup,
HTTP Basic authentication, integrations registry/UI, `bot.py` check-in and edited
live-location flows, `services/geo.py`, `services/session_track.py`, machinery
geofence logic, risk creation and incident display. GPS/risk implementations
were preserved; there is no LVM-specific risk engine.

Client isolation is by separate authenticated application instances and database
files, NOT organization filtering of the existing sector table. Configured
client roots include `/root/forest_ai_rm` and `/root/forest_ai_ingka`. Their code,
credentials and data were not modified. The main instance is not a way to import
sectors into Ingka's database. To enable a client, deploy the reviewed integration
code to that instance, preserving its own authentication and DB_PATH.

## 2. Files changed by this implementation

Existing files (previous unrelated changes preserved):

- `api.py`: authenticated geodata router and backend-gated frontend activation.
- `database.py`: additive geodata schema initialization after existing migrations.
- `index.html`: integration status/browser, source block and loader hooks.
- `requirements.txt`: pin already-installed Shapely 2.1.2 for polygon validation.
- `services/integrations/registry.py`: link LVM catalog entry to the dedicated browser;
  no false generic sync adapter/connected claim.
- `scripts/clone_sector_instance.py`: wipe temporary geodata previews when cloning;
  provenance/history use the existing automatic `sector` filtering rule.

New files:

- `services/geodata/{__init__,base,lvm_geo,store,routes}.py`
- `assets/lvm-geodata.js`
- `tests/test_geodata.py`
- `docs/LVM_GEO.md`

## 3. Database changes

Three additive tables created by `database.init_db()` on the next backend startup:

- `geodata_sources`: one related provenance record per imported sector, all required
  source metadata, fixed current-instance organization 1, unique provider/layer/
  feature identity within the instance.
- `geodata_boundary_history`: old/new boundaries, source snapshot, actor, action and
  timestamp for import and explicitly confirmed boundary refresh.
- `geodata_previews`: opaque account-bound expiring server-side import/refresh
  proposals; geometry in import/apply requests cannot be supplied by the browser.

No operational table is replaced or rewritten by the geodata migration. Existing
sectors report `boundary_source_type=manual` when no source relation exists.
The live production database has NOT been migrated. It still has 17 sectors,
no geodata tables, and integrity `ok`. All table counts match the pre-change backup.
The migration was applied and verified on a copy only.

## 4. Backups

`/root/forest_ai_backups/lvm_geo_20261030T100957Z/`

- `forest_ai.db`: consistent SQLite backup made through sqlite3's online backup API,
  with the source opened read-only.
- `project/`: original copies of every existing file modified above.
- `forest-api.service`: original deployment unit configuration.
- `implementation.patch`: exact implementation diff relative to these backups,
  excluding unrelated changes that already existed when this work began.

Do not restore the whole DB as a routine rollback after new operational data has
arrived. The new tables are additive and can remain during code rollback. Do not
use git reset/checkout: this checkout contained other uncommitted work beforehand.

## 5. Official endpoint discovery

Source inspected:
https://www.lvmgeo.lv/en/data/services/coming-soon

Officially published WMS endpoints:

- `https://geoserver.lvmgeo.lv/wms62531a9bfcfa4015856924e94076a178`
- `https://geoserver.lvmgeo.lv/wmsvector62531a9bfcfa4015856924e94076a179`

Only these endpoints are allowlisted. WMS 1.1.1 GetCapabilities / GetMap are used.
WFS GetCapabilities is probed on the SAME published OGC service URLs; no WFS URL
is invented. A valid WFS capabilities document advertising GetFeature is required
before WFS is shown available. Vector import additionally requires advertised
GeoJSON and EPSG:4326 support. Negotiated WFS 1.0/1.1/2.0 bbox axis orders are
handled separately; GeoJSON coordinates remain longitude/latitude.

Remote OnlineResource/metadata links and redirects are never fetched server-side.
The provider has no database, sector, GPS or risk dependencies.

## 6. WMS status

**Not live-verified.** The direct Python request failed DNS resolution in this
restricted session. Remote web tooling could read the official documentation but
could not retrieve GetCapabilities. This is not evidence that LVM itself is down.
The application reports UNAVAILABLE when its own requests fail; it never fabricates
CONNECTED. WMS tile rendering is implemented with toggles on the browser map and
existing Forest AI map, retaining OSM and operational sector overlays. Actual WMS
images must still be checked in a browser after activation.

## 7. WFS status

**Not live-verified.** No actual WFS feature types were confirmed. Import controls
stay disabled unless capabilities confirms support. A WMS-only layer is never
inferred to be WFS-capable. No real LVM polygon was downloaded or imported.

## 8. Layer count

**0 live layers verified in this session; actual service count unknown.**
The runtime browser lists actual capabilities responses, including WFS-only
feature types if advertised. Capability results are cached in process for 15
minutes when both WMS services respond, 60 seconds during partial/failing checks.
No stale/offline layer list is represented as live-connected.

## 9. Forestry-related layers

**None verified live.** No forest-register, road, drainage, terrain or orthophoto
layer names are guessed or seeded. Search matches actual names, titles,
descriptions and attribution once discovery succeeds.

## 10. Layer tested

No real dataset. Automated tests use clearly synthetic `fixture:polygon` and
`fixture:raster` XML/GeoJSON fixtures. These are never shown as real LVM layers or
inserted into production.

## 11. Polygon to existing Forest AI sector

Verified with synthetic polygons on temporary SQLite databases. The server validates
GeoJSON type, stable feature ID, ring closure, coordinate order/range, finite
coordinates, polygon validity and area before creating an ordinary `GEO-xxxx`
sector. Source feature IDs are never used as Forest AI IDs/names. Import persists
locally and needs no provider request afterward.

Preview requires a Latvian EPSG:4326 bbox no larger than 0.2° × 0.2°, max 100 returned
features. Out-of-area features are rejected even if a provider ignores bbox.
Selections import at most 25 features atomically. Duplicate protection is enforced
both by transaction/lookup and a database uniqueness constraint; parallel repeated
imports yield the existing sector. Preview tokens expire after 15 minutes, belong
to the authenticated account and exist only in its instance database.

## 12. Existing GPS and risk verification

Tests exercise the actual bot's existing inside/outside transition handler with an
imported local sector, checking that a single SECTOR_EXIT incident is created;
inside → outside → still outside → return transitions; the existing distance to
boundary helper; existing session route outside duration and distance; exit and
return markers; and machinery INSIDE/OUTSIDE evaluation. Provider failure cannot
enter this operational path. Telegram sends and AI recommendations are mocked;
no messages or paid AI calls were made.

The existing route/risk display receives the same stored polygon and recorded route.
This is automated verification, not a real worker/Telegram/GPS field test.

## 13. Limitations and security boundaries

- No production restart, live service status, actual layer discovery, real feature
  import or visual tile verification could be completed in this session.
  `systemctl show` and service listing returned `Failed to connect to bus:
  Operation not permitted`; the session cannot observe the production PID/listeners.
- Unit configuration identifies `forest-api.service`, working directory
  `/root/forest_ai`, uvicorn on port 8000. Running state is unverified.
- Only simple 2D Polygon rings without holes are supported by existing sector/GPS
  consumers. MultiPolygon, holes and invalid polygons are explicitly rejected.
  They are never flattened, repaired or partially imported.
- CRS transformation is delegated to a confirmed EPSG:4326 WFS request; other
  returned CRS values are rejected. No approximate EPSG:3059 conversion is used.
  WMS preview requests only an advertised EPSG:3857 or EPSG:4326 CRS.
- Import requires actual dataset attribution in capabilities. A missing source
  attribution is shown explicitly and blocks import; LVM is not substituted for
  VMD/LĢIA/VZD or another actual dataset owner. WFS preview can still be inspected.
- Remote XML/JSON has content-type, size (8 MiB), nesting/node, feature-count,
  geometry and CRS checks. DTD/entities and nonfinite JSON numbers are rejected.
  Requests use connect/read timeouts, a streaming deadline and no redirects.
- UI remote strings are text nodes; Leaflet attribution is HTML-escaped.
  Mutation endpoints require JSON, authentication, and reject cross-origin requests.
- Refresh only queries the original layer and feature ID. Unchanged geometry yields
  No changes. Changed geometry is shown side by side on a comparison map. A
  separate explicit confirmation is required to apply, and optimistic checking
  rejects a sector changed since preview. History records the prior boundary.
- Source geometry remains local during outages; no live LVM dependency was added
  to worker GPS, machinery geofences, risks, Inspector or reports.
- UI activation is injected by the matching backend version. An old running
  backend serving the updated index keeps the new UI hidden until restart.

## 14. Test URL and activation steps

After activation on the main instance: `/#lvm-geodata`, or
**Integrācijas → LVM GEO → Open layers / Slāņi**.

APIs: `/api/geodata/lvm/health`, `/capabilities`, `/services`, `/layers`, `/layer`,
`/map-url`, POST `/preview`, POST `/import`, GET `/sectors/{id}/source`, POST
`/sectors/{id}/refresh`, POST `/apply`, all under `/api/geodata/lvm` and existing
HTTP Basic authentication. No organization selector or arbitrary URL is accepted.

Activation must be performed from a session with actual production network and
service-manager access. The user has already authorized deployment; the obstacle
is environment access, not missing approval.

1. Check `systemctl status forest-api.service`, `systemctl cat forest-api.service`
   and its configured DB_PATH privately. Confirm the root/port/database match above.
   Confirm `python3 -c 'import shapely; print(shapely.__version__)'` is 2.1.2.
2. Make a fresh SQLite online backup before startup applies the three new tables.
   Preserve the pre-change source backup listed above.
3. From `/root/forest_ai`, run `python3 -m pytest tests -q` in a normal environment.
   No real network/Telegram/AI calls are required by the new tests.
4. Restart **only** `forest-api.service`. No bot/client/review service restart is
   required for main-instance imports: bot geofencing reads local sectors dynamically.
5. Check `systemctl is-active forest-api.service` and sanitized recent service logs.
   Authenticate with existing credentials privately; verify `/`, `/api/sectors`,
   `/api/map`, `/api/risks`, `/api/gps` and `/api/summary`.
6. Refresh `/api/geodata/lvm/health` (POST JSON `{}`) and inspect actual endpoints,
   statuses, layer count and forestry-related layer metadata. Record the results.
   If WFS is absent, report WMS-only; do not enable imports by bypassing detection.
7. In the browser verify a real advertised WMS overlay on/off, then (if WFS exists)
   preview a small AOI, select a real polygon with verified attribution and import
   one TEST sector into the intended client's authenticated instance. Confirm its
   map placement, provenance, duplicate handling and account isolation.
8. Test refresh/no-change and changed-boundary confirmation using a suitable source;
   check local GPS/risk operation with the provider unavailable. Record the real
   tested layer/feature/sector, without creating fabricated source data.

Validation recorded in this session:

- The first standard suite attempt passed 22 tests before its TestClient portal
  stalled. This happened before implementation changes.
- 140 existing non-browser tests passed after the initial implementation.
- **205 tests passed (155 existing + 50 geodata)** using a temporary test-only same-thread
  ASGI runner that bypasses the restricted environment's blocked TestClient portal.
  Lifecycle background jobs are deliberately not started by that runner.
- New geodata tests also run normally without that runner because their HTTP test
  uses ASGITransport with test-only synchronous dispatch.
- Production-backup copy migration preserved every existing table count; integrity
  passed. 25 authenticated ASGI routes returned 200, including all 17 sector detail
  pages, map, GPS, summary, integration listing and an existing SECTOR_EXIT risk.
- Python compilation and Node syntax checks passed for new JS and inline SPA JS.

A direct provider health probe at `2026-10-30T10:28:44Z` returned
`UNAVAILABLE`, WMS false, WFS false, layer_count 0, after connection failures
on all four capability requests. This records this environment’s reachability,
not a claim that the remote services are down.

The restricted test runner is `/tmp/forest_same_thread_tests.py`; the snapshot
smoke runner is `/tmp/forest_lvm_snapshot_smoke.py`. They are test tools, not
application changes, and do not mutate the production database.
