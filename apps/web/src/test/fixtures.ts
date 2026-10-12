import type { Forecast, LatestForecast, ObservationEvent, ReplaySession } from "@/api/types";

export function session(over: Partial<ReplaySession> = {}): ReplaySession {
  return {
    schema_version: "1.0", id: "s1", patient_id: "SYN-A", patient_alias: "Synthetic Participant A",
    created_at: "2026-10-11T10:00:00Z", mode: "synthetic_demo", clock_at: "2000-01-03T10:00:00Z", status: "paused",
    speed: 10, revision: 1,
    timeline: { start_at: "2000-01-03T00:00:00Z", end_at: "2000-01-07T00:00:00Z", step_minutes: 5 },
    time_policy: { policy_id: "synthetic-timeline-v1", description: "Fictional", source_timezone_known: false,
      calendar_values_synthetic: true },
    freshness: { latest_glucose_at: "2000-01-03T09:57:00Z", latest_glucose_age_minutes: 3, stale_threshold_minutes: 15,
      status: "fresh" },
    released_event_count: 10, error: null, ...over,
  };
}

export function glucose(id: string, observed: string, value: number, available = observed): ObservationEvent {
  return { schema_version: "1.0", event_id: id, patient_id: "SYN-A", kind: "glucose", observed_at: observed,
    available_at: available, source: "synthetic", quality: "ok", quality_flags: [], units: { value: "mg/dL" },
    values: { value } };
}

export function meal(id: string, observed: string, available: string): ObservationEvent {
  return { schema_version: "1.0", event_id: id, patient_id: "SYN-A", kind: "meal", observed_at: observed,
    available_at: available, source: "synthetic", quality: "estimated", quality_flags: [], units: { carbohydrate: "g" },
    values: { meal_type: "Lunch", carbohydrate: 60 } };
}

export function forecast(over: Partial<Forecast> = {}, interval = true): Forecast {
  return {
    schema_version: "1.0", forecast_id: "f1", session_id: "s1", patient_id: "SYN-A", session_revision: 1,
    as_of: "2000-01-03T09:57:00Z", mode: "synthetic_demo", model_version: "synthetic-demo", model_family: "lightgbm",
    personalization: { enabled: true, status: "warming_up", policy_id: "p", state_version: 1, horizons: [] },
    observed_glucose: { event_id: "g1", value_mg_dl: 150, observed_at: "2000-01-03T09:57:00Z", available_at: "2000-01-03T09:57:00Z" },
    estimates: [30, 60].map((h) => ({
      horizon_minutes: h, target_at: `2000-01-03T${h === 30 ? "10:27" : "10:57"}:00Z`, predicted_mg_dl: 160 + h / 10,
      lower_mg_dl: interval ? 140 : null, upper_mg_dl: interval ? 185 : null, interval_level: interval ? 0.8 : null,
      interval_status: interval ? "calibrated" : "unavailable", components: { population_mg_dl: 160, patient_correction_mg_dl: 0 },
    })),
    trajectory: null,
    event_risk: [30, 60].map((h) => ({ horizon_minutes: h, probability: null, score: -12, score_kind: "forecast_margin_mg_dl",
      score_description: "", state: "eligible", alert_threshold: h === 60 ? 0 : null, alert_fired: false })),
    episode_state: "normal", quality: { status: "ok", reasons: [] }, explanations: [], split_segment: null, ...over,
  } as Forecast;
}

export function latest(f: Forecast | null, over: Partial<LatestForecast> = {}): LatestForecast {
  return { schema_version: "1.0", session_id: "s1", session_revision: 1, clock_at: "2000-01-03T10:00:00Z",
    availability: f ? "available" : "not_ready", age_minutes: f ? 3 : null,
    reasons: f ? [] : [{ code: "forecast_insufficient", message: "The twin abstained at the latest origin." }],
    forecast: f, ...over };
}
