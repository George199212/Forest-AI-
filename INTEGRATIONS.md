# INTEGRATIONS.md — Forest AI

**Обновлено:** 2026-09-09, по коду коммита `0db0a79`.

## 1. Anthropic Claude API — используется ВНУТРИ продукта (две независимые интеграции)

### a) `services/ai_resolution.py` — рекомендации по инцидентам
- Модель: `claude-sonnet-4-5`, `max_tokens=2048` (было `1024`, увеличено
  после наблюдавшихся обрезаний JSON на части инцидентов — см.
  CURRENT_STATUS.md).
- Вызывается синхронно из `bot.py::handle_location()` через
  `loop.run_in_executor()` (чтобы не блокировать asyncio event loop бота
  на время сетевого запроса), сразу после `add_incident()` при детекции
  `SECTOR_EXIT`/`EMERGENCY`.
- Промпт — строгий JSON-контракт (`summary`, `options[]` с готовыми
  Telegram-текстами на русском, `recommended_option_id`,
  `estimated_exposure_eur_low/high`, `exposure_basis`), явная защита от
  галлюцинаций ("Based ONLY on the information given above... do not
  invent"). Никогда не бросает исключение наружу — при ошибке возвращает
  `None`, логирует через `print()`.
- **Никакого стриминга** (`stream=True` не используется) — обычный
  синхронный `client.messages.create()`, ответ приходит целиком.

### b) `services/robez_ocr_vision.py` — OCR сканов "Robežu Plāns"
- Заменил `pytesseract`-путь, который часто возвращал 0 точек на
  зашумлённых латышско-цифровых таблицах координат.
- Claude Vision читает изображение плана напрямую, возвращает
  структурированный JSON (`plan_title`, `total_area_ha`, `raw_points[]`,
  `proposed_sectors[]` — включая множественные под-фигуры/участки на одном
  плане, это отдельно чинили патчем от 2026-07-09).
- **Нет кэширования по хэшу файла** — повторная загрузка того же скана
  снова тратит платный вызов Claude API. Известный технический долг.

Обе интеграции используют **один и тот же `ANTHROPIC_API_KEY`**, но с
независимой инициализацией клиента в каждом файле (см. докстроку в
`ai_resolution.py`: "Same lazy Anthropic client pattern as
services/robez_ocr_vision.py").

## 2. Copernicus / Sentinel Hub — спутниковые снимки и NDVI

- OAuth client-credentials flow, креды `SENTINEL_CLIENT_ID`/
  `SENTINEL_CLIENT_SECRET`.
- Реализовано напрямую в `api.py` (не вынесено в `services/`):
  `/api/satellite/token-check`, `/api/satellite/sectors`,
  `/api/satellite/image/{sector_name}`, `/api/satellite/object/{plan_id}`,
  `/api/satellite/ndvi/{sector_name}`.
- `/api/satellite/sectors` вычисляет bbox из `boundary_json` сектора (либо
  fallback ±0.05° вокруг последней известной GPS-точки, если границы нет) —
  чисто геометрический расчёт, без вызова внешнего API на этом шаге.
- `/api/satellite/image/{sector_name}` принимает `date_from`/`date_to`
  query-параметры (default `2024-06-01`..`2024-06-30` — **это дефолт из
  прошлого года, стоит проверить, актуален ли он при демо**).
- Снимки/NDVI **не сохраняются в БД** — считаются on-the-fly по запросу
  (см. DATA_MODEL.md §1). `sector_snapshots` — отдельная, независимая
  таблица под вручную/скриптово загруженные архивные снимки, не под
  Sentinel Hub API результаты.

## 3. Telegram

- Bot: `python-telegram-bot`, **polling**-режим (не webhook) — подтверждено
  по `bot.py` (`app.run_polling()` — типовой запуск, отдельный процесс от
  `api.py`).
- `api.py` шлёт сообщения работникам напрямую через `requests.post()` к
  `https://api.telegram.org/bot{token}/sendMessage`, а не через SDK бота —
  то есть отправка исходящих сообщений дублирует HTTP-клиент отдельно от
  `bot.py`'шного SDK-объекта. Два разных способа общаться с Telegram API
  внутри одного проекта — исторически сложилось, работает, но не
  единообразно.
- `DISPATCHER_CHAT_ID` — опциональная env-переменная; если не задана,
  `bot.py` просто логирует и пропускает алерт диспетчеру (без падения).

## 4. GitHub

- Репозиторий: `github.com/George199212/Forest-AI-`, ветка `master`.
- В корне репозитория, кроме кода, лежат **свои** `ROADMAP.md`,
  `KNOWN_BUGS.md`, а также — что важно — **свои копии** `ARCHITECTURE.md`,
  `DATABASE.md`, `DATA_MODEL.md`, `API.md`, `INTEGRATIONS.md`,
  `CURRENT_STATUS.md` (все шесть, коммит `430f56d`, 2026-09-08). Это
  **отдельный набор** от документов в Project Knowledge данного Claude
  Project — они физически разные файлы в разных местах, легко разойтись.
  См. отдельное сравнение репо-версий vs Project-Knowledge-версий (шаг 2
  задачи текущей сессии).
- `install.sh` в корне — однострочный установщик стороннего инструмента
  `codebase-memory-mcp` (DeusData), не относится к Forest AI, просто лежит
  в репозитории отдельно.

## 5. Переменные окружения (из `.env.example`, актуально на коммит `0db0a79`)

```
ANTHROPIC_API_KEY          # обе AI-интеграции (ai_resolution.py, robez_ocr_vision.py)
TELEGRAM_BOT_TOKEN         # bot.py — обязателен, без него бот не стартует
SENTINEL_CLIENT_ID         # Copernicus/Sentinel Hub OAuth
SENTINEL_CLIENT_SECRET     # Copernicus/Sentinel Hub OAuth
DASHBOARD_USERNAME         # HTTP Basic Auth на весь api.py
DASHBOARD_PASSWORD         # HTTP Basic Auth на весь api.py
DISPATCHER_CHAT_ID         # опционально — Telegram-алерт диспетчеру при sector exit
# опционально:
DB_PATH                    # default: data/forest_ai.db
PHOTOS_DIR                 # default: data/work_photos
```

## 6. Integration Layer (added 2026-09-24) — `services/integrations/`

Generic adapter framework for external forestry-company systems (machine
telematics, fleet GPS, GIS, satellite, timber/weighbridge, worker, ERP,
audit). See `services/integrations/base.py::IntegrationAdapter` for the
lifecycle interface, `registry.py` for the full provider catalog, and
`demo/` for the three stage-1 implemented adapters (Fleet GPS, Sentinel,
Weighbridge — all synthetic, no network calls).

**Implemented (stage 1):** `fleet_gps_demo`, `sentinel_demo`,
`weighbridge_demo` — demo-only, `is_demo=1`, deterministic synthetic data.
**Everything else in the catalog (PONSSE, John Deere ×2, Komatsu ×3, ZF
SCALAR, LVM GEO, PlanetScope/SkySat/Maxar/ICEYE, TIMBRO Audit, generic
ERP/GIS/timber/weighbridge) is catalog-only** — no adapter code exists,
`implemented=False`, never shown as Connected. KRAUZERS (fleet/telematics)
and TIMBRO (forest audit) have a `confirmed_customer_use` note attached
(see `registry.py`) but no confirmed vendor/API — do not name a specific
product for either in any client-facing material until confirmed.

New tables (additive, see database.py `_migrate()`): `organizations`,
`integrations`, `integration_credentials` (Fernet-encrypted via
`INTEGRATION_CREDENTIALS_KEY`), `integration_sync_runs`, `integration_logs`,
`integration_records` (staging/dedup, `deduplication_key UNIQUE`),
`integration_webhook_events` (replay protection), `weighbridge_records`.
Existing domain tables (`sectors`, `vehicle_gps_pings`, `timber_movements`,
`satellite_observations`, `risks`) are reused, not duplicated — see
`categories.py` docstrings for which category writes which table.

**Tenant isolation caveat:** every new table carries `organization_id`, and
a `Default Organization` (id=1) is seeded, but this is schema-ready, not
enforced — the app still authenticates with one shared `DASHBOARD_USERNAME`/
`DASHBOARD_PASSWORD` HTTP Basic login (§3 above), so there is currently no
way for two different companies' users to get different views. Real
multi-tenant isolation needs per-user/per-org auth, which does not exist in
this codebase yet.

Risk Engine bridge: `services/integrations/risk_rules.py` reuses
`database.add_incident()`/`add_risk_event()`/`generate_incident_recommendation()`
exactly as `bot.py`'s live geofence flow and `services/demo_scenarios.py`
already do — not a second risk engine. New `rule_code` values:
`FLEET_SECTOR_EXIT`, `SATELLITE_UNREGISTERED_CHANGE`,
`WEIGHBRIDGE_WAYBILL_MISMATCH`, `TIMBER_VOLUME_OVER_PERMIT`. Dedup uses
`database.get_active_incident_by_rule()`, the generalized form of the
inline check `bot.py` already does for `SECTOR_EXIT`/`EMERGENCY`.

API: `/api/integrations/*` (CRUD, test/sync/reset-demo/logs/records) behind
the same `verify_credentials` global dependency as every other route.
`/api/webhooks/{provider}` is mounted as a separate sub-application
(`webhook_app`, see api.py) specifically because the app-level
`dependencies=[Depends(verify_credentials)]` on the main `FastAPI(...)`
cannot be exempted per-route — external webhook senders can't do this
dashboard's HTTP Basic login anyway. Webhook authenticity instead comes
from an HMAC-SHA256 signature (`WEBHOOK_SECRET_<PROVIDER>` env var) plus
`integration_webhook_events.payload_hash UNIQUE` replay protection.

Tests: `tests/test_integrations.py` (30 tests — migrations, dedup, demo/
production isolation, risk engine wiring, API routes, webhook signature +
replay). Run with `python3 -m pytest tests/test_integrations.py -v`.

**Known limitation:** demo adapter data generation and the Fleet GPS
"signal lost" / worker / wetland-proximity / machine-breakdown risk
scenarios from the spec are not wired yet — they need normalized data from
categories with no stage-1 demo adapter (worker, machine, GIS zones) and,
for signal-loss detection specifically, a periodic background scheduler
(no APScheduler/cron-in-process exists in this codebase yet — sync is
triggered manually via the UI/API today, not on a timer).

## 7. Netlify

Не подтверждается кодом или git-историей этого репозитория — упоминается
только в памяти проекта как отдельный статический сайт для
маркетинговых/pitch-материалов, независимый от VPS и от этого репо. Не
проверялось в этой сессии.
