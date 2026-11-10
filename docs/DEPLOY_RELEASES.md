# Deploy releases (`releases/`): how :8000 is deployed today

State as of 2026-11-10 09:16 UTC (activation of the LVM GEO + LV UI release). Mirrors of the
live systemd files are in `deploy/systemd/` (the `70-`/`90-`/`95-` drop-ins below are not mirrored there yet).

**Rule (AGENTS.md / CLAUDE.md):** agents may create NEW folders in `/root/forest_ai/releases/`, never
modify or delete existing ones. Production never runs from a worktree path. Activation (drop-in
change + restart) only after an explicit human OK in the chat.

## Which code runs on each port

| port | unit | code location | git |
|---|---|---|---|
| 8000 | `forest-api` | `/root/forest_ai/releases/forest-api-lvm-geo-lv-ui-20261110T0858Z` (via drop-in `95-lvm-geo-lv-ui-release.conf`; `90-` still supplies `FOREST_GPS_VIOLATIONS_DAYS=90`) | branch `release/2026-11-10-lvm-geo-lv-ui` @ `beb09d0` (runtime), dashboard version `geo-1ae5a85bfd23`, backend `552c46ae547b`. **Live-only content kept**: the manual nav edit and the `fd3d2c6` `assets/lvm-geodata.js` (see the activation record below) |
| — | `forest-bot` | `/root/forest_ai` (repo root; `python3 bot.py`) | repo root; its Ingka routing hook is **not** in git yet |
| 8002 | `forest-rm-api` | `/root/forest_ai_rm` (plain copy, `data/DEPLOYED_COMMIT` = `574bd97`) | 574bd97 |
| 8003 | `forest-review-api` | `/root/forest_ai_review` (copy of `84cb00b`) | 84cb00b |
| 8004 | `forest-ai-ingka` | `/root/forest_ai_ingka` (574bd97 + local changes) | not in git |

The root of `/root/forest_ai` is **not** what :8000 serves.

### Live files not in git (as of 2026-11-09, still true for the violations release)

The violations release was built from the remove-map-sidebar release, which was built from the GPS
release, which was built by copying the then-live meza-karte folder and replacing only the
five Forest Map/GPS files. Compared with master at the tag, exactly these 4 runtime files differ:
`assets/lvm-geodata.js`, `assets/vmd-production.js`, `assets/vmd-workflow.css`, `index.html`. The meza-karte folder had been edited in place earlier that day:
- `assets/lvm-geodata.js`, `assets/vmd-production.js`, `assets/vmd-workflow.css` and `index.html`
  are the versions from `feature/boundary-plan@fd3d2c6` (LVM GEO), which is not merged into master.
- `index.html` additionally has a manual edit (10:19 UTC) hiding the Photos, AI, AI Inspector and
  Satellite navigation items. It is in no branch.
- The sidebar change (Map item removed) and the Forest Map deep-link route **are** in master
  (`feature/remove-map-sidebar`, `feature/forest-map-violations`); in the live `index.html` they
  sit on top of the two items above.

The exact inventory (path, size, SHA-256) is `release-manifest.json` in the release folder. Until
these are committed, a release built from git alone would revert them.

## Release folders

```
/root/forest_ai/releases/
  forest-api-baseline-20261107T084300Z           older rollback target (pre-Forest-Map runtime, api.py dfbf12feae50)
  forest-api-meza-karte-20261107T084300Z         ROLLBACK TARGET for :8000 (previous active release)
  forest-api-forest-map-audit-20261107T1645Z     candidate, never activated (superseded)
  forest-api-forest-map-finish-20261109T1023Z    prepared, never activated (contained in the GPS release)
  forest-api-forest-map-gps-20261109T1129Z       was active 2026-11-09 11:44–14:31 UTC (geo-9c94d506a565)
  forest-api-remove-map-sidebar-20261109T1431Z   ROLLBACK TARGET for :8000: permanent copy (diff -r = 0) of
                                                 /root/wt/remove-map-sidebar/releases/forest-api-remove-map-sidebar-20261109,
                                                 which was active 14:31–16:28 UTC from that worktree path (geo-091ed8e852f9)
  forest-api-forest-map-violations-20261109T1623Z ROLLBACK TARGET for :8000: was active 2026-11-09 16:28 – 2026-11-10 09:16 UTC (geo-3b9cdfaac106)
  forest-api-lvm-geo-finish-20261110T0825Z       PREPARED, NOT ACTIVE, SUPERSEDED — do not activate (feature/lvm-geo-finish
                                                 e74b624 only; geo-ac8f6bf9b054). Kept because existing folders are never
                                                 modified or deleted.
  forest-api-lvm-geo-lv-ui-20261110T0858Z        ACTIVE on :8000 since 2026-11-10 09:16 UTC
  forest-api-forest-map-contrast-20261110T0949Z  PREPARED, NOT ACTIVE — candidate (feature/forest-map-basemap-contrast; geo-d0015b1f82a0)
                                                 (release/2026-11-10-lvm-geo-lv-ui beb09d0; geo-1ae5a85bfd23)
```

### History of :8000

| from (UTC) | release | geo- | how |
|---|---|---|---|
| 2026-11-07 08:52 | `forest-api-meza-karte-20261107T084300Z` | c5801dc23be5 (later edited in place) | `50-` drop-in |
| 2026-11-09 11:44 | `forest-api-forest-map-gps-20261109T1129Z` | 9c94d506a565 | `70-` drop-in |
| 2026-11-09 14:31 | worktree `/root/wt/remove-map-sidebar/releases/forest-api-remove-map-sidebar-20261109` | 091ed8e852f9 | `80-` drop-in (from a worktree; not documented at the time) |
| 2026-11-10 09:16 | `forest-api-lvm-geo-lv-ui-20261110T0858Z` | 1ae5a85bfd23 | `95-` drop-in (overrides `90-` WorkingDirectory; `90-` Environment kept) |
| 2026-11-09 16:28 | `forest-api-forest-map-violations-20261109T1623Z` | 3b9cdfaac106 | `90-` drop-in; `80-` removed |

- **Name:** `forest-api-<feature-slug>-<UTC timestamp YYYYMMDDTHHMM[SS]Z>`. The timestamp is
  when the release was cut. The audit candidate's folder name includes `1645Z`.
- **Contents:** a full runtime copy: `api.py`, `database.py`, `index.html`, `assets/`,
  `services/`, `lvm_3_sectors.geojson`. It does not contain `bot.py`, `tests/`, `scripts/`
  or `docs/`.
- **`data`** is a symlink: `data -> /root/forest_ai/data`. All releases share the
  operational SQLite DB (`data/forest_ai.db`), photos and the national geodata release.
  Switching releases never copies or restores data.
- **`.env`** is not in the folder. The unit loads `EnvironmentFile=/root/forest_ai/.env`.
- **The geodata manifest** comes from the drop-in `geodata.conf`
  (`FOREST_GEODATA_MANIFEST=/root/forest_ai/data/geodata/nationwide/active.json`).

## Prepared release: forest-api-forest-map-contrast-20261110T0949Z (2026-11-10, NOT active)

**Status:** prepared, not active. :8000 serves `forest-api-lvm-geo-lv-ui-20261110T0858Z` (`geo-1ae5a85bfd23`).
Activation needs an explicit human OK.

- **Source:** `feature/forest-map-basemap-contrast` (code `ae638d8`, docs `66572fa`) from `origin/master` `9140473`.
- **Built as:** copy of the ACTIVE folder `forest-api-lvm-geo-lv-ui-20261110T0858Z`; only `assets/forest-map.js` replaced.
  The live-only nav edit in `index.html` and the `fd3d2c6` `assets/lvm-geodata.js` are kept as they are live.
- **Checks:** `pre-activation-check.sh` OK (70 files; baseline = active folder unchanged). Smoke test of the folder on
  127.0.0.1:8016 (DB copy): `geo-d0015b1f82a0`; satellite map area pixel-identical to the live :8000 (0 differing
  pixels); Karte boundaries dark green; 0 tile requests per basemap switch; Latvian sidebar; LVM GEO unchanged
  (62420110056 → 25 rows, 18 selectable); 0 JS errors, 0 tracebacks.
- **Drop-in:** `96-forest-map-contrast-release.conf` (inside the folder) only sets `WorkingDirectory`; it overrides `95-`,
  which stays in place. `90-` still supplies `FOREST_GPS_VIOLATIONS_DAYS=90`.

Activate:
```sh
REL=/root/forest_ai/releases/forest-api-forest-map-contrast-20261110T0949Z
$REL/pre-activation-check.sh                                   # must print OK
TS=$(date -u +%Y%m%dT%H%M%SZ)
sqlite3 /root/forest_ai/data/forest_ai.db ".backup /root/backups/forest_ai_before_forest_map_contrast_$TS.db"
sqlite3 /root/backups/forest_ai_before_forest_map_contrast_$TS.db 'PRAGMA integrity_check'   # ok
cp -a /etc/systemd/system/forest-api.service.d /root/backups/forest-api.service.d-$TS
install -m 0644 $REL/96-forest-map-contrast-release.conf /etc/systemd/system/forest-api.service.d/96-forest-map-contrast-release.conf
systemctl daemon-reload && systemctl restart forest-api
readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd          # → …/forest-api-forest-map-contrast-20261110T0949Z
# /api/deployment → geo-d0015b1f82a0
```

Roll back (code only, no data restore):
```sh
rm -f /etc/systemd/system/forest-api.service.d/96-forest-map-contrast-release.conf
systemctl daemon-reload && systemctl restart forest-api
readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd          # → …/forest-api-lvm-geo-lv-ui-20261110T0858Z
# /api/deployment → geo-1ae5a85bfd23
```

## Activation record: lvm-geo-lv-ui (2026-11-10 09:16 UTC)

**Status:** ACTIVE on :8000 since 2026-11-10 09:16:12 UTC (`geo-1ae5a85bfd23`), activated after an explicit
human OK (tested by the owner on a loopback test server first). Rollback target:
`forest-api-forest-map-violations-20261109T1623Z` (`geo-3b9cdfaac106`).

1. Before: active folder `forest-api-forest-map-violations-20261109T1623Z`, PID 2869442.
2. `pre-activation-check.sh` printed OK (70 release files match the manifest; baseline = violations folder, 70 files unchanged).
3. Backups: DB `/root/backups/forest_ai_before_lvm_geo_lv_ui_20261110T091603Z.db` (`sqlite3 .backup`,
   `integrity_check` = ok, 1.3 MB); unit files `/root/backups/forest-api.service.d-20261110T091603Z/` and
   `/root/backups/forest-api.service-20261110T091603Z`.
4. Installed only `95-lvm-geo-lv-ui-release.conf` (from the release folder). `50-`, `70-`, `90-` stay in place;
   `90-` still provides `FOREST_GPS_VIOLATIONS_DAYS=90`. The superseded `95-lvm-geo-finish-release.conf` was NOT installed.
5. `systemctl daemon-reload && systemctl restart forest-api`. Only `forest-api` restarted: new PID 2905224,
   cwd = release folder. :8002 (2411749), :8003 (2535074), :8004 (2538345), forest-bot (2538882) and the
   ingka/rigas Telegram workers (2696056 / 2690389) kept their PIDs.
6. Verified on :8000 (headless Chromium, read-only): `/api/deployment` = `geo-1ae5a85bfd23`; Latvian sidebar and
   lv-LV header time on Pārskats, Meža karte and LVM GEO; Forest Map on-map switch Satelīts → Karte (OSM tiles)
   → Satelīts (Esri tiles), sidebar select in sync, violations panel and overlays present; LVM GEO search
   62420110056 → 25 rows, master checkbox, action bar with "Reģistrēt sektorus (0)" and its reason; 0 JS errors;
   no tracebacks in the forest-api journal after the restart.

Release contents:

- **Source:** branch `release/2026-11-10-lvm-geo-lv-ui` @ `beb09d0` = `origin/master` `99bc3be` + merge of
  `feature/lvm-geo-finish` (`e74b624`: LVM GEO registration UX, Forest Map basemap switch) + merge of
  `feature/lv-ui-global` (`4f3bbc0`: Latvian sidebar labels and lv-LV header time on every page).
- **Built as:** copy of the live violations folder; only 5 runtime files replaced from `beb09d0`:
  `index.html`, `assets/vmd-production.js`, `assets/vmd-workflow.css`, `assets/forest-map.js`,
  `assets/forest-map.css`. `api.py`, `database.py`, `services/` unchanged; no migrations; `data` symlink.
- **Live-only content preserved:** the manual nav edit (Photos, AI group, AI Inspector, Satellite hidden) is
  re-applied to `index.html` (its `<nav>` is identical to live); `assets/lvm-geodata.js` stays the live
  `fd3d2c6` version (extra Latvian error texts, superset of master). The `fd3d2c6` LVM GEO frontend is replaced
  by the `feature/lvm-geo-finish` one. `assets/vmd-workflow.css` is the branch version (the live-only `fd3d2c6`
  rules target classes no longer used).
- **Checks:** `pre-activation-check.sh` OK (70 files; baseline = live violations folder unchanged). Smoke test of
  the folder itself on 127.0.0.1:8016 with a DB copy: `/api/deployment` = `geo-1ae5a85bfd23`; Latvian sidebar and
  lv-LV time on all routes; Forest Map basemap control, violations, GPS; LVM GEO 62420110056 → 25 rows,
  18 selectable (28.18 ha); 0 JS errors, 0 tracebacks.
- **Drop-in:** `95-lvm-geo-lv-ui-release.conf` (inside the folder) only sets `WorkingDirectory`. The `90-`
  drop-in stays, so `FOREST_GPS_VIOLATIONS_DAYS=90` is kept.

Commands used to activate (2026-11-10 09:16 UTC):
```sh
REL=/root/forest_ai/releases/forest-api-lvm-geo-lv-ui-20261110T0858Z
$REL/pre-activation-check.sh                                   # must print OK
TS=$(date -u +%Y%m%dT%H%M%SZ)
sqlite3 /root/forest_ai/data/forest_ai.db ".backup /root/backups/forest_ai_before_lvm_geo_lv_ui_$TS.db"
sqlite3 /root/backups/forest_ai_before_lvm_geo_lv_ui_$TS.db 'PRAGMA integrity_check'      # ok
cp -a /etc/systemd/system/forest-api.service.d /root/backups/forest-api.service.d-$TS
install -m 0644 $REL/95-lvm-geo-lv-ui-release.conf /etc/systemd/system/forest-api.service.d/95-lvm-geo-lv-ui-release.conf
systemctl daemon-reload && systemctl restart forest-api
readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd          # → …/forest-api-lvm-geo-lv-ui-20261110T0858Z
# /api/deployment → geo-1ae5a85bfd23
```

Roll back (code only, no data restore; sectors registered meanwhile stay as ordinary sectors):
```sh
rm -f /etc/systemd/system/forest-api.service.d/95-lvm-geo-lv-ui-release.conf
systemctl daemon-reload && systemctl restart forest-api
readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd          # → …/forest-api-forest-map-violations-20261109T1623Z
# /api/deployment → geo-3b9cdfaac106
```

`forest-api-lvm-geo-finish-20261110T0825Z` is an earlier, superseded candidate (no LV UI change). Do not
activate it and do not install its `95-lvm-geo-finish-release.conf` next to the one above.

## Manifest format (`release-manifest.json` in the release folder)

```json
{
  "release": "forest-api-meza-karte-20261107T084300Z",
  "baseline_api_sha256": "<sha256 of the api.py it replaces>",
  "release_api_sha256": "<sha256 of this release's api.py>",
  "runtime_files": ["files changed relative to the baseline"],
  "baseline_runtime_code_reused": ["files copied unchanged from the baseline"],
  "data": "symlink to /root/forest_ai/data; ...",
  "database_migrations": false,
  "new_python_dependencies": [],
  "complete_source_inventory": [{"path": "...", "bytes": 0, "sha256": "..."}]
}
```

`complete_source_inventory` lists every file in the release with its SHA-256 (68 files for
meza-karte). Candidates also carry `forest-map-release-candidate.json`, which records the
`candidate`, `baseline`, `production_activated` and per-file SHA-256 values.
Caveat: the audit candidate's `release-manifest.json` was copied unchanged, so its
`release` field still says `meza-karte`. Use the folder name and the candidate JSON
instead.

The production manifest is committed at the repository root (`release-manifest.json`)
as part of the tagged commit.

## How a release was created (2026-11-07 procedure)

1. Fingerprint the code that is actually running: `sha256sum` of the live `api.py`, checked
   against the process (`systemctl show forest-api -p WorkingDirectory`,
   `/proc/<pid>/cwd`). Do not assume git `HEAD` is what is running.
2. Copy the running runtime files into `releases/<name>/`, then overlay only the files the
   feature changes. Create `data -> /root/forest_ai/data`. Write `release-manifest.json`.
3. Back up first into `data/backups/<task>_<timestamp>/` (mode 0700; files 0600). Include
   the unit and drop-ins, a `.env` copy, an SQLite backup made with
   `sqlite3.Connection.backup`, a code tarball, an `activate-release.conf`, a
   `rollback-release.conf` and a `rollback-forest-api.sh`.
   For meza-karte this was `data/backups/forest_api_meza_activation_20261107T0852Z/`.
4. Test the candidate on a loopback port with a temporary DB copy. Never start a second
   API on 8000.

## How the drop-in switches the release

`/etc/systemd/system/forest-api.service.d/50-meza-karte-release.conf`:

```ini
[Service]
WorkingDirectory=/root/forest_ai/releases/forest-api-meza-karte-20261107T084300Z
ExecStart=
ExecStart=/usr/local/bin/uvicorn api:app --host 0.0.0.0 --port 8000
```

The base unit (`forest-api.service`) still says `WorkingDirectory=/root/forest_ai`. The
drop-in overrides it. To activate a release, install a drop-in that points to the new
folder, then run `systemctl daemon-reload` and `systemctl restart forest-api`. Restart
only `forest-api`.

Check what is live:

```sh
systemctl show forest-api -p WorkingDirectory -p DropInPaths
readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd
curl -su "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" http://127.0.0.1:8000/api/deployment   # -> version geo-...
```

The `geo-<12 hex>` version is the first 12 hex characters of the SHA-256 of the
sorted-key JSON of `{path: sha256}`. The paths are `index.html`,
`assets/lvm-geodata.js`, `assets/vmd-production.js`, `assets/vmd-workflow.css`,
`assets/forest-map.js` and `assets/forest-map.css` (see `frontend_deployment()` in
`api.py`).

## Activation record: forest-map-gps (2026-11-09)

1. `pre-activation-check.sh` in the release printed OK (64 baseline files unchanged since build).
2. Backups:
   - DB: `/root/backups/forest_ai-20261109T114359Z.db` (`sqlite3 .backup`, `PRAGMA integrity_check` = ok, 1.3 MB).
   - Unit configuration: `/root/backups/forest-api-dropins-20261109T114359Z/`.
3. Added `/etc/systemd/system/forest-api.service.d/70-forest-map-gps-release.conf`:
   ```ini
   [Service]
   WorkingDirectory=/root/forest_ai/releases/forest-api-forest-map-gps-20261109T1129Z
   ```
   It overrides the `WorkingDirectory` of `50-meza-karte-release.conf`, which is left in place.
   `ExecStart` and the environment are unchanged. `FOREST_GPS_COMPARTMENT_ALERTS` is **not** set,
   so compartment alerts are off.
4. Ran `systemctl daemon-reload && systemctl restart forest-api`. Only `forest-api` was restarted.

## Activation record: forest-map-violations (2026-11-09 16:28 UTC)

1. Rollback copy `forest-api-remove-map-sidebar-20261109T1431Z` made from the live worktree folder
   (`cp -a`, `diff -r --no-dereference` = 0, served version `geo-091ed8e852f9` = live).
2. Release copied from the worktree build (`diff -r` = 0); `pre-activation-check.sh <rollback copy>`
   printed OK (70 release files match the manifest, 69 baseline files unchanged).
3. Backups: DB `/root/backups/forest_ai_before_violations_20261109T162758Z.db` (`sqlite3 .backup`, `integrity_check` = ok, 1.3 MB);
   unit files `/root/backups/forest-api.service.d-20261109T162811Z/` and `/root/backups/forest-api.service-20261109T162811Z`.
4. Removed `80-remove-map-sidebar-release.conf` (worktree path), added
   `90-forest-map-violations-release.conf`:
   ```ini
   [Service]
   WorkingDirectory=/root/forest_ai/releases/forest-api-forest-map-violations-20261109T1623Z
   ```
   `50-` and `70-` stay in place and are overridden. `FOREST_GPS_COMPARTMENT_ALERTS` is not set (off).
5. `systemctl daemon-reload && systemctl restart forest-api`. Only `forest-api` restarted; forest-bot and
   :8002/:8003/:8004 kept their PIDs.
6. Verified: `/api/deployment` = `geo-3b9cdfaac106`; `#forest-map` shows the session #32 red segment, exit/
   re-entry flags and the "Pārkāpumi" list with incident #62 without clicks; sidebar change present;
   `#lvm-geodata`, Risks, sector Map tab (11 min 00 s / 3 min 21 s) unchanged; no tracebacks.

## Rollback

Roll back code only. Do **not** restore the DB backup over live user writes unless a
data recovery has been separately approved. All schema changes are additive and can
remain in place.

- **meza-karte → baseline (pre-Forest-Map):** run
  `/root/forest_ai/data/backups/forest_api_meza_activation_20261107T0852Z/rollback-forest-api.sh`.
  It checks `releases/forest-api-baseline-.../api.py` has SHA-256 `dfbf12fe…`, installs
  `rollback-release.conf` over `50-meza-karte-release.conf`, runs `daemon-reload`, restarts
  `forest-api` and checks it is active.
- **lvm-geo-lv-ui → forest-map-violations (current rollback target):**
  ```sh
  rm -f /etc/systemd/system/forest-api.service.d/95-lvm-geo-lv-ui-release.conf
  systemctl daemon-reload && systemctl restart forest-api
  readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd   # → …/forest-api-forest-map-violations-20261109T1623Z
  ```
  Confirm `/api/deployment` reports `geo-3b9cdfaac106`. No data to restore (no migrations). Sectors registered
  through the new LVM GEO bar remain as ordinary sectors with their provenance.
- **forest-map-violations → remove-map-sidebar (older):**
  ```sh
  printf '[Service]\nWorkingDirectory=/root/forest_ai/releases/forest-api-remove-map-sidebar-20261109T1431Z\n' \
    > /etc/systemd/system/forest-api.service.d/90-forest-map-violations-release.conf
  systemctl daemon-reload && systemctl restart forest-api
  readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd   # → …/forest-api-remove-map-sidebar-20261109T1431Z
  ```
  Confirm `/api/deployment` reports `geo-091ed8e852f9`. No data to restore (no migrations). Incidents
  created with the "Izveidot incidentu" button remain as ordinary incidents.
- **forest-map-gps → meza-karte (older):**
  ```sh
  rm -f /etc/systemd/system/forest-api.service.d/70-forest-map-gps-release.conf /etc/systemd/system/forest-api.service.d/71-forest-gps-alerts.conf
  systemctl daemon-reload && systemctl restart forest-api
  readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd   # → …/forest-api-meza-karte-20261107T084300Z
  ```
  The `/api/deployment` version then returns to the meza-karte folder's current content (`geo-57c305ea4225`
  on 2026-11-09). No data needs restoring: the GPS release adds no tables or migrations. Incidents created
  while alerts were on (if they are ever enabled) remain as ordinary incidents.
  Confirm `/api/deployment` reports `geo-c5801dc23be5`.
- **From git:** `git archive prod-2026-11-07-meza-karte | tar -x -C releases/<new-name>`,
  then add the `data` symlink and point the drop-in at it.

## Files in `deploy/systemd/`

These are verbatim copies of `/etc/systemd/system/`. They contain no secret values; secrets
come from `EnvironmentFile=` paths, which are not committed.

- `forest-api.service`, plus `forest-api.service.d/50-meza-karte-release.conf` and `geodata.conf`
- `forest-bot.service`, plus `forest-bot.service.d/ingka-routing.conf` (only
  `Restart=always`, `RestartSec=5`; the name comes from the Ingka routing work)
- `forest-rm-api.service`

`deploy/forest-api-geodata.conf` (identical to `geodata.conf`) and
`deploy/forest-geodata-ingest@.service` are the geodata ingest files. Units of the other
instances (`forest-review-api`, `forest-ai-ingka*`, `forest-ai-rigas-telegram`) are
intentionally not mirrored here.
