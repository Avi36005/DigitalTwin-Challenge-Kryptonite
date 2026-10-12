import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { Providers, routes } from "@/App";
import { createClient } from "@/api/client";
import { ApiError } from "@/api/transport";
import { migrateLegacyUrl, paths } from "./routes";

describe("route migration", () => {
  it("moves an old replay link to the workspace without touching the session or other query state", () => {
    expect(migrateLegacyUrl("/", "?session=abc&x=1", "#chart")).toBe("/app?session=abc&x=1#chart");
  });

  it("keeps the landing page at / when there is no session", () => {
    expect(migrateLegacyUrl("/", "", "")).toBeNull();
    expect(migrateLegacyUrl("/", "?utm=1", "")).toBeNull();
  });

  it("redirects every old workspace page and preserves query and hash", () => {
    expect(migrateLegacyUrl("/participants", "?focus=SYN-A", "")).toBe("/app/participants?focus=SYN-A");
    expect(migrateLegacyUrl("/sessions", "", "")).toBe("/app/sessions");
    expect(migrateLegacyUrl("/evidence/", "", "#limits")).toBe("/app/evidence#limits");
    expect(migrateLegacyUrl("/data-quality", "", "")).toBe("/app/data-quality");
    expect(migrateLegacyUrl("/app/participants", "", "")).toBeNull();
  });

  it("builds workspace URLs in one place", () => {
    expect(paths.session("a b")).toBe("/app?session=a%20b");
    expect(paths.participants("SYN-A")).toBe("/app/participants?focus=SYN-A");
    expect(paths.overview()).toBe("/app");
  });
});

const offline = createClient({
  kind: "http",
  request: async () => {
    throw new ApiError(0, "api_unreachable", "offline in tests");
  },
});

describe("router redirects", () => {
  it("replaces /?session=<id> with /app?session=<id> (no extra history entry)", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/?session=s-123"] });
    render(<Providers client={offline}><RouterProvider router={router} /></Providers>);
    await waitFor(() => expect(router.state.location.pathname).toBe("/app"));
    expect(router.state.location.search).toBe("?session=s-123");
    expect(router.state.historyAction).toBe("REPLACE");
  });

  it("redirects /evidence to /app/evidence with replace, keeping the hash", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/evidence#protocol"] });
    render(<Providers client={offline}><RouterProvider router={router} /></Providers>);
    await waitFor(() => expect(router.state.location.pathname).toBe("/app/evidence"));
    expect(router.state.location.hash).toBe("#protocol");
    expect(router.state.historyAction).toBe("REPLACE");
  });

  it("renders the landing page at / even when the API is unreachable", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });
    render(<Providers client={offline}><RouterProvider router={router} /></Providers>);
    expect(await screen.findByRole("heading", { level: 1, name: /See the next chapter of a glucose/ })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Open workspace" })[0]).toHaveAttribute("href", "/app");
    expect(screen.queryByRole("navigation", { name: "Workspace" })).toBeNull(); // no sidebar in the landing DOM
  });
});
