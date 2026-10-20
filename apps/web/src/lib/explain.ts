/**
 * "How the twin reached this forecast": a plain account of one forecast, built only from values the API recorded for
 * that forecast (its population forecast, the patient correction applied at issue time, the final estimate, the
 * personalization state at issue time, its quality reasons) plus the warning list and profile at the same replay clock.
 * Nothing is recomputed or invented in the browser: the final estimate is the API's predicted value, not population plus
 * correction re-added here, and missing inputs stay missing.
 */
import type { AlertList, EvaluationReport, Forecast, SessionProfile } from "@/api/types";
import { featureSetOf, measuredCoverage, modelUsesProfile } from "./forecast";
import { ms } from "./time";

export interface HorizonLine {
  horizon: number;
  targetAt: string;
  population: number | null;
  correction: number | null;
  final: number | null;
}

export interface CorrectionState {
  status: "disabled" | "warming_up" | "active" | "reset_after_gap";
  /** matured (observed) forecast errors per horizon at issue time, and how many are needed before any correction */
  matured: { horizon: number; n: number; needed: number }[];
  cap: number | null;
  resetGap: number | null;
}

export type InputUse = "used" | "used_missing" | "not_input" | "unknown";

export interface InputsUsed {
  glucose: { value: number; observedAt: string } | null;
  wearable: InputUse;
  /** null when the model's feature set is not encoded in its version */
  profile: { use: InputUse; known: string[]; notYet: string[]; missing: string[] } | null;
}

export interface TrackRecord {
  total: number;
  onset: number;
  falseAlarm: number;
  pending: number;
  unknown: number;
}

export interface CoverageLine {
  target: number | null;
  measured: { horizon: number; coverage: number | null }[] | null;
  experiment: string | null;
}

/** This model's error at the forecast's glucose trend, from its validation segment (scripts/error_by_trend.py). */
export interface TrendAccuracy {
  slope: number;
  label: string;
  steady: boolean;
  byHorizon: { horizon: number; mae: number | null; steadyMae: number | null; origins: number }[];
  peakBias60: number | null;
  experiment: string | null;
}

export interface Explanation {
  issuedAt: string;
  modelVersion: string | null;
  horizons: HorizonLine[];
  correction: CorrectionState;
  inputs: InputsUsed;
  track: TrackRecord | null;
  coverage: CoverageLine;
  trend: TrendAccuracy | null;
}

/**
 * Error at the current trend for the exact model that issued the forecast, read from the evaluation report; null when
 * the forecast has no 15-minute trend or the report holds no trend errors for that model version. Never borrowed.
 */
export function trendAccuracy(f: Forecast, report: EvaluationReport | undefined): TrendAccuracy | null {
  const slope = f.glucose_trend_mg_dl_per_min;
  const t = report?.error_by_trend;
  if (slope == null || !t || !f.model_version || t.model_version !== f.model_version) return null;
  const inStratum = (r: (typeof t.rows)[number]) => r.trend !== "all"
    && (r.slope_min == null || slope > r.slope_min) && (r.slope_max == null || slope <= r.slope_max);
  const hit = t.rows.find(inStratum);
  if (!hit) return null;
  const horizons = [...new Set(t.rows.map((r) => r.horizon))].sort((a, b) => a - b);
  const row = (h: number, trend: string) => t.rows.find((r) => r.horizon === h && r.trend === trend);
  return {
    slope, label: hit.label, steady: hit.trend === "steady",
    byHorizon: horizons.map((h) => ({ horizon: h, mae: row(h, hit.trend)?.mae_macro ?? null,
      steadyMae: row(h, "steady")?.mae_macro ?? null, origins: row(h, hit.trend)?.origins ?? 0 })),
    peakBias60: row(60, "all")?.mean_signed_error_target_above_180 ?? null,
    experiment: report?.experiment_id ?? null,
  };
}

/** Warning outcomes as known at ``cutoff``: an outcome resolved after the cutoff counts as pending. */
export function trackRecord(alerts: AlertList | undefined, cutoff: number): TrackRecord | null {
  if (!alerts) return null;
  const items = alerts.items.filter((a) => ms(a.issued_at) <= cutoff);
  const resolvedLater = (a: AlertList["items"][number]) =>
    [a.outcome.confirmed_at, a.outcome.onset_at].some((t) => t != null && ms(t) > cutoff);
  const out = { total: items.length, onset: 0, falseAlarm: 0, pending: 0, unknown: 0 };
  for (const a of items) {
    const s = a.outcome.status;
    if ((s === "onset_observed" || s === "no_onset_observed") && resolvedLater(a)) out.pending += 1;
    else if (s === "onset_observed") out.onset += 1;
    else if (s === "no_onset_observed") out.falseAlarm += 1;
    else if (s === "unknown") out.unknown += 1;
    else out.pending += 1;
  }
  return out;
}

export function explainForecast(f: Forecast, opts: {
  /** the replay clock the explanation is read at (warnings and profile values are judged at this cutoff) */
  cutoff: number;
  alerts?: AlertList;
  profile?: SessionProfile;
  report?: EvaluationReport;
}): Explanation {
  const issued = ms(f.as_of);
  const p = f.personalization;
  const codes = new Set(f.quality.reasons.map((r) => r.code));
  const fs = featureSetOf(f.model_version);
  const usesProfile = modelUsesProfile(f.model_version);

  const wearable: InputUse = fs === null ? "unknown" : fs.startsWith("dyn") ? (codes.has("activity_unavailable") ? "used_missing" : "used") : "not_input";

  let profile: InputsUsed["profile"] = null;
  if (usesProfile !== null) {
    const prof = opts.profile && opts.profile.patient_id === f.patient_id && opts.profile.session_revision === f.session_revision
      ? opts.profile : undefined;
    const known: string[] = [];
    const notYet: string[] = [];
    const missing: string[] = [];
    for (const v of prof?.values ?? []) {
      // judged at the forecast's own issue time: a value that became available later was not known to this forecast
      if (v.status === "available" && v.available_at && ms(v.available_at) <= issued) known.push(v.label);
      else if (v.status === "available" || v.status === "not_yet_available") notYet.push(v.label);
      else missing.push(v.label);
    }
    const use: InputUse = !usesProfile ? "not_input" : codes.has("profile_unavailable") ? "used_missing" : prof ? "used" : "unknown";
    profile = { use, known, notYet, missing };
  }

  const cov = measuredCoverage(opts.report, f.model_version);
  const level = f.estimates.find((e) => e.interval_level != null)?.interval_level ?? null;

  return {
    issuedAt: f.as_of,
    modelVersion: f.model_version,
    horizons: f.estimates.map((e) => ({
      horizon: e.horizon_minutes, targetAt: e.target_at,
      population: e.components?.population_mg_dl ?? null,
      correction: e.components?.patient_correction_mg_dl ?? null,
      final: e.predicted_mg_dl,
    })),
    correction: {
      status: p.enabled ? p.status : "disabled",
      matured: p.horizons.map((h) => ({ horizon: h.horizon_minutes, n: h.matured_residuals, needed: h.min_required })),
      cap: p.cap_mg_dl ?? null,
      resetGap: p.reset_gap_minutes ?? null,
    },
    inputs: {
      glucose: f.observed_glucose ? { value: f.observed_glucose.value_mg_dl, observedAt: f.observed_glucose.observed_at } : null,
      wearable,
      profile,
    },
    track: trackRecord(opts.alerts && opts.alerts.session_id === f.session_id && opts.alerts.session_revision === f.session_revision
      ? opts.alerts : undefined, opts.cutoff),
    // measured coverage only for the exact model that issued this forecast; never borrowed from another model
    coverage: { target: level, measured: cov ? cov.byHorizon.map((b) => ({ horizon: b.horizon, coverage: b.coverage })) : null,
      experiment: cov?.experiment ?? null },
    trend: trendAccuracy(f, opts.report),
  };
}
