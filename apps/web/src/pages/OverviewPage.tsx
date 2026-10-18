import { ArrowRight, History, Play } from "lucide-react";
import { Link } from "react-router";
import type { PatientSummary, ReplaySession } from "@/api/types";
import { modeLabel } from "@/lib/format";
import { paths } from "@/lib/routes";
import { replayTime, wallTime } from "@/lib/time";
import { useCreateReplay } from "@/state/open";
import { usePatient, usePatients, useSessions } from "@/state/replay";
import { useShell } from "@/components/shell/ShellContext";
import { statusWord } from "@/components/shell/Sidebar";
import { Button, EmptyState, InlineNotice, PageHeader, Section, Skeleton } from "@/components/ui";

export function OverviewPage() {
  const shell = useShell();
  const sessions = useSessions();
  const patients = usePatients();
  const recent = sessions.data?.items ?? [];
  const all = patients.data?.items ?? [];
  const recorded = all.filter((p) => p.mode === "dataset_replay");
  const primary = recorded.filter((p) => p.eligible_for_primary_analysis).length;
  const synthetic = all.filter((p) => p.mode === "synthetic_demo").length;
  const demo = recorded.find((p) => p.eligible_for_primary_analysis);

  return (
    <>
      <PageHeader title="Overview">Open the recorded demo, resume a replay or choose a participant.</PageHeader>

      {demo && <RecordedDemo demo={demo} />}

      <Section title="Recent replays" divider={!!demo}
        actions={recent.length > 0 ? <Link to={paths.sessions()} className="text-link">View all<ArrowRight size={15} aria-hidden /></Link> : undefined}>
        {sessions.isLoading ? <Skeleton h={180} /> : sessions.isError ? (
          <InlineNotice tone="danger" role="alert">Replay sessions could not be loaded: {(sessions.error as Error).message}</InlineNotice>
        ) : recent.length === 0 ? (
          <EmptyState icon={History} title="No replays yet"
            action={<Button variant="primary" onClick={() => shell.open("new-replay")}>Choose participant</Button>}>
            Start a replay to see the twin update as measurements arrive. Sessions live in the local API process.
          </EmptyState>
        ) : (
          <SessionRows items={recent.slice(0, 6)} />
        )}
      </Section>

      <Section title="Start a new replay">
        {patients.isLoading ? <Skeleton h={40} /> : (
          <div className="start-row">
            <p className="start-row__text">
              {recorded.length > 0 ? (
                <>{recorded.length} recorded CGMacros participants — {primary} in the primary Type 2 analysis — and {synthetic} synthetic demonstration participants.</>
              ) : (
                <>{synthetic} synthetic demonstration participants. Recorded CGMacros data is not imported on this machine.</>
              )}
            </p>
            <div className="start-row__actions">
              <Button onClick={() => shell.open("new-replay")}>Choose participant</Button>
              <Link to={paths.participants()} className="text-link">Browse participants<ArrowRight size={15} aria-hidden /></Link>
            </div>
          </div>
        )}
      </Section>
    </>
  );
}

/** One click to the walkthrough: the first primary-analysis participant, starting at the final test period, so the
 *  first screen shows forecasts instead of an empty chart. */
function RecordedDemo({ demo }: { demo: PatientSummary }) {
  const detail = usePatient(demo.patient_id);
  const test = detail.data?.evaluation_segments?.find((s) => s.name === "test");
  const create = useCreateReplay();
  return (
    <Section title="Recorded demo" divider={false}>
      <div className="start-row">
        <p className="start-row__text">
          {demo.display_alias}, starting at the final test period
          {test ? <> (<span className="num">{replayTime(test.start_at)}</span>)</> : null}: forecasts, warnings and their outcomes
          on later recordings from a participant represented in training. Each click starts a new replay session.
        </p>
        <div className="start-row__actions">
          <Button variant="primary" icon={Play} disabled={!test} busy={create.isPending}
            onClick={() => test && create.mutate({ patientId: demo.patient_id, mode: "dataset_replay", startAt: test.start_at })}>
            Open recorded demo
          </Button>
        </div>
      </div>
    </Section>
  );
}

/** Flat divided rows: participant · data · replay time · state · action. Used by the overview (six) and sessions page. */
export function SessionRows({ items, detailed = false }: { items: ReplaySession[]; detailed?: boolean }) {
  const dup = new Map<string, number>();
  for (const s of items) dup.set(s.patient_id, (dup.get(s.patient_id) ?? 0) + 1);
  return (
    <div className="rows" role="table" aria-label="Replay sessions">
      <div className="rows__head" role="row">
        <span role="columnheader">Participant</span>
        <span role="columnheader">Data</span>
        <span role="columnheader">Replay time</span>
        <span role="columnheader">State</span>
        <span role="columnheader"><span className="visually-hidden">Action</span></span>
      </div>
      <div role="rowgroup">
        {items.map((s) => {
          const synthetic = s.mode === "synthetic_demo";
          const showSecondary = detailed || (dup.get(s.patient_id) ?? 0) > 1;
          return (
            <div key={s.id} className="rows__row" role="row">
              <span role="cell" className="rows__primary">
                <Link to={paths.session(s.id)} className="rows__alias">{s.patient_alias}</Link>
                {showSecondary && (
                  <span className="rows__secondary">Session {s.id.slice(0, 8)} · started {wallTime(s.created_at)}</span>
                )}
              </span>
              <span role="cell" className="rows__data">
                <span aria-hidden>{synthetic ? "Synthetic" : "Recorded"}</span>
                <span className="visually-hidden">{modeLabel(s.mode)}</span>
              </span>
              <span role="cell" className="rows__time num"><span className="visually-hidden">Replay time </span>{replayTime(s.clock_at)}</span>
              <span role="cell" className={`rows__state rows__state--${s.status}`}>{statusWord(s.status)}</span>
              <span role="cell" className="rows__action">
                <Link to={paths.session(s.id)} className="row-action" aria-label={`${s.status === "ready" ? "Open" : "Resume"} replay for ${s.patient_alias}`}>
                  {s.status === "ready" ? "Open" : "Resume"}<ArrowRight size={15} aria-hidden />
                </Link>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
