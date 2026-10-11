"""Research event definition: new onset of a sustained high-glucose episode.

Definition (configs/experiment.yaml ``event``):

* High: a native CGM observation strictly greater than 180 mg/dL. A reading of exactly 180 is not high.
* Confirmation: consecutive high native observations whose elapsed span (last - first) is at least
  15 minutes (minus a small declared timestamp jitter), with no gap between consecutive observations
  larger than the device's continuity limit. At a 5-minute cadence that requires four observations;
  three observations span only 10 minutes.
* Onset: the first high observation of the confirmed run.
* Recovery: a run of observations at or below the cutoff spanning at least 15 minutes under the same
  continuity rule. A return above the cutoff before recovery continues the same episode.
* A gap larger than the continuity limit resets the state to ``unknown``. A high run that begins after
  a gap has an uncertain onset; it is tracked as an episode but never counted as a clean new onset.
* At the start of a record the state is ``unknown`` until 15 minutes at or below the cutoff
  (-> ``normal``) or a confirmed high run (-> episode with uncertain onset) is observed.

The same machine produces the online state (information available at each observation) and, by
running forward from a copy of that state, the offline label for a forecast origin. Missing future
support yields a censored label, never a negative.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

UNKNOWN, NORMAL, IN_EPISODE = "unknown", "normal", "in_episode"


@dataclass(frozen=True)
class EventDefinition:
    threshold_mg_dl: float = 180.0
    confirm_minutes: float = 15.0
    recovery_minutes: float = 15.0
    max_gap_minutes: float = 7.5
    jitter_minutes: float = 1.0

    @property
    def confirm_span(self) -> float:
        return self.confirm_minutes - self.jitter_minutes

    @property
    def recovery_span(self) -> float:
        return self.recovery_minutes - self.jitter_minutes


@dataclass
class Onset:
    onset_at: float
    confirmed_at: float
    certain: bool


@dataclass
class EpisodeMachine:
    """Incremental episode state machine over native observations (times in minutes)."""

    definition: EventDefinition
    mode: str = UNKNOWN
    run_kind: str | None = None  # "high" | "low"
    run_start: float | None = None
    run_certain: bool = True
    last_time: float | None = None
    onsets: list[Onset] = field(default_factory=list)

    def clone(self) -> EpisodeMachine:
        m = copy.copy(self)
        m.onsets = []
        return m

    @property
    def public_state(self) -> str:
        if self.mode == UNKNOWN:
            return "unknown"
        if self.mode == NORMAL:
            return "pending_high" if self.run_kind == "high" else "normal"
        return "recovering" if self.run_kind == "low" else "in_episode"

    def pending_high_start(self) -> float | None:
        return self.run_start if self.run_kind == "high" else None

    def update(self, t: float, value: float) -> tuple[bool, Onset | None]:
        """Consume one observation. Returns (gap_detected, onset_confirmed_or_None)."""
        d = self.definition
        gap = self.last_time is not None and (t - self.last_time) > d.max_gap_minutes
        if gap:
            self.mode, self.run_kind, self.run_start = UNKNOWN, None, None
        self.last_time = t
        high = value > d.threshold_mg_dl
        onset: Onset | None = None

        if self.mode == NORMAL:
            if high:
                if self.run_kind != "high":
                    self.run_kind, self.run_start, self.run_certain = "high", t, True
                if t - self.run_start >= d.confirm_span:
                    onset = Onset(self.run_start, t, self.run_certain)
                    self.mode, self.run_kind, self.run_start = IN_EPISODE, None, None
            else:
                self.run_kind, self.run_start = None, None
        elif self.mode == IN_EPISODE:
            if not high:
                if self.run_kind != "low":
                    self.run_kind, self.run_start = "low", t
                if t - self.run_start >= d.recovery_span:
                    self.mode, self.run_kind, self.run_start = NORMAL, None, None
            else:
                self.run_kind, self.run_start = None, None
        else:  # UNKNOWN
            if high:
                if self.run_kind != "high":
                    self.run_kind, self.run_start, self.run_certain = "high", t, False
                if t - self.run_start >= d.confirm_span:
                    onset = Onset(self.run_start, t, False)
                    self.mode, self.run_kind, self.run_start = IN_EPISODE, None, None
            else:
                if self.run_kind != "low":
                    self.run_kind, self.run_start = "low", t
                if t - self.run_start >= d.recovery_span:
                    self.mode, self.run_kind, self.run_start = NORMAL, None, None
        if onset is not None:
            self.onsets.append(onset)
        return gap, onset


@dataclass
class EpisodeTrace:
    states: list[str]          # public state after each observation
    onsets: list[Onset]


def trace_episodes(times: np.ndarray, values: np.ndarray, definition: EventDefinition) -> EpisodeTrace:
    m = EpisodeMachine(definition)
    states: list[str] = []
    for t, v in zip(times.tolist(), values.tolist(), strict=True):
        m.update(t, v)
        states.append(m.public_state)
    return EpisodeTrace(states, m.onsets)


LabelStatus = Literal["positive", "negative", "censored", "ineligible"]


@dataclass
class OriginLabels:
    """Per-origin labels for one horizon."""

    eligible: np.ndarray        # bool: online state 'normal' at origin (early-warning eligible)
    state: list[str]            # online public state at origin
    label: np.ndarray           # float: 1, 0 or NaN (censored / ineligible)
    onset_at: np.ndarray        # float minutes or NaN
    support_end: np.ndarray     # time of the observation that resolved the label (NaN if never)
    censor_reason: list[str | None]


def label_new_onsets(
    times: np.ndarray, values: np.ndarray, definition: EventDefinition, horizon_minutes: float
) -> OriginLabels:
    """Label each observation (forecast origin) for a new confirmed onset in (t, t + horizon]."""
    n = len(times)
    t_list, v_list = times.tolist(), values.tolist()
    m = EpisodeMachine(definition)
    eligible = np.zeros(n, dtype=bool)
    label = np.full(n, np.nan)
    onset_at = np.full(n, np.nan)
    support_end = np.full(n, np.nan)
    states: list[str] = []
    reasons: list[str | None] = []
    for i in range(n):
        m.update(t_list[i], v_list[i])
        st = m.public_state
        states.append(st)
        if st != "normal":
            reasons.append(f"origin_state_{st}")
            continue
        eligible[i] = True
        t0 = t_list[i]
        end = t0 + horizon_minutes
        fwd = m.clone()
        decided = False
        for j in range(i + 1, n):
            gap, onset = fwd.update(t_list[j], v_list[j])
            if gap:
                reasons.append("gap_in_label_support")
                decided = True
                break
            if onset is not None:
                if onset.onset_at <= end:
                    label[i], onset_at[i] = 1.0, onset.onset_at
                else:
                    label[i] = 0.0
                support_end[i] = t_list[j]
                reasons.append(None)
                decided = True
                break
            if t_list[j] > end:
                pend = fwd.pending_high_start()
                if pend is None or pend > end:
                    label[i] = 0.0
                    support_end[i] = t_list[j]
                    reasons.append(None)
                    decided = True
                    break
        if not decided:
            reasons.append("end_of_record")
    return OriginLabels(eligible, states, label, onset_at, support_end, reasons)
