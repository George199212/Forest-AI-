# DATA_MODEL.md — Forest AI

**Verified against code:** commit `574bd97` (2026-10-20): `database.py`, `api.py`, `bot.py`, `services/*`.
Physical tables and columns: see DATABASE.md. This file describes meaning, relations and lifecycles.
**Supersedes:** earlier DATA_MODEL.md versions.

## 1. Entities

| Entity | Table(s) | Key used by code | Notes |
|---|---|---|---|
| Sector (cutting area) | `sectors` | `name` (text, not unique in schema) | WGS84 polygon in `boundary_json` as `[[lat, lon], ...]`; optional `pixel_boundary_json` on a plan image |
| Object (parcel, group of sectors) | derived: `boundary_plans` + `sectors.boundary_plan_id` | `boundary_plan_id` | No own table; `/api/objects` groups sectors. Sectors without plan → group `None` |
| Boundary plan scan | `boundary_plans`, `boundary_plan_points` | `id` | `plan_data_json` may hold `georef_scale` used to convert drawn pixels to coordinates |
| Employee / worker | `sector_employees` | `id`; Telegram link via `telegram_user_id` | Belongs to exactly one `sector` (text). One Telegram id can map to several employees |
| Vehicle (truck) | `sector_vehicles` | `id`, `plate` | Optional `employee_id`, `telegram_user_id` |
| Equipment (harvester/forwarder) | `sector_equipment` | `id`, `equipment_code` | `operator_employee_id` → employee; `status` default `OFFLINE` |
| Work session (check-in) | `work_sessions` | `id` | Created by bot check-in; `approved` YES/NO from geofence; `finish_time` set by `/finish` or auto-close |
| Worker route | `session_track_points` | `session_id` | Append-only real positions from Telegram Live Location during an active session; never interpolated |
| Live position | `live_locations` | one row per `telegram_user_id` | Latest position + `last_status` IN/OUT; used for transition detection |
| GPS ping (vehicle / employee / equipment) | `vehicle_gps_pings` | `entity_type` + `vehicle_id`/`employee_id`/`equipment_id` | Manual "Vehicle GPS" pings and fleet integration pings |
| Field photo | `work_photos` | `id`, `session_id` | `photo_type`: site / equipment / timber |
| Timber movement | `timber_movements` | `id` | `status`: `OK` / `MISSING_VOLUME` / `OVER_VOLUME` from planned − actual |
| Truck report | `truck_reports` | `id` | Free-text truck number/driver; compared to timber totals per sector |
| Weighbridge ticket | `weighbridge_records` | `id` | Currently only written by the `weighbridge_demo` adapter |
| Risk (manual/legacy) | `risks` with `entity_type IS NULL` | `id` | Created by `add_risk()` |
| Incident (attributed risk) | `risks` with `entity_type IS NOT NULL` | `id` | `entity_type` ∈ EMPLOYEE / SATELLITE (+ fleet/integration values); `rule_code` drives dedup |
| Audit event | `risk_events` | `risk_id` | Append-only log of every detection, message, AI call, decision |
| Risk conclusion | `risk_conclusions` | `risk_id` | Versioned: newer row supersedes older; undo keeps the decided row |
| Photo comparison | `photo_cmp_runs/points/point_photos/changes/events` | `run_id` | Two-date comparison for one sector |
| Sector snapshot (manual historical image) | `sector_snapshots`, `snapshot_risks` | `id` | Uploaded images (default source label `geolatvija`), manually linked to risks |
| Satellite observation / request / score / timeline | `satellite_*`, `sector_satellite_scores` | `sector` | See §5 — currently fed only by demo adapter or external scripts |
| AI Inspector analysis | `ai_inspector_analyses` | `id` | Stored after each streamed analysis |
| Integration instance | `integrations` (+ credentials, sync_runs, logs, records, webhook_events) | `id`, `provider` | `organization_id` always 1 (not an access boundary) |

## 2. Relations (all unenforced — no FKs)

```
sectors.name ◄─ (text) ─ risks.sector, work_sessions.sector, work_photos.sector, timber_movements.sector,
                         truck_reports.sector, sector_employees.sector, sector_vehicles.sector,
                         sector_equipment.sector, live_locations.sector, session_track_points.sector,
                         sector_snapshots.sector, satellite_*.sector, photo_cmp_runs.sector,
                         weighbridge_records.sector, integration_records.sector
sectors.boundary_plan_id ─► boundary_plans.id ◄─ boundary_plan_points.plan_id
sector_employees.id ◄─ risks.entity_id (when entity_type='EMPLOYEE'), work_sessions.employee_id,
                       live_locations.employee_id, session_track_points.employee_id,
                       sector_equipment.operator_employee_id, sector_vehicles.employee_id
work_sessions.id ◄─ work_photos.session_id, session_track_points.session_id, risks.session_id
risks.id ◄─ risk_events.risk_id, risk_conclusions.risk_id, snapshot_risks.risk_id,
            satellite_requests.linked_incident_id
photo_cmp_runs.id ◄─ photo_cmp_points.run_id ◄─ photo_cmp_changes.point_id; risk_conclusions.run_id
integrations.id ◄─ integration_credentials / sync_runs / logs / records / weighbridge_records.integration_id
```

Renaming a sector does **not** cascade; deleting a sector (`DELETE /api/sectors/{name}`) leaves all
dependent rows orphaned.

## 3. Lifecycles

**Incident (`risks.status`):** `OPEN` → `NOTIFIED` (Telegram message sent; `telegram_message_id` stored)
→ `RESOLVED` | `DISMISSED`. Closed set = `('RESOLVED','DISMISSED')` (used by score and conclusion).
`DISMISSED` is recognized by `update_incident_status()` but **no endpoint or bot handler writes it** —
there is no "dismiss as false positive" action in the product today.
Dedup: at most one `OPEN`/`NOTIFIED` incident per `rule_code` + entity (+ sector/session for SECTOR_EXIT).

**AI state on a risk (`risks.ai_status`):** `NULL` → `REQUESTED` → `RUNNING` → `DONE` | `FAILED`
(max 2 attempts; stale RUNNING > 600 s requeued). Existing `ai_recommendation` is never overwritten by the worker.

**Risk conclusion (`risk_conclusions.status`):** `DRAFT` → `INTERIM` (keep working) | `CLOSED` (accept & close,
sets risk RESOLVED) ; older rows → `SUPERSEDED`; decision undo → `UNDONE` + new `DRAFT` (`restored_as`).
`against_recommendation=1` + `override_reason` when a human closes against the rule result.

**Photo comparison point:** `UNCONFIRMED` → confirmed by human → check → detect → verify;
terminal: `NOT_SAME_PLACE`, `NOT_COMPARABLE`, `NOT_COMPARABLE_HUMAN`, `CHECKED`, `DONE`, `FAILED`.
Change review: `UNREVIEWED` → `CONFIRMED` | `REJECTED` | `RESHOOT` (undoable).

**Work session:** check-in creates row (`finish_time=''`) → `/finish` sets `finish_time`; a new check-in
auto-closes the same user's open sessions with a note.

## 4. Evidence chain mapping (raw → processed → AI → human)

| Layer | Where it lives |
|---|---|
| Raw evidence | `work_photos` files, `session_track_points`, `live_locations`, `vehicle_gps_pings`, `timber_movements`, `truck_reports`, `boundary_plans` scans, `sector_snapshots`, Sentinel images (not persisted) |
| Processed data | `work_sessions.approved`/`distance_m`, IN/OUT status, `calc_risk_score()` output (computed on request, not stored), `photo_cmp_points.same_place/comparability`, `satellite_monitoring_score` |
| AI interpretation | `risks.ai_recommendation` (JSON), `ai_inspector_analyses`, `photo_cmp_changes` (system-found), `risk_conclusions.ai_draft` |
| Human decision | `risk_events` with user actor (APPROVED, DISPATCHER_MESSAGE, CONCLUSION_ACCEPTED…), `photo_cmp_changes.review_status`, `risk_conclusions.decision/final_text/decided_by` |

Gaps vs. the target chain: no link table between timber movements, trucks and specific sessions/vehicles;
`truck_reports` do not reference `sector_vehicles`; satellite observations are not linked to real imagery
files; no contractor entity (contractor is a free-text column on `sectors` and `work_sessions`).

## 5. Enumerations used in code

- `risks.risk_level`: `HIGH`, `MEDIUM`, `LOW`.
- `risks.rule_code` written by live code: `SECTOR_EXIT`, `EMERGENCY` (bot); `EQUIPMENT_BREAKDOWN`,
  `TIMBER_VOLUME_MISMATCH`, `UNAUTHORIZED_LOGGING`, `ZONE_PROXIMITY_WARNING` (demo scenarios /
  Inspector report-issue); `FLEET_SECTOR_EXIT`, `SATELLITE_UNREGISTERED_CHANGE`,
  `WEIGHBRIDGE_WAYBILL_MISMATCH`, `TIMBER_VOLUME_OVER_PERMIT` (integration risk rules, demo adapters).
  Rule codes in `satellite_intelligence/events.py` (`STORM_DAMAGE`, `UNAUTHORIZED_FOREST_ROAD`, …) are unreachable — no callers.
- `risks.entity_type` written: `EMPLOYEE`, `SATELLITE` (+ values from integration rules).
- `risk_events.event_type` (40+ distinct literals in code; free text, no enum constraint): DETECTED, STILL_OUTSIDE, APPROVED, TELEGRAM_SENT,
  TELEGRAM_SEND_FAILED, WORKER_REPLIED, DISPATCHER_MESSAGE, DISPATCHER_ALERTED, DISPATCHER_ALERT_FAILED,
  DISPATCHER_NOT_CONFIGURED, AI_RECOMMENDATION_GENERATED, AI_RECOMMENDATION_REPLACED, AI_ANALYSIS_REQUESTED,
  AI_ANALYSIS_FAILED, CONFIRMED_RETURN, RESOLVED, REOPENED, SOS_REPEATED, REPAIR_MENU_OPENED,
  REPAIR_CHOICE_SERVICE/SELF/DISPATCHER_CONSULT, CONCLUSION_DRAFTED/AI_CALL/INTERIM/ACCEPTED/DECISION_UNDONE,
  plus demo-scenario events (LEAVING_ZONE, RETURNING, SAFE, WORK_STOPPED, PHOTO_RECEIVED, LOCATION_RECEIVED, …).
- `sector_snapshots.risk_level`: `''`, `LOW`, `MEDIUM`, `HIGH` (validated in API).
- Satellite tiers (`models.py`): TIER_1_BASELINE, TIER_2_FREQUENT, TIER_3A_OPTICAL_HIGHRES, TIER_3B_SAR_HIGHRES;
  bands NORMAL / WATCH / MEDIUM / HIGH / CRITICAL.
- `integrations.connection_status` default `NOT_CONNECTED`; `sync_status` default `IDLE`;
  `integration_records.validation_status/processing_status` default `PENDING`.

## 6. Missing-data semantics (0 vs NULL vs UNKNOWN) — as implemented

- `calc_financial_risk_from_incidents()` skips risks without exposure fields (not counted as 0) — correct.
- `calc_risk_score()` uses `COALESCE(...,0)` for volumes: a sector with **no** timber/truck data scores the same as one with verified zero discrepancy.
- `/api/summary` and many endpoints return `0` when a table is empty — the UI cannot distinguish "no data" from "zero".
- Sentinel endpoints fall back to a hardcoded Riga point (56.95, 24.11) and a ±0.05° box when a sector has no center/boundary — imagery returned for the wrong place instead of "no location".
- Bot geofence falls back to a 10 km radius around a hardcoded Riga point when a sector has no boundary and no center.
- `risk_conclusion` uses the literal `"nav datu"` for missing values — explicit UNKNOWN, correct.
