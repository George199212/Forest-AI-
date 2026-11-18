# Sectors as satellite-first workspace — Stage 0 (read-only inspection)

Date: 2026-11-17 · Branch `feature/sectors-workspace` (worktree `/root/wt/sectors-workspace`), created from tag
`prod-2026-11-17-satellite-monitoring` (bc8c428) as the prompt requires. Note: AGENTS.md/CLAUDE.md say "branch from
origin/master", but master has no satellite code, so I followed the prompt. Nothing on :8000, in `/root/forest_ai`, in
release folders or in the live DBs was changed. All data queries ran on checksum-verified copies (see §0).

Prompt: "FOREST AI — SECTORS AS SATELLITE-FIRST WORKSPACE, v2". `CODING_RULES.md` does not exist in the repo (the
Stage 5 Stage 0 found the same).

## v3 — re-verification on the NEW server (64.225.79.80), 2026-11-17 16:10–16:30 UTC

Prompt v3 (= v2 + server migration). The v2 Stage 0 below was written on OLD at ~10:20 UTC, before the snapshot
(~10:30), and it is present on NEW (worktree clean, commit 000f235, branch **not pushed**). Every fact was re-checked on NEW,
read-only. Result: **all v2 findings still hold, with one correction (85 sectors, not 68).**

| Check (prompt §10 Stage 0) | Result on NEW |
|---|---|
| Host | `forest-ai-production-ams3`, eth0 **64.225.79.80**; / 154 G, 101 G used (65 %), 54 G free |
| forest-api | active since 15:06 UTC; cwd `releases/forest-api-satellite-monitoring-20261117T0521Z` (drop-in 98-); new drop-in **99-bind-localhost** → `--host 127.0.0.1`; `data` → `/root/forest_ai/data` symlink; SAT_* env from 97- |
| Listeners | 127.0.0.1 only: 8000, 8002, 8003, 8004 |
| `curl 127.0.0.1:8000/` | **401** ✓ |
| `/api/sat-monitoring/health` (Basic Auth from .env, not printed) | **200**, 77 ms; provider OK; queue READY; 0 failed jobs; month 541 req / 893 PU of 2000 |
| Release vs tag `prod-2026-11-17-satellite-monitoring` (= bc8c428) | 89 runtime files: **0 drift, 0 untracked** (same as on OLD) |
| DNS | `app.forestaisystems.com` → 64.225.79.80 already (Stage 4 can curl the public URL directly) |
| Last sat_runs row | id 8, BACKFILL area 4, 08:03–08:04 UTC, OK (pre-snapshot) |
| Daily sync on NEW | **not run yet**. sync timer next = **2026-11-18 05:37:20 UTC** (prompt says 05:39; RandomizedDelay); "last trigger 05:38 today" is the OLD run carried in the snapshot. jobs timer runs every 5 min, last OK 16:11 |
| Open events | areas 1/3/4 (real sectors / LVM GEO): **0 current**. Area 2 (Ķekava EVAL_BBOX): 8 SUSPECTED + 1 RECOVERED current. sat_review_log: 0 rows. Unchanged from v2 |
| satellite.db | sha256 `7affc129…` = **identical** to the v2 copy; mtime 08:04; WAL mode; 14 tables |
| forest_ai.db | journal=delete, 45 tables (+ sqlite_sequence). sha changed (mtime 15:19). Per-table diff vs Codex's pre-flight backup `/root/forest_ai_backups/object-sync-0521-final-preflight-20261117T095128Z/`: **only `john_deere_sessions` 2 → 1 rows**. Sector-related tables are unchanged, so the §6 inventory and the fixtures remain valid |
| Missing references | `reports/MIGRATION_AUDIT_20261117.md` and `claude/SATELLITE_WORKSPACE_PROMPT_v2.md` **do not exist on NEW** (searched all of /). The §0a facts were re-verified directly instead |

**Correction to v2.** There are **85 sectors** (all org 1): 17 legacy/demo/test (ids 1–5, 9, 12–21, 26) + **68 LVM GEO/VMD
registrations** (ids 30–97, each with a `geodata_sources` row). v2 wrote "68 sectors" in §1 and §6 (the fixture
`sectors_list.json` already has 85 rows). Re-measured on live :8000: `GET /api/sectors` **1.56 s, 124 KB @ 85 sectors**;
`/sat-monitoring/sectors` 19 ms, `/overview` 31 ms. A linear extrapolation to 1,000 sectors gives ≈ 18 s. That is an
estimate; the measurement is a Stage 3 item. The case for the summary endpoint (D6) still holds.

**Stage 5 status on NEW: NOT released.** `/root/wt/satellite-workspace` is now **committed and clean** at 3068e99
(the Stage 1 prototype 71d2737 that was uncommitted on OLD is now committed). It is **5 commits ahead of
origin/feature/satellite-workspace (not pushed)**. Relative to bc8c428 it changes `assets/sat-workspace.{js,css}` (new),
`index.html` (+2), `satellite_monitoring/{api_routes,store,vmd_context}.py`. The mount evidence (§3) was re-checked in the
committed file: `root()` → `#satm-root` (l.266), `pageHead()` (l.303), Back `pushState` (l.477), event links
`location.hash` (l.752), 24 `getElementById`, `_worstColour` exported (l.979). **Stage 2 of this task stays blocked.**

**Uncommitted work by others on NEW (not touched):** `/root/forest_ai` (branch `vps-migration-2026-11-17`, HEAD 20bb021
15:15 UTC; 9 modified incl. api.py, index.html, bot.py, database.py + 84 untracked), `forest_ai_navfix` (2),
`forest-ai-native-isolation` (13), `forest-map-basemap-contrast` (3), `forest-map-polish` (1), **`hide-integrations` (4, based
on bc8c428, edits index.html nav: a third parallel change to the sidebar/router besides navfix and Stage 5)**,
`lvm-geo-registration-fix` (7, Codex). Note: the main checkout is not on master and is dirty. The release workflow
(DEPLOY_RELEASES.md) builds from tags/worktrees, so this does not block Stages 0–3. For Stage 4 the owner should know the
VPS-migration commit 20bb021 is not in the live release.

**Lost-write window (§0a).** Satellite side: nothing after 08:04 exists on NEW. If OLD ran a job or a review between
10:30 and going offline, it is missing. sat_review_log is empty on NEW. Main DB: unknown for OLD. §8 writes stay blocked
until the owner closes the OLD reconciliation.

**Out-of-scope items observed (reported, not fixed):** none blocks this task. The 99-bind-localhost drop-in and UFW are
already in place; the prompt does not list LVM GEO WMS reachability from NEW (TCP timeout to the geoserver, seen by the
object-sync work), but it affects §9 only if the registration flow needs live WMS. Cadastral search is local-only.

Decisions D1–D9 (§10) are unchanged. Add **D10**: who pushes `feature/sectors-workspace` (000f235 + this v3 commit) and
`feature/satellite-workspace` (5 unpushed commits). The only copy of both is this droplet.

## 0. Production state and drift

| Check | Result |
|---|---|
| forest-api :8000 cwd | `/root/forest_ai/releases/forest-api-satellite-monitoring-20261117T0521Z` (drop-in 98-) |
| Release dir vs tag `prod-2026-11-17-satellite-monitoring` (bc8c428) | 89 runtime files (.py/.js/.css/.html): **0 drift, 0 untracked** |
| DB copies used for all numbers below | forest_ai.db sha256 `75f527a2…` = live; satellite.db `7affc129…` = live; both `integrity_check ok` |
| Sandbox | 127.0.0.1:8040 from this worktree on a second copy of each DB, test-only Basic Auth; stopped after use |

**Stage 5 status: NOT released.** `/root/wt/satellite-workspace` (feature/satellite-workspace) has commits up to 7c5edfe
(read-only API additions) and **uncommitted** Stage 1 work: `assets/sat-workspace.js` (981 lines), `sat-workspace.css`,
`tests/test_sat_workspace.js`, plus 2 lines in index.html. Per the sequencing rule, **Stage 2 of this task is blocked until
Stage 5 is released**. Stages 0–1 can run (Stage 1 only on fixtures and in a sandbox).

Note: the prompt names the workspace `assets/sat-monitoring.{js,css}`. Stage 5 actually builds a **new** module,
`assets/sat-workspace.{js,css}` (`window.SatWorkspace`). It overrides `SatMonitoring.load/openArea/openEvent` and keeps
`sat-monitoring.js` for the legacy hooks (`lvmButton`, …). This report refers to the Stage 5 module.

Parallel work that touches the same code:
- `fix/navigation-history` (`/root/forest_ai_navfix`, 29ece75, not deployed) rewrites the router, popstate and the
  sector/tab history. Sector routes must be designed on top of it, or one of the two will conflict.
- Codex is working on LVM GEO / Boundary Plan. Files this task must not touch: `assets/vmd-production.js`,
  `assets/lvm-geodata.js`, `assets/lvm-wms-map.js`, `services/geodata/**`.

## 1. Current Sectors code (bc8c428)

| Piece | Where | Notes |
|---|---|---|
| Sidebar item | index.html:332 `nav('sectors')` | navMap index 2 |
| List section | index.html:421–473 `#sec-sectors`: "Create Sector" form + `#sectors-table` | mixed RU/EN headers (Сектор, Подрядчик…) |
| List loader | index.html:1335 `loadSectors()` → `GET /api/sectors` + `GET /api/objects` | table; object filter banner |
| Detail | index.html:1381 `openSector(name)` → `GET /api/sectors/{name}` | **keyed by name**, route `#sector-{encodedName}` |
| Detail tabs | index.html:1450 `detailTab()` | 13 tabs (see §5) |
| Router | index.html:4495 `routeFromHash`, 4519 `openRoute`, 4547 popstate | `#sat-monitoring?area=` / `?event=` deep links exist |
| `GET /api/sectors` | api.py:716 | **no `id` in SELECT**; per row: `calc_risk_score` + 5 COUNTs (N+1) |
| `GET /api/sectors/{name}` | api.py:1482 | `SELECT *`; unknown name → **HTTP 200 `{"error":"Not found"}`** |
| Provenance | `assets/lvm-geodata.js:224 loadLvmSource` → `/api/geodata/sectors/{id}/source` (table `geodata_sources`) | LVM GEO file; do not touch |
| Meža karte sectors | `GET /api/geodata/forest-map/sectors`; forest-map.js popup has only "Atvērt Sektori" → `nav('sectors')` (the list, not the sector) | |

Measured on the sandbox (85 sectors — v2 said 68, see v3 correction; 3 runs): `GET /api/sectors` **1.52–1.72 s, 124 KB**. Other calls:
`/api/sat-monitoring/overview` 17–52 ms, `/sat-monitoring/sectors` 10–20 ms, `/areas/{id}` 63–125 ms (~100 KB each),
`/api/sectors/BIK-001` 39–53 ms. The list cost grows linearly with the number of sectors; a straight extrapolation to 1,000
is ≈ 22 s (not measured; the measurement is a Stage 3 item). **The list needs a light summary endpoint** (§7).

## 2. Sector ↔ monitored area link and geometry

**Link (from code, store.py:565 `sectors()`, areas.py:13 `resolve_sector`):** `sat_monitored_areas.source='SECTOR'` AND
`source_ref = str(sectors.id)` (forest_ai.db), `active=1`. There is a **second, unused path**: areas added from LVM GEO have
`source='LVM_GEO'`, `source_ref='VMD:nodala…:…'`, which is the same string as `geodata_sources.source_feature_id`. So an
LVM_GEO area can be matched to a registered sector through that column. No code does this today.

Live state (copy):

| area | source | source_ref | sector | data_status | OK acq. (S1/S2) | events (current / all) |
|---|---|---|---|---|---|---|
| 1 | SECTOR | 26 | BIK-001 | OK | 71 / 23 | **0** / 9 (all superseded, gen 1) |
| 2 | EVAL_BBOX | kekava-… | — (not a sector) | OK | 140 / 58 | 9 / 57 |
| 3 | LVM_GEO | VMD:nodala2454:49647452 | **no sector** (LG917 registered other K348 compartments) | OK | 78 / 15 | 0 |
| 4 | SECTOR | 76 | Т-56 — K1 N23 | OK | 78 / 14 | 0 |

**No real sector has an open (current) change event.** The "monitored with event" state exists only on Ķekava, which is not
a sector. See decision D3.

**Geometry sources:**
- Authoritative: `sectors.boundary_json`, a `[[lat, lon], …]` list. For LVM GEO / VMD registrations the source polygon is
  recorded in `geodata_sources` (CRS EPSG:10306 → 4326 via pyproj) and in `geodata_boundary_history`.
- `sat_monitored_areas.geometry_geojson` is a **COPY** taken when the area was created (areas.py `create`).
- Today's comparison (coordinates, not screenshots): area 1 vs sector 26 and area 4 vs sector 76 are **identical**
  (max |Δ| 0.0°, same vertex count).
- **Drift risk:** if a sector boundary is later changed (geodata_boundary_history UPDATE flow, or manual edit), the satellite
  area keeps the old polygon. Nothing syncs the two, and the UI would show two different outlines. Proposal for Stage 2: the
  sector page compares the two and shows "Monitoringa robeža atšķiras no sektora robežas" when they differ. **No sync logic
  without approval.**
- Satellite risks store `risks.sector = area.name` (risk_bridge.py:114). That name is also a copy, so renaming a sector
  breaks the link.

**Legacy LKS-92 converter (KNOWN_BUGS #1).** Callers: api.py:1075/1108 (`create_sector_from_drawing`, boundary plans),
bot.py:161/172/241, services/robez_ocr_vision.py:59/202/472. Affected sectors:

| id | name | finding |
|---|---|---|
| 9 | S-004 | **outside Latvia** (58.87 N, 28.71 E), bot/OCR origin |
| 15, 16, 17 | S-00x — <property name> (plan 17) | **outside Latvia** (58.90 N, 32.74 E) |
| 12, 13, 14 | S-00x — Mūrnieku Jāņa (plan 16) | inside Latvia, but created through the same converter: **suspect, not verifiable** without the source plan |
| 18–21 | manual drafts on plans 16/17 | no boundary |

Not fixed, as instructed.

## 3. Can the Stage 5 workspace be mounted in the sector page? → **Option A is feasible after a small refactor in Stage 5's file**

Evidence (sat-workspace.js, uncommitted Stage 1):
- `root()` is hard-wired to `document.getElementById('satm-root')` (line 266). There are 24 `getElementById` calls with global
  ids (`satw-map`, `satw-right`, `satw-tl`…), and the module state `S` is a singleton.
- `pageHead()` writes the global `#page-title`. The Back button does `history.pushState('#sat-monitoring')` (line 477), and
  event links set `location.hash='sat-monitoring?event='` (line 745).
- The exports are `load`, `openArea`, `openEvent` and `_worstColour` (the §4.4 function, importable for cards ✓).

So `openArea(id)` cannot render into a second container today. Mounting it as-is would hijack `#satm-root`, the page title
and the history. The change needed (additive, no copy of the workspace):
`SatWorkspace.mount(el, {areaId, embedded: true, onBack, eventHref})`. It would:
1. set `S.root = el` (so `root()` returns it);
2. skip `pageHead()` when embedded;
3. let the caller supply the Back and "open event" routes;
4. call `cleanup()` on unmount.

The global ids remain unique because only one section is visible at a time; `mount` must unmount the other instance first.
This is ~20–30 lines in **sat-workspace.js**, which belongs to Stage 5 ("Stage 5 wins inside the workspace"). It must either
go into Stage 5 before its release, or be the first commit of this task's Stage 2 after rebasing on Stage 5. **Owner decides
(D1).** Fallback B (header + panel + a full-height link to `#sat-monitoring?area={id}`) works with zero changes to the
workspace.

## 4. Obsolete controls (§7) — remove the UI only; proposed list for approval

| # | Control | File:line | Calls | Other callers | Data / demo dependence | Proposal |
|---|---|---|---|---|---|---|
| O1 | "📤 Upload sector satellite" | index.html:1427, fn 1223 | POST `/api/sectors/{name}/satellite` (api.py:930) | none | 1 sector has `satellite_file_path` (BIK-001) | remove the button; keep the endpoint |
| O2 | Detail tab "🛰 Satellite" (legacy) | index.html:1698–1730, 3828–3860 | on-demand Sentinel Hub `/api/satellite/image|ndvi/{sector}` (api.py:2398/2514), `/api/satellite-intel/sector/{name}` (2653), shows the uploaded image | hidden `#sec-satellite` (index.html:3453–3583) uses the same endpoints | defaults to 2024-06; **falls back to Riga 56.95/24.11 when a sector has no centre** (fabricated location); spends CDSE quota per click; `satellite_requests` 0 rows | replace with the workspace (§1); remove the tab |
| O3 | Objects filter "🛰 Object satellite" | index.html:1351 | `/api/satellite/object/{id}` (api.py:2456) | none | — | remove the link |
| O4 | Detail tab "🗺 Map" (second map engine) | index.html:1687, `renderDetailMap` 3678 | `/api/sectors/{name}/session-tracks` | `trkOpenOnMap` (2517) | tracks exist only for BIK-001 (29 points) | becomes the workspace / empty-state map + Activity block; keep the tracks endpoint |
| O5 | Detail tab "📅 История" (manual snapshot upload) | index.html:1735, 4109 | `/api/sectors/{name}/snapshots`, `/api/sectors/snapshots/*` | snapshot↔risk linking (3659) | 6 rows: A-004 ×4, A-005 ×2 (demo sectors) | hide behind flag (data exists on demo sectors), do not remove |
| O6 | "Create Sector" manual lat/lon form | index.html:421–466, `createSector` 3900 | POST `/api/sectors` | — | produced the "Draft — manual" sectors 18–21 | **owner decides**: hide behind flag (registration goes through LVM GEO) or keep |
| O7 | Object-detail "📤 Upload satellite" | index.html:1182 | `/api/objects/{id}/satellite` | — | — | out of Sectors scope; listed only |
| — | Hidden nav: Photos, AI Inspector, Satellite (`display:none`, index.html:340–343) | | | `nav('map')` is still called from **lvm-geodata.js:215** (`lvmOnForestMap`, LVM GEO file) | | leave as is; `#sec-map` must stay because LVM GEO uses it |

demo_scenarios.py uses **A-005** (breakdown, sector exit, wetland), **A-006** (logging) and **A-007** (volume, prefix
match). None of them uses O1–O6. The Biķernieki storm case is BIK-001: photo_cmp_runs, 48 photos, 29 track points.

## 5. Sector menu audit (§6) — detail tabs and real data on :8000 (copy)

| Tab | Source | Rows (all sectors) | Real data |
|---|---|---|---|
| GPS | work_sessions | 29 (A-004 11, S-004 7, A-005 4, BIK 4, …) | yes |
| Photos | work_photos | 58 (BIK 48) | yes |
| 🔍 Salīdzināšana | photo_cmp_runs | 1 (BIK) | yes (storm case) |
| Risks | risks | 19 | yes |
| Comments | work_sessions.comment | 25 | yes |
| Trucks | truck_reports | **0** | empty everywhere |
| Timber | timber_movements | 2 | A-004, A-007 |
| 👷 People | sector_employees | 9 | yes |
| 🚛 Vehicles | sector_vehicles (+fuel logs 1) | 5 | A-004, A-005 |
| 🌲 Forest | sectors.notes/tree_species/cut_plan_notes | 1 sector | barely |
| 🗺 Map | boundary + session tracks | | O4 |
| 🛰 Satellite | legacy | | O2 |
| 📅 История | sector_snapshots | 6 | demo sectors |
| (Weighing) | weighbridge_records | **0** | no tab exists |
| (Documents) | — | no table | no tab exists |

The 68 LVM GEO / VMD sectors (ids 30–97) have **no** operational rows at all (only `geodata_sources` + boundary history).
Proposed flag, following the pattern already in `serve_index` (api.py:597): env `SECTOR_LEGACY_MODULES` (default off) →
`window.SECTOR_LEGACY_MODULES`. When it is off, a module block is rendered only if this sector has rows for it. Nothing is
deleted.

## 6. Sector inventory (§8 steps 1–2, read-only) — proposal, owner classifies

85 sectors (v3 correction; v2 said 68), all `organization_id=1`, `data_origin` = REAL except A-005 (SIMULATED). References are by **free-text name**
in 21 tables, plus `geodata_sources` / `geodata_boundary_history` by `sector_id` (`geodata_sources` has an FK with
**ON DELETE CASCADE**, a further reason never to hard-delete). Full per-sector counts: scratch `inventory.json`; the
non-zero ones:

| Proposed class | ids | References (forest_ai.db) | satellite.db |
|---|---|---|---|
| DEMO-REQUIRED | 2 A-005, 3 A-006, 4 A-007…, 26 BIK-001 | A-005: 32 rows in 12 tables; BIK-001: risks 2, sessions 4, photos 48, tracks 29, photo_cmp 1, live_loc 1 | BIK-001 = area 1 (134 acq, 9 events) |
| LEGACY (real history; keep or archive) | 1 A-004, 5 A-008 | A-004: 49 rows / 9 tables; A-008: 3 | — |
| TEST, outside Latvia | 9, 15, 16, 17 | 9: 7 sessions + 10 AI analyses **shared by name with 18** | — |
| TEST, plan drafts | 12, 13, 14 (suspect CRS), 18–21 (no boundary) | 13: 1 session + 2 analyses; 14: 1 session; 18 = "S-004", see below | — |
| LVM GEO registrations | 30–97 (names like "RD-9999", "Sektors jauns 123", "R123", "S003", "Т-56", "LG917", "Dob23") | geodata_sources 1 + history 1 each | 76 = area 4 (added by a user today 08:03) |

Findings that block a safe archive by name:
- **Duplicate name "S-004"** (ids 9 and 18). Every name-keyed row (7 sessions, 10 AI analyses) matches both, so neither
  can be archived "cleanly".
- **Orphan or mismatched names** (rows whose `sector` matches no sector): risks `'A-005 — <client>'` ×5 (3 DEMO_SCENARIO),
  `'A-007'` ×2, `'TEST-STAGE1B'` ×1, `'TEST-STAGE2B'` ×1; sector_employees `'A-007'` ×1; ai_inspector_analyses `NULL` ×15.
- LVM GEO sectors 30–97: I cannot tell test from production from the data (all REAL, all created by the dashboard account
  2026-10-30…11-17; LG917 and Dob23 were created today). **No proposal without the owner's list.**
- Area 3 (LVM_GEO, VMD 348-21) belongs to no sector. Archiving does not concern it.

The archive design (archived_at / archived_reason, ALTER TABLE ADD COLUMN, backups, preview doc, copy first) is unchanged
from the prompt. Nothing is prepared or written in Stage 0.

## 7. Gap list (§4–§5 field → existing payload or smallest read-only addition)

| Need | Existing | Gap / smallest addition |
|---|---|---|
| Card route by id | `/api/sectors` has **no id**; detail is by name (duplicates exist) | add `id` to the list SELECT; route `#sectors/{id}`, resolved to the name via the list (detail stays name-keyed; duplicate-name sectors stay ambiguous for name-keyed data, shown as a warning) |
| One list request, 1,000 sectors | `/api/sectors` 1.5 s @85, N+1 risk score | **new read-only `GET /api/sectors/cards`**: id, name, area_ha, status, created_at, provenance (`geodata_sources.provider/source_feature_id/imported_at`), centroid/bbox, simplified ring; **no risk score**; plus `GET /api/sat-monitoring/sector-summaries` (one query per table on satellite.db, Basic Auth) |
| Identifier | in the name text / `geodata_sources.source_feature_id`; cadastral number in `source_properties` | in `/cards` (stored values only) |
| area ha | `sectors.area_ha` (stored; for VMD it is computed at registration, from the source polygon) | label "saglabātā vērtība" |
| Monitoring status | `/sat-monitoring/sectors` (monitored_area_id, queued_job_id) + overview `data_status` | summary: SECTOR link + **LVM_GEO link via source_feature_id**; Netiek monitorēts / Gaida pirmos datus (`NO_DATA_YET`, `BACKFILL…`, queued job) / Monitorēts / Apturēts (`STOPPED`) |
| Last acquisition | overview `last_s1_utc`, `last_valid_s2_utc` (S2 only if valid ≥ min) | summary: `last_ok_sensing_utc` = max sensing of OK acquisitions, with its sensor (owner: include S1 and low-valid S2? D5) |
| Open suspected | overview `open_suspected_events` ✓ | — |
| Confirmed | overview `reviewed_events` = confirmed **+ rejected** | summary: `confirmed_events` (REVIEW_CONFIRMED, current generation) |
| Worst colour dot | only in `/areas/{id}` events | summary returns `{status, classification, confidence}` of the open events; client calls `SatWorkspace._worstColour` (not re-implemented) |
| Preview image | `truecolor_url` per timeline row, only in `/areas/{id}` | summary: `preview {acq_id, kind: truecolor|falsecolour, sensing_time_utc, valid_pct}` |
| Bbox for the overlay | overview `grid_bbox` ✓ | in summary |
| Panel: 3 timestamps | acquisition ✓ timeline; **last successful analysis = 7c5edfe (Stage 5, not live)**; system check = `/health` provider `at_utc` | none beyond Stage 5 |
| Panel: Riski | `/api/sectors/{name}`.risks, `entity_type='SATELLITE'` | none (name-link caveat §2) |
| Panel: Aktivitāte | gps_sessions, `/session-tracks`, risks | none |
| Meža karte → sector | popup "Atvērt Sektori" → list | forest-map.js: pass the sector id → `#sectors/{id}`. The index.html tag `forest-map.js?v=20261107` stays byte-exact; assets are served `no-cache, must-revalidate` (api.py:636), so editing the content is safe |

**Preview findings (§4.2):**
- True-colour files exist **only for area 4** (new acquisitions after the 2026-11-17 release). BIK-001 and area 3 have only
  the false-colour quicklook, which must be labelled.
- The latest true-colour for area 4 (acq 693, 2026-11-04) has **valid_pct_inside 7.4 %** (mostly cloud). "Latest" must mean
  latest OK acquisition with `valid_pct_inside ≥ min_valid_pct`, or the card shows a cloud.
- The quicklooks are tiny: 37×24 px (0.21 ha sector), 127×95 px (BIK-001 50 ha), at 10 m pixels including the buffer. On a
  card they will look blocky and need `image-rendering: pixelated` plus a "10 m pikseļi" note. Most of the 68 LVM GEO sectors are
  under 3 ha. Owner decides (D4).

## 8. Fixtures (`tests/fixtures/sectors_ui/`, 6 JSON files, 493 KB)

Captured from the sandbox on copies. Identity and personal fields are redacted (user/telegram ids, employee and responsible
names, accounts, file paths, `added_by`/`reviewed_by`/`actor`). One sector name containing a personal surname is redacted.
The secret scan (test credentials, dashboard/token/secret/password, telegram id, surname) found 0 hits.
- `sectors_list.json` (GET /api/sectors), `sat_sectors.json`, `sat_overview.json`
- `sector_monitored_history_no_open_BIK-001.json` — monitored, 9 superseded events, 0 open, false colour only
- `sector_monitored_truecolour_no_events_sector76.json` — monitored, true colour, 0 events
- `sector_not_monitored_lvmgeo_sector81.json` — LVM GEO registration, not monitored
- **No "monitored with open event" sector exists** (D3).

## 9. Tests

There are no code changes in Stage 0 (docs and fixtures only), so the suite was **not re-run**. The baseline on bc8c428 is
9 failed / 40 errors (Stage 5 Stage 0 and the Stage 2 records). Before Stage 2, it will be re-run in isolation on this
branch.

## 10. Decisions needed before Stage 1

- **D1** Mount: option A (`SatWorkspace.mount(el, opts)`, ~20–30 lines in sat-workspace.js, done in Stage 5 or as this
  task's first commit after rebasing), or fallback B (link-through)?
- **D2** Obsolete controls O1–O6: approve the list (remove O1–O4 UI; O5 behind a flag; O6?).
- **D3** "Monitored with event" state for Stage 1: use the Ķekava area payload (EVAL_BBOX, clearly labelled as not a sector)
  as the fixture, or skip that state until a real sector has an event?
- **D4** Previews for small sectors (most are < 3 ha → 20–40 px images): show them pixelated with a note, or fall back to the
  polygon-only preview below a size threshold?
- **D5** "Last satellite acquisition" on the card: S1 and S2 combined, or the last S2 with valid ≥ min only (plus S1 separately)?
- **D6** New read-only endpoints `GET /api/sectors/cards` and `GET /api/sat-monitoring/sector-summaries` (the second
  touches satellite_monitoring/store.py + api_routes.py, which Stage 5 also edits, so it goes after the Stage 5 release):
  approve?
- **D7** Should LVM_GEO areas count as a sector's monitoring when `source_ref = geodata_sources.source_feature_id`?
- **D8** Inventory classification (§6): your list of TEST / LEGACY / keep, especially ids 30–97 and the duplicate S-004.
- **D9** Flag name/default for the legacy modules (`SECTOR_LEGACY_MODULES`, off).

## 11. Owner decisions (2026-11-17, "approved, with these changes")

- **D1** Option A. `SatWorkspace.mount(el, opts)` is added by the Stage 5 session before its release; this branch never
  edits `sat-workspace.js`. The Stage 1 prototype may stub the mount call.
- **D2** O1–O4: UI removed; O5 + O6 behind the flag; backend unchanged.
- **D3** Ķekava payload only as a Stage 1 fixture, labelled "test area, not a sector"; never in Stage 2 code paths or the release.
- **D4** No pixelated previews. Longest side of the sector < 64 Sentinel-2 px (10 m) → polygon-only preview labelled
  "Sentinel-2 10 m — sektors par mazu priekšskatījumam" / "Sentinel-2 10 m — sector too small for a preview". The
  threshold is a named constant.
- **D5** Separate dates: primary = last valid S2 sensing date; secondary line = last S1 date. Never one combined date.
- **D6** Approved: read-only, Basic Auth, with tests.
- **D7** As recommended: exact `source_ref = geodata_sources.source_feature_id` match only, read-only, the source is shown.
- **D8** Archive nothing. The owner classifies ids 30–97 later.
- **D9** `SECTOR_LEGACY_MODULES`, default off (serve_index flag pattern).
- **D10** Both branches pushed by the owner.
