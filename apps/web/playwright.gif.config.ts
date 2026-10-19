import { defineConfig, devices } from "@playwright/test";
import base from "./playwright.config";

// `npm run demo-gif`: records the README GIF (e2e/demo.gif.ts) against the same throwaway API + web servers as the
// browser tests. Its file name does not match `*.spec.ts`, so `npm run e2e` never runs it.
export default defineConfig({
  ...base,
  testMatch: "demo.gif.ts",
  outputDir: "test-results/demo-gif",
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 1260 }, deviceScaleFactor: 1 } }],
});
