import { Download, FileText, Printer, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type {
  AlertList,
  EvaluationReport,
  EvaluationSegment,
  LatestForecast,
  ObservationEvent,
  PatientSummary,
  ReplaySession,
  SessionProfile,
  TwinState,
} from "@/api/types";
import { fmtGlucose, fmtPct } from "@/lib/format";
import { replayTime, wallTime } from "@/lib/time";
import { guardChecks } from "@/components/twin/Panels";
import { Button, Dialog, InlineNotice } from "@/components/ui";
import {
  buildSnapshot,
  downloadSnapshot,
  type GuardText,
  nodeText,
  type ReviewSnapshot,
  snapshotReadiness,
} from "./snapshot";
import "@/styles/review-summary.css";

type Q<T> = { data?: T; isPlaceholderData?: boolean; isError?: boolean };

/**
 * "Review summary": freezes what the workspace shows at the current replay time into a text-only report that can be
 * printed (only the report prints) or downloaded as JSON. The copy never changes while the replay plays; "Recreate"
 * makes a new one. A rewind/reset or another participant discards it.
 */
export function ReviewSummary({ session, patient, latest, alerts, twin, profile, events, eventsLoaded, report, segments }: {
  session: ReplaySession; patient?: PatientSummary; latest: Q<LatestForecast>; alerts: Q<AlertList>; twin: Q<TwinState>;
  profile: Q<SessionProfile>; events: ObservationEvent[]; eventsLoaded: boolean; report?: EvaluationReport;
  segments?: EvaluationSegment[] | null;
}) {
  const [open, setOpen] = useState(false);
  const [snap, setSnap] = useState<ReviewSnapshot | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const [discarded, setDiscarded] = useState(false);
  const ready = snapshotReadiness(session, { latest, alerts, twin, profile }, eventsLoaded, patient);

  // another participant/session: nothing carries over
  useEffect(() => {
    setSnap(null);
    setOpen(false);
    setBlocked(null);
    setDiscarded(false);
  }, [session.id]);
  // a rewind or reset makes the frozen copy belong to an abandoned timeline
  useEffect(() => {
    setSnap((s) => {
      if (s && s.session.revision !== session.revision) {
        setDiscarded(true);
        return null;
      }
      return s;
    });
  }, [session.revision]);

  const create = () => {
    if (!ready.ok) {
      setBlocked(ready.reason);
      return;
    }
    const guards: GuardText[] = guardChecks(session, latest.data, twin.data, alerts.data, report, segments).map((g) => ({
      label: g.label, status: g.tone === "ok" ? "passed" : g.tone === "attention" ? "flagged" : "info",
      value: nodeText(g.value), note: g.note ? nodeText(g.note) : null,
    }));
    setSnap(buildSnapshot({
      session, patient, profile: profile.data, latest: latest.data, twin: twin.data, alerts: alerts.data, events, report,
      guardrails: guards, generatedAt: new Date().toISOString(),
    }));
    setBlocked(null);
    setDiscarded(false);
  };

  const openPreview = () => {
    setOpen(true);
    if (!snap) create();
  };

  const moved = snap && snap.session.revision === session.revision && snap.replay_cutoff !== session.clock_at;
  return (
    <>
      <Button icon={FileText} onClick={openPreview} aria-haspopup="dialog">Review summary</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Review summary" width={820} className="review-dialog"
        description="A frozen copy of this replay at one moment. Research replay review — not a medical report."
        footer={
          <div className="review-actions">
            <Button icon={RefreshCw} onClick={create} disabled={!ready.ok} title={ready.ok ? undefined : ready.reason}>
              {snap ? "Recreate at current time" : "Create"}
            </Button>
            <span className="review-actions__spacer" />
            <Button icon={Download} disabled={!snap} onClick={() => snap && downloadSnapshot(snap)}>Download JSON</Button>
            <Button variant="primary" icon={Printer} disabled={!snap} onClick={() => window.print()}>Print / Save as PDF</Button>
          </div>
        }>
        {blocked && !snap && <InlineNotice tone="attention" role="status"><strong>Summary not created.</strong> {blocked}</InlineNotice>}
        {discarded && !snap && (
          <InlineNotice tone="neutral" role="status">
            The replay was rewound or reset after the last summary was created, so that copy was discarded. Create a new one.
          </InlineNotice>
        )}
        {moved && (
          <InlineNotice tone="neutral" role="status">
            The replay has moved to {replayTime(session.clock_at)} since this copy; it still shows {snap.replay_cutoff_label}.
            Use “Recreate at current time” for a newer copy.
          </InlineNotice>
        )}
        {snap && <ReviewDocument s={snap} />}
      </Dialog>
      {/* the print copy: outside the app shell, shown only by @media print while a summary is open */}
      {open && snap && createPortal(<div className="review-print-root" aria-hidden="true"><ReviewDocument s={snap} /></div>, document.body)}
    </>
  );
}

const mg = (v: number | null) => (v === null ? "—" : `${fmtGlucose(v)} mg/dL`);
const signed = (v: number | null) => (v === null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)} mg/dL`);

/** The report itself. Text only: every value is rendered by React as text, never as HTML. */
export function ReviewDocument({ s }: { s: ReviewSnapshot }) {
  const w = s.warnings;
  return (
    <article className="review-doc" aria-label="Review summary report">
      <header className="review-doc__head">
        <p className="review-doc__kicker">{s.title}</p>
        <h3 className="review-doc__title">{s.participant.alias} · review summary</h3>
        <p className="review-doc__disclaimer">{s.disclaimer}. A replay of {s.participant.synthetic ? "fictional, synthetic" : "recorded, de-identified"} data, not a live device; no treatment advice.</p>
      </header>

      <dl className="review-doc__meta">
        <dt>Replay cutoff</dt><dd className="num">{s.replay_cutoff_label}</dd>
        <dt>Generated</dt><dd>{wallTime(s.generated_at_wall_clock)} (wall clock, this computer)</dd>
        <dt>Data</dt><dd>{s.session.mode_label}{s.participant.dataset ? ` · ${s.participant.dataset}` : ""}{s.participant.license ? ` (${s.participant.license})` : ""}</dd>
        {s.participant.cohort && <><dt>Cohort</dt><dd>{s.participant.cohort}</dd></>}
        {s.participant.exploratory && <><dt>Analysis</dt><dd>{s.participant.exploratory}</dd></>}
        <dt>Session</dt><dd className="wrap-id">{s.session.id} · revision {s.session.revision}</dd>
      </dl>

      <section className="review-doc__sec">
        <h4>Latest glucose</h4>
        {s.glucose ? (
          <p>
            <strong className="num">{mg(s.glucose.value_mg_dl)}</strong>, observed {s.glucose.observed} ·{" "}
            {s.glucose.stale
              ? <strong className="review-doc__flag">Stale — {s.glucose.age_minutes} min old, over the {s.glucose.stale_limit_minutes}-min limit</strong>
              : <>{s.glucose.age_minutes} min old</>}
          </p>
        ) : <p>No glucose reading had been released by the cutoff.</p>}
      </section>

      <section className="review-doc__sec">
        <h4>Forecast</h4>
        <dl className="review-doc__meta">
          <dt>Availability</dt><dd>{s.forecast.availability}</dd>
          <dt>Issued</dt><dd className="num">{s.forecast.issued ?? "—"}</dd>
          <dt>Model</dt><dd className="wrap-id">{s.forecast.model_version ?? "none"}</dd>
          <dt>Evaluation context</dt><dd>{s.forecast.evaluation_context}</dd>
          {s.forecast.quality && <><dt>Input quality</dt><dd>{s.forecast.quality}</dd></>}
        </dl>
        {s.forecast.unavailable && <p className="review-doc__flag">{s.forecast.unavailable} Unavailable is not the same as low risk.</p>}
        {s.forecast.estimates.length > 0 ? (
          <table className="review-doc__table">
            <thead>
              <tr><th scope="col">Horizon</th><th scope="col">For</th><th scope="col" className="num">Population</th>
                <th scope="col" className="num">Patient correction</th><th scope="col" className="num">Forecast</th><th scope="col">Prediction range</th></tr>
            </thead>
            <tbody>
              {s.forecast.estimates.map((e) => (
                <tr key={e.horizon_minutes}>
                  <td>{e.horizon_minutes} min</td>
                  <td className="num">{e.target}</td>
                  <td className="num">{mg(e.population_mg_dl)}</td>
                  <td className="num">{signed(e.patient_correction_mg_dl)}</td>
                  <td className="num"><strong>{mg(e.forecast_mg_dl)}</strong></td>
                  <td>{e.range_mg_dl ? `${fmtGlucose(e.range_mg_dl[0])}–${fmtGlucose(e.range_mg_dl[1])} mg/dL · ` : ""}{e.range_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p>No forecast values: none was usable at the cutoff.</p>}
        {s.forecast.reasons.length > 0 && <p className="review-doc__note">Reasons given by the twin: {s.forecast.reasons.join(" ")}</p>}
        <p className="review-doc__note">
          {s.coverage
            ? <>Prediction ranges, measured on the final test period ({s.coverage.experiment}): {s.coverage.measured.map((m) => `${fmtPct(m.coverage, 1)} at ${m.horizon_minutes} min`).join(", ")} against a {fmtPct(s.coverage.target)} target. Coverage varies by participant; no guarantee.</>
            : <>No measured range coverage is available for this model version.</>}
        </p>
        {s.personalization && (
          <p className="review-doc__note">
            Patient correction: {s.personalization.status}
            {s.personalization.horizons.length > 0 && <> ({s.personalization.horizons.map((h) => `${h.horizon_minutes} min ${h.correction_mg_dl === null ? `${h.matured} of ${h.required} observed errors` : signed(h.correction_mg_dl)}`).join("; ")})</>}.
            Learned only from forecasts whose outcome was observed; capped at ±25 mg/dL.
          </p>
        )}
      </section>

      <section className="review-doc__sec">
        <h4>Research warnings at the cutoff</h4>
        {!w.rule_available ? <p>No validated warning rule is loaded for this mode.</p> : w.total === 0 ? <p>None issued by the cutoff.</p> : (
          <>
            <p>
              {w.total} issued since the start of this recording: {w.counts.onset} onset, {w.counts.false_alarm} false alarm,{" "}
              {w.counts.pending} pending, {w.counts.unknown} unknown (gap).{w.truncated && <> The {w.listed} most recent are listed below.</>}
            </p>
            <ul className="review-doc__warnings">
              {w.items.map((a) => (
                <li key={a.issued_at}>
                  <p><strong className="num">{a.issued}</strong> · {a.outcome}{a.trigger ? ` · ${a.trigger}` : ""}</p>
                  {a.reviewed && (
                    <p className="review-doc__note">
                      Marked as reviewed{a.reviewed_at_wall_clock ? ` ${wallTime(a.reviewed_at_wall_clock)} (wall clock)` : ""}
                      {a.note ? <> — note: <span className="review-doc__quote">{a.note}</span></> : " — no note"}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="review-doc__sec">
        <h4>Guardrails at the cutoff</h4>
        <ul className="review-doc__guards">
          {s.guardrails.map((g) => (
            <li key={g.label}>
              <strong>{g.label}</strong> <span className={`review-doc__tag review-doc__tag--${g.status}`}>{g.status === "passed" ? "passed" : g.status === "flagged" ? "flagged" : "info"}</span>
              <br />{g.value}{g.note ? <span className="review-doc__note"> {g.note}</span> : null}
            </li>
          ))}
        </ul>
      </section>

      {s.profile && (
        <section className="review-doc__sec">
          <h4>Baseline profile (EHR-like) known at the cutoff</h4>
          <p className="review-doc__note">{s.profile.note}</p>
          <dl className="review-doc__meta review-doc__meta--cols">
            {s.profile.items.map((v) => (
              <div key={v.label} className="review-doc__pair"><dt>{v.label}</dt><dd>{v.value}</dd></div>
            ))}
          </dl>
        </section>
      )}

      <footer className="review-doc__foot">
        {s.schema} · generated by GlucoTwin, a student research prototype. Not a medical device; no treatment advice;
        notes are local research-session annotations, not orders or messages to a patient.
      </footer>
    </article>
  );
}
