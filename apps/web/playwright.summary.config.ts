import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// Review-summary export check: the printed copy is exported to PDF (Chromium's print path) for recorded and synthetic
// edge cases and written to reports/ui/summary_check/ for inspection. Own ports and throwaway storage; it never touches
// the workspace you use on :8000/:5173 or the standard browser suite's ports.
const API_PORT = Number(process.env.E2E_SUMMARY_API_PORT ?? 8030);
const WEB_PORT = Number(process.env.E2E_SUMMARY_WEB_PORT ?? 5200);
const VAR_DIR = process.env.E2E_SUMMARY_VAR_DIR ?? join(tmpdir(), "glucotwin-summary-check-var");
process.env.SUMMARY_API = `http://127.0.0.1:${API_PORT}/api/v1`;

export default defineConfig({
  testDir: "./e2e-summary",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: `rm -rf "${VAR_DIR}" && cd ../.. && GLUCOTWIN_VAR_DIR="${VAR_DIR}" uv run glucotwin serve --host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`, reuseExistingServer: false, timeout: 120_000,
    },
    {
      command: `GLUCOTWIN_API_URL=http://127.0.0.1:${API_PORT} npx vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`, reuseExistingServer: false, timeout: 60_000,
    },
  ],
});
