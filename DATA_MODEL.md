# DATA_MODEL.md — Forest AI

**Обновлено:** 2026-09-09, по коду (`database.py`, `api.py`, `bot.py`),
коммит `0db0a79`. Источник истины — реальные таблицы, см. DATABASE.md для
полных DDL.

## 1. Концептуальные сущности

| Сущность | Статус | Таблица(ы) | Идентификация |
|---|---|---|---|
| Sector (сектор/участок) | Есть | `sectors` | `name` (+ `boundary_plan_id` для уникальности внутри одного плана) |
| Object/Parcel (объект — группа секторов из одного скана плана) | Есть, но не отдельная таблица | производное из `sectors.boundary_plan_id` + `object_name`, агрегируется в коде (`get_objects()`), не хранится отдельно | `boundary_plan_id` |
| Boundary Plan (скан "Robežu Plāns") | Есть | `boundary_plans`, `boundary_plan_points` | `id` |
| Employee (сотрудник сектора) | Есть | `sector_employees` | `id`; связь с Telegram через `telegram_user_id` (TEXT) |
| Vehicle (грузовик) | Есть | `sector_vehicles`, `vehicle_fuel_logs` | `id` |
| Equipment (харвестер/форвардер — отдельно от Vehicle) | Есть | `sector_equipment` | `id` |
| GPS Ping (обобщённая точка трека) | Есть | `vehicle_gps_pings` | `id`; `entity_type` определяет, к кому относится (`VEHICLE`/`EMPLOYEE`/`EQUIPMENT`) |
| Live Location (текущее состояние живой геолокации) | Есть | `live_locations` | по `employee_id` — одна активная запись на сотрудника, обновляется, не история |
| Work Session (check-in/check-out полевого работника) | Есть | `work_sessions` | `id` |
| Work Photo | Есть | `work_photos` | `id`, FK `session_id` |
| Timber Movement | Есть | `timber_movements` | `id` |
| Truck Report | Есть | `truck_reports` | `id` |
| Risk (ручной) | Есть | `risks` (где `entity_type IS NULL`) | `id` |
| Incident (авто-детектированный, расширение risks) | Есть | `risks` (где `entity_type IS NOT NULL`) | `id`; лайфцикл через `status` |
| Risk Event (аудит-запись) | Есть | `risk_events` | `id`, FK `risk_id` |
| Sector Snapshot (архивный/спутниковый снимок по дате) | Есть | `sector_snapshots` | `id` |
| Snapshot↔Risk (связь снимка с риском) | Есть | `snapshot_risks` | many-to-many |
| Satellite Observation (NDVI/анализ change-detection) | **Не отдельная сущность** — считается on-the-fly через Sentinel Hub API в `/api/satellite/*`, не сохраняется в БД | — | — |

## 2. Ключевые связи

```
boundary_plans (1) ──< sectors (N)              через sectors.boundary_plan_id
sectors (1, по имени TEXT) ──< sector_employees (N)
sectors (1, по имени TEXT) ──< sector_vehicles (N)
sectors (1, по имени TEXT) ──< sector_equipment (N)
sector_vehicles (1) ──< vehicle_fuel_logs (N)
sector_equipment (1) ──< sector_employees (N)   через operator_employee_id
sector_employees (1) ──< live_locations (N, фактически 1 активная)
{sector_vehicles|sector_employees|sector_equipment} (1) ──< vehicle_gps_pings (N)
                                                  через entity_type+id-колонку
risks (1) ──< risk_events (N)                    через risk_id
sector_snapshots (M) ──< snapshot_risks >── (N) risks
work_sessions (1) ──< work_photos (N)            через session_id
```

**Важно:** связь `sectors` со всеми полевыми таблицами (`risks`,
`work_sessions`, `sector_employees`, и т.д.) идёт по `sector` как свободному
TEXT-полю, а НЕ по числовому FK на `sectors.id`. Нет DB-level constraint,
опечатка в названии сектора создаёт молча "потерянные" записи.

## 3. Инцидент как расширение Risk — модель состояний

`risks.status` для инцидентов (`entity_type IS NOT NULL`) реально
используемые значения (по коду `add_incident`/`update_incident_status`):

```
OPEN ──(диспетчер жмёт Approve, /api/incidents/{id}/approve)──> NOTIFIED
NOTIFIED ──(работник отвечает в Telegram / диспетчер закрывает)──> RESOLVED
                                                              └──> DISMISSED
```

`OPEN` — только что задетектирован, ещё не отправлено уведомление
работнику. `NOTIFIED` — отправлено Telegram-сообщение
(`telegram_message_id` заполняется). `RESOLVED`/`DISMISSED` — финальные
состояния, пишут `resolved_at`. Каждый переход дублируется записью в
`risk_events` для аудита (`DETECTED`, `APPROVED`, `TELEGRAM_SENT`,
`STILL_OUTSIDE`, и т.п. — событий больше, чем формальных статусов, так как
`risk_events` — free-form audit log, не строгий state machine).

## 4. GPS Ping — обобщённая модель (Phase 1 миграция)

Исторически `vehicle_gps_pings` хранил только треки грузовиков
(`vehicle_id NOT NULL`). После обобщения одна и та же таблица несёт треки
трёх типов сущностей одновременно, различаемых `entity_type`:

| entity_type | какая колонка заполнена |
|---|---|
| `VEHICLE` | `vehicle_id` |
| `EMPLOYEE` | `employee_id` |
| `EQUIPMENT` | `equipment_id` |

Функция `database.py::get_route(entity_type, entity_id, start, end)`
выбирает нужную id-колонку динамически через словарь
`{"VEHICLE": "vehicle_id", ...}[entity_type]`.

## 5. Чего в модели данных нет (явно, чтобы не путать с планами)

- Нет модели "Organization"/"Tenant" — система однопользовательская
  (single-tenant), заточена под одного заказчика за раз (сейчас — демо для
  Rīgas meži). Мультитенантность не заложена ни в одной таблице.
- Нет модели "User" отдельно от `sector_employees` — доступ к дашборду
  контролируется одной парой HTTP Basic логин/пароль на всё приложение,
  ролей/уровней доступа нет.
- Нет отдельной таблицы под спутниковые наблюдения/change-detection —
  анализ Sentinel Hub делается по запросу и не персистится (см. §1).
