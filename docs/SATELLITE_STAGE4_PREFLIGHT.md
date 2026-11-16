# Satellite Monitoring — Stage 4 production preflight (read-only)

Date: 2026-11-16 (UTC). Branch `feature/satellite-monitoring` at `27806ab`.

No production change was made:
- no drop-in, no unit, no timer, no restart;
- the live `satellite.db` was only read (sha256 `052b99df…0201` before and after);
- all measurements ran on copies in the session scratchpad.

## Verdict: CONDITIONAL GO

Deploy only after blocker B1 is resolved and decisions D1–D3 are made. Everything else checked is ready.

| # | Blocker / decision | Why | Fix |
|---|---|---|---|
| **B1** | **Live `assets/vmd-production.js` ≠ branch** | Live = commit `50f6daf` (feature/live-vmd-ui-texts: sector-name validation, Latvian error texts, cadastral designation rule), edited in place in the active release on 2026-11-11 08:10 UTC (the only file changed since that release was built). The branch has the older file + the one-line satellite hook. Shipping the branch file would **silently revert** the live VMD fixes. | `git merge 50f6daf` into the feature branch (trial merge: clean, touches only `vmd-production.js`; `lvm-geodata.js` is already identical). Re-run JS tests. Build the release from the merged branch. |
| D1 | Keep Ķekava (EVAL_BBOX, 3,670 ha) in daily monitoring? | It is an evaluation box, not a client area. It costs ~4.3 PU and ~3.6 MB per acquisition, ~1.1 acquisitions/day ≈ **~145 PU and ~120 MB per month**. BIK-001 costs ≈ 4 PU and < 5 MB per month. | Recommended: stop Ķekava monitoring after release (history kept; `POST /areas/2/stop`). |
| D2 | Enable both timers at once, or only the job queue first? | The daily TIMER run starts PU spending (05:30 UTC). | Recommended: install both. Enable `forest-satellite-jobs.timer` at deploy; enable `forest-satellite-sync.timer` after the smoke test passes. |
| D3 | Disk at 93 % (8.8 GB free on `/`) | Not caused by satellite (898 MB total), but the whole host is tight; growth is ~4 MB/day with Ķekava, ~0.2 MB/day without. | Accept, or free space first (e.g. old scratch copies under `/tmp`). Not a blocker for this feature. |

## 1. Production forest-api (verified)

| Item | Value |
|---|---|
| Unit | `forest-api.service`, active since 2026-11-14 06:54:14 UTC, 0 restarts, PID 3092002 |
| Interpreter | `/usr/bin/python3` 3.12.3 via `/usr/local/bin/uvicorn api:app --host 0.0.0.0 --port 8000` |
| Active release | `/root/forest_ai/releases/forest-api-forest-map-contrast-20261110T0949Z` (drop-in `96-…`), built from `66572fa`, `data -> /root/forest_ai/data` |
| Drop-ins | `50-, 70-, 90-` (env `FOREST_GPS_VIOLATIONS_DAYS=90`), `95-`, `96-` (each later one overrides `WorkingDirectory`), `geodata.conf` (`FOREST_GEODATA_MANIFEST`) |
| Env (names only) | `SENTINEL_CLIENT_ID/SECRET`, `TELEGRAM_BOT_TOKEN`, `DISPATCHER_CHAT_ID`, `ANTHROPIC_API_KEY`, `DASHBOARD_*`, JD keys. **No `SAT_*`**, **no `UI_LANGUAGE`** (EN UI; the sidebar labels are localised in `index.html`) |
| Main DB | `data/forest_ai.db` → `/root/forest_ai/data/forest_ai.db` (rollback journal) |
| Dependencies | system python has fastapi, shapely 2.1.2, pyproj 3.7.2, numpy 2.5.2, requests, anthropic. The API does not need tifffile. No new package needed |
| Live release vs `66572fa` | 67 runtime files identical. `index.html` = live-only nav edit, which the branch already carries (`634eea4`); the branch diff on top is only the Stage 3 hunks. `lvm-geodata.js` = branch. **`vmd-production.js` → B1** |
| Branch runtime diff | `api.py` +5 lines (router + deployment hash list), `index.html` (nav item, section, assets), `assets/i18n-lv.js`, new `assets/sat-monitoring.{js,css}`, 1-line hook in `vmd-production.js`, new package `satellite_monitoring/`. `database.py`, `services/**` and `forest-map.*` are unchanged |
| Other services | RM :8002 (`/root/forest_ai_rm`), Ingka :8004 (`/root/forest_ai_ingka`), review :8003 (own release), `forest-bot` (`/root/forest_ai`), tenant Telegram workers: separate directories, not affected. :8010 = another session's localhost sandbox |

## 2. Host resources (2026-11-16 ~09:50 UTC)

| | |
|---|---|
| CPU | 2 cores, load 0.31 / 0.41 / 0.63, CPU pressure avg60 3.3 % |
| RAM | 3,915 MB total, 2,466 MB available, swap 2,337 / 4,095 MB used, memory pressure ~0 |
| Disk `/` | 116 GB, 93 % used, **8.8 GB free** (D3); `/root/forest_ai_satellite_data` 898 MB, `/root/backups` 423 MB |
| Worker peak (measured) | full redetect of Ķekava (all 195 acquisitions, worst case; a daily run handles a few) on a COPY: **peak RSS 424 MB**, 20 min 17 s wall at `nice 19` (81 % of one core), exit 0, 0 network, so `MemoryMax=2G` leaves ample headroom |

## 3. Live satellite.db vs migration

- Live: WAL mode, integrity ok, `user_version` 0. No `sat_jobs` table, no risk-carry columns. Generation 1 is current (events 49–57). 0 human decisions.
- The exact migration (`satellite_monitoring.db.connect()`), run on a backup copy:
  - **added** table `sat_jobs` + 2 indexes (`ux_sat_jobs_open` partial unique, `ix_sat_jobs_status`) + trigger `trg_jobs_no_delete`;
  - **changed** `sat_change_events`: 2 nullable columns appended (`risk_carried_from_event_id`, `risk_carry_overlap`) via `ALTER TABLE ADD COLUMN`; no rebuild;
  - **removed** nothing;
  - row counts identical, `integrity_check` ok, `foreign_key_check` empty, a second run is a no-op;
  - SQLite 3.45.1 in both interpreters.
- Rollback of the migration is not needed for the old code: it ignores the extra table and columns. A byte-exact restore is still prepared (below).

## 4. Backup and rollback (prepared, not executed)

```sh
# B-1  no writer may be running (no satellite unit exists yet; forest-api does not open satellite.db today)
systemctl list-units 'forest-satellite*' --no-legend          # expect empty
TS=$(date -u +%Y%m%dT%H%M%SZ); B=/root/backups/satellite_before_stage4_$TS
# B-2  byte copy + SQLite online backup, both verified
cp --preserve=all /root/forest_ai_satellite_data/satellite.db $B.db.raw
/root/forest_ai_satellite_venv2/bin/python -c "import sqlite3;s=sqlite3.connect('file:/root/forest_ai_satellite_data/satellite.db?mode=ro',uri=True);d=sqlite3.connect('$B.db');s.backup(d);print(d.execute('pragma integrity_check').fetchone())"
sha256sum /root/forest_ai_satellite_data/satellite.db $B.db.raw     # must be equal (expect 052b99df…0201)
chmod 600 $B.db $B.db.raw
# B-3  code rollback point = the current drop-in set (96- is the active release); nothing is removed
ls /etc/systemd/system/forest-api.service.d/ > $B.dropins.txt
```

Rollback (any step fails, or the smoke test fails):

```sh
systemctl disable --now forest-satellite-sync.timer forest-satellite-jobs.timer 2>/dev/null
rm -f /etc/systemd/system/forest-api.service.d/97-satellite-monitoring.conf \
      /etc/systemd/system/forest-api.service.d/98-satellite-monitoring-release.conf
systemctl daemon-reload && systemctl restart forest-api      # back to 96- forest-map-contrast
# only if satellite.db itself must go back (not needed for the old code):
cp --preserve=all $B.db.raw /root/forest_ai_satellite_data/satellite.db && rm -f /root/forest_ai_satellite_data/satellite.db-{wal,shm}
sha256sum /root/forest_ai_satellite_data/satellite.db        # = 052b99df…
```

## 5. Isolation (why the worker cannot interfere)

| Concern | Evidence |
|---|---|
| Writes | Worker units: `ProtectSystem=strict`, `ProtectHome=read-only`, `ReadWritePaths=/root/forest_ai_satellite_data` only, `PrivateTmp`, `NoNewPrivileges`, `UMask=0077`. It cannot write `forest_ai.db`, geodata, releases or client folders. |
| Reads of shared DBs | `forest_ai.db` is opened with `mode=ro` (rollback journal: no sidecar). The nationwide `compartments.sqlite` (WAL, `-shm` present) is opened with `mode=ro`; verified to work under a read-only bind mount (private mount namespace test). Optional hardening: `immutable=1` for the immutable release DB. |
| Risk engine | No automatic risks (D3, tested). The worker modules import neither `database` nor `ai_resolution`. Risks only from a human CREATE_RISK in the API. |
| CPU / RAM / IO | `Nice=10`, `CPUQuota=100%` (1 of 2 cores), `MemoryMax=2G`. Recommended addition before install: `IOSchedulingClass=idle`. |
| Network / quota | CDSE only; quota guard stops at 80 % of 2,000 PU / 6,000 requests per month (November so far: 302 requests, 852.8 PU). |
| LVM GEO | One added line (popup button) on top of the live `vmd-production.js` (after B1). Rest of the page unchanged (tested). |
| Meža Karte / Forest Map | `forest-map.js/.css` unchanged (byte-identical to live; tested). |
| Sectors / objects | Read-only (`/sectors` list). Areas are copies in `satellite.db`; the `sectors` table is never written. |
| Client instances | RM, Ingka and review keep their own code and data; the new release is used by `forest-api` :8000 only. |
| forest-api writes | Only small rows in `satellite.db` (jobs, reviews); the pipeline status guard prevents run/review overwrites (tested). |

## 6. Timers, load and overlap

| Unit | Schedule | Work |
|---|---|---|
| `forest-satellite-sync.timer` → `.service` (oneshot) | `OnCalendar=*-*-* 07:30:00 Europe/Riga` (= 05:30 UTC in winter; systemd 255 validated the expression; next would be 2026-11-17 05:30 UTC), `RandomizedDelaySec=10min`, `Persistent=true` | queue + TIMER run, 10-day lookback, all active areas |
| `forest-satellite-jobs.timer` → `.service` (oneshot) | `OnBootSec=2min`, `OnUnitInactiveSec=5min` | queued UI jobs only; no network when the queue is empty |

- No other Forest AI timers exist. The nearest system job is apt-daily-upgrade ~06:06 UTC (randomised).
- Expected daily load (BIK + Ķekava): ~2–4 Process requests + 2 Catalog searches, ≈ 5 PU, a few minutes of 1 core, ≈ 4 MB disk. Without Ķekava: < 0.2 PU/day.
- Overlap protection:
  1. systemd never starts a oneshot unit twice concurrently.
  2. `.sat-jobs.lock` (`fcntl`) gives one queue consumer, and an interrupted job is re-queued at most `max_attempts` times.
  3. `.sat-monitoring.lock` covers every pipeline / redetect run. A second run gets `Locked`: the job goes back to QUEUED, and the timer run is SKIPPED with exit 3.
  4. `TimeoutStartSec=3h`.
  5. The quota guard stops before the free-tier limits.

## 7. Deployment plan (after approval; every step stops on failure → rollback above)

```sh
# 0  branch (worktree): resolve B1, re-test, push
git -C /root/wt/satellite-monitoring merge --no-ff 50f6daf -m "Merge live VMD UI texts (50f6daf) before Stage 4"
node --test tests/*.js && python3 -m pytest -q tests/test_sat_stage2_api.py tests/test_sat_stage2_worker.py tests/test_satellite_monitoring.py
#    (optional, recommended) IOSchedulingClass=idle in both worker units; Ķekava decision D1

# 1  NEW release folder (never edit 96-, never a worktree path)
REL=/root/forest_ai/releases/forest-api-satellite-monitoring-$(date -u +%Y%m%dT%H%MZ)
cp -a /root/forest_ai/releases/forest-api-forest-map-contrast-20261110T0949Z $REL && rm -rf $REL/__pycache__ $REL/96-*.conf
git -C /root/wt/satellite-monitoring archive HEAD api.py index.html assets satellite_monitoring | tar -x -C $REL
#    check: every file in $REL == merged HEAD (except data symlink); live-only files unchanged; write release-manifest.json (+ sha256 inventory)
#    check: diff -r against 96- shows only api.py, index.html, i18n-lv.js, vmd-production.js (+hook), sat-monitoring.{js,css}, satellite_monitoring/

# 2  pre-activation check on a sandbox port against COPIES (as Stage 3): 127.0.0.1:8030, release dir as cwd,
#    DB_PATH + SAT_DB_PATH -> copies; smoke list S-1..S-8 below must pass; stop the sandbox

# 3  backup  (section 4: B-1 .. B-3)

# 4  migrate live satellite.db once with the worker (empty queue -> no network)
cd $REL && SAT_DATA_DIR=/root/forest_ai_satellite_data FOREST_DB_PATH=/root/forest_ai/data/forest_ai.db \
  /root/forest_ai_satellite_venv2/bin/python -c "from satellite_monitoring import db; c=db.connect(); print(c.execute('pragma integrity_check').fetchone())"
#    verify: sat_jobs exists, 2 columns added, row counts = backup

# 5  forest-api: env drop-in + release drop-in, restart (~3 s downtime of :8000)
install -m 644 /root/wt/satellite-monitoring/deploy/systemd/forest-api.service.d/97-satellite-monitoring.conf /etc/systemd/system/forest-api.service.d/
printf '[Service]\nWorkingDirectory=%s\n' "$REL" > /etc/systemd/system/forest-api.service.d/98-satellite-monitoring-release.conf
systemctl daemon-reload && systemctl restart forest-api && systemctl is-active forest-api

# 6  smoke test S-1..S-8 (below) against :8000

# 7  worker units (WorkingDirectory = $REL), jobs timer first; sync timer after D2
sed "s|@RELEASE_DIR@|$REL|" deploy/systemd/forest-satellite-jobs.service > /etc/systemd/system/forest-satellite-jobs.service
sed "s|@RELEASE_DIR@|$REL|" deploy/systemd/forest-satellite-sync.service > /etc/systemd/system/forest-satellite-sync.service
install -m 644 deploy/systemd/forest-satellite-{jobs,sync}.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/forest-satellite-*.{service,timer}
systemctl daemon-reload && systemctl start forest-satellite-jobs.service      # one manual pass, empty queue
systemctl enable --now forest-satellite-jobs.timer
#    after S-9: systemctl enable --now forest-satellite-sync.timer
```

### Post-deployment smoke test (separate; read-only except S-7)

| # | Check | Pass |
|---|---|---|
| S-1 | `systemctl is-active forest-api`; `/proc/<pid>/cwd` = `$REL`; journal has no traceback (mask the bot token) | active, correct cwd |
| S-2 | `GET /api/deployment` | new `geo-…` version; assets include `sat-monitoring.js` |
| S-3 | Existing routes unchanged: `/`, `/api/summary`, `/api/sectors`, `/api/objects`, `/api/risks`, `/api/satellite/sectors`, `/api/satellite-intel/providers`, Forest Map and LVM GEO endpoints used by the UI | HTTP 200, same shape as before (compare against a capture taken before step 5) |
| S-4 | `GET /api/sat-monitoring/health`, `/overview` | 200; `schema_stage2: true`, `credentials_configured: true`, `auto_risk_enabled: false`; 2 areas, 8 open + 1 recovered |
| S-5 | `GET /api/sat-monitoring/events/51` + its quicklook `/file/{acq}/quicklook` | 200, `image/png` |
| S-6 | Browser (headless) as the dashboard user: Overview, Satellite Monitoring, BIK-001, Ķekava, event 51, LVM GEO search + popup button state, Forest Map loads, Sectors / Objects lists | no console errors; screenshots |
| S-7 | Unauthenticated `GET /api/sat-monitoring/overview` | 401 |
| S-8 | `sha256` of `forest_ai.db` is not compared (live service writes); `risks` count before = after (no automatic risk) | equal |
| S-9 | `systemctl start forest-satellite-jobs.service` (empty queue) → exit 0, `sat_runs` unchanged; then the first daily run is checked the next morning (status OK/PARTIAL, PU < 10) | ok |

Not covered by this preflight:
- a real CDSE call from the systemd sandbox (first happens at the first FETCH or daily run);
- Telegram field check and the AI recommendation in production (both need a human action).
