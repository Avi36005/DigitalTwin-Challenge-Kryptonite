"""LightGBM-CatBoost population blend for the fusion feature set (protocol configs/experiments/gt-blend-2026-10-21.yaml,
decision D-048).

A re-analysis of the saved population predictions of gt-2h-2026-10-20 (`lightgbm_l2:dyn-prof-v2` and
`catboost:dyn-prof-v2`, mode off): a fixed alpha grid blends them, the declared past-only patient update (v2 policy)
is applied once to the blended population forecast, and alpha is chosen on development inner out-of-fold predictions
only. Stages, run in this order:

  --analyse   development error analysis of the matched incumbent only (alpha = 1); no blend is scored
  --develop   development selection on inner out-of-fold predictions (refused until the protocol is recorded)
  --assess    the declared outer-fold assessment, once, behind a lock file (refused unless --develop met the target)
  --render    rewrite the report from the saved JSON files

Usage:  uv run python scripts/blend_experiment.py --analyse | --develop | --assess [--reopen-reason TEXT] | --render
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from glucotwin.research import adapt
from glucotwin.research import metrics as M
from glucotwin.research import warnings as W
from glucotwin.research.calibration import finite_sample_quantile
from glucotwin.research.common import load_ctx
from glucotwin.research.protocol import FINAL, load_frozen, plans_of, research_dir

ROOT = Path(__file__).resolve().parents[1]
EXP = "gt-blend-2026-10-21"
PROTO_PATH = ROOT / "configs/experiments" / f"{EXP}.yaml"
BASE = "gt-2h-2026-10-20"
TRACK = "multimodal_5min"
LGB, CAT = "lightgbm_l2:dyn-prof-v2", "catboost:dyn-prof-v2"
HS = [30, 60, 120]
OUT = ROOT / "artifacts/research" / EXP
REPORT = ROOT / "reports/blend_experiment.md"
NBOOT, CAD = 2000, 5.0
HIGH_MIN_ORIGINS = 30


# ------------------------------------------------------------------------------------------------ shared helpers


class Data:
    """The frozen research table of gt-2h-2026-10-20 with the saved population predictions aligned to its rows."""

    def __init__(self) -> None:
        self.ctx = load_ctx(TRACK, "development", BASE)
        self.t = self.ctx.t
        self.pids = self.ctx.pids
        self.issued = self.ctx.issued
        a = self.ctx.proto["adaptation"]["v2_policy"]
        self.policy = adapt.make_policy(self.ctx.proto, TRACK, float(a["shrinkage_k"]), float(a["half_life_minutes"]))
        self.plans = {p.fold: p for p in plans_of(load_frozen(BASE))}
        self.root = research_dir(BASE)
        key = json.loads((self.root / "tables" / f"{TRACK}__cgmacros.json").read_text())["cache_key"]
        for f in self.plans:
            pl = json.loads((self.root / "development" / f / TRACK / "pipeline.json").read_text())
            if pl["table_cache_key"] != key:
                sys.exit(f"{f}: cached table differs from the one frozen with the pipeline; refusing to run.")

    def align(self, d: pd.DataFrame, col: str = "population") -> dict[int, np.ndarray]:
        out = {}
        for h in HS:
            m = self.t[["patient_id", "origin"]].merge(d.loc[d["horizon"] == h, ["patient_id", "origin", col]], how="left",
                                                       on=["patient_id", "origin"], validate="one_to_one")
            out[h] = m[col].to_numpy(float)
        return out

    def saved(self, fold: str, kind: str) -> dict[str, dict[int, np.ndarray]]:
        """Population (mode off) predictions of both families: kind = inner | calibration | assessment."""
        if kind == "assessment":
            d = pd.read_parquet(self.root / "assessment" / "predictions.parquet")
            d = d[(d["track"] == TRACK) & (d["fold"] == fold)]
        else:
            name = "inner_oof.parquet" if kind == "inner" else "calibration_predictions.parquet"
            d = pd.read_parquet(self.root / "development" / fold / TRACK / name)
        d = d[d["mode"] == "off"]
        out = {}
        for lab in (LGB, CAT):
            x = d[d["pipeline"] == lab]
            if x.empty:
                sys.exit(f"{fold}: no saved {kind} predictions for {lab}")
            out[lab] = self.align(x)
        return out

    def final(self, rows: np.ndarray, pop: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
        """The declared past-only patient update (v2 policy) applied once to a population forecast on ``rows``."""
        pop = {h: np.where(rows, pop[h], np.nan) for h in HS}
        corr, _ = adapt.prequential(self.t, self.ctx.td.prep, rows & self.issued, pop, self.policy, HS)
        return {h: np.where(rows, v, np.nan) for h, v in adapt.apply(pop, corr).items()}

    def target(self, h: int) -> np.ndarray:
        return self.ctx.target(h)


def blend(alpha: float, p: dict[str, dict[int, np.ndarray]]) -> dict[int, np.ndarray]:
    """alpha * LightGBM + (1 - alpha) * CatBoost; alpha = 1 is the LightGBM incumbent, alpha = 0 CatBoost alone."""
    return {h: alpha * p[LGB][h] + (1.0 - alpha) * p[CAT][h] for h in HS}


def scores(D: Data, pred: dict[int, np.ndarray], people: list[str]) -> dict:
    """Macro per-participant MAE by horizon, high-glucose MAE at 60 min, availability."""
    out = {}
    for h in HS:
        sc = D.ctx.scored(people, h)
        out[f"mae_{h}"] = M.macro(M.per_participant_mae(pred[h], D.target(h), D.pids, sc))
        out[f"availability_{h}"] = float(np.isfinite(pred[h][sc]).mean()) if sc.sum() else None
    sc = D.ctx.scored(people, 60) & (D.target(60) > 180)
    n = pd.Series(sc).groupby(D.pids).sum()
    elig = [p for p in people if n.get(p, 0) >= HIGH_MIN_ORIGINS]
    out["high_mae_60"] = M.macro(M.per_participant_mae(pred[60], D.target(60), D.pids, sc & np.isin(D.pids, elig)))
    out["high_people"] = len(elig)
    out["sel_score"] = float(np.mean([out["mae_30"], out["mae_60"]]))
    return out


def load_proto() -> dict:
    if not PROTO_PATH.exists() or not (OUT / "protocol_written.json").exists():
        sys.exit("The protocol and artifacts/research/gt-blend-2026-10-21/protocol_written.json must exist before any "
                 "blend is scored.")
    return yaml.safe_load(PROTO_PATH.read_text())


# ------------------------------------------------------------------------------------------------ stage 1: analysis


def analyse() -> dict:
    """Development (inner out-of-fold) errors of the matched incumbent, alpha = 1 only, on the final development set."""
    D = Data()
    p = D.plans[FINAL]
    dev = list(p.development)
    rows = np.isin(D.pids, dev)
    pop = D.saved(FINAL, "inner")[LGB]
    fin = D.final(rows, pop)
    t = D.t
    g = t["g_last"].to_numpy(float)
    slope = t["slope_15"].to_numpy(float)
    elapsed = t["elapsed_min"].to_numpy(float)
    deg = (t["quality"] == "degraded").to_numpy()
    act = t["act_cov_60"].to_numpy(float)
    prof_missing = t[["p_age", "p_sex_male", "p_bmi", "p_hba1c", "p_fasting_glucose", "p_fasting_insulin",
                      "p_triglycerides", "p_hdl"]].isna().any(axis=1).to_numpy()
    strata = {
        "all": np.ones(len(t), bool),
        "glucose < 70": g < 70, "glucose 70-180": (g >= 70) & (g <= 180), "glucose > 180": g > 180,
        "falling > 2 mg/dL/min": slope < -2, "falling 1-2": (slope >= -2) & (slope < -1),
        "steady (|slope| <= 1)": np.abs(slope) <= 1, "rising 1-2": (slope > 1) & (slope <= 2), "rising > 2": slope > 2,
        "first 24 h (cold start)": elapsed < 1440, "after 24 h": elapsed >= 1440,
        "degraded inputs": deg, "activity coverage < 0.5": act < 0.5, "profile value missing": prof_missing,
    }
    v2 = D.ctx.proto["adaptation"]["v2_policy"]
    res = {"policy": {"name": "v2_policy", "k": v2["shrinkage_k"], "half_life_minutes": v2["half_life_minutes"]},
           "development_people": len(dev), "strata": {}, "per_participant": {}}
    for name, m in strata.items():
        row = {}
        for h in HS:
            sc = D.ctx.scored(dev, h) & m
            s = M.per_participant_mae(fin[h], D.target(h), D.pids, sc)
            sp = M.per_participant_mae(pop[h], D.target(h), D.pids, sc)
            row[h] = {"macro_mae": M.macro(s), "population_macro_mae": M.macro(sp), "people": int(len(s)),
                      "origins": int((sc & np.isfinite(fin[h])).sum())}
        res["strata"][name] = row
    for h in HS:
        s = M.per_participant_mae(fin[h], D.target(h), D.pids, D.ctx.scored(dev, h))
        res["per_participant"][h] = {"min": float(s.min()), "median": float(s.median()), "max": float(s.max()),
                                     "spread_max_over_min": float(s.max() / s.min())}
    # signed bias in the high range (systematic under-forecast of peaks?)
    sc = D.ctx.scored(dev, 60) & (D.target(60) > 180)
    res["bias_60_target_above_180"] = float(np.nanmean((fin[60] - D.target(60))[sc]))
    sc = D.ctx.scored(dev, 60) & (D.target(60) < 70)
    res["bias_60_target_below_70"] = float(np.nanmean((fin[60] - D.target(60))[sc])) if sc.sum() else None
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "analysis.json").write_text(json.dumps(res, indent=1, default=str))
    return res


# ------------------------------------------------------------------------------------------------ stage 2: develop


def warn_eval(D: Data, rows: np.ndarray, fin: dict[int, np.ndarray], H: int, thr: float, merge: float) -> dict:
    sc = W.scores({h: fin[h] for h in HS if h <= H}, H)
    s, per = W.evaluate(D.t, rows, D.issued, sc, H, thr, merge, CAD)
    elig = D.t["ew_eligible"].to_numpy(bool)
    fire = rows & elig & D.issued & np.isfinite(sc) & (sc >= thr)
    base = rows & D.issued & elig
    leads = s["_qualified_leads"]
    return {"threshold": thr, "onsets": s["true_onsets"], "detected": s["detected_onsets"],
            "missed": s["true_onsets"] - s["detected_onsets"],
            "early_30": sum(1 for x in leads if x >= 30),
            "early_30_share_of_onsets": (sum(1 for x in leads if x >= 30) / s["true_onsets"]) if s["true_onsets"] else None,
            "false_alarms": s["false_alarm_episodes"], "fa_per_observed_day": s["false_alarms_per_observed_patient_day"],
            "observed_hours": s["observed_forecastable_hours"], "eligible_hours": s["eligible_uncensored_hours"],
            "episodes": s["warning_episodes"], "precision": s["precision"], "recall": s["recall"],
            "share_eligible_time_warning": int(fire.sum()) / int(base.sum()) if base.sum() else None,
            "lead_median": float(np.median(leads)) if leads else None,
            "lead_iqr": [float(np.percentile(leads, 25)), float(np.percentile(leads, 75))] if leads else None,
            "_per": {pid: {"onsets": v["onsets"], "detected": v["detected"], "false_alarms": v["false_alarms"],
                           "observed_min": v["observed_min"],
                           "early": sum(1 for x in per[pid].qualified_leads if x >= 30)}
                     for pid, v in s["_per_participant"].items()},
            "_leads": leads, "assessable": s["assessable_warnings"]}


def choose_alpha(rows_by_alpha: dict[float, dict], tie: float) -> float:
    best = min(r["sel_score"] for r in rows_by_alpha.values())
    tied = [a for a, r in rows_by_alpha.items() if r["sel_score"] <= best + tie]
    return max(tied)  # ties -> the larger alpha (closer to the LightGBM incumbent)


def develop() -> dict:
    proto = load_proto()
    alphas = [float(a) for a in proto["candidates"]["alpha_grid"]]
    tie = float(proto["selection"]["tie_mg_dl"])
    wcfg = proto["warnings"]
    grid = [float(x) for x in wcfg["threshold_grid"]]
    D = Data()
    res = {"folds": {}}
    for fold, p in D.plans.items():
        dev = list(p.development)
        rows = np.isin(D.pids, dev)
        saved = D.saved(fold, "inner")
        by_a, fins = {}, {}
        for a in alphas:
            fins[a] = D.final(rows, blend(a, saved))
            by_a[a] = scores(D, fins[a], dev)
        sel = choose_alpha(by_a, tie)
        out = {"development_people": len(dev), "alphas": by_a, "selected_alpha": sel}
        # warning threshold for the selected pipeline and the incumbent, inner OOF only (D-043 workload rule)
        for name, a in (("selected", sel), ("incumbent", 1.0)):
            curve = [warn_eval(D, rows, fins[a], int(wcfg["horizon_minutes"]), th, float(wcfg["episode_merge_minutes"]))
                     for th in grid]
            ok = [c for c in curve if c["assessable"] > 0 and c["precision"] is not None and c["fa_per_observed_day"] is not None
                  and c["fa_per_observed_day"] <= float(wcfg["workload_budget_per_observed_day"]) + 1e-12 and c["recall"] is not None]
            best = sorted(ok, key=lambda c: (-c["recall"], -c["precision"], c["episodes"], -c["threshold"]))[0] if ok else None
            out[f"warning_threshold_{name}"] = best["threshold"] if best else None
        # ranges: split-conformal on the fold's calibration participants for the blended final forecast
        cal = list(p.calibration)
        crow = np.isin(D.pids, cal)
        csaved = D.saved(fold, "calibration")
        for name, a in (("selected", sel), ("incumbent", 1.0)):
            cf = D.final(crow, blend(a, csaved))
            q = {}
            for h in HS:
                sc = D.ctx.scored(cal, h)
                q[h] = finite_sample_quantile(np.abs(D.target(h) - cf[h])[sc], float(proto["intervals"]["level"]))[0]
            out[f"range_half_width_{name}"] = q
        res["folds"][fold] = out
        print(fold, "selected alpha", sel, {a: round(r["sel_score"], 3) for a, r in by_a.items()}, flush=True)
    f = res["folds"][FINAL]
    sel, inc = f["alphas"][f["selected_alpha"]], f["alphas"][1.0]
    g = proto["development_target"]
    checks = {
        "improvement_60": inc["mae_60"] - sel["mae_60"],
        "worsening_30": sel["mae_30"] - inc["mae_30"],
        "high_worsening_60": (sel["high_mae_60"] - inc["high_mae_60"]) if sel["high_mae_60"] is not None else None,
        "availability_drop_points": 100 * max(inc[f"availability_{h}"] - sel[f"availability_{h}"] for h in (30, 60)),
    }
    met = (f["selected_alpha"] != 1.0
           and checks["improvement_60"] >= float(g["min_improvement_60_mg_dl"]) - 1e-12
           and checks["worsening_30"] <= float(g["max_worsening_30_mg_dl"]) + 1e-12
           and (checks["high_worsening_60"] is None or checks["high_worsening_60"] <= float(g["max_high_worsening_60_mg_dl"]) + 1e-12)
           and checks["availability_drop_points"] <= float(g["max_availability_drop_points"]) + 1e-12)
    res["decision"] = {"final_selected_alpha": f["selected_alpha"], "checks": checks, "target_met": bool(met),
                       "rule": "on the final development set (all development people, inner out-of-fold)"}
    (OUT / "development.json").write_text(json.dumps(res, indent=1, default=str))
    return res


# ------------------------------------------------------------------------------------------------ stage 3: assess


def assess(reopen: str | None) -> dict:
    proto = load_proto()
    dres = json.loads((OUT / "development.json").read_text())
    if not dres["decision"]["target_met"]:
        sys.exit("The development target was not met; the declared stop rule forbids opening the outer folds.")
    lock = OUT / "opened.json"
    if lock.exists() and not reopen:
        sys.exit(f"Assessment already opened ({json.loads(lock.read_text())['opened_at']}); re-running needs "
                 "--reopen-reason and is then exploratory.")
    D = Data()
    wcfg = proto["warnings"]
    now = datetime.now(UTC).isoformat(timespec="seconds")
    doc = json.loads(lock.read_text()) if lock.exists() else {"opened_at": now, "protocol": EXP, "reopened": []}
    if lock.exists():
        doc.setdefault("reopened", []).append({"at": now, "reason": reopen})
    lock.write_text(json.dumps(doc, indent=1))
    fins = {"selected": {}, "incumbent": {}}
    warn_parts = {"selected": [], "incumbent": []}
    cov = {"selected": {h: [] for h in HS}, "incumbent": {h: [] for h in HS}}
    people = []
    g_last = D.t["g_last"].to_numpy(float)
    for fold, p in D.plans.items():
        if fold == FINAL:
            continue
        fr = dres["folds"][fold]
        rows = np.isin(D.pids, list(p.assessment))
        people += list(p.assessment)
        saved = D.saved(fold, "assessment")
        for name, a in (("selected", fr["selected_alpha"]), ("incumbent", 1.0)):
            fin = D.final(rows, blend(a, saved))
            for h in HS:
                fins[name].setdefault(h, np.full(len(D.t), np.nan))
                fins[name][h] = np.where(rows, fin[h], fins[name][h])
                q = fr[f"range_half_width_{name}"][str(h)] if str(h) in fr[f"range_half_width_{name}"] else fr[f"range_half_width_{name}"][h]
                sc = D.ctx.scored(list(p.assessment), h) & np.isfinite(fin[h])
                err = np.abs(D.target(h) - fin[h])
                cov[name][h].append(pd.DataFrame({"pid": D.pids[sc], "covered": err[sc] <= q, "width": 2 * q}))
            thr = fr[f"warning_threshold_{name}"]
            if thr is not None:
                warn_parts[name].append(warn_eval(D, rows, fin, int(wcfg["horizon_minutes"]), float(thr),
                                                  float(wcfg["episode_merge_minutes"])))
    pers = {h: np.where(np.isin(D.pids, people), g_last, np.nan) for h in HS}
    res = {"opened": doc, "people": len(people), "forecast": {}, "comparisons": [], "ranges": {}, "warnings": {}}
    for name, f in (("selected", fins["selected"]), ("incumbent", fins["incumbent"]), ("persistence", pers)):
        res["forecast"][name] = scores(D, f, people)
    for h in HS:
        s = {n: M.per_participant_mae(f[h], D.target(h), D.pids, D.ctx.scored(people, h))
             for n, f in (("selected", fins["selected"]), ("incumbent", fins["incumbent"]), ("persistence", pers))}
        for title, a, b in (("Blend (nested alpha) minus LightGBM incumbent", "selected", "incumbent"),
                            ("Blend (nested alpha) minus persistence", "selected", "persistence"),
                            ("LightGBM incumbent minus persistence", "incumbent", "persistence")):
            r = M.paired_bootstrap(s[a], s[b], NBOOT, int(proto["random_seed"]) + h)
            res["comparisons"].append({"comparison": title, "horizon": h, **r,
                                       "per_participant_diff": {k: float(v) for k, v in (s[a] - s[b]).dropna().items()}})
    for name in ("selected", "incumbent"):
        res["ranges"][name] = {}
        for h in HS:
            df = pd.concat(cov[name][h])
            res["ranges"][name][h] = {"coverage_pooled": float(df["covered"].mean()),
                                      "coverage_participant_median": float(df.groupby("pid")["covered"].mean().median()),
                                      "width_mean": float(df["width"].mean())}
        parts = warn_parts[name]
        if parts:
            per = {k: v for x in parts for k, v in x["_per"].items()}
            leads = [y for x in parts for y in x["_leads"]]
            on = sum(v["onsets"] for v in per.values())
            days = sum(v["observed_min"] for v in per.values()) / 1440
            res["warnings"][name] = {
                "onsets": on, "detected": sum(v["detected"] for v in per.values()),
                "missed": on - sum(v["detected"] for v in per.values()),
                "early_30": sum(v["early"] for v in per.values()),
                "false_alarms": sum(v["false_alarms"] for v in per.values()),
                "fa_per_observed_day": sum(v["false_alarms"] for v in per.values()) / days if days else None,
                "observed_hours": sum(x["observed_hours"] for x in parts),
                "eligible_hours": sum(x["eligible_hours"] for x in parts),
                "share_eligible_time_warning": float(np.average([x["share_eligible_time_warning"] for x in parts],
                                                                weights=[x["eligible_hours"] for x in parts])),
                "precision": (lambda asb: (asb - sum(v["false_alarms"] for v in per.values())) / asb if asb else None)(
                    sum(x["assessable"] for x in parts)),
                "lead_median": float(np.median(leads)) if leads else None,
                "lead_iqr": [float(np.percentile(leads, 25)), float(np.percentile(leads, 75))] if leads else None,
                "folds_with_threshold": len(parts)}
    (OUT / "assessment.json").write_text(json.dumps(res, indent=1, default=str))
    return res


# ------------------------------------------------------------------------------------------------ report


def f2(x, nd=2, sign=False):
    return "—" if x is None else (f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}")


def render() -> str:
    proto = yaml.safe_load(PROTO_PATH.read_text())
    an = json.loads((OUT / "analysis.json").read_text())
    pw = json.loads((OUT / "protocol_written.json").read_text())
    out = [f"# LightGBM–CatBoost blend for the fusion feature set — `{EXP}`", "",
           "Research experiment (decision D-048) on the saved population predictions of `gt-2h-2026-10-20`: 14 CGMacros "
           "Type 2 people, each held out entirely once (5 participant folds). These people and the CatBoost and LightGBM "
           "results on them were already inspected, so every number here is internal validation, not untouched evidence. "
           f"Protocol recorded at {pw['written_at']} before any blend was scored. Not the demo model; nothing promoted.", "",
           "**Question.** For a person held out entirely, with the declared past-only patient update (v2 policy, k = 96, "
           "half-life 240 min) applied once, does `alpha × LightGBM + (1 − alpha) × CatBoost` on the profile-plus-wearable "
           "feature set (`dyn-prof-v2`) forecast glucose 60 minutes ahead at least 0.5 mg/dL better than LightGBM alone "
           "(alpha = 1, the matched incumbent)?", "",
           "## 1. Development errors of the matched incumbent (alpha = 1)", "",
           f"Final development set ({an['development_people']} people, inner out-of-fold, patient update applied). "
           "Macro per-participant MAE in mg/dL.", "",
           "| Stratum | 30 min | 60 min | 120 min | People (60 min) |", "|---|---|---|---|---|"]
    for name, row in an["strata"].items():
        r = {str(k): v for k, v in row.items()}
        out.append(f"| {name} | {f2(r['30']['macro_mae'])} | {f2(r['60']['macro_mae'])} | {f2(r['120']['macro_mae'])} | "
                   f"{r['60']['people']} ({r['60']['origins']:,} origins) |")
    pp = {str(k): v for k, v in an["per_participant"].items()}
    out += ["", f"Per-person 60-minute MAE ranges from {pp['60']['min']:.1f} to {pp['60']['max']:.1f} mg/dL (median "
            f"{pp['60']['median']:.1f}). Mean signed error at 60 min when the target is above 180 mg/dL: "
            f"{an['bias_60_target_above_180']:+.1f} mg/dL (peaks are under-forecast)" + (
                f"; below 70 mg/dL: {an['bias_60_target_below_70']:+.1f}." if an.get("bias_60_target_below_70") is not None else "."), ""]
    dpath = OUT / "development.json"
    if dpath.exists():
        d = json.loads(dpath.read_text())
        fin = d["folds"][FINAL]
        out += ["## 2. Development selection (inner out-of-fold only)", "",
                "Selection score: mean of the 30- and 60-minute macro MAE after the patient update; one alpha for all "
                "horizons; ties within "
                f"{proto['selection']['tie_mg_dl']} mg/dL go to the larger alpha.", "",
                "| alpha (LightGBM weight) | 30 min | 60 min | 120 min | 60 min, target > 180 | Score |", "|---|---|---|---|---|---|"]
        for a, r in sorted(fin["alphas"].items(), key=lambda kv: -float(kv[0])):
            mark = " **(selected)**" if float(a) == float(fin["selected_alpha"]) else ""
            out.append(f"| {float(a):g}{' (LightGBM alone)' if float(a) == 1 else ' (CatBoost alone)' if float(a) == 0 else ''}{mark} | "
                       f"{f2(r['mae_30'])} | {f2(r['mae_60'])} | {f2(r['mae_120'])} | {f2(r['high_mae_60'])} | {f2(r['sel_score'], 3)} |")
        out += ["", "Each outer fold's own inner folds (development people of that fold only; used only if the assessment runs):", "",
                "| Development set | People | Alpha chosen | 60-min gain vs alpha = 1 | 30-min gain vs alpha = 1 |",
                "|---|---|---|---|---|"]
        for k, v in d["folds"].items():
            al = {float(x): r for x, r in v["alphas"].items()}
            s, i = al[float(v["selected_alpha"])], al[1.0]
            out.append(f"| {k} | {v['development_people']} | {float(v['selected_alpha']):g} | {i['mae_60'] - s['mae_60']:+.2f} | "
                       f"{i['mae_30'] - s['mae_30']:+.2f} |")
        out.append("")
        c = d["decision"]["checks"]
        g = proto["development_target"]
        out += [f"Development target (final development set): 60-minute improvement {c['improvement_60']:+.2f} mg/dL "
                f"(needs ≥ {g['min_improvement_60_mg_dl']}); 30-minute worsening {c['worsening_30']:+.2f} (cap "
                f"{g['max_worsening_30_mg_dl']}); high-glucose 60-minute worsening {f2(c['high_worsening_60'], sign=True)} "
                f"(cap {g['max_high_worsening_60_mg_dl']}); availability drop {c['availability_drop_points']:.2f} points "
                f"(cap {g['max_availability_drop_points']}).", "",
                f"**Decision: {'target met — the declared assessment was run once' if d['decision']['target_met'] else 'target not met — the LightGBM incumbent is retained and the outer folds were not opened (declared stop rule)'}.**", ""]
    apath = OUT / "assessment.json"
    if apath.exists():
        a = json.loads(apath.read_text())
        out += ["## 3. Assessment (outer folds, opened once)", "",
                f"Opened at {a['opened']['opened_at']}" + "".join(f"; re-opened at {r['at']} ({r['reason']})" for r in a["opened"].get("reopened", []))
                + f". {a['people']} people, alpha chosen per outer fold on its own inner folds (nested).", "",
                "| Forecast | 30 min | 60 min | 120 min | 60 min, target > 180 |", "|---|---|---|---|---|"]
        for n, lab in (("selected", "Blend (nested alpha)"), ("incumbent", "LightGBM incumbent"), ("persistence", "Persistence")):
            r = a["forecast"][n]
            out.append(f"| {lab} | {f2(r['mae_30'])} | {f2(r['mae_60'])} | {f2(r['mae_120'])} | {f2(r['high_mae_60'])} |")
        out += ["", "| Comparison | Horizon | Mean difference (95 % participant bootstrap) | People better |", "|---|---|---|---|"]
        for c in a["comparisons"]:
            out.append(f"| {c['comparison']} | {c['horizon']} min | {f2(c['mean_diff'], sign=True)} "
                       f"[{f2(c['ci95'][0], sign=True)}, {f2(c['ci95'][1], sign=True)}] | {c['improved']} of {c['n_participants']} |")
        out += ["", "| Ranges (target 80 %) | 30 min | 60 min | 120 min |", "|---|---|---|---|"]
        for n in ("selected", "incumbent"):
            r = {str(k): v for k, v in a["ranges"][n].items()}
            out.append(f"| {n} | " + " | ".join(f"{100 * r[h]['coverage_pooled']:.1f} % ({r[h]['width_mean']:.0f} mg/dL)"
                                                for h in ("30", "60", "120")) + " |")
        out += ["", "| 60-minute warning | Onsets warned | Missed | Warned ≥ 30 min ahead | False alarms per observed day | Precision | Median lead (IQR) | Time in warning |",
                "|---|---|---|---|---|---|---|---|"]
        for n in ("selected", "incumbent"):
            w = a["warnings"].get(n)
            if not w:
                out.append(f"| {n} | no feasible threshold | | | | | | |")
                continue
            out.append(f"| {n} | {w['detected']} of {w['onsets']} | {w['missed']} | {w['early_30']} | {w['fa_per_observed_day']:.2f} "
                       f"(observed {w['observed_hours']:.0f} h) | {f2(w['precision'])} | {f2(w['lead_median'], 0)} "
                       f"({f2(w['lead_iqr'][0], 0)}–{f2(w['lead_iqr'][1], 0)}) | {100 * w['share_eligible_time_warning']:.1f} % |")
        out.append("")
    out += ["Regenerate: `uv run python scripts/blend_experiment.py --render`. Raw numbers: "
            f"`artifacts/research/{EXP}/` (analysis.json, development.json, assessment.json when run).", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--analyse", action="store_true")
    g.add_argument("--develop", action="store_true")
    g.add_argument("--assess", action="store_true")
    g.add_argument("--render", action="store_true")
    ap.add_argument("--reopen-reason")
    a = ap.parse_args()
    t0 = time.time()
    if a.analyse:
        print(json.dumps(analyse(), indent=1, default=str))
    elif a.develop:
        print(json.dumps(develop()["decision"], indent=1, default=str))
    elif a.assess:
        assess(a.reopen_reason)
    if not a.analyse:
        REPORT.write_text(render())
        print(REPORT.read_text())
    print(f"elapsed {time.time() - t0:.0f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
