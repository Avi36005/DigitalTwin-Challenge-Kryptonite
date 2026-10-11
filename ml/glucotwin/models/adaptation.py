"""Causal patient adaptation: a shrunk, bounded, decaying bias correction per horizon.

This one class is used by BOTH the offline prequential evaluation and the online twin engine, so the
personalization evaluated is exactly the personalization served.

Protocol per forecast origin ``t`` (call ``step`` once per origin, in time order):

1. If the time since the previous origin exceeds ``reset_gap_minutes``, clear all state.
2. Resolve pending forecasts whose target window ``[s + h - tol, s + h + tol]`` has fully passed
   (``s + h + tol < t``): find the nearest released native reading in that window that was available
   by ``t``. Its residual ``observed - population prediction`` matures now. A target that has not
   arrived keeps waiting for up to ``target_wait_minutes``; after that it is dropped (never imputed).
3. The correction for horizon ``h`` is
   ``clip(sum(w_i * r_i) / (sum(w_i) + k), -cap, cap)`` with ``w_i = 0.5 ** ((t - s_i) / half_life)``,
   or 0 while fewer than ``min_residuals`` residuals have matured since the last reset.
4. The new frozen POPULATION prediction (never an already-corrected value) is registered as pending.

Model weights are never refit; only this small state changes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class AdaptationPolicy:
    policy_id: str = "shrunk-bias-v1"
    enabled: bool = True
    shrinkage_k: float = 24.0
    half_life_minutes: float = 1440.0
    cap_mg_dl: float = 25.0
    min_residuals: int = 6
    reset_gap_minutes: float = 180.0
    match_tolerance_minutes: float = 2.5
    target_wait_minutes: float = 120.0   # how long a pending forecast waits for a late-arriving target

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class _HorizonState:
    pending: deque = field(default_factory=deque)       # (origin, pop_pred, forecast_id)
    sum_wr: float = 0.0
    sum_w: float = 0.0
    n: int = 0
    last_t: float | None = None                          # time the decayed sums refer to
    last_matured_at: float | None = None
    recent_ids: deque = field(default_factory=lambda: deque(maxlen=12))


class AdaptationState:
    def __init__(self, policy: AdaptationPolicy, horizons: list[int], collect_from: float = -np.inf):
        self.policy = policy
        self.horizons = list(horizons)
        self.collect_from = collect_from
        self.version = 0
        self.prev_origin: float | None = None
        self.reset_count = 0
        self.just_reset = False
        self.h: dict[int, _HorizonState] = {h: _HorizonState() for h in self.horizons}

    def reset(self) -> None:
        self.h = {h: _HorizonState() for h in self.horizons}
        self.version += 1
        self.reset_count += 1
        self.just_reset = True

    def _decay_to(self, hs: _HorizonState, t: float) -> None:
        if hs.last_t is not None and t > hs.last_t:
            f = 0.5 ** ((t - hs.last_t) / self.policy.half_life_minutes)
            hs.sum_wr *= f
            hs.sum_w *= f
        hs.last_t = t

    def step(
        self,
        t: float,
        sample_obs: np.ndarray,
        sample_val: np.ndarray,
        sample_avail: np.ndarray,
        pop_preds: dict[int, float | None],
        forecast_id: str,
    ) -> dict[int, float | None]:
        """Advance to origin ``t``; return the correction per horizon (None if adaptation disabled)."""
        p = self.policy
        self.just_reset = False
        if self.prev_origin is not None and t - self.prev_origin > p.reset_gap_minutes:
            self.reset()
        self.prev_origin = t
        tol = p.match_tolerance_minutes
        out: dict[int, float | None] = {}
        for h in self.horizons:
            hs = self.h[h]
            self._decay_to(hs, t)
            still_waiting: list = []
            while hs.pending and hs.pending[0][0] + h + tol < t:
                s, pop, fid = hs.pending.popleft()
                target = s + h
                lo = np.searchsorted(sample_obs, target - tol - 1e-6, "left")
                hi = np.searchsorted(sample_obs, target + tol + 1e-6, "right")
                best, bestd = -1, np.inf
                for j in range(lo, hi):
                    if sample_avail[j] <= t + 1e-6:
                        d = abs(sample_obs[j] - target)
                        if d < bestd:
                            best, bestd = j, d
                if best < 0:
                    if target + tol + p.target_wait_minutes >= t:
                        still_waiting.append((s, pop, fid))  # target may still arrive late
                    continue  # otherwise the target never arrived: drop, never impute
                r = float(sample_val[best] - pop)
                w = 0.5 ** ((t - s) / p.half_life_minutes)
                hs.sum_wr += w * r
                hs.sum_w += w
                hs.n += 1
                hs.last_matured_at = t
                hs.recent_ids.append(fid)
                self.version += 1
            hs.pending.extendleft(reversed(still_waiting))
            if not p.enabled:
                out[h] = None
            elif hs.n < p.min_residuals:
                out[h] = 0.0
            else:
                c = hs.sum_wr / (hs.sum_w + p.shrinkage_k)
                out[h] = float(np.clip(c, -p.cap_mg_dl, p.cap_mg_dl))
            pop = pop_preds.get(h)
            if t >= self.collect_from and pop is not None and np.isfinite(pop):
                hs.pending.append((t, float(pop), forecast_id))
        return out

    def status(self) -> str:
        if not self.policy.enabled:
            return "disabled"
        if self.just_reset and self.reset_count:
            return "reset_after_gap"
        if all(self.h[h].n >= self.policy.min_residuals for h in self.horizons):
            return "active"
        return "warming_up"

    def horizon_summary(self, h: int, t: float) -> dict:
        hs = self.h[h]
        corr = None
        if self.policy.enabled:
            if hs.n < self.policy.min_residuals:
                corr = 0.0
            else:
                f = 0.5 ** ((t - hs.last_t) / self.policy.half_life_minutes) if hs.last_t is not None else 1.0
                corr = float(np.clip(hs.sum_wr * f / (hs.sum_w * f + self.policy.shrinkage_k),
                                     -self.policy.cap_mg_dl, self.policy.cap_mg_dl))
        return {"horizon_minutes": h, "matured_residuals": hs.n, "min_required": self.policy.min_residuals,
                "correction_mg_dl": corr, "last_matured_at": hs.last_matured_at,
                "consumed_forecast_ids": list(hs.recent_ids)}


def conformal_quantile(abs_residuals: np.ndarray, level: float) -> float | None:
    r = np.sort(np.asarray(abs_residuals, dtype=float)[np.isfinite(abs_residuals)])
    n = r.size
    if n < 50:
        return None
    k = int(np.ceil((n + 1) * level)) - 1
    return float(r[min(k, n - 1)])
