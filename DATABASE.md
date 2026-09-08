# Forest AI — DATABASE.md

> Обновлено 2026-09-07 по прямому дампу с продакшн-сервера
> (`sqlite3 data/forest_ai.db ".schema"` + `PRAGMA table_info` + реальный
> `database.py`, снятые через Claude Code с `/root/forest_ai/`).
> Это **подтверждённая живая схема**, не гипотеза. Все прошлые пометки
> ⚠️/❌ из первой инспекции — сняты, ниже только факты.

## Все 16 таблиц (+ `sqlite_sequence`)

Создание централизовано в `database.py` (`init_db()` + `_migrate()`) —
и `api.py`, и `bot.py` вызывают `init_db()` на старте, поэтому единая точка
правды по схеме теперь реально есть (ранее упомянутая в памяти проблема
"схема размазана между database.py и bot.py" — **устранена**).

### `sectors`
```
id, name, contractor, status, approved_volume, map_url, image_path,
boundary_json, center_lat, center_lon, area_ha, color DEFAULT 'red',
created_at, updated_at, tree_species, cut_plan_notes, notes,
boundary_plan_id, object_name, pixel_boundary_json, satellite_file_path
```
Идентичность: `(name, boundary_plan_id)`.

### `risks` — теперь двойного назначения: ручные риски + Incident lifecycle
```
id, sector, risk_level, reason, created_at,
entity_type, entity_id, status DEFAULT 'OPEN', rule_code, ai_recommendation,
distance_m, duration_min, notified_at, resolved_at, telegram_message_id
```
Одна и та же таблица обслуживает и старые ручные `/add_risk` записи (только
`sector`/`risk_level`/`reason`), и новые автоматические "инциденты"
(геозона, AI-рекомендации) — различаются по `entity_type IS NOT NULL`.
Статусы инцидента: `OPEN` → `NOTIFIED` → `RESOLVED`/`DISMISSED`.

### `work_sessions`
```
id, user_id, employee, contractor, sector, check_in_time, finish_time,
latitude, longitude, distance_m, approved, comment, employee_id
```
`employee_id` — новая колонка (числовая), появилась вместе с Telegram-привязкой,
но связь с `sector_employees` по-прежнему **не enforced как FK** в SQLite.

### `work_photos`
```
id, session_id, sector, photo_type, image_path, uploaded_at
```

### `timber_movements`
```
id, sector, planned_volume TEXT, delivered_volume TEXT, note, created_at,
actual_volume REAL, difference_volume REAL, status TEXT
```
Legacy-колонки (`planned_volume`/`delivered_volume`, тип TEXT) сосуществуют
с новыми (`actual_volume`/`difference_volume`, тип REAL) — обе группы
реально используются кодом.

### `truck_reports`
```
id, sector, truck_number, driver, reported_volume, note, created_at
```

### `sector_employees`
```
id, sector NOT NULL, full_name, role, phone, id_number, notes,
active DEFAULT 1, created_at, telegram_user_id
```

### `sector_vehicles`
```
id, sector NOT NULL, plate, vehicle_type, driver, fuel_capacity_l,
fuel_per_100km, total_km DEFAULT 0, notes, active DEFAULT 1, created_at,
telegram_user_id
```

### `sector_equipment` — новая сущность (техника/машины, не грузовики)
```
id, sector NOT NULL, equipment_code, type, brand, model, registration_id,
photo_url, operator_employee_id, status DEFAULT 'OFFLINE', current_task,
fuel_level_pct, working_hours_today DEFAULT 0, active DEFAULT 1, created_at
```

### `vehicle_fuel_logs`
```
id, vehicle_id, sector, km_start, km_end, km_driven, fuel_added_l,
fuel_calc_l, discrepancy_l, note, logged_at
```

### `vehicle_gps_pings` — обобщён на VEHICLE/EMPLOYEE/EQUIPMENT
```
id, vehicle_id, sector NOT NULL, latitude, longitude, inside_boundary,
recorded_at, entity_type DEFAULT 'VEHICLE', employee_id, equipment_id
```
`vehicle_id` был NOT NULL, но на сервере уже прошла миграция, ослабляющая
constraint (пересборка таблицы, см. `database.py`, `_migrate()`) — сейчас
может быть NULL для employee/equipment-пингов.

### `live_locations` — Telegram Live Location (Phase B)
```
id, employee_id, telegram_user_id, sector, latitude, longitude,
live_period, started_at, updated_at, expires_at, last_status
```
CRUD-функции (`upsert_live_location`) живут **в `bot.py` напрямую**, не в
`database.py` — единственное исключение из принципа "вся схема
централизована", так как это чисто ботовая логика реального времени.

### `boundary_plans`
```
id, file_path, document_type, uploaded_at, status DEFAULT 'uploaded',
uploaded_by, plan_data_json, object_name, satellite_file_path
```

### `boundary_plan_points`
```
id, plan_id, point_name, x_coord, y_coord, lat, lon, raw_text
```

### `sector_snapshots`
```
id, sector NOT NULL, image_path NOT NULL, snapshot_date, label, note,
source DEFAULT 'geolatvija', uploaded_at, risk_level
```

### `snapshot_risks` — join-таблица many-to-many
```
id, snapshot_id NOT NULL, risk_id NOT NULL
```

## Связки сущность↔таблица GPS/риски (обобщённый паттерн)

`vehicle_gps_pings` и `risks` (как incidents) оба используют общий
`entity_type` (`VEHICLE` / `EMPLOYEE` / `EQUIPMENT`) + соответствующий
`*_id` — это единый паттерн для трекинга людей, техники и грузовиков через
одни и те же таблицы, введённый постепенно через additive-миграции.

## Известные "хвосты", не баги

- `timber_movements` хранит объём в двух параллельных форматах
  (TEXT-legacy + REAL-new) — не путать при новых запросах.
- `risks` — одна таблица, два логических назначения (ручные риски и
  авто-инциденты). Разделять через `entity_type IS NOT NULL`.
