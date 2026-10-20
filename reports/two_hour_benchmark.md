# Two-hour benchmark — `gt-2h-2026-10-20`

Research experiment (decision D-043), declared and frozen before any fit on 20 Oct 2026, the submission day. Protocol frozen 2026-10-20T09:18:07+00:00 (hash `8ddaa10d1287`, split `e3695ca98334`); outer-fold assessment opened once at 2026-10-20T09:35:52+00:00. 14 CGMacros Type 2 people, each held out entirely once (5 participant folds, same folds as `gt-nested-2026-10-12-v1`). These people were already inspected in earlier experiments, so this is internal validation, not untouched evidence. Nothing was promoted; the demo model is unchanged.

Selected per fold: outer-1 `lightgbm_l1:cgm-only-v1`, outer-2 `lightgbm_l1:cgm-only-v1`, outer-3 `ridge:cgm-only-v1`, outer-4 `lightgbm_l2:cgm-only-v1`, outer-5 `ridge:cgm-only-v1`, final `ridge:cgm-only-v1`.

## Forecast error on people held out (macro MAE, mg/dL)

| Pipeline | 30 min | 60 min | 120 min | Range coverage at 120 min (target 80 %) |
|---|---|---|---|---|
| Persistence | 15.339 | 24.467 | 35.869 | 76.9 % |
| Selected pipeline, population only | 14.153 | 22.614 | 31.389 | 77.5 % |
| **Selected pipeline, personalised** (the rule's choice per fold) | 13.953 | 22.288 | 30.617 | 76.5 % |
| LightGBM, CGM only | 14.288 | 22.833 | 31.529 | 77.3 % |
| LightGBM, CGM + wearable | 15.041 | 25.513 | 34.028 | 80.5 % |
| LightGBM, CGM + wearable + profile (EHR-like) | 15.081 | 24.781 | 33.173 | 77.2 % |
| Ridge, CGM only | 14.094 | 22.688 | 31.864 | 77.2 % |
| Ridge, CGM + wearable | 14.396 | 23.385 | 33.388 | 75.9 % |
| Ridge, CGM + wearable + profile (EHR-like) | 16.607 | 28.882 | 46.034 | 73.3 % |

## Paired differences, mg/dL (negative = first pipeline better; 95 % participant bootstrap; people better)

| Comparison | 30 min | 60 min | 120 min |
|---|---|---|---|
| Selected (personalised) minus persistence | -1.39 [-1.78, -1.02], 14/14 | -2.18 [-2.74, -1.59], 13/14 | -5.25 [-6.44, -4.05], 14/14 |
| Profile (EHR-like) inputs: LightGBM dyn-prof-v2 minus dyn-v2 | +0.04 [-0.50, +0.61], 8/14 | -0.73 [-2.33, +0.68], 6/14 | -0.86 [-2.60, +1.02], 8/14 |
| Profile (EHR-like) inputs: Ridge dyn-prof-v2 minus dyn-v2 | +2.21 [+0.54, +4.00], 4/14 | +5.50 [+0.88, +11.97], 5/14 | +12.65 [+1.34, +29.24], 4/14 |
| Wearable inputs: LightGBM dyn-v2 minus CGM-only | +0.75 [+0.34, +1.20], 4/14 | +2.68 [+1.28, +4.38], 2/14 | +2.50 [+0.96, +4.37], 3/14 |

## New high-glucose onsets (> 180 mg/dL, sustained 15 min): warnings on people held out

Threshold per fold chosen on inner folds only: most onsets warned with at most 2 false alarms per observed forecastable day. Lead = onset minus the earliest firing that forecast it (within the horizon).

| Warning | Onsets warned | False alarms per observed day | Precision | Median lead (IQR), min |
|---|---|---|---|---|
| **Selected pipeline, personalised** (the rule's choice per fold), **60-min warning** | 313 of 329 (95.1 %) | 1.478 | 0.6054 | 10.0 (5.0–30.0) |
| **Selected pipeline, personalised** (the rule's choice per fold), **120-min warning** | 315 of 329 (95.7 %) | 1.623 | 0.5844 | 15.0 (5.0–65.0) |
| Persistence, **60-min warning** | 283 of 329 (86.0 %) | 1.347 | 0.6034 | 10.0 (5.0–25.0) |
| Persistence, **120-min warning** | 297 of 329 (90.3 %) | 1.521 | 0.5858 | 15.0 (5.0–50.0) |

Regenerate: `uv run python scripts/summarise_two_hour.py`. Raw numbers: `artifacts/research/gt-2h-2026-10-20/two_hour_summary.json`.
