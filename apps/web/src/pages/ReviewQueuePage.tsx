import { useQueries } from "@tanstack/react-query";
import { ArrowRight, ListChecks } from "lucide-react";
import { Link } from "react-router";
import { useClient } from "@/api/client";
import type { ReplaySession } from "@/api/types";
import { modeLabel } from "@/lib/format";
import { queueRow, sortQueue, type InputState, type QueueRow } from "@/lib/queue";
import { paths } from "@/lib/routes";
import { durationLabel, replayTime } from "@/lib/time";
import { useSessions } from "@/state/replay";
import { useShell } from "@/components/shell/ShellContext";
import { Button, EmptyState, InlineNotice, PageHeader, Skeleton, StatusLabel } from "@/components/ui";
import "@/styles/review-queue.css";

/** Per session: its warnings and latest forecast at its own replay clock (cache keys carry id, revision and clock). */
function useQueueRows(items: ReplaySession[]): QueueRow[] {
  const client = useClient();
  const key = (s: ReplaySession) => [s.id, s.revision, s.clock_at] as const;
  const alerts = useQueries({
    queries: items.map((s) => ({ queryKey: ["queue-alerts", ...key(s)], queryFn: ({ signal }: { signal: AbortSignal }) => client.alerts(s.id, signal), staleTime: Infinity, retry: 0 })),
  });
  const latest = useQueries({
    queries: items.map((s) => ({ queryKey: ["queue-forecast", ...key(s)], queryFn: ({ signal }: { signal: AbortSignal }) => client.forecast(s.id, signal), staleTime: Infinity, retry: 0 })),
  });
  return items.map((s, i) => queueRow(s, alerts[i]?.data, latest[i]?.data, !!alerts[i]?.isError));
}

export function ReviewQueuePage() {
  const sessions = useSessions();
  const shell = useShell();
  const items = sessions.data?.items ?? [];
  const rows = sortQueue(useQueueRows(items));
  const waiting = rows.filter((r) => (r.unreviewed ?? 0) > 0).length;
  return (
    <>
      <PageHeader title="Review queue"
        meta={items.length > 0 ? <>{waiting === 0 ? "No replay has unreviewed warnings" : `${waiting} of ${items.length} replays have unreviewed warnings`}</> : undefined}>
        Replays held by the local API, with unreviewed research warnings first and then the most recent warning. Research demonstration,
        not triage: the order is not a risk ranking, and every count stops at that replay’s own clock.
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
        Counts include only warnings issued up to each replay’s clock. “Reviewed” means marked as reviewed in this local research
        session; no message is sent. Inputs describe the latest forecast: degraded inputs are flagged, and an abstained forecast is not shown.
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
};

export function QueueRows({ rows }: { rows: QueueRow[] }) {
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
          return (
            <div key={s.id} className="rows__row" role="row" data-unreviewed={(r.unreviewed ?? 0) > 0 ? "true" : undefined}>
              <span role="cell" className="rows__primary">
                <Link to={paths.session(s.id)} className="rows__alias">{s.patient_alias}</Link>
                <span className="rows__secondary">{s.mode === "synthetic_demo" ? "Synthetic" : "Recorded"} · session {s.id.slice(0, 8)}
                  <span className="visually-hidden">, {modeLabel(s.mode)}</span></span>
              </span>
              <span role="cell" className="rows__time num"><span className="visually-hidden">Replay time </span>{replayTime(s.clock_at)}</span>
              <span role="cell" className="queue__counts">
                {r.alertsError ? <span className="muted">Warnings could not be loaded</span>
                  : r.unreviewed === null ? <span className="muted">Loading…</span> : (
                    <>
                      <span className={r.unreviewed > 0 ? "queue__open" : undefined}>
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
                ) : r.unreviewed === null ? null : <span className="muted">No warning yet</span>}
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
                <Link to={paths.session(s.id)} className="row-action" aria-label={`Open replay for ${s.patient_alias}`}>
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
