"""Development stage of one fold and track (``glucotwin research develop``).

Uses ONLY the fold's development and calibration participants; the outer-assessment participants of the fold are not
even loaded into the masks used here. Order of operations (protocol gt-nested-2026-10-12-v1):

1. Inner participant cross-validation on the development participants: every candidate predicts each inner fold from
   a model that never saw those people. Trees fit on purged chronological heads of their training participants and
   early-stop on the tails.
2. Population-model selection by the declared rule (inner out-of-fold mean macro MAE, tie margin, complexity order).
3. Adaptation choice (off / v2 policy / grid) by the declared adoption rule, for the selected pipeline and the best
   pipeline of every tree configuration, with identical masks.
4. Warning thresholds on the exact final pipelines' inner out-of-fold predictions (5-minute track).
5. Refit every candidate on all development participants with the selected settings.
6. Calibrate prediction ranges on the reserved calibration participants with the frozen final pipelines.
7. Freeze: bundles, policies, quantiles, thresholds and their hashes are written to disk before any assessment.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import fingerprint
from glucotwin.features import FEATURE_SETS
from glucotwin.models.population import LinearTrendModel, PersistenceModel, PopulationBundle, RidgeModel
from glucotwin.research import adapt, calibration, warnings
from glucotwin.research.common import Ctx, v2_recipe
from glucotwin.research.metrics import macro, per_participant_mae
from glucotwin.research.models import fit_catboost, fit_lightgbm, sample_trials
from glucotwin.research.protocol import FoldPlan, pipeline_freeze_hash, research_dir

FAMILY_OF = {"persistence": "persistence", "linear_trend": "linear_trend", "ridge": "ridge",
             "lightgbm_l2": "lightgbm", "lightgbm_l1": "lightgbm", "catboost": "catboost", "v2_recipe": "lightgbm"}
TREE_CONFIGS = ("lightgbm_l2", "lightgbm_l1", "catboost")


@dataclass
class Cand:
    label: str
    config: str
    fs: str
    oof: dict[int, np.ndarray] = field(default_factory=dict)       # inner out-of-fold population predictions
    params: dict[int, dict] = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)

    @property
    def family(self) -> str:
        return FAMILY_OF[self.config]


def fold_dir(experiment_id: str, fold: str, track: str) -> Path:
    return research_dir(experiment_id) / "development" / fold / track


# ------------------------------------------------------------------------------------------------ masks


def head_tail(ctx: Ctx, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per participant: tail = last ``tail_fraction`` of the elapsed span; head = origins purged before the tail."""
    f = ctx.proto["folds"]
    frac, purge = float(f["early_stopping_tail_fraction"]), float(f["purge_minutes"])
    o = ctx.t["origin"].to_numpy(float)
    head, tail = np.zeros(len(o), bool), np.zeros(len(o), bool)
    for pid in pd.unique(ctx.pids[rows]):
        r = rows & (ctx.pids == pid)
        lo, hi = o[r].min(), o[r].max()
        start = lo + (1 - frac) * (hi - lo)
        tail |= r & (o >= start)
        head |= r & (o + purge < start)
    return head, tail


# ------------------------------------------------------------------------------------------------ candidates


def _pred_rows(ctx: Ctx, pids) -> np.ndarray:
    return ctx.rows(pids) & ctx.issued


def base_fs(ctx: Ctx) -> str:
    """Feature set recorded for the feature-free baselines: the track's CGM-only transformation."""
    return "cgm-only-v1" if ctx.track == "multimodal_5min" else ctx.proto["tracks"][ctx.track]["superset_feature_set"]


def persistence(ctx: Ctx, dev: list[str]) -> Cand:
    c = Cand("persistence:-", "persistence", base_fs(ctx))
    g = ctx.t["g_last"].to_numpy(float)
    m = _pred_rows(ctx, dev)
    c.oof = {h: np.where(m, g, np.nan) for h in ctx.horizons}
    return c


def trend_windows(proto: dict, track: str) -> list[int]:
    """Linear-trend slope windows for a track.

    Per-track mapping (protocols from gt-nested-2026-10-12-v2 on): every window must hold at least three readings at the
    track's cadence (window >= 2 x cadence) and have a slope feature, otherwise the protocol is refused — a too-short
    window silently degenerates to persistence. A plain list (gt-nested-2026-10-12-v1) is used unchanged so the frozen
    experiment reproduces exactly as measured."""
    from glucotwin.research.protocol import ProtocolError

    w = proto["models"]["baselines"]["linear_trend"]["window_minutes"]
    if not isinstance(w, dict):
        return [int(x) for x in w]
    cadence = float(proto["tracks"][track]["cadence_minutes"])
    cols = set(FEATURE_SETS[proto["tracks"][track]["superset_feature_set"]].columns())
    out = [int(x) for x in w[track]]
    bad = [x for x in out if x < 2 * cadence or f"slope_{x}" not in cols]
    if bad or not out:
        raise ProtocolError(f"{track}: linear-trend windows {bad or out} cannot hold three readings at a "
                            f"{cadence:g}-minute cadence or have no slope feature")
    return out


def linear_trend(ctx: Ctx, dev: list[str]) -> Cand:
    cfg = ctx.proto["models"]["baselines"]["linear_trend"]
    c = Cand("linear_trend:-", "linear_trend", base_fs(ctx))
    g = ctx.t["g_last"].to_numpy(float)
    m = _pred_rows(ctx, dev)
    for h in ctx.horizons:
        best = None
        for w in trend_windows(ctx.proto, ctx.track):
            for d in cfg["damping"]:
                mod = LinearTrendModel(h, int(w), float(d), float(cfg["max_change_mg_dl"]))
                pred = np.where(m, g + mod.predict_delta(ctx.t), np.nan)
                s = macro(per_participant_mae(pred, ctx.target(h), ctx.pids, ctx.scored(dev, h)))
                c.trace.append({"horizon": h, "window": w, "damping": d, "dev_macro_mae": s})
                if best is None or s < best[0]:
                    best = (s, mod, pred)
        c.params[h] = best[1].params()
        c.oof[h] = best[2]
    return c


def ridge(ctx: Ctx, plan: FoldPlan, fs: str) -> Cand:
    cols = FEATURE_SETS[fs].columns()
    c = Cand(f"ridge:{fs}", "ridge", fs)
    for h in ctx.horizons:
        best = None
        for a in ctx.proto["models"]["baselines"]["ridge"]["alpha"]:
            pred = np.full(len(ctx.t), np.nan)
            for fold in plan.inner:
                train = [p for p in plan.development if p not in fold]
                tr = ctx.scored(train, h)
                mod = RidgeModel(cols, alpha=float(a)).fit(ctx.t.loc[tr], ctx.y(h)[tr])
                te = _pred_rows(ctx, fold)
                pred[te] = ctx.t.loc[te, "g_last"].to_numpy(float) + mod.predict_delta(ctx.t.loc[te])
            s = macro(per_participant_mae(pred, ctx.target(h), ctx.pids, ctx.scored(plan.development, h)))
            c.trace.append({"horizon": h, "alpha": a, "inner_oof_macro_mae": s})
            if best is None or s < best[0]:
                best = (s, a, pred)
        c.params[h] = {"alpha": float(best[1])}
        c.oof[h] = best[2]
    return c


def _fit_tree(ctx: Ctx, config: str, fs: str, params: dict, train: list[str], h: int, seed: int,
              fixed_rounds: int | None = None):
    s = ctx.proto["models"]["search"]
    tc = ctx.proto["models"]["trees"].get(config, {"family": "lightgbm", "objective": "l2", "stopping_metric": "l2"})
    cols = FEATURE_SETS[fs].columns()
    rows = ctx.scored(train, h)
    if fixed_rounds is not None:
        return fit_lightgbm(cols, params, "l2", "l2", ctx.t.loc[rows], ctx.y(h)[rows], None, None, None, seed, 0, 0,
                            int(s["threads_per_fit"]), fixed_rounds=fixed_rounds)
    head, tail = head_tail(ctx, rows)
    Xtr, ytr, Xva, yva = ctx.t.loc[head], ctx.y(h)[head], ctx.t.loc[tail], ctx.y(h)[tail]
    if tc["family"] == "lightgbm":
        return fit_lightgbm(cols, params, tc["objective"], tc["stopping_metric"], Xtr, ytr, Xva, yva,
                            ctx.pids[tail], seed, int(s["max_boosting_rounds"]), int(s["early_stopping_rounds"]),
                            int(s["threads_per_fit"]))
    return fit_catboost(cols, params, Xtr, ytr, Xva, yva, seed, int(s["max_boosting_rounds"]),
                        int(s["early_stopping_rounds"]), int(s["threads_per_fit"]))


def tree_search(ctx: Ctx, plan: FoldPlan, config: str, fs: str, n_trials: int | None = None) -> Cand:
    s = ctx.proto["models"]["search"]
    tc = ctx.proto["models"]["trees"][config]
    fam = tc["family"]
    space = s[f"{fam}_space"]
    c = Cand(f"{config}:{fs}", config, fs)
    fs_idx = list(FEATURE_SETS).index(fs)
    for h in ctx.horizons:
        trials = sample_trials(space, fam, int(n_trials or s["trials_per_config"]), [ctx.seed, 0 if fam == "lightgbm" else 1,
                                                                                     h, fs_idx])
        best = None
        for ti, params in enumerate(trials):
            pred = np.full(len(ctx.t), np.nan)
            iters, secs = [], 0.0
            for fi, fold in enumerate(plan.inner):
                train = [p for p in plan.development if p not in fold]
                mod, info = _fit_tree(ctx, config, fs, params, train, h, ctx.seed + 31 * ti + fi)
                te = _pred_rows(ctx, fold)
                pred[te] = ctx.t.loc[te, "g_last"].to_numpy(float) + mod.predict_delta(ctx.t.loc[te])
                iters.append(info["best_iteration"])
                secs += info["fit_seconds"]
            score = macro(per_participant_mae(pred, ctx.target(h), ctx.pids, ctx.scored(plan.development, h)))
            c.trace.append({"horizon": h, "trial": ti, "params": params, "inner_best_iterations": iters,
                            "fit_seconds": secs, "inner_oof_macro_mae": score})
            if best is None or score < best[0]:
                best = (score, params, pred)
        c.params[h] = dict(best[1])
        c.oof[h] = best[2]
    return c


def v2_recipe_cand(ctx: Ctx, plan: FoldPlan) -> Cand:
    rec = v2_recipe()
    c = Cand(f"v2_recipe:{rec['feature_set']}", "v2_recipe", rec["feature_set"])
    for h in ctx.horizons:
        p = {k: v for k, v in rec["params"][h].items() if k != "_rounds"}
        pred = np.full(len(ctx.t), np.nan)
        for fi, fold in enumerate(plan.inner):
            train = [x for x in plan.development if x not in fold]
            mod, _ = _fit_tree(ctx, "v2_recipe", c.fs, p, train, h, ctx.seed + fi, fixed_rounds=rec["params"][h]["_rounds"])
            te = _pred_rows(ctx, fold)
            pred[te] = ctx.t.loc[te, "g_last"].to_numpy(float) + mod.predict_delta(ctx.t.loc[te])
        c.params[h] = {**p, "fixed_rounds": rec["params"][h]["_rounds"]}
        c.oof[h] = pred
    return c


# ------------------------------------------------------------------------------------------------ selection


def score_of(ctx: Ctx, preds: dict[int, np.ndarray], pids) -> dict[int, float]:
    return {h: macro(per_participant_mae(preds[h], ctx.target(h), ctx.pids, ctx.scored(pids, h))) for h in ctx.horizons}


def select(ctx: Ctx, cands: list[Cand], dev: list[str]) -> tuple[Cand, list[dict], str]:
    sel = ctx.proto["selection"]
    order = sel["complexity_order"]
    rows = []
    for c in cands:
        per_h = score_of(ctx, c.oof, dev)
        rows.append({"label": c.label, "config": c.config, "feature_set": c.fs, **{f"mae_{h}": v for h, v in per_h.items()},
                     "score": float(np.mean(list(per_h.values()))), "n_columns": len(FEATURE_SETS[c.fs].columns())})
    best = min(r["score"] for r in rows)
    tied = [r for r in rows if r["score"] <= best + float(sel["tie_margin_mg_dl"])]
    chosen = sorted(tied, key=lambda r: (order.index(r["config"]), r["n_columns"], r["score"]))[0]
    why = (f"{chosen['label']} inner-OOF score {chosen['score']:.3f} mg/dL (best {best:.3f}); {len(tied)} candidate(s) "
           f"within the {sel['tie_margin_mg_dl']} mg/dL margin; complexity order then smaller feature set.")
    return next(c for c in cands if c.label == chosen["label"]), rows, why


def select_adaptation(ctx: Ctx, c: Cand, dev: list[str]) -> dict[str, Any]:
    a = ctx.proto["adaptation"]
    rows = ctx.rows(dev) & ctx.issued
    res: dict[str, Any] = {"label": c.label, "candidates": []}

    def run(name, k, hl, enabled=True):
        pol = adapt.make_policy(ctx.proto, ctx.track, k, hl, enabled)
        corr, _ = adapt.prequential(ctx.t, ctx.td.prep, rows, c.oof, pol, ctx.horizons)
        sc = score_of(ctx, adapt.apply(c.oof, corr), dev)
        entry = {"name": name, "k": k, "half_life": hl, **{f"mae_{h}": v for h, v in sc.items()},
                 "mean": float(np.mean(list(sc.values())))}
        res["candidates"].append(entry)
        return entry

    off = {"name": "off", "k": None, "half_life": None, **{f"mae_{h}": v for h, v in score_of(ctx, c.oof, dev).items()}}
    off["mean"] = float(np.mean([off[f"mae_{h}"] for h in ctx.horizons]))
    res["candidates"].append(off)
    v2 = run("v2_policy", float(a["v2_policy"]["shrinkage_k"]), float(a["v2_policy"]["half_life_minutes"]))
    grid = [run("grid", float(k), float(hl)) for k in a["grid"]["shrinkage_k"] for hl in a["grid"]["half_life_minutes"]]
    base = v2 if v2["mean"] < off["mean"] else off
    best = sorted(grid, key=lambda e: (e["mean"], -e["k"], -e["half_life"]))[0]
    adopt = (base["mean"] - best["mean"] >= float(a["min_improvement_mg_dl"]) - 1e-12 and
             all(best[f"mae_{h}"] - base[f"mae_{h}"] <= float(a["max_horizon_worsening_mg_dl"]) + 1e-12
                 for h in ctx.horizons))
    final = best if adopt else base
    res.update({"base": base["name"], "best_grid": {"k": best["k"], "half_life": best["half_life"], "mean": best["mean"]},
                "grid_adopted": bool(adopt), "final": {"name": final["name"], "k": final["k"],
                                                         "half_life": final["half_life"], "mean": final["mean"]}})
    return res


def policy_for(ctx: Ctx, final: dict[str, Any]):
    if final["name"] == "off":
        return None
    return adapt.make_policy(ctx.proto, ctx.track, final["k"], final["half_life"])


# ------------------------------------------------------------------------------------------------ refit + freeze


def refit(ctx: Ctx, c: Cand, dev: list[str]) -> tuple[PopulationBundle, dict]:
    models, info = {}, {}
    for h in ctx.horizons:
        if c.config == "persistence":
            models[h] = PersistenceModel()
        elif c.config == "linear_trend":
            models[h] = LinearTrendModel(h, **c.params[h])
        elif c.config == "ridge":
            rows = ctx.scored(dev, h)
            models[h] = RidgeModel(FEATURE_SETS[c.fs].columns(), alpha=c.params[h]["alpha"]).fit(ctx.t.loc[rows], ctx.y(h)[rows])
        elif c.config == "v2_recipe":
            p = {k: v for k, v in c.params[h].items() if k != "fixed_rounds"}
            models[h], info[h] = _fit_tree(ctx, c.config, c.fs, p, dev, h, ctx.seed, fixed_rounds=c.params[h]["fixed_rounds"])
        else:
            models[h], info[h] = _fit_tree(ctx, c.config, c.fs, c.params[h], dev, h, ctx.seed)
    fam = c.family if c.config != "v2_recipe" else "lightgbm"
    params = {h: {**c.params.get(h, {}), **({k: v for k, v in info.get(h, {}).items() if k in ("best_iteration", "objective",
                                                                                        "stopping_metric", "fit_seconds")})}
              for h in ctx.horizons}
    return PopulationBundle(fam, c.fs, ctx.horizons, models, label=c.label, params=params), info


def modes_for(ctx: Ctx, label: str, adapt_sel: dict[str, dict]) -> dict[str, dict | None]:
    """Personalization modes assessed for a pipeline: name -> {k, half_life, freeze_after_min} (None = off)."""
    a = ctx.proto["adaptation"]
    v2 = {"k": float(a["v2_policy"]["shrinkage_k"]), "half_life": float(a["v2_policy"]["half_life_minutes"])}
    if label.startswith("v2_recipe"):
        return {"off": None, "v2_policy": v2}
    if label not in adapt_sel:
        return {"off": None}
    s = adapt_sel[label]
    tuned = {"k": s["best_grid"]["k"], "half_life": s["best_grid"]["half_life"]}
    final = s["final"]
    frozen_src = tuned if final["name"] == "off" else {"k": final["k"], "half_life": final["half_life"]}
    return {"off": None, "v2_policy": v2, "best_grid": tuned,
            "frozen_state": {**frozen_src, "freeze_after_min": 60.0 * float(a["frozen_state_boundary_hours"])},
            "final": None if final["name"] == "off" else {"k": final["k"], "half_life": final["half_life"]}}


def run_mode(ctx: Ctx, rows: np.ndarray, pop: dict[int, np.ndarray], mode: dict | None):
    if mode is None:
        z = {h: np.where(rows & np.isfinite(pop[h]), 0.0, np.nan) for h in ctx.horizons}
        return pop, z, {h: np.full(len(ctx.t), np.nan) for h in ctx.horizons}
    pol = adapt.make_policy(ctx.proto, ctx.track, mode["k"], mode["half_life"])
    corr, nres = adapt.prequential(ctx.t, ctx.td.prep, rows, pop, pol, ctx.horizons, mode.get("freeze_after_min"))
    return adapt.apply(pop, corr), corr, nres


def cal_identity(ctx: Ctx, label: str, mode_name: str, mode: dict | None, bundle_hash: str, fold: str,
                 fs: str) -> dict:
    return {"experiment_id": ctx.experiment_id, "fold": fold, "track": ctx.track, "pipeline": label, "mode": mode_name,
            "adaptation": mode, "bundle_hash": bundle_hash, "feature_transform": FEATURE_SETS[fs].transform_fingerprint(),
            "level": float(ctx.proto["intervals"]["level"]), "horizons": ctx.horizons}


def develop(ctx: Ctx, plan: FoldPlan, n_trials: int | None = None, log=print) -> dict[str, Any]:
    t0 = time.perf_counter()
    out = fold_dir(ctx.experiment_id, plan.fold, ctx.track)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "pipeline.json").exists():
        log(f"[{plan.fold}/{ctx.track}] already frozen; skipping")
        return json.loads((out / "pipeline.json").read_text())
    dev = list(plan.development)
    fsets = ctx.proto["tracks"][ctx.track]["feature_sets"]
    cands = [persistence(ctx, dev), linear_trend(ctx, dev)]
    for fs in fsets:
        cands.append(ridge(ctx, plan, fs))
    timings = {}
    for config in TREE_CONFIGS:
        for fs in fsets:
            t1 = time.perf_counter()
            cands.append(tree_search(ctx, plan, config, fs, n_trials))
            timings[f"{config}:{fs}"] = time.perf_counter() - t1
            log(f"[{plan.fold}/{ctx.track}] {config}:{fs} searched in {timings[f'{config}:{fs}']:.1f}s")
    # Protocols without the v2 recipe (it has no model beyond 60 min) declare `comparators: {v2_recipe: null}`.
    want_v2 = ctx.proto["models"].get("comparators", {}).get("v2_recipe") is not None
    comparators = [v2_recipe_cand(ctx, plan)] if ctx.track == "multimodal_5min" and want_v2 else []
    chosen, sel_rows, why = select(ctx, cands, dev)
    log(f"[{plan.fold}/{ctx.track}] selected {chosen.label}: {why}")

    # adaptation: selected pipeline + best pipeline of every tree configuration (same grid, same masks)
    by_score = {r["label"]: r["score"] for r in sel_rows}
    adapt_labels = [chosen.label] + [min((c for c in cands if c.config == cfg), key=lambda c: by_score[c.label]).label
                                     for cfg in TREE_CONFIGS]
    adapt_labels = list(dict.fromkeys(adapt_labels))
    adapt_sel = {}
    for lab in adapt_labels:
        adapt_sel[lab] = select_adaptation(ctx, next(c for c in cands if c.label == lab), dev)
        log(f"[{plan.fold}/{ctx.track}] adaptation {lab}: {adapt_sel[lab]['final']}")

    all_cands = cands + comparators
    dev_rows = ctx.rows(dev) & ctx.issued
    # final (adapted) inner-OOF predictions of every assessed (pipeline, mode)
    oof_final: dict[tuple[str, str], tuple] = {}
    for c in all_cands:
        for mname, mode in modes_for(ctx, c.label, adapt_sel).items():
            oof_final[(c.label, mname)] = run_mode(ctx, dev_rows, c.oof, mode)

    # warning thresholds (5-minute event track): exact final pipelines, inner OOF only
    warn: dict[str, Any] = {}
    if ctx.proto["tracks"][ctx.track].get("events"):
        w = ctx.proto["warnings"]
        targets = {"persistence:-": "off", "linear_trend:-": "off"}
        for lab in adapt_labels:
            targets[lab] = "final"
        for c in comparators:
            targets[c.label] = "v2_policy"
        for lab, mname in targets.items():
            final = oof_final[(lab, mname)][0]
            for H in w["horizons_minutes"]:
                rows = warnings.curve(ctx.t, dev_rows, ctx.issued, final, int(H), [float(x) for x in w["threshold_grid"]],
                                      float(w["episode_merge_minutes"]), ctx.td.cadence)
                prim, prim_why = warnings.select_workload(rows, float(w["workload_budget_per_observed_day"]))
                sens = {str(b): warnings.select_workload(rows, float(b)) for b in w["sensitivity_budgets"]}
                f1, f1_why = warnings.select_f1(rows)
                warn[f"{lab}|{mname}|{H}"] = {
                    "pipeline": lab, "mode": mname, "horizon": int(H), "curve": rows,
                    "primary": {"threshold": prim, "why": prim_why},
                    "sensitivity": {b: {"threshold": t, "why": y} for b, (t, y) in sens.items()},
                    "f1_comparator": {"threshold": f1, "why": f1_why}}
                if lab.startswith("v2_recipe"):
                    warn[f"{lab}|{mname}|{H}"]["v2_fixed_threshold"] = v2_recipe()["threshold"]

    # refit on all development participants, then freeze
    bundles: dict[str, dict] = {}
    for c in all_cands:
        b, info = refit(ctx, c, dev)
        bdir = out / "bundles" / c.label.replace(":", "__")
        man = b.save(bdir, extra={"research": {"experiment_id": ctx.experiment_id, "fold": plan.fold, "track": ctx.track,
                                               "development_participants": dev}})
        bundles[c.label] = {"dir": str(bdir.relative_to(research_dir(ctx.experiment_id))),
                            "hash": fingerprint(man["files"]), "params": {str(h): b.params[h] for h in ctx.horizons},
                            "family": b.family, "feature_set": c.fs, "config": c.config}

    # calibration participants: frozen pipelines run causally from an empty state
    cal_rows = ctx.rows(plan.calibration) & ctx.issued
    icfg = ctx.proto["intervals"]
    a = ctx.proto["adaptation"]
    cls_cfg = {"half_life": 720.0, "k_s": 24.0, "min_residuals": int(a["min_residuals"]),
               "reset_gap": float(a["reset_gap_minutes"])}
    cal_out, cal_pred_frames = {}, []
    for c in all_cands:
        b = PopulationBundle.load(research_dir(ctx.experiment_id) / bundles[c.label]["dir"])
        pop = {h: np.where(cal_rows, p, np.nan) for h, p in b.predict(ctx.t).items()}
        for mname, mode in modes_for(ctx, c.label, adapt_sel).items():
            final, corr, _ = run_mode(ctx, cal_rows, pop, mode)
            ident = cal_identity(ctx, c.label, mname, mode, bundles[c.label]["hash"], plan.fold, c.fs)
            cal = calibration.calibrate(ctx.t, cal_rows, final, ctx.horizons, float(icfg["level"]), ctx.td.tolerance, cls_cfg, ident)
            cal_out[f"{c.label}|{mname}"] = cal
            for h in ctx.horizons:
                cal_pred_frames.append(pd.DataFrame({
                    "patient_id": ctx.pids[cal_rows], "origin": ctx.t["origin"].to_numpy()[cal_rows], "horizon": h,
                    "pipeline": c.label, "mode": mname, "population": pop[h][cal_rows], "correction": corr[h][cal_rows],
                    "final": final[h][cal_rows], "target": ctx.target(h)[cal_rows]}))

    # inner OOF predictions (development partition) for the record
    frames = []
    for (lab, mname), (final, corr, nres) in oof_final.items():
        pop = next(c for c in all_cands if c.label == lab).oof
        for h in ctx.horizons:
            m = dev_rows & np.isfinite(pop[h])
            frames.append(pd.DataFrame({
                "patient_id": ctx.pids[m], "dataset_id": ctx.td.dataset_id,
                "recording_id": ctx.t["recording_id"].to_numpy()[m], "origin": ctx.t["origin"].to_numpy()[m],
                "horizon": h, "pipeline": lab, "mode": mname, "population": pop[h][m], "correction": corr[h][m],
                "final": final[h][m], "residuals_matured": nres[h][m], "target": ctx.target(h)[m],
                "target_at": ctx.t[f"target_{h}_at"].to_numpy()[m], "partition": "inner_oof"}))
    pd.concat(frames, ignore_index=True).to_parquet(out / "inner_oof.parquet", index=False)
    pd.concat(cal_pred_frames, ignore_index=True).to_parquet(out / "calibration_predictions.parquet", index=False)
    (out / "search_trace.json").write_text(json.dumps({c.label: {"params": c.params, "trace": c.trace} for c in all_cands},
                                                      indent=1, default=_jd))
    pipeline = {
        "experiment_id": ctx.experiment_id, "fold": plan.fold, "track": ctx.track,
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "plan": plan.as_dict(), "table_cache_key": ctx.td.meta["cache_key"],
        "selection": {"rows": sel_rows, "selected": chosen.label, "rationale": why,
                      "rule": ctx.proto["selection"]["score"]},
        "adaptation": adapt_sel, "warnings": warn, "bundles": bundles, "calibration": cal_out,
        "modes": {c.label: modes_for(ctx, c.label, adapt_sel) for c in all_cands},
        "timings_seconds": {**timings, "total": time.perf_counter() - t0},
    }
    pipeline["freeze_hash_version"] = 2
    pipeline["freeze_hash"] = pipeline_freeze_hash(pipeline)
    (out / "pipeline.json").write_text(json.dumps(pipeline, indent=1, default=_jd))
    log(f"[{plan.fold}/{ctx.track}] frozen in {time.perf_counter() - t0:.1f}s ({pipeline['freeze_hash']})")
    return pipeline


def _jd(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)
