import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// The hosted public synthetic demonstration, checked as visitors see it: one process (`glucotwin serve --public-demo`)
// serves the API and the built web app. Set PUBLIC_BASE_URL to test an already running deployment (e.g. the container)
// instead of starting one; the local server uses throwaway storage and never touches :8000/:5173.
const PORT = Number(process.env.E2E_PUBLIC_PORT ?? 8040);
const VAR_DIR = process.env.E2E_PUBLIC_VAR_DIR ?? join(tmpdir(), "glucotwin-public-e2e-var");
const external = process.env.PUBLIC_BASE_URL;

export default defineConfig({
  testDir: "./e2e-public",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: external ?? `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: external ? undefined : {
    command: `npm run build && rm -rf "${VAR_DIR}" && cd ../.. && GLUCOTWIN_VAR_DIR="${VAR_DIR}" `
      + `GLUCOTWIN_WEB_DIST="$PWD/apps/web/dist" uv run glucotwin serve --public-demo --host 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/v1/health`, reuseExistingServer: false, timeout: 180_000,
  },
});
