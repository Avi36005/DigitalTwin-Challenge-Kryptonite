"""Primary GlucoTwin experiment (Prompt 03). Run with ``glucotwin experiment run``.

Order of operations (each step uses only the data the protocol permits):

1. Fit baselines and search LightGBM / CatBoost on TRAINING rows; early-stop and score trials on the
   VALIDATION-SELECTION segment only.
2. Select the serving population model by the declared validation rule (no test data involved).
3. Select adaptation settings per tree bundle on validation-selection (prequential from zero state);
   apply the declared adoption rule.
4. Calibrate split-conformal intervals on the CALIBRATION segment with the actual serving pipeline.
5. Select alert thresholds on validation-selection.
6. Freeze everything, write the serving artifact, THEN evaluate every preregistered candidate on the
   final TEST segment once.
"""

from __future__ import annotations

import json
import platform
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import fingerprint, load_experiment_config, paths
from glucotwin.data.pipeline import dataset_store_dir
from glucotwin.data.store import Store
from glucotwin.dataset import experiment_dir, load_settings
from glucotwin.evaluation import alerts as alert_eval
from glucotwin.features import FEATURE_SETS, prepare
from glucotwin.models.adaptation import AdaptationPolicy, AdaptationState, conformal_quantile
from glucotwin.models.population import (
    COMPLEXITY,
    CatBoostModel,
    LightGBMModel,
    LinearTrendModel,
    PersistenceModel,
    PopulationBundle,
    RidgeModel,
)

SEGMENTS = ("validation", "calibration", "test")


@dataclass
class Ctx:
    st: Any
    exp: dict
    table: pd.DataFrame
    prep: dict
    manifest: dict
    horizons: list[int]
    seed: int

    @property
    def issued(self) -> np.ndarray:
        return (self.table["quality"] != "insufficient").to_numpy()

    def seg(self, name: str) -> np.ndarray:
        return (self.table["segment"] == name).to_numpy()

    def eval_mask(self, seg: str, h: int) -> np.ndarray:
        return self.seg(seg) & self.issued & self.table[f"target_{h}"].notna().to_numpy()


def load_ctx(store_dir: Path | None = None, experiment_id: str | None = None) -> Ctx:
    st = load_settings(experiment_id=experiment_id)
    exp = load_experiment_config(experiment_id)
    store_dir = store_dir or dataset_store_dir()
    out = experiment_dir(store_dir, exp["experiment_id"])
    table = pd.read_parquet(out / "origins.parquet")
    table = table.sort_values(["patient_id", "origin"], kind="mergesort").reset_index(drop=True)
    manifest = json.loads((out / "split_manifest.json").read_text())
    store = Store(store_dir)
    prep = {pid: prepare(store.load(pid)) for pid in table["patient_id"].unique()}
    return Ctx(st, exp, table, prep, manifest, list(exp["horizons_minutes"]), int(exp["random_seed"]))


# ------------------------------------------------------------------------------------------------
# metrics helpers
# ------------------------------------------------------------------------------------------------


def per_patient_mae(ctx: Ctx, mask: np.ndarray, pred: np.ndarray, h: int) -> pd.Series:
    err = np.abs(pred[mask] - ctx.table[f"target_{h}"].to_numpy(float)[mask])
    return pd.Series(err).groupby(ctx.table["patient_id"].to_numpy()[mask]).mean()


def per_patient_rmse(ctx: Ctx, mask: np.ndarray, pred: np.ndarray, h: int) -> pd.Series:
    err = (pred[mask] - ctx.table[f"target_{h}"].to_numpy(float)[mask]) ** 2
    return np.sqrt(pd.Series(err).groupby(ctx.table["patient_id"].to_numpy()[mask]).mean())


def macro(series: pd.Series) -> float:
    return float(series.mean()) if len(series) else float("nan")


def cluster_bootstrap_diff(a: pd.Series, b: pd.Series, n: int, seed: int) -> tuple[float, float, float]:
    """Mean of per-patient differences (a - b) with a participant-cluster bootstrap 95% interval."""
    d = (a - b).dropna().to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, d.size, size=(n, d.size))
    boots = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


# ------------------------------------------------------------------------------------------------
# step 1: population models
# ------------------------------------------------------------------------------------------------


def _train_rows(ctx: Ctx, h: int) -> np.ndarray:
    return ctx.seg("training") & ctx.issued & ctx.table[f"target_{h}"].notna().to_numpy()


def _y(ctx: Ctx, mask: np.ndarray, h: int) -> np.ndarray:
    t = ctx.table
    return (t[f"target_{h}"].to_numpy(float) - t["g_last"].to_numpy(float))[mask]


def _sample_params(space: dict, rng: np.random.Generator, family: str) -> dict:
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
    return p


def search_family(ctx: Ctx, family: str, fs: str, log: list) -> PopulationBundle:
    cfg = ctx.exp["models"]["tree_search"]
    space = cfg[f"{family}_space"]
    cols = FEATURE_SETS[fs].columns()
    models, params = {}, {}
    for h in ctx.horizons:
        tr = _train_rows(ctx, h)
        sel = ctx.eval_mask("validation", h)
        Xtr, ytr = ctx.table.loc[tr, cols], _y(ctx, tr, h)
        Xsel, ysel = ctx.table.loc[sel, cols], _y(ctx, sel, h)
        g_sel = ctx.table.loc[sel, "g_last"].to_numpy(float)
        rng = np.random.default_rng([ctx.seed, COMPLEXITY.index(family), h, len(fs)])
        best, best_score, t_start = None, np.inf, time.perf_counter()
        for trial in range(int(cfg["trials_per_family_per_horizon"])):
            if time.perf_counter() - t_start > cfg["wall_clock_budget_seconds_per_family"] / len(ctx.horizons):
                log.append({"family": family, "feature_set": fs, "horizon": h, "trial": trial,
                            "note": "wall-clock budget reached; search stopped"})
                break
            p = _sample_params(space, rng, family)
            m = (LightGBMModel if family == "lightgbm" else CatBoostModel)(cols, p)
            t0 = time.perf_counter()
            m.fit(Xtr, ytr, Xsel, ysel, seed=ctx.seed + trial, early_stopping=int(cfg["early_stopping_rounds"]),
                  max_rounds=int(cfg["max_boosting_rounds"]))
            fit_s = time.perf_counter() - t0
            pred = np.full(len(ctx.table), np.nan)
            pred[sel] = g_sel + m.predict_delta(Xsel)
            score = macro(per_patient_mae(ctx, sel, pred, h))
            log.append({"family": family, "feature_set": fs, "horizon": h, "trial": trial, "params": p,
                        "best_iteration": m.best_iteration, "selection_macro_mae": score, "fit_seconds": fit_s})
            if score < best_score:
                best, best_score = m, score
                params[h] = {**p, "best_iteration": m.best_iteration, "fit_seconds": fit_s}
        models[h] = best
    return PopulationBundle(family, fs, ctx.horizons, models, label=f"{family}:{fs}", params=params)


def fit_baselines(ctx: Ctx, log: list) -> list[PopulationBundle]:
    cfg = ctx.exp["models"]["baselines"]
    out = [PopulationBundle("persistence", "cgm-only-v1", ctx.horizons,
                            {h: PersistenceModel() for h in ctx.horizons}, label="persistence:cgm-only-v1")]
    # linear trend: grid on validation-selection
    lt_models, lt_params = {}, {}
    for h in ctx.horizons:
        sel = ctx.eval_mask("validation", h)
        best, best_s = None, np.inf
        for w in cfg["linear_trend"]["window_minutes"]:
            for dmp in cfg["linear_trend"]["damping"]:
                m = LinearTrendModel(h, w, dmp, cfg["linear_trend"]["max_change_mg_dl"])
                pred = np.full(len(ctx.table), np.nan)
                pred[sel] = ctx.table.loc[sel, "g_last"].to_numpy(float) + m.predict_delta(ctx.table.loc[sel])
                s = macro(per_patient_mae(ctx, sel, pred, h))
                log.append({"family": "linear_trend", "horizon": h, "params": m.params(), "selection_macro_mae": s})
                if s < best_s:
                    best, best_s = m, s
        lt_models[h], lt_params[h] = best, best.params()
    out.append(PopulationBundle("linear_trend", "cgm-only-v1", ctx.horizons, lt_models,
                                label="linear_trend:cgm-only-v1", params=lt_params))
    for fs in ctx.exp["features"]["candidate_feature_sets"]:
        cols = FEATURE_SETS[fs].columns()
        models, params = {}, {}
        for h in ctx.horizons:
            tr, sel = _train_rows(ctx, h), ctx.eval_mask("validation", h)
            best, best_s = None, np.inf
            for a in cfg["ridge"]["alpha"]:
                t0 = time.perf_counter()
                m = RidgeModel(cols, alpha=a).fit(ctx.table.loc[tr], _y(ctx, tr, h))
                fit_s = time.perf_counter() - t0
                pred = np.full(len(ctx.table), np.nan)
                pred[sel] = ctx.table.loc[sel, "g_last"].to_numpy(float) + m.predict_delta(ctx.table.loc[sel])
                s = macro(per_patient_mae(ctx, sel, pred, h))
                log.append({"family": "ridge", "feature_set": fs, "horizon": h, "alpha": a,
                            "selection_macro_mae": s, "fit_seconds": fit_s})
                if s < best_s:
                    best, best_s = m, s
                    params[h] = {"alpha": a, "fit_seconds": fit_s}
            models[h] = best
        out.append(PopulationBundle("ridge", fs, ctx.horizons, models, label=f"ridge:{fs}", params=params))
    return out


def population_predictions(ctx: Ctx, bundle: PopulationBundle) -> dict[int, np.ndarray]:
    issued = ctx.issued
    preds = bundle.predict(ctx.table)
    return {h: np.where(issued, p, np.nan) for h, p in preds.items()}


# ------------------------------------------------------------------------------------------------
# step 3: prequential adaptation
# ------------------------------------------------------------------------------------------------


def prequential(ctx: Ctx, pop: dict[int, np.ndarray], policy: AdaptationPolicy,
                freeze_at_test: bool = False) -> dict[int, np.ndarray]:
    """Return the correction per origin and horizon (NaN before collection start / not issued)."""
    corr = {h: np.full(len(ctx.table), np.nan) for h in ctx.horizons}
    bounds = {p["patient_id"]: p["boundaries_minutes"] for p in ctx.manifest["patients"]}
    pids = ctx.table["patient_id"].to_numpy()
    origins = ctx.table["origin"].to_numpy(float)
    for pid in np.unique(pids):
        rows = np.where(pids == pid)[0]
        prep = ctx.prep[pid]
        b = bounds[pid]
        state = AdaptationState(policy, ctx.horizons, collect_from=b["train_end"])
        frozen: dict[int, float] | None = None
        for r in rows:
            t = origins[r]
            if freeze_at_test and t >= b["val_end"]:
                if frozen is None:
                    frozen = {h: state.horizon_summary(h, t)["correction_mg_dl"] for h in ctx.horizons}
                for h in ctx.horizons:
                    corr[h][r] = frozen[h] if np.isfinite(pop[h][r]) else np.nan
                continue
            pp = {h: pop[h][r] for h in ctx.horizons}
            c = state.step(t, prep.g_obs, prep.g_val, prep.g_avail, pp, f"{pid}:{r}")
            for h in ctx.horizons:
                if t >= b["train_end"] and np.isfinite(pop[h][r]):
                    corr[h][r] = c[h] if c[h] is not None else 0.0
    return corr


def select_adaptation(ctx: Ctx, pop: dict[int, np.ndarray], log: list, label: str) -> tuple[AdaptationPolicy, dict]:
    a = ctx.exp["adaptation"]
    base = macro_over_horizons(ctx, "validation", pop)
    best_by_h: dict[int, tuple[float, float, float]] = {}
    for k in a["grid"]["shrinkage_k"]:
        for hl in a["grid"]["half_life_minutes"]:
            pol = AdaptationPolicy(a["policy_id"], True, float(k), float(hl), float(a["cap_mg_dl"]),
                                   int(a["min_residuals"]), float(a["reset_gap_minutes"]),
                                   float(ctx.exp["target"]["match_tolerance_minutes"]))
            corr = prequential(ctx, pop, pol)
            for h in ctx.horizons:
                m = ctx.eval_mask("validation", h)
                s = macro(per_patient_mae(ctx, m, pop[h] + np.nan_to_num(corr[h]), h))
                log.append({"bundle": label, "horizon": h, "k": k, "half_life": hl, "selection_macro_mae": s})
                if h not in best_by_h or s < best_by_h[h][0]:
                    best_by_h[h] = (s, k, hl)
    # one policy per bundle: choose the (k, half-life) with the best mean over horizons
    rows = pd.DataFrame([r for r in log if r.get("bundle") == label])
    agg = rows.groupby(["k", "half_life"])["selection_macro_mae"].mean().sort_values()
    (k, hl), score = agg.index[0], float(agg.iloc[0])
    k, hl = float(k), float(hl)
    adopted = score < base
    pol = AdaptationPolicy(a["policy_id"], adopted, float(k), float(hl), float(a["cap_mg_dl"]),
                           int(a["min_residuals"]), float(a["reset_gap_minutes"]),
                           float(ctx.exp["target"]["match_tolerance_minutes"]))
    return pol, {"bundle": label, "selection_macro_mae_without": base, "selection_macro_mae_with": score,
                 "shrinkage_k": k, "half_life_minutes": hl, "adopted": bool(adopted)}


def macro_over_horizons(ctx: Ctx, seg: str, preds: dict[int, np.ndarray]) -> float:
    return float(np.mean([macro(per_patient_mae(ctx, ctx.eval_mask(seg, h), preds[h], h)) for h in ctx.horizons]))


# ------------------------------------------------------------------------------------------------
# step 5: alerts
# ------------------------------------------------------------------------------------------------


def alert_scores(ctx: Ctx, preds: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
    thr = float(ctx.exp["event"]["threshold_mg_dl"])
    out = {}
    for H in ctx.horizons:
        stack = np.vstack([preds[h] for h in ctx.horizons if h <= H])
        with np.errstate(all="ignore"):
            out[H] = np.nanmax(np.where(np.isnan(stack), -np.inf, stack), axis=0) - thr
        out[H][~np.isfinite(out[H])] = np.nan
    return out


def event_eval(ctx: Ctx, seg: str, score: np.ndarray, H: int, threshold: float) -> tuple[dict, dict]:
    t = ctx.table
    merge = float(ctx.exp["alerts"]["episode_merge_minutes"])
    results, per_patient = [], {}
    in_seg = ctx.seg(seg)
    elig = t["ew_eligible"].to_numpy(bool)
    lab = t[f"label_{H}"].to_numpy(float)
    eligible_days = float((in_seg & elig & ctx.issued & np.isfinite(lab)).sum() * 5 / 1440)
    observed_days = float((in_seg & ctx.issued).sum() * 5 / 1440)
    for pid in t["patient_id"].unique():
        r = (t["patient_id"] == pid).to_numpy()
        res = alert_eval.evaluate_patient(
            t["origin"].to_numpy(float)[r], in_seg[r], elig[r], ctx.issued[r], score[r], lab[r],
            t[f"onset_{H}"].to_numpy(float)[r], threshold, H, merge)
        results.append(res)
        per_patient[pid] = res
    summ = alert_eval.summarize(results, eligible_days, observed_days, float(H))
    from sklearn.metrics import average_precision_score
    m = in_seg & elig & ctx.issued & np.isfinite(lab) & np.isfinite(score)
    summ["origin_pr_auc"] = (float(average_precision_score(lab[m], score[m]))
                             if m.sum() and 0 < lab[m].sum() < m.sum() else None)
    summ["origin_prevalence"] = float(lab[m].mean()) if m.sum() else None
    summ["censored_origins"] = int((in_seg & elig & ctx.issued & ~np.isfinite(lab)).sum())
    return summ, per_patient


def select_threshold(ctx: Ctx, score: np.ndarray, H: int) -> tuple[float, list[dict]]:
    rows = []
    for th in ctx.exp["alerts"]["threshold_grid"]:
        s, _ = event_eval(ctx, "validation", score, H, float(th))
        rows.append({"threshold": float(th), **{k: s[k] for k in ("f1", "recall", "precision",
                                                                   "warnings_per_patient_day")}})
    df = pd.DataFrame(rows)
    df["f1_"] = df["f1"].fillna(-1)
    df = df.sort_values(["f1_", "warnings_per_patient_day"], ascending=[False, True])
    return float(df.iloc[0]["threshold"]), rows


# ------------------------------------------------------------------------------------------------
# main
# ------------------------------------------------------------------------------------------------


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base.get(k, {}), v) if isinstance(v, dict) else v
    return out


def run(include_lopo: bool = True, stop_before_test: bool = False, store_dir: Path | None = None,
        artifacts_dir: Path | None = None, register: bool = True, overrides: dict | None = None,
        experiment_id: str | None = None) -> dict[str, Any]:
    """Run the protocol. ``overrides`` exists only for fast synthetic integration tests."""
    t_run = time.perf_counter()
    ctx = load_ctx(store_dir, experiment_id)
    if overrides:
        ctx.exp = _merge(ctx.exp, overrides)
    exp = ctx.exp
    exp_id = exp["experiment_id"]
    artifacts_root = artifacts_dir or paths().artifacts
    out_dir = artifacts_root / "experiments" / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    timings: dict[str, float] = {}

    # ---------------- step 1: fit candidates
    bundles = fit_baselines(ctx, log)
    for family in ("lightgbm", "catboost"):
        for fs in exp["features"]["candidate_feature_sets"]:
            t0 = time.perf_counter()
            bundles.append(search_family(ctx, family, fs, log))
            timings[f"{family}:{fs}"] = time.perf_counter() - t0
            print(f"searched {family}:{fs} in {timings[f'{family}:{fs}']:.1f}s", flush=True)
    pops = {b.label: population_predictions(ctx, b) for b in bundles}

    # ---------------- step 2: select serving population model on validation-selection
    sel_cfg = exp["models"]["selection"]
    cand_rows = []
    for b in bundles:
        per_h = {h: macro(per_patient_mae(ctx, ctx.eval_mask("validation", h), pops[b.label][h], h))
                 for h in ctx.horizons}
        cand_rows.append({"label": b.label, "family": b.family, "feature_set_id": b.feature_set_id,
                          **{f"selection_mae_{h}": v for h, v in per_h.items()},
                          "selection_score": float(np.mean(list(per_h.values())))})
    cand = pd.DataFrame(cand_rows)
    best = cand["selection_score"].min()
    tied = cand[cand["selection_score"] <= best + float(sel_cfg["tie_margin_mg_dl"])].copy()
    tied["c"] = tied["family"].map(sel_cfg["complexity_order"].index)
    tied["fs_size"] = tied["feature_set_id"].map(lambda f: len(FEATURE_SETS[f].columns()))
    chosen = tied.sort_values(["c", "fs_size", "selection_score"]).iloc[0]
    serving = next(b for b in bundles if b.label == chosen["label"])
    rationale = (f"{chosen['label']} had validation-selection score {chosen['selection_score']:.2f} mg/dL "
                 f"(best {best:.2f}); {len(tied)} candidate(s) within the "
                 f"{sel_cfg['tie_margin_mg_dl']} mg/dL tie margin; tie-break by declared complexity order.")
    print("selected", chosen["label"], rationale, flush=True)

    # ---------------- step 3: adaptation selection per tree bundle (and the serving bundle)
    adapt_log: list[dict] = []
    adapt_bundles = [b for b in bundles if b.family in ("lightgbm", "catboost")]
    if serving not in adapt_bundles:
        adapt_bundles.append(serving)
    policies, adapt_summary = {}, []
    for b in adapt_bundles:
        pol, summ = select_adaptation(ctx, pops[b.label], adapt_log, b.label)
        policies[b.label] = pol
        adapt_summary.append(summ)
    serving_policy = policies[serving.label]

    # pipelines: label -> {personalization: preds}
    pipelines: dict[str, dict[str, dict[int, np.ndarray]]] = {}
    corrections: dict[str, dict[int, np.ndarray]] = {}
    for b in bundles:
        pipelines[b.label] = {"off": pops[b.label]}
        if b.label in policies:
            pol = policies[b.label]
            pol_on = AdaptationPolicy(**{**pol.as_dict(), "enabled": True})
            corr = prequential(ctx, pops[b.label], pol_on)
            corr_f = prequential(ctx, pops[b.label], pol_on, freeze_at_test=True)
            corrections[b.label] = corr
            pipelines[b.label]["adaptive"] = {h: pops[b.label][h] + np.nan_to_num(corr[h]) for h in ctx.horizons}
            pipelines[b.label]["frozen_state"] = {h: pops[b.label][h] + np.nan_to_num(corr_f[h]) for h in ctx.horizons}
    serving_mode = "adaptive" if serving_policy.enabled else "off"
    serving_preds = pipelines[serving.label][serving_mode]

    # ---------------- step 4: conformal intervals on calibration segment (serving pipeline + others)
    level = float(exp["intervals"]["level"])
    interval_q: dict[str, dict[str, dict[int, float | None]]] = {}
    for label, modes in pipelines.items():
        interval_q[label] = {}
        for mode, preds in modes.items():
            interval_q[label][mode] = {}
            for h in ctx.horizons:
                m = ctx.eval_mask("calibration", h)
                res = np.abs(ctx.table[f"target_{h}"].to_numpy(float)[m] - preds[h][m])
                interval_q[label][mode][h] = conformal_quantile(res, level)

    # ---------------- step 5: alert thresholds on validation-selection
    alert_candidates = {
        "persistence": pipelines["persistence:cgm-only-v1"]["off"],
        "linear_trend": pipelines["linear_trend:cgm-only-v1"]["off"],
        f"{serving.label} (population)": pipelines[serving.label]["off"],
    }
    if serving_mode == "adaptive":
        alert_candidates[f"{serving.label} (adaptive)"] = serving_preds
    thresholds, threshold_logs = {}, {}
    for name, preds in alert_candidates.items():
        sc = alert_scores(ctx, preds)
        for H in ctx.horizons:
            th, rows = select_threshold(ctx, sc[H], H)
            thresholds[(name, H)] = th
            threshold_logs[f"{name}|{H}"] = rows
    serving_alert_name = f"{serving.label} ({'adaptive' if serving_mode == 'adaptive' else 'population'})"
    serving_threshold = thresholds[(serving_alert_name, int(exp["alerts"]["serving_horizon_minutes"]))]

    # ---------------- freeze + write serving artifact BEFORE looking at test
    model_version = f"{serving.family}.{serving.feature_set_id}.{exp_id}"
    model_dir = artifacts_root / "models" / model_version
    serving_cfg = {
        "model_version": model_version, "model_family": serving.family, "feature_set_id": serving.feature_set_id,
        "experiment_id": exp_id, "config_hash": ctx.st.config_hash,
        "data_fingerprint": ctx.manifest["data_fingerprint"], "split_hash": ctx.manifest["split_hash"],
        "transform_fingerprint": FEATURE_SETS[serving.feature_set_id].transform_fingerprint(),
        "adaptation": serving_policy.as_dict(),
        "adaptation_collect_rule": "origins at or after each participant's validation start; all origins for "
                                   "participants never seen in training",
        "intervals": {"method": exp["intervals"]["method"], "level": level,
                      "quantiles_mg_dl": {str(h): interval_q[serving.label][serving_mode][h] for h in ctx.horizons},
                      "calibrated_for": f"{serving.label} with personalization={serving_mode}"},
        "alerts": {"rule_version": exp["alerts"]["rule_version"],
                   "horizon_minutes": int(exp["alerts"]["serving_horizon_minutes"]),
                   "threshold_margin_mg_dl": serving_threshold, "score_kind": "forecast_margin_mg_dl",
                   "episode_merge_minutes": float(exp["alerts"]["episode_merge_minutes"])},
        "event_definition": exp["event"], "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "synthetic_fitted": False,
    }
    if stop_before_test:
        val = {b.label: {mode: {h: macro(per_patient_mae(ctx, ctx.eval_mask("validation", h), p[h], h))
                                for h in ctx.horizons} for mode, p in pipelines[b.label].items()}
               for b in bundles}
        report = {"status": "validation_only", "selection": cand.to_dict(orient="records"), "chosen": chosen["label"],
                  "rationale": rationale, "adaptation": adapt_summary, "validation_macro_mae": val,
                  "interval_q": {k: {m: {str(h): q for h, q in v.items()} for m, v in d.items()}
                                 for k, d in interval_q.items()},
                  "thresholds": {f"{k[0]}|{k[1]}": v for k, v in thresholds.items()},
                  "threshold_logs": threshold_logs, "timings": timings}
        (out_dir / "validation_only.json").write_text(json.dumps(report, indent=2, default=_json_default))
        print(f"validation-only run finished in {time.perf_counter() - t_run:.1f}s", flush=True)
        return report
    manifest = serving.save(model_dir, extra={"serving": serving_cfg})
    (model_dir / "serving.json").write_text(json.dumps(serving_cfg, indent=2, default=str))

    # ---------------- step 6: single final-test evaluation of all preregistered candidates
    lat_sample = ctx.table[ctx.eval_mask("test", ctx.horizons[0])]
    rows, per_patient_rows = [], []
    perpat: dict[tuple, pd.Series] = {}
    for b in bundles:
        latency = b.measure_latency_ms_per_1k(lat_sample)
        fit_s = sum(float(p.get("fit_seconds", 0) or 0) for p in b.params.values()) if b.params else 0.0
        for mode, preds in pipelines[b.label].items():
            for split in ("validation", "test"):
                for h in ctx.horizons:
                    m = ctx.eval_mask(split, h)
                    s_mae = per_patient_mae(ctx, m, preds[h], h)
                    s_rmse = per_patient_rmse(ctx, m, preds[h], h)
                    perpat[(b.label, mode, split, h)] = s_mae
                    seg_all = ctx.seg(split) & ctx.table[f"target_{h}"].notna().to_numpy()
                    rows.append({
                        "label": b.label, "family": b.family, "feature_set_id": b.feature_set_id,
                        "personalization": mode, "split": split, "horizon": h,
                        "mae": macro(s_mae), "rmse": macro(s_rmse), "n_patients": int(s_mae.size),
                        "n_origins": int(m.sum()),
                        "coverage": float(m.sum() / max(1, seg_all.sum())),
                        "train_seconds": fit_s, "latency_ms_per_1k": latency,
                        "selected": b.label == serving.label and mode == serving_mode,
                    })
                    if split == "test":
                        for pid, v in s_mae.items():
                            per_patient_rows.append({"patient_id": pid, "label": b.label, "personalization": mode,
                                                     "horizon": h, "mae": float(v)})
    results = pd.DataFrame(rows)

    # paired comparisons (participant-cluster bootstrap)
    nboot = int(exp["evaluation"]["bootstrap_resamples"])
    comparisons = []

    def add_cmp(name, a, b, h):
        mean, lo, hi = cluster_bootstrap_diff(perpat[a], perpat[b], nboot, ctx.seed + h)
        comparisons.append({"comparison": name, "horizon": h, "mean_diff_mae": mean, "ci95": [lo, hi],
                            "n_patients": int(len(perpat[a])), "a": list(a), "b": list(b)})

    for h in ctx.horizons:
        add_cmp("serving minus persistence", (serving.label, serving_mode, "test", h),
                ("persistence:cgm-only-v1", "off", "test", h), h)
        for b in adapt_bundles:
            add_cmp(f"{b.label}: adaptive minus population", (b.label, "adaptive", "test", h),
                    (b.label, "off", "test", h), h)
        for fs in exp["features"]["candidate_feature_sets"]:
            add_cmp(f"lightgbm minus catboost ({fs}, population)", (f"lightgbm:{fs}", "off", "test", h),
                    (f"catboost:{fs}", "off", "test", h), h)
        cands = exp["features"]["candidate_feature_sets"]
        prof = next((f for f in cands if "prof" in f), None)
        dyn = next((f for f in cands if "prof" not in f), None)
        if prof and dyn:
            for fam in ("lightgbm", "catboost"):
                add_cmp(f"{fam}: profile minus dynamic-only (population)", (f"{fam}:{prof}", "off", "test", h),
                        (f"{fam}:{dyn}", "off", "test", h), h)

    # intervals on test
    interval_rows = []
    for label, modes in pipelines.items():
        for mode, preds in modes.items():
            for h in ctx.horizons:
                q = interval_q[label][mode][h]
                for split in ("calibration", "test"):
                    m = ctx.eval_mask(split, h)
                    if q is None:
                        continue
                    err = np.abs(ctx.table[f"target_{h}"].to_numpy(float)[m] - preds[h][m])
                    inside = pd.Series(err <= q).groupby(ctx.table["patient_id"].to_numpy()[m]).mean()
                    interval_rows.append({"label": label, "personalization": mode, "horizon": h, "split": split,
                                          "level": level, "q": q, "coverage": float((err <= q).mean()),
                                          "width": 2 * q, "per_patient_min": float(inside.min()),
                                          "per_patient_max": float(inside.max()), "n": int(m.sum())})

    # events on validation + test
    event_rows, serving_test_patients = [], None
    for name, preds in alert_candidates.items():
        sc = alert_scores(ctx, preds)
        for H in ctx.horizons:
            for split in ("validation", "test"):
                s, per_p = event_eval(ctx, split, sc[H], H, thresholds[(name, H)])
                event_rows.append({"model": name, "horizon": H, "split": split, "threshold": thresholds[(name, H)], **s})
                if name == serving_alert_name and split == "test" and H == serving_cfg["alerts"]["horizon_minutes"]:
                    serving_test_patients = per_p

    # meal sensitivity (optimistic availability) — serving family, serving hyperparameters, never selectable
    sensitivity = []
    if serving.family in ("lightgbm", "catboost", "ridge"):
        fs = next(iter(exp["features"].get("sensitivity_feature_sets") or {"dyn-prof-meal-v1": ""}))
        cols = FEATURE_SETS[fs].columns()
        models = {}
        for h in ctx.horizons:
            tr, sel = _train_rows(ctx, h), ctx.eval_mask("validation", h)
            p = {k: v for k, v in serving.params[h].items() if k not in ("best_iteration", "fit_seconds", "alpha")}
            if serving.family == "ridge":
                models[h] = RidgeModel(cols, alpha=serving.params[h]["alpha"]).fit(ctx.table.loc[tr], _y(ctx, tr, h))
            else:
                cls = LightGBMModel if serving.family == "lightgbm" else CatBoostModel
                models[h] = cls(cols, p).fit(ctx.table.loc[tr], _y(ctx, tr, h), ctx.table.loc[sel], _y(ctx, sel, h),
                                             seed=ctx.seed, early_stopping=int(exp["models"]["tree_search"]["early_stopping_rounds"]),
                                             max_rounds=int(exp["models"]["tree_search"]["max_boosting_rounds"]))
        mb = PopulationBundle(serving.family, fs, ctx.horizons, models, label=f"{serving.family}:{fs}")
        mp = population_predictions(ctx, mb)
        for split in ("validation", "test"):
            for h in ctx.horizons:
                m = ctx.eval_mask(split, h)
                s = per_patient_mae(ctx, m, mp[h], h)
                base = perpat[(serving.label, "off", split, h)]
                sensitivity.append({"experiment": "optimistic meal logging", "label": mb.label, "split": split,
                                    "horizon": h, "mae": macro(s), "serving_population_mae": macro(base),
                                    "note": "Assumes meal macronutrients known at the photo timestamp; "
                                            "not eligible for serving."})

    # LOPO cold-start secondary analysis
    lopo = run_lopo(ctx, serving, serving_policy) if include_lopo and serving.family != "persistence" else []

    # ---------------- write outputs
    pred_rows = []
    keep = ctx.table["segment"].isin(list(SEGMENTS)).to_numpy()
    base_cols = ctx.table.loc[keep, ["patient_id", "origin", "segment", "g_last"]].reset_index(drop=True)
    for label, modes in pipelines.items():
        for mode, preds in modes.items():
            for h in ctx.horizons:
                df = base_cols.copy()
                df["model"], df["personalization"], df["horizon"] = label, mode, h
                df["predicted"] = preds[h][keep]
                df["target"] = ctx.table.loc[keep, f"target_{h}"].to_numpy(float)
                pred_rows.append(df)
    pd.concat(pred_rows, ignore_index=True).to_parquet(out_dir / "predictions.parquet", index=False)

    alerts_out = []
    if serving_test_patients:
        for pid, res in serving_test_patients.items():
            for ep in res.episodes:
                alerts_out.append({"patient_id": pid, **{k: v for k, v in ep.items()}})
    (out_dir / "alerts.json").write_text(json.dumps({"model": serving_alert_name, "split": "test",
                                                      "threshold": serving_threshold, "episodes": alerts_out},
                                                     indent=2, default=float))

    selection = {
        "rule": sel_cfg["rule"].strip(), "tie_break": sel_cfg["tie_break"].strip(),
        "candidates": cand.to_dict(orient="records"), "selected_label": serving.label,
        "selected_family": serving.family, "selected_feature_set": serving.feature_set_id,
        "rationale": rationale, "adaptation": adapt_summary, "serving_personalization": serving_mode,
    }
    metrics = {
        "experiment_id": exp_id, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "completed", "model_version": model_version,
        "corrects_experiment_id": exp.get("corrects"), "correction_note": (exp.get("correction_note") or "").strip() or None,
        "feature_transform": ctx.manifest.get("feature_transform"),
        "fingerprints": {"config_hash": ctx.st.config_hash, "data_fingerprint": ctx.manifest["data_fingerprint"],
                         "split_hash": ctx.manifest["split_hash"],
                         "model_artifact": fingerprint(manifest["files"])},
        "environment": env_info(), "timings_seconds": {**timings, "total": time.perf_counter() - t_run},
        "cohort": ctx.manifest["summary"], "excluded": ctx.manifest["excluded"],
        "selection": selection, "forecast_results": results.to_dict(orient="records"),
        "per_patient_test": per_patient_rows, "comparisons": comparisons,
        "intervals": interval_rows, "events": event_rows, "alert_threshold_selection": threshold_logs,
        "sensitivity": sensitivity, "lopo": lopo,
        "aliases": {p["patient_id"]: p["display_alias"] for p in ctx.manifest["patients"]},
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=_json_default))
    (out_dir / "search_log.json").write_text(json.dumps({"population": log, "adaptation": adapt_log},
                                                        indent=1, default=_json_default))
    if register:
        update_registry(model_version, model_dir, serving_cfg, rationale, exp_id)
    print(f"done in {time.perf_counter() - t_run:.1f}s -> {out_dir}", flush=True)
    return metrics


def run_lopo(ctx: Ctx, serving: PopulationBundle, policy: AdaptationPolicy) -> list[dict]:
    """Leave-one-participant-out cold start with the frozen serving configuration (no retuning)."""
    out = []
    cols = serving.columns
    pids = ctx.table["patient_id"].to_numpy()
    for pid in np.unique(pids):
        models = {}
        for h in ctx.horizons:
            tr = _train_rows(ctx, h) & (pids != pid)
            y = _y(ctx, tr, h)
            p = {k: v for k, v in serving.params.get(h, {}).items() if k not in ("best_iteration", "fit_seconds", "alpha")}
            if serving.family == "lightgbm":
                import lightgbm as lgb
                params = {"objective": "regression", "verbosity": -1, "seed": ctx.seed, "deterministic": True,
                          "force_row_wise": True, "num_threads": 4, "bagging_freq": 1, **p}
                booster = lgb.train(params, lgb.Dataset(ctx.table.loc[tr, cols].to_numpy(float), label=y,
                                                        feature_name=cols),
                                    num_boost_round=int(serving.params[h]["best_iteration"]))
                models[h] = LightGBMModel(cols, booster=booster)
            elif serving.family == "catboost":
                from catboost import CatBoostRegressor
                m = CatBoostRegressor(loss_function="RMSE", iterations=max(1, int(serving.params[h]["best_iteration"]) + 1),
                                      random_seed=ctx.seed, verbose=False, thread_count=4, allow_writing_files=False,
                                      nan_mode="Min", **p)
                m.fit(ctx.table.loc[tr, cols].to_numpy(float), y)
                models[h] = CatBoostModel(cols, model=m)
            elif serving.family == "ridge":
                models[h] = RidgeModel(cols, alpha=serving.params[h]["alpha"]).fit(ctx.table.loc[tr], y)
            else:
                models[h] = serving.models[h]
        b = PopulationBundle(serving.family, serving.feature_set_id, ctx.horizons, models)
        r = pids == pid
        sub = ctx.table.loc[r]
        preds = b.predict(sub)
        issued = ctx.issued[r]
        prep = ctx.prep[pid]
        state = AdaptationState(AdaptationPolicy(**{**policy.as_dict(), "enabled": True}), ctx.horizons,
                                collect_from=-np.inf)
        corr = {h: np.full(r.sum(), np.nan) for h in ctx.horizons}
        for i, t in enumerate(sub["origin"].to_numpy(float)):
            pp = {h: (preds[h][i] if issued[i] else None) for h in ctx.horizons}
            c = state.step(t, prep.g_obs, prep.g_val, prep.g_avail, pp, f"lopo:{pid}:{i}")
            for h in ctx.horizons:
                corr[h][i] = c[h]
        for h in ctx.horizons:
            m = (ctx.eval_mask("test", h))[r]
            tgt = sub[f"target_{h}"].to_numpy(float)
            out.append({
                "patient_id": pid, "horizon": h,
                "lopo_population_mae": float(np.mean(np.abs(preds[h][m] - tgt[m]))),
                "lopo_adaptive_mae": float(np.mean(np.abs(preds[h][m] + corr[h][m] - tgt[m]))),
                "n_origins": int(m.sum()),
            })
    return out


def env_info() -> dict[str, str]:
    import catboost
    import lightgbm
    import sklearn
    return {"python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(),
            "processor": platform.processor() or "unknown", "lightgbm": lightgbm.__version__,
            "catboost": catboost.__version__, "scikit-learn": sklearn.__version__, "numpy": np.__version__,
            "pandas": pd.__version__}


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def update_registry(model_version: str, model_dir: Path, serving_cfg: dict, rationale: str, exp_id: str) -> None:
    reg_path = paths().artifacts / "registry.json"
    reg = json.loads(reg_path.read_text()) if reg_path.exists() else {"models": [], "serving": {}}
    reg["models"] = [m for m in reg["models"] if m["model_version"] != model_version]
    manifest = json.loads((model_dir / "manifest.json").read_text())
    reg["models"].append({
        "model_version": model_version, "model_family": serving_cfg["model_family"],
        "feature_set_id": serving_cfg["feature_set_id"], "horizons": manifest["horizons"],
        "artifact_dir": str(model_dir.relative_to(paths().root)),
        "artifact_checksum": fingerprint(manifest["files"]), "selection_rationale": rationale,
        "evaluation_reference": f"artifacts/experiments/{exp_id}/metrics.json", "mode": "dataset_replay",
        "synthetic_fitted": False,
    })
    reg["serving"]["dataset_replay"] = model_version
    reg_path.write_text(json.dumps(reg, indent=2))
