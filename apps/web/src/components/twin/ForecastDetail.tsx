import { CircleCheck, Clock, TimerOff } from "lucide-react";
import type { EvaluationReport, Forecast, ObservationEvent, PatientSummary } from "@/api/types";
import { measuredCoverage } from "@/lib/forecast";
import { fmtGlucose, fmtPct, modeLabel } from "@/lib/format";
import { horizonOutcome, type HorizonOutcome } from "@/lib/outcome";
import { replayTime } from "@/lib/time";
import { Button, Dialog } from "../ui";

const SEG: Record<string, string> = {
  training: "Training period — this origin is in-sample for the population model",
  validation: "Validation-selection period",
  calibration: "Calibration period",
  test: "Final test period (later recordings from a participant represented in training)",
  unassigned: "Outside the evaluation segments",
};
const KIND: Record<string, string> = {
  observation: "Observation",
  data_quality: "Data quality",
  model_association: "Model association",
  personalization: "Patient adaptation",
};

/** Side drawer with the provenance of one forecast: identity, cutoff, components, range semantics, explanations. */
export function ForecastDetail({ f, patient, report, open, onClose, publicDemo = false, events = [], clock }: {
  f: Forecast | null; patient?: PatientSummary; report?: EvaluationReport; open: boolean; onClose: () => void; publicDemo?: boolean;
  /** released observations of the session and the replay clock, for the outcome of each horizon */
  events?: ObservationEvent[]; clock?: number;
}) {
  const cov = f ? measuredCoverage(report, f.model_version) : null;
  return (
    <Dialog open={open && !!f} onClose={onClose} title="Forecast details" variant="drawer" width={520}
      description={f ? `Issued at ${replayTime(f.as_of)} (information cutoff)` : undefined}
      footer={<Button onClick={onClose}>Close</Button>}>
      {f && (
        <div className="drawer-body">
          <section aria-label="Identity">
            <dl className="dl">
              <dt>Model</dt><dd>{f.model_family === "lightgbm" ? "LightGBM" : f.model_family ?? "—"}
                {publicDemo && f.mode === "synthetic_demo" && <span className="table__sub">Synthetic demonstration model, fitted on fictional data — not the evaluated real-data fusion model</span>}</dd>
              <dt>Model version</dt><dd className="wrap-id">{f.model_version ?? "none"}</dd>
              <dt>Data</dt><dd>{modeLabel(f.mode)}{patient ? ` · ${patient.dataset.name} ${patient.dataset.version} (${patient.dataset.license})` : ""}</dd>
              <dt>Evaluation period</dt><dd>{f.split_segment ? SEG[f.split_segment] ?? f.split_segment : "Not part of a measured evaluation"}</dd>
              <dt>Input quality</dt>
              <dd>{f.quality.status === "ok" ? "Complete" : f.quality.status === "degraded" ? "Degraded" : "Insufficient"}
                {f.quality.reasons.length > 0 && <span className="muted"> — {f.quality.reasons.map((r) => r.message).join(" ")}</span>}</dd>
              <dt>Latest input reading</dt>
              <dd className="num">{f.observed_glucose ? `${fmtGlucose(f.observed_glucose.value_mg_dl)} mg/dL at ${replayTime(f.observed_glucose.observed_at)}` : "—"}</dd>
              <dt>Forecast ID</dt><dd className="wrap-id">{f.forecast_id}</dd>
            </dl>
          </section>

          <section aria-labelledby="fd-components">
            <h3 className="drawer-body__h" id="fd-components">Estimate by horizon</h3>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr><th scope="col">Horizon</th><th scope="col" className="num">Population</th><th scope="col" className="num">Patient correction</th>
                    <th scope="col" className="num">Forecast</th><th scope="col">Prediction range</th></tr>
                </thead>
                <tbody>
                  {f.estimates.map((e) => (
                    <tr key={e.horizon_minutes}>
                      <td>{e.horizon_minutes} min → {replayTime(e.target_at, { day: false })}</td>
                      <td className="num">{fmtGlucose(e.components?.population_mg_dl) ?? "—"}</td>
                      <td className="num">{e.components?.patient_correction_mg_dl == null ? "—" : `${e.components.patient_correction_mg_dl >= 0 ? "+" : "−"}${Math.abs(e.components.patient_correction_mg_dl).toFixed(1)}`}</td>
                      <td className="num"><strong>{fmtGlucose(e.predicted_mg_dl) ?? "—"}</strong></td>
                      <td className="num">{e.interval_status === "calibrated" ? `${fmtGlucose(e.lower_mg_dl)}–${fmtGlucose(e.upper_mg_dl)}` : "Unavailable"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="drawer-body__note">
              Prediction range: target coverage {Math.round((f.estimates.find((e) => e.interval_level)?.interval_level ?? 0.8) * 100)}%.{" "}
              {cov ? <>Measured on the final test period: {cov.byHorizon.map((b) => `${fmtPct(b.coverage, 1)} at ${b.horizon} min`).join(", ")} ({cov.experiment}). Coverage varies by participant; no guarantee.</>
                : <>No measured coverage for this model version on recorded data; no guarantee.</>}
            </p>
          </section>

          {clock != null && (
            <section aria-labelledby="fd-outcome">
              <h3 className="drawer-body__h" id="fd-outcome">Outcome</h3>
              <OutcomeState f={f} events={events} clock={clock} />
              <ul className="facts">
                {f.estimates.map((e) => (
                  <li key={e.horizon_minutes}>
                    <OutcomeLine horizon={e.horizon_minutes} target={e.target_at} o={horizonOutcome(e, events, clock)} />
                  </li>
                ))}
              </ul>
              <p className="drawer-body__note">
                The observed reading is the sensor value recorded within 2.5 min of the target time and released by the replay
                clock — a measurement, not an estimate. Errors are the saved forecast minus that reading; one outcome says
                nothing about how often the correction helps.
              </p>
            </section>
          )}

          <section aria-labelledby="fd-why">
            <h3 className="drawer-body__h" id="fd-why">Factual explanations</h3>
            <ul className="explain-list">
              {f.explanations.map((e) => (
                <li key={e.code}><span className="explain-list__k">{KIND[e.kind] ?? e.kind}</span><span>{e.text}</span></li>
              ))}
            </ul>
            <p className="drawer-body__note">
              Tree contributions describe associations inside the population model; they are not causes and not clinical
              recommendations. Patient adaptation: {f.personalization.status.replace(/_/g, " ")}
              {f.personalization.enabled ? ` (state version ${f.personalization.state_version})` : ""}.
            </p>
          </section>
        </div>
      )}
    </Dialog>
  );
}

/** One line above the per-horizon outcomes: pending, partly observed, resolved or unknown, judged at the replay clock. */
function OutcomeState({ f, events, clock }: { f: Forecast; events: ObservationEvent[]; clock: number }) {
  const all = f.estimates.map((e) => ({ e, o: horizonOutcome(e, events, clock) }));
  const pending = all.filter((x) => x.o.state === "pending");
  const unknown = all.filter((x) => x.o.state === "unknown");
  const observed = all.filter((x) => x.o.state === "observed");
  const due = (xs: typeof all) => xs.map((x) => `${x.e.horizon_minutes} min, due ${replayTime(x.e.target_at, { day: false })}`).join("; ");
  const [state, Icon, title, text] = pending.length === all.length
    ? ["pending", Clock, "Pending", `No outcome is observed yet at this replay time (${due(pending)}).`] as const
    : pending.length > 0
      ? ["partial", Clock, "Partly observed", `${observed.length} of ${all.length} horizons observed; still pending: ${due(pending)}.`] as const
      : unknown.length === all.length
        ? ["unknown", TimerOff, "Outcome unknown", "No reading near either target time (sensor gap)."] as const
        : ["resolved", CircleCheck, "Observed", unknown.length
          ? `${observed.length} of ${all.length} horizons observed; no reading near the other target time.`
          : "Every horizon has an observed reading at this replay time."] as const;
  return (
    <p className="outcome-state" data-state={state}>
      <Icon size={15} aria-hidden strokeWidth={2} />
      <span><strong>{title}</strong> · {text}</span>
    </p>
  );
}

const signed = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}`;

function OutcomeLine({ horizon, target, o }: { horizon: number; target: string; o: HorizonOutcome }) {
  const head = <><strong>{horizon} min</strong> (for {replayTime(target, { day: false })}): </>;
  if (o.state === "pending") return <>{head}<span className="muted">Outcome not yet observed at this replay time.</span></>;
  if (o.state === "unknown") return <>{head}<span className="muted">No reading near the target time — outcome unknown.</span></>;
  return (
    <>
      {head}observed reading <strong className="num">{fmtGlucose(o.observed)} mg/dL</strong> at {replayTime(o.observedAt, { day: false })}.
      {" "}Forecast error {o.finalError == null ? "—" : `${signed(o.finalError)} mg/dL`}
      {o.populationError != null && <>; population forecast error {signed(o.populationError)} mg/dL</>}.
      {o.correction && (
        <span className="table__sub">
          {o.correction.effect === "none" ? "The patient correction made no difference to this forecast's error (under 0.5 mg/dL)."
            : `The patient correction moved this forecast ${o.correction.by.toFixed(1)} mg/dL ${o.correction.effect === "closer" ? "closer to" : "further from"} the observed value.`}
        </span>
      )}
    </>
  );
}
