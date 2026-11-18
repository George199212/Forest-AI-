# Auto-monitoring of sectors — proposal + estimate (owner D13, 2026-11-18)

**Proposal only. Nothing implemented, no worker/timer/config touched.** Note: the Sectors prompt v3 lists "workers, timers"
as OUT of scope; D13 is the owner's explicit override, so it is proposed here as a separate change for approval.
Data: `.backup` copy of satellite.db taken 2026-11-18 06:22 UTC (after today's daily run 9), real values only.

## (a) Measured cost — PU and requests

Source: `sat_request_log` (560 requests in November: 20 CATALOG + 540 PROCESS, 0 HTTP errors, 0 PU estimates — all PU from
the provider's response header), `sat_acquisitions.pu_spent`, `sat_runs` 1–9.

| Item | Measured |
|---|---|
| PU per request, S1 (VV+VH, orthorectified) | small grid **0.0267** (provider minimum: area factor 0.01) · BIK-001 (127×95 px) 0.1227 · Ķekava (631×624) 4.005 |
| PU per request, S2 | small grid **0.0467** (minimum, 7 bands incl. true colour) · BIK-001 0.1534 (5 bands, before true colour; 7 bands → ≈ 0.215) · Ķekava 5.007 |
| Process requests per area per 30 days | S1 ≈ **21** (areas 1/3/4: 76/108 d, 82/118 d, 81/117 d) + S2 ≈ **8** fetched (cloud-skipped S2 cost 0: filtered by the Catalog) → **≈ 29** |
| Catalog requests | 2 per daily run (one per sensor), **shared by all areas** → ≈ 60 / 30 days |
| Backfill of a new area (`area_backfill_days` 120) | measured: area 3 = 106 requests / 2.91 PU, area 4 = 117 requests / 3.81 PU, BIK-001 (101 d) = 99 / 12.67 PU |

Per month, per area (PU model `provider.estimate_pu`, checked against the measured values above):

| Area size | PU / 30 d | Requests / 30 d | Per ha |
|---|---|---|---|
| Small: grid ≤ 2,621 px (sector up to ≈ 10–15 ha incl. the 100 m buffer) — **73 of the 78 candidates** | **0.93** | **29** | floor-dominated: a 1 ha sector costs the same as a 10 ha one (≈ 0.93 PU/ha/month at 1 ha) |
| BIK-001 size (50 ha, 12,065 px) | 4.3 | 29 | ≈ 0.085 PU/ha/month |
| Large (≈ 107 px/ha, Ķekava-like) | 0.038 × ha | 29 | **≈ 0.038 PU/ha/month** |

**The request count, not PU, limits small sectors**: every area costs ≈ 29 requests/month whatever its size.

## (b) What fits under the existing guard

Budget (config): 2,000 PU and 6,000 requests per month, guard at 80 % → **1,600 PU / 4,800 requests**. November so far:
560 requests, 914.03 PU (most of it the Ķekava backfill, 840 PU on 11-11).

| Scenario | Requests | PU |
|---|---|---|
| Existing 4 areas, steady state | ≈ 116 + 60 catalog = 176 / month | ≈ 146 / month (Ķekava ≈ 140) |
| **All 78 candidates** (85 − 2 monitored − 5 without boundary), steady state | **≈ 2,262 / month** | **≈ 116 / month** (1,104 ha) |
| Their 120-day backfill (one-time) | **≈ 9,050** | ≈ 465 |
| Same with a 30-day backfill for auto-enrolled areas | ≈ 2,262 | ≈ 116 |
| **Capacity, steady state** (small sectors, existing load included) | (4,800 − 176) / 29 ≈ **159 small sectors** | PU allows ≈ 1,560 |
| Remaining this month under the guard | ≈ 4,240 requests → ≈ **35** 120-day backfills, or ≈ 140 30-day backfills | ≈ 686 PU |

Conclusion: steady state fits easily; the **120-day backfill does not** for all 78 at once (≈ 2 months of request budget).
Options: (1) a separate `auto_enroll_backfill_days` (e.g. 30) for reconciler-created areas, or (2) keep 120 days and let the
quota rule below spread enrolment over months. **Decision for the owner.** After D14 (archive all but BIK-001) the reconciler
has **0 candidates today**; the numbers matter for future registrations and for any un-archived sector.

## (c) Over quota → "Gaida kvotu", never silently skipped

No satellite.db schema change (`sat_jobs.status` CHECK allows only QUEUED/RUNNING/DONE/FAILED):
- The reconciler **always** queues an ADD_AREA job per candidate (the existing dedup key `ADD_AREA:SECTOR:{id}` prevents
  duplicates), so every eligible sector has a visible row.
- Before running an ADD_AREA job, the jobs worker estimates its backfill (the existing `backfill.dry_run` arithmetic:
  grid → `estimate_pu` × expected acquisitions) and checks *month usage + estimate* against the guard. If it does not fit,
  the job **stays QUEUED**, gets `result_json = {"waiting_quota": {"checked_at_utc", "needed_requests", "needed_pu",
  "month_requests", "month_pu", "guard_requests", "guard_pu"}}`, and the worker moves on to the next non-ADD job (STOP/FETCH
  are never blocked behind a waiting ADD). It is retried every tick; it runs when a new month resets the usage.
- API/UI: an open ADD_AREA job with `waiting_quota` → status **"Gaida kvotu"** / "Waiting for quota" (card chip, sector
  page, `/sat-monitoring/health` count). The daily TIMER run keeps its own existing guard (STOPPED_BY_GUARD).

## (d) Small sectors

Enrolled like every other sector. Flag derived only from pixel size, nothing stored: longest side < `PREVIEW_MIN_PX` (64 S2 px)
→ "Sektors ir mazs Sentinel-2 izšķirtspējai (10 m) — izmaiņu noteikšana var būt neuzticama" (card/page, see the earlier
proposal for placement). **74 of the 78 candidates are below 64 px.**

## Eligibility rule (proposed)

A sector is a candidate when **all** hold:
1. `archived_at IS NULL` (if the D14 column exists);
2. valid polygon: `areas.resolve_sector` succeeds (≥ 3 vertices, valid after the existing `areas.prepare`);
3. **no `sat_monitored_areas` row at all** for `SECTOR:{id}` (active **or stopped** — a manual stop is never undone) and no D7
   exact LVM GEO match;
4. inside Latvia: polygon bbox within the LV extent. **Excludes ids 9, 15, 16, 17** (legacy LKS-92 converter, 58.9 N /
   28.7–32.7 E) instead of paying to monitor the wrong place;
5. owner decision: only sectors with a registration record (`geodata_sources`, i.e. LVM GEO/VMD) — or all.

## (e) Exact files / functions

| File | Function | Change |
|---|---|---|
| `satellite_monitoring/reconcile.py` (new) | `candidates(sat_conn, forest_conn, cfg)`, `enroll(...)` | rule above; forest_ai.db **read-only** (`sdb.forest_ro`); queues through `store.queue_add_area("SECTOR", str(id), name, None, actor="auto-enroll")` — the same function `POST /api/sat-monitoring/areas` calls |
| `satellite_monitoring/jobs.py` | `process()` | call `reconcile.enroll` once per tick before claiming (behind `cfg["auto_enroll"]`, default **False** until approved) |
| `satellite_monitoring/jobs.py` | `_claim()` / `_run_job()` | quota pre-check for ADD_AREA; `waiting_quota` marker; claim order skips a waiting ADD |
| `satellite_monitoring/config.py` | `DEFAULTS` | `auto_enroll` (False), `auto_enroll_backfill_days` (if option 1), `auto_enroll_max_per_tick` (e.g. 5) |
| `satellite_monitoring/store.py` | `sectors()`, `overview()`, `health()`, sector summaries (D6) | expose `waiting_quota` → "Gaida kvotu" |
| `assets/sectors-cards.js` | `deriveStatus` | new status `WAITING_QUOTA` (LV "Gaida kvotu" / EN "Waiting for quota") |

Not changed: Sentinel requests/detection/thresholds, timers (the existing 5-min jobs timer runs it), satellite.db schema,
LVM GEO files. Worker venv only (`/root/forest_ai_satellite_venv2`).

## (f) Tests (fake provider, temporary DBs — the existing test pattern of `tests/test_sat_stage2_*.py`)

1. eligible sector → one ADD_AREA job; second tick → no duplicate (dedup);
2. skipped with a recorded reason: archived, no/invalid polygon, outside LV, existing active area, **stopped** area, D7 LVM GEO match;
3. quota: month usage near the guard → job stays QUEUED with `waiting_quota`, not FAILED; a STOP/FETCH job queued after it
   still runs; next month (fake `now`) → runs and creates the area;
4. `auto_enroll=False` → nothing queued;
5. forest_ai.db opened read-only (write attempt raises);
6. API: open ADD job with `waiting_quota` → card/summary status `WAITING_QUOTA`; JS: chip "Gaida kvotu";
7. small-sector flag: 639 m → flagged, 640 m → not (shared constant);
8. full suite: failure set = baseline (9 failed / 40 errors).

**STOP — approval needed:** eligibility rule 5, backfill option (1) or (2), `auto_enroll_max_per_tick`, and whether this
ships before or after D14.
