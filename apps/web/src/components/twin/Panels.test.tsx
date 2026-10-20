import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TwinState } from "@/api/types";
import { forecast, glucose, latest, session } from "@/test/fixtures";
import { GlucoseSummary, RecentObservations, ReviewStatus } from "./Panels";

const twin = (valid60: number) => ({ history: { valid_samples_60: valid60, lookback_minutes: 60, available_minutes: 60, valid_samples_lookback: valid60, latest_glucose: null } }) as unknown as TwinState;

describe("summary group", () => {
  it("states that a range is unavailable instead of drawing one", () => {
    render(<GlucoseSummary session={session()} events={[glucose("g", "2000-01-03T09:57:00Z", 150)]}
      latest={latest(forecast({}, false))} loading={false} />);
    expect(screen.getAllByText("Prediction range unavailable")).toHaveLength(2);
  });

  it("labels a range with its target coverage, never as a confidence score", () => {
    render(<GlucoseSummary session={session()} events={[glucose("g", "2000-01-03T09:57:00Z", 150)]}
      latest={latest(forecast())} loading={false} />);
    expect(screen.getByText("Prediction range · target coverage 80%")).toBeInTheDocument();
    expect(screen.queryByText(/80% interval|confidence/i)).toBeNull();
  });

  it("keeps the layout and explains an unavailable forecast once — never zero, never 'low risk'", () => {
    render(<GlucoseSummary session={session()} events={[]} latest={latest(null)} loading={false} />);
    expect(screen.getAllByText("Not available")).toHaveLength(2);
    expect(screen.getByText(/Unavailable is not the same as low risk\./)).toBeInTheDocument();
    expect(screen.queryByText(/^0$/)).toBeNull();
    expect(screen.getByText("No reading yet")).toBeInTheDocument();
  });

  it("gives the sparse-history reason with the actual reading count", () => {
    const f = forecast({ quality: { status: "insufficient", reasons: [{ code: "sparse_recent_history", message: "Too few glucose observations in the last 60 minutes." }] } });
    render(<GlucoseSummary session={session()} events={[glucose("g", "2000-01-03T09:57:00Z", 195)]}
      latest={latest(f, { availability: "not_ready", reasons: [{ code: "forecast_insufficient", message: "The twin abstained at the latest origin." }] })}
      twin={twin(2)} loading={false} />);
    expect(screen.getByText(/2 readings in the last hour; more recent history is required\./)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Current glucose" })).toHaveTextContent("195"); // the reading stays visible
  });

  it("says the model is unavailable instead of blaming sensor history", () => {
    render(<GlucoseSummary session={session()} events={[]} loading={false}
      latest={latest(null, { reasons: [{ code: "no_forecast_yet", message: "x" }, { code: "model_unavailable", message: "No verified forecasting model artifact is loaded for this mode." }] })} />);
    expect(screen.getByText("Model unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/readings in the last hour/)).toBeNull();
  });

  it("shows loading — not 'no reading released' — while released events are still being fetched", () => {
    render(<GlucoseSummary session={session()} events={[]} latest={latest(null)} loading={false} eventsLoaded={false} />);
    expect(screen.queryByText("No reading yet")).toBeNull();
    render(<RecentObservations events={[]} clock={Date.parse(session().clock_at)} loaded={false} />);
    expect(screen.getByText("Loading released observations…")).toBeInTheDocument();
    expect(screen.queryByText("No observations released yet.")).toBeNull();
  });

  it("labels a stale forecast and stale reading", () => {
    const s = session({ freshness: { latest_glucose_at: "2000-01-03T09:30:00Z", latest_glucose_age_minutes: 30,
      stale_threshold_minutes: 15, status: "stale" } });
    render(<GlucoseSummary session={s} events={[glucose("g", "2000-01-03T09:30:00Z", 150)]}
      latest={latest(forecast({ as_of: "2000-01-03T09:30:00Z" }), { availability: "stale", age_minutes: 30 })} loading={false} />);
    expect(screen.getAllByText("Stale").length).toBeGreaterThan(0);
    expect(screen.getByText(/Stale · 30 min old/)).toBeInTheDocument();
    expect(screen.getByText("Forecast out of date")).toBeInTheDocument();
  });

  it("does not display a forecast issued after the replay clock", () => {
    render(<GlucoseSummary session={session()} events={[]} latest={latest(forecast({ as_of: "2000-01-03T11:00:00Z" }))}
      loading={false} />);
    expect(screen.queryByText("166")).toBeNull();
    expect(screen.getAllByText("Not available")).toHaveLength(2);
  });
});

describe("review status", () => {
  it("shows the warning score as a margin, not a probability", () => {
    render(<ReviewStatus latest={latest(forecast())} />);
    expect(screen.getByText("No warning issued")).toBeInTheDocument();
    expect(screen.getByText(/not a probability/)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.queryByText(/safe/i)).toBeNull();
  });

  it("distinguishes an already-high state from a forecast warning", () => {
    render(<ReviewStatus latest={latest(forecast({ episode_state: "in_episode" }))} />);
    expect(screen.getByText("Already-high glucose state")).toBeInTheDocument();
    expect(screen.getByText(/observation, not a forecast/)).toBeInTheDocument();
  });

  it("reports insufficient information when the twin abstains", () => {
    render(<ReviewStatus latest={latest(null)} />);
    expect(screen.getByText("Insufficient information")).toBeInTheDocument();
  });

  const fired = (mode: "dataset_replay" | "synthetic_demo", margin: number, fire = true) => forecast({
    mode,
    estimates: [[30, 172], [60, 164]].map(([h, v]) => ({ horizon_minutes: h, target_at: "2000-01-03T10:57:00Z", predicted_mg_dl: v,
      lower_mg_dl: null, upper_mg_dl: null, interval_level: null, interval_status: "unavailable", components: null })),
    event_risk: [30, 60].map((h) => ({ horizon_minutes: h, probability: null, score: -8, score_kind: "forecast_margin_mg_dl",
      score_description: "", state: "eligible", alert_threshold: h === 60 ? margin : null, alert_fired: fire && h === 60 })),
  } as never);

  it("names the forecast that fired a warning and the trigger level, not 'above 180'", () => {
    render(<ReviewStatus latest={latest(fired("dataset_replay", -10))} />);
    expect(screen.getByText("Warning issued")).toBeInTheDocument();
    const text = screen.getByText(/reached the 170 mg\/dL warning trigger/).textContent ?? "";
    expect(text).toContain("the 30-minute forecast, 172 mg/dL");
    expect(text).toContain("10 mg/dL below the 180 mg/dL episode threshold (chosen on validation data)");
    expect(text).toContain("so warnings come earlier");
    expect(screen.queryByText(/sustained episode above 180/)).toBeNull();
    expect(screen.getByText(/Highest forecast within 60 min/)).toHaveTextContent("172 mg/dL (30-min) · warning trigger 170 mg/dL");
  });

  it("does not claim a validation-chosen or early trigger for the synthetic model", () => {
    render(<ReviewStatus latest={latest(fired("synthetic_demo", 0))} />);
    const text = screen.getByText(/warning trigger\. The rule/).textContent ?? "";
    expect(text).toContain("at the 180 mg/dL episode threshold");
    expect(text).not.toContain("validation");
    expect(text).not.toContain("earlier");
  });

  it("keeps an earlier warning visible as awaiting its outcome when the latest forecast does not fire", () => {
    const alerts = { items: [{ state: "open", issued_at: "2000-01-03T09:15:00Z" }], rule_available: true } as never;
    render(<ReviewStatus latest={latest(fired("dataset_replay", -10, false))} alerts={alerts} />);
    expect(screen.getByText("Warning awaiting outcome")).toBeInTheDocument();
    expect(screen.getByText(/is below the 170 mg\/dL trigger/)).toBeInTheDocument();
  });

  it("reports a missing model separately from abstention", () => {
    render(<ReviewStatus latest={latest(null, { reasons: [{ code: "model_unavailable", message: "x" }] })} />);
    expect(screen.getByText("Model unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Insufficient information")).toBeNull();
  });
});

describe("warning history", () => {
  const alert = (outcome: Record<string, unknown>) => ({
    schema_version: "1.0", alert_id: "a1", session_id: "s1", patient_id: "SYN-A", session_revision: 1,
    issued_at: "2000-01-03T08:00:00Z", last_supported_at: "2000-01-03T09:40:00Z", horizon_minutes: 60,
    rule_version: "new-high-warning-v1", model_version: "m", kind: "predicted_new_high_episode", title: "t",
    evidence: { forecast_id: "f", score: 2, score_kind: "forecast_margin_mg_dl", threshold: 0, latest_glucose_mg_dl: 170,
      predicted_mg_dl: { "60": 182 }, explanation_codes: [] },
    supporting_forecast_ids: ["f"], state: "closed", outcome,
    acknowledgement: { acknowledged: false, meaning: "local" },
  });

  it("keeps the forecast lead and the whole-episode duration apart", async () => {
    const { WarningHistory } = await import("./Panels");
    const list = { schema_version: "1.0", session_id: "s1", session_revision: 1, clock_at: "2000-01-03T11:00:00Z",
      rule_available: true, rule_description: null,
      items: [alert({ status: "onset_observed", onset_at: "2000-01-03T10:35:00Z", lead_time_minutes: 155,
        episode_start_to_onset_minutes: 155, qualified_lead_minutes: 55 })] };
    render(<WarningHistory alerts={list as never} onAck={() => {}} ackPending={false} />);
    expect(screen.getByText(/forecast lead 55 min/)).toBeInTheDocument();
    expect(screen.getByText(/first warning 155 min before/)).toBeInTheDocument();
  });

  it("shows which forecast fired each warning against the trigger", async () => {
    const { WarningHistory } = await import("./Panels");
    const a = alert({ status: "pending" });
    const list = { schema_version: "1.0", session_id: "s1", session_revision: 1, clock_at: "2000-01-03T11:00:00Z",
      rule_available: true, rule_description: null,
      items: [{ ...a, evidence: { ...a.evidence, threshold: -10, score: -8, predicted_mg_dl: { "30": 172, "60": 164 } } }] };
    render(<WarningHistory alerts={list as never} onAck={() => {}} ackPending={false} />);
    expect(screen.getByText(/Fired by the 30-min forecast/)).toHaveTextContent("Fired by the 30-min forecast 172 mg/dL ≥ 170 trigger · 60-min 164");
  });
});

describe("guardrails", () => {
  const FUSION = "lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion";
  const outcomes = (...st: string[]) => ({ rule_available: true, items: st.map((s) => ({ state: "closed", outcome: { status: s } })) }) as never;

  it("passes a fresh, complete forecast and states that the synthetic model has no measured coverage", async () => {
    const { Guardrails } = await import("./Panels");
    render(<Guardrails session={session()} latest={latest(forecast())} twin={twin(12)} alerts={outcomes()} />);
    expect(screen.getByText(/Fresh · 3 min old/)).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByText("12 readings in the hour before the replay clock (about 12 expected)")).toBeInTheDocument();
    expect(screen.getByText("None issued since the start of this recording")).toBeInTheDocument();
    expect(screen.getByText("80% target coverage")).toBeInTheDocument();
    expect(screen.getByText("The synthetic model has no measured coverage on recorded data.")).toBeInTheDocument();
    expect(screen.queryByText("Health record (profile)")).toBeNull(); // the synthetic model's inputs are not encoded in its version
  });

  it("shows the fusion model's profile gate and the twin's reasons when it abstains, and no range", async () => {
    const { Guardrails } = await import("./Panels");
    const f = forecast({ model_version: FUSION, mode: "dataset_replay", quality: { status: "insufficient", reasons: [
      { code: "profile_unavailable", message: "A baseline profile value used by this model is missing or not yet available." }] } });
    render(<Guardrails session={session()} latest={latest(f, { availability: "not_ready" })} />);
    expect(screen.getByText("Abstained: no forecast is shown")).toBeInTheDocument();
    expect(screen.getByText("A baseline profile value used by this model is missing or not yet available.")).toBeInTheDocument();
    expect(screen.getByText("A value is missing or not yet known, so the model abstained")).toBeInTheDocument();
    expect(screen.queryByText("Prediction range")).toBeNull();
  });

  it("confirms the profile check, states the correction cap and counts warning outcomes", async () => {
    const { Guardrails } = await import("./Panels");
    const f = forecast({ model_version: FUSION, mode: "dataset_replay", quality: { status: "degraded", reasons: [
      { code: "recent_gap", message: "A gap longer than 15 minutes occurred in the last 60 minutes." }] } });
    const tw = { ...twin(9), model_version: FUSION, personalization: { enabled: true, status: "active", state_version: 3,
      horizons: [{ horizon_minutes: 30, matured_residuals: 40, min_required: 6, correction_mg_dl: 2.14 },
        { horizon_minutes: 60, matured_residuals: 34, min_required: 6, correction_mg_dl: -3 }] } } as unknown as TwinState;
    render(<Guardrails session={session()} latest={latest(f)} twin={tw} alerts={outcomes("onset_observed", "no_onset_observed", "pending")} />);
    expect(screen.getByText("Degraded: forecast shown with a flag")).toBeInTheDocument();
    expect(screen.getByText("Every value the model reads was known at this time")).toBeInTheDocument();
    expect(screen.getByText("30 min +2.1 · 60 min −3.0 mg/dL")).toBeInTheDocument();
    expect(screen.getByText(/needs 6; capped at ±25 mg\/dL; resets after a 3-hour gap/)).toBeInTheDocument();
    expect(screen.getByText("3 research warnings since the start of this recording: 1 onset · 1 false alarm · 1 pending")).toBeInTheDocument();
  });

  it("flags ranges whose measured coverage is under target instead of ticking them", async () => {
    const { Guardrails } = await import("./Panels");
    const report = { status: "completed", experiment_id: "exp", protocol: { model_version: FUSION, intervals: { level: 0.8 } },
      forecast_results: [{ selected_for_serving: true, model_label: "LightGBM", personalization: "adaptive" }],
      interval_results: [[30, 0.742], [60, 0.74]].map(([h, c]) => ({ split: "test", model_label: "LightGBM (adaptive)", horizon_minutes: h,
        empirical_coverage: { value: c }, per_patient_coverage_min: 0.5, per_patient_coverage_max: 0.9, interval_level: 0.8 })) } as never;
    render(<Guardrails session={session()} latest={latest(forecast({ model_version: FUSION, mode: "dataset_replay" }))} report={report} />);
    expect(screen.getByText("Under target: 74.2% / 74.0% measured vs 80% target")).toBeInTheDocument();
    expect(screen.getByText(/final test period, 30 \/ 60 min: the ranges are narrower than they should be/)).toBeInTheDocument();
    expect(screen.getByText("Under target: 74.2% / 74.0% measured vs 80% target").closest("li")).toHaveClass("guard--attention");
  });

  it("says how many warnings fall in the final test period, so earlier ones are not read as test results", async () => {
    const { Guardrails } = await import("./Panels");
    const alerts = { rule_available: true, items: ["2000-01-05T10:00:00Z", "2000-01-06T10:00:00Z", "2000-01-09T10:00:00Z"]
      .map((t) => ({ state: "closed", issued_at: t, outcome: { status: "no_onset_observed" } })) } as never;
    const segments = [{ name: "training", start_at: "2000-01-03T00:00:00Z", end_at: "2000-01-08T00:00:00Z" },
      { name: "test", start_at: "2000-01-08T00:00:00Z", end_at: "2000-01-12T00:00:00Z" }] as never;
    render(<Guardrails session={session()} latest={latest(forecast())} alerts={alerts} segments={segments} />);
    expect(screen.getByText("3 research warnings since the start of this recording: 3 false alarms")).toBeInTheDocument();
    expect(screen.getByText(/^1 of them in the final test period; the rest fall in the training, validation or calibration periods\./)).toBeInTheDocument();
  });

  it("lists the eleven guardrails on the evidence page", async () => {
    const { SafetyGuardrails, GUARDRAILS } = await import("@/components/evidence/SafetyGuardrails");
    render(<SafetyGuardrails />);
    expect(GUARDRAILS).toHaveLength(11);
    expect(screen.getByRole("heading", { name: "Safety guardrails" })).toBeInTheDocument();
    expect(screen.getByText("Abstains instead of guessing")).toBeInTheDocument();
    expect(screen.getByText(/capped at ±25 mg\/dL and resets after a 3-hour gap/)).toBeInTheDocument();
  });
});
