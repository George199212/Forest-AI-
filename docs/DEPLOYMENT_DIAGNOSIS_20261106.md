# Live deployment diagnosis — 2026-11-06

The updated integration is verified at **http://164.90.188.136:8000/#lvm-geodata** using Chromium against that public address, not localhost. The user's exact browser URL has been requested and has not yet been supplied. Therefore this report does not establish that the user's unchanged page is this deployment, and does not claim that a different client deployment has been fixed.

## Deployment identity

| Public port | Service | Working directory | VMD routes/assets |
|---|---|---|---|
| 8000 | forest-api.service | /root/forest_ai | Current and verified |
| 8002 | forest-rm-api.service | /root/forest_ai_rm | Absent; 404 |
| 8003 | forest-review-api.service | /root/forest_ai_review | Absent; 404 |
| 8004 | forest-ai-ingka.service | /root/forest_ai_ingka | Absent; 404 |

The main deployment is FastAPI served directly by uvicorn, using `/usr/local/bin/uvicorn api:app --host 0.0.0.0 --port 8000` and `/usr/bin/python3`. It is not Flask or a frontend development server. The host listener inspection found no listener on ports 80/443 and no local nginx sites directory. No Netlify deployment is evidenced or was modified. An unknown user URL could still point to a separately hosted site or external proxy; the missing URL prevents checking that possibility.

Frontend files are `/root/forest_ai/index.html`, `/root/forest_ai/assets/vmd-production.js`, `/root/forest_ai/assets/lvm-geodata.js` and `/root/forest_ai/assets/lvm-wms-map.js`. FastAPI reads the HTML directly in `serve_index()` and delivers assets through `serve_asset()`. There is no separate bundle/build/publish directory for this application.

## Local/public comparison and history

Before this change, localhost:8000 and public-IP:8000 returned identical HTML hashes. Public JavaScript hashes matched the current local files. Both included the Latvian VMD interface and activated geodata frontend flag. In contrast, the three client instances served different HTML, had no VMD production JavaScript files, and returned 404 for both requested geodata endpoints. They have separate code and database roots.

Git HEAD remains `84cb00b` (2026-10-21); geodata work is uncommitted. The deployment version below is derived from actual frontend file contents, not falsely described as a new Git release. The previous main process had been activated on November 6 at 09:57 UTC. Only the main service was restarted again for the cache/version changes, at **10:50:09 UTC**, PID **2702727** at verification.

## Changes made in this follow-up

- `api.py`: authenticated `/api/deployment`; process-start backend revision; content-derived frontend version; `X-Forest-Deployment` header; HTML `Cache-Control: no-store, max-age=0` and `Vary: Authorization`; content-hashed local script query strings; script/CSS revalidation headers.
- `index.html`: visible deployment version on the LVM/VMD page.
- `tests/test_deployment_delivery.py`: regression checks for cache prevention, script fingerprints, version changes and process backend identity.

Current frontend version: **geo-6b110ed56893**. Running backend revision: **078a59160ba5**. These values are visible through authenticated `/api/deployment`; the frontend version also appears directly on the page.

Public scripts verified by Chromium:

| URL | Result |
|---|---|
| /assets/vmd-production.js?v=d9c98b23a1c9 | 200; SHA256 matches disk |
| /assets/lvm-geodata.js?v=b45bd5d2805b | 200; SHA256 matches disk |
| /assets/lvm-wms-map.js?v=6518a74a0203 | 200; SHA256 matches disk |

HTML previously had no cache-control/version diagnostics. This was a stale-delivery risk, not a proven explanation of the user's unchanged browser. It is now prevented and observable. Deployment mismatch between ports is confirmed; whether it explains the user's symptom requires the exact address from their browser. No other client/account deployment was changed on an assumption.

## Actual public browser/API results

| Check | Result |
|---|---|
| GET / | 200; uvicorn; no-store; current deployment header |
| GET /api/deployment | 200; current frontend/backend revisions |
| GET /api/geodata/vmd/dataset | 200; AVAILABLE; 513,776 records |
| GET /api/geodata/lvm/health | 200; UNAVAILABLE; zero verified live layers |
| GET /api/geodata/vmd/territories | 200; empty saved list for this account |
| Cadastral compartment search, 40940020002 | 10 real compartments rendered |
| Actual browser polygon click | Popup opened: Kadastrs 40940020002, quarter 1, compartment 9 |
| Multiple selection | 2 compartments, 0.61 ha |
| POST /api/geodata/vmd/import-selected, dry_run=true | 200; would_import=2; failed=0; imported=0 |
| POST /api/geodata/vmd/territory-preview | 200; actual territory validation |
| Blocking JavaScript exceptions | None |
| Normal browser reload | Same current visible version; dataset loaded |

The live LVM provider still times out; HTTP 200 health is not reported as successful provider connectivity. Actual sector creation and territory saving were not performed against production during this follow-up. Their mutation routes were tested in the prior isolated real-data acceptance; this run checks the production routes without creating records.

68 targeted Python tests passed, including the two new deployment-delivery tests and existing geodata/VMD suites. Syntax and whitespace checks passed. No database migrations were needed. A consistent SQLite backup passed integrity checking at `data/backups/deployment_delivery_20261106T104812Z/forest_ai.db`.

Machine-readable public-browser evidence: `data/vmd/public-deployment-verification-20261106.json`.
Screenshot: `data/vmd/public-deployment-20261106.png`.
Read-only four-instance comparison: `/tmp/forest_deployment_diagnosis.json`.

## Required next information

The exact URL in the user's address bar, including port and path/hash, is still required to connect their report to an identified deployment. If it differs from port 8000, inspect that specific target and prepare the integration deployment preserving its own authentication/database; do not copy the main account database or blindly replace a client's application.
