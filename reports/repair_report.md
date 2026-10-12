# Technical repair report — model-pipeline corrections (11 October 2026)

An independent review of GlucoTwin found that the LightGBM serving model loads, predicts and reproduces its saved
evaluation, but that the logic around it had defects. This report records how each finding was reproduced against the
code as it stood, what changed, which artifacts are affected and how the original results stay traceable. Every number
below comes from `artifacts/experiments/<id>/metrics.json`, the saved predictions or the test suite.

| # | Finding | Reproduced? | Status |
|---|---|---|---|
| 1 | Activity windows count more time than they cover | Yes — 5,711 of 39,939 origins with `act_cov_60 > 1` (max 1.0833 = 65 of 60 min) | Fixed in feature sets `*-v2`; v1 kept only for reproduction |
| 2 | Replay warning outcomes can credit one onset twice | Yes — warnings at 0 and 40 min, onset at 50: both credited online, one offline | Fixed: one shared matcher |
| 3 | "Lead time" mixes episode history with forecast horizon | Yes — 2 matched serving test episodes > 60 min (max 155 min) | Old metric renamed; qualified lead added |
| 4 | Prediction ranges under-cover the 80 % target | Yes — 74.37 % / 75.66 % on test (v1) | Reported as measured; wording changed; not "fixed" |
| 5 | False-alarm and warning rates use different denominators | Yes — 1.49 per 17.5 eligible days vs 2.95 per 26.8 observed days | Both rates now on both bases, with raw counts |

## 1. Activity-window accounting

**Reproduction.** `features.py` selected trailing 5-minute wearable summaries with `a_t > t - w - EPS` and summed
each summary's full duration. A summary ending exactly at `t − 60` covers `(t − 65, t − 60]` — entirely outside the
window — yet was counted, so an aligned origin could see 13 summaries (65 minutes) in a 60-minute window. In the v1
origin table, 5,711 of 39,939 rows have `act_cov_60 > 1` (maximum 1.0833). `hr_mean_*`, `mets_mean_*`, `mets_max_60`,
`kcal_sum_60` and `active_min_60` used the same selection, so the defect was not limited to the coverage percentage.

**Declared convention (`overlap-v2`, `glucotwin/features.py`).** A summary observed at `e` covers `(e − window, e]`.
For a lookback `(t − w, t]` it contributes only the overlapping share of its own interval, and only if it was
available by `t`. A summary ending at `t − w` contributes nothing. Covered minutes, activity energy and active minutes
are allocated in proportion to that share — an approximation at non-aligned origins, because minute-level data are
not part of the event model. Means are weighted by covered minutes inside the window. Summaries are processed in end
order, and each one's start is moved past the previous end, so duplicate or overlapping summaries cannot count a
minute twice. Missing wearable data stays missing: heart rate, energy and active minutes are NaN, never 0. Nothing is
clamped; `act_cov_60 ≤ 1` holds by construction.

**Scope.** Rebuilding the origin table with the corrected features changed `act_cov_60` and `kcal_sum_60` in 39,850 of
39,939 rows, `hr_mean_60` in 37,727, `mets_mean_60` in 26,404, `active_min_60` in 15,207 and `mets_max_60` in 241.
Glucose features, quality decisions, targets, labels, segments, the split hash (`b31e8d8c071eb425`) and the data
fingerprint (`289d296590837618`) are identical to v1.

**Versioning.** The corrected transformation is a new feature set (`dyn-v2`, `dyn-prof-v2`, `dyn-prof-meal-v2`) with
the same column names. Every new artifact stores a `transform_fingerprint` (sha-256 of the feature specification and
activity policy). `PopulationBundle.load` refuses an artifact whose fingerprint differs from this code's for the
same feature set, and refuses a pre-fingerprint artifact that claims a corrected feature set. The legacy convention
(`end-in-window-v1`) is kept unchanged under the `*-v1` feature sets, so the v1 artifacts still load and reproduce.

**Tests (`tests/test_corrections.py`).** Twelve contiguous summaries give exactly 60 minutes, and a summary ending at
the lower boundary adds nothing (the legacy rule gives 65). A non-aligned origin counts 58 minutes and the matching
proportional energy. Missing and duplicated summaries cannot inflate coverage or energy. Missing wearable data is not
treated as inactivity. A delayed summary has no influence before its `available_at`. Offline features (full
recording, filtered per origin) equal online features (only released events) for two synthetic participants. The
loader rejects mismatched semantics and still accepts the v1 artifacts.

## 2. Online and offline warning matching

**Reproduction.** `TwinEngine._update_alert_outcomes` looped over open warnings and credited a confirmed onset to
every warning whose window contained it. Two warning episodes at minutes 0 and 40 (30-minute merge rule, 60-minute
horizon) and one certain onset at minute 50, confirmed at 65, produced two `onset_observed` outcomes online. The
offline `evaluate_patient` produced one true warning and one false alarm. The offline matcher already guarded one-to-one
matching, so v1's offline recall was not inflated by this defect; the replay screen and the demonstration were.

**Fix.** `glucotwin.evaluation.alerts.match_episodes` is the single implementation. Episodes are taken in
chronological order; each takes the earliest unmatched onset with `start < onset ≤ last firing + H`. One onset goes
to at most one episode, and one episode receives at most one onset. The replay engine keeps every confirmed onset for
the life of a session revision and recomputes the matching from all warnings and onsets known so far. Repeated calls,
late delivery of an onset and replays to the same clock therefore give identical results. A seek or reset builds a
fresh engine. A warning becomes a false alarm only after its whole follow-up (`H` + 15-minute confirmation + 7.5-minute
continuity gap) has been observed, and becomes "unknown" if a sensor gap falls inside it. Marking a warning as reviewed
is a separate, local property and never changes outcomes.

**Tests.** Two warnings and one onset give one credit online and offline. One episode and two onsets match only the
earliest. Repeated confirmation callbacks change nothing. An outcome stays pending until follow-up is observable, and
gaps censor it. Incremental replay matching equals batch matching on 50 randomized event streams. An onset is credited
only after its confirmation arrives.

## 3. Lead-time definitions

**Reproduction.** The declared rule measures lead from the first firing of a merged episode, while matching allows an
onset up to `H` after the last firing. In v1's serving test output, 2 matched episodes started more than 60 minutes
before their onset (maximum 155 minutes), although no single forecast in them looked further than 60 minutes ahead.

**Change.** The v1 measure is preserved, renamed **episode-start-to-onset** (`lead_time_minutes` stays as a
deprecated alias in the API). A new **qualified forecast lead** is the onset minus the earliest firing of the episode
whose own horizon contains the onset (`f < o ≤ f + H`). It always satisfies `0 < lead ≤ H`, with no timestamp
tolerance added. Matched episodes without a qualifying firing are counted separately (0 on the v2 test). The API
alert outcome carries both measures and the last supporting forecast time; the replay screen shows "forecast lead" and
"first warning … before" side by side.

**Tests.** In a chain of firings at 0, 25, 50, 75 and 100 minutes with an onset at 155, episode-start-to-onset is 155
and the qualified lead is 55. A firing whose horizon misses the onset does not qualify. The onset is credited only
after confirmation.

## 4. Evidence semantics and time bases

* The evidence table's "Coverage" was forecast availability. It is now labelled **Forecast availability**: the share
  of origins with an observed target at which a forecast was issued; 99.87 % for the serving model on test. It is not
  accuracy and not interval coverage.
* Ranges are labelled **Prediction range · target coverage 80 %**. The measured test coverage, the experiment and
  "coverage varies by participant; no guarantee" are one click away on the replay screen and in the forecast drawer.
  The ranges themselves were not changed, and nothing was recalibrated on test residuals.
* v1 divided false alarms by eligible, forecastable, uncensored time (17.5 participant-days on test) and warnings by
  all observed forecastable time (26.8 participant-days). Both rates are now reported on **both** bases, next to the
  raw counts. Both bases are approximations: forecast-issued origins × 5-minute cadence. Unknown or censored outcomes
  stay separate from true negatives (`unresolved_episodes`, `censored_origins`).
* Batch latency is labelled "batch model inference per 1,000 forecasts, measured offline". Values below 0.1 ms show as
  "<0.1 ms", not "0.0 ms".

## 5. Corrected experiment `gt-primary-2026-10-11-v2`

`configs/experiment.yaml` now holds v2. It is the v1 protocol (preserved verbatim at
`configs/experiments/gt-primary-2026-10-11-v1.yaml`, config hash `e049a6a7769f8ff8`), declared after v1's single test
evaluation. Only the candidate feature sets moved to the corrected versions and two measures were added to reporting.
Cohort, splits, seeds, search spaces and budgets, the selection rule and tie-break, the adaptation grid and adoption
rule, the interval method, and the alert score, threshold grid and threshold rule are copied verbatim. **The test
segment is the one already inspected in v1, so v2 numbers are corrected retrospective results, not untouched test
evidence.**

| Final test (14 participants) | v1 (original) | v2 (corrected) |
|---|---:|---:|
| Serving pipeline | LightGBM `dyn-v1` + adaptation | LightGBM `dyn-v2` + adaptation (same declared tie-break) |
| MAE 30 / 60 min, mg/dL | 13.32 / 21.20 | 13.15 / 20.81 |
| Persistence MAE 30 / 60 min | 14.84 / 23.23 | 14.84 / 23.23 (unchanged: no activity input) |
| Serving − persistence, 30 / 60 min [95 % participant-cluster CI] | −1.51 [−2.15, −0.95] / −2.02 [−3.40, −0.80] | −1.69 [−2.34, −1.11] / −2.42 [−3.81, −1.11] |
| Best validation score (not selected: inside tie margin) | `lightgbm:dyn-prof-v1` 17.41 | `lightgbm:dyn-prof-v2` 17.36 |
| Adaptation (k, half-life) | 96, 240 min — both at grid edges | 96, 240 min — both at grid edges |
| Prediction-range coverage on test, 30 / 60 min (target 80 %) | 74.37 % / 75.66 % | 74.36 % / 75.94 % |
| Warning threshold (validation F1) | margin 0 mg/dL | margin −30 mg/dL |
| Onsets detected / warnings / false alarms | 53 of 64 / 79 / 26 | 64 of 64 / 143 / 79 |
| False alarms per eligible day · per observed day | 1.49 · not reported | 4.51 · 2.95 |
| Episode-start-to-onset median (episodes > 60 min) | 10 min (2) | 67.5 min (33) |
| Qualified forecast lead median | not reported | 55 min |

**Warning operating point.** The declared rule maximizes validation F1 over margins −30 … +40 mg/dL. In both
experiments the F1 curve is almost flat between −30 and 0: v1 0.689 at −30 vs 0.692 at 0; v2 0.674 at −30 vs 0.649 at
0, on 32 validation onsets. The corrected features moved the argmax from 0 to −30, which roughly triples false alarms.
The rule was applied as declared and was not retuned on test. This instability is evidence that F1 alone is a poor
objective for review workload, and it is the first item of the proposed next experiment (`docs/next_experiment.md`).

## 6. Checks before declaring the work complete

* Activity support and release cutoffs: exact boundary cases in `tests/test_corrections.py` (all pass).
* Matching: one-to-one online and offline; incremental equals batch (all pass).
* Qualified lead `≤ H`: tested. On v2 test, 64 of 64 matched episodes have a qualifying firing.
* Model load: the v2 artifact loads with transformation fingerprint `8e85d78d17122ef4`; the v1 artifact still loads
  with the legacy convention; a mismatched fingerprint is refused (tested).
* Metrics recomputed from `predictions.parquet`: all 32 v2 test MAE/RMSE rows match `metrics.json` exactly (max
  difference 0).
* Offline vs online: 1,152 forecasts issued by the replay API for four participants in the test period match the saved
  offline predictions within the API's 0.1 mg/dL rounding (max difference 0.05).
* Serving identity: the registry, `/api/v1/health/ready`, the evidence report and the browser's forecast drawer all
  show `lightgbm.dyn-v2.gt-primary-2026-10-11-v2`.
* Suites: backend `pytest` (event, leakage, replay API, pipeline integration and correction tests) with isolated
  writable directories; frontend type check, unit tests and production build; Playwright journeys against an isolated
  API and web server.

## 7. Affected artifacts and migration

| Artifact | Change |
|---|---|
| `artifacts/experiments/gt-primary-2026-10-11-v1/` | Unchanged, preserved |
| `artifacts/models/lightgbm.dyn-v1.gt-primary-2026-10-11-v1/` | Unchanged; still loads; no longer serving |
| `artifacts/experiments/gt-primary-2026-10-11-v2/` | New: metrics, predictions, alerts (with firing times, both leads), search log |
| `artifacts/models/lightgbm.dyn-v2.gt-primary-2026-10-11-v2/` | New serving artifact with transformation fingerprint |
| `artifacts/models/synthetic-demo.lightgbm.dyn-v2.v1/` | Synthetic demonstration model retrained on corrected features |
| `artifacts/registry.json` | Serving entries point to the v2 models; v1 entries kept |
| `data/processed/…/experiment/gt-primary-2026-10-11-v2/` | New origin table and split manifest; the v1 table is untouched |
| `reports/evaluation_report.md` | Now describes v2; v1 report preserved at `reports/archive/evaluation_report_gt-primary-2026-10-11-v1.md` |
| API contract | Additive fields only (`AlertOutcome`, `EventMetricsRow`, `EvaluationReport`); v1 reports still validate |

To reproduce v1, run `uv run glucotwin experiment build --experiment gt-primary-2026-10-11-v1` and then
`uv run glucotwin experiment run --experiment gt-primary-2026-10-11-v1`. The run re-registers v1 as serving, so
re-run v2 afterwards to restore it. To reproduce v2, run `make data experiment report` (no flag needed).

## 8. Limitations that remain

* The v2 test segment is the one inspected in v1. A genuinely fresh estimate needs new participants or a nested
  participant-level evaluation (`docs/next_experiment.md`).
* 14 participants, one US dataset, no Indian participants; overlapping origins are not independent patients.
* Prediction ranges under-cover their 80 % target, and coverage varies by participant (60–82 % at 30 minutes, 60–86 % at 60 minutes, v2 test).
* The warning threshold rule is unstable (flat F1) and blind to review workload.
* Leave-one-participant-out reuses globally selected hyperparameters; it is a secondary analysis, not a nested estimate.
* The proportional allocation of energy at non-aligned origins and the cadence-based time bases are approximations.
* Glucose windows remain closed intervals `[t − 60, t]` (up to 13 native readings); unchanged and documented, not a
  defect of the same kind.
