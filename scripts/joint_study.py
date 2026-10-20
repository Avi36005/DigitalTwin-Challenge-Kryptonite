"""Joint model + correction selection study gt-joint-2026-10-21 (decision D-052).

Inside each outer fold of gt-2h-2026-10-20: for three families (J0 LightGBM current features, J1 LightGBM + 24-hour
history, J2 CatBoost + history) choose configuration and patient correction together on the inner FINAL personalised
error, choose the family on the inner 60-minute error, refit and score the fold's assessment people once. R0 (refitted
serving recipe) is the primary comparator. Warning thresholds and 80 % ranges are fitted on development / calibration
people only.

Usage:  uv run python scripts/joint_study.py run       # the full nested study
        uv run python scripts/joint_study.py final     # only if the gate passed: rerun selection on the final plan
        uv run python scripts/joint_study.py render
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
from catboost import CatBoostRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import retrain_study as R  # noqa: E402  (shared table, history features, frozen serving recipe)
from glucotwin.research import adapt  # noqa: E402
from glucotwin.research import metrics as M  # noqa: E402
from glucotwin.research import warnings as W  # noqa: E402
from glucotwin.research.calibration import finite_sample_quantile  # noqa: E402
from glucotwin.research.history import COLUMNS as HIST  # noqa: E402
from glucotwin.research.protocol import FINAL, research_dir  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROTO_PATH = ROOT / "configs/experiments/gt-joint-2026-10-21.yaml"
PROTO = yaml.safe_load(PROTO_PATH.read_text())
OUT = ROOT / PROTO["artifacts"]["root"]
REPORT = ROOT / PROTO["artifacts"]["report"]
SEED = int(PROTO["random_seed"])
HS = [30, 60]
FAMS = ["J0", "J1", "J2"]
N_CFG = 16
POLICIES = [("off", None, None)] + [(f"k{k}_hl{hl}", k, hl) for k in (24, 48, 96, 192) for hl in (120, 240, 720)]
THR_GRID = [-30.0, -20.0, -10.0, 0.0, 10.0, 20.0]
CATBOOST_CEILING_S = 120 * 60
NBOOT = 2000
LOG = OUT / "progress.log"


def log(msg: str) -> None:
    line = f"{datetime.now(UTC).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def configs(fam: str, h: int, rec: dict) -> list[dict]:
    rng = np.random.default_rng(SEED + (1 if fam == "J2" else 0))
    out = []
    if fam == "J2":
        out.append({"loss_function": "RMSE", "learning_rate": 0.05, "depth": 6, "l2_leaf_reg": 3.0, "rsm": 1.0,
                    "_rounds": 600})
        for _ in range(N_CFG - 1):
            out.append({"loss_function": str(rng.choice(["RMSE", "MAE"])),
                        "learning_rate": float(np.exp(rng.uniform(np.log(0.02), np.log(0.1)))),
                        "depth": int(rng.integers(3, 9)), "l2_leaf_reg": float(rng.uniform(1, 30)),
                        "rsm": float(rng.uniform(0.6, 1.0)), "_rounds": int(rng.choice([300, 600, 1200]))})
    else:
        out.append({**rec[h]["params"], "objective": "regression", "_rounds": rec[h]["rounds"], "_incumbent": True})
        for _ in range(N_CFG - 1):
            out.append({"objective": str(rng.choice(["regression", "regression_l1"])),
                        "learning_rate": float(np.exp(rng.uniform(np.log(0.02), np.log(0.1)))),
                        "num_leaves": int(rng.integers(7, 64)), "max_depth": int(rng.integers(3, 9)),
                        "min_child_samples": int(rng.integers(20, 401)), "lambda_l2": float(rng.uniform(0, 20)),
                        "feature_fraction": float(rng.uniform(0.6, 1.0)), "bagging_fraction": float(rng.uniform(0.6, 1.0)),
                        "_rounds": int(rng.choice([300, 600, 1200]))})
    return out


class Joint:
    def __init__(self):
        self.s = R.Study()
        self.t, self.pids, self.issued = self.s.t, self.s.pids, self.s.issued
        self.cols = {"J0": self.s.base_cols, "J1": self.s.base_cols + HIST, "J2": self.s.base_cols + HIST,
                     "R0": self.s.base_cols}
        self.y = {h: self.t[f"target_{h}"].to_numpy(float) for h in HS}
        self.g = self.t["g_last"].to_numpy(float)
        self.fits = {"lightgbm": 0, "catboost": 0}
        self.seconds = {"lightgbm": 0.0, "catboost": 0.0}
        self.failures: list[dict] = []
        self.j2_disabled = False

    # ---------------------------------------------------------------- fitting
    def fit_predict(self, fam: str, cfg: dict, h: int, train, test_rows) -> np.ndarray:
        cols = self.cols[fam]
        y = self.y[h] - self.g
        rows = np.isin(self.pids, list(train)) & self.issued & np.isfinite(y)
        Xtr, Xte = self.s.X.loc[rows, cols].to_numpy(float), self.s.X.loc[test_rows, cols].to_numpy(float)
        out = np.full(len(self.t), np.nan)
        t0 = time.time()
        kind = "catboost" if fam == "J2" else "lightgbm"
        try:
            if kind == "catboost":
                p = {k: v for k, v in cfg.items() if not k.startswith("_")}
                m = CatBoostRegressor(iterations=cfg["_rounds"], random_seed=SEED + h, verbose=False, thread_count=4,
                                      allow_writing_files=False, nan_mode="Min", **p)
                m.fit(Xtr, y[rows])
                out[test_rows] = self.g[test_rows] + m.predict(Xte)
            else:
                p = {"metric": "l1", "verbosity": -1, "seed": SEED + h, "deterministic": True, "force_row_wise": True,
                     "num_threads": 4, "bagging_freq": 1, **{k: v for k, v in cfg.items() if not k.startswith("_")}}
                bst = lgb.train(p, lgb.Dataset(Xtr, label=y[rows], free_raw_data=False), num_boost_round=cfg["_rounds"])
                out[test_rows] = self.g[test_rows] + bst.predict(Xte)
        except Exception as exc:  # recorded, never silently dropped
            self.failures.append({"family": fam, "horizon": h, "config": {k: v for k, v in cfg.items()}, "error": str(exc)[:200]})
        self.fits[kind] += 1
        self.seconds[kind] += time.time() - t0
        return out

    def policy(self, name, k, hl):
        return adapt.make_policy(self.s.ctx.proto, R.TRACK, k or 96, hl or 240, enabled=k is not None)

    def personalise(self, pop_h: np.ndarray, h: int, rows: np.ndarray, pol) -> np.ndarray:
        corr, _ = adapt.prequential(self.t, self.s.ctx.td.prep, rows, {h: pop_h}, pol, [h])
        return adapt.apply({h: pop_h}, corr)[h]

    def macro(self, pred, h, rows) -> float:
        m = rows & np.isfinite(self.y[h]) & np.isfinite(pred)
        if not m.any():
            return float("inf")
        return float(pd.Series(np.abs(pred[m] - self.y[h][m])).groupby(self.pids[m]).mean().mean())

    # ---------------------------------------------------------------- selection on inner folds
    def inner_oof(self, fam: str, cfg: dict, h: int, plan) -> np.ndarray:
        dev = list(plan.development)
        oof = np.full(len(self.t), np.nan)
        for inner in plan.inner:
            te = np.isin(self.pids, list(inner)) & self.issued
            oof = np.where(te, self.fit_predict(fam, cfg, h, [p for p in dev if p not in inner], te), oof)
        return oof

    def select_family(self, fam: str, plan) -> dict:
        devrows = np.isin(self.pids, list(plan.development)) & self.issued
        res = {}
        for h in HS:
            cfgs = configs(fam, h, self.s.rec)
            table = []
            for ci, cfg in enumerate(cfgs):
                if fam == "J2" and self.seconds["catboost"] > CATBOOST_CEILING_S:
                    self.j2_disabled = True
                    return {"incomplete": True}
                oof = self.inner_oof(fam, cfg, h, plan)
                for name, k, hl in POLICIES:
                    fin = oof if k is None else self.personalise(oof, h, devrows, self.policy(name, k, hl))
                    table.append({"config": ci, "policy": name, "k": k, "half_life": hl, "rounds": cfg["_rounds"],
                                  "score": self.macro(fin, h, devrows)})
            best = min(x["score"] for x in table)
            tied = [x for x in table if x["score"] <= best + 0.005]
            pick = sorted(tied, key=lambda x: (x["policy"] != "off", x["rounds"], x["config"]))[0]
            res[h] = {"config": pick["config"], "params": cfgs[pick["config"]], "policy": pick["policy"], "k": pick["k"],
                      "half_life": pick["half_life"], "inner_final_mae": pick["score"], "table": table}
        return res

    # ---------------------------------------------------------------- outer scoring, ranges, warnings
    def procedure(self, fam: str, choice: dict | None, train, rows):
        """Population and personalised forecasts on ``rows`` for a family's chosen settings (or R0)."""
        pop, fin = {}, {}
        for h in HS:
            if choice is None:
                cfg = {**self.s.rec[h]["params"], "objective": "regression", "_rounds": self.s.rec[h]["rounds"]}
                pol = self.policy("k96_hl240", 96, 240)
            else:
                c = choice[h]
                cfg, pol = c["params"], self.policy(c["policy"], c["k"], c["half_life"])
            pop[h] = self.fit_predict("R0" if choice is None else fam, cfg, h, train, rows)
            fin[h] = pop[h] if (choice is not None and choice[h]["k"] is None) else self.personalise(pop[h], h, rows, pol)
        return pop, fin

    def inner_final(self, fam, choice, plan):
        dev = list(plan.development)
        fin = {h: np.full(len(self.t), np.nan) for h in HS}
        for inner in plan.inner:
            te = np.isin(self.pids, list(inner)) & self.issued
            _, f = self.procedure(fam, choice, [p for p in dev if p not in inner], te)
            for h in HS:
                fin[h] = np.where(te, f[h], fin[h])
        return fin


def warn_eval(t, rows, issued, fin, thr, pids) -> dict:
    sc = W.scores(fin, 60)
    s, per = W.evaluate(t, rows, issued, sc, 60, thr, 30.0, 5.0)
    elig = t["ew_eligible"].to_numpy(bool)
    fire = rows & elig & issued & np.isfinite(sc) & (sc >= thr)
    pp = {pid: {"onsets": v["onsets"], "detected": v["detected"], "false_alarms": v["false_alarms"],
                "observed_min": v["observed_min"], "ge15": sum(x >= 15 for x in per[pid].qualified_leads),
                "ge30": sum(x >= 30 for x in per[pid].qualified_leads), "ge60": sum(x >= 60 for x in per[pid].qualified_leads),
                "fire": int((fire & (pids == pid)).sum()), "eligible": int((rows & elig & issued & (pids == pid)).sum()),
                "episodes": len(per[pid].episodes), "assessable": s["_per_participant"][pid]["episodes"] - v["censored"],
                "durations": [ep["last"] - ep["start"] + 5.0 for ep in per[pid].episodes],
                "leads": list(per[pid].qualified_leads)} for pid, v in s["_per_participant"].items()}
    return pp


def pool_warn(per: dict) -> dict:
    v = list(per.values())
    on = sum(x["onsets"] for x in v)
    days = sum(x["observed_min"] for x in v) / 1440.0
    ass = sum(x["assessable"] for x in v)
    fa = sum(x["false_alarms"] for x in v)
    leads = [y for x in v for y in x["leads"]]
    dur = [y for x in v for y in x["durations"]]
    return {"onsets": on, "detected": sum(x["detected"] for x in v), "missed": on - sum(x["detected"] for x in v),
            "share_ge15": sum(x["ge15"] for x in v) / on if on else None, "share_ge30": sum(x["ge30"] for x in v) / on if on else None,
            "share_ge60": sum(x["ge60"] for x in v) / on if on else None, "false_alarms": fa,
            "fa_per_observed_day": fa / days if days else None, "precision": (ass - fa) / ass if ass else None,
            "time_in_warning": sum(x["fire"] for x in v) / max(1, sum(x["eligible"] for x in v)),
            "episode_minutes_median": float(np.median(dur)) if dur else None,
            "lead_median": float(np.median(leads)) if leads else None,
            "lead_iqr": [float(np.percentile(leads, 25)), float(np.percentile(leads, 75))] if leads else None}


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lock = OUT / "opened.json"
    if lock.exists():
        sys.exit(f"Assessment already opened at {json.loads(lock.read_text())['opened_at']}; use render.")
    started = datetime.now(UTC).isoformat(timespec="seconds")
    jt = Joint()
    plans = [p for p in jt.s.plans if p.fold != FINAL]
    procs = ["S", "R0", *FAMS]
    preds = {p: {"pop": {h: np.full(len(jt.t), np.nan) for h in HS}, "final": {h: np.full(len(jt.t), np.nan) for h in HS}}
             for p in procs}
    warn = {"S": {}, "R0": {}}
    ranges = {"S": {h: [] for h in HS}, "R0": {h: [] for h in HS}}
    choices, folds_doc = {}, {}
    for p in plans:
        t0 = time.time()
        ch = {}
        for fam in FAMS:
            if fam == "J2" and jt.j2_disabled:
                ch[fam] = {"incomplete": True}
                continue
            ch[fam] = jt.select_family(fam, p)
            if ch[fam].get("incomplete"):
                log(f"{p.fold} J2 stopped: CatBoost compute ceiling reached")
                continue
            log(f"{p.fold} {fam}: 30 cfg {ch[fam][30]['config']} {ch[fam][30]['policy']} {ch[fam][30]['inner_final_mae']:.3f}; "
                f"60 cfg {ch[fam][60]['config']} {ch[fam][60]['policy']} {ch[fam][60]['inner_final_mae']:.3f}")
        ok = [f for f in FAMS if not ch[f].get("incomplete")]
        best = min(ch[f][60]["inner_final_mae"] for f in ok)
        fam_sel = [f for f in ok if ch[f][60]["inner_final_mae"] <= best + 0.1][0]
        choices[p.fold] = {"selected_family": fam_sel, **ch}
        if not lock.exists():
            lock.write_text(json.dumps({"opened_at": datetime.now(UTC).isoformat(timespec="seconds"),
                                        "protocol_sha256": sha256(PROTO_PATH.read_bytes()).hexdigest()}, indent=1))
        train = list(p.development) + list(p.calibration)
        rows = np.isin(jt.pids, list(p.assessment)) & jt.issued
        for proc in procs:
            fam = fam_sel if proc == "S" else proc
            if fam in FAMS and ch[fam].get("incomplete"):
                continue
            pop, fin = jt.procedure(fam, None if proc == "R0" else ch[fam], train, rows)
            for h in HS:
                preds[proc]["pop"][h] = np.where(rows, pop[h], preds[proc]["pop"][h])
                preds[proc]["final"][h] = np.where(rows, fin[h], preds[proc]["final"][h])
        # warning threshold (inner OOF of the same procedure) and ranges (calibration people), S and R0 only
        devrows = np.isin(jt.pids, list(p.development)) & jt.issued
        cal = np.isin(jt.pids, list(p.calibration)) & jt.issued
        fdoc = {}
        for proc in ("S", "R0"):
            choice = None if proc == "R0" else ch[fam_sel]
            fam = fam_sel if proc == "S" else "R0"
            inner = jt.inner_final(fam, choice, p)
            curve = [W.evaluate(jt.t, devrows, jt.issued, W.scores(inner, 60), 60, th, 30.0, 5.0)[0] for th in THR_GRID]
            thr, why = W.select_workload(curve, 2.0)
            _, cfin = jt.procedure(fam, choice, list(p.development), cal)
            q = {h: finite_sample_quantile(np.abs(jt.y[h] - cfin[h])[cal & np.isfinite(cfin[h])], 0.8)[0] for h in HS}
            fdoc[proc] = {"threshold": thr, "why": why, "half_widths": q}
            if thr is not None:
                warn[proc].update(warn_eval(jt.t, rows, jt.issued, {h: preds[proc]["final"][h] for h in HS}, thr, jt.pids))
            for h in HS:
                m = rows & np.isfinite(jt.y[h]) & np.isfinite(preds[proc]["final"][h])
                err = np.abs(jt.y[h][m] - preds[proc]["final"][h][m])
                ranges[proc][h].append(pd.DataFrame({"pid": jt.pids[m], "hit": err <= (q[h] if q[h] is not None else -1),
                                                     "width": 2 * (q[h] or np.nan), "slope": jt.s.slope[m]}))
        folds_doc[p.fold] = fdoc
        log(f"{p.fold} scored: family {fam_sel}; {time.time() - t0:.0f}s; fits {jt.fits}; seconds "
            f"{ {k: round(v) for k, v in jt.seconds.items()} }")
    np.savez_compressed(OUT / "assessment_predictions.npz",
                        **{f"{a}_{k}_{h}": preds[a][k][h] for a in preds for k in ("pop", "final") for h in HS})
    doc = {"experiment_id": PROTO["experiment_id"], "started_at": started,
           "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
           "env": R.env() | {"protocol_sha256": sha256(PROTO_PATH.read_bytes()).hexdigest(),
                             "catboost": __import__("catboost").__version__},
           "opened": json.loads(lock.read_text()), "fits": jt.fits, "fit_seconds": {k: round(v, 1) for k, v in jt.seconds.items()},
           "failures": jt.failures, "j2_disabled": jt.j2_disabled,
           "choices": {f: {"selected_family": v["selected_family"],
                           **{fam: ({"incomplete": True} if c.get("incomplete") else
                                    {str(h): {k: c[h][k] for k in ("config", "params", "policy", "inner_final_mae")} for h in HS})
                              for fam, c in v.items() if fam in FAMS}} for f, v in choices.items()},
           "inner_tables": {f: {fam: ({str(h): c[h]["table"] for h in HS} if not c.get("incomplete") else None)
                                for fam, c in v.items() if fam in FAMS} for f, v in choices.items()},
           "warning_and_range_settings": folds_doc,
           **summarise(jt, preds, warn, ranges)}
    (OUT / "summary.json").write_text(json.dumps(doc, indent=1, default=float))
    REPORT.write_text(render(doc))
    log("done")
    print(render(doc))


def summarise(jt: Joint, preds: dict, warn: dict, ranges: dict) -> dict:
    rows = np.zeros(len(jt.t), bool)
    for p in jt.s.plans:
        if p.fold != FINAL:
            rows |= np.isin(jt.pids, list(p.assessment))
    rows &= jt.issued
    # a family stopped by the compute ceiling in any fold is excluded so every procedure is compared on identical origins
    procs = [p for p in preds if np.isfinite(preds[p]["final"][60][rows]).any() and not (p == "J2" and jt.j2_disabled)]
    base = research_dir(R.BASE)
    sa = pd.read_parquet(base / "assessment" / "predictions.parquet")
    lt = {}
    for h in HS:
        d = sa[(sa["track"] == R.TRACK) & (sa["pipeline"] == "linear_trend:-") & (sa["mode"] == "off") & (sa["horizon"] == h)]
        lt[h] = jt.t[["patient_id", "origin"]].merge(d[["patient_id", "origin", "final"]], how="left",
                                                     on=["patient_id", "origin"], validate="one_to_one")["final"].to_numpy(float)
    out = {"procedures": {}, "paired": {}}
    slope, el = jt.s.slope, jt.t["elapsed_min"].to_numpy(float)
    for h in HS:
        common = rows & np.isfinite(jt.y[h]) & np.all([np.isfinite(preds[p]["final"][h]) for p in procs], axis=0)
        avail = {p: float(np.isfinite(preds[p]["final"][h][rows]).mean()) for p in procs}
        hi = common & (jt.y[h] > 180)
        cnt = pd.Series(jt.pids[hi]).value_counts()
        hi &= np.isin(jt.pids, list(cnt[cnt >= 50].index))
        series = {**{p: (preds[p]["final"][h], preds[p]["pop"][h]) for p in procs}, "persistence": (jt.g, jt.g),
                  "linear_trend": (lt[h], lt[h])}
        for name, (fin, pop) in series.items():
            m = common & np.isfinite(fin)
            out["procedures"].setdefault(name, {})[str(h)] = {
                "mae": jt.macro(fin, h, m), "mae_population": jt.macro(pop, h, m), "mae_high": jt.macro(fin, h, hi & m),
                "mae_rise_fast": jt.macro(fin, h, m & (slope > 2)), "mae_steady": jt.macro(fin, h, m & (np.abs(slope) <= 1)),
                "mae_falling": jt.macro(fin, h, m & (slope < -1)), "mae_first_day": jt.macro(fin, h, m & (el < 1440)),
                "origins": int(m.sum()), "availability": avail.get(name)}
        for a in procs:
            for b in procs:
                if a == b or (a, b) not in {("S", "R0"), ("J0", "R0"), ("J1", "R0"), ("J2", "R0"), ("J1", "J0"), ("J2", "J1")}:
                    continue
                for mode in ("final", "pop"):
                    ser = {x: pd.Series(np.abs(preds[x][mode][h][common] - jt.y[h][common])).groupby(jt.pids[common]).mean()
                           for x in (a, b)}
                    r = M.paired_bootstrap(ser[a], ser[b], NBOOT, SEED + h)
                    out["paired"][f"{a}|{b}|{mode}|{h}"] = {"mean_diff": r["mean_diff"], "ci95": r["ci95"],
                                                            "improved": r["improved"], "n": r["n_participants"]}
        out.setdefault("common_origins", {})[str(h)] = int(common.sum())
    P = out["procedures"]
    g = out["paired"]["S|R0|final|60"]
    gate = {"mean_diff_60": g["mean_diff"], "ci95_60": g["ci95"],
            "worsening_30": P["S"]["30"]["mae"] - P["R0"]["30"]["mae"],
            "high_worsening_60": P["S"]["60"]["mae_high"] - P["R0"]["60"]["mae_high"],
            "availability_drop_points": 100 * (P["R0"]["60"]["availability"] - P["S"]["60"]["availability"])}
    gate["passed"] = bool(gate["mean_diff_60"] <= -0.5 and gate["ci95_60"][1] < 0 and gate["worsening_30"] <= 0.25
                          and gate["high_worsening_60"] <= 1.0 and gate["availability_drop_points"] <= 0.5)
    out["gate"] = gate
    out["warnings"] = {p: pool_warn(v) for p, v in warn.items() if v}
    if "S" in out["warnings"] and "R0" in out["warnings"]:
        s, r = out["warnings"]["S"], out["warnings"]["R0"]
        out["release_guardrails"] = {
            "fa_per_day_delta": s["fa_per_observed_day"] - r["fa_per_observed_day"],
            "time_in_warning_delta_points": 100 * (s["time_in_warning"] - r["time_in_warning"]),
            "warned30_delta_points": 100 * (s["share_ge30"] - r["share_ge30"])}
        rg = out["release_guardrails"]
        rg["passed"] = bool(rg["fa_per_day_delta"] <= 0.10 and rg["time_in_warning_delta_points"] <= 2.0
                            and rg["warned30_delta_points"] >= -2.0)
    out["ranges"] = {}
    for p, byh in ranges.items():
        out["ranges"][p] = {}
        for h, parts in byh.items():
            df = pd.concat(parts)
            per = df.groupby("pid")["hit"].mean()
            out["ranges"][p][str(h)] = {"coverage": float(df["hit"].mean()), "width_mean": float(df["width"].mean()),
                                        "per_person_min": float(per.min()), "per_person_max": float(per.max()),
                                        "rise_fast": float(df.loc[df["slope"] > 2, "hit"].mean()),
                                        "steady": float(df.loc[df["slope"].abs() <= 1, "hit"].mean())}
    return out


def render(d: dict) -> str:
    f = lambda x: "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.2f}"  # noqa: E731
    pct = lambda x: "—" if x is None else f"{100 * x:.1f} %"  # noqa: E731
    P, g = d["procedures"], d["gate"]
    names = {"S": "**S — selected procedure (family chosen inside each fold)**", "R0": "R0 — refitted serving recipe",
             "J0": "J0 — LightGBM, current features", "J1": "J1 — LightGBM + 24-hour history",
             "J2": "J2 — CatBoost + 24-hour history", "persistence": "Persistence", "linear_trend": "Linear trend"}
    sel = {k: v["selected_family"] for k, v in d["choices"].items()}
    L = ["# Joint model + correction selection — `gt-joint-2026-10-21` (D-052)", "",
         f"Protocol committed before any fit (sha256 `{d['env']['protocol_sha256'][:12]}`); outer folds first opened "
         f"{d['opened']['opened_at']}; run {d['started_at']} → {d['finished_at']} UTC. Fresh fits: LightGBM "
         f"{d['fits']['lightgbm']:,} ({d['fit_seconds']['lightgbm']:.0f} s), CatBoost {d['fits']['catboost']:,} "
         f"({d['fit_seconds']['catboost']:.0f} s); failures {len(d['failures'])}; J2 ceiling reached: {d['j2_disabled']}. "
         "Inside each outer fold, configuration and patient correction were chosen together on the inner personalised "
         "error and the family on the inner 60-minute error; the assessment people never influenced a choice. Families "
         "chosen per fold: " + ", ".join(f"{k} {v}" for k, v in sel.items()) + ". The 14 people were inspected in earlier "
         "experiments: internal validation, not independent confirmation.", "",
         "## Assessment people, macro per-participant MAE in mg/dL (identical origins)", "",
         "| Procedure | 60 min | 30 min | 60 min population only | 60 min, target > 180 | rising > 2/min | steady | falling | first 24 h | availability |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for k, n in names.items():
        if k not in P:
            continue
        a, b = P[k]["60"], P[k]["30"]
        L.append(f"| {n} | **{f(a['mae'])}** | {f(b['mae'])} | {f(a['mae_population'])} | {f(a['mae_high'])} | "
                 f"{f(a['mae_rise_fast'])} | {f(a['mae_steady'])} | {f(a['mae_falling'])} | {f(a['mae_first_day'])} | "
                 f"{pct(a['availability'])} |")
    L += ["", "## Paired differences (first minus second, negative = lower error, 95 % participant bootstrap)", "",
          "| Comparison | 60 min personalised | 60 min population only | 30 min personalised | people better (60) |", "|---|---|---|---|---|"]
    for key in ("S|R0", "J0|R0", "J1|R0", "J2|R0", "J1|J0", "J2|J1"):
        p = d["paired"]
        if f"{key}|final|60" not in p:
            continue
        c = lambda m, h, key=key, p=p: f"{p[f'{key}|{m}|{h}']['mean_diff']:+.2f} [{p[f'{key}|{m}|{h}']['ci95'][0]:+.2f}, {p[f'{key}|{m}|{h}']['ci95'][1]:+.2f}]"  # noqa: E731
        L.append(f"| {key.replace('|', ' vs ')} | {c('final', 60)} | {c('pop', 60)} | {c('final', 30)} | "
                 f"{p[f'{key}|final|60']['improved']} of {p[f'{key}|final|60']['n']} |")
    L += ["", f"**Primary gate (S vs R0: ≤ −0.5 mg/dL at 60 min with the interval below 0; 30-min worsening ≤ 0.25; "
          f"high-glucose worsening ≤ 1.0; availability drop ≤ 0.5 pt): {'PASSED' if g['passed'] else 'not met'}** — "
          f"{g['mean_diff_60']:+.2f} [{g['ci95_60'][0]:+.2f}, {g['ci95_60'][1]:+.2f}]; 30 min {g['worsening_30']:+.2f}; "
          f"high-glucose {g['high_worsening_60']:+.2f}; availability {g['availability_drop_points']:+.2f} pt.", ""]
    if d.get("warnings"):
        L += ["## 60-minute warning (thresholds chosen on inner folds per outer fold)", "",
              "| Procedure | Onsets | Detected / missed | Warned ≥ 15 / 30 / 60 min (all onsets) | False alarms / observed day | Precision | Time in warning | Median episode | Lead median (IQR) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for k, w in d["warnings"].items():
            iq = w["lead_iqr"] or [None, None]
            L.append(f"| {k} | {w['onsets']} | {w['detected']} / {w['missed']} | {pct(w['share_ge15'])} / {pct(w['share_ge30'])} / "
                     f"{pct(w['share_ge60'])} | {f(w['fa_per_observed_day'])} | {f(w['precision'])} | {pct(w['time_in_warning'])} | "
                     f"{f(w['episode_minutes_median'])} min | {f(w['lead_median'])} ({f(iq[0])}–{f(iq[1])}) min |")
        rg = d.get("release_guardrails")
        if rg:
            L += ["", f"Release guardrails vs R0 (false alarms ≤ +0.10/day, time in warning ≤ +2 pt, warned ≥ 30 min ≥ −2 pt): "
                  f"**{'passed' if rg['passed'] else 'not met'}** ({rg['fa_per_day_delta']:+.2f}/day, "
                  f"{rg['time_in_warning_delta_points']:+.1f} pt, {rg['warned30_delta_points']:+.1f} pt).", ""]
    L += ["## 80 % ranges (calibrated on each fold's calibration people for the exact procedure)", "",
          "| Procedure | 30 min coverage (width) | 60 min coverage (width) | 60 min per-person range | 60 min rising > 2 / steady |", "|---|---|---|---|---|"]
    for k, r in d["ranges"].items():
        L.append(f"| {k} | {pct(r['30']['coverage'])} ({f(r['30']['width_mean'])}) | {pct(r['60']['coverage'])} ({f(r['60']['width_mean'])}) | "
                 f"{pct(r['60']['per_person_min'])}–{pct(r['60']['per_person_max'])} | {pct(r['60']['rise_fast'])} / {pct(r['60']['steady'])} |")
    L += ["", "## Choices per outer fold (inner folds only)", "", "| Fold | Selected | J0 30 / 60 | J1 30 / 60 | J2 30 / 60 |", "|---|---|---|---|---|"]
    for fold, v in d["choices"].items():
        cell = lambda fam, v=v: "incomplete" if v[fam].get("incomplete") else " / ".join(  # noqa: E731
            f"#{v[fam][h]['config']} {v[fam][h]['policy']} ({v[fam][h]['inner_final_mae']:.2f})" for h in ("30", "60"))
        L.append(f"| {fold} | {v['selected_family']} | {cell('J0')} | {cell('J1')} | {cell('J2')} |")
    L += ["", "Regenerate: `uv run python scripts/joint_study.py render`. Raw numbers: "
          f"`{PROTO['artifacts']['root']}/summary.json`.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run()
    elif cmd == "render":
        REPORT.write_text(render(json.loads((OUT / "summary.json").read_text())))
    else:
        sys.exit(__doc__)
