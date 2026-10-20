import { expect, test, type Page } from "@playwright/test";
import { API } from "./env";

const SHOTS = "../../reports/ui";

async function startReplay(page: Page, mode: "synthetic_demo" | "dataset_replay", patient: string, testPeriod = false) {
  const previous = new URL(page.url()).searchParams.get("session");
  await page.getByRole("button", { name: "New replay" }).first().click();
  const dialog = page.getByRole("dialog", { name: "New replay" });
  await dialog.getByRole("radio", { name: mode === "synthetic_demo" ? /Synthetic demonstration/ : /Recorded-data replay/ }).check();
  await dialog.getByLabel("Participant", { exact: true }).selectOption(patient);
  if (testPeriod) await dialog.getByRole("radio", { name: /Final test period/ }).check();
  await dialog.getByRole("button", { name: "Start replay" }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("session")).not.toBe(previous);
  await expect(page).toHaveURL(/session=/);
  return new URL(page.url()).searchParams.get("session")!;
}

async function session(page: Page, sid: string) {
  return (await page.request.get(`${API}/replay/sessions/${sid}`)).json();
}

async function byAlias(page: Page, alias: string) {
  const pts = await (await page.request.get(`${API}/patients?mode=dataset_replay&limit=200`)).json();
  return (pts.items ?? []).find((x: { display_alias: string }) => x.display_alias === alias);
}

test("clinician replay journey on a synthetic participant", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/app");
  const sid = await startReplay(page, "synthetic_demo", "SYN-B");
  await expect(page.getByText("Synthetic demonstration").first()).toBeVisible();

  // step forward through observations
  for (let i = 0; i < 12; i++) await page.getByRole("button", { name: "Step 1 h forward" }).click();
  await expect.poll(async () => (await session(page, sid)).clock_at).toContain("2000-01-03T12");
  await expect(page.getByRole("region", { name: "30-minute forecast" }).getByText("mg/dL", { exact: true })).toBeVisible();

  // play then pause: the backend clock advances
  const before = (await session(page, sid)).clock_at;
  await page.getByRole("button", { name: "Play replay" }).click();
  await page.waitForTimeout(2500);
  await page.getByRole("button", { name: "Pause replay" }).click();
  await expect.poll(async () => (await session(page, sid)).status).toBe("paused");
  expect((await session(page, sid)).clock_at > before).toBeTruthy();

  // single step
  const c1 = (await session(page, sid)).clock_at;
  await page.getByRole("button", { name: "Step 5 min forward" }).click();
  await expect.poll(async () => (await session(page, sid)).clock_at).not.toBe(c1);

  // acknowledge a research warning (local only)
  const ack = page.getByRole("button", { name: /Mark warning issued .* as reviewed/ }).first();
  if (await ack.isVisible()) {
    await ack.click();
    await page.getByRole("dialog", { name: "Review research warning" }).getByRole("button", { name: "Save review" }).click();
    await expect(page.getByText(/no message was sent/i).first()).toBeVisible();
  }
  await page.screenshot({ path: `${SHOTS}/01-twin-workspace-synthetic.png` });

  // seek backward with the keyboard: new revision, no future state
  const rev = (await session(page, sid)).revision;
  const slider = page.getByLabel("Seek replay time");
  await slider.focus();
  await page.keyboard.press("Home");
  await expect(page.getByText(/Seek to Day 1/)).toBeVisible();
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await session(page, sid)).revision).toBe(rev + 1);
  const s2 = await session(page, sid);
  const fc = await (await page.request.get(`${API}/replay/sessions/${sid}/forecasts?order=desc&limit=500`)).json();
  for (const f of fc.items) expect(f.as_of <= s2.clock_at).toBeTruthy();
  const al = await (await page.request.get(`${API}/replay/sessions/${sid}/alerts`)).json();
  for (const a of al.items) expect(a.issued_at <= s2.clock_at).toBeTruthy();
  await expect(page.getByText("Day 1 · 00:00").first()).toBeVisible();

  // reset
  await page.getByRole("button", { name: "Reset to start of recording" }).click();
  await expect.poll(async () => (await session(page, sid)).status).toBe("ready");

  // switch participants from the participant list
  await page.getByRole("link", { name: "Participants", exact: true }).click();
  await expect(page).toHaveURL(/\/app\/participants$/);
  await page.getByRole("button", { name: /twin for Synthetic Participant A$/ }).click();
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Synthetic Participant A");
  const sidA = new URL(page.url()).searchParams.get("session")!;
  expect(sidA).not.toBe(sid);

  // reopen the earlier session from the sidebar's recent replays
  await page.getByRole("link", { name: /Synthetic Participant B/ }).first().click();
  await expect(page).toHaveURL(new RegExp(`session=${sid}`));
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Synthetic Participant B");

  // sidebar collapse and expand
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(page.locator(".shell")).toHaveAttribute("data-collapsed", "true");
  await page.getByRole("button", { name: "Expand sidebar" }).click();
  await expect(page.locator(".shell")).toHaveAttribute("data-collapsed", "false");

  // command search (keyboard)
  await page.locator("body").press(process.platform === "darwin" ? "Meta+k" : "Control+k");
  const search = page.getByRole("combobox", { name: /Search participants/ });
  await expect(search).toBeFocused();
  await search.fill("Participant C");
  await expect(page.getByRole("listbox", { name: "Results" }).getByRole("option", { name: /Synthetic Participant C/ })).toBeVisible();
  await search.fill("zzz-no-match");
  await expect(page.getByText(/No matches/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(search).toBeHidden();

  expect(errors).toEqual([]);
});

test("missing-data, stale and abstention states are explicit", async ({ page }) => {
  await page.goto("/app");
  await startReplay(page, "synthetic_demo", "SYN-E");
  await page.getByRole("button", { name: "Step 5 min forward" }).click();
  await expect(page.getByRole("region", { name: "60-minute forecast" }).getByText("Not available")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Review and guardrails" }).getByText("Insufficient information")).toBeVisible();
  // the guardrails readout says why there is no forecast instead of showing one
  await expect(page.getByRole("region", { name: "Guardrails" })).toContainText(/Abstained: no forecast is shown|No forecast yet/);
  // sensor-gap participant: seek into a long gap to see stale data
  await startReplay(page, "synthetic_demo", "SYN-D");
  const slider = page.getByLabel("Seek replay time");
  const sid = new URL(page.url()).searchParams.get("session")!;
  await page.request.post(`${API}/replay/sessions/${sid}/control`, { data: { action: "seek", seek_to: "2000-01-04T09:30:00Z" } });
  await page.reload();
  await expect(slider).toBeVisible();
  await expect(page.getByText(/Stale/).first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/02-missing-and-stale-data.png` });
});

test("recorded-data replay in the final test period shows prediction ranges with their target coverage", async ({ page, request }) => {
  const pts = await (await request.get(`${API}/patients?mode=dataset_replay`)).json();
  test.skip(!pts.items?.length, "CGMacros not imported on this machine");
  const p = pts.items.find((x: { eligible_for_primary_analysis: boolean }) => x.eligible_for_primary_analysis);
  await page.goto("/app");
  await startReplay(page, "dataset_replay", p.patient_id, true);
  await page.getByRole("button", { name: "Step 1 h forward" }).click();
  await expect(page.getByText("Prediction range · target coverage 80%")).toBeVisible();
  await page.getByRole("button", { name: "Details", exact: true }).click();
  await expect(page.getByText(/Measured coverage on the final test period/)).toBeVisible();
  await expect(page.getByText("Recorded-data replay").first()).toBeVisible();
  await expect(page.getByText(/Loading released observations/).first()).toBeHidden();
  await expect(page.getByRole("region", { name: "Current glucose" }).getByText("mg/dL", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/03-forecast-with-interval-recorded.png` });
  // the fusion model's guardrails: profile gate passed, bounded correction, range with its measured coverage
  const guards = page.getByRole("region", { name: "Guardrails" });
  await expect(guards).toContainText("Every value the model reads was known at this time");
  await expect(guards).toContainText("capped at ±25 mg/dL");
  await expect(guards).toContainText(/Under target: [\d.]+% \/ [\d.]+% measured vs 80% target|80% target coverage/);
  await expect(guards).toContainText("readings in the hour before the replay clock");
  await page.getByRole("button", { name: "View forecast details" }).click();
  await expect(page.getByRole("dialog", { name: "Forecast details" })).toContainText("Final test period (later recordings from a participant represented in training)");
  await page.waitForTimeout(400); // let the drawer finish its short slide-in
  await page.screenshot({ path: `${SHOTS}/04-forecast-evidence-dialog.png` });
  await page.keyboard.press("Escape");
  // the full list on the evidence page, reached from the readout
  await guards.getByRole("link", { name: "All safety guardrails" }).click();
  await expect(page).toHaveURL(/\/app\/evidence#safety-guardrails$/);
  const heading = page.getByRole("heading", { name: "Safety guardrails" });
  await expect(heading).toBeInViewport();
  await expect(page.locator("#safety-guardrails dt")).toHaveCount(11);
  await expect(page.getByText(/^Replay started for/)).toBeHidden({ timeout: 6000 }); // toasts close after 3.2 s
  await page.screenshot({ path: `${SHOTS}/19-safety-guardrails.png` });
});

test("model evidence and data quality pages render recorded results", async ({ page }) => {
  await page.goto("/app/evidence");
  await expect(page.getByRole("heading", { name: "Model evidence" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Comparison" }).or(page.getByText(/Evaluation not run|Evaluation unavailable/))).toBeVisible();
  const completed = await page.getByRole("heading", { name: "Comparison" }).isVisible();
  if (completed) {
    // a serving model chosen under an eligibility constraint is shown with its disclosures (from the API, not typed in)
    if (await page.getByText("Fusion-constrained result.").isVisible()) {
      await expect(page.getByText(/have not established that profile features improve forecasting for unseen patients/)).toBeVisible();
      await expect(page.getByText(/after the test segment had already been inspected/)).toBeVisible();
      await expect(page.getByRole("link", { name: "What this does and does not show" })).toBeVisible();
      await page.getByRole("heading", { name: "Results at a glance" }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SHOTS}/18-model-evidence-fusion-disclosures.png` });
    }
    await expect(page.getByText("Serving pipeline").first()).toBeVisible();
    await expect(page.getByText(/is the selected replay model\. Final-test results on later recordings of the same \d+ participants, not new patients/)).toBeVisible();
    await expect(page.getByLabel("Final-test results of the serving pipeline")).toBeVisible();
    await expect(page.getByText(/accuracy percentage/)).toBeVisible(); // MAE is explained, never called accuracy
    await page.getByRole("button", { name: "Show all configurations" }).click();
    await expect(page.getByRole("columnheader", { name: "Forecast availability" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: /^Coverage$/ })).toHaveCount(0);
    await page.getByRole("button", { name: /Sort by MAE 60 min/ }).click();
    await expect(page.getByRole("columnheader", { name: /MAE 60 min/ })).toHaveAttribute("aria-sort", "ascending");
    await page.getByRole("tab", { name: "Validation (selection)" }).click();
    await expect(page.getByRole("tab", { name: "Validation (selection)" })).toHaveAttribute("aria-selected", "true");
  } else {
    await expect(page.getByText(/Evaluation not run|unavailable/)).toBeVisible();
  }
  await page.screenshot({ path: `${SHOTS}/05-model-evidence.png` });
  await page.goto("/app/data-quality");
  await expect(page.getByRole("heading", { name: "Per-participant coverage" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/06-data-quality.png` });
  await page.goto("/app/participants");
  await page.getByLabel("Search participants").fill("nobody-matches-this");
  await expect(page.getByText("No participants match these filters")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).first().click();
  await expect(page.getByText(/\d+ of \d+ match/)).toBeVisible();
});

test("research evidence is separate from the serving model, and data scale is audited", async ({ page }) => {
  // decide from the experiment list the page itself receives, not from a render that may not have happened yet
  const listed = page.waitForResponse((r) => /\/api\/v1\/evaluations(\?|$)/.test(r.url()));
  await page.goto("/app/evidence");
  const list = (await (await listed).json()) as { items: { experiment_id: string; status: string }[] };
  await expect(page.getByText(/Serving model:/)).toBeVisible();
  const hasResearch = list.items.some((x) => x.experiment_id === "gt-nested-2026-10-12-v1" && x.status === "completed");
  test.skip(!hasResearch, "no assessed research experiment on this machine");
  const select = page.getByLabel("Evidence");
  await select.selectOption({ label: "Nested participant benchmark + external cohort" });
  await expect(page).toHaveURL(/experiment=gt-nested-2026-10-12-v1/);
  await expect(page.getByText(/a different experiment .* did not change the serving model/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Results on held-out people" })).toBeVisible();
  await expect(page.getByText(/New-participant research evidence/)).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Forecast availability" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/14-research-evidence.png`, fullPage: false });
  await page.getByText("Research warnings").click();
  await expect(page.getByRole("columnheader", { name: /False alarms per observed forecastable day/ })).toBeVisible();
  await page.getByRole("tab", { name: "15-minute · portable" }).click();
  await expect(page.getByRole("tab", { name: "15-minute · portable" })).toHaveAttribute("aria-selected", "true");
  await page.getByText("External cohort (ShanghaiT2DM)").click();
  await page.screenshot({ path: `${SHOTS}/15-research-portable-external.png`, fullPage: false });
  await page.goto("/app/data-quality");
  await expect(page.getByRole("heading", { name: "Data sources and scale" })).toBeVisible();
  const inv = page.getByRole("region", { name: "Dataset inventory" });
  await expect(inv.getByText("ShanghaiT2DM")).toBeVisible();
  await expect(inv.getByText("Access required")).toBeVisible();
  await expect(page.getByText(/never GlucoTwin\s+counts/)).toBeVisible();
  await inv.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/16-data-sources.png`, fullPage: false });
});

test("research after the demo model is tagged, and says when it was not run here", async ({ page }) => {
  const sums = (await (await page.request.get(`${API}/research-summaries`)).json()) as {
    items: { decision_id: string; status: string }[] };
  await page.goto("/app/evidence?experiment=gt-nested-2026-10-12-v1");
  const section = page.getByRole("region", { name: "Research after the demo model (20 Oct)" });
  await expect(section).toBeVisible();
  const rows = section.getByRole("list", { name: "Research after the demo model" }).locator(":scope > li");
  await expect(rows).toHaveCount(4);
  await expect(section.getByText("Not the demo model")).toHaveCount(4);
  const run = sums.items.filter((x) => x.status === "available").map((x) => x.decision_id);
  await expect(section.getByText(/Not run on this installation/)).toHaveCount(4 - run.length);
  if (run.includes("D-046")) {
    const d046 = rows.filter({ hasText: "D-046" });
    await expect(d046.locator("li", { hasText: "Prediction ranges calibrated on more people" })).toContainText("Shown");
    await expect(d046.locator("li", { hasText: "Earlier two-hour warning" })).toContainText("Not shown");
    await expect(d046.locator("li", { hasText: "starting correction" })).toContainText("Not shown");
  }
  if (run.includes("D-044")) await expect(rows.filter({ hasText: "D-044" })).toContainText("Negative result");
  await section.scrollIntoViewIfNeeded();
  await section.screenshot({ path: `${SHOTS}/21-research-after-demo-model.png` });
});

test.describe("mobile research evidence", () => {
  test("research after the demo model fits a phone", async ({ page }) => {
    await page.goto("/app/evidence?experiment=gt-nested-2026-10-12-v1");
    await expect(page.getByRole("region", { name: "Research after the demo model (20 Oct)" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
  test.use({ viewport: { width: 390, height: 844 } });
  test("tables scroll inside their region instead of clipping the page", async ({ page }) => {
    const rep = await (await page.request.get(`${API}/research/gt-nested-2026-10-12-v1`)).json();
    test.skip(rep.status !== "completed", "no research report on this machine");
    await page.goto("/app/evidence?experiment=gt-nested-2026-10-12-v1");
    await expect(page.getByRole("heading", { name: "Results on held-out people" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${SHOTS}/17-research-evidence-mobile.png`, fullPage: false });
  });
});

test("API failure is reported and never replaced with example data", async ({ page }) => {
  await page.route("**/api/v1/**", (route) => route.abort());
  await page.goto("/app");
  await expect(page.getByRole("alert")).toContainText("not reachable");
  // the landing page still works without the API
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: /See the next chapter of a glucose/ })).toBeVisible();
  await expect(page.getByRole("figure").getByRole("img")).toBeVisible();
});

test.describe("recording resolution (1920×1080) — demo sequence on recorded data", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  async function seek(page: Page, sid: string, iso: string) {
    await page.request.post(`${API}/replay/sessions/${sid}/control`, { data: { action: "seek", seek_to: iso } });
    await page.reload();
    await expect(page.getByRole("group", { name: "Replay controls" })).toBeVisible();
    await expect(page.getByText(/Loading released observations/).first()).toBeHidden();
  }

  test("Participant 01: a warning is pending until its outcome is knowable", async ({ page }) => {
    const p = await byAlias(page, "Participant 01");
    test.skip(!p, "CGMacros not imported on this machine");
    await page.goto("/app");
    const sid = await startReplay(page, "dataset_replay", p.patient_id, true);
    await seek(page, sid, "2000-01-11T09:24:00Z");
    await expect(page.getByRole("region", { name: "Current glucose" })).toContainText("158"); // reports/demo_sequence.md
    await expect(page.getByText("Outcome pending").first()).toBeVisible();
    // the warning names the forecast that fired it and the trigger level, not "above 180"
    await expect(page.getByText(/Fired by the (30|60)-min forecast \d+ mg\/dL ≥ \d+ trigger/).first()).toBeVisible();
    await expect(page.getByText(/forecasts a new sustained episode above 180/)).toHaveCount(0);
    // chart and control text stay legible at recording resolution
    const chart = page.getByRole("figure", { name: /Observed glucose/ });
    await expect(chart).toBeVisible();
    const sizes = await chart.evaluate((fig) => Array.from(fig.querySelectorAll("svg text"))
      .filter((t) => /^\d{2,3}(:\d{2})?$/.test((t.textContent ?? "").trim()))
      .map((t) => parseFloat(getComputedStyle(t).fontSize)));
    expect(sizes.length).toBeGreaterThan(4); // axis tick labels (times and mg/dL values)
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(12);
    await page.screenshot({ path: `${SHOTS}/08-recording-1920-warning-pending.png` });

    // review the pending warning with a note: cancel saves nothing; save keeps the note (as text) across a reload
    const reviewBtn = page.getByRole("button", { name: /Mark warning issued .* as reviewed/ }).first();
    const dialog = page.getByRole("dialog", { name: "Review research warning" });
    await reviewBtn.click();
    await expect(dialog).toContainText("Participant 01 · issued");
    await expect(dialog).toContainText("Outcome pending");
    await dialog.getByLabel("Review note (optional)").fill("Draft that must not be saved");
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("Draft that must not be saved")).toHaveCount(0);
    await reviewBtn.click();
    await expect(dialog.getByLabel("Review note (optional)")).toHaveValue(""); // a cancelled draft is not carried over
    const note = "Checked trace <b>no sensor issue</b>; discuss at visit.";
    await dialog.getByLabel("Review note (optional)").fill(note);
    await expect(dialog).toContainText(`${note.length} / 500`);
    await dialog.getByRole("button", { name: "Save review" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText(note).first()).toBeVisible();
    await page.reload();
    await expect(page.getByText(note).first()).toBeVisible(); // saved in the local API, not only in the page
    await expect(page.locator(".warn b")).toHaveCount(0); // rendered as text, never HTML
    await seek(page, sid, "2000-01-11T11:24:00Z");
    await expect(page.getByText("No onset (false alarm)").first()).toBeVisible();
  });

  test("Participant 01: a forecast's outcome appears only when the replay clock reaches its target time", async ({ page }) => {
    const p = await byAlias(page, "Participant 01");
    test.skip(!p, "CGMacros not imported on this machine");
    await page.goto("/app");
    const sid = await startReplay(page, "dataset_replay", p.patient_id, true);
    await seek(page, sid, "2000-01-11T20:35:00Z");
    await page.getByRole("button", { name: "View forecast details" }).click();
    const drawer = page.getByRole("dialog", { name: "Forecast details" });
    await expect(drawer).toContainText("Issued at Day 9 · 20:35");
    const outcome = drawer.getByRole("region", { name: "Outcome" });
    await expect(outcome).toContainText("Outcome not yet observed at this replay time.");
    await expect(outcome).not.toContainText(/observed reading \d/);
    await page.keyboard.press("Escape");
    // step past the 30-minute target (21:05); the opened forecast stays pinned
    for (let i = 0; i < 7; i++) await page.getByRole("button", { name: "Step 5 min forward" }).click();
    await expect(page.getByText("Day 9 · 21:10").first()).toBeVisible();
    await page.getByRole("button", { name: "View forecast details" }).click();
    await expect(drawer).toContainText("Issued at Day 9 · 20:35");
    await expect(outcome).toContainText(/30 min \(for 21:05\): observed reading \d+ mg\/dL at 21:0\d/);
    await expect(outcome).toContainText(/60 min \(for 21:35\): Outcome not yet observed at this replay time\./);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Step 1 h forward" }).click();
    await expect(page.getByText("Day 9 · 22:10").first()).toBeVisible();
    await page.getByRole("button", { name: "View forecast details" }).click();
    await expect(outcome).toContainText(/60 min \(for 21:35\): observed reading \d+ mg\/dL/);
    await expect(outcome).toContainText(/The patient correction (moved this forecast [\d.]+ mg\/dL (closer to|further from)|made no difference)/);
    await outcome.scrollIntoViewIfNeeded();
    await drawer.screenshot({ path: `${SHOTS}/25-forecast-outcome.png` });
    console.log("OUTCOME_TEXT::" + (await outcome.innerText()).replace(/\n/g, " | "));
    await page.keyboard.press("Escape");
  });

  test("Participant 12: a real sensor gap makes the forecast stale, then the twin abstains", async ({ page }) => {
    const p = await byAlias(page, "Participant 12");
    test.skip(!p, "CGMacros not imported on this machine");
    await page.goto("/app");
    const sid = await startReplay(page, "dataset_replay", p.patient_id, true);
    await seek(page, sid, "2000-01-11T10:50:00Z");
    const current = page.getByRole("region", { name: "Current glucose" });
    await expect(current).toContainText("391"); // last reading 10:29 (reports/demo_sequence.md)
    await expect(current.getByText(/Stale/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/09-recording-1920-recorded-gap-stale.png` });
    await seek(page, sid, "2000-01-11T11:45:00Z");
    await expect(page.getByRole("region", { name: "60-minute forecast" }).getByText("Not available")).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Review and guardrails" }).getByText("Insufficient information")).toBeVisible();
    await expect(page.getByText(/readings? in the last hour; more recent history is required/)).toBeVisible();
    await expect(page.getByRole("region", { name: "Current glucose" })).toContainText("195"); // the reading stays visible
    await page.screenshot({ path: `${SHOTS}/13-insufficient-history-recorded.png` });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBe(false);
  });
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("the review status sits directly under the forecast numbers, above the chart", async ({ page }) => {
    await page.goto("/app");
    await startReplay(page, "synthetic_demo", "SYN-B");
    await page.getByRole("button", { name: "Step 1 h forward" }).click();
    const strip = page.locator(".review-strip");
    await expect(strip).toBeVisible();
    await expect(strip.getByRole("link", { name: "Details" })).toHaveAttribute("href", "#review-title");
    const stripBox = await strip.boundingBox();
    const chartBox = await page.getByRole("heading", { name: "Glucose trace" }).boundingBox();
    expect(stripBox!.y).toBeLessThan(chartBox!.y);
    // a long participant name truncates: the page does not scroll sideways and "New replay" stays on screen
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
    const newBox = await page.locator(".topbar__mobile-action").getByRole("button", { name: "New replay" }).boundingBox();
    expect(newBox!.x + newBox!.width).toBeLessThanOrEqual(390);
    // forecast details fit the drawer; only the estimate table may scroll, inside its own region
    await page.getByRole("button", { name: "View forecast details" }).click();
    const details = page.getByRole("dialog", { name: "Forecast details" });
    await expect(details).toBeVisible();
    await page.waitForTimeout(400); // let the drawer finish its short slide-in
    const fit = await details.evaluate((d) => {
      const body = d.querySelector(".dialog__body") as HTMLElement;
      return { body: body.scrollWidth - body.clientWidth, drawer: d.getBoundingClientRect().right - window.innerWidth };
    });
    expect(fit.body).toBeLessThanOrEqual(1);
    expect(fit.drawer).toBeLessThanOrEqual(1);
  });

  test("navigation drawer traps focus, closes on Escape and restores focus", async ({ page }) => {
    await page.goto("/app");
    const trigger = page.getByRole("button", { name: "Open navigation" });
    await trigger.click();
    const drawer = page.getByRole("dialog", { name: "Navigation" });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("link", { name: "Model evidence" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(trigger).toBeFocused();
    // navigating from the drawer closes it
    await trigger.click();
    await drawer.getByRole("link", { name: "Participants", exact: true }).click();
    await expect(drawer).toBeHidden();
    await expect(page.getByRole("heading", { level: 1, name: "Participants" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBe(false);
    const sessions = await (await page.request.get(`${API}/replay/sessions`)).json();
    if (sessions.items.length) {
      await page.goto(`/app?session=${sessions.items[0].id}`);
      await expect(page.getByRole("group", { name: "Replay controls" })).toBeVisible();
      await page.screenshot({ path: `${SHOTS}/07-mobile-workspace.png` });
    }
  });

  test("landing page on a phone: brand and Open workspace stay visible, menu works", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: "Open workspace" }).first()).toBeVisible();
    await page.getByRole("button", { name: "Open menu" }).click();
    await expect(page.getByRole("link", { name: "How it works" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "Open menu" })).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
    await page.screenshot({ path: `${SHOTS}/11-landing-phone.png`, fullPage: true });
  });
});

test.describe("landing page and route compatibility", () => {
  test("landing actions lead into the workspace and evidence", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/See the next chapter of a glucose\s+trace\./);
    await expect(page.getByRole("navigation", { name: "Workspace" })).toHaveCount(0); // no hidden sidebar in the landing DOM
    await expect(page.getByText("Research prototype; not for clinical decisions.")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/10-landing-desktop.png` });
    await page.getByRole("link", { name: "View model evidence" }).click();
    await expect(page).toHaveURL(/\/app\/evidence$/);
    await page.goBack();
    await expect(page).toHaveURL(/:\d+\/$/);
    await page.getByRole("link", { name: "Open workspace" }).first().click();
    await expect(page).toHaveURL(/\/app$/);
    await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/12-overview.png` });
  });

  test("an old /?session= link resumes the same session without resetting its clock", async ({ page, request }) => {
    const created = await (await request.post(`${API}/replay/sessions`, { data: { patient_id: "SYN-C", mode: "synthetic_demo" } })).json();
    await request.post(`${API}/replay/sessions/${created.id}/control`, { data: { action: "seek", seek_to: "2000-01-03T09:30:00Z" } });
    const before = await (await request.get(`${API}/replay/sessions/${created.id}`)).json();
    await page.goto("/app");
    await page.goto(`/?session=${created.id}`);
    await expect(page).toHaveURL(new RegExp(`/app\\?session=${created.id}$`));
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Synthetic Participant C");
    const after = await (await request.get(`${API}/replay/sessions/${created.id}`)).json();
    expect(after.revision).toBe(before.revision);
    expect(after.clock_at).toBe(before.clock_at);
    await page.goBack(); // replace navigation: Back returns to the previous page, not into a redirect loop
    await expect(page).toHaveURL(/\/app$/);
  });

  test("old page URLs redirect with their query; an unknown session shows an error, not another participant", async ({ page }) => {
    await page.goto("/participants?focus=SYN-A");
    await expect(page).toHaveURL(/\/app\/participants\?focus=SYN-A$/);
    await page.goto("/sessions");
    await expect(page).toHaveURL(/\/app\/sessions$/);
    await page.goto("/app?session=does-not-exist");
    await expect(page.getByText("Replay session not found")).toBeVisible();
  });

  test("a new page starts at its heading", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 420 }); // short window: the page scrolls even without CGMacros
    await page.goto("/app/data-quality");
    await expect(page.getByRole("heading", { name: "Per-participant coverage" })).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(100);
    await page.getByRole("link", { name: "Model evidence" }).first().click();
    await expect(page.getByRole("heading", { level: 1, name: "Model evidence" })).toBeInViewport();
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
  });
});

// Last, so the sessions they create do not appear in the overview screenshot above.
test.describe("first replay experience on recorded data", () => {
  test("Open recorded demo starts Participant 01 at the final test period", async ({ page }) => {
    const p = await byAlias(page, "Participant 01");
    test.skip(!p, "CGMacros not imported on this machine");
    const detail = await (await page.request.get(`${API}/patients/${p.patient_id}`)).json();
    const testStart = detail.evaluation_segments.find((s: { name: string }) => s.name === "test").start_at;
    await page.goto("/app");
    const previous = new URL(page.url()).searchParams.get("session");
    await page.getByRole("button", { name: "Open recorded demo" }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get("session")).not.toBe(previous);
    const sid = new URL(page.url()).searchParams.get("session")!;
    const s = await session(page, sid);
    expect(s.patient_id).toBe(p.patient_id);
    expect(Date.parse(s.clock_at)).toBe(Date.parse(testStart));
    await expect(page.getByRole("region", { name: "Current glucose" })).not.toContainText("No reading yet");
  });

  test("a replay from the start of a recording offers the final test period", async ({ page }) => {
    const p = await byAlias(page, "Participant 01");
    test.skip(!p, "CGMacros not imported on this machine");
    const detail = await (await page.request.get(`${API}/patients/${p.patient_id}`)).json();
    const testStart = detail.evaluation_segments.find((s: { name: string }) => s.name === "test").start_at;
    await page.goto("/app");
    const sid = await startReplay(page, "dataset_replay", p.patient_id);
    await expect(page.getByText("No readings released yet.")).toBeVisible();
    await page.getByRole("button", { name: "Go to final test period" }).click();
    await expect.poll(async () => Date.parse((await session(page, sid)).clock_at)).toBe(Date.parse(testStart));
    await expect(page.getByText("No readings released yet.")).toBeHidden();
  });
});

test.describe("review summary", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("Participant 01: a frozen review summary with its cutoff and model, printing only the report", async ({ page }, info) => {
    const p = await byAlias(page, "Participant 01");
    test.skip(!p, "CGMacros not imported on this machine");
    await page.goto("/app");
    const sid = await startReplay(page, "dataset_replay", p.patient_id);
    await page.request.post(`${API}/replay/sessions/${sid}/control`, { data: { action: "seek", seek_to: "2000-01-11T20:35:00Z" } });
    await page.reload();
    await expect(page.getByText(/Loading released observations/).first()).toBeHidden();
    await page.getByRole("button", { name: "Review summary" }).click();
    const dialog = page.getByRole("dialog", { name: "Review summary" });
    const report = dialog.getByRole("article", { name: "Review summary report" });
    await expect(report).toContainText("Day 9 · 20:35 (replay time)");
    await expect(report).toContainText("Research replay review — not a medical report");
    await expect(report).toContainText("lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion");
    await expect(report).toContainText("Final test period (later recordings from a participant represented in training)");
    await expect(report).toContainText("Outcome pending");
    // the copy is frozen: stepping the replay on does not change it
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Step 1 h forward" }).click();
    await expect(page.getByText("Day 9 · 21:35").first()).toBeVisible();
    await page.getByRole("button", { name: "Review summary" }).click();
    await expect(dialog.getByText(/The replay has moved to Day 9 · 21:35 since this copy/)).toBeVisible();
    await expect(report).toContainText("Day 9 · 20:35 (replay time)");
    // print: only the report, not the app shell or the dialog
    await page.emulateMedia({ media: "print" });
    await expect(page.locator(".review-print-root")).toBeVisible();
    await expect(page.locator("#root")).toBeHidden();
    await page.screenshot({ path: info.outputPath("review-print.png"), fullPage: true });
    await page.emulateMedia({ media: "screen" });
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("button", { name: "Review summary" })).toBeFocused();
  });
});

test.describe("review queue", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("replays with unreviewed warnings come first; counts stop at each replay's clock", async ({ page }) => {
    const p = await byAlias(page, "Participant 01");
    test.skip(!p, "CGMacros not imported on this machine");
    await page.goto("/app");
    const sid = await startReplay(page, "dataset_replay", p.patient_id, true);
    await page.request.post(`${API}/replay/sessions/${sid}/control`, { data: { action: "seek", seek_to: "2000-01-11T20:38:00Z" } });
    const alerts = await (await page.request.get(`${API}/replay/sessions/${sid}/alerts`)).json();
    const clock = Date.parse(alerts.clock_at);
    const issued: number[] = alerts.items.map((a: { issued_at: string }) => Date.parse(a.issued_at));
    expect(issued.length).toBeGreaterThan(0);
    expect(Math.max(...issued)).toBeLessThanOrEqual(clock); // nothing after the replay clock

    await page.getByRole("link", { name: "Review queue" }).click();
    await expect(page).toHaveURL(/\/app\/review-queue$/);
    await expect(page.getByRole("heading", { name: "Review queue", level: 1 })).toBeVisible();
    await expect(page.getByText(/Research demonstration\. Administrative review order, not a risk ranking or triage/)).toBeVisible();
    const table = page.getByRole("table", { name: "Review queue" });
    const row = table.getByRole("row").filter({ has: page.locator(`a[href="/app?session=${sid}"]`) }).first();
    await expect(row).toContainText(`${issued.length} unreviewed0 reviewed`);
    await expect(row).toContainText("Day 9 · 20:30");
    await expect(row).toContainText("Outcome pending");
    await expect(row).toContainText(/Fired by the (30|60)-min forecast \d+ mg\/dL/);
    await expect(row).toHaveAttribute("data-unreviewed", "true");
    // every row with unreviewed warnings is listed before every row without
    const flags = await table.getByRole("row").evaluateAll((rs) => rs.slice(1).map((r) => r.getAttribute("data-unreviewed") === "true"));
    expect(flags.indexOf(false) === -1 || flags.lastIndexOf(true) < flags.indexOf(false)).toBe(true);
    await expect(page.getByText(/^Replay started for/)).toBeHidden({ timeout: 6000 }); // toasts close after 3.2 s
    await page.screenshot({ path: `${SHOTS}/20-review-queue.png` });

    // review the latest warning in the workspace; the queue then counts it as reviewed
    await row.getByRole("link", { name: "Open replay for Participant 01" }).click();
    await expect(page).toHaveURL(new RegExp(`session=${sid}`));
    // wait until the workspace shows the seeked revision; a warning from an older revision is refused, not saved
    await expect(page.getByText(/Loading released observations/).first()).toBeHidden();
    // the workspace explains the latest forecast from its own recorded components, at this replay clock
    const explain = page.getByRole("region", { name: "How the twin reached this forecast" });
    await expect(explain.getByRole("table", { name: "Forecast components" }).getByRole("row")).toHaveCount(3);
    await expect(explain).toContainText("Bounded at ±25 mg/dL");
    await expect(explain).toContainText("Health record: read by this model");
    await expect(explain).toContainText(/research warnings?: /);
    await page.getByRole("button", { name: "Mark warning issued Day 9 · 20:30 as reviewed" }).click();
    const dialog = page.getByRole("dialog", { name: "Review research warning" });
    await dialog.getByRole("button", { name: "Save review" }).click();
    await expect(dialog).toBeHidden();
    await expect(explain.getByRole("table", { name: "Forecast components" })).toBeVisible();
    await explain.scrollIntoViewIfNeeded();
    await explain.screenshot({ path: `${SHOTS}/24-twin-explanation.png` });
    await page.goto("/app/review-queue");
    await expect(row).toContainText(`${issued.length - 1} unreviewed1 reviewed`);
  });

  test("fits a 390 px phone without horizontal scrolling", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/app/review-queue");
    await expect(page.getByRole("heading", { name: "Review queue", level: 1 })).toBeVisible();
    await expect(page.getByRole("table", { name: "Review queue" }).or(page.getByText("Nothing to review yet"))).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
});
