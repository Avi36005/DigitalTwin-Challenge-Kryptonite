"""Workload-aware research warning policy (5-minute event track only).

Episodes and one-to-one matching come from ``glucotwin.evaluation.alerts`` — the same code the online twin uses — so
offline and replay accounting cannot drift apart. This module adds the threshold curve with exposure-based workload
denominators and the declared selection rules.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from glucotwin.evaluation import alerts as alert_eval
from glucotwin.research.metrics import exposure_minutes


def scores(final: dict[int, np.ndarray], H: int, threshold_mg_dl: float = 180.0) -> np.ndarray:
    hs = [h for h in sorted(final) if h <= H]
    stack = np.vstack([final[h] for h in hs])
    with np.errstate(all="ignore"):
        s = np.nanmax(np.where(np.isnan(stack), -np.inf, stack), axis=0) - threshold_mg_dl
    s[~np.isfinite(s)] = np.nan
    return s


def evaluate(table: pd.DataFrame, rows: np.ndarray, issued: np.ndarray, score: np.ndarray, H: int, threshold: float,
             merge: float, cadence: float) -> tuple[dict[str, Any], dict[str, alert_eval.EpisodeResult]]:
    pids = table["patient_id"].to_numpy()
    o = table["origin"].to_numpy(float)
    elig = table["ew_eligible"].to_numpy(bool)
    lab = table[f"label_{H}"].to_numpy(float)
    onset = table[f"onset_{H}"].to_numpy(float)
    obs_min = exposure_minutes(o, pids, rows & issued, cadence)
    elig_min = exposure_minutes(o, pids, rows & issued & elig & np.isfinite(lab), cadence)
    results, per = [], {}
    for pid in pd.unique(pids[rows]):
        r = pids == pid
        res = alert_eval.evaluate_patient(o[r], rows[r], elig[r], issued[r], score[r], lab[r], onset[r],
                                          threshold, float(H), merge)
        results.append(res)
        per[pid] = res
    s = alert_eval.summarize(results, elig_min / 1440.0, obs_min / 1440.0, float(H))
    s["time_base"] = ("exposure: sum over issued origins of min(next issued origin - t, 5 min) per person "
                      "(non-overlapping, gap-respecting)")
    s["observed_forecastable_hours"] = obs_min / 60.0
    s["eligible_uncensored_hours"] = elig_min / 60.0
    s["legacy_observed_days_approx"] = float((rows & issued).sum() * cadence / 1440.0)
    s["censored_warnings"] = s.pop("unresolved_episodes")
    s["assessable_warnings"] = s["warning_episodes"] - s["censored_warnings"]
    s["matched_warnings"] = s["assessable_warnings"] - s["false_alarm_episodes"]
    s["missed_onsets"] = s["true_onsets"] - s["detected_onsets"]
    m = rows & issued & elig & np.isfinite(lab) & np.isfinite(score)
    if m.sum() and 0 < lab[m].sum() < m.sum():
        from sklearn.metrics import average_precision_score
        s["origin_pr_auc"] = float(average_precision_score(lab[m], score[m]))
    else:
        s["origin_pr_auc"] = None
    s["origin_pr_auc_unit"] = "eligible origins with resolved labels (not episodes)"
    s["suppressed_not_eligible_origins"] = int((rows & issued & ~elig).sum())
    s["no_forecast_origins"] = int((rows & ~issued).sum())
    s["censored_label_origins"] = int((rows & issued & elig & ~np.isfinite(lab)).sum())
    s["participants"] = int(len(per))
    s["participants_with_onsets"] = int(sum(1 for r in results if r.detectable_onsets))
    # raw material for pooled medians and participant-cluster bootstrap (stripped from API payloads)
    s["_qualified_leads"] = [x for r in results for x in r.qualified_leads]
    s["_episode_start_leads"] = [x for r in results for x in r.lead_times]
    s["_per_participant"] = {
        pid: {"onsets": len(r.detectable_onsets), "detected": r.matched_onsets, "episodes": len(r.episodes),
              "false_alarms": r.false_alarms, "censored": r.unresolved,
              "matched": sum(1 for e in r.episodes if e.get("outcome") == "true_warning"),
              "observed_min": exposure_minutes(o, pids, rows & issued & (pids == pid), cadence),
              "eligible_min": exposure_minutes(o, pids, rows & issued & elig & np.isfinite(lab) & (pids == pid), cadence)}
        for pid, r in per.items()}
    s["threshold"] = threshold
    s["horizon"] = H
    return s, per


def curve(table: pd.DataFrame, rows: np.ndarray, issued: np.ndarray, final: dict[int, np.ndarray], H: int,
          grid: list[float], merge: float, cadence: float) -> list[dict[str, Any]]:
    sc = scores(final, H)
    return [evaluate(table, rows, issued, sc, H, float(th), merge, cadence)[0] for th in grid]


def select_workload(rows: list[dict[str, Any]], budget: float) -> tuple[float | None, str]:
    """Max recall s.t. false alarms per observed forecastable patient-day <= budget. Ties: precision, fewer episodes,
    higher threshold. Requires at least one assessable warning; None when nothing is feasible."""
    ok = [r for r in rows if r["assessable_warnings"] > 0 and r["precision"] is not None
          and r["false_alarms_per_observed_patient_day"] is not None
          and r["false_alarms_per_observed_patient_day"] <= budget + 1e-12 and r["recall"] is not None]
    if not ok:
        return None, f"no threshold keeps false alarms at or below {budget} per observed forecastable patient-day"
    best = sorted(ok, key=lambda r: (-r["recall"], -r["precision"], r["warning_episodes"], -r["threshold"]))[0]
    return float(best["threshold"]), (f"recall {best['recall']:.3f} at {best['false_alarms_per_observed_patient_day']:.2f} "
                                      f"false alarms per observed day (budget {budget})")


def select_f1(rows: list[dict[str, Any]]) -> tuple[float | None, str]:
    ok = [r for r in rows if r["f1"] is not None]
    if not ok:
        return None, "F1 undefined at every threshold"
    best = sorted(ok, key=lambda r: (-r["f1"], r["warnings_per_patient_day"] or np.inf))[0]
    return float(best["threshold"]), f"F1 {best['f1']:.3f}"
