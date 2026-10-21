import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// UI review screenshots (`npx playwright test --config playwright.shots.config.ts`): the same recorded-data states as the
// judge journey, at 1440×900, 1280×800, tablet and phone widths, written to $SHOTS_DIR (default
// reports/ui/overnight/latest). Own ports and throwaway storage; set SHOTS_WEB + SHOTS_API to reuse servers you started.
const API_PORT = Number(process.env.E2E_SHOTS_API_PORT ?? 8050);
const WEB_PORT = Number(process.env.E2E_SHOTS_WEB_PORT ?? 5220);
const VAR_DIR = process.env.E2E_SHOTS_VAR_DIR ?? join(tmpdir(), "glucotwin-shots-var");
const external = process.env.SHOTS_WEB;
process.env.SHOTS_API ??= `http://127.0.0.1:${API_PORT}/api/v1`;

export default defineConfig({
  testDir: "./e2e-shots",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: external ?? `http://127.0.0.1:${WEB_PORT}`, trace: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: external ? undefined : [
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
