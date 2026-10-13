# Rīgas meži — Architecture: Verified vs. Target Forest AI Integration

Status: proposal, not implemented
Date: 2026-10-13
Companion: `docs/rigas-mezi-real-infrastructure.md` (evidence and sources)

The two diagrams below are deliberately separate. Diagram 1 contains only CONFIRMED relationships. Diagram 2 is a proposal.

---

## 1. VERIFIED ARCHITECTURE (confirmed relationships only)

Source: LAD56 final report §3, §13, §17, unless noted.

```
                    ┌──────────────────────────────────────────┐
                    │  MDPS central database (PostgreSQL)      │  since 2017
                    │  stands, cirsmas, operations, ĪADT,      │
                    │  biotopes, properties, mežniecības, ...  │
                    └──┬───────────┬───────────┬───────────┬───┘
                       │           │           │           │
               FOREMS desktop   Go GIS web   QGIS (direct  │ sync (structure
               (front-end)      (SunGIS,     connection,   │ matches MVR)
                                 front-end)  can edit)     ▼
                                               │        VMD Meža valsts reģistrs
                                               │
                                    GeoPackage packages
                                     ┌─────────┴─────────┐
                                     ▼                   ▼
                                   QField          IntraMaps Roam
                                (mobile, outside   (mobile, outside
                                 central DB)        central DB)

  Palma Timber ── work orders (PDF) ──────────────► contractors / forest machines
  forest machines ── harvested volumes (StanForD) ─► imported into the IS ─► settlement docs

  MDPS planning env ── OIN digital work order + tech map ──► forest machine   (LAD56 pilot)

  Open data used by RM: DAP Ozols, VZD cadastre, LĢIA Lidar, Silava DTW
  Sentinel-2 used manually by RM to verify harvest results  (LAD56 §17)
```

**Not shown, because unverified:** PostGIS · Horizon · LAD integration · whether Palma writes directly into the MDPS DB · whether QField/Roam send data back · any API, WMS or WFS.

---

## 2. TARGET FOREST AI ARCHITECTURE (proposal)

### 2.1 Principle

Forest AI does not replace or duplicate any RM system. It reads **official intent** (what was approved) from RM and compares it to **independent evidence** (what actually happened):

```
 OFFICIAL INTENT (from RM)                 INDEPENDENT EVIDENCE (Forest AI)
 ───────────────────────────               ─────────────────────────────────
 approved cirsmas + boundaries (MDPS/OIN)  Sentinel-1/2 change detection
 planned / completed operations (MDPS)     Telegram GPS check-ins + live routes
 restrictions: ĪADT, micro-reserves,       field photos (before/after)
   biotopes, buffers (MDPS)                truck reports
 harvested volumes (StanForD via Palma)    (later) weighbridge, telematics
                    │                                   │
                    └──────────────┬────────────────────┘
                                   ▼
                    FOREST AI CROSS-CHECK ENGINE
                    · change outside approved cirsma
                    · change inside restricted area
                    · activity in a cirsma with no active operation
                    · machine volume vs. planned volume
                    · no satellite change where harvest is reported done
                                   ▼
                    AI INSPECTOR → risk (with evidence chain) → human decision
                                   ▼
            ┌──────────────────────┴───────────────────────┐
     Forest AI dashboard + Telegram           FOREST_AI_RISKS layer back to RM
                                              (GeoPackage → QGIS / MDPS)
```

### 2.2 Data flow: outbound-only, client-controlled

Because of RM's national-security status, the default design **never requires an inbound connection into RM's network**.

```
 RM network                                     Forest AI (RM instance)
 ──────────                                     ───────────────────────
 MDPS DB ──► export job (SunGIS/RM IT) ──► .gpkg ──┐
 Palma / IS ──► StanForD files (copy) ────────────┤  push over HTTPS
                                                  ├──────────────────► /api/ingest/{source}
 [optional later] Forest AI Connector             │   (token, IP allowlist,
   (small service inside RM network,              │    checksum, audit log)
    read-only DB role on export views,  ──────────┘
    pushes outbound only)
```

Three access levels, offered in order:

| Level | Mechanism | RM effort | Freshness | When |
|---|---|---|---|---|
| **L0** | Manual upload of .gpkg + StanForD files in Forest AI admin UI | Minimal: someone exports a file | Manual | Pilot, week 1 |
| **L1** | Scheduled export (nightly .gpkg + StanForD drop) pushed to the ingest endpoint or SFTP | SunGIS/IT sets up a cron export | Daily | After pilot approval |
| **L2** | On-prem connector with a read-only role on dedicated views (`forest_ai_export.*`), push only | Security review + views | Hourly | Production contract |

The **same normalization layer** consumes all three levels. L0 is not throwaway work.

### 2.3 Adapter set (deliberately small)

| Adapter | Input | Produces in Forest AI | Priority |
|---|---|---|---|
| `mdps_gpkg` | GeoPackage export (L0/L1) or views (L2) | sectors (= cirsmas/stands), restrictions, operations, mežniecības | **P1** |
| `stanford` | StanForD `.hpr/.prd` (and `.oin` if available) | harvest production records, machine positions if present, approved machine boundaries | **P1** |
| `sentinel` | existing | change detections | connected |
| `rm_risks_export` | Forest AI risks | `FOREST_AI_RISKS.gpkg` for QGIS | P2 |
| `field_gpkg` | QField/Roam returned packages (only if RM collects data) | observations, photos | P3 |
| Go GIS services / Horizon | — | — | P3, only if a real need appears |

**No adapters for FOREMS, Go GIS, QGIS, QField or Roam as data sources.** They are front-ends to the same database. One MDPS adapter covers all of them.

### 2.4 Normalization rules (non-negotiable)

- Every imported record keeps `source_system`, `source_id`, `source_file`/`sync_run_id`, `imported_at`, `source_valid_at`.
- Imported data is **official intent**, stored read-only. Forest AI never edits it. Corrections happen in MDPS.
- Missing ≠ zero. Fields absent from the export are `NULL` and displayed as "nav datu" / UNKNOWN, never as 0.
- CRS: keep the original geometry and record its CRS (expected LKS-92 / EPSG:3059, to be confirmed). Transform to WGS84 only for display.
- Every risk built on imported data links to the exact sync run, so the auditor can see which version of the plan the risk was judged against.

---

## 3. The "separate account" for Rīgas meži

### 3.1 Current state (from project memory, verify against `database.py` before building)

Forest AI today is **single-tenant**: one SQLite DB with no organization/tenant column, one HTTP Basic Auth user, one Telegram bot, one dispatcher chat. The Biķernieki storm case lives in the same DB as all demo data.

### 3.2 Options

| | A. Dedicated instance per client | B. Multi-tenant (`org_id` everywhere) |
|---|---|---|
| Work | Small: new folder/DB, `.env`, systemd units, subdomain, separate bot token | Large: `org_id` on 16+ tables, every query filtered, auth rework, migration |
| Isolation | Physical: separate DB, process, credentials | Logical, relies on every query being correct |
| Fit for national-security client | **Strong.** Can later move to an EU region or RM's own server unchanged | Weak. Data co-mingled with other clients |
| Scales to many clients | Poorly beyond ~5–10 | Well |

**Recommendation: A now, B later.** Rīgas meži gets its own instance (e.g. `rigasmezi.forest-ai.<domain>`), with its own DB, credentials, Telegram bot and dispatcher chat. The same code version runs everywhere, deployed from one repo with per-instance `.env`. Revisit multi-tenancy when there are 3+ paying clients.

The Biķernieki storm case moves into this instance as the first real RM sector (it was already planned to move to a separate account later).

### 3.3 Spatial capability: decision required

RM scale is about 63,000 ha, with tens of thousands of stands. Cross-checks such as "change polygon intersects cirsma but not restriction buffer" are spatial joins. SQLite without a spatial extension is the wrong tool for this at that scale.
Options: SpatiaLite (smallest change) or PostgreSQL + PostGIS for the RM instance (which matches RM's own stack).
**Decide after the repo inspection.** Do not decide from memory.

---

## 4. Integration priority matrix

Scores 1–5. For **Ease**, 5 = easiest, so higher is always better and totals are comparable.

| Integration | Data value | Technical accessibility | Risk detection value | Client relevance | Ease | Total |
|---|---|---|---|---|---|---|
| MDPS GeoPackage export (L0/L1) | 4 | 4 | 5 | 5 | 5 | **23** |
| StanForD production files | 5 | 3 | 5 | 5 | 3 | **21** |
| MDPS read-only views (L2) | 5 | 2 | 5 | 5 | 2 | 19 |
| OIN work orders (approved machine boundaries) | 4 | 3 | 5 | 4 | 3 | 19 |
| FOREST_AI_RISKS → QGIS (output) | 2 | 5 | 3 | 4 | 5 | 19 |
| Open data fetched by Forest AI itself (DAP Ozols, VZD) | 3 | 4 | 3 | 3 | 4 | 17 |
| QField / Roam returned observations | 2 | 2 | 3 | 3 | 3 | 13 |
| Go GIS web services | 2 | 2 | 2 | 3 | 3 | 12 |
| Horizon | 2 | 1 | 2 | 2 | 1 | 8 |

**Priority 1:** MDPS export (start at L0) + StanForD files
**Priority 2:** OIN boundaries (only if not already in the MDPS export) · FOREST_AI_RISKS layer back to QGIS · L2 views
**Priority 3:** field observations · Go GIS services · Horizon

---

## 5. Answer: smallest number of integrations for maximum data

**Two integrations, on top of what Forest AI already has.**

1. **MDPS data export.** One adapter replaces separate integrations with FOREMS, Go GIS, QGIS, QField and Roam, because those are all front-ends to the same PostgreSQL database. It provides sectors/cirsmas, operations, restrictions, mežniecības and (possibly) imported harvest volumes.
2. **StanForD harvest files.** These are machine-produced evidence that does not depend on contractor reporting. It may turn out to be unnecessary if MDPS already stores imported volumes with enough detail. Check this with question 9 before building.

Plus the existing **Sentinel** layer and **Telegram GPS/photo** evidence. These are independent of RM and are what makes Forest AI more than a viewer of RM's own data.

Recommended first adapter: **`mdps_gpkg` at L0 (manual upload).** It needs no security approval, uses a format RM already produces for QField and Roam, and lets the pilot run on real RM geometry within days.

---

## 6. Phased plan

| Phase | Scope | Exit criterion |
|---|---|---|
| **0. Prerequisites** | Repo inspection; fix the before/after "same place" false-match bug; decide on spatial storage | Docs match code; photo comparison trustworthy |
| **1. RM instance** | Dedicated instance, own bot, own credentials; move Biķernieki case into it | RM user logs in to an instance holding only RM data |
| **2. L0 MDPS import** | Upload `.gpkg` → validate → normalize → sectors + restrictions on the map | One mežniecība's real cirsmas visible with source attribution |
| **3. Cross-check v1** | Sentinel change vs. approved cirsmas and restrictions → risk with evidence | Inside-cirsma change is not flagged; outside or restricted change is flagged with evidence |
| **4. StanForD** | Parse production files; link to cirsma; positions if present | Volume and location per cirsma shown next to plan |
| **5. Output to RM GIS** | `FOREST_AI_RISKS.gpkg` export | RM GIS user opens risks in QGIS |
| **6. L1/L2** | Scheduled export or connector | Data refreshes without manual upload |

### FOREST_AI_RISKS layer (output schema draft)

`risk_id, geometry, cirsma_id, sector_code, risk_type, severity, confidence_category, detected_at, evidence_summary, evidence_url, status, decided_by, decided_at, source_sync_run`

Confidence is a category (`zema / vidēja / augsta`), not a percentage. Status distinguishes AI suspicion from human-confirmed.

---

## 7. Integrations page: target structure

**RĪGAS MEŽI — CORE SYSTEMS**

| Card | Badge | Note shown on card |
|---|---|---|
| MDPS (central DB) | HIGH PRIORITY · Awaiting export | "One integration covers FOREMS, Go GIS, QGIS, QField, Roam" |
| Palma Timber / StanForD | HIGH PRIORITY · Awaiting sample file | "Machine production data" |
| FOREMS | Front-end of MDPS | No separate integration |
| Go GIS (SunGIS) | Front-end of MDPS | MDPS vendor |
| PostgreSQL / PostGIS | Verification | PostGIS unconfirmed |
| QGIS | Output channel | Receives FOREST_AI_RISKS layer |
| QField · IntraMaps Roam | Field GIS (GeoPackage) | Data return unconfirmed |
| Sentinel-1/2 | CONNECTED | — |

**OPTIONAL / CONTRACTOR SYSTEMS** (collapsed by default, with the label "Not confirmed in use by Rīgas meži"): PONSSE Manager, John Deere, Komatsu, Fleet GPS, weighbridge, Planet, Horizon.

Badges must reflect real state. Nothing shows "Connected" unless data has actually flowed.
