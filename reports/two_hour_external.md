# Two hours ahead on an independent cohort — `gt-2h-ext-2026-10-20`

Research experiment (decision D-045), declared before any fit on 20 Oct 2026. The 15-minute CGM-only portable procedure of `gt-nested-2026-10-12-v1` with a 120-minute horizon, developed on the 14 CGMacros Type 2 people only and assessed once on 98 ShanghaiT2DM people (China, FreeStyle Libre H, 15-minute readings), opened at 2026-10-20T10:10:25+00:00. No 120-minute result had been computed on this cohort before; it is the cohort's second opening (the first was for 30/60 minutes). Nothing was chosen on it; not the demo model; nothing promoted.

Candidate: `lightgbm_l2:cgm15-v1` (final), freeze hash `aa43715707e8e80b`.

| Horizon | Candidate MAE (mg/dL) | Persistence MAE | Candidate minus persistence (95 % participant bootstrap) | People better | Range coverage (target 80 %) |
|---|---|---|---|---|---|
| 30 min | 10.90 | 12.14 | -1.25 [-1.40, -1.10] | 93 of 98 | 87.6 % |
| 60 min | 19.31 | 20.44 | -1.13 [-1.37, -0.88] | 81 of 98 | 86.6 % |
| 120 min | 29.55 | 31.68 | -2.12 [-2.67, -1.53] | 78 of 98 | 87.1 % |

Personalisation (the same candidate with minus without the patient correction): 30 min -0.46 [-0.57, -0.34]; 60 min -1.17 [-1.49, -0.88]; 120 min -2.35 [-3.02, -1.74] mg/dL.

CGM only: ShanghaiT2DM has no wearable data, so this checks the forecasting core, not the fusion. Ranges are wider than needed on this cohort (coverage above the 80 % target).

Regenerate: `uv run python scripts/summarise_two_hour_external.py`. Raw numbers: `artifacts/research/gt-2h-ext-2026-10-20/two_hour_external_summary.json`.
