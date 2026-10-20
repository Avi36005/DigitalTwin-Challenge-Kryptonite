# Second sprint handoff — retraining study, 20 October 2026

Started 22:28 IST. The protocol was committed at 22:30 IST, the runner at 22:32, and the development fits ran
22:32:49–22:33:05 IST. Local work only: nothing was deployed, published or made public.

## 1. Hypotheses and how they differ from earlier work

D-048 re-weighted saved predictions of existing models without fitting anything. Earlier studies compared model
families (LightGBM L1/L2, CatBoost, Ridge), always with unweighted rows. Every model already predicted the change from
the latest reading.

D-049 fits new models to test three things that had never been tried in this repository:

* **A1:** every training participant gets equal total weight. No training code passed sample weights before this.
* **A2:** as A1, plus double weight on past-only rising origins (`slope_15 > 1`). Each person's total weight is kept
  the same.
* **B1:** as A1, plus 12 causal features from the previous 6, 12 and 24 hours of glucose (`hist-v1`).

## 2. Training setup

| Item | Value |
|---|---|
| Model and settings | LightGBM 4.7.0; the serving model's frozen per-horizon parameters; fixed rounds (397 at 30 min, 868 at 60 min); no search, no early stopping; 4 threads |
| Selection data | Final plan of `gt-2h-2026-10-20`: 12 development people in 3 fixed inner folds (split `e3695ca98334`) |
| Patient update | Declared update applied once, from an empty state for each new person |
| Fits | 24 fresh fits (4 arms × 3 folds × 2 horizons), 12.9 s of fitting in total |

Causality tests for `hist-v1` (`tests/test_history_features.py`) check four things: future readings never change a past
origin; a reading released after the origin is excluded; sparse windows are left missing; suspect readings are
excluded. All four pass.

## 3. Development results

Macro per-participant MAE in mg/dL, inner out-of-fold, on identical origins (33,891 at 60 minutes). Full table:
[`retrain_study.md`](retrain_study.md).

| Arm | 60 min | 30 min | 60 min, population only | 60 min, target > 180 | 60 min, rising > 2/min | First 24 h | Availability |
|---|---|---|---|---|---|---|---|
| B0 control | 22.78 | 14.27 | 24.68 | 36.88 | 39.25 | 24.44 | 100 % |
| A1 balanced | 22.82 | 14.28 | 24.78 | 36.88 | 39.40 | 24.46 | 100 % |
| A2 balanced + rising 2× | 22.71 | 14.32 | 24.59 | 37.05 | 39.34 | 24.31 | 100 % |
| B1 balanced + 24 h history | 22.37 | 14.19 | 23.30 | 36.70 | 38.43 | 23.93 | 100 % |

No arm was skipped.

## 4. Selection and assessment

The gate was a 60-minute personalised gain of at least 0.5 mg/dL over B0. The gains were A1 −0.04, A2 +0.07 and
B1 +0.41, so **no arm qualified**. Under the stop rule B0 is retained, the outer folds were not opened and no arm was
added.

A descriptive per-person check, run after selection and not used for it, suggests B1's history features help the
population model: error change −1.39 mg/dL [−2.62, −0.29] at 60 minutes, lower for 9 of 12 people. Once the patient
correction is applied, the error change is −0.41 [−1.07, +0.12] (a gain of 0.41, interval −0.12 to +1.07; 7 of 12
people better), so no reliable gain. That the correction already captures most of the history's benefit is a
plausible explanation, not a tested one. This is development evidence on previously inspected people, measured after
selection — a lead, not confirmation.

The people used here were inspected in earlier experiments, so all of this is internal research.

## 5. Warnings and ranges

No candidate qualified, so threshold and range calibration for a candidate were not run; the code path exists in
`scripts/retrain_study.py`. The serving warnings and ranges are unchanged: 61/64 onsets, 1.49 false alarms per
observed day, coverage 74.2 % / 74.0 %.

## 6. Serving model

Unchanged: `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`.

Replay parity was re-run and saved this sprint ([`serving_parity.md`](serving_parity.md),
[`serving_parity.json`](serving_parity.json)): 15,440 of 15,440 forecasts matched, with a largest difference of
0.0500 mg/dL, inside the 0.05 tolerance. That figure is display rounding (forecasts are rounded to 0.1 mg/dL). The run
used commit `40c3229`. Rollback is unchanged: `glucotwin research rollback --to lightgbm.dyn-v2.gt-primary-2026-10-11-v2`.

## 7. Tests run on the final code

| Check | Result |
|---|---|
| `uv run pytest -q` | all passed, 1 skipped (the existing skip; includes the 4 new history tests) |
| `uv run ruff check .` | clean |
| Web: typecheck, vitest, build | clean; 126/126; built |
| `scripts/check_submission.py` | 116 links, 0 failures |

Browser suites were not re-run: no app or server code changed since `49defb8`, where the standard suite passed 23/23
and the public suite 4/4.

**Artifacts:**
* Code and protocol: `configs/experiments/gt-retrain-2026-10-21.yaml`, `scripts/retrain_study.py`,
  `ml/glucotwin/research/history.py`.
* Report: `reports/retrain_study.md`.
* Saved results: `artifacts/research/gt-retrain-2026-10-21/` (development.json and predictions; git-ignored).
* Parity: `scripts/serving_parity.py`.
* Deck: slide 20 now includes D-049.

## 8. For the team

* **Video:** the model you demo is unchanged, so the recording plan stands. The extension chapter has one added
  sentence about D-049, and the deck is rebuilt with 24 slides.
* **Possible next study:** longer history and the patient correction tuned together, with the original-feature
  baseline given the same tuning budget, so any gain is not just extra tuning. It needs its own declared protocol and
  gate; D-049's 0.5 mg/dL threshold stays as it was.
* **Still outstanding:** record and upload the video, confirm the deadline time and the copyright holder, say
  "make it public", and submit the form. Deployment stays paused.
