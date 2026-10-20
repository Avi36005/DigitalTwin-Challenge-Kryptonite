import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { Providers } from "@/App";
import { createClient } from "@/api/client";
import type { QueueSnapshot, ReplaySession } from "@/api/types";
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

function snapOf(s: ReplaySession): QueueSnapshot {
  return {
    schema_version: "1.0", session: s,
    alerts: { schema_version: "1.0", session_id: s.id, session_revision: s.revision, clock_at: s.clock_at, rule_available: true,
      rule_description: null, items: [] },
    latest_forecast: { ...latest(forecast()), session_id: s.id, session_revision: s.revision, clock_at: s.clock_at },
  };
}

const sessionList = (items: ReplaySession[]) => ({ schema_version: "1.0", items });
const isList = (path: string) => path.startsWith("/replay/sessions?");
const health = { schema_version: "1.0", status: "ok", service: "glucotwin-api", version: "x", public_demo: false, public_demo_limits: null };

describe("review queue page", () => {
  it("says there is nothing to review when no replay exists, and offers to start one", async () => {
    const shell = renderPage((path) => (path === "/health" ? health : sessionList([])));
    expect(await screen.findByText("Nothing to review yet")).toBeInTheDocument();
    screen.getByRole("button", { name: "Choose participant" }).click();
    expect(shell.open).toHaveBeenCalledWith("new-replay");
    expect(screen.getByText(/not a risk ranking or triage/)).toBeInTheDocument();
  });

  it("lists a replay with no warnings as such, read from one snapshot", async () => {
    const s = session();
    const seen: string[] = [];
    renderPage((path) => {
      seen.push(path);
      if (path === "/health") return health;
      if (isList(path)) return sessionList([s]);
      if (path === `/replay/sessions/${s.id}/review-snapshot`) return snapOf(s);
      throw new Error(path);
    });
    const table = await screen.findByRole("table", { name: "Review queue" });
    expect(await within(table).findByText("No warning yet")).toBeInTheDocument();
    expect(within(table).getByText("Fresh · 3 min old")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: /Open replay for Synthetic Participant A/ })).toHaveAttribute("href", "/app?session=s1");
    expect(screen.getByText("No replay has unreviewed warnings · 1 replay of 1 participant")).toBeInTheDocument();
    // the row never mixes separately timed requests
    expect(seen.some((p) => p.endsWith("/alerts") || p.endsWith("/forecast"))).toBe(false);
  });

  it("does not claim 'no unreviewed warnings' while counts are still loading", async () => {
    const s = session();
    renderPage((path) => {
      if (path === "/health") return health;
      if (isList(path)) return sessionList([s]);
      return new Promise(() => {}); // the snapshot never answers
    });
    expect(await screen.findByText("Counting warnings for 1 replay of 1 participant")).toBeInTheDocument();
    expect(screen.getByText("Counting…")).toBeInTheDocument();
    expect(screen.queryByText(/No replay has unreviewed warnings/)).toBeNull();
    expect(screen.queryByText("No warning yet")).toBeNull();
  });

  it("marks a failed row as not known, keeps the partial total honest, and retries on request", async () => {
    const a = session({ id: "a", patient_id: "SYN-A", patient_alias: "Synthetic Participant A" });
    const b = session({ id: "b", patient_id: "SYN-B", patient_alias: "Synthetic Participant B" });
    let fail = true;
    renderPage((path) => {
      if (path === "/health") return health;
      if (isList(path)) return sessionList([a, b]);
      if (path === "/replay/sessions/a/review-snapshot") return snapOf(a);
      if (path === "/replay/sessions/b/review-snapshot") {
        if (fail) throw new Error("offline");
        return snapOf(b);
      }
      throw new Error(path);
    });
    expect(await screen.findByText("None of the 1 counted so far has unreviewed warnings · 2 replays of 2 participants · 1 could not be counted")).toBeInTheDocument();
    expect(screen.getByText("Not known — offline")).toBeInTheDocument();
    expect(screen.queryByText("Inputs loading")).toBeNull();
    expect(screen.getByText("Inputs not known")).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry counting warnings for Synthetic Participant B" }));
    expect(await screen.findByText("No replay has unreviewed warnings · 2 replays of 2 participants")).toBeInTheDocument();
  });

  it("refuses a delayed answer from an earlier revision instead of showing its counts", async () => {
    const listed = session({ revision: 2 });
    const stale = snapOf(session({ revision: 1 }));
    stale.alerts.items = [{ alert_id: "old" } as never];
    renderPage((path) => {
      if (path === "/health") return health;
      if (isList(path)) return sessionList([listed]);
      return stale;
    });
    expect(await screen.findByText(/Not known — The answer described an earlier revision/)).toBeInTheDocument();
    expect(screen.queryByText(/unreviewed$/)).toBeNull();
  });

  it("keeps each of several replays of one participant linked to its own session", async () => {
    const a = session({ id: "aaaaaaaa1", created_at: "2026-10-20T10:00:00Z" });
    const b = session({ id: "bbbbbbbb2", created_at: "2026-10-20T11:00:00Z" });
    renderPage((path) => {
      if (path === "/health") return health;
      if (isList(path)) return sessionList([a, b]);
      return snapOf(path.includes("aaaaaaaa1") ? a : b);
    });
    expect(await screen.findByText("No replay has unreviewed warnings · 2 replays of 1 participant")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open replay for Synthetic Participant A, session aaaaaaaa" })).toHaveAttribute("href", "/app?session=aaaaaaaa1");
    expect(screen.getByRole("link", { name: "Open replay for Synthetic Participant A, session bbbbbbbb" })).toHaveAttribute("href", "/app?session=bbbbbbbb2");
  });

  it("reports a failed session list instead of an empty queue", async () => {
    renderPage((path) => { if (path === "/health") return health; throw new Error("offline"); });
    expect(await screen.findByRole("alert")).toHaveTextContent("The review queue could not be loaded: offline");
    expect(screen.queryByText("Nothing to review yet")).toBeNull();
  });
});
