# Remove Map sidebar — production handoff (not deployed)

Branch: `feature/remove-map-sidebar`, based on locally cached `origin/master` at `349bec3`.
Worktree: `/root/wt/remove-map-sidebar`.

## Production identification and candidate

The base `/etc/systemd/system/forest-api.service` uses `/root/forest_ai`, port 8000,
and `EnvironmentFile=/root/forest_ai/.env`. The effective on-disk drop-in sequence is:
`50-meza-karte-release.conf`, `70-forest-map-gps-release.conf`, `geodata.conf`.
The last WorkingDirectory override points to:
`/root/forest_ai/releases/forest-api-forest-map-gps-20261109T1129Z`.
`geodata.conf` preserves `FOREST_GEODATA_MANIFEST`.

**Running-process confirmation is unavailable:** `systemctl show` and `systemctl cat`
returned `Failed to connect to bus: Operation not permitted`. This sandbox's PID namespace
cannot see the VPS API process. The directory above is configuration-confirmed, not independently
process-confirmed. Confirm it from the host before deployment; do not infer it from Git.

Prepared full runtime directory:
`/root/wt/remove-map-sidebar/releases/forest-api-remove-map-sidebar-20261109`.
It was assembled exclusively from the configured release's 69 runtime files, retaining
its live-only LVM GEO assets and hidden Photos/AI/Satellite navigation. It contains no copied
credentials or databases. `data` remains a symlink to `/root/forest_ai/data`; do not start this
candidate for tests against that link. EnvironmentFile, geodata configuration, credentials,
client settings and integrations remain inherited from the existing service configuration.

The candidate is staged inside the isolated worktree because repository rules prohibit
writing `/root/forest_ai/releases/*`. Keep this worktree and candidate intact if activated
from this path. A future move requires regenerating the candidate path in the manifest and
activation file, then rerunning verification.

## Exact changes and preserved behavior

Only runtime file `index.html` changes: delete the standalone Map sidebar div and decrement
navigation indices after it. No Operations Map entry is introduced. The production HTML differs
from the committed source in pre-existing changes; the candidate uses production HTML plus only
these two edits. `review/verify_release.py` proves the exact transformation and all 69 hashes.

Visible groups stay Monitor (Overview, Objects, Sectors), Operations (Risks, GPS Sessions,
Truck Reports, Timber), Admin (LVM GEO, Integrations, Forest Map / Meža karte).
The unchanged backend enables the Forest Map item; its localization remains unchanged.
Hidden Photos/AI/Satellite items remain hidden exactly as in the production baseline.

All backend/API files, databases, services, Forest Map assets, VMD/VZD geometry validation,
Import as Sector, registration workflow, GPS tracking, worker positions, machinery telemetry,
truck reports, risk and satellite integrations remain unchanged. No migrations or dependencies.
Sector details remain reachable from existing Objects/Sectors/Forest Map workflows.
Legacy `#map`, `sec-map`, `loadMap`, and `/api/map` remain available internally without a sidebar
highlight. There are no remaining UI links to the old map. One uncalled legacy helper,
`lvmOnForestMap()` in `assets/lvm-geodata.js`, still invokes it; no HTML or asset calls that helper.
Generic Map identifiers, Leaflet maps and Forest Map labels must remain; removing these would
break preserved functionality.

Previous commit `0dd75c0` was reviewed, not cherry-picked: it renamed Map, added map links,
worker GPS rendering and API fields. None of those changes are included in this release.

## Exact validation results

- `node review/verify_navigation.js`: PASS. 10 visible requested destinations, 14 navigation
  function checks including hidden items and internal map, 7 JavaScript scripts parsed.
  Exercises the shipped `nav()` against a Node DOM fixture; not a browser render test.
- `python3 review/verify_release.py`: PASS, 69 runtime files verified, only `index.html` differs.
- `git diff --check`: PASS.
- `DB_PATH=/tmp/remove-map-focused.db timeout 55s python3 review/run_asgi_checks.py tests/test_forest_map.py tests/test_gps_map.py tests/test_geodata.py -q --disable-warnings`:
  `92 passed, 64 warnings in 25.44s`.
- `timeout 55s python3 review/run_asgi_checks.py tests/test_integrations.py -q --disable-warnings`:
  `30 passed, 190 warnings in 20.13s`.
- `DB_PATH=/tmp/remove-map-vmd-unit.db timeout 40s python3 review/run_asgi_checks.py tests/test_vmd_production.py -q --disable-warnings -k 'not real_native_source and not official_parcel and not additive_audit_migration and not actual_logged and not official_outside and not actual_audited and not api_auth_bounds'`:
  `25 passed, 11 deselected, 29 warnings in 7.70s`.

Focused total: **147 passed**. Registration tests cover isolated import/dry run, duplicate
handling, naming, organization scoping, geometry and cadastral rejection. Integration tests
include existing API compatibility; GPS tests include position/track endpoints and alert gates.
All tests use temporary databases; no production mutation requests were sent.
Test source is the worktree; every tested runtime Python file is byte-identical to the candidate.
The ASGI harness executes sync endpoints on the same thread to avoid sandbox-blocked thread
portals and does not start service lifecycle/background tasks. It does not prove production
startup or browser behavior.

Other attempts, retained as failures/limitations rather than passes:

- Stock pytest run stalled after 21 tests in TestClient's thread portal; interrupted. A diagnostic
  repeat hit timeout (exit 124), with `Timeout (0:00:15)!` in the faulthandler log.
- Initial broad isolated run: `9 failed, 111 passed, 1 skipped, 8 deselected, 83 warnings, 39 errors in 19.71s`.
  Exact error messages include `ModuleNotFoundError: No module named 'py7zr'`,
  `sqlite3.OperationalError: no such table: sectors`,
  `services.geodata.vmd_dataset.DatasetError: VMD local dataset is not available; build the catalogue first`,
  `sqlite3.OperationalError: unable to open database file`, and `assert (None)`.
  Nine errors came from unavailable ingest dependency, 30 from integration fixture initialization
  after cross-suite environment/module import interference. Integration tests pass in their own
  process. Nine failures require absent live catalogue/audit/database fixtures in this worktree.
- VMD run including the PDF/streaming API acceptance test also timed out after 9 completed tests.
  That API acceptance test is explicitly excluded from the successful focused VMD run.
- Playwright: `TargetClosedError: BrowserType.launch: Target page, context or browser has been closed`;
  Chromium: `Check failed: . shutdown: Operation not permitted (1)`.
- An initial Node subprocess-based parser hit `Error: spawnSync node EPERM`. The final parser
  uses Node's VM directly and passes.
- Fetch/push unavailable: `ssh: Could not resolve hostname github.com: Temporary failure in name resolution`.

Full local evidence is in the candidate's `evidence/` directory. No end-to-end browser,
live catalogue, real sector registration, process identity or live authenticated HTTP verification
is claimed. Repeat these from the VPS host with an isolated database before activation.

## Deployment procedure — explicit user approval required

Nothing in this procedure has been executed.

1. From the host, confirm `systemctl show forest-api.service -p MainPID -p WorkingDirectory -p DropInPaths`,
   inspect `/proc/<MainPID>/cwd` and verify port 8000's process. Stop if the actual baseline differs.
2. Run `python3 review/verify_release.py` and `node review/verify_navigation.js` from this worktree.
   These guard against concurrent baseline/candidate edits. Rerun browser and real catalogue
   checks with an isolated writable database; never point a test server at the candidate's data link.
3. Back up the existing unit/drop-ins and record `/api/deployment` from an authenticated read-only
   request without printing credentials. Use SQLite's backup API read-only source if a DB backup
   is desired; this release requires no data/schema changes.
4. After approval, install `review/activate-after-approval.conf` as
   `/etc/systemd/system/forest-api.service.d/80-remove-map-sidebar-release.conf` (ensure no later
   override wins). Preserve all existing drop-ins, ExecStart and EnvironmentFile settings.
5. Run `systemctl daemon-reload` and `systemctl restart forest-api.service` only after approval.
6. Confirm process cwd, service health and changed `/api/deployment` fingerprint. Verify sidebar,
   Forest Map, LVM GEO, sector details, GPS Sessions, Risks, truck reports and integration reads.
   Do not create test records in production.

## Rollback

After an approved deployment, remove only the newly added
`80-remove-map-sidebar-release.conf`, then daemon-reload and restart `forest-api.service`.
The unchanged `70-forest-map-gps-release.conf` restores the baseline above. Alternatively install
the supplied `review/rollback-after-approval.conf` over that new 80 drop-in. Verify process cwd,
health and the recorded pre-deployment fingerprint. Do not restore a DB backup or revert new
user records; this is code-only rollback.

Unresolved release gates: host process confirmation, browser acceptance, live catalogue regression,
and remote branch publication. Production has not been switched, restarted or reconfigured.
