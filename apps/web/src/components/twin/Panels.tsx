import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BellRing,
  CircleCheck,
  CircleDashed,
  Gauge,
  Info,
  TriangleAlert,
} from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import type {
  Alert,
  AlertList,
  EvaluationReport,
  EvaluationSegment,
  Forecast,
  HorizonEstimate,
  LatestForecast,
  ObservationEvent,
  PatientSummary,
  ReplaySession,
  SessionProfile,
  TwinState,
} from "@/api/types";
import { latestGlucose, trendFrom, visibleAt } from "@/lib/chart";
import { measuredCoverage, modelUsesProfile, unavailableReason } from "@/lib/forecast";
import { fmtGlucose, fmtPct, fmtProfileValue, modeLabel } from "@/lib/format";
import { durationLabel, minutesBetween, ms, replayTime } from "@/lib/time";
import { Button, InlineNotice, Skeleton, StatusLabel } from "../ui";
import { SavedReview, WarningReviewDialog } from "./WarningReview";

/* ================================================================ Baseline line + profile details */
export function BaselineLine({ patient, profile, session, modelVersion }: {
  patient?: PatientSummary; profile?: SessionProfile; session: ReplaySession; modelVersion?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const val = (name: string) => profile?.values.find((v) => v.name === name);
  const show = (name: string): string => {
    const v = val(name);
    if (!v || v.status === "missing_in_source" || v.status === "excluded_suspect") return "Not available";
    if (v.status === "not_yet_available") return "Not yet available";
    return fmtProfileValue(v.value, v.unit);
  };
  const sex = val("sex_male");
  const items: [string, string][] = [
    ["Age", show("age")],
    ["Sex", !sex || sex.value === null ? "Not available" : sex.value === 1 ? "Male" : "Female"],
    ["BMI", show("bmi")],
    ["HbA1c", show("hba1c")],
    ["Fasting glucose (baseline)", show("fasting_glucose")],
  ];
  const usesProfile = modelUsesProfile(modelVersion);
  return (
    <div className="baseline">
      <div className="baseline__row">
        {profile ? (
          <dl className="baseline__list" aria-label={`Baseline values as known at ${replayTime(profile.as_of)}`}>
            {items.map(([k, v]) => (
              <div key={k} className="baseline__item">
                <dt>{k}</dt>
                <dd className={v.startsWith("Not") ? "baseline__na" : "num"}>{v}</dd>
              </div>
            ))}
          </dl>
        ) : <Skeleton h={18} w={420} />}
        <button type="button" className="text-btn" aria-expanded={open} aria-controls={detailsId} onClick={() => setOpen((o) => !o)}>
          {open ? "Hide profile details" : "Profile details"}
        </button>
      </div>
      <p className="baseline__note">
        Baseline context known at {replayTime(profile?.as_of ?? session.clock_at)}, not live measurements.
        {usesProfile === false && " The current model forecasts from recent glucose and activity only; it does not use these values."}
        {usesProfile === true && " The current model includes baseline profile values among its inputs."}
      </p>
      {open && (
        <div id={detailsId} className="profile-details">
          <dl className="dl">
            <dt>Cohort</dt><dd>{patient?.cohort.label ?? "—"}{patient?.cohort.provenance ? ` — ${patient.cohort.provenance}` : ""}</dd>
            <dt>Data</dt><dd>{modeLabel(session.mode)}{patient ? ` · ${patient.dataset.name} ${patient.dataset.version} (${patient.dataset.license})` : ""}</dd>
            {patient?.mode === "dataset_replay" && !patient.eligible_for_primary_analysis && (
              <><dt>Analysis</dt><dd>Exploratory — outside the primary Type 2 analysis{patient.exclusion_reason ? ` (${patient.exclusion_reason})` : ""}</dd></>
            )}
            {(profile?.values ?? []).map((v) => (
              <div key={v.name} style={{ display: "contents" }}>
                <dt>{v.label}</dt>
                <dd>
                  {v.status === "available" ? fmtProfileValue(v.value, v.unit) : v.status === "not_yet_available" ? "Not yet available" : "Not available"}
                  {v.source && <span className="muted"> · {v.source}</span>}
                  {v.note && <span className="muted"> · {v.note}</span>}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

/* ================================================================ Summary: current reading and forecasts, one flat group */
function estimate(f: Forecast | null | undefined, h: number): HorizonEstimate | undefined {
  return f?.estimates.find((e) => e.horizon_minutes === h);
}

export function GlucoseSummary({ session, events, latest, twin, loading, eventsLoaded = true, report }: {
  session: ReplaySession; events: ObservationEvent[]; latest?: LatestForecast; twin?: TwinState; loading: boolean;
  /** false while the released events of this session revision are still being fetched */
  eventsLoaded?: boolean;
  report?: EvaluationReport;
}) {
  const clock = ms(session.clock_at);
  const last = latestGlucose(events, clock);
  const age = last ? minutesBetween(last.observed_at, clock) : null;
  const trend = trendFrom(events, clock);
  const f = latest?.forecast && ms(latest.forecast.as_of) <= clock ? latest.forecast : null;
  const why = unavailableReason(latest, twin, loading);
  const usable = !!f && (latest?.availability === "available" || latest?.availability === "stale");
  const TrendIcon = !trend ? null : trend.delta >= 5 ? ArrowUpRight : trend.delta <= -5 ? ArrowDownRight : ArrowRight;
  const stale = age !== null && age > session.freshness.stale_threshold_minutes;

  return (
    <div className="summary-wrap">
      <div className="summary">
        <section className="summary__item" aria-label="Current glucose">
          <p className="summary__label">Current glucose</p>
          {last ? (
            <>
              <p className="summary__value num">{fmtGlucose(last.values.value as number)}<span className="summary__unit">mg/dL</span></p>
              <p className="summary__meta">
                Observed <span className="num">{replayTime(last.observed_at)}</span>
                {stale ? <> · <StatusLabel tone="attention">Stale · {durationLabel(age)} old</StatusLabel></>
                  : <> · {durationLabel(age)} old</>}
              </p>
              {trend && TrendIcon && (
                <p className="summary__meta summary__trend">
                  <TrendIcon size={14} aria-hidden />
                  {trend.delta >= 0 ? "+" : ""}{Math.round(trend.delta)} mg/dL over {Math.round(trend.minutes)} min, observed
                </p>
              )}
            </>
          ) : loading || !eventsLoaded ? <Skeleton h={40} w={130} style={{ marginTop: 6 }} /> : (
            <>
              <p className="summary__value summary__value--na">No reading yet</p>
              <p className="summary__meta">No glucose observation has been released by the replay clock.</p>
            </>
          )}
        </section>
        {[30, 60].map((h) => (
          <ForecastItem key={h} h={h} f={usable ? f : null} latest={latest} loading={loading} />
        ))}
      </div>
      {why && why.kind !== "loading" && (
        <InlineNotice tone={why.kind === "stale" ? "attention" : "neutral"} icon={why.kind === "model" ? TriangleAlert : Info} role="status">
          <strong>{why.title}</strong> — {why.detail} <span className="muted">Unavailable is not the same as low risk.</span>
        </InlineNotice>
      )}
      {usable && f && <RangeNote f={f} report={report} />}
    </div>
  );
}

function ForecastItem({ h, f, latest, loading }: { h: number; f: Forecast | null; latest?: LatestForecast; loading: boolean }) {
  const e = estimate(f, h);
  const value = e?.predicted_mg_dl ?? null;
  return (
    <section className="summary__item summary__item--forecast" aria-label={`${h}-minute forecast`}>
      <p className="summary__label">{h}-minute forecast</p>
      {loading && !latest ? <Skeleton h={40} w={130} style={{ marginTop: 6 }} /> : value !== null && f && e ? (
        <>
          <p className="summary__value summary__value--forecast num">{fmtGlucose(value)}<span className="summary__unit">mg/dL</span></p>
          <p className="summary__meta">
            {e.lower_mg_dl !== null && e.upper_mg_dl !== null && e.interval_status === "calibrated"
              ? <>Range <span className="num">{fmtGlucose(e.lower_mg_dl)}–{fmtGlucose(e.upper_mg_dl)}</span> mg/dL</>
              : <>Prediction range unavailable</>}
          </p>
          <p className="summary__meta">
            For <span className="num">{replayTime(e.target_at)}</span> · issued <span className="num">{replayTime(f.as_of, { day: false })}</span>
            {latest?.availability === "stale" && <> · <StatusLabel tone="attention">Stale</StatusLabel></>}
            {f.quality.status === "degraded" && <> · <StatusLabel tone="attention">Degraded data</StatusLabel></>}
          </p>
        </>
      ) : (
        <>
          <p className="summary__value summary__value--na" aria-hidden>—</p>
          <p className="summary__meta">Not available</p>
        </>
      )}
    </section>
  );
}

/** "Prediction range · target coverage 80%" with the measured evidence one click away. */
function RangeNote({ f, report }: { f: Forecast; report?: EvaluationReport }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const level = f.estimates.find((e) => e.interval_level != null)?.interval_level;
  if (!level) return null;
  const cov = measuredCoverage(report, f.model_version);
  return (
    <div className="range-note">
      <span>Prediction range · target coverage {Math.round(level * 100)}%</span>
      <button type="button" className="text-btn" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        {open ? "Hide details" : "Details"}
      </button>
      {open && (
        <p id={id} className="range-note__detail">
          {cov ? (
            <>Measured coverage on the final test period: {cov.byHorizon.map((b) => `${fmtPct(b.coverage, 1)} at ${b.horizon} min (participants ${fmtPct(b.min, 0)}–${fmtPct(b.max, 0)})`).join("; ")} — experiment {cov.experiment}. Coverage varies by participant; no guarantee.</>
          ) : f.mode === "synthetic_demo" ? (
            <>The synthetic demonstration model has no measured coverage on recorded data. Coverage varies; no guarantee.</>
          ) : (
            <>Measured coverage for this model version is not available in the evaluation report. Coverage varies by participant; no guarantee.</>
          )}
        </p>
      )}
    </div>
  );
}

/* ================================================================ Review status (inspector) */
const EPISODE_MG_DL = 180;

/** The warning rule watches the highest forecast within its horizon; the trigger level is 180 mg/dL plus the margin
 *  chosen on validation data (e.g. −10 → 170 mg/dL), so a warning can fire before any forecast reaches 180. */
function warningRule(f: Forecast) {
  const maxH = Math.max(...f.event_risk.map((r) => r.horizon_minutes));
  const risk = f.event_risk.find((r) => r.alert_threshold != null) ?? f.event_risk.find((r) => r.horizon_minutes === maxH);
  if (!risk) return null;
  const top = f.estimates
    .filter((e) => e.horizon_minutes <= risk.horizon_minutes && e.predicted_mg_dl !== null)
    .reduce<HorizonEstimate | undefined>((a, e) => (!a || (e.predicted_mg_dl as number) > (a.predicted_mg_dl as number) ? e : a), undefined);
  return {
    risk, horizon: risk.horizon_minutes, top,
    trigger: risk.alert_threshold != null ? EPISODE_MG_DL + risk.alert_threshold : null,
  };
}

/** "10 mg/dL below the 180 mg/dL episode threshold" — the offset of a trigger level, in words. */
function triggerOffset(trigger: number): string {
  const d = trigger - EPISODE_MG_DL;
  return d === 0 ? `at the ${EPISODE_MG_DL} mg/dL episode threshold`
    : `${Math.abs(d)} mg/dL ${d < 0 ? "below" : "above"} the ${EPISODE_MG_DL} mg/dL episode threshold`;
}

type Review = { tone: "attention" | "neutral"; icon: typeof Info; title: string; text: string; short: string };

function reviewState(latest?: LatestForecast, alerts?: AlertList): Review {
  const f = latest?.forecast;
  const rule = f ? warningRule(f) : null;
  const openAlert = alerts?.items.find((a) => a.state === "open");
  if (latest?.reasons.some((r) => r.code === "model_unavailable")) {
    return { tone: "neutral", icon: TriangleAlert, title: "Model unavailable", short: "no warning can be assessed",
      text: "No verified forecasting model is loaded for this data mode, so no warning can be assessed." };
  }
  if (!latest || latest.availability === "not_ready" || !f || f.quality.status === "insufficient") {
    return { tone: "neutral", icon: CircleDashed, title: "Insufficient information", short: "no warning can be assessed",
      text: "The twin is not issuing a usable forecast right now, so no warning can be assessed." };
  }
  if (["pending_high", "in_episode", "recovering"].includes(f.episode_state)) {
    return { tone: "attention", icon: Gauge, title: "Already-high glucose state", short: "an observation, not a forecast",
      text: f.episode_state === "recovering"
        ? "A recent high-glucose episode has not yet met the 15-minute recovery rule. This is an observation, not a prediction."
        : `Current readings are above the ${EPISODE_MG_DL} mg/dL research threshold. This is an observation, not a forecast.` };
  }
  const top = rule?.top;
  const topText = top ? `the ${top.horizon_minutes}-minute forecast, ${fmtGlucose(top.predicted_mg_dl)} mg/dL` : "a forecast";
  if (rule?.risk.alert_fired && rule.trigger != null) {
    return { tone: "attention", icon: BellRing, title: "Warning issued",
      short: `${top ? `${top.horizon_minutes}-min forecast ${fmtGlucose(top.predicted_mg_dl)}` : "a forecast"} ≥ ${fmtGlucose(rule.trigger)} mg/dL trigger`,
      text: `Research warning: ${topText}, reached the ${fmtGlucose(rule.trigger)} mg/dL warning trigger. The rule watches the highest `
        + `forecast within ${rule.horizon} minutes and fires ${triggerOffset(rule.trigger)}`
        + (f.mode === "synthetic_demo" ? "" : " (chosen on validation data)")
        + (rule.trigger < EPISODE_MG_DL ? ", so warnings come earlier" : "")
        + ". Not a diagnosis." };
  }
  if (openAlert) {
    return { tone: "attention", icon: BellRing, title: "Warning awaiting outcome",
      short: `issued ${replayTime(openAlert.issued_at, { day: false })}, outcome pending`,
      text: `A research warning issued at ${replayTime(openAlert.issued_at, { day: false })} is waiting for its outcome. `
        + `The latest forecast${rule?.trigger != null ? ` is below the ${fmtGlucose(rule.trigger)} mg/dL trigger` : " did not fire the rule"}.` };
  }
  return { tone: "neutral", icon: CircleCheck, title: "No warning issued", short: "the rule did not fire",
    text: "The warning rule did not fire at the latest forecast. This does not mean glucose will stay below the threshold." };
}

export function ReviewStatus({ latest, alerts }: { latest?: LatestForecast; alerts?: AlertList }) {
  const f = latest?.forecast;
  const rule = f ? warningRule(f) : null;
  const state = reviewState(latest, alerts);
  const Icon = state.icon;
  return (
    <section className="inspector__block" aria-labelledby="review-title">
      <h2 className="inspector__title" id="review-title">Review</h2>
      <div className={`review review--${state.tone}`}>
        <Icon size={18} aria-hidden strokeWidth={1.9} className="review__icon" />
        <div>
          <p className="review__title">{state.title}</p>
          <p className="review__text">{state.text}</p>
        </div>
      </div>
      {rule && rule.risk.score != null && (
        <p className="review__score">
          Highest forecast within {rule.horizon} min <strong className="num">{fmtGlucose(EPISODE_MG_DL + rule.risk.score)} mg/dL</strong>
          {rule.top && <> ({rule.top.horizon_minutes}-min)</>}
          {rule.trigger != null && <> · warning trigger <span className="num">{fmtGlucose(rule.trigger)} mg/dL</span></>}.
          A forecast level, not a probability.
        </p>
      )}
      {alerts?.rule_available === false && <p className="inspector__muted">No validated warning rule is loaded for this mode.</p>}
    </section>
  );
}

/** One-line review status shown under the forecast numbers when the inspector sits below the chart (narrow screens). */
export function ReviewStrip({ latest, alerts }: { latest?: LatestForecast; alerts?: AlertList }) {
  const state = reviewState(latest, alerts);
  const Icon = state.icon;
  return (
    <p className={`review-strip review-strip--${state.tone}`}>
      <Icon size={16} aria-hidden strokeWidth={1.9} className="review-strip__icon" />
      <span className="review-strip__text">
        <strong className="review-strip__title">{state.title}</strong> · {state.short}{" "}
        <a href="#review-title" className="text-link review-strip__link">Details</a>
      </span>
    </p>
  );
}

/* ================================================================ Guardrails (inspector) */
type GuardTone = "ok" | "attention" | "neutral";
type Guard = { label: string; tone: GuardTone; value: ReactNode; note?: ReactNode };
const GUARD_ICON = { ok: CircleCheck, attention: TriangleAlert, neutral: CircleDashed } as const;
const GUARD_SR = { ok: "Check passed. ", attention: "Check flagged. ", neutral: "" } as const;

const signed = (v: number | null) => (v === null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}`);
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * Which safety checks applied at the latest forecast, read from the API: data freshness, input quality (abstained or
 * degraded, with the twin's own reasons), the fusion model's profile gate, the bounded patient correction, warning
 * outcomes and the prediction range. Rules the API does not return as values are stated as rules (the ±25 mg/dL cap and
 * the 3-hour reset hold for every model in the registry).
 */
export function guardChecks(session: ReplaySession, latest?: LatestForecast, twin?: TwinState, alerts?: AlertList,
  report?: EvaluationReport, segments?: EvaluationSegment[] | null): Guard[] {
  const out: Guard[] = [];
  const fr = session.freshness;
  out.push(fr.status === "fresh"
    ? { label: "Data freshness", tone: "ok",
      value: <>Fresh · {durationLabel(fr.latest_glucose_age_minutes)} old <span className="muted">(limit {fr.stale_threshold_minutes} min)</span></> }
    : fr.status === "stale"
      ? { label: "Data freshness", tone: "attention",
        value: <>Stale · {durationLabel(fr.latest_glucose_age_minutes)} old, over the {fr.stale_threshold_minutes}-min limit</> }
      : { label: "Data freshness", tone: "neutral", value: "No glucose reading released yet" });

  const f = latest?.forecast ?? null;
  const q = f?.quality.status;
  const reasons = [...(latest?.reasons ?? []), ...(f?.quality.reasons ?? [])];
  const codes = new Set(reasons.map((r) => r.code));
  const why = (f?.quality.reasons.length ? f.quality.reasons : latest?.reasons ?? []).map((r) => r.message).join(" ");
  const v60 = twin?.history.valid_samples_60;
  const abstained = !!latest && (!f || q === "insufficient" || latest.availability === "not_ready");
  if (!latest) out.push({ label: "Forecast inputs", tone: "neutral", value: "—" });
  else if (codes.has("model_unavailable")) {
    out.push({ label: "Forecast inputs", tone: "neutral", value: "No verified model is loaded for this mode" });
  } else if (abstained && (codes.has("no_glucose_history") || codes.has("no_forecast_yet"))) {
    out.push({ label: "Forecast inputs", tone: "neutral", value: "No forecast yet: no glucose reading released" });
  } else if (abstained) {
    out.push({ label: "Forecast inputs", tone: "attention", value: "Abstained: no forecast is shown", note: why || undefined });
  } else if (q === "degraded") {
    out.push({ label: "Forecast inputs", tone: "attention", value: "Degraded: forecast shown with a flag", note: why || undefined });
  } else if (fr.status !== "fresh" && f) {
    // the inputs were complete when the latest forecast was issued, but no newer reading has arrived since: not a success
    out.push({ label: "Forecast inputs", tone: "attention",
      value: `Latest forecast (issued ${replayTime(f.as_of, { day: false })}): complete`,
      note: `No newer reading since${v60 === undefined ? "" : `; ${plural(v60, "reading")} in the hour before the replay clock (about 12 expected)`}.` });
  } else {
    out.push({ label: "Forecast inputs", tone: "ok", value: "Complete",
      // twin.history is counted at the replay clock, which can be later than the forecast: say so
      note: v60 === undefined ? undefined
        : `${plural(v60, "reading")} in the hour before the replay clock (about 12 expected)` });
  }

  const usesProfile = modelUsesProfile(f?.model_version ?? twin?.model_version);
  if (usesProfile === true) {
    out.push(codes.has("profile_unavailable")
      ? { label: "Health record (profile)", tone: "attention", value: "A value is missing or not yet known, so the model abstained",
        note: "The fusion model was trained on complete profiles only." }
      : f && !abstained
        ? { label: "Health record (profile)", tone: "ok", value: "Every value the model reads was known at this time" }
        : { label: "Health record (profile)", tone: "neutral", value: "Checked with each forecast; the model abstains if a value is missing" });
  } else if (usesProfile === false) {
    out.push({ label: "Health record (profile)", tone: "neutral", value: "Not an input of this model" });
  }

  const p = twin?.personalization ?? f?.personalization;
  if (!p || !p.enabled) {
    out.push({ label: "Patient correction", tone: "neutral", value: "Off for this model" });
  } else {
    const need = p.horizons[0]?.min_required;
    const value = p.status === "active"
      ? <>{p.horizons.map((h) => `${h.horizon_minutes} min ${signed(h.correction_mg_dl)}`).join(" · ")} mg/dL</>
      : p.status === "reset_after_gap" ? "Reset after a data gap; learning again"
        : `Warming up · ${p.horizons.map((h) => `${h.matured_residuals} of ${h.min_required}`).join(" / ") || "0"} observed forecast errors`;
    out.push({ label: "Patient correction", tone: p.status === "active" ? "ok" : "neutral", value,
      note: `Learns only from forecasts whose outcome was observed${need ? `, needs ${need}` : ""}; capped at ±25 mg/dL; resets after a 3-hour gap.` });
  }

  if (alerts && !alerts.rule_available) {
    out.push({ label: "Warnings", tone: "neutral", value: "No validated warning rule is loaded for this mode" });
  } else if (alerts) {
    const n = alerts.items.length;
    const by = (s: string) => alerts.items.filter((a) => a.outcome.status === s).length;
    const pending = by("pending");
    const parts = [by("onset_observed") && plural(by("onset_observed"), "onset"),
      by("no_onset_observed") && plural(by("no_onset_observed"), "false alarm"),
      pending && `${pending} pending`, by("unknown") && `${by("unknown")} unknown (gap)`].filter(Boolean);
    // the engine replays the whole recording, so the list starts at the recording, not at the period the replay opened on
    const test = segments?.find((sg) => sg.name === "test");
    const inTest = test ? alerts.items.filter((a) => ms(a.issued_at) >= ms(test.start_at) && ms(a.issued_at) < ms(test.end_at)).length : null;
    const scope = inTest === null ? "" : inTest === n ? "All issued in the final test period. "
      : `${inTest} of them in the final test period; the rest fall in the training, validation or calibration periods. `;
    out.push(n === 0
      ? { label: "Warnings", tone: "ok", value: "None issued since the start of this recording" }
      : { label: "Warnings", tone: pending ? "attention" : "ok",
        value: `${plural(n, "research warning")} since the start of this recording: ${parts.join(" · ")}`,
        note: `${scope}Each stays “Outcome pending” until it can be judged, then counts as an onset or a false alarm.` });
  }

  const est = f?.estimates.find((e) => e.interval_level != null);
  if (f && !abstained) {
    const cov = measuredCoverage(report, f.model_version);
    const target = est?.interval_level as number;
    const under = !!cov && cov.byHorizon.some((b) => b.coverage != null && b.coverage < target);
    const where = cov ? `final test period, ${cov.byHorizon.map((b) => b.horizon).join(" / ")} min` : "";
    out.push(!est || est.interval_status !== "calibrated"
      ? { label: "Prediction range", tone: "attention", value: "Unavailable for this forecast" }
      : under && cov
        ? { label: "Prediction range", tone: "attention",
          value: `Under target: ${cov.byHorizon.map((b) => fmtPct(b.coverage, 1)).join(" / ")} measured vs ${fmtPct(target)} target`,
          note: `Measured on the ${where}: the ranges are narrower than they should be. Coverage varies by participant; no guarantee.` }
        : { label: "Prediction range", tone: "ok", value: `${fmtPct(target)} target coverage`,
          note: cov ? `Measured on the ${where}: ${cov.byHorizon.map((b) => fmtPct(b.coverage, 1)).join(" / ")}; no guarantee.`
            : f.mode === "synthetic_demo" ? "The synthetic model has no measured coverage on recorded data."
              : "No measured coverage for this model in the evaluation report." });
  }
  return out;
}

export function Guardrails({ session, latest, twin, alerts, report, segments, more }: {
  session: ReplaySession; latest?: LatestForecast; twin?: TwinState; alerts?: AlertList; report?: EvaluationReport;
  /** the participant's evaluation segments, to say how many warnings fall in the final test period */
  segments?: EvaluationSegment[] | null;
  /** a link to the full list, rendered under the checks */
  more?: ReactNode;
}) {
  const f = latest?.forecast;
  return (
    <section className="inspector__block" aria-labelledby="guard-title">
      <h2 className="inspector__title" id="guard-title">Guardrails</h2>
      <p className="guards__lede">
        {f ? <>Checks applied at the latest forecast, issued <span className="num">{replayTime(f.as_of, { day: false })}</span>.</>
          : <>Checks applied before any forecast is shown.</>}
      </p>
      <ul className="guards">
        {guardChecks(session, latest, twin, alerts, report, segments).map((g) => {
          const Icon = GUARD_ICON[g.tone];
          return (
            <li key={g.label} className={`guard guard--${g.tone}`}>
              <Icon size={15} aria-hidden strokeWidth={1.9} className="guard__icon" />
              <div>
                <p className="guard__label"><span className="visually-hidden">{GUARD_SR[g.tone]}</span>{g.label}</p>
                <p className="guard__value">{g.value}</p>
                {g.note && <p className="guard__note">{g.note}</p>}
              </div>
            </li>
          );
        })}
      </ul>
      {more}
    </section>
  );
}

/* ================================================================ Warnings (below the chart) */
export function WarningHistory({ alerts, revision, sessionKey, participant, onSave }: {
  alerts?: AlertList;
  /** the session's current revision: a warning from another revision is never submitted */
  revision?: number;
  /** session id + revision: unsaved review state is dropped when it changes */
  sessionKey: string;
  participant: string;
  onSave: (a: Alert, note: string | undefined) => Promise<unknown>;
}) {
  const [showAll, setShowAll] = useState(false);
  const [reviewing, setReviewing] = useState<Alert | null>(null);
  const items = alerts?.items ?? [];
  // the open review's warning in the CURRENT session and revision; after a rewind, reset or participant switch it is
  // undefined and the dialog says nothing was saved instead of submitting the old warning
  const current = reviewing ? items.find((x) => x.alert_id === reviewing.alert_id && x.session_id === reviewing.session_id
    && x.session_revision === revision && `${x.session_id}:${x.session_revision}` === sessionKey) : undefined;
  const shown = items.slice(0, showAll ? items.length : 4);
  return (
    <section className="lower__col" aria-labelledby="warnings-title">
      <h2 className="lower__title" id="warnings-title">Warnings{items.length ? <span className="lower__count"> · {items.length}</span> : null}</h2>
      {!alerts ? <Skeleton h={60} /> : items.length === 0 ? (
        <p className="lower__empty">{alerts.rule_available ? "No research warning issued in this replay so far." : "No warning rule is loaded for this mode."}</p>
      ) : (
        <>
          <ul className="warn-list">
            {shown.map((a) => (
              <li key={a.alert_id} className="warn">
                <div className="warn__top">
                  <span className="warn__time num">{replayTime(a.issued_at)}</span>
                  <Outcome a={a} />
                </div>
                <p className="warn__meta">
                  First warning {replayTime(a.issued_at, { day: false })} · last supporting forecast {replayTime(a.last_supported_at, { day: false })}
                </p>
                <WarningTrigger a={a} />
                <div className="warn__ack">
                  {a.acknowledgement.acknowledged ? <SavedReview a={a} /> : (
                    <Button size="sm" variant="quiet" onClick={() => setReviewing(a)} aria-haspopup="dialog"
                      aria-label={`Mark warning issued ${replayTime(a.issued_at)} as reviewed`}>Mark as reviewed</Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {items.length > 4 && (
            <Button size="sm" variant="quiet" onClick={() => setShowAll((x) => !x)} aria-expanded={showAll}>
              {showAll ? "Show fewer" : `Show all ${items.length} warnings`}
            </Button>
          )}
          <WarningReviewDialog alert={reviewing} current={current} revision={revision} participant={participant}
            trigger={current ?? reviewing ? <WarningTrigger a={(current ?? reviewing)!} /> : null}
            outcome={current ?? reviewing ? <Outcome a={(current ?? reviewing)!} /> : null}
            onSave={onSave} onClose={() => setReviewing(null)} />
          <p className="lower__note">“Marked as reviewed” and its optional note are kept in this local research session; no message is sent. Forecast lead counts
            from the earliest warning whose own 60-minute horizon contained the onset; “first warning … before” is the whole episode,
            which can be longer than the horizon.</p>
        </>
      )}
    </section>
  );
}

/** Which forecast fired the warning: the highest forecast within its horizon, against the trigger level. */
function WarningTrigger({ a }: { a: Alert }) {
  const preds = Object.entries(a.evidence.predicted_mg_dl)
    .map(([h, v]) => ({ h: Number(h), v }))
    .filter((p): p is { h: number; v: number } => p.v != null && p.h <= a.horizon_minutes)
    .sort((x, y) => x.h - y.h);
  if (!preds.length) return null;
  const top = preds.reduce((m, p) => (p.v > m.v ? p : m));
  const trigger = a.evidence.threshold != null ? EPISODE_MG_DL + a.evidence.threshold : null;
  const others = preds.filter((p) => p !== top);
  return (
    <p className="warn__meta">
      Fired by the {top.h}-min forecast <span className="num">{fmtGlucose(top.v)} mg/dL</span>
      {trigger != null && <> ≥ <span className="num">{fmtGlucose(trigger)}</span> trigger</>}
      {others.map((p) => <span key={p.h}> · {p.h}-min <span className="num">{fmtGlucose(p.v)}</span></span>)}
    </p>
  );
}

function Outcome({ a }: { a: Alert }) {
  const o = a.outcome;
  if (o.status === "onset_observed") {
    const episode = o.episode_start_to_onset_minutes ?? o.lead_time_minutes;
    return (
      <span className="warn__outcome">
        Onset {o.onset_at ? replayTime(o.onset_at, { day: false }) : ""}
        {o.qualified_lead_minutes != null ? <> · forecast lead {Math.round(o.qualified_lead_minutes)} min</> : null}
        {episode != null && (o.qualified_lead_minutes == null || Math.round(episode) !== Math.round(o.qualified_lead_minutes))
          ? <> · first warning {Math.round(episode)} min before</> : null}
      </span>
    );
  }
  if (o.status === "no_onset_observed") return <span className="warn__outcome">No onset (false alarm)</span>;
  if (o.status === "unknown") return <span className="warn__outcome warn__outcome--muted">Outcome unknown (gap)</span>;
  return <StatusLabel tone="attention">Outcome pending</StatusLabel>;
}

/* ================================================================ Observations (below the chart) */
export function RecentObservations({ events, clock, loaded = true }: { events: ObservationEvent[]; clock: number; loaded?: boolean }) {
  const vis = events.filter((e) => visibleAt(e, clock)).sort((a, b) => ms(b.observed_at) - ms(a.observed_at));
  const glucose = vis.filter((e) => e.kind === "glucose").slice(0, 4);
  const activity = vis.filter((e) => e.kind === "activity").slice(0, 1);
  const meals = vis.filter((e) => e.kind === "meal" && clock - ms(e.observed_at) <= 6 * 3600_000).slice(0, 2);
  const rows = [...glucose, ...activity, ...meals].sort((a, b) => ms(b.observed_at) - ms(a.observed_at));
  return (
    <section className="lower__col" aria-labelledby="obs-title">
      <h2 className="lower__title" id="obs-title">Observations</h2>
      {rows.length === 0 ? (
        <p className="lower__empty" role="status">{loaded ? "No observations released yet." : "Loading released observations…"}</p>
      ) : (
        <ul className="obs-list">
          {rows.map((e) => (
            <li key={e.event_id}>
              <time dateTime={e.observed_at} className="num">{replayTime(e.observed_at, { day: false })}</time>
              <span className="obs-list__kind">{e.kind === "glucose" ? "Glucose" : e.kind === "meal" ? "Meal" : "Activity"}</span>
              <span>{describe(e)}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="lower__note">Meal records are study estimates shown for context; the forecasting model does not use them.</p>
    </section>
  );
}

function describe(e: ObservationEvent): string {
  const v = e.values;
  if (e.kind === "glucose") return `${fmtGlucose(v.value as number)} mg/dL${e.quality === "suspect" ? " (sensor limit, flagged)" : ""}`;
  if (e.kind === "meal") {
    const late = ms(e.available_at) > ms(e.observed_at) ? ` · logged ${replayTime(e.available_at, { day: false })}` : "";
    return `${v.meal_type ?? "Meal"}${v.carbohydrate !== null && v.carbohydrate !== undefined ? ` · ~${Math.round(v.carbohydrate as number)} g carbohydrate` : ""}${late}`;
  }
  const parts = [];
  if (v.heart_rate !== null && v.heart_rate !== undefined) parts.push(`HR ${Math.round(v.heart_rate as number)} bpm`);
  if (v.mets !== null && v.mets !== undefined) parts.push(`${(v.mets as number).toFixed(1)} METs`);
  return `5-min summary${parts.length ? ` · ${parts.join(" · ")}` : ""}`;
}

/* ================================================================ Model details (below the chart) */
export function ModelDetails({ twin, latest, publicDemo = false }: { twin?: TwinState; latest?: LatestForecast; publicDemo?: boolean }) {
  const p = twin?.personalization;
  const f = latest?.forecast;
  const synthetic = f?.mode === "synthetic_demo" || twin?.model_version?.startsWith("synthetic") === true;
  const status = !p || !p.enabled ? "Unavailable" : p.status === "active" ? "Active" : p.status === "reset_after_gap" ? "Reset after a data gap" : "Warming up";
  return (
    <section className="lower__col" aria-labelledby="model-title">
      <h2 className="lower__title" id="model-title">Model details</h2>
      <dl className="dl dl--compact">
        <dt>Model</dt><dd>{twin?.model_family ? `${twin.model_family === "lightgbm" ? "LightGBM" : twin.model_family}` : "Unavailable"}
          {publicDemo && synthetic && <span className="table__sub">Synthetic demonstration model, fitted on fictional data — not the evaluated real-data fusion model</span>}</dd>
        <dt>Version</dt><dd className="wrap-id">{twin?.model_version ?? "—"}</dd>
        <dt>Patient adaptation</dt><dd>{status}</dd>
        {p?.enabled && p.horizons.map((h) => (
          // the twin's state at the replay clock: it applies to the NEXT forecast; the latest forecast's own population
          // value and the correction it used are in "How the twin reached this forecast" (never mixed here)
          <div key={h.horizon_minutes} style={{ display: "contents" }}>
            <dt>{h.horizon_minutes}-min correction now</dt>
            <dd className="num">
              {h.correction_mg_dl !== null ? `${h.correction_mg_dl >= 0 ? "+" : "−"}${Math.abs(h.correction_mg_dl).toFixed(1)} mg/dL` : "—"}
              <span className="table__sub">from {h.matured_residuals} observed outcomes (needs {h.min_required}); applies to the next forecast</span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="lower__note">Corrections learn only from earlier forecasts whose outcomes were already observed. Model weights are never refit during replay.
        {f && <> The latest forecast’s population value and the correction it used are shown above, under “How the twin reached this forecast”.</>}</p>
    </section>
  );
}
