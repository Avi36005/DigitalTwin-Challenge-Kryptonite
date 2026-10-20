import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { forecast, latest } from "@/test/fixtures";
import { TwinExplanation } from "./TwinExplanation";

describe("twin explanation", () => {
  it("shows population, correction and the API's final estimate per horizon, with the correction's bound", () => {
    const f = forecast({
      personalization: { enabled: true, status: "warming_up", policy_id: "p", state_version: 1, cap_mg_dl: 25, reset_gap_minutes: 180,
        horizons: [{ horizon_minutes: 30, matured_residuals: 2, min_required: 6, correction_mg_dl: 0, consumed_forecast_ids: [] }] },
    });
    render(<TwinExplanation latest={latest(f)} clockAt="2000-01-03T10:00:00Z" />);
    const table = screen.getByRole("table", { name: "Forecast components" });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("30 min160 mg/dL+0.0 mg/dL163 mg/dL");
    expect(screen.getByText(/Warming up: no correction until enough outcomes are observed/)).toBeInTheDocument();
    expect(screen.getByText(/30 min: 2 observed outcomes \(needs 6\)/)).toBeInTheDocument();
    expect(screen.getByText(/Bounded at ±25 mg\/dL; cleared after a 3 h gap/)).toBeInTheDocument();
    expect(screen.getByText(/No measured coverage is reported for this exact model/)).toBeInTheDocument();
  });

  it("says a stale forecast is stale and explains nothing when the twin abstained", () => {
    const { rerender } = render(<TwinExplanation latest={latest(forecast(), { availability: "stale", age_minutes: 40 })} clockAt="2000-01-03T10:00:00Z" />);
    expect(screen.getByText(/40 min before the replay clock \(stale\)/)).toBeInTheDocument();
    rerender(<TwinExplanation latest={latest(null)} clockAt="2000-01-03T10:00:00Z" />);
    expect(screen.getByText(/No forecast is shown at this replay time/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Forecast components" })).toBeNull();
  });

  it("never explains a forecast issued after the replay clock", () => {
    render(<TwinExplanation latest={latest(forecast({ as_of: "2000-01-03T10:05:00Z" }))} clockAt="2000-01-03T10:00:00Z" />);
    expect(screen.queryByRole("table", { name: "Forecast components" })).toBeNull();
  });
});
