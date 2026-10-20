# Retraining study — `gt-retrain-2026-10-21` (D-049)

Protocol committed before any fit (sha256 `d99847bfe808`); development run 2026-10-20T17:02:49+00:00 → 2026-10-20T17:03:05+00:00 UTC on git `a147e72`, LightGBM 4.7.0, split `e3695ca98334`. Every arm is a fresh LightGBM fit with the serving model's frozen parameters and rounds (no search, no early stopping). Selection: development inner out-of-fold on the final plan's 12 development people (3 inner folds), the declared patient update applied once. The 14 people were inspected in earlier experiments: internal research, not untouched evidence.

24 fits, 12.9 s of fitting in total.

## Development (inner out-of-fold, macro per-participant MAE in mg/dL, personalised unless stated)

| Arm | 60 min | 30 min | 60 min, population only | 60 min, target > 180 | 60 min, rising > 2 mg/dL/min | rising 1–2 | steady | falling | first 24 h | signed error, target > 180 | availability |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B0_control | **22.78** | 14.27 | 24.68 | 36.88 | 39.25 | 30.53 | 21.07 | 26.62 | 24.44 | -24.2 | 100.0 % |
| A1_participant_balanced | **22.82** | 14.28 | 24.78 | 36.88 | 39.40 | 30.66 | 21.10 | 26.67 | 24.46 | -24.3 | 100.0 % |
| A2_balanced_rising_2x | **22.71** | 14.32 | 24.59 | 37.05 | 39.34 | 30.75 | 20.97 | 26.58 | 24.31 | -24.3 | 100.0 % |
| B1_balanced_long_history | **22.37** | 14.19 | 23.30 | 36.70 | 38.43 | 29.78 | 20.74 | 25.56 | 23.93 | -21.0 | 100.0 % |
| persistence (comparator, saved) | 24.15 | 15.24 | | | | | | | | | |
| linear_trend (comparator, saved) | 24.55 | 14.66 | | | | | | | | | |

Same origins for every arm (33,891 at 60 min). High-glucose column: participants with ≥ 50 origins whose 60-minute target is above 180 mg/dL (12 people). Rising/steady/falling use the past-only `slope_15` at the origin; strata with fewer than 20 origins for a person leave that person out of that stratum.

## Selection against the declared gates

| Arm | 60-min gain vs B0 (≥ 0.5) | 30-min worsening (≤ 0.25) | high-glucose worsening (≤ 1.0) | availability drop (≤ 0.5 pt) | rising > 2 change | qualifies |
|---|---|---|---|---|---|---|
| A1_participant_balanced | -0.04 | +0.01 | +0.00 | +0.00 | -0.4 % | no |
| A2_balanced_rising_2x | +0.07 | +0.05 | +0.17 | +0.00 | -0.2 % | no |
| B1_balanced_long_history | +0.41 | -0.09 | -0.18 | +0.00 | +2.1 % | no |

Per-person paired differences on development, arm minus B0 (participant bootstrap, 2,000 resamples; descriptive, computed after selection and not used for it):

| Arm | 60 min personalised | 60 min population only | 30 min personalised | people better at 60 min (personalised) |
|---|---|---|---|---|
| A1 | +0.04 [+0.00, +0.08] | +0.09 [+0.02, +0.18] | +0.01 [-0.03, +0.04] | 4 of 12 |
| A2 | -0.07 [-0.20, +0.07] | -0.10 [-0.35, +0.15] | +0.05 [-0.02, +0.12] | 6 of 12 |
| B1 | -0.41 [-1.07, +0.12] | -1.39 [-2.62, -0.29] | -0.09 [-0.27, +0.13] | 7 of 12 |

**Decision:** no arm met the gate — B0 (the incumbent recipe) is retained, the outer folds were not opened and no new arm was added (stop rule).


Regenerate: `uv run python scripts/retrain_study.py render`. Raw numbers: `artifacts/research/gt-retrain-2026-10-21/development.json`.
