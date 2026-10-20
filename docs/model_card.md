# Model card — `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`

All numbers below are copied from `artifacts/experiments/gt-primary-2026-10-13-fusion/metrics.json` (and, where
stated, from the nested research report). To regenerate the full tables, run `glucotwin experiment report`, which
writes `reports/evaluation_report.md`.

> **Retrospective, fusion-constrained result.** This model comes from re-running the protocol of
> `gt-primary-2026-10-11-v2` with one change: the serving model must read both the static baseline profile and the
> dynamic glucose and wearable streams, as the challenge brief requires. The constraint was declared on 13 October
> 2026, **after** the final-test segment had been inspected in v1 and v2, so these are not untouched test results.
> **We selected a model that implements the required fusion; we have not established that profile features improve
> forecasting for unseen patients** (see *What the profile does and does not show*). The previous dynamic-only model
> (v2) stays registered for rollback; v1 and v2 metrics and reports are preserved (see *History*).

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

* **Family / feature set:** LightGBM direct regressors, one per horizon, on `dyn-prof-v2` (46 inputs in one model).
  - 38 dynamic features: native CGM history (levels, lags, changes, slopes, variability, coverage, gaps) and wearable
    activity (heart rate, METs, activity energy). Each 5-minute wearable summary counts only the part of its interval
    inside the lookback window (`activity_policy = overlap-v2`).
  - 8 static baseline profile values: age, sex, BMI, HbA1c, fasting glucose, fasting insulin, triglycerides and HDL,
    from the screening visit and treated as known from the start of the record (`docs/feature_availability.md`).
  - No meals, no time of day, no participant ID.
* **Profile gate:** the model was trained only on complete profiles, so it abstains (`profile_unavailable`) whenever a
  profile value it reads is missing or not yet available, instead of predicting from a gap it never saw. All 14
  evaluated participants have complete profiles.
* **Target:** glucose change from the latest reading at +30 and +60 minutes. The target is matched to a native
  reading within ±2.5 min and never interpolated.
* **Patient adaptation (`shrunk-bias-v1`, adopted on validation):** per horizon,
  - correction = clip(Σwᵢrᵢ / (Σwᵢ + k), ±25 mg/dL);
  - rᵢ = observed − frozen population forecast, using matured forecasts only;
  - wᵢ = 0.5^(age/240 min); k = 96; at least 6 matured residuals; reset after a 180-minute gap;
  - model weights are never refit.
* **Prediction ranges:** split-conformal with a target coverage of 80 %. Quantiles are 16.7 mg/dL (30 min) and
  26.4 mg/dL (60 min), calibrated on the calibration segment with the adaptive pipeline.
* **Warning score:** max(forecast within 60 min) − 180 mg/dL. The alert threshold is a −10 mg/dL margin (the
  declared validation-F1 rule, re-derived for this model), so a warning fires when a forecast within the hour reaches
  170 mg/dL. The score is uncalibrated and never shown as a probability.
* **Artifacts:**
  - LightGBM text models plus a JSON manifest with SHA-256 checksums, feature order and transformation fingerprint
    `38152f8846c88ed4`;
  - the loader refuses weights whose feature transformation differs;
  - no pickles.
* **Online/offline parity:** replaying every test participant through the app's twin engine reproduced all 15,440
  saved test forecasts within 0.05 mg/dL.

## Safety guardrails

Enforced in code and covered by tests (table with file links: [README](../README.md#safety-guardrails)):

* **Abstention:** no forecast with under 60 min of history, fewer than half the expected readings in the last hour or
  no new reading; after 15 min without one the last forecast is shown marked *Stale*; *Degraded* (with reasons) after a gap > 15 min, an incomplete last
  hour, a sensor-limit reading (40 / 400 mg/dL) or a missing wearable summary.
* **Fusion gate:** the profile model abstains when a profile value is missing or not yet available.
* **No look-ahead:** native readings only; labs, meals and wearable summaries enter only once available.
* **Bounded personalisation:** learns only from matured residuals, needs ≥ 6, capped at ±25 mg/dL, resets after a
  3-hour gap.
* **Warnings:** labelled *Research warning*, *Outcome pending* until judged, then matched one-to-one to an onset,
  counted as a false alarm or marked *Outcome unknown (gap)*; firings within 30 min merge into one episode.
* **Evaluation locks:** opened tests write lock files; re-running needs a written reason and is marked exploratory;
  research runs cannot change the demo model.
* **Public demo isolation** (opt-in, off by default): each browser sees only its own replays, recorded data is refused
  by the backend, replays are capped, expire and are rate-limited. The public demonstration runs the synthetic
  demonstration model, never this model ([`public.py`](../services/api/glucotwin_api/public.py),
  [`test_public_demo.py`](../tests/test_public_demo.py)).

## Data and protocol

* **Data:** CGMacros 1.0.0 (PhysioNet, CC BY-NC-SA 4.0). 14 participants in the dataset's Type 2 group
  (HbA1c > 6.4 %), one US site, about 10 days each, Dexcom G6 Pro native readings.
* **Split:** chronological within each participant by elapsed span — 60 % training, 10 % validation-selection, 10 %
  calibration, 20 % final test — with 82.5-minute purging of label support. Split hash `b31e8d8c071eb425`, identical
  to v2.
* **Protocol:** `configs/experiments/gt-primary-2026-10-13-fusion.yaml` — v2's protocol (`configs/experiment.yaml`)
  plus `models.selection.eligible_feature_sets: [dyn-prof-v2]`. Its header states the change, its reason and its
  timing.

## Selection

* **Candidates:** persistence, bounded linear trend, ridge (2 feature sets), LightGBM and CatBoost. The tree models had
  12 seeded random-search trials per family × horizon × feature set, with early stopping on validation-selection.
  Every candidate's test predictions are identical to v2's.
* **Rule (unchanged):** lowest mean of per-participant MAE over both horizons on validation-selection. Candidates
  within 0.5 mg/dL are tied and resolved by simpler family, then smaller feature set.
* **Eligibility (the one change):** only `dyn-prof-v2` models may serve.
* **Outcome:** `lightgbm:dyn-prof-v2` had the best validation score of all candidates (17.36); `catboost:dyn-prof-v2`
  tied (17.44) and lost on the simpler-family tie-break. Without the eligibility constraint the same rule selects
  `lightgbm:dyn-v2` (17.75), the previous serving model.

## Measured results (final test segment: 14 participants, 7,730 origins ≈ 644 h, 64 new high-glucose onsets)

| Model (test, macro per-participant) | MAE 30 min | MAE 60 min | RMSE 30 | RMSE 60 |
|---|---|---|---|---|
| Persistence | 14.84 | 23.23 | 22.08 | 33.56 |
| Linear trend | 14.03 | 23.23 | 21.03 | 33.96 |
| Ridge (dynamic + profile) | 14.61 | 22.96 | 21.25 | 31.83 |
| LightGBM dynamic + adaptation (previous serving model, v2) | 13.15 | 20.81 | 19.26 | 29.07 |
| LightGBM dynamic + profile, population | 13.14 | 20.59 | 18.86 | 28.14 |
| **LightGBM dynamic + profile + adaptation (serving)** | **12.96** | **20.26** | **18.79** | **28.00** |
| CatBoost dynamic + profile + adaptation (tied, not selected) | 12.93 | 19.80 | 18.73 | 27.72 |

**Paired per-participant differences** (participant-cluster bootstrap, 95 % interval):

* **Serving − persistence:** −1.88 mg/dL [−2.53, −1.32] at 30 min; −2.96 [−4.34, −1.77] at 60 min. Lower MAE than
  persistence for 14/14 participants at 30 min and 13/14 at 60 min.
* **Adaptation (LightGBM dynamic + profile):** −0.18 [−0.35, −0.01] at 30 min; −0.33 [−0.68, +0.02] at 60 min
  (inconclusive). It improved 8/14 participants at 30 min and 9/14 at 60 min. A frozen-state control (no test-time
  updates) gave 13.19 / 20.65, so the small gain comes from updating during the test period.
* **LightGBM − CatBoost (population, dynamic + profile):** +0.02 [−0.15, +0.20] at 30 min; +0.46 [+0.05, +0.92] at
  60 min — CatBoost slightly better at 60 min; the two tied on validation.
* **Profile − dynamic-only (LightGBM, population):** −0.25 [−0.43, −0.04] at 30 min; −0.61 [−1.15, −0.09] at 60 min,
  within the same participants. See the next section before reading this as a benefit of the profile.

**Forecast availability:** 99.9 % of test origins with an observed target received a forecast. This is availability,
not accuracy. Batch model inference took 5.3 ms per 1,000 forecasts (both horizons, Apple M4 CPU). The full
experiment ran in 128 s.

**Prediction ranges (target coverage 80 %):** test coverage was 74.2 % at 30 min and 74.0 % at 60 min; per participant
it was 60–82 % and 51–88 %. The under-coverage reflects drift between segments and time dependence; no guarantee is
claimed.

**Early warning (60-minute rule, test):**

| Measure | Serving rule (−10 mg/dL margin) | Previous serving model (v2, −30 mg/dL) | Persistence rule (glucose ≥ 150 mg/dL) |
|---|---|---|---|
| Onsets detected | 61 of 64 (recall 0.95) | 64 of 64 (recall 1.00) | 63 of 64 |
| Warning episodes | 101 (precision 0.60, F1 0.74) | 143 (precision 0.45, F1 0.62) | 133 (precision 0.47) |
| False alarms | 40 | 79 | 70 |
| False alarms per eligible day | 2.28 | 4.51 | 4.00 |
| False alarms per observed day | 1.49 | 2.95 | 2.61 |
| Warnings per observed day | 3.77 | 5.33 | 4.96 |
| Qualified forecast lead, median (IQR) | 30 min (10–55) | 55 min (30–60) | 40 min |
| Episode-start-to-onset, median | 30 min (16 episodes started > 60 min before onset) | 67.5 min (33) | — |
| Origin-level PR-AUC (prevalence 0.13) | 0.48 | 0.45 | — |

On validation, margins −10 and +0 mg/dL were within 0.03 F1 of the best. The model and its margin changed together,
so fewer false alarms (and three missed onsets, and a shorter lead) are a threshold trade-off on a nearly flat F1
curve, not evidence that the profile improves warnings. Choosing the threshold under a workload-aware objective is
proposed in `docs/next_experiment.md`.

**Secondary analyses:**

* **Leave-one-participant-out cold start** (hyperparameters reused, so not a nested estimate): 14.66 / 24.26 mg/dL
  without online adaptation and 13.81 / 22.12 with it. The held-out person's own profile is still an input here, but
  the model never saw that person in training.
* **Optimistic meal logging** (assumes macronutrients known at the photo time; not selectable): 12.08 / 19.07, against
  13.14 / 20.59 for the same family without meals.

## What the profile does and does not show

1. **The fusion requirement is met:** one model reads the static profile and the dynamic streams together.
2. **Within the same 14 people the profile model scored better** (−0.25 / −0.61 mg/dL above). But profile values are
   constant within a person and the test segment holds later days of the same people, so the profile can act as a
   participant identifier.
3. **On people held out entirely, no reliable benefit was shown.** In the nested experiment
   (`gt-nested-2026-10-12-v1`, `reports/nested_benchmark_report.md`), LightGBM `dyn-prof-v2` minus `dyn-v2` was
   +0.34 [−0.28, +0.89] mg/dL at 30 min and −0.75 [−2.19, +0.61] at 60 min.
4. **The constraint came after the test segment had been inspected.** Score, tie margin and tie-break are unchanged,
   but the decision to require the profile was made knowing that profile models had done well on test.
5. **The model is chosen for compliance with the brief, not for accuracy.**

## History

| Experiment | Status | Serving MAE 30 / 60 | Warning threshold, false alarms (test) |
|---|---|---|---|
| `gt-primary-2026-10-11-v1` (declared before fitting) | Superseded by the correction; artifacts and report preserved (`reports/archive/evaluation_report_gt-primary-2026-10-11-v1.md`) | 13.32 / 21.20 (`lightgbm.dyn-v1…`) | 0 mg/dL, 26 false alarms, episode-start median 10 min |
| `gt-primary-2026-10-11-v2` (corrected re-run, same protocol) | Served until 13 Oct 2026; registered for rollback; report preserved (`reports/archive/evaluation_report_gt-primary-2026-10-11-v2.md`) | 13.15 / 20.81 (`lightgbm.dyn-v2…`, dynamic only) | −30 mg/dL, 79 false alarms, qualified lead median 55 min |
| `gt-primary-2026-10-13-fusion` (v2 + fusion eligibility, declared after test inspection) | **Serving** | 12.96 / 20.26 (`lightgbm.dyn-prof-v2…`) | −10 mg/dL, 40 false alarms, qualified lead median 30 min |

v1's activity features counted up to 65 minutes in a 60-minute window (5,711 of 39,939 origins). Its replay screen could
also credit one onset to two warnings; the offline metrics were not affected by that. Rollback to v2:
`uv run glucotwin research rollback --to lightgbm.dyn-v2.gt-primary-2026-10-11-v2`, then restart the API.

## Limitations

* Small single-site US cohort (14 people), with no Indian participants.
* With 14 people the profile can act as an identity code; no benefit for unseen patients has been shown.
* Blinded research CGMs, replayed with an assumed zero latency; native timestamps known only to the minute.
* Unknown medication use; meal-logging time not documented.
* Prediction ranges under-cover their target.
* The warning score is uncalibrated, and its threshold rule ignores review workload.
* The research event threshold is not a triage rule.
* The test segment had already been inspected before the corrected run and before the fusion constraint.
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

**Recommendation by the pre-specified rule:** Replace the serving recipe with the frozen candidate — rule met; promotion is a separate, explicit decision. The registry serves `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`; no candidate of this experiment has been promoted. This recommendation belongs to `gt-nested-2026-10-12-v1`, declared before serving was required to read both the baseline profile and the dynamic streams. The serving model comes from `gt-primary-2026-10-13-fusion`, which allows only `dyn-prof-v2`; the five-minute candidate reads `cgm-only-v1` only, so it is not eligible and is not the submission demo model.

<!-- research-candidates:end -->

## Two-hour research benchmark — `gt-2h-2026-10-20` (not serving)

Related, also not serving: `gt-2h-ext-2026-10-20` (D-045) re-fitted the 15-minute CGM-only LightGBM with a 120-minute
horizon and assessed it once on 98 ShanghaiT2DM people: 29.55 vs 31.68 mg/dL for persistence at 120 min (−2.12
[−2.67, −1.53], better for 78 of 98; [report](../reports/two_hour_external.md)). `gt-2h-clf-2026-10-20` (D-044), a
direct onset classifier, was rejected: it warned at 97–99 % of eligible times ([report](../reports/two_hour_classifier.md)).

Declared and frozen before any fit on 20 Oct 2026 (D-043, `configs/experiments/gt-2h-2026-10-20.yaml`); full tables in
[`reports/two_hour_benchmark.md`](../reports/two_hour_benchmark.md). It repeats the procedure of
`gt-nested-2026-10-12-v1` with the same participant folds and adds a 120-minute horizon and a 120-minute warning (score =
max of the 30/60/120-minute forecasts − 180 mg/dL; threshold chosen on inner folds for at most 2 false alarms per
observed forecastable day). The 14 CGMacros Type 2 people are each held out entirely once; they were already inspected
in earlier experiments, so this is internal validation, not untouched evidence. It is not the demo model, and nothing
was promoted.

* **Forecast error at 120 min (macro MAE, mg/dL):** 30.617 for the rule's choice per fold, personalised (CGM-only
  features in every fold: LightGBM in 3 of 5, Ridge in 2), versus 35.869 for persistence; paired difference −5.25
  [−6.44, −4.05], lower for 14/14 people. Population only (no personalisation): 31.389.
* **Warnings on new high-glucose onsets** (> 180 mg/dL, sustained 15 min):
  - 120-minute warning: 315 of 329 onsets warned (95.7 %), 1.623 false alarms per observed day, precision 0.5844,
    median forecast lead 15.0 min (IQR 5.0–65.0);
  - 60-minute warning: 313 of 329 (95.1 %), 1.478 false alarms per observed day, precision 0.6054, lead 10.0 min
    (5.0–30.0);
  - persistence, 120-minute warning: 297 of 329 (90.3 %), 1.521, precision 0.5858, lead 15.0 min (5.0–50.0).
* **Range coverage at 120 min (target 80 %):** 76.5 % (persistence 76.9 %).
* **Profile (EHR-like) ablation at 120 min** (with minus without the profile, population models): LightGBM −0.86
  [−2.60, +1.02], 8/14 people better; Ridge +12.65 [+1.34, +29.24], 4/14.
* **Wearable ablation** (LightGBM with minus without wearable inputs): +0.75 [+0.34, +1.20] at 30 min, +2.68 [+1.28,
  +4.38] at 60 min and +2.50 [+0.96, +4.37] at 120 min; 4/14, 2/14 and 3/14 people better.

**What it does and does not show:** a CGM-only procedure forecast 120 minutes ahead with lower error than persistence
for all 14 held-out people, but the two-hour warning is not two hours of notice (median forecast lead 15.0 min, more
false alarms than the 60-minute warning), ranges under-covered, wearable inputs raised error, the profile showed no
reliable benefit on new people, and none of this is clinical validation.

**Re-analysis of these predictions — `gt-warn-range-2026-10-20` (D-046, not serving).** Declared and committed before
any arm was computed; every choice made on development and calibration people; outer predictions read once
([report](../reports/warning_range_experiment.md)). Internal validation on the same already-inspected people.

* **Ranges:** calibrated on the development and calibration people pooled instead of the fold's 2 calibration people,
  coverage at 120 min rose from 76.5 % to 79.8 % (60 min 78.2 → 79.5 %; 30 min 79.8 % unchanged; per-person median
  81.2 %), mean width 88 → 95 mg/dL. Not applied to the demo model: its ranges are already pooled over all 14 people,
  and its under-coverage most likely comes from drift between time segments.
* **Earlier warning: not shown.** Arms (forecast plus range half-width; 120-minute forecast only) and thresholds chosen
  on inner folds for the most onsets warned ≥ 30 min ahead at ≤ 2 false alarms per observed day and ≤ 15 % of eligible
  time: 126 vs 123 of 329 onsets warned ≥ 30 min ahead (+0.9 points [−5.5, +6.6]), 291 vs 315 warned in total,
  false alarms 1.65 vs 1.62 per observed day, median lead 15 min.
* **Health record as a starting correction: not shown.** Ridge on the 8 profile values (development people) predicting
  a new person's average error: −0.53 [−1.57, +0.58] mg/dL at 120 min (10 of 14 better); first 24 hours −0.93
  [−2.74, +0.48]. The declared claim rule (interval below zero) was not met.

**Retraining study — `gt-retrain-2026-10-21` (D-049, not serving).** Fresh LightGBM fits of the fusion recipe (frozen
serving parameters and rounds, no search) on development inner folds: participant-balanced weights −0.04, 2× rising-glucose
weights +0.07 and 6/12/24-hour causal history +0.41 mg/dL 60-minute gain over the refitted control, against a declared
0.5 gate; none adopted, outer folds not opened ([report](../reports/retrain_study.md)). Replay parity of the serving model
re-run and saved: 15,440 of 15,440 forecasts within 0.05 mg/dL ([serving parity](../reports/serving_parity.md)).

**Tuned retraining — `gt-tune-2026-10-21` (D-051, not serving).** Nested: equal tuning budget for the current
features (C0) and the same plus causal 6/12/24-hour history (C1), model and patient correction chosen on inner folds,
each person scored once (30 seeded trials per horizon, each sampling 300, 600 or 1200 boosting rounds). Personalised
60-min MAE 22.27 vs 21.90 mg/dL (C1 − C0 −0.37 [−0.63, −0.06], 10 of 14 better: a small internal gain); against the
refitted serving recipe −0.65 [−1.41, +0.07], 8 of 14 (not established); below the declared −0.5 bar, so not adopted ([report](../reports/tune_study.md)). Ranges (D-050): the served global
range is kept; calibrated on validation + calibration it covered 77.9 % / 78.7 % on the inspected test segment,
reported as a candidate only ([report](../reports/serving_ranges_study.md)).
