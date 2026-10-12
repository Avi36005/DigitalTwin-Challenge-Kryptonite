# Model card — `lightgbm.dyn-v2.gt-primary-2026-10-11-v2`

All numbers below are copied from `artifacts/experiments/gt-primary-2026-10-11-v2/metrics.json`. To regenerate the
full tables, run `glucotwin experiment report`, which writes `reports/evaluation_report.md`.

> **Corrected retrospective result.** This model comes from re-running the declared protocol of
> `gt-primary-2026-10-11-v1` after two code corrections: activity-window features, and warning accounting in replay
> (`reports/repair_report.md`). The final-test segment had already been inspected in v1, so these are not untouched
> test results. The original v1 model, metrics and report are preserved (see *History* below).

## Intended use

A research demonstration of a personalised glucose forecaster for adults with Type 2 diabetes, run inside a replay of
recorded or synthetic data and reviewed by a clinician or a jury. **Not** for clinical decisions, alarms, dosing,
diagnosis, screening, or use with real-time patient data.

**Excluded uses:**
- insulin or medication adjustment;
- emergency or hypoglycaemia triage;
- populations other than the evaluated cohort, including Indian patients, Type 1 diabetes, pregnancy and children;
- any use with a different CGM device without re-evaluation.

## Model

* **Family / feature set:** LightGBM direct regressors, one per horizon, on `dyn-v2`.
  - 38 trailing features: native CGM history (levels, lags, changes, slopes, variability, coverage, gaps) and wearable
    activity (heart rate, METs, activity energy).
  - Each 5-minute wearable summary counts only the part of its interval inside the lookback window
    (`activity_policy = overlap-v2`).
  - No profile features, no meals, no time of day, no participant ID.
* **Target:** glucose change from the latest reading at +30 and +60 minutes. The target is matched to a native
  reading within ±2.5 min and never interpolated.
* **Patient adaptation (`shrunk-bias-v1`, adopted):** per horizon,
  - correction = clip(Σwᵢrᵢ / (Σwᵢ + k), ±25 mg/dL);
  - rᵢ = observed − frozen population forecast, using matured forecasts only;
  - wᵢ = 0.5^(age/240 min); k = 96; at least 6 matured residuals; reset after a 180-minute gap;
  - model weights are never refit.
* **Prediction ranges:** split-conformal with a target coverage of 80 %. Quantiles are 16.8 mg/dL (30 min) and
  28.1 mg/dL (60 min), calibrated on the calibration segment with the adaptive pipeline.
* **Warning score:** max(forecast within 60 min) − 180 mg/dL. The alert threshold is a −30 mg/dL margin (the
  declared validation-F1 rule), so a warning fires when a forecast within the hour reaches 150 mg/dL. The score is
  uncalibrated and never shown as a probability.
* **Artifacts:**
  - LightGBM text models plus a JSON manifest with SHA-256 checksums, feature order and transformation fingerprint
    `8e85d78d17122ef4`;
  - the loader refuses weights whose feature transformation differs;
  - no pickles.

## Data and protocol

* **Data:** CGMacros 1.0.0 (PhysioNet, CC BY-NC-SA 4.0). 14 participants in the dataset's Type 2 group
  (HbA1c > 6.4 %), one US site, about 10 days each, Dexcom G6 Pro native readings.
* **Split:** chronological within each participant by elapsed span — 60 % training, 10 % validation-selection, 10 %
  calibration, 20 % final test — with 82.5-minute purging of label support.
* **Protocol:** `configs/experiment.yaml`. It is identical to the v1 protocol except for the corrected feature sets
  (the differences are listed in its header).

## Selection

* **Candidates:** persistence, bounded linear trend, ridge (2 feature sets), LightGBM and CatBoost. The tree models had
  12 seeded random-search trials per family × horizon × feature set, with early stopping on validation-selection.
* **Rule:** lowest mean of per-participant MAE over both horizons on validation-selection. Candidates within
  0.5 mg/dL are tied and resolved by simpler family, then smaller feature set.
* **Outcome:** four tree candidates fell within the margin (best 17.36 for `lightgbm:dyn-prof-v2`;
  `lightgbm:dyn-v2` 17.75), so the rule selected `lightgbm:dyn-v2` — the same choice as in v1. We did not change it
  after seeing test results.

## Measured results (final test segment: 14 participants, 7,730 origins ≈ 644 h, 64 new high-glucose onsets)

| Model (test, macro per-participant) | MAE 30 min | MAE 60 min | RMSE 30 | RMSE 60 |
|---|---|---|---|---|
| Persistence | 14.84 | 23.23 | 22.08 | 33.56 |
| Linear trend | 14.03 | 23.23 | 21.03 | 33.96 |
| Ridge (dynamic) | 14.37 | 23.11 | 20.96 | 32.13 |
| LightGBM dynamic, population | 13.38 | 21.20 | 19.42 | 29.42 |
| **LightGBM dynamic + adaptation (serving)** | **13.15** | **20.81** | **19.26** | **29.07** |
| CatBoost dynamic + adaptation | 13.23 | 20.44 | 19.33 | 28.75 |
| LightGBM + profile + adaptation (not selected) | 12.96 | 20.26 | 18.79 | 28.00 |
| CatBoost + profile + adaptation (not selected) | 12.93 | 19.80 | 18.73 | 27.72 |

**Paired per-participant differences** (participant-cluster bootstrap, 95 % interval):

* **Serving − persistence:** −1.69 mg/dL [−2.34, −1.11] at 30 min; −2.42 [−3.81, −1.11] at 60 min. Lower MAE than
  persistence for 14/14 participants at 30 min and 12/14 at 60 min.
* **Adaptation (LightGBM dynamic):** −0.24 [−0.43, −0.07] at 30 min; −0.39 [−0.79, −0.02] at 60 min. It improved 9/14
  participants at each horizon. A frozen-state control (no test-time updates) gave 13.40 / 21.16, so the small gain
  comes from updating during the test period.
* **LightGBM − CatBoost (population, dynamic):** −0.13 [−0.34, 0.07] at 30 min; +0.18 [−0.29, 0.66] at 60 min — no
  clear difference.
* **Profile features (LightGBM, population):** −0.25 [−0.43, −0.04] at 30 min; −0.61 [−1.15, −0.09] at 60 min, within
  participants. Caution: with 14 participants a profile vector is a quasi-identifier, so this gain may not transfer.

**Forecast availability:** 99.9 % of test origins with an observed target received a forecast. This is availability,
not accuracy. Batch model inference took 3.5 ms per 1,000 forecasts (both horizons, Apple M4 CPU). The full
experiment ran in 110 s.

**Prediction ranges (target coverage 80 %):** test coverage was 74.4 % at 30 min and 75.9 % at 60 min; per participant
it was 60–82 % and 60–86 %. The under-coverage reflects drift between segments and time dependence; no guarantee is
claimed.

**Early warning (60-minute rule, test):**

| Measure | Serving rule (−30 mg/dL margin) | Persistence rule (glucose ≥ 150 mg/dL) |
|---|---|---|
| Onsets detected | 64 of 64 (recall 1.00) | 63 of 64 |
| Warning episodes | 143 (precision 0.45, F1 0.62) | — |
| False alarms | 79 | — |
| False alarms per eligible day | 4.51 | 4.00 |
| False alarms per observed day | 2.95 | — |
| Warnings per observed day | 5.33 | — |
| Qualified forecast lead, median (IQR) | 55 min (30–60) | 40 min |
| Episode-start-to-onset, median | 67.5 min (33 episodes started > 60 min before onset) | — |
| Origin-level PR-AUC (prevalence 0.13) | 0.45 | — |

The declared F1 rule chose the lowest threshold in a nearly flat F1 curve. The serving rule is therefore sensitive but
burdensome: about as noisy as a simple threshold on the current reading. Choosing the threshold under a workload-aware
objective is proposed in `docs/next_experiment.md`.

**Secondary analyses:**

* **Leave-one-participant-out cold start** (hyperparameters reused, so not a nested estimate): 14.92 / 25.47 mg/dL
  without online adaptation and 14.07 / 23.12 with it. New participants are harder, and adaptation helps more for them.
* **Optimistic meal logging** (assumes macronutrients known at the photo time; not selectable): 12.07 / 18.87, against
  13.38 / 21.20 for the same family without meals.

## History

| Experiment | Status | Serving MAE 30 / 60 | Warning threshold, false alarms (test) |
|---|---|---|---|
| `gt-primary-2026-10-11-v1` (declared before fitting) | Superseded by the correction; artifacts and report preserved (`reports/archive/evaluation_report_gt-primary-2026-10-11-v1.md`) | 13.32 / 21.20 (`lightgbm.dyn-v1…`) | 0 mg/dL, 26 false alarms, episode-start median 10 min |
| `gt-primary-2026-10-11-v2` (corrected re-run, same protocol) | Serving | 13.15 / 20.81 (`lightgbm.dyn-v2…`) | −30 mg/dL, 79 false alarms, qualified lead median 55 min |

v1's activity features counted up to 65 minutes in a 60-minute window (5,711 of 39,939 origins). Its replay screen could
also credit one onset to two warnings; the offline metrics were not affected by that.

## Limitations

* Small single-site US cohort (14 people), with no Indian participants.
* Blinded research CGMs, replayed with an assumed zero latency; native timestamps known only to the minute.
* Unknown medication use; meal-logging time not documented.
* Prediction ranges under-cover their target.
* The warning score is uncalibrated, and its threshold rule ignores review workload.
* The research event threshold is not a triage rule.
* The test segment had already been inspected before this corrected run.
* The optional Chronos-Bolt research track was not run.

## Ethics and licensing

De-identified public research data are used under their license, with pseudonymous display aliases and no attempt to
re-identify anyone. Derived model weights are not redistributed. See the [data card](data_card.md).

<!-- research-candidates:start -->

## Research candidates — `gt-nested-2026-10-12-v1` (not serving)

Generated by `glucotwin research report` from saved predictions; see `reports/model_upgrade_review.md`.

* **multimodal_5min:** `ridge.cgm-only-v1.gt-nested-2026-10-12-v1` — `ridge:cgm-only-v1`, adaptation on (k 96, half-life 240 min), ranges ±20.8 / ±35.7 mg/dL, warning margin +0 mg/dL; status `candidate_not_promoted`.
* **portable_15min:** `lightgbm.cgm15-v1.gt-nested-2026-10-12-v1` — `lightgbm_l2:cgm15-v1`, adaptation on (k 96, half-life 240 min), ranges ±21.4 / ±36.3 mg/dL; status `candidate_not_promoted`.

* **New people, 5-minute track (14 CGMacros people, 5 outer folds; internal validation):** macro MAE 13.88 / 22.30 mg/dL at 30 / 60 min for the rule's per-fold choice, versus 14.52 / 24.25 for the v2 recipe refit per fold and 15.34 / 24.47 for persistence. When the 60-minute target exceeded 180 mg/dL: 39.71 versus 37.00 (v2 recipe).
* Ranges (target 80 %): measured 80.07 % / 78.81 % on outer-fold people.
* Portable 15-minute track, same people: 14.06 / 22.21 mg/dL.
* **External (ShanghaiT2DM, 98 people, 15-minute CGM only, opened once):** 11.15 / 20.11 mg/dL versus persistence 12.14 / 20.44; range coverage 87.06 % / 86.06 % (target 80 %).

**Recommendation by the pre-specified rule:** Replace the serving recipe with the frozen candidate — rule met; promotion is a separate, explicit decision. The registry serves `lightgbm.dyn-v2.gt-primary-2026-10-11-v2`; no candidate of this experiment has been promoted.

<!-- research-candidates:end -->
