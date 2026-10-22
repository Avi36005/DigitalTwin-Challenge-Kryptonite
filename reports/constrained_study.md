# Peak-aware constrained selection — `gt-constrained-2026-10-21` (D-053)

Protocol committed before any formal fit (sha256 `93b45c3ec35c`, code `ba4c39c`); run started 2026-10-21T17:06:28+00:00 UTC; development choices for all folds frozen 2026-10-21T18:08:48+00:00; outer folds opened 2026-10-21T18:08:48+00:00; finished 2026-10-21T18:09:10+00:00. Fresh fits: 1,490 logical (2,930 physical incl. early-stopping passes; LightGBM 1,006, CatBoost 484), 2638 s fitting, 3760 s wall; failures 0. LightGBM 4.7.0, CatBoost 1.2.10, split `e3695ca98334797c`.

Roles: every fit, early-stopping tail, configuration/correction/family choice, trend scale and warning threshold used outer **development** people only; the 2 calibration people per fold were used only for range quantiles of the same frozen predictor that was then scored on the assessment people. Motivation: D-052's already-seen high-target (+1.70) and workload failures and its mixed-fit range calibration. The 14 people were inspected in earlier studies: internal validation, not independent confirmation. Absolute MAE is not comparable with D-052 (9–10 fitting people per fold here instead of 11–12); the matched comparison below is authoritative.

## Matched assessment table (macro per-participant MAE, mg/dL; identical issued origins)

| Procedure | 60 min | 30 min | 60 min pooled | 60 min population | 60 min, target > 180 | signed bias > 180 | rising > 2 | steady | falling | first 24 h | availability 30 / 60 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **S — constrained selected procedure** | **22.00** | 13.89 | 22.00 | 23.15 | 39.45 | -22.4 | 39.54 | 20.11 | 26.32 | 24.38 | 100.0 % / 100.0 % |
| R0 — refitted serving recipe (and R0-P points) | **23.20** | 14.39 | 23.19 | 25.34 | 38.39 | -27.0 | 39.81 | 21.45 | 26.65 | 24.92 | 100.0 % / 100.0 % |
| Persistence | **24.47** | 15.34 | 24.47 | 24.47 | 45.03 | -14.0 | 42.44 | 21.78 | 35.91 | 26.19 | 100.0 % / 100.0 % |
| Bounded linear trend (window/damping chosen on development) | **24.71** | 14.66 | 24.71 | 24.71 | 44.63 | -10.3 | 52.36 | 21.83 | 32.34 | 27.93 | 100.0 % / 100.0 % |

Common origins: 39,646 (30 min), 39,553 (60 min); high-target column: people with ≥ 50 such origins (14 at 60 min).

## Paired differences (first minus second; negative = lower error; 95 % participant bootstrap, 2,000 resamples)

| Comparison | 60 min personalised | 60 min population only | 30 min personalised | people better (60) |
|---|---|---|---|---|
| S vs R0 | -1.19 [-2.09, -0.39] | -2.19 [-3.85, -0.74] | -0.50 [-0.77, -0.24] | 11 of 14 |
| S vs persistence | -2.46 [-3.00, -1.96] | — | -1.45 [-1.81, -1.12] | 14 of 14 |
| R0 vs persistence | -1.27 [-2.45, +0.01] | — | -0.95 [-1.38, -0.51] | 12 of 14 |
| S vs linear_trend | -2.71 [-3.44, -1.90] | — | -0.77 [-1.01, -0.54] | 13 of 14 |

**Primary point gate (S vs R0): NOT MET** — 60-min difference -1.19 (≤ −0.50: yes), interval upper -0.39 (< 0: yes); 30-min change -0.50 (≤ +0.25: yes); high-target change 1.07 (≤ +1.0: no); availability drop 0.00 pt (≤ 0.5: yes).

## 60-minute warning on assessment people (thresholds chosen on development inner folds per outer fold)

| Policy | Thresholds by fold | Onsets | Detected / missed | Warned ≥ 15 / 30 / 60 min (all onsets) | False alarms / observed day | Precision | Time in warning | Episode median (p90) | Qualified lead median (IQR) |
|---|---|---|---|---|---|---|---|---|---|
| S | 0, 0, -5, -5, -5 | 329 | 284 / 45 | 38.6 % / 21.9 % / 8.5 % | 1.15 | 0.64 | 6.1 % | 10 (45) min | 10 (5–30) min |
| R0-P | 5, 0, 0, 0, 0 | 329 | 256 / 73 | 31.9 % / 16.4 % / 5.2 % | 1.20 | 0.61 | 5.0 % | 10 (40) min | 10 (5–21) min |
| R0-serving-threshold | -10, -10, -10, -10, -10 | 329 | 317 / 12 | 65.3 % / 42.6 % / 21.3 % | 2.20 | 0.51 | 14.3 % | 15 (85) min | 20 (10–50) min |
| S-1day | 5, 5, 0, 5, 5 | 329 | 215 / 114 | 23.7 % / 12.2 % / 4.0 % | 0.64 | 0.71 | 3.0 % | 10 (32) min | 10 (5–20) min |
| R0-1day | 15, 5, 5, 10, 5 | 329 | 184 / 145 | 19.5 % / 10.6 % / 2.7 % | 0.70 | 0.65 | 2.6 % | 10 (25) min | 10 (5–20) min |

False alarms per observed day use gap-respecting exposure of issued origins; time in warning uses the same step on eligible issued origins with a resolved label; censored warnings are unresolved, never false alarms. S-1day / R0-1day: development-selected ≈ 1 false alarm/day operating points (reported only). R0-serving-threshold: the serving margin −10 (reported only).

**Operational gate (S vs R0-P): PASSED** — false alarms -0.04/day (≤ +0.10), time in warning 1.1 pt (≤ +2.0), warned ≥ 30 min 5.5 pt (≥ −2.0).

## 80 % ranges (one frozen predictor per fold: calibrated on its calibration people, scored on assessment people)

| Procedure | Method | 30 min coverage (mean width) | 60 min coverage (mean width) | 60 min per person | 60 min rising > 2 | rising > 1 | steady | falling | first 24 h |
|---|---|---|---|---|---|---|---|---|---|
| S | global split-conformal (primary) | 79.4 % (42.3) | 77.3 % (62.9) | 66.7 %–89.2 % | 46.2 % (n 1289) | 56.3 % | 80.9 % | 67.7 % | 76.0 % |
| S | past-trend-scaled (secondary) | 79.3 % (41.5) | 77.5 % (62.6) | 67.6 %–89.3 % | 74.8 % (n 1289) | 75.3 % | 78.0 % | 75.8 % | 76.2 % |
| R0 | global split-conformal (primary) | 79.1 % (43.8) | 78.5 % (68.6) | 62.6 %–91.4 % | 50.2 % (n 1289) | 60.2 % | 81.7 % | 70.3 % | 78.2 % |
| R0 | past-trend-scaled (secondary) | 79.1 % (43.3) | 78.8 % (68.7) | 61.5 %–91.5 % | 76.6 % (n 1289) | 77.7 % | 79.2 % | 76.8 % | 79.6 % |

**Range guardrails (primary range of S): PASSED** — identity yes, finite yes, coverage_30 yes, per_person_min_30 yes, width_30 yes, coverage_60 yes, per_person_min_60 yes, width_60 yes, rapid_rise_60 yes. Empirical coverage over overlapping windows of few people is not an individual guarantee.

## All gates: **NOT MET**

## Development choices per outer fold (inner folds only)

| Fold | Selected | 30-min member | 60-min member | threshold (S / R0-P) | feasible candidates LGB 30/60, CB 30/60 | pairs (with feasible warning) |
|---|---|---|---|---|---|---|
| outer-1 | lightgbm | `lgb-T1-F0-W1-l1|k192_hl720|30` | `lgb-T2-F1-W1-l2|k96_hl720|60` | 0 / 5 | 328/145, 187/68 | 18 (17) |
| outer-2 | catboost | `cb-C3-F1-W1|k24_hl240|30` | `cb-C2-F1-W1|k24_hl720|60` | 0 / 0 | 386/142, 166/50 | 18 (16) |
| outer-3 | lightgbm | `lgb-T2-F0-W1-l1|k192_hl720|30` | `lgb-T2-F0-W1-l1|k192_hl720|60` | -5 / 0 | 390/230, 178/46 | 18 (17) |
| outer-4 | lightgbm | `lgb-T2-F1-W1-l1|k96_hl720|30` | `lgb-T0-F1-WP-l1|k192_hl240|60` | -5 / 0 | 386/95, 186/110 | 18 (15) |
| outer-5 | catboost | `cb-C2-F1-W1|k24_hl720|30` | `cb-C0-F1-W1|k96_hl720|60` | -5 / 0 | 353/210, 173/141 | 18 (16) |

Regenerate: `uv run python scripts/constrained_study.py render`; check: `uv run python scripts/constrained_study.py validate`. Raw numbers: `artifacts/research/gt-constrained-2026-10-21/summary.json`, inner scores `inner_scores.parquet`, predictions `assessment_predictions.parquet`.
