/**
 * Review queue rows, built only from what each session's API already returns at its own replay clock (alerts issued up
 * to the clock, the latest forecast, data freshness). Nothing after the clock is read, and nothing is ranked by risk:
 * the order is "has unreviewed warnings", then the most recent warning.
 */
import type { AlertList, LatestForecast, ReplaySession } from "@/api/types";
import { outcomeText, triggerText } from "@/components/review/snapshot";
import { ms } from "./time";

export type InputState = "ok" | "degraded" | "abstained" | "no_forecast" | "no_model" | "unknown";

export interface QueueRow {
  session: ReplaySession;
  /** null while the session's warnings are loading or could not be loaded */
  unreviewed: number | null;
  reviewed: number | null;
  lastWarningAt: string | null;
  lastOutcome: string | null;
  lastTrigger: string | null;
  inputs: InputState;
  alertsError: boolean;
}

export function inputState(latest: LatestForecast | undefined): InputState {
  if (!latest) return "unknown";
  const f = latest.forecast;
  const codes = new Set([...(latest.reasons ?? []), ...(f?.quality.reasons ?? [])].map((r) => r.code));
  if (codes.has("model_unavailable")) return "no_model";
  if (codes.has("no_glucose_history") || codes.has("no_forecast_yet")) return "no_forecast";
  if (!f || f.quality.status === "insufficient" || latest.availability === "not_ready") return "abstained";
  return f.quality.status === "degraded" ? "degraded" : "ok";
}

/** One row. Responses from another revision of the session are ignored (a seek or reset rebuilds the twin). */
export function queueRow(session: ReplaySession, alerts?: AlertList, latest?: LatestForecast, alertsError = false): QueueRow {
  const a = alerts && alerts.session_revision === session.revision ? alerts : undefined;
  const l = latest && latest.session_revision === session.revision ? latest : undefined;
  const items = a?.items ?? [];
  const last = items.reduce<AlertList["items"][number] | null>((m, x) => (!m || ms(x.issued_at) > ms(m.issued_at) ? x : m), null);
  const reviewed = items.filter((x) => x.acknowledgement.acknowledged).length;
  return {
    session,
    unreviewed: a ? items.length - reviewed : null,
    reviewed: a ? reviewed : null,
    lastWarningAt: last?.issued_at ?? null,
    lastOutcome: last ? outcomeText(last, ms(session.clock_at)) : null,
    lastTrigger: last ? triggerText(last) : null,
    inputs: inputState(l),
    alertsError,
  };
}

/** Unreviewed warnings first, then the most recent warning, then sessions without warnings by participant name. */
export function sortQueue(rows: QueueRow[]): QueueRow[] {
  const t = (r: QueueRow) => (r.lastWarningAt ? ms(r.lastWarningAt) : -Infinity);
  return [...rows].sort((x, y) =>
    Number((y.unreviewed ?? 0) > 0) - Number((x.unreviewed ?? 0) > 0)
    || t(y) - t(x)
    || x.session.patient_alias.localeCompare(y.session.patient_alias)
    || x.session.id.localeCompare(y.session.id));
}
