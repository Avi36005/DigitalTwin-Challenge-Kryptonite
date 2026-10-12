"""Warning-episode formation and event-level matching (configs/experiment.yaml ``alerts``).

* A firing origin is early-warning eligible (online state 'normal'), issued a forecast, and has
  score >= threshold.
* Firings within ``merge_minutes`` of the previous firing extend the same warning episode; repeated
  firings are counted separately and never inflate true positives.
* An episode matches the earliest unmatched detectable onset ``o`` with
  ``start < o <= last_firing + H``. Each onset matches at most one episode; episodes are matched in chronological
  order. ``match_episodes`` is the single implementation used offline (here) and online (``TwinEngine``).
* Two lead measures are reported and never mixed (Prompt 05, docs/decisions.md D-026):
  - episode-start-to-onset = o - start (the v1 "lead time"; can exceed H because an episode may chain firings);
  - qualified forecast lead = o - f for the earliest firing f of the episode with f < o <= f + H, i.e. a firing whose
    own forecast horizon contains the onset; always 0 < lead <= H.
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
    lead_times: list[float] = field(default_factory=list)          # episode-start-to-onset (v1 definition)
    qualified_leads: list[float] = field(default_factory=list)     # within the firing's own horizon
    matched_without_qualified_firing: int = 0


def form_episodes(times: np.ndarray, firing: np.ndarray, merge_minutes: float) -> list[dict]:
    eps: list[dict] = []
    for t in times[firing].tolist():
        if eps and t - eps[-1]["last"] <= merge_minutes:
            eps[-1]["last"] = t
            eps[-1]["firings"] += 1
            eps[-1]["firing_times"].append(t)
        else:
            eps.append({"start": t, "last": t, "firings": 1, "firing_times": [t]})
    return eps


def in_window(start: float, last: float, onset: float, horizon: float) -> bool:
    return start < onset <= last + horizon


def match_episodes(windows: list[tuple[float, float]], onsets: list[float], horizon: float) -> list[float | None]:
    """One-to-one chronological matching: each episode (start, last firing), in order, takes the earliest onset not
    yet matched with start < o <= last + H. Deterministic; shared by offline evaluation and the online twin."""
    ordered = sorted(onsets)
    used: set[float] = set()
    out: list[float | None] = []
    for start, last in windows:
        hit = next((o for o in ordered if o not in used and in_window(start, last, o, horizon)), None)
        if hit is not None:
            used.add(hit)
        out.append(hit)
    return out


def qualified_lead(firing_times: list[float], onset: float, horizon: float) -> tuple[float | None, float | None]:
    """(qualified lead, last supporting firing before the onset). The qualified lead uses the earliest firing whose own
    horizon contains the onset (f < o <= f + H); None when no firing of the episode qualifies."""
    before = [f for f in firing_times if f < onset]
    last_support = max(before) if before else None
    qualifying = [f for f in before if onset <= f + horizon]
    return (onset - min(qualifying) if qualifying else None), last_support


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
    label_at = {round(t, 6): lab for t, lab in zip(times.tolist(), label.tolist(), strict=True)}
    hits = match_episodes([(ep["start"], ep["last"]) for ep in eps], onsets, horizon)
    matched: set[float] = set()
    for ep, hit in zip(eps, hits, strict=True):
        res.repeated_firings += ep["firings"] - 1
        if hit is not None:
            matched.add(hit)
            q, support = qualified_lead(ep["firing_times"], hit, horizon)
            ep["matched_onset"] = hit
            ep["lead_time"] = hit - ep["start"]  # episode-start-to-onset (v1 name kept for compatibility)
            ep["episode_start_to_onset"] = hit - ep["start"]
            ep["qualified_lead"] = q
            ep["last_supporting_firing"] = support
            res.lead_times.append(hit - ep["start"])
            if q is None:
                res.matched_without_qualified_firing += 1
            else:
                res.qualified_leads.append(q)
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


def _quartiles(x: list[float]) -> list[float | None]:
    return [float(np.percentile(x, 25)), float(np.percentile(x, 75))] if x else [None, None]


def summarize(results: list[EpisodeResult], eligible_days: float, observed_days: float, horizon: float | None = None) -> dict:
    """Event-level summary. Time bases (both approximate: forecastable origins x 5-minute native cadence, see
    ``event_eval``): ``eligible`` = early-warning-eligible, forecast-issued, uncensored-label time; ``observed`` = all
    forecast-issued time. Every rate is also given on the other base so false alarms and warnings can be compared."""
    n_onsets = sum(len(r.detectable_onsets) for r in results)
    matched = sum(r.matched_onsets for r in results)
    n_eps = sum(len(r.episodes) for r in results)
    fa = sum(r.false_alarms for r in results)
    true_eps = sum(1 for r in results for e in r.episodes if e.get("outcome") == "true_warning")
    lead = [x for r in results for x in r.lead_times]
    qlead = [x for r in results for x in r.qualified_leads]
    recall = matched / n_onsets if n_onsets else None
    precision = true_eps / (true_eps + fa) if (true_eps + fa) else None
    f1 = (2 * precision * recall / (precision + recall)) if (recall and precision) else (0.0 if (recall == 0 or precision == 0) else None)
    per = lambda n, d: n / d if d > 0 else None  # noqa: E731
    return {
        "true_onsets": n_onsets, "detected_onsets": matched, "warning_episodes": n_eps,
        "false_alarm_episodes": fa, "unresolved_episodes": sum(r.unresolved for r in results),
        "repeated_firings": sum(r.repeated_firings for r in results),
        "recall": recall, "precision": precision, "f1": f1,
        # v1 names: false alarms per ELIGIBLE day, warnings per OBSERVED day (different denominators)
        "false_alarms_per_patient_day": per(fa, eligible_days),
        "warnings_per_patient_day": per(n_eps, observed_days),
        # common time bases
        "false_alarms_per_observed_patient_day": per(fa, observed_days),
        "warnings_per_eligible_patient_day": per(n_eps, eligible_days),
        "lead_time_median": float(np.median(lead)) if lead else None,  # episode-start-to-onset (v1 definition)
        "lead_time_iqr": _quartiles(lead),
        "episode_start_lead_max": float(max(lead)) if lead else None,
        "episode_start_lead_over_horizon": (sum(1 for x in lead if x > horizon) if horizon is not None else None),
        "qualified_lead_median": float(np.median(qlead)) if qlead else None,
        "qualified_lead_iqr": _quartiles(qlead),
        "qualified_lead_n": len(qlead),
        "matched_without_qualified_firing": sum(r.matched_without_qualified_firing for r in results),
        "eligible_patient_days": eligible_days,
        "observed_patient_days": observed_days,
        "time_base": "approximate: number of forecast-issued origins x 5-minute native cadence",
    }
