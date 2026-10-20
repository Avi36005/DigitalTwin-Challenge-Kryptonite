# Cold start: does the profile help in a new person's first hours?

**Exploratory, not pre-specified.** This look was chosen after the frozen experiments showed that the static profile (EHR-like inputs: age, sex, BMI, HbA1c, fasting glucose and insulin, triglycerides, HDL) gave no reliable benefit on people held out over their whole recordings, so it is a search for a subgroup where it might help and must be read as hypothesis-generating. The 14 CGMacros Type 2 people (2–3 per participant fold, 5 folds) were already inspected in those experiments. Nothing was fitted and no assessment was re-opened: every number comes from the saved outer-fold predictions of `gt-nested-2026-10-12-v1` (30 and 60 min) and `gt-2h-2026-10-20` (30, 60 and 120 min), track `multimodal_5min`, mode `off` (population model, no personalisation: the cold-start case), excluding origins with insufficient quality or without a target. Each pipeline with the profile is paired with its twin without it on the origins both scored. Time is minutes since the recording's first reading. Per stratum: mean absolute error per person (people with at least 20 paired origins in that stratum), then the macro mean; the difference is profile minus no-profile (negative = profile better) with a participant-cluster bootstrap 95 % interval (2000 resamples, seed 20261012).

## `gt-nested-2026-10-12-v1`

| Model | Time since first reading | Horizon | People (≥ 20 origins / any) | Origins | MAE without → with profile, mg/dL | Difference [95 % CI], mg/dL | Better with profile |
|---|---|---|---|---|---|---|---|
| LightGBM | First 6 h | 30 min | 14 / 14 | 840 | 18.51 → 18.35 | -0.17 [-0.88, +0.60] | 9/14 |
| LightGBM | 6–24 h | 30 min | 14 / 14 | 3,015 | 15.92 → 16.47 | +0.55 [-0.09, +1.18] | 4/14 |
| LightGBM | After 24 h | 30 min | 14 / 14 | 35,791 | 14.68 → 15.01 | +0.33 [-0.25, +0.94] | 5/14 |
| LightGBM | *Whole recording (reference)* | 30 min | 14 / 14 | 39,646 | 14.85 → 15.19 | +0.34 [-0.24, +0.93] | 4/14 |
| LightGBM | First 6 h | 60 min | 14 / 14 | 840 | 27.06 → 26.20 | -0.86 [-2.52, +0.90] | 8/14 |
| LightGBM | 6–24 h | 60 min | 14 / 14 | 3,015 | 25.93 → 25.83 | -0.10 [-1.56, +1.44] | 7/14 |
| LightGBM | After 24 h | 60 min | 14 / 14 | 35,698 | 25.17 → 24.37 | -0.80 [-2.20, +0.57] | 7/14 |
| LightGBM | *Whole recording (reference)* | 60 min | 14 / 14 | 39,553 | 25.27 → 24.52 | -0.75 [-2.13, +0.59] | 7/14 |
| CatBoost | First 6 h | 30 min | 14 / 14 | 840 | 18.96 → 18.21 | -0.75 [-1.54, +0.24] | 12/14 |
| CatBoost | 6–24 h | 30 min | 14 / 14 | 3,015 | 16.39 → 16.43 | +0.04 [-0.69, +0.71] | 6/14 |
| CatBoost | After 24 h | 30 min | 14 / 14 | 35,791 | 15.06 → 14.77 | -0.29 [-0.76, +0.20] | 7/14 |
| CatBoost | *Whole recording (reference)* | 30 min | 14 / 14 | 39,646 | 15.25 → 14.97 | -0.28 [-0.74, +0.22] | 7/14 |
| CatBoost | First 6 h | 60 min | 14 / 14 | 840 | 27.24 → 26.13 | -1.11 [-3.24, +1.30] | 10/14 |
| CatBoost | 6–24 h | 60 min | 14 / 14 | 3,015 | 26.66 → 26.48 | -0.17 [-2.07, +1.53] | 6/14 |
| CatBoost | After 24 h | 60 min | 14 / 14 | 35,698 | 25.18 → 24.35 | -0.83 [-2.21, +0.60] | 7/14 |
| CatBoost | *Whole recording (reference)* | 60 min | 14 / 14 | 39,553 | 25.33 → 24.55 | -0.78 [-2.18, +0.65] | 7/14 |
| Ridge | First 6 h | 30 min | 14 / 14 | 840 | 17.81 → 20.38 | +2.58 [+0.49, +4.87] | 6/14 |
| Ridge | 6–24 h | 30 min | 14 / 14 | 3,015 | 16.30 → 17.85 | +1.55 [+0.16, +3.05] | 6/14 |
| Ridge | After 24 h | 30 min | 14 / 14 | 35,791 | 14.16 → 16.42 | +2.26 [+0.69, +4.00] | 3/14 |
| Ridge | *Whole recording (reference)* | 30 min | 14 / 14 | 39,646 | 14.40 → 16.61 | +2.21 [+0.65, +3.94] | 4/14 |
| Ridge | First 6 h | 60 min | 14 / 14 | 840 | 25.36 → 32.96 | +7.60 [+0.75, +15.86] | 7/14 |
| Ridge | 6–24 h | 60 min | 14 / 14 | 3,015 | 25.45 → 29.31 | +3.86 [-0.27, +8.67] | 7/14 |
| Ridge | After 24 h | 60 min | 14 / 14 | 35,698 | 23.17 → 28.75 | +5.59 [+0.91, +11.70] | 5/14 |
| Ridge | *Whole recording (reference)* | 60 min | 14 / 14 | 39,553 | 23.38 → 28.88 | +5.50 [+0.83, +11.50] | 5/14 |

Scored origins in the first 6 h start at 60 min (60 minutes of history are required). Pairing kept every scored origin.

## `gt-2h-2026-10-20`

| Model | Time since first reading | Horizon | People (≥ 20 origins / any) | Origins | MAE without → with profile, mg/dL | Difference [95 % CI], mg/dL | Better with profile |
|---|---|---|---|---|---|---|---|
| LightGBM | First 6 h | 30 min | 14 / 14 | 840 | 18.24 → 18.26 | +0.02 [-0.67, +0.84] | 8/14 |
| LightGBM | 6–24 h | 30 min | 14 / 14 | 3,015 | 16.12 → 16.35 | +0.23 [-0.48, +0.95] | 6/14 |
| LightGBM | After 24 h | 30 min | 14 / 14 | 35,791 | 14.88 → 14.90 | +0.02 [-0.53, +0.60] | 8/14 |
| LightGBM | *Whole recording (reference)* | 30 min | 14 / 14 | 39,646 | 15.04 → 15.08 | +0.04 [-0.51, +0.61] | 8/14 |
| LightGBM | First 6 h | 60 min | 14 / 14 | 840 | 27.57 → 25.94 | -1.63 [-2.99, -0.34] | 11/14 |
| LightGBM | 6–24 h | 60 min | 14 / 14 | 3,015 | 26.22 → 26.12 | -0.10 [-1.66, +1.25] | 5/14 |
| LightGBM | After 24 h | 60 min | 14 / 14 | 35,698 | 25.41 → 24.64 | -0.76 [-2.39, +0.65] | 6/14 |
| LightGBM | *Whole recording (reference)* | 60 min | 14 / 14 | 39,553 | 25.51 → 24.78 | -0.73 [-2.30, +0.65] | 6/14 |
| LightGBM | First 6 h | 120 min | 14 / 14 | 840 | 26.86 → 26.82 | -0.04 [-2.76, +3.30] | 8/14 |
| LightGBM | 6–24 h | 120 min | 14 / 14 | 3,015 | 36.09 → 35.93 | -0.16 [-2.97, +2.98] | 6/14 |
| LightGBM | After 24 h | 120 min | 14 / 14 | 35,529 | 34.02 → 33.09 | -0.94 [-2.78, +0.91] | 8/14 |
| LightGBM | *Whole recording (reference)* | 120 min | 14 / 14 | 39,384 | 34.03 → 33.17 | -0.86 [-2.69, +0.96] | 8/14 |
| CatBoost | First 6 h | 30 min | 14 / 14 | 840 | 18.76 → 18.16 | -0.59 [-1.29, +0.21] | 10/14 |
| CatBoost | 6–24 h | 30 min | 14 / 14 | 3,015 | 16.29 → 16.21 | -0.09 [-0.80, +0.52] | 5/14 |
| CatBoost | After 24 h | 30 min | 14 / 14 | 35,791 | 14.86 → 14.54 | -0.32 [-0.69, +0.05] | 7/14 |
| CatBoost | *Whole recording (reference)* | 30 min | 14 / 14 | 39,646 | 15.05 → 14.74 | -0.31 [-0.68, +0.06] | 7/14 |
| CatBoost | First 6 h | 60 min | 14 / 14 | 840 | 27.72 → 25.45 | -2.27 [-4.20, -0.22] | 10/14 |
| CatBoost | 6–24 h | 60 min | 14 / 14 | 3,015 | 26.66 → 26.23 | -0.44 [-2.47, +1.31] | 5/14 |
| CatBoost | After 24 h | 60 min | 14 / 14 | 35,698 | 25.27 → 24.06 | -1.21 [-2.88, +0.41] | 7/14 |
| CatBoost | *Whole recording (reference)* | 60 min | 14 / 14 | 39,553 | 25.43 → 24.26 | -1.17 [-2.88, +0.44] | 7/14 |
| CatBoost | First 6 h | 120 min | 14 / 14 | 840 | 30.52 → 26.36 | -4.17 [-7.06, -1.55] | 10/14 |
| CatBoost | 6–24 h | 120 min | 14 / 14 | 3,015 | 39.51 → 36.88 | -2.63 [-6.36, +0.73] | 6/14 |
| CatBoost | After 24 h | 120 min | 14 / 14 | 35,529 | 36.62 → 32.49 | -4.13 [-7.06, -1.44] | 11/14 |
| CatBoost | *Whole recording (reference)* | 120 min | 14 / 14 | 39,384 | 36.72 → 32.70 | -4.02 [-6.87, -1.38] | 10/14 |
| Ridge | First 6 h | 30 min | 14 / 14 | 840 | 17.81 → 20.38 | +2.58 [+0.49, +4.87] | 6/14 |
| Ridge | 6–24 h | 30 min | 14 / 14 | 3,015 | 16.30 → 17.85 | +1.55 [+0.16, +3.05] | 6/14 |
| Ridge | After 24 h | 30 min | 14 / 14 | 35,791 | 14.16 → 16.42 | +2.26 [+0.69, +4.00] | 3/14 |
| Ridge | *Whole recording (reference)* | 30 min | 14 / 14 | 39,646 | 14.40 → 16.61 | +2.21 [+0.65, +3.94] | 4/14 |
| Ridge | First 6 h | 60 min | 14 / 14 | 840 | 25.36 → 32.96 | +7.60 [+0.75, +15.86] | 7/14 |
| Ridge | 6–24 h | 60 min | 14 / 14 | 3,015 | 25.45 → 29.31 | +3.86 [-0.27, +8.67] | 7/14 |
| Ridge | After 24 h | 60 min | 14 / 14 | 35,698 | 23.17 → 28.75 | +5.59 [+0.91, +11.70] | 5/14 |
| Ridge | *Whole recording (reference)* | 60 min | 14 / 14 | 39,553 | 23.38 → 28.88 | +5.50 [+0.83, +11.50] | 5/14 |
| Ridge | First 6 h | 120 min | 14 / 14 | 840 | 27.61 → 45.85 | +18.24 [+3.95, +36.19] | 5/14 |
| Ridge | 6–24 h | 120 min | 14 / 14 | 3,015 | 36.15 → 44.76 | +8.61 [-1.64, +21.15] | 8/14 |
| Ridge | After 24 h | 120 min | 14 / 14 | 35,529 | 33.29 → 46.15 | +12.85 [+1.68, +28.89] | 3/14 |
| Ridge | *Whole recording (reference)* | 120 min | 14 / 14 | 39,384 | 33.39 → 46.03 | +12.65 [+1.50, +28.43] | 4/14 |

Scored origins in the first 6 h start at 60 min (60 minutes of history are required). Pairing kept every scored origin.

## Reading

**The profile may help the tree models in the first 6 hours, but this is not a reliable cold-start benefit.** 3 of 10 first-6-hour differences for LightGBM and CatBoost have a 95 % interval below zero: LightGBM 60 min in `gt-2h-2026-10-20`, -1.63 [-2.99, -0.34], 11/14 better (whole recording -0.73 [-2.30, +0.65]; same comparison in `gt-nested-2026-10-12-v1` -0.86 [-2.52, +0.90]); CatBoost 60 min in `gt-2h-2026-10-20`, -2.27 [-4.20, -0.22], 10/14 better (whole recording -1.17 [-2.88, +0.44]; same comparison in `gt-nested-2026-10-12-v1` -1.11 [-3.24, +1.30]); CatBoost 120 min in `gt-2h-2026-10-20`, -4.17 [-7.06, -1.55], 10/14 better (whole recording -4.02 [-6.87, -1.38]). None comes from `gt-nested-2026-10-12-v1`, whose sibling fits on the same people show no first-6-hour interval below zero. The CatBoost 120-min benefit holds over the whole recording as well, so it is not specific to the first hours (the frozen reports compared the profile for LightGBM and Ridge only; without the profile CatBoost is weaker than LightGBM at this horizon, MAE 36.72 vs 34.03; with it, 32.70 vs LightGBM's 33.17). For the other 2, the whole recording points the same way with an interval that includes zero, so the larger early difference is as consistent with noise as with a real early effect. Ridge with the profile is worse: 5 of 5 first-6-hour intervals lie above zero (+2.58 to +18.24 mg/dL), as over the whole recording. Caveats: 14 people (2–3 per fold), each person's first 6 hours hold only 60 scored origins (one stretch at the start of the recording, from 60 minutes of history onward); 45 stratified intervals are shown, so a few excluding zero are expected by chance; the two experiments share people and folds (their Ridge numbers are identical), so they are not independent replications. In mode "off" the population model never learns the person and its inputs reach back at most 180 minutes, so the first hours differ from later ones in a shorter glucose history and in what the person did then, not in what the twin knows about them; personalised modes, where cold start matters most, are not examined. At most this is a hypothesis for a pre-specified test on new people; nothing here changes the frozen conclusions or the served model.

Regenerate: `uv run python scripts/cold_start_profile.py`.
