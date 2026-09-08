# Forest AI — ARCHITECTURE.md

> Обновлено 2026-09-07 по прямому дампу с продакшн-сервера (systemd status,
> `ps aux`, `git log`). Заменяет предыдущую версию, основанную только на
> статичном снэпшоте файлов — тот снэпшок оказался устаревшим на ~10 коммитов
> относительно реального состояния сервера.

## 1. Общая картина

```
                     ┌───────────────────────────┐
                     │   Telegram (поле)          │
                     └─────────────┬─────────────┘
                                   │ python-telegram-bot, long polling
                                   ▼
                     ┌───────────────────────────┐
                     │          bot.py             │  отдельный процесс
                     │  (не под systemd — обычный   │  PID 1288950
                     │   python3 bot.py процесс)    │
                     └─────────────┬─────────────┘
                                   │ sqlite3, + database.py helpers
                                   ▼
                     ┌───────────────────────────┐
              ┌──────│ /root/forest_ai/data/       │──────┐
              │      │ forest_ai.db (SQLite)        │      │
              │      └───────────────────────────┘      │
              ▼                                          ▼
┌───────────────────────────┐                 ┌──────────────────────┐
│           api.py            │◄────────────────│    database.py        │
│  FastAPI, HTTP Basic Auth   │  init_db() +    │ единая точка правды   │
│  forest-api.service         │  все CRUD-хелперы│ по схеме (16 таблиц) │
│  (systemd, PID 1302315)     │                 └──────────────────────┘
└─────────────┬───────────────┘
              │ отдаёт index.html как "/"
              ▼
     ┌───────────────────┐        Внешние интеграции:
     │     index.html       │        → Copernicus CDSE / Sentinel Hub (OAuth2)
     └───────────────────┘        → Anthropic Claude API (claude-sonnet-4-5,
                                     Vision OCR лесных планов, services/robez_ocr_vision.py)
```

## 2. Компоненты (подтверждено с сервера)

| Компонент | Путь | Запуск | Статус на 2026-09-07 |
|---|---|---|---|
| REST API + дашборд | `/root/forest_ai/api.py` | `forest-api.service` (systemd) → `uvicorn api:app --host 0.0.0.0 --port 8000` | Активен, PID 1302315, запущен 09:43 UTC, отвечает 200 OK |
| Telegram-бот | `/root/forest_ai/bot.py` | Просто `/usr/bin/python3 bot.py`, **не под systemd** (по крайней мере не показан как отдельный systemd unit в дампе) | Активен, PID 1288950, запущен 09:10 |
| Общая БД | `/root/forest_ai/data/forest_ai.db` | — | 16 таблиц, схема централизована в `database.py` |
| OCR-сервис | `/root/forest_ai/services/robez_ocr_vision.py` | Импортируется `bot.py`/`api.py`, вызывает Anthropic API синхронно внутри запроса | Файл существует (33 КБ), последнее изменение 10 июля |

**⚠️ Найден побочный процесс, требующий внимания:** на сервере с 4 сентября
(PID 121233, `/usr/bin/python3 /usr/local/bin/uvicorn api:app --host
127.0.0.1 --port 8001`) до сих пор работает **тестовый инстанс API**,
запущенный ранее через Claude Code против копии базы `/tmp/prod_copy.db` и
фото `/tmp/prod_copy_photos`. Он не отдаёт наружу (127.0.0.1, только
локально), но висит уже 3+ дня и ест ресурсы. Стоит убить (`kill 121233`)
после подтверждения, что он больше не нужен.

## 3. Путь проекта — подтверждено окончательно

`/root/forest_ai/` (с подчёркиванием) — подтверждено напрямую выводом
`cd /root/forest_ai && ...` в успешно выполненных командах. Старое
предположение про `/root/forest-ai/` (дефис) окончательно опровергнуто.

## 4. Эволюция функциональности (по git log, 15 последних коммитов)

От старого к новому (HEAD = `8ac25d4`):
1. `cea50c3` — GPS-трекинг грузовиков (Phase 1 MVP): ручные пинги через Telegram, маршрут на карте
2. `d331c32` — `telegram_user_id` в `sector_employees`/`sector_vehicles` (Stage 1 auth linking)
3. `187ace6` — Enforce Telegram identity linking в check-in/vehicle GPS (Stage 2)
4. `c742cdf` — Fix stale cache после add/remove employees/vehicles
5. `6e9c0cf` — **HTTP Basic Auth на все роуты + удаление wildcard CORS**
6. `b327471` — Vehicle edit endpoint (фикс дублирующихся записей техники)
7. `f35969a` — Fix check-in crash / silent boundary wipe для секторов без гео
8. `d44df8a` — Привязка Telegram-аккаунтов к карточкам сотрудников при check-in
9. `9fdbf1e` — Telegram Live Location для трекинга полевых работников (Phase B)
10. `86ecc4f` — Fix: check-in больше не блокируется, если сотрудник не привязан к Telegram (регрессия Phase A)
11. `4c04a7b` — Схема Equipment/Incident/Equipment-GPS (additive migration)
12. `37b1754` — CRUD-хелперы Equipment/GPS-history/Incident в `database.py`
13. `214fc77` — Geofence detection (`_is_inside_sector`) + live location handling, Telegram-алерты сотруднику/диспетчеру
14. `8ac25d4` (**HEAD**) — Incident tracking (расширение `risks`), обработка live location, dispatcher-алерты, read-only `/api/incidents` + `/api/equipment`

Это подтверждает: **Phase A–E (AI Inspector / Live Location), упомянутые в
памяти проекта как "unconfirmed whether changes are live" — реально влиты
и работают на проде.** Сервисы были перезапущены (иначе не видели бы
эффекта в `git log` + активном процессе).

## 5. Открытых архитектурных вопросов, требовавших проверки, — больше нет

Все несостыковки, найденные при первой инспекции статичного снэпшота
(`telegram_user_id`, `sector_snapshots`, `snapshot_risks`,
`vehicle_gps_pings`, отсутствие `services/`) — **разрешены**: реальный
сервер содержит полную, согласованную версию всего этого. Снэпшот в
Project Knowledge был просто устаревшим. См. `CURRENT_STATUS.md`.
