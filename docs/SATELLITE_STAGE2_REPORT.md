# Satellite Monitoring — Stage 2 (API + scheduler) report

Date: 2026-11-16. Branch `feature/satellite-monitoring`. Spec: `docs/SATELLITE_SPEC.md` §6, with owner decisions
D1–D5 (2026-11-16). **Not deployed**:
- no restart, no unit installed, no production write;
- `forest_ai.db` is touched only as a test copy;
- the live `satellite.db` is opened read-only (see "Live data" at the end).

## Decisions applied

| | Decision | Where |
|---|---|---|
| D1 | `satellite_monitoring/` + `satellite.db` is the canonical subsystem. `services/satellite_intelligence/` and `/api/satellite*` are untouched, with no new callers | `api.py` gains only 2 added lines (router include) |
| D2 | **Worker** (venv2) writes `satellite.db` and opens `forest_ai.db` read-only. **API** reads `satellite.db` read-only. Its 4 POST routes write only a `sat_jobs` row or a review row | `store.py`, `jobs.py` |
| D2 | Risks only by a human `CREATE_RISK`, through the existing `add_incident` + `add_risk_event` + `add_risk_evidence` (source `SATELLITE`) | `risk_bridge.py` |
| D3 | No automatic risks: `auto_risk_enabled = False`. The worker modules do not import the risk engine (tested) | `config.py` |
| D4 | Neutral wording, e.g. "Suspected vegetation/land-cover change detected: X ha; Y ha outside the approved boundary". It never says "illegal", "violation" or "confirmed felling"; a guard and tests enforce this | `store.event_summary`, `risk_bridge` |
| D5 | LVM GEO button and UI: Stage 3, not touched here | — |
| Open point | A redetect carries `risk_id` to the successor event when the union masks overlap ≥ 30 % of the smaller mask. Best overlap wins; one risk per successor | `redetect.carry_risks` |

## Write path chosen: direct thin writes (not a subprocess)

`satellite_monitoring/db.py` and `config.py` import only the standard library (`json`, `sqlite3`, `os`, `pathlib`).
So the API can use them directly. The new API-side module `store.py` imports only them plus the standard library.
It does not import `areas`, `geometry`, `pipeline` or `raster`, which need numpy, pyproj, shapely or tifffile.
Its writes are:
- short `BEGIN IMMEDIATE` transactions;
- `busy_timeout` 5 s;
- the WAL mode set by the worker;
- no schema creation or migration. The API returns 503 until the worker has migrated the file.

A subprocess path was not needed.

## Files

| File | What |
|---|---|
| `satellite_monitoring/store.py` (new) | API-side reads (`mode=ro`) and the small writes: job rows, and review + undo with a status guard |
| `satellite_monitoring/api_routes.py` (new) | `/api/sat-monitoring/*` router (9 routes) and the field-check Telegram text and sender |
| `satellite_monitoring/risk_bridge.py` (new) | Human CREATE_RISK, linked to the existing Risk Engine. It is idempotent per `entity_id = sat_event:<id>` |
| `satellite_monitoring/jobs.py` (new) | Worker queue consumer: ADD_AREA (+ 120-day backfill), STOP_AREA and FETCH; `--daily` adds the TIMER run |
| `satellite_monitoring/db.py` | `sat_jobs` table (append-only; one open job per dedup key) and event columns `risk_carried_from_event_id` / `risk_carry_overlap` (additive) |
| `satellite_monitoring/pipeline.py` | **Status guard:** an event update made during a run no longer overwrites a human status set meanwhile through the API (the human decision wins; the measurements are still written) |
| `satellite_monitoring/redetect.py` | Allows events whose only human trace is CREATE_RISK, and carries their risk link (before, any risk link made redetect refuse) |
| `satellite_monitoring/config.py` | `auto_risk_enabled False`, `risk_carry_min_overlap 0.30`, `area_backfill_days 120` |
| `api.py` | `include_router(sat_monitoring_router(verify_credentials))` |
| `deploy/systemd/forest-satellite-sync.{service,timer}` | Daily 07:30 Europe/Riga: queue + TIMER run, venv2. **Prepared only** |
| `deploy/systemd/forest-satellite-jobs.{service,timer}` | Queue every 5 min (cheap when empty). **Prepared only** |
| `deploy/systemd/forest-api.service.d/97-satellite-monitoring.conf` | `SAT_DB_PATH` / `SAT_RASTER_DIR` for forest-api. **Prepared only** |
| `tests/test_sat_stage2_api.py`, `tests/test_sat_stage2_worker.py` (new) | 53 tests (below) |
| `API.md` | New section "Satellite Monitoring (S1+S2, Stage 2)" |

## Review semantics

**CONFIRM / REJECT / FIELD_CHECK**
- Set `REVIEW_CONFIRMED` / `REVIEW_REJECTED` / `FIELD_CHECK_REQUESTED`, together with `reviewed_by`, `reviewed_at_utc` and `review_note`.
- Each one appends a row to `sat_review_log` (append-only; triggers forbid UPDATE and DELETE).
- Every write is guarded by the status the reviewer saw. A second reviewer racing the first gets 409.
- **CONFIRM does not create a risk** (D2: only CREATE_RISK does).

**FIELD_CHECK**
- Sends first and records only if sending succeeded. A failed send changes nothing (502).
- The message goes to `DISPATCHER_CHAT_ID` via the Bot API, as `api.py` and `bot.py` do. It contains the area, the neutral summary, the dates, confidence, an approximate centre, the requester and the note.

**UNDO**
- Works as a stack: it cancels the most recent status decision that hasn't been undone yet, and restores the previous status and reviewer.
- CREATE_RISK is not undone here: the risk follows its own workflow.

**CREATE_RISK**
- Allowed on any current event, including LOW confidence, because it is a human decision.
- The risk gets:
  - `entity_type='SATELLITE'`, `entity_id='sat_event:<id>'`, `data_origin='REAL'`;
  - `rule_code` `SATELLITE_CHANGE_DURING_WORK` if the operational context counts registered work, else `SATELLITE_UNREGISTERED_CHANGE`;
  - `risk_level` = detection confidence;
  - risk event `SATELLITE_RISK_CREATED` (actor = the user);
  - one `risk_evidence` row (`SATELLITE`, `REAL`, `ref_table=sat_change_events`);
  - the AI recommendation through the existing call. The prompt gets only the stored metrics, plus rules: suspected, no invented facts, no "illegal/violation/confirmed felling". If the AI call fails, the existing fallback text is used.
- Retry is safe. If linking to the event fails after the risk was created, the retry finds the same open risk.
- A demo reset cannot delete these risks: it deletes only `is_demo=1` rows.

**REJECT and UNDO on an event with a linked risk**
- Each adds risk event `SATELLITE_REVIEW_REJECTED` / `SATELLITE_REVIEW_REJECT_UNDONE` to the same risk. The risk status is left to the existing workflow.

## Tests (exact results, 2026-11-16)

| Run | Result |
|---|---|
| System python 3.12.3 (forest-api interpreter): `tests/test_sat_stage2_api.py tests/test_sat_stage2_worker.py tests/test_satellite_monitoring.py` | **138 passed, 1 skipped** (the skip is the existing tifffile-only test) |
| venv2 (worker interpreter), same files | **98 passed, 1 skipped** (the API file skips there because venv2 has no fastapi, by design) |
| Full suite, system python, before Stage 2 (HEAD `c235df5`) | 9 failed, 373 passed, 4 skipped, 40 errors |
| Full suite, system python, after Stage 2 | **9 failed, 426 passed, 4 skipped, 40 errors**. The failure/error set is identical to the baseline: 8 FAILED in `test_vmd_production.py`, 1 FAILED in `test_john_deere_sync.py`, 30 ERROR in `test_integrations.py`, 10 ERROR in `test_nationwide_geodata.py` (pre-existing, unrelated) |

Stage 2 tests cover:
- Basic Auth (401 without or with wrong credentials) on every route of the **real** `api.app`;
- D1: the existing routes are still present;
- reads never change `satellite.db` (sha256), and the read handle cannot write;
- missing DB → 503, never created; writes refused before the worker migrated the schema;
- path traversal: absolute path outside the root, `..`, a symlink out of the root, non-PNG, missing file, other `kind`s, encoded `../`;
- validation (source, ref, name, geometry type, CRS / outside Latvia, unclosed ring, booleans, vertex limit);
- dedup (one open job per key; one active area per `source_ref`);
- the review / undo stack and the append-only log;
- FIELD_CHECK: failure leaves no change, the text is neutral;
- CREATE_RISK: existing tables and fields, rule code by context, idempotent retry, REJECT adds a risk event, CONFIRM never creates a risk;
- D3: config false, the worker never imports the risk engine, the main DB is byte-identical after a worker pass;
- the job queue: ADD_AREA creates the area and runs a 120-day backfill; SECTOR polygons are read read-only; an invalid polygon ends as a FAILED job; STOP, FETCH, lock → re-queue, an interrupted job is retried;
- risk carry: best overlap, one risk per successor, the 30 % threshold (0.4 carried, 0.2 not), redetect with a CREATE_RISK-linked event versus a refused REJECT;
- the pipeline status guard;
- a regression found and fixed: the RECOVERED-migration rebuild now keeps the new columns.

**Migration check on a copy of the live DB** (sqlite backup into the session scratchpad; live file not opened for writing):
- `connect()` added `sat_jobs` and the two columns, and all 57 event rows were kept.
- Overview gives BIK-001 0 open / 0 recovered, and Ķekava 8 open / 1 recovered.
- Event 55 detail has 24 before and 13 after images, and its quicklook resolves inside the raster root.
- Health shows 302 requests and 852.8 PU this month.

## Not verified / open

- **Not run against real services:** the Telegram send to the dispatcher, the Anthropic recommendation call, and any Copernicus request. All were faked in tests: 0 network, 0 PU.
- **No real ADD_AREA backfill was run.** It spends PU (quota guard applies) and will run only once the job timer is installed in Stage 4.
- **The systemd units were not installed or run** (`systemd-analyze verify` not run either).
  - `@RELEASE_DIR@` must be replaced with the active release folder at Stage 4.
  - `ProtectHome=read-only` relies on `forest_ai.db` being in rollback-journal mode (no `-wal` file today) for its read-only open. Check this before installing.
- **forest-api needs `SAT_DB_PATH`** (prepared drop-in `97-…`). Without it the API answers 503, because there is no `data/satellite.db` in the release folder.
- **Live data:** read-only opens of the live `satellite.db` (2026-11-16 07:11 UTC) created the usual empty WAL sidecars (`satellite.db-wal` 0 bytes, `satellite.db-shm`). The DB file is unchanged: sha256 `052b99df…0201`.
- **The worker must run once before the API can write.** Its first run migrates the live `satellite.db` (adds `sat_jobs` and 2 nullable columns; idempotent, checked on a copy). Back up the file first.
- **`positive_control.py` still counts RECOVERED events as outside events.** The reports already follow the 2026-11-16 decision; the code has not changed.
- **UI (Stage 3), the LVM GEO button (D5) and release (Stage 4) have not started.**
