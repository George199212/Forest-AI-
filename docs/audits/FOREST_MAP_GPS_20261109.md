# Forest Map → GPS control map, 2026-11-09

| | |
|---|---|
| **Branch** | `feature/forest-map-gps`, **stacked on `feature/forest-map-finish`** (your decision: finish is not merged or activated yet) |
| **Release** | **prepared, NOT activated**: `releases/forest-api-forest-map-gps-20261109T1129Z` (`geo-9c94d506a565`). It contains the finish work too |
| **Production** | untouched by this work. `forest-api` still runs the meza-karte folder |
| **Evidence** | `docs/audits/forest-map-gps-20261109/`. Screenshots are outside git (session scratchpad, `verify_3/*.png`) |

**Decisions you made at the start:**
- Stack on finish.
- Demo data = real data plus **labelled SIMULATED** data from the existing `fleet_gps_demo` sync.
- Vehicle pings without provenance = origin **UNKNOWN**, hidden by default.

## Step 0: data inventory (read-only, production DB backup taken 2026-11-09 10:55 UTC)

| source | table | rows | last 7 / 30 days | entity | frequency | accuracy | links to | origin |
|---|---|---|---|---|---|---|---|---|
| Telegram live location | `live_locations` | 2 (newest 2026-10-11) | 0 / 1 | worker | one row per worker, updated per point | none | `employee_id`, `telegram_user_id`, sector | REAL |
| Telegram live-location track | `session_track_points` | 29 (one session, BIK-001, 2026-10-11 05:24–05:38) | 0 / 29 | worker | median 31 s, max 36 s, no gaps > 120 s | `horizontal_accuracy` on 28/29 points, avg 3 m | session, employee, sector | REAL |
| Bot / integration pings | `vehicle_gps_pings` | 3 (2026-09-08, A-005 machines with plates ending `-DEMO`) | 0 / 0 | vehicle / equipment | single pings | none | `vehicle_id` / `equipment_id`, sector | **not provable**: `provider`/`source` empty; bot pings (`bot.py`) and fleet-integration mirrors (`categories.py`) also store none |
| John Deere | `sector_equipment` (+ pings with `provider='john_deere'`) | 1 demo harvester (`is_demo=1`), no position | — | machine | sync on demand | none | sector, operator | SANDBOX: **0 positions** |
| Simulated fleet | `integration_records` (`fleet_gps_demo`) | 0 before the demo sync | — | vehicle | one position per vehicle per sync run (time bucket) | none | plate, sector | SIMULATED |

**What is real today:**
- one 29-point worker track and two stale worker positions, all at least 29 days old;
- no live position from any source;
- no real vehicle or machine positions.

**At the demo:**
- live REAL positions appear only if someone shares a Telegram live location;
- SIMULATED vehicles appear after the existing Integrations → fleet_gps_demo sync, and are clearly labelled.

## What was built

**Step 1: live positions layer** (`gps_map.positions`, `GET /api/geodata/forest-map/gps/positions`; `forest-map.js`)

| source | read from | origin |
|---|---|---|
| Workers | `live_locations`, with accuracy from the matching stored track point | REAL |
| Vehicles and equipment | the newest `vehicle_gps_pings` per entity | `provider='john_deere'` → SANDBOX; otherwise UNKNOWN |
| John Deere machines | `sector_equipment` with a location | SANDBOX |
| Simulated fleet | `fleet_gps_demo` integration records | SIMULATED |

- **Mirror pings:** fleet integrations copy each record into `vehicle_gps_pings` without provenance. A ping with the same vehicle id and identical coordinates is recognised as that record and shown **once**, with the integration's origin.
- **Markers:** icon by type (worker / vehicle / machine); colour by origin (REAL blue, SIMULATED purple with a dashed ring, SANDBOX orange, UNKNOWN grey). Stale entities are faded and labelled "novecojis" (stale), with age. The stale threshold is configurable (`FOREST_GPS_STALE_MINUTES`, default 15, adjustable in the UI).
- **Polling:** every 30 s, paused while the tab is hidden; no websockets.
- **Popup:** name/plate/code, type, assigned sector, last update with "pirms X min" (X min ago), accuracy, origin with an explanation, and the spatial status (Step 3).
- **Filters:** type, origin (UNKNOWN off by default), sector, only active.

**Step 2: tracks** (`gps_map.track`, `GET /gps/track`)
- Windows: today / last 24 h / custom (up to 31 days).
- **Stored points only.** Every drawn vertex is a stored point. Gaps longer than `session_track.TRACK_GAP_SECONDS` (120 s) are not drawn; their ends are marked with the gap length.
- Runs are coloured by spatial class. A class change between two points is drawn grey and dashed, never as an invented crossing point.
- Start/end markers; photos placed when within ±60 s (`session_track.PHOTO_MATCH_SECONDS`).

**Step 3: spatial check of every point** (`gps_map.Classifier`)
- Done server-side in EPSG:10306 metres. pyproj handles the WGS84 → EPSG:10306 step, against registered sector polygons and the read-only national index (`native_index` + `native_geometry`).
- The accuracy radius is a buffer:

| class | condition |
|---|---|
| `INSIDE_REGISTERED_SECTOR` (sector) | buffer fully inside a sector |
| `INSIDE_UNREGISTERED_COMPARTMENT` (kadastrs, kvartāls, nogabals), "outside the approved area" | buffer covered by compartments that are not a registered sector |
| `OUTSIDE_FOREST_REGISTER` (road, field, settlement; not an alarm by itself) | buffer touches no compartment |
| `UNKNOWN` (with reason) | accuracy above `FOREST_GPS_MAX_ACCURACY_M` (100 m); accuracy radius crossing a sector or compartment boundary (**not a violation**); register unavailable; invalid register geometry; no position |

- A buffer spanning two *unregistered* compartments stays unregistered: no class boundary is crossed.

**Step 4: alert** (`gps_map.evaluate_alerts`; loop every 60 s **only when `FOREST_GPS_COMPARTMENT_ALERTS=1`**; default off)
- **Data used:** only REAL worker points (`session_track_points`) are evaluated. SIMULATED, SANDBOX and UNKNOWN points are never read by the evaluator.
- **Trigger:** ≥ `FOREST_GPS_ALERT_MIN_POINTS` (3) consecutive points, without a gap, in the same unregistered compartment, lasting ≥ `FOREST_GPS_ALERT_MIN_MINUTES` (5). Looks back `FOREST_GPS_ALERT_LOOKBACK_MINUTES` (180).
- **Incident:** `rule_code=WORK_OUTSIDE_REGISTERED_COMPARTMENT`, created via the existing `add_incident`, plus `add_risk_event('DETECTED')` and `add_risk_evidence`: compartment, first point, last point, track link; all `data_origin='REAL'`.
- **Dedup:** one OPEN/NOTIFIED incident per worker + compartment. Later points only update the last-point evidence.
- **Follow-up:** the AI recommendation is produced by the existing `risk_ai_worker`, which picks up OPEN non-demo risks without a recommendation. **No new AI or notification code.**
- **Real data check:** with the flag on, the real 2026-10-11 track produces **no incident**. Its points are inside BIK-001 (22) or outside the forest register (7), never in an unregistered compartment (`alert_check.txt`).

**Step 5: UI, i18n, performance**
- LV and EN are complete for every new string (browser-checked in both languages).
- The Karte page is unchanged. `api.py`, `index.html` and LVM GEO/registration code are unchanged.

## Numbers

**Real data on the map** (`positions_real.json`, `track_real.json`):
- 5 stored entities, all stale. 2 REAL workers shown; 3 UNKNOWN A-005 machines hidden by default.
- The real BIK-001 track: 29 points, 0 gaps, 22 `INSIDE_REGISTERED_SECTOR` + 7 `OUTSIDE_FOREST_REGISTER`, 2 class changes. This matches the 22 "inside" flags the bot stored at the time.

**100 moving entities** (synthetic SIMULATED records in the `/tmp` DB copy only; moved twice between 30 s polls; zoom-13 compartments visible; `perf_gps*.json`):

| | markers recreated each poll (first version) | **markers reused (final)** |
|---|---|---|
| `/gps/positions`, 107 entities incl. spatial check | 0.12–0.38 s, 45.7 KB | 0.12–0.16 s (cold 0.63 s), 45.8 KB |
| render per poll (104 markers) | 271 ms / 56 ms | **16 ms / 16 ms** |
| long tasks during a poll window | 492 ms / 181 ms (longest 371 ms) | **0 ms** |
| 5 pans at zoom 13 (incl. compartment tiles) | 794 ms total, longest 115 ms | 2,020 ms total, longest 180 ms |

The pan figures vary with host load: one run under load average 3.9 from other processes measured 14.3 s, discarded and repeated. The shared 2-vCPU host dominates pan cost through compartment tile drawing, not the GPS layer.

## Tests

| test | result |
|---|---|
| `tests/test_gps_map.py` (18) | inside sector; unregistered compartment (id, kadastrs, K, N); outside register; accuracy crossing the register edge → UNKNOWN; accuracy across two unregistered compartments stays unregistered; accuracy crossing the sector edge → UNKNOWN; poor accuracy / no geodata → UNKNOWN with reason; origins REAL / UNKNOWN / SANDBOX / SIMULATED and staleness; gap > 120 s stays a gap with no interpolated vertex; runs split by class with explicit transition; window validation; **flag off → no incidents**; flag on → one incident with 4 REAL evidence items and a DETECTED event; **dedup** on re-evaluation; short or gapped runs don't alert; accuracy-ambiguous points don't alert; **SIMULATED/SANDBOX never alert**; integration mirror shown once with its origin; endpoints (no-store, 422 on bad kind) |
| `tests/test_gps_map.py` + `tests/test_forest_map.py` | 40 passed |
| Full suite, branch vs clean `origin/master`, same command | branch **278 passed** / master 254. **Identical** 10 failures (9 `test_vmd_production` need the local catalogue; 1 `test_john_deere_sync`) and the same 30 order-dependent `test_integrations` errors already on master |
| Browser acceptance (`verify_gps.py`, staging tree identical to the release) | **22/22**. Covers: markers hide UNKNOWN by default; origin classes; stale marking; each filter (origin, only active, type, sector); worker popup in LV with spatial status; real track summary, drawing and start/end; SIMULATED popup labelled; 30 s polling; LV and EN filter/popup texts; compartment popup still works; Karte page and `#lvm-geodata` without errors; no console errors, failed requests or HTTP errors |

## Release: prepared, NOT activated

Activating this release also activates the Forest Map finish work, because this branch is stacked on it. You can
activate either `forest-api-forest-map-finish-20261109T1023Z` first, or this one alone. The alert flag is
off unless you add the optional line.

```sh
REL=/root/forest_ai/releases/forest-api-forest-map-gps-20261109T1129Z
# 0. Guard: must print OK. If NOT OK, the live folder changed after the build; rebuild.
$REL/pre-activation-check.sh
# 1. Back up the unit configuration (no migrations; the database is not touched).
B=/root/forest_ai/data/backups/forest_map_gps_$(date -u +%Y%m%dT%H%MZ); install -d -m 0700 "$B"; cp -p /etc/systemd/system/forest-api.service.d/*.conf "$B"/
# 2. Activate: a drop-in later in name order overrides WorkingDirectory.
printf '[Service]\nWorkingDirectory=%s\n' "$REL" > /etc/systemd/system/forest-api.service.d/70-forest-map-gps-release.conf
#    Optional, only with explicit approval: compartment alerts (default off)
#    printf '[Service]\nEnvironment=FOREST_GPS_COMPARTMENT_ALERTS=1\n' > /etc/systemd/system/forest-api.service.d/71-forest-gps-alerts.conf
systemctl daemon-reload && systemctl restart forest-api
# 3. Verify (within 1 minute)
systemctl is-active forest-api
readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd       # expect $REL
curl -su "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" http://127.0.0.1:8000/api/deployment                       # expect geo-9c94d506a565
curl -su "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/geodata/forest-map/gps/positions   # expect 200
```

**Rollback (under 1 minute; no data to restore):**

```sh
rm -f /etc/systemd/system/forest-api.service.d/70-forest-map-gps-release.conf /etc/systemd/system/forest-api.service.d/71-forest-gps-alerts.conf
systemctl daemon-reload && systemctl restart forest-api
readlink /proc/$(systemctl show -p MainPID --value forest-api)/cwd       # expect the previous release folder
```

If the alert flag was on, incidents it created stay in `risks` as ordinary REAL incidents. They are closed
like any other incident; rollback does not delete them.

## What was NOT verified / known limits

- **No live REAL data exists.** Live behaviour is verified with tests and SIMULATED records only. A real
  Telegram live-location share during the demo should appear within 30 s; this was not observed end to end.
- **The alert loop on real data:** tested on temp DBs and on the real 29-point track (no qualifying run).
  Not run against a real violation.
- **Bot vehicle pings have no provenance** (`bot.py` stores no `provider`/`source`). They show as UNKNOWN
  until the bot stamps them; that change is outside this task.
- **John Deere SANDBOX:** no machine positions exist; that path is covered by unit tests only.
- **Touch devices** were not tested.
