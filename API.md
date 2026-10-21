# API.md — Forest AI

**Verified against code:** commit `574bd97` (2026-10-20). Route list generated on 2026-10-21 by
importing `api.py` and enumerating `app.routes` / `webhook_app.routes` — **106 routes on the main app + 1 webhook route**.
Descriptions from reading each handler. **Supersedes:** earlier API.md (54 routes, commit `0db0a79`).

## Conventions

- **Auth:** HTTP Basic on every main-app route (`DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD`), single shared login.
  Exceptions reachable without auth (verified with TestClient): `/docs`, `/redoc`, `/openapi.json`, and everything under `/api/webhooks`.
- **Errors:** inconsistent. Mix of `HTTPException` (`{"detail": ...}`), hand-built `Response` with `{"error": ...}`, and
  `200 {"error": "Not found"}` (`GET /api/sectors/{name}`). Clients must handle all three.
- **Pagination:** none. List endpoints return everything or a fixed LIMIT (200/300).
- **Sector identity:** path parameter is the sector **name** (free text, URL-encoded).
- **Coordinates:** WGS84, boundary arrays are `[[lat, lon], ...]` (note: Sentinel bbox uses `[minLon, minLat, maxLon, maxLat]`).
- **Paid/quota calls** (Anthropic / Sentinel Hub) happen in: inspector analyze*, inspector report-issue, photo-compare match/process, conclusion draft (`use_ai=true`), satellite image/ndvi/object (Sentinel Hub processing units), demo triggers, background AI worker. `approve` does **not** call AI — it sends the already-stored recommendation text.
- **Body** column: Pydantic model name or multipart fields. **Query** column: query parameters.


## Frontend & files

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/` | `serve_index` | — | — | SPA. Injects `assets/i18n-{UI_LANGUAGE}.js` when set. |
| GET | `/photos/file/{filename}` | `serve_photo_file` | — | — | Serves `PHOTOS_DIR/{filename}`. |
| GET | `/assets/{filename}` | `serve_asset` | — | — | Serves `assets/{filename}`. |

## Overview

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/summary` | `summary` | — | — | Overview KPIs. `exposure_*` = sum of **AI-estimated** incident exposure; counts return 0 on empty tables. |

## Sectors

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/sectors` | `get_sectors` | — | — | All sectors + `calc_risk_score` fields (score/level/color/exposure_low/high/label/basis) + per-sector counts + parsed `boundary`. N+1 queries per sector. |
| POST | `/api/sectors` | `create_sector` | SectorIn | — | Upsert via `database.add_sector`. `boundary` ≥ 4 points `[[lat,lon],...]` WGS84. |
| PUT | `/api/sectors/{name}` | `update_sector` | SectorIn | — | Same upsert by path name. |
| DELETE | `/api/sectors/{name}` | `delete_sector` | — | — | Deletes sector row only — dependent rows are orphaned. 404 if missing. |
| PATCH | `/api/sectors/{name}/notes` | `update_sector_notes` | SectorNotesIn | — | Update tree_species / cut_plan_notes / notes. |
| GET | `/api/sectors/{name}` | `get_sector_detail` | — | — | Sector + score + risks, trucks, timber, sessions, photos, comments, employees, vehicles (+fuel), snapshots (+linked risks). Returns `{error}` with **200** when not found. |
| GET | `/api/map` | `get_map_data` | — | — | Map markers: center (or last GPS), boundary, risk color. |

## Objects & boundary plans

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/objects` | `get_objects` | — | — | Sectors grouped by `boundary_plan_id`. |
| GET | `/api/boundary-plans/{plan_id}/scan` | `get_boundary_plan_scan` | — | — | Original plan scan file. |
| POST | `/api/objects` | `create_object` | ObjectCreate | — | Creates empty `boundary_plans` row (`document_type=manual_object`). |
| POST | `/api/objects/{plan_id}/boundary-plan` | `upload_boundary_plan` | file | — | Multipart `file` → `data/boundary_plans/manual_{id}{ext}`. No type/size validation. |
| POST | `/api/objects/{plan_id}/satellite` | `upload_object_satellite` | file | — | Multipart manual satellite image for an object. |
| GET | `/api/objects/{plan_id}/satellite-image` | `get_object_satellite_image` | — | — | Manual image if present, else redirect to live Sentinel. |
| POST | `/api/objects/{plan_id}/sectors` | `create_sector_from_drawing` | SectorPolygonIn | — | Sector from pixel polygon; converted to lat/lon only if plan has `georef_scale` (**uses the broken LKS-92 approximation**). |
| POST | `/api/sectors/{name}/polygon` | `update_sector_polygon` | SectorPolygonIn | — | Redraw pixel outline; recompute WGS84 boundary if georef available (same conversion). |
| GET | `/api/boundary-plans/{plan_id}/annotated` | `get_boundary_plan_annotated` | — | — | Plan scan with all sector outlines drawn (Pillow, JPEG). |
| GET | `/api/sectors/{name}/plan-crop` | `get_sector_plan_crop` | — | — | Crop of plan around one sector. |

## Snapshots

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| POST | `/api/sectors/{name}/snapshots` | `upload_sector_snapshot` | file snapshot_date label note risk_level | — | Multipart dated historical image (`snapshot_date` required, `label`, `note`, `risk_level` ∈ ''/LOW/MEDIUM/HIGH). Never overwrites. |
| GET | `/api/sectors/{name}/snapshots` | `get_sector_snapshots_route` | — | — | List snapshots of a sector. |
| GET | `/api/sectors/snapshots/{id}/image` | `get_sector_snapshot_image` | — | — | Snapshot image file. |
| DELETE | `/api/sectors/snapshots/{id}` | `delete_sector_snapshot_route` | — | — | Delete snapshot (row + file per `database.delete_sector_snapshot`). |
| POST | `/api/sectors/snapshots/{id}/risks` | `link_snapshot_risk` | SnapshotRiskIn | — | Link a risk to a snapshot. |
| GET | `/api/sectors/snapshots/{id}/risks` | `get_snapshot_risks_route` | — | — | Risks linked to snapshot. |
| DELETE | `/api/sectors/snapshots/{id}/risks/{risk_id}` | `unlink_snapshot_risk` | — | — | Remove link. |

## GPS, routes, tracks

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/sectors/{name}/vehicles/{vehicle_id}/route` | `get_vehicle_route` | — | — | Vehicle pings ordered by time (path `name` is ignored in the query). |
| GET | `/api/sectors/{name}/session-tracks` | `get_sector_session_tracks` | — | — | Work sessions of a sector with track metadata. |
| GET | `/api/risks/{risk_id}/exit-route` | `get_risk_exit_route` | — | — | Track segment around a SECTOR_EXIT incident; 404 if none. |
| GET | `/api/sessions/{session_id}/track` | `get_session_track` | — | — | Full session route: points, gaps (>120 s), photos placed within 60 s, summary. |
| GET | `/api/gps` | `get_gps` | — | — | Last 200 work_sessions. |
| GET | `/api/gps/activity` | `gps_activity` | — | — | Check-ins per day, last 30 days with data. |

## Employees & vehicles

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/employees` | `get_all_employees` | — | — | All employees. |
| GET | `/api/employees/{sector}` | `get_sector_employees` | — | — | Employees of sector. |
| POST | `/api/employees` | `create_employee` | EmployeeIn | — | Create employee (incl. `id_number`, `telegram_user_id`). |
| DELETE | `/api/employees/{eid}` | `delete_employee` | — | — | Hard delete; references in risks/sessions are orphaned. |
| PATCH | `/api/employees/{eid}` | `update_employee` | EmployeePatchIn | — | Partial update; only non-null fields. |
| GET | `/api/vehicles` | `get_all_vehicles` | — | — | All vehicles. |
| GET | `/api/vehicles/{sector}` | `get_sector_vehicles` | — | — | Vehicles of sector + last 5 fuel logs. |
| POST | `/api/vehicles` | `create_vehicle` | VehicleIn | — | Create vehicle. |
| POST | `/api/vehicles/fuel-log` | `add_fuel_log` | FuelLogIn | — | Fuel log; |discrepancy| > 5 L auto-creates MEDIUM risk. |
| DELETE | `/api/vehicles/{vid}` | `delete_vehicle` | — | — | Hard delete. |
| PATCH | `/api/vehicles/{vid}` | `update_vehicle` | VehiclePatchIn | — | Partial update. |

## Risks & incidents

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/risks` | `get_risks` | — | — | All risks, pinned first, then HIGH→LOW, newest first. No pagination. |
| GET | `/api/risks/by-sector` | `risks_by_sector` | — | — | HIGH/MEDIUM/LOW counts per sector (all statuses). |
| GET | `/api/risks/financial-breakdown` | `risks_financial_breakdown` | — | — | Per-risk AI-estimated exposure rows behind the Overview KPI. |
| GET | `/api/risks/{risk_id}` | `get_risk_detail` | — | — | Risk + events + `ai_state`; for EMPLOYEE: name, telegram_connected, last live location, assigned equipment/vehicle. |
| POST | `/api/risks/{risk_id}/ai-retry` | `retry_risk_ai` | — | — | Queue risk for background AI worker (daily cap applies). |
| GET | `/api/risks/{risk_id}/photo` | `get_risk_photo` | — | — | `risks.photo_path` file. |
| GET | `/api/risks/{risk_id}/photo2` | `get_risk_photo2` | — | — | `risks.photo_path_2` file. |
| GET | `/api/incidents` | `get_incidents_route` | — | status | Incidents (entity_type NOT NULL), optional `status` filter. |
| GET | `/api/equipment` | `get_equipment_route` | — | sector | Equipment, optional `sector` filter. |
| POST | `/api/incidents/{incident_id}/approve` | `approve_incident` | ApproveIn | — | Dispatcher approves: sends chosen AI option text to worker via Telegram, status→NOTIFIED, events APPROVED + TELEGRAM_SENT (actor = Basic username). |
| POST | `/api/risks/{risk_id}/send-message` | `send_risk_message` | SendMessageIn | — | Free-text dispatcher→worker Telegram message; event DISPATCHER_MESSAGE. |

## Risk conclusion (Slēdziens)

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/risks/{risk_id}/conclusion` | `risk_conclusion_get` | — | — | Current conclusion state + history. |
| POST | `/api/risks/{risk_id}/conclusion/draft` | `risk_conclusion_draft` | RiskConclusionDraftIn | — | Build evidence + rule result; optional AI text (`use_ai`); manual `weather_text/source`. |
| POST | `/api/risks/{risk_id}/conclusion/{conclusion_id}/close` | `risk_conclusion_close` | RiskConclusionCloseIn | — | Accept and close → risk RESOLVED; `override_reason` required when against rule recommendation. |
| POST | `/api/risks/{risk_id}/conclusion/{conclusion_id}/continue` | `risk_conclusion_continue` | RiskConclusionContinueIn | — | Interim conclusion, risk stays open, `next_steps` required. |
| POST | `/api/risks/{risk_id}/conclusion/{conclusion_id}/undo` | `risk_conclusion_undo` | RiskConclusionUndoIn | — | Undo a decision (reason required); restores draft. |

## AI Inspector

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/inspector/analyze/{sector_name}` | `inspector_analyze_sector` | — | — | SSE stream (`text/event-stream`): `data:{chunk}` events, then `event: done` with risk_breakdown/exposure/suggested_actions, or `event: error`. Paid Claude call. Saves `ai_inspector_analyses`. |
| GET | `/api/inspector/analyze-all` | `inspector_analyze_all` | — | — | Same SSE contract over all sectors (portfolio + satellite pending requests). |
| POST | `/api/inspector/actions/report-issue` | `inspector_report_issue` | ReportIssueIn | — | Creates HIGH incident for equipment operator, generates AI recommendation (sync), sends Telegram with inline button. 400 if operator not linked to Telegram; 502 if Telegram fails (incident stays OPEN). |

## Photo comparison

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/photo-compare/runs` | `photo_cmp_list_runs` | — | sector | List runs (optional `sector`). |
| POST | `/api/photo-compare/runs` | `photo_cmp_create_run` | PhotoCmpRunIn | — | Create run for sector + baseline/follow-up dates (optional explicit photo ids). |
| GET | `/api/photo-compare/runs/{run_id}` | `photo_cmp_get_run` | — | — | Run with points, photos, changes. |
| GET | `/api/photo-compare/runs/{run_id}/events` | `photo_cmp_get_events` | — | — | Audit log incl. paid-call token counts. |
| POST | `/api/photo-compare/runs/{run_id}/match` | `photo_cmp_match` | — | — | Start AI matching pass (paid, background thread). |
| POST | `/api/photo-compare/runs/{run_id}/confirm-all` | `photo_cmp_confirm_all` | — | — | Human confirms all points. |
| POST | `/api/photo-compare/points/{point_id}/confirm` | `photo_cmp_confirm_point` | — | — | Human confirms one point. |
| POST | `/api/photo-compare/points/{point_id}/not-same-place` | `photo_cmp_not_same_place` | PhotoCmpForceIn | — | Human marks point not comparable. |
| POST | `/api/photo-compare/runs/{run_id}/reassign` | `photo_cmp_reassign` | PhotoCmpReassignIn | — | Move a photo to another point or `new`. |
| POST | `/api/photo-compare/runs/{run_id}/process` | `photo_cmp_process` | PhotoCmpProcessIn | — | Run check→detect→verify on confirmed points (paid; `limit`, `point_ids`, `force`). |
| POST | `/api/photo-compare/points/{point_id}/observations` | `photo_cmp_add_observation` | PhotoCmpObservationIn | — | Reviewer observation (`change_class` possible_change|possible_damage). |
| POST | `/api/photo-compare/changes/{change_id}/withdraw` | `photo_cmp_withdraw_observation` | — | — | Withdraw own observation. |
| POST | `/api/photo-compare/changes/{change_id}/undo` | `photo_cmp_undo_review` | — | — | Undo review decision. |
| POST | `/api/photo-compare/changes/{change_id}/review` | `photo_cmp_review_change` | PhotoCmpReviewIn | — | `action` confirm|reject|reshoot. |

## Timber & trucks

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/timber` | `get_timber` | — | — | Last 200 timber movements. |
| GET | `/api/timber/volume-by-sector` | `timber_volume` | — | — | Actual vs planned volume per sector. |
| GET | `/api/trucks` | `get_trucks` | — | — | Last 200 truck reports. |

## Photos

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/photos` | `get_photos` | — | sector photo_type | Work photos, filters `sector`, `photo_type`, max 300. |

## Reports

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/report/pdf/{sector_name}` | `generate_pdf` | — | — | Sector PDF (reportlab). Returns 500 JSON if reportlab missing — **reportlab is not in requirements.txt**. |

## Satellite (imagery)

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| POST | `/api/sectors/{name}/satellite` | `upload_sector_satellite` | file | — | Multipart manual satellite image for a sector. |
| GET | `/api/sectors/{name}/satellite-image` | `get_sector_satellite_image` | — | — | Manual image if present, else redirect to `/api/satellite/image/{name}`. |
| GET | `/api/satellite/token-check` | `satellite_token_check` | — | — | Copernicus OAuth check; returns first 20 chars of client id. |
| GET | `/api/satellite/sectors` | `satellite_sectors` | — | — | Sectors with bbox for imagery browser (falls back to Riga point). |
| GET | `/api/satellite/image/{sector_name}` | `satellite_image` | — | date_from date_to | Live Sentinel-2 L2A true-colour JPEG 512×512, query `date_from`/`date_to` (default 2024-06-01..30), cloud ≤50%. Not cached. |
| GET | `/api/satellite/object/{plan_id}` | `satellite_object` | — | date_from date_to | Same over all sectors of an object. |
| GET | `/api/satellite/ndvi/{sector_name}` | `satellite_ndvi` | — | date_from date_to | Live NDVI colour-classified JPEG (4 classes). |

## Satellite Intelligence

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/satellite-intel/providers` | `satellite_intel_providers` | — | — | Provider list + configured flag + last observation. |
| GET | `/api/satellite-intel/sectors` | `satellite_intel_sectors` | — | — | Latest satellite score/band/tier, pending request per sector. |
| GET | `/api/satellite-intel/sector/{sector_name}` | `satellite_intel_sector_detail` | — | — | Score, requests, observations, timeline for one sector. |

## Integration Layer

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| GET | `/api/integrations` | `list_integrations_route` | — | category | Catalog merged with configured instances; optional `category`. |
| POST | `/api/integrations` | `create_integration_route` | CreateIntegrationIn | — | Create instance for a catalog provider (400 if unknown). |
| GET | `/api/integrations/health` | `integrations_health_route` | — | — | Counts by status; connected-but-never-synced ids. |
| GET | `/api/integrations/{integration_id}` | `get_integration_route` | — | — | Instance + catalog entry. |
| PATCH | `/api/integrations/{integration_id}` | `update_integration_route` | UpdateIntegrationIn | — | Update name/config/frequency/status; `credentials` encrypted (Fernet) and never returned. |
| DELETE | `/api/integrations/{integration_id}` | `delete_integration_route` | — | — | Delete instance. |
| POST | `/api/integrations/{integration_id}/test` | `test_integration_route` | — | — | Adapter `test_connection`. |
| POST | `/api/integrations/{integration_id}/sync` | `sync_integration_route` | — | — | Run sync now (only demo adapters are implemented). |
| GET | `/api/integrations/{integration_id}/logs` | `get_integration_logs_route` | — | limit | Logs + sync history. |
| GET | `/api/integrations/{integration_id}/records` | `get_integration_records_route` | — | limit | Staged normalized records. |
| POST | `/api/integrations/{integration_id}/reset-demo` | `reset_integration_demo_route` | — | — | Remove demo records of a demo integration. |

## Demo

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| POST | `/api/demo/reset` | `demo_reset_route` | — | — | Deletes is_demo rows. |
| POST | `/api/demo/{scenario}` | `run_demo_scenario` | — | — | `scenario` ∈ breakdown, worker-exit, volume-mismatch, wetland, logging-boundary. Creates real incident + real Telegram message. |

## Webhooks (no Basic Auth)

| Method | Path | Handler | Body | Query | Behaviour |
|---|---|---|---|---|---|
| POST | `/api/webhooks/{provider}` | `integration_webhook_route` | — | — | Raw body; HMAC-SHA256 via `X-Signature`/`X-Hub-Signature-256` if `WEBHOOK_SECRET_<PROVIDER>` set (401 on mismatch); replay-dedup by payload hash; 429 over 30/min per provider+IP. Stage 1: only logged, not routed to adapters. |

## Telegram bot surface (bot.py) — not HTTP, listed for completeness

Commands: `/start` `/help` `/checkin` `/finish` `/add_sector` `/add_risk` `/add_timber` `/add_truck` `/sectors` `/risks` `/report` `/export_report`,
demo (admin-only): `/demo_breakdown` `/demo_worker_exit` `/demo_volume_mismatch` `/demo_wetland` `/demo_logging_boundary` `/demo_reset`.
Callbacks: `checkin_sector:` `linkemp:` `vehgps_sector:` `vehgps_vehicle:` `plan_*` `repair_menu:` `repair_choice:` `confirm_return:` `brk_diag:` `brk_action|sxt_action|wtl_action|vol_action|log_action:`.
Message handlers: location (check-in, live-location edits, vehicle ping), photo (work photo, plan OCR, demo evidence), text (menu router; worker reply capture at group −1).
**Only `/demo_*` is access-controlled.** Pipe-separated command formats: see `bot.py` handlers.

## Endpoints referenced by the frontend
All 64 distinct `/api/...` path patterns referenced in `index.html` map to existing routes (scripted check 2026-10-21; one pattern built by string concatenation verified manually). No frontend call to any chat/history endpoint for AI Inspector exists.
