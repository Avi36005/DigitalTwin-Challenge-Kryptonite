# Prediction ranges for the serving pipeline — `gt-ranges-2026-10-21` (D-050)

Pipeline `lightgbm:dyn-prof-v2 (adaptive)` of `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`; point forecasts fixed, only the 80 % range studied. Protocol committed before any candidate was computed. Origins: validation 7,532, calibration 7,532, test 15,389 (both horizons).

## Pre-test check (calibrate on validation, score on the later calibration segment; no test data)

| Shape | 30 min coverage (width) | 60 min coverage (width) | 60 min per-person range | 60 min rising / steady / falling |
|---|---|---|---|---|
| G — one range per horizon | 85.8 % (42) | 87.1 % (68) | 74.3 %–98.5 % | 71.5 % / 89.1 % / 77.3 % |
| T — range per past-only trend stratum | 85.4 % (40) | 86.1 % (63) | 72.1 %–98.5 % | 87.7 % / 86.2 % / 82.8 % |

Mean coverage error: G 6.48 points, T 5.77 points; mean width G 55.0, T 51.6 mg/dL. Declared rule (T if ≥ 1.0 point better and ≤ 15 % wider): **G kept**.

## Final test segment, read once (retrospective: this segment was inspected on 11–13 Oct)

| Ranges | Half-widths 30 / 60 min | 30 min coverage (width) | 60 min coverage (width) | 60 min per-person range | 60 min rising / steady / falling |
|---|---|---|---|---|---|
| Incumbent (served): G on the calibration segment | 16.7 / 26.4 | 74.2 % (33) | 74.0 % (53) | 51.4 %–87.6 % | 51.6 % / 77.9 % / 59.0 % |
| G on validation + calibration | 18.9 / 29.8 | 77.9 % (38) | 78.7 % (60) | 57.7 %–88.6 % | 56.5 % / 82.5 % / 65.2 % |

Widths in mg/dL (full range, upper minus lower). Trend strata use `slope_15` at the origin (past readings only). Test origins are later recordings of the same 14 people, so there is no first-day stratum. Coverage is pooled over origins; a range is a statement about many forecasts, not a guarantee for one.

Regenerate: `uv run python scripts/serving_ranges_study.py`. Raw numbers: `artifacts/research/gt-ranges-2026-10-21/summary.json`.
