/**
 * Review summary snapshot: a frozen, text-only copy of what the workspace shows at one replay time. Pure functions; every
 * value comes from API responses of ONE session revision, and nothing observed, released, issued or resolved after the
 * replay cutoff is included. Unavailable values stay unavailable (null + a reason), never zero.
 */
import { isValidElement, type ReactNode } from "react";
import type {
  AlertList,
  EvaluationReport,
  LatestForecast,
  ObservationEvent,
  PatientSummary,
  ReplaySession,
  SessionProfile,
  TwinState,
} from "@/api/types";
import { forecastUsable, latestGlucose } from "@/lib/chart";
import { measuredCoverage, unavailableReason } from "@/lib/forecast";
import { fmtProfileValue, modeLabel } from "@/lib/format";
import { minutesBetween, ms, replayTime } from "@/lib/time";

export const SNAPSHOT_SCHEMA = "glucotwin-review-snapshot/1";
export const TITLE = "GlucoTwin — Team Kryptonite (VESIT)";
export const DISCLAIMER = "Research replay review — not a medical report";
/** Most recent warnings listed in full; the total is always stated. */
export const MAX_WARNINGS = 20;
const EPISODE_MG_DL = 180;

const SEGMENT: Record<string, string> = {
  training: "Training period — in-sample for the population model",
  validation: "Validation-selection period",
  calibration: "Calibration period",
  test: "Final test period (later recordings from a participant represented in training)",
  unassigned: "Outside the evaluation segments",
};

export interface GuardText { label: string; status: "passed" | "flagged" | "info"; value: string; note: string | null }

export interface SnapshotEstimate {
  horizon_minutes: number; target: string; target_at: string;
  forecast_mg_dl: number | null; range_mg_dl: [number, number] | null; range_status: string;
  population_mg_dl: number | null; patient_correction_mg_dl: number | null;
}

export interface SnapshotWarning {
  issued: string; issued_at: string; horizon_minutes: number; trigger: string | null; outcome: string;
  reviewed: boolean; reviewed_at_wall_clock: string | null; note: string | null;
}

export interface ReviewSnapshot {
  schema: string;
  title: string;
  disclaimer: string;
  generated_at_wall_clock: string;
  replay_cutoff: string;
  replay_cutoff_label: string;
  session: { id: string; revision: number; status: string; mode: string; mode_label: string };
  participant: {
    alias: string; patient_id: string; cohort: string | null; dataset: string | null; license: string | null;
    synthetic: boolean; exploratory: string | null;
  };
  profile: { as_of: string; note: string; items: { label: string; value: string; status: string; source: string | null }[] } | null;
  glucose: { value_mg_dl: number; observed: string; observed_at: string; age_minutes: number; stale: boolean; stale_limit_minutes: number } | null;
  forecast: {
    availability: string; issued: string | null; issued_at: string | null; model_version: string | null; model_family: string | null;
    evaluation_context: string; quality: string | null; reasons: string[]; unavailable: string | null;
    estimates: SnapshotEstimate[];
  };
  personalization: { status: string; horizons: { horizon_minutes: number; correction_mg_dl: number | null; matured: number; required: number }[] } | null;
  coverage: { target: number | null; measured: { horizon_minutes: number; coverage: number | null }[]; experiment: string } | null;
  warnings: {
    rule_available: boolean; total: number; listed: number; truncated: boolean;
    counts: { onset: number; false_alarm: number; pending: number; unknown: number };
    items: SnapshotWarning[];
  };
  guardrails: GuardText[];
}

export interface SnapshotInput {
  session: ReplaySession;
  patient?: PatientSummary;
  profile?: SessionProfile;
  latest?: LatestForecast;
  twin?: TwinState;
  alerts?: AlertList;
  events: ObservationEvent[];
  report?: EvaluationReport;
  /** guardrail rows from the workspace's own guardChecks(), already converted to text */
  guardrails: GuardText[];
  generatedAt: string;
}

type Q<T> = { data?: T; isPlaceholderData?: boolean; isError?: boolean };

/** Whether a frozen copy can be made now; otherwise the reason, in words. Every response must belong to this session
 *  revision and this replay time (no placeholder from an earlier clock) and the released events must be complete. */
export function snapshotReadiness(session: ReplaySession | undefined, q: {
  latest: Q<LatestForecast>; alerts: Q<AlertList>; twin: Q<TwinState>; profile: Q<SessionProfile>;
}, eventsLoaded: boolean, patient?: PatientSummary): { ok: true } | { ok: false; reason: string } {
  if (!session) return { ok: false, reason: "The replay session is still loading." };
  const parts = [["forecast", q.latest], ["warnings", q.alerts], ["twin state", q.twin], ["baseline profile", q.profile]] as const;
  const failed = parts.filter(([, x]) => x.isError).map(([n]) => n);
  if (failed.length) return { ok: false, reason: `Could not load the ${failed.join(", ")} for this replay time.` };
  const waiting: string[] = parts.filter(([, x]) => !x.data || x.isPlaceholderData).map(([n]) => n);
  if (!eventsLoaded) waiting.unshift("released observations");
  if (waiting.length) {
    return { ok: false, reason: `Loading the ${waiting.join(", ")} for ${replayTime(session.clock_at)}. Try again in a moment, or pause the replay.` };
  }
  const items = [q.latest.data!, q.alerts.data!, q.twin.data!, q.profile.data!];
  if (items.some((d) => d.session_id !== session.id || d.session_revision !== session.revision)) {
    return { ok: false, reason: "The replay was rewound or reset while loading. Try again in a moment." };
  }
  if (q.latest.data!.clock_at !== session.clock_at || q.alerts.data!.clock_at !== session.clock_at) {
    return { ok: false, reason: `Waiting for data at ${replayTime(session.clock_at)}. Try again in a moment, or pause the replay.` };
  }
  if ((patient && patient.patient_id !== session.patient_id) || q.profile.data!.patient_id !== session.patient_id) {
    return { ok: false, reason: "Participant details are still loading." };
  }
  return { ok: true };
}

/** Plain text of a React node (guardrail values are small JSX fragments); never HTML. */
export function nodeText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return nodeText(node.props.children);
  return "";
}

const after = (iso: string | null | undefined, cutoff: number) => !!iso && ms(iso) > cutoff;

function outcomeText(a: AlertList["items"][number], cutoff: number): string {
  const o = a.outcome;
  // an outcome resolved after the cutoff was not known at the cutoff
  if ((o.status === "onset_observed" || o.status === "no_onset_observed") && (after(o.confirmed_at, cutoff) || after(o.onset_at, cutoff))) {
    return "Outcome pending at the cutoff";
  }
  if (o.status === "onset_observed") {
    const lead = o.qualified_lead_minutes != null ? ` · forecast lead ${Math.round(o.qualified_lead_minutes)} min` : "";
    return `Onset ${o.onset_at ? replayTime(o.onset_at, { day: false }) : ""}${lead}`.trim();
  }
  if (o.status === "no_onset_observed") return "No onset (false alarm)";
  if (o.status === "unknown") return "Outcome unknown (gap)";
  return "Outcome pending";
}

function triggerText(a: AlertList["items"][number]): string | null {
  const preds = Object.entries(a.evidence.predicted_mg_dl)
    .map(([h, v]) => ({ h: Number(h), v }))
    .filter((p): p is { h: number; v: number } => p.v != null && p.h <= a.horizon_minutes);
  if (!preds.length) return null;
  const top = preds.reduce((m, p) => (p.v > m.v ? p : m));
  const trigger = a.evidence.threshold != null ? EPISODE_MG_DL + a.evidence.threshold : null;
  return `Fired by the ${top.h}-min forecast ${Math.round(top.v)} mg/dL${trigger != null ? ` ≥ ${Math.round(trigger)} mg/dL trigger` : ""}`;
}

export function buildSnapshot(x: SnapshotInput): ReviewSnapshot {
  const s = x.session;
  const cutoff = ms(s.clock_at);
  const p = x.patient && x.patient.patient_id === s.patient_id ? x.patient : undefined;

  const prof = x.profile && x.profile.patient_id === s.patient_id && x.profile.session_revision === s.revision ? x.profile : undefined;
  const profile = prof ? {
    as_of: replayTime(prof.as_of),
    note: "Baseline (EHR-like) values as known at the cutoff — not live measurements and not a hospital record.",
    items: prof.values.map((v) => {
      const notYet = v.status === "not_yet_available" || (v.status === "available" && after(v.available_at, cutoff));
      const value = v.status === "available" && !notYet
        ? (v.name === "sex_male" ? (v.value === 1 ? "Male" : v.value === 0 ? "Female" : "Not available") : fmtProfileValue(v.value, v.unit))
        : notYet ? "Not yet available" : v.status === "excluded_suspect" ? "Excluded (suspect value)" : "Not available";
      return { label: v.label, value, status: notYet ? "not_yet_available" : v.status, source: v.source ?? null };
    }),
  } : null;

  const g = latestGlucose(x.events.filter((e) => e.patient_id === s.patient_id), cutoff);
  const age = g ? minutesBetween(g.observed_at, cutoff) : null;
  const glucose = g && typeof g.values.value === "number" && age !== null ? {
    value_mg_dl: g.values.value, observed: replayTime(g.observed_at), observed_at: g.observed_at, age_minutes: Math.round(age),
    stale: age > s.freshness.stale_threshold_minutes, stale_limit_minutes: s.freshness.stale_threshold_minutes,
  } : null;

  const lat = x.latest && x.latest.session_revision === s.revision ? x.latest : undefined;
  const f = forecastUsable(lat?.forecast, cutoff) && lat?.forecast?.patient_id === s.patient_id ? lat.forecast : null;
  const usable = !!f && (lat?.availability === "available" || lat?.availability === "stale");
  const why = unavailableReason(lat, x.twin, false);
  const forecast: ReviewSnapshot["forecast"] = {
    availability: !lat ? "unknown" : lat.availability === "available" ? "Available" : lat.availability === "stale" ? "Stale (no newer reading)" : "Not available",
    issued: f ? replayTime(f.as_of) : null, issued_at: f?.as_of ?? null,
    model_version: f?.model_version ?? x.twin?.model_version ?? null, model_family: f?.model_family ?? x.twin?.model_family ?? null,
    evaluation_context: s.mode === "synthetic_demo"
      ? "Synthetic demonstration model; no measured evaluation on recorded data."
      : f?.split_segment ? SEGMENT[f.split_segment] ?? f.split_segment : "Not part of a measured evaluation",
    quality: f ? (f.quality.status === "ok" ? "Complete" : f.quality.status === "degraded" ? "Degraded" : "Insufficient — abstained") : null,
    reasons: [...(lat?.reasons ?? []), ...(f?.quality.reasons ?? [])].map((r) => r.message).filter((m, i, a) => a.indexOf(m) === i),
    unavailable: why && why.kind !== "loading" ? `${why.title} — ${why.detail}` : null,
    estimates: usable && f ? [30, 60].map((h) => {
      const e = f.estimates.find((z) => z.horizon_minutes === h);
      const ranged = !!e && e.interval_status === "calibrated" && e.lower_mg_dl != null && e.upper_mg_dl != null;
      return {
        horizon_minutes: h, target: e ? replayTime(e.target_at) : "—", target_at: e?.target_at ?? "",
        forecast_mg_dl: e?.predicted_mg_dl ?? null,
        range_mg_dl: ranged ? [e!.lower_mg_dl as number, e!.upper_mg_dl as number] : null,
        range_status: ranged ? `Calibrated, target coverage ${Math.round((e!.interval_level ?? 0) * 100)}%` : "Unavailable",
        population_mg_dl: e?.components?.population_mg_dl ?? null,
        patient_correction_mg_dl: e?.components?.patient_correction_mg_dl ?? null,
      };
    }) : [],
  };

  const pers = x.twin && x.twin.session_revision === s.revision ? x.twin.personalization : f?.personalization;
  const personalization = pers && pers.enabled ? {
    status: pers.status.replace(/_/g, " "),
    horizons: pers.horizons.map((h) => ({ horizon_minutes: h.horizon_minutes, correction_mg_dl: h.correction_mg_dl ?? null,
      matured: h.matured_residuals, required: h.min_required })),
  } : null;

  const cov = f ? measuredCoverage(x.report, f.model_version) : null;
  const coverage = cov ? {
    target: cov.target ?? null, experiment: cov.experiment ?? "",
    measured: cov.byHorizon.map((b) => ({ horizon_minutes: b.horizon, coverage: b.coverage ?? null })),
  } : null;

  const al = x.alerts && x.alerts.session_revision === s.revision && x.alerts.session_id === s.id ? x.alerts : undefined;
  const visible = (al?.items ?? []).filter((a) => a.patient_id === s.patient_id && ms(a.issued_at) <= cutoff)
    .sort((a, b) => ms(b.issued_at) - ms(a.issued_at));
  const outcomes = visible.map((a) => outcomeText(a, cutoff));
  const items = visible.slice(0, MAX_WARNINGS).map((a, i) => ({
    issued: replayTime(a.issued_at), issued_at: a.issued_at, horizon_minutes: a.horizon_minutes, trigger: triggerText(a),
    outcome: outcomes[i], reviewed: !!a.acknowledgement.acknowledged,
    reviewed_at_wall_clock: a.acknowledgement.acknowledged ? a.acknowledgement.acknowledged_at ?? null : null,
    note: a.acknowledgement.acknowledged && a.acknowledgement.note ? a.acknowledgement.note : null,
  }));
  const count = (pred: (o: string) => boolean) => outcomes.filter(pred).length;

  return {
    schema: SNAPSHOT_SCHEMA, title: TITLE, disclaimer: DISCLAIMER,
    generated_at_wall_clock: x.generatedAt, replay_cutoff: s.clock_at, replay_cutoff_label: `${replayTime(s.clock_at)} (replay time)`,
    session: { id: s.id, revision: s.revision, status: s.status, mode: s.mode, mode_label: modeLabel(s.mode) },
    participant: {
      alias: s.patient_alias, patient_id: s.patient_id, cohort: p?.cohort.label ?? null,
      dataset: p ? `${p.dataset.name} ${p.dataset.version}` : null, license: p?.dataset.license ?? null,
      synthetic: s.mode === "synthetic_demo",
      exploratory: p && p.mode === "dataset_replay" && !p.eligible_for_primary_analysis
        ? `Exploratory — outside the primary Type 2 analysis${p.exclusion_reason ? ` (${p.exclusion_reason})` : ""}` : null,
    },
    profile, glucose, forecast, personalization, coverage,
    warnings: {
      rule_available: al?.rule_available ?? false, total: visible.length, listed: items.length, truncated: visible.length > items.length,
      counts: {
        onset: count((o) => o.startsWith("Onset")), false_alarm: count((o) => o.startsWith("No onset")),
        pending: count((o) => o.startsWith("Outcome pending")), unknown: count((o) => o.startsWith("Outcome unknown")),
      },
      items,
    },
    guardrails: x.guardrails,
  };
}

export function snapshotFileName(s: ReviewSnapshot): string {
  const safe = (v: string) => v.replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
  return `glucotwin-review-${safe(s.participant.alias)}-r${s.session.revision}-${safe(s.replay_cutoff)}.json`;
}

/** Download the frozen snapshot as JSON (the exact object the preview renders). */
export function downloadSnapshot(s: ReviewSnapshot): void {
  const blob = new Blob([JSON.stringify(s, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = snapshotFileName(s);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
