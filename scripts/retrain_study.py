"""Retraining study gt-retrain-2026-10-21 (decision D-049): four fixed arms of the fusion LightGBM recipe.

B0 control (unweighted), A1 participant-balanced weights, A2 A1 + 2x weight on past-only rising origins, B1 A1 + causal
6/12/24-hour history features (hist-v1). Every arm is a fresh LightGBM fit with the serving model's frozen parameters
and rounds (no search, no early stopping). Selection uses development inner out-of-fold predictions of the FINAL plan
of gt-2h-2026-10-20 only; the outer folds are opened once, behind a lock file, and only if an arm qualifies.

Usage:  uv run python scripts/retrain_study.py develop        # fit every arm, select on development, write the report
        uv run python scripts/retrain_study.py assess         # only if development qualified (refuses otherwise)
        uv run python scripts/retrain_study.py render         # rewrite the report from saved summaries
"""

from __future__ import annotations

import json
import platform
import sys
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from glucotwin.config import paths
from glucotwin.features import FEATURE_SETS
from glucotwin.research import adapt
from glucotwin.research import metrics as M
from glucotwin.research import warnings as W
from glucotwin.research.calibration import finite_sample_quantile
from glucotwin.research.common import load_ctx
from glucotwin.research.history import COLUMNS as HIST
from glucotwin.research.history import table_history
from glucotwin.research.protocol import FINAL, load_frozen, plans_of, research_dir

ROOT = Path(__file__).resolve().parents[1]
PROTO_PATH = ROOT / "configs/experiments/gt-retrain-2026-10-21.yaml"
PROTO = yaml.safe_load(PROTO_PATH.read_text())
BASE = PROTO["base_experiment"]
TRACK = "multimodal_5min"
OUT = ROOT / PROTO["artifacts"]["root"]
REPORT = ROOT / PROTO["artifacts"]["report"]
SERVING_DIR = paths().artifacts / "models" / "lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion"
HS = [30, 60]
ARMS = ["B0_control", "A1_participant_balanced", "A2_balanced_rising_2x", "B1_balanced_long_history"]
SHORT = {"B0_control": "B0", "A1_participant_balanced": "A1", "A2_balanced_rising_2x": "A2",
         "B1_balanced_long_history": "B1"}
SEED = int(PROTO["random_seed"])
SEL = PROTO["selection"]
NBOOT = 2000


def recipe() -> dict[int, dict]:
    m = json.loads((SERVING_DIR / "manifest.json").read_text())
    out = {}
    for h, p in m["params"].items():
        q = {k: v for k, v in p.items() if k not in ("best_iteration", "fit_seconds")}
        out[int(h)] = {"params": q, "rounds": int(p["best_iteration"])}
    return out


class Study:
    def __init__(self):
        t0 = time.time()
        self.ctx = load_ctx(TRACK, "development", BASE)
        self.t = self.ctx.t
        self.pids = self.ctx.pids
        self.issued = self.ctx.issued
        self.base_cols = FEATURE_SETS["dyn-prof-v2"].columns()
        self.hist = table_history(self.t, self.ctx.td.prep)
        self.X = pd.concat([self.t[self.base_cols].reset_index(drop=True), self.hist.reset_index(drop=True)], axis=1)
        self.rec = recipe()
        self.policy = adapt.make_policy(self.ctx.proto, TRACK, 96, 240)
        self.plans = plans_of(load_frozen(BASE))
        self.final = next(p for p in self.plans if p.fold == FINAL)
        self.slope = self.t["slope_15"].to_numpy(float)
        self.setup_seconds = time.time() - t0
        self.fits: list[dict] = []

    def cols(self, arm: str) -> list[str]:
        return self.base_cols + HIST if arm.startswith("B1") else self.base_cols

    def weights(self, arm: str, rows: np.ndarray) -> np.ndarray | None:
        if arm == "B0_control":
            return None
        p = self.pids[rows]
        n = pd.Series(p).map(pd.Series(p).value_counts()).to_numpy(float)
        w = 1.0 / n                                             # every training person has total weight 1
        if arm == "A2_balanced_rising_2x":
            raw = np.where(np.nan_to_num(self.slope[rows], nan=0.0) > 1.0, 2.0, 1.0)
            tot = pd.Series(raw).groupby(p).transform("sum").to_numpy()
            w = raw / tot                                       # same per-person total, more on rising rows
        return w / w.mean()

    def fit_predict(self, arm: str, h: int, train: list[str], test_rows: np.ndarray, tag: str) -> np.ndarray:
        y = self.t[f"target_{h}"].to_numpy(float) - self.t["g_last"].to_numpy(float)
        rows = np.isin(self.pids, train) & self.issued & np.isfinite(y)
        cols = self.cols(arm)
        r = self.rec[h]
        params = {"objective": "regression", "metric": "l2", "verbosity": -1, "seed": SEED + h, "deterministic": True,
                  "force_row_wise": True, "num_threads": 4, "bagging_freq": 1, **r["params"]}
        t0 = time.time()
        ds = lgb.Dataset(self.X.loc[rows, cols].to_numpy(float), label=y[rows], weight=self.weights(arm, rows),
                         feature_name=cols, free_raw_data=False)
        bst = lgb.train(params, ds, num_boost_round=r["rounds"])
        out = np.full(len(self.t), np.nan)
        out[test_rows] = self.t["g_last"].to_numpy(float)[test_rows] + bst.predict(self.X.loc[test_rows, cols].to_numpy(float))
        self.fits.append({"arm": arm, "horizon": h, "scope": tag, "train_people": len(train), "train_rows": int(rows.sum()),
                          "features": len(cols), "rounds": r["rounds"], "seconds": round(time.time() - t0, 2)})
        return out

    def predictions(self, arm: str, scope: str):
        """Population and personalised forecasts for every development person (inner OOF) or assessment person."""
        pop = {h: np.full(len(self.t), np.nan) for h in HS}
        if scope == "development":
            dev = list(self.final.development)
            for k, inner in enumerate(self.final.inner):
                test = np.isin(self.pids, list(inner)) & self.issued
                train = [p for p in dev if p not in inner]
                for h in HS:
                    pop[h] = np.where(test, self.fit_predict(arm, h, train, test, f"inner-{k + 1}"), pop[h])
            rows = np.isin(self.pids, dev) & self.issued
        else:
            rows = np.zeros(len(self.t), bool)
            for p in [p for p in self.plans if p.fold != FINAL]:
                test = np.isin(self.pids, list(p.assessment)) & self.issued
                train = list(p.development) + list(p.calibration)
                for h in HS:
                    pop[h] = np.where(test, self.fit_predict(arm, h, train, test, p.fold), pop[h])
                rows |= test
        corr, _ = adapt.prequential(self.t, self.ctx.td.prep, rows, pop, self.policy, HS)
        return pop, adapt.apply(pop, corr), rows


def summarise(s: Study, preds: dict, rows: np.ndarray, label: str) -> dict:
    t = s.t
    tgt = {h: t[f"target_{h}"].to_numpy(float) for h in HS}
    common = {h: rows & np.isfinite(tgt[h]) & np.all([np.isfinite(p["final"][h]) for p in preds.values()], axis=0)
              for h in HS}
    elapsed = t["elapsed_min"].to_numpy(float)
    slope = s.slope

    def mmae(pred, m, min_n=1):
        d = pd.DataFrame({"p": s.pids[m], "e": np.abs(pred[m] - tgt[cur[0]][m])})
        g = d.groupby("p")["e"].agg(["mean", "size"])
        g = g[g["size"] >= min_n]
        return (float(g["mean"].mean()) if len(g) else None), int(len(g))

    base = preds["B0_control"]["final"]
    hi_people = {}
    for h in HS:
        m = common[h] & (tgt[h] > 180)
        cnt = pd.Series(s.pids[m]).value_counts()
        hi_people[h] = set(cnt[cnt >= 50].index)
    out = {"label": label, "arms": {}}
    cur = [HS[0]]
    for arm, p in preds.items():
        r = {}
        for h in HS:
            cur[0] = h
            m = common[h]
            fin, pop = p["final"][h], p["pop"][h]
            row = {"mae": mmae(fin, m)[0], "mae_population": mmae(pop, m)[0], "people": mmae(fin, m)[1],
                   "origins": int(m.sum())}
            mh = m & (tgt[h] > 180) & np.isin(s.pids, list(hi_people[h]))
            row["mae_high"], row["high_people"] = mmae(fin, mh)
            row["signed_high"] = float(np.mean(fin[m & (tgt[h] > 180)] - tgt[h][m & (tgt[h] > 180)]))
            for key, sm, mn in [("rise_fast", slope > 2, 20), ("rise", (slope > 1) & (slope <= 2), 20),
                                ("steady", np.abs(slope) <= 1, 20), ("falling", slope < -1, 20)]:
                row[f"mae_{key}"], row[f"{key}_people"] = mmae(fin, m & sm, mn)
            row["mae_first_day"], _ = mmae(fin, m & (elapsed < 1440))
            row["availability"] = float(np.isfinite(fin[rows & s.issued]).mean())
            r[str(h)] = row
        out["arms"][arm] = r
    out["high_glucose_people"] = {str(h): len(v) for h, v in hi_people.items()}
    out["_common"] = common
    out["_base"] = base
    return out


def qualify(summ: dict) -> dict:
    b = summ["arms"]["B0_control"]
    res = {}
    for arm in ARMS[1:]:
        a = summ["arms"][arm]
        gain = b["60"]["mae"] - a["60"]["mae"]
        checks = {"gain_60": gain, "worsening_30": a["30"]["mae"] - b["30"]["mae"],
                  "high_worsening_60": a["60"]["mae_high"] - b["60"]["mae_high"],
                  "availability_drop_points": 100 * (b["60"]["availability"] - a["60"]["availability"])}
        ok = (gain >= 0.5 and checks["worsening_30"] <= SEL["secondary_gates"]["mae_30_worsening_max"]
              and checks["high_worsening_60"] <= SEL["secondary_gates"]["high_glucose_60_worsening_max"]
              and checks["availability_drop_points"] <= SEL["secondary_gates"]["availability_drop_max_points"])
        rf = (b["60"]["mae_rise_fast"] - a["60"]["mae_rise_fast"]) / b["60"]["mae_rise_fast"] if b["60"]["mae_rise_fast"] else None
        res[arm] = {"checks": checks, "qualifies": bool(ok), "rise_fast_improvement_share": rf}
    qual = [a for a in ARMS[1:] if res[a]["qualifies"]]
    selected = None
    if qual:
        best = min(summ["arms"][a]["60"]["mae"] for a in qual)
        tied = [a for a in qual if summ["arms"][a]["60"]["mae"] <= best + SEL["near_tie_margin_mg_dl"]]
        selected = tied[0]  # ARMS order = A1, A2, B1: simplest first
    return {"by_arm": res, "selected": selected}


def env() -> dict:
    import catboost  # noqa: F401
    import sklearn

    rev = __import__("subprocess").run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    return {"python": platform.python_version(), "lightgbm": lgb.__version__, "numpy": np.__version__,
            "pandas": pd.__version__, "sklearn": sklearn.__version__, "git_head": rev,
            "protocol_sha256": sha256(PROTO_PATH.read_bytes()).hexdigest(),
            "split_hash": load_frozen(BASE)["split_hash"],
            "table_cache_key": json.loads((research_dir(BASE) / "tables" / f"{TRACK}__cgmacros.json").read_text())["cache_key"]}


def develop() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "development.json").exists():
        sys.exit("Development already run; rerunning would overwrite the recorded selection. Use render.")
    started = datetime.now(UTC).isoformat(timespec="seconds")
    s = Study()
    hist_cov = {c: float(np.isfinite(s.hist[c]).mean()) for c in HIST}
    preds = {}
    t0 = time.time()
    for arm in ARMS:
        pop, fin, rows = s.predictions(arm, "development")
        preds[arm] = {"pop": pop, "final": fin}
        print(arm, "done", round(time.time() - t0, 1), "s", flush=True)
    summ = summarise(s, preds, rows, "development inner out-of-fold, final plan (12 people)")
    # comparators from the saved inner OOF of the base experiment (same people, folds, origins)
    oof = pd.read_parquet(research_dir(BASE) / "development" / FINAL / TRACK / "inner_oof.parquet")
    comp = {}
    for name in ("persistence:-", "linear_trend:-"):
        d = oof[(oof["pipeline"] == name) & (oof["mode"] == "off")]
        r = {}
        for h in HS:
            mg = s.t[["patient_id", "origin"]].merge(d[d["horizon"] == h][["patient_id", "origin", "final"]], how="left",
                                                       on=["patient_id", "origin"], validate="one_to_one")["final"].to_numpy(float)
            m = summ["_common"][h] & np.isfinite(mg)
            e = pd.DataFrame({"p": s.pids[m], "e": np.abs(mg[m] - s.t[f"target_{h}"].to_numpy(float)[m])})
            r[str(h)] = {"mae": float(e.groupby("p")["e"].mean().mean()), "origins": int(m.sum())}
        comp[name] = r
    sel = qualify(summ)
    np.savez_compressed(OUT / "development_predictions.npz",
                        **{f"{SHORT[a]}_{k}_{h}": preds[a][k][h] for a in ARMS for k in ("pop", "final") for h in HS})
    doc = {"experiment_id": PROTO["experiment_id"], "started_at": started,
           "finished_at": datetime.now(UTC).isoformat(timespec="seconds"), "env": env(),
           "setup_seconds": round(s.setup_seconds, 1), "fit_seconds_total": round(sum(f["seconds"] for f in s.fits), 1),
           "fits": s.fits, "history_feature_availability": hist_cov,
           "summary": {k: v for k, v in summ.items() if not k.startswith("_")}, "comparators": comp, "selection": sel}
    (OUT / "development.json").write_text(json.dumps(doc, indent=1, default=float))
    REPORT.write_text(render(doc, None))
    print(json.dumps(sel, indent=1, default=float))


def assess() -> None:
    dev = json.loads((OUT / "development.json").read_text())
    arm = dev["selection"]["selected"]
    if arm is None:
        sys.exit("No arm qualified on development; under the stop rule the outer folds are not opened.")
    lock = OUT / "opened.json"
    if lock.exists():
        sys.exit(f"Assessment already opened at {json.loads(lock.read_text())['opened_at']}.")
    lock.write_text(json.dumps({"opened_at": datetime.now(UTC).isoformat(timespec="seconds"), "arm": arm}, indent=1))
    s = Study()
    preds = {}
    for a in ("B0_control", arm):
        pop, fin, rows = s.predictions(a, "assessment")
        preds[a] = {"pop": pop, "final": fin}
    summ = summarise(s, {a: preds[a] for a in preds}, rows, "outer assessment, 14 people each held out once")
    comps = {}
    for h in HS:
        m = summ["_common"][h]
        tg = s.t[f"target_{h}"].to_numpy(float)
        for mode in ("final", "pop"):
            ser = {a: pd.Series(np.abs(preds[a][mode][h][m] - tg[m])).groupby(s.pids[m]).mean() for a in preds}
            r = M.paired_bootstrap(ser[arm], ser["B0_control"], NBOOT, SEED + h)
            comps[f"{mode}_{h}"] = {"mean_diff": r["mean_diff"], "ci95": r["ci95"], "improved": r["improved"],
                                    "n": r["n_participants"]}
    doc = {"opened": json.loads(lock.read_text()), "arm": arm,
           "summary": {k: v for k, v in summ.items() if not k.startswith("_")}, "paired": comps,
           "warnings_ranges": warning_range(s, preds, arm)}
    (OUT / "assessment.json").write_text(json.dumps(doc, indent=1, default=float))
    REPORT.write_text(render(dev, doc))
    print(json.dumps(comps, indent=1, default=float))


def warning_range(s: Study, assess_preds: dict, arm: str) -> dict:
    """Thresholds from development inner OOF (D-043 workload rule) and 80 % ranges from the final plan's calibration
    people, each for the exact personalised pipeline; then measured on the assessment people."""
    dz = np.load(OUT / "development_predictions.npz")
    devrows = np.isin(s.pids, list(s.final.development)) & s.issued
    w = PROTO["warnings_and_ranges_if_qualified"]
    grid = [float(x) for x in w["warning"].split("[")[1].split("]")[0].split(",")]
    out = {}
    cal = list(s.final.calibration)
    for a in ("B0_control", arm):
        dev_final = {h: dz[f"{SHORT[a]}_final_{h}"] for h in HS}
        sc = W.scores(dev_final, 60)
        curve = [W.evaluate(s.t, devrows, s.issued, sc, 60, th, 30.0, 5.0)[0] for th in grid]
        thr, why = W.select_workload(curve, 2.0)
        # ranges: fit on the final plan's development people, personalised, scored on its calibration people
        pop = {h: np.full(len(s.t), np.nan) for h in HS}
        crow = np.isin(s.pids, cal) & s.issued
        for h in HS:
            pop[h] = s.fit_predict(a, h, list(s.final.development), crow, "calibration")
        corr, _ = adapt.prequential(s.t, s.ctx.td.prep, crow, pop, s.policy, HS)
        cfin = adapt.apply(pop, corr)
        q = {}
        for h in HS:
            res = np.abs(s.t[f"target_{h}"].to_numpy(float) - cfin[h])[crow]
            q[h] = finite_sample_quantile(res, 0.8)[0]
        arows = np.isfinite(assess_preds[a]["final"][60]) & s.issued
        asc = W.scores({h: assess_preds[a]["final"][h] for h in HS}, 60)
        ev = W.evaluate(s.t, arows, s.issued, asc, 60, thr, 30.0, 5.0)[0] if thr is not None else None
        elig = s.t["ew_eligible"].to_numpy(bool)
        fire = arows & elig & np.isfinite(asc) & (asc >= (thr if thr is not None else np.inf))
        leads = ev["_qualified_leads"] if ev else []
        cov = {}
        for h in HS:
            tg = s.t[f"target_{h}"].to_numpy(float)
            m = arows & np.isfinite(tg) & np.isfinite(assess_preds[a]["final"][h])
            hit = np.abs(tg[m] - assess_preds[a]["final"][h][m]) <= q[h]
            per = pd.Series(hit).groupby(s.pids[m]).mean()
            cov[str(h)] = {"half_width": q[h], "coverage": float(hit.mean()), "per_person_min": float(per.min()),
                           "per_person_max": float(per.max())}
        out[a] = {"threshold": thr, "why": why, "onsets": ev and ev["true_onsets"], "detected": ev and ev["detected_onsets"],
                  "false_alarms_per_observed_day": ev and ev["false_alarms_per_observed_patient_day"],
                  "precision": ev and ev["precision"], "early_30_share": (sum(x >= 30 for x in leads) / ev["true_onsets"])
                  if ev and ev["true_onsets"] else None, "lead_median": float(np.median(leads)) if leads else None,
                  "time_in_warning": float(fire.sum() / max(1, (arows & elig).sum())), "ranges": cov}
    return out


def render(dev: dict, ass: dict | None) -> str:
    sm, sel, comp = dev["summary"]["arms"], dev["selection"], dev["comparators"]
    f = lambda x, d=2: "—" if x is None else f"{x:.{d}f}"  # noqa: E731
    lines = ["# Retraining study — `gt-retrain-2026-10-21` (D-049)", "",
             f"Protocol committed before any fit (sha256 `{dev['env']['protocol_sha256'][:12]}`); development run "
             f"{dev['started_at']} → {dev['finished_at']} UTC on git `{dev['env']['git_head'][:7]}`, LightGBM "
             f"{dev['env']['lightgbm']}, split `{dev['env']['split_hash'][:12]}`. Every arm is a fresh LightGBM fit with the "
             "serving model's frozen parameters and rounds (no search, no early stopping). Selection: development inner "
             "out-of-fold on the final plan's 12 development people (3 inner folds), the declared patient update applied once. "
             "The 14 people were inspected in earlier experiments: internal research, not untouched evidence.", "",
             f"{len(dev['fits'])} fits, {dev['fit_seconds_total']} s of fitting in total.", "",
             "## Development (inner out-of-fold, macro per-participant MAE in mg/dL, personalised unless stated)", "",
             "| Arm | 60 min | 30 min | 60 min, population only | 60 min, target > 180 | 60 min, rising > 2 mg/dL/min | rising 1–2 | steady | falling | first 24 h | signed error, target > 180 | availability |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in ARMS:
        r60, r30 = sm[a]["60"], sm[a]["30"]
        lines.append(f"| {a} | **{f(r60['mae'])}** | {f(r30['mae'])} | {f(r60['mae_population'])} | {f(r60['mae_high'])} | "
                     f"{f(r60['mae_rise_fast'])} | {f(r60['mae_rise'])} | {f(r60['mae_steady'])} | {f(r60['mae_falling'])} | "
                     f"{f(r60['mae_first_day'])} | {f(r60['signed_high'], 1)} | {100 * r60['availability']:.1f} % |")
    for name, r in comp.items():
        lines.append(f"| {name.split(':')[0]} (comparator, saved) | {f(r['60']['mae'])} | {f(r['30']['mae'])} | | | | | | | | | |")
    hp = dev["summary"]["high_glucose_people"]
    lines += ["", f"Same origins for every arm ({sm['B0_control']['60']['origins']:,} at 60 min). High-glucose column: "
              f"participants with ≥ 50 origins whose 60-minute target is above 180 mg/dL ({hp['60']} people). Rising/steady/"
              "falling use the past-only `slope_15` at the origin; strata with fewer than 20 origins for a person leave that "
              "person out of that stratum.", "", "## Selection against the declared gates", "",
              "| Arm | 60-min gain vs B0 (≥ 0.5) | 30-min worsening (≤ 0.25) | high-glucose worsening (≤ 1.0) | availability drop (≤ 0.5 pt) | rising > 2 change | qualifies |",
              "|---|---|---|---|---|---|---|"]
    for a in ARMS[1:]:
        c = sel["by_arm"][a]["checks"]
        rf = sel["by_arm"][a]["rise_fast_improvement_share"]
        lines.append(f"| {a} | {c['gain_60']:+.2f} | {c['worsening_30']:+.2f} | {c['high_worsening_60']:+.2f} | "
                     f"{c['availability_drop_points']:+.2f} | {'—' if rf is None else f'{100 * rf:+.1f} %'} | "
                     f"{'**yes**' if sel['by_arm'][a]['qualifies'] else 'no'} |")
    pd_ = dev.get("development_paired_descriptive")
    if pd_:
        lines += ["", "Per-person paired differences on development, arm minus B0 (participant bootstrap, 2,000 resamples; "
                  "descriptive, computed after selection and not used for it):", "",
                  "| Arm | 60 min personalised | 60 min population only | 30 min personalised | people better at 60 min (personalised) |",
                  "|---|---|---|---|---|"]
        for arm in ("A1", "A2", "B1"):
            c = lambda k: f"{pd_[k]['mean_diff']:+.2f} [{pd_[k]['ci95'][0]:+.2f}, {pd_[k]['ci95'][1]:+.2f}]"  # noqa: E731
            lines.append(f"| {arm} | {c(f'{arm}_final_60')} | {c(f'{arm}_pop_60')} | {c(f'{arm}_final_30')} | "
                         f"{pd_[f'{arm}_final_60']['improved']} of {pd_[f'{arm}_final_60']['n']} |")
    lines += ["", f"**Decision:** {'selected ' + sel['selected'] if sel['selected'] else 'no arm met the gate — B0 (the incumbent recipe) is retained, the outer folds were not opened and no new arm was added (stop rule).'}", ""]
    if ass:
        lines += ["## Assessment (outer folds, opened once)", "",
                  f"Opened at {ass['opened']['opened_at']} for {ass['arm']}. Internal validation on already-inspected people.", "",
                  "| Comparison (selected minus B0) | Mean difference (95 % participant bootstrap) | People better |", "|---|---|---|"]
        for k, v in ass["paired"].items():
            mode, h = k.split("_")
            lines.append(f"| {h} min, {'personalised' if mode == 'final' else 'population only'} | {v['mean_diff']:+.2f} "
                         f"[{v['ci95'][0]:+.2f}, {v['ci95'][1]:+.2f}] | {v['improved']} of {v['n']} |")
        wr = ass["warnings_ranges"]
        lines += ["", "| Pipeline | Threshold | Onsets warned | ≥ 30 min ahead | False alarms / observed day | Precision | Time in warning | 60-min range coverage (width) |", "|---|---|---|---|---|---|---|---|"]
        for a, r in wr.items():
            rg = r["ranges"]["60"]
            lines.append(f"| {a} | {r['threshold']} | {r['detected']} of {r['onsets']} | {f(r['early_30_share'] and 100 * r['early_30_share'], 1)} % | "
                         f"{f(r['false_alarms_per_observed_day'])} | {f(r['precision'])} | {100 * r['time_in_warning']:.1f} % | "
                         f"{100 * rg['coverage']:.1f} % (±{rg['half_width']:.1f}) |")
    lines += ["", "Regenerate: `uv run python scripts/retrain_study.py render`. Raw numbers: "
              f"`{PROTO['artifacts']['root']}/development.json`" + (" and `assessment.json`." if ass else "."), ""]
    return "\n".join(lines)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "develop"
    if cmd == "develop":
        develop()
    elif cmd == "assess":
        assess()
    elif cmd == "render":
        d = json.loads((OUT / "development.json").read_text())
        a = json.loads((OUT / "assessment.json").read_text()) if (OUT / "assessment.json").exists() else None
        REPORT.write_text(render(d, a))
    else:
        sys.exit(__doc__)
