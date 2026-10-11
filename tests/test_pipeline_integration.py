"""Synthetic end-to-end integration: origin table -> experiment pipeline -> artifacts (reduced budget)."""

import json

import pandas as pd
from glucotwin.data.pipeline import synthetic_store_dir
from glucotwin.data.store import Store
from glucotwin.dataset import build_origin_table, load_settings
from glucotwin.evaluation.run import run


def test_experiment_pipeline_on_synthetic_participants(synthetic_ready, tmp_path):
    st = load_settings()
    store_copy = tmp_path / "store"
    import shutil

    shutil.copytree(synthetic_store_dir(), store_copy, ignore=shutil.ignore_patterns("experiment"))
    build_origin_table(Store(store_copy), st, store_copy / "experiment",
                       include=lambda m: m["patient_id"].startswith("SYN-T"))
    out = run(include_lopo=False, store_dir=store_copy, artifacts_dir=tmp_path / "artifacts", register=False,
              overrides={"models": {"tree_search": {"trials_per_family_per_horizon": 2}},
                         "evaluation": {"bootstrap_resamples": 100}})
    assert out["status"] == "completed"
    fr = pd.DataFrame(out["forecast_results"])
    # every candidate is evaluated on identical origins per split and horizon
    for (split, h), g in fr.groupby(["split", "horizon"]):
        assert g["n_origins"].nunique() == 1, (split, h)
    # validation and test are reported separately, and exactly one pipeline is marked as serving
    assert set(fr["split"]) == {"validation", "test"}
    assert fr["selected"].sum() == len(st.horizons) * 2  # one row per horizon per split
    exp_dir = tmp_path / "artifacts" / "experiments" / st.raw["experiment"]["experiment_id"]
    for name in ("metrics.json", "predictions.parquet", "alerts.json", "search_log.json"):
        assert (exp_dir / name).exists()
    model_dirs = list((tmp_path / "artifacts" / "models").iterdir())
    assert len(model_dirs) == 1
    serving = json.loads((model_dirs[0] / "serving.json").read_text())
    assert serving["alerts"]["score_kind"] == "forecast_margin_mg_dl"
    assert all(e["threshold"] is not None for e in out["events"])
