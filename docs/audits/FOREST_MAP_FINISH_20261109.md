# Forest Map finish for the grant demo, 2026-11-09

| | |
|---|---|
| **Branch** | `feature/forest-map-finish`, from `origin/master` (`f2f3e92`, which contains the audit candidate) |
| **Release** | **prepared, NOT activated**: `releases/forest-api-forest-map-finish-20261109T1023Z` (`geo-948c79b34ed7`) |
| **Production** | untouched by this work (see "Production changed during this task") |
| **Evidence** | `docs/audits/forest-map-finish-20261109/` (JSON/TXT). Screenshots are kept outside git (session scratchpad, `verify_4/*.png`) |

## Overlap with Codex

- **`feature/boundary-plan`** (`/root/wt/boundary-plan`): changes `index.html` (≈ lines 710–735, LVM/VMD
  markup), `assets/lvm-geodata.js`, `vmd-production.js`, `vmd-workflow.css`, `services/geodata/vmd_dataset.py`,
  `vmd_production.py` and their tests.
- **`feature/boundary-plans-20261108`:** carries the production versions of the Forest Map files, unchanged.
- **This branch changes only** `assets/forest-map.js`, `assets/forest-map.css`, `services/geodata/forest_map.py`,
  `services/geodata/nationwide.py` (helpers appended only) and Forest Map tests/docs.
  It makes **no** changes to `index.html`, `api.py` or any LVM/VMD file.

## Production changed during this task (not by me)

1. **07:27 UTC:** Codex's `feature/boundary-plan@fd3d2c6` LVM GEO files were copied **into the live release
   folder** `forest-api-meza-karte-20261107T084300Z`. The changed files were `lvm-geodata.js`,
   `vmd-production.js`, `vmd-workflow.css` and `index.html`.
2. **09:38:36 UTC:** `forest-api` was restarted with a manual `systemctl restart` (`NRestarts=0`). The PID changed
   from 2737889 to 2821886.
3. **10:19 UTC:** the live `index.html` was edited again to hide the Photos, AI, AI Inspector and Satellite
   navigation items, leaving `index.html.backup-20261109-101936` beside it. **This edit is in no git branch.**

**Consequences:**
- Production no longer equals the tag `prod-2026-11-07-meza-karte`. Live now reports `geo-57c305ea4225`.
- **A release built from this branch alone would revert the live LVM GEO changes.** The prepared release is
  therefore the **current live folder plus only the four Forest Map files**.
- `pre-activation-check.sh` refuses activation if the live folder changed after the build.

## Base choice: candidate kept, with one exception

- **The audit candidate (on master) worked on the temp server** (`:8011`): status, inspect, search and selection
  all ran with no JavaScript errors. It is the base for this work.
- **Exception:** the candidate also refactored `nationwide.search()`. That is the cadastral search behind the
  LVM GEO/VMD wizard and registration, which is out of scope here, and the refactor was never deployed.
- **What ships instead:** production's `nationwide.py` byte-for-byte, plus the three helpers the map's inspect
  path needs (`compartment_validation`, `native_parcel_geometry`, `original_wgs84`), appended verbatim
  (commit `6d983d2`: +48 lines, 0 lines changed).
- **Open item:** the `search()` refactor needs its own review with the LVM GEO owner.

## What changed (task items 1–8)

| # | change | where |
|---|---|---|
| 1 | **Click popup**, built from LVM GEO's field semantics (own renderer): Kadastra apzīmējums, Kvartāls, Nogabals, Platība, Datu avots, Avota ID, Kadastra saistība, Ģeometrija, Reģistrācijas iespēja, plus **Select / Add**. **Hover tooltip** (hover-capable devices only, throttled to 80 ms) from tile data: cadastral id · K/N · area | `forest-map.js` `showPopup`, `hover`; tiles now carry `kvart`, `nog`, `area_ha`, `area_declared` |
| 2 | **Boundaries from zoom 13 with no truncation.** Limits are sized at about 2× the nationwide census maximum (967 records / 333 KB input in the densest of 9,312 zoom-13 tiles). Busy server: **bounded queue (10 s)** instead of an instant 503; the client retries 503 twice with backoff. **gzip**; **`immutable` caching for URLs carrying the current dataset version** (`no-cache` otherwise) | `forest_map.py` (`DETAIL_MIN_ZOOM`, `MAX_*`, `WORKER_WAIT_SECONDS`, `get_tile`), `forest-map.js` `loadTile` |
| 3 | **Country zoom:** cells drawn at their **true ~1.3 km size**, shaded by record count, sent as compact arrays. The old 10 km squares and the uniform dots are gone. Hint: "Ierakstu blīvums ~1,3 km šūnās (nav meža platība). Nogabalu robežas redzamas no mēroga 13." No invented data: cells come from the existing overview (bbox centre of each record) | `forest_map.py` `coverage`, `forest-map.js` `drawTile` |
| 4 | **Own sectors:** every sector not drawn is listed with its reason; drawn sectors outside the Latvia envelope are flagged. No sector data changed (see table below) | `forest_map.py` `sectors` (`unmapped`, `outside_latvia`); `forest-map.js` `loadSectors`. Also fixes a candidate bug: the layers panel had no id, so the sector notice was never attached |
| 5 | **Review-only compartments:** a readable reason plus "Ko darīt / Next:", in both the popup and the sidebar (geometry invalid, display repair, boundary not fully inside VZD unit with overlap %, source conflict, spatial-only, unsupported multipart, already registered) | `reviewReason()` |
| 6 | **Registration result:** a dialog listing created sectors (each linked to **Sektori**) and the skipped ones with translated reasons, built from the existing import response | `showResult()` |
| 7 | **i18n:** LV complete. Server texts replaced by client strings (notice codes, known server reasons). Number formatting by language. Localised zoom-control titles and Refresh label. No absolute server paths in the details panel | `forest-map.js`; `forest_map.py` (`notice_code`, `_without_server_paths`) |
| 8 | **Console errors / failed requests:** none found in the final run | — |

**Own sectors (production DB copy taken today: 47 sectors, 39 drawn)**

The 8 not drawn, each with its reason shown in the layer list:

| sector(s) | reason shown |
|---|---|
| A-004, S-004 (id 18), Sectors 124, Ы-13223, S- 123 | "nav robežas" (no boundary) |
| S-001/S-002 Plieksana zeme | "nederīga robeža (pašķrustojas)" (invalid, self-intersecting boundary) |
| S-003 Plieksana zeme | "ārpus Latvijas, pārbaudiet koordinātas" (outside Latvia; check coordinates) |

**On "draw those with valid geometry":** the only one of the 8 with a valid polygon is S-003 Plieksana zeme.
It lies about 500 km away in Russia, from a bad OCR reading, so it is listed rather than drawn. The drawn
sector S-004 (id 9), which is also in Russia, is flagged "ārpus Latvijas teritorijas" (outside Latvia).

## Before / after (same scripted browser run on the temp server; `perf_before.json`, `perf_after.json`)

| scenario | requests | transfer | tile latency p50 | map idle | long tasks |
|---|---|---|---|---|---|
| Country view, before | 12 | 136.5 KB | 203 ms | 1.81 s | 296 ms |
| Country view, **after** | 12 | **61.5 KB** | **71 ms** | **1.12 s** | **0 ms** |
| Zoom-13 view (Gauja), before | 16 | 3,120 KB | 2,551 ms | 14.7 s | 630 ms |
| Zoom-13 view, **after** | 16 | **702 KB** (gzip) | **1,377 ms** | **7.6 s** | **0 ms** |
| 5 pans at zoom 13, before | 28 | 4,388 KB | 1,502 ms | 11.9 s | 710 ms |
| 5 pans at zoom 13, **after** | 28 | **1,057 KB** | 1,462 ms | 10.9 s | 57 ms |
| Zoom-12 view, before | 16 | 214 KB | 654 ms | 3.9 s | 0 ms |
| Zoom-12 view, **after** | 16 | **12.7 KB** | 154 ms | 0.7 s | 66 ms |

- **Requests per pan are unchanged** (28 for 5 pans). The tile layer already fetches only when the map stops
  moving (`updateWhenIdle`), so there was nothing further to debounce.
- **Canvas vs SVG** (`svg_vs_canvas.json`), measured on a 342-compartment tile:
  - `L.geoJSON` with SVG renderer: 74 ms median;
  - `L.geoJSON` with Canvas renderer: 79 ms;
  - **the existing custom canvas tiles: 14 ms per tile.**

  The existing renderer is kept.
- **Server limit:** the 2-core host still bounds zoom-13 throughput, at about 1–2.5 s per uncached dense tile.
  The queue now delays tiles instead of dropping them.

## Zoom × completeness

`render_after_summary.txt`: same 50 sample points and zooms 7–17 as the audit, on the staging tree. A census of
all 9,312 occupied zoom-13 tiles bounds the limits: the maximum is 967 records against a limit of 2,000.

| zoom | what is drawn | compartments drawn individually |
|---|---|---|
| 4–12 | record-density cells at true ~1.3 km size, plus a hint to zoom to 13 | none, by design (median compartment is under 4 px at zoom 12) |
| 13–19 | full compartment outlines | **100% in every sampled tile**: at zoom 13, 50/50 tiles detailed, minimum 100%, largest tile 802 compartments, max 412 KB raw / p50 0.09 s. No tile in Latvia exceeds the limits (census) |

Before this change the same sample had 2 of 50 zoom-13 tiles fall back (0% each). Nationwide, 17% of compartments at zoom 13 and 97–99.8% at zooms 11–12 were silently replaced by cells
(see the 2026-11-09 audit).

## Tests run

| test | result |
|---|---|
| `pytest tests/test_forest_map.py tests/test_nationwide_geodata.py tests/test_geodata.py` | **84 passed**. Without the ingest-only `py7zr` package, the 10 `test_nationwide_geodata` tests error with `ModuleNotFoundError: No module named 'py7zr'`; with it installed into a scratch folder, all pass |
| New backend tests (`test_forest_map.py`, 22 in total) | cover: density cells never enlarged; 750 records in one zoom-13 tile all drawn (old limit 600); missing area → `null`, never 0; gzip + version-keyed cache; no server paths; notice codes; every hidden sector has a reason; bounded worker queue |
| Browser acceptance on the staging tree (`verify_browser.py`, headless Chromium) | **22/22 pass**. Covers: density cells at country zoom with the LV hint; zoom 13 with no fallback in Gauja, the densest tile and Riga; no tile errors; hover tooltip; popup with all LVM GEO fields; Select/Add; review reasons for a repaired and an invalid record; 8 hidden sectors listed with reasons; registration result dialog and Sektori link (on the `/tmp` DB copy); LV page without English UI text; EN page without Latvian UI text; `#lvm-geodata` without console errors; no console errors, failed requests or HTTP errors |
| `#lvm-geodata` equals production | **Holds by construction.** The release differs from the live folder only in the four Forest Map files, and `nationwide.search()` is byte-identical to production |

## Release: prepared, NOT activated

```sh
REL=/root/forest_ai/releases/forest-api-forest-map-finish-20261109T1023Z
# 0. Guard: must print "OK". If NOT OK, the live folder changed after the build; rebuild the release.
$REL/pre-activation-check.sh
# 1. Back up the current unit configuration (the database is not touched; no migrations).
B=/root/forest_ai/data/backups/forest_map_finish_$(date -u +%Y%m%dT%H%MZ); install -d -m 0700 "$B"
cp -p /etc/systemd/system/forest-api.service.d/*.conf "$B"/
# 2. Activate: a later drop-in overrides WorkingDirectory. ExecStart and the env stay as they are.
printf '[Service]\nWorkingDirectory=%s\n' "$REL" > /etc/systemd/system/forest-api.service.d/60-forest-map-finish-release.conf
systemctl daemon-reload && systemctl restart forest-api
# 3. Verify (within 1 minute)
systemctl is-active forest-api
readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd      # expect $REL
curl -su "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" http://127.0.0.1:8000/api/deployment                 # expect geo-948c79b34ed7
curl -su "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/geodata/forest-map/status   # expect 200
```

**Rollback (under 1 minute, no data to restore):**

```sh
rm /etc/systemd/system/forest-api.service.d/60-forest-map-finish-release.conf
systemctl daemon-reload && systemctl restart forest-api
readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd      # expect …/forest-api-meza-karte-20261107T084300Z
```

## What was NOT verified

- **Real touch devices:** the tooltip is disabled where `(hover: hover)` is false; only desktop Chromium was
  tested.
- **More than one concurrent user on the new code:** the bounded queue is unit-tested; the multi-user load
  test from the audit was not rerun. The 2-core host remains the throughput limit.
- **Long-term caching:** cache headers were checked in tests only. A long browser session across a dataset
  publication was not tested.
- **Registration against the production database:** registration was exercised only on a `/tmp` copy.
