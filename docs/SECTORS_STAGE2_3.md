# Sectors — Stage 2 (implementation) + Stage 3 (tests), 2026-11-18

Owner: "Stage 1: approved with fixes F1–F3, then proceed to Stage 2 + Stage 3 on feature/sectors-workspace". D14 not applied,
D13 not enabled, nothing deployed, no production DB written. Branch base: production tag
`prod-2026-11-18-remove-integrations-page` (b86ebf4 = the live :8000 release `…remove-integrations-page-20261118T0532Z`,
0 drift) merged in (pushed history not rewritten).

**Sequencing note:** Stage 5 (satellite workspace) is still unreleased (worktree at c8bbe79, sandbox only). Stage 2 went
ahead on the owner's instruction without touching Stage 5's files (`assets/sat-workspace.*`, `satellite_monitoring/*`).
So in this release: no `SatWorkspace.mount` → fallback B; no worst-event colour dots on cards (the colour function is
imported from Stage 5, never re-implemented); "Pēdējā veiksmīgā analīze" shows "Nav pieejams" because the production
satellite API (b86ebf4) has no `last_successful_analysis_utc` yet — all three light up when Stage 5 is released.

## 1. What changed

| Area | Files |
|---|---|
| `GET /api/sectors/cards`, `GET /api/sectors/cards/{id}` (global Basic Auth; `/{id}` also returns archived sectors; 404 unknown) | api.py, **services/sector_cards.py** (new, read-only: forest_ai.db + satellite.db `mode=ro`) |
| Archive filter **only when `sectors.archived_at` exists** (no migration): `/api/sectors`, `/api/objects`, cards list, Meža karte sectors | api.py `_sectors_not_archived`, services/sector_cards.py, services/geodata/forest_map.py `sectors()` |
| `SECTOR_LEGACY_MODULES` env → `window.SECTOR_LEGACY_MODULES` (default off) | api.py `serve_index` |
| Meža karte: sector popup "Atvērt sektoru →" `#sectors/{id}`; `#forest-map?sector={id}` focuses the sector | assets/forest-map.js (`focusSector`), index.html router; tag `forest-map.js?v=20261107` byte-exact |
| F1/F2 detection note: stored `area_ha` < `meta.detection_min_ha` (env `DETECTION_MIN_HA`, default 0.5), only Monitorēts / Gaida pirmos datus | services/sector_cards.py, assets/sectors-cards.js `detectionNote` |
| Archived id by direct link → card via `/cards/{id}` + "Arhivēts" chip; satellite.db unavailable → status "Nav pieejams" (never a false "Netiek monitorēts") | assets/sectors-cards.js |
| Panel: "Analīze nav veikta" only when the API says so; Riga + UTC times without the Stage 5 module | assets/sectors-cards.js |
| Fixture builder now runs the same code as the API (+ fixture-only redaction) | scripts/sector_cards_fixture.py |

## 2. F3 — identifier formatting code path (production shows the full number)

1. `services/sector_cards.py::identifier(src)` returns `geodata_sources.source_properties.kadastrs` **as stored**.
2. `GET /api/sectors/cards` → `cards()` → `build_sectors()` → `identifier()` — no masking anywhere in this path.
3. `assets/sectors-cards.js::identifierText(card)` joins `identifier.cadastre` + "kv. {kvart} nog. {nog}" — no masking.
4. Masking (`60…(11)`) exists only in `scripts/fixture_redaction.py`, used only by `scripts/sector_cards_fixture.py` for
   committed fixtures. Test `test_identifier_is_the_full_stored_number_F3` asserts the API returns the full stored 11-digit number (synthetic test value) and that
   neither api.py, services/sector_cards.py nor assets/sectors-cards.js references the redaction code or "…(".
   Browser check: LG917 header shows the full 11-digit number.

## 3. Test report

| Suite | Result |
|---|---|
| Python, full (`pytest tests`) | **9 failed / 455 passed / 5 skipped / 40 errors** — failure set **identical** (49 ids, diffed) to a clean b86ebf4 checkout (9 / 448 / 5 / 40). +7 = the new tests |
| Python, new `tests/test_sector_cards_api.py` | **7/7**: auth (401 without/wrong credentials) on both new routes; stored values (last *valid* S2, S1 separate, superseded events not counted, D7 LVM GEO link, stopped area, queued job, NULL area stays NULL); F3 full identifier; satellite.db missing → unknown; archive filter only with the column (cards, `/api/sectors`, `/api/objects`; archived id still opens, 404 unknown); Meža karte filter; legacy flag injection |
| JS, all (`node --test tests/*.js`) | **105/105** (92 existing + 13 Sectors: status, D4 preview edge 639/640 m, NULL≠0, suspected vs confirmed, worst colour imported, routes, D11 counters, D10/D12 flag, R3 area, **F1/F2** T-56 0.21 ha → note / LG917 1.08 ha → no note / not monitored → never, no developer text, Riga+UTC, analysis wording) |
| Browser, release-candidate sandbox (`tests/e2e/sectors_stage1/stage3_browser.js`) | **22/22 PASS**, 1 console error = the deliberate 404 of the "unknown id" check |
| LVM GEO registration on a copy (§9, `stage3_api.py`) | cadastral search 200 → import of one READY compartment → **1 sector**; identical second submit → **no duplicate**; card ring, Meža karte polygon, detail boundary **coordinate-identical** to the stored boundary; in Objekti. LVM GEO files unchanged |
| Geometry sector ↔ satellite area | sector 76 = area 4 (Δ 0.0°); BIK-001 = area 1 except GeoJSON's closing vertex; the newly registered compartment = area 3 (Δ 0.0°, D7 link → "Monitorēts") |
| 1,000 sectors (generated on a DB copy) | `cards()` 47–138 ms, payload 846 KB; browser: first page 0.8–2.1 s incl. page load, 100 per page, search 0.17–0.20 s, filter 0.16–0.33 s. At 85 real sectors: `/api/sectors/cards` 66 ms vs old `/api/sectors` 976 ms |

Browser checks (all PASS): list from one `/api/sectors/cards` request; no RU headers / risk score; F1/F2 card notes (76 yes,
81 no, 16 small-but-unmonitored no); Back keeps scroll (800→800) + filter; BIK-001 fallback B with the Sentinel overlay
"Sentinel-2 · 2026-11-06 · viltus krāsas"; no developer text; no duplicated top-bar title; Foto → photo comparison in 1
click; T-56 note next to Izmaiņas and no image (D4); "Atvērt Meža kartē" → Meža karte zoomed on the sector with the popup;
popup "Atvērt sektoru" → `#sectors/76`; LG917 not monitored, no note, full cadastral number; deep-link reload; legacy
`#sector-BIK-001` → `#sectors/26`; unknown id → "Sektors nav atrasts"; add to monitoring → 202 → "Gaida pirmos datus"
after reload (stored job); 1,000-sector pagination.

Screenshots (not in git): `/root/sectors_sandbox/screenshots_stage3/` — `list_1366_lv`, `sector_BIK-001_1366_lv`,
`sector_BIK-001_1920_lv`, `sector_T-56_1366_lv`, `sector_LG917_1366_lv`, `forest_map_focus_T-56_1366_lv`.

## 4. Not verified / open

- Real `SatWorkspace.mount`, worst-colour dots and "last successful analysis" (Stage 5 not released).
- Archive filter in a browser (Python tests cover it; no `archived_at` column exists anywhere — D14 not applied).
- The sandbox writes (one registered sector, two queued ADD_AREA jobs) exist only in the sandbox copies.
- Telegram bot sector list and GPS classification are not archive-filtered (outside the owner's list for this step).
- Stage 4 (release) not started: needs "approved release", a release folder + drop-in per DEPLOY_RELEASES.md, and the
  docs updates (CURRENT_STATUS, CHANGELOG, KNOWN_BUGS, API.md).
