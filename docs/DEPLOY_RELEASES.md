# Deploy releases (`releases/`): how :8000 is deployed today

State as of 2026-11-10 09:16 UTC (activation of the LVM GEO + LV UI release). Mirrors of the
live systemd files are in `deploy/systemd/` (the `70-`/`90-`/`95-` drop-ins below are not mirrored there yet).

**Rule (AGENTS.md / CLAUDE.md):** agents may create NEW folders in `/root/forest_ai/releases/`, never
modify or delete existing ones. Production never runs from a worktree path. Activation (drop-in
change + restart) only after an explicit human OK in the chat.

## Host (since 2026-11-17)

Production runs on the **NEW host `forest-ai-production-ams3`, 64.225.79.80**, restored from a snapshot of the OLD
host 164.90.188.136 taken ~10:30 UTC 2026-11-17. OLD is unreachable (SSH/80/443 closed); nothing is synced from it.
Verified on NEW 2026-11-17 16:35–16:50 UTC:

- Boot 12:27:23 UTC (`last reboot`). DNS `app.forestaisystems.com` and `forestaisystems.com` → 64.225.79.80
  (cutover done; DNS switched by the owner, verified 14:36 UTC per `/root/forest_ai/docs/MIGRATION_CHANGELOG_20261117.md`).
- :8000 runs the release folder `…satellite-monitoring-20261117T0521Z` (97 files byte-identical to `bc8c428`); since
  15:06 UTC all four uvicorn units bind 127.0.0.1 only (`99-bind-localhost.conf`), nginx proxies.
- satellite.db: last written 08:04:14 UTC (run 8, on OLD, before the snapshot); `integrity_check` ok. No satellite run
  has happened on NEW yet; first one: `forest-satellite-sync.timer` 2026-11-18 05:37:20 UTC.
- **Snapshot gap (UNKNOWN):** anything done on OLD after ~10:30 UTC and not pushed to origin. Every satellite branch
  (`feature/satellite-monitoring` af4e97d, `feature/satellite-workspace` 3068e99, `feature/sat-rollback-8band` e0c9c84)
  equals origin.

### Restarts on NEW, 2026-11-17 (journal + migration changelog)

After boot, the services were restarted once, by hand, by the owner's ams3-migration session (root SSH session from
12:29 UTC; changelog `docs/MIGRATION_CHANGELOG_20261117.md`, committed to `master` as `2404561` on 2026-11-17 16:57 UTC, docs only, secret-scanned; the
file in the repo root `/root/forest_ai` is still untracked there), each with
an explicit owner OK in that session. Each restart was preceded by `daemon-reload`; all clean stops, `NRestarts=0`:

| UTC | unit | why (changelog task) |
|---|---|---|
| 14:59:26 | forest-review-api | T5: new `99-bind-localhost.conf` (bind 127.0.0.1:8003), file written 14:59:10 |
| 15:02:51 | forest-rm-api | T5: `99-bind-localhost.conf` (127.0.0.1:8002), written 15:02:37 |
| 15:03:44 | forest-ai-ingka | T5: `99-bind-localhost.conf` (127.0.0.1:8004), written 15:03:27 |
| 15:06:00 | forest-api | T5: `99-bind-localhost.conf` (127.0.0.1:8000), written 15:05:39; WorkingDirectory unchanged (0521Z) |
| 15:10:12 | forest-bot | T9: `DASHBOARD_PUBLIC_URL` in `.env` + `bot.py` (files written 15:09:53; backups `*.bak-20261117T1509Z`) |
| 15:10:56 | forest-ai-rigas-telegram | T9: same, `/root/forest_ai_rm` |
| 15:11:57 | forest-ai-ingka-telegram | T9: same, `/root/forest_ai_ingka` |

The satellite timers were not touched (active since boot 12:27:30). The `bot.py` change (and the uncommitted
tenant-router hook) is on local branch `vps-migration-2026-11-17` @ `20bb021` / working tree of `/root/forest_ai`, not on origin.

## Which code runs on each port

| port | unit | code location | git |
|---|---|---|---|
| 8000 | `forest-api` | `/root/forest_ai/releases/forest-api-satellite-monitoring-20261117T0521Z` (via drop-in `98-satellite-monitoring-release.conf`; `97-satellite-monitoring.conf` sets the SAT_* paths; `90-` still supplies `FOREST_GPS_VIOLATIONS_DAYS=90`). Worker units `forest-satellite-{jobs,sync}.service` use the same folder | branch `feature/satellite-monitoring` @ `bc8c428`, dashboard version `geo-d7081327a3d2` (since 2026-11-17 07:11 UTC) |
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
  forest-api-lvm-geo-lv-ui-20261110T0858Z        was active on :8000 2026-11-10 09:16 – 10:32 UTC
                                                 (release/2026-11-10-lvm-geo-lv-ui beb09d0; geo-1ae5a85bfd23)
  forest-api-forest-map-contrast-20261110T0949Z  was active 2026-11-10 10:32 – 2026-11-16 15:52 UTC
  forest-api-satellite-monitoring-20261116T1021Z PREPARED 2026-11-16 10:21 UTC, NEVER ACTIVE, SUPERSEDED by …1545Z — do not activate
                                                 (= d71ba07: 95 files identical, only its own release-manifest.json differs; manifest:
                                                 production_activated false, steps a-c only; no systemd unit, nginx or process
                                                 references it, checked 2026-11-17 16:50 UTC on NEW). Pre-bc8c428 code: 6-band S2 decoder.
  forest-api-satellite-monitoring-20261116T1545Z DO NOT ROLL BACK: cannot read 8-band S2 (was active 2026-11-16 15:52 – 2026-11-17 07:11)
  forest-api-satellite-monitoring-20261117T0521Z :8000 2026-11-17 07:11 – 2026-11-18 05:33 UTC; ROLLBACK TARGET for :8000;
                                                 satellite worker units STILL run this folder (bc8c428)
  forest-api-satellite-monitoring-rollback8band-20261117T0831Z  ONLY valid rollback target for 0521Z (7bd2bbb + e0c9c84)
  forest-api-remove-integrations-page-20261118T0532Z ACTIVE on :8000 since 2026-11-18 05:33 UTC (b86ebf4 = bc8c428 + Integrations page removed)
```

### History of :8000

| from (UTC) | release | geo- | how |
|---|---|---|---|
| 2026-11-07 08:52 | `forest-api-meza-karte-20261107T084300Z` | c5801dc23be5 (later edited in place) | `50-` drop-in |
| 2026-11-09 11:44 | `forest-api-forest-map-gps-20261109T1129Z` | 9c94d506a565 | `70-` drop-in |
| 2026-11-09 14:31 | worktree `/root/wt/remove-map-sidebar/releases/forest-api-remove-map-sidebar-20261109` | 091ed8e852f9 | `80-` drop-in (from a worktree; not documented at the time) |
| 2026-11-10 09:16 | `forest-api-lvm-geo-lv-ui-20261110T0858Z` | 1ae5a85bfd23 | `95-` drop-in (overrides `90-` WorkingDirectory; `90-` Environment kept) |
| 2026-11-10 10:32 | `forest-api-forest-map-contrast-20261110T0949Z` | d0015b1f82a0 | `96-` drop-in (row added 2026-11-16) |
| 2026-11-16 15:52 | `forest-api-satellite-monitoring-20261116T1545Z` | 178d80bd1896 | `97-` env + `98-` release drop-ins; satellite.db migrated; worker units + timers installed |
| 2026-11-17 07:11 | `forest-api-satellite-monitoring-20261117T0521Z` | d7081327a3d2 | `98-` re-pointed; worker units re-pointed; no migration |
| 2026-11-18 05:33 | `forest-api-remove-integrations-page-20261118T0532Z` | e546c26f549f | `98-` re-pointed; worker units NOT re-pointed (stay on 0521Z); no migration |
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

## Activation record: remove-integrations-page-20261118T0532Z (2026-11-18 05:33:36 UTC, owner "approved release")

- **Git:** branch `feature/remove-integrations-page`, commit `b86ebf4` (on `bc8c428`); annotated tag
  `prod-2026-11-18-remove-integrations-page` → `b86ebf4`. Release folder: 96 files byte-identical to `b86ebf4`
  (`git hash-object`); not in git: `pre-activation-check.sh`; `release-manifest.json` is the folder's own.
- **Build:** copy of the active `…20261117T0521Z` + `git archive b86ebf4 index.html`; `assets/john-deere-logo.png`
  removed. `changed_vs_baseline` = `index.html`; `removed_vs_baseline` = the logo. `pre-activation-check.sh` OK
  (97 files; baseline 0521Z unchanged, 98 files).
- **Tests before release:** pytest (system python) 9 failed / 448 passed / 5 skipped / 40 errors on both `bc8c428`
  and `b86ebf4`, identical failure+error set; node tests 9/9 files pass; sandbox 127.0.0.1:8031 (release code,
  DB copies, no `.env`) headless Chromium: 0 console errors.
- **Backup:** `/root/backups/remove_integrations_page_activation_20261118T053321Z` (0700): unit + all drop-ins, `.env` copy, `forest_ai.db` + `satellite.db` (online backup,
  integrity ok), `code-0521Z.tar.gz`, `activate-release.conf`, `rollback-release.conf` (= old `98-`),
  `rollback-forest-api.sh`, `SHA256SUMS`, `units-before.txt`. sha256: forest_ai.db `f5dbb09d…`, satellite.db
  `d8b1945d…`, rollback-release.conf `31ebe7d3…`.
- **Switch:** `98-satellite-monitoring-release.conf` → `forest-api-remove-integrations-page-20261118T0532Z`; `daemon-reload`; restart of `forest-api` only
  (05:33:36, PID 372710, NRestarts 0). forest-rm-api, forest-review-api, forest-ai-ingka(+telegram),
  forest-ai-rigas-telegram, forest-bot, nginx, timers: PIDs/timestamps unchanged. `forest-satellite-sync` daily run 9
  was started by its own timer at 05:33:35 (unrelated, runs from 0521Z).
- **Smoke:** 127.0.0.1:8000/ without auth 401; https://app.forestaisystems.com/ with `.env` credentials 200, served
  HTML has no "Integrācijas", no `sec-integrations`, no logo reference; `/assets/john-deere-logo.png` 404;
  `#integrations`, `#integration-detail`, in-page hash change and stale history entries → `#overview`/Pārskats;
  Pārskats, Objekti, Sektori, Satelītu monitorings, Riski, GPS sesijas, Kokvedēju atskaites, Kokmateriāli, LVM GEO,
  Meža karte open with the right active item, 0 console errors, 0 page errors, 0 failed requests;
  `/api/sat-monitoring/health` 200; `/api/integrations`, `/api/john-deere/status`, `/api/summary` 200;
  journal from 05:33:30 without traceback.
- **forest-map tag:** `<script src="/assets/forest-map.js?v=20261107"></script>` present once in `index.html`,
  line byte-identical to `bc8c428`. Served HTML shows `?v=<content hash>` because `serve_index()` fingerprints every
  `/assets/*.js` URL (api.py unchanged; same before this release).

## Activation record: satellite-monitoring-20261117T0521Z (2026-11-17 07:11 UTC, owner "approved release")

- **Git tag:** `prod-2026-11-17-satellite-monitoring` (annotated, object `1a7426f5`) → commit `bc8c428`, pushed.
  Verified 2026-11-17 07:57 UTC: 97 files of the release folder byte-identical to `bc8c428` (`git hash-object`);
  not in git: `pre-activation-check.sh` (release helper inherited from an older folder) and the `data` symlink.
  Re-verified on NEW 2026-11-17 ~16:45 UTC: tag object `1a7426f5` → `bc8c428` locally and on origin (`git ls-remote`);
  97 files identical to `bc8c428`, `release-manifest.json` differs (the folder's own manifest, its
  `production_activated: false` was written before activation), `pre-activation-check.sh` not in git. No second tag.

- `/root/forest_ai/releases/forest-api-satellite-monitoring-20261117T0521Z` = active `98-` folder
  (`…20261116T1545Z`) + `git archive bc8c428` of `api.py index.html assets satellite_monitoring` (44 files identical
  to git; no unversioned live edit lost). Changed vs active: `index.html`, `assets/{sat-monitoring.js,.css,i18n-lv.js}`,
  `satellite_monitoring/{config,detection,evidence,pipeline,provider,raster,store,truecolor}.py`. No DB migration.
- Sandbox check 2026-11-17 (127.0.0.1:8030, release code, copies of the live gen-2 satellite.db, forest_ai.db and
  rasters): 50 GET routes vs :8000 — same status and shape except `/api/sat-monitoring/health` (+`worker`, intended)
  and the John Deere routes (sandbox env has no JD credentials; `api.py` unchanged); LV pages, events 61/64, area 3,
  Forest Map from event 61 checked in headless Chromium, no console errors.
- Before: true-colour quicklooks for the 4 images shown on open events (run 7, `satellite_monitoring.truecolor --scope
  shown --yes`, transient unit with worker isolation): 4 requests, **12.0161 PU actual** (x-processingunits-spent);
  evidence rasters unchanged. No code change, so the prepared folder was used (= HEAD code, checked file by file).
- Backup `/root/backups/satellite_before_release_20261117_20261117T071051Z.db.raw` (byte copy under a SQLite write lock, WAL empty, sha256 `8ff6a526…` = live) and `.db`
  (online backup, integrity ok), plus the drop-in list and both worker unit files; mode 600.
- `98-satellite-monitoring-release.conf` → this folder; `WorkingDirectory` of `forest-satellite-jobs.service` and
  `forest-satellite-sync.service` → this folder (`systemd-analyze verify` ok); `daemon-reload`; restart of
  `forest-api` only (07:11:37). Timers not restarted; RM / Ingka / review / bot / Telegram workers kept their PIDs
  **on OLD at the time of this activation**. No longer true on NEW: every unit started at boot 12:27 UTC and all were
  restarted by hand 14:59–15:12 UTC (see "Restarts on NEW" above).
- Smoke: 50 GET routes same status/shape as before the switch (only `/api/sat-monitoring/health` + `worker`; the 4
  pre-existing non-200 unchanged); `/health` queue READY, provider OK, worker IDLE, auto_risk false; overview 3 areas,
  8 open + 1 recovered; events 61 and 64 200; true-colour images 200 `image/png`; map-layer 15 features / 139,661 B,
  superseded event 55 → 404; unauthenticated 401 (incl. `/file/…/truecolor`); risks 19 / max id 62 before = after;
  headless Chromium (LV): event 61 and 64 open in "Patiesās krāsas", "Viltus krāsas" switches, Forest Map from event
  64 centred with popup, LVM GEO loads, no console errors; journal 07:11:30–07:17:20 no traceback, 0 restarts.
- Worker: first jobs pass from the new folder 07:12:03 OK; next daily run 2026-11-18 05:35 UTC (first S2 with B03/B02).

## Activation record: satellite-monitoring (2026-11-16 15:52 UTC, Stage 4, owner "approved release")

- Release `/root/forest_ai/releases/forest-api-satellite-monitoring-20261116T1545Z` = active `96-` folder (`forest-map-contrast`) + `git archive 7bd2bbb`
  of `api.py index.html assets satellite_monitoring` (43 files, all byte-identical to git; changed vs 96-: `api.py`,
  `index.html`, `assets/{forest-map.js,forest-map-sat.js,i18n-lv.js,sat-monitoring.js,sat-monitoring.css,vmd-production.js}`,
  `satellite_monitoring/*`). Before the overlay, every live 96- version of the 5 overwritten files was found in git
  history (no unversioned live edit lost). `release-manifest.json` has the sha256 inventory.
- Pre-release: one CDSE token request with the production credentials → HTTP 200 (no Catalog/Process, 0 PU).
- d. Backup: `/root/backups/satellite_before_stage4_20261116T154655Z.db.raw` (byte copy, sha256 `052b99df…20201` = live before) and `.db`
  (SQLite online backup, integrity ok), `.dropins.txt`; mode 600.
- e. Migration (`satellite_monitoring.db.connect()` from the release, venv2): integrity ok, foreign_key_check empty;
  added `sat_jobs` (+2 indexes, 1 trigger) and `sat_change_events.risk_carried_from_event_id` / `risk_carry_overlap`;
  all 13 existing tables same row counts. Live sha256 after: `97a86c40…`.
- f. `97-satellite-monitoring.conf` + `98-satellite-monitoring-release.conf`, `daemon-reload`, restart of
  `forest-api` only (15:52:02). RM / Ingka / review / bot / Telegram workers not restarted (same PIDs).
- g. Smoke: 46 existing GET routes same status and JSON shape as before (4 pre-existing non-200 need parameters:
  `/api/geodata/vmd/compartments` 422, three John Deere OAuth routes 400); new `/api/sat-monitoring/{health,overview,
  sectors,map-layer}` 200; `/health` queue READY, provider OK (last 2026-11-11 07:13 UTC), `auto_risk_enabled` false;
  overview 2 areas, 8 open + 1 recovered; event 51 quicklooks 200 `image/png`; map-layer 14 features / 137,679 B;
  unauthenticated 401; risks 19 (max id 62) before = after; journal 15:52–16:35 no traceback, 0 restarts.
- h. `forest-satellite-{jobs,sync}.{service,timer}` installed (`WorkingDirectory` = the release), `systemd-analyze
  verify` ok; one manual jobs pass: exit 0, empty queue, no rows changed, no request; `forest-satellite-jobs.timer`
  enabled (every 5 min after the last run).
- i. `forest-satellite-sync.timer` enabled: 07:30 Europe/Riga + up to 10 min; first run 2026-11-17 05:38:40 UTC.
  Not yet observed: the first real daily run (status, PU) — check on 2026-11-17.

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

- **forest-api-remove-integrations-page-20261118T0532Z → forest-api-satellite-monitoring-20261117T0521Z (code only, UI):**
  `sh /root/backups/remove_integrations_page_activation_20261118T053321Z/rollback-forest-api.sh` (installs the old `98-` drop-in, `daemon-reload`, restarts forest-api only).
  Safe: identical api.py and satellite code; only `index.html` and the logo differ. Worker units are not involved.
- **forest-api-satellite-monitoring-20261117T0521Z → forest-api-satellite-monitoring-rollback8band-20261117T0831Z — the ONLY valid rollback target (built 2026-11-17 08:31 UTC on OLD, owner OK):**
  Re-verified on NEW 2026-11-17 ~16:45 UTC (read-only, not activated): folder = 96 files byte-identical to `e0c9c84`
  (+ `pre-activation-check.sh`, not in git; `release-manifest.json` is the folder's own); vs `7bd2bbb` exactly
  `satellite_monitoring/{evidence,pipeline,raster}.py` differ; `diff -r` vs `…1545Z` = those 3 files + manifest; no
  `__pycache__` (never imported). Tests of `e0c9c84` on a `git archive` copy (sandbox env paths): system Python
  `155 passed, 2 skipped`; worker venv2 `101 passed, 1 skipped` (test_satellite_monitoring + test_sat_stage2_api +
  test_sat_stage2_worker). Real files read with the folder's `raster.read_stored()`: acq 693 (area 4, 8 bands,
  24×37) → 6 bands, identical to bands 0–5 from the active 0521Z decoder; acq 546 (area 3, 6 bands, 43×32) → identical.
  The `…1545Z` decoder on acq 693: `ValueError: raster has 8 bands, expected 6`.
  On NEW the `99-bind-localhost.conf` drop-in only overrides `ExecStart` (127.0.0.1), so the commands below are unchanged;
  after them also check `ss -ltnp | grep ':8000 '` → `127.0.0.1:8000`.
  Runtime proof without activation (2026-11-17 16:52 UTC, NEW): a hash-identical copy of the folder (scratch dir,
  `diff -rq` = 0 except `data`) ran on 127.0.0.1:8099 with copies of forest_ai.db and satellite.db (startup `init_db()`
  and `risk_ai_worker` write → copies only; no ANTHROPIC/TELEGRAM/SENTINEL/JOHN_DEERE/INTEGRATION credentials in its env),
  rasters read in place. Results: `/health` 200 (last_run 8 OK, provider OK, queue READY, no `worker` key = old code),
  `/areas/4` 200, `/events/66` 200, `/file/693/quicklook` (8-band acquisition) 200 `image/png`, byte-identical to the
  stored PNG; `/file/357/truecolor` 404 (expected: no true colour in the rollback); unauthenticated 401; log without
  tracebacks. Stopped afterwards; :8000 (PID 43619), units and timers untouched; no `__pycache__` in the release folder.
  **Scope of this proof:** API code only, on DB copies and with no credentials (see KNOWN_BUGS P1 on startup side
  effects). The rollback worker units (`forest-satellite-{jobs,sync}.service` from this folder) and the switch commands
  above have **NOT been executed**.
  Folder `/root/forest_ai/releases/forest-api-satellite-monitoring-rollback8band-20261117T0831Z` = `…20261116T1545Z` (code `7bd2bbb`) + 3 files from branch
  `feature/sat-rollback-8band` @ `e0c9c84`: `satellite_monitoring/{raster,pipeline,evidence}.py` — stored S2 rasters with
  6 OR 8 bands are read via `raster.read_stored()` (bands 0-5 by index), so this rollback code works on the 8-band
  files the current release writes from the 2026-11-18 daily run on. Its own fetches stay 6-band (no true colour).
  Verified: 96 files identical to `e0c9c84`, only those 3 files differ from `…1545Z`, no migration; worker venv and
  system Python import it; a real stored Ķekava raster (acq 375, 631 × 624) read as 6-band and as 8-band gives identical
  arrays and NDVI/NBR/valid layers. Tests on the branch: 155 (system Python) + 88 (worker venv) passed.
  ```sh
  printf '[Service]\nWorkingDirectory=/root/forest_ai/releases/forest-api-satellite-monitoring-rollback8band-20261117T0831Z\n' \
    > /etc/systemd/system/forest-api.service.d/98-satellite-monitoring-release.conf
  sed -i 's|^WorkingDirectory=/root/forest_ai/releases/forest-api-satellite-monitoring-20261117T0521Z$|WorkingDirectory=/root/forest_ai/releases/forest-api-satellite-monitoring-rollback8band-20261117T0831Z|' \
    /etc/systemd/system/forest-satellite-jobs.service /etc/systemd/system/forest-satellite-sync.service
  systemctl daemon-reload && systemctl restart forest-api
  readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd        # → …/forest-api-satellite-monitoring-rollback8band-20261117T0831Z
  systemctl show -p WorkingDirectory --value forest-satellite-sync.service  # → …/forest-api-satellite-monitoring-rollback8band-20261117T0831Z
  ```
  The timers can stay enabled (no need to disable `forest-satellite-sync.timer`). What is lost in this rollback:
  true colour (toggle falls back to false colour; existing `*_tc.png` stay on disk), real worker state, Latvian
  section default, image loading state, fragmentation rule for NEW detections (rows already in generation 2 stay).
  satellite.db stays as is (no migration in either direction). Saved unit files: `/root/backups/satellite_before_release_20261117_20261117T071051Z.forest-satellite-{jobs,sync}.service`.
- **forest-api-satellite-monitoring-20261117T0521Z → forest-api-satellite-monitoring-20261116T1545Z: DO NOT ROLL BACK — cannot read 8-band S2.**
  Already unsafe, not only from the 2026-11-18 run on: run 8 (BACKFILL of area 4, 2026-11-17 08:03–08:04 UTC, job #2,
  0521Z code) stored **37 8-band S2 rasters** (all from run 8: 14 OK + 23 NO_VALID_PIXELS; verified on disk with
  tifffile 2026-11-17 16:40 UTC, next to 115 6-band files). The 1545Z decoder accepts exactly 6 bands
  (`ValueError: raster has 8 bands, expected 6`), so detection baselines, redetect and evidence for area 4 would fail.
  Use `…rollback8band-20261117T0831Z` instead.
- **satellite-monitoring → forest-map-contrast (older rollback target, 2026-11-16):**
  ```sh
  systemctl disable --now forest-satellite-sync.timer forest-satellite-jobs.timer
  rm -f /etc/systemd/system/forest-api.service.d/97-satellite-monitoring.conf \
        /etc/systemd/system/forest-api.service.d/98-satellite-monitoring-release.conf
  systemctl daemon-reload && systemctl restart forest-api
  readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd   # → …/forest-api-forest-map-contrast-20261110T0949Z
  ```
  Confirm `/api/deployment` reports `geo-d0015b1f82a0`. The old code ignores `sat_jobs` and the 2 new columns, so
  satellite.db stays as is. Only if satellite.db itself must go back (separate approval; loses jobs/reviews made
  since 15:52): `cp --preserve=all /root/backups/satellite_before_stage4_20261116T154655Z.db.raw /root/forest_ai_satellite_data/satellite.db
  && rm -f /root/forest_ai_satellite_data/satellite.db-{wal,shm}` → sha256 `052b99df…`. Optionally remove the unit
  files `/etc/systemd/system/forest-satellite-{jobs,sync}.{service,timer}` + `daemon-reload`.

- **meza-karte → baseline (pre-Forest-Map):** run
  `/root/forest_ai/data/backups/forest_api_meza_activation_20261107T0852Z/rollback-forest-api.sh`.
  It checks `releases/forest-api-baseline-.../api.py` has SHA-256 `dfbf12fe…`, installs
  `rollback-release.conf` over `50-meza-karte-release.conf`, runs `daemon-reload`, restarts
  `forest-api` and checks it is active.
- **lvm-geo-lv-ui → forest-map-violations (historical, 2026-11-10):**
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
