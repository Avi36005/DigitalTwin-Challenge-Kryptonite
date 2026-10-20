# How much of the time the warnings fire

Post-hoc diagnostic, computed from saved forecasts only (no model fitted, no assessment re-opened). The direct two-hour classifier fired at almost every eligible moment, so its episode counts looked perfect ([two-hour classifier](two_hour_classifier.md)). This checks the warnings we report for the same failure.

- **Fires at eligible origins**: share of forecast-issued, early-warning-eligible origins (glucose not already in a high episode) at which the warning fires; the same quantity as the classifier's "share of eligible time warning".
- **Fires at all issued origins**: the same firings over every forecast-issued origin (origins already in a high episode can never fire).
- **Onset ahead**: share of eligible origins with a resolved label at which a new high onset (> 180 mg/dL, sustained 15 min) really follows within the horizon, for reference.
- **Episode length**: first to last firing of a warning episode (firings within 30 min merge) plus one 5-minute step, so a single firing counts as 5 min.

| Warning | Where (people) | Threshold, mg/dL margin | Fires at eligible origins | Fires at all issued origins | Onset ahead | Episodes | Episode length, median (IQR), min | Onsets warned |
|---|---|---|---|---|---|---|---|---|
| Demo model (fusion LightGBM, personalised), 60 min | final test segment (14) | -10 | 11.8 % (596 of 5,042) | 7.7 % (596 of 7,720) | 13.1 % | 101 | 15 (10–40) | 61 of 64 |
| Persistence, 60 min | final test segment (14) | -30 | 31.0 % (1,562 of 5,042) | 20.2 % (1,562 of 7,720) | 13.1 % | 133 | 35 (15–80) | 63 of 64 |
| Research regression warning (gt-2h-2026-10-20), 120 min, selected per fold, personalised | outer-fold people held out (14) | outer-1 -10, outer-2 -10, outer-3 0, outer-4 -10, outer-5 0 | 10.6 % (2,776 of 26,077) | 7.0 % (2,776 of 39,761) | 23.9 % | 544 | 15 (5–30) | 315 of 329 |
| Research regression warning (gt-2h-2026-10-20), 60 min, selected per fold, personalised | outer-fold people held out (14) | outer-1 -10, outer-2 -10, outer-3 0, outer-4 -10, outer-5 0 | 7.8 % (2,035 of 26,077) | 5.1 % (2,035 of 39,761) | 13.0 % | 521 | 10 (5–25) | 313 of 329 |

- **Demo 60-minute warning:** it fires at 11.8 % of eligible moments on the test segment, below the 13.1 % at which an onset really follows, in episodes of median 15 min, so it is an intermittent warning, not an always-on alarm (retrospective: this test segment was inspected in earlier experiments).
- **Persistence 60-minute warning:** it fires at 31.0 % of eligible moments, 2.6 times as often as the demo warning, to warn 63 rather than 61 of 64 onsets with 70 rather than 40 false alarms.
- **Research 120-minute warning:** it fires at 10.6 % of eligible moments for people held out (below the 23.9 % onset rate), so its 315 of 329 onsets warned are not bought with an always-on alarm, but most of them are caught late (median forecast lead 15 min of the 120 available).
- **Research 60-minute warning:** it fires at 7.8 % of eligible moments for people held out (below the 13.0 % onset rate), median forecast lead 10 min; like the 120-minute row this is research on internally re-used people, not the demo model.
- **For contrast**, the degenerate two-hour classifier fired at 99.0 % of eligible moments (96.7 %–99.3 % across feature sets; read from `artifacts/research/gt-2h-clf-2026-10-20/summary.json`).

Each warning was rebuilt from the saved forecasts and had to reproduce the saved episode, onset and false-alarm counts before anything was reported. Sources: `artifacts/experiments/gt-primary-2026-10-13-fusion/` (predictions.parquet, metrics.json) with that experiment's origin table (eligibility, labels, forecast quality); `artifacts/research/gt-2h-2026-10-20/` (assessment/predictions.parquet, per-fold `pipeline.json`, cached table).

Regenerate: `uv run python scripts/warning_time_share.py`.
