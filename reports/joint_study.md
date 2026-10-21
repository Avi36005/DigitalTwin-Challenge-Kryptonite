# Joint model + correction selection — `gt-joint-2026-10-21` (D-052)

Protocol committed before any fit (sha256 `7b622c76f13b`); outer folds first opened 2026-10-20T18:57:03+00:00; run 2026-10-20T18:44:07+00:00 → 2026-10-20T20:05:09+00:00 UTC. Fresh fits: LightGBM 1,050 (1533 s), CatBoost 520 (2236 s); failures 0; J2 ceiling reached: False. Inside each outer fold, configuration and patient correction were chosen together on the inner personalised error and the family on the inner 60-minute error; the assessment people never influenced a choice. Families chosen per fold: outer-1 J0, outer-2 J2, outer-3 J0, outer-4 J2, outer-5 J2. The 14 people were inspected in earlier experiments: internal validation, not independent confirmation.

## Assessment people, macro per-participant MAE in mg/dL (identical origins)

| Procedure | 60 min | 30 min | 60 min population only | 60 min, target > 180 | rising > 2/min | steady | falling | first 24 h | availability |
|---|---|---|---|---|---|---|---|---|---|
| **S — selected procedure (family chosen inside each fold)** | **21.62** | 13.64 | 22.63 | 39.98 | 38.28 | 19.84 | 25.11 | 23.74 | 100.0 % |
| R0 — refitted serving recipe | **22.50** | 14.14 | 24.11 | 38.28 | 38.84 | 20.80 | 25.78 | 24.43 | 100.0 % |
| J0 — LightGBM, current features | **21.64** | 13.78 | 23.08 | 40.04 | 38.87 | 19.84 | 25.23 | 24.08 | 100.0 % |
| J1 — LightGBM + 24-hour history | **21.79** | 13.82 | 22.18 | 39.75 | 39.03 | 20.04 | 25.07 | 24.25 | 100.0 % |
| J2 — CatBoost + 24-hour history | **21.57** | 13.65 | 21.80 | 40.21 | 39.06 | 19.77 | 25.09 | 23.98 | 100.0 % |
| Persistence | **24.47** | 15.34 | 24.47 | 45.03 | 42.44 | 21.78 | 35.91 | 26.19 | — |
| Linear trend | **24.71** | 14.66 | 24.71 | 44.63 | 52.36 | 21.83 | 32.34 | 27.93 | — |

## Paired differences (first minus second, negative = lower error, 95 % participant bootstrap)

| Comparison | 60 min personalised | 60 min population only | 30 min personalised | people better (60) |
|---|---|---|---|---|
| S vs R0 | -0.88 [-1.75, -0.13] | -1.49 [-2.67, -0.45] | -0.50 [-0.85, -0.18] | 8 of 14 |
| J0 vs R0 | -0.86 [-1.71, -0.13] | -1.04 [-2.15, -0.09] | -0.36 [-0.73, -0.05] | 8 of 14 |
| J1 vs R0 | -0.71 [-1.65, +0.11] | -1.93 [-3.28, -0.78] | -0.32 [-0.67, -0.01] | 8 of 14 |
| J2 vs R0 | -0.93 [-1.84, -0.15] | -2.31 [-3.65, -1.14] | -0.49 [-0.89, -0.12] | 9 of 14 |
| J1 vs J0 | +0.14 [-0.07, +0.34] | -0.90 [-1.60, -0.33] | +0.04 [-0.07, +0.14] | 5 of 14 |
| J2 vs J1 | -0.22 [-0.35, -0.08] | -0.38 [-0.64, -0.06] | -0.17 [-0.30, -0.02] | 10 of 14 |

**Primary gate (S vs R0: ≤ −0.5 mg/dL at 60 min with the interval below 0; 30-min worsening ≤ 0.25; high-glucose worsening ≤ 1.0; availability drop ≤ 0.5 pt): not met** — -0.88 [-1.75, -0.13]; 30 min -0.50; high-glucose +1.70; availability +0.00 pt.

## 60-minute warning (thresholds chosen on inner folds per outer fold)

| Procedure | Onsets | Detected / missed | Warned ≥ 15 / 30 / 60 min (all onsets) | False alarms / observed day | Precision | Time in warning | Median episode | Lead median (IQR) |
|---|---|---|---|---|---|---|---|---|
| S | 329 | 320 / 9 | 52.3 % / 34.3 % / 14.9 % | 1.79 | 0.56 | 10.4 % | 15.00 min | 15.00 (5.00–40.00) min |
| R0 | 329 | 255 / 74 | 35.6 % / 18.8 % / 7.9 % | 1.19 | 0.61 | 5.1 % | 10.00 min | 10.00 (5.00–25.00) min |

Release guardrails vs R0 (false alarms ≤ +0.10/day, time in warning ≤ +2 pt, warned ≥ 30 min ≥ −2 pt): **not met** (+0.60/day, +5.4 pt, +15.5 pt).

## 80 % ranges (calibrated on each fold's calibration people for the exact procedure)

| Procedure | 30 min coverage (width) | 60 min coverage (width) | 60 min per-person range | 60 min rising > 2 / steady |
|---|---|---|---|---|
| S | 79.9 % (42.28) | 78.4 % (63.20) | 68.8 %–89.4 % | 47.0 % / 81.9 % |
| R0 | 79.7 % (43.96) | 79.2 % (68.48) | 64.0 %–90.2 % | 50.7 % / 82.3 % |

## Choices per outer fold (inner folds only)

| Fold | Selected | J0 30 / 60 | J1 30 / 60 | J2 30 / 60 |
|---|---|---|---|---|
| outer-1 | J0 | #3 k96_hl720 (14.49) / #1 k96_hl720 (23.40) | #3 k24_hl120 (14.62) / #3 k24_hl120 (24.00) | #2 k48_hl120 (14.48) / #2 k24_hl120 (23.34) |
| outer-2 | J2 | #3 k96_hl720 (13.32) / #3 k96_hl720 (20.61) | #3 k24_hl240 (13.22) / #3 k96_hl720 (20.66) | #2 k48_hl240 (13.13) / #2 k96_hl720 (20.36) |
| outer-3 | J0 | #1 k48_hl240 (13.52) / #1 k192_hl720 (21.78) | #13 k24_hl120 (13.55) / #1 k24_hl120 (21.93) | #2 k24_hl120 (13.44) / #10 k24_hl120 (21.72) |
| outer-4 | J2 | #13 k48_hl720 (14.07) / #3 k48_hl720 (22.28) | #13 k96_hl720 (13.97) / #1 k96_hl720 (21.93) | #2 k96_hl720 (13.90) / #10 k96_hl720 (21.63) |
| outer-5 | J2 | #13 k48_hl720 (14.30) / #13 k24_hl720 (22.72) | #13 k48_hl720 (14.15) / #1 k48_hl720 (22.49) | #2 k96_hl720 (13.98) / #2 k48_hl720 (22.20) |

Regenerate: `uv run python scripts/joint_study.py render`. Raw numbers: `artifacts/research/gt-joint-2026-10-21/summary.json`.
