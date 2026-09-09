# API.md — Forest AI

**Обновлено:** 2026-09-09, по построчному чтению `api.py` (1811 строк,
коммит `0db0a79`). Все 54 роута ниже — реальные, извлечены grep'ом по
`@app.get/post/put/delete/patch`. **Все роуты требуют HTTP Basic Auth**
(`DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD`) — задано на уровне всего
FastAPI-приложения.

## Frontend / статика
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/` | Отдаёт `index.html` (`FileResponse`, изменения на диске подхватываются без рестарта) |
| GET | `/photos/file/{filename}` | Отдаёт файл фото с диска |

## Summary
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/summary` | KPI для Overview: счётчики, `red_sectors`/`yellow_sectors`, финансовый риск — **суммируется из `ai_recommendation.estimated_exposure_eur_*` по всем инцидентам** (`calc_financial_risk_from_incidents()`), НЕ из `calc_risk_score()` |

## Sectors
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/sectors` | Список секторов + `risk_score/level/color/exposure_label` (из `calc_risk_score()`) и счётчики. **⚠️ Не включает `exposure_low`/`exposure_high` числом** — см. §"Известные несостыковки" ниже |
| POST | `/api/sectors` | Создать сектор (`SectorIn`: name/contractor/status/approved_volume/boundary/color) |
| PUT | `/api/sectors/{name}` | Обновить сектор (тот же body что POST) |
| DELETE | `/api/sectors/{name}` | Удалить сектор |
| GET | `/api/sectors/{name}` | Детали сектора, **включает** `exposure_low/high/vol_at_risk` числом (в отличие от списка выше) |
| PATCH | `/api/sectors/{name}/notes` | Частичное обновление `tree_species`/`cut_plan_notes`/`notes` |
| POST | `/api/sectors/{name}/polygon` | Задать/обновить полигон границы |
| GET | `/api/sectors/{name}/vehicles/{vehicle_id}/route` | Трек движения техники по сектору за период |

## Objects (группировка секторов по одному Robežu Plāns)
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/objects` | Сектора, сгруппированные по `boundary_plan_id` |
| POST | `/api/objects` | Создать объект |
| POST | `/api/objects/{plan_id}/boundary-plan` | Привязать скан плана к объекту |
| POST | `/api/objects/{plan_id}/satellite` | Загрузить спутниковый снимок объекта |
| GET | `/api/objects/{plan_id}/satellite-image` | Получить снимок |
| POST | `/api/objects/{plan_id}/sectors` | Создать сектора внутри объекта (обычно из результата OCR) |

## Boundary plans (OCR границ)
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/boundary-plans/{plan_id}/scan` | Файл скана плана |
| GET | `/api/boundary-plans/{plan_id}/annotated` | Скан с наложенной разметкой |

## Sector snapshots + Snapshot risks
| Метод | Путь | Что делает |
|---|---|---|
| POST | `/api/sectors/{name}/snapshots` | Загрузить снимок сектора по дате |
| GET | `/api/sectors/{name}/snapshots` | Список снимков сектора |
| GET | `/api/sectors/snapshots/{id}/image` | Файл снимка |
| DELETE | `/api/sectors/snapshots/{id}` | Удалить снимок (+ файл с диска) |
| POST | `/api/sectors/snapshots/{id}/risks` | Привязать риск к снимку |
| GET | `/api/sectors/snapshots/{id}/risks` | Риски, привязанные к снимку |
| DELETE | `/api/sectors/snapshots/{id}/risks/{risk_id}` | Отвязать риск от снимка |

## Sector satellite (одиночный сектор, не объект)
| Метод | Путь | Что делает |
|---|---|---|
| POST | `/api/sectors/{name}/satellite` | Загрузить снимок для сектора |
| GET | `/api/sectors/{name}/satellite-image` | Получить снимок сектора |
| GET | `/api/sectors/{name}/plan-crop` | Кроп исходного плана по границе сектора |

## Employees
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/employees` | Все сотрудники |
| GET | `/api/employees/{sector}` | Сотрудники сектора |
| POST | `/api/employees` | Создать (`EmployeeIn`: sector/full_name/role/phone/id_number/notes/telegram_user_id) |
| DELETE | `/api/employees/{eid}` | Удалить |
| PATCH | `/api/employees/{eid}` | Частичное обновление любого поля из `EmployeePatchIn` (динамический `SET` только по переданным полям) |

## Vehicles
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/vehicles` | Все грузовики |
| GET | `/api/vehicles/{sector}` | Грузовики сектора (+ последние 5 `fuel_logs` на каждый) |
| POST | `/api/vehicles` | Создать |
| POST | `/api/vehicles/fuel-log` | Записать заправку; **если расхождение > 5л — автоматически создаётся `risk` MEDIUM** через `add_risk()` (не `add_incident()` — это ручной риск, не инцидент с AI-рекомендацией) |
| DELETE | `/api/vehicles/{vid}` | Удалить |
| PATCH | `/api/vehicles/{vid}` | Частичное обновление |

## Risks / Incidents
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/risks` | Все риски (и ручные, и инциденты вперемешку) |
| GET | `/api/risks/by-sector` | Группировка HIGH/MEDIUM/LOW по сектору (для чарта Overview) |
| GET | `/api/risks/{risk_id}` | Детали одного риска/инцидента |
| GET | `/api/risks/{risk_id}/photo` | Первое фото |
| GET | `/api/risks/{risk_id}/photo2` | Второе фото |
| GET | `/api/incidents` | Только инциденты (`entity_type IS NOT NULL`), опц. `?status=` |
| GET | `/api/equipment` | Список техники, опц. `?sector=` |
| POST | `/api/incidents/{incident_id}/approve` | Диспетчер утверждает AI-рекомендацию → шлёт Telegram-сообщение работнику с кнопкой (`🛠 Ремонт техники` если `rule_code=='EQUIPMENT_BREAKDOWN'`, иначе `✓ I HAVE RETURNED`) → статус `NOTIFIED` |
| POST | `/api/risks/{risk_id}/send-message` | Диспетчер шлёт произвольное текстовое сообщение работнику через Telegram |

## GPS / Timber / Trucks / Photos
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/gps` | Последние 200 `work_sessions` |
| GET | `/api/gps/activity` | Агрегированная активность |
| GET | `/api/timber` | Все `timber_movements` |
| GET | `/api/timber/volume-by-sector` | Агрегация для чарта Overview |
| GET | `/api/trucks` | Все `truck_reports` |
| GET | `/api/photos` | Все фото |

## Map / Report
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/map` | Данные для карты (сектора + позиции) |
| GET | `/api/report/pdf/{sector_name}` | Генерация PDF-отчёта по сектору |

## Satellite (Sentinel Hub)
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/satellite/token-check` | Проверка валидности OAuth-токена Sentinel Hub |
| GET | `/api/satellite/sectors` | Список секторов, доступных для спутникового анализа |
| GET | `/api/satellite/image/{sector_name}` | Спутниковый снимок сектора |
| GET | `/api/satellite/object/{plan_id}` | Спутниковый снимок объекта |
| GET | `/api/satellite/ndvi/{sector_name}` | NDVI-слой для сектора |

---

## Известные несостыковки, найденные при инспекции (не выдумки, видно в коде)

1. **`/api/sectors` (список) не отдаёт `exposure_low`/`exposure_high`
   числом** — только `exposure_label` (строка). `/api/sectors/{name}`
   (детали одного сектора) — отдаёт. Это значит, что любой frontend-код,
   суммирующий `sector.exposure_low` по массиву из `/api/sectors` (именно
   так делает `loadInspector()` в `index.html` — см. отдельный разбор для
   AI Inspector), **всегда получит 0**, даже если у секторов есть реальная
   rule-based exposure. Нужно решить с пользователем — либо добавить эти
   поля в `/api/sectors`, либо это осознанно не нужно (т.к. Overview уже
   показывает AI-based финансовый риск из другого источника).
2. **Нет `/api/inspector/*`** — раздела AI Inspector с backend-эндпоинтом
   не существует вообще, вся его "аналитика" сейчас — чистый client-side JS
   (см. ARCHITECTURE.md §6). Это отправная точка для текущей рабочей задачи
   (streaming AI-анализ).
3. **Нет пагинации** почти нигде (кроме `/api/gps` — жёсткий `LIMIT 200`).
   При росте данных `/api/risks`, `/api/employees` и т.п. отдают всё целиком.
