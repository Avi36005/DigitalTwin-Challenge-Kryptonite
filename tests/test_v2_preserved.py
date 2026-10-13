"""The corrected v2 experiment, the fusion-constrained serving experiment and their model artifacts are preserved
(skipped without local data).

1. Headline metrics recompute exactly from each experiment's saved predictions.
2. Each experiment's model bundle, loaded from its own artifact directory (not via the registry, so v2 stays checked
   after the serving switch), reproduces the saved adaptive forecasts of every evaluated origin with today's feature
   and adaptation code.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from glucotwin.config import paths

V2 = "gt-primary-2026-10-11-v2"
FUSION = "gt-primary-2026-10-13-fusion"


@pytest.fixture(scope="module", params=[V2, FUSION])
def saved(request):
    exp = paths().artifacts / "experiments" / request.param
    if not (exp / "predictions.parquet").exists():
        pytest.skip(f"{request.param} artifacts not present on this machine")
    return request.param, pd.read_parquet(exp / "predictions.parquet"), json.loads((exp / "metrics.json").read_text())


def test_headline_metrics_recompute_from_saved_predictions(saved):
    _, preds, m = saved
    for r in m["forecast_results"]:
        if not r["selected"]:
            continue
        d = preds[(preds["model"] == r["label"]) & (preds["personalization"] == r["personalization"])
                  & (preds["segment"] == r["split"]) & (preds["horizon"] == r["horizon"])
                  & np.isfinite(preds["predicted"]) & np.isfinite(preds["target"])]
        mae = (d["predicted"] - d["target"]).abs().groupby(d["patient_id"]).mean().mean()
        assert mae == pytest.approx(r["mae"], abs=1e-9)


def test_model_bundle_reproduces_saved_adaptive_forecasts(saved):
    from glucotwin.evaluation.run import load_ctx, prequential
    from glucotwin.models.population import PopulationBundle
    from glucotwin.serving import ServingModel

    eid, preds, m = saved
    d = paths().artifacts / "models" / m["model_version"]
    if not (d / "serving.json").exists():
        pytest.skip(f"model artifact of {eid} not present on this machine")
    cfg = json.loads((d / "serving.json").read_text())
    s = ServingModel(m["model_version"], PopulationBundle.load(d), cfg, d)
    ctx = load_ctx(experiment_id=eid)
    pop = {h: np.where(ctx.issued, p, np.nan) for h, p in s.predict(ctx.table).items()}
    corr = prequential(ctx, pop, s.policy)
    for h in ctx.horizons:
        mine = pd.DataFrame({"patient_id": ctx.table["patient_id"], "origin": ctx.table["origin"],
                             "mine": pop[h] + np.nan_to_num(corr[h])})
        ref = preds[(preds["model"] == m["selection"]["selected_label"]) & (preds["personalization"] == "adaptive")
                    & (preds["horizon"] == h)][["patient_id", "origin", "predicted"]]
        j = ref.merge(mine, on=["patient_id", "origin"])
        ok = np.isfinite(j["predicted"])
        assert len(j) == len(ref) and ok.sum() > 1000
        assert np.abs(j.loc[ok, "predicted"] - j.loc[ok, "mine"]).max() < 1e-9


def test_v2_and_fusion_share_the_split_and_every_candidate_prediction(saved):
    eid, preds, m = saved
    if eid != FUSION:
        pytest.skip("compared once, from the fusion side")
    v2 = paths().artifacts / "experiments" / V2
    if not (v2 / "predictions.parquet").exists():
        pytest.skip("v2 artifacts not present on this machine")
    mv2 = json.loads((v2 / "metrics.json").read_text())
    assert m["fingerprints"]["split_hash"] == mv2["fingerprints"]["split_hash"]
    keys = ["model", "personalization", "segment", "horizon", "patient_id", "origin"]
    a = preds.sort_values(keys).reset_index(drop=True)
    b = pd.read_parquet(v2 / "predictions.parquet").sort_values(keys).reset_index(drop=True)
    assert len(a) == len(b) and (a[keys] == b[keys]).all().all()
    assert np.allclose(a["predicted"], b["predicted"], equal_nan=True, atol=0)
