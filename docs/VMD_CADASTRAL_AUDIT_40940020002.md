# VMD cadastral accuracy audit — 2026-11-06

**Finding:** the 10 results for `40940020002` are genuine separate compartments in the supplied official VMD snapshot. The count is correct. The original exact SQL search was already correct; no substring search, wrong field, wrong join, duplicate-index record or coordinate swap caused these results. A separate row-focus/popup auto-pan issue was found during browser verification and corrected.

All ten original DBF records carry exactly `kadastrs = 40940020002`, quarter 1, subcompartment 0, in `nodala2651.shp`. The compartment numbers are 1, 3, 4, 5, 6, 7, 8, 9, 10 and 12. Missing numbers 2 and 11 were not invented or filled in. The results total **7.99 ha** in source-declared area. Their centroids are at most **718.79 m** apart; they are not geographically scattered across Latvia.

## Exact source field mappings

All five original DBF schemas were inspected directly. Each has 88 fields. In this archive, the identifier fields below are character fields of width 254, despite carrying numeric-looking strings. They must not be converted to numbers or lose leading zeros.

| Meaning | Actual DBF field | Mapping/interpretation |
|---|---|---|
| Cadastral land-unit designation | `kadastrs` | Land-unit designation; normalized index column `compartments.kadastrs`; only field used for cadastral search |
| Cadastral property number | **Absent** | No separate property-number field exists among the actual 88 source fields; no property lookup or substitution is performed |
| Source GIS feature ID | `objectid` | Source feature identifier within this snapshot; application qualifies it as `VMD:{source_layer}:{objectid}` |
| Forest quarter | `kvart` | Source quarter number, preserved as text |
| Forest compartment number | `nog` | Source compartment number, preserved as text; not unique across cadastral units |
| Subcompartment | `anog` | Source subcompartment, preserved as text |
| Domain compartment reference | `kadastrs`, `kvart`, `nog`, `anog` | Composite reference; distinct quarters/compartments under the same land unit are legitimate records |
| Area, ha | `nog_plat` | Source declared area, displayed without substituting an unrelated area field |
| Geometry | SHP record, linked by SHX and matching DBF row | Original polygon, not inferred from imagery |

The inspected open-data schema does **not** contain `VMD_ID`; `objectid` is not presented as a separately verified permanent legal compartment identifier. Publisher semantics for KADASTRS/KVART/NOG/NOG_PLAT are corroborated by [the official published-data field definitions, Annex 9](https://likumi.lv/ta/id/283091-meza-inventarizacijas-un-meza-valsts-registra-informacijas-aprites-noteikumi) and [VMD's file-structure documentation](https://www.vmd.gov.lv/lv/meza-valsts-registra-meza-inventarizacijas-failu-struktura). Original source-file authenticity was previously established by matching all 25 files to the official Centra download; the same hashes were rechecked unchanged in this task.

## Diagnostic table

Centroids below use EPSG:4326 **longitude, latitude**. Additional decimal places are diagnostic serialization precision, not a statement of survey/datum accuracy. All areas below are the source `nog_plat`, in hectares.

| Source file | Source feature ID | Kadastra apzīmējums | Kvartāls | Nogabals | Centroid lon | Centroid lat | ha | Valid |
|---|---|---|---|---|---|---|---|---|
| nodala2651.shp | VMD:nodala2651:49703938 | 40940020002 | 1 | 1 | 24.408436007 | 56.676400394 | 0.45 | True |
| nodala2651.shp | VMD:nodala2651:49703940 | 40940020002 | 1 | 3 | 24.411368259 | 56.677712841 | 0.55 | True |
| nodala2651.shp | VMD:nodala2651:49703941 | 40940020002 | 1 | 4 | 24.412718911 | 56.678416397 | 0.25 | True |
| nodala2651.shp | VMD:nodala2651:49703942 | 40940020002 | 1 | 5 | 24.415294467 | 56.677765515 | 0.14 | True |
| nodala2651.shp | VMD:nodala2651:49703943 | 40940020002 | 1 | 6 | 24.415766226 | 56.677564641 | 0.18 | True |
| nodala2651.shp | VMD:nodala2651:76122062 | 40940020002 | 1 | 7 | 24.416416905 | 56.677086258 | 0.38 | True |
| nodala2651.shp | VMD:nodala2651:49703945 | 40940020002 | 1 | 8 | 24.417384109 | 56.677317259 | 0.24 | True |
| nodala2651.shp | VMD:nodala2651:49703946 | 40940020002 | 1 | 9 | 24.419397677 | 56.677543106 | 0.16 | True |
| nodala2651.shp | VMD:nodala2651:49703947 | 40940020002 | 1 | 10 | 24.418146932 | 56.676143571 | 5.19 | True |
| nodala2651.shp | VMD:nodala2651:49703948 | 40940020002 | 1 | 12 | 24.411604103 | 56.672716923 | 0.45 | True |

## Independent source/geometry verification

`scripts/audit_vmd_cadastre.py` scans the actual `kadastrs` bytes in **all five original DBFs**, independently of the SQLite index. It reads each matching native SHP record through its SHX offset, decodes the original DBF identifiers, and checks source file, row, object ID, quarter and compartment against the indexed record. The original files are opened read-only.

- Raw source matches: **10**; catalogue matches: **10**; ID sets identical.
- Duplicate source feature IDs: **0**; duplicate cadastral/quarter/compartment/subcompartment tuples: **0**; duplicate geometries: **0**.
- Source and normalized geometries: all valid Polygon geometries.
- Original PRJ: **EPSG:10306, LKS-2020 / Latvia TM**, GRS80, central meridian 24°, scale 0.9996, false easting 500000 m, false northing −6000000 m. It is not silently relabeled EPSG:3059.
- Independent PROJ transformation uses `always_xy=True`; GeoJSON remains longitude/latitude. Leaflet handles conversion to latitude/longitude internally through `L.geoJSON`.
- Maximum difference between the existing catalogue geometry and independently projected source geometry is **0.000136 m**, when compared back in the same source projection/datum approximation. No simplification, geometry replacement or re-indexing was performed.
- This checks projection/serialization consistency, not authoritative WGS84 datum accuracy. PROJ describes this particular 10306→4326 operation as a **ballpark geographic offset**, with accuracy reported as **unknown**. Native source geometry remains the accuracy/provenance reference; no cadastral/legal boundary accuracy is claimed.
- Normalized extent: longitude **24.407399030–24.420125690**, latitude **56.672123989–56.678703273**.
- Source projected geometry totals approximately **7.983626 ha**, versus **7.99 ha** summed rounded source-declared areas. That rounding difference is not a search or axis-order bug.
- The search without a spatial filter reads `compartments` directly through `cadastre_idx`, with no geometry/attribute join. Spatial queries join the RTree by the same integer feature key. Per-record source row/ID/geometry agreement rules out the suspected incorrect join for these ten records.

“All ten belong to this land unit” means that the official VMD records consistently assign them this exact land-unit designation. An independent VZD cadastral polygon/ownership check was not performed; forestry compartment polygons are not substituted for a legal parcel boundary.

## Changes and search contract

1. Exact search remains SQL equality on the existing indexed, canonical `kadastrs` column. All **513,776** stored designations were checked to be exactly 11 ASCII digits. No catalogue migration or source alteration was necessary.
2. Full inputs are validated as 11 ASCII digits. Standard `4094 002 0002` or `4094-002-0002` display formatting is normalized while preserving every digit and leading zero. Arbitrary punctuation, wildcards, scientific notation and extra suffixes are rejected.
3. Optional partial mode is explicitly named **Daļēja meklēšana pēc sākuma (4–10 cipari)** and uses an indexed digit-prefix range, not a substring/fuzzy match. A full 11-digit value always uses exact equality, even if partial mode was selected.
4. The backend reports the actual search field, normalized value and effective matching mode in `summary.cadastral_search`. Empty input does not become a national search just because a default mode is present.
5. The interface explicitly shows **Kadastra apzīmējums**, **Kvartāls**, **Nogabals**, **Platība (ha)** and **Datu avots**, explains land-unit versus property number, and distinguishes exact/prefix result summaries. Source layer is also shown.
6. Row focus uses the selected polygon's actual bounds with immediate zoom. It temporarily disables popup auto-pan while opening the row's details so the popup cannot undo the requested fit. Normal polygon-click popup behavior is retained; tall popups scroll.

Files changed: `services/geodata/vmd_dataset.py`, `services/geodata/vmd_production.py`, `assets/vmd-production.js`, `index.html`, `tests/test_vmd_production.py`, `tests/test_vmd_production_ui.js`. Added `scripts/audit_vmd_cadastre.py`, `scripts/verify_vmd_cadastral_browser.py`, and this report.

## Testing and deployment

- **252 Python tests passed**, using the documented test-only same-thread ASGI runner where required by this executor; includes source geometry, exact matching, multiple compartments, invalid/no-match inputs, explicit prefix matching, duplicate identity protection and existing integrations.
- **29 JavaScript checks passed**: production UI 10, WMS 9, dispatch 3, legacy local UI 7. Includes selection, pagination, labels and row zoom/popup behavior.
- Original source audit: all ten native source/geometry checks passed. All **25** original file hashes remain unchanged. Existing production database row contents match the pre-task backup.
- Deployed to **http://164.90.188.136:8000/#lvm-geodata**. Main backend `forest-api.service` was restarted at **2026-11-06 11:07:57 UTC**, PID **2703766** at verification. No client service, credentials, database schema or sectors were changed.
- Live frontend version: **geo-c8a10dc581f1**. Chromium confirmed the downloaded production JavaScript matches disk.
- Real live Chromium: HTTP 200 exact search → exactly ten audited IDs; API and all ten Leaflet geometries match the audit; clicking every result fits that exact polygon's source bounds; multiple selection works; formatted exact input returns ten; short exact input returns **422**; explicit prefix `4094` returns **15,420** total matches with pagination; full 11-digit input in prefix mode still returns ten exact matches; no-match input returns HTTP **200**, zero features; no blocking JavaScript errors. All browser checks are read-only and created no production sectors or territories.

Artifacts:

- Full independent audit: `data/vmd/cadastral-audit-40940020002/audit.json`.
- Requested diagnostic CSV: `data/vmd/cadastral-audit-40940020002/audit.csv`.
- Live browser evidence: `data/vmd/cadastral-search-live-20261106.json`.
- Screenshot: `data/vmd/cadastral-search-live-20261106.png`.
- Backup: `data/backups/cadastral_search_20261106T110109Z/` (database integrity verified).

Reproduce the independent source audit: `python3 scripts/audit_vmd_cadastre.py 40940020002`.
Reproduce the live browser check with the temporary browser install: `FOREST_PLAYWRIGHT_PATH=/tmp/forest_browser PLAYWRIGHT_BROWSERS_PATH=/tmp/forest_chromium python3 scripts/verify_vmd_cadastral_browser.py`.

The external LVM capability endpoint remains a separate provider-availability issue and is not involved in this local VMD cadastral query.
