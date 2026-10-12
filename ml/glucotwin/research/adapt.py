"""Prequential (causal) personalization over whole participants, using the serving ``AdaptationState``.

Each participant starts from an EMPTY state at their first origin (the new-participant setting); residuals mature only
once their matched target is available (``AdaptationState.step``), and repeated origins are ignored.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from glucotwin.features import Prepared
from glucotwin.models.adaptation import AdaptationPolicy, AdaptationState


def make_policy(proto: dict[str, Any], track: str, k: float, half_life: float, enabled: bool = True) -> AdaptationPolicy:
    a = proto["adaptation"]
    return AdaptationPolicy(a["policy_id"], enabled, float(k), float(half_life), float(a["cap_mg_dl"]),
                            int(a["min_residuals"]), float(a["reset_gap_minutes"]),
                            float(a["match_tolerance_minutes"][track]), float(a["target_wait_minutes"]))


def prequential(table: pd.DataFrame, prep: dict[str, Prepared], rows: np.ndarray, pop: dict[int, np.ndarray],
                policy: AdaptationPolicy, horizons: list[int], freeze_after_min: float | None = None
                ) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """Corrections and matured-residual counts per row (NaN outside ``rows`` or where no forecast was issued)."""
    corr = {h: np.full(len(table), np.nan) for h in horizons}
    nres = {h: np.full(len(table), np.nan) for h in horizons}
    pids = table["patient_id"].to_numpy()
    origins = table["origin"].to_numpy(float)
    elapsed = table["elapsed_min"].to_numpy(float)
    idx = np.where(rows)[0]
    for pid in pd.unique(pids[idx]):
        r_p = idx[pids[idx] == pid]
        p = prep[pid]
        state = AdaptationState(policy, horizons, collect_from=-np.inf)
        frozen: dict[int, float] | None = None
        for r in r_p:
            t = origins[r]
            pp = {h: (pop[h][r] if np.isfinite(pop[h][r]) else None) for h in horizons}
            if freeze_after_min is not None and elapsed[r] >= freeze_after_min:
                if frozen is None:
                    frozen = {h: (state.horizon_summary(h, t)["correction_mg_dl"] or 0.0) for h in horizons}
                for h in horizons:
                    if pp[h] is not None:
                        corr[h][r] = frozen[h]
                        nres[h][r] = state.h[h].n
                continue
            c = state.step(t, p.g_obs, p.g_val, p.g_avail, pp, f"{pid}:{t:.3f}")
            for h in horizons:
                if pp[h] is not None:
                    corr[h][r] = c[h] if c[h] is not None else 0.0
                    nres[h][r] = state.h[h].n
    return corr, nres


def apply(pop: dict[int, np.ndarray], corr: dict[int, np.ndarray]) -> dict[int, np.ndarray]:
    return {h: pop[h] + np.where(np.isfinite(corr[h]), corr[h], 0.0) for h in pop}
