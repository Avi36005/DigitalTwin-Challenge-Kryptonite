import { useQueries } from "@tanstack/react-query";
import { ArrowRight, ListChecks, RotateCw } from "lucide-react";
import { Link } from "react-router";
import { useClient } from "@/api/client";
import type { ReplaySession } from "@/api/types";
import { friendlyError } from "@/lib/apiErrors";
import { modeLabel } from "@/lib/format";
import { queueRow, sortQueue, summarizeQueue, type InputState, type QueueRow } from "@/lib/queue";
import { paths } from "@/lib/routes";
import { durationLabel, replayTime } from "@/lib/time";
import { useDeployment } from "@/state/deployment";
import { useSessions } from "@/state/replay";
import { useShell } from "@/components/shell/ShellContext";
import { Button, EmptyState, InlineNotice, PageHeader, Skeleton, StatusLabel } from "@/components/ui";
import "@/styles/review-queue.css";

type Row = QueueRow & { retry: () => void };

/** One review snapshot per listed session; the cache key carries id, revision and clock, so a seek or a playing clock
 *  asks again and never reuses another revision's answer. */
function useQueueRows(items: ReplaySession[]): Row[] {
  const client = useClient();
  const { publicDemo } = useDeployment();
  const snaps = useQueries({
    queries: items.map((s) => ({
      queryKey: ["queue-snapshot", s.id, s.revision, s.clock_at],
      queryFn: ({ signal }: { signal: AbortSignal }) => client.reviewSnapshot(s.id, signal),
      staleTime: Infinity, retry: 0,
    })),
  });
  return items.map((s, i) => {
    const q = snaps[i];
    const row = queueRow(s, q?.data, q?.isError ? friendlyError(q.error, publicDemo) : null);
    return { ...row, retry: () => { void q?.refetch(); } };
  });
}

export function ReviewQueuePage() {
  const sessions = useSessions();
  const shell = useShell();
  const items = sessions.data?.items ?? [];
  const rows = sortQueue(useQueueRows(items)) as Row[];
  const summary = summarizeQueue(rows);
  return (
    <>
      <PageHeader title="Review queue" meta={items.length > 0 ? <span aria-live="polite">{summary.text}</span> : undefined}>
        The 50 most recent replays held by the local API. Administrative review order, not a risk ranking or triage:
        replays with unreviewed research warnings first, then replays whose counts are not known yet, then the rest; within
        each group the most recently started replay first. Every count stops at that replay’s own clock, and replay times of
        different participants are separate recorded timelines, never compared.
      </PageHeader>
      {sessions.isLoading ? <Skeleton h={160} /> : sessions.isError ? (
        <InlineNotice tone="danger" role="alert">The review queue could not be loaded: {(sessions.error as Error).message}</InlineNotice>
      ) : rows.length === 0 ? (
        <EmptyState icon={ListChecks} title="Nothing to review yet"
          action={<Button variant="primary" onClick={() => shell.open("new-replay")}>Choose participant</Button>}>
          Start a replay; its research warnings appear here as the replay clock reaches them.
        </EmptyState>
      ) : (
        <QueueRows rows={rows} />
      )}
      <p className="page-note">
        Each row is read in one request at one replay clock: its counts, latest warning and inputs all describe the replay
        time shown. Several replays of one participant are separate replays, not more patients. “Reviewed” means marked as
        reviewed in this local research session; no message is sent. Inputs describe the latest forecast: degraded inputs
        are flagged, and an abstained forecast is not shown.
      </p>
    </>
  );
}

const INPUTS: Record<InputState, { text: string; tone: "neutral" | "attention" | "muted" }> = {
  ok: { text: "Inputs complete", tone: "neutral" },
  degraded: { text: "Degraded inputs", tone: "attention" },
  abstained: { text: "Abstained", tone: "attention" },
  no_forecast: { text: "No forecast yet", tone: "muted" },
  no_model: { text: "No verified model", tone: "muted" },
  unknown: { text: "Inputs loading", tone: "muted" },
  unavailable: { text: "Inputs not known", tone: "muted" },
};

export function QueueRows({ rows }: { rows: (QueueRow & { retry?: () => void })[] }) {
  return (
    <div className="rows rows--queue" role="table" aria-label="Review queue">
      <div className="rows__head" role="row">
        <span role="columnheader">Participant</span>
        <span role="columnheader">Replay time</span>
        <span role="columnheader">Warnings</span>
        <span role="columnheader">Latest warning</span>
        <span role="columnheader">Data</span>
        <span role="columnheader"><span className="visually-hidden">Action</span></span>
      </div>
      <div role="rowgroup">
        {rows.map((r) => {
          const s = r.session;
          const fr = s.freshness;
          const inp = INPUTS[r.inputs];
          const known = r.status === "complete";
          return (
            <div key={s.id} className="rows__row" role="row" data-status={r.status}
              data-unreviewed={known && (r.unreviewed ?? 0) > 0 ? "true" : undefined}>
              <span role="cell" className="rows__primary">
                <Link to={paths.session(s.id)} className="rows__alias">{s.patient_alias}</Link>
                <span className="rows__secondary">{s.mode === "synthetic_demo" ? "Synthetic" : "Recorded"} · session {s.id.slice(0, 8)}
                  <span className="visually-hidden">, {modeLabel(s.mode)}</span></span>
              </span>
              <span role="cell" className="rows__time num">
                <span className="visually-hidden">Replay time </span>{replayTime(r.cutoff)}
                {s.status === "playing" && <span className="rows__secondary">Playing · counts as of this time</span>}
              </span>
              <span role="cell" className="queue__counts">
                {r.status === "unavailable" ? (
                  <span className="queue__problem">
                    <span className="muted">Not known — {r.problem}</span>
                    {r.retry && (
                      <button type="button" className="text-btn" onClick={r.retry} aria-label={`Retry counting warnings for ${s.patient_alias}`}>
                        <RotateCw size={13} aria-hidden /> Retry
                      </button>
                    )}
                  </span>
                ) : r.status === "loading" ? <span className="muted">Counting…</span> : (
                  <>
                    <span className={(r.unreviewed ?? 0) > 0 ? "queue__open" : undefined}>
                      <span className="num">{r.unreviewed}</span> unreviewed
                    </span>
                    <span className="rows__secondary"><span className="num">{r.reviewed}</span> reviewed</span>
                  </>
                )}
              </span>
              <span role="cell" className="queue__last">
                {r.lastWarningAt ? (
                  <>
                    <span className="num">{replayTime(r.lastWarningAt)}</span>
                    {r.lastOutcome && (r.lastOutcome.startsWith("Outcome pending")
                      ? <> <StatusLabel tone="attention">{r.lastOutcome}</StatusLabel></>
                      : <span className="queue__outcome"> · {r.lastOutcome}</span>)}
                    {r.lastTrigger && <span className="rows__secondary">{r.lastTrigger}</span>}
                  </>
                ) : known ? <span className="muted">No warning yet</span> : null}
              </span>
              <span role="cell" className="queue__data">
                <span className={fr.status === "stale" ? "queue__flag" : undefined}>
                  {fr.status === "fresh" ? `Fresh · ${durationLabel(fr.latest_glucose_age_minutes)} old`
                    : fr.status === "stale" ? `Stale · ${durationLabel(fr.latest_glucose_age_minutes)} old`
                      : "No reading yet"}
                </span>
                <span className={`rows__secondary${inp.tone === "attention" ? " queue__flag" : ""}`}>{inp.text}</span>
              </span>
              <span role="cell" className="rows__action">
                <Link to={paths.session(s.id)} className="row-action" aria-label={`Open replay for ${s.patient_alias}, session ${s.id.slice(0, 8)}`}>
                  Open<ArrowRight size={15} aria-hidden />
                </Link>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
