# Forest AI — API.md

> Обновлено 2026-09-07. Базовые ~52 эндпоинта ниже подтверждены по коду
> `api__5_.py` из Project Knowledge (это состояние сохраняется — только
> HTTP Basic Auth и Sentinel-блок были в нём актуальны). **Начиная с раздела
> "Incidents / Equipment" — эндпоинты подтверждены только по сообщениям
> коммитов git log с продакшн-сервера, точная сигнатура (query-параметры,
> response-shape) НЕ вытащена из исходника `api.py` — это нужно сделать
> отдельным запросом, если нужна точность.**

Все роуты защищены HTTP Basic Auth (`DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD`).

## ✅ Подтверждено по коду (`api__5_.py` + продакшн database.py)

### Frontend / статика
| Метод | Путь |
|---|---|
| GET | `/` |
| GET | `/photos/file/{filename}` |

### Summary
| Метод | Путь |
|---|---|
| GET | `/api/summary` |

### Sectors
| Метод | Путь |
|---|---|
| GET/POST | `/api/sectors` |
| PUT/DELETE/GET | `/api/sectors/{name}` |
| PATCH | `/api/sectors/{name}/notes` |
| POST | `/api/sectors/{name}/polygon` |
| GET | `/api/sectors/{name}/plan-crop` |

### Objects / Plans
| Метод | Путь |
|---|---|
| GET/POST | `/api/objects` |
| POST | `/api/objects/{plan_id}/boundary-plan` |
| POST | `/api/objects/{plan_id}/sectors` |
| GET | `/api/boundary-plans/{plan_id}/scan` |
| GET | `/api/boundary-plans/{plan_id}/annotated` |

### Satellite (загрузка вручную)
| Метод | Путь |
|---|---|
| POST/GET | `/api/objects/{plan_id}/satellite`, `/api/objects/{plan_id}/satellite-image` |
| POST/GET | `/api/sectors/{name}/satellite`, `/api/sectors/{name}/satellite-image` |

### Sector Snapshots — ✅ теперь подтверждён рабочим (все 6 backend-функций существуют в проде)
| Метод | Путь |
|---|---|
| POST/GET | `/api/sectors/{name}/snapshots` |
| GET/DELETE | `/api/sectors/snapshots/{id}/image`, `/api/sectors/snapshots/{id}` |
| POST/GET/DELETE | `/api/sectors/snapshots/{id}/risks[/{risk_id}]` |

### Live Satellite (Sentinel Hub / Copernicus CDSE)
| Метод | Путь |
|---|---|
| GET | `/api/satellite/token-check` |
| GET | `/api/satellite/sectors` |
| GET | `/api/satellite/image/{sector_name}` |
| GET | `/api/satellite/object/{plan_id}` |
| GET | `/api/satellite/ndvi/{sector_name}` |

### Employees / Vehicles — ✅ POST теперь подтверждён рабочим
`telegram_user_id` реально есть и в колонке БД, и в сигнатуре
`add_employee`/`add_vehicle` на проде — прошлое подозрение о падении с
`TypeError` **снято**.
| Метод | Путь |
|---|---|
| GET/POST/DELETE | `/api/employees[/{sector}]`, `/api/employees/{eid}` |
| GET/POST/PATCH/DELETE | `/api/vehicles[/{sector}]`, `/api/vehicles/{vid}` |
| POST | `/api/vehicles/fuel-log` |
| GET | `/api/sectors/{name}/vehicles/{vehicle_id}/route` |

### Risks / GPS / Timber / Trucks / Photos / Map / PDF
| Метод | Путь |
|---|---|
| GET | `/api/risks`, `/api/risks/by-sector` |
| GET | `/api/gps`, `/api/gps/activity` |
| GET | `/api/timber`, `/api/timber/volume-by-sector` |
| GET | `/api/trucks` |
| GET | `/api/photos` |
| GET | `/api/map` |
| GET | `/api/report/pdf/{sector_name}` |

## ⚠️ Подтверждено только по git log (продакшн ушёл на 10 коммитов вперёд) — точная сигнатура не проверена

| Эндпоинт | Источник подтверждения | Что известно |
|---|---|---|
| `GET /api/incidents` | commit `8ac25d4` | Read-only. По `database.get_incidents(status=None)` — вероятно принимает `status` query-параметр |
| `GET /api/equipment` | commit `8ac25d4` | Read-only. По `database.get_equipment(sector=None)` — вероятно принимает `sector` query-параметр |
| Эндпоинты для GPS-пингов сотрудников/техники (`add_gps_ping`) | commit `37b1754` | Обобщённая функция в `database.py` подтверждена, но какой именно роут её вызывает (для employee/equipment, не только vehicle) — не проверено |
| Employee edit endpoint | commit `c61084b` | Существование подтверждено, метод/путь не проверен (вероятно `PATCH /api/employees/{eid}`, по аналогии с vehicles) |
| Live Location webhook/handler | commit `9fdbf1e`, `214fc77` | Это Telegram-хендлер в `bot.py` (`edited_message` / `handle_location`), не HTTP-эндпоинт |

## Risk Score — бизнес-логика (не менялась)
```
score = high_risks*25 + medium_risks*10 + rejected_gps*15 + timber_miss*20 + timber_over*15  (max 100)
LOW ≤30 / MEDIUM ≤60 / HIGH >60
exposure_low/high (€) = f(timber_miss_vol, truck_discrepancy) × 60–120 €/м³ + штрафы за rejected GPS и HIGH risks
```

## Рекомендация
Чтобы закрыть раздел "⚠️", нужен ещё один прогон Claude Code: `cat api.py`
целиком с сервера (это единственное, что не попало в текущий дамп — брали
только `database.py`, а не `api.py`/`bot.py`).
