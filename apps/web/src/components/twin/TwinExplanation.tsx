import type { AlertList, EvaluationReport, LatestForecast, SessionProfile } from "@/api/types";
import { explainForecast, type Explanation, type InputUse } from "@/lib/explain";
import { fmtGlucose, fmtPct } from "@/lib/format";
import { durationLabel, ms, replayTime } from "@/lib/time";
import "@/styles/twin-explanation.css";

const signed = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}`;
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

/**
 * How the twin reached its latest forecast, from the values the API recorded for that forecast: population forecast,
 * the patient correction applied at issue time and the final estimate per horizon; the correction's state and bound;
 * which inputs were available; the warning track record and range coverage at this replay clock. No history curve and
 * no recomputation: the final estimate shown is the API's own.
 */
export function TwinExplanation({ latest, alerts, profile, report, clockAt, profileInputs }: {
  latest?: LatestForecast; alerts?: AlertList; profile?: SessionProfile; report?: EvaluationReport; clockAt: string;
  /** profile values the issuing model reads, from /serving for the same model version */
  profileInputs?: string[] | null;
}) {
  const cutoff = ms(clockAt);
  const f = latest?.forecast && ms(latest.forecast.as_of) <= cutoff ? latest.forecast : null;
  const usable = !!f && f.quality.status !== "insufficient" && (latest?.availability === "available" || latest?.availability === "stale");
  return (
    <section className="explain" aria-labelledby="explain-title">
      <h2 className="explain__title" id="explain-title">How the twin reached this forecast</h2>
      {!latest ? <p className="explain__lede muted">Loading the latest forecast…</p>
        : !usable || !f ? (
          <p className="explain__lede">No forecast is shown at this replay time, so there is nothing to explain yet.
            {" "}{latest.forecast?.quality.reasons[0]?.message ?? latest.reasons[0]?.message ?? ""}</p>
        ) : <Body e={explainForecast(f, { cutoff, alerts, profile, report, profileInputs })} stale={latest.availability === "stale"} age={latest.age_minutes} />}
    </section>
  );
}

function Body({ e, stale, age }: { e: Explanation; stale: boolean; age: number | null }) {
  const c = e.correction;
  return (
    <>
      <p className="explain__lede">
        Forecast issued <span className="num">{replayTime(e.issuedAt)}</span>
        {stale && <> — <span className="explain__flag">{age != null ? `${durationLabel(age)} ` : ""}before the replay clock (stale)</span></>}
        {" "}by <span className="wrap-id">{e.modelVersion ?? "an unknown model"}</span>. Every value below was recorded with this forecast.
      </p>
      <div className="explain__table" role="table" aria-label="Forecast components">
        <div role="row" className="explain__row explain__row--head">
          <span role="columnheader">Horizon</span>
          <span role="columnheader">Population forecast</span>
          <span role="columnheader">Patient correction</span>
          <span role="columnheader">Final estimate</span>
          <span role="columnheader">For</span>
        </div>
        {e.horizons.map((h) => (
          <div role="row" className="explain__row" key={h.horizon}>
            <span role="cell">{h.horizon} min</span>
            <span role="cell" className="num">{h.population != null ? `${fmtGlucose(h.population)} mg/dL` : "—"}</span>
            <span role="cell" className="num">{h.correction != null ? `${signed(h.correction)} mg/dL` : c.status === "disabled" ? "Off" : "—"}</span>
            <span role="cell" className="num explain__final">{h.final != null ? `${fmtGlucose(h.final)} mg/dL` : "Not available"}</span>
            <span role="cell" className="num">{replayTime(h.targetAt)}</span>
          </div>
        ))}
      </div>
      <dl className="dl dl--compact explain__facts">
        <dt>Patient correction</dt>
        <dd>
          {c.status === "disabled" ? "Off for this model."
            : c.status === "active" ? "Active: learned from this person's own earlier forecasts whose outcome had been observed."
              : c.status === "reset_after_gap" ? "Reset after a data gap; learning again (no correction until enough outcomes are observed)."
                : "Warming up: no correction until enough outcomes are observed."}
          {c.matured.length > 0 && (
            <span className="table__sub">
              {c.matured.map((m) => `${m.horizon} min: ${m.n} observed ${m.n === 1 ? "outcome" : "outcomes"} (needs ${m.needed})`).join(" · ")}
            </span>
          )}
          {c.cap != null && (
            <span className="table__sub">Bounded at ±{c.cap} mg/dL{c.resetGap != null ? `; cleared after a ${durationLabel(c.resetGap)} gap between readings` : ""}. Model weights are never refit.</span>
          )}
        </dd>
        <dt>Inputs at issue time</dt>
        <dd>
          <span className="explain__input">Glucose: {e.inputs.glucose
            ? <>latest reading <span className="num">{fmtGlucose(e.inputs.glucose.value)} mg/dL</span> observed <span className="num">{replayTime(e.inputs.glucose.observedAt, { day: false })}</span></>
            : "no reading"}</span>
          <span className="explain__input">Wearable activity: {WEARABLE[e.inputs.wearable]}</span>
          {e.inputs.profile && (
            <span className="explain__input">Health record: {profileText(e.inputs.profile)}</span>
          )}
        </dd>
        <dt>Warnings so far</dt>
        <dd>
          {!e.track ? "—" : e.track.total === 0 ? "None issued since the start of this recording." : (
            <>
              {plural(e.track.total, "research warning")}: {[
                e.track.onset && `${e.track.onset} ${e.track.onset === 1 ? "onset" : "onsets"} observed`,
                e.track.falseAlarm && plural(e.track.falseAlarm, "false alarm"),
                e.track.pending && `${e.track.pending} pending`,
                e.track.unknown && `${e.track.unknown} unknown (data gap)`,
              ].filter(Boolean).join(" · ")}
              <span className="table__sub">As known at this replay time; an outcome observed later still counts as pending.</span>
            </>
          )}
        </dd>
        <dt>Prediction range</dt>
        <dd>
          {e.coverage.target == null ? "No calibrated range for this forecast." : (
            <>
              Target coverage {fmtPct(e.coverage.target)}.
              {e.coverage.measured
                ? <> Measured for this model on its final test period: {e.coverage.measured.map((m) => `${fmtPct(m.coverage, 1)} at ${m.horizon} min`).join(", ")} ({e.coverage.experiment}).</>
                : <> No measured coverage is reported for this exact model.</>}
              <span className="table__sub">An aggregate over the test period, not a guarantee for this person or this forecast.</span>
            </>
          )}
        </dd>
        {e.trend && (
          <>
            <dt>Accuracy at this trend</dt>
            <dd>
              Glucose {e.trend.slope > 0 ? "rising" : e.trend.slope < 0 ? "falling" : "changing"} {Math.abs(e.trend.slope).toFixed(1)} mg/dL per
              minute over the last 15 min ({e.trend.label.charAt(0).toLowerCase() + e.trend.label.slice(1)}). On this model's validation data at this trend:{" "}
              {e.trend.byHorizon.filter((b) => b.mae != null).map((b) => `${b.horizon}-min error ${b.mae!.toFixed(1)} mg/dL`
                + (e.trend!.steady || b.steadyMae == null ? "" : ` (steady: ${b.steadyMae.toFixed(1)})`)).join("; ")}.
              {e.trend.peakBias60 != null && e.trend.peakBias60 < 0 && <> Peaks above 180 mg/dL were under-forecast by {Math.abs(e.trend.peakBias60).toFixed(0)} mg/dL on average at 60 min.</>}
              {(() => {
                const c = e.trend.byHorizon.filter((b) => b.rangeCoverage != null);
                return c.length ? <> At this trend the {fmtPct(e.coverage.target ?? 0.8, 0)} range held the outcome {c.map((b) => `${fmtPct(b.rangeCoverage!, 0)} of the time at ${b.horizon} min`).join(", ")}.</> : null;
              })()}
              <span className="table__sub">Average error over many forecasts ({e.trend.experiment}, validation segment); descriptive, not a guarantee for this forecast.</span>
            </dd>
          </>
        )}
      </dl>
    </>
  );
}

const WEARABLE: Record<InputUse, string> = {
  used: "5-minute summaries from the last hour were available and used.",
  used_missing: "read by this model, but no summary was available for the last hour; left missing, not filled in.",
  not_input: "not an input of this model.",
  unknown: "not stated by this model's version.",
};

function profileText(p: NonNullable<Explanation["inputs"]["profile"]>): string {
  const list = (xs: string[]) => xs.join(", ");
  const known = p.known.length ? `${p.known.length} ${p.known.length === 1 ? "value" : "values"} known (${list(p.known)})` : "no value known";
  const rest = [p.notYet.length ? `not yet available: ${list(p.notYet)}` : null, p.missing.length ? `missing in the source: ${list(p.missing)}` : null]
    .filter(Boolean).join("; ");
  if (p.use === "not_input") return `not an input of this model; ${known}${rest ? `; ${rest}` : ""} — shown for context only.`;
  if (p.use === "used_missing") return `read by this model; a value it needs was missing or not yet known, so it abstained. ${rest}`.trim();
  if (p.use === "unknown") return "read by this model; the profile has not loaded yet.";
  const ctx = p.context.length ? ` Context only, not model inputs: ${list(p.context)}.` : "";
  return `read by this model; ${known}${rest ? `; ${rest}` : ""}.${ctx}`;
}
