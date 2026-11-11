# Satellite Monitoring — positive control: Ķekava (VMD 2026 clear-cuts)

Branch `feature/satellite-monitoring` · evaluated 2026-11-11 · contains modified Copernicus Sentinel data [2026].
Ground truth: VMD Meža valsts reģistrs open data (CC0-1.0, nationwide release 20261106, snapshot 2026-10-07).

Labels: **RAW** = Copernicus data as delivered (GeoTIFF + sha256) · **PROCESSED** = statistics computed here ·
**INTERPRETATION** = automated rules · **HUMAN** = review (none yet, except where marked "visual check").

## 1. Run

| | |
|---|---|
| area | #2 `Kekava positive control`, source `EVAL_BBOX`, bbox 24.10,56.812 – 24.20,56.866, 3,670.17 ha (100 m buffer) |
| window | 2026-05-01 … 2026-11-10, S1 + S2, run #2 `BACKFILL`, worker venv2 |
| result | status **OK**, no errors, no guard stop |
| requests | **200** (5 Catalog incl. pagination + 195 Process), all counted in `sat_request_log` |
| PU | **840.13 measured** (estimate was ~840); not estimated |
| acquisitions | 251 new: S1 136 OK; S2 59 OK, 56 `SKIPPED_CLOUD` |
| detections | 39 events, 100 radar anomalies (82 promoted); S2 candidates: CONFIRMED 15, PENDING_CONFIRMATION 1, TRANSIENT 10 |
| backup before run | `/root/backups/satellite_before_kekava_20261111T070616Z.db` (the run migrated `satellite.db`: `EVAL_BBOX`, `sat_radar_anomalies`, `sat_s2_candidates`) |
| ground truth | `/root/forest_ai_satellite_data/eval/kekava_vmd_2026_clearcuts.geojson`, sha256 `7faf461382a2cf42c10ecd2d6190d172d5617cfcffeab1373c79a880bd5d812e` (19 stands, 31.93 ha; WGS84 from the verified `forestry_io` converter) |
| evaluation output | `/root/forest_ai_satellite_data/eval/kekava_evaluation_20261111.json` (per-stand S2 series included) |
| review sheets | `/root/forest_ai_satellite_data/satellite/2/events/review_eval/` (`stand_*.png`, `event_*.png`; cropped to the mask, yellow outline, false colour B11/B08/B04, S1 VH dB) |

Method: `python -m satellite_monitoring.positive_control` (definitions in its docstring). Stand interior = stand
raster eroded by 1 px. "Cut" in an S2 image = interior median minus intact-VMD-forest median within 1 km
(1,097 reference stands: zkat 10, no felling since 2024, age ≥ 20) ≤ −0.10 NDVI and ≤ −0.15 NBR, with ≥ 60 %
of the interior valid. T_cut = first image cut and still cut in the next usable image. Detected = an event
overlaps the interior by ≥ 0.1 ha or ≥ 20 %.

## 2. Per-stand result (INTERPRETATION)

| kv-nog | VMD ha | interior ha | usable S2 | 05-01 cut? | T_cut (S2) | status (rule) | events overlapping (id: first after, basis, conf.) | S2-backed delay d | sheet |
|---|---|---|---|---|---|---|---|---|---|
| 79-11 | 3.7 | 2.71 | 37 | no | 2026-08-04 | DETECTED_IN_WINDOW | 29: 08-11 S1+S2 HIGH, 32: 07-09 S1 LOW, 33: 07-14 S1 LOW, 34: 07-14 S1 LOW … (+6) | -1 | stand_79-11_145858589.png |
| 69-23 | 2.27 | 1.51 | 32 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | — | NULL | stand_69-23_145858979.png |
| 68-37 | 2.13 | 1.46 | 31 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | 12: 05-15 S1 LOW, 13: 05-15 S1 LOW, 14: 05-15 S1 LOW, 15: 05-15 S1 LOW … (+4) | NULL | stand_68-37_145858961.png |
| 68-62 | 2.05 | 1.34 | 33 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | — | NULL | stand_68-62_145858959.png |
| 68-63 | 2.03 | 1.25 | 33 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | 42: 09-13 S1+S2 HIGH | NULL | stand_68-63_161887864.png |
| 68-66 | 2.03 | 1.32 | 30 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | — | NULL | stand_68-66_145858275.png |
| 68-57 | 1.97 | 1.27 | 37 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | — | NULL | stand_68-57_145858425.png |
| 68-60 | 1.95 | 1.15 | 32 | no | 2026-05-03 | NOT_DETECTED | — | NULL | stand_68-60_145858969.png |
| 91-5 | 1.7 | 0.86 | 37 | no | 2026-08-04 | DETECTED_IN_WINDOW | 29: 08-11 S1+S2 HIGH, 32: 07-09 S1 LOW, 33: 07-14 S1 LOW, 34: 07-14 S1 LOW … (+4) | 6 | stand_91-5_139102304.png |
| 68-58 | 1.64 | 0.89 | 34 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | — | NULL | stand_68-58_145858487.png |
| 1-5 | 1.54 | 0.91 | 35 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | 12: 05-15 S1 LOW, 13: 05-15 S1 LOW, 14: 05-15 S1 LOW, 15: 05-15 S1 LOW … (+6) | NULL | stand_1-5_161201304.png |
| 69-22 | 1.53 | 0.8 | 32 | no | 2026-05-03 | NOT_DETECTED | — | NULL | stand_69-22_145859059.png |
| 68-65 | 1.51 | 0.77 | 35 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | 42: 09-13 S1+S2 HIGH | NULL | stand_68-65_161887862.png |
| 91-1 | 1.34 | 0.84 | 38 | no | 2026-07-25 | DETECTED_IN_WINDOW | 29: 08-11 S1+S2 HIGH, 32: 07-09 S1 LOW, 33: 07-14 S1 LOW, 34: 07-14 S1 LOW … (+6) | 9 | stand_91-1_139102302.png |
| 68-64 | 1.24 | 0.67 | 35 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | — | NULL | stand_68-64_145859177.png |
| 68-59 | 1.12 | 0.55 | 37 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | — | NULL | stand_68-59_145858605.png |
| 68-24 | 1.06 | 0.6 | 36 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | 42: 09-13 S1+S2 HIGH | NULL | stand_68-24_145858743.png |
| 1-5 | 1.02 | 0.53 | 36 | yes | 2026-05-01 | CUT_BEFORE_WINDOW | 42: 09-13 S1+S2 HIGH | NULL | stand_1-5_144097771.png |
| 1-6 | 0.1 | 0.0 | 0 | — | NULL | TOO_SMALL | — | NULL | — |

"S2-backed delay" = first after-image of the overlapping events that contain S2, minus T_cut. The tool's JSON
also reports the delay against *any* overlapping event, including S1-only ones that start earlier (median −26 d).

**Visual check (HUMAN-style, by me, not the owner):** stands **68-60 and 69-22 are already bare on 2026-05-01**
(sheets `stand_68-60_*.png`, `stand_69-22_*.png`). The rule missed this because on 05-01 the leaf-off deciduous
reference forest has low NDVI too, so the stand-minus-reference difference stays above the threshold. They are
effectively CUT_BEFORE_WINDOW. Stand 91-1 is dark forest on 07-17 and bare on 07-25: a real in-window felling,
detected.

## 3. Metrics

| | rule as written | after the visual check of 68-60 / 69-22 |
|---|---|---|
| stands | 19 (1 TOO_SMALL, 13 CUT_BEFORE_WINDOW) | 19 (1 TOO_SMALL, 15 CUT_BEFORE_WINDOW) |
| eligible | 5 | 3 |
| detected / eligible | **3 / 5 = 0.60** (Wilson 95 %: 0.23–0.88) | **3 / 3 = 1.00** (Wilson 95 %: 0.44–1.00) |
| median detection delay (S2-backed event vs T_cut) | **6 d** (−1, 6, 9) | same |
| outside events (unreviewed, upper bound) | 16 = **4.36 / 1,000 ha** of box | — |
| outside events ≥ 50 % in VMD forest | 4 (10, 11, 44, 47); all four pre-tagged VMD_OTHER_FELLING_2025_2026; 10 and 11 have identical masks | **0 unexplained** in-forest outside events per 2,640 ha VMD land (72 % of box), pending review |
| without Oct–Apr events | recall unchanged; outside 14 = 3.81 / 1,000 ha | — |

n is tiny: the confidence intervals are wide. 15 of 18 stands were felled before May (Latvian felling is
mostly winter), so this control mainly tests summer fellings.

## 4. Events outside the 19 stands (candidates for visual review; INTERPRETATION + pre-tag, no verdict)

| event | basis | classification | conf. | first … last after | ha | in VMD forest % | pre-tag | sheet |
|---|---|---|---|---|---|---|---|---|
| 10 | S1 | POTENTIAL_FOREST_LOSS | LOW | 2026-05-15 … 2026-08-03 | 7.47 | 72 | VMD_OTHER_FELLING_2025_2026 | event_10_review.png |
| 11 | S1 | POTENTIAL_FOREST_LOSS | LOW | 2026-05-15 … 2026-08-03 | 7.47 | 72 | VMD_OTHER_FELLING_2025_2026 | event_11_review.png |
| 17 | S1+S2 | POTENTIAL_CHANGE_OUTSIDE_BOUNDARY | HIGH | 2026-06-20 … 2026-07-15 | 10.02 | 0 | — | event_17_review.png |
| 18 | S1+S2 | POTENTIAL_FOREST_LOSS | HIGH | 2026-06-22 … 2026-07-23 | 5.58 | 0 | — | event_18_review.png |
| 19 | S1+S2 | POTENTIAL_CHANGE_OUTSIDE_BOUNDARY | HIGH | 2026-06-22 … 2026-06-29 | 1.17 | 0 | — | event_19_review.png |
| 21 | S1+S2 | POTENTIAL_CHANGE_OUTSIDE_BOUNDARY | HIGH | 2026-06-25 … 2026-07-29 | 8.58 | 2 | — | event_21_review.png |
| 22 | S1+S2 | POTENTIAL_FOREST_LOSS | HIGH | 2026-06-29 … 2026-08-04 | 12.29 | 5 | — | event_22_review.png |
| 25 | S2 | POTENTIAL_FOREST_LOSS | MEDIUM | 2026-06-30 … 2026-07-12 | 1.55 | 37 | — | event_25_review.png |
| 30 | S1+S2 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | HIGH | 2026-08-14 … 2026-11-08 | 27.19 | 14 | — | event_30_review.png |
| 31 | S1+S2 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | HIGH | 2026-08-21 … 2026-11-08 | 25.98 | 6 | — | event_31_review.png |
| 43 | S1+S2 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | HIGH | 2026-08-14 … 2026-11-08 | 13.40 | 0 | — | event_43_review.png |
| 44 | S1+S2 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | HIGH | 2026-10-01 … 2026-11-02 | 42.13 | 98 | VMD_OTHER_FELLING_2025_2026 | event_44_review.png |
| 45 | S1 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | LOW | 2026-08-20 … 2026-11-08 | 12.45 | 0 | — | event_45_review.png |
| 46 | S1 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | LOW | 2026-08-31 … 2026-11-08 | 11.62 | 0 | — | event_46_review.png |
| 47 | S1+S2 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | HIGH | 2026-10-02 … 2026-11-08 | 34.66 | 73 | VMD_OTHER_FELLING_2025_2026 | event_47_review.png |
| 48 | S1 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | LOW | 2026-09-01 … 2026-11-08 | 11.57 | 0 | — | event_48_review.png |

12 of the 16 lie mostly on non-forest land (0–14 % VMD forest): fields, greenhouses, settlements. The box is a
bbox, not a forest polygon, so these are expected and not forest false positives in the operational sense.
Classification later (HUMAN): FALSE_POSITIVE / UNREGISTERED_CHANGE / REGISTERED_OTHER / UNCERTAIN.

## 5. Findings (need decisions; nothing changed after the run)

- **F1 (P1, bug in rule b, mine, 78ad69f):** a rule-b promotion always starts a new event from the oldest
  contributing anomaly instead of updating an event that already covers those pixels. Result: 39 events but
  only 34 distinct masks; event groups [10, 11] and [12–16] are identical; merged by ≥ 30 % overlap they are
  **12 change locations**, one of which holds 28 events. Stand-level recall is not affected; event counts are
  inflated. Fix: match the rule-b mask against open events first (as `_upsert_events` does) and skip
  contributors that are already PROMOTED; then re-run detection offline on a copy (0 PU).
- **F2 (classification):** 31 of 39 events are POSSIBLE_SEASONAL_OR_ENVIRONMENTAL, because the class is
  recomputed from the **latest** after-image, and events keep updating into Oct–Nov. The 3 detected summer
  fellings end up "seasonal". Proposal: classify on the onset (first after-image) month and keep the latest
  month as a separate caveat.
- **F3 (rule b is easy to meet):** 100 radar anomalies, 82 promoted. With 4 geometries × S1C/S1D (~21
  passes / 30 d), "≥ 3 anomalies on ≥ 2 orbits within 60 d" is met by most persistent field changes (mowing,
  harvest). Calibrate (e.g. require ≥ 3 distinct orbits, or a forest mask) on forest areas, not on a bbox.
- **F4 (evaluation method):** the stand-vs-reference test is unreliable in early May (leaf-off reference),
  see §2. Use an absolute bare-soil test (e.g. NDVI < 0.5 with NBR < 0.2) or evergreen-only reference
  stands for spring images.
- **F5 (coverage):** to evaluate winter fellings the window must start in January, where S2 is mostly unusable
  (snow, low sun) and only S1 helps.

## 6. Not verified

- No owner/human review of the outside events or of the stands' sheets (only my visual check).
- The VMD felling year comes from the register; actual felling dates are unknown.
- S1C vs S1D calibration offset; effect of F1–F3 fixes on the numbers.
