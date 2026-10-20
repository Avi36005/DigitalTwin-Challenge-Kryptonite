# LightGBM–CatBoost blend for the fusion feature set — `gt-blend-2026-10-21`

Research experiment (decision D-048) on the saved population predictions of `gt-2h-2026-10-20`: 14 CGMacros Type 2 people, each held out entirely once (5 participant folds). These people and the CatBoost and LightGBM results on them were already inspected, so every number here is internal validation, not untouched evidence. Protocol recorded at 2026-10-20T15:06:25+00:00 before any blend was scored. Not the demo model; nothing promoted.

**Question.** For a person held out entirely, with the declared past-only patient update (v2 policy, k = 96, half-life 240 min) applied once, does `alpha × LightGBM + (1 − alpha) × CatBoost` on the profile-plus-wearable feature set (`dyn-prof-v2`) forecast glucose 60 minutes ahead at least 0.5 mg/dL better than LightGBM alone (alpha = 1, the matched incumbent)?

## 1. Development errors of the matched incumbent (alpha = 1)

Final development set (12 people, inner out-of-fold, patient update applied). Macro per-participant MAE in mg/dL.

| Stratum | 30 min | 60 min | 120 min | People (60 min) |
|---|---|---|---|---|
| all | 14.11 | 22.28 | 30.28 | 12 (33,891 origins) |
| glucose < 70 | 12.98 | 8.04 | 19.84 | 2 (38 origins) |
| glucose 70-180 | 12.71 | 20.80 | 29.22 | 12 (22,694 origins) |
| glucose > 180 | 21.10 | 30.72 | 39.67 | 12 (11,159 origins) |
| falling > 2 mg/dL/min | 19.47 | 29.15 | 35.31 | 12 (653 origins) |
| falling 1-2 | 17.03 | 25.20 | 32.01 | 12 (2,463 origins) |
| steady (|slope| <= 1) | 12.49 | 20.48 | 29.16 | 12 (27,485 origins) |
| rising 1-2 | 22.58 | 30.56 | 36.43 | 12 (2,187 origins) |
| rising > 2 | 28.45 | 39.49 | 43.20 | 12 (1,095 origins) |
| first 24 h (cold start) | 15.81 | 23.98 | 31.49 | 12 (3,303 origins) |
| after 24 h | 13.92 | 22.10 | 30.14 | 12 (30,588 origins) |
| degraded inputs | 15.36 | 26.45 | 60.35 | 5 (157 origins) |
| activity coverage < 0.5 | 11.84 | 18.94 | 26.90 | 1 (73 origins) |
| profile value missing | — | — | — | 0 (0 origins) |

Per-person 60-minute MAE ranges from 16.5 to 27.5 mg/dL (median 22.5). Mean signed error at 60 min when the target is above 180 mg/dL: -23.4 mg/dL (peaks are under-forecast); below 70 mg/dL: +49.6.

## 2. Development selection (inner out-of-fold only)

Selection score: mean of the 30- and 60-minute macro MAE after the patient update; one alpha for all horizons; ties within 0.01 mg/dL go to the larger alpha.

| alpha (LightGBM weight) | 30 min | 60 min | 120 min | 60 min, target > 180 | Score |
|---|---|---|---|---|---|
| 1 (LightGBM alone) | 14.11 | 22.28 | 30.28 | 37.52 | 18.192 |
| 0.75 **(selected)** | 14.08 | 22.26 | 30.32 | 37.34 | 18.168 |
| 0.5 | 14.08 | 22.31 | 30.44 | 37.22 | 18.197 |
| 0.25 | 14.12 | 22.45 | 30.64 | 37.17 | 18.285 |
| 0 (CatBoost alone) | 14.20 | 22.66 | 30.90 | 37.21 | 18.429 |

Each outer fold's own inner folds (development people of that fold only; used only if the assessment runs):

| Development set | People | Alpha chosen | 60-min gain vs alpha = 1 | 30-min gain vs alpha = 1 |
|---|---|---|---|---|
| outer-1 | 9 | 0.25 | +0.18 | +0.19 |
| outer-2 | 9 | 0.5 | +0.14 | +0.11 |
| outer-3 | 9 | 0.5 | +0.12 | +0.15 |
| outer-4 | 9 | 0.25 | +0.48 | +0.19 |
| outer-5 | 10 | 0.5 | +0.25 | +0.14 |
| final | 12 | 0.75 | +0.02 | +0.03 |

Development target (final development set): 60-minute improvement +0.02 mg/dL (needs ≥ 0.5); 30-minute worsening -0.03 (cap 0.25); high-glucose 60-minute worsening -0.18 (cap 1.0); availability drop 0.00 points (cap 0.5).

**Decision: target not met — the LightGBM incumbent is retained and the outer folds were not opened (declared stop rule).**

Regenerate: `uv run python scripts/blend_experiment.py --render`. Raw numbers: `artifacts/research/gt-blend-2026-10-21/` (analysis.json, development.json, assessment.json when run).
