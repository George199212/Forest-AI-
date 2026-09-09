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

## 6. Netlify

Не подтверждается кодом или git-историей этого репозитория — упоминается
только в памяти проекта как отдельный статический сайт для
маркетинговых/pitch-материалов, независимый от VPS и от этого репо. Не
проверялось в этой сессии.
