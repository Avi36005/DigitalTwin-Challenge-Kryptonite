import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Info, Target } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { useClient } from "@/api/client";
import { ApiError } from "@/api/transport";
import type { Alert, EvaluationSegment, Forecast, ObservationEvent, ReplaySession } from "@/api/types";
import { EXPIRED_REPLAY, friendlyError } from "@/lib/apiErrors";
import { forecastUsable, latestGlucose } from "@/lib/chart";
import { modeLabel } from "@/lib/format";
import { paths } from "@/lib/routes";
import { ms, replayTime } from "@/lib/time";
import { useDeployment } from "@/state/deployment";
import { useEvaluation, useServing } from "@/state/evaluation";
import { useOpenTwin } from "@/state/open";
import { usePreferences } from "@/state/preferences";
import {
  useAlerts,
  useControl,
  useForecastHistory,
  useLatestForecast,
  usePatient,
  usePatients,
  useReleasedEvents,
  useSession,
  useSessionProfile,
  useTwin,
} from "@/state/replay";
import { useToast } from "@/state/toasts";
import { useShell } from "@/components/shell/ShellContext";
import { statusWord } from "@/components/shell/Sidebar";
import { ReplayToolbar } from "@/components/replay/ReplayToolbar";
import { ReviewSummary } from "@/components/review/ReviewSummary";
import { ForecastDetail } from "@/components/twin/ForecastDetail";
import { GlucoseChart } from "@/components/twin/GlucoseChart";
import { TwinExplanation } from "@/components/twin/TwinExplanation";
import {
  BaselineLine,
  GlucoseSummary,
  Guardrails,
  ModelDetails,
  RecentObservations,
  ReviewStatus,
  ReviewStrip,
  WarningHistory,
} from "@/components/twin/Panels";
import { Button, EmptyState, InlineNotice, MetadataLine, PageHeader, Skeleton } from "@/components/ui";

export function ReplayPage({ sid }: { sid: string }) {
  const client = useClient();
  const qc = useQueryClient();
  const toast = useToast();
  const { reduceMotion } = usePreferences();
  const sessionQ = useSession(sid);
  const session = sessionQ.data;
  const patient = usePatient(session?.patient_id);
  const latest = useLatestForecast(session);
  const history = useForecastHistory(session, 144);
  const alerts = useAlerts(session);
  const twin = useTwin(session);
  const profile = useSessionProfile(session);
  const evaluation = useEvaluation();
  const serving = useServing();
  const { publicDemo } = useDeployment();
  const { events, loaded: eventsLoaded } = useReleasedEvents(session);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [announce, setAnnounce] = useState("");
  const clock = session ? ms(session.clock_at) : 0;

  // a selected forecast must exist in the CURRENT revision and not lie after the clock (cleared after a rewind)
  const historyItems = history.data?.items ?? [];
  const selected = useMemo(
    () => historyItems.find((f) => f.forecast_id === selectedId && ms(f.as_of) <= clock) ?? null,
    [historyItems, selectedId, clock],
  );
  useEffect(() => setSelectedId(null), [session?.id, session?.revision]);

  const latestF: Forecast | null = forecastUsable(latest.data?.forecast, clock) ? latest.data!.forecast! : null;

  // announce significant changes only (a new warning, the end of the recording) — not every reading
  const prevAlerts = useRef<number>(0);
  useEffect(() => {
    const n = alerts.data?.items.length ?? 0;
    if (n > prevAlerts.current && prevAlerts.current !== 0) setAnnounce("New research warning issued.");
    prevAlerts.current = n;
  }, [alerts.data?.items.length]);
  useEffect(() => {
    if (session?.status === "completed") setAnnounce("Replay reached the end of the recording.");
  }, [session?.status]);

  // the review dialog shows errors inline (the typed note is kept), so only success is toasted
  const ack = useMutation({
    mutationFn: ({ a, note }: { a: Alert; note?: string }) => client.acknowledge(sid, a.alert_id, note),
    onSuccess: () => {
      toast("Marked as reviewed in this local session — no message was sent");
      qc.invalidateQueries({ queryKey: ["alerts", sid] });
    },
  });

  if (sessionQ.isError) {
    const notFound = sessionQ.error instanceof ApiError && sessionQ.error.status === 404;
    if (publicDemo) return <PublicReplayError error={sessionQ.error} retry={() => sessionQ.refetch()} />;
    return (
      <>
        <PageHeader title="Replay" />
        <EmptyState title={notFound ? "Replay session not found" : "Could not load the replay session"}
          action={<Link className="btn btn--secondary" to={paths.sessions()}>Open replay sessions</Link>}>
          {notFound ? "Sessions live in the API process’s memory and end when it restarts. No other session was opened in its place." : (sessionQ.error as Error).message}
        </EmptyState>
      </>
    );
  }
  if (!session) {
    return (
      <div className="replay-loading" aria-busy="true">
        <Skeleton h={34} w={260} /><Skeleton h={18} w={420} /><Skeleton h={90} /><Skeleton h={380} />
      </div>
    );
  }

  const synthetic = session.mode === "synthetic_demo";
  return (
    <>
      <PageHeader title={session.patient_alias}
        meta={
          <MetadataLine>
            {patient.data?.cohort.label ?? (synthetic ? "Fictional participant" : "—")}
            {modeLabel(session.mode)}
            {patient.data ? `${patient.data.dataset.name} ${patient.data.dataset.version}` : null}
            <>{statusWord(session.status)} at <span className="num">{replayTime(session.clock_at)}</span> (replay time)</>
          </MetadataLine>
        }
        actions={<div className="replay-actions">
          <ReviewSummary session={session} patient={patient.data} latest={latest} alerts={alerts} twin={twin} profile={profile}
            events={events} eventsLoaded={eventsLoaded} report={evaluation.data} segments={patient.data?.evaluation_segments} />
          <ParticipantSwitcher currentId={session.patient_id} />
        </div>} />

      {patient.data?.mode === "dataset_replay" && !patient.data.eligible_for_primary_analysis && (
        <InlineNotice tone="neutral" icon={Info} role="note">
          Exploratory participant — outside the primary Type 2 analysis. The model was not evaluated on this cohort.
        </InlineNotice>
      )}

      <BaselineLine patient={patient.data} profile={profile.data} session={session} modelVersion={latestF?.model_version ?? twin.data?.model_version} />

      <GlucoseSummary session={session} events={events} latest={latest.data} twin={twin.data} loading={latest.isLoading}
        eventsLoaded={eventsLoaded} report={evaluation.data} />
      <ReviewStrip latest={latest.data} alerts={alerts.data} />

      <StartNotice session={session} events={events} eventsLoaded={eventsLoaded} segments={patient.data?.evaluation_segments}
        onAnnounce={setAnnounce} />

      {latestF?.split_segment === "training" && (
        <InlineNotice tone="neutral" icon={Info} role="note">
          This replay time lies in the model’s training period, so these forecasts are in-sample. Use <strong>Test period</strong> below
          the chart to review forecasts from the final test period.
        </InlineNotice>
      )}

      <div className="workspace">
        <div className="workspace__main">
          <GlucoseChart session={session} events={events} latest={latestF} history={historyItems}
            selected={selected} onSelect={(f) => setSelectedId(f?.forecast_id ?? null)} reduceMotion={reduceMotion}
            eventsLoaded={eventsLoaded} />
          <ReplayToolbar session={session} segments={patient.data?.evaluation_segments} onAnnounce={setAnnounce} />
        </div>
        <aside className="workspace__inspector" aria-label="Review and guardrails">
          <ReviewStatus latest={latest.data} alerts={alerts.data} />
          <Guardrails session={session} latest={latest.data} twin={twin.data} alerts={alerts.data} report={evaluation.data}
            segments={patient.data?.evaluation_segments}
            more={<Link className="text-link guards__more" to={paths.evidence("safety-guardrails")}>All safety guardrails<ArrowRight size={14} aria-hidden /></Link>} />
          {(selected ?? latestF) && (
            <button type="button" className="text-btn inspector__link" onClick={() => setDetailOpen(true)}>
              View forecast details<ArrowRight size={14} aria-hidden />
            </button>
          )}
        </aside>
      </div>

      <TwinExplanation latest={latest.data} alerts={alerts.data} profile={profile.data} report={evaluation.data}
        clockAt={session.clock_at}
        profileInputs={serving.data?.items.find((m) => m.model_version === latest.data?.forecast?.model_version)?.profile_inputs} />

      <div className="lower">
        <RecentObservations events={events} clock={clock} loaded={eventsLoaded} />
        <WarningHistory alerts={alerts.data} revision={session.revision} sessionKey={`${session.id}:${session.revision}`}
          participant={session.patient_alias} onSave={(a, note) => ack.mutateAsync({ a, note })} />
        <ModelDetails twin={twin.data} latest={latest.data} publicDemo={publicDemo} />
      </div>

      <ForecastDetail f={selected ?? latestF} patient={patient.data} report={evaluation.data} open={detailOpen} onClose={() => setDetailOpen(false)}
        publicDemo={publicDemo} />
      <div className="visually-hidden" aria-live="polite">{announce}</div>
    </>
  );
}

/** At the start of a recording nothing has been released yet, so the chart is empty: say so, and offer the final test
 *  period (later recordings from a participant represented in training) as the first stop. */
function StartNotice({ session, events, eventsLoaded, segments, onAnnounce }: {
  session: ReplaySession; events: ObservationEvent[]; eventsLoaded: boolean; segments?: EvaluationSegment[] | null;
  onAnnounce: (msg: string) => void;
}) {
  const control = useControl(session.id);
  const toast = useToast();
  const { publicDemo } = useDeployment();
  const clock = ms(session.clock_at);
  if (!eventsLoaded || latestGlucose(events, clock) || session.status === "playing") return null;
  const test = segments?.find((s) => s.name === "test");
  const go = () => test && control.mutate({ action: "seek", seek_to: test.start_at }, {
    onSuccess: (s) => onAnnounce(`Moved to the final test period. Replay time ${replayTime(s.clock_at)}.`),
    onError: (e) => toast(`Replay control failed: ${friendlyError(e, publicDemo)}`, "error"),
  });
  return (
    <InlineNotice tone="neutral" icon={Info} role="note"
      action={test ? <Button variant="primary" size="sm" icon={Target} busy={control.isPending} onClick={go}>Go to final test period</Button> : undefined}>
      <strong>No readings released yet.</strong> The replay clock is at the start of the recording.{" "}
      {test ? <>Jump to the final test period (from {replayTime(test.start_at)}) to see forecasts on later recordings from a participant represented in training, or press Play.</>
        : <>Press Play to release readings as they would have arrived.</>}
    </InlineNotice>
  );
}

/** Public demonstration: a replay that expired or belongs to another browser is said so plainly, with a way forward. */
function PublicReplayError({ error, retry }: { error: unknown; retry: () => void }) {
  const shell = useShell();
  const gone = error instanceof ApiError && error.status === 404;
  const limited = error instanceof ApiError && error.status === 429;
  return (
    <>
      <PageHeader title="Replay" />
      <EmptyState title={gone ? EXPIRED_REPLAY : limited ? "Too many requests" : "Could not load the replay session"}
        action={limited ? <Button onClick={retry}>Try again</Button>
          : <Button variant="primary" onClick={() => shell.open("new-replay")}>Start a new replay</Button>}>
        {gone ? "Replays in this public demonstration are private to the browser that started them and are removed after a period of inactivity or when the demonstration restarts."
          : limited ? "Too many requests; wait a moment and try again." : friendlyError(error, true)}
      </EmptyState>
    </>
  );
}

function ParticipantSwitcher({ currentId }: { currentId: string }) {
  const patients = usePatients();
  const { publicDemo } = useDeployment();
  const open = useOpenTwin();
  const items = patients.data?.items ?? [];
  return (
    <div className="switcher">
      <label htmlFor="switch-participant" className="switcher__label">Change participant</label>
      <select id="switch-participant" className="select" value={currentId} disabled={open.isPending}
        onChange={(e) => {
          const p = items.find((x) => x.patient_id === e.target.value);
          if (p) open.open(p.patient_id, p.mode); // resumes that participant's own session or starts one; never resets this one
        }}>
        {(publicDemo ? ["synthetic_demo"] : ["dataset_replay", "synthetic_demo"]).map((m) => (
          <optgroup key={m} label={modeLabel(m)}>
            {items.filter((p) => p.mode === m).map((p) => (
              <option key={p.patient_id} value={p.patient_id}>
                {p.display_alias} · {p.cohort.label}{p.mode === "dataset_replay" && !p.eligible_for_primary_analysis ? " (exploratory)" : ""}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
