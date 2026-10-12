"""Canonical GlucoTwin contracts (schema_version 1.0).

This module is the single source of truth for externally consumed payloads. The FastAPI service
uses these models directly, the OpenAPI document is exported from the service, and the web client's
TypeScript types are generated from that export (see packages/contracts).

Conventions
-----------
* Missing numeric values are ``None`` (JSON ``null``) — never 0, "N/A" or NaN.
* Timestamps are offset-qualified ISO-8601 strings. Dataset timelines use a declared synthetic UTC
  mapping (see ``TimePolicy``); the ``Z`` suffix is a transport convention, not a verified timezone.
* Glucose is mg/dL in every canonical payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: Literal["1.0"] = "1.0"

ReplayMode = Literal["dataset_replay", "synthetic_demo"]
SessionStatus = Literal["ready", "playing", "paused", "completed", "error"]
QualityStatus = Literal["ok", "degraded", "insufficient"]
EventKind = Literal["glucose", "meal", "activity"]
ControlAction = Literal["play", "pause", "step", "seek", "reset"]
EpisodeState = Literal["normal", "pending_high", "in_episode", "recovering", "unknown"]
SplitSegment = Literal["training", "validation", "calibration", "test", "unassigned"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", ser_json_inf_nan="null")


class Versioned(Contract):
    schema_version: Literal["1.0"] = SCHEMA_VERSION


# --------------------------------------------------------------------------------------------
# Shared small types
# --------------------------------------------------------------------------------------------


class ReasonCode(Contract):
    """Machine-readable code plus a plain-language explanation."""

    code: str
    message: str


class DatasetRef(Contract):
    name: str
    version: str
    license: str
    citation_url: str | None = None
    synthetic: bool = False


class TimePolicy(Contract):
    policy_id: str
    description: str
    source_timezone_known: bool
    calendar_values_synthetic: bool


class CohortLabel(Contract):
    label: str
    provenance: str


# --------------------------------------------------------------------------------------------
# Patients
# --------------------------------------------------------------------------------------------


class AttributeAvailability(Contract):
    name: str
    label: str
    unit: str | None = None
    present_in_source: bool
    source: str | None = None
    availability_rule: str | None = None
    note: str | None = None


class DataCoverage(Contract):
    primary_device: str | None = None
    native_cadence_minutes: float | None = None
    recording_days: float | None = None
    glucose_samples: int | None = None
    glucose_coverage_fraction: float | None = None
    gaps_over_threshold: int | None = None
    meals_logged: int | None = None
    activity_coverage_fraction: float | None = None


class SessionBrief(Contract):
    session_id: str
    status: SessionStatus
    clock_at: datetime
    revision: int


class PatientSummary(Versioned):
    """Catalogue entry. Contains identifiers and field-availability metadata, never clinical values."""

    patient_id: str
    display_alias: str
    mode: ReplayMode
    dataset: DatasetRef
    cohort: CohortLabel
    eligible_for_primary_analysis: bool
    exclusion_reason: str | None = None
    attributes: list[AttributeAvailability]
    missing_fields: list[str]
    coverage: DataCoverage
    active_session: SessionBrief | None = None


class EvaluationSegment(Contract):
    name: SplitSegment
    start_at: datetime
    end_at: datetime


class PatientDetail(PatientSummary):
    time_policy: TimePolicy
    availability_policy_id: str
    notes: list[str] = Field(default_factory=list)
    evaluation_segments: list[EvaluationSegment] | None = Field(
        default=None,
        description="Chronological split segments for participants in the measured evaluation. Forecasts issued "
                    "in the training segment are in-sample for the population model.",
    )


class PatientPage(Versioned):
    items: list[PatientSummary]
    next_cursor: str | None = None
    total: int = Field(description="Participants matching the filters (all pages), not the size of this page.")
    total_unfiltered: int | None = Field(default=None, description="Participants in the catalogue before filtering.")


class ProfileValue(Contract):
    name: str
    label: str
    value: float | str | None
    unit: str | None = None
    source: str | None = None
    available_at: datetime | None = None
    status: Literal["available", "not_yet_available", "missing_in_source", "excluded_suspect"]
    note: str | None = None


class SessionProfile(Versioned):
    """Baseline values as known at the session clock. Future values are withheld."""

    session_id: str
    patient_id: str
    session_revision: int
    as_of: datetime
    cohort: CohortLabel
    values: list[ProfileValue]


# --------------------------------------------------------------------------------------------
# Observations and replay
# --------------------------------------------------------------------------------------------


class ObservationEvent(Versioned):
    event_id: str
    patient_id: str
    kind: EventKind
    observed_at: datetime
    available_at: datetime
    source: str
    quality: Literal["ok", "suspect", "estimated"]
    quality_flags: list[str] = Field(default_factory=list)
    units: dict[str, str]
    values: dict[str, float | str | None]


class TimelineBounds(Contract):
    start_at: datetime
    end_at: datetime
    step_minutes: int


class FreshnessInfo(Contract):
    latest_glucose_at: datetime | None
    latest_glucose_age_minutes: float | None
    stale_threshold_minutes: float
    status: Literal["fresh", "stale", "no_data"]


class ReplaySession(Versioned):
    id: str
    patient_id: str
    patient_alias: str
    created_at: datetime = Field(description="Wall-clock creation time of the session (not replay time).")
    mode: ReplayMode
    clock_at: datetime
    status: SessionStatus
    speed: float = Field(description="Replay minutes advanced per wall-clock second while playing.")
    revision: int
    timeline: TimelineBounds
    time_policy: TimePolicy
    freshness: FreshnessInfo
    released_event_count: int
    error: ReasonCode | None = None


class ReplaySessionList(Versioned):
    items: list[ReplaySession]


class CreateSessionRequest(Contract):
    patient_id: str
    mode: ReplayMode
    start_at: datetime | None = Field(
        default=None, description="Initial replay clock. Defaults to the start of the timeline."
    )
    speed: float = Field(default=10.0, gt=0, le=240)


class ControlCommand(Contract):
    action: ControlAction
    steps: int | None = Field(default=None, ge=1, le=2016)
    seek_to: datetime | None = None
    speed: float | None = Field(default=None, gt=0, le=240)

    @model_validator(mode="after")
    def _check(self) -> ControlCommand:
        if self.action == "seek" and self.seek_to is None:
            raise ValueError("seek requires seek_to")
        if self.action != "seek" and self.seek_to is not None:
            raise ValueError("seek_to is only valid with action 'seek'")
        if self.action != "step" and self.steps is not None:
            raise ValueError("steps is only valid with action 'step'")
        return self

    @field_validator("seek_to")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("seek_to must include a UTC offset")
        return v


class EventPage(Versioned):
    session_id: str
    session_revision: int
    clock_at: datetime
    items: list[ObservationEvent]
    next_cursor: str
    has_more: bool


# --------------------------------------------------------------------------------------------
# Twin state and forecasts
# --------------------------------------------------------------------------------------------


class HorizonAdaptation(Contract):
    horizon_minutes: int
    matured_residuals: int
    min_required: int
    correction_mg_dl: float | None
    last_matured_at: datetime | None = None
    consumed_forecast_ids: list[str] = Field(
        default_factory=list, description="Most recent forecast IDs whose matured residuals feed the state."
    )


class Personalization(Contract):
    enabled: bool
    status: Literal["disabled", "warming_up", "active", "reset_after_gap"]
    policy_id: str | None = None
    state_version: int
    horizons: list[HorizonAdaptation]


class ObservedGlucose(Contract):
    event_id: str
    value_mg_dl: float
    observed_at: datetime
    available_at: datetime


class HistorySummary(Contract):
    lookback_minutes: int
    available_minutes: float | None
    valid_samples_lookback: int
    valid_samples_60: int
    latest_glucose: ObservedGlucose | None


class TwinState(Versioned):
    session_id: str
    patient_id: str
    session_revision: int
    as_of: datetime
    state_version: int
    model_version: str | None
    model_family: str | None
    personalization: Personalization
    history: HistorySummary
    episode_state: EpisodeState
    supporting_event_ids: list[str]
    consumed_event_count: int
    issued_forecast_count: int


class EstimateComponents(Contract):
    population_mg_dl: float | None
    patient_correction_mg_dl: float | None


class HorizonEstimate(Contract):
    horizon_minutes: int
    target_at: datetime
    predicted_mg_dl: float | None
    lower_mg_dl: float | None = None
    upper_mg_dl: float | None = None
    interval_level: float | None = None
    interval_status: Literal["calibrated", "unavailable"] = "unavailable"
    components: EstimateComponents | None = None


class TrajectoryPoint(Contract):
    target_at: datetime
    predicted_mg_dl: float | None


class EventRisk(Contract):
    horizon_minutes: int
    probability: float | None = Field(default=None, description="Calibrated probability; null unless measured.")
    score: float | None = None
    score_kind: Literal["forecast_margin_mg_dl", "none"]
    score_description: str
    state: Literal["eligible", "already_high", "in_episode", "unknown", "insufficient"]
    alert_threshold: float | None = None
    alert_fired: bool = False


class ForecastQuality(Contract):
    status: QualityStatus
    reasons: list[ReasonCode]


class Explanation(Contract):
    code: str
    text: str
    kind: Literal["observation", "data_quality", "model_association", "personalization"]
    evidence_event_ids: list[str] = Field(default_factory=list)


class Forecast(Versioned):
    forecast_id: str
    session_id: str
    patient_id: str
    session_revision: int
    as_of: datetime
    mode: ReplayMode
    model_version: str | None
    model_family: str | None
    personalization: Personalization
    observed_glucose: ObservedGlucose | None
    estimates: list[HorizonEstimate]
    trajectory: list[TrajectoryPoint] | None = None
    event_risk: list[EventRisk]
    episode_state: EpisodeState
    quality: ForecastQuality
    explanations: list[Explanation]
    split_segment: SplitSegment | None = Field(
        default=None,
        description="Evaluation segment that contains this origin. 'training' origins are in-sample for the model.",
    )


class LatestForecast(Versioned):
    session_id: str
    session_revision: int
    clock_at: datetime
    availability: Literal["available", "stale", "not_ready"]
    age_minutes: float | None
    reasons: list[ReasonCode]
    forecast: Forecast | None


class ForecastPage(Versioned):
    session_id: str
    session_revision: int
    clock_at: datetime
    items: list[Forecast]
    next_cursor: str | None
    order: Literal["asc", "desc"]


# --------------------------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------------------------


class AlertEvidence(Contract):
    forecast_id: str
    score: float | None
    score_kind: str
    threshold: float | None
    latest_glucose_mg_dl: float | None
    predicted_mg_dl: dict[str, float | None]
    explanation_codes: list[str]
    # the warning policy this warning was issued under (pinned for the life of the session)
    policy_id: str | None = None
    rule_version: str | None = None
    experiment_id: str | None = None
    score_units: str | None = None
    episode_merge_minutes: float | None = None
    applicability: str | None = None


class AlertOutcome(Contract):
    status: Literal["pending", "onset_observed", "no_onset_observed", "unknown"]
    onset_at: datetime | None = None
    confirmed_at: datetime | None = None
    lead_time_minutes: float | None = Field(
        default=None, description="Deprecated alias of episode_start_to_onset_minutes (v1 'lead time').")
    episode_start_to_onset_minutes: float | None = Field(
        default=None, description="Onset minus the first warning of the merged episode. Can exceed the horizon.")
    qualified_lead_minutes: float | None = Field(
        default=None, description="Onset minus the earliest firing whose own horizon contains the onset (0 < x <= H).")
    last_supporting_forecast_at: datetime | None = None
    note: str | None = None


class Acknowledgement(Contract):
    acknowledged: bool
    acknowledged_at: datetime | None = None
    note: str | None = None
    meaning: str = "Marked as reviewed in this local research session. No message was sent to anyone."


class Alert(Versioned):
    alert_id: str
    session_id: str
    patient_id: str
    session_revision: int
    issued_at: datetime
    last_supported_at: datetime
    horizon_minutes: int
    rule_version: str
    model_version: str | None
    kind: Literal["predicted_new_high_episode"]
    title: str
    evidence: AlertEvidence
    supporting_forecast_ids: list[str]
    state: Literal["open", "closed"]
    outcome: AlertOutcome
    acknowledgement: Acknowledgement


class AlertList(Versioned):
    session_id: str
    session_revision: int
    clock_at: datetime
    rule_available: bool
    rule_description: str | None
    items: list[Alert]


class AcknowledgementRequest(Contract):
    note: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------------


class MetricValue(Contract):
    value: float | None
    reason_if_null: str | None = None
    ci_low: float | None = None
    ci_high: float | None = None


class ModelResultRow(Contract):
    model_family: str
    model_label: str
    feature_set_id: str
    personalization: Literal["off", "adaptive", "frozen_state"]
    split: Literal["validation", "test"]
    horizon_minutes: int
    mae_mg_dl: MetricValue
    rmse_mg_dl: MetricValue
    n_patients: int
    n_origins: int
    coverage_fraction: float | None
    train_seconds: float | None = None
    inference_ms_per_1k: float | None = None
    selected_for_serving: bool = False


class EventMetricsRow(Contract):
    model_label: str
    horizon_minutes: int
    split: Literal["validation", "test"]
    threshold: float | None
    true_onsets: int
    detected_onsets: int
    warning_episodes: int
    false_alarm_episodes: int
    recall: MetricValue
    precision: MetricValue
    f1: MetricValue
    origin_pr_auc: MetricValue
    false_alarms_per_patient_day: MetricValue
    warnings_per_patient_day: MetricValue
    lead_time_minutes_median: MetricValue = Field(description="Episode-start-to-onset time (v1 definition), median.")
    lead_time_minutes_iqr: list[float | None]
    eligible_patient_days: float
    censored_origins: int
    # added with the Prompt 05 corrections; null for reports produced before them
    observed_patient_days: float | None = None
    false_alarms_per_observed_patient_day: MetricValue | None = None
    warnings_per_eligible_patient_day: MetricValue | None = None
    qualified_lead_minutes_median: MetricValue | None = None
    qualified_lead_minutes_iqr: list[float | None] | None = None
    qualified_lead_n: int | None = None
    episode_start_lead_max_minutes: float | None = None
    episode_start_lead_over_horizon: int | None = None
    matched_without_qualified_firing: int | None = None
    time_base: str | None = None


class IntervalMetricsRow(Contract):
    model_label: str
    horizon_minutes: int
    split: Literal["calibration", "test"]
    interval_level: float
    empirical_coverage: MetricValue
    mean_width_mg_dl: MetricValue
    per_patient_coverage_min: float | None
    per_patient_coverage_max: float | None
    n_origins: int


class CohortAccounting(Contract):
    participants_in_source: int | None
    participants_in_cohort: int | None
    participants_included: int
    excluded: list[dict[str, Any]]
    origins_by_split: dict[str, int]
    events_by_split: dict[str, int]
    covered_hours_by_split: dict[str, float]


class SelectionRecord(Contract):
    rule: str
    tie_break: str
    candidates: list[dict[str, Any]]
    selected_model_label: str | None
    selected_model_family: str | None
    rationale: str


class EvaluationReport(Versioned):
    status: Literal["completed", "not_run", "unavailable", "synthetic_only"]
    status_message: str
    experiment_id: str | None = None
    corrects_experiment_id: str | None = Field(
        default=None, description="Earlier experiment this one corrects; that test segment was already inspected.")
    correction_note: str | None = None
    created_at: datetime | None = None
    mode: ReplayMode | None = None
    dataset: DatasetRef | None = None
    fingerprints: dict[str, str] = Field(default_factory=dict)
    protocol: dict[str, Any] = Field(default_factory=dict)
    cohort: CohortAccounting | None = None
    selection: SelectionRecord | None = None
    forecast_results: list[ModelResultRow] = Field(default_factory=list)
    per_patient: list[dict[str, Any]] = Field(default_factory=list)
    event_results: list[EventMetricsRow] = Field(default_factory=list)
    interval_results: list[IntervalMetricsRow] = Field(default_factory=list)
    optional_experiments: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------------
# Experiment catalogue, research reports, serving summary and dataset inventory (additive, schema 1.0)
# --------------------------------------------------------------------------------------------

EvaluationRegime = Literal["serving_retrospective", "superseded_original", "nested_research"]
AccessStatus = Literal["planned", "access_required", "available_locally", "imported", "failed_validation",
                       "eligible_for_experiment"]


class EvaluationSummary(Contract):
    experiment_id: str
    regime: EvaluationRegime
    title: str
    description: str
    status: Literal["completed", "not_run", "development_only", "unavailable"]
    created_at: datetime | None = None
    is_serving_evidence: bool = Field(description="True only for the experiment that produced the serving model.")


class EvaluationList(Versioned):
    items: list[EvaluationSummary]
    serving_experiment_id: str | None = None


class ServingSummary(Versioned):
    mode: ReplayMode
    status: Literal["ready", "unavailable"]
    detail: str
    model_version: str | None = None
    model_family: str | None = None
    feature_set_id: str | None = None
    experiment_id: str | None = None
    evaluation_regime: EvaluationRegime | None = None
    adaptation: dict[str, Any] | None = None
    interval_level: float | None = None
    interval_quantiles_mg_dl: dict[str, float | None] | None = None
    warning_threshold_margin_mg_dl: float | None = None
    warning_horizon_minutes: int | None = None


class ServingList(Versioned):
    items: list[ServingSummary]


class ResearchHorizonResult(Contract):
    horizon: int
    mae: float | None
    rmse: float | None
    mae_high_glucose_target: float | None = Field(
        default=None, description="Macro MAE on origins whose target exceeded 180 mg/dL (people with >= 20 such origins).")
    high_glucose_participants: int
    n_participants: int
    n_origins: int
    availability: float | None = Field(
        default=None, description="Share of target-bearing origins that received a forecast. Not accuracy.")
    cold_start: dict[str, dict[str, Any]]
    unavailable_forecasts: int


class ResearchPipeline(Contract):
    pipeline: str
    mode: str
    display: str
    config: str | None = None
    feature_set: str | None = None
    selected: bool | None = None
    horizons: dict[str, ResearchHorizonResult]
    intervals: dict[str, dict[str, Any]]
    inference_ms_per_1k: float | None = None


class ResearchComparison(Contract):
    comparison: str
    horizon: int
    kind: str | None = None
    a: list[str] | None = None
    b: list[str] | None = None
    mean_diff: float | None
    ci95: list[float | None]
    n_participants: int
    improved: int
    worsened: int
    unchanged: int | None = None


class ResearchTrack(Contract):
    name: str
    participants: int
    selection_by_fold: dict[str, dict[str, Any]]
    pipelines: list[ResearchPipeline]
    comparisons: list[ResearchComparison]
    warnings: dict[str, Any] | None = None


class ResearchExternal(Contract):
    status: Literal["completed", "not_run"]
    reason: str | None = None
    dataset: str | None = None
    opened: dict[str, Any] | None = None
    candidate: str | None = None
    candidate_freeze_hash: str | None = None
    participants: int | None = None
    decimation: dict[str, Any] | None = None
    pipelines: list[ResearchPipeline] = Field(default_factory=list)
    comparisons: list[ResearchComparison] = Field(default_factory=list)
    note: str | None = None


class ResearchReport(Versioned):
    """Nested participant-level research experiment (internal folds + reserved external cohort)."""

    experiment_id: str
    status: Literal["completed", "not_run"]
    status_message: str
    kind: str | None = None
    created_at: datetime | None = None
    declared_on: str | None = None
    frozen_at: str | None = None
    protocol_hash: str | None = None
    split_hash: str | None = None
    assessment_opened: dict[str, Any] | None = None
    inspection_log: list[dict[str, Any]] = Field(default_factory=list)
    folds: list[dict[str, Any]] = Field(default_factory=list)
    tracks: dict[str, ResearchTrack] = Field(default_factory=dict)
    external: ResearchExternal | None = None
    candidates: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class DatasetEntry(Contract):
    dataset_id: str
    name: str
    release: str | None = None
    access_status: AccessStatus
    role: str | None = None
    license: str | None = None
    country_site: str | None = None
    native_cadence_minutes: list[float] = Field(default_factory=list)
    publisher_participants: int | None = Field(default=None, description="Publisher-reported scale: external metadata.")
    acquired_participants: int | None = None
    parsed_participants: int | None = None
    eligible: dict[str, int] = Field(default_factory=dict)
    native_readings: int | None = None
    observed_hours: float | None = None
    wearable: str | None = None
    profile: str | None = None
    split_counts: dict[str, Any] | None = None
    detail: str | None = None
    user_steps: list[str] = Field(default_factory=list)
    citation_url: str | None = None


class DatasetInventory(Versioned):
    status: Literal["available", "not_generated"]
    generated_at: datetime | None = None
    canonical_schema: str | None = None
    datasets: list[DatasetEntry] = Field(default_factory=list)
    summary_sentence: str | None = Field(
        default=None, description="Rendered only from verified assessed counts; null when they are not available.")
    overlap_check: dict[str, Any] | None = None
    synthetic: dict[str, Any] | None = None


# --------------------------------------------------------------------------------------------
# Health and errors
# --------------------------------------------------------------------------------------------


class Health(Versioned):
    status: Literal["ok"]
    service: str
    version: str


class ComponentReadiness(Contract):
    ready: bool
    detail: str
    version: str | None = None


class Readiness(Versioned):
    ready: bool
    dataset: ComponentReadiness
    synthetic: ComponentReadiness
    model: ComponentReadiness
    evaluation: ComponentReadiness


class ErrorBody(Contract):
    code: str
    message: str
    request_id: str | None = None
    details: list[dict[str, Any]] | None = None


class ErrorEnvelope(Versioned):
    error: ErrorBody
