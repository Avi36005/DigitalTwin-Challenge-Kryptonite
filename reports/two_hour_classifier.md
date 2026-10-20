# Two-hour onset classifier — `gt-2h-clf-2026-10-20`

Research experiment (decision D-044), declared before any fit on 20 Oct 2026, on the frozen table and participant folds of `gt-2h-2026-10-20`: 14 CGMacros Type 2 people, each held out entirely once (internal validation; these people were inspected in earlier experiments). Assessment opened once at 2026-10-20T09:57:29+00:00. Not the demo model; nothing promoted.

Feature set chosen per fold on inner folds: outer-1 `cgm-only-v1`, outer-2 `dyn-v2`, outer-3 `dyn-prof-v2`, outer-4 `cgm-only-v1`, outer-5 `dyn-v2`. Thresholds chosen on inner folds for at most 2 false alarms per observed forecastable day.

**Result: negative — this classifier is not useful as a warning.** In every fold the inner-fold rule chose the lowest threshold on the declared grid (0.02), so the classifier fires at almost every eligible moment (share column, a post-hoc diagnostic). Firings within 30 minutes merge into one episode, so a near-constant alarm becomes a few long episodes that each contain an onset: the episode counts below look perfect while the warning carries little information (origin-level ROC AUC 0.62–0.66). Episode-based workload alone can be gamed this way; time spent in warning has to be read beside it. The regression-derived warning of `gt-2h-2026-10-20` stays the two-hour result we report.

Assessment first opened at 2026-10-20T09:57:29+00:00; re-opened at 2026-10-20T09:58:18+00:00 (post-hoc diagnostic: share of eligible time in warning (thresholds hit the grid minimum)). The models are deterministic, so the declared metrics did not change.

| Classifier (120-min onset) | Onsets warned | False alarms per observed day | Precision | Median forecast lead (IQR), min | Share of eligible time warning | ROC AUC | Average precision (base rate) |
|---|---|---|---|---|---|---|---|
| **Selected per fold** (inner-fold rule) | 329 of 329 (100.0 %) | 0.181 | 0.9294 | 120.0 (75.0–120.0) | 99 % | 0.638 | 0.384 (0.239) |
| CGM only | 329 of 329 (100.0 %) | 0.13 | 0.9481 | 120.0 (75.0–120.0) | 99 % | 0.659 | 0.392 (0.239) |
| CGM + wearable | 329 of 329 (100.0 %) | 0.369 | 0.8658 | 120.0 (70.0–120.0) | 97 % | 0.622 | 0.354 (0.239) |
| CGM + wearable + profile (EHR-like) | 329 of 329 (100.0 %) | 0.355 | 0.8704 | 120.0 (75.0–120.0) | 97 % | 0.639 | 0.361 (0.239) |

Comparator (same people and folds, `gt-2h-2026-10-20`): the regression-derived 120-minute warning warned 315 of 329 onsets at 1.62 false alarms per observed day, median forecast lead 15 min (IQR 5–65) ([two-hour benchmark](two_hour_benchmark.md)).

Regenerate: `uv run python scripts/two_hour_classifier.py` (refuses to re-open the assessment without `--reopen-reason`). Raw numbers: `artifacts/research/gt-2h-clf-2026-10-20/summary.json`.
