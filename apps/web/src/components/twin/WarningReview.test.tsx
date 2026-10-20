import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, type Mock, vi } from "vitest";
import type { Alert, AlertList } from "@/api/types";
import { WarningHistory } from "./Panels";
import { NOTE_MAX } from "./WarningReview";

// jsdom has no modal <dialog>: open/close by the attribute, as the Dialog primitive's own fallback does
beforeAll(() => {
  const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
  if (typeof proto.showModal !== "function") proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
  if (typeof proto.close !== "function") {
    proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); };
  }
});

const alert = (over: Partial<Alert> = {}): Alert => ({
  schema_version: "1.0", alert_id: "a1", session_id: "s1", patient_id: "SYN-A", session_revision: 1,
  issued_at: "2000-01-03T08:00:00Z", last_supported_at: "2000-01-03T08:10:00Z", horizon_minutes: 60,
  rule_version: "new-high-warning-v1", model_version: "m",
  kind: "predicted_new_high_episode", title: "Research warning: forecast suggests a new sustained high (>180 mg/dL) within 60 minutes",
  evidence: { forecast_id: "f", score: 2, score_kind: "forecast_margin_mg_dl", threshold: -10, latest_glucose_mg_dl: 160,
    predicted_mg_dl: { "30": 175, "60": 182 }, explanation_codes: [] },
  supporting_forecast_ids: ["f"], state: "open", outcome: { status: "pending" },
  acknowledgement: { acknowledged: false, meaning: "local" },
  ...over,
} as Alert);

const list = (items: Alert[], revision = 1): AlertList => ({
  schema_version: "1.0", session_id: "s1", session_revision: revision, clock_at: "2000-01-03T08:30:00Z",
  rule_available: true, rule_description: null, items,
} as AlertList);

type SaveFn = (a: Alert, note: string | undefined) => Promise<unknown>;
const saveOk = () => vi.fn<SaveFn>(async () => undefined);

function setup(onSave: Mock<SaveFn> = saveOk(), items = [alert()], revision = 1) {
  const ui = render(<WarningHistory alerts={list(items, revision)} revision={revision} sessionKey={`s1:${revision}`}
    participant="Synthetic Participant A" onSave={onSave} />);
  return { onSave, ...ui };
}

const openReview = async () => {
  await userEvent.click(screen.getByRole("button", { name: /Mark warning issued .* as reviewed/ }));
  return screen.getByLabelText("Review note (optional)");
};

describe("warning review", () => {
  it("names the warning and keeps a pending outcome pending", async () => {
    setup();
    await openReview();
    expect(screen.getByText(/Synthetic Participant A · issued/)).toBeInTheDocument();
    expect(screen.getAllByText("Outcome pending").length).toBeGreaterThan(1); // the row and the dialog
    expect(screen.getAllByText(/Fired by the 60-min forecast/).length).toBeGreaterThan(1);
  });

  it("saves the typed note through the acknowledgement call and closes", async () => {
    const { onSave } = setup();
    const field = await openReview();
    await userEvent.type(field, "Reviewed the trace; sensor looked fine.");
    expect(screen.getByText(`39 / ${NOTE_MAX}`)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save review" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][1]).toBe("Reviewed the trace; sensor looked fine.");
    await waitFor(() => expect(screen.queryByLabelText("Review note (optional)")).toBeNull());
  });

  it("sends no note when the field is empty", async () => {
    const { onSave } = setup();
    await openReview();
    await userEvent.click(screen.getByRole("button", { name: "Save review" }));
    expect(onSave.mock.calls[0][1]).toBeUndefined();
  });

  it("does not save anything on cancel", async () => {
    const { onSave } = setup();
    const field = await openReview();
    await userEvent.type(field, "draft");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onSave).not.toHaveBeenCalled();
  });

  it("keeps the typed note after an error and retries", async () => {
    const onSave = vi.fn<SaveFn>().mockRejectedValueOnce(new Error("API offline")).mockResolvedValueOnce(undefined);
    setup(onSave);
    const field = await openReview();
    await userEvent.type(field, "keep me");
    await userEvent.click(screen.getByRole("button", { name: "Save review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save the review: API offline");
    expect(screen.getByLabelText("Review note (optional)")).toHaveValue("keep me");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(onSave.mock.calls[1][1]).toBe("keep me");
  });

  it("never submits a warning from an earlier revision", async () => {
    const { onSave, rerender } = setup();
    const field = await openReview();
    await userEvent.type(field, "old");
    // the replay is rewound: a new revision whose list no longer holds this warning
    rerender(<WarningHistory alerts={list([], 2)} revision={2} sessionKey="s1:2" participant="Synthetic Participant A"
      onSave={onSave} />);
    // an empty list renders no history, so the open dialog must not be able to save the old warning
    expect(screen.queryByRole("button", { name: "Save review" })).toBeNull();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("says nothing was saved when the warning disappears while the dialog is open", async () => {
    const { onSave, rerender } = setup(saveOk(), [alert(), alert({ alert_id: "a2", issued_at: "2000-01-03T07:00:00Z" })]);
    await userEvent.click(screen.getAllByRole("button", { name: /Mark warning issued .* as reviewed/ })[0]);
    rerender(<WarningHistory alerts={list([alert({ alert_id: "a2", session_revision: 2, issued_at: "2000-01-03T07:00:00Z" })], 2)}
      revision={2} sessionKey="s1:2" participant="Synthetic Participant A" onSave={onSave} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was saved");
    expect(screen.queryByRole("button", { name: "Save review" })).toBeNull();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("shows a saved note as text, never as HTML", () => {
    const note = "<b>bold</b><img src=x onerror=alert(1)>";
    setup(saveOk(), [alert({ acknowledgement: { acknowledged: true, acknowledged_at: "2026-10-20T10:00:00Z", note, meaning: "local" } })]);
    expect(screen.getByText(note)).toBeInTheDocument();
    expect(document.querySelector(".warn b, .warn img")).toBeNull();
    expect(screen.queryByRole("button", { name: /as reviewed/ })).toBeNull(); // no editing of a saved review
  });

  it("limits the note to the API's 500 characters", async () => {
    setup();
    const field = await openReview();
    expect(field).toHaveAttribute("maxLength", String(NOTE_MAX));
  });
});
