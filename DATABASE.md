# DATABASE.md — Forest AI

**Verified against code:** commit `574bd97` (2026-10-20), `database.py` (2026 lines).
Column lists below were generated on 2026-10-21 by running `database.init_db()` on an empty
file and reading `PRAGMA table_info` — i.e. exactly what the code creates. The production DB
may additionally carry columns/rows from manual scripts — **[NOT VERIFIED]** (no VPS access).
**Supersedes:** earlier DATABASE.md versions (they described 16–17 tables; code now has **37**).

## 1. Engine and access

- SQLite file `data/forest_ai.db` (override `DB_PATH`). Each client instance has its own file.
- No ORM, no pool. Connections are opened per call in `database.py`, `api.py` (`db()/db1()/n()`),
  `bot.py` (`db_execute/db_fetchone/db_fetchall`) and 10 `services/*` modules.
- No WAL / busy-timeout configured in code; `api.py` (+ its AI worker thread) and `bot.py` write concurrently.
- **No FOREIGN KEY constraints anywhere.** Relations are by convention, most via the free-text
  `sector` name (`sectors.name` has no UNIQUE constraint either).
- Only declared indexes/uniques: `idx_session_track_points_session (session_id, recorded_at)`,
  `organizations.slug` UNIQUE, `integration_records.deduplication_key` UNIQUE,
  `integration_webhook_events.payload_hash` UNIQUE, `photo_cmp_point_photos (run_id, photo_id)` UNIQUE.

## 2. Schema management

- Single entry point: `database.init_db()` → `_migrate()`; called by `api.py` startup and `bot.py` main.
- Migrations are additive only: `CREATE TABLE IF NOT EXISTS` + `_add_column_if_missing()` (`ALTER TABLE ADD COLUMN`).
- One managed rebuild: `vehicle_gps_pings` (drop `NOT NULL` on `vehicle_id`), guarded by `PRAGMA table_info`, re-run safe.
- Seeds one row `organizations(id=1, 'Default Organization', 'default')` if empty.
- There is no migration version table; schema state = "whatever init_db() last added".

## 3. Tables (37)

### Core operations

**`sectors`** — `id` INTEGER PK · `name` TEXT · `contractor` TEXT · `status` TEXT · `approved_volume` TEXT · `map_url` TEXT · `image_path` TEXT · `boundary_json` TEXT · `center_lat` REAL · `center_lon` REAL · `area_ha` REAL · `color` TEXT DEFAULT 'red' · `created_at` TEXT · `updated_at` TEXT · `tree_species` TEXT · `cut_plan_notes` TEXT · `notes` TEXT · `boundary_plan_id` INTEGER · `object_name` TEXT · `pixel_boundary_json` TEXT · `satellite_file_path` TEXT

**`risks`** — `id` INTEGER PK · `sector` TEXT · `risk_level` TEXT · `reason` TEXT · `created_at` TEXT · `entity_type` TEXT · `entity_id` INTEGER · `status` TEXT DEFAULT 'OPEN' · `rule_code` TEXT · `ai_recommendation` TEXT · `distance_m` REAL · `duration_min` REAL · `notified_at` TEXT · `resolved_at` TEXT · `telegram_message_id` TEXT · `photo_path` TEXT · `photo_path_2` TEXT · `is_demo` INTEGER DEFAULT 0 · `pinned_order` INTEGER DEFAULT NULL · `ai_status` TEXT · `ai_attempts` INTEGER DEFAULT 0 · `session_id` INTEGER · `identity_ambiguous` INTEGER · `identity_shared_count` INTEGER · `occurred_at` TEXT

**`risk_events`** — `id` INTEGER PK · `risk_id` INTEGER NOT NULL · `event_type` TEXT NOT NULL · `actor` TEXT · `details` TEXT · `created_at` TEXT NOT NULL

**`sector_employees`** — `id` INTEGER PK · `sector` TEXT NOT NULL · `full_name` TEXT · `role` TEXT · `phone` TEXT · `id_number` TEXT · `notes` TEXT · `active` INTEGER DEFAULT 1 · `created_at` TEXT · `telegram_user_id` TEXT

**`sector_vehicles`** — `id` INTEGER PK · `sector` TEXT NOT NULL · `plate` TEXT · `vehicle_type` TEXT · `driver` TEXT · `fuel_capacity_l` REAL · `fuel_per_100km` REAL · `total_km` REAL DEFAULT 0 · `notes` TEXT · `active` INTEGER DEFAULT 1 · `created_at` TEXT · `telegram_user_id` TEXT · `employee_id` INTEGER

**`sector_equipment`** — `id` INTEGER PK · `sector` TEXT NOT NULL · `equipment_code` TEXT · `type` TEXT · `brand` TEXT · `model` TEXT · `registration_id` TEXT · `photo_url` TEXT · `operator_employee_id` INTEGER · `status` TEXT DEFAULT 'OFFLINE' · `current_task` TEXT · `fuel_level_pct` REAL · `working_hours_today` REAL DEFAULT 0 · `active` INTEGER DEFAULT 1 · `created_at` TEXT · `is_demo` INTEGER DEFAULT 0

**`vehicle_fuel_logs`** — `id` INTEGER PK · `vehicle_id` INTEGER · `sector` TEXT · `km_start` REAL · `km_end` REAL · `km_driven` REAL · `fuel_added_l` REAL · `fuel_calc_l` REAL · `discrepancy_l` REAL · `note` TEXT · `logged_at` TEXT

**`vehicle_gps_pings`** — `id` INTEGER PK · `vehicle_id` INTEGER · `sector` TEXT NOT NULL · `latitude` REAL · `longitude` REAL · `inside_boundary` INTEGER · `recorded_at` TEXT · `entity_type` TEXT DEFAULT 'VEHICLE' · `employee_id` INTEGER · `equipment_id` INTEGER

**`live_locations`** — `id` INTEGER PK · `employee_id` INTEGER · `telegram_user_id` TEXT · `sector` TEXT · `latitude` REAL · `longitude` REAL · `live_period` INTEGER · `started_at` TEXT · `updated_at` TEXT · `expires_at` TEXT · `last_status` TEXT

### Field work (Telegram)

**`work_sessions`** — `id` INTEGER PK · `user_id` TEXT · `employee` TEXT · `employee_id` INTEGER · `contractor` TEXT · `sector` TEXT · `check_in_time` TEXT · `finish_time` TEXT · `latitude` REAL · `longitude` REAL · `distance_m` REAL · `approved` TEXT · `comment` TEXT · `identity_ambiguous` INTEGER · `identity_shared_count` INTEGER

**`work_photos`** — `id` INTEGER PK · `session_id` INTEGER · `sector` TEXT · `photo_type` TEXT · `image_path` TEXT · `uploaded_at` TEXT

**`session_track_points`** — `id` INTEGER PK · `session_id` INTEGER NOT NULL · `employee_id` INTEGER · `telegram_user_id` TEXT · `live_message_id` INTEGER · `sector` TEXT · `latitude` REAL NOT NULL · `longitude` REAL NOT NULL · `horizontal_accuracy` REAL · `inside_boundary` INTEGER · `recorded_at` TEXT NOT NULL · `received_at` TEXT  
  Constraints: INDEX (session_id, recorded_at)

**`timber_movements`** — `id` INTEGER PK · `sector` TEXT · `planned_volume` REAL · `actual_volume` REAL · `difference_volume` REAL · `status` TEXT · `note` TEXT · `created_at` TEXT · `is_demo` INTEGER DEFAULT 0

**`truck_reports`** — `id` INTEGER PK · `sector` TEXT · `truck_number` TEXT · `driver` TEXT · `reported_volume` REAL · `note` TEXT · `created_at` TEXT

### Boundary plans (Robežu Plāns OCR)

**`boundary_plans`** — `id` INTEGER PK · `file_path` TEXT · `document_type` TEXT · `uploaded_at` TEXT · `status` TEXT DEFAULT 'uploaded' · `uploaded_by` TEXT · `plan_data_json` TEXT · `object_name` TEXT · `satellite_file_path` TEXT

**`boundary_plan_points`** — `id` INTEGER PK · `plan_id` INTEGER · `point_name` TEXT · `x_coord` REAL · `y_coord` REAL · `lat` REAL · `lon` REAL · `raw_text` TEXT

### Snapshots / imagery history

**`sector_snapshots`** — `id` INTEGER PK · `sector` TEXT NOT NULL · `image_path` TEXT NOT NULL · `snapshot_date` TEXT · `label` TEXT · `note` TEXT · `source` TEXT DEFAULT 'geolatvija' · `uploaded_at` TEXT · `risk_level` TEXT

**`snapshot_risks`** — `id` INTEGER PK · `snapshot_id` INTEGER NOT NULL · `risk_id` INTEGER NOT NULL

### AI Inspector

**`ai_inspector_analyses`** — `id` INTEGER PK · `scope` TEXT NOT NULL · `sector` TEXT · `summary_text` TEXT · `risk_breakdown_json` TEXT · `exposure_low` REAL · `exposure_high` REAL · `exposure_basis` TEXT · `model` TEXT · `created_at` TEXT NOT NULL

### Satellite Intelligence Engine

**`satellite_observations`** — `id` INTEGER PK · `sector` TEXT NOT NULL · `provider` TEXT NOT NULL · `satellite` TEXT · `tier` TEXT NOT NULL · `acquisition_date` TEXT · `resolution_m` REAL · `cloud_cover_pct` REAL · `bbox_json` TEXT · `image_id` TEXT · `image_ref` TEXT · `source` TEXT DEFAULT 'LIVE' · `cost_eur` REAL · `risk_score` REAL · `ai_analysis_ref` TEXT · `created_at` TEXT NOT NULL

**`satellite_requests`** — `id` INTEGER PK · `sector` TEXT NOT NULL · `tier` TEXT NOT NULL · `provider` TEXT NOT NULL · `estimated_cost_eur` REAL · `reason` TEXT · `justification` TEXT NOT NULL · `satellite_risk_score` REAL · `requested_resolution_m` REAL · `aoi_area_ha` REAL · `approval_status` TEXT DEFAULT 'PENDING' · `combined_group_id` TEXT · `linked_incident_id` INTEGER · `fulfilled_observation_id` INTEGER · `created_at` TEXT NOT NULL · `fulfilled_at` TEXT

**`sector_satellite_scores`** — `id` INTEGER PK · `sector` TEXT NOT NULL · `score` REAL NOT NULL · `band` TEXT NOT NULL · `tier_recommended` TEXT · `inputs_json` TEXT · `computed_at` TEXT NOT NULL

**`satellite_timeline_events`** — `id` INTEGER PK · `sector` TEXT NOT NULL · `event_type` TEXT NOT NULL · `label` TEXT · `detail` TEXT · `ref_table` TEXT · `ref_id` INTEGER · `occurred_at` TEXT NOT NULL

### Integration Layer

**`organizations`** — `id` INTEGER PK · `name` TEXT NOT NULL · `slug` TEXT · `created_at` TEXT  
  Constraints: UNIQUE (slug)

**`integrations`** — `id` INTEGER PK · `organization_id` INTEGER NOT NULL DEFAULT 1 · `category` TEXT NOT NULL · `provider` TEXT NOT NULL · `integration_type` TEXT · `display_name` TEXT · `connection_status` TEXT NOT NULL DEFAULT 'NOT_CONNECTED' · `sync_status` TEXT NOT NULL DEFAULT 'IDLE' · `is_demo` INTEGER NOT NULL DEFAULT 0 · `credentials_reference` TEXT · `configuration_json` TEXT · `sync_frequency_minutes` INTEGER DEFAULT 60 · `last_sync_at` TEXT · `next_sync_at` TEXT · `last_success_at` TEXT · `last_error_at` TEXT · `error_message` TEXT · `records_received` INTEGER NOT NULL DEFAULT 0 · `created_at` TEXT · `updated_at` TEXT

**`integration_credentials`** — `id` INTEGER PK · `integration_id` INTEGER NOT NULL · `encrypted_value` TEXT NOT NULL · `created_at` TEXT · `updated_at` TEXT

**`integration_sync_runs`** — `id` INTEGER PK · `integration_id` INTEGER NOT NULL · `trigger` TEXT · `status` TEXT NOT NULL DEFAULT 'RUNNING' · `records_fetched` INTEGER DEFAULT 0 · `records_saved` INTEGER DEFAULT 0 · `records_deduplicated` INTEGER DEFAULT 0 · `error_message` TEXT · `started_at` TEXT · `finished_at` TEXT

**`integration_logs`** — `id` INTEGER PK · `integration_id` INTEGER NOT NULL · `sync_run_id` INTEGER · `level` TEXT NOT NULL DEFAULT 'INFO' · `message` TEXT NOT NULL · `created_at` TEXT

**`integration_records`** — `id` INTEGER PK · `integration_id` INTEGER NOT NULL · `organization_id` INTEGER NOT NULL DEFAULT 1 · `source_provider` TEXT NOT NULL · `entity_type` TEXT NOT NULL · `external_id` TEXT NOT NULL · `sector` TEXT · `source_timestamp` TEXT · `received_at` TEXT NOT NULL · `raw_payload_json` TEXT · `normalized_payload_json` TEXT · `validation_status` TEXT NOT NULL DEFAULT 'PENDING' · `processing_status` TEXT NOT NULL DEFAULT 'PENDING' · `deduplication_key` TEXT NOT NULL · `linked_table` TEXT · `linked_id` INTEGER · `is_demo` INTEGER NOT NULL DEFAULT 0 · `created_at` TEXT  
  Constraints: UNIQUE (deduplication_key)

**`integration_webhook_events`** — `id` INTEGER PK · `provider` TEXT NOT NULL · `integration_id` INTEGER · `payload_hash` TEXT NOT NULL · `signature_valid` INTEGER · `status` TEXT NOT NULL DEFAULT 'RECEIVED' · `received_at` TEXT NOT NULL · `processed_at` TEXT  
  Constraints: UNIQUE (payload_hash)

**`weighbridge_records`** — `id` INTEGER PK · `integration_id` INTEGER · `sector` TEXT · `vehicle_plate` TEXT · `driver` TEXT · `trip_number` TEXT · `destination` TEXT · `species` TEXT · `assortment` TEXT · `weighed_at` TEXT · `weight_gross_kg` REAL · `weight_tare_kg` REAL · `weight_net_kg` REAL · `declared_volume_m3` REAL · `actual_volume_m3` REAL · `document_number` TEXT · `photo_path` TEXT · `acceptance_status` TEXT DEFAULT 'PENDING' · `is_demo` INTEGER NOT NULL DEFAULT 0 · `source_record_id` INTEGER · `created_at` TEXT

### Photo comparison

**`photo_cmp_runs`** — `id` INTEGER PK · `sector` TEXT NOT NULL · `baseline_date` TEXT NOT NULL · `followup_date` TEXT NOT NULL · `baseline_photo_ids` TEXT NOT NULL · `followup_photo_ids` TEXT NOT NULL · `status` TEXT NOT NULL DEFAULT 'CREATED' · `created_by` TEXT · `created_at` TEXT · `updated_at` TEXT

**`photo_cmp_points`** — `id` INTEGER PK · `run_id` INTEGER NOT NULL · `seq` INTEGER NOT NULL · `kind` TEXT NOT NULL · `match_confidence` TEXT · `confirmed` INTEGER NOT NULL DEFAULT 0 · `confirmed_by` TEXT · `confirmed_at` TEXT · `status` TEXT NOT NULL DEFAULT 'UNCONFIRMED' · `same_place` TEXT · `comparability` TEXT · `comparability_reason` TEXT · `detect_limits` TEXT · `check_attempts` INTEGER NOT NULL DEFAULT 0 · `detect_attempts` INTEGER NOT NULL DEFAULT 0 · `checked_at` TEXT · `detected_at` TEXT · `created_at` TEXT · `updated_at` TEXT

**`photo_cmp_point_photos`** — `id` INTEGER PK · `run_id` INTEGER NOT NULL · `point_id` INTEGER NOT NULL · `photo_id` INTEGER NOT NULL · `side` TEXT NOT NULL · `match_confidence` TEXT · `match_reason` TEXT  
  Constraints: UNIQUE (run_id, photo_id)

**`photo_cmp_changes`** — `id` INTEGER PK · `point_id` INTEGER NOT NULL · `kind` TEXT NOT NULL · `cell` TEXT NOT NULL · `class` TEXT NOT NULL · `description` TEXT · `limits` TEXT · `verification` TEXT · `verification_reason` TEXT · `verify_attempts` INTEGER NOT NULL DEFAULT 0 · `confidence` TEXT · `discarded` INTEGER NOT NULL DEFAULT 0 · `review_status` TEXT NOT NULL DEFAULT 'UNREVIEWED' · `reviewer` TEXT · `reviewed_at` TEXT · `created_at` TEXT · `source` TEXT NOT NULL DEFAULT 'system' · `created_by` TEXT

**`photo_cmp_events`** — `id` INTEGER PK · `run_id` INTEGER · `point_id` INTEGER · `change_id` INTEGER · `event_type` TEXT NOT NULL · `actor` TEXT · `purpose` TEXT · `model` TEXT · `input_tokens` INTEGER · `output_tokens` INTEGER · `details` TEXT · `created_at` TEXT

### Risk conclusion (Slēdziens)

**`risk_conclusions`** — `id` INTEGER PK · `risk_id` INTEGER NOT NULL · `run_id` INTEGER · `status` TEXT NOT NULL · `rule` TEXT · `recommendation` TEXT · `outcome` TEXT · `rule_line` TEXT · `evidence_json` TEXT · `weather_text` TEXT · `weather_source` TEXT · `ai_draft` TEXT · `model` TEXT · `created_by` TEXT · `created_at` TEXT · `final_text` TEXT · `decision` TEXT · `against_recommendation` INTEGER NOT NULL DEFAULT 0 · `override_reason` TEXT · `next_steps` TEXT · `reshoot_points_json` TEXT · `decided_by` TEXT · `decided_at` TEXT · `superseded_by` INTEGER · `superseded_at` TEXT · `text_at` TEXT · `risk_status_before` TEXT · `undone_by` TEXT · `undone_at` TEXT · `undo_reason` TEXT · `restored_as` INTEGER


## 4. Data-quality notes found in code

- `risks.created_at`: two formats — `add_incident()` → `YYYY-MM-DD HH:MM:SS UTC`; `add_risk()` → ISO `datetime.isoformat()`. Code that parses it must accept both.
- `work_sessions.approved` is text `'YES'`/`'NO'`; `finish_time` is `''` (empty string) for open sessions in bot inserts, but some queries also test `IS NULL`.
- `risks.status` has `DEFAULT 'OPEN'`; legacy `add_risk()` rows rely on that default and have `entity_type IS NULL`.
- `sector_equipment.operator_employee_id`, `sector_vehicles.employee_id`, `live_locations.employee_id`, `risks.entity_id` — unenforced references to `sector_employees.id`.
- `sector_employees.telegram_user_id` is not unique: several employees may share one Telegram id; `bot.py::resolve_employee` flags this (`identity_ambiguous`, `identity_shared_count` on `risks`/`work_sessions`).
- `sector_employees.id_number` stores a personal ID number as plain text.
- Missing table vs. earlier project notes: **`ai_inspector_chat_messages` does not exist in code** (no CREATE, no endpoint, no frontend call). If it exists on production, it was created outside the repo.
