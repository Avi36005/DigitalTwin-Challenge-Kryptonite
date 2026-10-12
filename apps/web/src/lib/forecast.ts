/** Wording helpers for forecast state. Pure functions; every value comes from API responses. */
import type { EvaluationReport, LatestForecast, TwinState } from "@/api/types";

/** Feature-set id encoded in a model version, e.g. "lightgbm.dyn-v1.<experiment>" → "dyn-v1". Null if not encoded. */
export function featureSetOf(modelVersion: string | null | undefined): string | null {
  const m = modelVersion?.match(/(?:^|\.)(dyn(?:-[a-z]+)*-v\d+)(?:\.|$)/);
  return m ? m[1] : null;
}

/** True/false when the model version states whether profile (baseline) features are inputs; null when unknown. */
export function modelUsesProfile(modelVersion: string | null | undefined): boolean | null {
  const fs = featureSetOf(modelVersion);
  return fs === null ? null : fs.includes("prof");
}

export type Unavailable = { kind: "model" | "no_data" | "abstained" | "stale" | "loading"; title: string; detail: string };

/**
 * Why no usable forecast is shown, in plain words. Loading, model absence, missing data, abstention and staleness are
 * different states and are never collapsed into one another (and never into "low risk").
 */
export function unavailableReason(latest: LatestForecast | undefined, twin: TwinState | undefined, loading: boolean): Unavailable | null {
  if (!latest) return loading ? { kind: "loading", title: "Loading forecast…", detail: "" } : null;
  const codes = new Set([...latest.reasons.map((r) => r.code), ...(latest.forecast?.quality.reasons.map((r) => r.code) ?? [])]);
  if (codes.has("model_unavailable")) {
    const msg = latest.reasons.find((r) => r.code === "model_unavailable")?.message;
    return { kind: "model", title: "Model unavailable", detail: msg ?? "No verified forecasting model is loaded for this data mode." };
  }
  if (latest.availability === "stale") {
    const age = latest.age_minutes;
    return { kind: "stale", title: "Forecast out of date",
      detail: `Issued ${age != null ? `${Math.round(age)} min` : "some time"} before the replay clock; no newer glucose reading has arrived.` };
  }
  if (latest.availability === "available") return null;
  if (codes.has("no_forecast_yet") || codes.has("no_glucose_history")) {
    return { kind: "no_data", title: "Forecast unavailable", detail: "No glucose reading has been released by the replay clock yet." };
  }
  const n60 = twin?.history.valid_samples_60;
  const readings = n60 === undefined ? null : `${n60} ${n60 === 1 ? "reading" : "readings"} in the last hour`;
  if (codes.has("sparse_recent_history") || codes.has("recent_gap") || codes.has("incomplete_recent_history")) {
    return { kind: "abstained", title: "Forecast unavailable",
      detail: `${readings ?? "Too few recent readings"}; more recent history is required.` };
  }
  if (codes.has("insufficient_history")) {
    const span = twin?.history.available_minutes;
    return { kind: "abstained", title: "Forecast unavailable",
      detail: `Not enough glucose history yet${span != null ? ` (${Math.round(span)} min available)` : ""}; the twin abstains rather than guess.` };
  }
  if (codes.has("stale_glucose")) {
    return { kind: "abstained", title: "Forecast unavailable", detail: "The latest glucose reading is too old to forecast from." };
  }
  const first = latest.forecast?.quality.reasons[0]?.message ?? latest.reasons[0]?.message;
  return { kind: "abstained", title: "Forecast unavailable", detail: first ?? "The twin abstained at the latest forecast time." };
}

/** Measured test coverage of the prediction ranges for the model that issued the forecast, if the report has it. */
export function measuredCoverage(report: EvaluationReport | undefined, modelVersion: string | null | undefined) {
  if (!report || report.status !== "completed" || !modelVersion) return null;
  const proto = report.protocol as { model_version?: string; intervals?: { level?: number } };
  if (proto.model_version !== modelVersion) return null;
  const sel = (report.forecast_results ?? []).find((r) => r.selected_for_serving);
  if (!sel) return null;
  const label = `${sel.model_label} (${sel.personalization})`; // interval rows are labelled "<model> (<personalization>)"
  const rows = (report.interval_results ?? []).filter((r) => r.split === "test" && r.model_label === label);
  if (!rows.length) return null;
  return {
    experiment: report.experiment_id,
    target: proto.intervals?.level ?? rows[0].interval_level,
    byHorizon: rows.map((r) => ({
      horizon: r.horizon_minutes, coverage: r.empirical_coverage.value, min: r.per_patient_coverage_min, max: r.per_patient_coverage_max,
    })),
  };
}
