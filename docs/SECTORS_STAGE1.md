# Sectors as satellite-first workspace — Stage 1 (prototype on fixtures)

Date: 2026-11-17/18 · Server NEW 64.225.79.80 · Branch `feature/sectors-workspace` · Owner decisions D1–D10: see
`docs/SECTORS_STAGE0.md` §11. **Nothing in production changed**: :8000, its release folder, the live DBs, timers, nginx and UFW
are untouched. Stage 2 is still blocked until Stage 5 is released.

## 1. Sandbox

| Item | Value |
|---|---|
| Disk before copies | `df -h /`: 154 G, 101 G used (66 %), 54 G free |
| DB copies (`sqlite3 … ".backup"`, WAL-safe) | `/root/sectors_sandbox/data/forest_ai.db` sha256 `2b22fb18de3095bb…`, `satellite.db` `460aad632b02065e…` (full sums in `data/SHA256SUMS`); both `integrity_check ok`. A `.backup` copy has a different hash from the live file (pages are rewritten); content = live at 16:32 UTC |
| App | `git archive 3068e99` (Stage 5 head, so `last_successful_analysis_utc`, `_worstColour` and the real workspace link-through exist) + this branch's prototype files + the index.html hooks. Sandbox-only line: `window.SECTOR_CARDS_URL="/assets/sector-cards-fixture.json"` |
| Server | `/root/sectors_sandbox/start.sh` → uvicorn **127.0.0.1:8010** only, in a private mount namespace where `/root` is read-only except `/root/sectors_sandbox`; rasters read from the live raster folder, read-only. Copy in `tests/e2e/sectors_stage1/start.sh` |
| Auth | **test-only** Basic Auth in `/root/sectors_sandbox/.sandbox_auth` (0600), not the production credentials |
| View | `ssh -L 8010:127.0.0.1:8010 root@64.225.79.80` → `http://127.0.0.1:8010/#sectors` |
| Stop | `pkill -f '[u]vicorn api:app --host 127.0.0.1 --port 8010'` (the `[u]` keeps pkill from matching its own shell) |

## 2. What the prototype is

| Piece | File | Notes |
|---|---|---|
| Card data (shape of the D6 endpoints) | `scripts/sector_cards_fixture.py` → `tests/fixtures/sectors_ui/sector_cards.json` (85 sectors + 1 Ķekava card flagged `_fixture_only`, 124 KB) | read-only on copies; refuses live DB paths; stored values only; S2 "valid" = `valid_pct_inside ≥ min_valid_pct` (60); preview = latest valid S2 with a stored image (true colour if the `_tc.png` exists, else false colour); open = SUSPECTED + FIELD_CHECK_REQUESTED, current generation; D7 exact LVM GEO match; open ADD_AREA job → `queued_job_id` |
| UI module | `assets/sectors-cards.{js,css}` (`window.SectorCards`) | cards, search, status filter, pagination (100), `#sectors/{id}` route, sector page, LV/EN (shares `satMonitoring.lang` with Stage 5) |
| index.html | +11 / −1 lines | CSS/JS include; `loadSectors()` delegates (object-filtered table unchanged); router `#sectors/{id}`; popstate `sectorPage`; `nav()` calls `SectorCards.leave()`. `forest-map.js?v=20261107` tag byte-exact |
| O6 | "Create Sector" card hidden unless `window.SECTOR_LEGACY_MODULES` | nothing removed (D2/D9); the flag injection itself is Stage 2 |
| Mount (D1) | sector page calls `SatWorkspace.mount(el, {areaId, embedded, onBack, eventHref})` **if it exists**; otherwise a labelled stub with the link-through `#sat-monitoring?area={id}` | `sat-workspace.js` not edited |
| Tests | `tests/test_sectors_cards.js` (node --test) | **6/6 pass**: status derivation, D4 threshold edge (639 m → too small, 640 m → image), NULL ≠ 0, suspected ≠ confirmed (never "verified"), worst colour imported (no colour literals in the module), routes |

Card rules as built: status chip from stored fields only (`deriveStatus`); counts shown as numbers only when monitoring
data exists, else "Nav pieejams"; S2 date primary, S1 date as a smaller second line (D5); worst open-event dot from
`SatWorkspace._worstColour`; preview = Sentinel image with the polygon drawn from the stored ring over the stored CRS84 grid
bbox, caption "Sentinel-2 · {date}" (+ "viltus krāsas" when false colour) and "Contains modified Copernicus Sentinel data
{YEAR}"; otherwise a polygon-only SVG (scale bar, ha) labelled "Satelīta attēls vēl nav pieejams" or, under 64 px, "Sentinel-2
10 m — sektors par mazu priekšskatījumam" (D4); no basemap snapshots, no Leaflet per card, `loading="lazy"`, fixed 16:9 box.

## 3. Screenshots (31, `/root/sectors_sandbox/screenshots/`, not committed: 5.4 MB, real sector data)

Reproduce: `NODE_PATH=/root/forest_ai_navfix/tests/e2e/node_modules node tests/e2e/sectors_stage1/shots.js` (+ `add_flow.js`).
The main app has no light/dark theme, so LV/EN only (the Stage 5 workspace has its own theme once mounted).

| State | Files |
|---|---|
| List | `list_{1366,1440,1920}_{lv,en}`; search `list_1366_lv_search_{BIK-001,sector76_small,kekava_fixture}_card`; filter `list_1366_lv_filter_not_monitored_LG917`; keyboard focus `list_1366_lv_keyboard_focus` |
| Monitored, Sentinel image (false colour) — BIK-001 | `sector_BIK-001_monitored_image_{1366_lv,1366_en,1440_lv,1920_lv}`; drawer `…_1279_{lv,en}_drawer` |
| Monitored, D4 too small (0.21 ha) — sector 76 | `sector_sector76_monitored_small_1366_{lv,en}` |
| Not monitored — sector 81 (LVM GEO registration) | `sector_sector81_not_monitored_{1366_lv,1366_en,1440_lv,1920_lv,1279_lv,1279_en}` |
| Awaiting first data — sector 81 after a **real** `POST /api/sat-monitoring/areas` on the sandbox copy (HTTP 202, job 3 QUEUED; no worker in the sandbox) | `sector_sector81_awaiting_from_stored_job_1366_{lv,en}`, `list_1366_{lv,en}_filter_awaiting_from_stored_job` |
| Monitored with open events — **Ķekava, test area, not a sector (D3)** | `sector_kekava_fixture_events_1366_{lv,en}`, card in `…_search_kekava_fixture_card` |

Browser checks on the sandbox (shots.js LOG.txt): card → `#sectors/83` → browser Back: **scroll 1039 → 1039, filter
NOT_MONITORED kept**; reload `#sectors` OK; deep-link reload `#sectors/81` opens the sector; `#sectors/999999` → "Sektors nav
atrasts."; **0 console errors** across all runs.

## 4. Findings for the owner / Stage 2

1. **Stage 5 header vs D5.** The Stage 5 workspace header shows one combined "last acquisition" (max of S1/S2, any validity;
   tooltip with both). The card and the sector panel follow D5 (last *valid* S2, S1 separate). Sector 76 shows why it matters:
   last OK S2 = 2026-11-04 with 7.4 % valid pixels; last valid S2 = 2026-10-27. Inside the workspace Stage 5 wins — raise with
   the Stage 5 session if the owner wants D5 there too.
2. **Panel width at 1366.** Panel 320 px + 210 px sidebar → map ≈ 71 % of the content area at 1366, ≈ 73 % at 1440, ≈ 81 % at
   1920 (target 75–80 %). The drawer starts at ≤ 1279 px as specified. Option: drawer up to 1439 px.
3. **"Atvērt Meža kartē" focus.** Meža karte has no sector deep link. Monitored sectors use the existing
   `#forest-map?sat_area={id}`; others open `#forest-map` unfocused. Stage 2 needs a small addition in forest-map.js
   (`#forest-map?sector={id}` + the popup's "Atvērt sektoru"); the index.html tag stays byte-exact.
4. **Ķekava true-colour image is 879 KB** (631×624 px). Lazy-loaded, but at 1,000 sectors many large areas would be heavy. No
   thumbnail pipeline is proposed (Sentinel pipeline is out of scope); measure in Stage 3.
5. **List payload.** 124 KB / 86 cards ≈ 1.45 KB per card (rings thinned to ≤ 64 vertices) → ≈ 1.5 MB at 1,000. Stage 2's
   `/api/sectors/cards` could thin to 32 vertices; to be measured with the 1,000-sector fixture in Stage 3.
6. **Name-keyed data.** The sector page still reads `/api/sectors/{name}` for risks/GPS/photos; duplicate names (S-004 ids
   9/18) get a warning in the panel. Unchanged from Stage 0.
7. **BIK-001 provenance** is "Nav pieejams": it has no `geodata_sources` row and no boundary plan. Correct per stored data.

## 5. Not verified in Stage 1

- The real `SatWorkspace.mount` (does not exist yet; stub shown) and the monitored "backfill in progress" state *inside* the
  workspace (no area with 0 OK acquisitions exists; the awaiting state shown is the queued-job state before an area exists).
- 1,000-sector timings, LVM GEO registration on a copy, Meža karte → sector: Stage 3.
- The full Python suite was not run (only new JS + a Python script that touches no app code); baseline 9 failed / 40 errors.

## 6. Revision 2 — owner decisions D10–D14 (2026-11-18)

Sandbox now runs on **fresh `.backup` copies** `/root/sectors_sandbox/data_20261118` (taken after the first daily run on NEW,
run 9; forest_ai.db sha256 `b05a6b79…`, satellite.db `b727162e…`, integrity ok). Photo/plan folders are symlinks to the live
folders, read-only inside the sandbox namespace. App rebuilt by `tests/e2e/sectors_stage1/build_sandbox.sh` (Stage 5 3068e99 +
this branch). Old copies kept in `data_20261117`.

| Decision | Prototype |
|---|---|
| **D10** one sector page | Every legacy entry (`openSector(name)` from GPS/Risks/Trucks/Timber/Objects tables, old `#sector-{name}` links) redirects to `#sectors/{id}` while `SECTOR_LEGACY_MODULES` is off. The 13-tab bar, KPI row, risk gauge, financial exposure and "Upload sector satellite" are only reachable with the flag on. Nothing deleted (test asserts the legacy markup is still in index.html) |
| **D11** panel | Sektors · Satelīta monitorings (3 timestamps) · Izmaiņas · Riski · Aktivitāte. Aktivitāte = last 5 GPS sessions + counters rendered only when > 0: GPS sesijas, Riski, Kokvedēju atskaites, Kokmateriāli, Komentāri, Foto. "Dati nav pieejami" only when `/api/sectors/{name}` itself fails |
| deep links | The top-level sections have **no sector filter** and Komentāri / Salīdzināšana exist only as per-sector detail views, so each counter opens the **existing** per-sector view alone: `#sectors/{id}/{gps,risks,trucks,timber,comments,compare,photos}` = `detailTab()` with the legacy chrome hidden and a "← {sector}" bar. No code copied. Alternative (sector filter on the 4 top-level sections) available if preferred |
| Foto → Salīdzināšana | **1 click** from the sector page (`#sectors/26` → `#sectors/26/compare`, photo comparison run #1, 30 points); "Visi foto (48)" next to it; Back returns to the sector page |
| **D12** list | cards only, LV/EN; Objects → sectors filter is now cards with an LV/EN banner (no RU table); "Visi sektori" header; "Create sector" hidden |
| **D13** auto-monitoring | proposal + estimate: `docs/SECTORS_AUTO_MONITORING_PROPOSAL.md` — not implemented |
| **D14** archive | preview: `docs/SECTOR_CLEANUP_PREVIEW_20261118.md` (85 rows, 84 archive + BIK-001 keep) — nothing written |

**Screenshots v2** (`/root/sectors_sandbox/screenshots_v2/`, LV, `tests/e2e/sectors_stage1/shots_v2.js`, 0 console errors):
`list_1366_lv`, `list_1920_lv`, `list_1366_lv_object_filter_plan17`, `sector_BIK-001_1366_lv`, `sector_BIK-001_1920_lv`,
`sector_BIK-001_1366_lv_panel_aktivitate`, `sector_BIK-001_1366_lv_foto_salidzinasana`, `sector_76_monitored_small_1366_lv`,
`sector_81_not_monitored_1366_lv`. Checks logged: Foto 1 click → compare; Back → `#sectors/26`; `#sector-BIK-001` →
`#sectors/26`; GPS table sector link → `#sectors/26`; object filter 17 → 5 cards, no RU headers.

JS tests: `node --test tests/test_sectors_cards.js` **8/8 pass** (adds D11 counters and D10/D12 flag assertions).

**Release rule (owner, 2026-11-18):** Sectors Stage 4 ships only with the real `SatWorkspace.mount` or fallback B (full-height
link-through + back link). The stub text ("Stage 5 · SatWorkspace.mount", "Šeit tiek iemontēta…") is sandbox-only; Stage 2
renders fallback B when `mount` is missing, with a test that the stub strings are absent.

**Privacy:** sector id 36's name contains a personal surname. The card fixture is now redacted
(`--redact-name`, same format as Stage 0). The local Stage 1 commits that carried the unredacted name (3f96a41, 435abc4,
15e02b4) were squashed with 4304b5e into one commit before any push (owner, 2026-11-18); no commit on this branch contains it.
No push until the owner confirms the repo is private.
