# Forest AI: nationwide cadastral and VMD data — technical decision report

**Date:** 2026-11-06. **Scope:** source audit, anonymous access probes, local read-only validation and implementation design. No application/UI files, production records, datasets or services were changed for this report. A nationwide implementation is **not yet complete**.

## 1. Decision

Nationwide public-data acquisition is technically and legally viable using the official bulk downloads. No paid cadastral API or new credentials are required for that route. The immediate constraints are missing ingestion/indexing and the existing association policy, rather than unavailable public sources.

Build a versioned national geodata catalogue alongside the existing operational database. Load all five VMD regional archives and the VZD parcel records from all 42 municipal archives. Resolve the exact VZD land unit first, then query VMD by both its reported cadastral attribute and actual geometric intersection. Keep those two types of evidence separate. Preserve the existing FastAPI, SQLite operational sectors, authentication, Leaflet and Esri basemap.

Use the working bulk downloads as the primary source. Treat live WFS as an optional future adapter until connectivity and query behaviour are verified. Do not use cadastral WMS/tiles to reconstruct vector geometry.

## 2. What is actually loaded

Only **Centra**, not all Latvia, is indexed in `data/vmd/compartments.sqlite`. Its original files are under `data/vmd/source/centra_data/centra/`.

| Loaded layer | Source records |
|---|---:|
| nodala2651 | 92,079 |
| nodala2652 | 79,970 |
| nodala2653 | 114,627 |
| nodala2654 | 116,100 |
| nodala2655 | 111,000 |
| **Total** | **513,776** |

All 513,776 records have an 11-digit numeric `kadastrs` stored as text; leading zeros are preserved. The index `cadastre_idx(kadastrs,kvart,nog)` exists, and EXPLAIN QUERY PLAN confirms an indexed exact lookup. The RTree also contains 513,776 entries. The catalogue reports 513,421 unmodified valid geometries, 355 repaired display geometries and zero failed features. Original source geometry remains separately retrievable. There are 8,101 duplicate groups for the insufficient legacy tuple `(kadastrs,kvart,nog)`; there are no duplicate qualified source IDs. A national catalogue must not use that legacy tuple alone as its primary key.

WGS84 extent: **22.4427017–25.5504795 E, 56.2523705–57.4100612 N**. This is a feature-envelope extent, not an administrative coverage polygon or a statement that every parcel inside it has forest inventory. Source municipality attributes include Bauskas, Dobeles, Jelgavas, Mārupes, Ogres, Olaines, Ropažu, Salaspils, Saulkrastu, Siguldas, Tukuma, Ādažu and Ķekavas novadi, plus Jelgava, Jūrmala and Rīga. Detailed municipality counts are in the saved local coverage audit.

Dates must be distinguished:

- VMD publication describes the current release as prepared **2026-10-07**.
- Original Centra DBF headers report **2026-10-08**.
- The official Centra archive upload was last modified **2026-10-14**.
- The local index was built **2026-10-30**.
- VZD archive DBFs held locally were exported **2026-10-31**. Their `GEOM_ACT_D` attributes can be much older and describe individual geometry updates, not archive freshness.

The local source is a repackaged `centra_data.zip`; its hash differs from the official `centra.7z` container. Existing provenance verification establishes byte equality for all 25 extracted source files. Those two container hashes must not be presented as the same archive hash.

### A second, independent limitation

The current cadastral resolver `services/geodata/cadastral_authority.py` reads one JSON file per designation. It has **seven** extracted land units, not a national parcel index. Four complete municipal archives are present locally but mostly unused by the resolver:

| VZD archive already downloaded | KKParcel rows in archive | Exposed parcel snapshots |
|---|---:|---:|
| Rīga | 53,200 | 2 |
| Bauskas novads | 36,227 | 1 |
| Ropažu novads | 20,048 | 3 |
| Daugavpils | 21,048 | 1 |

Thus even a genuine VMD match can remain unavailable for registration solely because its VZD parcel was never extracted. Adding more example JSON files is not a nationwide solution.

## 3. Available forestry sources and missing archives

[Official VMD catalogue](https://data.gov.lv/dati/dataset/meza-valsts-registra-meza-dati): SHP packages by five forestry regions, CC0 1.0, quarterly publication. These are public bulk resources, not restricted service scraping.

| Regional archive | Exact compressed bytes | Local status | Anonymous probe |
|---|---:|---|---|
| [Austrumu](https://data.gov.lv/dati/dataset/40014c0a-90f5-42be-afb2-fe3c4b8adf92/resource/584ce572-e3f9-4fb4-94a6-7fc8c4c34330/download/austrumu.7z) | 121,227,785 | **Missing** | HTTP206; 7z signature |
| [Centra](https://data.gov.lv/dati/dataset/40014c0a-90f5-42be-afb2-fe3c4b8adf92/resource/392dfb67-eeeb-43c2-b082-35f9cf986128/download/centra.7z) | 107,400,185 | Loaded | HTTP206; 7z signature |
| [Dienvidu](https://data.gov.lv/dati/dataset/40014c0a-90f5-42be-afb2-fe3c4b8adf92/resource/bbf4820e-4b77-4563-bc12-dc95df1cec60/download/dienvidu.7z) | 118,706,317 | **Missing** | HTTP206; 7z signature |
| [Kurzemes](https://data.gov.lv/dati/dataset/40014c0a-90f5-42be-afb2-fe3c4b8adf92/resource/5019d0a9-cf54-4509-8753-d4c159a872a8/download/kurzemes.7z) | 138,430,114 | **Missing** | HTTP206; 7z signature |
| [Vidzemes](https://data.gov.lv/dati/dataset/40014c0a-90f5-42be-afb2-fe3c4b8adf92/resource/9a755463-7271-41a1-9ee6-fce76e68e146/download/vidzemes.7z) | 166,700,310 | **Missing** | HTTP206; 7z signature |

All five current resources advertise the October7 release. Upload dates are October14 except Vidzemes October9. All five URLs were probed successfully without credentials using bounded byte-range reads. This verifies access, not full archive integrity, schemas, feature counts or national completeness. Those checks belong to ingestion.

Total VMD download: **652,464,711 bytes**. The four missing archives total **545,064,526 bytes**. Their feature counts have not been measured; no national record total is claimed.

Official regional allocation PDFs are linked from the catalogue. Use those and the actual source metadata to assess regional completeness; do not infer region membership from the approximate extent of existing forest polygons.

## 4. Authoritative cadastral sources, access, licence and cost

| Source | Useful data | Access/cost | Verified state |
|---|---|---|---|
| [VZD open spatial SHP](https://data.gov.lv/dati/dataset/kadastra-informacijas-sistemas-atverti-telpiskie-dati) | KKParcel polygon, exact `CODE`, source attributes/CRS | Public anonymous download; CC BY4.0; retain VZD attribution; no data fee | **All42 municipal URLs** returned HTTP206 and ZIP signatures |
| [VZD open XML](https://data.gov.lv/dati/dataset/kadastra-informacijas-sistemas-atvertie-dati) | Structured cadastral objects/property composition; potential explicit property-to-land-unit resolution | Public bulk downloads; CC BY4.0 | Catalogue inspected; not ingested or used as an inferred membership crosswalk |
| [INSPIRE WFS](https://data.gov.lv/dati/dataset/kadastrlie-zemes-gabali-inspire-wfs) | Published nationwide vector download service | Officially advertised open service; no secret endpoint/key invented | Published DPPS endpoint **ConnectTimeout** from this server; GetCapabilities/schema/query behaviour not verified |
| [INSPIRE Atom/GML](https://data.gov.lv/dati/dataset/kadastrlie-zemes-gabali-inspire-wfs1) | Advertised bulk GML download | Public service listing | Catalogue exposes a generic GeoLatvija link, not a verified feed URL; direct feed discovery remains pending |
| WMS/public tiles | Reference images only | Source-specific viewing terms | **Not a vector polygon source**; excluded from geometry derivation |
| Authenticated owner/private-data services | Restricted or identified-person information | Separate rights/contracts may apply | Not needed for public geometry lookup; not requested or accessed |

[VZD's service description](https://www.vzd.gov.lv/lv/pakalpojumi/Kisad2) identifies the open-data service as free and available to any person. No new credentials, paid account or permission request is needed for the verified public SHP downloads. The INSPIRE catalogue lists CC0, while VZD spatial SHP explicitly lists CC BY4.0; retain resource-specific licences and VZD attribution rather than treating all variants as interchangeable. This report does not claim that open geometry includes personal ownership information or establishes access rights to land.

The 42 SHP resources advertise **520,915,216 compressed bytes**, updated weekly; current catalogue snapshot October31. Combined current VMD and VZD spatial downloads total **1,173,379,927 bytes**. All probes are saved with URLs, response codes, signatures and modification dates. No full nationwide download was performed during this report phase.

A connection timeout does not establish an authentication requirement. Do not ask the user for an invented WFS API key. If WFS is later required, confirm the exact endpoint, access policy, supported filters/CRS and operational limits with VZD; bulk ingestion does not depend on resolving that service.

## 5. Why the observed identifiers have no matches

`80840050013`, `80600030025` and `80960030024` each exist as exact VZD `KKParcel.CODE` records in the official Ropaži archive. Each has zero raw VMD `kadastrs` matches and zero actual VMD polygon intersections in the loaded snapshot. Other source records share their cadastral prefixes, so regional absence cannot honestly be inferred for those three parcels.

This establishes that the current open VMD snapshot has no compartment records for those exact land units. It does **not** establish that there is no forest on the land, explain every possible inventory omission, or justify borrowing polygons from another parcel. If the owner expects registered forest inventory there, the next factual source is the corresponding VMD inventory/version information or a provider-confirmed association. A nationwide loader will solve missing-region cases; it cannot create absent inventory for these already-covered examples.

A parcel outside the Centra feature envelope is a different state. For example, official Daugavpils `05000010139` exists with retrieved geometry, but its region's forestry data is not loaded. Its nationwide VMD match count is **unknown**, not proven zero. Source-not-loaded must remain distinct from no inventory record in an available source.

## 6. Fresh verification of 01000950031

The original-source audit was rerun for this report and compared raw DBF attributes and SHP geometry with the read-only index. All six records have raw `kadastrs=01000950031`, quarter268, valid original and normalized geometries, unique qualified IDs, and no duplicate geometries. VZD has exactly one matching parcel; its area is5.179558728ha.

| VMD OBJECTID, layer nodala2653 | Nogabals | Declared ha | Source identifier evidence | Current strict geometry policy |
|---|---:|---:|---|---|
| 70588598 | 15 | 0.50 | Exact original VMD attribute and VZD CODE | Boundary review |
| 70588599 | 16 | 0.11 | Exact original VMD attribute and VZD CODE | Fully contained; eligible |
| 70588600 | 17 | 1.03 | Exact original VMD attribute and VZD CODE | Boundary review |
| 70588601 | 18 | 0.56 | Exact original VMD attribute and VZD CODE | Boundary review |
| 70588602 | 19 | 0.15 | Exact original VMD attribute and VZD CODE | Boundary review |
| 105553907 | 20 | 0.24 | Exact original VMD attribute and VZD CODE | Boundary review |

Declared VMD area totals2.59ha. Overlap with the VZD parcel is99.998079565%–100%; total outside slivers are0.172508858m². These are valid geometries, not invalid polygons. Five are blocked by the current **zero-tolerance containment policy**, which is separate from the exact source-attribute association. Their disconnected appearance does not invalidate the original cadastral attribute. Do not silently repair, clip or buffer them, but do not describe the source identifiers as invented or geometrically invalid either.

Source and cadastral data dates differ. The next design should report source-attribute evidence and geometry-quality/containment results independently; any review/tolerance policy needs an explicit documented decision and must not be represented as legal cadastral precision. Native EPSG:10306 intersection avoids an unnecessary datum transformation between these two current sources. For display in4326, use a verified PROJ operation and record its limitations. The existing builder's blanket “1 metre” metadata must not be generalized into a verified accuracy guarantee; the audited PROJ operation reports unknown ballpark geographic accuracy.

Fresh artifacts: `docs/evidence/nationwide/audit-01000950031/{audit.json,audit.csv,table.md}`.

## 7. Recommended integration architecture

### Ingestion and storage

1. Catalogue-driven manifests for all 5 VMD and42 VZD resources: publisher, licence, source date, URL, modification token, bytes, SHA256, native CRS, per-file schema/count/validity and normalization version.
2. Download to immutable staging directories. Validate archives, CRS/axis order, DBF character fields and geometries before indexing. Do not assume that all regional schemas and layer names match Centra without inspection.
3. Build a **separate geodata store** containing national parcels and forestry features. Reuse SQLite/RTree and bounded GEOS queries initially; nationwide scale has not demonstrated a need to replace the existing database or map library. Benchmark before choosing PostGIS as an additional service.
4. Store unchanged native geometry, exact source attributes and qualified IDs. Keep optional repaired/simplified display geometry separate. Preserve region/version provenance per feature; replace hard-coded Centra titles and single-archive hashes with manifest-derived metadata.
5. Keep existing Centra source IDs/import links compatible. Check regional identifier collisions before publication. Do not regenerate IDs in a way that makes existing sectors appear unimported. Dataset-version changes must not silently overwrite manually edited sectors.
6. Publish only after count, hash, geometry, query and cross-region acceptance checks. Keep the previous immutable release available for rollback. Use bounded chunking and serial/background ingestion to protect the live service. Existing account/sector database remains intact.

### Lookup and evidence classification

1. Validate exactly 11 ASCII digits, keeping leading zeros.
2. Resolve `KKParcel.CODE` in the national authoritative parcel index independently of whether VMD contains a matching attribute. Return parcel-found/source-unavailable/not-found separately.
3. Determine relevant available forestry releases from manifests/official regional allocation; missing/stale/failed regions are explicit availability states.
4. Query exact VMD `kadastrs` and spatial intersections as **two distinct candidate sets**. RTree bounding boxes are only an accelerator; actual native-CRS intersections and areas are then calculated. No nearest-polygon fallback.
5. Classify each result: `source_attribute_exact`, `spatial_candidate_only`, `identifier_conflict`, `boundary_review_required`, `geometry_invalid` or `verified_for_registration`. Preserve the raw identifiers and evidence used for each decision.
6. A spatial candidate without matching source attributes is **derived**, even when fully contained. It is not legal membership or ownership evidence. Do not automatically promote it to a verified import; a provider-confirmed crosswalk/history or an explicitly authorized review policy is required.
7. Compute overlap as native intersection area / compartment area ×100, retain original geometry and disclose any cross-boundary scope. Never use a clipped approximation as the original imported compartment.
8. Return separate parcel and compartment geometry roles, authoritative/derived flags, source/version/date, candidate and verified counts, pagination and explicit unavailable-data state. Cache by parcel and both dataset versions. Keep selection IDs stable across pages and pin the reviewed versions through import.
9. Continue using existing sector registration transactions, server-derived organization/account, duplicate checks, audit/contact fields and main-map integration. Registering a monitoring sector is not a declaration of cadastral ownership.

The existing frontend layout is sufficient for this architecture. Required changes concern data resolution, evidence/status and coverage information, not a visual redesign.

## 8. Validation results and limits

All rows below use real designations independently read from official source records. “Registered” refers to the previously completed full Chromium test in an isolated production database copy, not a new live write during this report phase.

| Municipality | Designation | VZD land unit/geometry | Exact VMD rows in loaded source | Evidence/registration result |
|---|---|---|---:|---|
| Rīga | 01000950030 | Found/retrieved | 209 | Exact VMD attributes; VZD checked;2 selected eligible sectors registered and persisted in copy |
| Rīga | 01000950031 | Found/retrieved | 6 | Exact VMD attributes;1 fully contained sector registered/persisted in copy;5 require boundary review |
| Bauskas novads | 40940020002 | Found/retrieved | 10 | Exact VMD attributes;2 eligible sectors registered/persisted in copy |
| Ropažu novads | 80840050013 | Found/retrieved | 0 | No exact record or geometric intersection in available source; nothing registered |
| Ropažu novads | 80600030025 | Found/retrieved | 0 | No exact record or geometric intersection in available source; nothing registered |
| Ropažu novads | 80960030024 | Found/retrieved | 0 | No exact record or geometric intersection in available source; nothing registered |
| Daugavpils | 05000010139 | Found/retrieved | Current index0; national count unknown | Forestry region not loaded; registration unavailable, not a claim of no forest |

No test establishes successful nationwide forestry matching in Kurzeme, Vidzeme or the missing eastern/southern source releases. Positive forest samples from **every missing archive** must be independently selected from its actual records after ingestion, matched against VZD and tested end-to-end. Invented numbers and successful basemap tiles do not satisfy that gate. Prior automated pass counts do not establish nationwide completeness.

This report phase freshly checked index/schema/counts, seven authoritative parcel lookups, all five VMD resource endpoints, all 42 VZD bulk endpoints and the six raw source records. It did not rerun production imports, alter sectors or deploy an unverified national replacement.

## 9. Effort, infrastructure and permissions

Preliminary estimate for one engineer, reusing the current application:

| Work package | Engineering effort |
|---|---:|
| Manifest/download pipeline, full source validation and regional provenance | 1–2 days |
| National parcel/forest indexes, staged publication and query performance | 1–2 days |
| Exact + spatial lookup, evidence classification and safe import integration | 2–3 days |
| Cross-region real-data acceptance, update/rollback rehearsal and verified cutover | 1–2 days |
| **Total** | **5–9 working days** |

Bulk transfer/decompression/indexing are additional machine time, provisionally hours rather than days, but no nationwide throughput benchmark has been run. Record counts and uncompressed national sizes must be measured during staging; estimates are not commitments. Reserve roughly 20–40GB for initial staging/indexing and more for dual-release retention, then replace that allowance with measured archive/extraction sizes. The host currently reports 73GB free; available disk alone does not prove sufficient CPU/memory headroom for concurrent live traffic and ingestion.

**Data fees:** zero for the verified public bulk routes. **Credentials:** none for those downloads. **Attribution:** retain VZD CC BY4.0 terms and source provenance; VMD catalogue CC0. **Optional private/history/owner services or commercial SLA:** require separate provider confirmation and may introduce fees or authorization; not assumed necessary for public geometry.

Existing shared-account authentication lacks individual profiles; that is an independent audit-identity limitation and must not be “solved” by cadastral data or fabricated user identities. The current organization/account isolation and existing sectors must be preserved.

## 10. Report-first checkpoint

Proceeding from this report means substantive data ingestion and backend integration, not another UI patch. The next measurable milestone is a staged national catalogue with per-archive counts and independently verified positive samples from all five VMD regions. Production publication should follow that evidence, not precede it.

No production implementation, rebuild, database migration, service restart, private-data request or restricted-service scraping was performed for this report. Nationwide lookup remains unfinished; the public source path is verified and the missing work is now explicit.

Evidence bundle: `docs/evidence/nationwide/` contains captured official catalogue metadata, bounded endpoint probes and read-only local audit results. Historical per-parcel source/registration artifacts remain under `data/vmd/`.
