import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { Providers, routes } from "@/App";
import { createClient } from "@/api/client";
import { ApiError, type Transport } from "@/api/transport";
import type { PatientSummary } from "@/api/types";
import { NewReplayDialog } from "@/components/shell/Dialogs";
import { PublicDemoBanner } from "@/components/shell/PublicDemoBanner";
import { ModelDetails } from "@/components/twin/Panels";
import { forecast, latest } from "@/test/fixtures";
import { ShellContext } from "@/components/shell/ShellContext";
import { friendlyError } from "@/lib/apiErrors";
import { OverviewPage } from "@/pages/OverviewPage";
import { ParticipantsPage } from "@/pages/ParticipantsPage";
import { ReplayPage } from "@/pages/ReplayPage";
import { RECORDED_UNAVAILABLE } from "./deployment";

const PUBLIC = { schema_version: "1.0", status: "ok", service: "glucotwin-api", version: "test", public_demo: true,
  public_demo_limits: { session_idle_minutes: 120, max_sessions_per_visitor: 5 } };
const LOCAL = { schema_version: "1.0", status: "ok", service: "glucotwin-api", version: "test" };

function patient(id: string, mode: PatientSummary["mode"], over: Partial<PatientSummary> = {}): PatientSummary {
  return {
    schema_version: "1.0", patient_id: id, display_alias: id === "SYN-A" ? "Synthetic Participant A" : `Participant ${id}`, mode,
    dataset: { name: mode === "synthetic_demo" ? "GlucoTwin synthetic fixtures" : "CGMacros", version: "1", license: "x",
      citation_url: null, synthetic: mode === "synthetic_demo" },
    cohort: { label: mode === "synthetic_demo" ? "Synthetic (fictional) participant" : "Type 2 diabetes", provenance: "" },
    eligible_for_primary_analysis: mode === "dataset_replay", exclusion_reason: null, attributes: [], missing_fields: [],
    coverage: { primary_device: null, native_cadence_minutes: 5, recording_days: 4, glucose_samples: 100,
      glucose_coverage_fraction: 1, gaps_over_threshold: 0, meals_logged: 0, activity_coverage_fraction: 1 },
    active_session: null, ...over,
  } as PatientSummary;
}

/** Records every request path; ``health`` decides public or local; ``rest`` answers everything else. */
function client(health: unknown, rest: (path: string) => unknown = () => { throw new Error("unexpected"); }) {
  const paths: string[] = [];
  const t: Transport = {
    kind: "http",
    request: async <T,>(_m: "GET" | "POST", path: string) => {
      paths.push(path);
      if (path === "/health") {
        if (health instanceof Error) throw health;
        return health as T;
      }
      return (await rest(path)) as T;
    },
  };
  return { c: createClient(t), paths };
}

function wrap(ui: React.ReactNode, c: ReturnType<typeof createClient>, shell = { open: vi.fn(), close: vi.fn() }) {
  render(
    <Providers client={c} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ShellContext.Provider value={shell}><MemoryRouter>{ui}</MemoryRouter></ShellContext.Provider>
    </Providers>,
  );
  return shell;
}

describe("public demonstration banner", () => {
  it("names the synthetic model and the expiry when the API is a public demonstration", async () => {
    wrap(<PublicDemoBanner />, client(PUBLIC).c);
    const note = await screen.findByRole("note", { name: "Public synthetic demonstration" });
    expect(note).toHaveTextContent("not the evaluated real-data fusion model");
    expect(note).toHaveTextContent("private to this browser and expire after 120 minutes of inactivity");
    expect(note).toHaveTextContent("not a medical device");
  });

  it("renders nothing on a local installation or when the health check fails", async () => {
    const local = client(LOCAL);
    wrap(<PublicDemoBanner />, local.c);
    await waitFor(() => expect(local.paths).toContain("/health"));
    expect(screen.queryByRole("note", { name: "Public synthetic demonstration" })).toBeNull();
  });

  it("appears above the landing page", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });
    const { c } = client(PUBLIC, (p) => { throw new ApiError(404, "not_found", p); });
    render(<Providers client={c}><RouterProvider router={router} /></Providers>);
    expect(await screen.findByRole("note", { name: "Public synthetic demonstration" })).toBeInTheDocument();
    expect(await screen.findByText(/Synthetic data only in this public demonstration/)).toBeInTheDocument();
  });
});

describe("recorded data is never requested in a public demonstration", () => {
  it("participants page asks the API for synthetic participants only and hides the recorded-data filter", async () => {
    const { c, paths } = client(PUBLIC, (p) => {
      if (p.startsWith("/patients")) return { schema_version: "1.0", items: [patient("SYN-A", "synthetic_demo")], next_cursor: null,
        total: 1, total_unfiltered: 1 };
      if (p.startsWith("/replay/sessions")) return { schema_version: "1.0", items: [] };
      throw new Error(p);
    });
    wrap(<ParticipantsPage />, c);
    expect(await screen.findByText(RECORDED_UNAVAILABLE, { exact: false })).toBeInTheDocument();
    await waitFor(() => expect(paths.some((p) => p.includes("mode=synthetic_demo"))).toBe(true));
    expect(paths.some((p) => p.includes("dataset_replay"))).toBe(false);
    expect(screen.queryByLabelText("Data")).toBeNull();
    expect(screen.queryByText("Primary Type 2 analysis only")).toBeNull();
  });

  it("overview offers no recorded demo even if a recorded participant were listed", async () => {
    const { c, paths } = client(PUBLIC, (p) => {
      if (p.startsWith("/patients?")) return { schema_version: "1.0", items: [patient("01", "dataset_replay"), patient("SYN-A", "synthetic_demo")],
        next_cursor: null, total: 2 };
      if (p.startsWith("/replay/sessions")) return { schema_version: "1.0", items: [] };
      throw new Error(p);
    });
    wrap(<OverviewPage />, c);
    expect(await screen.findByText(/1 synthetic demonstration participants/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open recorded demo" })).toBeNull();
    expect(paths.some((p) => p.startsWith("/patients/01"))).toBe(false);
  });

  it("a local installation still shows recorded data as today", async () => {
    const { c } = client(LOCAL, (p) => {
      if (p.startsWith("/patients?")) return { schema_version: "1.0", items: [patient("01", "dataset_replay"), patient("SYN-A", "synthetic_demo")],
        next_cursor: null, total: 2 };
      if (p.startsWith("/patients/01")) return { ...patient("01", "dataset_replay"), evaluation_segments: [] };
      if (p.startsWith("/replay/sessions")) return { schema_version: "1.0", items: [] };
      throw new Error(p);
    });
    wrap(<OverviewPage />, c);
    expect(await screen.findByRole("button", { name: "Open recorded demo" })).toBeInTheDocument();
    expect(screen.getByText("Open the recorded demo, resume a replay or choose a participant.")).toBeInTheDocument();
  });
});

describe("new replay dialog", () => {
  it("public: recorded data is disabled with its reason and the synthetic participant is chosen", async () => {
    HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
    HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.removeAttribute("open"); };
    const { c, paths } = client(PUBLIC, (p) => {
      if (p.startsWith("/patients?")) return { schema_version: "1.0", items: [patient("01", "dataset_replay"), patient("SYN-A", "synthetic_demo")],
        next_cursor: null, total: 2 };
      if (p.startsWith("/patients/SYN-A")) return patient("SYN-A", "synthetic_demo");
      throw new Error(p);
    });
    wrap(<NewReplayDialog open onClose={() => {}} />, c);
    expect(await screen.findByText("Local installation only — not redistributed in this public demonstration")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("radio", { name: /Synthetic/ })).toBeChecked());
    expect(screen.getByRole("radio", { name: /Recorded/ })).toBeDisabled();
    expect((screen.getByLabelText("Participant") as HTMLSelectElement).value).toBe("SYN-A");
    expect(paths.some((p) => p.startsWith("/patients/01"))).toBe(false);
  });
});

describe("model labels", () => {
  it("public: a synthetic forecast is labelled as the synthetic demonstration model, never the fusion model", () => {
    const f = forecast();
    render(<ModelDetails twin={{ model_family: "lightgbm", model_version: "synthetic-demo.lightgbm.dyn-v2.v1" } as never}
      latest={latest(f)} publicDemo />);
    expect(screen.getByText(/not the evaluated real-data fusion model/)).toBeInTheDocument();
  });

  it("local: unchanged", () => {
    render(<ModelDetails twin={{ model_family: "lightgbm", model_version: "synthetic-demo.lightgbm.dyn-v2.v1" } as never}
      latest={latest(forecast())} />);
    expect(screen.queryByText(/not the evaluated real-data fusion model/)).toBeNull();
  });
});

describe("a replay that is gone", () => {
  const gone = () => { throw new ApiError(404, "session_not_found", "Unknown session"); };

  it("public: says it expired or belongs to another browser and offers a new replay", async () => {
    const shell = wrap(<ReplayPage sid="abc" />, client(PUBLIC, gone).c);
    expect(await screen.findByText("This replay has expired or belongs to another browser.")).toBeInTheDocument();
    screen.getByRole("button", { name: "Start a new replay" }).click();
    expect(shell.open).toHaveBeenCalledWith("new-replay");
  });

  it("local: keeps the existing explanation", async () => {
    wrap(<ReplayPage sid="abc" />, client(LOCAL, gone).c);
    expect(await screen.findByText("Replay session not found")).toBeInTheDocument();
    expect(screen.getByText(/end when it restarts/)).toBeInTheDocument();
  });
});

describe("friendly API errors", () => {
  it("words rate limits, the synthetic-only rule and (public only) a missing session", () => {
    expect(friendlyError(new ApiError(429, "rate_limited", "slow down"))).toBe("Too many requests; wait a moment and try again.");
    expect(friendlyError(new ApiError(403, "public_demo_synthetic_only", "no"))).toBe(RECORDED_UNAVAILABLE);
    expect(friendlyError(new ApiError(404, "session_not_found", "Unknown session"), true))
      .toBe("This replay has expired or belongs to another browser.");
    expect(friendlyError(new ApiError(404, "session_not_found", "Unknown session"))).toBe("Unknown session");
    expect(friendlyError(new Error("boom"))).toBe("boom");
  });
});
