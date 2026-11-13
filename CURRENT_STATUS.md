# CURRENT_STATUS.md — Forest AI

**As of:** 2026-10-21. **Code basis:** `github.com/George199212/Forest-AI-` `master` @ `5f82a8d`
(= `574bd97` inspected in full + docs commit `ac347e2` + demo-layer Stage 1 `5f82a8d`).
**Production MAIN (`/root/forest_ai`) == GitHub `master` as of 2026-10-21 12:39** — verified: prod `git diff` applied cleanly on `574bd97`, committed, `git status` empty. Running processes still execute pre-Stage-1 code until the next `systemctl restart forest-api` (migration is additive). Method: fresh clone, source reading, `init_db()` on an empty DB,
route enumeration via import, TestClient auth probes, pytest (30/30 passed), pyproj check of CRS math.
No VPS access in this session — everything about the running servers is **[NOT VERIFIED]**.
**Supersedes:** CURRENT_STATUS.md of 2026-09-09 (commit `0db0a79`) and the Project Knowledge copies of 2026-09-02/07.

## Update 2026-11-13 — DEMO :8003 runs LVM GEO + Meža karte (ACTIVE since 13:05 UTC)

Deployment topology, verified on the VPS on 2026-11-13 10:07 UTC (`systemctl show`, `/proc/<pid>/cwd`):

| port | unit | runs from | code version |
|---|---|---|---|
| 8000 | `forest-api` | `/root/forest_ai/releases/forest-api-forest-map-contrast-20261110T0949Z` (drop-in `96-`) | `66572fa` + 3 live-only files (`index.html` nav edit; `lvm-geodata.js` and `vmd-production.js`, now versioned as `feature/live-vmd-ui-texts` `50f6daf`) |
| 8002 | `forest-rm-api` | `/root/forest_ai_rm` | `574bd97` copy (unchanged) |
| 8003 | `forest-review-api` (DEMO) | `/root/forest_ai/releases/forest-review-geo-20261113T1023Z` (drop-in `50-review-geo-release.conf`, active since 2026-11-13 13:05 UTC) | `feature/review-geo-release` @ `bd36ce2` (runtime = `b6d3769`). Own DB copy `data/forest_ai.db` (rebuilt from the untouched demo DB). Sandbox: `ProtectSystem=strict`, `ProtectHome=read-only`, writable only `data/`; `/root/forest_ai/data` = tmpfs + read-only `geodata/nationwide`; prod `.env`, `_rm`, `_ingka`, `_telegram`, old demo `data/` inaccessible. Rollback: `rm -f /etc/systemd/system/forest-review-api.service.d/50-review-geo-release.conf && systemctl daemon-reload && systemctl restart forest-review-api` → `/root/forest_ai_review` |
| 8004 | `forest-ai-ingka` | `/root/forest_ai_ingka` | not in git (unchanged) |

The demo release adds the LVM GEO and Meža karte (Forest Map) sections to the read-only demo:
- First activation (10:59 UTC) was rolled back at 11:01: the smoke test found that `GET /api/john-deere/status`
  wrote a `john_deere_sessions` row (the only GET writer of 101). Fixed for review mode (`b6d3769`); release DB rebuilt;
  `tests/test_review_no_writes.py` now walks every GET route and compares DB content + `data/` files.
- Every non-GET is still 403. Registration, including its dry-run preview dialog, and "Izveidot incidentu" return
  an explicit bilingual 403 and are refused by the route handlers too. LVM GEO steps 1–2 are GETs.
- FIELD-TEST-01 (real field test) is hidden from Meža karte and LVM GEO with `REVIEW_MAP_EXCLUDED_SECTORS`
  (display exclusion through TEMP views; no data edited). The existing pages still show it: see "Open" below.
- Seeded demo GPS sessions are labelled from their sector's `data_origin` (SIMULATED) instead of a hard-coded REAL.
- The national catalogue is opened read-only. A systemd sandbox hides the rest of `/root/forest_ai/data`,
  the other instances and the production `.env` from the demo process; only its own `data/` is writable.

Open (not changed in this task):
- FIELD-TEST-01's real boundary, centre, live position, session 32 track (29 points) and 48 photos (no EXIF)
  are still served by the existing demo pages (`/api/sectors`, `/api/sectors/FIELD-TEST-01`, `/api/map`,
  `/api/gps`, `/api/sessions/27–32/track`, `/api/photos`).
- :8003 (and 8000/8002/8004) listen on 0.0.0.0 over plain HTTP with Basic Auth. There is no reverse proxy and ufw is inactive.
- Forest Map tiles: up to 1290 features / 525 KB (parcels z14, Riga) and 702 features at z13 (forest);
  the code limits are production's 2000 / 1.5 MB.

## Update 2026-11-10 — LVM GEO registration UX + Forest Map basemap (branch `feature/lvm-geo-finish`, NOT deployed)

Frontend only (`assets/vmd-production.js`, `assets/forest-map.js`, `index.html` `#sec-lvm-geodata`,
CSS). No backend, `import-selected` contract, schema or endpoint change.

- **Live :8000 is not master for LVM GEO.** The active release
  (`releases/forest-api-forest-map-violations-20261109T1623Z`) serves the LVM GEO frontend of
  `feature/boundary-plan@fd3d2c6` (see `docs/DEPLOY_RELEASES.md`, "Live files not in git") with the master
  backend. This branch builds on master and supersedes that frontend when deployed.
- **Forest Map:** on-map basemap switch "Satelīts" / "Karte" (top-right), synced with the sidebar
  "Pamatkarte" select, choice kept in localStorage, satellite failure falls back to "Karte" with a notice.
  Root cause of "cannot switch": the only switch was a sidebar `<select>` below the fold (y=905 in a 750 px
  sidebar viewport at 1440×900), labelled only "Kartes slāņi"; it worked when reached.
- **LVM GEO:** polygon / row click only inspects; selection changes only via row checkbox, popup button
  "Atlasīt" / "Noņemt no atlases", tri-state master checkbox (current page, importable rows) or
  "Noņemt atlasi". Sticky action bar "Reģistrēt sektorus (N)" with sector name, Vārds, Uzvārds and inline
  reason when disabled; dry-run preview + confirm kept; results marked "Reģistrēts" / "Jau reģistrēts".
- Verified in headless Chromium on a throwaway server (127.0.0.1:8015, DB copy in `/tmp/lgf`):
  62420110056 → 25 rows, 18 importable, master selects 18 (28.18 ha); 3 rows registered with full
  `geodata_sources` provenance and visible in `/api/sectors` and the Forest Map sectors layer.

Observations (not changed):
- Boundary rule blocks compartments with < 1 m² outside the VZD land unit: 62420110056 — 7 blocked, 5 of
  them < 1 m²; 01000920499 — 35 blocked, all 35 < 1 m² (smallest 3.1e-8 m²).
- :8000 runs without `UI_LANGUAGE=lv`, so the sidebar is English. `localizeGeodataNavigation()`
  (`index.html` ~893) translates the sidebar to Latvian only while LVM GEO is open, and the header time is
  `lv-LV` only there (`index.html` ~921, other pages use the browser locale). Leaving LVM GEO for
  "Meža karte" therefore shows an English menu and en-US time.

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
| Provenance (Stage 1) | `risks.data_origin`, `sectors.data_origin`, `risk_evidence` table + helpers; demo resets can no longer delete REAL risks; 38/38 tests pass |

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
| Persistent AI Inspector chat via `ai_inspector_chat_messages` | **Not in code and not on prod MAIN** (prod code == GitHub). The feature does not exist; the earlier note was wrong. |
| Satellite Intelligence Engine "implemented" | Modules exist; decision/trigger layer not called anywhere |
| `/api/sectors` lacks exposure_low/high (KPI shows €0) | Fixed (commit `34e05da`) |
| CORS wildcard removed | Correct — no CORS middleware |
| Hardcoded Sentinel credentials | Not in current code — read from env |

## 5. Not verified (needs VPS session)
- Production MAIN code == GitHub: **verified 2026-10-21**. RM instance (`/root/forest_ai_rm`) code version: not verified (plan says `data/DEPLOYED_COMMIT` = `574bd97`).
- systemd units/state for `forest-api`, `forest-bot`, `forest-rm-api`; orphaned uvicorn on :8001.
- nginx/TLS in front of :8000 / :8002.
- Real `.env` contents per instance; which integrations are configured; DB sizes; presence of `ai_inspector_chat_messages` on prod.

## 6. Work in progress: Rīgas meži demo layer
`docs/demo-layer-plan.md` (approved 2026-10-20, decisions Q1–Q15, amendments A1–A4). Stage 1 committed (`5f82a8d`). Next: Stage 2 (catalog statuses/grouping, demo adapters never shown as Connected). Stages are implemented by Claude Code on the VPS, verified on /tmp copies and a temp server :8011, committed by the user.

## 7. Readiness for the LVM GEO integration task
Framework fit is good: `lvm_geo` already sits in the registry as a planned `gis` provider and the
`GISIntegrationAdapter` category exists. Blockers before any LVM GEO work: finding #1 (CRS), plus a
decision on whether external reference layers are browser-side WMS (Leaflet) or server-side proxied.
No LVM GEO service has been verified yet — that research is a separate step.
