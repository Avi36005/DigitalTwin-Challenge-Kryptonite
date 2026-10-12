"""Synthetic-demonstration model: lets the software run with no dataset download.

Fitted ONLY on hidden synthetic training participants (SYN-T01..T12). Its identity carries
``synthetic_fitted: true`` in the API and UI, and its numbers never appear in real-data reports.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from glucotwin.config import fingerprint, paths
from glucotwin.data.pipeline import synthetic_store_dir
from glucotwin.data.store import Store
from glucotwin.dataset import build_origin_table, load_settings
from glucotwin.features import FEATURE_SETS
from glucotwin.models.adaptation import AdaptationPolicy, conformal_quantile
from glucotwin.models.population import LightGBMModel, PopulationBundle

VERSION = "synthetic-demo.lightgbm.dyn-v2.v1"  # dyn-v2: corrected activity windows (v1 artifact kept)
PARAMS = {"learning_rate": 0.05, "num_leaves": 15, "max_depth": 5, "min_child_samples": 100, "lambda_l2": 5.0,
          "feature_fraction": 0.9, "bagging_fraction": 0.9}


def train() -> dict:
    st = load_settings()
    store = Store(synthetic_store_dir())
    out = synthetic_store_dir() / "experiment"
    build_origin_table(store, st, out, include=lambda m: m["patient_id"].startswith("SYN-T"))
    table = pd.read_parquet(out / "origins.parquet")
    issued = table["quality"] != "insufficient"
    fs = "dyn-v2"
    cols = FEATURE_SETS[fs].columns()
    models, q = {}, {}
    for h in st.horizons:
        ok = issued & table[f"target_{h}"].notna()
        tr = ok & (table["segment"] == "training")
        va = ok & (table["segment"] == "validation")
        ca = ok & (table["segment"] == "calibration")
        y = (table[f"target_{h}"] - table["g_last"]).to_numpy(float)
        m = LightGBMModel(cols, PARAMS).fit(table[tr], y[tr], table[va], y[va], seed=7, early_stopping=50,
                                            max_rounds=1500)
        models[h] = m
        pred = table.loc[ca, "g_last"].to_numpy(float) + m.predict_delta(table[ca])
        q[str(h)] = conformal_quantile(np.abs(table.loc[ca, f"target_{h}"].to_numpy(float) - pred), 0.8)
    bundle = PopulationBundle("lightgbm", fs, st.horizons, models, label=f"lightgbm:{fs}",
                              params={h: {**PARAMS, "best_iteration": models[h].best_iteration} for h in st.horizons})
    cfg = {
        "model_version": VERSION, "model_family": "lightgbm", "feature_set_id": fs,
        "experiment_id": None, "synthetic_fitted": True,
        "note": "Fitted on fictional synthetic participants for software demonstration only. Not clinical evidence.",
        "adaptation": AdaptationPolicy(enabled=True).as_dict(),
        "adaptation_collect_rule": "all origins (synthetic demonstration participants were never used in training)",
        "intervals": {"method": "split-conformal on synthetic calibration segment", "level": 0.8,
                      "quantiles_mg_dl": q, "calibrated_for": "synthetic demonstration model without adaptation"},
        "alerts": {"rule_version": "new-high-warning-v1", "horizon_minutes": 60, "threshold_margin_mg_dl": 0.0,
                   "score_kind": "forecast_margin_mg_dl", "episode_merge_minutes": 30.0},
        "event_definition": {"threshold_mg_dl": 180, "confirm_minutes": 15, "recovery_minutes": 15},
    }
    directory = paths().artifacts / "models" / VERSION
    manifest = bundle.save(directory, extra={"serving": cfg})
    (directory / "serving.json").write_text(json.dumps(cfg, indent=2))
    reg_path = paths().artifacts / "registry.json"
    reg = json.loads(reg_path.read_text()) if reg_path.exists() else {"models": [], "serving": {}}
    reg["models"] = [m for m in reg["models"] if m["model_version"] != VERSION]
    reg["models"].append({
        "model_version": VERSION, "model_family": "lightgbm", "feature_set_id": fs, "horizons": st.horizons,
        "artifact_dir": str(directory.relative_to(paths().root)), "artifact_checksum": fingerprint(manifest["files"]),
        "selection_rationale": "Fixed demonstration configuration; not selected by any evaluation.",
        "evaluation_reference": None, "mode": "synthetic_demo", "synthetic_fitted": True,
    })
    reg["serving"]["synthetic_demo"] = VERSION
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps(reg, indent=2))
    return {"model_version": VERSION, "interval_q": q}
