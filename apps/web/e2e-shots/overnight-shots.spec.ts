/**
 * Review screenshots of the recorded-data patient journey (Participant 01 forecast/outcome/warnings, Participant 12
 * gap and recovery) plus landing, queue and evidence, at several viewports. It navigates the same states as
 * e2e/judge-journey.spec.ts, checks that each state was actually reached before saving it, and fails at the end if any
 * state was missed or any expected file is absent. Run it against fresh API storage so the queue holds exactly the two
 * replays it creates (one Participant 01 and one Participant 12 session, shared by every viewport and re-seeked to the
 * same replay times), which keeps before/after captures comparable. Skipped without CGMacros.
 */
import { existsSync, mkdirSync, rmSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const API = process.env.SHOTS_API!;
const DIR = process.env.SHOTS_DIR ?? "../../reports/ui/overnight/latest";

const VIEWPORTS = [
  { tag: "1440", width: 1440, height: 900, full: true },
  { tag: "1280", width: 1280, height: 800, full: false },
  { tag: "tablet", width: 820, height: 1180, full: false },
  { tag: "phone", width: 390, height: 844, full: false },
];
const STATES = ["01-landing", "02-review-queue", "03-workspace-p01", "04-forecast-components", "05a-forecast-detail-pending",
  "05b-forecast-detail-outcome", "06-warnings", "07-review-summary", "08a-p12-gap-abstention", "08b-p12-recovery",
  "09-evidence", "09b-evidence-guardrails", "10-overview"];
const FULL = ["01-landing-full", "03-workspace-p01-full", "09-evidence-full"];

let shared: { s1: string; s12: string } | null = null;

async function byAlias(page: Page, alias: string) {
  const pts = await (await page.request.get(`${API}/patients?mode=dataset_replay&limit=200`)).json();
  return (pts.items ?? []).find((x: { display_alias: string }) => x.display_alias === alias);
}

async function newSession(page: Page, patientId: string) {
  const detail = await (await page.request.get(`${API}/patients/${patientId}`)).json();
  const test = (detail.evaluation_segments ?? []).find((s: { name: string }) => s.name === "test");
  const r = await page.request.post(`${API}/replay/sessions`, {
    data: { mode: "dataset_replay", patient_id: patientId, ...(test ? { start_at: test.start_at } : {}) },
  });
  if (r.ok()) return (await r.json()).id as string;
  throw new Error(`session create failed ${r.status()} ${await r.text()}`);
}

async function seek(page: Page, sid: string, iso: string) {
  const r = await page.request.post(`${API}/replay/sessions/${sid}/control`, { data: { action: "seek", seek_to: iso } });
  expect(r.ok(), `seek ${sid} to ${iso}`).toBe(true);
}

/** Data loaded, no loading notice, and the window scrolled to the top (no restored scroll position). */
async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(/Loading released observations/)).toHaveCount(0);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
}

const visibleText = (page: Page, text: string) => page.getByText(text).filter({ visible: true }).first();

for (const vp of VIEWPORTS) {
  test(`screens at ${vp.tag}`, async ({ page }) => {
    const p01 = await byAlias(page, "Participant 01");
    const p12 = await byAlias(page, "Participant 12");
    test.skip(!p01 || !p12, "CGMacros not imported on this machine");
    mkdirSync(DIR, { recursive: true });
    await page.setViewportSize({ width: vp.width, height: vp.height });
    const expected = [...STATES, ...(vp.full ? FULL : [])].map((n) => `${DIR}/${vp.tag}-${n}.png`);
    for (const f of expected) rmSync(f, { force: true }); // a capture left by an earlier run never counts
    const failed: string[] = [];
    const shot = async (name: string, full = false) => {
      await page.screenshot({ path: `${DIR}/${vp.tag}-${name}.png`, fullPage: full });
    };
    const step = async (name: string, fn: () => Promise<void>) => {
      try { await fn(); } catch (e) { failed.push(`${name}: ${(e as Error).message.split("\n")[0]}`); }
    };

    shared ??= { s1: await newSession(page, p01.patient_id), s12: await newSession(page, p12.patient_id) };
    const { s1, s12 } = shared;
    await seek(page, s1, "2000-01-11T20:38:00Z");
    await seek(page, s12, "2000-01-11T11:47:00Z");

    await step("landing", async () => {
      await page.goto("/");
      await settle(page);
      await shot("01-landing");
      if (vp.full) await shot("01-landing-full", true);
    });

    await step("queue", async () => {
      await page.goto("/app/review-queue");
      const table = page.getByRole("table", { name: "Review queue" });
      await expect(table.getByRole("link", { name: /^Open replay for/ })).toHaveCount(2);
      await expect(page.getByText("Counting…")).toHaveCount(0);
      await settle(page);
      await shot("02-review-queue");
    });

    await step("workspace", async () => {
      await page.goto(`/app?session=${s1}`);
      await expect(page.getByRole("group", { name: "Replay controls" })).toBeVisible();
      await expect(visibleText(page, "Day 9 · 20:38")).toBeVisible();
      await settle(page);
      await shot("03-workspace-p01");
      if (vp.full) await shot("03-workspace-p01-full", true);
    });

    await step("explanation", async () => {
      const explain = page.getByRole("region", { name: "How the twin reached this forecast" });
      await expect(explain).toContainText("Forecast issued Day 9 · 20:35");
      await explain.evaluate((el) => el.scrollIntoView({ block: "start" }));
      await shot("04-forecast-components");
    });

    await step("detail-pending", async () => {
      await page.getByRole("button", { name: "View forecast details" }).click();
      const drawer = page.getByRole("dialog", { name: "Forecast details" });
      await expect(drawer).toContainText("Issued at Day 9 · 20:35");
      const outcome = drawer.getByRole("region", { name: "Outcome" });
      await expect(outcome).not.toContainText(/observed reading \d/);
      await outcome.evaluate((el) => el.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(300);
      await shot("05a-forecast-detail-pending");
      await page.keyboard.press("Escape");
      await expect(drawer).toBeHidden();
    });

    await step("detail-resolved", async () => {
      await page.getByRole("button", { name: "Step 1 h forward" }).click();
      await expect(visibleText(page, "Day 9 · 21:38")).toBeVisible();
      await page.waitForLoadState("networkidle");
      await page.getByRole("button", { name: "View forecast details" }).click();
      const drawer = page.getByRole("dialog", { name: "Forecast details" });
      await expect(drawer).toContainText("Issued at Day 9 · 20:35");
      const outcome = drawer.getByRole("region", { name: "Outcome" });
      await expect(outcome).toContainText(/60 min \(for 21:35\): observed reading \d+ mg\/dL/);
      await outcome.evaluate((el) => el.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(300);
      await shot("05b-forecast-detail-outcome");
      await page.keyboard.press("Escape");
      await expect(drawer).toBeHidden();
    });

    await step("warnings", async () => {
      const w = page.getByRole("region", { name: /^Warnings/ });
      await expect(w.getByText("No onset (false alarm)").first()).toBeVisible();
      await w.evaluate((el) => el.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(300);
      await shot("06-warnings");
    });

    await step("summary", async () => {
      await page.getByRole("button", { name: "Review summary" }).click();
      const dialog = page.getByRole("dialog", { name: "Review summary" });
      await expect(dialog.getByRole("article", { name: "Review summary report" })).toContainText("Day 9 · 21:38 (replay time)");
      await page.waitForTimeout(300);
      await shot("07-review-summary");
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
    });

    await step("gap", async () => {
      await page.goto(`/app?session=${s12}`);
      await expect(page.getByRole("group", { name: "Replay controls" })).toBeVisible();
      await expect(page.getByRole("region", { name: "60-minute forecast" }).getByText("Not available")).toBeVisible();
      await settle(page);
      await shot("08a-p12-gap-abstention");
    });

    await step("recovery", async () => {
      let recovered = false;
      for (let i = 0; i < 24 && !recovered; i++) {
        await page.getByRole("button", { name: "Step 5 min forward" }).click();
        await page.waitForTimeout(150);
        const lf = await (await page.request.get(`${API}/replay/sessions/${s12}/forecast`)).json();
        recovered = lf.availability === "available" && lf.forecast?.quality?.status !== "insufficient";
      }
      expect(recovered, "a forecast is issued again after the gap").toBe(true);
      await expect(page.getByRole("region", { name: "60-minute forecast" }).getByText("mg/dL", { exact: true })).toBeVisible();
      await settle(page);
      await shot("08b-p12-recovery");
    });

    await step("evidence", async () => {
      await page.goto("/app/evidence");
      await expect(page.getByText(/Serving model:/)).toBeVisible();
      await settle(page);
      await shot("09-evidence");
      if (vp.full) await shot("09-evidence-full", true);
      await page.locator("#safety-guardrails").evaluate((el) => el.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(300);
      await shot("09b-evidence-guardrails");
    });

    await step("overview", async () => {
      await page.goto("/app");
      await settle(page);
      await shot("10-overview");
    });

    const missing = expected.filter((f) => !existsSync(f));
    expect(failed, `states not reached at ${vp.tag}`).toEqual([]);
    expect(missing, `captures missing at ${vp.tag}`).toEqual([]);
  });
}
