# Forest AI — DATA_MODEL.md

> Обновлено 2026-09-07 по подтверждённой продакшн-схеме (см. `DATABASE.md`).

## Основные сущности

### Sector (участок леса)
Центральная сущность. Идентичность `(name, boundary_plan_id)`. Хранит
геометрию как `boundary_json` (лат/лон) и отдельно `pixel_boundary_json`
(координаты на пиксельном скане плана — для отрисовки поверх исходного
документа).

### Object / Plan (`boundary_plans`)
Группа секторов, пришедших из одного скана Robežu Plāns. OCR/распознавание
теперь идёт через `services/robez_ocr_vision.py` (Claude Vision API,
модель `claude-sonnet-4-5`), а не через Tesseract — старая
`analyze_robez_plan_ocr()` в `bot.py` заменена полностью, сохранён только
формат возвращаемых данных для совместимости.

### Entity Tracking — обобщённая модель (VEHICLE / EMPLOYEE / EQUIPMENT)
Три отдельные "карточки" сущностей:
- **Employee** (`sector_employees`) — привязывается к Telegram через `telegram_user_id`
- **Vehicle** (`sector_vehicles`) — грузовики, привязка через `telegram_user_id`
- **Equipment** (`sector_equipment`) — техника (харвестеры, форвардеры и т.п.),
  у каждой единицы есть `operator_employee_id` (кто оператор), `status`
  (`OFFLINE` по умолчанию), `current_task`, `fuel_level_pct`, `working_hours_today`

Все три типа шлют точки в **одну общую таблицу** `vehicle_gps_pings` через
`entity_type` (`VEHICLE`/`EMPLOYEE`/`EQUIPMENT`) + соответствующий id-столбец
(`vehicle_id`/`employee_id`/`equipment_id`). Единая функция `add_gps_ping()`
и `get_route()` в `database.py` работают со всеми тремя типами одинаково.

### Live Location (`live_locations`)
Отдельная от `vehicle_gps_pings` сущность — конкретно Telegram Live Location
(живая трансляция геопозиции с истечением `expires_at`, `live_period`).
Используется для дашборд-визуализации "кто сейчас онлайн и где" в реальном
времени, в отличие от `vehicle_gps_pings`, которая скорее история точек.
Управляется напрямую из `bot.py` (`upsert_live_location`), не через
`database.py`.

### Risk / Incident (`risks`) — одна таблица, две смысловые роли
1. **Ручной Risk** — создаётся человеком (`/add_risk` в боте или через
   dashboard), поля: `sector`, `risk_level`, `reason`.
2. **Автоматический Incident** — создаётся системой (геозона-детекция,
   `_is_inside_sector` в `bot.py`), дополнительно несёт `entity_type`,
   `entity_id`, `rule_code`, `ai_recommendation`, `distance_m`,
   `duration_min`, lifecycle `status` (`OPEN`→`NOTIFIED`→`RESOLVED`/`DISMISSED`),
   `telegram_message_id` (для последующего апдейта уже отправленного
   Telegram-сообщения об алерте).

Отличать одно от другого: `entity_type IS NOT NULL` = Incident.

### Timber Movement / Truck Report — сверка объёмов
`timber_movements` (план vs факт по сектору) и `truck_reports` (что заявил
водитель) сверяются между собой для risk-score и financial exposure
(логика в `api.py`, `calc_risk_score`).

### Sector Snapshot + Snapshot↔Risk (many-to-many)
`sector_snapshots` — датированные исторические снимки сектора (например, с
geolatvija.lv), отдельно от live-запроса к Sentinel-2. `snapshot_risks` —
join-таблица, позволяющая привязать один или несколько существующих `risks`
к конкретному снапшоту (например, "на этом снимке от 2026-03-01 видно
вырубку — вот привязанный к ней risk").

## Связи

```
boundary_plans (1) ──< sectors (N)                — boundary_plan_id (FK-подобный)
sectors (1) ──< sector_employees (N)              — текст sector, без FK
sectors (1) ──< sector_vehicles (N)               — текст sector, без FK
sectors (1) ──< sector_equipment (N)              — текст sector, без FK
sectors (1) ──< work_sessions (N)                 — текст sector, без FK
sectors (1) ──< risks (N)                          — текст sector, без FK
sectors (1) ──< timber_movements (N)              — текст sector, без FK
sectors (1) ──< truck_reports (N)                 — текст sector, без FK
sectors (1) ──< sector_snapshots (N)              — текст sector, без FK
sector_vehicles (1) ──< vehicle_fuel_logs (N)     — vehicle_id
{vehicle|employee|equipment} (1) ──< vehicle_gps_pings (N) — entity_type + *_id
sector_employees (1) ──< live_locations (N)       — employee_id / telegram_user_id
sector_snapshots (N) ──< snapshot_risks >── (N) risks  — реальная many-to-many join-таблица
sector_equipment.operator_employee_id → sector_employees — логическая связь, без FK
```

**Важно (не изменилось):** ни одна связь "через текст `sector`" не защищена
реальным FK constraint в SQLite — архитектурная особенность, подтверждённая
и в старой памяти проекта, и в реальной схеме.
