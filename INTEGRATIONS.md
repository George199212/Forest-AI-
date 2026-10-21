# INTEGRATIONS.md — Forest AI

**Verified against code:** commit `574bd97` (2026-10-20). Status labels:
**LIVE** = real network integration in code · **DEMO** = code exists, fabricates data, no network ·
**STUB** = interface only / "not configured" · **CATALOG** = listed in registry, no adapter code ·
**[NOT VERIFIED]** = cannot be confirmed from the repo.
**Supersedes:** earlier INTEGRATIONS.md versions.

## 1. Summary

| External system | Status | Where | Credentials (env) |
|---|---|---|---|
| Anthropic Claude API | LIVE | 6 call sites (§2) | `ANTHROPIC_API_KEY`, opt. `ANTHROPIC_MODEL`, `AI_OUTPUT_LANGUAGE` |
| Telegram Bot API (polling + sendMessage) | LIVE | `bot.py`; `api.py` + `demo_scenarios.py` post directly via HTTPS | `TELEGRAM_BOT_TOKEN`, `DISPATCHER_CHAT_ID`, opt. `DEMO_ADMIN_IDS` |
| Copernicus Data Space / Sentinel Hub Process API | LIVE (on-demand imagery only) | `api.py` `/api/satellite/*`, `satellite_intelligence/providers/sentinel.py` | `SENTINEL_CLIENT_ID`, `SENTINEL_CLIENT_SECRET` |
| OpenStreetMap raster tiles | LIVE (browser) | `index.html` (6 Leaflet maps) | none — OSM tile usage policy applies |
| unpkg (Leaflet 1.9.4), cdnjs (Chart.js 4.4.1), Google Fonts | LIVE (browser CDN) | `index.html` | none |
| Sentinel-1, Landsat via Sentinel Hub | STUB-ish: provider classes exist, same token; **no caller outside the unwired decision engine** | `satellite_intelligence/providers/sentinel.py` | same as Sentinel |
| PlanetScope, SkySat, ICEYE | STUB (report not configured) | `satellite_intelligence/providers/commercial.py` | provider env vars, none in `.env.example` |
| Fleet GPS, Sentinel, Weighbridge (demo) | DEMO | `services/integrations/demo/*` | none |
| LVM GEO | CATALOG (`status_claim="planned"`) | `services/integrations/registry.py` | — |
| PONSSE, John Deere (TimberMatic/TimberManager), Komatsu (Smart Forestry/MaxiFleet/MaxiVision), ZF SCALAR, KRAUZERS fleet, Landsat, Maxar, generic GIS/ERP/timber/weighbridge, GeoJSON/KML import, TIMBRO audit | CATALOG | registry | — |
| geolatvija.lv | **Not an integration** — only the default text label `source='geolatvija'` on manually uploaded `sector_snapshots` | `database.py` | — |
| Google Maps | Link only (`maps.google.com/?q=lat,lon` in Telegram alerts) | `bot.py`, `demo_scenarios.py` | — |
| Weather | **None.** `risk_conclusion` accepts manual `weather_text`/`weather_source` from the user | | — |

## 2. Anthropic Claude (LIVE)

Default model everywhere: `claude-sonnet-4-5`.

| Call site | Mode | max_tokens | Trigger | Failure behaviour |
|---|---|---|---|---|
| `services/ai_resolution.py::generate_incident_recommendation` | `messages.create` | 2048 | incident creation, worker reply, integration rules, demo | returns `None`, never raises |
| `services/risk_ai_worker.py` → `generate_incident_recommendation({"prompt_override": ...})` | thread in API | 2048 | risks without AI (id ≥ 60) | `ai_status=FAILED` after 2 attempts; **cap 30 calls/UTC day** |
| `api.py::_stream_inspector_analysis` | `messages.stream` (real SSE) | 2048 | user click | SSE `event: error` |
| `services/photo_compare.py::_call_vision` | vision, images downscaled in memory (512/1024 px) | varies | explicit user steps | logged in `photo_cmp_events` with token counts |
| `services/risk_conclusion.py::_generate_text` | `messages.create` | 1200 | conclusion draft with `use_ai` | text rejected by regex guards → retry (max 2) |
| `services/robez_ocr_vision.py::analyze_robez_plan_ocr_vision` | vision | 4096 | Telegram plan photo | error dict; **no caching by file hash** (re-upload = new paid call) |

Cost controls exist only in the worker (daily cap) and photo-compare (points/attempts caps).
Inspector, report-issue, OCR and integration-rule calls have no rate/cost cap.

## 3. Telegram (LIVE)

- `bot.py` long-polling, `allowed_updates=ALL_TYPES` (needed for live-location edits).
- Outbound from API process: `requests.post("https://api.telegram.org/bot{token}/sendMessage")` in
  `approve_incident`, `send_risk_message`, `inspector_report_issue`, `demo_scenarios._tg_send`.
- httpx/httpcore loggers forced to WARNING so the token-bearing URL is not logged (commit `574bd97`).
- Only `/demo_*` commands are restricted (to `DEMO_ADMIN_IDS` or `DISPATCHER_CHAT_ID`); all other
  commands are open to any Telegram user — see ARCHITECTURE.md §5.
- Client instance (Rīgas meži, port 8002) runs **without** a bot (per `docs/CLIENT_INSTANCES.md`).

## 4. Copernicus / Sentinel Hub (LIVE, on-demand)

- Token: `POST https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`
  (client-credentials), cached in process memory until `expires_in − 60 s`.
- Imagery: `POST https://sh.dataspace.copernicus.eu/api/v1/process`, collection `sentinel-2-l2a`,
  bbox in EPSG:4326, 512×512, true colour (cloud ≤ 50 %) or NDVI classes. Returned straight to the
  browser; **nothing persisted, no cache, no observation row written**.
- Default date window hardcoded `2024-06-01 … 2024-06-30` unless the frontend passes `date_from/date_to`.
- No automated change detection from real imagery exists. The Satellite Intelligence decision engine
  (`decide_and_request`, `events.trigger_*`) has **no callers** in the repo.

## 5. Integration Layer framework (`services/integrations/`)

- `registry.py` — single catalog (`ProviderEntry`: provider, category, implemented, demo_available,
  status_claim, confirmed_customer_use). UI must not show CATALOG entries as Connected.
- `base.py::IntegrationAdapter` — `test_connection`, `authenticate`, `fetch_data`, `normalize_data`,
  `validate_data`, `save_data`, `sync()`; credentials via `get/set_credentials` (Fernet, key
  `INTEGRATION_CREDENTIALS_KEY`; losing it makes stored credentials unrecoverable).
- `categories.py` — Machine, Fleet (→ `vehicle_gps_pings`), GIS (staging only, never writes sector
  boundaries automatically), Satellite (→ `satellite_observations`), Timber, Weighbridge
  (→ `weighbridge_records`), Worker, ERP, Audit.
- `manager.py` — CRUD, test, sync, logs, records, demo reset, health, webhook handling.
- `risk_rules.py` — FLEET_SECTOR_EXIT, SATELLITE_UNREGISTERED_CHANGE, WEIGHBRIDGE_WAYBILL_MISMATCH,
  TIMBER_VOLUME_OVER_PERMIT → `add_incident` + AI recommendation, deduped via `get_active_incident_by_rule`.
- Webhooks: `POST /api/webhooks/{provider}` (outside Basic Auth). Stage 1 only records + dedups payloads.
- Multi-tenancy: `organization_id` always 1; not an access boundary.
- Tests: `tests/test_integrations.py`, 30 passing (run 2026-10-21).

Confirmed real-world ties recorded in the registry (factual notes, no API contract): KRAUZERS uses GPS
fleet systems for timber trucks (vendor unknown); TIMBRO develops a LiDAR/GNSS/camera audit system.

## 6. Coordinate reference systems used by integrations

- All storage and APIs: WGS84 lat/lon. Sentinel bbox: `[minLon, minLat, maxLon, maxLat]` EPSG:4326.
- LKS-92 (EPSG:3059) → WGS84 conversion in three copies is wrong by 150–190 km (verified with pyproj);
  affects OCR plan import and georeferenced drawn polygons. **Any future Latvian GIS integration
  (LVM GEO, VMD, VZD, LĢIA — all publish in LKS-92) must use a real projection library, not this function.**
- No `pyproj`/GDAL dependency exists today.

## 7. Not verified
Which integrations are actually configured on production (`.env`), Sentinel Hub quota/plan,
Anthropic monthly spend, whether demo integrations are enabled on the client instance.
