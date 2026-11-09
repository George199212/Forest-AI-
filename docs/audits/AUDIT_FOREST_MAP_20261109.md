# Forest Map (#forest-map) bug and completeness audit, 2026-11-09

This audit is read-only. No code changed, and production was not touched. `forest-api` kept
PID 2737889 (running since 2026-11-07 09:16 UTC) before and after the audit.

| | |
|---|---|
| **Production code** | tag `prod-2026-11-07-meza-karte`. The live `:8000` and the temporary audit server both report `geo-c5801dc23be5` / backend `552c46ae547b` |
| **Candidate** | `origin/master` (commits `8f715b0`, `81f96fb`). Reports `geo-e05af6cfb2c1`. Not deployed |
| **Dataset** | `15b2ef2b…eb13a`. National indexes opened `mode=ro`. Operational DB: a `/tmp` backup copy |
| **Temp servers** | `127.0.0.1:8011` (production code), then `127.0.0.1:8012` (candidate), one at a time, `nice 10`, no AI or Telegram credentials. Both stopped |
| **Evidence** | `docs/audits/forest-map-20261109/` (JSON/TXT plus the scripts that produced them). Browser screenshots were taken but not committed (evidence-image rule) |

## The answer

**Are all 3,063,409 compartments shown at every zoom? No.**

| map zoom | compartments drawn individually (nationwide) | what the user sees instead | evidence |
|---|---|---|---|
| 4–10 (default view is 7) | **0** (0%) | Square "presence cells" covering 98–250% of Latvia's area, sea included (candidate: a uniform dot lattice) | `presence_cells.txt`, `render_*_summary.txt` |
| 11 | ≈ 0.2%. 611 of 654 occupied tiles fall back; 3,056,494 compartments centred in them | Presence cells | `census.json` |
| 12 | ≈ 3.1%. 2,076 of 2,428 tiles fall back; 2,968,390 centred in them | Mostly presence cells, a few detailed tiles | `census.json` |
| 13 | ≈ 83%. 857 of 9,312 tiles fall back; **520,839 (17.0%) not drawn** | A patchwork: detailed tiles next to cell tiles | `census.json`, `render_prod_summary.txt` |
| 14–19 | **100%**. No tile exceeds the limits: densest zoom-14 tile has 343 compartments, 208 KB, 0.29 s | Full outlines | `census.json`, `z14_worst.txt` |

- **How the "not drawn" counts were computed:** compartments whose bounding-box centre lies
  in a tile whose index count exceeds `MAX_FEATURES=600`. That is exactly the server's
  fallback rule (`forest_map.py:95`). A compartment crossing into a neighbouring detailed
  tile can show partially there.
- **Where it happens:** in the 50-point sample, every dense-forest point (13/13) fell back
  at zooms 11 and 12, and 2/13 still fell back at zoom 13. In sparse farmland, Riga and on
  the coast, most tiles render from zoom 12 or 13.
- **What happens when a tile renders in detail:** it is complete. 0 of 448 sampled detail
  tiles missed a compartment that intersects the tile (`render_prod.json`).
- **A second, independent cause of missing compartments at every zoom is HTTP 503**
  (BUG-02).
  - 2 concurrent users had 38 of 48 tiles rejected (79%); 5 users had 114 of 120 (95%).
  - A single browser session got 31 × 503 while zooming.
  - Rejected tiles stay blank.
- **Physical limit:** at zoom 7 the median compartment (7,222 m²) is 0.13 px across. It
  reaches 1 px at zoom 10 and 8 px at zoom 13. "Every compartment at every zoom" can only
  mean the *area* they cover is drawn exactly at low zooms. Individual boundaries become
  legible from about zoom 13.

## 1. Architecture trace

```
index.html #sec-forest-map  ── assets/forest-map.js (Leaflet 1.9.4, canvas GridLayer, 256 px tiles)
   │ GET /api/geodata/forest-map/status                    once: dataset_version, counts
   │ GET /api/geodata/forest-map/tiles/{forest|parcels}/{z}/{x}/{y}?v=<version>   per tile, max 3 in flight (client queue)
   │ GET /api/geodata/forest-map/identify?lat&lon&zoom      click
   │ GET /api/geodata/forest-map/feature?id=                inspect
   │ GET /api/geodata/forest-map/sectors                    own-sector overlay
   │ GET /api/geodata/vmd/cadastre?kadastrs=                cadastral search
   │ POST /api/geodata/vmd/import-selected                  registration (dry run, then confirm)
   ▼
services/geodata/forest_map.py  (router registered in api.py)
   ├─ nationwide.release() → $FOREST_GEODATA_MANIFEST = data/geodata/nationwide/active.json
   ├─ forest: releases/20261106/compartments.sqlite  (8.7 GB; rtree spatial_index on WGS84 bbox)
   ├─ parcels: releases/20261106/parcels.sqlite       (1.4 GB; VZD)
   └─ overview: data/geodata/forest-map/<version>/overview.npz (35,621 zoom-14 cells, built by scripts/build_forest_map_overview.py)
```

### Limits and what happens when one is hit (production)

| limit | value | where | effect when hit | flagged in UI? |
|---|---|---|---|---|
| forest zoom ≤ 10 | always cells | `forest_map.py:84` | No compartments at all | Badge "Generalized forest presence cells…" |
| `MAX_FEATURES` | 600 bbox hits | `:95` | **Whole tile** replaced by cells | Badge only. It is the same badge as zoom ≤ 10, with no count of what is missing |
| `MAX_INPUT_BYTES` | 4,000,000 B of WKB | `:95` | Whole tile → cells | Same badge |
| query/geometry deadline | 2.5 s + 2.5 s | `:91`, `:101` | Whole tile → cells | Same badge |
| vertex budget | 20,000 after simplify | `:108` | Whole tile → cells | Same badge |
| `MAX_TILE_BYTES` | 400,000 B response | `:115` | Whole tile → cells | Same badge |
| simplified geometry invalid | per feature | `:106` | **That feature silently dropped** | No (0 cases in the sample) |
| worker slots | `BoundedSemaphore(3)`, acquire timeout 0.05 s | `:31`, `:126` | HTTP 503 | Generic "Some tiles failed…" status; **tile stays blank** |
| parcels | zoom < 14 | `:85` | No parcels | Badge text |
| identify | zoom < 11 or > 128 candidates within 6 px | `:165`, `:169` | No inspection | Notice (English only) |
| server cache | 24 MB / 256 tiles LRU, key `(version, layer, z, x, y)` | `:24`, `:122` | Eviction only | n/a |
| HTTP cache | `private, max-age=120`, URL carries `?v=<version>` | `:225` | n/a | n/a |
| simplification tolerance | `(tile width / 256) × 1.2` (zoom < 14), × 0.3 (zoom 14–16), none at 17+ | `:99`, `:105` | n/a | Badge says "display geometry only" |

**Tile edges, axis order, cache.**
- Features are clipped to each tile (`:103`) and drawn per canvas tile, so nothing is
  duplicated. In the sample, no compartment intersecting a detailed tile was missing.
- Axis order and CRS are correct (see section 5). The antimeridian does not apply to Latvia.
- The server cache and the request URL include the dataset version, so a published new
  version never serves old tiles.
- **However** the client keeps the old `s.version`. "↻ Refresh" calls `load()`, which
  returns early when the map exists (`forest-map.js:51`, `if(s.map&&s.metadata)`) and never
  re-reads `/status`. After a catalogue publication every tile then fails its version check
  until a full page reload (BUG-11). This was derived from the code, not tested: testing it
  would require publishing a dataset.

## 2. Catalogue completeness (data)

Source: one read-only pass over all rows, 74 s (`catalogue_stats.json`). The `files`,
`rejections` and `duplicate_sources` tables were also read.

| VMD region | indexed | shapefile layers | source rows (`files.total_rows`) | rejected | duplicates |
|---|---|---|---|---|---|
| Austrumu | 570,975 | 5 | 570,975 | 0 | 0 |
| Centra | 513,776 | 5 | 513,776 | 0 | 0 |
| Dienvidu | 553,644 | 5 | 553,644 | 0 | 0 |
| Kurzemes | 645,334 | 5 | 645,334 | 0 | 0 |
| Vidzemes | 779,680 | 6 | 779,680 | 0 | 0 |
| **Total** | **3,063,409** | 26 | 3,063,409 | 0 | 0 |

All 26 layers are marked `complete=1`. The `rejections` and `duplicate_sources` tables are
empty for VMD. The catalogue is **complete against its source.** (VZD parcels: 1,055,666
indexed out of 1,059,766 source features; 4,100 identical duplicate source rows removed.)

**Land category (`zkat`).** Code names are from VMD's official classifier
(`gis.vmd.gov.lv/Public/GetClasificators`, sheet `ZKAT_klasifikators`).

| zkat | VMD name | records | area ha | importable=1 |
|---|---|---|---|---|
| 10 | Mežaudze | 2,799,772 | 3,110,642 | 2,776,393 |
| 14 | Izcirtums | 156,480 | 139,845 | 155,441 |
| 12 | Iznīkusi mežaudze | 2,505 | 2,659 | 2,485 |
| 16 | Sēklu ieguves plantācija | 173 | 945 | 166 |
| 31 | Meža lauce | 31,083 | 13,835 | 30,874 |
| 22 | Zāļu purvs | 20,455 | 28,018 | 19,989 |
| 41 | Pārplūstošs klajums | 19,986 | 19,377 | 19,751 |
| 32 | Meža dzīvnieku barošanas lauce | 11,216 | 8,803 | 11,091 |
| 42 | Bebru applūdinājums | 8,139 | 8,662 | 7,996 |
| 21 | Sūnu purvs | 7,388 | 124,926 | 6,879 |
| 23 | Pārejas purvs | 3,819 | 11,151 | 3,704 |
| 34 | Smiltājs | 1,073 | 834 | 1,061 |
| 542 | Rekultivēta zeme | 874 | 8,165 | 842 |
| 33 | Virsājs | 172 | 2,934 | 159 |
| 544 | Rekreācijas platība | 159 | 73 | 152 |
| 543 | Kokmateriālu krautuves vieta | 115 | 26 | 114 |

- **Categories 10/12/14/16** (stands, dead stands, clear-cuts, seed orchards):
  2,958,930 records, 3,254,092 ha.
- **All other categories** (bogs, glades, heath, sand, flooded areas, reclaimed land, timber
  yards, recreation areas): 104,479 records, 226,803 ha.
- **The map shows every category identically:** there is no `zkat` filter in
  `forest_map.py`, the legend has a single "Available" colour, and the inspect panel labels
  the area "Forest area". Which categories should count as "forest" is a product decision.
  The data supports styling them separately (BUG-08).

**Geometry:**
- 3,061,686 valid, 1,723 invalid (`geometry_valid=0`).
- 2,152 with a display repair (`repair`), so 429 repaired records are valid.
- 26,312 records have `importable=0`.
- 413 have `nog_plat = 0`; none are NULL.

## 3. Rendering completeness (sample)

**Method** (`scripts/render_audit.py`):
- 50 points covering all 5 regions, by type: 13 dense forest, 16 sparse or farmland,
  9 coastal, 6 border, 4 Riga, 2 open water.
- Zooms 7–17, giving 448 distinct tiles, each requested exactly as the frontend requests it.
- **Ground truth:** every index row whose stored geometry intersects the tile with positive
  area, for tiles with ≤ 20,000 bbox hits.

| zoom | tiles | detailed | fell back to cells | completeness min / median | response bytes p50 / max | latency p50 / max |
|---|---|---|---|---|---|---|
| 7 | 6 | 0 | 6 | 0% / 0% | 22.7 KB / 67 KB | 0.03 / 0.14 s |
| 8 | 16 | 0 | 16 | 0 / 0 | 48 KB / 74 KB | 0.05 / 0.10 |
| 9 | 33 | 0 | 33 | 0 / 0 | 65 KB / 75 KB | 0.07 / 0.23 |
| 10 | 45 | 0 | 45 | 0 / 0 | 73 KB / 76 KB | 0.07 / 0.22 |
| 11 | 48 | 4 | 44 | 0 / 0 | 18 KB / 216 KB | 0.13 / 0.40 |
| 12 | 50 | 21 | 29 | 0 / 0 | 5 KB / 233 KB | 0.03 / 0.27 |
| 13 | 50 | 48 | 2 | 0 / **100** | 72 KB / 272 KB | 0.08 / 0.34 |
| 14–17 | 200 | 200 | 0 | **100 / 100** | ≤ 139 KB | ≤ 0.11 s |

- **First zoom that is 100% complete in every sampled tile: 14.** The nationwide census
  confirms this: 0 of 35,621 zoom-14 tiles exceed the limit.
- **Every fallback tile had more than 600 bbox hits** (minimum 635, maximum 9,285). So in
  practice the count rule is the only trigger that fires.
- **The candidate is identical** in completeness at every zoom (`render_cand_summary.txt`).

## 4. Presence-cell layer (S1)

- **How cells are built:** `scripts/build_forest_map_overview.py` takes the **centre of each
  compartment's WGS84 bounding box** and counts these per zoom-14 cell, giving 35,621
  occupied cells for 3,063,409 records.
- **How they are drawn:** at map zoom z, cells are aggregated to zoom `min(14, z+4)`
  (`forest_map.py:55`). Each occupied cell is drawn as the **whole cell square**
  (`:70-72`), and the frontend fills every cell with one colour, `rgba(82,169,105,.38)`,
  ignoring `compartment_count` (`forest-map.js:34`).
- **Why it covers water and farmland:** a 10 km cell (zoom 11, drawn at map zoom 7) is
  "occupied" if a single compartment centre lies in it. Coastal cells therefore extend over
  the sea, and farmland cells over fields.

| map zoom | cell zoom | occupied cells | area drawn | % of Latvia (64,589 km²) |
|---|---|---|---|---|
| 6 | 10 | 190 | 86,794 km² | 134% |
| **7 (default)** | 11 | 654 | **74,678 km²** | **116%** |
| 8 | 12 | 2,428 | 69,301 km² | 107% |
| 10 | 14 | 35,621 | 63,533 km² | 98% |

Real compartment area is 34,809 km², 54% of Latvia. **The layer does not reflect forest
density or shape at all:**
- the median cell at map zoom 7 holds 5,039 compartments;
- only 5 of 654 cells hold 5 or fewer;
- every cell is drawn identically.

**Candidate:** each cell becomes a point at the cell centre, with radius
`min(9, 4 + log2(count))` px. That gives a regular lattice in which almost every dot is at
the 9 px maximum. It removes the "blanket", but **still shows neither forest shape nor
density**. It only partially fixes S1 (screenshot seen, not committed).

## 5. Positional accuracy

- **20 random compartments** (seed 20261109, all 5 regions; `position_prod.json`):
  - The source native EPSG:10306 geometry was transformed with pyproj to EPSG:4326.
  - Stored display geometry vs pyproj: maximum Hausdorff distance 1e-9°, which is under
    1 mm.
  - API `/feature` geometry vs pyproj: **0.000 m maximum**.
  - **No CRS or axis error in the national map.**
- **5 compartments against their VZD parcel** (`vzd_spotcheck.txt`, native EPSG:10306
  geometries): 4 lie 100.000% inside their own cadastral parcel, and 1 lies 99.987% inside
  (0.4 m² outside).
- **LVM GEO WMS:** not checked. `geoserver.lvmgeo.lv` timed out from the VPS (HTTP 000 after
  15 s), consistent with the earlier diagnosis that it is unavailable.

## 6. Own sectors (S3: "13/21")

From `sectors_status.txt`, computed with production's own overlay logic on a `/tmp` DB copy.
The geometry source comes from the `boundary_plan_id`, `pixel_boundary_json` and
`geodata_sources` columns.

| id | name | geometry source | status in overlay | shown | location check |
|---|---|---|---|---|---|
| 1 | A-004 | none | no boundary, no centre | **no** | — |
| 2–5 | A-005 … A-008 | manual 4-point rectangle | valid | yes | Riga / Ogre / Sigulda / Tukums area |
| 9 | S-004 | 13-point polygon, no plan/provenance | valid | **yes, but wrong** | **58.868°N 28.714°E, in Russia.** Passes the coarse 55–59°N / 20–29°E check (`forest_map.py:194`) |
| 12, 14 | S-001/S-003 — Mūrnieku Jāņa | boundary-plan OCR (plan 16) | valid | **yes, about 174 km off** | Stored at 56.259°N 26.446°E. pyproj on the plan's own LKS-92 points gives **56.692°N 23.708°E**: the legacy `lks92_to_wgs84` error (P0 #1, `api.py:1105`) |
| 13 | S-002 — Mūrnieku Jāņa | OCR (plan 16) | invalid boundary (self-intersection) | centre marker only | same 174 km error |
| 15, 16 | S-001/S-002 — Plieksana zeme | OCR (plan 17) | invalid (self-intersection), centre outside | **no** | about 58.90°N 32.74°E, Russia |
| 17 | S-003 — Plieksana zeme | OCR (plan 17) | outside map extent | **no** | about 58.90°N 32.74°E. The plan's OCR coordinates (Y ≈ 951,163) lie outside the valid LKS-92 range; garbage OCR that was not rejected |
| 18–21 | S-004, Sectors 124, Ы-13223, S- 123 | OCR pixel boundary only, never georeferenced | no boundary, no centre | **no** | — |
| 26 | BIK-001 | 4-point rectangle | valid | yes | Riga |
| 30–33 | VMD 40940020002 … | VMD import (local / open data) | valid | yes | Bauska municipality, correct |

**The 8 hidden sectors:** 5 have no geometry at all (ids 1, 18, 19, 20, 21), and 3 have
OCR coordinates far outside Latvia (15, 16, 17). Additionally **4 sectors are shown in the
wrong place**: 12, 13 and 14 are about 174 km off, and 9 is in Russia. None of this is
specific to the Forest Map; the whole dashboard reads the same sector rows.

## 7. Interaction (headless Chromium against the temp server, `browser_*_log.json`)

- **Click → details (production):** fields shown:
  - cadastral number, VMD ID, municipality, parish;
  - "Forest area" in ha;
  - source geometry status and import eligibility.

  Attributes missing from the panel: `zkat` (land category), quarter/compartment
  (`kvart`/`nog`), species and age. Area handling: where `nog_plat = 0` (413 records) the
  API **silently substitutes** the geometric area (`vmd_dataset.py:125`), without marking
  that the value is computed. A missing value never shows as 0. The candidate adds
  quarter/compartment, source layer and record, a cadastral check and a geometry section.
- **Candidate:** the details panel shows an **absolute server file path**
  (`/root/forest_ai/data/geodata/…/KKParcel.shp`) as "VZD avots" (BUG-12).
- **Selection and Import as Sector:** "Select" and "Add" are enabled only when the server
  marks the feature eligible. That requires:
  - `importable`, `geometry_valid` and no `repair`;
  - the VZD parcel validation allowing registration;
  - the source attribute verified;
  - no existing sector.

  Selection works (1 compartment, 2.65 ha). "Import" opens a dry-run preview per
  cadastral number, and confirming is blocked when any item fails. Registration rereads
  full source records (`/api/geodata/vmd/import-selected`); display geometry is never used.
- **Search:**
  - Cadastral search for 40940020002 found 10 compartments (7.99 ha).
  - Coordinates outside Latvia are rejected.
  - "All Latvia" works.
  - "↻ Refresh" redraws the map but does not re-read the dataset version (BUG-11).
- **Console and network:** production 31 × HTTP 503 on tiles and 35 aborted tile requests;
  candidate 22 × 503. No JavaScript exceptions.

## 8. Performance and load (temp server, 2 vCPU / 3.9 GB VPS, `load_prod.json`)

| scenario | tiles | transfer | wall time | server CPU | server RSS | result |
|---|---|---|---|---|---|---|
| Pan west→east across Latvia, zoom 10, 1366×860 view | 108 | 5.3 MB | 6.2 s | 7.1 s | 127 → 133 MB | 104 tiles are cells, 4 detailed |
| Same pan, zoom 13 | 696 | **80.8 MB** (uncompressed) | 97.5 s | **114 s** (more than one core) | 133 → 155 MB | 646 detailed, 50 cells |
| 1 user, cold zoom-13 view | 24 | — | — | — | — | 24/24 OK |
| **2 users** at once, zoom 13 | 48 | — | — | — | — | **38 × 503 (79%)** |
| **5 users** at once, zoom 13 | 120 | — | ~1.6 s | — | ≤ 161 MB | **114 × 503 (95%)** |

- **No compression:** responses carry no `Content-Encoding` (BUG-10). A 160 KB tile would
  gzip to about 20%.
- **Candidate:** 2 users gave 13 × 503 out of 48 (`load_two_users_cand.txt`). The same
  semaphore is in place.

## 9. i18n (S4)

- **Production chooses the language from `<html lang>`** (`forest-map.js:51`). `:8000` has
  no `UI_LANGUAGE`, so it serves `lang="en"` (`api.py:603`). The Forest Map therefore opens
  in English, while the LVM GEO / VMD wizard and several server messages are Latvian-only.
- **The EN/LV dictionaries are complete:** 67/67 keys in production, 113/113 in the
  candidate, no missing keys.
- **Untranslated or mixed text found:**
  - **Server notices, production:** all English, shown unchanged in LV mode. Examples:
    "Zoom in to inspect individual compartments.", "Dense location; zoom in to inspect.",
    "Map is busy; retry this tile", "Forest compartment not found" (`forest_map.py:122-231`).
  - **Server notices, candidate:** at least the presence-layer notice is Latvian (verified);
    the HTTP error texts (`HTTPException` details) are still English.
  - **Cadastral search:** returns a Latvian `search_message` ("Atrasti VMD nogabali…") inside
    the English UI.
  - **Hard-coded English:** `aria-label` "Zoom in"/"Zoom out" (Leaflet), "Tiles © Esri", the
    selector label "Language / Valoda".
  - **Top-bar button:** "↻ Refresh" is English on every page except LVM GEO
    (`index.html:921`).
  - **Dashboard navigation:** English (Overview, Objects, Sectors…).
  - **Candidate number formatting:** mixed in one view ("3 063 409" next to "3,063,409").
- **Switching:** the selector rebuilds the map at the same centre and zoom. It works in both
  directions.
- **Candidate default:** LV regardless of `<html lang>`.

## 10. Bugs

Severity: **P0** = data shown wrong or missing; **P1** = misleading UI or broken action;
**P2** = cosmetic or minor.

| ID | sev | summary | repro | expected / actual | location | fixed by candidate |
|---|---|---|---|---|---|---|
| BUG-01 | **P0** | All-or-nothing fallback hides compartments at zoom 11–13 | Open #forest-map, go to 57.25, 25.10 and zoom 11, then 12, then 13 | Expected: all compartments. Actual: 99.8% / 96.9% / 17.0% of the catalogue drawn only as cells | `forest_map.py:95` (`MAX_FEATURES=600`), `:84` | No |
| BUG-02 | **P0** | Tiles rejected with HTTP 503 and left blank | Two users open zoom-13 views at once, or one user zooms quickly | Expected: tiles queued and retried. Actual: 79% (2 users) / 95% (5 users) of tiles 503; blank tiles. Likely cause, not proven: cancelled fetches keep server slots busy (sync handlers) | `forest_map.py:31,126`; client never retries (`forest-map.js:33`) | No |
| BUG-03 | **P0** | Sectors 12–14 drawn about 174 km from their surveyed location | Sectors layer at 56.259°N 26.446°E | Expected: 56.692°N 23.708°E (pyproj on the plan's LKS-92 points). Actual: legacy converter output | `api.py:1072,1105` (`_lks92_to_wgs84`) | No |
| BUG-04 | **P0** | OCR coordinates outside LKS-92 range accepted (sectors 15–17 in Russia) | Boundary plan 17 | Expected: reject Y ≈ 951,163 (outside range). Actual: stored at about 58.90°N 32.74°E | boundary-plan OCR → `api.py:1105` | No |
| BUG-05 | P1 | Zoom 4–10 shows a uniform square blanket, not forest | Open the Forest Map (zoom 7) | Expected: forest extent. Actual: cells covering 116% of Latvia's area, sea included, with no density | `forest_map.py:70-72`, `forest-map.js:34` | Partly (dots instead of squares, still uniform) |
| BUG-06 | P1 | Fallback is indistinguishable from the zoom ≤ 10 overview | Zoom 12 in a dense area | Expected: a tile-level "N compartments not drawn, zoom in" message. Actual: the same generic badge | `forest-map.js:39` (`scaleNotice`) | No |
| BUG-07 | P1 | Sector outside Latvia shown as valid (sector 9 in Russia); 5 sectors without geometry not listed | Sectors layer | Expected: real Latvia boundary check and a list of unmapped sectors. Actual: bbox check 55–59°N / 20–29°E; only a count shown | `forest_map.py:194`, `forest-map.js:39` (label) | No |
| BUG-08 | P1 | Non-forest land categories (bogs, glades, flooded, …; 104,479 records) styled and labelled as "forest" | Click a bog compartment (zkat 21) | Expected: category shown and styled separately. Actual: "Forest area", one colour | `forest-map.js:34,40` | No |
| BUG-09 | P1 | Mixed languages | Open the page on `:8000` | Expected: one language. Actual: EN UI with LV server messages, LV mode with EN server errors | `forest-map.js:51`, `forest_map.py`, `api.py:603` | Partly (LV default; HTTP errors still EN) |
| BUG-10 | P2 | Tile responses uncompressed | `curl -H 'Accept-Encoding: gzip'` on a tile | Expected: gzip, about 5× smaller. Actual: 160 KB raw | `api.py` (no GZip middleware) | No |
| BUG-11 | P2 | Refresh does not pick up a new dataset version (from code reading) | Publish a dataset with the page open, press Refresh | Expected: reload. Actual: every tile errors with "version" until a full reload | `forest-map.js:51` (`load()` early return) | No |
| BUG-12 | P2 | Candidate shows an absolute server path in the details panel | Candidate: click a compartment | Expected: dataset/record reference. Actual: `/root/forest_ai/data/…/KKParcel.shp` | candidate `forest_map.py` / `nationwide.source_reference` | Introduced by candidate |
| BUG-13 | P2 | Declared area 0 silently replaced by geometric area | Inspect a compartment with `nog_plat = 0` | Expected: "declared 0 / computed x ha". Actual: computed value shown as "Forest area" | `vmd_dataset.py:125` | No |

## 11. Options for "all compartments visible at every zoom"

**Measured** on the same real tiles, outside the server (`scripts/options_proto.py`,
`options_proto*.json`). The tiles were the densest, a median one and random ones per zoom.
Occupied-tile counts come from `census.json`: zoom 10: 190, zoom 11: 654, zoom 12: 2,428,
zoom 13: 9,312, zoom 14: 35,621.

| tile (densest / median) | (a) GeoJSON, no limits: raw / gzip, generate | (b) MVT gzip, encode | (c) PNG 256 px, render |
|---|---|---|---|
| zoom 10 | 9.0 MB / 1.8 MB, 8.7 s (+ 48 s read) · 4.6 MB / 0.9 MB | 494 KB, 17 s · 261 KB | **7.0 KB, 3.0 s · 8.0 KB** |
| zoom 11 | 2.5 MB / 520 KB, 2.1 s · 1.3 MB / 257 KB | 175 KB, 4.1 s · 86 KB | 7.2 KB, 0.7 s · 6.2 KB |
| zoom 12 | 871 KB / 184 KB, 0.7 s · 389 KB / 76 KB | 72 KB, 1.5 s · 29 KB | 19 KB, 0.33 s · 12.7 KB |
| zoom 13 | 310 KB / 68 KB, 0.2 s · 123 KB / 27 KB | 28 KB, 0.5 s · 11 KB | 15 KB, 0.16 s · 10 KB |
| zoom 14 | 118 KB / 27 KB, 0.13 s · 49 KB / 12 KB | 7.0 KB, 0.13 s · 3.4 KB | 9.4 KB · 6.1 KB |

| | **a) Dynamic GeoJSON, tuned limits** | **b) Pre-generated vector tiles (MVT/PMTiles)** | **c) Raster ≤ zoom 13 + current vector ≥ zoom 14** |
|---|---|---|---|
| Shows every compartment | Only if limits are lifted. A zoom-11 view (about 24 tiles) is 30–60 MB raw / 6–12 MB gzip | At ≤ zoom 11 tiles of 100–500 KB gzip hold up to 37k polygons each; in practice features must be dropped or merged there | **Yes**: the exact area of all 3,063,409 is rasterized at every zoom ≤ 13 (individual outlines legible at zoom 13, where the median compartment is about 8 px); full vectors from zoom 14 (100% measured) |
| Build time | none | Python prototype, extrapolated: about 4–5 h on 1 core for zoom 10–14 (C++ tippecanoe faster, not measured; not installed) | About 1–1.5 h: zoom 13 ≈ 9,312 × 0.25 s, zoom 12 ≈ 2,428 × 0.5 s; lower zooms downsampled from zoom 12 |
| Disk | none | About 0.5 GB for zoom 10–14 (median sizes × tile counts) | **About 0.15 GB** (zoom 13: 9,312 × ~11 KB, zoom 12: 2,428 × ~13 KB, rest < 10 MB) |
| Server load | High: seconds of CPU per dense tile on a 2-core host that already 503s | Static range reads, negligible | Static files, negligible; zoom ≥ 14 dynamic tiles already ≤ 0.3 s / 208 KB |
| Client | Heavy canvas redraws of thousands of polygons | Needs a vector-tile renderer plugin for Leaflet (new dependency) | Native `L.tileLayer`; trivial |
| Rebuild on catalogue update | none | Full rebuild | Rebuild job keyed by dataset version, like the existing `overview.npz` |
| Licence / attribution | unchanged | unchanged | unchanged. VMD CC0, VZD CC-BY-4.0 (parcel layer attribution "Valsts zemes dienests" still required) |
| Effort | small (constants, gzip), but does not solve zoom ≤ 12 | large (new build pipeline and client renderer) | medium (offline render script, static route, tile-layer switch at zoom 14) |
| Risk to registration | none | none if display-only | none: tiles are display-only; inspect and import keep rereading full original source records |

**Recommendation: option (c), plus two independent fixes.**
1. **Why (c):** it is the only option that, measured on this hardware, draws every
   compartment's area at every zoom.
   - Its tiles are 7–19 KB.
   - The build is about 1–1.5 h, offline and per dataset version.
   - It needs about 0.15 GB of disk.
   - It adds no request-time CPU on a 2-core host that already fails at 2 concurrent users.
   - Above zoom 14 it keeps the existing vector path, measured 100% complete with
     ≤ 208 KB / 0.3 s per tile.
   - Clicking keeps working through `/identify`, which is independent of tiles from
     zoom 11. Registration is untouched.
2. **Why not (b):** MVT does not remove the low-zoom density problem. It needs a new client
   renderer and roughly 3× the disk.
3. **Why not (a):** cannot serve zoom ≤ 12 within the server's capacity.
4. **Independently of the option, do both of these:**
   - **Fix BUG-02:** queue instead of an immediate 503; retry on the client.
   - **Enable gzip for GeoJSON responses** (BUG-10).

## What was not verified
- **LVM GEO WMS overlay alignment:** the host is unreachable from the VPS.
- **BUG-11:** found from code reading only; testing it needs a dataset publication.
- **Root cause of the single-user 503s:** cancelled fetches keeping server slots busy is
  inferred, not traced.
- **Option (b) build time:** extrapolated from a Python encoder. tippecanoe was not
  available.
- **Option (c) build time and disk:** extrapolated from 21 rendered sample tiles, not a full
  build.
- **Nationwide fallback triggers:** only the 600-feature rule was evaluated for all tiles.
  The byte, vertex and time triggers were checked on the 25 densest zoom-14 tiles and the
  448 sample tiles only.
- **Screenshots** (production zoom 7 blanket, zoom 15 holes, candidate dot lattice) are
  outside git, in this session's temporary scratchpad.
