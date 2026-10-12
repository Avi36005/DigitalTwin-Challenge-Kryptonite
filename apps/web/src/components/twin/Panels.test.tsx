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
});
