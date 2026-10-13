# Proposed next experiment

Successor declared (2026-10-12, not run): `configs/experiments/gt-nested-2026-10-12-v2.yaml` — multi-criteria
promotion, valid trend windows, public-key folds, AI-READI development data required.

Status (2026-10-12): **executed** as `gt-nested-2026-10-12-v1` (protocol `configs/experiments/gt-nested-2026-10-12-v1.yaml`,
results `reports/nested_benchmark_report.md`, review `reports/model_upgrade_review.md`). The proposal below is kept
as written.

Original status: **proposal**. Nothing here has been fitted or evaluated. It follows the corrections in
`reports/repair_report.md` and must be declared — frozen in a new `configs/experiments/<id>.yaml` with an entry in
`docs/decisions.md` — before any model in it is fitted.

## Why

The corrected experiment (`gt-primary-2026-10-11-v2`) re-used a test segment that was already inspected, so it cannot
support a new selection claim. It also exposed three weak points:

* the warning threshold rule (event-level F1) is nearly flat across margins −30 … 0 mg/dL and ignores review workload;
* prediction ranges under-cover their 80 % target (74.4 % / 75.9 % on test in v2; 74.2 % / 74.0 % for the
  fusion-constrained serving model);
* the adaptation settings sit on the edge of the declared grid (k = 96, half-life 240 min).

A larger architecture is not the first priority.

## Evaluation design

* **New-participant claims:** nested participant-level cross-validation. The outer folds hold out whole participants;
  all tuning (hyperparameters, adaptation settings, thresholds, interval quantiles) happens inside the training folds
  only. Report per-fold and pooled results with participant-cluster intervals.
* **Returning-participant claims:** the existing within-participant chronological split. Keep the test segment
  untouched until the protocol is frozen.
* Calibration data stay separate from selection data. Keep the purge at segment boundaries, and keep adaptation causal
  (matured residuals only). No preprocessing, imputation, threshold or quantile may see final-test data.
* Persist the config, data, split, transformation and model fingerprints, the seeds, the environment, predictions,
  metrics and selection rationale. Keep separate statuses for corrected evidence, exploratory runs and a model
  eligible for serving.

## Comparisons (identical masks, origins, horizons and inputs)

1. Baselines: persistence, bounded linear trend and ridge on identical masks.
2. LightGBM vs CatBoost on the same corrected feature sets with an equal, declared search budget.
3. Inputs: CGM-only vs dynamic (`dyn-v2`) vs dynamic + profile (`dyn-prof-v2`), evaluated separately. The CGM-only
   ablation measures whether activity inputs help. Check how far static profile vectors can identify participants
   within a 14-person cohort before reading any profile gain as generalizable.
4. Training objective: L2 (current) vs an MAE-aligned LightGBM configuration (L1 objective and/or early stopping on the
   declared criterion). The declared selection criterion is the equal-weight mean of per-participant MAE; a row-weighted
   L1 is not the same thing, so implement the declared criterion itself if aligning.
5. Adaptation: off vs the frozen v2 policy vs a small declared grid extension beyond the current edges. Adopt only
   for a meaningful validation gain, and report participants made worse, not just the average.
6. Ranges: recalibrate on the calibration data only; report widths and empirical coverage by horizon and participant.
   Test an alternative (for example per-participant or locally weighted conformal) only under the declared protocol.
   Time dependence means no coverage guarantee can be claimed.
7. Warning policy: choose the threshold under a stated objective — for example, the highest recall subject to a
   maximum number of false alarms per observed day agreed with clinicians. That workload limit is a research design
   choice, not a clinical standard. Report the qualified forecast lead, episode-start-to-onset time and raw counts
   on one declared time base.

Deferred until the above is solid: sequence models (LSTM, transformers) and Chronos-Bolt. If one is tried, it must use
the same available inputs, forecast origins, split protections and compute budget, and report failure or no gain
honestly. A foundation model given future context must never be compared to a causal tree baseline.

## What would change the serving model

Only the declared selection rule applied to the new protocol's validation data. A candidate that merely looks better
on the already-inspected test segment (for example, the profile-augmented models in v1 and v2) is not a reason to
switch.

Recorded exception (13 October 2026, decisions D-038 and D-039): the serving model was switched to the profile model
of `gt-primary-2026-10-13-fusion` to meet the brief's requirement that one model ingest static and dynamic data. The
eligibility constraint was declared after the test segment had been inspected, and the switch rests on compliance with
the brief, not on test scores. This protocol must therefore test the profile on people held out entirely; the nested
experiment found no reliable benefit (+0.34 [−0.28, +0.89] mg/dL at 30 min, −0.75 [−2.19, +0.61] at 60 min).

LightGBM's L1/L2 objectives are documented in the
[LightGBM parameter reference](https://lightgbm.readthedocs.io/en/latest/Parameters.html); leakage and test-set
separation follow [scikit-learn's common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html).
