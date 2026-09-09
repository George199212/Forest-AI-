# DATABASE.md — Forest AI

**Обновлено:** 2026-09-09, по построчному чтению `database.py` (коммит
`0db0a79`). Все `CREATE TABLE`/`ALTER TABLE` — реальные, скопированы из кода.

## 1. Движок и подключение

- **SQLite**, файл `data/forest_ai.db` (переопределяется `DB_PATH` env).
- Без ORM. Каждая функция открывает своё `sqlite3.connect(DB_NAME)` и
  закрывает после запроса. Нет connection pool, нет единого модуля доступа —
  `api.py` тоже открывает прямые `sqlite3.connect()` в своих роутах (`db()`,
  `db1()`, `n()` helpers), а не только через функции `database.py`.
- **Единая точка создания схемы**: `database.py::init_db()` →
  `_migrate()`. Вызывается и из `api.py` (`@app.on_event("startup")`), и из
  `bot.py` — любой процесс поднимает БД с нуля идентично.
- Миграции — только additive: `_add_column_if_missing(cur, table, column,
  definition)` — helper на `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`.
  Единственное исключение — управляемый rebuild `vehicle_gps_pings` (см. §3).

## 2. Таблицы (17 штук, все из `_migrate()`)

| Таблица | Назначение | Ключевые поля |
|---|---|---|
| `sectors` | Лесные участки/сектора | `name`, `boundary_json`, `center_lat/lon`, `area_ha`, `boundary_plan_id` (FK на `boundary_plans`), `object_name`, `pixel_boundary_json` |
| `risks` | **Двойное назначение**: ручные риски И авто-инциденты | `sector`, `risk_level`, `reason`; для инцидентов доп.: `entity_type`, `entity_id`, `status`, `rule_code`, `ai_recommendation`, `distance_m`, `duration_min`, `notified_at`, `resolved_at`, `telegram_message_id`, `photo_path`, `photo_path_2` |
| `risk_events` | Аудит-лог по каждому risk/incident | `risk_id`, `event_type`, `actor`, `details`, `created_at` |
| `sector_employees` | Сотрудники сектора | `sector`, `full_name`, `role`, `telegram_user_id`, `active` |
| `sector_vehicles` | Грузовики | `sector`, `plate`, `driver`, `fuel_capacity_l`, `total_km`, `telegram_user_id`, `employee_id` |
| `sector_equipment` | Харвестеры/форвардеры (отдельно от vehicles) | `sector`, `equipment_code`, `type`, `operator_employee_id`, `status` (default `OFFLINE`), `fuel_level_pct`, `working_hours_today` |
| `vehicle_fuel_logs` | Заправки | `vehicle_id`, `km_start/end`, `fuel_added_l`, `fuel_calc_l`, `discrepancy_l` |
| `vehicle_gps_pings` | Обобщённый GPS-лог (не только vehicle, несмотря на имя) | `vehicle_id` (nullable), `employee_id`, `equipment_id`, `entity_type` (`VEHICLE`/`EMPLOYEE`/`EQUIPMENT`), `latitude/longitude`, `inside_boundary`, `recorded_at` |
| `live_locations` | Текущее состояние Telegram Live Location по сотруднику | `employee_id`, `telegram_user_id`, `sector`, `latitude/longitude`, `expires_at`, `last_status` (IN/OUT) |
| `sector_snapshots` | Спутниковые/архивные снимки сектора по датам | `sector`, `image_path`, `snapshot_date`, `source` (default `geolatvija`), `risk_level` |
| `snapshot_risks` | Many-to-many: снимок ↔ риск | `snapshot_id`, `risk_id` |
| `work_sessions` | GPS check-in/check-out полевых работников | `employee`, `employee_id`, `sector`, `check_in_time`, `finish_time`, `distance_m`, `approved` |
| `work_photos` | Фото с полевых сессий | `session_id`, `sector`, `photo_type`, `image_path` |
| `timber_movements` | Заявленный/фактический объём древесины | `sector`, `planned_volume`, `actual_volume`, `difference_volume`, `status` (`MISSING_VOLUME`/`OVER_VOLUME`/…) |
| `truck_reports` | Отчёты по вывозу | `sector`, `truck_number`, `driver`, `reported_volume` |
| `boundary_plans` | Загруженные сканы "Robežu Plāns" | `file_path`, `document_type`, `status`, `plan_data_json`, `object_name`, `satellite_file_path` |
| `boundary_plan_points` | Точки координат, распознанные OCR | `plan_id` (FK), `point_name`, `x/y_coord`, `lat/lon`, `raw_text` |

**Нет реальных FOREIGN KEY constraints нигде** — `sector` почти везде хранится
как свободный TEXT, связь по имени, не по ID. Единственное исключение —
`boundary_plan_id` в `sectors` (числовой FK-подобное поле, но без
`REFERENCES`/`FOREIGN KEY` в DDL — SQLite это не enforce'ит без явного
`PRAGMA foreign_keys=ON`, которого в коде нет).

## 3. `vehicle_gps_pings` — managed rebuild (не просто ALTER)

Изначально `vehicle_id` был `NOT NULL` (таблица создавалась только для
грузовиков). Когда её обобщили под employee/equipment пинги через
`entity_type`, `NOT NULL` пришлось снять — SQLite не умеет ослаблять
constraint через `ALTER TABLE ADD COLUMN`. Код проверяет текущий
`notnull`-флаг через `PRAGMA table_info`, и если он ещё стоит — пересоздаёт
таблицу (`..._new` → `INSERT INTO ... SELECT ...` → `DROP` → `RENAME`),
сохраняя все данные. Идемпотентно: на уже мигрированной БД блок не
срабатывает повторно.

## 4. `risks` — как отличить ручной риск от авто-инцидента

`entity_type IS NOT NULL` → это инцидент (создан через `add_incident()`,
имеет `rule_code`/`status`-лайфцикл/возможный `ai_recommendation`).
`entity_type IS NULL` → это старый ручной риск (создан через `add_risk()`,
только `sector`/`risk_level`/`reason`). `database.py::get_incidents()`
фильтрует именно по `entity_type IS NOT NULL`.

Известные `rule_code`, реально создаваемые автоматическим кодом (см.
ARCHITECTURE.md §5.1): `SECTOR_EXIT`, `EMERGENCY`. Другие значения
(`EQUIPMENT_BREAKDOWN` и т.п., встречающиеся в демо-данных) вставлены
вручную, не автоматической геозона-логикой.

## 5. Известные особенности / технический долг схемы

1. **`risks` двойного назначения** усложняет запросы — придётся всегда
   помнить про `entity_type IS NOT NULL` фильтр при работе с инцидентами.
2. **Нет FK constraints** на `sector` — опечатка в имени сектора создаёт
   "невидимые" осиротевшие записи без ошибки на уровне БД.
3. **`vehicle_gps_pings`** — имя таблицы теперь вводит в заблуждение (несёт
   не только vehicle-данные), но переименование не делалось, чтобы не ломать
   существующие вызовы/индексы.
4. Нет явных `CREATE INDEX` вообще — все выборки идут full-table-scan (для
   текущего объёма демо-данных не критично, но при росте данных по
   `sector`/`created_at`/`status` в `risks` и `vehicle_gps_pings` понадобятся
   индексы).

## 6. Правила изменения схемы (обязательны)

1. Инспектировать реальную схему и всех вызывающих перед любым изменением.
2. Только additive (`ALTER TABLE ADD COLUMN` / `CREATE TABLE IF NOT EXISTS`).
   Никогда не удалять колонки/таблицы без явного одобрения человека.
3. Каждое изменение схемы — сразу отражается и здесь, и в DATA_MODEL.md.
4. Raw `git diff` → `.patch` файл → review → commit (см. CODING_RULES.md).
