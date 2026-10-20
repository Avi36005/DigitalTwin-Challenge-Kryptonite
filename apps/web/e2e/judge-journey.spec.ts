/**
 * The judge's patient-review story, rehearsed end to end on recorded data (Participant 01 and Participant 12), at the
 * video's recording resolution. Each step asserts what the narration says and saves one screenshot to
 * reports/ui/journey/. Skipped cleanly when CGMacros is not imported on this machine.
 */
import { expect, test, type Page } from "@playwright/test";
import { API } from "./env";

const SHOTS = "../../reports/ui/journey";
const PROFILE_INPUTS = ["Age", "Sex (male = 1)", "BMI", "HbA1c", "Fasting glucose", "Fasting insulin", "Triglycerides",
  "HDL cholesterol"];

async function byAlias(page: Page, alias: string) {
  const pts = await (await page.request.get(`${API}/patients?mode=dataset_replay&limit=200`)).json();
  return (pts.items ?? []).find((x: { display_alias: string }) => x.display_alias === alias);
}

async function startTestPeriod(page: Page, patientId: string) {
  const previous = new URL(page.url()).searchParams.get("session");
  await page.getByRole("button", { name: "New replay" }).first().click();
  const dialog = page.getByRole("dialog", { name: "New replay" });
  await dialog.getByRole("radio", { name: /Recorded-data replay/ }).check();
  await dialog.getByLabel("Participant", { exact: true }).selectOption(patientId);
  await dialog.getByRole("radio", { name: /Final test period/ }).check();
  await dialog.getByRole("button", { name: "Start replay" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("session")).not.toBe(previous);
  return new URL(page.url()).searchParams.get("session")!;
}

/** A seek as the timeline does it (new revision), then wait for the workspace to show that revision. */
async function seek(page: Page, sid: string, iso: string) {
  await page.request.post(`${API}/replay/sessions/${sid}/control`, { data: { action: "seek", seek_to: iso } });
  await page.reload();
  await expect(page.getByRole("group", { name: "Replay controls" })).toBeVisible();
  await expect(page.getByText(/Loading released observations/).first()).toBeHidden();
}

async function clockLabel(page: Page, label: string) {
  await expect(page.getByText(label).first()).toBeVisible();
}

test.describe("judge journey (recorded data, 1920×1080)", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test("Participant 01: inputs, forecast, outcome, warnings, review and a frozen summary", async ({ page }) => {
    const p = await byAlias(page, "Participant 01");
    test.skip(!p, "CGMacros not imported on this machine");
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/app");
    const sid = await startTestPeriod(page, p.patient_id);
    await seek(page, sid, "2000-01-11T20:38:00Z");
    await clockLabel(page, "Day 9 · 20:38");

    // 1. the explanation names the 8 profile values the model reads, and wearable availability
    const explain = page.getByRole("region", { name: "How the twin reached this forecast" });
    await expect(explain).toContainText("Health record: read by this model; 8 values known");
    for (const label of PROFILE_INPUTS) await expect(explain).toContainText(label);
    await expect(explain).toContainText("Context only, not model inputs");
    await expect(explain).toContainText("Wearable activity: 5-minute summaries from the last hour were available and used.");
    await explain.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${SHOTS}/01-inputs-read-by-the-model.png` });

    // 2. the 20:35 forecast: population, bounded correction, final estimate, measured range limitation
    await expect(explain).toContainText("Forecast issued Day 9 · 20:35");
    const comp = explain.getByRole("table", { name: "Forecast components" });
    await expect(comp).toContainText("192 mg/dL");
    await expect(comp).toContainText("−3.0 mg/dL");
    await expect(comp).toContainText("189 mg/dL");
    await expect(comp).toContainText("195 mg/dL");
    await expect(comp).toContainText("−6.7 mg/dL");
    await expect(comp).toContainText("188 mg/dL");
    await expect(explain).toContainText("Bounded at ±25 mg/dL");
    await expect(explain).toContainText(/74\.2%.*74\.0%/);
    await expect(explain).toContainText("Accuracy at this trend");
    await expect(explain).toContainText(/range held the outcome \d+% of the time at 30 min, \d+% of the time at 60 min/);
    await expect(explain).toContainText("(rising > 2 mg/dL/min)"); // unit case kept
    await page.screenshot({ path: `${SHOTS}/02-forecast-components.png` });
    console.log("STEP2::" + (await explain.innerText()).replace(/\n/g, " | "));

    // 3. pin the 20:35 forecast, step on one hour, reopen: the released readings and the correction's effect
    await page.getByRole("button", { name: "View forecast details" }).click();
    const drawer = page.getByRole("dialog", { name: "Forecast details" });
    await expect(drawer).toContainText("Issued at Day 9 · 20:35");
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await page.getByRole("button", { name: "Step 1 h forward" }).click();
    await clockLabel(page, "Day 9 · 21:38");
    await page.getByRole("button", { name: "View forecast details" }).click();
    await expect(drawer).toContainText("Issued at Day 9 · 20:35");
    const outcome = drawer.getByRole("region", { name: "Outcome" });
    await expect(outcome).toContainText(/30 min \(for 21:05\): observed reading 189 mg\/dL at 21:05/);
    await expect(outcome).toContainText(/60 min \(for 21:35\): observed reading 169 mg\/dL at 21:35/);
    await expect(outcome).toContainText(/The patient correction moved this forecast [\d.]+ mg\/dL closer to the observed value/);
    await outcome.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${SHOTS}/03-forecast-outcome.png` });
    console.log("STEP3::" + (await outcome.innerText()).replace(/\n/g, " | "));
    await page.keyboard.press("Escape");

    // 4. the warning list holds both a false alarm and the matched 20:30 onset with its lead
    const warnings = page.getByRole("region", { name: /^Warnings/ });
    await expect(warnings.getByText("No onset (false alarm)").first()).toBeVisible();
    const w2030 = warnings.locator(".warn").filter({ hasText: "Day 9 · 20:30" }).first();
    await expect(w2030).toContainText(/Onset 20:45 · forecast lead \d+ min/);
    await w2030.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${SHOTS}/04-warnings-hit-and-false-alarm.png` });
    console.log("STEP4::" + (await w2030.innerText()).replace(/\n/g, " | "));

    // 5. review with a note, then a frozen summary with participant, session, revision, model and cutoff
    await page.getByRole("button", { name: "Mark warning issued Day 9 · 20:30 as reviewed" }).click();
    const review = page.getByRole("dialog", { name: "Review research warning" });
    await review.getByLabel("Review note (optional)").fill("Seen; recheck after dinner.");
    await review.getByRole("button", { name: "Save review" }).click();
    await expect(review).toBeHidden();
    await expect(page.getByText("Seen; recheck after dinner.").first()).toBeVisible();
    const sess = await (await page.request.get(`${API}/replay/sessions/${sid}`)).json();
    await page.getByRole("button", { name: "Review summary" }).click();
    const dialog = page.getByRole("dialog", { name: "Review summary" });
    const report = dialog.getByRole("article", { name: "Review summary report" });
    await expect(report).toContainText("Participant 01");
    await expect(report).toContainText(`${sid} · revision ${sess.revision}`);
    await expect(report).toContainText("lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion");
    await expect(report).toContainText("Day 9 · 21:38 (replay time)");
    await expect(report).toContainText("Seen; recheck after dinner.");
    const frozen = await report.innerText();
    await page.screenshot({ path: `${SHOTS}/05-frozen-review-summary.png` });
    await page.keyboard.press("Escape");
    // stepping on does not change the copy
    await page.getByRole("button", { name: "Step 5 min forward" }).click();
    await clockLabel(page, "Day 9 · 21:43");
    await page.getByRole("button", { name: "Review summary" }).click();
    await expect(dialog.getByText(/The replay has moved to Day 9 · 21:43 since this copy/)).toBeVisible();
    expect(await report.innerText()).toBe(frozen);
    await page.keyboard.press("Escape");

    // a rewind clears the pinned forecast: the drawer then shows the latest forecast of the new revision
    await seek(page, sid, "2000-01-11T20:03:00Z");
    await page.getByRole("button", { name: "View forecast details" }).click();
    await expect(drawer).not.toContainText("Issued at Day 9 · 20:35");
    await expect(drawer).toContainText(/Issued at Day 9 · 20:0\d/);
    await page.keyboard.press("Escape");
    expect(errors).toEqual([]);
  });

  test("Participant 12: a real sensor gap, abstention without a made-up forecast, then recovery", async ({ page }) => {
    const p = await byAlias(page, "Participant 12");
    test.skip(!p, "CGMacros not imported on this machine");
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/app");
    const sid = await startTestPeriod(page, p.patient_id);
    await seek(page, sid, "2000-01-11T10:52:00Z");
    const current = page.getByRole("region", { name: "Current glucose" });
    await expect(current).toContainText("391");
    await expect(current.getByText(/Stale/)).toBeVisible();
    await seek(page, sid, "2000-01-11T11:47:00Z");
    const f60 = page.getByRole("region", { name: "60-minute forecast" });
    await expect(f60.getByText("Not available")).toBeVisible();
    await expect(f60.getByText(/\d+\s*mg\/dL/)).toHaveCount(0); // no fabricated number
    await expect(page.getByRole("complementary", { name: "Review and guardrails" }).getByText("Insufficient information")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/06-gap-abstention.png` });
    // recovery: step on until a forecast is issued again from new readings
    let recovered = "";
    for (let i = 0; i < 24 && !recovered; i++) {
      await page.getByRole("button", { name: "Step 5 min forward" }).click();
      const lf = await (await page.request.get(`${API}/replay/sessions/${sid}/forecast`)).json();
      if (lf.availability === "available" && lf.forecast?.quality?.status !== "insufficient") recovered = lf.clock_at;
    }
    expect(recovered).not.toBe("");
    await expect(f60.getByText("mg/dL", { exact: true })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/06b-gap-recovery.png` });
    console.log("STEP6::recovered at " + recovered + " | " + (await f60.innerText()).replace(/\n/g, " | "));
    expect(errors).toEqual([]);
  });

  test("queue: two replays are counted separately; an unknown count is never shown as zero", async ({ page }) => {
    const a = await byAlias(page, "Participant 01");
    const b = await byAlias(page, "Participant 12");
    test.skip(!a || !b, "CGMacros not imported on this machine");
    await page.goto("/app");
    const sa = await startTestPeriod(page, a.patient_id);
    const sb = await startTestPeriod(page, b.patient_id);
    await page.request.post(`${API}/replay/sessions/${sa}/control`, { data: { action: "seek", seek_to: "2000-01-11T20:38:00Z" } });
    await page.request.post(`${API}/replay/sessions/${sb}/control`, { data: { action: "seek", seek_to: "2000-01-11T11:47:00Z" } });
    // cross-session isolation: each snapshot describes its own session, participant and revision
    for (const [sid, pid] of [[sa, a.patient_id], [sb, b.patient_id]]) {
      const snap = await (await page.request.get(`${API}/replay/sessions/${sid}/review-snapshot`)).json();
      expect(JSON.stringify(snap)).toContain(sid);
      expect(JSON.stringify(snap)).toContain(pid);
    }
    // one row's snapshot fails: that row says "Not known" with a retry, never "0 unreviewed"
    let fail = true;
    await page.route(`**/api/v1/replay/sessions/${sb}/review-snapshot`, (route) =>
      fail ? route.fulfill({ status: 503, contentType: "application/json",
        body: JSON.stringify({ schema_version: "1.0", error: { code: "unavailable", message: "Snapshot unavailable" } }) })
        : route.continue());
    await page.goto("/app/review-queue");
    const table = page.getByRole("table", { name: "Review queue" });
    const rowA = table.getByRole("row").filter({ has: page.locator(`a[href="/app?session=${sa}"]`) }).first();
    const rowB = table.getByRole("row").filter({ has: page.locator(`a[href="/app?session=${sb}"]`) }).first();
    await expect(rowA).toContainText(/\d+ unreviewed/);
    await expect(rowB).toContainText("Not known");
    await expect(rowB).not.toContainText("0 unreviewed");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    fail = false;
    await rowB.getByRole("button", { name: /Retry counting warnings for Participant 12/ }).click();
    await expect(rowB).toContainText(/\d+ unreviewed/);
    await expect(rowB).toContainText("Participant 12");
    await expect(rowA).toContainText("Participant 01");
  });
});
