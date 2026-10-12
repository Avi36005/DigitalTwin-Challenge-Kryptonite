"""Research report built ONLY from saved records (``glucotwin research report``).

Every headline number is recomputed here from ``assessment/predictions.parquet``, ``assessment/events.json``,
``external/predictions.parquet`` and the frozen fold pipelines — never copied from a log. Outputs:

* ``artifacts/research/<id>/report.json``   payload served by the API (``/api/v1/evaluations/<id>``)
* ``reports/nested_benchmark_report.md``    full research report
* ``reports/model_upgrade_review.md``       judge-facing review + candidate handoff
* ``reports/figures/*.png``                 warning trade-off and coverage figures from saved threshold records
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import paths
from glucotwin.research import metrics as M
from glucotwin.research.protocol import FINAL, load_frozen, load_protocol, plans_of, research_dir

TRACK_NAMES = {"multimodal_5min": "5-minute multimodal track (CGMacros)",
               "portable_15min": "15-minute portable CGM-only track"}
CONFIG_NAMES = {"persistence": "Persistence", "linear_trend": "Linear trend", "ridge": "Ridge",
                "lightgbm_l2": "LightGBM (L2 objective, L2 stopping)", "lightgbm_l1": "LightGBM (L1 objective, macro-MAE stopping)",
                "catboost": "CatBoost (RMSE)", "v2_recipe": "Current v2 serving recipe (refit per fold)"}
MODE_NAMES = {"off": "population only", "v2_policy": "v2 adaptation policy", "best_grid": "best grid adaptation",
              "frozen_state": "adaptation frozen after 24 h", "final": "selected personalization"}


def _r(x, nd=2):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)


def _pipelines(experiment_id: str, track: str) -> dict[str, dict]:
    doc = load_frozen(experiment_id)
    out = {}
    for p in plans_of(doc):
        path = research_dir(experiment_id) / "development" / p.fold / track / "pipeline.json"
        if path.exists():
            out[p.fold] = json.loads(path.read_text())
    return out


def pseudo_map(pls: dict[str, dict]) -> dict[str, dict[str, str]]:
    """fold -> pseudo pipeline name -> concrete label for per-fold choices (selected / best per tree config)."""
    out = {}
    for fold, pl in pls.items():
        m = {"selected": pl["selection"]["selected"]}
        for lab in pl["adaptation"]:
            cfg = lab.split(":")[0]
            if cfg in ("lightgbm_l2", "lightgbm_l1", "catboost"):
                m[f"best:{cfg}"] = lab
        out[fold] = m
    return out


def resolve(preds: pd.DataFrame, pmap: dict[str, dict[str, str]], name: str, mode: str) -> pd.DataFrame:
    """Rows of a fixed pipeline label, or of a per-fold pseudo pipeline ('selected', 'best:<config>')."""
    if name in ("selected",) or name.startswith("best:"):
        parts = []
        for fold, m in pmap.items():
            if fold == FINAL or name not in m:
                continue
            parts.append(preds[(preds["fold"] == fold) & (preds["pipeline"] == m[name]) & (preds["mode"] == mode)])
        return pd.concat(parts) if parts else preds.iloc[0:0]
    return preds[(preds["pipeline"] == name) & (preds["mode"] == mode)]


def forecast_row(df: pd.DataFrame, h: int, total_target_rows: int) -> dict[str, Any]:
    d = df[df["horizon"] == h]
    scored = d[(d["quality"] != "insufficient") & np.isfinite(d["target"]) & np.isfinite(d["final"])]
    pids = scored["patient_id"].to_numpy()
    err = np.abs(scored["final"].to_numpy() - scored["target"].to_numpy())
    mae = pd.Series(err).groupby(pids).mean()
    rmse = np.sqrt(pd.Series(err ** 2).groupby(pids).mean())
    hi = scored["target"].to_numpy() > 180
    hi_s = pd.Series(err[hi]).groupby(pids[hi]).agg(["mean", "size"])
    hi_s = hi_s[hi_s["size"] >= 20]
    cold = {}
    for name, lo, up in (("first_6h", 0, 360), ("6_to_24h", 360, 1440), ("after_24h", 1440, np.inf)):
        sel = (scored["elapsed_min"].to_numpy() >= lo) & (scored["elapsed_min"].to_numpy() < up)
        s = pd.Series(err[sel]).groupby(pids[sel]).mean()
        cold[name] = {"mae_macro": _r(M.macro(s)), "participants": int(s.size), "origins": int(sel.sum())}
    target_rows = d[np.isfinite(d["target"])]
    return {"horizon": h, "mae": _r(M.macro(mae), 3), "rmse": _r(M.macro(rmse), 3),
            "mae_high_glucose_target": _r(M.macro(hi_s["mean"]) if len(hi_s) else None, 3),
            "high_glucose_participants": int(len(hi_s)), "n_participants": int(mae.size),
            "n_origins": int(len(scored)), "availability": _r(len(scored) / max(1, len(target_rows)), 4),
            "per_participant_mae": {k: round(float(v), 3) for k, v in mae.items()},
            "cold_start": cold, "unavailable_forecasts": int(len(target_rows) - len(scored))}


def per_participant_high(df: pd.DataFrame, h: int, min_n: int = 20) -> pd.Series:
    """Per-person MAE on forecasts whose observed target exceeded 180 mg/dL (people with >= ``min_n`` such forecasts)."""
    d = df[(df["horizon"] == h) & (df["quality"] != "insufficient") & np.isfinite(df["target"]) & np.isfinite(df["final"])
           & (df["target"] > 180)]
    g = pd.Series(np.abs(d["final"].to_numpy() - d["target"].to_numpy())).groupby(d["patient_id"].to_numpy())
    s = g.mean()
    return s[g.size() >= min_n]


def per_participant_series(df: pd.DataFrame, h: int) -> pd.Series:
    d = df[(df["horizon"] == h) & (df["quality"] != "insufficient") & np.isfinite(df["target"]) & np.isfinite(df["final"])]
    return pd.Series(np.abs(d["final"].to_numpy() - d["target"].to_numpy())).groupby(d["patient_id"].to_numpy()).mean()


def interval_rows(df: pd.DataFrame, h: int, proto: dict) -> dict[str, Any]:
    d = df[(df["horizon"] == h) & (df["quality"] != "insufficient") & np.isfinite(df["target"]) & np.isfinite(df["final"])]
    icfg = proto["intervals"]
    out = {}
    for meth in ("global", "cls"):
        s = M.interval_summary(d[f"lower_{meth}"].to_numpy(float), d[f"upper_{meth}"].to_numpy(float),
                               d["target"].to_numpy(float), d["patient_id"].to_numpy(), d["g_last"].to_numpy(float),
                               float(icfg["interval_score_alpha"]), icfg["glucose_strata_mg_dl"],
                               int(icfg["min_stratum_observations"]), int(icfg["min_stratum_participants"]))
        cold = {}
        for name, lo, up in (("first_6h", 0, 360), ("6_to_24h", 360, 1440), ("after_24h", 1440, np.inf)):
            sel = (d["elapsed_min"].to_numpy() >= lo) & (d["elapsed_min"].to_numpy() < up) & np.isfinite(d[f"lower_{meth}"].to_numpy(float))
            ins = (d["target"].to_numpy()[sel] >= d[f"lower_{meth}"].to_numpy()[sel]) & \
                  (d["target"].to_numpy()[sel] <= d[f"upper_{meth}"].to_numpy()[sel])
            cold[name] = {"coverage": _r(ins.mean(), 4) if sel.sum() >= int(icfg["min_stratum_observations"]) else None,
                          "n": int(sel.sum())}
        s["by_elapsed_history"] = cold
        if meth == "cls":
            s["fallback_rate"] = _r(float(d["cls_fallback"].mean()), 4) if len(d) else None
        out[meth] = s
    return out


def _agg_events(rows: list[dict], nboot: int, seed: int) -> dict[str, Any]:
    ok = [r for r in rows if r.get("status") == "ok"]
    if not ok:
        return {"status": "no_feasible_threshold", "folds_without_threshold": len(rows)}
    per: dict[str, dict] = {}
    for r in ok:
        for pid, v in r["_per_participant"].items():
            per[pid] = v
    tot = defaultdict(float)
    for v in per.values():
        for k, x in v.items():
            tot[k] += x
    recall = tot["detected"] / tot["onsets"] if tot["onsets"] else None
    precision = tot["matched"] / (tot["matched"] + tot["false_alarms"]) if (tot["matched"] + tot["false_alarms"]) else None
    obs_days, elig_days = tot["observed_min"] / 1440.0, tot["eligible_min"] / 1440.0
    ql = [x for r in ok for x in r["_qualified_leads"]]
    el = [x for r in ok for x in r["_episode_start_leads"]]
    pids = sorted(per)
    rng = np.random.default_rng(seed)
    rec_b, fa_b = [], []
    arr = np.array([[per[p]["onsets"], per[p]["detected"], per[p]["false_alarms"], per[p]["observed_min"]] for p in pids])
    for _ in range(nboot):
        s = arr[rng.integers(0, len(pids), len(pids))].sum(axis=0)
        if s[0] > 0:
            rec_b.append(s[1] / s[0])
        if s[3] > 0:
            fa_b.append(s[2] / (s[3] / 1440.0))
    return {
        "status": "ok", "folds": len(ok), "folds_without_threshold": len(rows) - len(ok),
        "thresholds_by_fold": {r["fold"]: r["threshold"] for r in rows},
        "true_onsets": int(tot["onsets"]), "detected_onsets": int(tot["detected"]),
        "missed_onsets": int(tot["onsets"] - tot["detected"]), "warning_episodes": int(tot["episodes"]),
        "assessable_warnings": int(tot["episodes"] - tot["censored"]), "matched_warnings": int(tot["matched"]),
        "false_alarms": int(tot["false_alarms"]), "censored_warnings": int(tot["censored"]),
        "recall": _r(recall, 4), "precision": _r(precision, 4),
        "f1": _r(2 * precision * recall / (precision + recall), 4) if recall and precision else None,
        "observed_forecastable_days": _r(obs_days, 2), "eligible_uncensored_days": _r(elig_days, 2),
        "false_alarms_per_observed_day": _r(tot["false_alarms"] / obs_days, 3) if obs_days else None,
        "false_alarms_per_eligible_day": _r(tot["false_alarms"] / elig_days, 3) if elig_days else None,
        "warnings_per_observed_day": _r(tot["episodes"] / obs_days, 3) if obs_days else None,
        "warnings_per_eligible_day": _r(tot["episodes"] / elig_days, 3) if elig_days else None,
        "recall_ci95": [_r(np.percentile(rec_b, 2.5), 3), _r(np.percentile(rec_b, 97.5), 3)] if rec_b else [None, None],
        "false_alarms_per_observed_day_ci95": [_r(np.percentile(fa_b, 2.5), 3), _r(np.percentile(fa_b, 97.5), 3)]
        if fa_b else [None, None],
        "qualified_lead_median": _r(np.median(ql), 1) if ql else None,
        "qualified_lead_iqr": [_r(np.percentile(ql, 25), 1), _r(np.percentile(ql, 75), 1)] if ql else [None, None],
        "qualified_lead_n": len(ql), "qualified_lead_max": _r(max(ql), 1) if ql else None,
        "episode_start_to_onset_median": _r(np.median(el), 1) if el else None,
        "episode_start_to_onset_iqr": [_r(np.percentile(el, 25), 1), _r(np.percentile(el, 75), 1)] if el else [None, None],
        "participants": len(pids), "participants_with_onsets": int(sum(1 for p in pids if per[p]["onsets"] > 0)),
        "participant_uncertainty": "participant-cluster bootstrap of pooled counts",
    }


def build(experiment_id: str) -> dict[str, Any]:
    proto = load_protocol(experiment_id)
    doc = load_frozen(experiment_id)
    root = research_dir(experiment_id)
    nboot, seed = int(proto["evaluation"]["bootstrap_resamples"]), int(proto["random_seed"])
    horizons = [int(h) for h in proto["horizons_minutes"]]
    ap = root / "assessment" / "predictions.parquet"
    if not ap.exists():
        return {"experiment_id": experiment_id, "status": "not_run",
                "status_message": "Development may be frozen, but the outer-fold assessment has not been run."}
    preds = pd.read_parquet(ap)
    ev_doc = json.loads((root / "assessment" / "events.json").read_text())
    summary = json.loads((root / "assessment" / "summary.json").read_text())
    rep: dict[str, Any] = {
        "schema_version": "1.0", "experiment_id": experiment_id, "status": "completed",
        "kind": "nested-participant-benchmark", "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "declared_on": proto["declared_on"], "frozen_at": doc["frozen_at"], "protocol_hash": doc["protocol_hash"],
        "split_hash": doc["split_hash"], "assessment_opened": summary["opened"],
        "inspection_log": proto["inspection_log"], "tracks": {}, "folds": [],
        "status_message": ("Internal nested participant-level evaluation of CGMacros (14 people already inspected in "
                           "v1/v2: internal validation, not untouched evidence)"),
    }
    for p in plans_of(doc):
        rep["folds"].append({"fold": p.fold, "assessment": len(p.assessment), "calibration": len(p.calibration),
                             "development": len(p.development), "inner_folds": [len(f) for f in p.inner]})
    for track in ("multimodal_5min", "portable_15min"):
        pls = _pipelines(experiment_id, track)
        pmap = pseudo_map(pls)
        tp = preds[preds["track"] == track]
        sel_by_fold = {f: {"selected": pl["selection"]["selected"], "rationale": pl["selection"]["rationale"],
                           "adaptation": pl["adaptation"].get(pl["selection"]["selected"], {}).get("final"),
                           "grid_adopted": pl["adaptation"].get(pl["selection"]["selected"], {}).get("grid_adopted"),
                           "inner_scores": pl["selection"]["rows"]} for f, pl in pls.items()}
        pipelines = []
        names = sorted({(r.pipeline, r.mode) for r in tp[["pipeline", "mode"]].drop_duplicates().itertuples()})
        names = [n for n in names if n[1] == "off" or n[0].startswith("v2_recipe")] + \
                [("selected", m) for m in ("off", "v2_policy", "best_grid", "frozen_state", "final")] + \
                [(f"best:{c}", m) for c in ("lightgbm_l2", "lightgbm_l1", "catboost") for m in ("off", "final")]
        lat = summary.get("inference_ms_per_1k", {})
        for name, mode in names:
            df = resolve(tp, pmap, name, mode)
            if df.empty:
                continue
            cfg = name.split(":")[0] if not name.startswith(("selected", "best:")) else name
            row = {"pipeline": name, "mode": mode, "config": cfg,
                   "feature_set": name.split(":")[1] if ":" in name and not name.startswith("best:") else None,
                   "display": _display(name, mode), "horizons": {}, "intervals": {}}
            for h in horizons:
                row["horizons"][str(h)] = forecast_row(df, h, 0)
                row["intervals"][str(h)] = interval_rows(df, h, proto)
            ms = [v.get(name) for k, v in lat.items() if k.startswith(track) and v.get(name) is not None]
            row["inference_ms_per_1k"] = _r(float(np.median(ms)), 3) if ms else None
            pipelines.append(row)
        comps = []

        def cmp(title, a, b, kind="internal", dfp=tp, pm=pmap, out=comps):
            da, db = resolve(dfp, pm, *a), resolve(dfp, pm, *b)
            if da.empty or db.empty:
                return
            for h in horizons:
                r = M.paired_bootstrap(per_participant_series(da, h), per_participant_series(db, h), nboot, seed + h)
                out.append({"comparison": title, "kind": kind, "horizon": h, "a": list(a), "b": list(b),
                              **{k: (_r(v, 3) if isinstance(v, float) else v) for k, v in r.items()},
                              "ci95": [_r(x, 3) for x in r["ci95"]]})

        fsets = proto["tracks"][track]["feature_sets"]
        cmp("Selected pipeline minus persistence", ("selected", "final"), ("persistence:-", "off"))
        cmp("Selected pipeline: personalization minus population only", ("selected", "final"), ("selected", "off"))
        cmp("Selected pipeline: best grid adaptation minus v2 policy", ("selected", "best_grid"), ("selected", "v2_policy"))
        if track == "multimodal_5min":
            cmp("Selected pipeline minus current v2 recipe", ("selected", "final"), ("v2_recipe:dyn-v2", "v2_policy"))
            da, db = resolve(tp, pmap, "selected", "final"), resolve(tp, pmap, "v2_recipe:dyn-v2", "v2_policy")
            for h in horizons:
                r = M.paired_bootstrap(per_participant_high(da, h), per_participant_high(db, h), nboot, seed + 50 + h)
                comps.append({"comparison": "High-glucose error (target > 180): selected minus current v2 recipe",
                              "kind": "internal", "horizon": h, "a": ["selected", "final"],
                              "b": ["v2_recipe:dyn-v2", "v2_policy"],
                              **{k: (_r(v, 3) if isinstance(v, float) else v) for k, v in r.items()},
                              "ci95": [_r(x, 3) for x in r["ci95"]]})
            cmp("Activity inputs: LightGBM L2 dyn-v2 minus CGM-only", ("lightgbm_l2:dyn-v2", "off"),
                ("lightgbm_l2:cgm-only-v1", "off"))
            cmp("Profile inputs: LightGBM L2 dyn-prof-v2 minus dyn-v2", ("lightgbm_l2:dyn-prof-v2", "off"),
                ("lightgbm_l2:dyn-v2", "off"))
        for fs in fsets:
            cmp(f"L1 objective + macro-MAE stopping minus L2 ({fs}, population)", (f"lightgbm_l1:{fs}", "off"),
                (f"lightgbm_l2:{fs}", "off"))
            cmp(f"CatBoost minus LightGBM L2 ({fs}, population)", (f"catboost:{fs}", "off"), (f"lightgbm_l2:{fs}", "off"))
        cmp("Best CatBoost minus best LightGBM L2 (each with its selected personalization)", ("best:catboost", "final"),
            ("best:lightgbm_l2", "final"))
        cmp("Best LightGBM L1 minus best LightGBM L2 (each with its selected personalization)", ("best:lightgbm_l1", "final"),
            ("best:lightgbm_l2", "final"))
        trep: dict[str, Any] = {"name": TRACK_NAMES[track], "selection_by_fold": sel_by_fold, "pipelines": pipelines,
                                "comparisons": comps, "participants": int(tp["patient_id"].nunique())}
        if proto["tracks"][track].get("events"):
            trep["warnings"] = _warnings(ev_doc, track, pmap, proto, nboot, seed)
        rep["tracks"][track] = trep
    rep["external"] = _external(experiment_id, proto, nboot, seed, horizons)
    rep["candidates"] = _candidates(experiment_id)
    rep["data"] = _data_summary(doc)
    rep["limitations"] = LIMITATIONS
    return rep


def _display(name: str, mode: str) -> str:
    if name == "selected":
        base = "Selected by the declared rule (per fold)"
    elif name.startswith("best:"):
        base = f"Best {CONFIG_NAMES[name.split(':')[1]]} (per fold)"
    else:
        cfg, fs = name.split(":")
        base = CONFIG_NAMES.get(cfg, cfg) + ("" if fs == "-" else f", {fs}")
    return f"{base} — {MODE_NAMES.get(mode, mode)}"


def _warnings(ev_doc: dict, track: str, pmap: dict, proto: dict, nboot: int, seed: int) -> dict[str, Any]:
    rows = [e for e in ev_doc["events"] if e["track"] == track]
    out = {"policies": [], "curves": []}
    w = proto["warnings"]

    def pick(name, mode):
        out_rows = []
        for r in rows:
            lab = pmap.get(r["fold"], {}).get(name) if (name == "selected" or name.startswith("best:")) else name
            if r["pipeline"] == lab and r["mode"] == mode:
                out_rows.append(r)
        return out_rows

    targets = [("persistence:-", "off"), ("linear_trend:-", "off"), ("selected", "final"),
               ("best:lightgbm_l2", "final"), ("best:lightgbm_l1", "final"), ("best:catboost", "final"),
               ("v2_recipe:dyn-v2", "v2_policy")]
    for name, mode in targets:
        sub = pick(name, mode)
        if not sub:
            continue
        for H in w["horizons_minutes"]:
            hs = [r for r in sub if r["horizon"] == int(H)]
            pols = ["primary", "f1_comparator", *[f"budget_{b}" for b in w["sensitivity_budgets"]]]
            if name.startswith("v2_recipe"):
                pols.append("v2_fixed")
            for pol in pols:
                pr = [r for r in hs if r["policy"] == pol]
                if pr:
                    out["policies"].append({"pipeline": name, "mode": mode, "display": _display(name, mode),
                                            "horizon": int(H), "policy": pol,
                                            **_agg_events(pr, nboot, seed + int(H))})
            for th in w["threshold_grid"]:
                pr = [r for r in hs if r["policy"] == f"grid_{th}"]
                if pr:
                    a = _agg_events(pr, 0, seed)
                    out["curves"].append({"pipeline": name, "mode": mode, "horizon": int(H), "threshold": float(th),
                                          "recall": a.get("recall"), "precision": a.get("precision"),
                                          "false_alarms_per_observed_day": a.get("false_alarms_per_observed_day"),
                                          "warning_episodes": a.get("warning_episodes"),
                                          "missed_onsets": a.get("missed_onsets")})
    return out


def _external(experiment_id: str, proto: dict, nboot: int, seed: int, horizons: list[int]) -> dict[str, Any]:
    root = research_dir(experiment_id) / "external"
    path = root / "predictions.parquet"
    if not path.exists():
        return {"status": "not_run", "reason": "The reserved external assessment has not been opened."}
    df = pd.read_parquet(path)
    summ = json.loads((root / "summary.json").read_text())
    pl = json.loads((research_dir(experiment_id) / "development" / FINAL / "portable_15min" / "pipeline.json").read_text())
    sel = pl["selection"]["selected"]
    pipes = []
    for (lab, mode), d in df.groupby(["pipeline", "mode"]):
        if mode not in ("off", "final", "v2_policy", "best_grid", "frozen_state"):
            continue
        row = {"pipeline": lab, "mode": mode, "display": _display(lab, mode), "selected": lab == sel,
               "horizons": {str(h): forecast_row(d, h, 0) for h in horizons},
               "intervals": {str(h): interval_rows(d, h, proto) for h in horizons}}
        pipes.append(row)
    comps = []
    for title, a, b in (("Selected candidate minus persistence", (sel, "final"), ("persistence:-", "off")),
                        ("Selected candidate minus linear trend", (sel, "final"), ("linear_trend:-", "off")),
                        ("Selected candidate: personalization minus population only", (sel, "final"), (sel, "off"))):
        da = df[(df["pipeline"] == a[0]) & (df["mode"] == a[1])]
        db = df[(df["pipeline"] == b[0]) & (df["mode"] == b[1])]
        if da.empty or db.empty:
            continue
        for h in horizons:
            r = M.paired_bootstrap(per_participant_series(da, h), per_participant_series(db, h), nboot, seed + 100 + h)
            comps.append({"comparison": title, "horizon": h, **{k: (_r(v, 3) if isinstance(v, float) else v)
                                                               for k, v in r.items()}, "ci95": [_r(x, 3) for x in r["ci95"]]})
    return {"status": "completed", "dataset": "ShanghaiT2DM (figshare 21600933 v5)", "opened": summ["opened"],
            "candidate": sel, "candidate_freeze_hash": summ["candidate_freeze_hash"],
            "participants": summ["participants"], "decimation": summ.get("decimation"),
            "pipelines": pipes, "comparisons": comps,
            "note": "Opened once after the portable candidate was frozen; never used for any choice."}


def _candidates(experiment_id: str) -> dict[str, Any]:
    out = {}
    for track in ("multimodal_5min", "portable_15min"):
        d = research_dir(experiment_id) / "candidates" / track
        if (d / "candidate.json").exists():
            c = json.loads((d / "candidate.json").read_text())
            s = json.loads((d / "serving.json").read_text())
            par = json.loads((d / "parity.json").read_text()) if (d / "parity.json").exists() else None
            out[track] = {"candidate": c, "adaptation": s["adaptation"], "intervals": s["intervals"],
                          "alerts": s.get("alerts"), "parity": par, "status": s["status"]}
    return out


def _data_summary(doc: dict) -> dict[str, Any]:
    inv = paths().reports / "dataset_inventory.json"
    d = json.loads(inv.read_text()) if inv.exists() else {}
    return {"counts_by_dataset": doc.get("counts_by_dataset"), "inventory_generated_at": d.get("generated_at"),
            "overlap_check": doc.get("overlap_check")}


LIMITATIONS = [
    "CGMacros (14 people with Type 2 diabetes) was already inspected in v1/v2; its nested resampling is internal "
    "validation, not an untouched or independent clinical evaluation.",
    "Outer assessment groups hold 2-3 people; per-fold results are noisy and few-event folds are reported as such.",
    "ShanghaiT2DM differs in country, device (FreeStyle Libre H, 15-minute), care setting (registry including "
    "inpatients with insulin) and cadence; the portable track uses CGM only and no event metric is defined for it.",
    "Real-time availability is a replay assumption for both datasets (zero latency).",
    "Prediction ranges come from split-conformal calibration under serial dependence and participant shift; empirical "
    "coverage is a measured result, not a guarantee.",
    "Warning scores are uncalibrated forecast margins; workload budgets are engineering choices, not clinical standards.",
    "No Indian participants were evaluated; nothing here supports clinical use or treatment decisions.",
    "AI-READI was not accessed; no result here uses it.",
]


def write_reports(experiment_id: str) -> dict[str, Any]:
    rep = build(experiment_id)
    root = research_dir(experiment_id)
    (root / "report.json").write_text(json.dumps(rep, indent=1, default=_jd))
    if rep.get("status") != "completed":
        return {"status": rep.get("status"), "message": rep.get("status_message")}
    from glucotwin.research.render import figures, render_report, render_review, update_model_card

    figs = figures(rep)
    update_model_card(rep)
    (paths().reports / "nested_benchmark_report.md").write_text(render_report(rep, figs))
    (paths().reports / "model_upgrade_review.md").write_text(render_review(rep, figs))
    return {"report_json": str(root / "report.json"), "markdown": ["reports/nested_benchmark_report.md",
                                                                   "reports/model_upgrade_review.md"], "figures": figs}


def _jd(o):
    from glucotwin.research.develop import _jd as j
    return j(o)


def strip_private(obj: Any) -> Any:
    """Drop per-participant raw material (keys starting with '_') before serving."""
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [strip_private(v) for v in obj]
    return obj


def load_report(experiment_id: str) -> dict[str, Any] | None:
    p = research_dir(experiment_id) / "report.json"
    return json.loads(p.read_text()) if p.exists() else None


__all__ = ["build", "write_reports", "load_report", "strip_private", "Path"]
