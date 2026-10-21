# CURRENT_STATUS.md — Forest AI

**As of:** 2026-10-21. **Code basis:** `github.com/George199212/Forest-AI-` `master` @ `574bd97`
(2026-10-20 08:00 UTC, 87 commits). Method: fresh clone, source reading, `init_db()` on an empty DB,
route enumeration via import, TestClient auth probes, pytest (30/30 passed), pyproj check of CRS math.
No VPS access in this session — everything about the running servers is **[NOT VERIFIED]**.
**Supersedes:** CURRENT_STATUS.md of 2026-09-09 (commit `0db0a79`) and the Project Knowledge copies of 2026-09-02/07.

## 1. What exists and works in code

| Area | State |
|---|---|
| Telegram field app | Check-in with polygon geofence, self-link to employee, live-location route recording (`session_track_points`), photos (site/equipment/timber), comments, finish, SOS, vehicle GPS pings, timber/truck commands, plan OCR, CSV export |
| Auto-incidents | `SECTOR_EXIT` (live location IN→OUT, deduped per employee/sector/session), `EMERGENCY` (SOS). Legacy risks: rejected check-in, fuel discrepancy >5 L, timber/truck mismatch |
| Incident workflow | AI recommendation (options + Telegram texts + AI exposure estimate) → dispatcher approve / free-text message → worker reply capture → AI follow-up → `confirm_return` closes. Full `risk_events` audit |
| Background AI worker | Analyses every new risk lacking AI (Latvian by default), 30 calls/day cap, retry endpoint |
| AI Inspector | Real SSE streaming analysis per sector / all sectors, stored in `ai_inspector_analyses`; one-click report-issue → incident + Telegram |
| Photo comparison | Two-date comparison per sector: AI point matching, human confirmation, same-place/comparability check, change detection, independent verification, human review with undo |
| Risk conclusion (Slēdziens) | Evidence package + rule-based close/keep-open (R0–R3, never AI) + optional AI text with wording guards + human decision with override reason + undo |
| Worker route on map | Real points only, gaps >120 s, photos placed ±60 s, exit route on SECTOR_EXIT cards |
| Satellite imagery | On-demand Sentinel-2 true colour / NDVI per sector/object; manual satellite images and dated snapshots with risk links |
| Objects / boundary plans | Plan scan upload, manual polygon drawing on scan, annotated/cropped plan views |
| Integration Layer | Framework + catalog + 3 demo adapters + risk rules + encrypted credentials + webhook endpoint; tests pass |
| Client instances | Script-based separate copies (Rīgas meži: port 8002, LV UI overlay, no bot) |
| Reports | Sector PDF (needs `reportlab`), bot CSV ZIP |

## 2. Demo / not real yet (must not be presented as live capability)

- **Satellite Intelligence Engine decision layer is not wired:** no code calls `events.trigger_*` or
  `decide_and_request`. Satellite scores/requests/timeline come only from the `sentinel_demo` adapter
  (fabricated scenes) or out-of-repo scripts. No automatic change detection from real imagery.
- Integration adapters: only `fleet_gps_demo`, `sentinel_demo`, `weighbridge_demo` (no network).
  LVM GEO, PONSSE, John Deere, Komatsu, ZF, Planet, etc. are catalog entries only.
- Commercial satellite providers (PlanetScope/SkySat/ICEYE): stubs.
- Demo scenarios (breakdown, worker-exit, volume-mismatch, wetland, logging-boundary) create real
  incidents and real Telegram messages on hardcoded sectors (A-005/A-006/A-007), names and a
  hardcoded rectangular "wetland" polygon — **not real protected-area data**.
- Financial "exposure" on Overview = sum of **AI estimates**, not measured losses.

## 3. Findings from this inspection (not fixed — awaiting decision)

Severity: **P0** wrong data / exposure, **P1** security or reliability, **P2** hygiene.

| # | Sev | Finding | Evidence |
|---|---|---|---|
| 1 | P0 | LKS-92→WGS84 conversion is off by **150–190 km** (docstring claims ~100 m). Affects OCR-imported plans and georeferenced drawn sectors. Directly blocks any Latvian GIS integration (LVM GEO etc. publish in EPSG:3059). | `bot.py::lks92_to_wgs84`, `api.py::_lks92_to_wgs84`, `services/robez_ocr_vision.py::lks92_to_wgs84`; pyproj comparison 2026-10-21 |
| 2 | P1 | Telegram bot has no authorization except `/demo_*`: anyone can add sectors/risks/timber/trucks, read all sectors/risks, export CSV ZIP with worker names, Telegram IDs and GPS tracks, and self-link to unlinked employees. | `bot.py::main` handler registration, `link_employee_callback` |
| 3 | P1 | `/docs`, `/redoc`, `/openapi.json` are served without Basic Auth → public API map. | TestClient probe 2026-10-21 |
| 4 | P1 | Dashboard links in bot messages are plain `http://164.90.188.136:8000`; Basic Auth credentials would travel unencrypted unless a TLS proxy exists. | `bot.py` lines ~409, 478, 501 — TLS **[NOT VERIFIED]** |
| 5 | P1 | Repository is **public**. No secrets found in 87 commits (pattern scan), but the full code, internal decisions and a real person's name + Telegram ID (`tools/i18n_check/make_fixture.py`) are exposed. | `git log -p` scan |
| 6 | P1 | `reportlab` missing from `requirements.txt` → PDF export fails on a fresh install. | `api.py::generate_pdf` |
| 7 | P1 | No cost cap on Inspector, report-issue, OCR, integration-rule AI calls (only worker has 30/day). OCR has no file-hash cache. | INTEGRATIONS.md §2 |
| 8 | P1 | Missing-data handling: Sentinel endpoints and bot geofence fall back to a hardcoded Riga point; `calc_risk_score` treats "no timber data" as 0; deleting a sector or employee orphans dependent rows (no FKs). | DATA_MODEL.md §6, DATABASE.md §1 |
| 9 | P2 | `DISMISSED` status is recognized but nothing can set it — no false-positive dismissal action. | `database.update_incident_status`; no writer |
| 10 | P2 | `GET /api/sectors/{name}` returns HTTP 200 `{"error":"Not found"}`; error shapes inconsistent across API. | API.md |
| 11 | P2 | `install.sh` is an unrelated third-party installer (`codebase-memory-mcp`); `config.py` empty; Tesseract OCR function dead; three copies of geo helpers. | repo root |
| 12 | P2 | Mixed timestamp formats in `risks.created_at` (`... UTC` vs ISO). | `add_incident` vs `add_risk` |
| 13 | P2 | Sentinel default date window hardcoded to June 2024. | `api.py` satellite routes |

## 4. Discrepancies with earlier project notes / Project Knowledge

| Earlier claim | Code says |
|---|---|
| 16–17 tables | **37 tables** |
| 54 API routes | **106 + 1 webhook** |
| "No requirements.txt" | Exists (pinned), but missing `reportlab` |
| "AI Inspector is a client-side calculator, no streaming" | Real SSE streaming endpoint exists since 2026-09-09 |
| Persistent AI Inspector chat via `ai_inspector_chat_messages` | **Not in code** — no table, no endpoint, no frontend call. Either never committed or lives only on the server → **[NOT VERIFIED]** |
| Satellite Intelligence Engine "implemented" | Modules exist; decision/trigger layer not called anywhere |
| `/api/sectors` lacks exposure_low/high (KPI shows €0) | Fixed (commit `34e05da`) |
| CORS wildcard removed | Correct — no CORS middleware |
| Hardcoded Sentinel credentials | Not in current code — read from env |

## 5. Not verified (needs VPS session)
- Production code == `574bd97`? (commit `8afb109` says "as deployed 2026-10-13" — code was committed after deployment.)
- systemd units/state for `forest-api`, `forest-bot`, `forest-rm-api`; orphaned uvicorn on :8001.
- nginx/TLS in front of :8000 / :8002.
- Real `.env` contents per instance; which integrations are configured; DB sizes; presence of `ai_inspector_chat_messages` on prod.

## 6. Readiness for the LVM GEO integration task
Framework fit is good: `lvm_geo` already sits in the registry as a planned `gis` provider and the
`GISIntegrationAdapter` category exists. Blockers before any LVM GEO work: finding #1 (CRS), plus a
decision on whether external reference layers are browser-side WMS (Leaflet) or server-side proxied.
No LVM GEO service has been verified yet — that research is a separate step.
