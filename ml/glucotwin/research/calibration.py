"""Prediction ranges calibrated for the EXACT final pipeline on reserved calibration participants.

* ``global``: finite-sample split-conformal quantile of absolute residuals per horizon (primary).
* ``cls``  : causal locally scaled conformal (secondary; declared in the protocol, not selectable). The person's scale
  sigma_p(t) uses only residuals that have matured by t; with too few the frozen global range is used.

Calibration artifacts record what they were calibrated for; ``check_compatible`` refuses to pair them with anything
else (another model, adaptation policy, feature transformation, level or horizon).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import fingerprint

MIN_CALIBRATION = 50


class CalibrationError(RuntimeError):
    pass


def finite_sample_quantile(x: np.ndarray, level: float) -> tuple[float | None, int, int]:
    """(quantile, rank k (1-based), n). The ceil((n+1) level)-th smallest value; None when n < 50 or k > n."""
    v = np.sort(np.asarray(x, float)[np.isfinite(x)])
    n = int(v.size)
    k = int(math.ceil((n + 1) * level))
    if n < MIN_CALIBRATION or k > n:
        return None, k, n
    return float(v[k - 1]), k, n


def matured_scale(table: pd.DataFrame, rows: np.ndarray, final: dict[int, np.ndarray], horizons: list[int],
                  tol: float, half_life: float, k_s: float, sigma_g: dict[int, float | None], min_res: int,
                  reset_gap: float) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """sigma_p(t) per row and horizon from already-matured absolute residuals of the person (NaN = fallback)."""
    pids = table["patient_id"].to_numpy()
    o = table["origin"].to_numpy(float)
    sig = {h: np.full(len(table), np.nan) for h in horizons}
    nmat = {h: np.zeros(len(table)) for h in horizons}
    idx = np.where(rows)[0]
    for pid in pd.unique(pids[idx]):
        r_p = idx[pids[idx] == pid]
        for h in horizons:
            if sigma_g.get(h) is None:
                continue
            y = table[f"target_{h}"].to_numpy(float)
            ya = table[f"target_{h}_avail"].to_numpy(float)
            pending: list[int] = []
            sw = swr = 0.0
            n = 0
            last_t = None
            prev = None
            for r in r_p:
                t = o[r]
                if prev is not None and t - prev > reset_gap:
                    pending, sw, swr, n, last_t = [], 0.0, 0.0, 0, None
                prev = t
                if last_t is not None:
                    f = 0.5 ** ((t - last_t) / half_life)
                    sw, swr = sw * f, swr * f
                last_t = t
                keep = []
                for s in pending:
                    if not o[s] + h + tol < t:
                        keep.append(s)                      # target window not over yet
                    elif np.isfinite(ya[s]) and ya[s] <= t:  # matured: target observed and available by t
                        w = 0.5 ** ((t - o[s]) / half_life)
                        sw += w
                        swr += w * abs(y[s] - final[h][s])
                        n += 1
                    elif np.isfinite(ya[s]) and t <= o[s] + h + tol + 120:
                        keep.append(s)                      # a late target may still arrive (same wait as adaptation)
                    # otherwise the target never arrives: dropped, never imputed
                pending = keep
                nmat[h][r] = n
                if n >= min_res:
                    sig[h][r] = (swr + k_s * sigma_g[h]) / (sw + k_s)
                if np.isfinite(final[h][r]):
                    pending.append(r)
    return sig, nmat


def calibrate(table: pd.DataFrame, cal_rows: np.ndarray, final: dict[int, np.ndarray], horizons: list[int],
              level: float, tol: float, cls_cfg: dict[str, float], identity: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"identity": identity, "identity_hash": fingerprint(identity), "level": level,
                           "horizons": {}, "method_primary": "split-conformal-global",
                           "method_secondary": "causal-locally-scaled-conformal"}
    sigma_g: dict[int, float | None] = {}
    for h in horizons:
        y = table[f"target_{h}"].to_numpy(float)
        m = cal_rows & np.isfinite(final[h]) & np.isfinite(y)
        res = np.abs(y[m] - final[h][m])
        q, k, n = finite_sample_quantile(res, level)
        sigma_g[h] = float(res.mean()) if res.size else None
        out["horizons"][str(h)] = {"global_q": q, "rank": k, "n": n, "sigma_g": sigma_g[h],
                                   "participants": int(pd.Series(table["patient_id"].to_numpy()[m]).nunique())}
    sig, _ = matured_scale(table, cal_rows, final, horizons, tol, cls_cfg["half_life"], cls_cfg["k_s"], sigma_g,
                           int(cls_cfg["min_residuals"]), cls_cfg["reset_gap"])
    for h in horizons:
        y = table[f"target_{h}"].to_numpy(float)
        m = cal_rows & np.isfinite(final[h]) & np.isfinite(y) & np.isfinite(sig[h])
        ratio = np.abs(y[m] - final[h][m]) / sig[h][m]
        q_s, k, n = finite_sample_quantile(ratio, level)
        out["horizons"][str(h)].update({"cls_q_scaled": q_s, "cls_rank": k, "cls_n": n})
    out["cls"] = dict(cls_cfg)
    return out


def check_compatible(cal: dict[str, Any], identity: dict[str, Any]) -> None:
    if cal.get("identity_hash") != fingerprint(identity):
        diff = sorted(k for k in set(cal.get("identity", {})) | set(identity)
                      if cal.get("identity", {}).get(k) != identity.get(k))
        raise CalibrationError(f"Calibration artifact was made for a different pipeline (differs in {diff}); refusing it")


def intervals(table: pd.DataFrame, rows: np.ndarray, final: dict[int, np.ndarray], cal: dict[str, Any],
              horizons: list[int], tol: float) -> dict[str, dict[int, tuple[np.ndarray, np.ndarray]]]:
    """Lower/upper bounds per method and horizon (no endpoint clipping) + the CLS fallback mask."""
    out: dict[str, Any] = {"global": {}, "cls": {}, "cls_fallback": {}}
    sigma_g = {h: cal["horizons"][str(h)]["sigma_g"] for h in horizons}
    c = cal["cls"]
    sig, _ = matured_scale(table, rows, final, horizons, tol, c["half_life"], c["k_s"], sigma_g, int(c["min_residuals"]),
                           c["reset_gap"])
    for h in horizons:
        hc = cal["horizons"][str(h)]
        q = hc["global_q"]
        f = np.where(rows, final[h], np.nan)
        if q is None:
            lo = hi = np.full(len(table), np.nan)
        else:
            lo, hi = f - q, f + q
        out["global"][h] = (lo, hi)
        qs = hc.get("cls_q_scaled")
        fb = rows & np.isfinite(f) & ~np.isfinite(sig[h])
        if q is None or qs is None:
            out["cls"][h] = (np.full(len(table), np.nan), np.full(len(table), np.nan))
        else:
            half = np.where(np.isfinite(sig[h]), qs * sig[h], q)
            out["cls"][h] = (f - half, f + half)
        out["cls_fallback"][h] = fb
    return out
