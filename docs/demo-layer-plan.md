# Forest AI — Rīgas meži demo layer: implementation plan

Status: **PLAN ONLY** (2026-10-20). No code, DB or service changes have been made. Not committed.
Code base: MAIN `/root/forest_ai` at **574bd97** (= RM `data/DEPLOYED_COMMIT`). Every `file:line` below refers to that commit.

## Goal in one paragraph

On :8002 (RM), Forest AI is presented as an independent control layer above the client's systems, with two cases:

- **Case 1, REAL:** BIK-001 (storm case). It uses existing data only: risks 59 and 62, the GPS track of session 32 (29 points), 48 photos (sessions 27 and 31), photo-comparison run 1 (30 points), and `BIK_001.png`. Nothing is simulated.
- **Case 2, DEMO:** a new sector **DEMO-01**, named and marked as simulated. Planned volume 200 m³ (MDPS, simulated) is compared with recorded volume 260 m³ (Palma Timber, simulated). Simulated Sentinel-2 change, machine GPS, a photo and a QField/Roam observation corroborate it.
  - Forest AI raises **one** combined risk, `VOLUME_DISCREPANCY_CROSSCHECK`. It starts as a data discrepancy (volume anomaly) and escalates through independent evidence. It never says "illegal logging".
  - Every evidence item carries source system, origin (REAL / SIMULATED), timestamp and a short description, so that **no simulated value can be mistaken for live data.**

## 0. Facts found in the code that shape this plan

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| F-a | The global demo reset deletes **every** `risks.is_demo=1` row. | `services/demo_scenarios.py:943-970` (`DELETE FROM risks WHERE is_demo=1`, `:952`), via `POST /api/demo/reset` (`api.py:1740-1746`) | `is_demo` cannot carry provenance alone (R1). |
| F-b | The per-integration reset deletes `is_demo=1` risks by rule code of the integration's category. | `services/integrations/manager.py:144-185`, `risk_rules.RULE_CODES_BY_CATEGORY` (`risk_rules.py:40-44`) | The new rule code must be scoped deliberately. |
| F-c | `test_connection()` sets `connection_status='CONNECTED'` for demo adapters, and the catalog then displays that status unchanged. | `manager.py:100-112` (`:107`), `manager.py:57-60` | **Today a demo adapter can already appear as "Pieslēgts"**, which violates R2. |
| F-d | The Integrations KPI "Подключено/Pieslēgts" counts demo rows that are CONNECTED. | `index.html:4000` | Must exclude demo rows. |
| F-e | **All three existing demo adapters pick sectors themselves:** "first sectors with a boundary". In RM that is **BIK-001**. Fleet would create a simulated HIGH `FLEET_SECTOR_EXIT` on the **real** sector. | `fleet_gps_demo.py:65-66` (`LIMIT 3`), `sentinel_demo.py:47-48` (`LIMIT 5`), `weighbridge_demo.py:43-45` (`LIMIT 3`) | All demo adapters must be restricted to simulated sectors, which needs a sector-level origin marker. |
| F-f | Category base adapters write domain tables **that have no provenance column**: Fleet → `vehicle_gps_pings` (no is_demo), Satellite → `satellite_observations` (has `source='DEMO'`). | `categories.py:39-54`, `categories.py:74-88`, `database.add_gps_ping` `database.py:1107` | New simulated adapters must not write into provenance-less tables. |
| F-g | `integration_records` already stores every adapter record with `source_provider`, `is_demo`, `source_timestamp`, `raw_payload_json`, `normalized_payload_json`, idempotently via a UNIQUE `deduplication_key`. | DDL `database.py:547-568`, `base.save_data` `base.py:115-142`, `make_dedup_key` `base.py:220-222` | The natural store for simulated raw data. |
| F-h | **Two separate AI paths:** (1) integration rules generate AI inline with `ai_resolution.PROMPT_TEMPLATE`; (2) the background worker skips `is_demo=1` risks entirely. | (1) `risk_rules.py:47-64`, `ai_resolution.py:28-79`; (2) `risk_ai_worker.py:120-121` (`_excluded`), `:177-190` (`_candidates`, SQL `COALESCE(is_demo,0)=0` at `:180`) | R8 must deal with both paths. The plan uses only the worker for the new risk. |
| F-i | `risks.is_demo` is **never shown in the UI**. Demo-scenario risks currently look real in the risk list and detail. | `index.html:2057-2066` (`loadRisks`), `:2092-2236` (`openRisk`); no `is_demo` read in `index.html` outside integrations (`:4001`, `:4041`, `:4109`, `:4125`) | R6 must add an origin badge to the list as well as the detail. |
| F-j | `risks` has no per-risk score column; the sector score is computed by `calc_risk_score()`. | `api.py:102-185` | The R5 score must be stored somewhere auditable (see §2). |
| F-k | The app has a single Basic Auth for every route. | `api.py:67` (`FastAPI(dependencies=[Depends(verify_credentials)])`) | The GeoJSON export inherits auth automatically. |
| F-l | Pillow 12.3 and shapely 2.1 are installed; `ogrinfo` and the `geojson` package are **not**. | `python3 -c 'import PIL, shapely'`; `which ogrinfo` → none | Use shapely for validation; no new dependency. |
| F-m | RM BIK-001 real evidence that exists: | | Stage 3 links it as REAL evidence. |
|  | – work_photos: session 27 = 27 photos (2026-10-09 05:18–05:41 UTC), session 31 = 21 photos (2026-10-10 05:50–06:05 UTC) | RM DB | |
|  | – `photo_cmp_runs` id 1 (2026-10-09 vs 2026-10-10, READY), 30 points | RM DB | |
|  | – session 32 track: 29 points, 05:24:27–05:38:48 UTC | RM DB | |
|  | – `sectors.satellite_file_path = data/sector_satellite/BIK_001.png` | RM DB | |

## 1. Touchpoints

| # | file:line (574bd97) | What changes | Why |
|---|---|---|---|
| T1 | `database.py:55-115` (`_migrate`, risks columns `:80-115`) | Add `risks.data_origin`, `sectors.data_origin`, plus an idempotent backfill. | R1 provenance; sector-level marker for F-e. |
| T2 | `database.py:603-606` (end of `_migrate`, beside `_create_photo_compare_tables`/`_create_risk_conclusion_table`) | New `_create_risk_evidence_table(cur)`. | R1. |
| T3 | `database.py:1183-1199` (`add_incident`) | Add optional `data_origin=None` and `occurred_at=None` parameters; defaults keep every existing caller identical. | One insert path with provenance (removes the `is_demo` "flip after insert" pattern for new code only). |
| T4 | `database.py` (new helpers next to Incidents, after `:1290`) | `add_risk_evidence(...)` (UPSERT on `(risk_id, source_provider, ref_table, ref_id)`), `get_risk_evidence(risk_id)`. | R1, R6, R7. |
| T5 | `services/demo_scenarios.py:943-970` (`reset_demo`) | `DELETE … WHERE is_demo=1 AND COALESCE(data_origin,'DEMO_SCENARIO')='DEMO_SCENARIO'`, plus an opt-in parameter `include_simulated_integrations=False`. | R1: never delete SIMULATED_INTEGRATION rows implicitly. |
| T6 | `api.py:1740-1746` (`/api/demo/reset`) | Pass the optional query flag `?include_simulated=1` through to T5 (default off). | R1, explicit only. |
| T7 | `services/integrations/manager.py:144-185` (`reset_demo`) | Additionally scope the deletion to `data_origin='SIMULATED_INTEGRATION' AND sector IN (simulated sectors)`, and delete matching `risk_evidence`. | Keeps the per-integration reset limited to its own simulated rows. |
| T8 | `services/integrations/manager.py:100-112` (`test_connection`) | For `row.is_demo` → `connection_status='SIMULATED'` (never `CONNECTED`). | R2, F-c. |
| T9 | `services/integrations/manager.py:34-61` (`list_catalog`) | Map `display_status`: demo → "Demo · simulated"; `requires_confirmation` → "Integration requires confirmation". Add `group`, `group_order`, `group_label`, `collapsed_by_default` to each entry. | R2, R3 (data-driven grouping). |
| T10 | `services/integrations/registry.py:28-38` (`ProviderEntry`) | New fields `group: Optional[str] = None` and `real_counterpart: Optional[str] = None`; `status_claim` comment gains `requires_confirmation`. | R2, R3. |
| T11 | `services/integrations/registry.py:41-128` (`_catalog`) | 4 new simulated entries plus 4 `requires_confirmation` real-world counterparts; assign a `group` to every entry. | R2, R3. |
| T12 | `services/integrations/demo/` (new files) | `mdps_demo.py`, `palma_timber_demo.py`, `qfield_demo.py`, `roam_demo.py`, `sentinel2_change_demo.py`, `machine_gps_demo.py`, `field_photo_demo.py` (or one module with 7 small classes; see Q3). | R4. |
| T13 | `fleet_gps_demo.py:65-66`, `sentinel_demo.py:47-48`, `weighbridge_demo.py:43-45` | Restrict sector selection to `sectors.data_origin='SIMULATED'`. | F-e: never touch BIK-001. |
| T14 | `services/integrations/risk_rules.py:40-44` (`RULE_CODES_BY_CATEGORY`), plus a new function after `:215` | `check_volume_discrepancy_crosscheck(sector_name)` and its constants; register the rule code under `"timber"`. | R5. |
| T15 | `services/risk_ai_worker.py:120-121` (`_excluded`), `:177-190` (`_candidates`) | Allow `is_demo=1 AND data_origin='SIMULATED_INTEGRATION'`; keep excluding `DEMO_SCENARIO` and TEST. | R8: the simulated risk gets worker analysis. |
| T16 | `services/risk_ai_worker.py:306-320` (`_build_prompt`), `:247-304` (`_sector_facts`), `:41-75` (template) | Facts: "Data origin" line plus an evidence list with origins. Template: `{origin_rule}` slot appended after rule 7, empty for REAL risks. | R8. |
| T17 | `services/risk_ai_worker.py:326-339` (`_valid_recommendation`) | For SIMULATED_INTEGRATION: the summary must contain the language's simulated marker; reject wording of illegality. | R8 enforced, not just requested. |
| T18 | `api.py:1507-1544` (`get_risk_detail`) | Add `risk["evidence"] = get_risk_evidence(risk_id)` and `risk["data_origin"]`. | R6. |
| T19 | `api.py` (new route after `/api/report/pdf`, `:1969`) | `GET /api/export/risks.geojson`. | R7. |
| T20 | `index.html:2092-2236` (`openRisk`, insert after the reason block at `:2158-2163`) | "Pierādījumi" (evidence) list with source and origin badge; a red/amber banner on SIMULATED risks. | R6. |
| T21 | `index.html:2057-2066` (`loadRisks`) | A small origin badge next to the level badge. | F-i. |
| T22 | `index.html:3997-4011` (`loadIntegrations` KPIs), `:4013-4052` (`renderIntegrationCards`), `:3962-3969` (`statusBadgeClass`), filter bar `:619-630` | Group rendering from API fields; the KPI excludes simulated; badge classes for the new statuses. | R2, R3. |
| T23 | `assets/i18n-lv.js` (EXACT `:27+`, near `:79-80`, `:99`, `:256`) | LV strings: "Demo · simulēts", "Integrācija jāapstiprina", group names, "Pierādījumi", "Reāls", "Simulēts", banner text. | Every new UI string needs LV. |
| T24 | `scripts/seed_demo_layer.py` (new) | Idempotent creation of DEMO-01 plus integration rows plus a sync run, and the REAL evidence backfill for BIK-001; `--target-db`, `--allow-main`, `--reset`. | R9. |
| T25 | `tests/test_demo_layer.py` (new) | Unit tests on a temp DB, following `tests/test_integrations.py:1-35`. | Acceptance. |

## 2. Schema changes (additive only, idempotent, in `_migrate`)

### 2.1 Choice of design (R1)

| Option | What it needs | Verdict |
|---|---|---|
| A. `risks.is_demo` only | nothing | **Rejected.** It is wiped by the global reset (F-a), cannot tell a demo scenario from a simulated integration, and records no source system per evidence item. |
| B. `integration_records` only (`source_provider`, `is_demo`, `linked_table`/`linked_id`) | no new table | **Rejected as the sole carrier.** Each record links to **one** domain row; there is no risk→many-evidence relation. REAL evidence (Telegram GPS, photos, photo comparison) is not in `integration_records` at all (it comes from `bot.py`, not adapters), and copying it in would invent fake "integrations". |
| C. `risks.data_origin` + `risk_evidence` (+ `sectors.data_origin`) | 3 columns, 1 table | **Chosen.** `risk_evidence` is a thin join table: it *points to* `integration_records` for simulated data and to `session_track_points`/`work_photos`/`photo_cmp_runs`/`sectors` for real data. Nothing is duplicated, every item carries origin and source, and it is the smallest design that satisfies R1, R6 and R7. |

`sectors.data_origin` is needed because of F-e: adapters must select "simulated sectors only", and the GeoJSON export and UI must be able to mark a whole sector as simulated.

The per-risk crosscheck score (F-j) is **not** stored in a new column. Every (re)score writes a `risk_events` row `CROSSCHECK_SCORED` whose `details` are JSON `{score, level, deviation_pct, corroborating_sources, components}`. That gives an audit trail for free; the export reads the latest one.

### 2.2 Statements

```sql
-- via _add_column_if_missing (database.py:48-53), so they run once:
ALTER TABLE risks   ADD COLUMN data_origin TEXT;   -- 'REAL' | 'DEMO_SCENARIO' | 'SIMULATED_INTEGRATION'
ALTER TABLE sectors ADD COLUMN data_origin TEXT;   -- 'REAL' | 'SIMULATED'

-- idempotent backfill (only rows still NULL):
UPDATE risks SET data_origin = CASE
    WHEN COALESCE(is_demo,0)=0 THEN 'REAL'
    WHEN rule_code IN ('FLEET_SECTOR_EXIT','SATELLITE_UNREGISTERED_CHANGE',
                       'WEIGHBRIDGE_WAYBILL_MISMATCH','TIMBER_VOLUME_OVER_PERMIT') THEN 'SIMULATED_INTEGRATION'
    ELSE 'DEMO_SCENARIO' END
WHERE data_origin IS NULL;
UPDATE sectors SET data_origin='REAL' WHERE data_origin IS NULL;

CREATE TABLE IF NOT EXISTS risk_evidence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id         INTEGER NOT NULL,
    source_provider TEXT    NOT NULL,   -- registry provider key, or 'telegram_bot' / 'photo_compare' / 'sector_satellite_file'
    data_origin     TEXT    NOT NULL,   -- 'REAL' | 'SIMULATED'
    evidence_type   TEXT    NOT NULL,   -- PLANNED_VOLUME | RECORDED_VOLUME | SATELLITE_CHANGE | MACHINE_GPS |
                                        -- FIELD_OBSERVATION | PHOTO | GPS_TRACK | PHOTO_COMPARISON | WARNING
    summary         TEXT    NOT NULL,   -- short human description (LV)
    ref_table       TEXT,               -- integration_records | session_track_points | work_photos | photo_cmp_runs | sectors
    ref_id          INTEGER,
    observed_at     TEXT,               -- when the source observed it (UTC, '%Y-%m-%d %H:%M:%S UTC')
    created_at      TEXT    NOT NULL,
    UNIQUE (risk_id, source_provider, evidence_type, ref_table, ref_id)
);
CREATE INDEX IF NOT EXISTS idx_risk_evidence_risk ON risk_evidence(risk_id);
```

- The UNIQUE constraint makes re-attaching evidence idempotent (`INSERT … ON CONFLICT DO UPDATE SET summary=…, observed_at=…`).
- No foreign keys, matching the rest of the schema (DATABASE.md §2).
- **Backfill in today's DBs** (checked read-only on the /tmp copies): MAIN has 19 risks and RM has 2. RM's risks 59 and 62 are `is_demo=0`, so both get **REAL**.

## 3. Stages (each stage = one reviewable patch, in this order)

All code goes to MAIN, gets reviewed, is committed by the user, and is deployed with `create_client_instance.sh --slug rm --update-code` (R9). Data for DEMO-01 is created **only** by the stage-6 script, run against the RM DB.

### Stage 1: provenance schema and safe resets (no visible change)
- **Code:** T1, T2, T3, T4, T5, T6, T7.
- **Acceptance:**
  1. On /tmp copies of both DBs: the migration runs twice without error, and the schema diff is exactly §2.2.
  2. Backfill: RM risks 59 and 62 → `REAL`, MAIN `is_demo=1` rows → `DEMO_SCENARIO`/`SIMULATED_INTEGRATION` per rule code. Show the counts.
  3. In a temp DB, insert one row of each origin, then `demo_scenarios.reset_demo()`: only `DEMO_SCENARIO` is deleted; with `include_simulated_integrations=True`, `SIMULATED_INTEGRATION` is deleted too; `REAL` never is.
  4. `manager.reset_demo(id)` deletes only its own category's `SIMULATED_INTEGRATION` rows plus their `risk_evidence`.
  5. `calc_risk_score` output for every sector in both copies is unchanged (reuse the step-4 harness and before/after table).
  6. `pytest -q tests/` passes.

### Stage 2: catalog, statuses and grouping (UI shows groups; nothing connectable yet)
- **Code:** T8, T9, T10, T11, T22, T23. Plus the `index.html` group container and a collapsible `<details>` for the third group.
- **New `registry.py` entries.** All have `implemented=True`, `demo_available=True`, `status_claim="demo"`, and an adapter from stage 4:

  | provider | display_name | category | group |
  |---|---|---|---|
  | `mdps_demo` | MDPS (meža datu pārvaldības sistēma) — Demo | timber | client_systems |
  | `palma_timber_demo` | Palma Timber — Demo | timber | client_systems |
  | `qgis_qfield_demo` | QGIS / QField — Demo | gis | client_systems |
  | `intramaps_roam_demo` | IntraMaps Roam — Demo | gis | client_systems |

  Real-world counterparts: `mdps`, `palma_timber`, `qgis_qfield`, `intramaps_roam`, all with `status_claim="requires_confirmation"`, `implemented=False`, and `notes` saying "the client's real system; connection only after a confirmed API/data contract".
  - Each demo entry has `real_counterpart="<key>"`, so the UI can show the pair.
  - **Q1:** should the simulated entries use the bare keys from the requirement (`mdps`, …) instead of `_demo` keys? The plan uses `_demo` keys, so that the real key stays free for a future real adapter. This matches the existing `fleet_gps_demo` / `sentinel_demo` naming.
- **Groups** (data in `registry.py`; order and labels from a module constant `GROUPS = [("client_systems", "Rīgas meži sistēmas", False), ("independent_sources", "Neatkarīgie datu avoti", False), ("machine_fleet", "Tehnikas / autoparka integrācijas", True), ("other", "Citas / plānotās integrācijas", True)]`):
  - client_systems: the 4 demo entries and their 4 `requires_confirmation` counterparts.
  - independent_sources: `sentinel_copernicus`, `sentinel_demo`, `telegram_bot` (GPS + photos). Plus a display-only `field_photos` entry if Q2 says so.
  - machine_fleet: every `category in ("machine","fleet")` entry (`registry.py:52-79`), collapsed by default.
  - other: GIS/ERP/audit/weighbridge/timber generic, landsat/planet/etc., collapsed by default (**Q2**).
- **Status mapping** (`manager.list_catalog` and `test_connection`):
  - an integration row with `is_demo=1` → `connection_status='SIMULATED'`, display **"Demo · simulated"** (LV "Demo · simulēts"), amber badge;
  - `requires_confirmation` → "Integration requires confirmation" (LV "Integrācija jāapstiprina"), grey;
  - `CONNECTED` is only possible for `is_demo=0` rows of implemented, non-demo adapters (none exist today).
  - The KPI "Pieslēgts" counts `connection_status==='CONNECTED' && !is_demo` (`index.html:4000`).
- **Acceptance:**
  1. A new test asserts that every provider with `status_claim=='demo'` gets display "Demo · simulated" and never "CONNECTED"/"Pieslēgts", **before and after** `test_connection()`.
  2. `requires_confirmation` entries cannot be created (`create_integration` raises, `manager.py:76-80`).
  3. `GET /api/integrations` returns `group`/`group_order` for all entries, and the UI renders 3 visible groups in the required order with the fleet/machine group collapsed. Checked on the temp server (127.0.0.1:8011, as in step 4).
  4. The LV overlay shows "Demo · simulēts" and "Integrācija jāapstiprina".
  5. `tests/test_integrations.py:135-142` still passes. Ponsse/Komatsu remain "planned".

### Stage 3: REAL evidence for Case 1 plus the evidence UI
- **Code:** T18, T20, T21, T23, and the REAL-evidence part of T24 (`seed_demo_layer.py --real-evidence-only`).
  - REAL evidence linked by the script, RM only, idempotent:

    | risk | source_provider | evidence_type | ref | observed_at |
    |---|---|---|---|---|
    | 62 | telegram_bot | GPS_TRACK | session_track_points of session 32 (`ref_table='work_sessions', ref_id=32`) | 2026-10-11 05:24:27–05:38:48 UTC |
    | 62 | telegram_bot | PHOTO | `work_photos` sessions 27 and 31 (one row per session, summary "27 foto" / "21 foto") | first photo time |
    | 59 and 62 | photo_compare | PHOTO_COMPARISON | `photo_cmp_runs` id 1 | 2026-10-10 08:34:45 UTC |
    | 59 | external_warning | WARNING | none; summary "LVĢMC dzeltenais brīdinājums" (source quoted in the reason text) | 2026-10-09 04:20 local (from the reason text) |

    Each is `data_origin='REAL'`.
  - `BIK_001.png` is linked **only after Q4**, because its provenance is unknown.
- **UI:**
  - "Pierādījumi" list in `openRisk`, after the reason block (`index.html:2158-2163`): source display name, `evidence_type`, `summary`, `observed_at` (via `riskLocal`, `index.html:2069-2075`), and the badge — **"Reāls"** green (`b-green`) or **"Demo · simulēts"** amber (`b-amber`).
  - A SIMULATED risk additionally gets a full-width amber banner at the top: "SIMULĒTI DATI — demonstrācijas scenārijs, nav saistīts ar reālām sistēmām".
  - `loadRisks` shows a compact "DEMO" amber badge for `data_origin != 'REAL'`.
- **Acceptance:**
  1. RM risk 62 detail lists 3 items, all "Reāls". Risk 59 lists 2.
  2. Running the script twice gives the same row count in `risk_evidence`.
  3. A risk with no evidence renders exactly as today (snapshot of HTML before and after for risk 59 in MAIN).
  4. No change to conclusions (`loadRiskConclusion`, `index.html:2323-2500`), the exit route (`:2256-2310`) or photos.

### Stage 4: simulated adapters (code only; no data yet)
- **Code:** T12 and T13.
- **Pattern:** subclass **`IntegrationAdapter`** (`base.py:39`), not the category classes (avoids F-f), with:
  - `test_connection()` → `(True, "Simulēts avots — nav reālas savienojuma")`
  - `fetch_data()` reads only `sectors WHERE data_origin='SIMULATED'`, and returns fixed scenario values (not time-bucketed like `fleet_gps_demo.py:37-45`), so a re-sync is idempotent.
  - `normalize_data()` sets `entity_type`, `external_id`, `source_timestamp`, `sector`, and the **marker fields** `"simulated": true, "data_origin": "SIMULATED"`.
  - `save_data()` = `super().save_data()` (`integration_records`, deduplicated by `make_dedup_key`, `base.py:220-222`), then `risk_rules.check_volume_discrepancy_crosscheck(sector)`.
- **Fixed DEMO-01 scenario values** (one record each):

  | provider | entity_type | values |
  |---|---|---|
  | mdps_demo | PlannedVolume | planned_volume_m3 = 200, permit "DEMO-PERMIT-01" |
  | palma_timber_demo | RecordedVolume | recorded_volume_m3 = 260, 3 harvester reports summed |
  | sentinel_demo (extended) or sentinel2_change_demo | SatelliteChange | change_detected = true, change_area_ha = 1.4, confidence 0.8, inside polygon |
  | machine_gps_demo (category fleet, but **no** `vehicle_gps_pings` write) | MachineTrack | harvester "DEMO-H1", 6 points inside the polygon over 2 days |
  | field_photo_demo | FieldPhoto | 1 generated placeholder image with a watermark (see stage 6) |
  | qgis_qfield_demo / intramaps_roam_demo | FieldObservation | "svaigi celmi" (fresh stumps) observed at 2 points, by "DEMO inspektors" |

  - **Q5:** Roam and QField both as separate corroborating sources, or one of them?
- **Existing demo adapters:** `fleet_gps_demo.py:65`, `sentinel_demo.py:47` and `weighbridge_demo.py:43` gain `AND data_origin='SIMULATED'` in their sector query. In RM they then never touch BIK-001. In MAIN they do nothing until a simulated sector exists there (**Q6:** acceptable for MAIN demos?).
- **Acceptance (temp DB):**
  1. Each adapter `sync()` twice → `integration_records` count is unchanged on the 2nd run (`deduplicated == N`).
  2. With BIK-001 present and DEMO-01 present, no adapter writes any row with `sector='BIK-001'` (assert in the test).
  3. No new rows in `vehicle_gps_pings`, `work_photos` or `timber_movements`.

### Stage 5: crosscheck rule, scoring and AI provenance
- **Code:** T14, T15, T16, T17.
- **Rule** `check_volume_discrepancy_crosscheck(sector_name)` in `risk_rules.py`:
  1. Read the latest `PlannedVolume` and `RecordedVolume` for the sector from `integration_records` (by `entity_type`, `sector`). If either is missing → return.
  2. `deviation_pct = (recorded − planned) / planned × 100`. If `|deviation_pct| ≤ CROSSCHECK_TOLERANCE_PCT` → return (and, if an open risk exists, add the event `WITHIN_TOLERANCE`; never auto-resolve).
  3. Corroborating sources = distinct `source_provider` among `integration_records` for the sector whose normalized payload corroborates:
     - `SatelliteChange.change_detected` true;
     - a `MachineTrack` with ≥ `CROSSCHECK_MIN_MACHINE_POINTS` points inside the polygon (`geo.point_in_polygon`);
     - a `FieldObservation`;
     - a `FieldPhoto`.
     The two compared systems themselves are **not** counted. REAL `risk_evidence` of the same sector (Telegram GPS or photos) also counts if present.
  4. Score and level (constants at the top of `risk_rules.py`):
     ```
     CROSSCHECK_TOLERANCE_PCT       = 10    # below: no risk
     CROSSCHECK_BASE_POINTS         = 20    # any discrepancy above tolerance
     CROSSCHECK_DEVIATION_WEIGHT    = 1.0   # points per % deviation …
     CROSSCHECK_DEVIATION_CAP_PCT   = 50    # … counted up to 50 %
     CROSSCHECK_POINTS_PER_SOURCE   = 10    # per independent corroborating source …
     CROSSCHECK_MAX_SOURCES         = 4     # … counted up to 4
     CROSSCHECK_MIN_MACHINE_POINTS  = 3
     # level bands = the existing calc_risk_score bands (api.py:111-117): ≤30 LOW, ≤60 MEDIUM, else HIGH
     score = min(100, round(BASE + min(|dev|, CAP) × WEIGHT + min(n_sources, MAX_SOURCES) × PER_SOURCE))
     ```
  5. Create **one** risk per sector: lookup `database.get_active_incident_by_rule("VOLUME_DISCREPANCY_CROSSCHECK", sector=…)` (`database.py:1276`).
     - If none exists: `add_incident(sector, level, reason, entity_type="TIMBER", entity_id=sector, rule_code=…, data_origin=<SIMULATED_INTEGRATION if any compared record is_demo else REAL>)` with `is_demo` set accordingly.
     - If one exists: update `risk_level` when it changed (event `ESCALATED` / `DEESCALATED` with old→new).
     - Always: attach or refresh `risk_evidence` for **every** item (including the two volume records), and write `CROSSCHECK_SCORED`.
     - **No inline AI call**: the worker generates the text (stage 5 T15), so there is a single prompt with full provenance.
     - The reason text is fixed and neutral: `"Datu neatbilstība: reģistrētais apjoms {recorded} m³ atšķiras no plānotā {planned} m³ ({dev:+.0f}%)"`, plus `" — SIMULĒTI DATI"` when simulated. **Never** "illegal logging"/"nelikumīga".
  6. Register `"timber": [..., "VOLUME_DISCREPANCY_CROSSCHECK"]` in `RULE_CODES_BY_CATEGORY` (`risk_rules.py:40-44`), so the mdps/palma reset clears it (**Q7**).
- **DEMO-01 expected result** (computed by the rule, asserted in the test, never hard-coded in data). The deviation is (260 − 200) / 200 = **+30 %**.

  | Evidence present | n_sources | score = 20 + 30 + 10·n | level |
  |---|---|---|---|
  | MDPS + Palma only | 0 | 50 | MEDIUM ("data discrepancy") |
  | + Sentinel-2 change | 1 | 60 | MEDIUM |
  | + machine GPS | 2 | 70 | HIGH (escalated) |
  | + field photo | 3 | 80 | HIGH |
  | + QField/Roam observation | 4 | **90** | **HIGH** |

  - The seed script (stage 6) syncs in this order, so the risk shows the escalation path in `risk_events`: CREATED MEDIUM 50 → SCORED 60 → ESCALATED HIGH 70 → 80 → 90.
  - DEMO-01 sector card (`calc_risk_score`, `api.py:102-185`): one open HIGH → 25 → **floor 61, HIGH**. Exposure is the flat €500–€1,500 (`exposure_basis=flat_per_open_high_risk`), because no `timber_movements` are written (**Q8**).
- **AI:**
  - `_excluded`/`_candidates` (`risk_ai_worker.py:120-121`, `:180`) allow `data_origin='SIMULATED_INTEGRATION'`.
  - `_build_prompt` (`:306-320`) adds to the facts a `Data origin: SIMULATED (demonstration data, not from a live client system)` line and the evidence list (`source_provider`, origin, `observed_at`, summary).
  - The template gets `{origin_rule}` after rule 7. For simulated risks it is: "8. All data for this risk is simulated for a demonstration. Say so explicitly in the first sentence of the summary. Describe it as a data discrepancy; never call it illegal logging or theft."
  - `_valid_recommendation` (`:326-339`) rejects simulated-risk output whose summary lacks the language marker (`lv: "simulēt"`, `en: "simulat"`, `ru: "симулир"`) or contains `nelikumīg|illegal|незакон|zādzīb|theft`. The existing 2-attempt limit (`:31`) applies.
- **Acceptance:**
  1. Unit tests: the 5-row table above is reproduced exactly from the constants.
  2. A second full sync creates no second risk and no duplicate evidence.
  3. Tolerance edge cases: 10 % gives no risk; 10.1 % gives a risk.
  4. Negative deviation (recorded < planned) is also a discrepancy, with the reason wording "mazāks" (smaller) (**Q9**).
  5. The prompt for the DEMO-01 risk (printed with the AI call blocked, step-4 harness) contains the origin line, all 6 evidence lines and rule 8.
  6. Real risks' prompts are byte-identical to today (diff of the BIK-001 risk 62 prompt before/after, excluding "Current time").

### Stage 6: DEMO-01 seed script (data, RM only)
- **Code:** T24 `scripts/seed_demo_layer.py`.
- **Safety:** refuses to run unless `--target-db` resolves to `/root/forest_ai_rm/data/forest_ai.db`. It also accepts an explicit `--allow-main` together with a different path, and refuses MAIN without it (R9). Before writing, it runs `.backup` to `data/backups/…pre-demo-layer.db`.
- **Steps, all idempotent:**
  1. `sectors`: insert DEMO-01 if missing, with `data_origin='SIMULATED'`, `contractor='DEMO (simulēts)'`, `status='DEMO — simulēts sektors'`, `notes='Simulēts sektors demonstrācijai. Visi dati ir simulēti.'`, and a polygon at an **agreed location** (**Q10**), stored like BIK-001 as `[lat, lon]`, unclosed (`database.add_sector`, `database.py:~815`).
  2. `integrations`: one `is_demo=1` row per simulated provider, created via `manager.create_integration`, with status `SIMULATED` after `test_connection`.
  3. `run_sync` per provider in the escalation order of stage 5.
  4. Placeholder photo: generated with Pillow (F-l) as `data/demo/DEMO-01_photo_1.jpg`. It is a neutral forest-colour canvas with a large diagonal watermark **"SIMULĒTS ATTĒLS — DEMO"**, never a real photo (**Q11**).
  5. REAL evidence backfill for BIK-001 (the stage-3 part, if not already run).
  6. Print a summary: rows created, evidence counts, the risk id, score and level.
  - `--reset` deletes only DEMO-01 rows (sector, integration rows and their records, the risk, `risk_evidence`, `risk_events`, the demo photo).
- **Acceptance (on a /tmp copy first, then RM):**
  1. Run 1 creates DEMO-01, 7 integration rows, 1 risk at score 90 / HIGH with 6 evidence rows. Run 2 changes nothing (all counts equal).
  2. BIK-001 rows (risks 59/62, sessions, photos, `photo_cmp_*`) are byte-identical before and after, checked by `sqlite3 .dump` diff filtered to BIK-001.
  3. With `--reset`, the DB equals the pre-seed DB except for the empty `integrations`/`integration_*` tables' `sqlite_sequence`.

### Stage 7: GeoJSON export (REAL feature)
- **Code:** T19.
- **Route:** `GET /api/export/risks.geojson?status=open|all` (default `all`); Basic Auth comes from `api.py:67`. It returns `Response(media_type="application/geo+json")` with a `Content-Disposition: attachment; filename="forest_ai_risks_<UTC date>.geojson"` header.
- **Feature per risk:**
  - `geometry`: the sector polygon. `boundary_json` `[[lat,lon],…]` is converted to `[[lon,lat],…]` and the ring closed (first point appended if `first != last`). `geometry: null` when the sector has no boundary, which is valid GeoJSON.
  - `properties`:
    - `risk_id`; `sector_id` (`sectors.id`); `sector` (name);
    - `risk_type` (`rule_code` or `"MANUAL"`); `risk_level`;
    - `risk_score`: the latest `CROSSCHECK_SCORED.score` for crosscheck risks. For others, the sector's `calc_risk_score().score`, with `risk_score_basis: "risk" | "sector"` added so it isn't misread;
    - `detected_at`: ISO-8601 `Z`, from `occurred_at` or else `created_at` (`_parse_ts` handles both formats, `risk_ai_worker.py:104-113`);
    - `source_count`, `sources` (distinct `source_provider` list), `real_evidence_count`, `demo_evidence_count` (from `risk_evidence`);
    - `status`; `data_origin`; `simulated: true|false`.
  - FeatureCollection-level `"name": "forest_ai_risks"` and a top-level `"crs"`-free WGS84 document (RFC 7946).
- **Validation (the script `tools/validate_geojson.py`, no new dependency):**
  - JSON parses; `type == "FeatureCollection"`.
  - Each feature has `geometry` either null or a valid Polygon: `shapely.geometry.shape(g).is_valid`, ring closed, ≥ 4 positions, and all positions `-180≤lon≤180`, `-90≤lat≤90`.
  - **Axis sanity:** for Latvian sectors, lon ∈ [20, 29] and lat ∈ [55, 59]. This catches an unswapped `[lat,lon]`.
  - Every required property is present.
  - `ogrinfo` is not installed (F-l). Optional: `apt install gdal-bin` (**Q12**) or a manual QGIS import by the user.
- **Acceptance:**
  1. The RM export has 2 REAL features (59, 62) and, after stage 6, 1 SIMULATED feature (DEMO-01) with `simulated: true` and `demo_evidence_count: 6`.
  2. The validator passes.
  3. BIK-001's first exported coordinate is `[24.1958, 56.968]`, and the ring is closed.
  4. An unauthenticated request gets 401.

### Stage 8: deploy and demo dry run
- **Order:** user commits stages 1–7 (one by one, or reviewed patches squashed per stage); RM DB backup; `--update-code` deploy (as in "Deployed F8/F9"); restart `forest-rm-api` → `forest-api` → `forest-bot`; run `seed_demo_layer.py` against the RM DB **once**; the worker generates the DEMO-01 AI text within about 2–3 minutes (`AI_WORKER_INTERVAL_S=60`, `AI_WORKER_MIN_AGE_S=120`, `risk_ai_worker.py:28-29`), using 1 paid call.
- **Acceptance (on :8002):**
  - The Integrations page shows the groups in the required order, with no "Pieslēgts" anywhere.
  - The BIK-001 risks show only "Reāls" evidence.
  - The DEMO-01 risk shows the banner, 6 "Demo · simulēts" items, score 90 HIGH, and an AI summary that starts by stating the data is simulated.
  - The GeoJSON export opens in QGIS (by the user).
  - MAIN :8000 is unchanged apart from origin badges on its existing demo-scenario risks.

## 4. Risks and what must not break

| Existing feature | Touches | How it is verified |
|---|---|---|
| Live geofence / SECTOR_EXIT / EMERGENCY (`bot.py:938-990`, `:1638-1690`) | `add_incident` gains optional args only | Defaults keep the INSERT identical; `pytest`; temp-DB call with old args → row identical except `data_origin` NULL → backfilled REAL by the next `_migrate`. **Better:** `add_incident` defaults `data_origin='REAL'` when `is_demo` is not set. |
| Demo scenarios (`demo_scenarios.py:275-930`, `/api/demo/{scenario}` `api.py:1748`) | reset scope | Stage-1 test 3; run `trigger_breakdown` plus reset on a temp DB: the scenario row is deleted as today. |
| Integration demo adapters and per-integration reset (`manager.py:144-185`) | status, sector scope, reset scope | Stage-2/4 tests; `tests/test_integrations.py` all pass; the fleet demo in RM produces **no** BIK-001 risk. |
| AI worker (risks ≥ 60, daily cap 30, `risk_ai_worker.py:28-34`) | eligibility and prompt | Prompt diff for REAL risks is empty (stage-5 test 6); worker eligibility unchanged for REAL and DEMO_SCENARIO risks (unit test over all 3 origins). |
| Sector score and floor, exposure (`api.py:102-185`) | none directly; new risks are counted | Stage-1 test 5 (scores unchanged before seeding); DEMO-01 expected 61 HIGH. **Note:** global KPIs in `/api/summary` (`api.py:595-622`) will count the DEMO-01 risk (**Q13**). |
| Risk conclusions and photo comparison (`services/risk_conclusion.py`, `services/photo_compare.py`) | none (constraint) | The stage-6 dump diff for BIK-001 rows; `photo_cmp_*` row counts unchanged; risk 59 conclusion still renders. |
| PDF report (`api.py:1969-2060`) | none | Generate `/api/report/pdf/BIK-001` before and after: same page count and risk lines. |
| Satellite intelligence (`api.py:2483-2560`, `services/satellite_intelligence/*`) | none (constraint). The simulated Sentinel change lives only in `integration_records` | `satellite_observations` row counts unchanged in RM. |
| Clone script (`scripts/clone_sector_instance.py`) | new table and columns | It copies per-sector tables by a `sector` column. `risk_evidence` has none, so add it to the children-of-`risks` list (stage 1) or document it (**Q14**). |
| LV overlay (`assets/i18n-lv.js`) | new strings | Every new visible string in EXACT. Spot-check on the 8011 temp server with `UI_LANGUAGE=lv`. |
| Token safety | the new code calls no Telegram | No new logging of URLs. Journal checks use the `/bot<REDACTED>/` filter only. |

**General rules for every stage:**
- Additive schema only; no renames or reformatting.
- Every stage is tested on /tmp copies and the 8011 temp server before review.
- No AI calls in verification (monkey-patched).
- The patch hash is checked before commit, and the user commits and pushes.

## 5. Open questions (the code does not decide these)

| # | Question | Default if not answered |
|---|---|---|
| Q1 | Registry keys: bare `mdps`/`palma_timber`/`qgis_qfield`/`intramaps_roam` for the simulated entries, or `*_demo`, with the bare keys reserved for the real `requires_confirmation` entries? | `*_demo` for simulated, bare keys for the real counterparts. |
| Q2 | "Neatkarīgie datu avoti": is Telegram enough as one entry ("Telegram bots — GPS un foto"), or should a display-only "Lauka foto" entry be added? And where do the remaining ~12 catalog entries go (GIS generic, ERP, audit, Landsat, Planet…)? | One Telegram entry; a 4th group "Citas / plānotās integrācijas", collapsed. |
| Q3 | One module with all simulated adapters, or one file per adapter (current pattern)? | One file per adapter. |
| Q4 | What is the provenance of RM `data/sector_satellite/BIK_001.png` (Sentinel export, other imagery, screenshot)? It can only be REAL evidence with a named source. | Not linked as evidence until confirmed. |
| Q5 | QField and Roam: both simulated sources (two corroborations) or one field-observation source? This changes the score (90 vs 80). | Both entries exist, but only **one** field observation is seeded (from QField), giving 4 sources = 90. |
| Q6 | MAIN demos: after T13, MAIN's demo adapters find no simulated sector and do nothing. Is that acceptable, or should MAIN get its own simulated sector (only with `--allow-main`)? | Acceptable; nothing in MAIN. |
| Q7 | Which explicit action may delete the crosscheck risk: the mdps/palma per-integration reset, `seed_demo_layer.py --reset`, or both? | Both; the global `/api/demo/reset` only with `?include_simulated=1`. |
| Q8 | Should the 60 m³ excess produce a computed exposure (60 × €60–120 = €3,600–7,200) on the DEMO-01 card? That would require writing a `timber_movements` row (which also adds +15 OVER_VOLUME to the sector score and is wiped by the global reset, F-a), or a new exposure path. | No: keep the flat basis, with the explanation line. |
| Q9 | Is a negative deviation (recorded < planned) also a risk in this rule, or only over-recording? | Both directions, with direction-specific wording. |
| Q10 | DEMO-01 polygon location: it must not overlap a real Rīgas meži property or BIK-001. A clearly fictional area (e.g. inside a lake or offshore) is unmistakable but looks odd on the map. | To be provided by the client/user; the script refuses to run without `--polygon`. |
| Q11 | Simulated photo: is a generated watermarked placeholder acceptable, or should a licensed stock image (watermarked) be used? Real BIK-001 photos must **not** be reused. | Generated placeholder (Pillow). |
| Q12 | May `gdal-bin` be installed for `ogrinfo` validation (a new system package)? | No; shapely validation plus a manual QGIS check. |
| Q13 | Should the global KPIs (`/api/summary`, overview tiles) exclude `data_origin != 'REAL'`, or include them with a label? | Include them, plus a sub-label "t.sk. N demo"; this needs one more small UI change in stage 3. |
| Q14 | Should `risk_evidence` be copied by `scripts/clone_sector_instance.py` when new client instances are created? | Yes, as a child of `risks`. |
| Q15 | DEMO-01 dates: should the simulated observations carry dates in the past (e.g. 2026-10-12…14) or "today" at seed time? Past fixed dates keep the escalation reproducible. | Fixed past dates; `observed_at` shown, `created_at` real. |

## 6. Decisions (2026-10-20)

The plan is **approved** with the decisions and amendments below. Implementation goes stage by stage; after each stage the user commits and replies "Stage N committed — continue".

### Answers to the open questions
| # | Decision |
|---|---|
| Q1 | Default: `*_demo` keys for the simulated entries; bare `mdps` / `palma_timber` / `qgis_qfield` / `intramaps_roam` for the real `requires_confirmation` counterparts. |
| Q2 | Default: one Telegram entry in "Neatkarīgie datu avoti"; a 4th group "Citas / plānotās integrācijas", collapsed by default. |
| Q3 | One file per adapter. |
| Q4 | `BIK_001.png` is **Sentinel-2 L2A, exported manually from Copernicus Browser; the acquisition date was NOT recorded**. Stage 3 links it as REAL evidence: `evidence_type='SATELLITE_IMAGE'`, `source_provider='sector_satellite_file'`, summary "Sentinel-2 L2A (Copernicus Browser, manuāla augšupielāde) — uzņemšanas datums nav fiksēts", `observed_at` NULL. It must **never** count as `SATELLITE_CHANGE` evidence anywhere, in particular not as a corroborating source in the stage-5 crosscheck. |
| Q5 | Default: QField and Roam both exist as entries; one field observation is seeded (QField), so 4 corroborating sources and score 90. |
| Q6 | Default: MAIN demo adapters do nothing until a simulated sector exists there. |
| Q7 | Default: the crosscheck risk is deleted by the mdps/palma per-integration reset and by `seed_demo_layer.py --reset`; the global `/api/demo/reset` only with `?include_simulated=1`. |
| Q8 | **Replaced by amendment A2.** |
| Q9 | Default: deviation in both directions; wording depends on direction. |
| Q10 | The user will provide **one centre point in the Tīreļi area** later. Stage 6 builds a rectangle of about 4 ha around it and **refuses to run without `--center LAT,LON`**. Stages 1–5 and 7 do not depend on it. |
| Q11 | Default: generated watermarked placeholder (Pillow); no real BIK-001 photo reused. |
| Q12 | **No** `gdal-bin`; validation with shapely, plus a manual QGIS check by the user. |
| Q13 | Default, in stage 3: global KPIs include non-REAL risks with a sub-label "t.sk. N demo". |
| Q14 | **Yes:** `scripts/clone_sector_instance.py` copies `risk_evidence` as a child of `risks`. |
| Q15 | Default: fixed past dates for the simulated observations. |

### Amendments
- **A1 (Stage 5): sector score follows the crosscheck score.**
  - `calc_risk_score()` `score = max(current score including the HIGH floor, max CROSSCHECK_SCORED.score of the sector's OPEN crosscheck risks)`.
  - The level comes from the existing bands.
  - The DEMO-01 card must show **90 HIGH**, the same as its risk.
- **A2 (Stage 5; replaces Q8): computed exposure without `timber_movements`.**
  - The crosscheck rule stores `excess_m3 = |recorded − planned|`, **only when recorded > planned**, in the `CROSSCHECK_SCORED` details.
  - For open crosscheck risks, `calc_risk_score()` adds `excess_m3 × the existing €60–120/m³ rate`, and does **not** add the flat per-HIGH-risk constant.
  - `exposure_basis = "calculated_volume_excess"`.
  - Expected DEMO-01: 60 m³ × 60–120 = **€3,600–€7,200**.
- **A3 (Stage 5, UI): no flat amount shown as a € range.**
  - Wherever `exposure_basis == 'flat_per_open_high_risk'`, the sector card and the sector table show **"Not calculated"** (LV "Nav aprēķināts") instead of the € range. The explanation line stays as a tooltip or secondary line.
  - The API numbers are unchanged (backward compatible).
  - Before/after shown for MAIN and RM sectors.
- **A4 (Stage 1):** `add_incident()` defaults `data_origin='REAL'` when the caller does not mark the row as demo.

### Process for every stage
- Work only in MAIN. Never edit `/root/forest_ai_rm`. No restarts, no deploy, no Anthropic calls (monkey-patched as in step 4).
- Verify on `/tmp` DB copies and, where UI is involved, on the temporary server 127.0.0.1:8011 (`env -i`, empty secrets), then stop it.
- Output per stage:
  - `git diff > /root/patches/2026-10-20-demo-sN.patch` (stat and sha256);
  - a section "## Stage N" in `/root/inspection/2026-10-20-demo-layer.md`, with each acceptance criterion marked PASS or FAIL;
  - the exact commit command for the user to run with "!".
- STOP after each stage until "Stage N committed — continue".
