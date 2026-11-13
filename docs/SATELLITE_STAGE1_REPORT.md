# Satellite Monitoring — Stage 1 report (BIK-001 negative control)

Branch `feature/satellite-monitoring` (worktree `/root/wt/satellite-monitoring`, not pushed) · code at `fb0d57c` ·
report written 2026-11-10. Contains modified Copernicus Sentinel data [2026].

**Result: Stage 1 negative control FAILED.** BIK-001 is supposed to produce no change event. The backfill
produced **9 suspected change events**: 7 `POSSIBLE_SEASONAL_OR_ENVIRONMENTAL`, 1 `POTENTIAL_FOREST_LOSS`
and 1 `POTENTIAL_CHANGE_OUTSIDE_BOUNDARY`. The full time series over each event mask points to optical
artefacts (unmasked cloud edges and haze) as the cause in 8 of 9 events. Event 7 is inconclusive. Felling is
not the likely cause. Per your instruction, **nothing was tuned**. I stopped here; the options for your
decision are in §6.

Labels used throughout: **RAW** = data as delivered by Copernicus (GeoTIFF + sha256) · **PROCESSED** =
statistics computed here · **INTERPRETATION** = automated rules (suspected change only) · **HUMAN** = review.

## 1. What was approved and what was done

| item | status |
|---|---|
| Steps 1, 2, 4 of the plan | done (step 3, the positive control, is still waiting for the area from you) |
| Per-cluster matching + 1-px dilation, status tables, append-only triggers | in code (`337ad8d`, `b038c37`) |
| Seasonal caveat months Nov–Mar → **Oct–Apr** (`config.seasonal_months = [10,11,12,1,2,3,4]`) | done, `fb0d57c`; detection thresholds unchanged |
| `SAT_DATA_DIR=/root/forest_ai_satellite_data`, dir 700, DB/raster files 600 | done: dir `700`; all 214 files `600` (checked by `find ! -perm 600`, none found) |
| Credentials via `set -a; source <(grep …)` | used for the Copernicus calls; no `set -x`, no echo. I scanned the data dir, both session scratchpads and the worktree for the client-id/secret **values** (filenames printed only): **0 hits** |
| `--dry-run --discover` → S1 orbit field check → backfill only if OK | done in this order (13:18 discover, 13:20 backfill, UTC) |
| Branch pushed | **no** |

## 2. Discovery (`--dry-run --discover`, 2026-08-01 … 2026-11-10, 102 days)

- Catalog requests: 3 (the offline estimate said 2; I did not determine why there was a third).
- Discovered: **67 S1** datatakes (all "would fetch") and **60 S2** products (29 "would fetch", 31
  `SKIPPED_CLOUD` with scene cloud above `s2_max_scene_cloud_pct`, no Process request).
- Discovered estimate: 96 Process requests, 12.669 PU. The offline estimate had been 92 requests, 12.854 PU.
- The full product list with stored status is in Appendix A.

### S1 relative-orbit field check (gate)

| platform | catalog items | `sat:relative_orbit` present | derived (S1A formula) | unknown | `sat:orbit_state` present |
|---|---|---|---|---|---|
| S1A | 0 | — (no items in this window) | 0 | 0 | — |
| S1C | 34 | **34 / 34** | 0 | 0 | 34 / 34 |
| S1D | 33 | **33 / 33** | 0 | 0 | 33 / 33 |

**Gate OK:** every S1C/S1D item has the Catalog value, so no fallback grouping was needed or used. The S1A
derivation formula was never exercised. Geometries seen: ASC 58, ASC 131, DESC 80 and DESC 153. Each is
flown by both S1C and S1D (S1C and S1D share ground tracks), with 8–9 passes per platform per geometry.
Comparisons are made only within the same direction and relative orbit (`detection.same_geometry`), so S1C and
S1D passes on one track are compared with each other. That is geometrically valid, but it mixes two
instruments, and no calibration offset between them was checked.

## 3. Backfill (run #1, `BACKFILL`, 2026-11-10 13:20:07–13:20:59 UTC)

| | |
|---|---|
| status | OK, no errors, no stop reason |
| new acquisitions | 127 (S1 67 OK; S2 23 OK, 31 SKIPPED_CLOUD, 6 NO_VALID_PIXELS) |
| requests | 99 in the run (3 Catalog + 96 Process) + 3 Catalog in the dry-run = **102 total**, all HTTP 200 |
| PU | **12.672** measured (`pu_includes_estimates = 0`) |
| detections | 90 rows; change events **9** (all `SUSPECTED`, no `risk_id`, nothing written to forest_ai.db) |
| storage | `/root/forest_ai_satellite_data/satellite.db` + `satellite/1/{S1,S2,events}` |

## 4. Events (INTERPRETATION) with PROCESSED evidence

All index values are **medians over the event's own change mask**, not over the whole area. I computed them
offline from the stored RAW GeoTIFFs and checked each file's sha256 against the DB first. No new requests
were made. Each event's "before" values are the S2 baselines in `before_acq_ids`; Δ is each after-image
against the median of those baselines. Review sheets show the last S2 baseline, then every after-image
(S2 = false colour B11/B08/B04; S1 = VH dB; yellow = event mask outline; grey = invalid/SCL-masked).

### Event summary

| # | classification | conf. / evidence | basis | after window (UTC) | changed ha (in / buffer) | ctx | mask-median NDVI / NBR / NDMI: before → worst after | recovers on next clear S2? |
|---|---|---|---|---|---|---|---|---|
| 1 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | HIGH / GOOD | S1+S2 | 2026-08-14 … 2026-10-10 | 2.06 (0.91 / 1.15) | CHANGE_DURING_REGISTERED_WORK (53) | 0.815 / 0.651 / 0.370 → 0.611 / 0.457 / 0.253 (08-21) | yes (08-28 NDVI 0.866) |
| 2 | POTENTIAL_FOREST_LOSS | HIGH / LIMITED | S1+S2 | 2026-08-15 … 2026-08-19 | 1.30 (1.30 / 0.00) | UNREGISTERED_CHANGE_CANDIDATE (0) | 0.813 / 0.651 / 0.378 → 0.516 / 0.369 / 0.181 (08-19) | yes (08-21 NDVI 0.828) |
| 3 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | MEDIUM / GOOD | S2 | 2026-08-19 … 2026-10-10 | 5.14 (3.78 / 1.36) | CHANGE_DURING_REGISTERED_WORK (53) | 0.832 / 0.672 / 0.396 → 0.654 / 0.484 / 0.300 (10-10) | yes (10-18 NDVI 0.874) |
| 4 | POTENTIAL_CHANGE_OUTSIDE_BOUNDARY | MEDIUM / GOOD | S2 | 2026-08-21 … 2026-08-21 | 1.29 (0.16 / 1.13) | UNREGISTERED_CHANGE_CANDIDATE (0) | 0.822 / 0.662 / 0.393 → 0.502 / 0.380 / 0.196 (08-21) | yes (08-28 NDVI 0.854) |
| 5 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | HIGH / GOOD | S1+S2 | 2026-09-15 … 2026-11-06 | 2.40 (1.79 / 0.61) | CHANGE_DURING_REGISTERED_WORK (83) | 0.823 / 0.591 / 0.337 → 0.527 / 0.359 / 0.243 (10-10) | yes (10-18 NDVI 0.826) |
| 6 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | MEDIUM / GOOD | S2 | 2026-09-28 … 2026-11-06 | 0.79 (0.53 / 0.26) | CHANGE_DURING_REGISTERED_WORK (83) | 0.720 / 0.473 / 0.246 → 0.257 / 0.005 / -0.005 (09-28) | yes (10-03 NDVI 0.739) |
| 7 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | MEDIUM / GOOD | S1+S2 | 2026-10-03 … 2026-11-02 | 0.47 (0.47 / 0.00) | CHANGE_DURING_REGISTERED_WORK (83) | 0.763 / 0.498 / 0.300 → 0.561 / 0.227 / 0.090 (10-03) | no (10-07 NDVI 0.555) |
| 8 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | MEDIUM / GOOD | S2 | 2026-10-07 … 2026-10-07 | 4.55 (4.16 / 0.39) | UNREGISTERED_CHANGE_CANDIDATE (0) | 0.841 / 0.668 / 0.387 → 0.625 / 0.426 / 0.218 (10-07) | no (10-10 NDVI 0.684) |
| 9 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | HIGH / GOOD | S1+S2 | 2026-10-10 … 2026-10-20 | 10.91 (6.33 / 4.58) | CHANGE_DURING_REGISTERED_WORK (83) | 0.800 / 0.606 / 0.346 → 0.583 / 0.417 / 0.249 (10-10) | yes (10-18 NDVI 0.854) |

### Event #1 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL

- Detection confidence HIGH, evidence quality GOOD, sensor basis S1+S2; seasonal caveat: yes (after-image in Oct–Apr)
- Changed 2.06 ha (206 px; inside 0.91 ha, buffer 1.15 ha), 1.8 % of area, largest cluster 1.66 ha, max outside boundary 85.4 m
- Operational context: CHANGE_DURING_REGISTERED_WORK (53 registered records in window/buffer)
- Review sheet (PROCESSED; yellow = event mask outline): `/root/forest_ai_satellite_data/satellite/1/events/review/event_1_review.png`

| role | acq | sensor | sensing (UTC) | geometry | NDVI | NBR | NDMI | VH dB | VV dB | Δ vs before-median (NDVI / NBR / NDMI or VH) | quicklook |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before | 2 | S1 | 2026-08-02T16:03:28 | ASCENDING/58 | — | — | — | -11.876 | -7.903 |  | `2026-08-02_S1D_IW_GRDH_1SDV_20260802T160328_20260802T160353_003949_007286_BAB2_COG.SAFE.png` |
| before | 76 | S2 | 2026-08-14T09:54:32 | — | 0.815 | 0.662 | 0.388 | — | — |  | `2026-08-14_S2B_MSIL2A_20260814T095029_N0512_R079_T34VFJ_20260814T121106.SAFE.png` |
| before | 79 | S2 | 2026-08-19T09:54:31 | — | 0.842 | 0.651 | 0.370 | — | — |  | `2026-08-19_S2C_MSIL2A_20260819T095031_N0512_R079_T34VFJ_20260819T131410.SAFE.png` |
| before | 103 | S2 | 2026-09-28T09:54:35 | — | 0.855 | 0.676 | 0.391 | — | — |  | `2026-09-28_S2C_MSIL2A_20260928T095031_N0513_R079_T34VFJ_20260928T131313.SAFE.png` |
| before | 106 | S2 | 2026-10-03T09:54:33 | — | 0.803 | 0.615 | 0.349 | — | — |  | `2026-10-03_S2B_MSIL2A_20261003T095029_N0513_R079_T34VFJ_20261003T133632.SAFE.png` |
| before | 108 | S2 | 2026-10-07T09:44:50 | — | 0.812 | 0.620 | 0.332 | — | — |  | `2026-10-07_S2A_MSIL2A_20261007T094041_N0513_R036_T34VFJ_20261007T144706.SAFE.png` |
| after | 10 | S1 | 2026-08-14T16:03:29 | ASCENDING/58 | — | — | — | -14.59 | -8.284 | -2.714 | `2026-08-14_S1D_IW_GRDH_1SDV_20260814T160329_20260814T160354_004124_007891_CC48_COG.SAFE.png` |
| after | 80 | S2 | 2026-08-21T09:44:33 | — | 0.611 | 0.457 | 0.253 | — | — | -0.204 / -0.194 / -0.117 | `2026-08-21_S2B_MSIL2A_20260821T094029_N0512_R036_T34VFJ_20260821T115427.SAFE.png` |
| after | 110 | S2 | 2026-10-10T09:44:36 | — | 0.680 | 0.502 | 0.296 | — | — | -0.135 / -0.149 / -0.074 | `2026-10-10_S2B_MSIL2A_20261010T094029_N0513_R036_T34VFJ_20261010T133655.SAFE.png` |

Full S2 NDVI series over the event mask (median, ≥60 % of mask valid): 08-08 0.80, 08-14 0.81, 08-19 0.84, 08-21 0.61, 08-21 0.83, 08-28 0.87, 09-07 0.86, 09-15 0.85, 09-28 0.85, 10-03 0.80, 10-07 0.81, 10-10 0.68, 10-18 0.84, 10-20 0.73, 10-27 0.79, 11-06 0.80

S1 VH dB over the event mask, per geometry (min … max over Aug–Nov): A131 -13.6 … -12.2 (n=17); A58 -14.6 … -11.9 (n=17); D153 -14.2 … -13.2 (n=17); D80 -14.5 … -12.9 (n=16)

### Event #2 — POTENTIAL_FOREST_LOSS

- Detection confidence HIGH, evidence quality LIMITED, sensor basis S1+S2; seasonal caveat: no
- Changed 1.30 ha (130 px; inside 1.30 ha, buffer 0.00 ha), 2.6 % of area, largest cluster 1.30 ha, max outside boundary NULL m
- Operational context: UNREGISTERED_CHANGE_CANDIDATE (0 registered records in window/buffer)
- Review sheet (PROCESSED; yellow = event mask outline): `/root/forest_ai_satellite_data/satellite/1/events/review/event_2_review.png`

| role | acq | sensor | sensing (UTC) | geometry | NDVI | NBR | NDMI | VH dB | VV dB | Δ vs before-median (NDVI / NBR / NDMI or VH) | quicklook |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before | 3 | S1 | 2026-08-03T04:42:11 | DESCENDING/153 | — | — | — | -12.051 | -9.015 |  | `2026-08-03_S1C_IW_GRDH_1SDV_20260803T044211_20260803T044236_008826_011816_D07A_COG.SAFE.png` |
| before | 76 | S2 | 2026-08-14T09:54:32 | — | 0.813 | 0.651 | 0.378 | — | — |  | `2026-08-14_S2B_MSIL2A_20260814T095029_N0512_R079_T34VFJ_20260814T121106.SAFE.png` |
| after | 11 | S1 | 2026-08-15T04:42:12 | DESCENDING/153 | — | — | — | -14.244 | -8.058 | -2.193 | `2026-08-15_S1C_IW_GRDH_1SDV_20260815T044212_20260815T044237_009001_011DDA_5E57_COG.SAFE.png` |
| after | 79 | S2 | 2026-08-19T09:54:31 | — | 0.516 | 0.369 | 0.181 | — | — | -0.297 / -0.282 / -0.197 | `2026-08-19_S2C_MSIL2A_20260819T095031_N0512_R079_T34VFJ_20260819T131410.SAFE.png` |

Full S2 NDVI series over the event mask (median, ≥60 % of mask valid): 08-14 0.81, 08-19 0.52, 08-21 0.83, 08-21 0.82, 08-28 0.86, 09-07 0.85, 09-15 0.84, 09-28 0.85, 10-03 0.80, 10-07 0.75, 10-10 0.72, 10-18 0.85, 10-20 0.78, 10-27 0.80, 11-06 0.80

S1 VH dB over the event mask, per geometry (min … max over Aug–Nov): A131 -14.7 … -12.4 (n=17); A58 -14.1 … -12.5 (n=17); D153 -14.4 … -12.1 (n=17); D80 -14.8 … -13.1 (n=16)

### Event #3 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL

- Detection confidence MEDIUM, evidence quality GOOD, sensor basis S2; seasonal caveat: yes (after-image in Oct–Apr)
- Changed 5.14 ha (514 px; inside 3.78 ha, buffer 1.36 ha), 7.5 % of area, largest cluster 3.66 ha, max outside boundary 100.0 m
- Operational context: CHANGE_DURING_REGISTERED_WORK (53 registered records in window/buffer)
- Review sheet (PROCESSED; yellow = event mask outline): `/root/forest_ai_satellite_data/satellite/1/events/review/event_3_review.png`

| role | acq | sensor | sensing (UTC) | geometry | NDVI | NBR | NDMI | VH dB | VV dB | Δ vs before-median (NDVI / NBR / NDMI or VH) | quicklook |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before | 76 | S2 | 2026-08-14T09:54:32 | — | 0.809 | 0.668 | 0.406 | — | — |  | `2026-08-14_S2B_MSIL2A_20260814T095029_N0512_R079_T34VFJ_20260814T121106.SAFE.png` |
| before | 81 | S2 | 2026-08-21T09:54:48 | — | 0.832 | 0.681 | 0.403 | — | — |  | `2026-08-21_S2A_MSIL2A_20260821T095041_N0512_R079_T34VFJ_20260821T175657.SAFE.png` |
| before | 84 | S2 | 2026-08-28T09:44:52 | — | 0.851 | 0.672 | 0.396 | — | — |  | `2026-08-28_S2A_MSIL2A_20260828T094051_N0512_R036_T34VFJ_20260828T161023.SAFE.png` |
| before | 90 | S2 | 2026-09-07T09:44:52 | — | 0.841 | 0.672 | 0.402 | — | — |  | `2026-09-07_S2A_MSIL2A_20260907T094121_N0512_R036_T34VFJ_20260907T161656.SAFE.png` |
| before | 103 | S2 | 2026-09-28T09:54:35 | — | 0.850 | 0.678 | 0.395 | — | — |  | `2026-09-28_S2C_MSIL2A_20260928T095031_N0513_R079_T34VFJ_20260928T131313.SAFE.png` |
| before | 106 | S2 | 2026-10-03T09:54:33 | — | 0.813 | 0.633 | 0.374 | — | — |  | `2026-10-03_S2B_MSIL2A_20261003T095029_N0513_R079_T34VFJ_20261003T133632.SAFE.png` |
| before | 108 | S2 | 2026-10-07T09:44:50 | — | 0.823 | 0.639 | 0.359 | — | — |  | `2026-10-07_S2A_MSIL2A_20261007T094041_N0513_R036_T34VFJ_20261007T144706.SAFE.png` |
| after | 79 | S2 | 2026-08-19T09:54:31 | — | 0.657 | 0.571 | 0.296 | — | — | -0.175 / -0.101 / -0.100 | `2026-08-19_S2C_MSIL2A_20260819T095031_N0512_R079_T34VFJ_20260819T131410.SAFE.png` |
| after | 95 | S2 | 2026-09-15T09:44:36 | — | 0.790 | 0.616 | 0.343 | — | — | -0.042 / -0.056 / -0.053 | `2026-09-15_S2C_MSIL2A_20260915T094031_N0512_R036_T34VFJ_20260915T125911.SAFE.png` |
| after | 110 | S2 | 2026-10-10T09:44:36 | — | 0.654 | 0.484 | 0.300 | — | — | -0.178 / -0.188 / -0.096 | `2026-10-10_S2B_MSIL2A_20261010T094029_N0513_R036_T34VFJ_20261010T133655.SAFE.png` |

Full S2 NDVI series over the event mask (median, ≥60 % of mask valid): 08-04 0.79, 08-14 0.81, 08-19 0.66, 08-21 0.83, 08-21 0.83, 08-28 0.85, 09-07 0.84, 09-15 0.79, 10-03 0.81, 10-07 0.82, 10-10 0.65, 10-18 0.87, 10-20 0.80, 10-27 0.81, 11-06 0.81

S1 VH dB over the event mask, per geometry (min … max over Aug–Nov): A131 -13.6 … -12.8 (n=17); A58 -13.7 … -11.9 (n=17); D153 -14.1 … -12.8 (n=17); D80 -14.7 … -13.4 (n=16)

### Event #4 — POTENTIAL_CHANGE_OUTSIDE_BOUNDARY

- Detection confidence MEDIUM, evidence quality GOOD, sensor basis S2; seasonal caveat: no
- Changed 1.29 ha (129 px; inside 0.16 ha, buffer 1.13 ha), 0.3 % of area, largest cluster 1.29 ha, max outside boundary 98.5 m
- Operational context: UNREGISTERED_CHANGE_CANDIDATE (0 registered records in window/buffer)
- Review sheet (PROCESSED; yellow = event mask outline): `/root/forest_ai_satellite_data/satellite/1/events/review/event_4_review.png`

| role | acq | sensor | sensing (UTC) | geometry | NDVI | NBR | NDMI | VH dB | VV dB | Δ vs before-median (NDVI / NBR / NDMI or VH) | quicklook |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before | 76 | S2 | 2026-08-14T09:54:32 | — | 0.804 | 0.661 | 0.396 | — | — |  | `2026-08-14_S2B_MSIL2A_20260814T095029_N0512_R079_T34VFJ_20260814T121106.SAFE.png` |
| before | 79 | S2 | 2026-08-19T09:54:31 | — | 0.840 | 0.663 | 0.390 | — | — |  | `2026-08-19_S2C_MSIL2A_20260819T095031_N0512_R079_T34VFJ_20260819T131410.SAFE.png` |
| after | 80 | S2 | 2026-08-21T09:44:33 | — | 0.502 | 0.380 | 0.196 | — | — | -0.320 / -0.282 / -0.197 | `2026-08-21_S2B_MSIL2A_20260821T094029_N0512_R036_T34VFJ_20260821T115427.SAFE.png` |

Full S2 NDVI series over the event mask (median, ≥60 % of mask valid): 08-11 0.83, 08-14 0.80, 08-19 0.84, 08-21 0.50, 08-21 0.83, 08-28 0.85, 09-15 0.84, 09-28 0.86, 10-03 0.80, 10-07 0.82, 10-10 0.71, 10-18 0.87, 10-20 0.78, 10-27 0.81, 11-06 0.81

S1 VH dB over the event mask, per geometry (min … max over Aug–Nov): A131 -14.0 … -12.8 (n=17); A58 -14.2 … -12.0 (n=17); D153 -14.8 … -12.5 (n=17); D80 -14.2 … -12.5 (n=16)

### Event #5 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL

- Detection confidence HIGH, evidence quality GOOD, sensor basis S1+S2; seasonal caveat: yes (after-image in Oct–Apr)
- Changed 2.40 ha (240 px; inside 1.79 ha, buffer 0.61 ha), 3.5 % of area, largest cluster 1.99 ha, max outside boundary 72.8 m
- Operational context: CHANGE_DURING_REGISTERED_WORK (83 registered records in window/buffer)
- Review sheet (PROCESSED; yellow = event mask outline): `/root/forest_ai_satellite_data/satellite/1/events/review/event_5_review.png`

| role | acq | sensor | sensing (UTC) | geometry | NDVI | NBR | NDMI | VH dB | VV dB | Δ vs before-median (NDVI / NBR / NDMI or VH) | quicklook |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before | 81 | S2 | 2026-08-21T09:54:48 | — | 0.760 | 0.521 | 0.280 | — | — |  | `2026-08-21_S2A_MSIL2A_20260821T095041_N0512_R079_T34VFJ_20260821T175657.SAFE.png` |
| before | 84 | S2 | 2026-08-28T09:44:52 | — | 0.829 | 0.595 | 0.340 | — | — |  | `2026-08-28_S2A_MSIL2A_20260828T094051_N0512_R036_T34VFJ_20260828T161023.SAFE.png` |
| before | 90 | S2 | 2026-09-07T09:44:52 | — | 0.849 | 0.626 | 0.362 | — | — |  | `2026-09-07_S2A_MSIL2A_20260907T094121_N0512_R036_T34VFJ_20260907T161656.SAFE.png` |
| before | 30 | S1 | 2026-09-13T16:03:18 | ASCENDING/58 | — | — | — | -12.823 | -7.449 |  | `2026-09-13_S1C_IW_GRDH_1SDV_20260913T160318_20260913T160343_009431_012C1F_D7C6_COG.SAFE.png` |
| before | 34 | S1 | 2026-09-19T16:03:30 | ASCENDING/58 | — | — | — | -12.965 | -7.156 |  | `2026-09-19_S1D_IW_GRDH_1SDV_20260919T160330_20260919T160355_004649_008AD8_ACD2_COG.SAFE.png` |
| before | 38 | S1 | 2026-09-25T16:03:18 | ASCENDING/58 | — | — | — | -12.246 | -6.566 |  | `2026-09-25_S1C_IW_GRDH_1SDV_20260925T160318_20260925T160343_009606_0131E0_C227_COG.SAFE.png` |
| before | 103 | S2 | 2026-09-28T09:54:35 | — | NULL | NULL | NULL | — | — |  | `2026-09-28_S2C_MSIL2A_20260928T095031_N0513_R079_T34VFJ_20260928T131313.SAFE.png` |
| before | 106 | S2 | 2026-10-03T09:54:33 | — | 0.826 | 0.586 | 0.342 | — | — |  | `2026-10-03_S2B_MSIL2A_20261003T095029_N0513_R079_T34VFJ_20261003T133632.SAFE.png` |
| before | 108 | S2 | 2026-10-07T09:44:50 | — | 0.820 | 0.596 | 0.334 | — | — |  | `2026-10-07_S2A_MSIL2A_20261007T094041_N0513_R036_T34VFJ_20261007T144706.SAFE.png` |
| before | 115 | S2 | 2026-10-18T09:54:38 | — | 0.826 | 0.603 | 0.345 | — | — |  | `2026-10-18_S2C_MSIL2A_20261018T095031_N0513_R079_T34VFJ_20261018T134609.SAFE.png` |
| before | 116 | S2 | 2026-10-20T09:54:43 | — | 0.739 | 0.566 | 0.309 | — | — |  | `2026-10-20_S2A_MSIL2A_20261020T095041_N0513_R079_T34VFJ_20261020T150311.SAFE.png` |
| before | 119 | S2 | 2026-10-27T09:44:44 | — | 0.704 | 0.523 | 0.264 | — | — |  | `2026-10-27_S2A_MSIL2A_20261027T094041_N0513_R036_T34VFJ_20261027T144648.SAFE.png` |
| after | 95 | S2 | 2026-09-15T09:44:36 | — | 0.607 | 0.404 | 0.222 | — | — | -0.216 / -0.186 / -0.115 | `2026-09-15_S2C_MSIL2A_20260915T094031_N0512_R036_T34VFJ_20260915T125911.SAFE.png` |
| after | 46 | S1 | 2026-10-07T16:03:18 | ASCENDING/58 | — | — | — | -13.403 | -7.649 | -0.580 | `2026-10-07_S1C_IW_GRDH_1SDV_20261007T160318_20261007T160343_009781_0137B4_F45E_COG.SAFE.png` |
| after | 110 | S2 | 2026-10-10T09:44:36 | — | 0.527 | 0.359 | 0.243 | — | — | -0.296 / -0.232 / -0.094 | `2026-10-10_S2B_MSIL2A_20261010T094029_N0513_R036_T34VFJ_20261010T133655.SAFE.png` |
| after | 124 | S2 | 2026-11-06T09:44:43 | — | 0.662 | 0.452 | 0.212 | — | — | -0.161 / -0.139 / -0.125 | `2026-11-06_S2A_MSIL2A_20261106T094121_N0513_R036_T34VFJ_20261106T143053.SAFE.png` |

Full S2 NDVI series over the event mask (median, ≥60 % of mask valid): 08-04 0.82, 08-14 0.80, 08-19 0.84, 08-21 0.83, 08-28 0.83, 09-07 0.85, 09-15 0.61, 10-03 0.83, 10-07 0.82, 10-10 0.53, 10-18 0.83, 10-20 0.74, 10-27 0.70, 11-06 0.66

S1 VH dB over the event mask, per geometry (min … max over Aug–Nov): A131 -13.7 … -12.2 (n=17); A58 -13.5 … -12.1 (n=17); D153 -15.1 … -13.9 (n=17); D80 -15.1 … -13.6 (n=16)

### Event #6 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL

- Detection confidence MEDIUM, evidence quality GOOD, sensor basis S2; seasonal caveat: yes (after-image in Oct–Apr)
- Changed 0.79 ha (79 px; inside 0.53 ha, buffer 0.26 ha), 1.1 % of area, largest cluster 0.79 ha, max outside boundary 36.1 m
- Operational context: CHANGE_DURING_REGISTERED_WORK (83 registered records in window/buffer)
- Review sheet (PROCESSED; yellow = event mask outline): `/root/forest_ai_satellite_data/satellite/1/events/review/event_6_review.png`

| role | acq | sensor | sensing (UTC) | geometry | NDVI | NBR | NDMI | VH dB | VV dB | Δ vs before-median (NDVI / NBR / NDMI or VH) | quicklook |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before | 84 | S2 | 2026-08-28T09:44:52 | — | 0.709 | 0.478 | 0.254 | — | — |  | `2026-08-28_S2A_MSIL2A_20260828T094051_N0512_R036_T34VFJ_20260828T161023.SAFE.png` |
| before | 90 | S2 | 2026-09-07T09:44:52 | — | 0.793 | 0.504 | 0.278 | — | — |  | `2026-09-07_S2A_MSIL2A_20260907T094121_N0512_R036_T34VFJ_20260907T161656.SAFE.png` |
| before | 95 | S2 | 2026-09-15T09:44:36 | — | 0.763 | 0.499 | 0.281 | — | — |  | `2026-09-15_S2C_MSIL2A_20260915T094031_N0512_R036_T34VFJ_20260915T125911.SAFE.png` |
| before | 115 | S2 | 2026-10-18T09:54:38 | — | 0.732 | 0.468 | 0.238 | — | — |  | `2026-10-18_S2C_MSIL2A_20261018T095031_N0513_R079_T34VFJ_20261018T134609.SAFE.png` |
| before | 116 | S2 | 2026-10-20T09:54:43 | — | 0.670 | 0.403 | 0.209 | — | — |  | `2026-10-20_S2A_MSIL2A_20261020T095041_N0513_R079_T34VFJ_20261020T150311.SAFE.png` |
| before | 119 | S2 | 2026-10-27T09:44:44 | — | 0.672 | 0.390 | 0.186 | — | — |  | `2026-10-27_S2A_MSIL2A_20261027T094041_N0513_R036_T34VFJ_20261027T144648.SAFE.png` |
| after | 103 | S2 | 2026-09-28T09:54:35 | — | 0.257 | 0.005 | -0.005 | — | — | -0.463 / -0.468 / -0.251 | `2026-09-28_S2C_MSIL2A_20260928T095031_N0513_R079_T34VFJ_20260928T131313.SAFE.png` |
| after | 124 | S2 | 2026-11-06T09:44:43 | — | 0.522 | 0.321 | 0.097 | — | — | -0.198 / -0.152 / -0.149 | `2026-11-06_S2A_MSIL2A_20261106T094121_N0513_R036_T34VFJ_20261106T143053.SAFE.png` |

Full S2 NDVI series over the event mask (median, ≥60 % of mask valid): 08-04 0.77, 08-14 0.76, 08-19 0.77, 08-21 0.75, 08-21 0.53, 08-28 0.71, 09-07 0.79, 09-15 0.76, 09-28 0.26, 10-03 0.74, 10-07 0.74, 10-10 0.58, 10-18 0.73, 10-20 0.67, 10-27 0.67, 11-06 0.52

S1 VH dB over the event mask, per geometry (min … max over Aug–Nov): A131 -14.6 … -12.7 (n=17); A58 -14.9 … -11.8 (n=17); D153 -16.6 … -13.9 (n=17); D80 -16.5 … -13.4 (n=16)

### Event #7 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL

- Detection confidence MEDIUM, evidence quality GOOD, sensor basis S1+S2; seasonal caveat: yes (after-image in Oct–Apr)
- Changed 0.47 ha (47 px; inside 0.47 ha, buffer 0.00 ha), 0.9 % of area, largest cluster 0.47 ha, max outside boundary NULL m
- Operational context: CHANGE_DURING_REGISTERED_WORK (83 registered records in window/buffer)
- Review sheet (PROCESSED; yellow = event mask outline): `/root/forest_ai_satellite_data/satellite/1/events/review/event_7_review.png`

| role | acq | sensor | sensing (UTC) | geometry | NDVI | NBR | NDMI | VH dB | VV dB | Δ vs before-median (NDVI / NBR / NDMI or VH) | quicklook |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before | 90 | S2 | 2026-09-07T09:44:52 | — | 0.793 | 0.521 | 0.317 | — | — |  | `2026-09-07_S2A_MSIL2A_20260907T094121_N0512_R036_T34VFJ_20260907T161656.SAFE.png` |
| before | 95 | S2 | 2026-09-15T09:44:36 | — | 0.763 | 0.498 | 0.300 | — | — |  | `2026-09-15_S2C_MSIL2A_20260915T094031_N0512_R036_T34VFJ_20260915T125911.SAFE.png` |
| before | 103 | S2 | 2026-09-28T09:54:35 | — | 0.447 | 0.129 | 0.094 | — | — |  | `2026-09-28_S2C_MSIL2A_20260928T095031_N0513_R079_T34VFJ_20260928T131313.SAFE.png` |
| before | 44 | S1 | 2026-10-03T04:34:22 | DESCENDING/80 | — | — | — | -17.488 | -7.532 |  | `2026-10-03_S1D_IW_GRDH_1SDV_20261003T043422_20261003T043447_004846_0091BB_BEA0_COG.SAFE.png` |
| before | 48 | S1 | 2026-10-09T04:34:09 | DESCENDING/80 | — | — | — | -14.627 | -9.149 |  | `2026-10-09_S1C_IW_GRDH_1SDV_20261009T043409_20261009T043434_009803_013871_90EA_COG.SAFE.png` |
| before | 52 | S1 | 2026-10-15T04:34:22 | DESCENDING/80 | — | — | — | -14.778 | -8.706 |  | `2026-10-15_S1D_IW_GRDH_1SDV_20261015T043422_20261015T043447_005021_0097D8_5CBA_COG.SAFE.png` |
| after | 106 | S2 | 2026-10-03T09:54:33 | — | 0.561 | 0.227 | 0.090 | — | — | -0.202 / -0.271 / -0.210 | `2026-10-03_S2B_MSIL2A_20261003T095029_N0513_R079_T34VFJ_20261003T133632.SAFE.png` |
| after | 63 | S1 | 2026-11-02T04:34:09 | DESCENDING/80 | — | — | — | -17.506 | -9.899 | -2.728 | `2026-11-02_S1C_IW_GRDH_1SDV_20261102T043409_20261102T043434_010153_014440_0BD9_COG.SAFE.png` |

Full S2 NDVI series over the event mask (median, ≥60 % of mask valid): 08-04 0.57, 08-14 0.74, 08-19 0.77, 08-21 0.75, 08-21 0.68, 08-28 0.53, 09-07 0.79, 09-15 0.76, 10-03 0.56, 10-07 0.56, 10-10 0.52, 10-18 0.63, 10-20 0.57, 10-27 0.59, 11-06 0.55

S1 VH dB over the event mask, per geometry (min … max over Aug–Nov): A131 -19.9 … -16.6 (n=17); A58 -19.2 … -16.7 (n=17); D153 -17.8 … -13.6 (n=17); D80 -18.3 … -12.7 (n=16)

### Event #8 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL

- Detection confidence MEDIUM, evidence quality GOOD, sensor basis S2; seasonal caveat: yes (after-image in Oct–Apr)
- Changed 4.55 ha (455 px; inside 4.16 ha, buffer 0.39 ha), 8.2 % of area, largest cluster 3.37 ha, max outside boundary 60.0 m
- Operational context: UNREGISTERED_CHANGE_CANDIDATE (0 registered records in window/buffer)
- Review sheet (PROCESSED; yellow = event mask outline): `/root/forest_ai_satellite_data/satellite/1/events/review/event_8_review.png`

| role | acq | sensor | sensing (UTC) | geometry | NDVI | NBR | NDMI | VH dB | VV dB | Δ vs before-median (NDVI / NBR / NDMI or VH) | quicklook |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before | 95 | S2 | 2026-09-15T09:44:36 | — | 0.841 | 0.668 | 0.387 | — | — |  | `2026-09-15_S2C_MSIL2A_20260915T094031_N0512_R036_T34VFJ_20260915T125911.SAFE.png` |
| before | 103 | S2 | 2026-09-28T09:54:35 | — | 0.846 | 0.673 | 0.395 | — | — |  | `2026-09-28_S2C_MSIL2A_20260928T095031_N0513_R079_T34VFJ_20260928T131313.SAFE.png` |
| before | 106 | S2 | 2026-10-03T09:54:33 | — | 0.805 | 0.619 | 0.357 | — | — |  | `2026-10-03_S2B_MSIL2A_20261003T095029_N0513_R079_T34VFJ_20261003T133632.SAFE.png` |
| after | 108 | S2 | 2026-10-07T09:44:50 | — | 0.625 | 0.426 | 0.218 | — | — | -0.216 / -0.242 / -0.169 | `2026-10-07_S2A_MSIL2A_20261007T094041_N0513_R036_T34VFJ_20261007T144706.SAFE.png` |

Full S2 NDVI series over the event mask (median, ≥60 % of mask valid): 08-08 0.76, 08-14 0.81, 08-19 0.83, 08-21 0.82, 08-21 0.82, 08-28 0.86, 09-07 0.85, 09-15 0.84, 09-28 0.85, 10-03 0.81, 10-07 0.62, 10-10 0.68, 10-18 0.86, 10-20 0.77, 10-27 0.80, 11-06 0.81

S1 VH dB over the event mask, per geometry (min … max over Aug–Nov): A131 -14.1 … -13.0 (n=17); A58 -13.8 … -12.6 (n=17); D153 -14.3 … -12.8 (n=17); D80 -14.5 … -13.2 (n=16)

### Event #9 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL

- Detection confidence HIGH, evidence quality GOOD, sensor basis S1+S2; seasonal caveat: yes (after-image in Oct–Apr)
- Changed 10.91 ha (1091 px; inside 6.33 ha, buffer 4.58 ha), 12.5 % of area, largest cluster 6.46 ha, max outside boundary 100.0 m
- Operational context: CHANGE_DURING_REGISTERED_WORK (83 registered records in window/buffer)
- Review sheet (PROCESSED; yellow = event mask outline): `/root/forest_ai_satellite_data/satellite/1/events/review/event_9_review.png`

| role | acq | sensor | sensing (UTC) | geometry | NDVI | NBR | NDMI | VH dB | VV dB | Δ vs before-median (NDVI / NBR / NDMI or VH) | quicklook |
|---|---|---|---|---|---|---|---|---|---|---|---|
| before | 35 | S1 | 2026-09-20T04:42:13 | DESCENDING/153 | — | — | — | -14.138 | -9.355 |  | `2026-09-20_S1C_IW_GRDH_1SDV_20260920T044213_20260920T044238_009526_012F4A_01B1_COG.SAFE.png` |
| before | 39 | S1 | 2026-09-26T04:42:26 | DESCENDING/153 | — | — | — | -13.294 | -8.666 |  | `2026-09-26_S1D_IW_GRDH_1SDV_20260926T044226_20260926T044251_004744_008E16_7826_COG.SAFE.png` |
| before | 103 | S2 | 2026-09-28T09:54:35 | — | 0.843 | 0.671 | 0.392 | — | — |  | `2026-09-28_S2C_MSIL2A_20260928T095031_N0513_R079_T34VFJ_20260928T131313.SAFE.png` |
| before | 43 | S1 | 2026-10-02T04:42:13 | DESCENDING/153 | — | — | — | -14.413 | -9.06 |  | `2026-10-02_S1C_IW_GRDH_1SDV_20261002T044213_20261002T044238_009701_01351C_8A3F_COG.SAFE.png` |
| before | 106 | S2 | 2026-10-03T09:54:33 | — | 0.798 | 0.606 | 0.346 | — | — |  | `2026-10-03_S2B_MSIL2A_20261003T095029_N0513_R079_T34VFJ_20261003T133632.SAFE.png` |
| before | 108 | S2 | 2026-10-07T09:44:50 | — | 0.800 | 0.605 | 0.330 | — | — |  | `2026-10-07_S2A_MSIL2A_20261007T094041_N0513_R036_T34VFJ_20261007T144706.SAFE.png` |
| before | 110 | S2 | 2026-10-10T09:44:36 | — | 0.583 | 0.417 | 0.249 | — | — |  | `2026-10-10_S2B_MSIL2A_20261010T094029_N0513_R036_T34VFJ_20261010T133655.SAFE.png` |
| before | 115 | S2 | 2026-10-18T09:54:38 | — | 0.854 | 0.641 | 0.367 | — | — |  | `2026-10-18_S2C_MSIL2A_20261018T095031_N0513_R079_T34VFJ_20261018T134609.SAFE.png` |
| after | 110 | S2 | 2026-10-10T09:44:36 | — | 0.583 | 0.417 | 0.249 | — | — | -0.217 / -0.189 / -0.097 | `2026-10-10_S2B_MSIL2A_20261010T094029_N0513_R036_T34VFJ_20261010T133655.SAFE.png` |
| after | 51 | S1 | 2026-10-14T04:42:13 | DESCENDING/153 | — | — | — | -14.232 | -9.259 | -0.094 | `2026-10-14_S1C_IW_GRDH_1SDV_20261014T044213_20261014T044238_009876_013B09_C04B_COG.SAFE.png` |
| after | 116 | S2 | 2026-10-20T09:54:43 | — | 0.749 | 0.568 | 0.304 | — | — | -0.051 / -0.038 / -0.042 | `2026-10-20_S2A_MSIL2A_20261020T095041_N0513_R079_T34VFJ_20261020T150311.SAFE.png` |

Full S2 NDVI series over the event mask (median, ≥60 % of mask valid): 08-08 0.71, 08-11 0.82, 08-14 0.80, 08-19 0.82, 08-21 0.79, 08-21 0.82, 08-28 0.85, 09-07 0.84, 09-15 0.83, 09-28 0.84, 10-03 0.80, 10-07 0.80, 10-10 0.58, 10-18 0.85, 10-20 0.75, 10-27 0.80, 11-06 0.80

S1 VH dB over the event mask, per geometry (min … max over Aug–Nov): A131 -13.9 … -13.1 (n=17); A58 -14.0 … -12.9 (n=17); D153 -15.0 … -13.2 (n=17); D80 -14.8 … -14.0 (n=16)



## 5. Diagnosis (my reading of the evidence, not verified on the ground)

1. **Transient optical drops.** In 8 of 9 events the NDVI drop over the mask shows up on a single S2 date
   (sometimes on two hazy dates). The next clear S2 image is back at the baseline level, e.g. event 2:
   0.813 → **0.516** (08-19) → 0.828 (08-21); event 4: 0.822 → **0.502** (08-21 R036) while **the same
   day's** R079 image has 0.832 over the same mask. Felling does not recover in 2–7 days.
2. **Where the dips sit.** On the review sheets, every flagged patch lies on the rim of an SCL-masked cloud
   (events 2, 4, 8) or inside visible haze (event 9, 2026-10-10, scene cloud 76.7 %, SCL kept ~94 % of the
   area valid). SCL does not mask thin cloud, haze or cloud-edge halos, so `valid_pct` passes.
3. **The same after-images recur.** Acquisitions #79 (08-19), #80 (08-21 R036), #95 (09-15), #103 (09-28)
   and #110 (10-10) produce almost all after-image hits. Area-wide median NDVI on #110 is 0.631, against
   0.79–0.85 on the neighbouring clear dates.
4. **Why persistence did not stop it.** The S1+S2 events (1, 2, 5, 7, 9) paired an S2 dip with a single S1
   VH drop of 2.2–2.7 dB on overlapping pixels. Over these masks VH varies by roughly ±1–2.5 dB from pass to
   pass for the whole of Aug–Nov, with no step change (per-geometry ranges in §4). Events 1 and 2 also fall at
   the start of the window, where each S1 geometry had only 1–2 baseline passes. Ongoing-event matching then
   merged later, unrelated dips at the same spot into the same event, which raised its confidence to HIGH.
5. **Baselines are contaminated.** `before_acq_ids` is the union of the baselines used across all
   updates of an event. It includes hazy images and images taken after the first after-image: event 9
   lists #110 (its own first after-image) and #115. A hazy image that becomes a baseline lowers the
   reference for later comparisons.
6. **Seasonal caveat.** With Oct–Apr, every event whose last after-image is in October or later is labelled
   `POSSIBLE_SEASONAL_OR_ENVIRONMENTAL`. That label is honest, but it hides the real cause (artefacts) rather
   than rejecting it. The two events without the caveat (2, 4) are August events.
7. **Event 7 (0.47 ha) is inconclusive.** Its mask is an open/edge patch with low and unstable NDVI
   (0.52–0.79 already in Aug–Sep) and low VH (−17 to −19 dB on the ascending tracks). After 10-03 it stays
   around 0.52–0.63. That fits leaf-off or wet ground as well as anything else; I did not assess it further.

Operational context: events 1, 3, 5, 6, 7 and 9 coincide with registered field activity in BIK-001
(53–83 records). Events 2, 4 and 8 have none and are therefore labelled `UNREGISTERED_CHANGE_CANDIDATE`.
That is the label a dispatcher would act on, which is exactly the false-positive path the negative control
exists to catch.

## 6. Options for your decision (none applied; thresholds unchanged)

| option | what it changes | cost | expected effect on BIK-001 (my estimate, not re-run) |
|---|---|---|---|
| **A. Cloud-edge guard** (recommended) | Dilate SCL classes 3/8/9/10 (shadow, cloud medium/high, cirrus) by N px (e.g. 3 px = 30 m) before computing validity | none (local) | removes events 2, 4, 8 and parts of 1/3 |
| **B. Confirm-or-recover** (recommended) | A new S2-led event stays `PENDING_CONFIRMATION` until the next S2 image with ≥ 60 % of the mask valid. If dNBR is still ≤ threshold → `SUSPECTED`; if it has recovered → closed as `TRANSIENT_OPTICAL`. Recorded, never deleted | none; adds ~2–10 days of latency | removes 7 of 9 on its own (event 8: the next image #110 is itself hazy; event 7 likely stays) |
| C. Haze/scene guard | Reject an S2 after-image as a change source when the area-wide median NDVI drop exceeds a scene-level limit (e.g. > 0.08 against the baseline median), or when scene cloud is > 50 % | none | removes the #110-driven hits (3, 5, 9) |
| D. Use the CDSE cloud-probability band (CLP/CLM) in the Process evalscript | Replaces or augments SCL | +1 band per S2 request (PU change to be measured) | similar to A, more robust for haze |
| E. S1 corroboration rule | S1 counts as corroboration only with ≥ 3 same-geometry baseline passes **and** two consecutive same-geometry drops | none | removes the S1 support for events 1, 2, 7 |
| F. Clean baselines | Exclude acquisitions that triggered a detection (or failed C) from later baselines | none | prevents baseline contamination (finding 5) |

My recommendation is **A + B + F**, then re-run detection **offline** on the stored rasters (no new
Copernicus requests and no extra PU), then do the positive control. B is the change that matters most;
A and F reduce noise around it.

## 7. Environment issue found while writing this report (not fixed)

At **2026-11-10 13:22 UTC**, two minutes after the backfill, `aider-chat` 0.86.2 was installed into
**system** Python (`/usr/local/lib/python3.12/dist-packages`). This downgraded system **numpy to 1.26.4**,
and pip now also reports `transformers` incompatible with the installed `huggingface-hub`/`tokenizers`. The worker venv
`/root/forest_ai_satellite_venv` uses `--system-site-packages`, and tifffile 2026.11.8 needs numpy ≥ 2.1.
**Every stored GeoTIFF now fails to decode** (`TypeError: 'copy' is an invalid keyword argument`), so
the next worker run would fail at decode. For this report I put numpy 2.2.6 in a scratchpad-only path
(`PYTHONPATH`); I changed nothing in system Python or in the venv.
Proposed fix (needs your OK): pin `numpy==2.2.6` **inside** the worker venv so it no longer depends on
system numpy. I did not check whether the 13:22 install affects the :8000 API or the bot.

## 8. Not done / open

- Step 3 (positive control) is waiting for the area from you.
- No `risk` rows, no Telegram messages and no writes to `forest_ai.db`. The satellite DB is separate.
- The analysis scripts used for §4 are not committed. They are in the session scratchpad
  (`event_evidence.py`, `event_series.py`); I can add them to the repo as `satellite_monitoring/evidence.py`
  if you want this kept reproducible.
- Review sheets: `/root/forest_ai_satellite_data/satellite/1/events/review/event_<n>_review.png` (600).

### Open calibration items (recorded 2026-11-11; nothing changed)

- **C1: uniform drop (G) vs. near-total clear-cut of a small area.** G marks an S2 image as
  `UNIFORM_DROP_ATMOSPHERIC` when at least 60 % of the comparable pixels (INSIDE + BUFFER) pass the change rule
  and std(dNDVI) ≤ 0.10 (`uniform_drop_min_fraction`, `uniform_drop_max_std_dndvi`). A small area felled almost
  completely, buffer included, has the same signature, and G would hide it. G uses NDVI only, so it cannot
  tell the two apart. A possible separator to test: haze and thin cloud raise blue reflectance (B02) across
  the scene, while a fresh cut raises SWIR (B11/B12) on the cut pixels. B11/B12 are already stored. B02 is
  **not** requested (the evalscript asks for B04, B08, B11, B12, SCL and dataMask), so a B02 test needs an
  evalscript change, and the PU per S2 request rises from 5/3 to 6/3 band factor. Calibrate on the Ķekava positive
  control (19 VMD 2026 clear-cuts) and the BIK-001 negative control before any threshold or rule change.
  Note: in the BIK-001 offline re-run of 2026-11-11, G never triggered (highest drop fraction 0.358,
  on 2026-10-10).

## 9. Offline re-run 2026-11-11 (A/B/F/G + RADAR_ANOMALY rule)

**How:** code at the commit that adds this section (`fde1302` A/B/F/G, the S1 RADAR_ANOMALY rule, venv2).
Detection was re-run on a **scratch copy**. A fresh DB was built in the session scratchpad from the 127 stored
acquisitions of run #1. The stored RAW GeoTIFFs were sha256-checked, and the provider refuses any network
call. Result: **0 requests, 0 PU, no errors**. The live `satellite.db` still holds the run #1 detections
and the 9 events of §4; it was not modified.

**Result:** 2 suspected events, both S2-only and both `POSSIBLE_SEASONAL_OR_ENVIRONMENTAL`. There are 0 S1
events. The 5 S1-only drops are now `RADAR_ANOMALY` rows and none is promoted. 10 S2 candidates: 7
`TRANSIENT`, 2 `CONFIRMED` (both into event 1) and 1 still `PENDING_CONFIRMATION` (11-06).

**HUMAN decision (2026-11-11):** both events are accepted as seasonal. No risk is created. The evidence below
is attached so that a human can verify it.

| # | classification | conf. / evidence | basis | after window (UTC) | changed ha (in / buffer) | ctx | S2 confirmation |
|---|---|---|---|---|---|---|---|
| 1 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | MEDIUM / LIMITED | S2 | 2026-10-20 … 2026-11-06 | 2.99 (2.99 / 0.00) | CHANGE_DURING_REGISTERED_WORK | cand. 8 (10-20) confirmed by 10-27, 57 % persist; cand. 9 (10-27) confirmed by 11-06, 96 % |
| 2 | POSSIBLE_SEASONAL_OR_ENVIRONMENTAL | MEDIUM / LIMITED | S2 | 2026-10-27 … 2026-11-06 | 1.16 (0.76 / 0.40) | CHANGE_DURING_REGISTERED_WORK | clusters of cand. 9 not matching event 1 |

Both events are at mostly new locations: only 17 of event 1's 299 pixels overlap the §4 events.

**Review sheets** (PROCESSED, false colour B11/B08/B04, yellow = event mask outline, grey = invalid; file
mode 600): `/root/forest_ai_satellite_data/satellite/1/events/review_rerun_20261111/event_{1,2}_review.png`.
Tiles: `baseline` (last S2 baseline, #90 09-07, cloud-masked over the event), `last clear` (latest S2 that is
usable over the mask), then every `after` image.

**My reading (INTERPRETATION, not a decision):**
- **Event 1 should be checked by a human before the "seasonal" label is relied on.**
  - From 10-20 a compact brown patch appears inside the outline. In this false colour that is the
    bare-soil / clear-cut colour, and it is not a uniform fade.
  - The context is CHANGE_DURING_REGISTERED_WORK.
  - Against that, S1 VH over the same mask shows no drop: it stays at −14.8 … −12.4 dB on all four
    geometries from August to November. A clear-cut usually lowers VH by ≥ 2 dB.
  - So: a thinning or small local clearing, or seasonal. I cannot tell which from these images.
- **Event 2:** thin linear clusters along a ditch/track and a field edge. This is consistent with edge
  senescence.

Per-event S2 medians over the event mask (NULL = < 60 % of the mask valid after the 3-px cloud dilation):

| date | acq | mask valid % | ev 1 NDVI | ev 1 NBR | ev 1 NDMI | ev 2 NDVI | ev 2 NBR | ev 2 NDMI |
|---|---|---|---|---|---|---|---|---|
| 2026-08-14 | 76 | 100 / 100 | 0.845 | 0.676 | 0.396 | 0.829 | 0.637 | 0.353 |
| 2026-08-19 | 79 | 2 / 100 | NULL | NULL | NULL | 0.864 | 0.643 | 0.349 |
| 2026-08-21 | 80 | 100 / 100 | 0.861 | 0.678 | 0.392 | 0.804 | 0.610 | 0.331 |
| 2026-08-21 | 81 | 74 / 61 | 0.867 | 0.689 | 0.396 | 0.836 | 0.623 | 0.334 |
| 2026-08-28 | 84 | 100 / 100 | 0.880 | 0.670 | 0.376 | 0.876 | 0.639 | 0.343 |
| 2026-09-07 | 90 | 20 / 74 | NULL | NULL | NULL | 0.861 | 0.622 | 0.329 |
| 2026-09-15 | 95 | 100 / 100 | 0.853 | 0.637 | 0.339 | 0.857 | 0.631 | 0.336 |
| 2026-09-28 | 103 | 99 / 71 | 0.859 | 0.639 | 0.335 | 0.870 | 0.665 | 0.361 |
| 2026-10-03 | 106 | 100 / 100 | 0.806 | 0.582 | 0.294 | 0.794 | 0.562 | 0.282 |
| 2026-10-07 | 108 | 100 / 100 | 0.781 | 0.559 | 0.263 | 0.769 | 0.514 | 0.235 |
| 2026-10-10 | 110 | 100 / 100 | 0.654 | 0.492 | 0.249 | 0.594 | 0.413 | 0.218 |
| 2026-10-18 | 115 | 100 / 100 | 0.765 | 0.532 | 0.245 | 0.730 | 0.468 | 0.194 |
| 2026-10-20 | 116 | 98 / 83 | 0.670 | 0.489 | 0.201 | 0.634 | 0.459 | 0.192 |
| 2026-10-27 | 119 | 100 / 100 | 0.631 | 0.427 | 0.153 | 0.600 | 0.393 | 0.116 |
| 2026-11-06 | 124 | 100 / 100 | 0.597 | 0.388 | 0.110 | 0.607 | 0.339 | 0.085 |

S2 images where both masks are < 60 % valid (08-04, 08-08, 08-11, 08-24, 08-26, 09-03, 09-27, 10-10 #111) are
left out.

Radar anomalies (S1-only, two consecutive same-geometry drops). None is promoted:
- rule a: no S2-backed event overlaps them within 24 days;
- rule b: no pixels drop in ≥ 3 anomalies on ≥ 2 geometries.

| # | S1 image (UTC) | geometry | ha | status |
|---|---|---|---|---|
| 1 | 2026-08-14 16:03 | ASCENDING/58 | 0.79 | RADAR_ANOMALY |
| 2 | 2026-08-15 04:42 | DESCENDING/153 | 0.38 | RADAR_ANOMALY |
| 3 | 2026-10-07 16:03 | ASCENDING/58 | 0.31 | RADAR_ANOMALY |
| 4 | 2026-10-14 04:42 | DESCENDING/153 | 0.32 | RADAR_ANOMALY |
| 5 | 2026-11-02 04:34 | DESCENDING/80 | 0.32 | RADAR_ANOMALY |

The series and sheets were produced with `satellite_monitoring/evidence.py` (`event_review`).

## 10. Offline re-run after the Ķekava fixes F1–F4 (2026-11-11)

**Code:** `4853cc0`. The fixes are described in `docs/SATELLITE_POSITIVE_CONTROL_KEKAVA.md` §5/§7:
- **F1:** rule b deduplicated.
- **F2:** class decided on the onset month.
- **F3:** VMD forest mask, and rule b needs ≥ 3 distinct relative orbits.
- **F4:** evaluation only, not used for BIK-001.

**How:**
- Same method as §9, on a **copy** of the live `satellite.db` (sha256 `9ce79c76…`, unchanged).
- Two fresh DBs over the same 127 stored acquisitions: **before** = `ae6bdfa` (the §9 code plus EVAL_BBOX and
  the evaluation module), **after** = `4853cc0`.
- 0 requests, 0 PU, 0 errors. The before run reproduces §9 exactly.

**Forest mask, BIK-001** (PROCESSED):
- 114 VMD compartments, all zkat 10.
- Forest share: inside 0.783, buffer 0.618. **Non-forest share of INSIDE+BUFFER: 0.283** (stored in
  `sat_area_masks`).
- 5,970 pixels analysed.

| | before (`ae6bdfa`, = §9) | after (`4853cc0`) |
|---|---|---|
| events | 2 | **0** |
| distinct change locations | 2 | 0 |
| classifications | SEASONAL 2 | — |
| outside events (POTENTIAL_CHANGE_OUTSIDE_BOUNDARY) | 0 | 0 |
| radar anomalies (promoted) | 5 (0) | 3 (0) |
| S2 candidates CONFIRMED / PENDING / TRANSIENT | 2 / 1 / 7 | 0 / 0 / 6 |
| detections CANDIDATE_BELOW_MIN | 6 | 17 |

**Why the two seasonal events disappear (PROCESSED, checked on the copies):**
- 111 of event 1's 299 pixels (37 %) and 65 of event 2's 116 pixels (56 %) lie outside VMD compartments. They
  are no longer analysed.
- With the mask, the 10-20 change shrinks to 126 px (candidate 6). On 10-27 its persistence is **0.0** →
  TRANSIENT. The persistent part of the old candidate 8 (57 %) was on non-forest land.
- The 10-27 and 11-06 changes break into clusters below `min_cluster_ha` 0.3 ha (largest 0.17 and 0.29 ha) →
  CANDIDATE_BELOW_MIN, so no candidate is created.

BIK-001 is the negative control (no felling expected), so 0 events is the expected direction.

**Per stand / per event:** BIK-001 has no ground-truth stands. The before/after per-event rows are in
`/root/forest_ai_satellite_data/eval/rerun_f1f4_{before,after}_20261111.json` (`summary."1"`).

**Not verified:**
- The masked-out pixels were not visually confirmed as non-forest. The VMD register snapshot is 2026-10-07.
- The §9 HUMAN decision (both events seasonal) still stands. The re-run does not replace it.
- The masking cuts clusters at the forest edge. Here that removed small clusters (0.17 / 0.29 ha), and it
  could also hide a small felling at a stand edge. Not measured.

## 11. F6 offline re-run (2026-11-11)

Same copy and method as §10. **before** = `4853cc0`, **after** = `a6079d3` (F6: event area = current mask, see
`docs/SATELLITE_POSITIVE_CONTROL_KEKAVA.md` §8). 0 requests, 0 PU, 0 errors.

| | before (`4853cc0`) | after F6 (`a6079d3`) |
|---|---|---|
| events | 0 | 0 |
| outside events | 0 | 0 |
| radar anomalies (promoted) | 3 (0) | 3 (0) |
| S2 candidates TRANSIENT | 6 | 6 |

F6 changes only existing events, and BIK-001 has none after F3, so nothing changes here. There are no event
areas and no per-stand table (no ground-truth stands). The live `satellite.db` was not modified: the Ķekava
outside-event count is worse after F6, so the owner's condition for the live re-run is not met.

## Appendix A — product list (Catalog discovery 2026-08-01 … 2026-11-10, stored status)

| acq | sensor | platform | sensing (UTC) | orbit / rel. orbit | scene cloud % | status |
|---|---|---|---|---|---|---|
| 68 | S2 | sentinel-2b | 2026-08-01T09:44:37 | — | 99.7 | SKIPPED_CLOUD |
| 69 | S2 | sentinel-2a | 2026-08-01T09:54:52 | — | 98.1 | SKIPPED_CLOUD |
| 1 | S1 | sentinel-1c | 2026-08-01T16:11:22 | ASCENDING / 131 | — | OK |
| 2 | S1 | sentinel-1d | 2026-08-02T16:03:28 | ASCENDING / 58 | — | OK |
| 3 | S1 | sentinel-1c | 2026-08-03T04:42:11 | DESCENDING / 153 | — | OK |
| 4 | S1 | sentinel-1d | 2026-08-04T04:34:20 | DESCENDING / 80 | — | OK |
| 70 | S2 | sentinel-2b | 2026-08-04T09:54:34 | — | 17.3 | OK |
| 71 | S2 | sentinel-2c | 2026-08-06T09:44:38 | — | 96.2 | SKIPPED_CLOUD |
| 5 | S1 | sentinel-1d | 2026-08-07T16:11:34 | ASCENDING / 131 | — | OK |
| 72 | S2 | sentinel-2a | 2026-08-08T09:44:54 | — | 56.2 | OK |
| 6 | S1 | sentinel-1c | 2026-08-08T16:03:16 | ASCENDING / 58 | — | OK |
| 7 | S1 | sentinel-1d | 2026-08-09T04:42:24 | DESCENDING / 153 | — | OK |
| 73 | S2 | sentinel-2c | 2026-08-09T09:54:34 | — | 28.8 | NO_VALID_PIXELS |
| 8 | S1 | sentinel-1c | 2026-08-10T04:34:08 | DESCENDING / 80 | — | OK |
| 74 | S2 | sentinel-2b | 2026-08-11T09:44:36 | — | 40.4 | NO_VALID_PIXELS |
| 75 | S2 | sentinel-2a | 2026-08-11T09:54:50 | — | 35.7 | OK |
| 9 | S1 | sentinel-1c | 2026-08-13T16:11:23 | ASCENDING / 131 | — | OK |
| 76 | S2 | sentinel-2b | 2026-08-14T09:54:32 | — | 48.6 | OK |
| 10 | S1 | sentinel-1d | 2026-08-14T16:03:29 | ASCENDING / 58 | — | OK |
| 11 | S1 | sentinel-1c | 2026-08-15T04:42:12 | DESCENDING / 153 | — | OK |
| 12 | S1 | sentinel-1d | 2026-08-16T04:34:21 | DESCENDING / 80 | — | OK |
| 77 | S2 | sentinel-2c | 2026-08-16T09:44:35 | — | 89.4 | SKIPPED_CLOUD |
| 78 | S2 | sentinel-2a | 2026-08-18T09:44:52 | — | 99.1 | SKIPPED_CLOUD |
| 79 | S2 | sentinel-2c | 2026-08-19T09:54:31 | — | 13.7 | OK |
| 13 | S1 | sentinel-1d | 2026-08-19T16:11:35 | ASCENDING / 131 | — | OK |
| 14 | S1 | sentinel-1c | 2026-08-20T16:03:17 | ASCENDING / 58 | — | OK |
| 15 | S1 | sentinel-1d | 2026-08-21T04:42:25 | DESCENDING / 153 | — | OK |
| 80 | S2 | sentinel-2b | 2026-08-21T09:44:33 | — | 50.2 | OK |
| 81 | S2 | sentinel-2a | 2026-08-21T09:54:48 | — | 52.5 | OK |
| 16 | S1 | sentinel-1c | 2026-08-22T04:34:08 | DESCENDING / 80 | — | OK |
| 82 | S2 | sentinel-2b | 2026-08-24T09:54:30 | — | 60.9 | OK |
| 17 | S1 | sentinel-1c | 2026-08-25T16:11:23 | ASCENDING / 131 | — | OK |
| 83 | S2 | sentinel-2c | 2026-08-26T09:44:35 | — | 42.8 | OK |
| 18 | S1 | sentinel-1d | 2026-08-26T16:03:30 | ASCENDING / 58 | — | OK |
| 19 | S1 | sentinel-1c | 2026-08-27T04:42:12 | DESCENDING / 153 | — | OK |
| 20 | S1 | sentinel-1d | 2026-08-28T04:34:22 | DESCENDING / 80 | — | OK |
| 84 | S2 | sentinel-2a | 2026-08-28T09:44:52 | — | 41.7 | OK |
| 85 | S2 | sentinel-2c | 2026-08-29T09:54:31 | — | 100.0 | SKIPPED_CLOUD |
| 86 | S2 | sentinel-2b | 2026-08-31T09:44:34 | — | 75.3 | NO_VALID_PIXELS |
| 87 | S2 | sentinel-2a | 2026-08-31T09:54:49 | — | 77.4 | NO_VALID_PIXELS |
| 21 | S1 | sentinel-1d | 2026-08-31T16:11:35 | ASCENDING / 131 | — | OK |
| 22 | S1 | sentinel-1c | 2026-09-01T16:03:17 | ASCENDING / 58 | — | OK |
| 23 | S1 | sentinel-1d | 2026-09-02T04:42:25 | DESCENDING / 153 | — | OK |
| 24 | S1 | sentinel-1c | 2026-09-03T04:34:09 | DESCENDING / 80 | — | OK |
| 88 | S2 | sentinel-2b | 2026-09-03T09:54:31 | — | 47.6 | OK |
| 89 | S2 | sentinel-2c | 2026-09-05T09:44:35 | — | 95.8 | SKIPPED_CLOUD |
| 25 | S1 | sentinel-1c | 2026-09-06T16:11:24 | ASCENDING / 131 | — | OK |
| 90 | S2 | sentinel-2a | 2026-09-07T09:44:52 | — | 31.1 | OK |
| 26 | S1 | sentinel-1d | 2026-09-07T16:03:30 | ASCENDING / 58 | — | OK |
| 27 | S1 | sentinel-1c | 2026-09-08T04:42:12 | DESCENDING / 153 | — | OK |
| 91 | S2 | sentinel-2c | 2026-09-08T09:54:31 | — | 91.6 | SKIPPED_CLOUD |
| 28 | S1 | sentinel-1d | 2026-09-09T04:34:22 | DESCENDING / 80 | — | OK |
| 92 | S2 | sentinel-2b | 2026-09-10T09:44:34 | — | 92.4 | SKIPPED_CLOUD |
| 93 | S2 | sentinel-2a | 2026-09-10T09:54:48 | — | 91.4 | SKIPPED_CLOUD |
| 29 | S1 | sentinel-1d | 2026-09-12T16:11:36 | ASCENDING / 131 | — | OK |
| 94 | S2 | sentinel-2b | 2026-09-13T09:54:30 | — | 100.0 | SKIPPED_CLOUD |
| 30 | S1 | sentinel-1c | 2026-09-13T16:03:18 | ASCENDING / 58 | — | OK |
| 31 | S1 | sentinel-1d | 2026-09-14T04:42:26 | DESCENDING / 153 | — | OK |
| 32 | S1 | sentinel-1c | 2026-09-15T04:34:09 | DESCENDING / 80 | — | OK |
| 95 | S2 | sentinel-2c | 2026-09-15T09:44:36 | — | 35.1 | OK |
| 96 | S2 | sentinel-2a | 2026-09-17T09:44:50 | — | 93.2 | SKIPPED_CLOUD |
| 97 | S2 | sentinel-2c | 2026-09-18T09:54:33 | — | 98.1 | SKIPPED_CLOUD |
| 33 | S1 | sentinel-1c | 2026-09-18T16:11:24 | ASCENDING / 131 | — | OK |
| 34 | S1 | sentinel-1d | 2026-09-19T16:03:30 | ASCENDING / 58 | — | OK |
| 35 | S1 | sentinel-1c | 2026-09-20T04:42:13 | DESCENDING / 153 | — | OK |
| 98 | S2 | sentinel-2b | 2026-09-20T09:44:36 | — | 90.1 | SKIPPED_CLOUD |
| 99 | S2 | sentinel-2a | 2026-09-20T09:54:47 | — | 81.4 | SKIPPED_CLOUD |
| 36 | S1 | sentinel-1d | 2026-09-21T04:34:22 | DESCENDING / 80 | — | OK |
| 100 | S2 | sentinel-2b | 2026-09-23T09:54:33 | — | 99.8 | SKIPPED_CLOUD |
| 37 | S1 | sentinel-1d | 2026-09-24T16:11:36 | ASCENDING / 131 | — | OK |
| 101 | S2 | sentinel-2c | 2026-09-25T09:44:38 | — | 100.0 | SKIPPED_CLOUD |
| 38 | S1 | sentinel-1c | 2026-09-25T16:03:18 | ASCENDING / 58 | — | OK |
| 39 | S1 | sentinel-1d | 2026-09-26T04:42:26 | DESCENDING / 153 | — | OK |
| 40 | S1 | sentinel-1c | 2026-09-27T04:34:09 | DESCENDING / 80 | — | OK |
| 102 | S2 | sentinel-2a | 2026-09-27T09:44:51 | — | 52.4 | OK |
| 103 | S2 | sentinel-2c | 2026-09-28T09:54:35 | — | 9.5 | OK |
| 104 | S2 | sentinel-2b | 2026-09-30T09:44:37 | — | 100.0 | SKIPPED_CLOUD |
| 105 | S2 | sentinel-2a | 2026-09-30T09:54:47 | — | 100.0 | SKIPPED_CLOUD |
| 41 | S1 | sentinel-1c | 2026-09-30T16:11:24 | ASCENDING / 131 | — | OK |
| 42 | S1 | sentinel-1d | 2026-10-01T16:03:30 | ASCENDING / 58 | — | OK |
| 43 | S1 | sentinel-1c | 2026-10-02T04:42:13 | DESCENDING / 153 | — | OK |
| 44 | S1 | sentinel-1d | 2026-10-03T04:34:22 | DESCENDING / 80 | — | OK |
| 106 | S2 | sentinel-2b | 2026-10-03T09:54:33 | — | 65.9 | OK |
| 107 | S2 | sentinel-2c | 2026-10-05T09:44:39 | — | 100.0 | SKIPPED_CLOUD |
| 45 | S1 | sentinel-1d | 2026-10-06T16:11:36 | ASCENDING / 131 | — | OK |
| 108 | S2 | sentinel-2a | 2026-10-07T09:44:50 | — | 12.1 | OK |
| 46 | S1 | sentinel-1c | 2026-10-07T16:03:18 | ASCENDING / 58 | — | OK |
| 47 | S1 | sentinel-1d | 2026-10-08T04:42:26 | DESCENDING / 153 | — | OK |
| 109 | S2 | sentinel-2c | 2026-10-08T09:54:35 | — | 88.4 | SKIPPED_CLOUD |
| 48 | S1 | sentinel-1c | 2026-10-09T04:34:09 | DESCENDING / 80 | — | OK |
| 110 | S2 | sentinel-2b | 2026-10-10T09:44:36 | — | 76.7 | OK |
| 111 | S2 | sentinel-2a | 2026-10-10T09:54:46 | — | 80.0 | OK |
| 49 | S1 | sentinel-1c | 2026-10-12T16:11:24 | ASCENDING / 131 | — | OK |
| 112 | S2 | sentinel-2b | 2026-10-13T09:54:33 | — | 99.4 | SKIPPED_CLOUD |
| 50 | S1 | sentinel-1d | 2026-10-13T16:03:30 | ASCENDING / 58 | — | OK |
| 51 | S1 | sentinel-1c | 2026-10-14T04:42:13 | DESCENDING / 153 | — | OK |
| 52 | S1 | sentinel-1d | 2026-10-15T04:34:22 | DESCENDING / 80 | — | OK |
| 113 | S2 | sentinel-2c | 2026-10-15T09:44:38 | — | 98.8 | SKIPPED_CLOUD |
| 114 | S2 | sentinel-2a | 2026-10-17T09:44:48 | — | 79.2 | NO_VALID_PIXELS |
| 115 | S2 | sentinel-2c | 2026-10-18T09:54:38 | — | 8.3 | OK |
| 53 | S1 | sentinel-1d | 2026-10-18T16:11:36 | ASCENDING / 131 | — | OK |
| 54 | S1 | sentinel-1c | 2026-10-19T16:03:18 | ASCENDING / 58 | — | OK |
| 55 | S1 | sentinel-1d | 2026-10-20T04:42:26 | DESCENDING / 153 | — | OK |
| 116 | S2 | sentinel-2a | 2026-10-20T09:54:43 | — | 50.1 | OK |
| 56 | S1 | sentinel-1c | 2026-10-21T04:34:09 | DESCENDING / 80 | — | OK |
| 117 | S2 | sentinel-2b | 2026-10-23T09:54:34 | — | 100.0 | SKIPPED_CLOUD |
| 57 | S1 | sentinel-1c | 2026-10-24T16:11:23 | ASCENDING / 131 | — | OK |
| 118 | S2 | sentinel-2c | 2026-10-25T09:44:36 | — | 86.0 | SKIPPED_CLOUD |
| 58 | S1 | sentinel-1d | 2026-10-25T16:03:30 | ASCENDING / 58 | — | OK |
| 59 | S1 | sentinel-1c | 2026-10-26T04:42:12 | DESCENDING / 153 | — | OK |
| 119 | S2 | sentinel-2a | 2026-10-27T09:44:44 | — | 21.7 | OK |
| 120 | S2 | sentinel-2c | 2026-10-28T09:54:32 | — | 93.6 | SKIPPED_CLOUD |
| 121 | S2 | sentinel-2b | 2026-10-30T09:44:38 | — | 99.8 | SKIPPED_CLOUD |
| 122 | S2 | sentinel-2a | 2026-10-30T09:54:40 | — | 99.9 | SKIPPED_CLOUD |
| 60 | S1 | sentinel-1d | 2026-10-30T16:11:36 | ASCENDING / 131 | — | OK |
| 61 | S1 | sentinel-1c | 2026-10-31T16:03:17 | ASCENDING / 58 | — | OK |
| 62 | S1 | sentinel-1d | 2026-11-01T04:42:25 | DESCENDING / 153 | — | OK |
| 63 | S1 | sentinel-1c | 2026-11-02T04:34:09 | DESCENDING / 80 | — | OK |
| 123 | S2 | sentinel-2c | 2026-11-04T09:44:33 | — | 54.6 | NO_VALID_PIXELS |
| 64 | S1 | sentinel-1c | 2026-11-05T16:11:24 | ASCENDING / 131 | — | OK |
| 124 | S2 | sentinel-2a | 2026-11-06T09:44:43 | — | 54.5 | OK |
| 65 | S1 | sentinel-1d | 2026-11-06T16:03:30 | ASCENDING / 58 | — | OK |
| 66 | S1 | sentinel-1c | 2026-11-07T04:42:12 | DESCENDING / 153 | — | OK |
| 125 | S2 | sentinel-2c | 2026-11-07T09:54:29 | — | 92.6 | SKIPPED_CLOUD |
| 67 | S1 | sentinel-1d | 2026-11-08T04:34:22 | DESCENDING / 80 | — | OK |
| 126 | S2 | sentinel-2b | 2026-11-09T09:44:38 | — | 100.0 | SKIPPED_CLOUD |
| 127 | S2 | sentinel-2a | 2026-11-09T09:54:39 | — | 100.0 | SKIPPED_CLOUD |

## Appendix B — generated timeline (`python -m satellite_monitoring.report --area BIK-001`)

### Satellite monitoring — BIK-001 (area #1)

Source: SECTOR · ref 26 · 50.49 ha · buffer 100 m · active=1 · added 2026-11-10T13:20:07Z by cli:stage1-negative-control

Labels: **RAW** = data as delivered by Copernicus (GeoTIFF + sha256) · **PROCESSED** = statistics computed here · **INTERPRETATION** = automated rules (suspected change only) · **HUMAN** = review decisions.

Contains modified Copernicus Sentinel data [2026].


### S2 timeline (60 acquisitions) — PROCESSED

| sensing (UTC) | status | scene cloud % | valid % in / buf | NDVI med | NBR med | NDMI med | detection |
|---|---|---|---|---|---|---|---|
| 2026-08-01T09:44:37.95Z | SKIPPED_CLOUD | 99.7 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 99.7%)) | NULL (SKIPPED_CLOUD (scene 99.7%)) | NULL (SKIPPED_CLOUD (scene 99.7%)) | — |
| 2026-08-01T09:54:52.004Z | SKIPPED_CLOUD | 98.1 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 98.1%)) | NULL (SKIPPED_CLOUD (scene 98.1%)) | NULL (SKIPPED_CLOUD (scene 98.1%)) | — |
| 2026-08-04T09:54:34.136Z | OK | 17.3 | 48.5 / 52.4 | 0.788 | 0.612 | 0.364 | NOT_USABLE |
| 2026-08-06T09:44:38.05Z | SKIPPED_CLOUD | 96.2 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 96.2%)) | NULL (SKIPPED_CLOUD (scene 96.2%)) | NULL (SKIPPED_CLOUD (scene 96.2%)) | — |
| 2026-08-08T09:44:54.581Z | OK | 56.2 | 25.9 / 36.8 | 0.745 | 0.670 | 0.405 | NOT_USABLE |
| 2026-08-09T09:54:34.02Z | NO_VALID_PIXELS | 28.8 | 0.0 / 0.0 | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | — |
| 2026-08-11T09:44:36.21Z | NO_VALID_PIXELS | 40.4 | 0.0 / 0.0 | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | — |
| 2026-08-11T09:54:50.657Z | OK | 35.7 | 27.9 / 33.5 | 0.824 | 0.706 | 0.437 | NOT_USABLE |
| 2026-08-14T09:54:32.097Z | OK | 48.6 | 99.8 / 99.9 | 0.806 | 0.649 | 0.382 | NO_BASELINE |
| 2026-08-16T09:44:35.734Z | SKIPPED_CLOUD | 89.4 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 89.4%)) | NULL (SKIPPED_CLOUD (scene 89.4%)) | NULL (SKIPPED_CLOUD (scene 89.4%)) | — |
| 2026-08-18T09:44:52.571Z | SKIPPED_CLOUD | 99.1 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 99.1%)) | NULL (SKIPPED_CLOUD (scene 99.1%)) | NULL (SKIPPED_CLOUD (scene 99.1%)) | — |
| 2026-08-19T09:54:31.401Z | OK | 13.7 | 79.1 / 82.6 | 0.823 | 0.632 | 0.359 | EVENT_CREATED → event #2 |
| 2026-08-21T09:44:33.821Z | OK | 50.2 | 98.1 / 87.1 | 0.817 | 0.652 | 0.379 | EVENT_CREATED → event #1 |
| 2026-08-21T09:54:48.868Z | OK | 52.5 | 86.2 / 87.1 | 0.824 | 0.657 | 0.375 | CANDIDATE_BELOW_MIN |
| 2026-08-24T09:54:30.856Z | OK | 60.9 | 1.3 / 1.2 | 0.400 | 0.358 | 0.230 | NOT_USABLE |
| 2026-08-26T09:44:35.173Z | OK | 42.8 | 9.1 / 9.9 | 0.386 | 0.262 | 0.189 | NOT_USABLE |
| 2026-08-28T09:44:52.662Z | OK | 41.7 | 100.0 / 100.0 | 0.852 | 0.653 | 0.369 | CANDIDATE_BELOW_MIN |
| 2026-08-29T09:54:31.983Z | SKIPPED_CLOUD | 100.0 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | — |
| 2026-08-31T09:44:34.87Z | NO_VALID_PIXELS | 75.3 | 0.0 / 0.0 | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | — |
| 2026-08-31T09:54:49.237Z | NO_VALID_PIXELS | 77.4 | 0.0 / 0.0 | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | — |
| 2026-09-03T09:54:31.483Z | OK | 47.6 | 0.7 / 2.8 | 0.290 | 0.554 | 0.378 | NOT_USABLE |
| 2026-09-05T09:44:35.427Z | SKIPPED_CLOUD | 95.8 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 95.8%)) | NULL (SKIPPED_CLOUD (scene 95.8%)) | NULL (SKIPPED_CLOUD (scene 95.8%)) | — |
| 2026-09-07T09:44:52.189Z | OK | 31.1 | 82.6 / 83.6 | 0.840 | 0.651 | 0.374 | CANDIDATE_BELOW_MIN |
| 2026-09-08T09:54:31.884Z | SKIPPED_CLOUD | 91.6 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 91.6%)) | NULL (SKIPPED_CLOUD (scene 91.6%)) | NULL (SKIPPED_CLOUD (scene 91.6%)) | — |
| 2026-09-10T09:44:34.62Z | SKIPPED_CLOUD | 92.4 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 92.4%)) | NULL (SKIPPED_CLOUD (scene 92.4%)) | NULL (SKIPPED_CLOUD (scene 92.4%)) | — |
| 2026-09-10T09:54:48.429Z | SKIPPED_CLOUD | 91.4 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 91.4%)) | NULL (SKIPPED_CLOUD (scene 91.4%)) | NULL (SKIPPED_CLOUD (scene 91.4%)) | — |
| 2026-09-13T09:54:30.378Z | SKIPPED_CLOUD | 100.0 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | — |
| 2026-09-15T09:44:36.46Z | OK | 35.1 | 100.0 / 100.0 | 0.832 | 0.647 | 0.366 | EVENT_CREATED → event #3 |
| 2026-09-17T09:44:50.792Z | SKIPPED_CLOUD | 93.2 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 93.2%)) | NULL (SKIPPED_CLOUD (scene 93.2%)) | NULL (SKIPPED_CLOUD (scene 93.2%)) | — |
| 2026-09-18T09:54:33.712Z | SKIPPED_CLOUD | 98.1 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 98.1%)) | NULL (SKIPPED_CLOUD (scene 98.1%)) | NULL (SKIPPED_CLOUD (scene 98.1%)) | — |
| 2026-09-20T09:44:36.506Z | SKIPPED_CLOUD | 90.1 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 90.1%)) | NULL (SKIPPED_CLOUD (scene 90.1%)) | NULL (SKIPPED_CLOUD (scene 90.1%)) | — |
| 2026-09-20T09:54:47.6Z | SKIPPED_CLOUD | 81.4 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 81.4%)) | NULL (SKIPPED_CLOUD (scene 81.4%)) | NULL (SKIPPED_CLOUD (scene 81.4%)) | — |
| 2026-09-23T09:54:33.477Z | SKIPPED_CLOUD | 99.8 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 99.8%)) | NULL (SKIPPED_CLOUD (scene 99.8%)) | NULL (SKIPPED_CLOUD (scene 99.8%)) | — |
| 2026-09-25T09:44:38.379Z | SKIPPED_CLOUD | 100.0 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | — |
| 2026-09-27T09:44:51.171Z | OK | 52.4 | 0.8 / 4.7 | 0.600 | 0.573 | 0.397 | NOT_USABLE |
| 2026-09-28T09:54:35.305Z | OK | 9.5 | 62.2 / 62.8 | 0.846 | 0.666 | 0.384 | EVENT_CREATED → event #6 |
| 2026-09-30T09:44:37.338Z | SKIPPED_CLOUD | 100.0 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | — |
| 2026-09-30T09:54:47.618Z | SKIPPED_CLOUD | 100.0 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | — |
| 2026-10-03T09:54:33.776Z | OK | 65.9 | 100.0 / 100.0 | 0.802 | 0.609 | 0.346 | EVENT_CREATED → event #7 |
| 2026-10-05T09:44:39.139Z | SKIPPED_CLOUD | 100.0 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | — |
| 2026-10-07T09:44:50.321Z | OK | 12.1 | 97.7 / 93.0 | 0.795 | 0.587 | 0.311 | EVENT_CREATED → event #8 |
| 2026-10-08T09:54:35.736Z | SKIPPED_CLOUD | 88.4 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 88.4%)) | NULL (SKIPPED_CLOUD (scene 88.4%)) | NULL (SKIPPED_CLOUD (scene 88.4%)) | — |
| 2026-10-10T09:44:36.972Z | OK | 76.7 | 100.0 / 99.4 | 0.656 | 0.502 | 0.291 | EVENT_CREATED → event #1 |
| 2026-10-10T09:54:46.435Z | OK | 80.0 | 6.8 / 7.0 | 0.532 | 0.324 | 0.208 | NOT_USABLE |
| 2026-10-13T09:54:33.147Z | SKIPPED_CLOUD | 99.4 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 99.4%)) | NULL (SKIPPED_CLOUD (scene 99.4%)) | NULL (SKIPPED_CLOUD (scene 99.4%)) | — |
| 2026-10-15T09:44:38.658Z | SKIPPED_CLOUD | 98.8 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 98.8%)) | NULL (SKIPPED_CLOUD (scene 98.8%)) | NULL (SKIPPED_CLOUD (scene 98.8%)) | — |
| 2026-10-17T09:44:48.047Z | NO_VALID_PIXELS | 79.2 | 0.0 / 0.0 | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | — |
| 2026-10-18T09:54:38.607Z | OK | 8.3 | 100.0 / 100.0 | 0.849 | 0.639 | 0.366 | CANDIDATE_BELOW_MIN |
| 2026-10-20T09:54:43.611Z | OK | 50.1 | 96.7 / 99.3 | 0.752 | 0.578 | 0.312 | EVENT_UPDATED → event #9 |
| 2026-10-23T09:54:34.258Z | SKIPPED_CLOUD | 100.0 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | — |
| 2026-10-25T09:44:36.57Z | SKIPPED_CLOUD | 86.0 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 86.0%)) | NULL (SKIPPED_CLOUD (scene 86.0%)) | NULL (SKIPPED_CLOUD (scene 86.0%)) | — |
| 2026-10-27T09:44:44.138Z | OK | 21.7 | 96.8 / 100.0 | 0.783 | 0.588 | 0.320 | CANDIDATE_BELOW_MIN |
| 2026-10-28T09:54:32.257Z | SKIPPED_CLOUD | 93.6 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 93.6%)) | NULL (SKIPPED_CLOUD (scene 93.6%)) | NULL (SKIPPED_CLOUD (scene 93.6%)) | — |
| 2026-10-30T09:44:38.326Z | SKIPPED_CLOUD | 99.8 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 99.8%)) | NULL (SKIPPED_CLOUD (scene 99.8%)) | NULL (SKIPPED_CLOUD (scene 99.8%)) | — |
| 2026-10-30T09:54:40.165Z | SKIPPED_CLOUD | 99.9 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 99.9%)) | NULL (SKIPPED_CLOUD (scene 99.9%)) | NULL (SKIPPED_CLOUD (scene 99.9%)) | — |
| 2026-11-04T09:44:33.133Z | NO_VALID_PIXELS | 54.6 | 0.0 / 0.0 | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | NULL (NO_VALID_PIXELS) | — |
| 2026-11-06T09:44:43.447Z | OK | 54.5 | 99.8 / 94.3 | 0.779 | 0.612 | 0.342 | EVENT_UPDATED → event #5 |
| 2026-11-07T09:54:29.891Z | SKIPPED_CLOUD | 92.6 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 92.6%)) | NULL (SKIPPED_CLOUD (scene 92.6%)) | NULL (SKIPPED_CLOUD (scene 92.6%)) | — |
| 2026-11-09T09:44:38.076Z | SKIPPED_CLOUD | 100.0 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | — |
| 2026-11-09T09:54:39.731Z | SKIPPED_CLOUD | 100.0 | NULL / NULL | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | NULL (SKIPPED_CLOUD (scene 100.0%)) | — |

### S1 timeline (67 acquisitions) — PROCESSED

| sensing (UTC) | status | orbit | rel. orbit | valid % in / buf | VV dB med | VH dB med | detection |
|---|---|---|---|---|---|---|---|
| 2026-08-01T16:11:22Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.711 | -13.425 | NO_BASELINE |
| 2026-08-02T16:03:28Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.152 | -13.156 | NO_BASELINE |
| 2026-08-03T04:42:11Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.687 | -13.895 | NO_BASELINE |
| 2026-08-04T04:34:20Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -9.236 | -14.133 | NO_BASELINE |
| 2026-08-07T16:11:34Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.664 | -13.586 | SINGLE_DROP |
| 2026-08-08T16:03:16Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.258 | -13.437 | SINGLE_DROP |
| 2026-08-09T04:42:24Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -9.043 | -14.195 | SINGLE_DROP |
| 2026-08-10T04:34:08Z | OK | DESCENDING | 80 | 99.9 / 100.0 | -9.321 | -14.525 | SINGLE_DROP |
| 2026-08-13T16:11:23Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.760 | -13.786 | SINGLE_DROP |
| 2026-08-14T16:03:29Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.385 | -13.230 | EVENT_CREATED → event #1 |
| 2026-08-15T04:42:12Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.777 | -14.071 | EVENT_CREATED → event #2 |
| 2026-08-16T04:34:21Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -8.804 | -14.129 | SINGLE_DROP |
| 2026-08-19T16:11:35Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.662 | -13.436 | SINGLE_DROP |
| 2026-08-20T16:03:17Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.125 | -13.443 | SINGLE_DROP |
| 2026-08-21T04:42:25Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.660 | -14.114 | SINGLE_DROP |
| 2026-08-22T04:34:08Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -9.263 | -14.421 | SINGLE_DROP |
| 2026-08-25T16:11:23Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.973 | -13.698 | SINGLE_DROP |
| 2026-08-26T16:03:30Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.561 | -13.274 | SINGLE_DROP |
| 2026-08-27T04:42:12Z | OK | DESCENDING | 153 | 99.9 / 100.0 | -8.680 | -14.069 | SINGLE_DROP |
| 2026-08-28T04:34:22Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -9.237 | -14.405 | SINGLE_DROP |
| 2026-08-31T16:11:35Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.450 | -13.287 | SINGLE_DROP |
| 2026-09-01T16:03:17Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -7.994 | -13.040 | SINGLE_DROP |
| 2026-09-02T04:42:25Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.493 | -13.515 | SINGLE_DROP |
| 2026-09-03T04:34:09Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -9.320 | -14.525 | SINGLE_DROP |
| 2026-09-06T16:11:24Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.761 | -13.600 | SINGLE_DROP |
| 2026-09-07T16:03:30Z | OK | ASCENDING | 58 | 99.9 / 100.0 | -8.617 | -13.241 | SINGLE_DROP |
| 2026-09-08T04:42:12Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.818 | -14.148 | SINGLE_DROP |
| 2026-09-09T04:34:22Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -8.899 | -14.044 | SINGLE_DROP |
| 2026-09-12T16:11:36Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.720 | -13.480 | SINGLE_DROP |
| 2026-09-13T16:03:18Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.480 | -13.518 | SINGLE_DROP |
| 2026-09-14T04:42:26Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.828 | -14.189 | SINGLE_DROP |
| 2026-09-15T04:34:09Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -9.434 | -14.840 | SINGLE_DROP |
| 2026-09-18T16:11:24Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -9.134 | -13.786 | SINGLE_DROP |
| 2026-09-19T16:03:30Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.714 | -13.659 | SINGLE_DROP |
| 2026-09-20T04:42:13Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.821 | -14.146 | SINGLE_DROP |
| 2026-09-21T04:34:22Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -8.993 | -14.133 | CANDIDATE_BELOW_MIN |
| 2026-09-24T16:11:36Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.630 | -13.360 | SINGLE_DROP |
| 2026-09-25T16:03:18Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -7.911 | -12.673 | CANDIDATE_BELOW_MIN |
| 2026-09-26T04:42:26Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.341 | -13.430 | SINGLE_DROP |
| 2026-09-27T04:34:09Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -8.614 | -14.017 | SINGLE_DROP |
| 2026-09-30T16:11:24Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.657 | -13.509 | SINGLE_DROP |
| 2026-10-01T16:03:30Z | OK | ASCENDING | 58 | 99.9 / 99.9 | -8.685 | -13.539 | SINGLE_DROP |
| 2026-10-02T04:42:13Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -9.104 | -14.227 | SINGLE_DROP |
| 2026-10-03T04:34:22Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -8.993 | -14.313 | SINGLE_DROP |
| 2026-10-06T16:11:36Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.492 | -13.201 | SINGLE_DROP |
| 2026-10-07T16:03:18Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.605 | -13.682 | EVENT_UPDATED → event #5 |
| 2026-10-08T04:42:26Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -9.082 | -14.264 | SINGLE_DROP |
| 2026-10-09T04:34:09Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -8.612 | -13.917 | SINGLE_DROP |
| 2026-10-12T16:11:24Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.813 | -13.606 | SINGLE_DROP |
| 2026-10-13T16:03:30Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.657 | -13.522 | SINGLE_DROP |
| 2026-10-14T04:42:13Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.917 | -13.796 | EVENT_UPDATED → event #9 |
| 2026-10-15T04:34:22Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -8.941 | -13.957 | SINGLE_DROP |
| 2026-10-18T16:11:36Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.895 | -13.590 | SINGLE_DROP |
| 2026-10-19T16:03:18Z | OK | ASCENDING | 58 | 99.9 / 100.0 | -8.885 | -13.841 | SINGLE_DROP |
| 2026-10-20T04:42:26Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -9.522 | -14.422 | SINGLE_DROP |
| 2026-10-21T04:34:09Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -9.778 | -14.521 | SINGLE_DROP |
| 2026-10-24T16:11:23Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.762 | -13.697 | SINGLE_DROP |
| 2026-10-25T16:03:30Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.465 | -13.267 | SINGLE_DROP |
| 2026-10-26T04:42:12Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.865 | -13.803 | SINGLE_DROP |
| 2026-10-30T16:11:36Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.305 | -13.272 | SINGLE_DROP |
| 2026-10-31T16:03:17Z | OK | ASCENDING | 58 | 100.0 / 100.0 | -8.297 | -13.198 | SINGLE_DROP |
| 2026-11-01T04:42:25Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -8.827 | -13.652 | CANDIDATE_BELOW_MIN |
| 2026-11-02T04:34:09Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -9.606 | -14.314 | EVENT_UPDATED → event #7 |
| 2026-11-05T16:11:24Z | OK | ASCENDING | 131 | 100.0 / 100.0 | -8.818 | -13.422 | SINGLE_DROP |
| 2026-11-06T16:03:30Z | OK | ASCENDING | 58 | 100.0 / 99.9 | -8.744 | -13.520 | SINGLE_DROP |
| 2026-11-07T04:42:12Z | OK | DESCENDING | 153 | 100.0 / 100.0 | -9.253 | -14.143 | SINGLE_DROP |
| 2026-11-08T04:34:22Z | OK | DESCENDING | 80 | 100.0 / 100.0 | -9.338 | -13.954 | SINGLE_DROP |

### Suspected change events (9) — INTERPRETATION

### Event #1 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL (suspected change)

- Status (HUMAN): SUSPECTED
- Sensor basis: S1+S2 · detection confidence: HIGH · evidence quality: GOOD
- After window: 2026-08-14T16:03:29Z … 2026-10-10T09:44:36.972Z; before acquisitions: [2, 76, 79, 103, 106, 108]
- Changed: 2.06 ha (inside 0.91 ha, buffer 1.15 ha), 1.8 % of area, largest cluster 1.66 ha, max distance outside boundary 85 m
- Seasonal caveat: After-image is from Oct–Apr: leaf fall/leaf-off, frozen or wet ground and snow change optical indices and radar backscatter without any felling.
- Operational context: CHANGE_DURING_REGISTERED_WORK (53 registered records in window)
- Thresholds: `{"baseline_max_acq": 3, "baseline_max_age_days": 90, "buffer_m": 100.0, "high_confidence_max_gap_days": 24, "min_cluster_ha": 0.3, "min_valid_pct": 60.0, "ongoing_max_gap_days": 60, "ongoing_overlap_fraction": 0.3, "outside_min_ha": 0.3, "pixel_m": 10.0, "s1_filter_size": 3, "s1_vh_drop_db": 2.0, "s2_dnbr_threshold": -0.15, "s2_dndmi_threshold": -0.1, "s2_dndvi_threshold": -0.1, "s2_valid_scl": [4, 5], "seasonal_months": [10, 11, 12, 1, 2, 3, 4], "snow_max_pct": 10.0}`

### Event #2 — POTENTIAL_FOREST_LOSS (suspected change)

- Status (HUMAN): SUSPECTED
- Sensor basis: S1+S2 · detection confidence: HIGH · evidence quality: LIMITED
- After window: 2026-08-15T04:42:12Z … 2026-08-19T09:54:31.401Z; before acquisitions: [3, 76]
- Changed: 1.30 ha (inside 1.30 ha, buffer 0.00 ha), 2.6 % of area, largest cluster 1.30 ha, max distance outside boundary NULL m
- Operational context: UNREGISTERED_CHANGE_CANDIDATE (0 registered records in window)
- Thresholds: `{"baseline_max_acq": 3, "baseline_max_age_days": 90, "buffer_m": 100.0, "high_confidence_max_gap_days": 24, "min_cluster_ha": 0.3, "min_valid_pct": 60.0, "ongoing_max_gap_days": 60, "ongoing_overlap_fraction": 0.3, "outside_min_ha": 0.3, "pixel_m": 10.0, "s1_filter_size": 3, "s1_vh_drop_db": 2.0, "s2_dnbr_threshold": -0.15, "s2_dndmi_threshold": -0.1, "s2_dndvi_threshold": -0.1, "s2_valid_scl": [4, 5], "seasonal_months": [10, 11, 12, 1, 2, 3, 4], "snow_max_pct": 10.0}`

### Event #3 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL (suspected change)

- Status (HUMAN): SUSPECTED
- Sensor basis: S2 · detection confidence: MEDIUM · evidence quality: GOOD
- After window: 2026-08-19T09:54:31.401Z … 2026-10-10T09:44:36.972Z; before acquisitions: [76, 81, 84, 90, 103, 106, 108]
- Changed: 5.14 ha (inside 3.78 ha, buffer 1.36 ha), 7.5 % of area, largest cluster 3.66 ha, max distance outside boundary 100 m
- Seasonal caveat: After-image is from Oct–Apr: leaf fall/leaf-off, frozen or wet ground and snow change optical indices and radar backscatter without any felling.
- Operational context: CHANGE_DURING_REGISTERED_WORK (53 registered records in window)
- Thresholds: `{"baseline_max_acq": 3, "baseline_max_age_days": 90, "buffer_m": 100.0, "high_confidence_max_gap_days": 24, "min_cluster_ha": 0.3, "min_valid_pct": 60.0, "ongoing_max_gap_days": 60, "ongoing_overlap_fraction": 0.3, "outside_min_ha": 0.3, "pixel_m": 10.0, "s1_filter_size": 3, "s1_vh_drop_db": 2.0, "s2_dnbr_threshold": -0.15, "s2_dndmi_threshold": -0.1, "s2_dndvi_threshold": -0.1, "s2_valid_scl": [4, 5], "seasonal_months": [10, 11, 12, 1, 2, 3, 4], "snow_max_pct": 10.0}`

### Event #4 — POTENTIAL_CHANGE_OUTSIDE_BOUNDARY (suspected change)

- Status (HUMAN): SUSPECTED
- Sensor basis: S2 · detection confidence: MEDIUM · evidence quality: GOOD
- After window: 2026-08-21T09:44:33.821Z … 2026-08-21T09:44:33.821Z; before acquisitions: [79, 76]
- Changed: 1.29 ha (inside 0.16 ha, buffer 1.13 ha), 0.3 % of area, largest cluster 1.29 ha, max distance outside boundary 98 m
- Operational context: UNREGISTERED_CHANGE_CANDIDATE (0 registered records in window)
- Thresholds: `{"baseline_max_acq": 3, "baseline_max_age_days": 90, "buffer_m": 100.0, "high_confidence_max_gap_days": 24, "min_cluster_ha": 0.3, "min_valid_pct": 60.0, "ongoing_max_gap_days": 60, "ongoing_overlap_fraction": 0.3, "outside_min_ha": 0.3, "pixel_m": 10.0, "s1_filter_size": 3, "s1_vh_drop_db": 2.0, "s2_dnbr_threshold": -0.15, "s2_dndmi_threshold": -0.1, "s2_dndvi_threshold": -0.1, "s2_valid_scl": [4, 5], "seasonal_months": [10, 11, 12, 1, 2, 3, 4], "snow_max_pct": 10.0}`

### Event #5 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL (suspected change)

- Status (HUMAN): SUSPECTED
- Sensor basis: S1+S2 · detection confidence: HIGH · evidence quality: GOOD
- After window: 2026-09-15T09:44:36.46Z … 2026-11-06T09:44:43.447Z; before acquisitions: [30, 34, 38, 81, 84, 90, 103, 106, 108, 115, 116, 119]
- Changed: 2.40 ha (inside 1.79 ha, buffer 0.61 ha), 3.5 % of area, largest cluster 1.99 ha, max distance outside boundary 73 m
- Seasonal caveat: After-image is from Oct–Apr: leaf fall/leaf-off, frozen or wet ground and snow change optical indices and radar backscatter without any felling.
- Operational context: CHANGE_DURING_REGISTERED_WORK (83 registered records in window)
- Thresholds: `{"baseline_max_acq": 3, "baseline_max_age_days": 90, "buffer_m": 100.0, "high_confidence_max_gap_days": 24, "min_cluster_ha": 0.3, "min_valid_pct": 60.0, "ongoing_max_gap_days": 60, "ongoing_overlap_fraction": 0.3, "outside_min_ha": 0.3, "pixel_m": 10.0, "s1_filter_size": 3, "s1_vh_drop_db": 2.0, "s2_dnbr_threshold": -0.15, "s2_dndmi_threshold": -0.1, "s2_dndvi_threshold": -0.1, "s2_valid_scl": [4, 5], "seasonal_months": [10, 11, 12, 1, 2, 3, 4], "snow_max_pct": 10.0}`

### Event #6 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL (suspected change)

- Status (HUMAN): SUSPECTED
- Sensor basis: S2 · detection confidence: MEDIUM · evidence quality: GOOD
- After window: 2026-09-28T09:54:35.305Z … 2026-11-06T09:44:43.447Z; before acquisitions: [84, 90, 95, 115, 116, 119]
- Changed: 0.79 ha (inside 0.53 ha, buffer 0.26 ha), 1.1 % of area, largest cluster 0.79 ha, max distance outside boundary 36 m
- Seasonal caveat: After-image is from Oct–Apr: leaf fall/leaf-off, frozen or wet ground and snow change optical indices and radar backscatter without any felling.
- Operational context: CHANGE_DURING_REGISTERED_WORK (83 registered records in window)
- Thresholds: `{"baseline_max_acq": 3, "baseline_max_age_days": 90, "buffer_m": 100.0, "high_confidence_max_gap_days": 24, "min_cluster_ha": 0.3, "min_valid_pct": 60.0, "ongoing_max_gap_days": 60, "ongoing_overlap_fraction": 0.3, "outside_min_ha": 0.3, "pixel_m": 10.0, "s1_filter_size": 3, "s1_vh_drop_db": 2.0, "s2_dnbr_threshold": -0.15, "s2_dndmi_threshold": -0.1, "s2_dndvi_threshold": -0.1, "s2_valid_scl": [4, 5], "seasonal_months": [10, 11, 12, 1, 2, 3, 4], "snow_max_pct": 10.0}`

### Event #7 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL (suspected change)

- Status (HUMAN): SUSPECTED
- Sensor basis: S1+S2 · detection confidence: MEDIUM · evidence quality: GOOD
- After window: 2026-10-03T09:54:33.776Z … 2026-11-02T04:34:09Z; before acquisitions: [44, 48, 52, 90, 95, 103]
- Changed: 0.47 ha (inside 0.47 ha, buffer 0.00 ha), 0.9 % of area, largest cluster 0.47 ha, max distance outside boundary NULL m
- Seasonal caveat: After-image is from Oct–Apr: leaf fall/leaf-off, frozen or wet ground and snow change optical indices and radar backscatter without any felling.
- Operational context: CHANGE_DURING_REGISTERED_WORK (83 registered records in window)
- Thresholds: `{"baseline_max_acq": 3, "baseline_max_age_days": 90, "buffer_m": 100.0, "high_confidence_max_gap_days": 24, "min_cluster_ha": 0.3, "min_valid_pct": 60.0, "ongoing_max_gap_days": 60, "ongoing_overlap_fraction": 0.3, "outside_min_ha": 0.3, "pixel_m": 10.0, "s1_filter_size": 3, "s1_vh_drop_db": 2.0, "s2_dnbr_threshold": -0.15, "s2_dndmi_threshold": -0.1, "s2_dndvi_threshold": -0.1, "s2_valid_scl": [4, 5], "seasonal_months": [10, 11, 12, 1, 2, 3, 4], "snow_max_pct": 10.0}`

### Event #8 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL (suspected change)

- Status (HUMAN): SUSPECTED
- Sensor basis: S2 · detection confidence: MEDIUM · evidence quality: GOOD
- After window: 2026-10-07T09:44:50.321Z … 2026-10-07T09:44:50.321Z; before acquisitions: [106, 103, 95]
- Changed: 4.55 ha (inside 4.16 ha, buffer 0.39 ha), 8.2 % of area, largest cluster 3.37 ha, max distance outside boundary 60 m
- Seasonal caveat: After-image is from Oct–Apr: leaf fall/leaf-off, frozen or wet ground and snow change optical indices and radar backscatter without any felling.
- Operational context: UNREGISTERED_CHANGE_CANDIDATE (0 registered records in window)
- Thresholds: `{"baseline_max_acq": 3, "baseline_max_age_days": 90, "buffer_m": 100.0, "high_confidence_max_gap_days": 24, "min_cluster_ha": 0.3, "min_valid_pct": 60.0, "ongoing_max_gap_days": 60, "ongoing_overlap_fraction": 0.3, "outside_min_ha": 0.3, "pixel_m": 10.0, "s1_filter_size": 3, "s1_vh_drop_db": 2.0, "s2_dnbr_threshold": -0.15, "s2_dndmi_threshold": -0.1, "s2_dndvi_threshold": -0.1, "s2_valid_scl": [4, 5], "seasonal_months": [10, 11, 12, 1, 2, 3, 4], "snow_max_pct": 10.0}`

### Event #9 — POSSIBLE_SEASONAL_OR_ENVIRONMENTAL (suspected change)

- Status (HUMAN): SUSPECTED
- Sensor basis: S1+S2 · detection confidence: HIGH · evidence quality: GOOD
- After window: 2026-10-10T09:44:36.972Z … 2026-10-20T09:54:43.611Z; before acquisitions: [35, 39, 43, 103, 106, 108, 110, 115]
- Changed: 10.91 ha (inside 6.33 ha, buffer 4.58 ha), 12.5 % of area, largest cluster 6.46 ha, max distance outside boundary 100 m
- Seasonal caveat: After-image is from Oct–Apr: leaf fall/leaf-off, frozen or wet ground and snow change optical indices and radar backscatter without any felling.
- Operational context: CHANGE_DURING_REGISTERED_WORK (83 registered records in window)
- Thresholds: `{"baseline_max_acq": 3, "baseline_max_age_days": 90, "buffer_m": 100.0, "high_confidence_max_gap_days": 24, "min_cluster_ha": 0.3, "min_valid_pct": 60.0, "ongoing_max_gap_days": 60, "ongoing_overlap_fraction": 0.3, "outside_min_ha": 0.3, "pixel_m": 10.0, "s1_filter_size": 3, "s1_vh_drop_db": 2.0, "s2_dnbr_threshold": -0.15, "s2_dndmi_threshold": -0.1, "s2_dndvi_threshold": -0.1, "s2_valid_scl": [4, 5], "seasonal_months": [10, 11, 12, 1, 2, 3, 4], "snow_max_pct": 10.0}`


### Evidence files — RAW

| acquisition | product_id | raster (GeoTIFF) | sha256 | quicklook (PNG, PROCESSED) |
|---|---|---|---|---|
| 1 S1 2026-08-01 | `S1C_IW_GRDH_1SDV_20260801T161122_20260801T161147_008804_011743_EE44_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-01_S1C_IW_GRDH_1SDV_20260801T161122_20260801T161147_008804_011743_EE44_COG.SAFE.tif` | `164782981add2d9e9bc01553aa66edd7d9f40f195faa191ee2d5132608cc9674` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-01_S1C_IW_GRDH_1SDV_20260801T161122_20260801T161147_008804_011743_EE44_COG.SAFE.png` |
| 2 S1 2026-08-02 | `S1D_IW_GRDH_1SDV_20260802T160328_20260802T160353_003949_007286_BAB2_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-02_S1D_IW_GRDH_1SDV_20260802T160328_20260802T160353_003949_007286_BAB2_COG.SAFE.tif` | `b38b6cc439b2e9adf9a7dd9da028eb30cac049542b3f76d6b524375532391ec8` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-02_S1D_IW_GRDH_1SDV_20260802T160328_20260802T160353_003949_007286_BAB2_COG.SAFE.png` |
| 3 S1 2026-08-03 | `S1C_IW_GRDH_1SDV_20260803T044211_20260803T044236_008826_011816_D07A_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-03_S1C_IW_GRDH_1SDV_20260803T044211_20260803T044236_008826_011816_D07A_COG.SAFE.tif` | `19d81ba4c74d8cb203b2911b37987bf1fbc7b8a8b327a9d1c2ace74cf62943ad` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-03_S1C_IW_GRDH_1SDV_20260803T044211_20260803T044236_008826_011816_D07A_COG.SAFE.png` |
| 4 S1 2026-08-04 | `S1D_IW_GRDH_1SDV_20260804T043420_20260804T043445_003971_007356_0D87_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-04_S1D_IW_GRDH_1SDV_20260804T043420_20260804T043445_003971_007356_0D87_COG.SAFE.tif` | `f19116f3a5999ab7c7f38be2c276d59871b60c50e4e99f4a090a776269e59bd8` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-04_S1D_IW_GRDH_1SDV_20260804T043420_20260804T043445_003971_007356_0D87_COG.SAFE.png` |
| 70 S2 2026-08-04 | `S2B_MSIL2A_20260804T095029_N0512_R079_T34VFJ_20260804T121325.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-04_S2B_MSIL2A_20260804T095029_N0512_R079_T34VFJ_20260804T121325.SAFE.tif` | `15cf00e04c73b1bbe3530dfe09a55f584eee8b739e5e58f775155fa6458dad50` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-04_S2B_MSIL2A_20260804T095029_N0512_R079_T34VFJ_20260804T121325.SAFE.png` |
| 5 S1 2026-08-07 | `S1D_IW_GRDH_1SDV_20260807T161134_20260807T161159_004022_00750A_614A_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-07_S1D_IW_GRDH_1SDV_20260807T161134_20260807T161159_004022_00750A_614A_COG.SAFE.tif` | `784c0db757e8f282711e001af6df9a6a6b6c06118d1e4304643e51f28e4feceb` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-07_S1D_IW_GRDH_1SDV_20260807T161134_20260807T161159_004022_00750A_614A_COG.SAFE.png` |
| 72 S2 2026-08-08 | `S2A_MSIL2A_20260808T094051_N0512_R036_T34VFJ_20260808T162111.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-08_S2A_MSIL2A_20260808T094051_N0512_R036_T34VFJ_20260808T162111.SAFE.tif` | `b778c924634fe392c1efc2bf29bb91dec9f0f4391b423af1816a232ac159c6d2` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-08_S2A_MSIL2A_20260808T094051_N0512_R036_T34VFJ_20260808T162111.SAFE.png` |
| 6 S1 2026-08-08 | `S1C_IW_GRDH_1SDV_20260808T160316_20260808T160341_008906_011AA5_D028_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-08_S1C_IW_GRDH_1SDV_20260808T160316_20260808T160341_008906_011AA5_D028_COG.SAFE.tif` | `423a67d131e94404faa0b0880e2edbe18c07650953999b5230934d6701f5ca6a` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-08_S1C_IW_GRDH_1SDV_20260808T160316_20260808T160341_008906_011AA5_D028_COG.SAFE.png` |
| 7 S1 2026-08-09 | `S1D_IW_GRDH_1SDV_20260809T044224_20260809T044249_004044_0075C8_2363_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-09_S1D_IW_GRDH_1SDV_20260809T044224_20260809T044249_004044_0075C8_2363_COG.SAFE.tif` | `349119d5d90549a991923db747f8a0e40e2e241697f42585734549af53f0d5b0` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-09_S1D_IW_GRDH_1SDV_20260809T044224_20260809T044249_004044_0075C8_2363_COG.SAFE.png` |
| 73 S2 2026-08-09 | `S2C_MSIL2A_20260809T095031_N0512_R079_T34VFJ_20260809T131207.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-09_S2C_MSIL2A_20260809T095031_N0512_R079_T34VFJ_20260809T131207.SAFE.tif` | `43f4c2f0c09a7f6ba980ee868872ba832e8582bd25c84a1638c3eb6ad429da85` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-09_S2C_MSIL2A_20260809T095031_N0512_R079_T34VFJ_20260809T131207.SAFE.png` |
| 8 S1 2026-08-10 | `S1C_IW_GRDH_1SDV_20260810T043408_20260810T043433_008928_011B65_1690_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-10_S1C_IW_GRDH_1SDV_20260810T043408_20260810T043433_008928_011B65_1690_COG.SAFE.tif` | `b591d99e787e0a106523c9ef8aa488bad0c4995316b5acffa8162a6272eebd63` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-10_S1C_IW_GRDH_1SDV_20260810T043408_20260810T043433_008928_011B65_1690_COG.SAFE.png` |
| 74 S2 2026-08-11 | `S2B_MSIL2A_20260811T094029_N0512_R036_T34VFJ_20260811T115425.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-11_S2B_MSIL2A_20260811T094029_N0512_R036_T34VFJ_20260811T115425.SAFE.tif` | `399e9e6ac44f981be72ee41dfa786da4507df9f74a703f13cc6f168f5a4fd51d` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-11_S2B_MSIL2A_20260811T094029_N0512_R036_T34VFJ_20260811T115425.SAFE.png` |
| 75 S2 2026-08-11 | `S2A_MSIL2A_20260811T095101_N0512_R079_T34VFJ_20260811T163220.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-11_S2A_MSIL2A_20260811T095101_N0512_R079_T34VFJ_20260811T163220.SAFE.tif` | `a658f83887e0c0224824134525a83d084d713bf674dec76583ceb6b9d225b30b` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-11_S2A_MSIL2A_20260811T095101_N0512_R079_T34VFJ_20260811T163220.SAFE.png` |
| 9 S1 2026-08-13 | `S1C_IW_GRDH_1SDV_20260813T161123_20260813T161148_008979_011D13_1A84_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-13_S1C_IW_GRDH_1SDV_20260813T161123_20260813T161148_008979_011D13_1A84_COG.SAFE.tif` | `dc744d5fa0eb2d74f2a9f7e052a6506ff6a42c03809f099b048a3b18a6f5ebf1` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-13_S1C_IW_GRDH_1SDV_20260813T161123_20260813T161148_008979_011D13_1A84_COG.SAFE.png` |
| 76 S2 2026-08-14 | `S2B_MSIL2A_20260814T095029_N0512_R079_T34VFJ_20260814T121106.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-14_S2B_MSIL2A_20260814T095029_N0512_R079_T34VFJ_20260814T121106.SAFE.tif` | `090fa92184ee0af2b08e91f568c0d017d1fc2e1ff9e0f4cd5e075f01897668ac` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-14_S2B_MSIL2A_20260814T095029_N0512_R079_T34VFJ_20260814T121106.SAFE.png` |
| 10 S1 2026-08-14 | `S1D_IW_GRDH_1SDV_20260814T160329_20260814T160354_004124_007891_CC48_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-14_S1D_IW_GRDH_1SDV_20260814T160329_20260814T160354_004124_007891_CC48_COG.SAFE.tif` | `29e5ec742a7194345ae2b514f6c11bb6b9dcdc14fec6b2bca2f90ae36d4362c2` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-14_S1D_IW_GRDH_1SDV_20260814T160329_20260814T160354_004124_007891_CC48_COG.SAFE.png` |
| 11 S1 2026-08-15 | `S1C_IW_GRDH_1SDV_20260815T044212_20260815T044237_009001_011DDA_5E57_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-15_S1C_IW_GRDH_1SDV_20260815T044212_20260815T044237_009001_011DDA_5E57_COG.SAFE.tif` | `927a9e8cd1f40c22ff7822d8e6c0c672b21355109db1ddd8a08af881b8eef67d` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-15_S1C_IW_GRDH_1SDV_20260815T044212_20260815T044237_009001_011DDA_5E57_COG.SAFE.png` |
| 12 S1 2026-08-16 | `S1D_IW_GRDH_1SDV_20260816T043421_20260816T043446_004146_00795C_2AEB_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-16_S1D_IW_GRDH_1SDV_20260816T043421_20260816T043446_004146_00795C_2AEB_COG.SAFE.tif` | `99a0cfbcbf4e524932fb5a86f898a52271ff2de6469de5cd5aa5c18f1113da1d` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-16_S1D_IW_GRDH_1SDV_20260816T043421_20260816T043446_004146_00795C_2AEB_COG.SAFE.png` |
| 79 S2 2026-08-19 | `S2C_MSIL2A_20260819T095031_N0512_R079_T34VFJ_20260819T131410.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-19_S2C_MSIL2A_20260819T095031_N0512_R079_T34VFJ_20260819T131410.SAFE.tif` | `cc5b7b198cf4320bf3ed5781ad2935c801cecc33e84626f7b0f8d805e0ee0701` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-19_S2C_MSIL2A_20260819T095031_N0512_R079_T34VFJ_20260819T131410.SAFE.png` |
| 13 S1 2026-08-19 | `S1D_IW_GRDH_1SDV_20260819T161135_20260819T161200_004197_007B0D_D58F_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-19_S1D_IW_GRDH_1SDV_20260819T161135_20260819T161200_004197_007B0D_D58F_COG.SAFE.tif` | `09e6a9655d36446a6bc53f81b427754c411ef35416e6cc05aaa831965cc36df9` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-19_S1D_IW_GRDH_1SDV_20260819T161135_20260819T161200_004197_007B0D_D58F_COG.SAFE.png` |
| 14 S1 2026-08-20 | `S1C_IW_GRDH_1SDV_20260820T160317_20260820T160342_009081_012067_E3BE_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-20_S1C_IW_GRDH_1SDV_20260820T160317_20260820T160342_009081_012067_E3BE_COG.SAFE.tif` | `f4bbf2a3a0eb99a9fd973f4a3afd58158d94537bce5a4623f61582c86878ffd6` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-20_S1C_IW_GRDH_1SDV_20260820T160317_20260820T160342_009081_012067_E3BE_COG.SAFE.png` |
| 15 S1 2026-08-21 | `S1D_IW_GRDH_1SDV_20260821T044225_20260821T044250_004219_007BE0_0E03_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-21_S1D_IW_GRDH_1SDV_20260821T044225_20260821T044250_004219_007BE0_0E03_COG.SAFE.tif` | `46fcc2b657a3aeb33529164bad393bf0c781b7dd06fbb5023534e9e923c064c4` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-21_S1D_IW_GRDH_1SDV_20260821T044225_20260821T044250_004219_007BE0_0E03_COG.SAFE.png` |
| 80 S2 2026-08-21 | `S2B_MSIL2A_20260821T094029_N0512_R036_T34VFJ_20260821T115427.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-21_S2B_MSIL2A_20260821T094029_N0512_R036_T34VFJ_20260821T115427.SAFE.tif` | `ea7e57fa26153e895b514e258caf14652cbe155013c287f4ab49bbfcc5de375f` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-21_S2B_MSIL2A_20260821T094029_N0512_R036_T34VFJ_20260821T115427.SAFE.png` |
| 81 S2 2026-08-21 | `S2A_MSIL2A_20260821T095041_N0512_R079_T34VFJ_20260821T175657.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-21_S2A_MSIL2A_20260821T095041_N0512_R079_T34VFJ_20260821T175657.SAFE.tif` | `7dec2eb818a7cc421e6c02a37640bdc4e6f303d4c2ba0c569813bd40a53e7eff` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-21_S2A_MSIL2A_20260821T095041_N0512_R079_T34VFJ_20260821T175657.SAFE.png` |
| 16 S1 2026-08-22 | `S1C_IW_GRDH_1SDV_20260822T043408_20260822T043433_009103_012129_FF6B_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-22_S1C_IW_GRDH_1SDV_20260822T043408_20260822T043433_009103_012129_FF6B_COG.SAFE.tif` | `41b6a411872e5c0bbbb49f558b317aa1cae3cf145ff1907ed2a81d5dd8536448` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-22_S1C_IW_GRDH_1SDV_20260822T043408_20260822T043433_009103_012129_FF6B_COG.SAFE.png` |
| 82 S2 2026-08-24 | `S2B_MSIL2A_20260824T095029_N0512_R079_T34VFJ_20260824T121326.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-24_S2B_MSIL2A_20260824T095029_N0512_R079_T34VFJ_20260824T121326.SAFE.tif` | `0ca4edcc5619ac6c9c798ad8c24f4f52111991a1bcda9453750b1e7a244dd753` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-24_S2B_MSIL2A_20260824T095029_N0512_R079_T34VFJ_20260824T121326.SAFE.png` |
| 17 S1 2026-08-25 | `S1C_IW_GRDH_1SDV_20260825T161123_20260825T161148_009154_0122E5_FEDB_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-25_S1C_IW_GRDH_1SDV_20260825T161123_20260825T161148_009154_0122E5_FEDB_COG.SAFE.tif` | `24d7608d875b235833cae18cc7285e1d49182594a7a3ecd2550f158a946dc045` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-25_S1C_IW_GRDH_1SDV_20260825T161123_20260825T161148_009154_0122E5_FEDB_COG.SAFE.png` |
| 83 S2 2026-08-26 | `S2C_MSIL2A_20260826T094031_N0512_R036_T34VFJ_20260826T130356.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-26_S2C_MSIL2A_20260826T094031_N0512_R036_T34VFJ_20260826T130356.SAFE.tif` | `97e59b4bc2a0ab0101a3a89ca0658917092344d79ccc0773e1cadf9e95fcc650` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-26_S2C_MSIL2A_20260826T094031_N0512_R036_T34VFJ_20260826T130356.SAFE.png` |
| 18 S1 2026-08-26 | `S1D_IW_GRDH_1SDV_20260826T160330_20260826T160355_004299_007EB0_18E4_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-26_S1D_IW_GRDH_1SDV_20260826T160330_20260826T160355_004299_007EB0_18E4_COG.SAFE.tif` | `53836a50425061fbb26fbfc3d23a4df5a64e84653c3f7bf732a8d1708200509f` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-26_S1D_IW_GRDH_1SDV_20260826T160330_20260826T160355_004299_007EB0_18E4_COG.SAFE.png` |
| 19 S1 2026-08-27 | `S1C_IW_GRDH_1SDV_20260827T044212_20260827T044237_009176_0123A8_35D5_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-27_S1C_IW_GRDH_1SDV_20260827T044212_20260827T044237_009176_0123A8_35D5_COG.SAFE.tif` | `63c48fbe57d03d61cd478597bc09710a5ae72ef1e6205e697609b2313ea4e170` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-27_S1C_IW_GRDH_1SDV_20260827T044212_20260827T044237_009176_0123A8_35D5_COG.SAFE.png` |
| 20 S1 2026-08-28 | `S1D_IW_GRDH_1SDV_20260828T043422_20260828T043447_004321_007F80_2C7F_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-28_S1D_IW_GRDH_1SDV_20260828T043422_20260828T043447_004321_007F80_2C7F_COG.SAFE.tif` | `56ed6e0bdf69da6fd91f361c7414934c04223a0a37b15bb451ebdb42abac0245` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-28_S1D_IW_GRDH_1SDV_20260828T043422_20260828T043447_004321_007F80_2C7F_COG.SAFE.png` |
| 84 S2 2026-08-28 | `S2A_MSIL2A_20260828T094051_N0512_R036_T34VFJ_20260828T161023.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-28_S2A_MSIL2A_20260828T094051_N0512_R036_T34VFJ_20260828T161023.SAFE.tif` | `1022f79ff652f3a825857b573ef12d4352d192e96be119df40154471d11814a7` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-28_S2A_MSIL2A_20260828T094051_N0512_R036_T34VFJ_20260828T161023.SAFE.png` |
| 86 S2 2026-08-31 | `S2B_MSIL2A_20260831T094029_N0512_R036_T34VFJ_20260831T120647.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-31_S2B_MSIL2A_20260831T094029_N0512_R036_T34VFJ_20260831T120647.SAFE.tif` | `2b148a3e55216e20d2f6037bd4b52500ee245d7b24be33822741c98c29db477c` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-31_S2B_MSIL2A_20260831T094029_N0512_R036_T34VFJ_20260831T120647.SAFE.png` |
| 87 S2 2026-08-31 | `S2A_MSIL2A_20260831T095101_N0512_R079_T34VFJ_20260831T162308.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-31_S2A_MSIL2A_20260831T095101_N0512_R079_T34VFJ_20260831T162308.SAFE.tif` | `924c6423192c4ef85a3d3e7feb9866bdb141c81527bdb12de4fcd7bd9d41b6ca` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-08-31_S2A_MSIL2A_20260831T095101_N0512_R079_T34VFJ_20260831T162308.SAFE.png` |
| 21 S1 2026-08-31 | `S1D_IW_GRDH_1SDV_20260831T161135_20260831T161200_004372_00813B_45F5_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-31_S1D_IW_GRDH_1SDV_20260831T161135_20260831T161200_004372_00813B_45F5_COG.SAFE.tif` | `878cb3307f1662d01d0ff6f2a31d9e68f68fcbef075023fca87d382dae98d2f4` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-08-31_S1D_IW_GRDH_1SDV_20260831T161135_20260831T161200_004372_00813B_45F5_COG.SAFE.png` |
| 22 S1 2026-09-01 | `S1C_IW_GRDH_1SDV_20260901T160317_20260901T160342_009256_012648_1A66_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-01_S1C_IW_GRDH_1SDV_20260901T160317_20260901T160342_009256_012648_1A66_COG.SAFE.tif` | `731982086596b2bd1c88a0ad55f83e48d5a88683e1492a9908332919ce4b6aa7` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-01_S1C_IW_GRDH_1SDV_20260901T160317_20260901T160342_009256_012648_1A66_COG.SAFE.png` |
| 23 S1 2026-09-02 | `S1D_IW_GRDH_1SDV_20260902T044225_20260902T044250_004394_008200_EDF7_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-02_S1D_IW_GRDH_1SDV_20260902T044225_20260902T044250_004394_008200_EDF7_COG.SAFE.tif` | `08017aee278cf096c7fe0b9a49bdfbc158c2cd2dd58bf719e91a40863d1336d7` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-02_S1D_IW_GRDH_1SDV_20260902T044225_20260902T044250_004394_008200_EDF7_COG.SAFE.png` |
| 24 S1 2026-09-03 | `S1C_IW_GRDH_1SDV_20260903T043409_20260903T043434_009278_01270B_F4A2_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-03_S1C_IW_GRDH_1SDV_20260903T043409_20260903T043434_009278_01270B_F4A2_COG.SAFE.tif` | `f789105f2da35257d18b207e87059ad0a4a1edab2d63a73e7e7594ba21295f37` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-03_S1C_IW_GRDH_1SDV_20260903T043409_20260903T043434_009278_01270B_F4A2_COG.SAFE.png` |
| 88 S2 2026-09-03 | `S2B_MSIL2A_20260903T095029_N0512_R079_T34VFJ_20260903T133554.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-09-03_S2B_MSIL2A_20260903T095029_N0512_R079_T34VFJ_20260903T133554.SAFE.tif` | `8fc294f6702f91e365ffeea66d1eba64c120a6fdb0678f2783244bf98f8441fb` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-09-03_S2B_MSIL2A_20260903T095029_N0512_R079_T34VFJ_20260903T133554.SAFE.png` |
| 25 S1 2026-09-06 | `S1C_IW_GRDH_1SDV_20260906T161124_20260906T161149_009329_0128CD_96D7_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-06_S1C_IW_GRDH_1SDV_20260906T161124_20260906T161149_009329_0128CD_96D7_COG.SAFE.tif` | `7386b79ce97153ccd9b348fb458fcbbad385578b8aa9b59fd24a4306d006da1d` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-06_S1C_IW_GRDH_1SDV_20260906T161124_20260906T161149_009329_0128CD_96D7_COG.SAFE.png` |
| 90 S2 2026-09-07 | `S2A_MSIL2A_20260907T094121_N0512_R036_T34VFJ_20260907T161656.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-09-07_S2A_MSIL2A_20260907T094121_N0512_R036_T34VFJ_20260907T161656.SAFE.tif` | `3d687d9535c7015375e8d98f553e3d3af85364e9f686787a35c5b0c749839487` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-09-07_S2A_MSIL2A_20260907T094121_N0512_R036_T34VFJ_20260907T161656.SAFE.png` |
| 26 S1 2026-09-07 | `S1D_IW_GRDH_1SDV_20260907T160330_20260907T160355_004474_0084CD_16AC_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-07_S1D_IW_GRDH_1SDV_20260907T160330_20260907T160355_004474_0084CD_16AC_COG.SAFE.tif` | `f0d80d27da52b9230e724baf8cc969ef88e0b17b278978100c6523d1ed34e37a` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-07_S1D_IW_GRDH_1SDV_20260907T160330_20260907T160355_004474_0084CD_16AC_COG.SAFE.png` |
| 27 S1 2026-09-08 | `S1C_IW_GRDH_1SDV_20260908T044212_20260908T044237_009351_012992_B30B_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-08_S1C_IW_GRDH_1SDV_20260908T044212_20260908T044237_009351_012992_B30B_COG.SAFE.tif` | `c7e057cc9a3dbacf58ea8b19326c36d6f2f350fb312b710a44deecb007939b0d` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-08_S1C_IW_GRDH_1SDV_20260908T044212_20260908T044237_009351_012992_B30B_COG.SAFE.png` |
| 28 S1 2026-09-09 | `S1D_IW_GRDH_1SDV_20260909T043422_20260909T043447_004496_00859F_BD67_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-09_S1D_IW_GRDH_1SDV_20260909T043422_20260909T043447_004496_00859F_BD67_COG.SAFE.tif` | `61d6d645c90ea31618258370b4084df9bdf376c2c16e95a76d470bdabb5c0dba` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-09_S1D_IW_GRDH_1SDV_20260909T043422_20260909T043447_004496_00859F_BD67_COG.SAFE.png` |
| 29 S1 2026-09-12 | `S1D_IW_GRDH_1SDV_20260912T161136_20260912T161201_004547_008753_E392_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-12_S1D_IW_GRDH_1SDV_20260912T161136_20260912T161201_004547_008753_E392_COG.SAFE.tif` | `5c7199dffb09b5857700b096509d2109609a1ead33704ada7a4fbbde0f08c523` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-12_S1D_IW_GRDH_1SDV_20260912T161136_20260912T161201_004547_008753_E392_COG.SAFE.png` |
| 30 S1 2026-09-13 | `S1C_IW_GRDH_1SDV_20260913T160318_20260913T160343_009431_012C1F_D7C6_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-13_S1C_IW_GRDH_1SDV_20260913T160318_20260913T160343_009431_012C1F_D7C6_COG.SAFE.tif` | `742df5006b12d67b828d77d3653d2a132bf4b39647b0ed974cba78aded75c6ed` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-13_S1C_IW_GRDH_1SDV_20260913T160318_20260913T160343_009431_012C1F_D7C6_COG.SAFE.png` |
| 31 S1 2026-09-14 | `S1D_IW_GRDH_1SDV_20260914T044226_20260914T044251_004569_008819_4799_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-14_S1D_IW_GRDH_1SDV_20260914T044226_20260914T044251_004569_008819_4799_COG.SAFE.tif` | `98edf3927463456991b31c9573f2f783bd5f4b41dca3e824c8c93609519bc37a` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-14_S1D_IW_GRDH_1SDV_20260914T044226_20260914T044251_004569_008819_4799_COG.SAFE.png` |
| 32 S1 2026-09-15 | `S1C_IW_GRDH_1SDV_20260915T043409_20260915T043434_009453_012CDD_1D41_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-15_S1C_IW_GRDH_1SDV_20260915T043409_20260915T043434_009453_012CDD_1D41_COG.SAFE.tif` | `cf141c854a55204918e48bd3392084bb9de60a665ef2c8f868d6fe4b39da1fe3` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-15_S1C_IW_GRDH_1SDV_20260915T043409_20260915T043434_009453_012CDD_1D41_COG.SAFE.png` |
| 95 S2 2026-09-15 | `S2C_MSIL2A_20260915T094031_N0512_R036_T34VFJ_20260915T125911.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-09-15_S2C_MSIL2A_20260915T094031_N0512_R036_T34VFJ_20260915T125911.SAFE.tif` | `7be93bab1399cba7b82e21d90dffbe85e560ec0e5d6b89a24be77299f984ba49` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-09-15_S2C_MSIL2A_20260915T094031_N0512_R036_T34VFJ_20260915T125911.SAFE.png` |
| 33 S1 2026-09-18 | `S1C_IW_GRDH_1SDV_20260918T161124_20260918T161149_009504_012E90_1D19_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-18_S1C_IW_GRDH_1SDV_20260918T161124_20260918T161149_009504_012E90_1D19_COG.SAFE.tif` | `0412cdc975bcc6ec0df3c4b03b6fb8038351486f3bf629bb614c13cf67d08548` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-18_S1C_IW_GRDH_1SDV_20260918T161124_20260918T161149_009504_012E90_1D19_COG.SAFE.png` |
| 34 S1 2026-09-19 | `S1D_IW_GRDH_1SDV_20260919T160330_20260919T160355_004649_008AD8_ACD2_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-19_S1D_IW_GRDH_1SDV_20260919T160330_20260919T160355_004649_008AD8_ACD2_COG.SAFE.tif` | `7eab0aea711b364342c9c32d0b76421586775718356bbe42844b84ca770195f1` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-19_S1D_IW_GRDH_1SDV_20260919T160330_20260919T160355_004649_008AD8_ACD2_COG.SAFE.png` |
| 35 S1 2026-09-20 | `S1C_IW_GRDH_1SDV_20260920T044213_20260920T044238_009526_012F4A_01B1_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-20_S1C_IW_GRDH_1SDV_20260920T044213_20260920T044238_009526_012F4A_01B1_COG.SAFE.tif` | `324c36578e5771c1d68b5f242657953b87931265afdad2d45ec5e8c201d248f8` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-20_S1C_IW_GRDH_1SDV_20260920T044213_20260920T044238_009526_012F4A_01B1_COG.SAFE.png` |
| 36 S1 2026-09-21 | `S1D_IW_GRDH_1SDV_20260921T043422_20260921T043447_004671_008BA2_0DC6_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-21_S1D_IW_GRDH_1SDV_20260921T043422_20260921T043447_004671_008BA2_0DC6_COG.SAFE.tif` | `480b778d370d2ad27c62a65ecbfc18de61a8702548d1b3a1116cb347c4f05f75` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-21_S1D_IW_GRDH_1SDV_20260921T043422_20260921T043447_004671_008BA2_0DC6_COG.SAFE.png` |
| 37 S1 2026-09-24 | `S1D_IW_GRDH_1SDV_20260924T161136_20260924T161201_004722_008D59_47D5_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-24_S1D_IW_GRDH_1SDV_20260924T161136_20260924T161201_004722_008D59_47D5_COG.SAFE.tif` | `5819cbd3c2f6410ef88fab8a6e89fdabe28e08c9e1ef50656cab032aeeca2364` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-24_S1D_IW_GRDH_1SDV_20260924T161136_20260924T161201_004722_008D59_47D5_COG.SAFE.png` |
| 38 S1 2026-09-25 | `S1C_IW_GRDH_1SDV_20260925T160318_20260925T160343_009606_0131E0_C227_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-25_S1C_IW_GRDH_1SDV_20260925T160318_20260925T160343_009606_0131E0_C227_COG.SAFE.tif` | `f96f48ea82492fc473c800ef138e7f65967599d4e66eb6d01efa1c9935a3e4aa` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-25_S1C_IW_GRDH_1SDV_20260925T160318_20260925T160343_009606_0131E0_C227_COG.SAFE.png` |
| 39 S1 2026-09-26 | `S1D_IW_GRDH_1SDV_20260926T044226_20260926T044251_004744_008E16_7826_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-26_S1D_IW_GRDH_1SDV_20260926T044226_20260926T044251_004744_008E16_7826_COG.SAFE.tif` | `934ebc0a62d423e4b23590ab8575956074fd09ee3b9ff34a12896775dfc425a8` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-26_S1D_IW_GRDH_1SDV_20260926T044226_20260926T044251_004744_008E16_7826_COG.SAFE.png` |
| 40 S1 2026-09-27 | `S1C_IW_GRDH_1SDV_20260927T043409_20260927T043434_009628_0132A0_71BD_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-27_S1C_IW_GRDH_1SDV_20260927T043409_20260927T043434_009628_0132A0_71BD_COG.SAFE.tif` | `70815dc98b4de73e0a3e05836692ea21fffbf12908b1adbec97ea992b58972dd` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-27_S1C_IW_GRDH_1SDV_20260927T043409_20260927T043434_009628_0132A0_71BD_COG.SAFE.png` |
| 102 S2 2026-09-27 | `S2A_MSIL2A_20260927T094121_N0513_R036_T34VFJ_20260927T161814.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-09-27_S2A_MSIL2A_20260927T094121_N0513_R036_T34VFJ_20260927T161814.SAFE.tif` | `5fe87087414800561887b009ff66ea6e4c36deb727f3b9e22bf1b0a075c1c3ca` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-09-27_S2A_MSIL2A_20260927T094121_N0513_R036_T34VFJ_20260927T161814.SAFE.png` |
| 103 S2 2026-09-28 | `S2C_MSIL2A_20260928T095031_N0513_R079_T34VFJ_20260928T131313.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-09-28_S2C_MSIL2A_20260928T095031_N0513_R079_T34VFJ_20260928T131313.SAFE.tif` | `8c3cd157daaec9c66ea88d271a97508f70eafd8bcc2f9e3b7f2b739f5ffcd12e` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-09-28_S2C_MSIL2A_20260928T095031_N0513_R079_T34VFJ_20260928T131313.SAFE.png` |
| 41 S1 2026-09-30 | `S1C_IW_GRDH_1SDV_20260930T161124_20260930T161149_009679_013455_93D2_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-30_S1C_IW_GRDH_1SDV_20260930T161124_20260930T161149_009679_013455_93D2_COG.SAFE.tif` | `0ac4ba2bc7007e5eda373b5d3d65fafc2e2f3c5b25f73bd2eb465038176fc84a` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-09-30_S1C_IW_GRDH_1SDV_20260930T161124_20260930T161149_009679_013455_93D2_COG.SAFE.png` |
| 42 S1 2026-10-01 | `S1D_IW_GRDH_1SDV_20261001T160330_20261001T160355_004824_0090EF_1385_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-01_S1D_IW_GRDH_1SDV_20261001T160330_20261001T160355_004824_0090EF_1385_COG.SAFE.tif` | `125e0c3a7a1ea6d4972e417610181fe1cedea97932314aa05e0db39198338c07` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-01_S1D_IW_GRDH_1SDV_20261001T160330_20261001T160355_004824_0090EF_1385_COG.SAFE.png` |
| 43 S1 2026-10-02 | `S1C_IW_GRDH_1SDV_20261002T044213_20261002T044238_009701_01351C_8A3F_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-02_S1C_IW_GRDH_1SDV_20261002T044213_20261002T044238_009701_01351C_8A3F_COG.SAFE.tif` | `376222a755370080ea8f736068a82eb44f9b15c136b81cd2ea48731771db014e` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-02_S1C_IW_GRDH_1SDV_20261002T044213_20261002T044238_009701_01351C_8A3F_COG.SAFE.png` |
| 44 S1 2026-10-03 | `S1D_IW_GRDH_1SDV_20261003T043422_20261003T043447_004846_0091BB_BEA0_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-03_S1D_IW_GRDH_1SDV_20261003T043422_20261003T043447_004846_0091BB_BEA0_COG.SAFE.tif` | `c8521b0ba3436683b82349f519bfcbc9da06063bb9302103bba51b36c303730d` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-03_S1D_IW_GRDH_1SDV_20261003T043422_20261003T043447_004846_0091BB_BEA0_COG.SAFE.png` |
| 106 S2 2026-10-03 | `S2B_MSIL2A_20261003T095029_N0513_R079_T34VFJ_20261003T133632.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-03_S2B_MSIL2A_20261003T095029_N0513_R079_T34VFJ_20261003T133632.SAFE.tif` | `7aea1affa6e6f132dfcd4e4dcb3c574cc9a1bff38a041f1366717a8fe096f1c0` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-03_S2B_MSIL2A_20261003T095029_N0513_R079_T34VFJ_20261003T133632.SAFE.png` |
| 45 S1 2026-10-06 | `S1D_IW_GRDH_1SDV_20261006T161136_20261006T161201_004897_009372_E3C5_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-06_S1D_IW_GRDH_1SDV_20261006T161136_20261006T161201_004897_009372_E3C5_COG.SAFE.tif` | `6e67d20608a3bdabec24c4566ede28db1c243112e7b54ca976235cfd499c0ac9` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-06_S1D_IW_GRDH_1SDV_20261006T161136_20261006T161201_004897_009372_E3C5_COG.SAFE.png` |
| 108 S2 2026-10-07 | `S2A_MSIL2A_20261007T094041_N0513_R036_T34VFJ_20261007T144706.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-07_S2A_MSIL2A_20261007T094041_N0513_R036_T34VFJ_20261007T144706.SAFE.tif` | `21bb9d8ee9b82f3a896a51208a6dbc4676f802b7b6b1df483bd6fd588c184282` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-07_S2A_MSIL2A_20261007T094041_N0513_R036_T34VFJ_20261007T144706.SAFE.png` |
| 46 S1 2026-10-07 | `S1C_IW_GRDH_1SDV_20261007T160318_20261007T160343_009781_0137B4_F45E_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-07_S1C_IW_GRDH_1SDV_20261007T160318_20261007T160343_009781_0137B4_F45E_COG.SAFE.tif` | `f0e6bda0316605b7d44941d603cab57795476da6f942fca5f3a056a902a7a55b` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-07_S1C_IW_GRDH_1SDV_20261007T160318_20261007T160343_009781_0137B4_F45E_COG.SAFE.png` |
| 47 S1 2026-10-08 | `S1D_IW_GRDH_1SDV_20261008T044226_20261008T044251_004919_00943F_D214_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-08_S1D_IW_GRDH_1SDV_20261008T044226_20261008T044251_004919_00943F_D214_COG.SAFE.tif` | `1ee66533bf7b9e0b086c61f531064d85bf070d1c8f1fb517c3f548871edfe391` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-08_S1D_IW_GRDH_1SDV_20261008T044226_20261008T044251_004919_00943F_D214_COG.SAFE.png` |
| 48 S1 2026-10-09 | `S1C_IW_GRDH_1SDV_20261009T043409_20261009T043434_009803_013871_90EA_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-09_S1C_IW_GRDH_1SDV_20261009T043409_20261009T043434_009803_013871_90EA_COG.SAFE.tif` | `4559d3a8585ad603edc7a24d414b92a84c4a08f6bc2a93a2844be7ed8670e150` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-09_S1C_IW_GRDH_1SDV_20261009T043409_20261009T043434_009803_013871_90EA_COG.SAFE.png` |
| 110 S2 2026-10-10 | `S2B_MSIL2A_20261010T094029_N0513_R036_T34VFJ_20261010T133655.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-10_S2B_MSIL2A_20261010T094029_N0513_R036_T34VFJ_20261010T133655.SAFE.tif` | `d0cfe9492dc4d0e64d1aee3a4d02b97c0e616904831c9d6bb41aadbb759b11e5` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-10_S2B_MSIL2A_20261010T094029_N0513_R036_T34VFJ_20261010T133655.SAFE.png` |
| 111 S2 2026-10-10 | `S2A_MSIL2A_20261010T095051_N0513_R079_T34VFJ_20261010T144103.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-10_S2A_MSIL2A_20261010T095051_N0513_R079_T34VFJ_20261010T144103.SAFE.tif` | `e87af03c2930a4d78b9b2ac383b76743c8d407ba432322d370fcebd1f29612e4` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-10_S2A_MSIL2A_20261010T095051_N0513_R079_T34VFJ_20261010T144103.SAFE.png` |
| 49 S1 2026-10-12 | `S1C_IW_GRDH_1SDV_20261012T161124_20261012T161149_009854_013A3D_F362_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-12_S1C_IW_GRDH_1SDV_20261012T161124_20261012T161149_009854_013A3D_F362_COG.SAFE.tif` | `ea2028c468c1e76166caf96e5f93ce6e96a48abb638153db272d4fb1ac996865` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-12_S1C_IW_GRDH_1SDV_20261012T161124_20261012T161149_009854_013A3D_F362_COG.SAFE.png` |
| 50 S1 2026-10-13 | `S1D_IW_GRDH_1SDV_20261013T160330_20261013T160355_004999_00970F_CCA5_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-13_S1D_IW_GRDH_1SDV_20261013T160330_20261013T160355_004999_00970F_CCA5_COG.SAFE.tif` | `6d9b214a2889c813d7d495128787450a3f7d710896cb670bf4e1a7208881cc75` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-13_S1D_IW_GRDH_1SDV_20261013T160330_20261013T160355_004999_00970F_CCA5_COG.SAFE.png` |
| 51 S1 2026-10-14 | `S1C_IW_GRDH_1SDV_20261014T044213_20261014T044238_009876_013B09_C04B_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-14_S1C_IW_GRDH_1SDV_20261014T044213_20261014T044238_009876_013B09_C04B_COG.SAFE.tif` | `e25918fc02a88262ad5ca371eefe34c2558cf8e38de8758035803fb6d0c4d728` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-14_S1C_IW_GRDH_1SDV_20261014T044213_20261014T044238_009876_013B09_C04B_COG.SAFE.png` |
| 52 S1 2026-10-15 | `S1D_IW_GRDH_1SDV_20261015T043422_20261015T043447_005021_0097D8_5CBA_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-15_S1D_IW_GRDH_1SDV_20261015T043422_20261015T043447_005021_0097D8_5CBA_COG.SAFE.tif` | `7a50bb524e4330957303802901fd8462abb04151a023c5d7918e086eb824c341` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-15_S1D_IW_GRDH_1SDV_20261015T043422_20261015T043447_005021_0097D8_5CBA_COG.SAFE.png` |
| 114 S2 2026-10-17 | `S2A_MSIL2A_20261017T094111_N0513_R036_T34VFJ_20261017T163803.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-17_S2A_MSIL2A_20261017T094111_N0513_R036_T34VFJ_20261017T163803.SAFE.tif` | `806d3d2f00b59baea0cbca4bfd4b576e641de9be7843922a7ff7c698829b1c95` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-17_S2A_MSIL2A_20261017T094111_N0513_R036_T34VFJ_20261017T163803.SAFE.png` |
| 115 S2 2026-10-18 | `S2C_MSIL2A_20261018T095031_N0513_R079_T34VFJ_20261018T134609.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-18_S2C_MSIL2A_20261018T095031_N0513_R079_T34VFJ_20261018T134609.SAFE.tif` | `fc5d5b9956417ca78dc714840d63f0de0c1de070fff838c64714be1403ba95c6` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-18_S2C_MSIL2A_20261018T095031_N0513_R079_T34VFJ_20261018T134609.SAFE.png` |
| 53 S1 2026-10-18 | `S1D_IW_GRDH_1SDV_20261018T161136_20261018T161201_005072_009987_68D2_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-18_S1D_IW_GRDH_1SDV_20261018T161136_20261018T161201_005072_009987_68D2_COG.SAFE.tif` | `343c1757def82ca492fa7092e35ee14f41bd31f2db3f46992be179d9d1f3ccec` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-18_S1D_IW_GRDH_1SDV_20261018T161136_20261018T161201_005072_009987_68D2_COG.SAFE.png` |
| 54 S1 2026-10-19 | `S1C_IW_GRDH_1SDV_20261019T160318_20261019T160343_009956_013D93_6022_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-19_S1C_IW_GRDH_1SDV_20261019T160318_20261019T160343_009956_013D93_6022_COG.SAFE.tif` | `feb0c1918ba7fd5082c948785598f53609705fa848090b278ae3932b720b253d` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-19_S1C_IW_GRDH_1SDV_20261019T160318_20261019T160343_009956_013D93_6022_COG.SAFE.png` |
| 55 S1 2026-10-20 | `S1D_IW_GRDH_1SDV_20261020T044226_20261020T044251_005094_009A43_DE2F_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-20_S1D_IW_GRDH_1SDV_20261020T044226_20261020T044251_005094_009A43_DE2F_COG.SAFE.tif` | `ce1a4b0514d987f709914af601de508dfba3abdee4bf4985b4ec585839192739` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-20_S1D_IW_GRDH_1SDV_20261020T044226_20261020T044251_005094_009A43_DE2F_COG.SAFE.png` |
| 116 S2 2026-10-20 | `S2A_MSIL2A_20261020T095041_N0513_R079_T34VFJ_20261020T150311.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-20_S2A_MSIL2A_20261020T095041_N0513_R079_T34VFJ_20261020T150311.SAFE.tif` | `3f286fda6a27df83df1110fe7ebf5838b4ac6b679a9f8d3d3af0701ddc58cdef` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-20_S2A_MSIL2A_20261020T095041_N0513_R079_T34VFJ_20261020T150311.SAFE.png` |
| 56 S1 2026-10-21 | `S1C_IW_GRDH_1SDV_20261021T043409_20261021T043434_009978_013E60_8D5F_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-21_S1C_IW_GRDH_1SDV_20261021T043409_20261021T043434_009978_013E60_8D5F_COG.SAFE.tif` | `265c4669d1115b95411c7f37e2355abb440786a726932880b65c735cf44a8a5f` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-21_S1C_IW_GRDH_1SDV_20261021T043409_20261021T043434_009978_013E60_8D5F_COG.SAFE.png` |
| 57 S1 2026-10-24 | `S1C_IW_GRDH_1SDV_20261024T161123_20261024T161148_010029_014036_4420_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-24_S1C_IW_GRDH_1SDV_20261024T161123_20261024T161148_010029_014036_4420_COG.SAFE.tif` | `c999a9b7fd69f8806d1326fc07d6d3418ca084956e69f56044bba62dd661f974` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-24_S1C_IW_GRDH_1SDV_20261024T161123_20261024T161148_010029_014036_4420_COG.SAFE.png` |
| 58 S1 2026-10-25 | `S1D_IW_GRDH_1SDV_20261025T160330_20261025T160355_005174_009D10_423E_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-25_S1D_IW_GRDH_1SDV_20261025T160330_20261025T160355_005174_009D10_423E_COG.SAFE.tif` | `baf2c1ec80fdfa326232abe8fb343faf3ab383f2c5a11ca31d5f8e8a95b8c625` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-25_S1D_IW_GRDH_1SDV_20261025T160330_20261025T160355_005174_009D10_423E_COG.SAFE.png` |
| 59 S1 2026-10-26 | `S1C_IW_GRDH_1SDV_20261026T044212_20261026T044237_010051_0140F7_7B5D_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-26_S1C_IW_GRDH_1SDV_20261026T044212_20261026T044237_010051_0140F7_7B5D_COG.SAFE.tif` | `b20b4b4654974d71f0643ebc5d5a440cdd33913ff3e4e2eeb2a9b54c35da9f03` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-26_S1C_IW_GRDH_1SDV_20261026T044212_20261026T044237_010051_0140F7_7B5D_COG.SAFE.png` |
| 119 S2 2026-10-27 | `S2A_MSIL2A_20261027T094041_N0513_R036_T34VFJ_20261027T144648.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-27_S2A_MSIL2A_20261027T094041_N0513_R036_T34VFJ_20261027T144648.SAFE.tif` | `64a1ad580d3f706f766fe23e288e4fa86faf03326c5083f5782aa041b0848eab` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-10-27_S2A_MSIL2A_20261027T094041_N0513_R036_T34VFJ_20261027T144648.SAFE.png` |
| 60 S1 2026-10-30 | `S1D_IW_GRDH_1SDV_20261030T161136_20261030T161201_005247_009F80_58E4_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-30_S1D_IW_GRDH_1SDV_20261030T161136_20261030T161201_005247_009F80_58E4_COG.SAFE.tif` | `398cacc85a72170fece3d3e686504c976cb55dc011a1106846a4dfb991120629` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-30_S1D_IW_GRDH_1SDV_20261030T161136_20261030T161201_005247_009F80_58E4_COG.SAFE.png` |
| 61 S1 2026-10-31 | `S1C_IW_GRDH_1SDV_20261031T160317_20261031T160342_010131_014387_D61E_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-31_S1C_IW_GRDH_1SDV_20261031T160317_20261031T160342_010131_014387_D61E_COG.SAFE.tif` | `29ad93328b5d375ad529f057a30ca2e55cfaf375f70302cdb60e41a2bbbad5e1` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-10-31_S1C_IW_GRDH_1SDV_20261031T160317_20261031T160342_010131_014387_D61E_COG.SAFE.png` |
| 62 S1 2026-11-01 | `S1D_IW_GRDH_1SDV_20261101T044225_20261101T044250_005269_00A04F_CCCA_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-01_S1D_IW_GRDH_1SDV_20261101T044225_20261101T044250_005269_00A04F_CCCA_COG.SAFE.tif` | `247508e7f0954c5a83ea8325698cff562d9e48ef7250df8ff9debdab4f8c8de4` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-01_S1D_IW_GRDH_1SDV_20261101T044225_20261101T044250_005269_00A04F_CCCA_COG.SAFE.png` |
| 63 S1 2026-11-02 | `S1C_IW_GRDH_1SDV_20261102T043409_20261102T043434_010153_014440_0BD9_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-02_S1C_IW_GRDH_1SDV_20261102T043409_20261102T043434_010153_014440_0BD9_COG.SAFE.tif` | `00e334410a3a6a1ecce53e78567ad693c6aea1ce7b7a7c5cdac713bf2abee4f0` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-02_S1C_IW_GRDH_1SDV_20261102T043409_20261102T043434_010153_014440_0BD9_COG.SAFE.png` |
| 123 S2 2026-11-04 | `S2C_MSIL2A_20261104T094151_N0513_R036_T34VFJ_20261104T112603.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-11-04_S2C_MSIL2A_20261104T094151_N0513_R036_T34VFJ_20261104T112603.SAFE.tif` | `5889d2c1fa6cb215b4983358f601131a4a4c625e4475f5ba37fc3b0acf4f0212` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-11-04_S2C_MSIL2A_20261104T094151_N0513_R036_T34VFJ_20261104T112603.SAFE.png` |
| 64 S1 2026-11-05 | `S1C_IW_GRDH_1SDV_20261105T161124_20261105T161149_010204_0145F9_A73F_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-05_S1C_IW_GRDH_1SDV_20261105T161124_20261105T161149_010204_0145F9_A73F_COG.SAFE.tif` | `4886be8c38c31a26f127a72a47173c1f2aa563cbcc45109b7832d60eb929ea6d` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-05_S1C_IW_GRDH_1SDV_20261105T161124_20261105T161149_010204_0145F9_A73F_COG.SAFE.png` |
| 124 S2 2026-11-06 | `S2A_MSIL2A_20261106T094121_N0513_R036_T34VFJ_20261106T143053.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-11-06_S2A_MSIL2A_20261106T094121_N0513_R036_T34VFJ_20261106T143053.SAFE.tif` | `aab4d05f59d9e49aada97183ebd0441508f079fe62e11e3a6aa9a05f3556a96c` | `/root/forest_ai_satellite_data/satellite/1/S2/2026-11-06_S2A_MSIL2A_20261106T094121_N0513_R036_T34VFJ_20261106T143053.SAFE.png` |
| 65 S1 2026-11-06 | `S1D_IW_GRDH_1SDV_20261106T160330_20261106T160355_005349_00A30A_9FFD_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-06_S1D_IW_GRDH_1SDV_20261106T160330_20261106T160355_005349_00A30A_9FFD_COG.SAFE.tif` | `e6d47230a1b6f2d3f7eda84f8d86be13c8b08dbd6f7270039041a6fec5dfa9a2` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-06_S1D_IW_GRDH_1SDV_20261106T160330_20261106T160355_005349_00A30A_9FFD_COG.SAFE.png` |
| 66 S1 2026-11-07 | `S1C_IW_GRDH_1SDV_20261107T044212_20261107T044237_010226_0146C0_159D_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-07_S1C_IW_GRDH_1SDV_20261107T044212_20261107T044237_010226_0146C0_159D_COG.SAFE.tif` | `a56d4070d561a3ebd450c33013462823b5dac07e53101ddcbfe9851896d8fd8a` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-07_S1C_IW_GRDH_1SDV_20261107T044212_20261107T044237_010226_0146C0_159D_COG.SAFE.png` |
| 67 S1 2026-11-08 | `S1D_IW_GRDH_1SDV_20261108T043422_20261108T043447_005371_00A3DA_39FB_COG.SAFE` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-08_S1D_IW_GRDH_1SDV_20261108T043422_20261108T043447_005371_00A3DA_39FB_COG.SAFE.tif` | `fbf437f653cbb508bb3c2345ec2cbe693fb1fe6170a0ab2447c9d2b65e9e587d` | `/root/forest_ai_satellite_data/satellite/1/S1/2026-11-08_S1D_IW_GRDH_1SDV_20261108T043422_20261108T043447_005371_00A3DA_39FB_COG.SAFE.png` |
