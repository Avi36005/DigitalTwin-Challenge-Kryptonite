"""The corrected v2 experiment and its serving artifact are preserved by the v4 work (skipped without local data).

1. Headline metrics recompute exactly from the saved v2 predictions.
2. The registered v2 serving bundle, with today's feature and adaptation code, reproduces the saved adaptive
   forecasts of every evaluated origin (the duplicate-origin guard added to AdaptationState changes nothing).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from glucotwin.config import paths

V2 = "gt-primary-2026-10-11-v2"
EXP = paths().artifacts / "experiments" / V2


@pytest.fixture(scope="module")
def saved():
    if not (EXP / "predictions.parquet").exists():
        pytest.skip("v2 artifacts not present on this machine")
    return pd.read_parquet(EXP / "predictions.parquet"), json.loads((EXP / "metrics.json").read_text())


def test_v2_headline_metrics_recompute_from_saved_predictions(saved):
    preds, m = saved
    for r in m["forecast_results"]:
        if not r["selected"]:
            continue
        d = preds[(preds["model"] == r["label"]) & (preds["personalization"] == r["personalization"])
                  & (preds["segment"] == r["split"]) & (preds["horizon"] == r["horizon"])
                  & np.isfinite(preds["predicted"]) & np.isfinite(preds["target"])]
        mae = (d["predicted"] - d["target"]).abs().groupby(d["patient_id"]).mean().mean()
        assert mae == pytest.approx(r["mae"], abs=1e-9)


def test_v2_serving_bundle_reproduces_saved_adaptive_forecasts(saved):
    from glucotwin.evaluation.run import load_ctx, prequential
    from glucotwin.serving import load_serving

    preds, m = saved
    s = load_serving("dataset_replay")
    if s is None or s.model_version != m["model_version"]:
        pytest.skip("the registered serving model is not the v2 artifact")
    ctx = load_ctx(experiment_id=V2)
    pop = {h: np.where(ctx.issued, p, np.nan) for h, p in s.predict(ctx.table).items()}
    corr = prequential(ctx, pop, s.policy)
    for h in ctx.horizons:
        mine = pd.DataFrame({"patient_id": ctx.table["patient_id"], "origin": ctx.table["origin"],
                             "mine": pop[h] + np.nan_to_num(corr[h])})
        ref = preds[(preds["model"] == "lightgbm:dyn-v2") & (preds["personalization"] == "adaptive")
                    & (preds["horizon"] == h)][["patient_id", "origin", "predicted"]]
        j = ref.merge(mine, on=["patient_id", "origin"])
        ok = np.isfinite(j["predicted"])
        assert len(j) == len(ref) and ok.sum() > 1000
        assert np.abs(j.loc[ok, "predicted"] - j.loc[ok, "mine"]).max() < 1e-9
