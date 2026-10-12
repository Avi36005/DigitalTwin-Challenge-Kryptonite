"""Participant-weighted metrics, paired participant bootstrap, interval metrics and exposure time.

Every summary is macro over participants (each person weighted equally) unless a name says otherwise. Overlapping
forecast windows of one person are never treated as independent units.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def per_participant(values: np.ndarray, pids: np.ndarray) -> pd.Series:
    ok = np.isfinite(values)
    return pd.Series(values[ok]).groupby(pids[ok]).mean()


def per_participant_mae(pred: np.ndarray, target: np.ndarray, pids: np.ndarray, mask: np.ndarray) -> pd.Series:
    m = mask & np.isfinite(pred) & np.isfinite(target)
    return pd.Series(np.abs(pred[m] - target[m])).groupby(pids[m]).mean()


def per_participant_rmse(pred: np.ndarray, target: np.ndarray, pids: np.ndarray, mask: np.ndarray) -> pd.Series:
    m = mask & np.isfinite(pred) & np.isfinite(target)
    return np.sqrt(pd.Series((pred[m] - target[m]) ** 2).groupby(pids[m]).mean())


def macro(s: pd.Series) -> float | None:
    return float(s.mean()) if len(s) else None


def macro_mae_grouped(pred: np.ndarray, target: np.ndarray, groups: np.ndarray) -> float:
    """Mean over groups of the group's mean absolute error (the declared early-stopping metric)."""
    err = np.abs(np.asarray(pred, float) - np.asarray(target, float))
    codes, inv = np.unique(groups, return_inverse=True)
    sums = np.bincount(inv, weights=err, minlength=codes.size)
    counts = np.bincount(inv, minlength=codes.size)
    return float(np.mean(sums / counts))


def paired_bootstrap(a: pd.Series, b: pd.Series, n: int, seed: int) -> dict[str, Any]:
    """Mean per-participant difference a - b with a participant-cluster bootstrap 95 % interval. Participants are
    resampled with both pipelines' values together (pairs), never origins."""
    d = (a - b).dropna()
    if d.empty:
        return {"mean_diff": None, "ci95": [None, None], "n_participants": 0, "improved": 0, "worsened": 0}
    v = d.to_numpy(float)
    rng = np.random.default_rng(seed)
    boots = v[rng.integers(0, v.size, size=(n, v.size))].mean(axis=1)
    return {"mean_diff": float(v.mean()), "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
            "n_participants": int(v.size), "improved": int((v < 0).sum()), "worsened": int((v > 0).sum()),
            "unchanged": int((v == 0).sum())}


def exposure_minutes(origins: np.ndarray, pids: np.ndarray, mask: np.ndarray, cadence: float) -> float:
    """Non-overlapping, gap-respecting time represented by the masked origins: each origin covers
    min(next masked origin of the same person - t, cadence)."""
    total = 0.0
    o, p = origins[mask], pids[mask]
    if o.size == 0:
        return 0.0
    order = np.lexsort((o, p))
    o, p = o[order], p[order]
    nxt = np.append(o[1:], np.inf)
    same = np.append(p[1:] == p[:-1], False)
    step = np.where(same, np.minimum(nxt - o, cadence), cadence)
    total = float(step.sum())
    return total


def interval_score(lower: np.ndarray, upper: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    """Proper interval score of a central (1 - alpha) interval (Gneiting & Raftery 2007); lower is better."""
    return (upper - lower) + (2.0 / alpha) * np.clip(lower - y, 0, None) + (2.0 / alpha) * np.clip(y - upper, 0, None)


def interval_summary(lower: np.ndarray, upper: np.ndarray, y: np.ndarray, pids: np.ndarray, glast: np.ndarray,
                     alpha: float, strata: dict[str, list], min_n: int, min_p: int) -> dict[str, Any]:
    ok = np.isfinite(lower) & np.isfinite(upper) & np.isfinite(y)
    out: dict[str, Any] = {"n_with_interval": int(ok.sum()), "n_without_interval": int((~ok & np.isfinite(y)).sum())}
    if not ok.any():
        return {**out, "coverage_pooled": None, "coverage_macro": None}
    inside = (y[ok] >= lower[ok]) & (y[ok] <= upper[ok])
    width = (upper - lower)[ok]
    per_p = pd.Series(inside.astype(float)).groupby(pids[ok]).mean()
    isc = interval_score(lower[ok], upper[ok], y[ok], alpha)
    out.update({
        "coverage_pooled": float(inside.mean()), "coverage_macro": float(per_p.mean()),
        "coverage_participant_min": float(per_p.min()), "coverage_participant_max": float(per_p.max()),
        "coverage_participant_iqr": [float(per_p.quantile(0.25)), float(per_p.quantile(0.75))],
        "participants": int(per_p.size), "width_mean": float(width.mean()), "width_median": float(np.median(width)),
        "width_p10_p90": [float(np.percentile(width, 10)), float(np.percentile(width, 90))],
        "interval_score_macro": float(pd.Series(isc).groupby(pids[ok]).mean().mean()),
    })
    st = {}
    for name, (lo, hi) in strata.items():
        sel = ok.copy()
        if lo is not None:
            sel &= glast >= lo
        if hi is not None:
            sel &= glast < hi
        n, npart = int(sel.sum()), int(pd.Series(pids[sel]).nunique())
        if n < min_n or npart < min_p:
            st[name] = {"n": n, "participants": npart, "coverage": None, "reason_if_null": "insufficient evidence"}
        else:
            ins = (y[sel] >= lower[sel]) & (y[sel] <= upper[sel])
            st[name] = {"n": n, "participants": npart, "coverage": float(ins.mean()),
                        "width_mean": float((upper - lower)[sel].mean())}
    out["by_current_glucose"] = st
    return out
