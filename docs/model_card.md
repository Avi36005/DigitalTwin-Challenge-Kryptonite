# Model card — `lightgbm.dyn-v1.gt-primary-2026-10-11-v1`

All numbers below are copied from `artifacts/experiments/gt-primary-2026-10-11-v1/metrics.json`
(regenerate the full tables with `glucotwin experiment report` → `reports/evaluation_report.md`).

## Intended use

Research demonstration of a personalised glucose forecaster for adults with Type 2 diabetes, inside a replay of
recorded or synthetic data, reviewed by a clinician or a jury. **Not** for clinical decisions, alarms, dosing,
diagnosis, screening, or use with real-time patient data.

**Excluded uses:** insulin or medication adjustment; emergency or hypoglycaemia triage; populations other than
the evaluated cohort (including Indian patients, Type 1 diabetes, pregnancy, children); any use with a different
CGM device without re-evaluation.

## Model

* **Family / feature set:** LightGBM direct regressors (one per horizon) on `dyn-v1`: 38 trailing features of
  native CGM history (levels, lags, changes, slopes, variability, coverage, gaps) and wearable activity (heart rate,
  METs, activity energy). No profile features, no meals, no time of day, no participant ID.
* **Target:** glucose change from the latest reading at +30 and +60 minutes (target matched to a native reading
  within ±2.5 min; never interpolated).
* **Patient adaptation (`shrunk-bias-v1`, adopted):** per horizon, correction =
  clip(Σwᵢrᵢ / (Σwᵢ + k), ±25 mg/dL), rᵢ = observed − frozen population forecast for matured forecasts only,
  wᵢ = 0.5^(age/240 min), k = 96, ≥ 6 matured residuals, reset after a 180-minute gap. Model weights are never refit.
* **Intervals:** split-conformal, nominal 80 %, quantiles 17.1 mg/dL (30 min) and 28.4 mg/dL (60 min), calibrated on
  the calibration segment with the adaptive pipeline.
* **Warning score:** max(forecast within 60 min) − 180 mg/dL; alert threshold 0 mg/dL (validation-selected);
  uncalibrated, never shown as a probability.
* **Artifacts:** LightGBM text models + JSON manifest with SHA-256 checksums and feature order (no pickles).

## Data and protocol

CGMacros 1.0.0 (PhysioNet, CC BY-NC-SA 4.0): 14 participants in the dataset's Type 2 group (HbA1c > 6.4 %), one US
site, ~10 days each, Dexcom G6 Pro native readings. Within each participant, chronological split by elapsed span:
60 % training, 10 % validation-selection, 10 % calibration, 20 % final test, with 82.5-minute purging of label
support. Protocol declared before fitting (`configs/experiment.yaml`); test evaluated once.

## Selection

Candidates: persistence, bounded linear trend, ridge (2 feature sets), LightGBM and CatBoost (12 seeded random-search
trials per family × horizon × feature set, early stopping on validation-selection). Rule: lowest mean of
per-participant MAE over both horizons on validation-selection; candidates within 0.5 mg/dL tie → simpler family,
then smaller feature set. Four tree candidates fell within the margin (best 17.41 for `lightgbm:dyn-prof-v1`;
`lightgbm:dyn-v1` 17.69), so the rule selected `lightgbm:dyn-v1`. We did not change this after seeing test results.

## Measured results (final test segment: 14 participants, 7,730 origins ≈ 644 h, 64 new high-glucose onsets)

| Model (test, macro per-participant) | MAE 30 min | MAE 60 min | RMSE 30 | RMSE 60 |
|---|---|---|---|---|
| Persistence | 14.84 | 23.23 | 22.08 | 33.56 |
| Linear trend | 14.03 | 23.23 | 21.03 | 33.96 |
| Ridge (dynamic) | 14.37 | 23.36 | 21.06 | 32.49 |
| LightGBM dynamic, population | 13.60 | 21.74 | 19.69 | 30.10 |
| **LightGBM dynamic + adaptation (serving)** | **13.32** | **21.20** | **19.50** | **29.68** |
| CatBoost dynamic + adaptation | 13.35 | 20.83 | 19.57 | 29.47 |
| LightGBM + profile + adaptation (not selected) | 12.97 | 20.30 | 18.83 | 28.06 |
| CatBoost + profile + adaptation (not selected) | 13.04 | 19.80 | 18.90 | 27.67 |

Paired per-participant differences (participant-cluster bootstrap, 95 % interval):

* Serving − persistence: −1.51 mg/dL [−2.15, −0.95] at 30 min; −2.02 [−3.40, −0.80] at 60 min. Lower MAE than
  persistence for 14/14 participants at 30 min and 11/14 at 60 min.
* Adaptation (LightGBM dynamic): −0.28 [−0.45, −0.11] at 30 min; −0.53 [−0.92, −0.16] at 60 min; improved 11/14
  participants at each horizon. A frozen-state control (no test-time updates) gave 13.57 / 21.60, so the gain comes
  from prequential updating during the test period.
* LightGBM − CatBoost (population, dynamic): −0.03 [−0.19, 0.13] at 30 min; +0.35 [−0.08, 0.80] at 60 min — no
  clear difference. With profile features CatBoost was better at 60 min (+0.44 [0.06, 0.89]).
* Profile features (LightGBM): −0.47 [−0.64, −0.26] at 30 min; −1.11 [−1.68, −0.52] at 60 min within participants.
  Caution: with 14 participants a profile vector is a quasi-identifier; this within-participant gain may not transfer.

Forecast availability: 99.9 % of test origins with an observed target received a forecast. Inference: 3.3 ms per
1,000 forecasts (both horizons, Apple M4 CPU). Full experiment runtime 127 s.

**Intervals (nominal 80 %):** test coverage 74.4 % (30 min) and 75.7 % (60 min); per-participant 58–85 %. Under-
coverage reflects drift between segments and time dependence; no guarantee is claimed.

**Early warning (60-minute rule, test):** 53 of 64 onsets detected (recall 0.83), precision 0.67, F1 0.74,
1.49 false alarms per patient-day (2.95 warnings per day), **median lead time 10 minutes** (IQR 5–20), origin-level
PR-AUC 0.44 (prevalence 0.13). A "current glucose > 150 mg/dL" persistence rule detected 63/64 with 40-minute median
lead but 4.00 false alarms per patient-day. The model's warnings are fewer but late.

**Secondary analyses:** leave-one-participant-out cold start (no retuning): 14.76 / 24.87 mg/dL without and
14.09 / 23.06 with online adaptation — new participants are harder, and adaptation helps more. Optimistic meal
logging (assumes macronutrients known at the photo time; not selectable): 12.07 / 18.76 vs 13.60 / 21.74 for the
same family without meals — timely meal information would likely help most.

## Limitations

Small single-site US cohort (14 people), no Indian participants, blinded research CGMs replayed with assumed zero
latency, minute-resolution native timestamps, unknown medication use, meal timing availability undocumented,
under-covering intervals, uncalibrated warning score with short lead time, research event threshold (not triage).
Optional Chronos-Bolt research track not run.

## Ethics and licensing

De-identified public research data used under its license; pseudonymous display aliases; no attempt to
re-identify. Derived model weights are not redistributed. See [data card](data_card.md).
