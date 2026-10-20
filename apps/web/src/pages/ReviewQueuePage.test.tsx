import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { Providers } from "@/App";
import { createClient } from "@/api/client";
import type { Transport } from "@/api/transport";
import { ShellContext } from "@/components/shell/ShellContext";
import { forecast, latest, session } from "@/test/fixtures";
import { ReviewQueuePage } from "./ReviewQueuePage";

function transport(handler: (path: string) => unknown): Transport {
  return { kind: "http", request: async <T,>(_m: "GET" | "POST", path: string) => (await handler(path)) as T };
}

function renderPage(handler: (path: string) => unknown) {
  const shell = { open: vi.fn(), close: vi.fn() };
  render(
    <Providers client={createClient(transport(handler))} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ShellContext.Provider value={shell}>
        <MemoryRouter><ReviewQueuePage /></MemoryRouter>
      </ShellContext.Provider>
    </Providers>,
  );
  return shell;
}

describe("review queue page", () => {
  it("says there is nothing to review when no replay exists, and offers to start one", async () => {
    const shell = renderPage(() => ({ schema_version: "1.0", items: [] }));
    expect(await screen.findByText("Nothing to review yet")).toBeInTheDocument();
    screen.getByRole("button", { name: "Choose participant" }).click();
    expect(shell.open).toHaveBeenCalledWith("new-replay");
    expect(screen.getByText(/not triage/)).toBeInTheDocument();
  });

  it("lists a replay with no warnings as such, with its data freshness", async () => {
    const s = session();
    renderPage((path) => {
      if (path.startsWith("/replay/sessions?")) return { schema_version: "1.0", items: [s] };
      if (path.endsWith("/alerts")) return { schema_version: "1.0", session_id: s.id, session_revision: 1, clock_at: s.clock_at,
        rule_available: true, rule_description: null, items: [] };
      if (path.endsWith("/forecast")) return latest(forecast());
      throw new Error(path);
    });
    const table = await screen.findByRole("table", { name: "Review queue" });
    expect(await within(table).findByText("No warning yet")).toBeInTheDocument();
    expect(within(table).getByText("Fresh · 3 min old")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "Open replay for Synthetic Participant A" })).toHaveAttribute("href", "/app?session=s1");
    expect(screen.getByText("No replay has unreviewed warnings")).toBeInTheDocument();
  });

  it("reports a failed session list instead of an empty queue", async () => {
    renderPage(() => { throw new Error("offline"); });
    expect(await screen.findByRole("alert")).toHaveTextContent("The review queue could not be loaded: offline");
    expect(screen.queryByText("Nothing to review yet")).toBeNull();
  });
});
