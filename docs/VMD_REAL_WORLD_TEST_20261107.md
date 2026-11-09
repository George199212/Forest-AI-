**Forest AI — real-world VMD database test, 7 November 2026 (UTC)**

**Result:** all 20 selected cadastral units passed the local API, geometry/source checks and live Leaflet tests; four regional sector previews passed without creating sectors. The 20 units contain **497 forest compartments / 470.15 ha**. There are outstanding evidence/reporting issues, strict-boundary compatibility issues and an unavailable optional live LVM service. Unrestricted production readiness is not established.

**1. Scope, safeguards and evidence**

Active national release: `data/geodata/nationwide/releases/20261106/`; forest catalogue `compartments.sqlite`; parcel catalogue `parcels.sqlite`; operational DB `data/forest_ai.db`. Dataset version: `15b2ef2b3e6b4bba295c309fa237ac49bd06772b36440c10d38d8a0b47eeb13a`. Existing full diagnostics established 3,063,409 VMD records, 1,055,666 VZD parcels, database/RTree integrity and full geometry counts; those expensive full scans were not unnecessarily repeated. See [the earlier full diagnostic](LVM_VMD_FULL_DIAGNOSTIC_20261107.md).

No production code was changed; no database INSERT/UPDATE/DELETE, new sector, staging sector or full ingest was executed. The local harness forces persistent SQLite connections to URI `mode=ro` and `query_only=ON`, and blocks socket creation/connection/DNS lookups. Actual FastAPI VMD route handlers execute in a minimal ASGI harness without application lifespan/background workers. Its synchronous routes run inline to avoid this environment’s blocked threadpool portal; these timings are not live HTTP latency or concurrency benchmarks. Live browser checks independently exercised the deployed authenticated UI and HTTP API. A browser request guard permitted only reads and `import-selected` POSTs with `dry_run:true`.

Logical hashes and counts of all **46 operational tables** matched before/after the local API run; **21 sectors** remained. Both national database files retained their size and nanosecond mtime. The live `/api/map` response hash matched before/after browser tests. There were zero blocked-network attempts in the completed local API run, zero unsafe browser requests and zero browser JavaScript errors. These checks establish no changes from this diagnostic; they do not freeze unrelated future activity.

Evidence and reproducible diagnostic scripts: `docs/evidence/vmd-real-world-20261107/`. No credentials are included.

**2. Twenty real cadastral identifiers**

Every identifier was extracted from local `compartments.kadastrs`, verified as an exact 11-digit text identifier and found in local VZD `parcels.designation`. Every selected unit has valid original/display geometries, no repair-flagged exact records and at least one source-exact, parcel-contained, importable compartment. Selection deliberately favors around 25 compartments per unit for multi-polygon workloads; it is not a random prevalence sample. There are five units from five distinct municipalities in each requested region: **20 different municipalities** overall.

The four requested historical/geographical regions are distinct from the five VMD forestry service regions. Parish membership was checked against the [official historical-region parish list, Annex 1](https://likumi.lv/ta/id/324253-latviesu-vesturisko-zemju-likums). Municipal/parish labels come directly from source `adm1`/`adm2`; the report does not relabel the VMD forestry service regions. Sēlija was not folded into Zemgale.

Area is the sum of positive VMD `nog_plat` hectares, with the application’s geometric-area fallback; it is **not** cadastral parcel area or a union-dissolved footprint. Latitude/longitude identify the parcel’s native projected centroid transformed to WGS84, not a guaranteed point inside a concave parcel.

| Region | Municipality | Parish | Cadastral land unit | Compartments | Forest ha | Latitude | Longitude | API / map |
|---|---|---|---|---:|---:|---:|---:|---|
| VIDZEME | Valmieras novads | Burtnieku pagasts | `96480160030` | 25 | 19.6300 | 57.604269 | 25.334821 | PASS / PASS |
| VIDZEME | Cēsu novads | Amatas pagasts | `42420010146` | 25 | 13.5200 | 57.202980 | 25.228791 | PASS / PASS |
| VIDZEME | Smiltenes novads | Launkalnes pagasts | `94700040023` | 25 | 13.7700 | 57.389291 | 25.953650 | PASS / PASS |
| VIDZEME | Alūksnes novads | Alsviķu pagasts | `36420040017` | 25 | 23.1600 | 57.458423 | 26.808962 | PASS / PASS |
| VIDZEME | Gulbenes novads | Lejasciema pagasts | `50640020008` | 25 | 17.8300 | 57.344023 | 26.407021 | PASS / PASS |
| LATGALE | Ludzas novads | Istras pagasts | `68600020035` | 25 | 29.0200 | 56.287339 | 27.998357 | PASS / PASS |
| LATGALE | Rēzeknes novads | Mākoņkalna pagasts | `78720010031` | 25 | 30.4400 | 56.278684 | 27.288112 | PASS / PASS |
| LATGALE | Krāslavas novads | Indras pagasts | `60620022173` | 26 | 39.2000 | 55.890545 | 27.612956 | PASS / PASS |
| LATGALE | Preiļu novads | Aglonas pagasts | `76420050155` | 25 | 29.4500 | 56.165096 | 27.080514 | PASS / PASS |
| LATGALE | Balvu novads | Baltinavas pagasts | `38440020151` | 24 | 20.1100 | 56.966354 | 27.738921 | PASS / PASS |
| KURZEME | Ventspils novads | Tārgales pagasts | `98660020099` | 25 | 14.3900 | 57.589039 | 21.916355 | PASS / PASS |
| KURZEME | Kuldīgas novads | Alsungas pagasts | `62420110056` | 25 | 46.6800 | 56.909251 | 21.530218 | PASS / PASS |
| KURZEME | Talsu novads | Dundagas pagasts | `88500020032` | 25 | 16.9300 | 57.663415 | 22.453312 | PASS / PASS |
| KURZEME | Dienvidkurzemes novads | Rucavas pagasts | `64840080332` | 25 | 18.5700 | 56.166111 | 21.107799 | PASS / PASS |
| KURZEME | Saldus novads | Nīgrandes pagasts | `84700030005` | 25 | 27.0600 | 56.476348 | 22.087528 | PASS / PASS |
| ZEMGALE | Dobeles novads | Tērvetes pagasts | `46880010410` | 24 | 11.6500 | 56.505982 | 23.297159 | PASS / PASS |
| ZEMGALE | Jelgavas novads | Elejas pagasts | `54480090003` | 22 | 33.0000 | 56.414239 | 23.660333 | PASS / PASS |
| ZEMGALE | Bauskas novads | Iecavas pagasts | `40640020105` | 25 | 16.3300 | 56.683472 | 24.171388 | PASS / PASS |
| ZEMGALE | Ķekavas novads | Daugmales pagasts | `80560020116` | 26 | 29.6500 | 56.791759 | 24.430754 | PASS / PASS |
| ZEMGALE | Ogres novads | Birzgales pagasts | `74440030154` | 25 | 19.7600 | 56.673033 | 24.752260 | PASS / PASS |

The complete table was also printed directly to terminal output, not merely saved. Original query/selection details, source forestry regions, VZD municipal source labels and parcel bounds are in `selection.json`.

**3. Cadastral search API results**

The frontend’s exact endpoint is `GET /api/geodata/vmd/cadastre?kadastrs=...&limit=100&offset=0&review_offset=0`. Each local ASGI request called the same registered handler and backend search functions; each deployed browser also used that endpoint. All pages, where applicable, were collected and compared by complete source ID set with `SELECT ... WHERE kadastrs=?`. Returned display WKB/GeoJSON, source area, source `kadastrs`, dataset version and exact record counts matched. Review-only spatial candidates remained separate and nonimportable. Raw DBF/SHP attributes and geometry were independently reread for **all 497 exact forest compartments and all 20 parcels**.

| Cadastral identifier | Exact DB/API records | Verified eligible matches | Review entries (including spatial candidates) | Local route ms | Live server ms | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `96480160030` | 25 | 18 | 15 | 59.16 | 52 | PASS |
| `42420010146` | 25 | 18 | 10 | 35.38 | 31 | PASS |
| `94700040023` | 25 | 15 | 20 | 41.15 | 40 | PASS |
| `36420040017` | 25 | 9 | 30 | 49.94 | 39 | PASS |
| `50640020008` | 25 | 8 | 28 | 76.51 | 66 | PASS |
| `68600020035` | 25 | 16 | 24 | 65.85 | 29 | PASS |
| `78720010031` | 25 | 4 | 27 | 70.54 | 49 | PASS |
| `60620022173` | 26 | 15 | 31 | 74.80 | 43 | PASS |
| `76420050155` | 25 | 15 | 18 | 52.22 | 28 | PASS |
| `38440020151` | 24 | 16 | 23 | 59.72 | 40 | PASS |
| `98660020099` | 25 | 22 | 20 | 59.04 | 39 | PASS |
| `62420110056` | 25 | 18 | 19 | 69.76 | 60 | PASS |
| `88500020032` | 25 | 14 | 20 | 72.99 | 53 | PASS |
| `64840080332` | 25 | 19 | 14 | 62.53 | 36 | PASS |
| `84700030005` | 25 | 13 | 23 | 69.66 | 50 | PASS |
| `46880010410` | 24 | 8 | 24 | 80.73 | 44 | PASS |
| `54480090003` | 22 | 6 | 21 | 43.60 | 32 | PASS |
| `40640020105` | 25 | 16 | 19 | 66.58 | 60 | PASS |
| `80560020116` | 26 | 20 | 14 | 64.24 | 76 | PASS |
| `74440030154` | 25 | 9 | 28 | 62.70 | 60 | PASS |

Local first-pass range: 0.0354–0.0807 s; mean 0.0619 s. Live server-reported range: 0.028–0.076 s. These measure different paths and are shown separately. Invalid short identifier returned HTTP 422; unknown designation returned `PARCEL_NOT_FOUND` with no forest polygons. Both negative checks passed.

**4. Polygon and map validation**

| Check across all 497 selected forest records | Result | Verdict |
|---|---|---|
| Exact source ID set / source DBF cadastral field | All match local rows and source files | PASS |
| Original/native Polygon or MultiPolygon validity | All valid; none repaired or substituted | PASS |
| Display GeoJSON validity, nonempty geometry and positive area | All valid | PASS |
| CRS | PRJ/source EPSG:10306; display EPSG:4326, longitude/latitude | PASS |
| Coordinate finiteness and Leaflet range | All finite; 20–29° E, 55–59° N | PASS |
| Independent native-to-WGS84 transformation | Maximum Hausdorff error 1.61e-09 degrees; threshold 2e-8 | PASS |
| Native geometric area vs stored `area_m2` | Within max(0.001 m², 1e-10 relative) | PASS |
| API hectares vs source/application formula and summed totals | All match; sum 470.15 ha | PASS |
| Parcel GeoJSON bounding box vs API summary bounds | Exact match for all 20 | PASS |
| Centroid finiteness/bounds and native-centroid transform sanity | All pass | PASS |
| Exact national-border containment | No authoritative country boundary in local inputs | NOT ESTABLISHED |
| Live Leaflet geometry vs API geometry | Every returned feature compared for all 20 units | PASS |
| Polygon click popup | Cadastral code, source ID and formatted hectare value match | PASS |
| Browser frontend/backend dataset version | Matches active release; frontend Versija: geo-cac1a48e954b | PASS |

There are **34 legitimate polygon centroids outside their own concave/multipart polygon**, despite finite correct centroid calculations. This is not invalid geometry. Interior-point monitoring checks use `representative_point()`; do not use a mathematical centroid as proof of polygon containment. Source hectares can differ slightly from computed polygon hectares because the source declares rounded areas; both values are retained per feature in `api-tests.json`.

No selected polygon failed the Latvia envelope/locality checks. An envelope cannot detect every small national-border crossing; no legal-boundary containment claim is made. For exact national-border detection, supply an authoritative dated national boundary and run native-CRS difference checks. No invalid geometry was silently repaired by this diagnostic. Existing repair-flagged records were investigated separately below.

**5. Import as Sectors — four dry-runs**

| Region | Cadastral identifier | Source compartment ID | Sector name | Source ha | Organization | Dry-run | Monitoring geometry |
|---|---|---|---|---:|---|---|---|
| VIDZEME | `96480160030` | `VMD:nodala2255:98895536` | VMD diagnostic VIDZEME 96480160030 | 0.53 | 1 — Default Organization | PASS: ready=1, imported=0 | PASS |
| LATGALE | `68600020035` | `VMD:nodala2854:103206241` | VMD diagnostic LATGALE 68600020035 | 0.77 | 1 — Default Organization | PASS: ready=1, imported=0 | PASS |
| KURZEME | `98660020099` | `VMD:nodala2055:111693865` | VMD diagnostic KURZEME 98660020099 | 0.46 | 1 — Default Organization | PASS: ready=1, imported=0 | PASS |
| ZEMGALE | `46880010410` | `VMD:nodala2652:143876960` | VMD diagnostic ZEMGALE 46880010410 | 0.21 | 1 — Default Organization | PASS: ready=1, imported=0 | PASS |

For all four: exact WGS84 coordinates and vertex counts survived `store.normalize()`’s lon/lat → lat/lon boundary conversion; original native SHP geometry matched the stored source; cadastral designation, source ID and hectares were preserved in the preview path; sector naming and authenticated account → organization 1 assignment passed. The live UI separately displayed one-polygon review dialogs for the same four regions and sent only `dry_run:true`. Four screenshots are retained.

Forest AI’s shared geo helper and the actual bot ray-casting function both recognized an interior point and rejected an exterior point for each proposed boundary. Distance-to-boundary returned a positive exterior distance. This establishes geometry compatibility for GPS/geofence monitoring without inserting a sector, GPS ping, risk or incident. Full tracking, alerts, satellite acquisition and model execution were not invoked.

Duplicate safety: duplicate feature IDs in one request returned HTTP 422; repeating a dry-run created no rows. The real existing-source checker recognized `VMD:nodala2651:49703938` as sector 31. Its endpoint preview produced `would_import=0/imported=0` and was rejected earlier by strict cadastral containment. Therefore the deployed import endpoint’s `already_exists` branch was **not reached** in that case; the read-only existing-source lookup was independently verified. Current database uniqueness constraints and source ID lookup remain in the write implementation, but no new duplicate-insert transaction was attempted.

Three already-persisted VMD sectors (31, 32, 33) were read without modification: stored native/display geometry, cadastral/source IDs, sector boundary, organization and area match their imported source records. They retain their older dataset version (`26bd2653...`) as provenance; that is not overwritten with the active release version. These are historical persistence observations, not a new registration/restart test of the current national write branch. The four current dry-runs stop before metadata INSERT; new persisted metadata, restart persistence, concurrent duplicate handling and full monitoring lifecycle are not claimed verified.

**6. Search performance with external network blocked**

| Workload | Runs | Minimum s | Average s | Maximum s | Returned exact records/run | Verdict |
|---|---:|---:|---:|---:|---|---|
| single cadastral repeated; sockets blocked | 8 | 0.0468 | 0.0610 | 0.0682 | 25 | PASS |
| large cadastral; all 435 compartments across pages | 3 | 2.2460 | 2.5939 | 3.1185 | 435 | PASS |
| cross-region cohort VIDZEME | 5 | 0.0430 | 0.0465 | 0.0517 | 25 | PASS |
| cross-region cohort LATGALE | 5 | 0.0613 | 0.0738 | 0.0877 | 24, 25, 26 | PASS |
| cross-region cohort KURZEME | 5 | 0.0514 | 0.0598 | 0.0644 | 25 | PASS |
| cross-region cohort ZEMGALE | 5 | 0.0392 | 0.0540 | 0.0722 | 22, 24, 25, 26 | PASS |
| four-region sequential search batch | 3 | 0.2612 | 0.2872 | 0.3388 | 99 | PASS |
| spatial bbox; four regions x three repeats | 12 | 0.0654 | 0.0834 | 0.1061 | 42, 52, 63, 74 | PASS |

The large multi-compartment search used real local designation `36680080065` and collected all 435 unique records across five frontend-sized pages on each run. BBox searches independently recomputed the expected ID set from the local WGS84 RTree plus exact `intersects()` and matched 74/52/63/42 records in the four regions. The four-region batch performs four sequential searches, 99 records in total. Separate five-unit regional cohorts cover all 20 selections.

Exact queries use `cadastre_idx`; native spatial relationship discovery uses the RTree followed by compartment primary-key lookup. No network attempt occurred in the completed local run. Timings include in-process request validation, route execution, geometry operations and JSON serialization; they exclude real HTTP network latency and do not establish concurrent-user throughput or cold-cache percentiles.

Slowest measured path: retrieving the 435-record unit across five pages (2.2460–3.1185 s, average 2.5939 s). Code inspection shows exact and spatial candidate relationships are recalculated for every page, then the result list is sliced. Recommend a bounded, dataset-versioned/parcel-versioned search-result cache or server cursor so later pages reuse computed relationships; preserve account-sensitive import-status checks. Evaluate indexes/plans and use low-impact concurrency profiling before changing query logic. No performance fix was made.

**7. Why 1,723 invalid originals differ from 2,152 repair flags**

Every one of the **2,152 flagged rows** was freshly compared with its original SHP record, including rows with invalid-native flags. Results:

| Stored repair text | Native/source validity | Rows |
|---|---|---:|
| `Source invalid; display-only make_valid` | Invalid | 1,717 |
| `Display normalization repair; original preserved` | Invalid | 6 |
| `Display normalization repair; original preserved` | Valid | 429 |
| **Total repair flags** | | **2,152** |
| **Invalid originals** | 1,717 + 6 | **1,723** |

The counts measure different sets. During ingestion, invalid source geometry is retained as native/original WKB while a separate polygon is normalized for display. Even a valid source polygon can become topologically invalid through coordinate transformation/numerical effects; the display validation/repair branch then flags it. In six source-invalid cases that display branch also ran, so their text describes display repair although their native geometry is invalid. The report’s `repaired` field is computed from `geometry_valid=0`, counting invalid natives rather than all repair-flagged rows.

Verified for all 2,152: **0 raw-source/stored-original WKB mismatches; 0 invalid display polygons; 0 validity-flag mismatches; 0 importable repair-flagged rows**. Raw and stored SHA256 hashes, source file/row references and native validity errors are retained in `quality.json`. **Original geometry was not overwritten.**

Remaining risks: misleading single `repaired` counter; repair text alone does not identify native validity; display repair does not legitimize a source boundary; strict cross-source containment can reject tiny precision slivers; simple sector boundaries cannot represent holes/MultiPolygon. The earlier full scan found 26,312 geometry-ineligible records (2,152 repair-flagged plus 24,160 other unsupported geometries). No repair/import exclusions were changed.

**8. Existing failures and operational impact**

Live LVM: the deployed health endpoint returned HTTP 200 / `UNAVAILABLE`, WMS=false, WFS=false, zero layers. Four direct bounded GetCapabilities probes (maps/vector × WMS/WFS) resolved `geoserver.lvmgeo.lv` to **195.13.215.225** but all returned **`ConnectTimeout`**, around three seconds per probe. There was no HTTP response or capabilities document to inspect. This identifies a connection-stage failure on the tested path; it does not distinguish remote outage, filtering/firewall or routing, and does not prove that the configured URL paths are stale. The generic application error is `LVM GEO unavailable or request timed out`.

Staging conflict: `staging-acceptance.json` still contains `status=RUNNING`, `cases=[]`; the same release’s `publication-check.json` says `staging_acceptance=PASSED`, `activated=true`. Publication evidence timestamp: 2026-11-06T19:18:45.041592+00:00; staging file last modified later: 2026-11-06T19:30:53.861550+00:00. The verifier writes RUNNING to a fixed evidence filename before running; a later interrupted/failed rerun can replace successful proof. The surviving files are inconsistent, so a historical successful write/persistence run cannot be freshly established from them. The publisher currently requires PASSED; it would reject this staging file now. No publication/activation/restart was attempted.

Newly confirmed compatibility finding: three already-imported source polygons for `40940020002` are not fully contained under the current exact VZD rule. Their native outside areas are:

| Existing sector | Source ID | Outside VZD parcel m² |
|---|---|---:|
| 31 | `VMD:nodala2651:49703938` | 0.000946553162 |
| 33 | `VMD:nodala2651:49703942` | 0.005656028169 |
| 32 | `VMD:nodala2651:49703946` | 0.000021943361 |

The retry preview reports `Robežu neatbilstība — nepieciešama pārbaude` before existing-source duplicate status is evaluated. No duplicate or overwrite occurred. Existing persisted sector boundaries/metadata still match the originals and remain available for monitoring.

| Finding | Local cadastral search | Map rendering | Sector registration | Production monitoring |
|---|---|---|---|---|
| Live LVM connection timeouts | No impact observed; local test passed with sockets blocked | Local VMD vectors pass; optional LVM WMS overlays unavailable | Local VMD dry-runs pass | Local GPS math unaffected; any feature requiring live LVM layers remains unavailable |
| RUNNING/PASSED evidence conflict | No runtime effect observed | No runtime effect observed | Preview works; release acceptance/new write-persistence evidence incomplete | Does not directly stop existing sectors; blocks a defensible full release-readiness claim |
| Native-invalid/display-repair records | Search can show review records | Valid display geometry, flagged for review | All flagged rows remain nonimportable | No new flagged geometry introduced into sectors |
| Repair counter semantics | Metadata count misleading | Does not change coordinates | Restrictions remain correct | Operational reporting/review risk |
| Tiny boundary slivers in three existing sectors | Returns review classification | Existing stored boundaries still match | Retry rejected before duplicate status | Existing geometry still usable; source association needs review |
| 34 sample centroids outside own polygon | Centroid remains mathematically valid | Marker/focus need not lie inside polygon | Four interior-point checks pass | Do not treat a centroid as proof of inside-boundary location |
| Frontend/backend | No new request/ID/area mismatch in 20 cases | 497 exact features match; zero JS errors | Four live preview dialogs pass | Full operational lifecycle not run |

**9. Recommended fixes and readiness assessment**

1. Separate `native_invalid`, `display_repaired` and `repair_flagged_total` counters. Report the six-row overlap and preserve both original/display WKB.
2. Store acceptance output in unique per-run files; atomically attach completed successful evidence to a release. Preserve failed/running runs without overwriting the successful record. Repeat the full national persistence/duplicate/restart acceptance in a disposable environment when authorized; do not use production test sectors.
3. Investigate TCP/TLS/routing/firewall access to the LVM host from production, then validate actual capabilities documents. Keep local VMD testing and registration independent of this optional service.
4. Reconcile VMD/VZD source precision and dates for boundary slivers. Any tolerance requires a documented accuracy policy and audited review; do not buffer, clip or silently auto-approve. Consider reporting existing-source duplicate state separately from cadastral review so retry messages explain both.
5. Reuse versioned spatial relationship results across pages with bounded caching/cursors; benchmark concurrent users separately.
6. Use representative interior points when an inside-polygon marker/test point is required. Supply an authoritative native-CRS country boundary for precise national-border tests.
7. Keep unsupported multipart/holes and repaired polygons review-only until sector storage/monitoring support them fully. Validate the current national write/persistence/metadata branch and monitoring lifecycle in an isolated test before broad production sign-off.

| Requested verdict | YES / NO | Scope and reason |
|---|---|---|
| DATABASE READY | **YES** | Local indexed snapshot is usable; known invalid originals are preserved and quarantined from import |
| CADASTRAL SEARCH READY | **YES** | 20/20 real units pass API/DB/source checks with external network blocked |
| MAP READY | **YES** | Local VMD Leaflet vectors, click data and geometry pass; optional LVM basemap/overlay service remains unavailable |
| SECTOR IMPORT READY | **YES** | Supported, source-exact, valid, parcel-contained simple polygons pass four regional dry-runs and geometry/organization/duplicate checks; this is conditional readiness, not a newly exercised production write transaction |
| FOREST AI PRODUCTION READY | **NO** | Full current national write/restart/monitoring acceptance remains unverified and retained release evidence conflicts; remaining boundary/reporting issues need resolution. This NO is not imposed by optional LVM availability alone |

No test that was not run is counted as a pass. Exact national-border containment, new write/restart persistence, concurrent insert races, alert delivery and satellite/model monitoring remain outside this read-only run. The local database/search/map/dry-run outcomes stand independently of external LVM service availability.
