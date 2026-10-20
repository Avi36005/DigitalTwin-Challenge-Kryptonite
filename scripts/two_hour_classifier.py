"""Two-hour onset classifier (protocol configs/experiments/gt-2h-clf-2026-10-20.yaml, decision D-044).

A LightGBM classifier is trained directly on "a new high-glucose onset begins within 120 minutes" on the frozen research
table and participant folds of gt-2h-2026-10-20. Per outer fold, the feature set and the warning threshold are chosen on
inner folds only; each assessment fold is scored once (lock file). Warnings use the repository's own episode merge and
one-to-one matcher (glucotwin.research.warnings), so the numbers are comparable with every other warning reported.

Usage:  uv run python scripts/two_hour_classifier.py [--reopen-reason TEXT]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import yaml
from glucotwin.features import FEATURE_SETS
from glucotwin.research import warnings as W
from glucotwin.research.common import load_ctx
from glucotwin.research.protocol import FINAL, load_frozen, plans_of
from glucotwin.research.report import _agg_events, _r
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
PROTO = yaml.safe_load((ROOT / "configs/experiments/gt-2h-clf-2026-10-20.yaml").read_text())
BASE = "gt-2h-2026-10-20"
OUT = ROOT / PROTO["artifacts"]["root"]
H, MERGE, BUDGET = 120, 30.0, 2.0


def fit(ctx, rows: np.ndarray, fs: str, seed: int) -> lgb.LGBMClassifier:
    cols = FEATURE_SETS[fs].columns()
    y = ctx.t[f"label_{H}"].to_numpy(float)[rows]
    m = lgb.LGBMClassifier(**PROTO["model"]["params"], random_state=seed, verbose=-1, n_jobs=4)
    return m.fit(ctx.t.loc[rows, cols], y.astype(int))


def predict(ctx, m: lgb.LGBMClassifier, rows: np.ndarray, fs: str) -> np.ndarray:
    p = np.full(len(ctx.t), np.nan)
    p[rows] = m.predict_proba(ctx.t.loc[rows, FEATURE_SETS[fs].columns()])[:, 1]
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reopen-reason")
    ap.add_argument("--render", action="store_true", help="rewrite the report from the saved summary (no fitting)")
    a = ap.parse_args()
    if a.render:
        (ROOT / PROTO["artifacts"]["report"]).write_text(render(json.loads((OUT / "summary.json").read_text())))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "opened.json"
    if lock.exists() and not a.reopen_reason:
        sys.exit(f"Assessment already opened ({json.loads(lock.read_text())['opened_at']}); re-running needs "
                 "--reopen-reason and is then exploratory.")
    ctx = load_ctx("multimodal_5min", "development", BASE)
    t, pids, issued = ctx.t, ctx.pids, ctx.issued
    lab = t[f"label_{H}"].to_numpy(float)
    elig = t["ew_eligible"].to_numpy(bool)
    trainable = issued & elig & np.isfinite(lab)
    cad = ctx.td.cadence
    seed = int(PROTO["random_seed"])
    grid = [float(x) for x in PROTO["threshold_grid"]]
    fsets = list(PROTO["model"]["feature_sets"])
    plans = [p for p in plans_of(load_frozen(BASE)) if p.fold != FINAL]

    # ---- inner-fold choices for every outer fold (no assessment participant is touched here)
    choices = {}
    for p in plans:
        dev = list(p.development)
        oof = {fs: np.full(len(t), np.nan) for fs in fsets}
        for k, inner in enumerate(p.inner):
            tr = trainable & np.isin(pids, [x for x in dev if x not in inner])
            te = issued & np.isin(pids, list(inner))
            for fs in fsets:
                oof[fs] = np.where(te, predict(ctx, fit(ctx, tr, fs, seed + k), te, fs), oof[fs])
        devrows = issued & np.isin(pids, dev)
        m = devrows & elig & np.isfinite(lab)
        ap_by = {fs: float(average_precision_score(lab[m], oof[fs][m])) for fs in fsets}
        best = max(ap_by.values())
        fs = next(f for f in fsets if ap_by[f] >= best - 0.005)  # declared order = smaller feature set first
        sel = {f: W.select_workload([W.evaluate(t, devrows, issued, oof[f], H, th, MERGE, cad)[0] for th in grid], BUDGET)
               for f in fsets}
        thr, why = sel[fs]
        choices[p.fold] = {"feature_set": fs, "inner_average_precision": ap_by, "threshold": thr, "why": why,
                           "threshold_by_feature_set": {f: v[0] for f, v in sel.items()}}
        print(p.fold, choices[p.fold]["feature_set"], thr, why, flush=True)

    # ---- open the assessment folds once
    now = datetime.now(UTC).isoformat(timespec="seconds")
    doc = json.loads(lock.read_text()) if lock.exists() else {"opened_at": now, "protocol": PROTO["experiment_id"],
                                                              "reopened": []}
    if a.reopen_reason:  # a re-open is appended; the first opening time is never overwritten
        doc.setdefault("reopened", []).append({"at": now, "reason": a.reopen_reason})
    lock.write_text(json.dumps(doc, indent=1))
    per_fs = {fs: {"events": [], "p": np.full(len(t), np.nan), "fire": 0, "elig": 0} for fs in fsets + ["selected"]}
    for i, p in enumerate(plans):
        tr = trainable & np.isin(pids, list(p.development) + list(p.calibration))
        te = issued & np.isin(pids, list(p.assessment))
        for fs in fsets:
            prob = predict(ctx, fit(ctx, tr, fs, seed + 100 + i), te, fs)
            per_fs[fs]["p"] = np.where(te, prob, per_fs[fs]["p"])
            thr = choices[p.fold]["threshold_by_feature_set"][fs]
            per_fs[fs]["elig"] += int((te & elig).sum())
            per_fs[fs]["fire"] += int((te & elig & (prob >= (thr if thr is not None else np.inf))).sum())
            if thr is not None:
                per_fs[fs]["events"].append({**W.evaluate(t, te, issued, prob, H, thr, MERGE, cad)[0], "fold": p.fold,
                                             "status": "ok"})
            if fs == choices[p.fold]["feature_set"]:
                per_fs["selected"]["p"] = np.where(te, prob, per_fs["selected"]["p"])
                per_fs["selected"]["elig"] += int((te & elig).sum())
                per_fs["selected"]["fire"] += int((te & elig & (prob >= (choices[p.fold]["threshold"] or np.inf))).sum())
                if choices[p.fold]["threshold"] is not None:
                    per_fs["selected"]["events"].append({**W.evaluate(t, te, issued, prob, H, choices[p.fold]["threshold"],
                                                                      MERGE, cad)[0], "fold": p.fold, "status": "ok"})
    nboot = 2000
    res = {}
    ass = np.isin(pids, [x for p in plans for x in p.assessment]) & trainable
    for name, d in per_fs.items():
        m = ass & np.isfinite(d["p"])
        agg = _agg_events(d["events"], nboot, seed) if d["events"] else {"status": "no_feasible_threshold"}
        res[name] = {"origin_roc_auc": _r(roc_auc_score(lab[m], d["p"][m]), 3),
                     "origin_average_precision": _r(average_precision_score(lab[m], d["p"][m]), 3),
                     "base_rate": _r(float(lab[m].mean()), 3), "origins": int(m.sum()),
                     # post-hoc diagnostic (not in the declared protocol): share of eligible origins at which it fires
                     "share_of_eligible_time_warning": _r(d["fire"] / d["elig"], 3) if d["elig"] else None,
                     **{k: agg.get(k) for k in ("status", "true_onsets", "detected_onsets", "missed_onsets",
                                                 "warning_episodes", "false_alarms", "recall", "precision",
                                                 "false_alarms_per_observed_day", "recall_ci95",
                                                 "false_alarms_per_observed_day_ci95", "qualified_lead_median",
                                                 "qualified_lead_iqr", "episode_start_to_onset_median",
                                                 "folds_without_threshold")}}
    summary = {"experiment_id": PROTO["experiment_id"], "base_table": BASE, "choices": choices, "results": res,
               "opened": json.loads(lock.read_text())}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    (ROOT / PROTO["artifacts"]["report"]).write_text(render(summary))
    print(render(summary))
    return 0


def render(s: dict) -> str:
    r = s["results"]
    names = {"selected": "**Selected per fold** (inner-fold rule)", "cgm-only-v1": "CGM only",
             "dyn-v2": "CGM + wearable", "dyn-prof-v2": "CGM + wearable + profile (EHR-like)"}
    out = [f"# Two-hour onset classifier — `{s['experiment_id']}`", "",
           "Research experiment (decision D-044), declared before any fit on 20 Oct 2026, on the frozen table and participant "
           f"folds of `{s['base_table']}`: 14 CGMacros Type 2 people, each held out entirely once (internal validation; these "
           f"people were inspected in earlier experiments). Assessment opened once at {s['opened']['opened_at']}. Not the demo "
           "model; nothing promoted.", "",
           "Feature set chosen per fold on inner folds: " + ", ".join(f"{k} `{v['feature_set']}`" for k, v in s["choices"].items())
           + ". Thresholds chosen on inner folds for at most 2 false alarms per observed forecastable day.", "",
           "**Result: negative — this classifier is not useful as a warning.** In every fold the inner-fold rule chose the "
           "lowest threshold on the declared grid (0.02), so the classifier fires at almost every eligible moment (share "
           "column, a post-hoc diagnostic). Firings within 30 minutes merge into one episode, so a near-constant alarm "
           "becomes a few long episodes that each contain an onset: the episode counts below look perfect while the "
           "warning carries little information (origin-level ROC AUC 0.62–0.66). Episode-based workload alone can be "
           "gamed this way; time spent in warning has to be read beside it. The regression-derived warning of "
           "`gt-2h-2026-10-20` stays the two-hour result we report.", "",
           f"Assessment first opened at {s['opened']['opened_at']}"
           + "".join(f"; re-opened at {r['at']} ({r['reason']})" for r in s["opened"].get("reopened", []))
           + ". The models are deterministic, so the declared metrics did not change.", "",
           "| Classifier (120-min onset) | Onsets warned | False alarms per observed day | Precision | Median forecast lead (IQR), min | Share of eligible time warning | ROC AUC | Average precision (base rate) |",
           "|---|---|---|---|---|---|---|---|"]
    for k, label in names.items():
        x = r[k]
        if x.get("status") != "ok":
            out.append(f"| {label} | no feasible threshold | — | — | — | — | {x['origin_roc_auc']} | {x['origin_average_precision']} ({x['base_rate']}) |")
            continue
        iqr = x["qualified_lead_iqr"]
        out.append(f"| {label} | {x['detected_onsets']} of {x['true_onsets']} ({100 * x['recall']:.1f} %) | "
                   f"{x['false_alarms_per_observed_day']} | {x['precision']} | {x['qualified_lead_median']} ({iqr[0]}–{iqr[1]}) | "
                   f"{100 * x['share_of_eligible_time_warning']:.0f} % | "
                   f"{x['origin_roc_auc']} | {x['origin_average_precision']} ({x['base_rate']}) |")
    out += ["", "Comparator (same people and folds, `gt-2h-2026-10-20`): the regression-derived 120-minute warning warned 315 "
            "of 329 onsets at 1.62 false alarms per observed day, median forecast lead 15 min (IQR 5–65) "
            "([two-hour benchmark](two_hour_benchmark.md)).", "",
            "Regenerate: `uv run python scripts/two_hour_classifier.py` (refuses to re-open the assessment without "
            "`--reopen-reason`). Raw numbers: `artifacts/research/gt-2h-clf-2026-10-20/summary.json`.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
