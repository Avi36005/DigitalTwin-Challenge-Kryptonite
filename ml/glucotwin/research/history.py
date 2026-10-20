"""Causal long-history glucose features (feature set ``hist-v1``, research only; protocol gt-retrain-2026-10-21, D-049).

For each origin t and window w in 6, 12 and 24 hours: mean, standard deviation, coverage and the deviation of the latest
reading from the window mean, over the person's own native readings with observed and available time in (t − w, t].
Suspect readings are excluded. With coverage below 0.5 of the expected 5-minute readings, mean/std/dev are missing.
Nothing after the origin, no centred window and no whole-recording statistic enters a value.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WINDOWS_MIN = (360, 720, 1440)
CADENCE_MIN = 5.0
MIN_COVERAGE = 0.5
COLUMNS = [f"hist_{k}_{w}" for w in WINDOWS_MIN for k in ("mean", "std", "cov", "dev")]


def history_features(origins: np.ndarray, g_last: np.ndarray, obs: np.ndarray, avail: np.ndarray, vals: np.ndarray,
                     suspect: np.ndarray | None = None) -> pd.DataFrame:
    """Features for one person's origins (minutes) from that person's readings (minutes, mg/dL)."""
    keep = np.isfinite(vals) & np.isfinite(obs) & np.isfinite(avail)
    if suspect is not None:
        keep &= ~np.asarray(suspect, bool)
    o, a, v = obs[keep], avail[keep], vals[keep]
    order = np.argsort(o, kind="mergesort")
    o, a, v = o[order], a[order], v[order]
    out = {c: np.full(len(origins), np.nan) for c in COLUMNS}
    if not len(o):
        for w in WINDOWS_MIN:
            out[f"hist_cov_{w}"][:] = 0.0
        return pd.DataFrame(out)
    # a reading counts at t only if it was observed AND available by t; with available >= observed, the available time
    # bounds the window's right edge
    for i, t in enumerate(origins):
        ok_t = a <= t
        for w in WINDOWS_MIN:
            sel = ok_t & (o > t - w) & (o <= t)
            n = int(sel.sum())
            cov = n / (w / CADENCE_MIN)
            out[f"hist_cov_{w}"][i] = cov
            if cov >= MIN_COVERAGE and n >= 2:
                x = v[sel]
                m = float(x.mean())
                out[f"hist_mean_{w}"][i] = m
                out[f"hist_std_{w}"][i] = float(x.std(ddof=1))
                if np.isfinite(g_last[i]):
                    out[f"hist_dev_{w}"][i] = float(g_last[i] - m)
    return pd.DataFrame(out)


def table_history(table: pd.DataFrame, prep: dict) -> pd.DataFrame:
    """``hist-v1`` columns aligned to ``table`` rows, computed per person from that person's prepared readings."""
    res = pd.DataFrame(np.nan, index=table.index, columns=COLUMNS)
    for pid, idx in table.groupby("patient_id").groups.items():
        p = prep[pid]
        rows = table.loc[idx]
        f = history_features(rows["origin"].to_numpy(float), rows["g_last"].to_numpy(float), np.asarray(p.g_obs, float),
                             np.asarray(p.g_avail, float), np.asarray(p.g_val, float), getattr(p, "g_suspect", None))
        res.loc[idx, COLUMNS] = f.to_numpy()
    return res
