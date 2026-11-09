**Forest AI — LVM GEO / VMD diagnostic, 7 November 2026 (UTC)**

Overall: **FAIL for an unqualified “everything works correctly” claim; PASS for tested local cadastral search, Leaflet integration and eligible sector dry-runs.** Original data defects, an unavailable live LVM service and inconsistent retained acceptance evidence prevent an overall clean pass. No production code was changed, no import restarted, no production sectors created, and no existing data or evidence overwritten. New report/evidence files are additive.

**Database and import status**

Active release: `data/geodata/nationwide/active.json`, matching `data/geodata/nationwide/releases/20261106/release.json`. Dataset version: `15b2ef2b3e6b4bba295c309fa237ac49bd06772b36440c10d38d8a0b47eeb13a`. National forest database: `data/geodata/nationwide/releases/20261106/compartments.sqlite` (~8.7 GiB); cadastral database: adjacent `parcels.sqlite` (~1.4 GiB). Operational sectors remain in `data/forest_ai.db`. The older `data/vmd/compartments.sqlite` is a Centra-only legacy catalogue; root `forest.db` is empty and is not the active catalogue.

Forest tables: `compartments` (records/attributes/WKB), `files` (row checkpoints and source metadata), `rejections`, `duplicate_sources`, `metadata`, `spatial_index` (EPSG:4326 RTree), `native_index` (native CRS RTree), RTree shadow tables and `sqlite_stat1`. Parcel database has `parcels`, the same bookkeeping tables and one `spatial_index`. Relevant operational tables are `sectors`, `geodata_sources`, `geodata_boundary_history` and `geodata_previews` and `organizations`.

| Measure | VMD forestry | VZD cadastre |
|---|---:|---:|
| Indexed records | 3,063,409 | 1,055,666 |
| Original source records | 3,063,409 | 1,059,766 |
| Duplicate source rows retained | 0 | 4,100 |
| Rejected/missing source rows by conservation | 0 | 0 |
| Incomplete files | 0 / 26 | 0 / 5,240 |
| Invalid identifiers / missing native or display geometry | 0 | 0 |
| Unverified source flags / nonpositive stored areas | 0 | 0 |

All 47 archives (5 VMD, 42 VZD) were freshly hashed: SHA256 and size match the manifest. Existing archive markers record successful CRC validation; CRC decompression was not rerun. All original DBF header counts were freshly read and reconcile with the source totals and deduplication counts. Worker status is `READY / already_complete`; no ingest was run. This establishes conservation of the supplied snapshot, not the absence of omissions in the official source. VMD publication is 2026-10-07 (SHP/DBF export 2026-10-08); VZD export is 2026-10-31.

**Geographic coverage**

| Forestry region | Records |
|---|---:|
| Austrumu | 570,975 |
| Centra | 513,776 |
| Dienvidu | 553,644 |
| Kurzemes | 645,334 |
| Vidzemes | 779,680 |

All five forestry regions and all 42 municipal source archives are present. Forest display extent, measured from every polygon: approximately **20.971755–28.240974° E, 55.674734–58.085502° N**. No polygon lies outside the tested broad Latvia envelope (20–29° E, 55–59° N). This envelope is a sanity check, not an administrative boundary intersection. National source-set completeness is supported; legal, current, gap-free coverage of every forest parcel in Latvia is not established.

**Full geometry validation**

| Test | Result | Status |
|---|---|---|
| VMD: every stored native and display WKB decoded | 3,063,409 | PASS |
| VMD: valid original/native polygons | 3,061,686; invalid 1,723 | FAIL |
| VMD: valid display polygons | 3,063,409; invalid 0 | PASS |
| VMD: empty geometries / nonfinite bounds | 0 / 0 display; 0 / 0 native | PASS |
| VZD: every stored native and display WKB decoded | 1,055,666 | PASS |
| VZD: valid original/native polygons | 1,055,666; invalid 0 | PASS |
| VZD: valid display polygons | 1,055,666; invalid 0 | PASS |
| VZD: empty geometries / nonfinite bounds | 0 / 0 display; 0 / 0 native | PASS |

VMD: **1,723 invalid source polygons** are retained; normalized display polygons are valid. **2,152 rows have repair flags**: 1,717 labelled `Source invalid; display-only make_valid`, and 435 labelled `Display normalization repair; original preserved`. Six in the latter group also have invalid native geometry, leaving **429 additional source-valid display repairs**. The API summary `repaired=1723` counts invalid native geometry, not every repair-flagged record: **FAIL for accurate total repair reporting**.

**3,037,097** rows carry the geometry-level importable flag; **26,312** are excluded (2,152 repair-flagged records plus 24,160 other unsupported geometries under the simple Polygon/no-holes/vertex-limit sector rules). This is not a count of cadastrally approved registrations; containment, association, existing-sector and name checks still apply.

Source CRS is **EPSG:10306, LKS-2020 Latvia TM**; display GeoJSON is **EPSG:4326, longitude/latitude**; sector boundary lists use latitude/longitude. Ten independent original DBF/SHP forest records and ten original parcel records matched the chosen identifiers and native WKB. Independent PROJ transformation matched the API geometry within 2e-8 degrees. Sector normalization preserved all coordinates and vertices for all ten samples. Source `nog_plat` hectares matched displayed hectares; small differences from polygon-computed hectares reflect the declared/rounded source area. CRS/source comparisons are sampled, not an independent reread of all SHP geometry records.

Exact invalid examples (native metre coordinates):
- `VMD:nodala2851:49792753`, cadastre `36880050114`, source row 489: `Ring Self-intersection[677024.279583485 384305.990988402]`.
- `VMD:nodala2851:49830180`, cadastre `36760090053`, source row 2059: `Ring Self-intersection[693211.208768267 374409.189822572]`.
- `VMD:nodala2851:49921508`, cadastre `36560050061`, source row 3552: `Ring Self-intersection[693036.728535042 368795.900016471]`.
- `VMD:nodala2851:50451429`, cadastre `36720020215`, source row 4695: `Ring Self-intersection[687867.128128745 360524.760597906]`.
- `VMD:nodala2851:51150761`, cadastre `36880030113`, source row 10878: `Ring Self-intersection[677408.077387431 388160.044034537]`.

All 20 collected examples with source filenames are retained in `invalid_examples.json`; this is a sample of the 1,723 invalid originals. No geometry was edited.

**Cadastral searches and map integration**

Ten real identifiers were selected from imported records, two per forestry region. Each fresh live search passed exact identifier checks, source comparison, Leaflet/API geometry equality, polygon click/popup cadastral data, map fit and registration preview. Spatial candidates remained nonimportable.

| Region | Cadastral designation | Exact VMD | Verified matches | Separate spatial candidates | Server seconds | Status |
|---|---|---:|---:|---:|---:|---|
| Austrumu | `36680080065` | 435 | 365 | 87 | 0.275 | PASS |
| Austrumu | `36680010022` | 8 | 7 | 11 | 0.032 | PASS |
| Centra | `01000950031` | 6 | 1 | 7 | 0.025 | PASS |
| Centra | `32900020043` | 25 | 15 | 3 | 0.034 | PASS |
| Dienvidu | `32920120011` | 11 | 4 | 9 | 0.037 | PASS |
| Dienvidu | `32960090079` | 7 | 2 | 11 | 0.023 | PASS |
| Kurzemes | `64960030075` | 144 | 122 | 37 | 0.293 | PASS |
| Kurzemes | `64960010131` | 298 | 245 | 54 | 0.357 | PASS |
| Vidzemes | `42680030058` | 47 | 28 | 18 | 0.088 | PASS |
| Vidzemes | `42560060473` | 15 | 7 | 4 | 0.038 | PASS |

`01000950031`: six exact compartments total **2.59 ha** (declared source area). `VMD:nodala2653:70588599` is eligible, **0.11 ha**. The other five exact records require boundary review. Seven additional spatial candidates are separate from the six exact records.

| Exact feature | Area ha | Outside VZD parcel m² | Dry-run outcome |
|---|---:|---:|---|
| `VMD:nodala2653:105553907` | 0.24 | 0.007645634 | boundary_review_required |
| `VMD:nodala2653:70588598` | 0.50 | 0.095906457 | boundary_review_required |
| `VMD:nodala2653:70588599` | 0.11 | 0.000000000 | ready |
| `VMD:nodala2653:70588600` | 1.03 | 0.012120901 | boundary_review_required |
| `VMD:nodala2653:70588601` | 0.56 | 0.040534569 | boundary_review_required |
| `VMD:nodala2653:70588602` | 0.15 | 0.016301298 | boundary_review_required |

Five blocked records return exact error **`Robežu neatbilstība — nepieciešama pārbaude`**. Their very small outside areas arise from source boundary disagreement under strict `covers()`; no tolerance is configured. They are valid polygons, not import-corrupted records. A different-cadastre spatial candidate was rejected with **`Nogabala avota kadastra apzīmējums neatbilst pārbaudītajai atlasei`**. These rejection checks **PASS**.

The live browser used `http://164.90.188.136:8000/#lvm-geodata`, frontend `geo-cac1a48e954b`, with the same dataset version as the local manifest. All 435 results in the largest tested search were traversed; selection survived pagination. Invalid short input made no lookup request; an unknown 11-digit designation returned `PARCEL_NOT_FOUND` with no borrowed geometry. Browser errors: **0**. Leaflet integration: **PASS**.

**Import as Sectors: dry-run only**

All ten single-feature live previews passed. An 83-compartment live bulk preview passed in **0.194 s**, response **221,947 bytes**, with no failures. A direct six-feature preview for `01000950031` returned `would_import=1`, `failed=5`, `imported=0`, as expected from boundary checks. Sector names, source IDs, cadastre/quarter/compartment fields and server-derived organization context were verified in previews/source records. Geometry conversion preserved coordinates for all ten samples. Hashes/counts of sectors, geodata sources, organizations and risks matched before/after the direct dry-runs; 21 production sectors remained.

Eligible simple polygons are **READY FOR DRY-RUN / CONDITIONAL REGISTRATION**. A dry-run returns before the metadata INSERT branch, so this diagnostic does **not** establish fresh persistence of metadata or production registrations. No sector was created in production or staging during this diagnostic. The damaged saved staging evidence prevents relying on its prior end-to-end persistence claim without a new, separately authorized disposable test.

**Performance and indexes**

All ten local searches also passed with Python socket connections explicitly blocked: local SQLite is sufficient; no source download is required. Fresh live server timings were **0.023–0.357 s** for these cases, measured while read-only audits were running; these are sample timings, not load-test percentiles. Exact cadastral lookup uses `cadastre_idx (kadastrs=?)`; spatial search uses the native RTree and compartment primary key.

| Spatial index | Entries | Missing compartment/parcel entries | RTree integrity | Status |
|---|---:|---:|---|---|
| vmd.spatial_index | 3,063,409 | 0 | ok | PASS |
| vmd.native_index | 3,063,409 | 0 | ok | PASS |
| vzd.spatial_index | 1,055,666 | 0 | ok | PASS |
Full SQLite vmd integrity_check: ['ok']. **PASS**.
Full SQLite vzd integrity_check: ['ok']. **PASS**.

Observed/design bottlenecks: every pagination request recomputes the exact/spatial relationship set; native topology calculations grow with candidate count. The service caps exact/candidate sets at 50,000 and computation at 25 s; these limits were inspected, not load-tested. Very large/complex parcel searches and concurrent production load remain unmeasured. Full-table integrity/geometry diagnostics are substantially more expensive than indexed cadastral searches and should run off-peak.

**Failures and recommended fixes**

1. **FAIL — invalid original geometry:** 1,723 source polygons. Keep originals and exclusion rules; review/correct through authoritative source updates or an audited manual process. Do not silently register display repairs as original boundaries.
2. **FAIL — repair-count reporting:** expose native-invalid, display-repaired and total-repair-flagged counts separately (1,723 / 435 / 2,152 with overlap 6). Preserve import restrictions.
3. **FAIL — retained staging acceptance evidence:** `staging-acceptance.json` currently says `RUNNING`, `cases=[]`, while `publication-check.json` says staging `PASSED`. The verifier writes RUNNING into that same evidence filename before executing, allowing later runs to replace earlier proof. Use immutable per-run evidence, atomically publish final successful results, and validate a matching completed run before publication. Do not infer that yesterday’s test did not run; its surviving evidence is inconsistent.
4. **FAIL — separate live LVM service availability:** authenticated `/api/geodata/lvm/health` returned HTTP 200 with `status=UNAVAILABLE`, `wms=false`, `wfs=false`, `layer_count=0`. Both configured maps/vector endpoints report **`LVM GEO unavailable or request timed out`** twice. Investigate the configured capabilities endpoints, DNS/network/TLS and provider response before claiming live LVM availability. Local VMD search/map is independently operational.
5. **REVIEW — strict parcel containment:** five of six target matches are blocked despite only 0.008–0.096 m² outside the parcel. Reconcile source versions/precision with the data owner; any tolerance needs an explicit accuracy policy and separate review. Do not enable it silently.
6. **LIMITATION — geometry compatibility:** 26,312 rows are not currently geometry-importable; supporting holes/MultiPolygon needs coordinated sector data-model, map and area handling. Keep review-only behavior until supported.

**Test verdict matrix**

| Test | Verdict |
|---|---|
| Active national dataset located; live version matches | PASS |
| Archive SHA256/sizes and all DBF header count conservation | PASS |
| Import checkpoints complete; no missing/rejected records in supplied snapshot | PASS |
| Five VMD regions and 42 municipal source sets loaded | PASS |
| Every real Latvian forest parcel is covered/current | NOT ESTABLISHED |
| Every source polygon valid | FAIL — 1,723 invalid VMD originals |
| Every display polygon valid; finite bounds; no missing geometry | PASS |
| CRS and original-source comparison for ten forest/parcel samples | PASS |
| Full SQLite integrity checks (both databases) | PASS |
| RTree integrity and record inclusion | PASS |
| Ten real cadastral searches including 01000950031 | PASS |
| Exact/spatial separation; foreign-cadastre rejection | PASS |
| Leaflet polygon render/click/data and API consistency | PASS |
| 435-result pagination and retained selection | PASS |
| Ten single and 83-compartment bulk dry-runs | PASS |
| Sector normalization preserves ten sample geometries | PASS |
| No production sector creation or direct dry-run row changes | PASS |
| Fresh persisted metadata/end-to-end registration | NOT RUN — dry-run scope |
| Indexed local lookup, no network/source redownload | PASS |
| Concurrent load / worst-case huge polygons | NOT RUN |
| Accurate total repair summary | FAIL |
| Retained completed staging acceptance evidence | FAIL |
| Separate live LVM WMS/WFS availability | FAIL |

NOT RUN / NOT ESTABLISHED are deliberately not reported as passes. Fresh detailed evidence accompanies this report in `docs/evidence/full-diagnostic-20261107/`. Diagnostics used SQLite read-only/query-only connections for national data and dry-run requests for registration. Chromium/network checks required sandbox escalation; an initial sandbox launch/network denial was an environment restriction and passed after escalation. Historical report/acceptance files were only read.
