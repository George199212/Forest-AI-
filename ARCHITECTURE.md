# ARCHITECTURE.md — Forest AI

**Обновлено:** 2026-09-09, по прямому клонированию и построчной инспекции
`github.com/George199212/Forest-AI-` (ветка `master`, коммит `0db0a79`,
2026-09-08 16:54 UTC).
**Источник истины:** реальный код в этом коммите. Всё, что требует проверки
на живом VPS (systemd-статусы, осиротевшие процессы, аптайм), помечено явно
как непроверенное в этой сессии — здесь нет SSH-доступа к серверу, только
git clone публичного репозитория.

---

## 1. Обзор системы

Forest AI — платформа мониторинга лесохозяйственных операций: полевой ввод
через Telegram, геозона-контроль GPS, учёт техники/сотрудников, риски и
инциденты с AI-рекомендациями, спутниковый мониторинг (Sentinel Hub), Web SPA
дашборд.

```
                    ┌─────────────────────┐
   Браузер ────────►│   index.html (SPA)  │  2612 строк, без сборки/фреймворка,
   (HTTP Basic)     │                      │  JS/CSS инлайн, Chart.js с CDN
                    └──────────┬──────────┘
                               │ fetch() → /api/*
                               ▼
                    ┌─────────────────────┐
                    │      api.py          │  FastAPI, 1811 строк, 54 роута,
                    │  (uvicorn, :8000)     │  HTTP Basic Auth на всём app
                    └──────────┬──────────┘
                               │
       ┌───────────────────────┼───────────────────────┐
       ▼                       ▼                        ▼
  database.py            services/                Copernicus/Sentinel Hub
  (SQLite,           ai_resolution.py          (спутниковые снимки, NDVI —
  data/forest_ai.db)  robez_ocr_vision.py        endpoints /api/satellite/*)
  908 строк           (оба — Anthropic SDK,
                       claude-sonnet-4-5)

   Отдельный процесс:
                    ┌─────────────────────┐
   Telegram ───────►│      bot.py           │  python-telegram-bot,
   (polling)         │  1527 строк           │  polling, свой процесс
                    └──────────┬──────────┘
                               │ собственный sqlite3.connect()
                               ▼
                         тот же forest_ai.db
```

## 2. Технологический стек (подтверждено кодом)

- **Backend:** Python, FastAPI + uvicorn (`api.py`), python-telegram-bot
  (`bot.py`) — два независимых процесса, own event loop у каждого.
- **База данных:** SQLite, файл `data/forest_ai.db` (путь переопределяется
  `DB_PATH` env-переменной). Прямые `sqlite3.connect()`-вызовы, без ORM,
  без connection pool — каждая функция в `database.py`/`api.py` открывает
  и закрывает своё соединение.
- **Frontend:** одна HTML-страница (`index.html`), полностью client-side
  роутинг (`nav()`, `history.pushState`/`popstate`), Chart.js 4.4.1 с CDN
  (`cdnjs.cloudflare.com`) для графиков на Overview.
- **AI:** Anthropic Python SDK (`anthropic`), модель `claude-sonnet-4-5`,
  используется в двух местах — `services/ai_resolution.py` (рекомендации по
  инцидентам) и `services/robez_ocr_vision.py` (OCR планов границ).
- **Спутник:** Copernicus Data Space Ecosystem / Sentinel Hub, OAuth
  client-credentials (`SENTINEL_CLIENT_ID`/`SENTINEL_CLIENT_SECRET`).
- **Изображения:** Pillow (`PIL`) — опционально импортируется в `api.py`,
  код деградирует, если пакет недоступен (`_PIL_AVAILABLE` флаг).
- **⚠️ `requirements.txt` / `pyproject.toml` / `Pipfile` — в репозитории
  НЕТ.** Список реальных зависимостей нигде не зафиксирован файлом —
  известен только по факту импортов в коде (`fastapi`, `uvicorn`,
  `python-telegram-bot`, `anthropic`, `requests`, `Pillow`). Это пробел,
  стоит завести `requirements.txt` явно.
- **`config.py` — файл размером 0 байт, нигде не импортируется.**
  Мёртвый файл-заглушка, подтверждено grep по всему репо. Вся конфигурация
  идёт через `os.environ.get(...)` напрямую в `api.py`/`bot.py`/`database.py`.

## 3. Аутентификация

`api.py`: `HTTPBasic()` подключён на уровне всего FastAPI-приложения через
`app = FastAPI(dependencies=[Depends(verify_credentials)])` — то есть
**абсолютно все роуты**, включая `/` (сама SPA-страница) и `/photos/file/*`,
защищены Basic Auth. Сравнение логина/пароля — через `secrets.compare_digest`
(защита от timing-атак). Креды — `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD` из
env. Явного CORS middleware в коде нет вообще (ни разрешающего, ни
запрещающего) — по умолчанию FastAPI не отдаёт CORS-заголовки.

## 4. Модель данных и единая точка схемы

`database.py::init_db()` → `_migrate()` — централизованная точка создания
ВСЕХ 17 таблиц (см. DATABASE.md), включая те, что раньше исторически
создавал `bot.py` отдельно. И `api.py`, и `bot.py` вызывают `init_db()` на
старте (`@app.on_event("startup")` в api.py) — любой процесс может поднять
БД с нуля. Миграции только additive: `_add_column_if_missing()` — helper на
`ALTER TABLE ADD COLUMN`, плюс один задокументированный managed rebuild
(`vehicle_gps_pings` — снятие `NOT NULL` с `vehicle_id`, 12-шаговый
SQLite-паттерн пересоздания таблицы с сохранением данных, guard'ится через
`PRAGMA table_info`, безопасно перезапускать).

## 5. Ключевые потоки данных

### 5.1 Геозона-детекция (Telegram Live Location → инцидент)
`bot.py::handle_location()` обрабатывает `update.edited_message` (Telegram
шлёт обновления живой геолокации каждые несколько секунд как edit исходного
сообщения). Функция апдейтит `live_locations`, сравнивает `old_status` vs
`new_status` (`IN`/`OUT` относительно границы сектора). При переходе
`IN → OUT`:
1. Если для этого employee уже есть открытый инцидент с `rule_code='SECTOR_EXIT'`
   (`status IN ('OPEN','NOTIFIED')`) — просто пишется `risk_events` запись
   `STILL_OUTSIDE` (дедупликация по `rule_code` + `entity_id`, не создаётся
   дубль).
2. Иначе — `add_incident(..., rule_code="SECTOR_EXIT")`, событие `DETECTED`,
   и синхронный вызов `generate_incident_recommendation()` через
   `loop.run_in_executor` (чтобы не блокировать asyncio event loop
   bot.py на время сетевого вызова к Anthropic API) — результат пишется в
   `risks.ai_recommendation` через `set_ai_recommendation()`.

Второй, независимый триггер — `rule_code="EMERGENCY"` (кнопка тревоги в
Telegram-меню, `emergency_button()` в bot.py), та же дедупликация и та же
генерация AI-рекомендации.

**Важно:** это единственные ДВА rule_code, которые реально генерируются
автоматическим кодом (`grep add_incident bot.py` подтверждает). Другие
rule_code, встречающиеся в демо-данных (например `EQUIPMENT_BREAKDOWN`,
упомянутый в handling `/api/incidents/{id}/approve` — см. API.md), в текущем
коде **не создаются никаким автоматическим правилом** — такие инциденты
попадают в БД только через прямую ручную вставку (скрипт/консоль), не через
живую логику `bot.py`. Это не баг, а осознанное ограничение MVP/демо —
но следует явно понимать, что "живой" auto-detection покрывает пока только
sector exit и emergency-кнопку.

### 5.2 Финансовый risk score (`api.py::calc_risk_score()`)
Считается по требованию для каждого сектора (вызывается внутри
`/api/sectors`). Формула: `score = min(100, HIGH*25 + MEDIUM*10 +
rejected_gps*15 + timber_missing*20 + timber_over*15)`. Дополнительно
считается денежная "exposure" (€60–120/м³ рыночная цена, плюс фиксированные
надбавки за rejected GPS и HIGH-риски) — это тот же расчёт, что суммируется
в KPI-карточке "Общий финансовый риск" на странице AI Inspector, и это
**отдельный, чисто rule-based** расчёт от AI-генерируемого
`estimated_exposure_eur_low/high` внутри `ai_recommendation` конкретных
инцидентов (два разных источника чисел, не путать при доработке).

### 5.3 AI-рекомендации по инцидентам (`services/ai_resolution.py`)
Единая точка вызова Claude API для инцидентов. Промпт строго ограничен
("Based ONLY on the information given above... do not invent"), просит
вернуть строгий JSON (`summary`, `options[]` с готовыми текстами сообщений
на русском, `recommended_option_id`, `estimated_exposure_eur_low/high`,
`exposure_basis`). `max_tokens=2048`. Любая ошибка (нет ключа, сетевая
ошибка, API-ошибка) — ловится, логируется через `print()`, функция
возвращает `None`, никогда не поднимает исключение — вызывающий код
(`handle_location`, ручная демо-вставка) должен быть готов к `None`.

## 6. AI Inspector — важное уточнение (актуально на 0db0a79)

Раздел "AI Inspector" в дашборде состоит из ДВУХ независимых частей —
подробности и точный код см. в отдельном разборе для текущей рабочей
задачи (streaming). Кратко для архитектурной картины:

- `loadInspector()` (index.html) — чисто клиентский JS-калькулятор
  (if/else пороги на данных из `/api/sectors`, `/api/risks`, `/api/gps`,
  `/api/timber`, `/api/trucks`). **Не вызывает LLM.**
- `loadIncidentsEquipment()` — отображает уже сгенерированные
  `ai_recommendation` из инцидентов через `/api/incidents`. Вызывает
  реальный AI только на этапе создания инцидента (см. 5.1), не в момент
  просмотра дашборда.
- В `index.html` есть функция `startTypewriter(elId, text)` — это
  **имитация печати** (`setInterval` по уже полностью готовой строке,
  15мс/символ), используется на Risk Detail для показа `ai_recommendation.
  summary`. Это НЕ настоящий стриминг: текст уже полностью в памяти
  браузера до начала "печати". В коде нет ни `EventSource`, ни
  `ReadableStream`, ни `text/event-stream` — ни на фронте, ни в `api.py`.
  Backend-эндпоинта для streaming-анализа в реальном времени не существует.

## 7. Что не проверено в этой сессии (нужна живая VPS-сессия)

- Актуальный статус systemd-юнитов (`forest-api.service`/`forest-bot.service`)
  — репозиторий не содержит `.service`-файлов (они и не должны быть в git,
  но и подтвердить их состояние по коду нельзя).
- Осиротевший процесс на порту 8001 (упоминался в памяти проекта) —
  не проверялся, требует SSH.
- Реальное содержимое `.env` на сервере (в репо только `.env.example` с
  пустыми значениями, что и ожидаемо).
