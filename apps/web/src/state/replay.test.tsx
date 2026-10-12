import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Providers } from "@/App";
import { createClient } from "@/api/client";
import { ApiError, type Transport } from "@/api/transport";
import type { ReplaySession } from "@/api/types";
import { ReplayToolbar } from "@/components/replay/ReplayToolbar";
import { forecast, latest, session } from "@/test/fixtures";
import { useLatestForecast } from "./replay";

function Probe({ s }: { s: ReplaySession }) {
  const q = useLatestForecast(s);
  return <div data-testid="probe">{q.data ? `rev${q.data.session_revision}:${q.data.forecast?.as_of}` : "none"}</div>;
}

function transport(handler: (method: string, path: string, body?: unknown) => unknown): Transport {
  return {
    kind: "http",
    request: async <T,>(method: "GET" | "POST", path: string, body?: unknown) => (await handler(method, path, body)) as T,
  };
}

describe("revision-keyed caches", () => {
  it("rejects a late response that belongs to an older revision of the session", async () => {
    // The server answers with revision 1 data although the session has been rewound to revision 2.
    const client = createClient(transport(() => latest(forecast(), { session_revision: 1 })));
    render(<Providers client={client} queryClient={new QueryClient()}><Probe s={session({ revision: 2 })} /></Providers>);
    await waitFor(() => expect(client).toBeTruthy());
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.getByTestId("probe").textContent).toBe("none");
  });

  it("keeps two sessions' forecasts isolated", async () => {
    const client = createClient(transport((_m, path) => {
      const sid = path.split("/")[3];
      return latest(forecast({ session_id: sid, as_of: sid === "a" ? "2000-01-03T09:00:00Z" : "2000-01-03T09:30:00Z" }));
    }));
    render(
      <Providers client={client} queryClient={new QueryClient()}>
        <Probe s={session({ id: "a" })} />
        <Probe s={session({ id: "b" })} />
      </Providers>,
    );
    await waitFor(() => expect(screen.getAllByTestId("probe")[1].textContent).toContain("09:30"));
    expect(screen.getAllByTestId("probe")[0].textContent).toContain("09:00");
  });
});

describe("replay controls", () => {
  it("recovers visibly from a failed control command and allows retry", async () => {
    const calls = vi.fn();
    let fail = true;
    const client = createClient(transport((method, path, body) => {
      if (method === "POST" && path.endsWith("/control")) {
        calls(body);
        if (fail) throw new ApiError(500, "internal_error", "Unexpected server error");
        return session({ status: "playing" });
      }
      return session();
    }));
    const user = userEvent.setup();
    render(<Providers client={client} queryClient={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
      <ReplayToolbar session={session()} onAnnounce={() => {}} />
    </Providers>);
    await user.click(screen.getByRole("button", { name: "Play replay" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The last replay command failed");
    expect(screen.getByRole("button", { name: "Play replay" })).toBeEnabled();
    fail = false;
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Retry" }));
    });
    expect(calls).toHaveBeenCalledTimes(2);
    expect(calls.mock.calls[1][0]).toEqual({ action: "play" });
  });
});
