"""Nested tuning study gt-tune-2026-10-21 (decision D-051): current fusion features (C0) versus the same plus causal
6/12/24-hour history (C1), each with the identical tuning budget for the model AND the patient correction.

For every outer fold of gt-2h-2026-10-20: tune on the fold's development people (3 inner folds), refit on development
+ calibration people, score the assessment people once (lock file). Assessment people never influence a choice.

Usage:  uv run python scripts/tune_study.py run        # the full nested study (writes a progress log)
        uv run python scripts/tune_study.py render     # rewrite the report from the saved summary
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import retrain_study as R  # noqa: E402  (shared data, features and frozen serving recipe)
from glucotwin.research import adapt  # noqa: E402
from glucotwin.research import metrics as M  # noqa: E402
from glucotwin.research.history import COLUMNS as HIST  # noqa: E402
from glucotwin.research.protocol import FINAL  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROTO_PATH = ROOT / "configs/experiments/gt-tune-2026-10-21.yaml"
PROTO = yaml.safe_load(PROTO_PATH.read_text())
OUT = ROOT / PROTO["artifacts"]["root"]
REPORT = ROOT / PROTO["artifacts"]["report"]
SEED = int(PROTO["random_seed"])
HS = [30, 60]
N_TRIALS = 30
ROUNDS = (300, 600, 1200)
GRID_K = (24, 48, 96, 192)
GRID_HL = (120, 240, 720)
NBOOT = 2000
LOG = OUT / "progress.log"


def log(msg: str) -> None:
    line = f"{datetime.now(UTC).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def trials(h: int) -> list[dict]:
    """The same seeded parameter sets for both arms (one list per horizon)."""
    rng = np.random.default_rng(SEED + h)
    out = []
    for _ in range(N_TRIALS):
        out.append({"learning_rate": float(np.exp(rng.uniform(np.log(0.02), np.log(0.1)))),
                    "num_leaves": int(rng.integers(7, 64)), "max_depth": int(rng.integers(3, 9)),
                    "min_child_samples": int(rng.integers(20, 401)), "lambda_l2": float(rng.uniform(0, 20)),
                    "feature_fraction": float(rng.uniform(0.6, 1.0)), "bagging_fraction": float(rng.uniform(0.6, 1.0)),
                    "_rounds": int(rng.choice(ROUNDS))})
    return out


class Tuner:
    def __init__(self):
        self.s = R.Study()
        self.t, self.pids, self.issued = self.s.t, self.s.pids, self.s.issued
        self.cols = {"C0_current_features": self.s.base_cols, "C1_with_history": self.s.base_cols + HIST}
        self.y = {h: self.t[f"target_{h}"].to_numpy(float) for h in HS}
        self.g = self.t["g_last"].to_numpy(float)
        self.n_fits, self.fit_seconds = 0, 0.0

    def fit_predict(self, cols, params, rounds, h, train, test_rows, seed):
        y = self.y[h] - self.g
        rows = np.isin(self.pids, list(train)) & self.issued & np.isfinite(y)
        p = {"objective": "regression", "metric": "l2", "verbosity": -1, "seed": seed, "deterministic": True,
             "force_row_wise": True, "num_threads": 4, "bagging_freq": 1, **params}
        t0 = time.time()
        bst = lgb.train(p, lgb.Dataset(self.s.X.loc[rows, cols].to_numpy(float), label=y[rows], free_raw_data=False),
                        num_boost_round=rounds)
        out = np.full(len(self.t), np.nan)
        out[test_rows] = self.g[test_rows] + bst.predict(self.s.X.loc[test_rows, cols].to_numpy(float))
        self.n_fits += 1
        self.fit_seconds += time.time() - t0
        return out

    def macro(self, pred, h, rows) -> float:
        m = rows & np.isfinite(self.y[h]) & np.isfinite(pred)
        return float(pd.Series(np.abs(pred[m] - self.y[h][m])).groupby(self.pids[m]).mean().mean())

    def tune(self, arm: str, plan) -> dict:
        dev = list(plan.development)
        devrows = np.isin(self.pids, dev) & self.issued
        best, oof_best = {}, {}
        for h in HS:
            scores = []
            for tr in trials(h):
                params = {k: v for k, v in tr.items() if not k.startswith("_")}
                oof = np.full(len(self.t), np.nan)
                for inner in plan.inner:
                    te = np.isin(self.pids, list(inner)) & self.issued
                    oof = np.where(te, self.fit_predict(self.cols[arm], params, tr["_rounds"], h,
                                                        [p for p in dev if p not in inner], te, SEED + h), oof)
                sc = self.macro(oof, h, devrows)
                scores.append(sc)
                if sc <= min(scores):
                    oof_best[h] = oof
            i_best = int(np.argmin(scores))
            best[h] = {"trial": i_best, "params": trials(h)[i_best], "inner_population_mae": scores[i_best],
                       "trial_scores": scores}
        pols = [("off", None, None)] + [(f"k{k}_hl{hl}", k, hl) for k in GRID_K for hl in GRID_HL]
        res = []
        for name, k, hl in pols:
            pol = adapt.make_policy(self.s.ctx.proto, R.TRACK, k or 96, hl or 240, enabled=k is not None)
            corr, _ = adapt.prequential(self.t, self.s.ctx.td.prep, devrows, oof_best, pol, HS)
            fin = adapt.apply(oof_best, corr)
            res.append({"policy": name, "k": k, "half_life": hl,
                        "mae": {str(h): self.macro(fin[h], h, devrows) for h in HS}})
        chosen = min(res, key=lambda r: (np.mean(list(r["mae"].values())), r["policy"] != "off"))
        return {"params": best, "correction": chosen, "correction_grid": res}

    def score(self, arm: str, plan, choice: dict | None) -> dict:
        """Refit on development + calibration people, predict the assessment people, apply the correction causally."""
        train = list(plan.development) + list(plan.calibration)
        te = np.isin(self.pids, list(plan.assessment)) & self.issued
        pop = {}
        for h in HS:
            if choice is None:  # untuned serving recipe (frozen serving parameters, v2 correction)
                r = self.s.rec[h]
                pop[h] = self.fit_predict(self.s.base_cols, r["params"], r["rounds"], h, train, te, SEED + h)
            else:
                tr = choice["params"][h]["params"]
                pop[h] = self.fit_predict(self.cols[arm], {k: v for k, v in tr.items() if not k.startswith("_")},
                                          tr["_rounds"], h, train, te, SEED + h)
        if choice is None:
            pol = adapt.make_policy(self.s.ctx.proto, R.TRACK, 96, 240)
        else:
            c = choice["correction"]
            pol = adapt.make_policy(self.s.ctx.proto, R.TRACK, c["k"] or 96, c["half_life"] or 240, enabled=c["k"] is not None)
        corr, _ = adapt.prequential(self.t, self.s.ctx.td.prep, te, pop, pol, HS)
        return {"pop": pop, "final": adapt.apply(pop, corr)}


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "opened.json"
    if lock.exists():
        sys.exit(f"Assessment already opened at {json.loads(lock.read_text())['opened_at']}; use render.")
    started = datetime.now(UTC).isoformat(timespec="seconds")
    tu = Tuner()
    plans = [p for p in tu.s.plans if p.fold != FINAL]
    arms = list(tu.cols)
    preds = {a: {"pop": {h: np.full(len(tu.t), np.nan) for h in HS}, "final": {h: np.full(len(tu.t), np.nan) for h in HS}}
             for a in arms + ["R0_untuned_serving_recipe"]}
    choices = {}
    for p in plans:
        choices[p.fold] = {}
        for a in arms:
            t0 = time.time()
            choices[p.fold][a] = tu.tune(a, p)
            c = choices[p.fold][a]
            log(f"{p.fold} {a} tuned in {time.time() - t0:.0f}s: trials "
                f"{[c['params'][h]['trial'] for h in HS]}, correction {c['correction']['policy']}, "
                f"inner personalised {c['correction']['mae']}")
        if not lock.exists():  # first outer opening
            lock.write_text(json.dumps({"opened_at": datetime.now(UTC).isoformat(timespec="seconds"),
                                        "protocol_sha256": sha256(PROTO_PATH.read_bytes()).hexdigest()}, indent=1))
        rows = np.isin(tu.pids, list(p.assessment)) & tu.issued
        for a in arms + ["R0_untuned_serving_recipe"]:
            r = tu.score(a, p, choices[p.fold].get(a))
            for k in ("pop", "final"):
                for h in HS:
                    preds[a][k][h] = np.where(rows, r[k][h], preds[a][k][h])
        log(f"{p.fold} scored ({tu.n_fits} fits so far, {tu.fit_seconds:.0f}s fitting)")
    np.savez_compressed(OUT / "assessment_predictions.npz",
                        **{f"{a}_{k}_{h}": preds[a][k][h] for a in preds for k in ("pop", "final") for h in HS})
    summ = summarise(tu, preds)
    doc = {"experiment_id": PROTO["experiment_id"], "started_at": started,
           "finished_at": datetime.now(UTC).isoformat(timespec="seconds"), "env": R.env() | {"protocol_sha256": sha256(PROTO_PATH.read_bytes()).hexdigest()},
           "opened": json.loads(lock.read_text()), "n_fits": tu.n_fits, "fit_seconds": round(tu.fit_seconds, 1),
           "choices": {f: {a: {"params": {str(h): c["params"][h]["params"] | {"trial": c["params"][h]["trial"],
                                                                               "inner_population_mae": c["params"][h]["inner_population_mae"]}
                                          for h in HS},
                               "correction": c["correction"]} for a, c in v.items()} for f, v in choices.items()},
           **summ}
    (OUT / "summary.json").write_text(json.dumps(doc, indent=1, default=float))
    REPORT.write_text(render(doc))
    log("done")
    print(render(doc))


def summarise(tu: Tuner, preds: dict) -> dict:
    rows = np.zeros(len(tu.t), bool)
    for p in tu.s.plans:
        if p.fold != FINAL:
            rows |= np.isin(tu.pids, list(p.assessment))
    rows &= tu.issued
    slope, elapsed = tu.s.slope, tu.t["elapsed_min"].to_numpy(float)
    names = list(preds)
    out = {"arms": {}, "paired": {}}
    for h in HS:
        common = rows & np.isfinite(tu.y[h]) & np.all([np.isfinite(preds[a]["final"][h]) for a in names], axis=0)
        hi = common & (tu.y[h] > 180)
        cnt = pd.Series(tu.pids[hi]).value_counts()
        hi &= np.isin(tu.pids, list(cnt[cnt >= 50].index))
        pers = {"persistence": tu.g}
        for a in names + list(pers):
            pr = preds[a]["final"][h] if a in preds else pers[a]
            pp = preds[a]["pop"][h] if a in preds else pers[a]
            r = out["arms"].setdefault(a, {})
            r[str(h)] = {"mae": tu.macro(pr, h, common), "mae_population": tu.macro(pp, h, common),
                         "mae_high": tu.macro(pr, h, hi), "mae_rise_fast": tu.macro(pr, h, common & (slope > 2)),
                         "mae_steady": tu.macro(pr, h, common & (np.abs(slope) <= 1)),
                         "mae_falling": tu.macro(pr, h, common & (slope < -1)),
                         "mae_first_day": tu.macro(pr, h, common & (elapsed < 1440)), "origins": int(common.sum()),
                         "people": int(len(set(tu.pids[common])))}
        for a, b in (("C1_with_history", "C0_current_features"), ("C0_current_features", "R0_untuned_serving_recipe"),
                     ("C1_with_history", "R0_untuned_serving_recipe")):
            for mode in ("final", "pop"):
                ser = {x: pd.Series(np.abs(preds[x][mode][h][common] - tu.y[h][common])).groupby(tu.pids[common]).mean()
                       for x in (a, b)}
                r = M.paired_bootstrap(ser[a], ser[b], NBOOT, SEED + h)
                out["paired"][f"{a}|{b}|{mode}|{h}"] = {"mean_diff": r["mean_diff"], "ci95": r["ci95"],
                                                        "improved": r["improved"], "n": r["n_participants"]}
    p60 = out["paired"]["C1_with_history|C0_current_features|final|60"]
    w30 = out["arms"]["C1_with_history"]["30"]["mae"] - out["arms"]["C0_current_features"]["30"]["mae"]
    whi = out["arms"]["C1_with_history"]["60"]["mae_high"] - out["arms"]["C0_current_features"]["60"]["mae_high"]
    out["adoption"] = {"mean_diff_60": p60["mean_diff"], "ci95_60": p60["ci95"], "worsening_30": w30,
                       "high_worsening_60": whi,
                       "c1_better": bool(p60["mean_diff"] <= -0.5 and p60["ci95"][1] < 0 and w30 <= 0.25 and whi <= 1.0)}
    return out


def render(d: dict) -> str:
    f = lambda x: "—" if x is None else f"{x:.2f}"  # noqa: E731
    a, ad = d["arms"], d["adoption"]
    names = {"C0_current_features": "C0 — current fusion features, tuned", "C1_with_history": "C1 — + 6/12/24-hour history, tuned",
             "R0_untuned_serving_recipe": "R0 — serving recipe, frozen settings", "persistence": "Persistence"}
    lines = ["# Nested tuning study — `gt-tune-2026-10-21` (D-051)", "",
             f"Protocol committed before any fit (sha256 `{d['env']['protocol_sha256'][:12]}`). Outer folds first opened "
             f"{d['opened']['opened_at']}; run {d['started_at']} → {d['finished_at']} UTC, {d['n_fits']:,} LightGBM fits "
             f"({d['fit_seconds']:.0f} s of fitting), LightGBM {d['env']['lightgbm']}. Each arm got the same 30 seeded "
             "trials per horizon (each trial samples one boosting-round count from 300, 600 or 1200) and the same "
             "patient-correction grid, chosen on each outer fold's "
             "inner folds; the assessment people never influenced a choice. The 14 people were inspected in earlier "
             "experiments: internal validation, not untouched evidence.", "",
             "## Assessment people (each held out once), macro per-participant MAE in mg/dL", "",
             "| Pipeline | 60 min | 30 min | 60 min, population only | 60 min, target > 180 | rising > 2/min | steady | falling | first 24 h |",
             "|---|---|---|---|---|---|---|---|---|"]
    for k, n in names.items():
        r60, r30 = a[k]["60"], a[k]["30"]
        lines.append(f"| {n} | **{f(r60['mae'])}** | {f(r30['mae'])} | {f(r60['mae_population'])} | {f(r60['mae_high'])} | "
                     f"{f(r60['mae_rise_fast'])} | {f(r60['mae_steady'])} | {f(r60['mae_falling'])} | {f(r60['mae_first_day'])} |")
    lines += ["", f"Identical origins: {a['C0_current_features']['60']['origins']:,} at 60 min, {a['C0_current_features']['60']['people']} people.", "",
              "## Paired differences (first minus second; negative = lower error; 95 % participant bootstrap)", "",
              "| Comparison | 60 min personalised | 60 min population only | 30 min personalised | people better (60 min) |", "|---|---|---|---|---|"]
    for pair, label in (("C1_with_history|C0_current_features", "C1 vs C0 (history, equal tuning)"),
                        ("C0_current_features|R0_untuned_serving_recipe", "C0 vs R0 (effect of tuning)"),
                        ("C1_with_history|R0_untuned_serving_recipe", "C1 vs R0")):
        p = d["paired"]

        def c(m, h, p=p, pair=pair):
            x = p[f"{pair}|{m}|{h}"]
            return f"{x['mean_diff']:+.2f} [{x['ci95'][0]:+.2f}, {x['ci95'][1]:+.2f}]"
        lines.append(f"| {label} | {c('final', 60)} | {c('pop', 60)} | {c('final', 30)} | "
                     f"{p[f'{pair}|final|60']['improved']} of {p[f'{pair}|final|60']['n']} |")
    lines += ["", f"**Declared rule (C1 better only if the 60-minute difference ≤ −0.5 with its interval below 0, 30-minute "
              f"worsening ≤ 0.25, high-glucose worsening ≤ 1.0):** {'met' if ad['c1_better'] else 'not met'} "
              f"({ad['mean_diff_60']:+.2f} [{ad['ci95_60'][0]:+.2f}, {ad['ci95_60'][1]:+.2f}]; 30 min {ad['worsening_30']:+.2f}; "
              f"high-glucose {ad['high_worsening_60']:+.2f}). The serving model is not changed by this study.", "",
              "## Choices per outer fold (inner folds only)", "", "| Fold | Arm | 30-min trial / rounds | 60-min trial / rounds | Correction |", "|---|---|---|---|---|"]
    for fold, v in d["choices"].items():
        for arm, c in v.items():
            lines.append(f"| {fold} | {arm.split('_')[0]} | {c['params']['30']['trial']} / {c['params']['30']['_rounds']} | "
                         f"{c['params']['60']['trial']} / {c['params']['60']['_rounds']} | {c['correction']['policy']} |")
    lines += ["", "Regenerate: `uv run python scripts/tune_study.py render`. Raw numbers: "
              f"`{PROTO['artifacts']['root']}/summary.json`.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run()
    elif cmd == "render":
        REPORT.write_text(render(json.loads((OUT / "summary.json").read_text())))
    else:
        sys.exit(__doc__)
