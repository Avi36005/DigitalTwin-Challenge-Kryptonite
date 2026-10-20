"""Earlier two-hour warnings, pooled ranges and a health-record starting correction (protocol
configs/experiments/gt-warn-range-2026-10-20.yaml, decision D-046).

A re-analysis of the saved predictions of gt-2h-2026-10-20: every choice is made on inner out-of-fold predictions of
the development participants (and the fold's calibration participants), and the outer-fold predictions are read once
behind a lock file. Warnings use the repository's own episode merge and one-to-one matcher.

Usage:  uv run python scripts/warning_range_experiment.py [--reopen-reason TEXT] [--render]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from glucotwin.research import metrics as M
from glucotwin.research import warnings as W
from glucotwin.research.calibration import finite_sample_quantile
from glucotwin.research.protocol import FINAL, load_frozen, plans_of, research_dir
from glucotwin.research.report import per_participant_series
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[1]
PROTO = yaml.safe_load((ROOT / "configs/experiments/gt-warn-range-2026-10-20.yaml").read_text())
BASE = PROTO["base_experiment"]
TRACK = "multimodal_5min"
OUT = ROOT / PROTO["artifacts"]["root"]
HS = [30, 60, 120]
A = PROTO["part_A_warning"]
H, MERGE, CAD = int(A["horizon_minutes"]), float(A["episode_merge_minutes"]), 5.0
EARLY, BUDGET, CAP = float(A["early_lead_minutes"]), float(A["workload_budget_per_observed_day"]), float(A["time_share_cap"])
GRID = [float(x) for x in A["threshold_grid"]]
ARMS = ["A0_point", "A1_upper_calibration", "A2_upper_pooled", "A3_long_only"]
PROFILE = PROTO["part_C_profile_prior"]["profile_columns"]
NBOOT, SEED = 2000, int(PROTO["random_seed"])


def align(t: pd.DataFrame, d: pd.DataFrame, col: str = "final") -> dict[int, np.ndarray]:
    """Per-horizon column of ``d`` aligned to the rows of ``t`` (NaN where ``d`` has no row)."""
    out = {}
    for h in HS:
        m = t[["patient_id", "origin"]].merge(d.loc[d["horizon"] == h, ["patient_id", "origin", col]], how="left",
                                              on=["patient_id", "origin"], validate="one_to_one")
        out[h] = m[col].to_numpy(float)
    return out


def arm_score(arm: str, final: dict[int, np.ndarray], q: dict[str, dict[int, float]]) -> np.ndarray:
    if arm == "A0_point":
        return W.scores(final, H)
    if arm == "A3_long_only":
        return final[H] - 180.0
    qq = q["cal"] if arm == "A1_upper_calibration" else q["pooled"]
    return W.scores({h: final[h] + qq[h] for h in HS}, H)


def warn(t, rows, issued, score, thr) -> dict:
    """Workload, early-warned onsets and time in warning for one score and threshold on ``rows``."""
    s, per = W.evaluate(t, rows, issued, score, H, thr, MERGE, CAD)
    elig = t["ew_eligible"].to_numpy(bool)
    pids = t["patient_id"].to_numpy()
    fire = rows & elig & issued & np.isfinite(score) & (score >= thr)
    base = rows & issued & elig
    pp = {pid: {"onsets": v["onsets"], "detected": v["detected"], "false_alarms": v["false_alarms"],
                "observed_min": v["observed_min"], "early": sum(1 for x in per[pid].qualified_leads if x >= EARLY),
                "fire": int((fire & (pids == pid)).sum()), "eligible": int((base & (pids == pid)).sum())}
          for pid, v in s["_per_participant"].items()}
    leads = s["_qualified_leads"]
    return {"threshold": thr, "onsets": s["true_onsets"], "detected": s["detected_onsets"],
            "early": sum(1 for x in leads if x >= EARLY), "false_alarms": s["false_alarm_episodes"],
            "episodes": s["warning_episodes"], "assessable": s["assessable_warnings"], "precision": s["precision"],
            "fa_per_day": s["false_alarms_per_observed_patient_day"],
            "lead_median": float(np.median(leads)) if leads else None,
            "lead_iqr": [float(np.percentile(leads, 25)), float(np.percentile(leads, 75))] if leads else None,
            "share": int(fire.sum()) / int(base.sum()) if base.sum() else None, "per": pp, "_leads": leads}


def choose(cands: list[dict]) -> dict | None:
    ok = [c for c in cands if c["assessable"] > 0 and c["precision"] is not None and c["fa_per_day"] is not None
          and c["fa_per_day"] <= BUDGET + 1e-12 and c["share"] is not None and c["share"] <= CAP + 1e-12]
    if not ok:
        return None
    return sorted(ok, key=lambda c: (-c["early"], -c["precision"], c["share"], -c["threshold"], ARMS.index(c["arm"])))[0]


def pool(parts: list[dict]) -> dict:
    per = {k: v for p in parts for k, v in p["per"].items()}
    on = sum(v["onsets"] for v in per.values())
    days = sum(v["observed_min"] for v in per.values()) / 1440.0
    leads = [x for p in parts for x in p.get("_leads", [])]
    return {"onsets": on, "detected": sum(v["detected"] for v in per.values()),
            "early": sum(v["early"] for v in per.values()), "false_alarms": sum(v["false_alarms"] for v in per.values()),
            "episodes": sum(p["episodes"] for p in parts),
            "fa_per_day": sum(v["false_alarms"] for v in per.values()) / days if days else None,
            "share": sum(v["fire"] for v in per.values()) / max(1, sum(v["eligible"] for v in per.values())),
            "precision": (lambda a: (a - sum(v["false_alarms"] for v in per.values())) / a if a else None)(
                sum(p["assessable"] for p in parts)),
            "lead_median": float(np.median(leads)) if leads else None,
            "lead_iqr": [float(np.percentile(leads, 25)), float(np.percentile(leads, 75))] if leads else None,
            "people": len(per), "per": per}


def boot_diff(a: dict, b: dict) -> dict:
    """Participant-cluster bootstrap of (a - b) in early-warned share of onsets and in false alarms per observed day."""
    ids = sorted(a["per"])
    rng = np.random.default_rng(SEED)
    va = np.array([[a["per"][i]["early"], a["per"][i]["false_alarms"]] for i in ids], float)
    vb = np.array([[b["per"][i]["early"], b["per"][i]["false_alarms"]] for i in ids], float)
    on = np.array([a["per"][i]["onsets"] for i in ids], float)
    dy = np.array([a["per"][i]["observed_min"] / 1440.0 for i in ids], float)

    def stat(ix):
        n, d = on[ix].sum(), dy[ix].sum()
        return [(va[ix, 0].sum() - vb[ix, 0].sum()) / n if n else np.nan, (va[ix, 1].sum() - vb[ix, 1].sum()) / d]

    pt = stat(np.arange(len(ids)))
    bs = np.array([stat(rng.integers(0, len(ids), len(ids))) for _ in range(NBOOT)])
    ci = lambda k: [float(np.nanpercentile(bs[:, k], 2.5)), float(np.nanpercentile(bs[:, k], 97.5))]  # noqa: E731
    return {"early_share_diff": float(pt[0]), "early_share_ci95": ci(0), "fa_per_day_diff": float(pt[1]),
            "fa_per_day_ci95": ci(1), "people": len(ids)}


def run(reopen: str | None, dev_only: bool = False) -> dict:
    root = research_dir(BASE)
    tpath = root / "tables" / f"{TRACK}__cgmacros.parquet"
    t = pd.read_parquet(tpath).sort_values(["patient_id", "origin"], kind="mergesort").reset_index(drop=True)
    key = json.loads(tpath.with_suffix(".json").read_text())["cache_key"]
    issued = (t["quality"] != "insufficient").to_numpy()
    pids = t["patient_id"].to_numpy()
    g_last = t["g_last"].to_numpy(float)
    plans = [p for p in plans_of(load_frozen(BASE)) if p.fold != FINAL]
    prof = t.groupby("patient_id")[PROFILE].median()

    # ---------------- development side: every choice (no outer participant is read here)
    fold = {}
    for p in plans:
        d = root / "development" / p.fold / TRACK
        pl = json.loads((d / "pipeline.json").read_text())
        if pl["table_cache_key"] != key:
            sys.exit(f"{p.fold}: cached table differs from the one frozen with the pipeline; refusing to run.")
        lab = pl["selection"]["selected"]
        inner = pd.read_parquet(d / "inner_oof.parquet")
        inner = inner[inner["pipeline"] == lab]
        cal = pd.read_parquet(d / "calibration_predictions.parquet")
        cal = cal[(cal["pipeline"] == lab) & (cal["mode"] == "final")]
        fin_in, tgt_in = align(t, inner[inner["mode"] == "final"]), align(t, inner[inner["mode"] == "final"], "target")
        off_in = align(t, inner[inner["mode"] == "off"])
        if not np.isfinite(fin_in[H]).any():
            sys.exit(f"{p.fold}: no inner personalised predictions for {lab}")
        fin_c, tgt_c = align(t, cal), align(t, cal, "target")
        qcal = {h: float(pl["calibration"][f"{lab}|final"]["horizons"][str(h)]["global_q"]) for h in HS}
        qpool, qstrat = {}, {}
        for h in HS:
            r_in = np.abs(tgt_in[h] - fin_in[h])
            r_c = np.abs(tgt_c[h] - fin_c[h])
            both = np.where(np.isfinite(r_in), r_in, r_c)
            qpool[h], _, n = finite_sample_quantile(both, 0.8)
            qstrat[h] = {}
            for name, m in (("low", g_last < 180), ("high", g_last >= 180)):
                qs, _, ns = finite_sample_quantile(np.where(m, both, np.nan), 0.8)
                qstrat[h][name] = qs if qs is not None else qpool[h]
        q = {"cal": qcal, "pooled": qpool}
        dev = np.isin(pids, list(p.development))
        cands = []
        for arm in ARMS:
            sc = arm_score(arm, fin_in, q)
            for th in GRID:
                c = warn(t, dev, issued, np.where(dev, sc, np.nan), th)
                cands.append({**{k: v for k, v in c.items() if k not in ("per", "_leads")}, "arm": arm})
        best = choose(cands)
        own = {arm: choose([c for c in cands if c["arm"] == arm]) for arm in ARMS}
        inc_thr = float(pl["warnings"][f"{lab}|final|{H}"]["primary"]["threshold"])
        # part C: profile -> mean population-only residual of each development participant
        prior = {}
        devp = list(p.development)
        for h in HS:
            res = pd.Series(tgt_in[h] - off_in[h]).groupby(pids).mean().reindex(devp)
            X = prof.reindex(devp)
            med, sd = X.median(), X.std(ddof=0).replace(0, 1.0)
            Xs = ((X.fillna(med) - X.fillna(med).mean()) / sd).to_numpy(float)
            ok = res.notna().to_numpy()
            mdl = Ridge(alpha=10.0).fit(Xs[ok], res.to_numpy(float)[ok])
            Xa = prof.reindex(list(p.assessment))
            pa = mdl.predict(((Xa.fillna(med) - X.fillna(med).mean()) / sd).to_numpy(float))
            prior[h] = {pid: float(np.clip(v, -25, 25)) for pid, v in zip(Xa.index, pa, strict=True)}
        fold[p.fold] = {"label": lab, "q": q, "qstrat": qstrat, "chosen": best, "own": own, "incumbent_threshold": inc_thr,
                        "prior": prior, "inner_candidates": cands}
        print(p.fold, lab, "chosen", best and (best["arm"], best["threshold"], best["early"], best["fa_per_day"],
                                                round(best["share"], 3)), flush=True)

    if dev_only:
        return {"dev_only": {k: {"label": v["label"], "q": v["q"], "chosen": v["chosen"], "own": v["own"]}
                             for k, v in fold.items()}}
    # ---------------- open the outer predictions once
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "opened.json"
    now = datetime.now(UTC).isoformat(timespec="seconds")
    doc = json.loads(lock.read_text()) if lock.exists() else {"opened_at": now, "protocol": PROTO["experiment_id"],
                                                              "reopened": []}
    if lock.exists():
        doc.setdefault("reopened", []).append({"at": now, "reason": reopen})
    lock.write_text(json.dumps(doc, indent=1))
    preds = pd.read_parquet(root / "assessment" / "predictions.parquet")
    preds = preds[preds["track"] == TRACK]
    events = json.loads((root / "assessment" / "events.json").read_text())["events"]

    parts = {k: [] for k in ["incumbent", "selected"] + ARMS}
    cov = {b: {h: [] for h in HS} for b in ("B0_calibration", "B1_pooled", "B2_pooled_by_glucose")}
    cframes = []
    for p in plans:
        f = fold[p.fold]
        lab = f["label"]
        rows = np.isin(pids, list(p.assessment))
        d = preds[(preds["fold"] == p.fold) & (preds["pipeline"] == lab)]
        fin = {h: np.where(rows, v, np.nan) for h, v in align(t, d[d["mode"] == "final"]).items()}
        up = align(t, d[d["mode"] == "final"], "upper_global")
        for h in HS:  # guard: the saved B0 range is the calibration half-width used by arm A1
            m = np.isfinite(up[h]) & rows
            if not np.allclose(up[h][m] - fin[h][m], f["q"]["cal"][h], atol=1e-6):
                sys.exit(f"{p.fold} {h}: saved range half-width differs from pipeline.json; refusing to report.")

        def run_arm(arm, thr, rows=rows, fin=fin, q=f["q"]):
            return warn(t, rows, issued, np.where(rows, arm_score(arm, fin, q), np.nan), thr)

        inc = run_arm("A0_point", f["incumbent_threshold"])
        saved = next(e for e in events if e["track"] == TRACK and e["fold"] == p.fold and e["pipeline"] == lab
                     and e["mode"] == "final" and e["horizon"] == H and e["policy"] == "primary")
        if (inc["episodes"], inc["detected"], inc["onsets"]) != (saved["warning_episodes"], saved["detected_onsets"],
                                                                 saved["true_onsets"]):
            sys.exit(f"{p.fold}: rebuilt incumbent warning does not reproduce the saved D-043 metrics; refusing to report.")
        parts["incumbent"].append(inc)
        ch = f["chosen"]
        parts["selected"].append(run_arm(ch["arm"], ch["threshold"]) if ch else inc)
        for arm in ARMS:
            o = f["own"][arm]
            if o:
                parts[arm].append(run_arm(arm, o["threshold"]))
        # part B
        tgt = {h: np.where(rows, v, np.nan) for h, v in align(t, d[d["mode"] == "final"], "target").items()}
        for h in HS:
            m = rows & issued & np.isfinite(fin[h]) & np.isfinite(tgt[h])
            err = np.abs(tgt[h] - fin[h])
            half = {"B0_calibration": np.full(len(t), f["q"]["cal"][h]),
                    "B1_pooled": np.full(len(t), f["q"]["pooled"][h]),
                    "B2_pooled_by_glucose": np.where(g_last >= 180, f["qstrat"][h]["high"], f["qstrat"][h]["low"])}
            for b, hw in half.items():
                cov[b][h].append(pd.DataFrame({"pid": pids[m], "covered": err[m] <= hw[m], "width": 2 * hw[m]}))
        # part C
        for mode in ("off", "final"):
            x = d[d["mode"] == mode][["patient_id", "origin", "horizon", "quality", "target", "final", "elapsed_min"]].copy()
            x["arm"] = mode
            cframes.append(x)
            if mode == "off":
                y = x.copy()
                y["final"] = y["final"] + [f["prior"][int(h)].get(pid, 0.0) for pid, h in zip(y["patient_id"], y["horizon"], strict=True)]
                y["arm"] = "C1_profile_prior"
                cframes.append(y)

    res = {"opened": doc, "folds": {k: {kk: vv for kk, vv in v.items() if kk != "inner_candidates"} for k, v in fold.items()}}
    strip = lambda x: {k: v for k, v in x.items() if k != "per"}  # noqa: E731
    pooled = {k: pool(v) for k, v in parts.items() if v}
    res["warnings"] = {k: {**strip(v), "folds_with_threshold": len(parts[k])} for k, v in pooled.items()}
    res["warning_diff_selected_minus_incumbent"] = boot_diff(pooled["selected"], pooled["incumbent"])
    res["ranges"] = {}
    for b, byh in cov.items():
        res["ranges"][b] = {}
        for h in HS:
            df = pd.concat(byh[h])
            res["ranges"][b][h] = {"coverage_pooled": float(df["covered"].mean()),
                                   "coverage_participant_median": float(df.groupby("pid")["covered"].mean().median()),
                                   "width_mean": float(df["width"].mean()), "n": int(len(df))}
    cf = pd.concat(cframes)
    res["profile_prior"] = {}
    for label, sub in (("all", cf), ("first_24h", cf[cf["elapsed_min"] < 1440])):
        res["profile_prior"][label] = {}
        for h in HS:
            s = {a: per_participant_series(sub[sub["arm"] == a], h) for a in ("off", "final", "C1_profile_prior")}
            r1 = M.paired_bootstrap(s["C1_profile_prior"], s["off"], NBOOT, SEED + h)
            r2 = M.paired_bootstrap(s["C1_profile_prior"], s["final"], NBOOT, SEED + h)
            res["profile_prior"][label][h] = {
                "mae": {a: float(v.mean()) for a, v in s.items()},
                "c1_minus_population": {"mean_diff": r1["mean_diff"], "ci95": r1["ci95"], "better_for": r1["improved"],
                                        "n": r1["n_participants"]},
                "c1_minus_personalised": {"mean_diff": r2["mean_diff"], "ci95": r2["ci95"], "better_for": r2["improved"],
                                          "n": r2["n_participants"]}}
    (OUT / "summary.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def render(s: dict) -> str:
    w, dd = s["warnings"], s["warning_diff_selected_minus_incumbent"]
    names = {"incumbent": "A0 point forecasts at the D-043 threshold (incumbent)",
             "selected": "**Selected per fold (inner-fold rule)**", "A0_point": "A0 point forecasts, own inner threshold",
             "A1_upper_calibration": "A1 forecast + range half-width (2 calibration people)",
             "A2_upper_pooled": "A2 forecast + pooled range half-width", "A3_long_only": "A3 120-minute forecast only"}
    pct = lambda x: "—" if x is None else f"{100 * x:.1f} %"  # noqa: E731
    out = ["# Earlier warnings, pooled ranges and the health record as a starting correction — `gt-warn-range-2026-10-20`", "",
           "Research experiment (decision D-046), declared and committed before any arm was computed, on 20 Oct 2026. A "
           "re-analysis of the saved predictions of `gt-2h-2026-10-20` (no forecasting model refitted): 14 CGMacros Type 2 "
           "people, each held out entirely once (5 participant folds). Every arm, threshold, range and profile model was "
           "chosen or fitted on development and calibration people only; the outer predictions were read once at "
           f"{s['opened']['opened_at']}"
           + "".join(f"; re-opened at {r['at']} ({r['reason']})" for r in s["opened"].get("reopened", []))
           + ". **These outer-fold people were already inspected** (D-043 and the time-in-warning check), and this "
           "protocol was written because of those results: internal validation, not untouched evidence. Not the demo "
           "model; nothing promoted.", "",
           "## A. Two-hour warning: earlier, at the same workload", "",
           "Per fold, the inner-fold rule chose: " + "; ".join(
               f"{k} {v['chosen']['arm']} at {v['chosen']['threshold']:+g}" if v["chosen"] else f"{k} incumbent (nothing feasible)"
               for k, v in s["folds"].items()) + ". Constraint: at most 2 false alarms per observed day and at most "
           "15 % of eligible time in warning, on inner folds.", "",
           "| 120-minute warning | Onsets warned | Warned ≥ 30 min ahead | False alarms per observed day | Precision | Median forecast lead (IQR), min | Share of eligible time warning |",
           "|---|---|---|---|---|---|---|"]
    for k, label in names.items():
        if k not in w:
            out.append(f"| {label} | no feasible threshold in any fold | | | | | |")
            continue
        x = w[k]
        iqr = x["lead_iqr"] or [None, None]
        out.append(f"| {label} | {x['detected']} of {x['onsets']} | {x['early']} ({pct(x['early'] / x['onsets'] if x['onsets'] else None)}) "
                   f"| {x['fa_per_day']:.2f} | {x['precision']:.2f} | {x['lead_median']:.0f} ({iqr[0]:.0f}–{iqr[1]:.0f}) "
                   f"| {pct(x['share'])} |" + ("" if x["folds_with_threshold"] == 5 else f" ({x['folds_with_threshold']} of 5 folds)"))
    out += ["", f"Selected minus incumbent (participant-cluster bootstrap, {dd['people']} people): onsets warned ≥ 30 min "
            f"ahead {100 * dd['early_share_diff']:+.1f} points [{100 * dd['early_share_ci95'][0]:+.1f}, "
            f"{100 * dd['early_share_ci95'][1]:+.1f}]; false alarms per observed day {dd['fa_per_day_diff']:+.2f} "
            f"[{dd['fa_per_day_ci95'][0]:+.2f}, {dd['fa_per_day_ci95'][1]:+.2f}].", "",
            "## B. Prediction ranges (target coverage 80 %)", "",
            "| Range calibration | 30 min coverage (width) | 60 min | 120 min | Per-person median coverage, 120 min |",
            "|---|---|---|---|---|"]
    rn = {"B0_calibration": "B0 two calibration people (incumbent)", "B1_pooled": "**B1 development + calibration people pooled** (declared primary)",
          "B2_pooled_by_glucose": "B2 pooled, separate below / above 180 mg/dL"}
    for b, label in rn.items():
        r = s["ranges"][b]
        c = {h: r.get(str(h)) or r[h] for h in HS}
        cells = " | ".join(f"{pct(c[h]['coverage_pooled'])} ({c[h]['width_mean']:.0f} mg/dL)" for h in HS)
        out.append(f"| {label} | {cells} | {pct(c[120]['coverage_participant_median'])} |")
    out += ["", "## C. Health record as a starting personal correction", "",
            "A ridge regression on the 8 baseline profile values, fitted on development people, predicts each new "
            "person's average forecast error and adds it from their first reading (no glucose of that person used).", "",
            "| Horizon | Population only MAE | + profile prior (C1) | Personalised (patient correction) | C1 minus population only (95 % CI), people better | C1 minus personalised |",
            "|---|---|---|---|---|---|"]
    for label in ("all", "first_24h"):
        for h in HS:
            r = s["profile_prior"][label].get(str(h)) or s["profile_prior"][label][h]
            a, b = r["c1_minus_population"], r["c1_minus_personalised"]
            out.append(f"| {h} min{' (first 24 h)' if label == 'first_24h' else ''} | {r['mae']['off']:.2f} | "
                       f"{r['mae']['C1_profile_prior']:.2f} | {r['mae']['final']:.2f} | {a['mean_diff']:+.2f} "
                       f"[{a['ci95'][0]:+.2f}, {a['ci95'][1]:+.2f}], {a['better_for']} of {a['n']} | {b['mean_diff']:+.2f} "
                       f"[{b['ci95'][0]:+.2f}, {b['ci95'][1]:+.2f}] |")
    c = s["profile_prior"]["all"].get("120") or s["profile_prior"]["all"][120]
    helps = c["c1_minus_population"]["ci95"][1] < 0
    out += ["", f"Declared claim rule (interval of C1 minus population only below zero at 120 min): "
            f"**{'met — the profile prior helps new people in this cohort' if helps else 'not met — no reliable benefit shown'}**.", "",
            "Regenerate: `uv run python scripts/warning_range_experiment.py --render` (rewrites this report from the "
            "saved summary; a full re-run needs `--reopen-reason` and is then exploratory). Raw numbers: "
            f"`{PROTO['artifacts']['root']}/summary.json`.", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reopen-reason")
    ap.add_argument("--render", action="store_true", help="rewrite the report from the saved summary (no outer read)")
    ap.add_argument("--dev-only", action="store_true", help="make every choice on development people and stop (no outer read)")
    a = ap.parse_args()
    if a.dev_only:
        print(json.dumps(run(None, dev_only=True), indent=1, default=str))
        return 0
    if a.render:
        s = json.loads((OUT / "summary.json").read_text())
    else:
        if (OUT / "opened.json").exists() and not a.reopen_reason:
            sys.exit(f"Outer predictions already read ({json.loads((OUT / 'opened.json').read_text())['opened_at']}); "
                     "re-running needs --reopen-reason and is then exploratory.")
        s = json.loads(json.dumps(run(a.reopen_reason), default=str))
    md = render(s)
    (ROOT / PROTO["artifacts"]["report"]).write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
