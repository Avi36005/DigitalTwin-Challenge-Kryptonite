# Earlier warnings, pooled ranges and the health record as a starting correction — `gt-warn-range-2026-10-20`

Research experiment (decision D-046), declared and committed before any arm was computed, on 20 Oct 2026. A re-analysis of the saved predictions of `gt-2h-2026-10-20` (no forecasting model refitted): 14 CGMacros Type 2 people, each held out entirely once (5 participant folds). Every arm, threshold, range and profile model was chosen or fitted on development and calibration people only; the outer predictions were read once at 2026-10-20T12:24:25+00:00. **These outer-fold people were already inspected** (D-043 and the time-in-warning check), and this protocol was written because of those results: internal validation, not untouched evidence. Not the demo model; nothing promoted.

## A. Two-hour warning: earlier, at the same workload

Per fold, the inner-fold rule chose: outer-1 A0_point at -10; outer-2 A0_point at -10; outer-3 A1_upper_calibration at +30; outer-4 A2_upper_pooled at +40; outer-5 A2_upper_pooled at +40. Constraint: at most 2 false alarms per observed day and at most 15 % of eligible time in warning, on inner folds.

| 120-minute warning | Onsets warned | Warned ≥ 30 min ahead | False alarms per observed day | Precision | Median forecast lead (IQR), min | Share of eligible time warning |
|---|---|---|---|---|---|---|
| A0 point forecasts at the D-043 threshold (incumbent) | 315 of 329 | 123 (37.4 %) | 1.62 | 0.58 | 15 (5–65) | 10.6 % |
| **Selected per fold (inner-fold rule)** | 291 of 329 | 126 (38.3 %) | 1.65 | 0.56 | 15 (5–75) | 12.5 % |
| A0 point forecasts, own inner threshold | 300 of 329 | 109 (33.1 %) | 1.45 | 0.60 | 15 (5–60) | 9.5 % |
| A1 forecast + range half-width (2 calibration people) | 252 of 329 | 111 (33.7 %) | 1.25 | 0.59 | 18 (5–81) | 11.6 % |
| A2 forecast + pooled range half-width | 266 of 329 | 115 (35.0 %) | 1.30 | 0.60 | 15 (5–79) | 11.6 % |
| A3 120-minute forecast only | 228 of 329 | 104 (31.6 %) | 1.14 | 0.59 | 20 (5–85) | 10.2 % |

Selected minus incumbent (participant-cluster bootstrap, 14 people): onsets warned ≥ 30 min ahead +0.9 points [-5.5, +6.6]; false alarms per observed day +0.03 [-0.35, +0.47].

## B. Prediction ranges (target coverage 80 %)

| Range calibration | 30 min coverage (width) | 60 min | 120 min | Per-person median coverage, 120 min |
|---|---|---|---|---|
| B0 two calibration people (incumbent) | 79.8 % (43 mg/dL) | 78.2 % (66 mg/dL) | 76.5 % (88 mg/dL) | 76.9 % |
| **B1 development + calibration people pooled** (declared primary) | 79.8 % (43 mg/dL) | 79.5 % (68 mg/dL) | 79.8 % (95 mg/dL) | 81.2 % |
| B2 pooled, separate below / above 180 mg/dL | 80.1 % (43 mg/dL) | 80.0 % (68 mg/dL) | 80.0 % (94 mg/dL) | 80.8 % |

## C. Health record as a starting personal correction

A ridge regression on the 8 baseline profile values, fitted on development people, predicts each new person's average forecast error and adds it from their first reading (no glucose of that person used).

| Horizon | Population only MAE | + profile prior (C1) | Personalised (patient correction) | C1 minus population only (95 % CI), people better | C1 minus personalised |
|---|---|---|---|---|---|
| 30 min | 14.15 | 14.13 | 13.95 | -0.03 [-0.25, +0.26], 10 of 14 | +0.17 [-0.06, +0.47] |
| 60 min | 22.61 | 22.60 | 22.29 | -0.01 [-0.55, +0.63], 10 of 14 | +0.31 [-0.27, +0.97] |
| 120 min | 31.39 | 30.86 | 30.62 | -0.53 [-1.57, +0.58], 10 of 14 | +0.24 [-0.90, +1.33] |
| 30 min (first 24 h) | 16.14 | 15.99 | 16.13 | -0.15 [-0.50, +0.15], 9 of 14 | -0.13 [-0.48, +0.16] |
| 60 min (first 24 h) | 24.36 | 24.01 | 24.34 | -0.35 [-1.46, +0.47], 9 of 14 | -0.34 [-1.46, +0.45] |
| 120 min (first 24 h) | 32.59 | 31.66 | 32.54 | -0.93 [-2.74, +0.48], 9 of 14 | -0.88 [-2.70, +0.53] |

Declared claim rule (interval of C1 minus population only below zero at 120 min): **not met — no reliable benefit shown**.

Regenerate: `uv run python scripts/warning_range_experiment.py --render` (rewrites this report from the saved summary; a full re-run needs `--reopen-reason` and is then exploratory). Raw numbers: `artifacts/research/gt-warn-range-2026-10-20/summary.json`.
