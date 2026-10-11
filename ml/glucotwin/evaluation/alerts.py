"""Warning-episode formation and event-level matching (configs/experiment.yaml ``alerts``).

* A firing origin is early-warning eligible (online state 'normal'), issued a forecast, and has
  score >= threshold.
* Firings within ``merge_minutes`` of the previous firing extend the same warning episode; repeated
  firings are counted separately and never inflate true positives.
* An episode matches the earliest unmatched detectable onset ``o`` with
  ``start < o <= last_firing + H``. Each onset matches at most one episode. Lead time = o - start.
* Unmatched episodes are false alarms when the label at the episode start is uncensored; otherwise
  they are reported as unresolved.
* Detectable onsets are distinct onsets that have at least one eligible origin labelled positive in
  the evaluated segment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class EpisodeResult:
    episodes: list[dict] = field(default_factory=list)
    detectable_onsets: list[float] = field(default_factory=list)
    matched_onsets: int = 0
    false_alarms: int = 0
    unresolved: int = 0
    repeated_firings: int = 0
    lead_times: list[float] = field(default_factory=list)


def form_episodes(times: np.ndarray, firing: np.ndarray, merge_minutes: float) -> list[dict]:
    eps: list[dict] = []
    for t in times[firing].tolist():
        if eps and t - eps[-1]["last"] <= merge_minutes:
            eps[-1]["last"] = t
            eps[-1]["firings"] += 1
        else:
            eps.append({"start": t, "last": t, "firings": 1})
    return eps


def evaluate_patient(
    times: np.ndarray,
    in_segment: np.ndarray,
    eligible: np.ndarray,
    issued: np.ndarray,
    score: np.ndarray,
    label: np.ndarray,
    onset: np.ndarray,
    threshold: float,
    horizon: float,
    merge_minutes: float,
) -> EpisodeResult:
    firing = in_segment & eligible & issued & np.isfinite(score) & (score >= threshold)
    eps = form_episodes(times, firing, merge_minutes)
    pos = in_segment & eligible & (label == 1)
    onsets = sorted(set(np.round(onset[pos], 6).tolist()))
    res = EpisodeResult(detectable_onsets=onsets)
    matched: set[float] = set()
    label_at = {round(t, 6): lab for t, lab in zip(times.tolist(), label.tolist(), strict=True)}
    for ep in eps:
        res.repeated_firings += ep["firings"] - 1
        hit = None
        for o in onsets:
            if o in matched:
                continue
            if ep["start"] < o <= ep["last"] + horizon:
                hit = o
                break
        if hit is not None:
            matched.add(hit)
            ep["matched_onset"] = hit
            ep["lead_time"] = hit - ep["start"]
            res.lead_times.append(hit - ep["start"])
            ep["outcome"] = "true_warning"
        else:
            lab = label_at.get(round(ep["start"], 6), np.nan)
            if lab is None or (isinstance(lab, float) and np.isnan(lab)):
                ep["outcome"] = "unresolved"
                res.unresolved += 1
            else:
                ep["outcome"] = "false_alarm"
                res.false_alarms += 1
    res.matched_onsets = len(matched)
    res.episodes = eps
    return res


def summarize(results: list[EpisodeResult], eligible_days: float, observed_days: float) -> dict:
    n_onsets = sum(len(r.detectable_onsets) for r in results)
    matched = sum(r.matched_onsets for r in results)
    n_eps = sum(len(r.episodes) for r in results)
    fa = sum(r.false_alarms for r in results)
    true_eps = sum(1 for r in results for e in r.episodes if e.get("outcome") == "true_warning")
    lead = [x for r in results for x in r.lead_times]
    recall = matched / n_onsets if n_onsets else None
    precision = true_eps / (true_eps + fa) if (true_eps + fa) else None
    f1 = (2 * precision * recall / (precision + recall)) if (recall and precision) else (0.0 if (recall == 0 or precision == 0) else None)
    return {
        "true_onsets": n_onsets, "detected_onsets": matched, "warning_episodes": n_eps,
        "false_alarm_episodes": fa, "unresolved_episodes": sum(r.unresolved for r in results),
        "repeated_firings": sum(r.repeated_firings for r in results),
        "recall": recall, "precision": precision, "f1": f1,
        "false_alarms_per_patient_day": fa / eligible_days if eligible_days > 0 else None,
        "warnings_per_patient_day": n_eps / observed_days if observed_days > 0 else None,
        "lead_time_median": float(np.median(lead)) if lead else None,
        "lead_time_iqr": [float(np.percentile(lead, 25)), float(np.percentile(lead, 75))] if lead else [None, None],
        "eligible_patient_days": eligible_days,
    }
