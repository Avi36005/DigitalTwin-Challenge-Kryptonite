# Nested tuning study — `gt-tune-2026-10-21` (D-051)

Protocol committed before any fit (sha256 `ad758b9481c1`). Outer folds first opened 2026-10-20T17:51:02+00:00; run 2026-10-20T17:46:24+00:00 → 2026-10-20T18:12:33+00:00 UTC, 1,830 LightGBM fits (1524 s of fitting), LightGBM 4.7.0. Each arm got the same 30 seeded trials per horizon (each trial samples one boosting-round count from 300, 600 or 1200) and the same patient-correction grid, chosen on each outer fold's inner folds; the assessment people never influenced a choice. The 14 people were inspected in earlier experiments: internal validation, not untouched evidence.

## Assessment people (each held out once), macro per-participant MAE in mg/dL

| Pipeline | 60 min | 30 min | 60 min, population only | 60 min, target > 180 | rising > 2/min | steady | falling | first 24 h |
|---|---|---|---|---|---|---|---|---|
| C0 — current fusion features, tuned | **22.27** | 13.91 | 24.10 | 38.97 | 38.36 | 20.59 | 25.64 | 24.49 |
| C1 — + 6/12/24-hour history, tuned | **21.90** | 13.84 | 22.92 | 38.17 | 38.60 | 20.19 | 25.17 | 24.10 |
| R0 — serving recipe, frozen settings | **22.55** | 14.11 | 24.25 | 38.41 | 38.96 | 20.85 | 25.66 | 24.43 |
| Persistence | **24.47** | 15.34 | 24.47 | 45.03 | 42.44 | 21.78 | 35.91 | 26.19 |

Identical origins: 39,553 at 60 min, 14 people.

## Paired differences (first minus second; negative = lower error; 95 % participant bootstrap)

| Comparison | 60 min personalised | 60 min population only | 30 min personalised | people better (60 min) |
|---|---|---|---|---|
| C1 vs C0 (history, equal tuning) | -0.37 [-0.63, -0.06] | -1.18 [-1.97, -0.52] | -0.06 [-0.19, +0.07] | 10 of 14 |
| C0 vs R0 (effect of tuning) | -0.28 [-1.06, +0.37] | -0.15 [-0.44, +0.14] | -0.21 [-0.50, +0.03] | 5 of 14 |
| C1 vs R0 | -0.65 [-1.41, +0.07] | -1.33 [-2.15, -0.58] | -0.27 [-0.60, -0.00] | 8 of 14 |

**Declared rule (C1 better only if the 60-minute difference ≤ −0.5 with its interval below 0, 30-minute worsening ≤ 0.25, high-glucose worsening ≤ 1.0):** not met (-0.37 [-0.63, -0.06]; 30 min -0.06; high-glucose -0.80). The serving model is not changed by this study.

## Choices per outer fold (inner folds only)

| Fold | Arm | 30-min trial / rounds | 60-min trial / rounds | Correction |
|---|---|---|---|---|
| outer-1 | C0 | 8 / 300 | 8 / 300 | k24_hl120 |
| outer-1 | C1 | 8 / 300 | 8 / 300 | k24_hl120 |
| outer-2 | C0 | 8 / 300 | 8 / 300 | k24_hl720 |
| outer-2 | C1 | 8 / 300 | 8 / 300 | k24_hl240 |
| outer-3 | C0 | 8 / 300 | 4 / 300 | k24_hl120 |
| outer-3 | C1 | 8 / 300 | 8 / 300 | k24_hl120 |
| outer-4 | C0 | 8 / 300 | 4 / 300 | k24_hl720 |
| outer-4 | C1 | 8 / 300 | 8 / 300 | k48_hl720 |
| outer-5 | C0 | 8 / 300 | 4 / 300 | k24_hl720 |
| outer-5 | C1 | 8 / 300 | 8 / 300 | k48_hl720 |

Regenerate: `uv run python scripts/tune_study.py render`. Raw numbers: `artifacts/research/gt-tune-2026-10-21/summary.json`.
