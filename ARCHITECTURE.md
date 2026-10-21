# ARCHITECTURE.md — Forest AI

**Verified against code:** `github.com/George199212/Forest-AI-`, branch `master` (now `5f82a8d`; full inspection at
commit `574bd97` (2026-10-20). Inspected 2026-10-21 by direct clone + reading source.
**Supersedes:** all earlier ARCHITECTURE.md versions (repo copy describes commit `0db0a79`, 2026-09-08).

Legend: **[CODE]** confirmed in source · **[TEST]** confirmed by running code locally ·
**[NOT VERIFIED]** needs the live VPS (no SSH access in this session).

---

## 1. System overview

Forest AI is a single-tenant monolith: one FastAPI process, one Telegram polling bot
process, one SQLite file, one single-file SPA.

```
 Browser (HTTP Basic) ──► index.html (vanilla JS SPA, 4207 lines, no build step)
                              │  fetch('/api/...'), SSE via fetch+ReadableStream
                              ▼
                         api.py  FastAPI, 2767 lines, 106 routes
                         + mounted sub-app /api/webhooks (no Basic Auth, HMAC optional)
                         + background thread: services/risk_ai_worker.py
                              │
     ┌────────────────────────┼─────────────────────────────┐
     ▼                        ▼                             ▼
 database.py            services/*                    External APIs
 SQLite, 38 tables      ai_resolution, risk_ai_worker,  Anthropic (claude-sonnet-4-5)
 data/forest_ai.db      photo_compare, risk_conclusion, Copernicus CDSE / Sentinel Hub
                        session_track, robez_ocr_vision, Telegram Bot API (sendMessage)
                        demo_scenarios, geo,
                        satellite_intelligence/, integrations/

 Telegram ──► bot.py  python-telegram-bot 22.8, polling, 1881 lines, own process
                       opens its own sqlite3 connections to the same DB file
```

## 2. Tech stack [CODE]

| Layer | Technology | Source of truth |
|---|---|---|
| API | FastAPI 0.136.3 + uvicorn 0.52.4, pydantic 2 | `requirements.txt`, `api.py` |
| Bot | python-telegram-bot 22.8, `run_polling(allowed_updates=ALL_TYPES)` | `bot.py::main` |
| DB | SQLite, raw `sqlite3`, no ORM, no pool; connection per call | `database.py` |
| AI | Anthropic SDK 0.116, default model `claude-sonnet-4-5` (override `ANTHROPIC_MODEL` in worker / photo-compare / conclusion) | 6 call sites, see INTEGRATIONS.md |
| Satellite | Copernicus Data Space (OAuth client-credentials) + Sentinel Hub Process API | `api.py` lines ~2156–2462 |
| Images | Pillow (optional import in `api.py`, required in `photo_compare.py`) | |
| PDF | `reportlab` — imported lazily in `/api/report/pdf/{sector}`; **NOT in requirements.txt** | `api.py::generate_pdf` |
| Crypto | `cryptography` Fernet for integration credentials | `services/integrations/crypto.py` |
| Frontend | Vanilla JS, Chart.js 4.4.1 (cdnjs), Leaflet 1.9.4 (unpkg, lazy-loaded), OSM raster tiles, Google Fonts | `index.html` |
| i18n | Optional display-only LV overlay `assets/i18n-lv.js`, injected when `UI_LANGUAGE=lv` | `api.py::serve_index` |
| Tests | pytest, `tests/test_integrations.py` — 30 tests, all pass [TEST] | |

`config.py` is 0 bytes and imported nowhere — dead file. All config is `os.environ.get(...)`.

## 3. Processes and runtime

| Process | Entry | Notes |
|---|---|---|
| API | `uvicorn api:app` (port 8000 per docstring) | `@app.on_event("startup")` → `init_db()` + `risk_ai_worker.start()` (daemon thread, polls every 60 s) |
| Bot | `python bot.py` | Raises at import if `TELEGRAM_BOT_TOKEN` unset. Calls `init_db()` on start. |
| Webhooks | sub-app mounted at `/api/webhooks` inside API process | separate FastAPI instance → outside global Basic Auth |

systemd units (`forest-api.service`, `forest-bot.service`, `forest-rm-api.service`) are
described in `docs/CLIENT_INSTANCES.md` but no unit files are in the repo — **[NOT VERIFIED]** live state.
No reverse proxy / TLS config exists in the repo; bot.py hardcodes `http://164.90.188.136:8000`
(plain HTTP) in three dashboard links — **[NOT VERIFIED]** whether a proxy/TLS exists on the VPS.

Both processes write the same SQLite file concurrently with no WAL/timeout configuration in code.

## 4. Multi-instance model (client accounts) [CODE: docs + scripts]

Per `docs/CLIENT_INSTANCES.md` (implemented 2026-10-13): a client account = **full copy of
the code in its own directory**, own `.env`, own `data/`, own port, own systemd unit.
First instance: Rīgas meži (`/root/forest_ai_rm`, port 8002, no Telegram bot, `UI_LANGUAGE=lv`).
Created by `deploy/create_client_instance.sh` + `scripts/clone_sector_instance.py`
(clones one sector's data into a new DB).

Reason it's copies, not shared code: `photo_compare.APP_DIR` resolves photo paths
relative to the code directory. Operational tables have no `organization_id`;
`organizations`/`organization_id` exists only in Integration Layer tables and is always `1`.

## 5. Authentication and access control

**API [CODE+TEST]:** `FastAPI(dependencies=[Depends(verify_credentials)])` — HTTP Basic,
single shared login from `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD`, `secrets.compare_digest`.
No CORS middleware. No roles, no per-user identity beyond the Basic username
(used as `actor` in audit events).

Exceptions that are reachable **without** Basic Auth [TEST, local TestClient]:
- `/docs`, `/redoc`, `/openapi.json` (FastAPI built-ins are not APIRoutes → app-level dependency not applied) — full API map is public.
- `/api/webhooks/*` + `/api/webhooks/docs|openapi.json` — by design; HMAC checked only if `WEBHOOK_SECRET_<PROVIDER>` is set, otherwise accepted with `signature_valid=NULL` and only logged (no domain writes). In-memory rate limit 30/min per provider+IP.

**Telegram bot [CODE]:** no authorization on any command except `/demo_*`
(`demo_scenarios.is_demo_admin`, defaults to `DISPATCHER_CHAT_ID`). Any Telegram user who
finds the bot can run `/add_sector`, `/add_risk`, `/add_timber`, `/add_truck`, `/sectors`,
`/risks`, `/report`, and `/export_report` (ZIP of CSVs: all work sessions with worker names,
Telegram user ids and GPS coordinates; sector boundaries; timber; trucks; risks), and can self-link to
any unlinked employee of a sector via the check-in "Это вы?" buttons.

## 6. Key data flows

### 6.1 Check-in and geofence (bot.py)
1. `📍 GPS Check-in` → choose sector (inline) → optional self-link to employee → send location.
2. `handle_location` (new message): point-in-polygon on `sectors.boundary_json`; if no
   boundary → 10 km radius around `center_lat/lon`, falling back to hardcoded Riga
   (56.9587, 24.1034). Inserts `work_sessions` (`approved` YES/NO), auto-closes the
   user's previous open sessions. Rejected → `add_risk(HIGH)`.
3. Live location edits (`edited_message`): upsert `live_locations` (one row per Telegram id),
   append `session_track_points` while a session is active; on IN→OUT transition →
   `add_incident(rule_code='SECTOR_EXIT')` deduped per employee+sector+session,
   synchronous AI recommendation via `run_in_executor`, worker + dispatcher Telegram alerts.
4. Session state lives in `context.user_data` (in memory, no persistence). After a bot
   restart, `/finish` falls back to the latest open DB session; live-tracking state does not.

### 6.2 Incident lifecycle
`risks.status`: `OPEN` → `NOTIFIED` (Telegram sent: approve endpoint, SOS, report-issue,
demo) → `RESOLVED` (`confirm_return` button, conclusion accept) / `DISMISSED`.
Every step writes `risk_events` (audit log, 40+ event types — see DATA_MODEL.md).

Auto-generated `rule_code`s from live code: `SECTOR_EXIT`, `EMERGENCY` (bot.py);
`EQUIPMENT_BREAKDOWN` and others via AI Inspector report-issue / demo scenarios;
`FLEET_SECTOR_EXIT`, `SATELLITE_UNREGISTERED_CHANGE`, `WEIGHBRIDGE_WAYBILL_MISMATCH`,
`TIMBER_VOLUME_OVER_PERMIT` via Integration Layer **demo** adapters only.
Legacy `add_risk()` rows (fuel discrepancy >5 L, rejected check-in, timber/truck mismatch)
have no `entity_type`/`rule_code`.

### 6.3 AI layers (all `claude-sonnet-4-5` by default)
| Component | Trigger | Output | Guards |
|---|---|---|---|
| `ai_resolution.generate_incident_recommendation` | incident creation (bot, report-issue, demo, integration rules), worker reply | JSON: summary, options[] with Telegram texts, exposure EUR range | never raises; returns None |
| `risk_ai_worker` (thread in API) | any risk without AI, id ≥ 60, age ≥ 120 s | same JSON contract, language `AI_OUTPUT_LANGUAGE` (default lv) | 1 risk/60 s, max 2 attempts, **30 paid calls/UTC day** |
| AI Inspector `/api/inspector/analyze*` | user click | real SSE stream (text) + `---JSON---` block | persisted to `ai_inspector_analyses` |
| `photo_compare` | explicit authenticated steps only | point matching, same-place check, change detection on 3×3 grid, independent verification | max 40 points/run, 2 attempts/call, forbidden-wording regex (no cause/weather claims) |
| `risk_conclusion` | user click | conclusion text; **close/keep-open decided by fixed rules R0–R3 in code, never by the model** | text checked for money/cause/coverage/decision wording |
| `robez_ocr_vision` | Telegram plan photo | coordinates from boundary-plan scan | no caching by file hash |

### 6.4 Financial numbers — two independent sources (do not merge)
- `api.py::calc_risk_score()` — rule-based: open HIGH×25 + MEDIUM×10 + rejected GPS×15 +
  timber missing×20 + over×15, capped 100, HIGH floor 61. Exposure = volume at risk × €60–120
  + flat GPS/HIGH add-ons. Used by `/api/sectors`, `/api/map`, Inspector, PDF.
- `calc_financial_risk_from_incidents()` — sum of AI-estimated
  `estimated_exposure_eur_low/high` from `risks.ai_recommendation`. Used by `/api/summary`
  (Overview KPI) and `/api/risks/financial-breakdown`. **These are AI estimates, not measured losses.**

### 6.5 Satellite
- **Live imagery (works):** `/api/satellite/image|ndvi|object/*` call Sentinel Hub Process API on
  every request (512×512, no caching, no persistence). Default date window hardcoded
  `2024-06-01..2024-06-30`.
- **Satellite Intelligence Engine (partially wired):** providers, `satellite_monitoring_score`,
  tier decision engine, cost estimation, and 7 event triggers exist in
  `services/satellite_intelligence/`, **but no code in the repo calls any `events.trigger_*`
  function or `decide_and_request`.** `satellite_*` tables are filled only by the
  `sentinel_demo` integration adapter (fabricated deterministic scenes) or by out-of-repo scripts.
  There is **no automatic change detection from real Sentinel imagery**.
- Commercial providers (PlanetScope, SkySat, ICEYE) are stubs that report "not configured".

### 6.6 Integration Layer (`services/integrations/`)
Registry (single catalog) → category adapter classes → `sync()` pipeline:
`fetch → normalize → validate → save (integration_records staging + domain table) → risk_rules`.
Only 3 adapters are implemented and all are **demo** (no network): `fleet_gps_demo`,
`sentinel_demo`, `weighbridge_demo`. `lvm_geo` exists as a catalog entry with
`status_claim="planned"`, no adapter. `GISIntegrationAdapter` category exists but, by design,
does not write sector boundaries automatically (stage 1 = staging only).

## 7. Coordinate systems — CRITICAL [CODE+TEST]

Storage CRS is WGS84 `[lat, lon]` everywhere (`boundary_json`, GPS). Leaflet + OSM (EPSG:3857 display).

The LKS-92 (EPSG:3059) → WGS84 conversion `lks92_to_wgs84()` is duplicated in
`bot.py`, `api.py::_lks92_to_wgs84`, `services/robez_ocr_vision.py`. It is a linear
approximation documented as "accurate to ~100 m". **Checked against pyproj EPSG:3059 on
2026-10-21: error is 150–190 km** (e.g. X=310280, Y=504908 → true 56.936 N 24.081 E;
formula gives 56.503 N 26.750 E). Any sector created from OCR coordinates or from a drawn
polygon with a solved georef scale lands in the wrong place. Sectors entered directly in
WGS84 (`/add_sector`, `POST /api/sectors`) are unaffected. Not fixed — see CURRENT_STATUS.md.

## 8. Repository hygiene findings [CODE]
- `install.sh` (403 lines) is an unrelated third-party installer for `codebase-memory-mcp`,
  committed into this repo.
- `bot.py::analyze_robez_plan_ocr` (Tesseract) is dead code; the live path is Claude Vision.
- `tools/i18n_check/make_fixture.py` contains a real person's full name and Telegram ID in a **public** repo.
- Timestamp formats differ in the same column: `add_incident` writes `YYYY-MM-DD HH:MM:SS UTC`,
  `add_risk` writes ISO `YYYY-MM-DDTHH:MM:SS.ffffff`.

## 9. Not verified in this session
Live systemd status, nginx/TLS presence, port 8001 orphan, whether production code equals
`574bd97`, contents of production `.env`, size of production DB.
