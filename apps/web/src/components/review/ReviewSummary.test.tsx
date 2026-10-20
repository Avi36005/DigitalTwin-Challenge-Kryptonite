import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { Alert, AlertList, SessionProfile, TwinState } from "@/api/types";
import { forecast, glucose, latest, session } from "@/test/fixtures";
import { ReviewSummary } from "./ReviewSummary";

const CUT = "2000-01-03T10:00:00Z";
const alerts = (items: Alert[] = [], clock = CUT): AlertList =>
  ({ schema_version: "1.0", session_id: "s1", session_revision: 1, clock_at: clock, rule_available: true, rule_description: null, items }) as AlertList;
const profile = { schema_version: "1.0", session_id: "s1", patient_id: "SYN-A", session_revision: 1, as_of: CUT,
  cohort: { label: "Fictional" }, values: [] } as unknown as SessionProfile;
const twin = { schema_version: "1.0", session_id: "s1", patient_id: "SYN-A", session_revision: 1, as_of: CUT, model_version: "synthetic-demo",
  personalization: { enabled: false, status: "disabled", state_version: 0, horizons: [] },
  history: { valid_samples_60: 12 } } as unknown as TwinState;
const noted = { schema_version: "1.0", alert_id: "a1", session_id: "s1", patient_id: "SYN-A", session_revision: 1,
  issued_at: "2000-01-03T09:00:00Z", last_supported_at: "2000-01-03T09:00:00Z", horizon_minutes: 60, rule_version: "r",
  model_version: "m", kind: "predicted_new_high_episode", title: "t",
  evidence: { forecast_id: "f", score: 5, score_kind: "x", threshold: -10, latest_glucose_mg_dl: 150, predicted_mg_dl: { "60": 185 }, explanation_codes: [] },
  supporting_forecast_ids: [], state: "closed", outcome: { status: "no_onset_observed" },
  acknowledgement: { acknowledged: true, acknowledged_at: "2026-10-20T10:00:00Z", note: "<b>bold?</b> trend checked", meaning: "local" } } as unknown as Alert;

function props(clock = CUT, over: Record<string, unknown> = {}) {
  return {
    session: session({ clock_at: clock }), latest: { data: latest(forecast(), { clock_at: clock }) },
    alerts: { data: alerts([noted], clock) }, twin: { data: twin }, profile: { data: { ...profile, as_of: clock } },
    events: [glucose("g1", "2000-01-03T09:55:00Z", 150)], eventsLoaded: true, ...over,
  };
}

describe("ReviewSummary", () => {
  beforeAll(() => { // jsdom has no <dialog> methods
    const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
    if (typeof proto.close !== "function") proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); };
    // jsdom cannot navigate to a blob URL; the download itself is checked through the Blob
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  it("freezes the report: a playing replay does not change the open copy", () => {
    const { rerender } = render(<ReviewSummary {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "Review summary" }));
    expect(screen.getAllByText("Day 1 · 10:00 (replay time)").length).toBeGreaterThan(0);
    rerender(<ReviewSummary {...props("2000-01-03T10:05:00Z")} />);
    expect(screen.getAllByText("Day 1 · 10:00 (replay time)").length).toBeGreaterThan(0);
    expect(screen.getByText(/The replay has moved to Day 1 · 10:05 since this copy/)).toBeInTheDocument();
  });

  it("renders a saved note as text, never as HTML", () => {
    const { container } = render(<ReviewSummary {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "Review summary" }));
    expect(screen.getAllByText("<b>bold?</b> trend checked").length).toBeGreaterThan(0);
    expect(container.ownerDocument.querySelector(".review-doc b")).toBeNull();
  });

  it("refuses to create a copy while data for the replay time is still loading, with the reason", () => {
    render(<ReviewSummary {...props(CUT, { eventsLoaded: false })} />);
    fireEvent.click(screen.getByRole("button", { name: "Review summary" }));
    expect(screen.getByText(/Summary not created\./)).toBeInTheDocument();
    expect(screen.getByText(/Loading the released observations/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Print/ })).toBeDisabled();
  });

  it("discards the copy after a rewind and on another participant", () => {
    const { rerender } = render(<ReviewSummary {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "Review summary" }));
    rerender(<ReviewSummary {...props(CUT, { session: session({ revision: 2 }) })} />);
    expect(screen.getByText(/rewound or reset after the last summary was created/)).toBeInTheDocument();
    expect(screen.queryByText("Day 1 · 10:00 (replay time)")).toBeNull();
    rerender(<ReviewSummary {...props(CUT, { session: session({ id: "s2" }) })} />);
    expect(screen.queryByRole("article", { name: "Review summary report" })).toBeNull();
  });

  it("downloads exactly the frozen snapshot as JSON", async () => {
    const blobs: Blob[] = [];
    const create = vi.fn((b: Blob) => { blobs.push(b); return "blob:x"; });
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() });
    render(<ReviewSummary {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "Review summary" }));
    fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));
    const json = JSON.parse(await blobs[0].text());
    expect(json.replay_cutoff).toBe(CUT);
    expect(json.warnings.items[0].note).toBe("<b>bold?</b> trend checked");
    expect(json.disclaimer).toBe("Research replay review — not a medical report");
  });
});
