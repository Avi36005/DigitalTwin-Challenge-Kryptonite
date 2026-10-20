# Serving model parity — online replay vs saved offline forecasts

`scripts/serving_parity.py` replays every participant with final-test forecasts through the online twin engine the
way a replay session does: events are released by the replay clock one day per `advance` call, and adaptation
collects from each participant's training end. It then compares every final-test forecast of the serving pipeline with
the saved offline prediction (`artifacts/experiments/gt-primary-2026-10-13-fusion/predictions.parquet`). The API rounds
forecasts to 0.1 mg/dL, so the tolerance is 0.05 mg/dL, the same as stated in [`verification.md`](verification.md).

| Model | Forecasts compared | Missing online | Max abs. difference | Over tolerance | Outcome |
|---|---|---|---|---|---|
| `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion` (adaptive), 14 participants, 30 and 60 min | 15,440 of 15,440 | 0 | 0.0500 mg/dL (display rounding) | 0 | **pass** |

The check ran at 2026-10-20 17:00:54 UTC on commit `40c3229` (clean tracked tree) and took 35 s. Machine-readable
summary, aggregate only: [`serving_parity.json`](serving_parity.json). It records the feature set and transform
fingerprint (`38152f8846c88ed4`), the data fingerprint (`289d296590837618`), the split hash (`b31e8d8c071eb425`),
the tolerance and the outcome. Per-participant counts are kept in the git-ignored
`artifacts/verification/serving_parity_<model>.json`.

Regenerate: `uv run python scripts/serving_parity.py` (exits 1 on failure).
