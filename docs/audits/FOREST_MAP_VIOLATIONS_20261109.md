# Forest Map → presence outside the cutting zone, 2026-11-09

| | |
|---|---|
| **Branch** | `feature/forest-map-violations`, from `origin/master` `349bec3` |
| **Commits** | `473ab0c` backend + tests · `9e6ddc2` UI + display fix · (this report) |
| **Release** | **prepared, NOT activated**: `/root/wt/forest-map-violations/releases/forest-api-forest-map-violations-20261109T1600Z` (`geo-4d6245820768`) |
| **Production** | untouched. No service was restarted. Production DB and geodata were only read (DB copied with `.backup`, read-only URI) |
| **Evidence** | screenshots outside git: `/root/wt/forest-map-violations/docs/evidence/forest-map-violations-20261109/` (git-ignored); `browser-check.json` next to them |
| **Waiting for** | your OK to activate |

"Cutting zone" = the registered sector the worker is assigned to (`work_sessions.sector`).

## 1. What was built

### Session track with violations (Forest Map → GPS layer)

**Opening a session:**
- Worker or vehicle popup → **session picker**, then **"Rādīt maršrutu"**.
  - Workers: `work_sessions` rows, shown as date · sector · points · "nav pabeigta".
  - Vehicles: they have no sessions, so the picker lists local days with stored pings.
  - The old time windows (Šodien / 24 h / Pielāgots) are still in the same picker.
- Deep link: `#forest-map/session-N` opens the map on that session. It is used as the track link in incident evidence.

**Track drawing:**
- Inside the assigned sector: green.
- Outside: **red, 8 px with a white halo**.
- Outside but **UNKNOWN** (within GPS accuracy): amber, dashed.
- Outside points are dots; their tooltip shows time, accuracy, distance and register class.
- **Flags:** "⇥ Izeja 08:30:14" at the first point outside, "⇤ Atpakaļ 08:33:51" at the first point back inside.
- S/E markers sit below the live markers, so the worker stays clickable.

**Clicking a red segment** opens a popup with:
- **Exit and re-entry:** time of the first point outside / first point back inside, plus the estimated crossing. If a gap hides the crossing, the popup shows "between A and B".
- **Duration** outside, with gap seconds named and not counted.
- **Points**, and how many lie beyond their accuracy.
- **Max distance from the sector boundary** in metres (EPSG:10306 via pyproj).
- **Compartments entered:** kadastrs · K · N from the national VMD index, "outside forest register", or another registered sector.
- **Median GPS accuracy.**
- **Status:**
  - **PĀRKĀPUMS** only if at least one point is farther from the polygon than its accuracy radius. A missing accuracy counts as the worst accepted accuracy, `FOREST_GPS_MAX_ACCURACY_M` = 100 m.
  - Otherwise **NENOSAKĀMS, nav pārkāpums**, with a reason: within accuracy / accuracy too poor / no polygon.
- **Incident:**
  - If one is linked: links that open it in Risks.
  - Otherwise: **"Izveidot incidentu"** for a violation; nothing for UNKNOWN segments or vehicles.

**Summary card (sidebar):**
- Time inside and time outside.
- Exits (violation / unknown), and whether the session started outside.
- Max distance, compartments entered and points.
- A note saying the Map-tab rules are used.
- An explicit line whenever the numbers could differ: segment sum ≠ Map tab, a stored flag ≠ the current polygon, vehicles, or no polygon.
- Clickable list of exits, with incident links and any session incidents not matched to an exit.

**Worker marker:** if the current/last position is outside its own assigned sector by more than the accuracy radius:
- red ring and label **"Ārpus cirsmas"**, which stays readable on stale markers;
- popup row "Pozīcija pret piešķirto sektoru".

If the accuracy radius crosses the boundary, the marker shows UNKNOWN with no ring.

### Numbers are the sector Map tab's numbers

Worker sessions use exactly the Map tab's inputs:
- `inside_boundary` stored per point by the bot;
- the straight-line crossing split (`session_track._crossing`);
- gaps > `TRACK_GAP_SECONDS` = 120 s counted as neither inside nor outside.

The summary's inside/outside values are taken from `session_track.build_track()` itself. The segment sums are checked against them (`matches_map_tab`).

The geometric distance and accuracy test is added on top of that. It only decides VIOLATION vs UNKNOWN; it never changes the time split. If a stored flag disagrees with the current polygon, the card says so, and the stored flag is used, as on the Map tab. Vehicles have no stored flag, so the current polygon is used, and the card says that.

### Incident link / button (human action)

**Linking an incident to an exit:**
- Incidents with `rule_code IN (SECTOR_EXIT, WORK_OUTSIDE_REGISTERED_COMPARTMENT)` belong to the session through `risks.session_id`, or through `risk_evidence(work_sessions, id)`.
- An incident is linked to an exit by its `GPS_EXIT_POINT` evidence.
- Failing that, by `occurred_at` (or `created_at`) falling between the last inside point − 120 s and the re-entry.

**"Izveidot incidentu"** → `POST /api/geodata/forest-map/gps/violations/incident {session_id, exit_point_id}`:
- The server recomputes everything; it never trusts client numbers. It refuses with 409 for an UNKNOWN segment and 404 for a non-exit point.
- **Dedup:** a process lock is held during the check and insert.
  1. An incident already linked to this exit is returned (`existing`).
  2. Otherwise, an OPEN/NOTIFIED `SECTOR_EXIT` of the same employee + sector + session gets this exit as evidence, plus a `STILL_OUTSIDE` event with the user as actor (`attached`). This is the bot's one-per-session rule (`bot.py` ~l. 966).
  3. Otherwise a new incident is created through the existing `database.add_incident`:
     - `SECTOR_EXIT`, `EMPLOYEE`, `HIGH`, `data_origin=REAL`;
     - `occurred_at` = first point outside, `distance_m`, `duration_min`;
     - `session_id` set as the bot does;
     - `risk_events CREATED_FROM_RECORD`, actor = the Basic Auth account (in the test: `fmv`).
- **Evidence** (`add_risk_evidence`, all REAL):
  - `GPS_EXIT_POINT` and `GPS_REENTRY_POINT` (ref `session_track_points` id);
  - `OUTSIDE_SEGMENT` (times, seconds, points, max distance, median accuracy);
  - `COMPARTMENTS_ENTERED`;
  - `TRACK` (`#forest-map/session-N · /api/sessions/N/track`).
- **AI recommendation:** the existing `risk_ai_worker` picks up any new risk with `ai_status` NULL.
- **Rule code:** `SECTOR_EXIT`, because leaving the assigned sector is what the bot raises. Compartments go into the evidence. Tell me if you want `WORK_OUTSIDE_REGISTERED_COMPARTMENT` when a VMD compartment was entered.
- **Automatic alerts stay OFF.** Nothing is created without the button. `FOREST_GPS_COMPARTMENT_ALERTS` is untouched (default off).

**API** (all inside the Forest Map router; **`api.py`, LVM GEO and registration backend unchanged**):

| method | path |
|---|---|
| GET | `/api/geodata/forest-map/gps/sessions?kind&id` |
| GET | `/api/geodata/forest-map/gps/violations?kind&id&session` |
| GET | `/api/geodata/forest-map/gps/session/{id}` (deep link) |
| POST | `/api/geodata/forest-map/gps/violations/incident` |

Also `assigned_status` was added to `/gps/positions`. `index.html` got the deep-link route only.

### Display fix: review reason precision (validation rule unchanged)

- **Before:** "Nogabals neatrodas pilnībā savā VZD zemes vienībā (100.00% iekšā)" (`toFixed(2)`).
- **Now:** decimals are added until the value is below 100, and the outside area is shown:
  - "(99,99999% iekšā · < 0,01 m² ārpus)"
  - EN: "(99.99999% inside · < 0.01 m² outside)"
  - "99,86% iekšā · 9,52 m² ārpus"
- `outside_area_m2` was already in the payload.
- **Not changed:** `assets/vmd-production.js` (LVM GEO page) has the same pattern with `toFixed(4)` ("Robežu neatbilstība · 100.0000% sakritība" is possible there). It is out of scope because LVM GEO was not to be touched. Say if you want it.

## 2. Session #32 (11.10.2026 08:24, Test User, BIK-001)

| | sector Map tab (`build_track(32)`) | Forest Map (new) |
|---|---|---|
| points | 29 | 29 |
| time inside | 660.04 s = **11 min 0 s** | 11 min 0 s |
| time outside | 200.96 s = **3 min 21 s** | 3 min 21 s (segment sum 200.9567 s, equal) |
| gaps > 120 s | 0 | 0 |
| exits | (not shown on Map tab) | **1**, violation |
| exit | — | first point outside #12 **08:30:14** (last inside #11 08:29:43, est. crossing 08:30:04) |
| re-entry | — | first point back inside #19 **08:33:51** (est. crossing 08:33:25) |
| outside points | — | 7 (#12–#18), all 7 beyond their accuracy |
| max distance from BIK-001 boundary | — | **79.8 m** |
| median accuracy | — | ± 3 m |
| compartments entered | — | **outside forest register** (7/7 points: no VMD compartment there) |
| incident | — | **#62** `SECTOR_EXIT` OPEN, linked (its `occurred_at` 05:30:14 UTC = point #12) → link to Risks |
| stored flag vs current polygon | — | 0 disagreements |

Why only the last marker was visible before: the GPS layer showed positions, and the track came only from a time window (today / 24 h). An October session was never drawn unless you picked a custom window, and the track had no exit marking.

### Screenshots

All in `docs/evidence/forest-map-violations-20261109/` (git-ignored); `release-8013/` holds the same set taken against the release folder.

| file | what |
|---|---|
| `01-session32-lv-track-summary.png` | session #32: green inside, red outside segment, exit/re-entry flags with times |
| `02-session32-lv-segment-popup.png` | segment popup (LV) with incident #62 link; summary card in the sidebar |
| `02b-session32-lv-line-click.png` | the same popup opened by clicking the red line itself |
| `03-worker-popup-session-picker-lv.png` | worker popup: assigned-sector status + session picker |
| `04-marker-outside-ring-lv.png` | red ring + "Ārpus cirsmas" (Jānis Bērziņš, A-005, see 4b) |
| `05-review-reason-precision-lv.png` | "(99,99999% iekšā · < 0,01 m² ārpus)" |
| `06-create-incident-button-lv.png` | "Izveidot incidentu" (#62 hidden in the /tmp copy for this test) |
| `07-incident-created-link-lv.png` | after the click: #63 linked |
| `08-risk-detail-opened.png` | link opened `#risk/63` in Risks |
| `09`/`10-session32-en-*.png` | EN summary + popup |
| `11-session32-phone.png` | 390 px width; no horizontal page scroll |

## 3. Tests (exact results)

| run | result |
|---|---|
| `FOREST_TEST_PROD_COPY=/tmp/fmv/forest_ai.db pytest tests/test_gps_violations.py tests/test_gps_map.py tests/test_forest_map.py` | `56 passed in 19.01s` |
| `node --test tests/test_forest_map_overlap.js` | `# pass 3 # fail 0` |
| other JS tests (`test_lvm_wms_map`, `test_vmd_local_ui`, `test_vmd_production_ui`, `test_vmd_test_geojson`) | 9 / 7 / 16 / 3 pass, 0 fail |
| full `pytest tests` on **branch** | `9 failed, 284 passed, 3 skipped, 40 errors` |
| full `pytest tests` on **origin/master** (same box) | `9 failed, 269 passed, 2 skipped, 40 errors` |

The failure/error lists are **identical** (`diff` of the sorted FAILED/ERROR lines is empty). They are pre-existing:
- `test_nationwide_geodata.py` errors;
- `test_vmd_production.py::test_real_native_source_exact_designations_geometry_and_cadastral_gate[40940020002-10]` and others.

The branch adds 15 passing tests and 1 test skipped without `FOREST_TEST_PROD_COPY`.

**What `tests/test_gps_violations.py` (17 tests) covers:**
- exit/re-entry, with the Map-tab equality asserted in every scenario;
- two exits;
- a gap inside an outside segment (not counted, line split);
- an exit across a gap (time unknown, "between");
- started/ended outside;
- within accuracy → UNKNOWN;
- missing accuracy → worst accepted (50 m out = UNKNOWN, 150 m = VIOLATION);
- accuracy too poor → UNKNOWN;
- compartments entered (VMD id/K/N and outside register);
- incident: created with fields, event actor and all 5 evidence items;
- second press → `existing`, still 1 risk;
- second exit → `attached` + `STILL_OUTSIDE` actor;
- a bot-created incident matched by time → no duplicate;
- UNKNOWN segment → refused, no row;
- non-exit point → 404;
- session picker;
- marker assigned status;
- **session #32 on a production copy** = Map tab (660/201 s, 1 exit, incident 62).

**JS test:** never 100 when < 100, EN/LV decimal and m² format, and the template order.

**Browser** (headless Chromium, `:8012` with the branch + `:8013` with the release folder, `/tmp` DB copies):
- LV and EN; **0 console errors, 0 page errors**;
- line click opens the popup;
- incident created (#63 in the copy), second press `existing`, Risks link opens `#risk/63`;
- 390 px: `scrollWidth 390 = innerWidth 390`.

**Note:** `:8011` was already taken by another agent's server (`/root/forest_ai_ui_p0_test/_baseline`, since 12:25). I did not touch it and used 8012/8013. Both of my servers are stopped.

## 4. Report items (no changes)

### (a) Containment tolerance and Biķernieki compartments

**Tolerance: none.** Registration requires `parcel.covers(compartment)` on the unmodified native EPSG:10306 geometry:
- `nationwide.compartment_validation` l. 186;
- `nationwide.parcel_validation` l. 87;
- the search path l. 137;
- `cadastral_authority` l. 49 ("Bez pielaides, bufera vai robežu labošanas").

There is no buffer, snapping or area threshold. A difference of 2·10⁻⁹ m² blocks registration.

**VMD compartments within 1 km of BIK-001** (national release, all 248 checked with `compartment_validation`):

| | count |
|---|---|
| total | 248 (71 intersect the BIK-001 polygon) |
| `verified`, registration allowed | 165 (158 also `importable`; 35 intersect BIK-001) |
| **`boundary_review_required` → review-only** | **83** (36 intersect BIK-001) |
| … outside area < 0.001 m² | 8 |
| … 0.001–0.1 m² | 62 |
| … 0.1–1 m² | 11 |
| … 1–10 m² | 1 (`VMD:nodala2653:64835054`, 01000920600 K123 N8, 99.8568 %, **9.52 m²**) |
| … ≥ 10 m² | 1 (`VMD:nodala2653:73459706`, 01000922290 K127 N19, **0 % inside, 1 835.25 m²**: not in its parcel at all) |
| would have displayed "100.00%" before the fix | **77** |

Median outside area of the 83 is **0.03 m²**. So 81 of 83 are blocked by numerical slivers smaller than 1 m² between the VMD and VZD boundaries, not by a real discrepancy.

**Can a real cutting area there be registered today?**
- Yes, if it consists only of the 165 verified compartments: 35 of them lie in the BIK-001 area.
- No, if it includes any of the 83 review-only compartments: 36 of them lie in the BIK-001 area, and 35 of those 36 differ by less than 1 m².
- There is no manual override in the registration path.
- Context: BIK-001 itself is a hand-drawn 4-point polygon (50.35 ha, "Rekreācijas mežs, mežizstrāde nenotiek"), not a set of VMD compartments.

<details><summary>All 83 review-only compartments (sorted by outside area)</summary>

| VMD id | kadastrs · K · N | inside % | outside m² | in BIK-001 polygon |
|---|---|---|---|---|
| VMD id | kadastrs · K · N | inside % | outside m² | in BIK-001 polygon |
|---|---|---|---|---|
| VMD:nodala2653:95263474 | 01000922053 · K124 · N3 | 99.9999999999 | 2.17324e-09 | yes |
| VMD:nodala2653:157907165 | 01000920499 · K121 · N14 | 99.999999999 | 3.10042e-08 | yes |
| VMD:nodala2653:51006795 | 01000922053 · K127 · N1 | 99.99999999 | 8.38605e-07 | yes |
| VMD:nodala2653:108371697 | 01000710012 · K127 · N21 | 99.9999995 | 1.30961e-06 | yes |
| VMD:nodala2653:51006658 | 01000922053 · K124 · N25 | 99.99999 | 0.000185136 | yes |
| VMD:nodala2653:66728243 | 01000922053 · K124 · N4 | 99.999998 | 0.000233997 | yes |
| VMD:nodala2653:51006772 | 01000922053 · K125 · N5 | 99.999996 | 0.000421574 | no |
| VMD:nodala2653:108371701 | 01000710012 · K127 · N22 | 99.999 | 0.000463841 | no |
| VMD:nodala2653:51006664 | 01000922053 · K125 · N1 | 99.99999 | 0.00145665 | yes |
| VMD:nodala2653:64835065 | 01000920600 · K123 · N19 | 99.9999 | 0.00170763 | no |
| VMD:nodala2653:157907110 | 01000920499 · K118 · N12 | 99.99997 | 0.00259408 | no |
| VMD:nodala2653:51006659 | 01000922053 · K124 · N26 | 99.99996 | 0.00282447 | yes |
| VMD:nodala2653:157907130 | 01000920499 · K118 · N6 | 99.99999 | 0.00284632 | no |
| VMD:nodala2653:108371538 | 01000711181 · K127 · N20 | 99.9996 | 0.00285482 | yes |
| VMD:nodala2653:51006897 | 01000922053 · K127 · N4 | 99.9999 | 0.00306376 | yes |
| VMD:nodala2653:73459592 | 01000712439 · K127 · N21 | 99.996 | 0.00336469 | yes |
| VMD:nodala2653:51006903 | 01000922053 · K127 · N10 | 99.9998 | 0.00338469 | no |
| VMD:nodala2653:51006898 | 01000922053 · K127 · N5 | 99.9999 | 0.00353456 | yes |
| VMD:nodala2653:157907158 | 01000920499 · K120 · N1 | 99.99998 | 0.00381366 | no |
| VMD:nodala2653:61151386 | 01000922135 · K1 · N6 | 99.99999 | 0.00389641 | no |
| VMD:nodala2653:51006648 | 01000922053 · K124 · N15 | 99.9999 | 0.00413286 | yes |
| VMD:nodala2653:73459593 | 01000712439 · K127 · N22 | 99.998 | 0.0045599 | no |
| VMD:nodala2653:51006907 | 01000922053 · K127 · N14 | 99.9999 | 0.00472172 | no |
| VMD:nodala2653:51006786 | 01000922053 · K126 · N5 | 99.99998 | 0.00507526 | no |
| VMD:nodala2653:66728272 | 01000922053 · K125 · N6 | 99.9999 | 0.00514185 | no |
| VMD:nodala2653:64835048 | 01000920600 · K123 · N2 | 99.9997 | 0.00663938 | yes |
| VMD:nodala2653:51006782 | 01000922053 · K126 · N1 | 99.9999 | 0.00717448 | no |
| VMD:nodala2653:51007208 | 01000922053 · K129 · N11 | 99.9999 | 0.00727128 | no |
| VMD:nodala2653:157907149 | 01000920499 · K109 · N12 | 99.9998 | 0.00782044 | no |
| VMD:nodala2653:51006660 | 01000922053 · K124 · N27 | 99.9999 | 0.00855615 | yes |
| VMD:nodala2653:157907127 | 01000920499 · K118 · N4 | 99.99997 | 0.00856146 | no |
| VMD:nodala2653:157907166 | 01000920499 · K121 · N12 | 99.9996 | 0.0099373 | yes |
| VMD:nodala2653:157907136 | 01000920499 · K118 · N11 | 99.9999 | 0.0138399 | no |
| VMD:nodala2653:75276557 | 01000710735 · K1 · N2 | 99.999 | 0.0146832 | no |
| VMD:nodala2653:157907137 | 01000920499 · K110 · N11 | 99.999 | 0.0164753 | no |
| VMD:nodala2653:61151371 | 01000922135 · K1 · N45 | 99.9996 | 0.0179572 | yes |
| VMD:nodala2653:61151348 | 01000922135 · K1 · N41 | 99.9999 | 0.0193781 | no |
| VMD:nodala2653:61151354 | 01000922135 · K1 · N27 | 99.9999 | 0.0217753 | no |
| VMD:nodala2653:51954307 | 01000920409 · K1 · N4 | 99.999 | 0.0262683 | no |
| VMD:nodala2653:51007207 | 01000922053 · K129 · N10 | 99.999 | 0.0270945 | no |
| VMD:nodala2653:157907154 | 01000920499 · K121 · N18 | 99.999 | 0.0285109 | yes |
| VMD:nodala2653:157907192 | 01000920499 · K121 · N4 | 99.9999 | 0.0304886 | no |
| VMD:nodala2653:51007194 | 01000922053 · K128 · N13 | 99.9998 | 0.0311959 | no |
| VMD:nodala2653:157907141 | 01000920499 · K121 · N17 | 99.999 | 0.0324399 | yes |
| VMD:nodala2653:157907129 | 01000920499 · K118 · N7 | 99.9999 | 0.0327494 | no |
| VMD:nodala2653:51006787 | 01000922053 · K126 · N6 | 99.998 | 0.0373728 | no |
| VMD:nodala2653:51713503 | 01000922135 · K1 · N46 | 99.9996 | 0.0375685 | yes |
| VMD:nodala2653:64835061 | 01000920600 · K123 · N15 | 99.998 | 0.0378965 | yes |
| VMD:nodala2653:64835062 | 01000920600 · K123 · N16 | 99.997 | 0.0407284 | yes |
| VMD:nodala2653:51006785 | 01000922053 · K126 · N4 | 99.9997 | 0.0423587 | no |
| VMD:nodala2653:51713507 | 01000922135 · K1 · N5 | 99.999 | 0.0441758 | no |
| VMD:nodala2653:157907169 | 01000920499 · K121 · N15 | 99.999 | 0.0447772 | yes |
| VMD:nodala2653:49745823 | 01000920166 · K696 · N1 | 99.998 | 0.0453495 | no |
| VMD:nodala2653:64831645 | 01000920144 · K123 · N21 | 99.996 | 0.0478149 | yes |
| VMD:nodala2653:61151385 | 01000922135 · K1 · N20 | 99.9999 | 0.0481205 | no |
| VMD:nodala2653:157907163 | 01000920499 · K120 · N14 | 99.9996 | 0.049081 | yes |
| VMD:nodala2653:64835053 | 01000920600 · K123 · N7 | 99.999 | 0.0509093 | yes |
| VMD:nodala2653:64835058 | 01000920600 · K123 · N12 | 99.998 | 0.0542569 | yes |
| VMD:nodala2653:64835056 | 01000920600 · K123 · N10 | 99.998 | 0.0560175 | no |
| VMD:nodala2653:64835057 | 01000920600 · K123 · N11 | 99.998 | 0.0573952 | no |
| VMD:nodala2653:64835064 | 01000920600 · K123 · N18 | 99.998 | 0.0621001 | no |
| VMD:nodala2653:157907186 | 01000920499 · K121 · N8 | 99.9999 | 0.0630965 | no |
| VMD:nodala2653:157907170 | 01000920499 · K120 · N12 | 99.998 | 0.0632469 | yes |
| VMD:nodala2653:64833558 | 01000920162 · K123 · N22 | 99.98 | 0.0645344 | yes |
| VMD:nodala2653:157907173 | 01000920499 · K120 · N13 | 99.998 | 0.0654781 | yes |
| VMD:nodala2653:157907160 | 01000920499 · K121 · N11 | 99.998 | 0.0670313 | no |
| VMD:nodala2653:64835059 | 01000920600 · K123 · N13 | 99.997 | 0.069031 | yes |
| VMD:nodala2653:51712958 | 01000922135 · K1 · N12 | 99.998 | 0.0725571 | no |
| VMD:nodala2653:51954305 | 01000920409 · K1 · N2 | 99.999 | 0.0933809 | no |
| VMD:nodala2653:51713504 | 01000922135 · K1 · N47 | 99.998 | 0.0941965 | no |
| VMD:nodala2653:51713491 | 01000922135 · K1 · N35 | 99.999 | 0.101198 | yes |
| VMD:nodala2653:64835060 | 01000920600 · K123 · N14 | 99.997 | 0.111512 | yes |
| VMD:nodala2653:61151379 | 01000922135 · K1 · N44 | 99.999 | 0.113564 | no |
| VMD:nodala2653:157907193 | 01000920499 · K121 · N10 | 99.9998 | 0.128069 | yes |
| VMD:nodala2653:157907182 | 01000920499 · K120 · N4 | 99.998 | 0.133127 | no |
| VMD:nodala2653:64835063 | 01000920600 · K123 · N17 | 99.997 | 0.133644 | yes |
| VMD:nodala2653:60013168 | 01000920230 · K1 · N1 | 99.98 | 0.154026 | no |
| VMD:nodala2653:64835055 | 01000920600 · K123 · N9 | 99.997 | 0.203007 | no |
| VMD:nodala2653:51713239 | 01000922135 · K1 · N18 | 99.9996 | 0.20919 | no |
| VMD:nodala2653:51954309 | 01000920409 · K1 · N6 | 99.99 | 0.286562 | no |
| VMD:nodala2653:51713505 | 01000922135 · K1 · N48 | 99.99 | 0.825183 | no |
| VMD:nodala2653:64835054 | 01000920600 · K123 · N8 | 99.86 | 9.51937 | no |
| VMD:nodala2653:73459706 | 01000922290 · K127 · N19 | 0.00 | 1835.25 | yes |
</details>

### (b) The rectangular sector over residential Purvciems

| | |
|---|---|
| id / name | **2 / `A-005`** (contractor "Rigas Mezi", approved_volume "600 m3", `data_origin` **REAL**) |
| geometry | axis-aligned rectangle `[[56.965,24.18],[56.965,24.195],[56.955,24.195],[56.955,24.18]]`, 101.5 ha (`area_ha` 101.35) |
| created_at | **2026-06-11 10:09:31 UTC**; updated_at 2026-09-17 05:38:33 UTC |
| creator | **not recorded**: `created_by_user_id`, `created_by_account` and the responsible names are NULL (those columns were added later). There is no audit row; the sector predates the git history (first commit 2026-09-04) |
| geometry source | **the example coordinates from the product's own help text**, verbatim: `/add_sector` help in `bot.py` (l. 769/783/809 at `1e9c98f`), the dashboard create-sector placeholder (`index.html` `#cs-boundary`) and the `database.py` parser docstring. It is not from VMD/VZD (`boundary_plan_id` NULL) |
| forest inside | **0.00 ha** of VMD compartments intersect it, so it covers Purvciems apartment blocks |
| used by | `services/demo_scenarios.py` (`SECTOR_EXIT_SECTOR = "A-005"`, wetland demo just south), 4 work sessions, risks 35–37, 55–58 |

The "Ārpus cirsmas" marker in screenshot 04 is Jānis Bērziņš (employee 4):
- his last stored position (2026-09-17) is 137.1 m south of A-005;
- `live_locations.last_status` says `IN` because the demo writer stores a literal status (`demo_scenarios._upsert_live_location`), not a computed one;
- the new marker uses geometry, so it shows him outside.

Recommendation, not done: set A-005 to demo/SIMULATED, or delete it. It is labelled REAL.

### (c) Open sessions

- Session **#32 is still open**: `finish_time` NULL, shown as "nav pabeigta". At 2026-11-09 15:30 UTC it had been open 706.1 h.
- It is the **only** open session; the live DB was checked read-only (`count = 1, max id 32`).
- Open sessions > 12 h: **#32 only** (Test User, employee 2, BIK-001, 29 points).
- Nothing closes sessions automatically; no auto-close was added.

## 5. Release (prepared, NOT activated)

**Folder:** `/root/wt/forest-map-violations/releases/forest-api-forest-map-violations-20261109T1600Z` (git-ignored). I did not write it into `/root/forest_ai/releases/`, because the agent rules forbid that path.

**Live baseline drift found:**
- `:8000` no longer runs the GPS release that `DEPLOY_RELEASES.md` names.
- Since **14:31 UTC** it runs `/root/wt/remove-map-sidebar/releases/forest-api-remove-map-sidebar-20261109`, via drop-in `80-remove-map-sidebar-release.conf`. That folder is in another agent's worktree, and the release is not documented in `DEPLOY_RELEASES.md` on master.

**How it was built:**
- Copy of that live folder (69 files), then overlay of the 5 files this branch changes.
- `index.html` = the live file + this branch's deep-link hunk (`git diff 349bec3..HEAD -- index.html`, applied cleanly). The live sidebar change is kept.
- `api.py`, `database.py` and `session_track.py` are byte-identical to live; no DB migration and no new dependency.

**Manifest and activation files:**
- `release-manifest.json` records the baseline SHA-256 of every file at build time and the full inventory.
- `pre-activation-check.sh` → `OK: baseline unchanged since build; 69 files verified` (at build time).
- `90-forest-map-violations-release.conf` is the drop-in, **not installed**.

**Smoke test on `:8013`** (release folder, /tmp DB copy):
- `/api/deployment` → `geo-4d6245820768`, backend `552c46ae547b`;
- the served page has `FOREST_MAP_ENABLED=true`;
- session #32 gives the same numbers;
- bad session → 422, no auth → 401;
- browser check as above.

**To activate (after your OK):**
```sh
/root/wt/forest-map-violations/releases/forest-api-forest-map-violations-20261109T1600Z/pre-activation-check.sh   # must print OK; else rebuild
cp …/90-forest-map-violations-release.conf /etc/systemd/system/forest-api.service.d/
systemctl daemon-reload && systemctl restart forest-api
curl -su "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" http://127.0.0.1:8000/api/deployment   # expect geo-4d6245820768
```
Rollback: remove the `90-` drop-in, `daemon-reload`, restart. The `80-` remove-map-sidebar release becomes active again.

**Caution:** the release lives in a worktree. If the worktree is removed, the release goes with it. Copy the folder to a permanent place before activating if you prefer.

## 6. Not verified / limits

- **Real Telegram exit:** not tested live with a phone. No real exit happened during this task, and the user's own account routes to the tenant DB. Only the stored session #32 and synthetic tests were used.
- **Vehicles:**
  - the day-session view was tested only through code paths and unit logic;
  - the only stored pings are 3 single 2026-09-08 points (origin UNKNOWN, hidden by default);
  - no SIMULATED sync was run;
  - incidents are never offered for vehicles.
- **AI recommendation** for a button-created incident was not run: the temp server had no AI key and no worker. It uses the existing `risk_ai_worker` path, unchanged.
- **Concurrency:** dedup uses a process-local lock plus the DB check. :8000 runs one uvicorn process, so that is enough there. With several worker processes, two simultaneous first presses could still race.
- **Inconsistency left as is:** `gps_map._raise` (flag-gated alerts) writes `entity_type='worker'`, while the bot and this button use `'EMPLOYEE'`. The Risks page and `exit_route()` expect `EMPLOYEE`.
- **Pre-existing i18n:** in the EN popup "Platība" stays LV, and the Risks status/rule labels come from the instance's `i18n-lv.js` layer. Neither was touched.
