/**
 * Review queue rows. Each row is built from ONE review snapshot: the session, its warnings and its latest forecast read
 * by the API under one lock at one replay clock, so a playing replay cannot advance between them. A snapshot that
 * describes another session, another participant or an earlier revision than the one listed is refused, never shown.
 * Counts that are still loading or could not be loaded are unknown, never zero. The order is administrative (unreviewed
 * warnings first, then the most recently started replay), not a risk ranking: replay times of different participants
 * sit on separate recorded timelines and are never compared.
 */
import type { AlertList, LatestForecast, QueueSnapshot, ReplaySession } from "@/api/types";
import { outcomeText, triggerText } from "@/components/review/snapshot";
import { ms } from "./time";

export type InputState = "ok" | "degraded" | "abstained" | "no_forecast" | "no_model" | "unknown" | "unavailable";

/** loading: no usable snapshot yet · complete: every value known at the row's cutoff · unavailable: the request failed
 *  or its answer was refused (see ``problem``). */
export type RowStatus = "loading" | "complete" | "unavailable";

export interface QueueRow {
  /** the session as displayed: the snapshot's own session when one was accepted, otherwise the listed one */
  session: ReplaySession;
  status: RowStatus;
  /** the replay clock every value of the row refers to */
  cutoff: string;
  /** null whenever the count is unknown (loading or unavailable); a known zero is 0 */
  unreviewed: number | null;
  reviewed: number | null;
  lastWarningAt: string | null;
  lastOutcome: string | null;
  lastTrigger: string | null;
  inputs: InputState;
  /** why the row is unavailable, in one sentence */
  problem: string | null;
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

/**
 * Why a snapshot cannot describe the listed session, or null when it can. A newer revision than the list is accepted
 * (the replay was sought or reset after the list was read; the snapshot is then the current state). An earlier
 * revision, a different session or participant, or parts that disagree on revision or clock are refused.
 */
export function snapshotProblem(listed: ReplaySession, snap: QueueSnapshot): string | null {
  const s = snap.session;
  const a = snap.alerts;
  const l = snap.latest_forecast;
  if (s.id !== listed.id || a.session_id !== listed.id || l.session_id !== listed.id) {
    return "The answer described a different replay, so it was not used.";
  }
  if (s.patient_id !== listed.patient_id) return "The answer described a different participant, so it was not used.";
  if (s.revision < listed.revision) return "The answer described an earlier revision of this replay, so it was not used.";
  if (a.session_revision !== s.revision || l.session_revision !== s.revision
      || ms(a.clock_at) !== ms(s.clock_at) || ms(l.clock_at) !== ms(s.clock_at)) {
    return "The parts of the answer disagree on the replay clock, so it was not used.";
  }
  return null;
}

function unknownRow(listed: ReplaySession, status: "loading" | "unavailable", problem: string | null): QueueRow {
  return {
    session: listed, status, cutoff: listed.clock_at, unreviewed: null, reviewed: null, lastWarningAt: null,
    lastOutcome: null, lastTrigger: null, inputs: status === "loading" ? "unknown" : "unavailable", problem,
  };
}

/**
 * One row from the listed session and (when it has arrived) its snapshot. ``error`` is the failure message of the
 * snapshot request, if it failed.
 */
export function queueRow(listed: ReplaySession, snap?: QueueSnapshot, error?: string | null): QueueRow {
  if (error) return unknownRow(listed, "unavailable", error);
  if (!snap) return unknownRow(listed, "loading", null);
  const problem = snapshotProblem(listed, snap);
  if (problem) return unknownRow(listed, "unavailable", problem);
  const s = snap.session;
  const cutoff = ms(s.clock_at);
  // defensive: only this session's warnings of this revision, issued at or before the cutoff
  const items: AlertList["items"] = snap.alerts.items.filter((x) =>
    x.session_id === s.id && x.session_revision === s.revision && ms(x.issued_at) <= cutoff);
  const last = items.reduce<AlertList["items"][number] | null>((m, x) => (!m || ms(x.issued_at) > ms(m.issued_at) ? x : m), null);
  const reviewed = items.filter((x) => x.acknowledgement.acknowledged).length;
  return {
    session: s,
    status: "complete",
    cutoff: s.clock_at,
    unreviewed: items.length - reviewed,
    reviewed,
    lastWarningAt: last?.issued_at ?? null,
    // an outcome resolved after the cutoff reads "Outcome pending at the cutoff" (same cutoff as the counts)
    lastOutcome: last ? outcomeText(last, cutoff) : null,
    lastTrigger: last ? triggerText(last) : null,
    inputs: inputState(snap.latest_forecast),
    problem: null,
  };
}

/** 0 = has unreviewed warnings · 1 = count unknown (loading or unavailable) · 2 = known to have none. */
function group(r: QueueRow): number {
  if (r.status !== "complete") return 1;
  return (r.unreviewed ?? 0) > 0 ? 0 : 2;
}

/**
 * Administrative review order: replays with unreviewed warnings, then replays whose counts are not known yet, then the
 * rest; within each group the most recently started replay first (wall-clock start, the one timeline all replays share),
 * then the session id. Never ordered by replay time across participants and never by any risk score.
 */
export function sortQueue(rows: QueueRow[]): QueueRow[] {
  return [...rows].sort((x, y) =>
    group(x) - group(y)
    || ms(y.session.created_at) - ms(x.session.created_at)
    || x.session.id.localeCompare(y.session.id));
}

export interface QueueSummary {
  replays: number;
  participants: number;
  complete: number;
  loading: number;
  unavailable: number;
  waiting: number;
  /** one sentence; never claims "none" while any count is unknown */
  text: string;
}

export function summarizeQueue(rows: QueueRow[]): QueueSummary {
  const replays = rows.length;
  const participants = new Set(rows.map((r) => r.session.patient_id)).size;
  const complete = rows.filter((r) => r.status === "complete").length;
  const loading = rows.filter((r) => r.status === "loading").length;
  const unavailable = rows.filter((r) => r.status === "unavailable").length;
  const waiting = rows.filter((r) => r.status === "complete" && (r.unreviewed ?? 0) > 0).length;
  const of = `${replays} ${replays === 1 ? "replay" : "replays"} of ${participants} ${participants === 1 ? "participant" : "participants"}`;
  const unknown = [loading && `${loading} still counting`, unavailable && `${unavailable} could not be counted`].filter(Boolean).join(", ");
  let text: string;
  if (complete === replays) {
    text = waiting === 0 ? `No replay has unreviewed warnings · ${of}` : `${waiting} of ${of} ${waiting === 1 ? "has" : "have"} unreviewed warnings`;
  } else if (complete === 0) {
    text = `${loading === replays ? "Counting warnings" : "Warnings could not be counted"} for ${of}${loading && unavailable ? ` (${unknown})` : ""}`;
  } else {
    text = waiting > 0
      ? `At least ${waiting} of ${of} ${waiting === 1 ? "has" : "have"} unreviewed warnings · ${unknown}`
      : `None of the ${complete} counted so far ${complete === 1 ? "has" : "have"} unreviewed warnings · ${of} · ${unknown}`;
  }
  return { replays, participants, complete, loading, unavailable, waiting, text };
}
