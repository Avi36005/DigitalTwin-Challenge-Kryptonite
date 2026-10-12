"""Model-neutral, causal feature builder shared by offline evaluation and online (replay) inference.

For a forecast origin ``t`` only records with ``observed_at <= t`` AND ``available_at <= t`` are used.
All aggregates are trailing; nothing is interpolated or back-filled from later samples. The same
function is called by the training pipeline (on full recordings, filtered per origin) and by the twin
engine (on events released by the replay clock), which is what the parity tests check.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.data.store import PatientData, to_minutes

EPS = 1e-6

# Activity-window conventions. A 5-minute summary observed at ``e`` covers the interval (e - window, e].
#
# * "end-in-window-v1" (feature sets *-v1, experiment gt-primary-2026-10-11-v1): selects every released summary
#   whose END lies in [t - w, t] and counts its full duration. A summary ending exactly at t - w is included although
#   its support lies outside the window, so a 60-minute window could hold 65 minutes (act_cov_60 = 1.083).
#   Kept unchanged ONLY so the v1 artifacts reproduce; it is a known defect (reports/repair_report.md).
# * "overlap-v2" (feature sets *-v2): each released summary contributes the part of (e - window, e] that overlaps the
#   lookback window (t - w, t]. A summary ending at t - w contributes nothing. Covered minutes, activity energy and
#   active minutes are allocated in proportion to the overlapping share of the summary (an approximation for
#   non-aligned origins: minute-level data are not part of the event model); means are weighted by covered minutes
#   in the window; overlapping summaries are de-duplicated so no minute is counted twice. Missing wearable data stays
#   missing (NaN), never zero activity.
ACTIVITY_POLICIES = ("end-in-window-v1", "overlap-v2")

PROFILE_FEATURES = [
    ("age_years", "age"),
    ("sex_male", "sex_male"),
    ("bmi_kg_m2", "bmi"),
    ("hba1c_pct", "hba1c"),
    ("fasting_glucose_mg_dl", "fasting_glucose"),
    ("fasting_insulin_uU_ml", "fasting_insulin"),
    ("triglycerides_mg_dl", "triglycerides"),
    ("hdl_mg_dl", "hdl"),
]


@dataclass(frozen=True)
class FeatureSpec:
    feature_set_id: str
    use_activity: bool = True
    use_profile: bool = False
    use_meals: bool = False
    lookback_minutes: float = 180.0
    min_history_minutes: float = 60.0
    cadence_minutes: float = 5.0
    match_tolerance_minutes: float = 2.5
    stale_threshold_minutes: float = 15.0
    lags: tuple[int, ...] = (5, 10, 15, 20, 30, 45, 60, 90, 120)
    activity_policy: str = "end-in-window-v1"

    def columns(self) -> list[str]:
        cols = ["g_last", "g_age_min"]
        cols += [f"g_lag_{lag}" for lag in self.lags]
        cols += ["d_15", "d_30", "d_60", "slope_15", "slope_30", "slope_60", "accel_30"]
        cols += ["mean_60", "std_60", "mean_180", "std_180", "min_180", "max_180", "frac_high_180"]
        cols += ["n_60", "n_180", "max_gap_180", "hist_minutes"]
        if self.use_activity:
            cols += [
                "hr_mean_30", "hr_mean_60", "hr_mean_120", "mets_mean_30", "mets_mean_60",
                "mets_max_60", "kcal_sum_60", "active_min_60", "act_cov_60",
            ]
        if self.use_meals:
            cols += ["carbs_60", "carbs_180", "kcal_180", "protein_180", "fat_180", "fiber_180",
                     "min_since_meal", "last_meal_carbs"]
        if self.use_profile:
            cols += [f"p_{name}" for _, name in PROFILE_FEATURES]
        return cols

    def transform_fingerprint(self) -> str:
        """Identity of the feature TRANSFORMATION, not just the column order. Artifacts store it; the loader rejects
        weights whose fingerprint differs from this code's, even when the column names are identical."""
        d = asdict(self)
        d["lags"] = list(self.lags)
        d["columns"] = self.columns()
        if not self.use_activity:
            d.pop("activity_policy")  # the activity convention cannot change a CGM-only transformation
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


FEATURE_SETS: dict[str, FeatureSpec] = {
    "cgm-only-v1": FeatureSpec("cgm-only-v1", use_activity=False),
    # v1: experiment gt-primary-2026-10-11-v1 (legacy activity windows, kept for reproducibility)
    "dyn-v1": FeatureSpec("dyn-v1", use_activity=True),
    "dyn-prof-v1": FeatureSpec("dyn-prof-v1", use_activity=True, use_profile=True),
    "dyn-prof-meal-v1": FeatureSpec("dyn-prof-meal-v1", use_activity=True, use_profile=True, use_meals=True),
    # v2: corrected activity-window overlap (same columns, different transformation)
    "dyn-v2": FeatureSpec("dyn-v2", use_activity=True, activity_policy="overlap-v2"),
    "dyn-prof-v2": FeatureSpec("dyn-prof-v2", use_activity=True, use_profile=True, activity_policy="overlap-v2"),
    "dyn-prof-meal-v2": FeatureSpec("dyn-prof-meal-v2", use_activity=True, use_profile=True, use_meals=True,
                                    activity_policy="overlap-v2"),
    # portable 15-minute CGM-only track (experiment gt-nested-2026-10-12-v1): native 15-minute sources and causally
    # decimated 5-minute sources share it. slope_15 needs three readings in 15 minutes, so it is always missing here.
    "cgm15-v1": FeatureSpec("cgm15-v1", use_activity=False, cadence_minutes=15.0, match_tolerance_minutes=7.5,
                            stale_threshold_minutes=22.5, lags=(15, 30, 45, 60, 90, 120)),
}


def spec_for(feature_set_id: str, device_cfg: dict[str, Any] | None = None) -> FeatureSpec:
    base = FEATURE_SETS[feature_set_id]
    if device_cfg is None:
        return base
    return FeatureSpec(
        base.feature_set_id,
        use_activity=base.use_activity,
        use_profile=base.use_profile,
        use_meals=base.use_meals,
        cadence_minutes=float(device_cfg["nominal_cadence_minutes"]),
        match_tolerance_minutes=float(device_cfg["match_tolerance_minutes"]),
        activity_policy=base.activity_policy,
    )


@dataclass
class Prepared:
    """Fast array view of one patient's (released) data."""

    g_obs: np.ndarray
    g_avail: np.ndarray
    g_val: np.ndarray
    g_suspect: np.ndarray
    g_ids: np.ndarray
    a_obs: np.ndarray
    a_avail: np.ndarray
    a_hr: np.ndarray
    a_mets: np.ndarray
    a_kcal: np.ndarray
    a_cov: np.ndarray
    a_win: np.ndarray
    m_obs: np.ndarray
    m_avail: np.ndarray
    m_carbs: np.ndarray
    m_kcal: np.ndarray
    m_protein: np.ndarray
    m_fat: np.ndarray
    m_fiber: np.ndarray
    profile: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)  # name -> (value, avail_min)


def _sorted_by_obs(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["observed_at", "available_at", "event_id"], kind="mergesort").reset_index(drop=True)


def prepare(pdata: PatientData) -> Prepared:
    g = _sorted_by_obs(pdata.glucose)
    a = _sorted_by_obs(pdata.activity)
    m = _sorted_by_obs(pdata.meals)
    prof: dict[str, tuple[float | None, float | None]] = {}
    for attr in pdata.profile:
        val = attr.get("value")
        avail = attr.get("available_at")
        avail_min = float(to_minutes(pd.Series([avail]))[0]) if avail else None
        num = float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else None
        if attr.get("status") == "excluded_suspect":
            num = None
        prof[attr["name"]] = (num, avail_min)
    return Prepared(
        g_obs=to_minutes(g["observed_at"]), g_avail=to_minutes(g["available_at"]),
        g_val=g["value_mg_dl"].to_numpy(float),
        g_suspect=g["quality"].to_numpy(str) != "ok",
        g_ids=g["event_id"].to_numpy(str),
        a_obs=to_minutes(a["observed_at"]), a_avail=to_minutes(a["available_at"]),
        a_hr=a["heart_rate_bpm"].to_numpy(float), a_mets=a["mets"].to_numpy(float),
        a_kcal=a["activity_kcal"].to_numpy(float), a_cov=a["minutes_covered"].to_numpy(float),
        a_win=(a["window_minutes"].to_numpy(float) if "window_minutes" in a else np.full(len(a), 5.0)),
        m_obs=to_minutes(m["observed_at"]), m_avail=to_minutes(m["available_at"]),
        m_carbs=m["carbs_g"].to_numpy(float), m_kcal=m["energy_kcal"].to_numpy(float),
        m_protein=m["protein_g"].to_numpy(float), m_fat=m["fat_g"].to_numpy(float),
        m_fiber=m["fiber_g"].to_numpy(float),
        profile=prof,
    )


def _slope(ts: np.ndarray, vs: np.ndarray, t: float, window: float) -> float:
    sel = ts >= t - window - EPS
    if sel.sum() < 3:
        return np.nan
    x, y = ts[sel], vs[sel]
    if x[-1] - x[0] < window / 2:
        return np.nan
    xm = x - x.mean()
    denom = float((xm * xm).sum())
    return float((xm * (y - y.mean())).sum() / denom) if denom > 0 else np.nan


def _nanmean(x: np.ndarray) -> float:
    x = x[~np.isnan(x)]
    return float(x.mean()) if x.size else np.nan


@dataclass
class FeatureResult:
    frame: pd.DataFrame                  # one row per origin, columns = spec.columns()
    quality: list[str]                   # ok | degraded | insufficient
    reasons: list[list[str]]             # reason codes per origin
    latest_index: np.ndarray             # index into prepared glucose arrays of the latest usable sample (-1)
    support_ids: list[list[str]]         # glucose event ids inside the trailing 60 minutes


QUALITY_MESSAGES = {
    "no_glucose_history": "No glucose observation is available yet.",
    "stale_glucose": "The latest available glucose observation is older than the freshness limit.",
    "insufficient_history": "Less than the minimum span of glucose history is available.",
    "sparse_recent_history": "Too few glucose observations in the last 60 minutes.",
    "incomplete_recent_history": "Some expected glucose observations in the last 60 minutes are missing.",
    "recent_gap": "A gap longer than 15 minutes occurred in the last 60 minutes.",
    "sensor_limit_value": "The latest reading is at a sensor reporting limit (40 or 400 mg/dL).",
    "activity_unavailable": "No wearable activity summary is available for the last 60 minutes.",
}


def build_features(prep: Prepared, origins: np.ndarray, spec: FeatureSpec) -> FeatureResult:
    cols = spec.columns()
    n = len(origins)
    out = np.full((n, len(cols)), np.nan)
    col_idx = {c: i for i, c in enumerate(cols)}
    quality: list[str] = []
    reasons: list[list[str]] = []
    latest_idx = np.full(n, -1, dtype=int)
    support_ids: list[list[str]] = []
    L = spec.lookback_minutes
    tol = spec.match_tolerance_minutes
    expected_60 = 60.0 / spec.cadence_minutes

    for r, t in enumerate(np.asarray(origins, dtype=float).tolist()):
        row = out[r]
        why: list[str] = []
        lo = np.searchsorted(prep.g_obs, t - L - EPS, "left")
        hi = np.searchsorted(prep.g_obs, t + EPS, "right")
        idx = np.arange(lo, hi)
        idx = idx[prep.g_avail[lo:hi] <= t + EPS]
        if idx.size == 0:
            quality.append("insufficient")
            reasons.append(["no_glucose_history"])
            support_ids.append([])
            continue
        ts, vs = prep.g_obs[idx], prep.g_val[idx]
        latest_idx[r] = idx[-1]
        g_last, g_age = vs[-1], t - ts[-1]
        row[col_idx["g_last"]] = g_last
        row[col_idx["g_age_min"]] = g_age
        lag_vals = {}
        for lag in spec.lags:
            target = t - lag
            k = np.searchsorted(ts, target)
            best = np.nan
            cands = [j for j in (k - 1, k) if 0 <= j < ts.size]
            if cands:
                j = min(cands, key=lambda q: abs(ts[q] - target))
                if abs(ts[j] - target) <= tol + EPS:
                    best = vs[j]
            lag_vals[lag] = best
            row[col_idx[f"g_lag_{lag}"]] = best
        for w in (15, 30, 60):
            lagv = lag_vals.get(w, np.nan)
            row[col_idx[f"d_{w}"]] = g_last - lagv
            row[col_idx[f"slope_{w}"]] = _slope(ts, vs, t, w)
        l15, l30 = lag_vals.get(15, np.nan), lag_vals.get(30, np.nan)
        row[col_idx["accel_30"]] = ((g_last - l15) - (l15 - l30)) / 15.0
        in60 = ts >= t - 60 - EPS
        v60 = vs[in60]
        row[col_idx["mean_60"]] = v60.mean()
        row[col_idx["std_60"]] = v60.std() if v60.size > 1 else np.nan
        row[col_idx["mean_180"]] = vs.mean()
        row[col_idx["std_180"]] = vs.std() if vs.size > 1 else np.nan
        row[col_idx["min_180"]] = vs.min()
        row[col_idx["max_180"]] = vs.max()
        row[col_idx["frac_high_180"]] = float((vs > 180).mean())
        n60 = int(in60.sum())
        row[col_idx["n_60"]] = n60
        row[col_idx["n_180"]] = vs.size
        gaps = np.diff(np.append(ts, t))
        row[col_idx["max_gap_180"]] = gaps.max() if gaps.size else np.nan
        hist = t - ts[0]
        row[col_idx["hist_minutes"]] = hist
        gaps60 = np.diff(np.append(ts[in60], t))
        support_ids.append(prep.g_ids[idx[in60]].tolist())

        if spec.use_activity:
            if spec.activity_policy == "overlap-v2":
                cov = _activity_overlap(prep, t, row, col_idx)
            else:
                cov = _activity_end_in_window_v1(prep, t, row, col_idx)
            row[col_idx["act_cov_60"]] = cov
            if cov <= 0:
                why.append("activity_unavailable")

        if spec.use_meals:
            mlo = np.searchsorted(prep.m_obs, t - 360 - EPS, "left")
            mhi = np.searchsorted(prep.m_obs, t + EPS, "right")
            midx = np.arange(mlo, mhi)
            midx = midx[prep.m_avail[mlo:mhi] <= t + EPS]
            m_t = prep.m_obs[midx]
            s60 = midx[m_t > t - 60 - EPS]
            s180 = midx[m_t > t - 180 - EPS]
            row[col_idx["carbs_60"]] = np.nansum(prep.m_carbs[s60]) if s60.size else 0.0
            row[col_idx["carbs_180"]] = np.nansum(prep.m_carbs[s180]) if s180.size else 0.0
            row[col_idx["kcal_180"]] = np.nansum(prep.m_kcal[s180]) if s180.size else 0.0
            row[col_idx["protein_180"]] = np.nansum(prep.m_protein[s180]) if s180.size else 0.0
            row[col_idx["fat_180"]] = np.nansum(prep.m_fat[s180]) if s180.size else 0.0
            row[col_idx["fiber_180"]] = np.nansum(prep.m_fiber[s180]) if s180.size else 0.0
            if midx.size:
                row[col_idx["min_since_meal"]] = t - m_t[-1]
                row[col_idx["last_meal_carbs"]] = prep.m_carbs[midx[-1]]

        if spec.use_profile:
            for _, name in PROFILE_FEATURES:
                val, avail = prep.profile.get(name, (None, None))
                if val is not None and avail is not None and avail <= t + EPS:
                    row[col_idx[f"p_{name}"]] = val

        status = "ok"
        hard: list[str] = []
        if g_age > spec.stale_threshold_minutes + EPS:
            hard.append("stale_glucose")
        if hist < spec.min_history_minutes - spec.match_tolerance_minutes:
            hard.append("insufficient_history")
        if n60 < 0.5 * expected_60:
            hard.append("sparse_recent_history")
        if hard:
            status = "insufficient"
            why = hard + why
        else:
            soft: list[str] = []
            if n60 < 0.8 * expected_60:
                soft.append("incomplete_recent_history")
            if gaps60.size and gaps60.max() > spec.stale_threshold_minutes + EPS:
                soft.append("recent_gap")
            if prep.g_suspect[idx[-1]]:
                soft.append("sensor_limit_value")
            why = soft + why
            if soft or "activity_unavailable" in why:
                status = "degraded"
        quality.append(status)
        reasons.append(why)

    frame = pd.DataFrame(out, columns=cols)
    return FeatureResult(frame, quality, reasons, latest_idx, support_ids)


def _released_activity(prep: Prepared, t: float, lookback: float) -> np.ndarray:
    """Indices of activity summaries observed AND available by ``t`` whose end lies within ``lookback`` (+ window)."""
    wmax = float(np.nanmax(prep.a_win)) if prep.a_win.size else 0.0
    alo = np.searchsorted(prep.a_obs, t - lookback - wmax - EPS, "left")
    ahi = np.searchsorted(prep.a_obs, t + EPS, "right")
    aidx = np.arange(alo, ahi)
    return aidx[prep.a_avail[alo:ahi] <= t + EPS]


def _activity_end_in_window_v1(prep: Prepared, t: float, row: np.ndarray, col_idx: dict[str, int]) -> float:
    """LEGACY (feature sets *-v1). Reproduces experiment gt-primary-2026-10-11-v1 exactly, including its defect."""
    alo = np.searchsorted(prep.a_obs, t - 120 - EPS, "left")
    ahi = np.searchsorted(prep.a_obs, t + EPS, "right")
    aidx = np.arange(alo, ahi)
    aidx = aidx[prep.a_avail[alo:ahi] <= t + EPS]
    a_t = prep.a_obs[aidx]
    for w, name in ((30, "30"), (60, "60"), (120, "120")):
        sel = aidx[a_t > t - w - EPS]
        row[col_idx[f"hr_mean_{name}"]] = _nanmean(prep.a_hr[sel]) if sel.size else np.nan
        if w in (30, 60):
            row[col_idx[f"mets_mean_{name}"]] = _nanmean(prep.a_mets[sel]) if sel.size else np.nan
    sel60 = aidx[a_t > t - 60 - EPS]
    if not sel60.size:
        return 0.0
    mets60 = prep.a_mets[sel60]
    row[col_idx["mets_max_60"]] = np.nanmax(mets60) if np.isfinite(mets60).any() else np.nan
    row[col_idx["kcal_sum_60"]] = np.nansum(prep.a_kcal[sel60])
    active = (mets60 >= 3.0) & np.isfinite(mets60)
    row[col_idx["active_min_60"]] = float(np.nansum(prep.a_cov[sel60][active]))
    return float(np.nansum(prep.a_cov[sel60])) / 60.0


def activity_overlap_weights(prep: Prepared, aidx: np.ndarray, t: float, w: float) -> np.ndarray:
    """Share (0..1) of each summary's own interval (e - window, e] that lies inside (t - w, t].

    Summaries are processed in end order; a summary's start is moved past the end of any earlier summary so that two
    overlapping or duplicate summaries never count the same minute twice.
    """
    if aidx.size == 0:
        return np.zeros(0)
    e = prep.a_obs[aidx]
    win = np.where(np.isfinite(prep.a_win[aidx]) & (prep.a_win[aidx] > 0), prep.a_win[aidx], 5.0)
    start = e - win
    prev_end = np.maximum.accumulate(np.concatenate([[-np.inf], e[:-1]]))
    start_eff = np.maximum(start, prev_end)
    lo = np.maximum(start_eff, t - w)
    hi = np.minimum(e, t)
    overlap = np.clip(hi - lo, 0.0, None)
    overlap[overlap < EPS] = 0.0
    return overlap / win


def _activity_overlap(prep: Prepared, t: float, row: np.ndarray, col_idx: dict[str, int]) -> float:
    """Corrected activity features (feature sets *-v2); see ACTIVITY_POLICIES. Returns act_cov_60 (0..1)."""
    aidx = _released_activity(prep, t, 120.0)
    for w, name in ((30, "30"), (60, "60"), (120, "120")):
        f = activity_overlap_weights(prep, aidx, t, w)
        covered = prep.a_cov[aidx] * f  # covered minutes of each summary that fall inside the window
        row[col_idx[f"hr_mean_{name}"]] = _weighted_mean(prep.a_hr[aidx], covered)
        if w in (30, 60):
            row[col_idx[f"mets_mean_{name}"]] = _weighted_mean(prep.a_mets[aidx], covered)
        if w == 60:
            inside = f > 0
            mets = prep.a_mets[aidx]
            ok_mets = inside & np.isfinite(mets)
            row[col_idx["mets_max_60"]] = float(mets[ok_mets].max()) if ok_mets.any() else np.nan
            kcal = prep.a_kcal[aidx]
            ok_kcal = inside & np.isfinite(kcal)
            row[col_idx["kcal_sum_60"]] = float((kcal[ok_kcal] * f[ok_kcal]).sum()) if ok_kcal.any() else np.nan
            row[col_idx["active_min_60"]] = float(covered[ok_mets & (mets >= 3.0)].sum()) if ok_mets.any() else np.nan
            cov60 = float(np.nansum(covered)) / 60.0
    return cov60  # <= 1 by construction: de-duplicated intervals inside a 60-minute window (no clamping)


def _weighted_mean(x: np.ndarray, w: np.ndarray) -> float:
    ok = np.isfinite(x) & (w > 0)
    return float((x[ok] * w[ok]).sum() / w[ok].sum()) if ok.any() else np.nan


def match_targets(
    obs: np.ndarray, vals: np.ndarray, avail: np.ndarray, origins: np.ndarray, horizon: float, tol: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Match each origin + horizon to an actually observed native sample within ``tol`` minutes.

    Returns (target_value, target_observed_at, target_available_at); NaN where unmatched.
    """
    target = np.asarray(origins, dtype=float) + horizon
    k = np.searchsorted(obs, target)
    out_v = np.full(target.shape, np.nan)
    out_t = np.full(target.shape, np.nan)
    out_a = np.full(target.shape, np.nan)
    for i, (tt, kk) in enumerate(zip(target.tolist(), k.tolist(), strict=True)):
        best, bestd = -1, np.inf
        for j in (kk - 1, kk):
            if 0 <= j < obs.size:
                d = abs(obs[j] - tt)
                if d < bestd:
                    best, bestd = j, d
        if best >= 0 and bestd <= tol + EPS:
            out_v[i], out_t[i], out_a[i] = vals[best], obs[best], avail[best]
    return out_v, out_t, out_a
