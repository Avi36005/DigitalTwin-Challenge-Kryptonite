# Forecast error by glucose trend — serving model `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`

Validation segment of `gt-primary-2026-10-13-fusion` (used for model selection, before the final test segment; the test segment is not read here). Pipeline `lightgbm:dyn-prof-v2` with adaptive personalisation. Trend = `slope_15`, the least-squares slope of native readings over the last 15 minutes. Macro per-participant MAE in mg/dL; a stratum with fewer than 3 participants is not summarised. Descriptive only: it says when forecasts tend to be less accurate, not why.

| Trend | 30-min MAE (origins) · served 80 % range coverage | 60-min MAE (origins) · served 80 % range coverage |
|---|---|---|
| All origins | 13.4 (3,766) · 73 % | 20.9 (3,766) · 73 % |
| Falling > 2 mg/dL/min | 18.8 (100) · 52 % | 23.5 (100) · 61 % |
| Falling 1–2 mg/dL/min | 15.3 (332) · 64 % | 21.8 (332) · 64 % |
| Steady (within ±1 mg/dL/min) | 11.9 (2,947) · 77 % | 19.5 (2,947) · 77 % |
| Rising 1–2 mg/dL/min | 19.0 (249) · 56 % | 28.8 (249) · 53 % |
| Rising > 2 mg/dL/min | 25.9 (138) · 40 % | 35.3 (138) · 46 % |

Mean signed error (forecast − actual) when the actual value was above 180 mg/dL: 30 min -7.7 mg/dL; 60 min -16.9 mg/dL — peaks tend to be under-forecast.

Range coverage uses the served half-widths (30 min ±16.7, 60 min ±26.4 mg/dL, calibrated on the later calibration segment), pooled over origins: they cover far fewer than 80 % of outcomes while glucose changes fast, and come closest to the target when it is steady.

Regenerate: `uv run python scripts/error_by_trend.py`. Raw numbers: `artifacts/experiments/gt-primary-2026-10-13-fusion/error_by_trend.json`.
