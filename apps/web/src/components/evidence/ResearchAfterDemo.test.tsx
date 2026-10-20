import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { researchSummaries, researchSummariesNotRun } from "@/test/researchSummaries";
import { ResearchAfterDemo } from "./ResearchAfterDemo";

describe("research after the demo model", () => {
  it("tags each finding and never presents an experiment as the demo model", () => {
    render(<ResearchAfterDemo data={researchSummaries} />);
    const list = screen.getByRole("list", { name: "Research after the demo model" });
    const rows = within(list).getAllByRole("listitem").filter((li) => li.classList.contains("rsum__row"));
    expect(rows).toHaveLength(4);
    for (const r of rows) expect(within(r).getByText("Not the demo model")).toBeInTheDocument();
    const d046 = rows.find((r) => within(r).queryByText("D-046"))!;
    expect(within(d046).getByText("Prediction ranges calibrated on more people.").closest("li")).toHaveTextContent("Shown");
    expect(within(d046).getByText("Earlier two-hour warning.").closest("li")).toHaveTextContent("Not shown");
    expect(within(d046).getByText("Health record as a new person's starting correction.").closest("li")).toHaveTextContent("Not shown");
    const d044 = rows.find((r) => within(r).queryByText("D-044"))!;
    expect(within(d044).getByText("Negative result")).toBeInTheDocument();
  });

  it("says when the research was not run on this installation", () => {
    render(<ResearchAfterDemo data={researchSummariesNotRun} />);
    expect(screen.getAllByText(/Not run on this installation/)).toHaveLength(4);
    expect(screen.queryByText("Shown")).toBeNull();
  });

  it("reports a failed request instead of an empty section", () => {
    render(<ResearchAfterDemo error={new Error("offline")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The research summaries could not be loaded: offline");
  });
});
