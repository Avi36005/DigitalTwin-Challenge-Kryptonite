# Foundation-model baseline — zero-shot, CGM-only (gt-foundation-2026-10-21, D-054)

**Label.** CGM-only, zero-shot research baseline on the 14 previously inspected CGMacros Type 2 people. Internal comparison, not independent confirmation, not clinical evidence. Not fusion, not fine-tuned. The checkpoint's public pretraining corpus may include public CGM data; whether any CGMacros recording was included is unknown. Raw model quantiles are not calibrated ranges and are not reported as such.

Protocol `configs/experiments/gt-foundation-2026-10-21.yaml` was committed before any participant forecast (protocol sha256 prefix `85b4bc7c10ef58a1`).

## Result in brief

- Zero-shot foundation median vs persistence (identical origins, macro per-person MAE): 30 min -0.79 [-1.01, -0.59], 60 min -1.54 [-1.81, -1.30] mg/dL; lower error for 14/14 people at 60 min.
- It does not beat the personalised fusion recipe R0 (60 min +0.42 [-0.70, +1.47]) and is clearly worse on targets > 180 (43.67 vs 38.28).
- The declared fusion residual F1 (foundation median + fresh LightGBM residual on the served inputs) vs the same-code R0 refit, personalised 60 min: -0.46 [-0.72, -0.21] mg/dL, > 180: 38.09 vs 38.36. Descriptive only: for reference, the D-052 gate's −0.5 mg/dL threshold would not be met; F1 was seen on the same 14 inspected people and is not a release candidate from this study.

## Model, versions, hardware

- Checkpoint `amazon/chronos-bolt-tiny` at revision `a0e552de83495b5c28c14c71c374f3e33280b340` (ChronosBoltPipeline, 8,652,672 parameters), license apache-2.0; weights sha256 `75068728d376d2be…`.
- Mode: zero-shot inference (eval, no grad). Chronos-2 and larger checkpoints were not downloaded or tested.
- Versions: torch 2.14.1, chronos-forecasting 2.3.2, transformers 5.20.2, numpy 2.5.4, pandas 3.0.6; Python 3.12.12. Isolated environment `~/.cache/glucotwin-chronos/venv`; not a project dependency.
- Hardware: Apple M4 (arm64), 16 GB RAM, 2 CPU threads used.

## Protocol in brief

- Context: 512 five-minute slots ending at the origin (about 42.6 h); a reading enters only if observed and available at or before the origin; gaps are NaN (the model's missing mask). Native cadence verified (99.92 % of reading gaps are exactly 5 min).
- Horizons: +30 min = output step 6 (index 5), +60 min = step 12 (index 11); prediction length 12, single block.
- Point forecast: the median, fixed before the run. Each origin is an independent series (no cross-series mode).
- Origins: the full five-minute mask — 39,761 issued origins of 14 people; scored where the target is matched. Comparators are scored on identical origins.

## Latency and memory

- Warm single-origin forecast: 5.62 ms.
- Batched (batch 256): 0.550 ms per origin (1,819.1 origins/s), full mask in 21.9 s (causal context construction + hashing + model forward).
- Peak resident memory of the inference process: 868.1 MB.
- Determinism: 1000 origins re-predicted in reverse order with batch 97; maximum absolute difference 0.00e+00 mg/dL; context hashes equal: True.
- Run twice (21:34 and 21:39 IST; the second after lint-only code changes): every cached quantile and context hash identical (maximum difference 0). First-run latency was 4.06 ms single / 0.624 ms batched per origin; the figures above are from the second run.

## Accuracy on identical origins (mg/dL)

Difference = first − second; negative means the first has lower error. Interval: paired participant bootstrap, 2000 resamples, 95 %.

| Horizon | Comparison | Origins | People | Macro MAE (first / second) | Difference [95 % CI] | Pooled MAE (first / second) | > 180 macro MAE (people ≥ 50) |
|---|---|---|---|---|---|---|---|
| 30 min | Foundation (median) vs Persistence | 39,646 | 14 | 14.55 / 15.34 | -0.79 [-1.01, -0.59] | 14.54 / 15.34 | 26.13 / 27.69 (14) |
| 30 min | Foundation (median) vs R0 personalised (saved D-052) | 39,646 | 14 | 14.55 / 14.14 | +0.41 [-0.11, +0.89] | 14.54 / 14.14 | 26.13 / 23.28 (14) |
| 30 min | Persistence vs R0 personalised (saved D-052) | 39,646 | 14 | 15.34 / 14.14 | +1.20 [+0.68, +1.74] | 15.34 / 14.14 | 27.69 / 23.28 (14) |
| 30 min | F1 fusion residual, personalised vs R0 refit, personalised | 39,646 | 14 | 13.89 / 14.12 | -0.24 [-0.38, -0.11] | 13.88 / 14.12 | 23.04 / 23.29 (14) |
| 30 min | F1 fusion residual, population vs R0 refit, population | 39,646 | 14 | 14.43 / 14.81 | -0.38 [-0.55, -0.21] | 14.43 / 14.81 | 23.16 / 23.53 (14) |
| 60 min | Foundation (median) vs Persistence | 39,553 | 14 | 22.92 / 24.47 | -1.54 [-1.81, -1.30] | 22.92 / 24.47 | 43.67 / 45.03 (14) |
| 60 min | Foundation (median) vs R0 personalised (saved D-052) | 39,553 | 14 | 22.92 / 22.50 | +0.42 [-0.70, +1.47] | 22.92 / 22.50 | 43.67 / 38.28 (14) |
| 60 min | Persistence vs R0 personalised (saved D-052) | 39,553 | 14 | 24.47 / 22.50 | +1.97 [+0.78, +3.10] | 24.47 / 22.50 | 45.03 / 38.28 (14) |
| 60 min | F1 fusion residual, personalised vs R0 refit, personalised | 39,553 | 14 | 22.08 / 22.54 | -0.46 [-0.72, -0.21] | 22.08 / 22.54 | 38.09 / 38.36 (14) |
| 60 min | F1 fusion residual, population vs R0 refit, population | 39,553 | 14 | 23.30 / 24.20 | -0.90 [-1.43, -0.48] | 23.30 / 24.20 | 37.78 / 38.53 (14) |

People with lower foundation error than persistence: 30 min 14/14, 60 min 14/14.
Mean signed error on targets > 180 (foundation / persistence): 30 min -5.40 / -5.86, 60 min -15.31 / -14.04 (negative = under-forecast of high glucose).

## Fusion residual candidate F1 (secondary, descriptive)

Template F1 (declared before the run): the fixed zero-shot median plus a freshly fitted LightGBM residual that reads the served dyn-prof-v2 inputs (46: CGM history, Fitbit heart-rate / METs / energy summaries, baseline profile when available; no meal inputs) plus the foundation delta and spread; the serving model's frozen per-horizon parameters and rounds; fitted per outer fold on that fold's development + calibration people; R0's patient correction (k 96, half-life 240 min) applied causally. R0 was refitted by the same code (2 threads, same seed) so the only difference is the foundation input. 10 F1 fits, 7 s total. Not entered into the D-053 family selection and not adopted; any adoption needs the lead's separately declared gate.

Consistency: R0 refit here (seed 20261021 + h, 2 threads) vs the saved D-052 R0 personalised forecasts (seed 20261023 + h, 4 threads; bagging makes single forecasts seed-dependent), maximum absolute difference: 30 min 9.09 mg/dL, 60 min 10.9 mg/dL.

## Not run

- Fine-tuning (full or LoRA): not run. Zero-shot only; no participant-held-out fine-tuned claim is made.
- Chronos-2 and larger Chronos-Bolt sizes: not tested (one checkpoint approved; the result is not evidence about them).
- Calibrated ranges from model quantiles, warning thresholds on the foundation forecast: not run.

## Files

- `artifacts/research/gt-foundation-2026-10-21/` (git-ignored): `zero_shot_predictions.parquet` (one row per issued origin: q0.1…q0.9 at 30/60 min, origin and context SHA-256 prefixes; join key patient_id, origin, horizon), `run_meta.json`, `summary.json`, `residual_predictions.parquet`, `residual_fits.json`, `inputs/`.
- `scripts/foundation_baseline.py`, `tests/test_foundation_baseline.py`.
