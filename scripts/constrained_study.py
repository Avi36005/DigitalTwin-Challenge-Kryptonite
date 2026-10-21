"""Peak-aware, constrained personalised selection study gt-constrained-2026-10-21 (decision D-053).

Inside each outer fold of gt-2h-2026-10-20, using DEVELOPMENT people only: fit LightGBM (32 configurations per horizon:
4 regularisation templates x current / +history features x unweighted / future-high-weighted loss x L2 / L1) and
CatBoost (16) with early stopping on purged training-people tails, choose configuration and patient correction on the
inner personalised error under a high-target limit and a 0.5 mg/dL gain requirement against the freshly fitted serving
recipe R0, keep at most 3 candidates per horizon and family (<= 9 pairs), and choose the pair and its warning threshold
under absolute and R0-P-relative workload limits. Then ONE frozen predictor per fold (development people only) is
calibrated on the reserved calibration people and scored once on the assessment people. See the protocol YAML.

Usage:  uv run python scripts/constrained_study.py run        # fresh run (refuses if a run already exists)
        uv run python scripts/constrained_study.py resume     # continue an interrupted run (identical hashes only)
        uv run python scripts/constrained_study.py render     # rewrite the report from summary.json
        uv run python scripts/constrained_study.py validate   # check locks, hashes, identities and saved artifacts
"""

from __future__ import annotations

import dataclasses
import json
import math
import sys
import tempfile
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glucotwin.config import fingerprint  # noqa: E402
from glucotwin.research import metrics as M  # noqa: E402
from glucotwin.research import warnings as W  # noqa: E402
from glucotwin.research.calibration import CalibrationError, finite_sample_quantile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROTO_PATH = ROOT / "configs/experiments/gt-constrained-2026-10-21.yaml"
PROTO = yaml.safe_load(PROTO_PATH.read_text())
OUT = ROOT / PROTO["artifacts"]["root"]
REPORT = ROOT / PROTO["artifacts"]["report"]
SEED = int(PROTO["random_seed"])
THREADS = int(PROTO["threads"])
HS = [30, 60]
CADENCE = 5.0
HIGH = 180.0
THR_GRID = [float(x) for x in range(-30, 31, 5)]
POLICIES: list[tuple[str, int | None, int | None]] = [("off", None, None)] + [
    (f"k{k}_hl{hl}", k, hl) for k in (24, 48, 96, 192) for hl in (120, 240, 720)]
NBOOT = 2000
# selection / gate constants (protocol)
GAIN_MIN = 0.5
HIGH_MAX = 1.0
W30_MAX = 0.25
AVAIL_MAX_PTS = 0.5
TIE = 0.005
FA_MAX, TIW_MAX = 1.5, 0.12
REL_FA, REL_TIW, REL_S30 = 0.10, 0.02, 0.02
FA_SECOND = 1.0
SERVING_MARGIN = -10.0
EPS = 1e-9
ES_PATIENCE, ES_MAX = 200, 3000
TAIL_FRAC, PURGE = 0.2, 142.5
HIGH_SUPPORT, HIGH_SUPPORT_FALLBACK = 50, 20
SLOPE_BINS = ("falling", "steady", "rising", "rapid")
SCALE_MIN_N, SCALE_MIN_P, SCALE_CLIP = 200, 3, (0.5, 2.5)
LOG = OUT / "progress.log"

LGB_TEMPLATES = {
    "T1": {"learning_rate": 0.03, "num_leaves": 15, "max_depth": 4, "min_leaf_pe": 0.10, "lambda_l1": 0.0,
           "lambda_l2": 10.0, "feature_fraction": 0.8, "bagging_fraction": 0.8},
    "T2": {"learning_rate": 0.03, "num_leaves": 31, "max_depth": 6, "min_leaf_pe": 0.25, "lambda_l1": 1.0,
           "lambda_l2": 20.0, "feature_fraction": 0.7, "bagging_fraction": 0.7},
    "T3": {"learning_rate": 0.02, "num_leaves": 7, "max_depth": 3, "min_leaf_pe": 0.50, "lambda_l1": 5.0,
           "lambda_l2": 50.0, "feature_fraction": 0.6, "bagging_fraction": 0.6},
}
CB_TEMPLATES = {
    "C0": {"learning_rate": 0.05, "depth": 6, "l2_leaf_reg": 3.0, "rsm": 1.0},
    "C1": {"learning_rate": 0.05, "depth": 4, "l2_leaf_reg": 10.0, "rsm": 0.8},
    "C2": {"learning_rate": 0.03, "depth": 8, "l2_leaf_reg": 10.0, "rsm": 0.8, "min_leaf_pe": 0.10, "grow_policy": "Depthwise"},
    "C3": {"learning_rate": 0.03, "depth": 5, "l2_leaf_reg": 30.0, "rsm": 0.6},
}
FAMILY_RANK = {"lightgbm": 0, "catboost": 1}


def log(msg: str) -> None:
    line = f"{datetime.now(UTC).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


# ===================================================================================================== configurations


def lgb_configs(serving: dict[int, dict], h: int) -> list[dict]:
    """32 LightGBM configurations for horizon h: template x feature set x weight x objective (objective fastest)."""
    out = []
    t0 = {k: serving[h]["params"][k] for k in ("learning_rate", "num_leaves", "max_depth", "min_child_samples",
                                                "lambda_l2", "feature_fraction", "bagging_fraction")}
    templates = {"T0": {**t0, "lambda_l1": 0.0}, **LGB_TEMPLATES}
    for ti, (tn, tp) in enumerate(templates.items()):
        for fs in ("F0", "F1"):
            for wp in ("W1", "WP"):
                for obj in ("l2", "l1"):
                    out.append({"family": "lightgbm", "template": tn, "template_index": ti, "features": fs, "weights": wp,
                                "objective": obj, "params": dict(tp)})
    for i, c in enumerate(out):
        c["index"] = i
        c["id"] = f"lgb-{c['template']}-{c['features']}-{c['weights']}-{c['objective']}"
    return out


def cb_configs() -> list[dict]:
    out = []
    for ti, (tn, tp) in enumerate(CB_TEMPLATES.items()):
        for fs in ("F0", "F1"):
            for wp in ("W1", "WP"):
                out.append({"family": "catboost", "template": tn, "template_index": ti, "features": fs, "weights": wp,
                            "objective": "rmse", "params": dict(tp)})
    for i, c in enumerate(out):
        c["index"] = i
        c["id"] = f"cb-{c['template']}-{c['features']}-{c['weights']}"
    return out


def simplicity_key(c: dict) -> tuple:
    """Declared order: F0 < F1, W1 < WP, l2 < l1, lower template, correction off < on, smaller k, shorter half-life."""
    if c.get("r0"):
        return (-1,)
    k = c.get("k")
    return (c["features"] != "F0", c["weights"] != "W1", c["objective"] == "l1", c["template_index"],
            k is not None, k or 0, c.get("half_life") or 0)


# ===================================================================================================== pure helpers


def peak_weights(y_abs: np.ndarray, policy: str) -> np.ndarray | None:
    """Training-loss weights from the fit's OWN training labels. W1 -> None (unweighted). WP -> 1 + I(absolute future
    glucose > 180), normalised to mean 1 over these rows. Uses the absolute target, never the delta."""
    if policy == "W1":
        return None
    if policy != "WP":
        raise ValueError(f"unknown weight policy {policy}")
    y = np.asarray(y_abs, float)
    if not np.all(np.isfinite(y)):
        raise ValueError("training targets must be finite")
    w = 1.0 + (y > HIGH).astype(float)
    return w / w.mean()


def min_leaf(person_equivalents: float, n_rows: int, n_people: int) -> int:
    return max(1, int(math.ceil(person_equivalents * n_rows / max(1, n_people))))


def head_tail(origins: np.ndarray, pids: np.ndarray, rows: np.ndarray, frac: float = TAIL_FRAC,
              purge: float = PURGE) -> tuple[np.ndarray, np.ndarray]:
    """Per training person: tail = last ``frac`` of the elapsed span; head = origins at least ``purge`` min before it."""
    head, tail = np.zeros(len(origins), bool), np.zeros(len(origins), bool)
    for pid in pd.unique(pids[rows]):
        r = rows & (pids == pid)
        lo, hi = origins[r].min(), origins[r].max()
        start = lo + (1 - frac) * (hi - lo)
        tail |= r & (origins >= start)
        head |= r & (origins + purge < start)
    return head, tail


def _macro_feval(groups: np.ndarray):
    _, inv = np.unique(groups, return_inverse=True)
    cnt = np.bincount(inv)

    def feval(preds, data):
        e = np.abs(preds - data.get_label())
        return "macro_mae", float(np.mean(np.bincount(inv, weights=e) / cnt)), False
    return feval


def _model_hash_lgb(b) -> str:
    return sha256(b.model_to_string().encode()).hexdigest()


def _model_hash_cb(m) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "m.cbm"
        m.save_model(str(p))
        return sha256(p.read_bytes()).hexdigest()


def _lgb_params(cfg: dict, n_rows: int, n_people: int, seed: int) -> dict:
    p = dict(cfg["params"])
    pe = p.pop("min_leaf_pe", None)
    if pe is not None:
        p["min_data_in_leaf"] = min_leaf(pe, n_rows, n_people)
    return {"boosting": "gbdt", "objective": "regression" if cfg["objective"] == "l2" else "regression_l1",
            "metric": "None", "verbosity": -1, "seed": seed, "deterministic": True, "force_row_wise": True,
            "num_threads": THREADS, "bagging_freq": 1, "feature_pre_filter": False, **p}


def _cb_model(cfg: dict, n_rows: int, n_people: int, seed: int, iterations: int, stopping: bool):
    from catboost import CatBoostRegressor

    p = dict(cfg["params"])
    pe = p.pop("min_leaf_pe", None)
    if pe is not None:
        p["min_data_in_leaf"] = min_leaf(pe, n_rows, n_people)
    kw = {"eval_metric": "MAE", "od_type": "Iter", "od_wait": ES_PATIENCE, "use_best_model": True} if stopping else {}
    return CatBoostRegressor(loss_function="RMSE", iterations=iterations, random_seed=seed, verbose=False,
                             thread_count=THREADS, allow_writing_files=False, nan_mode="Min", **p, **kw)


class FittedPredictor:
    """A frozen fitted population model (delta target) with its identity."""

    def __init__(self, family: str, model: Any, columns: list[str], rounds: int, train_people: list[str], cfg_id: str,
                 info: dict):
        self.family, self.model, self.columns, self.rounds = family, model, list(columns), int(rounds)
        self.train_people = sorted(train_people)
        self.cfg_id = cfg_id
        self.info = info
        self.model_hash = _model_hash_lgb(model) if family == "lightgbm" else _model_hash_cb(model)

    def predict_delta(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict(X), float)

    def identity(self, policy_hash: str, feature_hash: str) -> dict:
        return {"predictor_sha256": self.model_hash, "family": self.family, "config": self.cfg_id, "rounds": self.rounds,
                "feature_hash": feature_hash, "training_participants_hash": fingerprint(self.train_people),
                "correction_policy_hash": policy_hash}


def fit_tree(cfg: dict, X: np.ndarray, y_delta: np.ndarray, y_abs: np.ndarray, pids: np.ndarray, origins: np.ndarray,
             train_rows: np.ndarray, seed: int, columns: list[str], rounds: int | None = None,
             early_stop: bool = True) -> tuple[FittedPredictor | None, dict]:
    """Fit one tree model on ``train_rows`` only. With ``rounds`` None and ``early_stop``: early-stopping pass on the
    head rows validated on the purged tails of the SAME training people, then a refit on all training rows with the
    best iteration. With ``rounds``: one fit with that fixed count. Weights come from the training rows' absolute
    targets only. Returns (predictor or None on failure, info)."""
    t0 = time.time()
    fam = cfg["family"]
    train_people = sorted(pd.unique(pids[train_rows]).tolist())
    info: dict[str, Any] = {"config": cfg["id"], "seed": seed, "train_people": len(train_people),
                            "train_rows": int(train_rows.sum()), "training_participants_hash": fingerprint(train_people)}
    try:
        if not train_rows.any() or not np.all(np.isfinite(y_delta[train_rows])):
            raise ValueError("empty training set or nonfinite training targets")
        best = None
        if rounds is None:
            if not early_stop:
                raise ValueError("rounds required without early stopping")
            head, tail = head_tail(origins, pids, train_rows)
            if fam == "lightgbm":
                import lightgbm as lgb

                hp = _lgb_params(cfg, int(head.sum()), len(train_people), seed)
                dtr = lgb.Dataset(X[head], label=y_delta[head], weight=peak_weights(y_abs[head], cfg["weights"]),
                                  params={"feature_pre_filter": False}, free_raw_data=False)
                dva = lgb.Dataset(X[tail], label=y_delta[tail], reference=dtr)
                b = lgb.train(hp, dtr, num_boost_round=ES_MAX, valid_sets=[dva], feval=_macro_feval(pids[tail]),
                              callbacks=[lgb.early_stopping(ES_PATIENCE, verbose=False)])
                best = int(b.best_iteration or b.current_iteration())
            else:
                m = _cb_model(cfg, int(head.sum()), len(train_people), seed, ES_MAX, True)
                m.fit(X[head], y_delta[head], sample_weight=peak_weights(y_abs[head], cfg["weights"]),
                      eval_set=(X[tail], y_delta[tail]))
                best = int(m.get_best_iteration()) + 1
            rounds = max(1, best)
        info["best_iteration"] = best
        info["rounds"] = int(rounds)
        w = peak_weights(y_abs[train_rows], cfg["weights"])
        if fam == "lightgbm":
            import lightgbm as lgb

            p = _lgb_params(cfg, int(train_rows.sum()), len(train_people), seed)
            model = lgb.train(p, lgb.Dataset(X[train_rows], label=y_delta[train_rows], weight=w,
                                              params={"feature_pre_filter": False}, free_raw_data=False),
                              num_boost_round=int(rounds))
            info["min_data_in_leaf"] = p.get("min_data_in_leaf", p.get("min_child_samples"))
        else:
            model = _cb_model(cfg, int(train_rows.sum()), len(train_people), seed, int(rounds), False)
            model.fit(X[train_rows], y_delta[train_rows], sample_weight=w)
        fp = FittedPredictor(fam, model, columns, int(rounds), train_people, cfg["id"], info)
        info["model_sha256"] = fp.model_hash
        info["weight_mean"] = None if w is None else float(w.mean())
        info["seconds"] = round(time.time() - t0, 3)
        return fp, info
    except Exception as exc:  # recorded and penalised by the caller, never silently dropped
        info["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        info["seconds"] = round(time.time() - t0, 3)
        return None, info


def macro_mae(pred: np.ndarray, y: np.ndarray, pids: np.ndarray, mask: np.ndarray) -> float | None:
    m = mask & np.isfinite(pred) & np.isfinite(y)
    if not m.any():
        return None
    return float(pd.Series(np.abs(pred[m] - y[m])).groupby(pids[m]).mean().mean())


def pooled_mae(pred: np.ndarray, y: np.ndarray, mask: np.ndarray) -> float | None:
    m = mask & np.isfinite(pred) & np.isfinite(y)
    return float(np.mean(np.abs(pred[m] - y[m]))) if m.any() else None


def high_support(y: np.ndarray, pids: np.ndarray, mask: np.ndarray, min_n: int = HIGH_SUPPORT,
                 fallback_n: int | None = HIGH_SUPPORT_FALLBACK, min_people: int = 2) -> tuple[np.ndarray, int]:
    """Mask of origins with target > 180 among people with >= min_n such origins (fallback threshold if fewer than
    ``min_people`` qualify). Defined from targets only, so it is the same for every candidate."""
    hi = mask & np.isfinite(y) & (y > HIGH)
    cnt = pd.Series(pids[hi]).value_counts()
    ok = cnt[cnt >= min_n].index
    used = min_n
    if len(ok) < min_people and fallback_n is not None:
        ok, used = cnt[cnt >= fallback_n].index, fallback_n
    return hi & np.isin(pids, list(ok)), used


def availability(pred: np.ndarray, rows: np.ndarray) -> float:
    return float(np.isfinite(pred[rows]).mean()) if rows.any() else 0.0


def check_feasible(c: dict, r0: dict, h: int) -> tuple[bool, list[str]]:
    """Inner development filters for an alternative (c) versus R0 (r0) at horizon h."""
    why = []
    if c.get("failed"):
        why.append("fit failed in this fold")
    if c.get("mae") is None:
        why.append("no score")
    if c.get("high") is None or r0.get("high") is None:
        why.append("high-target endpoint undefined")
    if 100 * (r0["avail"] - c.get("avail", 0.0)) > AVAIL_MAX_PTS + EPS:
        why.append("availability drop > 0.5 pt")
    if not why:
        if h == 60:
            if r0["mae"] - c["mae"] < GAIN_MIN - EPS:
                why.append("60-min gain < 0.5")
        else:
            if c["mae"] - r0["mae"] > W30_MAX + EPS:
                why.append("30-min worsening > 0.25")
        if c["high"] - r0["high"] > HIGH_MAX + EPS:
            why.append("high-target worsening > 1.0")
    return (not why), why


def pick(cands: list[dict]) -> dict | None:
    """Lowest MAE; candidates within TIE of it are broken by the simplicity key."""
    if not cands:
        return None
    best = min(c["mae"] for c in cands)
    return sorted([c for c in cands if c["mae"] <= best + TIE + EPS], key=simplicity_key)[0]


def retain(cands: list[dict], n: int = 3) -> list[dict]:
    """Feasible candidates -> best policy per configuration -> the n best configurations (deterministic)."""
    by_cfg: dict[str, list[dict]] = {}
    for c in cands:
        if c.get("feasible"):
            by_cfg.setdefault(c["config"], []).append(c)
    per = [pick(v) for v in by_cfg.values()]
    out: list[dict] = []
    while per and len(out) < n:
        b = pick(per)
        out.append(b)
        per = [c for c in per if c is not b]
    return out


def make_pairs(short30: list[dict], short60: list[dict], r0_30: dict) -> list[tuple[dict, dict]]:
    if not short60:
        return []
    s30 = short30 if short30 else [r0_30]
    return [(a, b) for a in s30 for b in short60]


def exposure_steps(origins: np.ndarray, pids: np.ndarray, base: np.ndarray, cadence: float = CADENCE) -> np.ndarray:
    """Per-origin gap-respecting exposure on the ``base`` set: min(next base origin of the same person - t, cadence);
    zero outside ``base``."""
    step = np.zeros(len(origins))
    idx = np.where(base)[0]
    if not idx.size:
        return step
    order = idx[np.lexsort((origins[idx], pids[idx]))]
    o, p = origins[order], pids[order]
    nxt = np.append(o[1:], np.inf)
    same = np.append(p[1:] == p[:-1], False)
    step[order] = np.where(same, np.minimum(nxt - o, cadence), cadence)
    return step


def warn_metrics(t: pd.DataFrame, rows: np.ndarray, issued: np.ndarray, final: dict[int, np.ndarray],
                 thr: float | None, per_person: bool = False) -> dict:
    """Warning accounting for one threshold on ``rows``. None threshold = no warning policy (reported, zero recall)."""
    pids = t["patient_id"].to_numpy()
    o = t["origin"].to_numpy(float)
    elig = t["ew_eligible"].to_numpy(bool)
    lab = t["label_60"].to_numpy(float)
    sc = W.scores(final, 60) if thr is not None else np.full(len(t), np.nan)  # None: no warning policy at all
    s, per = W.evaluate(t, rows, issued, sc, 60, 0.0 if thr is None else thr, 30.0, CADENCE)
    base = rows & issued & elig & np.isfinite(lab)
    step = exposure_steps(o, pids, base)
    fire = base & np.isfinite(sc) & (sc >= (np.inf if thr is None else thr))
    on = s["true_onsets"]
    leads = s["_qualified_leads"]
    fa = s["false_alarm_episodes"]
    obs_days = s["observed_forecastable_hours"] / 24.0
    out = {"threshold": thr, "onsets": on, "detected": s["detected_onsets"], "missed": on - s["detected_onsets"],
           "episodes": s["warning_episodes"], "assessable": s["assessable_warnings"], "censored": s["censored_warnings"],
           "false_alarms": fa, "observed_days": obs_days, "fa_day": (fa / obs_days) if obs_days > 0 else None,
           "precision": s["precision"], "fired_min": float(step[fire].sum()), "eligible_min": float(step.sum()),
           "tiw": float(step[fire].sum() / step.sum()) if step.sum() > 0 else None,
           "ge15": sum(x >= 15 for x in leads), "ge30": sum(x >= 30 for x in leads), "ge60": sum(x >= 60 for x in leads),
           "nonempty": bool(s["assessable_warnings"] > 0)}
    for k in (15, 30, 60):
        out[f"share{k}"] = out[f"ge{k}"] / on if on else None
    if per_person:
        out["per_person"] = {}
        for pid, r in per.items():
            pp = pids == pid
            out["per_person"][str(pid)] = {
                "onsets": len(r.detectable_onsets), "detected": r.matched_onsets, "false_alarms": r.false_alarms,
                "censored": r.unresolved, "episodes": len(r.episodes),
                "assessable": len(r.episodes) - r.unresolved,
                "observed_min": M.exposure_minutes(o, pids, rows & issued & pp, CADENCE),
                "fired_min": float(step[fire & pp].sum()), "eligible_min": float(step[pp].sum()),
                "ge15": sum(x >= 15 for x in r.qualified_leads), "ge30": sum(x >= 30 for x in r.qualified_leads),
                "ge60": sum(x >= 60 for x in r.qualified_leads), "leads": [float(x) for x in r.qualified_leads],
                "durations": [float(ep["last"] - ep["start"] + CADENCE) for ep in r.episodes]}
    return out


def choose_threshold(curve: list[dict], fa_max: float = FA_MAX, tiw_max: float = TIW_MAX,
                     ref: dict | None = None) -> dict | None:
    """Max share30 subject to nonempty, FA/day <= fa_max, time in warning <= tiw_max (and, with ``ref``, the
    R0-P-relative limits). Ties: lower FA/day, lower time in warning, higher threshold. None when nothing is feasible."""
    ok = []
    for r in curve:
        if not r["nonempty"] or not r["onsets"] or r["fa_day"] is None or r["tiw"] is None or r["share30"] is None:
            continue
        if r["fa_day"] > fa_max + EPS or r["tiw"] > tiw_max + EPS:
            continue
        if ref is not None and (r["fa_day"] > ref["fa_day"] + REL_FA + EPS or r["tiw"] > ref["tiw"] + REL_TIW + EPS
                                or r["share30"] < ref["share30"] - REL_S30 - EPS):
            continue
        ok.append(r)
    if not ok:
        return None
    return sorted(ok, key=lambda r: (-r["share30"], r["fa_day"], r["tiw"], -r["threshold"]))[0]


def select_pair(items: list[dict]) -> dict | None:
    """items: {"warn": chosen threshold row, "mae60", "mae30", "family", "key60", "key30", ...}. Banded hierarchy."""
    if not items:
        return None
    best = max(i["warn"]["share30"] for i in items)
    c = [i for i in items if i["warn"]["share30"] >= best - 0.01 - EPS]
    lo = min(i["warn"]["fa_day"] for i in c)
    c = [i for i in c if i["warn"]["fa_day"] <= lo + 0.05 + EPS]
    lo = min(i["warn"]["tiw"] for i in c)
    c = [i for i in c if i["warn"]["tiw"] <= lo + 0.005 + EPS]
    return sorted(c, key=lambda i: (i["mae60"], i["mae30"], FAMILY_RANK[i["family"]], i["key60"], i["key30"]))[0]


def point_gate(mean_diff_60: float | None, ci95_60: list | None, worsening_30: float | None,
               high_worsening_60: float | None, availability_drop_points: float | None) -> dict:
    vals = [mean_diff_60, worsening_30, high_worsening_60, availability_drop_points]
    ci_ok = ci95_60 is not None and ci95_60[1] is not None
    checks = {
        "mean_diff_60": mean_diff_60 is not None and mean_diff_60 <= -GAIN_MIN + EPS,
        "ci95_upper_below_0": ci_ok and ci95_60[1] < 0,
        "worsening_30": worsening_30 is not None and worsening_30 <= W30_MAX + EPS,
        "high_worsening_60": high_worsening_60 is not None and high_worsening_60 <= HIGH_MAX + EPS,
        "availability_drop": availability_drop_points is not None and availability_drop_points <= AVAIL_MAX_PTS + EPS}
    return {"values": {"mean_diff_60": mean_diff_60, "ci95_60": ci95_60, "worsening_30": worsening_30,
                       "high_worsening_60": high_worsening_60, "availability_drop_points": availability_drop_points},
            "checks": checks, "passed": bool(all(checks.values()) and None not in vals)}


def operational_gate(s: dict | None, r: dict | None) -> dict:
    keys = ("fa_day", "tiw", "share30")
    if s is None or r is None or any(s.get(k) is None or r.get(k) is None for k in keys) or not r.get("onsets") \
            or not s.get("nonempty"):
        return {"values": None, "checks": {"defined": False}, "passed": False}
    v = {"fa_per_day_delta": s["fa_day"] - r["fa_day"], "time_in_warning_delta_points": 100 * (s["tiw"] - r["tiw"]),
         "share30_delta_points": 100 * (s["share30"] - r["share30"])}
    checks = {"fa_per_day": v["fa_per_day_delta"] <= REL_FA + EPS,
              "time_in_warning": v["time_in_warning_delta_points"] <= 100 * REL_TIW + EPS,
              "share30": v["share30_delta_points"] >= -100 * REL_S30 - EPS}
    return {"values": v, "checks": checks, "passed": bool(all(checks.values()))}


def range_gate(sel: dict, r0: dict) -> dict:
    """sel / r0: {"identity_ok", "finite_ok", "30": {coverage, per_person_min, width_mean, rapid: {coverage, n, people}},
    "60": {...}}."""
    checks: dict[str, bool] = {"identity": bool(sel.get("identity_ok")), "finite": bool(sel.get("finite_ok"))}
    for h in ("30", "60"):
        a, b = sel.get(h) or {}, r0.get(h) or {}
        cov, pmin, wa, wb = a.get("coverage"), a.get("per_person_min"), a.get("width_mean"), b.get("width_mean")
        checks[f"coverage_{h}"] = cov is not None and 0.75 - EPS <= cov <= 0.85 + EPS
        checks[f"per_person_min_{h}"] = pmin is not None and pmin >= 0.55 - EPS
        checks[f"width_{h}"] = wa is not None and wb is not None and wa <= 1.15 * wb + EPS
    ra, rb = (sel.get("60") or {}).get("rapid") or {}, (r0.get("60") or {}).get("rapid") or {}
    supported = ra.get("n", 0) >= 200 and ra.get("people", 0) >= 3
    checks["rapid_rise_60"] = bool(supported and ra.get("coverage") is not None and rb.get("coverage") is not None
                                   and ra["coverage"] >= rb["coverage"] - 0.05 - EPS)
    return {"checks": checks, "passed": bool(all(checks.values()))}


def slope_bin(slope: np.ndarray) -> np.ndarray:
    s = np.asarray(slope, float)
    out = np.full(len(s), "unknown", dtype=object)
    out[s < -1] = "falling"
    out[(s >= -1) & (s <= 1)] = "steady"
    out[(s > 1) & (s <= 2)] = "rising"
    out[s > 2] = "rapid"
    return out


def trend_scale(dev_abs_resid: np.ndarray, dev_slope: np.ndarray, dev_pids: np.ndarray) -> dict[str, float]:
    """Scale per past-slope bin from DEVELOPMENT residuals only (mean in bin / overall mean); unsupported -> 1.0."""
    r = np.asarray(dev_abs_resid, float)
    ok = np.isfinite(r)
    overall = float(r[ok].mean()) if ok.any() else float("nan")
    b = slope_bin(dev_slope)
    out = {}
    for name in SLOPE_BINS:
        m = ok & (b == name)
        if m.sum() < SCALE_MIN_N or pd.Series(dev_pids[m]).nunique() < SCALE_MIN_P or not np.isfinite(overall) or overall <= 0:
            out[name] = 1.0
        else:
            out[name] = float(np.clip(r[m].mean() / overall, *SCALE_CLIP))
    out["unknown"] = 1.0
    return out


def scale_of(slope: np.ndarray, scales: dict[str, float]) -> np.ndarray:
    return np.array([scales[b] for b in slope_bin(slope)], float)


def calibrate(cal_abs_resid: np.ndarray, identity: dict, cal_scale: np.ndarray | None = None) -> dict:
    """80 % split-conformal record for ONE frozen predictor+policy (primary global; optional trend-scaled)."""
    q, k, n = finite_sample_quantile(cal_abs_resid, 0.8)
    rec = {"identity": identity, "identity_hash": fingerprint(identity), "global_q": q, "rank": k, "n": n}
    if cal_scale is not None:
        qs, ks, ns = finite_sample_quantile(np.asarray(cal_abs_resid, float) / cal_scale, 0.8)
        rec.update({"scaled_q": qs, "scaled_rank": ks, "scaled_n": ns})
    rec["calibration_hash"] = fingerprint({k: v for k, v in rec.items() if k != "identity"})
    return rec


def check_identity(cal: dict, identity: dict) -> None:
    """Refuse to apply a calibration to any other predictor, policy, transform or training-participant set."""
    if cal.get("identity_hash") != fingerprint(identity):
        diff = sorted(k for k in set(cal.get("identity", {})) | set(identity)
                      if cal.get("identity", {}).get(k) != identity.get(k))
        raise CalibrationError(f"calibration made for a different predictor (differs in {diff}); refusing it")


def bands(final: np.ndarray, cal: dict, identity: dict, scale: np.ndarray | None = None) -> dict[str, np.ndarray]:
    check_identity(cal, identity)
    q = cal.get("global_q")
    lo = final - q if q is not None else np.full(len(final), np.nan)
    hi = final + q if q is not None else np.full(len(final), np.nan)
    out = {"lower": lo, "upper": hi}
    if scale is not None:
        qs = cal.get("scaled_q")
        half = qs * scale if qs is not None else np.full(len(final), np.nan)
        out["lower_ts"], out["upper_ts"] = final - half, final + half
    return out


def file_hashes(paths: list[Path]) -> dict[str, str]:
    def name(p: Path) -> str:
        return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
    return {name(p): sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}


def code_paths() -> list[Path]:
    return [Path(__file__).resolve(), ROOT / "scripts/retrain_study.py", ROOT / "ml/glucotwin/research/history.py",
            ROOT / "ml/glucotwin/research/adapt.py", ROOT / "ml/glucotwin/research/warnings.py",
            ROOT / "ml/glucotwin/research/calibration.py", ROOT / "ml/glucotwin/research/metrics.py",
            ROOT / "ml/glucotwin/evaluation/alerts.py", ROOT / "ml/glucotwin/models/adaptation.py"]


def check_roles(plan, train_people: list[str], purpose: str) -> None:
    """Every fit/selection call may only see development people of its plan."""
    bad = set(train_people) - set(plan.development)
    if bad:
        raise RuntimeError(f"{plan.fold} {purpose}: non-development people {sorted(bad)} would enter a fit")


# ===================================================================================================== the study


class Constrained:
    def __init__(self):
        import retrain_study as R  # heavy: data, history features, frozen serving recipe
        from glucotwin.research import adapt
        from glucotwin.research.history import COLUMNS as HIST
        from glucotwin.research.protocol import load_frozen, research_dir

        self.R, self.adapt = R, adapt
        self.s = R.Study()
        self.t, self.pids, self.issued = self.s.t, self.s.pids, self.s.issued
        self.o = self.t["origin"].to_numpy(float)
        self.g = self.t["g_last"].to_numpy(float)
        self.y = {h: self.t[f"target_{h}"].to_numpy(float) for h in HS}
        self.slope = self.t["slope_15"].to_numpy(float)
        self.cols = {"F0": list(self.s.base_cols), "F1": list(self.s.base_cols) + list(HIST)}
        self.Xn = {k: self.s.X[c].to_numpy(float) for k, c in self.cols.items()}
        self.feature_hash = {k: fingerprint({"columns": c, "history_module": sha256((ROOT / "ml/glucotwin/research/history.py").read_bytes()).hexdigest(),
                                             "table_cache_key": self._table_key(research_dir)}) for k, c in self.cols.items()}
        self.rec = R.recipe()
        self.cfgs = {h: lgb_configs(self.rec, h) + cb_configs() for h in HS}
        self.plans = self.s.plans
        self.split_hash = load_frozen(R.BASE)["split_hash"]
        self.fit_log: list[dict] = []
        self.failures: list[dict] = []

    @staticmethod
    def _table_key(research_dir) -> str:
        import retrain_study as R
        return json.loads((research_dir(R.BASE) / "tables" / f"{R.TRACK}__cgmacros.json").read_text())["cache_key"]

    # ---------------------------------------------------------------- basic operations
    def r0_cfg(self, h: int) -> dict:
        return {"family": "lightgbm", "template": "R0", "template_index": -1, "features": "F0", "weights": "W1",
                "objective": "l2", "id": f"R0-{h}", "index": -1,
                "params": {k: v for k, v in self.rec[h]["params"].items()}, "r0": True}

    def policy(self, k, hl):
        return self.adapt.make_policy(self.s.ctx.proto, self.R.TRACK, k or 96, hl or 240, enabled=k is not None)

    def policy_hash(self, k, hl) -> str:
        return fingerprint(dataclasses.asdict(self.policy(k, hl)))

    def personalise(self, pop: np.ndarray, h: int, rows: np.ndarray, k, hl) -> np.ndarray:
        if k is None:
            return np.where(rows, pop, np.nan)
        corr, _ = self.adapt.prequential(self.t, self.s.ctx.td.prep, rows, {h: pop}, self.policy(k, hl), [h])
        return np.where(rows, self.adapt.apply({h: pop}, corr)[h], np.nan)

    def fit(self, cfg: dict, h: int, train_people: list[str], plan, scope: str, rounds: int | None = None):
        check_roles(plan, train_people, f"{scope} {cfg['id']}")
        yd = self.y[h] - self.g
        rows = np.isin(self.pids, list(train_people)) & self.issued & np.isfinite(yd)
        fp, info = fit_tree(cfg, self.Xn[cfg["features"]], yd, self.y[h], self.pids, self.o, rows, SEED + h,
                            self.cols[cfg["features"]], rounds=rounds, early_stop=rounds is None)
        info.update({"fold": plan.fold, "scope": scope, "horizon": h, "family": cfg["family"]})
        self.fit_log.append(info)
        if fp is None:
            self.failures.append(info)
            log(f"FIT FAILED {plan.fold} {scope} {cfg['id']} h{h}: {info.get('error')}")
        return fp, info

    def predict(self, fp: FittedPredictor | None, cfg: dict, rows: np.ndarray) -> np.ndarray:
        out = np.full(len(self.t), np.nan)
        if fp is not None and rows.any():
            p = self.g[rows] + fp.predict_delta(self.Xn[cfg["features"]][rows])
            out[rows] = np.where(np.isfinite(p), p, np.nan)
        return out

    def inner_oof(self, cfg: dict, h: int, plan) -> tuple[np.ndarray, list, bool]:
        dev = list(plan.development)
        oof = np.full(len(self.t), np.nan)
        best, failed = [], False
        for k, inner in enumerate(plan.inner):
            te = np.isin(self.pids, list(inner)) & self.issued
            rounds = self.rec[h]["rounds"] if cfg.get("r0") else None
            fp, info = self.fit(cfg, h, [p for p in dev if p not in inner], plan, f"inner-{k + 1}", rounds)
            if fp is None:
                failed = True
                continue
            best.append(info.get("best_iteration"))
            pr = self.predict(fp, cfg, te)
            if not np.all(np.isfinite(pr[te])):
                failed = True
            oof = np.where(te, pr, oof)
        return oof, best, failed

    # ---------------------------------------------------------------- development (inner folds only)
    def develop_fold(self, plan) -> tuple[dict, dict[str, np.ndarray]]:
        t0 = time.time()
        dev = list(plan.development)
        devrows = np.isin(self.pids, dev) & self.issued
        arrays: dict[str, np.ndarray] = {}
        hsup = {h: high_support(self.y[h], self.pids, devrows)[0] for h in HS}

        def score(fin, h):
            m = devrows & np.isfinite(self.y[h])
            return {"mae": macro_mae(fin, self.y[h], self.pids, m), "high": macro_mae(fin, self.y[h], self.pids, hsup[h]),
                    "avail": availability(fin, devrows)}

        # R0 inner (its own correction k96/hl240)
        r0 = {}
        for h in HS:
            oof, _, failed = self.inner_oof(self.r0_cfg(h), h, plan)
            fin = self.personalise(oof, h, devrows, 96, 240)
            r0[h] = {**score(fin, h), "failed": failed, "config": f"R0-{h}", "policy": "k96_hl240", "k": 96,
                     "half_life": 240, "r0": True, "family": "lightgbm"}
            arrays[f"R0_pop_{h}"], arrays[f"R0_final_{h}"] = oof, fin
        # all candidates
        table, best_iters, pops = [], {}, {}
        for h in HS:
            for cfg in self.cfgs[h]:
                oof, best, failed = self.inner_oof(cfg, h, plan)
                best_iters[f"{cfg['id']}|{h}"] = best
                pops[(cfg["id"], h)] = oof
                for name, k, hl in POLICIES:
                    fin = oof if failed else self.personalise(oof, h, devrows, k, hl)
                    sc = score(fin, h) if not failed else {"mae": None, "high": None, "avail": availability(oof, devrows)}
                    c = {"family": cfg["family"], "config": cfg["id"], "config_index": cfg["index"], "horizon": h,
                         "template": cfg["template"], "template_index": cfg["template_index"],
                         "features": cfg["features"], "weights": cfg["weights"], "objective": cfg["objective"],
                         "policy": name, "k": k, "half_life": hl, "failed": failed, **sc}
                    c["feasible"], c["why"] = check_feasible(c, r0[h], h)
                    table.append(c)
            log(f"{plan.fold} h{h} candidates scored ({time.time() - t0:.0f}s)")
        # retention per family/horizon; exact arrays of the retained winners
        short = {}
        for fam in ("lightgbm", "catboost"):
            for h in HS:
                short[(fam, h)] = retain([c for c in table if c["family"] == fam and c["horizon"] == h])
        retained = {}
        for (_fam, h), lst in short.items():
            for c in lst:
                cid = f"{c['config']}|{c['policy']}|{h}"
                fin = self.personalise(pops[(c["config"], h)], h, devrows, c["k"], c["half_life"])
                assert abs(score(fin, h)["mae"] - c["mae"]) < 1e-9, "retained prediction does not reproduce its score"
                arrays[f"cand_{cid}"] = fin
                retained[cid] = c
        # warning policy: R0-P
        r0_curve = [warn_metrics(self.t, devrows, self.issued, {30: arrays["R0_final_30"], 60: arrays["R0_final_60"]}, th)
                    for th in THR_GRID]
        r0p = choose_threshold(r0_curve)
        r0p_fallback = r0p is None
        if r0p_fallback:
            r0p = warn_metrics(self.t, devrows, self.issued, {30: arrays["R0_final_30"], 60: arrays["R0_final_60"]},
                               SERVING_MARGIN)
        r0_1day = choose_threshold(r0_curve, FA_SECOND)
        # pairs
        items, pair_docs = [], []
        r0_30 = {**r0[30], "id": "R0_30"}
        for fam in ("lightgbm", "catboost"):
            for a, b in make_pairs(short[(fam, 30)], short[(fam, 60)], r0_30):
                ida = "R0_30" if a.get("r0") else f"{a['config']}|{a['policy']}|30"
                idb = f"{b['config']}|{b['policy']}|60"
                f30 = arrays["R0_final_30"] if a.get("r0") else arrays[f"cand_{ida}"]
                curve = [warn_metrics(self.t, devrows, self.issued, {30: f30, 60: arrays[f"cand_{idb}"]}, th)
                         for th in THR_GRID]
                ch = choose_threshold(curve, ref=r0p)
                doc = {"family": fam, "m30": ida, "m60": idb, "mae30": a["mae"], "mae60": b["mae"],
                       "warn": ch, "curve": curve, "feasible_warning": ch is not None}
                pair_docs.append(doc)
                if ch is not None:
                    items.append({**doc, "key60": simplicity_key(b), "key30": simplicity_key(a)})
        sel = select_pair(items)
        if sel is None:
            selected = {"fallback": True, "family": None, "m30": "R0_30", "m60": "R0_60", "threshold": r0p["threshold"],
                        "inner_warn": r0p}
        else:
            selected = {"fallback": False, "family": sel["family"], "m30": sel["m30"], "m60": sel["m60"],
                        "threshold": sel["warn"]["threshold"], "inner_warn": sel["warn"],
                        "mae30": sel["mae30"], "mae60": sel["mae60"]}
        s30 = arrays["R0_final_30"] if selected["m30"] == "R0_30" else arrays[f"cand_{selected['m30']}"]
        s60 = arrays["R0_final_60"] if selected["m60"] == "R0_60" else arrays[f"cand_{selected['m60']}"]
        s_curve = [warn_metrics(self.t, devrows, self.issued, {30: s30, 60: s60}, th) for th in THR_GRID]
        s_1day = choose_threshold(s_curve, FA_SECOND)
        arrays["S_final_30"], arrays["S_final_60"] = s30, s60
        doc = {"fold": plan.fold, "development": dev, "calibration": list(plan.calibration),
               "assessment_people_count": len(plan.assessment), "inner": [list(x) for x in plan.inner],
               "r0_inner": {str(h): {k: v for k, v in r0[h].items()} for h in HS},
               "high_support_people": {str(h): int(pd.Series(self.pids[hsup[h]]).nunique()) for h in HS},
               "candidates": table, "best_iterations": best_iters,
               "shortlists": {f"{fam}|{h}": [f"{c['config']}|{c['policy']}" for c in lst] for (fam, h), lst in short.items()},
               "retained": retained, "pairs": [{k: v for k, v in p.items() if k != "curve"} | {"curve": p["curve"]} for p in pair_docs],
               "r0p": {"threshold": r0p["threshold"], "fallback": r0p_fallback, "inner_warn": r0p, "curve": r0_curve},
               "r0_1day": r0_1day, "s_1day": s_1day, "s_curve": s_curve, "selected": selected,
               "seconds": round(time.time() - t0, 1)}
        log(f"{plan.fold} development done in {doc['seconds']}s: selected "
            f"{'R0 fallback' if selected['fallback'] else selected['family'] + ' ' + selected['m30'] + ' + ' + selected['m60']}"
            f", threshold {selected['threshold']}; R0-P threshold {r0p['threshold']}")
        return doc, arrays

    # ---------------------------------------------------------------- outer: one frozen predictor -> calibration + assessment
    def member_cfg(self, mid: str, h: int) -> tuple[dict, int | None, int | None]:
        if mid in ("R0_30", "R0_60"):
            return self.r0_cfg(h), 96, 240
        cid, pol, _ = mid.split("|")
        cfg = next(c for c in self.cfgs[h] if c["id"] == cid)
        k, hl = next((k, hl) for n, k, hl in POLICIES if n == pol)
        return cfg, k, hl

    def assess_fold(self, plan, ddoc: dict, darr: dict) -> tuple[dict, dict[str, np.ndarray]]:
        t0 = time.time()
        dev = list(plan.development)
        devrows = np.isin(self.pids, dev) & self.issued
        cal = np.isin(self.pids, list(plan.calibration)) & self.issued
        ass = np.isin(self.pids, list(plan.assessment)) & self.issued
        assert not (set(plan.development) & (set(plan.calibration) | set(plan.assessment)))
        assert not (set(plan.calibration) & set(plan.assessment))
        sel = ddoc["selected"]
        arrays: dict[str, np.ndarray] = {}
        fitted: dict[tuple, FittedPredictor] = {}
        doc: dict[str, Any] = {"fold": plan.fold, "selected": sel, "procedures": {}}
        members = {"R0": {30: "R0_30", 60: "R0_60"}, "S": {30: sel["m30"], 60: sel["m60"]}}
        for h in HS:  # fit every needed predictor ONCE on development people; an S member failure -> declared R0 fallback
            for proc in ("R0", "S"):
                cfg, _, _ = self.member_cfg(members[proc][h], h)
                key = (cfg["id"], h)
                if key in fitted:
                    continue
                rounds = self.rec[h]["rounds"] if cfg.get("r0") else int(np.median(ddoc["best_iterations"][f"{cfg['id']}|{h}"]))
                fp, info = self.fit(cfg, h, dev, plan, "outer", rounds)
                if fp is None:
                    if cfg.get("r0"):
                        raise RuntimeError(f"R0 outer fit failed for h{h}: {info.get('error')}")
                    log(f"{plan.fold} S member {cfg['id']} failed in the outer fit -> R0 fallback for this fold")
                    members["S"] = {30: "R0_30", 60: "R0_60"}
                    doc["outer_fit_failed_fallback"] = info
                    continue
                fitted[key] = fp
        if doc.get("outer_fit_failed_fallback"):
            doc["selected"] = sel = {**sel, "fallback": True, "m30": "R0_30", "m60": "R0_60",
                                     "threshold": ddoc["r0p"]["threshold"]}
        for proc, mem in members.items():
            pdoc = {}
            for h in HS:
                cfg, k, hl = self.member_cfg(mem[h], h)
                key = (cfg["id"], h)
                fp = fitted[key]
                both = cal | ass
                pop = self.predict(fp, cfg, both)  # the SAME frozen predictor for calibration and assessment people
                fin = self.personalise(pop, h, both, k, hl)
                ident = fp.identity(self.policy_hash(k, hl), self.feature_hash[cfg["features"]])
                # trend-scaled range: scales from development inner OOF residuals of this exact member procedure
                dev_fin = darr[f"{'R0' if doc.get('outer_fit_failed_fallback') else proc}_final_{h}"]
                dres = np.abs(self.y[h] - dev_fin)
                dm = devrows & np.isfinite(dres)
                scales = trend_scale(dres[dm], self.slope[dm], self.pids[dm])
                cm = cal & np.isfinite(fin) & np.isfinite(self.y[h])
                crec = calibrate(np.abs(self.y[h] - fin)[cm], ident, scale_of(self.slope[cm], scales))
                b = bands(np.where(ass, fin, np.nan), crec, fp.identity(self.policy_hash(k, hl),
                                                                         self.feature_hash[cfg["features"]]),
                          scale_of(self.slope, scales))
                arrays[f"{proc}_pop_{h}"] = np.where(ass, pop, np.nan)
                arrays[f"{proc}_final_{h}"] = np.where(ass, fin, np.nan)
                for nm, v in b.items():
                    arrays[f"{proc}_{nm}_{h}"] = np.where(ass, v, np.nan)
                pdoc[str(h)] = {"member": mem[h], "config": cfg["id"], "rounds": fp.rounds, "policy_k": k,
                                "policy_half_life": hl, "identity": ident, "calibration": crec, "scales": scales,
                                "identity_checked": True}
            doc["procedures"][proc] = pdoc
        # baselines on identical rows
        arrays["persistence_final_30"] = np.where(ass, self.g, np.nan)
        arrays["persistence_final_60"] = np.where(ass, self.g, np.nan)
        from glucotwin.models.population import LinearTrendModel
        trend = {}
        for h in HS:
            best = None
            for w in (15, 30):
                for d in (0.25, 0.5, 0.75, 1.0):
                    mod = LinearTrendModel(h, w, d, 120.0)
                    pr = self.g + mod.predict_delta(self.t)
                    sc = macro_mae(pr, self.y[h], self.pids, devrows)
                    if best is None or sc < best[0] - 1e-12:
                        best = (sc, w, d, pr)
            trend[str(h)] = {"window": best[1], "damping": best[2], "dev_mae": best[0]}
            arrays[f"linear_trend_final_{h}"] = np.where(ass, best[3], np.nan)
        doc["linear_trend"] = trend
        # warnings on assessment people (thresholds from development only)
        fin = lambda p: {h: arrays[f"{p}_final_{h}"] for h in HS}  # noqa: E731
        doc["warnings"] = {
            "S": warn_metrics(self.t, ass, self.issued, fin("S"), sel["threshold"], True),
            "R0-P": warn_metrics(self.t, ass, self.issued, fin("R0"), ddoc["r0p"]["threshold"], True),
            "R0-serving-threshold": warn_metrics(self.t, ass, self.issued, fin("R0"), SERVING_MARGIN, True),
            "S-1day": warn_metrics(self.t, ass, self.issued, fin("S"), (ddoc["s_1day"] or {}).get("threshold"), True)
            if ddoc["s_1day"] else None,
            "R0-1day": warn_metrics(self.t, ass, self.issued, fin("R0"), (ddoc["r0_1day"] or {}).get("threshold"), True)
            if ddoc["r0_1day"] else None}
        doc["seconds"] = round(time.time() - t0, 1)
        log(f"{plan.fold} assessed in {doc['seconds']}s")
        return doc, arrays


# ===================================================================================================== orchestration


def hashes(st: Constrained | None = None) -> dict:
    import retrain_study as R
    from glucotwin.research.protocol import load_frozen, research_dir

    return {"protocol_sha256": sha256(PROTO_PATH.read_bytes()).hexdigest(),
            "code_sha256": fingerprint(file_hashes(code_paths())),
            "split_hash": load_frozen(R.BASE)["split_hash"], "table_cache_key": Constrained._table_key(research_dir)}


def _env() -> dict:
    import catboost
    import lightgbm
    import retrain_study as R
    return {**{k: v for k, v in R.env().items() if k != "protocol_sha256"}, "catboost": catboost.__version__, "lightgbm": lightgbm.__version__, "threads": THREADS}


def _save_arrays(path: Path, arrays: dict[str, np.ndarray]) -> None:
    np.savez_compressed(path, **{k.replace("|", "__"): v for k, v in arrays.items()})


def _load_arrays(path: Path) -> dict[str, np.ndarray]:
    z = np.load(path)
    return {k.replace("__", "|"): z[k] for k in z.files}


def run(resume: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    man_p = OUT / "run_manifest.json"
    h_now = hashes()
    if man_p.exists() and not resume:
        sys.exit("A run already exists; use `resume` (identical hashes only) or `render`.")
    if resume:
        if not man_p.exists():
            sys.exit("Nothing to resume.")
        man = json.loads(man_p.read_text())
        diff = [k for k in h_now if man["hashes"].get(k) != h_now[k]]
        if diff:
            sys.exit(f"Refusing to resume: {diff} changed since the run started. Mark the run invalid and start a "
                     "separately labelled rerun instead.")
        log(f"resume requested; hashes match ({h_now['protocol_sha256'][:12]})")
    else:
        man = {"experiment_id": PROTO["experiment_id"], "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
               "hashes": h_now, "env": _env(), "code_files": file_hashes(code_paths())}
        man_p.write_text(json.dumps(man, indent=1))
        log(f"run started; protocol {h_now['protocol_sha256'][:12]} code {h_now['code_sha256']}")
    st = Constrained()
    plans = [p for p in st.plans if p.fold != "final"]
    (OUT / "development").mkdir(exist_ok=True)
    (OUT / "assessment").mkdir(exist_ok=True)
    counts = json.loads((OUT / "fit_counts.json").read_text()) if (OUT / "fit_counts.json").exists() else {"segments": []}
    # ---- phase 1: development choices for every fold (no calibration or assessment label is read)
    for p in plans:
        jp = OUT / "development" / f"{p.fold}.json"
        if jp.exists():
            log(f"{p.fold} development already saved; reused unchanged")
            continue
        n0, s0 = len(st.fit_log), time.time()
        doc, arr = st.develop_fold(p)
        _save_arrays(OUT / "development" / f"{p.fold}.npz", arr)
        jp.write_text(json.dumps(doc, default=float))
        counts["segments"].append({"phase": "development", "fold": p.fold, "fits": len(st.fit_log) - n0,
                                   "fit_seconds": round(sum(f["seconds"] for f in st.fit_log[n0:]), 1),
                                   "wall_seconds": round(time.time() - s0, 1),
                                   "failures": sum(1 for f in st.fit_log[n0:] if "error" in f)})
        _append_fits(st.fit_log[n0:])
        (OUT / "fit_counts.json").write_text(json.dumps(counts, indent=1))
    dc = OUT / "development_complete.json"
    if not dc.exists():
        dc.write_text(json.dumps({"completed_at": datetime.now(UTC).isoformat(timespec="seconds"), "hashes": h_now,
                                  "files": file_hashes(sorted((OUT / "development").glob("*")))}, indent=1))
        log("development complete for all folds (choices frozen)")
    # ---- phase 2: assessment (lock first)
    lock = OUT / "assessment_opened.json"
    if not lock.exists():
        lock.write_text(json.dumps({"opened_at": datetime.now(UTC).isoformat(timespec="seconds"), "hashes": h_now},
                                   indent=1))
        log("assessment lock written; outer folds opened")
    for p in plans:
        jp = OUT / "assessment" / f"{p.fold}.json"
        if jp.exists():
            log(f"{p.fold} assessment already saved; reused unchanged")
            continue
        ddoc = json.loads((OUT / "development" / f"{p.fold}.json").read_text())
        darr = _load_arrays(OUT / "development" / f"{p.fold}.npz")
        n0, s0 = len(st.fit_log), time.time()
        doc, arr = st.assess_fold(p, ddoc, darr)
        _save_arrays(OUT / "assessment" / f"{p.fold}.npz", arr)
        jp.write_text(json.dumps(doc, default=float))
        counts["segments"].append({"phase": "assessment", "fold": p.fold, "fits": len(st.fit_log) - n0,
                                   "fit_seconds": round(sum(f["seconds"] for f in st.fit_log[n0:]), 1),
                                   "wall_seconds": round(time.time() - s0, 1),
                                   "failures": sum(1 for f in st.fit_log[n0:] if "error" in f)})
        _append_fits(st.fit_log[n0:])
        (OUT / "fit_counts.json").write_text(json.dumps(counts, indent=1))
    summary = summarise(st, plans)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    REPORT.write_text(render(summary))
    log("summary saved and report rendered")


def _append_fits(rows: list[dict]) -> None:
    with (OUT / "fits.jsonl").open("a") as f:
        for r in rows:
            f.write(json.dumps(r, default=float) + "\n")


def summarise(st: Constrained, plans) -> dict:
    t, pids = st.t, st.pids
    arr = {k: np.full(len(t), np.nan) for k in ()}
    folds, ddocs = {}, {}
    rows = np.zeros(len(t), bool)
    for p in plans:
        a = _load_arrays(OUT / "assessment" / f"{p.fold}.npz")
        m = np.isin(pids, list(p.assessment)) & st.issued
        rows |= m
        for k, v in a.items():
            arr.setdefault(k, np.full(len(t), np.nan))
            arr[k] = np.where(m, v, arr[k])
        folds[p.fold] = json.loads((OUT / "assessment" / f"{p.fold}.json").read_text())
        ddocs[p.fold] = json.loads((OUT / "development" / f"{p.fold}.json").read_text())
    procs = ["S", "R0", "persistence", "linear_trend"]
    out: dict[str, Any] = {"procedures": {}, "paired": {}, "per_person": {}}
    el = t["elapsed_min"].to_numpy(float)
    s = st.slope
    long = []
    for h in HS:
        y = st.y[h]
        common = rows & np.isfinite(y) & np.all([np.isfinite(arr[f"{p}_final_{h}"]) for p in procs], axis=0)
        hi, used = high_support(y, pids, common, fallback_n=None)
        for p in procs:
            f = arr[f"{p}_final_{h}"]
            pop = arr.get(f"{p}_pop_{h}", f)
            m = common
            himask = common & (y > HIGH)
            out["procedures"].setdefault(p, {})[str(h)] = {
                "mae": macro_mae(f, y, pids, m), "mae_pooled": pooled_mae(f, y, m),
                "rmse_macro": float(M.per_participant_rmse(f, y, pids, m).mean()),
                "mae_population": macro_mae(pop, y, pids, m), "mae_high": macro_mae(f, y, pids, hi),
                "signed_bias_high": float(np.mean(f[himask] - y[himask])) if himask.any() else None,
                "mae_rise_fast": macro_mae(f, y, pids, m & (s > 2)), "mae_rise_1": macro_mae(f, y, pids, m & (s > 1)),
                "mae_steady": macro_mae(f, y, pids, m & (np.abs(s) <= 1)), "mae_falling": macro_mae(f, y, pids, m & (s < -1)),
                "mae_first_day": macro_mae(f, y, pids, m & (el < 1440)), "origins": int(m.sum()),
                "availability": availability(f, rows)}
            long.append(pd.DataFrame({"patient_id": pids[rows], "origin": t["origin"].to_numpy(float)[rows],
                                      "horizon": h, "procedure": p, "target": y[rows], "population": pop[rows],
                                      "final": f[rows],
                                      **({"lower": arr[f"{p}_lower_{h}"][rows], "upper": arr[f"{p}_upper_{h}"][rows],
                                          "lower_ts": arr[f"{p}_lower_ts_{h}"][rows], "upper_ts": arr[f"{p}_upper_ts_{h}"][rows]}
                                         if p in ("S", "R0") else {})}))
        out["high_target_people"] = out.get("high_target_people", {}) | {str(h): int(pd.Series(pids[hi]).nunique())}
        out.setdefault("common_origins", {})[str(h)] = int(common.sum())
        for a, b in (("S", "R0"), ("S", "persistence"), ("R0", "persistence"), ("S", "linear_trend")):
            for mode in ("final", "pop"):
                if mode == "pop" and b in ("persistence", "linear_trend"):
                    continue
                ser = {x: pd.Series(np.abs(arr.get(f"{x}_{mode}_{h}", arr[f"{x}_final_{h}"])[common] - y[common])).groupby(pids[common]).mean()
                       for x in (a, b)}
                r = M.paired_bootstrap(ser[a], ser[b], NBOOT, SEED + h)
                out["paired"][f"{a}|{b}|{mode}|{h}"] = {k: r[k] for k in ("mean_diff", "ci95", "improved", "worsened", "n_participants")}
                if (a, b, mode) == ("S", "R0", "final"):
                    out["per_person"][str(h)] = {str(k): float(v) for k, v in (ser[a] - ser[b]).items()}
    pd.concat(long).to_parquet(OUT / "assessment_predictions.parquet", index=False)
    P = out["procedures"]
    g = out["paired"]["S|R0|final|60"]
    avail_drop = max(100 * (P["R0"][str(h)]["availability"] - P["S"][str(h)]["availability"]) for h in HS)
    out["primary_gate"] = point_gate(g["mean_diff"], g["ci95"], P["S"]["30"]["mae"] - P["R0"]["30"]["mae"],
                                     (P["S"]["60"]["mae_high"] - P["R0"]["60"]["mae_high"])
                                     if P["S"]["60"]["mae_high"] is not None and P["R0"]["60"]["mae_high"] is not None else None,
                                     avail_drop)
    # warnings pooled over folds (per-person raw counts)
    out["warnings"] = {}
    for name in ("S", "R0-P", "R0-serving-threshold", "S-1day", "R0-1day"):
        per = {}
        thr = {}
        for f, d in folds.items():
            w = d["warnings"].get(name)
            if w is None:
                continue
            per.update(w["per_person"])
            thr[f] = w["threshold"]
        out["warnings"][name] = pool_warn(per) | {"thresholds": thr, "folds_with_policy": len(thr)}
    out["operational_gate"] = operational_gate(out["warnings"]["S"], out["warnings"]["R0-P"])
    # ranges
    out["ranges"] = {}
    for p in ("S", "R0"):
        rr = {"identity_ok": all(f["procedures"][p][str(h)]["identity_checked"] for f in folds.values() for h in HS)}
        fin_ok = True
        for h in HS:
            y = st.y[h]
            f = arr[f"{p}_final_{h}"]
            for kind in ("", "_ts"):
                lo, up = arr[f"{p}_lower{kind}_{h}"], arr[f"{p}_upper{kind}_{h}"]
                m = rows & np.isfinite(y) & np.isfinite(f)
                if kind == "" and not np.all(np.isfinite(lo[m]) & np.isfinite(up[m]) & (lo[m] <= f[m]) & (f[m] <= up[m])):
                    fin_ok = False
                ok = m & np.isfinite(lo) & np.isfinite(up)
                hit = (y >= lo) & (y <= up)
                per = pd.Series(hit[ok]).groupby(pids[ok]).mean()
                def strat(mask, ok=ok, hit=hit, lo=lo, up=up):
                    mm = ok & mask
                    return {"coverage": float(hit[mm].mean()) if mm.any() else None, "n": int(mm.sum()),
                            "people": int(pd.Series(pids[mm]).nunique()),
                            "width_mean": float((up - lo)[mm].mean()) if mm.any() else None}
                rr.setdefault(f"{h}{kind}", {}).update({
                    "coverage": float(hit[ok].mean()) if ok.any() else None,
                    "coverage_macro": float(per.mean()) if len(per) else None,
                    "per_person_min": float(per.min()) if len(per) else None,
                    "per_person_max": float(per.max()) if len(per) else None,
                    "width_mean": float((up - lo)[ok].mean()) if ok.any() else None,
                    "available": int(ok.sum()), "unavailable": int((m & ~ok).sum()),
                    "rapid": strat(s > 2), "rising_gt1": strat(s > 1), "steady": strat(np.abs(s) <= 1),
                    "falling": strat(s < -1), "first_day": strat(el < 1440)})
        rr["finite_ok"] = fin_ok
        rr["30"], rr["60"] = rr.pop("30"), rr.pop("60")
        out["ranges"][p] = rr
    out["range_gate"] = range_gate(out["ranges"]["S"], out["ranges"]["R0"])
    out["all_gates_passed"] = bool(out["primary_gate"]["passed"] and out["operational_gate"]["passed"]
                                   and out["range_gate"]["passed"])
    man = json.loads((OUT / "run_manifest.json").read_text())
    counts = json.loads((OUT / "fit_counts.json").read_text())
    fits = [json.loads(x) for x in (OUT / "fits.jsonl").read_text().splitlines()]
    out.update({
        "experiment_id": PROTO["experiment_id"], "decision": PROTO["decision"], "manifest": man,
        "development_complete": json.loads((OUT / "development_complete.json").read_text()),
        "assessment_opened": json.loads((OUT / "assessment_opened.json").read_text()),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "fit_totals": {"fits": len(fits), "lightgbm": sum(f["family"] == "lightgbm" for f in fits),
                       "catboost": sum(f["family"] == "catboost" for f in fits),
                       "failures": sum("error" in f for f in fits),
                       "fit_seconds": round(sum(f["seconds"] for f in fits), 1),
                       "wall_seconds": round(sum(s_["wall_seconds"] for s_ in counts["segments"]), 1)},
        "failures": [f for f in fits if "error" in f],
        "fold_choices": {f: {"selected": d["selected"] | {"inner_warn": {k: v for k, v in d["selected"]["inner_warn"].items()
                                                                          if k != "per_person"}},
                             "r0p_threshold": d["r0p"]["threshold"], "r0p_fallback": d["r0p"]["fallback"],
                             "r0_1day_threshold": (d["r0_1day"] or {}).get("threshold"),
                             "s_1day_threshold": (d["s_1day"] or {}).get("threshold"),
                             "shortlists": d["shortlists"], "r0_inner": d["r0_inner"],
                             "feasible_candidates": {f"{fam}|{h}": sum(1 for c in d["candidates"] if c["feasible"]
                                                                       and c["family"] == fam and c["horizon"] == h)
                                                     for fam in ("lightgbm", "catboost") for h in HS},
                             "pairs": len(d["pairs"]), "pairs_with_feasible_warning": sum(p_["feasible_warning"] for p_ in d["pairs"])}
                         for f, d in ddocs.items()},
        "outer_identities": {f: {p: {h: d["procedures"][p][h]["identity"] | {"calibration_hash": d["procedures"][p][h]["calibration"]["calibration_hash"],
                                                                            "global_q": d["procedures"][p][h]["calibration"]["global_q"],
                                                                            "n": d["procedures"][p][h]["calibration"]["n"]}
                                     for h in ("30", "60")} for p in ("S", "R0")} for f, d in folds.items()},
        "linear_trend_choices": {f: d["linear_trend"] for f, d in folds.items()},
        "artifact_sha256": file_hashes(sorted(OUT.glob("**/*.npz")) + sorted(OUT.glob("**/*.parquet"))
                                       + sorted((OUT / "development").glob("*.json")) + sorted((OUT / "assessment").glob("*.json")))})
    pd.DataFrame([c | {"fold": f} for f, d in ddocs.items() for c in d["candidates"]]).drop(columns=["why"]).assign(
        why=[";".join(c["why"]) for d in ddocs.values() for c in d["candidates"]]).to_parquet(OUT / "inner_scores.parquet", index=False)
    (OUT / "fold_choices.json").write_text(json.dumps(out["fold_choices"], indent=1, default=float))
    (OUT / "failures.json").write_text(json.dumps(out["failures"], indent=1, default=float))
    return out


def pool_warn(per: dict) -> dict:
    v = list(per.values())
    if not v:
        return {"defined": False, "fa_day": None, "tiw": None, "share30": None, "onsets": 0, "nonempty": False}
    on = sum(x["onsets"] for x in v)
    days = sum(x["observed_min"] for x in v) / 1440.0
    ass = sum(x["assessable"] for x in v)
    fa = sum(x["false_alarms"] for x in v)
    elig = sum(x["eligible_min"] for x in v)
    leads = [y for x in v for y in x["leads"]]
    dur = [y for x in v for y in x["durations"]]
    return {"defined": True, "onsets": on, "detected": sum(x["detected"] for x in v),
            "missed": on - sum(x["detected"] for x in v), "episodes": sum(x["episodes"] for x in v),
            "assessable": ass, "censored": sum(x["censored"] for x in v), "nonempty": ass > 0,
            "share15": sum(x["ge15"] for x in v) / on if on else None,
            "share30": sum(x["ge30"] for x in v) / on if on else None,
            "share60": sum(x["ge60"] for x in v) / on if on else None, "false_alarms": fa,
            "observed_days": days, "fa_day": fa / days if days else None,
            "precision": (ass - fa) / ass if ass else None,
            "tiw": sum(x["fired_min"] for x in v) / elig if elig else None,
            "episode_minutes_median": float(np.median(dur)) if dur else None,
            "episode_minutes_p90": float(np.percentile(dur, 90)) if dur else None,
            "lead_median": float(np.median(leads)) if leads else None,
            "lead_iqr": [float(np.percentile(leads, 25)), float(np.percentile(leads, 75))] if leads else None,
            "per_person_share30": {k: (x["ge30"] / x["onsets"] if x["onsets"] else None) for k, x in per.items()},
            "per_person_fa_day": {k: (x["false_alarms"] / (x["observed_min"] / 1440.0) if x["observed_min"] else None)
                                  for k, x in per.items()}}


# ===================================================================================================== report


def render(d: dict) -> str:
    def f(x, n=2):
        return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{n}f}"

    def pct(x):
        return "—" if x is None else f"{100 * x:.1f} %"

    def ci(r):
        return f"{r['mean_diff']:+.2f} [{r['ci95'][0]:+.2f}, {r['ci95'][1]:+.2f}]" if r and r.get("mean_diff") is not None else "—"

    P, man = d["procedures"], d["manifest"]
    ft = d["fit_totals"]
    pg, og, rg = d["primary_gate"], d["operational_gate"], d["range_gate"]
    names = {"S": "**S — constrained selected procedure**", "R0": "R0 — refitted serving recipe (and R0-P points)",
             "persistence": "Persistence", "linear_trend": "Bounded linear trend (window/damping chosen on development)"}
    L = [f"# Peak-aware constrained selection — `{d['experiment_id']}` ({d['decision']})", "",
         f"Protocol committed before any formal fit (sha256 `{man['hashes']['protocol_sha256'][:12]}`, code "
         f"`{man['env']['git_head'][:7]}`); run started {man['started_at']} UTC; development choices for all folds "
         f"frozen {d['development_complete']['completed_at']}; outer folds opened {d['assessment_opened']['opened_at']}; "
         f"finished {d['finished_at']}. Fresh fits: {ft['fits']:,} (LightGBM {ft['lightgbm']:,}, CatBoost "
         f"{ft['catboost']:,}), {ft['fit_seconds']:.0f} s fitting, {ft['wall_seconds']:.0f} s wall; failures "
         f"{ft['failures']}. LightGBM {man['env']['lightgbm']}, CatBoost {man['env']['catboost']}, split "
         f"`{man['hashes']['split_hash']}`.", "",
         "Roles: every fit, early-stopping tail, configuration/correction/family choice, trend scale and warning threshold "
         "used outer **development** people only; the 2 calibration people per fold were used only for range quantiles of "
         "the same frozen predictor that was then scored on the assessment people. Motivation: D-052's already-seen "
         "high-target (+1.70) and workload failures and its mixed-fit range calibration. The 14 people were inspected in "
         "earlier studies: internal validation, not independent confirmation. Absolute MAE is not comparable with D-052 "
         "(9–10 fitting people per fold here instead of 11–12); the matched comparison below is authoritative.", "",
         "## Matched assessment table (macro per-participant MAE, mg/dL; identical issued origins)", "",
         "| Procedure | 60 min | 30 min | 60 min pooled | 60 min population | 60 min, target > 180 | signed bias > 180 | rising > 2 | steady | falling | first 24 h | availability 30 / 60 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, n in names.items():
        a, b = P[k]["60"], P[k]["30"]
        L.append(f"| {n} | **{f(a['mae'])}** | {f(b['mae'])} | {f(a['mae_pooled'])} | {f(a['mae_population'])} | "
                 f"{f(a['mae_high'])} | {f(a['signed_bias_high'], 1)} | {f(a['mae_rise_fast'])} | {f(a['mae_steady'])} | "
                 f"{f(a['mae_falling'])} | {f(a['mae_first_day'])} | {pct(b['availability'])} / {pct(a['availability'])} |")
    pp = d["paired"]
    L += ["", f"Common origins: {d['common_origins']['30']:,} (30 min), {d['common_origins']['60']:,} (60 min); high-target "
          f"column: people with ≥ 50 such origins ({d['high_target_people']['60']} at 60 min).", "",
          "## Paired differences (first minus second; negative = lower error; 95 % participant bootstrap, 2,000 resamples)", "",
          "| Comparison | 60 min personalised | 60 min population only | 30 min personalised | people better (60) |", "|---|---|---|---|---|"]
    for a, b in (("S", "R0"), ("S", "persistence"), ("R0", "persistence"), ("S", "linear_trend")):
        r60, r30 = pp[f"{a}|{b}|final|60"], pp[f"{a}|{b}|final|30"]
        rp = pp.get(f"{a}|{b}|pop|60")
        L.append(f"| {a} vs {b} | {ci(r60)} | {ci(rp) if rp else '—'} | {ci(r30)} | {r60['improved']} of {r60['n_participants']} |")
    v = pg["values"]
    L += ["", f"**Primary point gate (S vs R0): {'PASSED' if pg['passed'] else 'NOT MET'}** — 60-min difference "
          f"{f(v['mean_diff_60'])} (≤ −0.50: {'yes' if pg['checks']['mean_diff_60'] else 'no'}), interval upper "
          f"{f(v['ci95_60'][1] if v['ci95_60'] else None)} (< 0: {'yes' if pg['checks']['ci95_upper_below_0'] else 'no'}); "
          f"30-min change {f(v['worsening_30'])} (≤ +0.25: {'yes' if pg['checks']['worsening_30'] else 'no'}); "
          f"high-target change {f(v['high_worsening_60'])} (≤ +1.0: {'yes' if pg['checks']['high_worsening_60'] else 'no'}); "
          f"availability drop {f(v['availability_drop_points'])} pt (≤ 0.5: {'yes' if pg['checks']['availability_drop'] else 'no'}).", "",
          "## 60-minute warning on assessment people (thresholds chosen on development inner folds per outer fold)", "",
          "| Policy | Thresholds by fold | Onsets | Detected / missed | Warned ≥ 15 / 30 / 60 min (all onsets) | False alarms / observed day | Precision | Time in warning | Episode median (p90) | Qualified lead median (IQR) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for k, w in d["warnings"].items():
        if not w.get("defined"):
            L.append(f"| {k} | no feasible development policy | — | — | — | — | — | — | — | — |")
            continue
        iq = w["lead_iqr"] or [None, None]
        L.append(f"| {k} | {', '.join(f(x, 0) for x in w['thresholds'].values())} | {w['onsets']} | {w['detected']} / {w['missed']} | "
                 f"{pct(w['share15'])} / {pct(w['share30'])} / {pct(w['share60'])} | {f(w['fa_day'])} | {f(w['precision'])} | "
                 f"{pct(w['tiw'])} | {f(w['episode_minutes_median'], 0)} ({f(w['episode_minutes_p90'], 0)}) min | "
                 f"{f(w['lead_median'], 0)} ({f(iq[0], 0)}–{f(iq[1], 0)}) min |")
    ov = og["values"] or {}
    L += ["", "False alarms per observed day use gap-respecting exposure of issued origins; time in warning uses the same "
          "step on eligible issued origins with a resolved label; censored warnings are unresolved, never false alarms. "
          "S-1day / R0-1day: development-selected ≈ 1 false alarm/day operating points (reported only). "
          "R0-serving-threshold: the serving margin −10 (reported only).", "",
          f"**Operational gate (S vs R0-P): {'PASSED' if og['passed'] else 'NOT MET'}** — false alarms "
          f"{f(ov.get('fa_per_day_delta'))}/day (≤ +0.10), time in warning {f(ov.get('time_in_warning_delta_points'), 1)} pt "
          f"(≤ +2.0), warned ≥ 30 min {f(ov.get('share30_delta_points'), 1)} pt (≥ −2.0).", "",
          "## 80 % ranges (one frozen predictor per fold: calibrated on its calibration people, scored on assessment people)", "",
          "| Procedure | Method | 30 min coverage (mean width) | 60 min coverage (mean width) | 60 min per person | 60 min rising > 2 | rising > 1 | steady | falling | first 24 h |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for p in ("S", "R0"):
        r = d["ranges"][p]
        for kind, label in (("", "global split-conformal (primary)"), ("_ts", "past-trend-scaled (secondary)")):
            a, b = r[f"30{kind}"] if kind else r["30"], r[f"60{kind}"] if kind else r["60"]
            L.append(f"| {p} | {label} | {pct(a['coverage'])} ({f(a['width_mean'], 1)}) | {pct(b['coverage'])} ({f(b['width_mean'], 1)}) | "
                     f"{pct(b['per_person_min'])}–{pct(b['per_person_max'])} | {pct(b['rapid']['coverage'])} (n {b['rapid']['n']}) | "
                     f"{pct(b['rising_gt1']['coverage'])} | {pct(b['steady']['coverage'])} | {pct(b['falling']['coverage'])} | "
                     f"{pct(b['first_day']['coverage'])} |")
    L += ["", f"**Range guardrails (primary range of S): {'PASSED' if rg['passed'] else 'NOT MET'}** — "
          + ", ".join(f"{k} {'yes' if ok else 'no'}" for k, ok in rg["checks"].items()) + ". Empirical coverage over "
          "overlapping windows of few people is not an individual guarantee.", "",
          f"## All gates: **{'PASSED' if d['all_gates_passed'] else 'NOT MET'}**", "",
          "## Development choices per outer fold (inner folds only)", "",
          "| Fold | Selected | 30-min member | 60-min member | threshold (S / R0-P) | feasible candidates LGB 30/60, CB 30/60 | pairs (with feasible warning) |",
          "|---|---|---|---|---|---|---|"]
    for fold, c in d["fold_choices"].items():
        s_ = c["selected"]
        fc = c["feasible_candidates"]
        L.append(f"| {fold} | {'R0 fallback' if s_['fallback'] else s_['family']} | `{s_['m30']}` | `{s_['m60']}` | "
                 f"{f(s_['threshold'], 0)} / {f(c['r0p_threshold'], 0)}{' (fallback)' if c['r0p_fallback'] else ''} | "
                 f"{fc['lightgbm|30']}/{fc['lightgbm|60']}, {fc['catboost|30']}/{fc['catboost|60']} | {c['pairs']} ({c['pairs_with_feasible_warning']}) |")
    L += ["", "Regenerate: `uv run python scripts/constrained_study.py render`; check: `uv run python "
          "scripts/constrained_study.py validate`. Raw numbers: "
          f"`{PROTO['artifacts']['root']}/summary.json`, inner scores `inner_scores.parquet`, predictions "
          "`assessment_predictions.parquet`.", ""]
    return "\n".join(L)


# ===================================================================================================== validate


def validate() -> int:
    problems = []
    man = json.loads((OUT / "run_manifest.json").read_text())
    if man["hashes"]["protocol_sha256"] != sha256(PROTO_PATH.read_bytes()).hexdigest():
        problems.append("protocol file changed since the run started")
    for lk in ("development_complete.json", "assessment_opened.json"):
        if not (OUT / lk).exists():
            problems.append(f"missing lock {lk}")
    dc = json.loads((OUT / "development_complete.json").read_text()) if (OUT / "development_complete.json").exists() else {}
    for k, v in dc.get("files", {}).items():
        if sha256((ROOT / k).read_bytes()).hexdigest() != v:
            problems.append(f"development file changed after freezing: {k}")
    if (OUT / "assessment_opened.json").exists() and dc:
        if json.loads((OUT / "assessment_opened.json").read_text())["opened_at"] < dc["completed_at"]:
            problems.append("assessment opened before development completed")
    if (OUT / "summary.json").exists():
        s = json.loads((OUT / "summary.json").read_text())
        for k, v in s["artifact_sha256"].items():
            if k.endswith("assessment_predictions.parquet") or k.endswith("inner_scores.parquet"):
                continue  # rewritten together with summary.json
            if sha256((ROOT / k).read_bytes()).hexdigest() != v:
                problems.append(f"artifact changed: {k}")
        for fold in s["outer_identities"]:
            for p in ("S", "R0"):
                for h in ("30", "60"):
                    a = json.loads((OUT / "assessment" / f"{fold}.json").read_text())["procedures"][p][h]
                    try:
                        check_identity(a["calibration"], a["identity"])
                    except CalibrationError as e:
                        problems.append(f"{fold} {p} {h}: {e}")
                    if a["identity"]["training_participants_hash"] != fingerprint(
                            sorted(json.loads((OUT / "development" / f"{fold}.json").read_text())["development"])):
                        problems.append(f"{fold} {p} {h}: predictor not fitted on exactly the development people")
            if s["fold_choices"][fold]["selected"]["fallback"]:
                z = _load_arrays(OUT / "assessment" / f"{fold}.npz")
                for h in HS:
                    if not np.array_equal(z[f"S_final_{h}"], z[f"R0_final_{h}"], equal_nan=True):
                        problems.append(f"{fold}: fallback S differs from R0 at {h} min")
        if REPORT.exists() and REPORT.read_text() != render(s):
            problems.append("report differs from render(summary.json)")
    print(json.dumps({"ok": not problems, "problems": problems}, indent=1))
    return 0 if not problems else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        run(resume=False)
    elif cmd == "resume":
        run(resume=True)
    elif cmd == "render":
        REPORT.write_text(render(json.loads((OUT / "summary.json").read_text())))
    elif cmd == "validate":
        sys.exit(validate())
    else:
        sys.exit(__doc__)
