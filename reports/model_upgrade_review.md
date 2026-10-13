# Model upgrade review

Experiment `gt-nested-2026-10-12-v1` (nested participant-level benchmark + reserved external cohort). Every number below is generated from saved prediction and event records by `glucotwin research report`; nothing is typed in by hand.

| Model | Role | Status |
|---|---|---|
| LightGBM v2 (`lightgbm.dyn-v2.gt-primary-2026-10-11-v2`) | demo model before this experiment | not serving (registry serves `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`) |
| Ridge (`ridge.cgm-only-v1.gt-nested-2026-10-12-v1`) | five-minute candidate | evaluated, not promoted |
| LightGBM (`lightgbm.cgm15-v1.gt-nested-2026-10-12-v1`) | external check (separate 15-minute model) | evaluated once on ShanghaiT2DM |

**Recommendation by the pre-specified rule: Replace the serving recipe with the frozen candidate — rule met; promotion is a separate, explicit decision.** The registry serves `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`; no candidate of this experiment has been promoted.

* 30 min, outer folds: selected minus refit v2 recipe -0.64 mg/dL, 95 % CI [-0.98, -0.32] (12 of 14 people improved).
* 60 min, outer folds: selected minus refit v2 recipe -1.95 mg/dL, 95 % CI [-2.83, -1.04] (13 of 14 people improved).
* 60-minute warnings: 301 of 329 onsets at 1.31 false alarms per observed day (selected, workload rule) versus 329 of 329 at 2.80 (v2 recipe, margin −30).
* Trade-off: when the 60-minute target was above 180 mg/dL, the selected pipeline's MAE was 39.71 versus 37.00 mg/dL for the v2 recipe (worse on large highs; paired difference +2.71 [+0.28, +5.11] over 14 people). This rule did not bound it; the next protocol does (gt-nested-2026-10-12-v2).
* Chosen per outer fold: `ridge:cgm-only-v1` in 4 of 5, `lightgbm_l1:cgm-only-v1` in 1 of 5; deployment candidate (all 14 people): `ridge:cgm-only-v1`.
* Scope: internal validation on 14 already-inspected CGMacros people; the 5-minute candidate has no independent 5-minute external test. Promotion was NOT executed; it needs an explicit decision.

## 1. Research question and current limitations

Does a tuned LightGBM (L2 or L1 objective), CatBoost, or a different input set forecast glucose 30 and 60 minutes ahead better than the v2 serving recipe for people the model has never seen — and does a portable CGM-only model trained on CGMacros transfer to an independent cohort recorded with a different device, cadence and country? The model serving when this experiment was declared (LightGBM dyn-v2 + adaptation, experiment v2) was selected on the same 14 CGMacros people and its test segment was already inspected, so it could not answer either question.

## 2. Provenance and inclusion

```text
CGMacros 1.0.0 (PhysioNet, 45 people) ──► Type 2 + >=72 h Dexcom: 14 ──► 5 outer participant folds
   └─ 31 pre-diabetes / no diabetes: replay only (not trained, tuned or assessed)
ShanghaiT2DM (figshare v5, 100 people, 109 recordings) ──► >=72 observed h: 98 ──► reserved external cohort (opened once)
AI-READI v3 (2,280 people, publisher) ──► access_required: 0 imported
Glucose-ML (catalog) ──► discovery only: 0 imported (would duplicate CGMacros / Shanghai / AI-READI)
```

## 3. Counts actually used

| | CGMacros | ShanghaiT2DM |
|---|---:|---:|
| Imported real participants | 45 | 100 |
| Eligible for this experiment | 14 | 98 |
| Outer-fold assessment groups | 3/3/3/3/2 | — |
| Development (training) people per outer fold | 9/9/9/9/10 | 0 (never trained on) |
| Calibration people per outer fold | 2/2/2/2/2 | 0 |
| Assessed people | 14 (internal, each once) | 98 (external) |
| Final candidate: development / calibration people | 12 / 2 | — |

Native readings, observed hours and exclusions: `reports/dataset_expansion_audit.md`.

## 4. Frozen evaluation design

Protocol `configs/experiments/gt-nested-2026-10-12-v1.yaml`, declared and frozen before any fit (hashes in `reports/nested_benchmark_report.md`). Five outer folds grouped by participant; inside each, a reserved calibration group and three inner participant folds. Every choice (family, objective, feature set, hyperparameters, adaptation, warning threshold, interval quantile) was made on inner or calibration data; the outer participants of a fold were assessed once with the frozen pipeline. The external cohort was never used for any choice.

## 5. Same-input family comparisons and feature ablations

| Pipeline | MAE 30 | MAE 60 | RMSE 30 | RMSE 60 | High-glucose MAE 60 | Availability | People |
|---|---:|---:|---:|---:|---:|---:|---:|
| Selected by the declared rule (per fold) — selected personalization | 13.88 | 22.30 | 20.71 | 32.40 | 39.71 | 99.55 % | 14 |
| Current v2 serving recipe (refit per fold), dyn-v2 — v2 adaptation policy | 14.52 | 24.25 | 21.04 | 33.60 | 37.00 | 99.55 % | 14 |
| Persistence — population only | 15.34 | 24.47 | 23.14 | 36.15 | 45.03 | 99.55 % | 14 |
| LightGBM (L2 objective, L2 stopping), dyn-v2 — population only | 14.85 | 25.27 | 21.25 | 34.24 | 37.61 | 99.55 % | 14 |
| LightGBM (L1 objective, macro-MAE stopping), dyn-v2 — population only | 14.46 | 23.55 | 21.24 | 33.73 | 41.49 | 99.55 % | 14 |
| CatBoost (RMSE), dyn-v2 — population only | 15.25 | 25.34 | 21.64 | 34.50 | 37.25 | 99.55 % | 14 |
| LightGBM (L2 objective, L2 stopping), cgm-only-v1 — population only | 14.25 | 22.84 | 21.00 | 32.77 | 39.51 | 99.55 % | 14 |
| LightGBM (L2 objective, L2 stopping), dyn-prof-v2 — population only | 15.19 | 24.52 | 21.48 | 33.69 | 38.70 | 99.55 % | 14 |

| Comparison (a minus b, mg/dL) | Horizon | Mean difference | 95 % CI | Improved / worsened |
|---|---:|---:|---|---|
| Selected pipeline minus persistence | 30 | -1.46 | [-1.90, -1.02] | 13 / 1 of 14 |
| Selected pipeline minus persistence | 60 | -2.16 | [-2.92, -1.38] | 13 / 1 of 14 |
| Selected pipeline: personalization minus population only | 30 | -0.22 | [-0.42, -0.06] | 11 / 3 of 14 |
| Selected pipeline: personalization minus population only | 60 | -0.47 | [-0.94, -0.10] | 11 / 3 of 14 |
| Selected pipeline: best grid adaptation minus v2 policy | 30 | -0.09 | [-0.20, +0.00] | 9 / 5 of 14 |
| Selected pipeline: best grid adaptation minus v2 policy | 60 | -0.28 | [-0.56, -0.05] | 11 / 3 of 14 |
| Selected pipeline minus current v2 recipe | 30 | -0.64 | [-0.98, -0.32] | 12 / 2 of 14 |
| Selected pipeline minus current v2 recipe | 60 | -1.95 | [-2.83, -1.04] | 13 / 1 of 14 |
| High-glucose error (target > 180): selected minus current v2 recipe | 30 | +0.66 | [-0.19, +1.77] | 3 / 11 of 14 |
| High-glucose error (target > 180): selected minus current v2 recipe | 60 | +2.71 | [+0.28, +5.11] | 4 / 10 of 14 |
| Activity inputs: LightGBM L2 dyn-v2 minus CGM-only | 30 | +0.61 | [+0.18, +1.09] | 4 / 10 of 14 |
| Activity inputs: LightGBM L2 dyn-v2 minus CGM-only | 60 | +2.42 | [+1.21, +3.86] | 1 / 13 of 14 |
| Profile inputs: LightGBM L2 dyn-prof-v2 minus dyn-v2 | 30 | +0.34 | [-0.28, +0.89] | 4 / 10 of 14 |
| Profile inputs: LightGBM L2 dyn-prof-v2 minus dyn-v2 | 60 | -0.75 | [-2.19, +0.61] | 7 / 7 of 14 |
| L1 objective + macro-MAE stopping minus L2 (cgm-only-v1, population) | 30 | -0.26 | [-0.50, -0.01] | 10 / 4 of 14 |
| L1 objective + macro-MAE stopping minus L2 (cgm-only-v1, population) | 60 | -0.44 | [-1.11, +0.19] | 9 / 5 of 14 |
| CatBoost minus LightGBM L2 (cgm-only-v1, population) | 30 | -0.08 | [-0.17, +0.00] | 9 / 5 of 14 |
| CatBoost minus LightGBM L2 (cgm-only-v1, population) | 60 | -0.04 | [-0.19, +0.09] | 6 / 8 of 14 |
| L1 objective + macro-MAE stopping minus L2 (dyn-v2, population) | 30 | -0.40 | [-0.76, -0.08] | 10 / 4 of 14 |
| L1 objective + macro-MAE stopping minus L2 (dyn-v2, population) | 60 | -1.72 | [-2.92, -0.68] | 12 / 2 of 14 |
| CatBoost minus LightGBM L2 (dyn-v2, population) | 30 | +0.39 | [-0.08, +0.92] | 5 / 9 of 14 |
| CatBoost minus LightGBM L2 (dyn-v2, population) | 60 | +0.07 | [-0.67, +0.82] | 6 / 8 of 14 |
| L1 objective + macro-MAE stopping minus L2 (dyn-prof-v2, population) | 30 | -0.76 | [-1.21, -0.33] | 11 / 3 of 14 |
| L1 objective + macro-MAE stopping minus L2 (dyn-prof-v2, population) | 60 | -1.02 | [-1.98, -0.17] | 11 / 3 of 14 |
| CatBoost minus LightGBM L2 (dyn-prof-v2, population) | 30 | -0.22 | [-0.48, +0.03] | 7 / 7 of 14 |
| CatBoost minus LightGBM L2 (dyn-prof-v2, population) | 60 | +0.03 | [-0.89, +0.79] | 6 / 8 of 14 |
| Best CatBoost minus best LightGBM L2 (each with its selected personalization) | 30 | -0.19 | [-0.38, -0.04] | 10 / 4 of 14 |
| Best CatBoost minus best LightGBM L2 (each with its selected personalization) | 60 | -0.27 | [-0.71, +0.05] | 10 / 4 of 14 |
| Best LightGBM L1 minus best LightGBM L2 (each with its selected personalization) | 30 | -0.29 | [-0.52, -0.03] | 11 / 3 of 14 |
| Best LightGBM L1 minus best LightGBM L2 (each with its selected personalization) | 60 | -0.42 | [-1.00, +0.15] | 9 / 5 of 14 |

## 6. Cold start and adaptation

* 60 min, population only: first 6 h 24.78, 6–24 h 24.17, after 24 h 22.61 mg/dL.
* 60 min, selected personalization: first 6 h 25.04, 6–24 h 23.84, after 24 h 22.11 mg/dL.
* Adaptation per fold: outer-1: v2_policy; outer-2: v2_policy; outer-3: v2_policy; outer-4: v2_policy; outer-5: v2_policy; final: v2_policy.

## 7. Warning burden and prediction ranges

| Pipeline | Policy | Thresholds by fold | Recall (95 % CI) | Missed / onsets | Precision | False alarms per observed day (95 % CI) | per eligible day | Warnings per observed day | Censored | Qualified lead median (IQR) |
|---|---|---|---|---|---:|---|---:|---:|---:|---|
| Persistence — population only | workload ≤ 2.0/day (primary) | -10, -10, -10, -10, -10 | 0.860 [0.81, 0.90] | 46 / 329 | 0.603 | 1.35 [1.12, 1.59] | 2.07 | 3.41 | 2 | 10.0 (5.0–25.0) |
| Persistence — population only | max F1 (v1/v2 rule) | -10, -10, -10, -10, -10 | 0.860 [0.81, 0.90] | 46 / 329 | 0.603 | 1.35 [1.12, 1.59] | 2.07 | 3.41 | 2 | 10.0 (5.0–25.0) |
| Persistence — population only | budget 0.5/day | +0, +0, +0, +0, +0 | 0.182 [0.14, 0.23] | 269 / 329 | 0.638 | 0.25 [0.16, 0.33] | 0.38 | 0.69 | 1 | 5.0 (5.0–15.0) |
| Persistence — population only | budget 1.0/day | +0, +0, +0, +0, +0 | 0.182 [0.14, 0.23] | 269 / 329 | 0.638 | 0.25 [0.16, 0.33] | 0.38 | 0.69 | 1 | 5.0 (5.0–15.0) |
| Persistence — population only | budget 3.0/day | -30, -20, -30, -30, -30 | 0.994 [0.98, 1.00] | 2 / 329 | 0.484 | 2.53 [1.90, 3.14] | 3.88 | 4.92 | 3 | 30.0 (10.0–60.0) |
| Linear trend — population only | workload ≤ 2.0/day (primary) | +0, +0, +0, +0, +0 | 0.912 [0.88, 0.95] | 29 / 329 | 0.581 | 1.56 [1.23, 1.93] | 2.40 | 3.77 | 5 | 10.0 (5.0–25.0) |
| Linear trend — population only | max F1 (v1/v2 rule) | +0, +0, +0, +0, +0 | 0.912 [0.88, 0.95] | 29 / 329 | 0.581 | 1.56 [1.23, 1.93] | 2.40 | 3.77 | 5 | 10.0 (5.0–25.0) |
| Linear trend — population only | budget 0.5/day | +20, +20, +20, +20, +20 | 0.344 [0.26, 0.43] | 216 / 329 | 0.758 | 0.26 [0.17, 0.35] | 0.40 | 1.09 | 2 | 5.0 (5.0–10.0) |
| Linear trend — population only | budget 1.0/day | +10, +10, +10, +10, +10 | 0.593 [0.50, 0.68] | 134 / 329 | 0.668 | 0.70 [0.53, 0.90] | 1.08 | 2.13 | 2 | 5.0 (5.0–15.0) |
| Linear trend — population only | budget 3.0/day | -10, -10, -10, -20, -20 | 0.994 [0.99, 1.00] | 2 / 329 | 0.467 | 2.71 [2.04, 3.56] | 4.15 | 5.12 | 5 | 20.0 (10.0–45.0) |
| Selected by the declared rule (per fold) — selected personalization | workload ≤ 2.0/day (primary) | +0, -10, +0, +0, +0 | 0.915 [0.88, 0.95] | 28 / 329 | 0.625 | 1.31 [1.00, 1.60] | 2.01 | 3.51 | 3 | 10.0 (5.0–25.0) |
| Selected by the declared rule (per fold) — selected personalization | max F1 (v1/v2 rule) | +0, -10, +0, +0, +0 | 0.915 [0.88, 0.95] | 28 / 329 | 0.625 | 1.31 [1.00, 1.60] | 2.01 | 3.51 | 3 | 10.0 (5.0–25.0) |
| Selected by the declared rule (per fold) — selected personalization | budget 0.5/day | +10, +10, +10, +10, +10 | 0.447 [0.38, 0.52] | 182 / 329 | 0.821 | 0.23 [0.15, 0.32] | 0.35 | 1.31 | 2 | 5.0 (5.0–10.0) |
| Selected by the declared rule (per fold) — selected personalization | budget 1.0/day | +10, +0, +10, +10, +10 | 0.523 [0.45, 0.60] | 157 / 329 | 0.785 | 0.34 [0.24, 0.45] | 0.52 | 1.60 | 2 | 5.0 (5.0–10.0) |
| Selected by the declared rule (per fold) — selected personalization | budget 3.0/day | -30, -20, -10, -10, -30 | 1.000 [1.00, 1.00] | 0 / 329 | 0.496 | 2.42 [1.81, 3.04] | 3.71 | 4.83 | 3 | 30.0 (10.0–60.0) |
| Best LightGBM (L2 objective, L2 stopping) (per fold) — selected personalization | workload ≤ 2.0/day (primary) | +0, +0, +0, -10, +0 | 0.839 [0.79, 0.89] | 53 / 329 | 0.591 | 1.38 [1.05, 1.70] | 2.12 | 3.43 | 6 | 10.0 (5.0–25.0) |
| Best LightGBM (L2 objective, L2 stopping) (per fold) — selected personalization | max F1 (v1/v2 rule) | +0, +0, +0, +0, +0 | 0.796 [0.75, 0.84] | 67 / 329 | 0.617 | 1.18 [0.88, 1.51] | 1.81 | 3.12 | 6 | 10.0 (5.0–20.0) |
| Best LightGBM (L2 objective, L2 stopping) (per fold) — selected personalization | budget 0.5/day | +10, +10, +10, +10, +10 | 0.465 [0.41, 0.52] | 176 / 329 | 0.769 | 0.33 [0.22, 0.46] | 0.51 | 1.46 | 2 | 5.0 (5.0–10.0) |
| Best LightGBM (L2 objective, L2 stopping) (per fold) — selected personalization | budget 1.0/day | +10, +0, +10, +10, +10 | 0.523 [0.44, 0.62] | 157 / 329 | 0.726 | 0.47 [0.30, 0.66] | 0.72 | 1.75 | 4 | 5.0 (5.0–15.0) |
| Best LightGBM (L2 objective, L2 stopping) (per fold) — selected personalization | budget 3.0/day | -30, -10, -10, -30, -30 | 0.994 [0.99, 1.00] | 2 / 329 | 0.463 | 2.75 [2.08, 3.40] | 4.22 | 5.14 | 3 | 35.0 (15.0–60.0) |
| Best LightGBM (L1 objective, macro-MAE stopping) (per fold) — selected personalization | workload ≤ 2.0/day (primary) | -10, -10, -10, -10, -10 | 0.957 [0.94, 0.98] | 14 / 329 | 0.577 | 1.67 [1.35, 2.03] | 2.57 | 3.98 | 4 | 10.0 (5.0–30.0) |
| Best LightGBM (L1 objective, macro-MAE stopping) (per fold) — selected personalization | max F1 (v1/v2 rule) | -10, -10, -10, -10, -10 | 0.957 [0.94, 0.98] | 14 / 329 | 0.577 | 1.67 [1.35, 2.03] | 2.57 | 3.98 | 4 | 10.0 (5.0–30.0) |
| Best LightGBM (L1 objective, macro-MAE stopping) (per fold) — selected personalization | budget 0.5/day | +10, +10, +0, +10, +10 | 0.416 [0.31, 0.53] | 192 / 329 | 0.741 | 0.35 [0.15, 0.62] | 0.53 | 1.35 | 2 | 5.0 (5.0–10.0) |
| Best LightGBM (L1 objective, macro-MAE stopping) (per fold) — selected personalization | budget 1.0/day | +0, +0, +0, +0, +0 | 0.650 [0.57, 0.73] | 115 / 329 | 0.690 | 0.69 [0.46, 0.98] | 1.07 | 2.26 | 2 | 5.0 (5.0–15.0) |
| Best LightGBM (L1 objective, macro-MAE stopping) (per fold) — selected personalization | budget 3.0/day | -30, -20, -20, -20, -20 | 0.997 [0.99, 1.00] | 1 / 329 | 0.482 | 2.55 [1.90, 3.29] | 3.91 | 4.96 | 4 | 25.0 (10.0–60.0) |
| Best CatBoost (RMSE) (per fold) — selected personalization | workload ≤ 2.0/day (primary) | -10, +0, +0, -10, +0 | 0.860 [0.81, 0.92] | 46 / 329 | 0.587 | 1.44 [1.11, 1.83] | 2.21 | 3.53 | 5 | 10.0 (5.0–27.5) |
| Best CatBoost (RMSE) (per fold) — selected personalization | max F1 (v1/v2 rule) | -10, +0, +0, +0, +0 | 0.821 [0.77, 0.88] | 59 / 329 | 0.605 | 1.27 [0.94, 1.70] | 1.96 | 3.27 | 5 | 10.0 (5.0–25.0) |
| Best CatBoost (RMSE) (per fold) — selected personalization | budget 0.5/day | +10, +10, +10, +10, +10 | 0.410 [0.35, 0.47] | 194 / 329 | 0.804 | 0.24 [0.15, 0.33] | 0.37 | 1.23 | 2 | 5.0 (5.0–10.0) |
| Best CatBoost (RMSE) (per fold) — selected personalization | budget 1.0/day | +10, +0, +10, +10, +10 | 0.474 [0.38, 0.59] | 173 / 329 | 0.761 | 0.35 [0.20, 0.52] | 0.54 | 1.51 | 3 | 5.0 (5.0–10.0) |
| Best CatBoost (RMSE) (per fold) — selected personalization | budget 3.0/day | -30, -10, -10, -20, -30 | 0.988 [0.98, 1.00] | 4 / 329 | 0.486 | 2.49 [1.87, 3.16] | 3.82 | 4.87 | 3 | 30.0 (10.0–60.0) |
| Current v2 serving recipe (refit per fold), dyn-v2 — v2 adaptation policy | workload ≤ 2.0/day (primary) | +0, +0, +0, +0, +0 | 0.815 [0.71, 0.90] | 61 / 329 | 0.539 | 1.66 [1.22, 2.17] | 2.54 | 3.63 | 4 | 15.0 (5.0–40.0) |
| Current v2 serving recipe (refit per fold), dyn-v2 — v2 adaptation policy | max F1 (v1/v2 rule) | -10, +0, +0, -30, -10 | 0.881 [0.76, 0.98] | 39 / 329 | 0.457 | 2.49 [1.75, 3.20] | 3.82 | 4.63 | 5 | 25.0 (10.0–55.0) |
| Current v2 serving recipe (refit per fold), dyn-v2 — v2 adaptation policy | budget 0.5/day | +30, +20, +20, +30, +20 | 0.255 [0.16, 0.37] | 245 / 329 | 0.718 | 0.24 [0.17, 0.31] | 0.37 | 0.86 | 2 | 5.0 (5.0–15.0) |
| Current v2 serving recipe (refit per fold), dyn-v2 — v2 adaptation policy | budget 1.0/day | +20, +10, +10, +10, +10 | 0.523 [0.38, 0.66] | 157 / 329 | 0.635 | 0.72 [0.46, 0.99] | 1.10 | 1.99 | 3 | 10.0 (5.0–25.0) |
| Current v2 serving recipe (refit per fold), dyn-v2 — v2 adaptation policy | budget 3.0/day | -30, -10, -10, -30, -30 | 0.988 [0.98, 1.00] | 4 / 329 | 0.458 | 2.79 [2.14, 3.38] | 4.28 | 5.18 | 5 | 40.0 (15.0–60.0) |
| Current v2 serving recipe (refit per fold), dyn-v2 — v2 adaptation policy | v2 margin −30 | -30, -30, -30, -30, -30 | 1.000 [1.00, 1.00] | 0 / 329 | 0.460 | 2.80 [2.07, 3.49] | 4.30 | 5.21 | 3 | 55.0 (25.0–60.0) |

| Pipeline | Horizon | Method | Coverage (pooled) | Coverage (macro) | Participant range | Mean width | Interval score | Low / usual / high glucose coverage | No interval |
|---|---:|---|---:|---:|---|---:|---:|---|---:|
| 5-min selected | 30 | split-conformal | 80.07 % | 80.07 % | 67.90 %–89.53 % | 43.4 | 77.5 | — / 84.88 % / 70.00 % | 0 |
| 5-min selected | 30 | locally scaled (fallback 0.42 %) | 80.14 % | 80.14 % | 76.70 %–83.58 % | 42.3 | 76.7 | — / 83.62 % / 72.86 % | 0 |
| 5-min selected | 60 | split-conformal | 78.81 % | 78.81 % | 69.48 %–90.25 % | 66.7 | 122.4 | — / 83.66 % / 68.56 % | 0 |
| 5-min selected | 60 | locally scaled (fallback 0.64 %) | 79.79 % | 79.79 % | 76.82 %–83.44 % | 67.1 | 121.9 | — / 83.16 % / 72.67 % | 0 |
| 15-min selected | 30 | split-conformal | 80.57 % | 80.57 % | 68.82 %–89.01 % | 44.3 | 79.2 | — / 85.31 % / 70.72 % | 0 |
| 15-min selected | 30 | locally scaled (fallback 0.85 %) | 80.37 % | 80.37 % | 77.27 %–83.40 % | 42.9 | 78.4 | — / 84.05 % / 72.74 % | 0 |
| 15-min selected | 60 | split-conformal | 79.03 % | 79.03 % | 67.16 %–89.94 % | 67.5 | 124.3 | — / 83.70 % / 69.16 % | 0 |
| 15-min selected | 60 | locally scaled (fallback 1.06 %) | 79.93 % | 79.93 % | 76.27 %–82.94 % | 67.5 | 123.4 | — / 83.33 % / 72.74 % | 0 |

## 8. External validation (ShanghaiT2DM)

The frozen 15-minute LightGBM `lightgbm_l2:cgm15-v1` (a separate model from the demo model and the five-minute candidate) reached macro MAE 11.15 / 20.11 mg/dL at 30/60 minutes on 98 ShanghaiT2DM participants (persistence 12.14 / 20.44). Difference from persistence: 30 min -0.99 mg/dL [-1.21, -0.77], clear; 60 min -0.34 mg/dL [-0.76, +0.10], inconclusive.

| Comparison (a minus b, mg/dL) | Horizon | Mean difference | 95 % CI | Improved / worsened |
|---|---:|---:|---|---|
| Selected candidate minus persistence | 30 | -0.99 | [-1.21, -0.77] | 80 / 18 of 98 |
| Selected candidate minus persistence | 60 | -0.34 | [-0.76, +0.10] | 66 / 32 of 98 |
| Selected candidate minus linear trend | 30 | -0.14 | [-0.29, +0.02] | 68 / 30 of 98 |
| Selected candidate minus linear trend | 60 | -0.34 | [-0.76, +0.10] | 66 / 32 of 98 |
| Selected candidate: personalization minus population only | 30 | -0.20 | [-0.24, -0.15] | 89 / 9 of 98 |
| Selected candidate: personalization minus population only | 60 | -0.42 | [-0.52, -0.32] | 83 / 15 of 98 |

| Pipeline | Horizon | Method | Coverage (pooled) | Coverage (macro) | Participant range | Mean width | Interval score | Low / usual / high glucose coverage | No interval |
|---|---:|---|---:|---:|---|---:|---:|---|---:|
| External candidate | 30 | split-conformal | 87.06 % | 86.78 % | 71.34 %–97.11 % | 42.8 | 58.5 | 91.16 % / 88.90 % / 79.04 % | 0 |
| External candidate | 30 | locally scaled (fallback 0.77 %) | 81.59 % | 81.61 % | 74.50 %–91.33 % | 35.1 | 56.1 | 89.00 % / 83.31 % / 73.69 % | 0 |
| External candidate | 60 | split-conformal | 86.06 % | 85.70 % | 72.19 %–96.86 % | 72.6 | 100.9 | 90.76 % / 88.22 % / 76.66 % | 0 |
| External candidate | 60 | locally scaled (fallback 0.96 %) | 82.14 % | 82.20 % | 75.65 %–92.84 % | 63.6 | 98.2 | 90.14 % / 83.99 % / 73.59 % | 0 |

## 9. Handoff, reproducibility and limitations

### Candidate handoff

**multimodal_5min** — `ridge.cgm-only-v1.gt-nested-2026-10-12-v1` (`ridge:cgm-only-v1`, personalization `final`), status `candidate_not_promoted`, serving-eligible: True.
* Adaptation: enabled (k=96, half-life 240 min); ranges: 30 min ±20.8, 60 min ±35.7 mg/dL (level 0.8); warning margin: 0.0.
* Freeze hash `d3824fadeafde687`; file checksums in `artifacts/research/gt-nested-2026-10-12-v1/candidates/multimodal_5min/candidate.json`.
* Online/offline parity: 2843 origins, max absolute difference population 0.0, correction 0.0, final 0.0 mg/dL before display rounding; engine replay 0.486 ms per origin (end-to-end engine, excluding HTTP).

**portable_15min** — `lightgbm.cgm15-v1.gt-nested-2026-10-12-v1` (`lightgbm_l2:cgm15-v1`, personalization `final`), status `candidate_not_promoted`, serving-eligible: False.
* Adaptation: enabled (k=96, half-life 240 min); ranges: 30 min ±21.4, 60 min ±36.3 mg/dL (level 0.8); warning margin: n/a.
* Freeze hash `31b8872ba8a28293`; file checksums in `artifacts/research/gt-nested-2026-10-12-v1/candidates/portable_15min/candidate.json`.
* Online/offline parity: 948 origins, max absolute difference population 0.0, correction 0.0, final 0.0 mg/dL before display rounding; engine replay 0.318 ms per origin (end-to-end engine, excluding HTTP).

### Commands

```bash
uv run glucotwin data import --dataset shanghai_t2dm && uv run glucotwin data manifest
uv run glucotwin research freeze && uv run glucotwin research smoke
uv run glucotwin research develop        # isolated: never writes artifacts/registry.json
uv run glucotwin research assess         # outer folds, once
uv run glucotwin research external       # ShanghaiT2DM, once
uv run glucotwin research report
# Promotion is a separate explicit action (dry run without --yes):
uv run glucotwin research promote --track multimodal_5min
uv run glucotwin research promote --track multimodal_5min --yes
# Rollback to the model served before a promotion:
uv run glucotwin research rollback --to lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion
```

### Limitations

* CGMacros (14 people with Type 2 diabetes) was already inspected in v1/v2; its nested resampling is internal validation, not an untouched or independent clinical evaluation.
* Outer assessment groups hold 2-3 people; per-fold results are noisy and few-event folds are reported as such.
* ShanghaiT2DM differs in country, device (FreeStyle Libre H, 15-minute), care setting (registry including inpatients with insulin) and cadence; the portable track uses CGM only and no event metric is defined for it.
* Real-time availability is a replay assumption for both datasets (zero latency).
* Prediction ranges come from split-conformal calibration under serial dependence and participant shift; empirical coverage is a measured result, not a guarantee.
* Warning scores are uncalibrated forecast margins; workload budgets are engineering choices, not clinical standards.
* No Indian participants were evaluated; nothing here supports clinical use or treatment decisions.
* AI-READI was not accessed; no result here uses it.
* External cohort: 7 other frozen pipeline/personalization combinations had lower error than the candidate at both horizons; the lowest was `lightgbm_l1:cgm15-v1` (best_grid) at 10.81 / 19.00 vs 11.15 / 20.11 mg/dL. All were frozen before opening; none was chosen by the development rule, and switching on this result would turn the external cohort into a tuning set, so it is reported, not adopted.
* Portable track, 60 min: the declared linear-trend grid offered a 15-minute slope window, which cannot be computed at 15-minute cadence (fewer than three readings); development data chose it, so this 'linear trend' equals persistence. A protocol design flaw, reported rather than fixed after freezing.
