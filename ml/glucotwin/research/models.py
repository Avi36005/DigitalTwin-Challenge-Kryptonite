"""Tree fitting for the research runner with the objective and the early-stopping metric as SEPARATE fields.

* LightGBM objective ``l2`` -> ``regression``; ``l1`` -> ``regression_l1``.
* Stopping metric ``l2`` uses LightGBM's built-in metric; ``macro_mae`` is a custom evaluation: the mean over
  participants of each participant's mean absolute error on the early-stopping rows (row counts do not weight it).
* CatBoost keeps RMSE loss and RMSE stopping (the v1/v2 configuration).

Fitted models are the ordinary ``LightGBMModel`` / ``CatBoostModel`` objects, so they serialize with the existing
checksum-verified artifact format and never through pickle.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.models.population import CatBoostModel, LightGBMModel
from glucotwin.research.metrics import macro_mae_grouped

LGB_OBJECTIVE = {"l2": "regression", "l1": "regression_l1"}


def sample_trials(space: dict[str, list], family: str, n: int, seed_key: list[int]) -> list[dict[str, Any]]:
    """``n`` parameter sets drawn deterministically from ``space`` (same draw for every outer fold and objective)."""
    rng = np.random.default_rng(seed_key)
    out = []
    for _ in range(n):
        p: dict[str, Any] = {}
        for k, (lo, hi) in space.items():
            if k in ("learning_rate", "l2_leaf_reg"):
                p[k] = float(np.exp(rng.uniform(np.log(lo), np.log(hi)))) if lo > 0 else float(rng.uniform(lo, hi))
            elif isinstance(lo, int) and isinstance(hi, int):
                p[k] = int(rng.integers(lo, hi + 1))
            else:
                p[k] = float(rng.uniform(lo, hi))
        if family == "lightgbm":
            p["num_leaves"] = int(min(p["num_leaves"], 2 ** p["max_depth"]))
        out.append(p)
    return out


def _lgb_macro_feval(groups: np.ndarray):
    def feval(preds, data):
        return "macro_mae", macro_mae_grouped(preds, data.get_label(), groups), False
    return feval


def fit_lightgbm(cols: list[str], params: dict[str, Any], objective: str, stopping: str, Xtr: pd.DataFrame,
                 ytr: np.ndarray, Xva: pd.DataFrame | None, yva: np.ndarray | None, gva: np.ndarray | None, seed: int,
                 max_rounds: int, patience: int, threads: int, fixed_rounds: int | None = None) -> tuple[LightGBMModel, dict]:
    import lightgbm as lgb

    p = {"objective": LGB_OBJECTIVE[objective], "verbosity": -1, "seed": seed, "deterministic": True,
         "force_row_wise": True, "num_threads": threads, "bagging_freq": 1, **params}
    p["metric"] = "l2" if stopping == "l2" else "None"
    t0 = time.perf_counter()
    dtrain = lgb.Dataset(Xtr[cols].to_numpy(float), label=ytr, feature_name=cols, free_raw_data=False)
    if fixed_rounds is not None:
        booster = lgb.train(p, dtrain, num_boost_round=int(fixed_rounds))
        best = int(fixed_rounds)
    else:
        dval = lgb.Dataset(Xva[cols].to_numpy(float), label=yva, reference=dtrain)
        kw: dict[str, Any] = {}
        if stopping == "macro_mae":
            kw["feval"] = _lgb_macro_feval(np.asarray(gva))
        booster = lgb.train(p, dtrain, num_boost_round=max_rounds, valid_sets=[dval],
                            callbacks=[lgb.early_stopping(patience, first_metric_only=True, verbose=False)], **kw)
        best = int(booster.best_iteration or booster.current_iteration())
    m = LightGBMModel(cols, params, booster)
    m.best_iteration = best
    return m, {"best_iteration": best, "fit_seconds": time.perf_counter() - t0, "objective": objective,
               "stopping_metric": stopping, "fixed_rounds": fixed_rounds}


def fit_catboost(cols: list[str], params: dict[str, Any], Xtr: pd.DataFrame, ytr: np.ndarray, Xva: pd.DataFrame,
                 yva: np.ndarray, seed: int, max_rounds: int, patience: int, threads: int) -> tuple[CatBoostModel, dict]:
    from catboost import CatBoostRegressor

    t0 = time.perf_counter()
    model = CatBoostRegressor(loss_function="RMSE", eval_metric="RMSE", iterations=max_rounds, random_seed=seed,
                              verbose=False, thread_count=threads, allow_writing_files=False, od_type="Iter",
                              od_wait=patience, use_best_model=True, nan_mode="Min", **params)
    model.fit(Xtr[cols].to_numpy(float), ytr, eval_set=(Xva[cols].to_numpy(float), yva))
    m = CatBoostModel(cols, params, model)
    return m, {"best_iteration": m.best_iteration, "fit_seconds": time.perf_counter() - t0, "objective": "RMSE",
               "stopping_metric": "RMSE"}
