import { defineConfig, devices } from "@playwright/test";
import { API_PORT, VAR_DIR, WEB, WEB_PORT } from "./e2e/env";

// Real local API + web app on separate ports with an isolated, fresh var/ directory (see e2e/env.ts).
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: WEB, trace: "retain-on-failure", viewport: { width: 1440, height: 900 } },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: `rm -rf "${VAR_DIR}" && cd ../.. && GLUCOTWIN_VAR_DIR="${VAR_DIR}" uv run glucotwin serve --host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`, reuseExistingServer: false, timeout: 120_000,
    },
    {
      command: `GLUCOTWIN_API_URL=http://127.0.0.1:${API_PORT} npx vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: WEB, reuseExistingServer: false, timeout: 60_000,
    },
  ],
});
