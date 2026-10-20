import { mkdirSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const API = process.env.SUMMARY_API ?? "http://127.0.0.1:8030/api/v1";
const OUT = "../../reports/ui/summary_check";
mkdirSync(OUT, { recursive: true });

// 500 characters: ordinary words, one 60-character unbroken token (wrapping) and markup that must stay text.
const NOTE = (() => {
  const head = "Seen at the cutoff; recheck after dinner. <b>not bold</b> " + "x".repeat(60) + " ";
  const words = "glucose rising after the evening meal, compare with the previous evening and the sensor gap. ";
  let s = head;
  while (s.length < 500) s += words;
  return s.slice(0, 500);
})();

async function patient(page: Page, mode: "dataset_replay" | "synthetic_demo", pick: (p: Record<string, unknown>) => boolean) {
  const r = await (await page.request.get(`${API}/patients?mode=${mode}&limit=200`)).json();
  return (r.items ?? []).find(pick) as { patient_id: string; display_alias: string; missing_fields: string[] } | undefined;
}

async function replayAt(page: Page, pid: string, mode: string, iso: string | null, testPeriod = false) {
  let start_at: string | null = null;
  if (testPeriod) {
    const d = await (await page.request.get(`${API}/patients/${pid}`)).json();
    start_at = d.evaluation_segments.find((s: { name: string }) => s.name === "test").start_at;
  }
  const s = await (await page.request.post(`${API}/replay/sessions`, { data: { patient_id: pid, mode, start_at, speed: 60 } })).json();
  if (iso) await page.request.post(`${API}/replay/sessions/${s.id}/control`, { data: { action: "seek", seek_to: iso } });
  await page.goto(`/app?session=${s.id}`);
  await expect(page.getByRole("group", { name: "Replay controls" })).toBeVisible();
  await expect(page.getByText(/Loading released observations/).first()).toBeHidden();
  return s.id as string;
}

async function openSummary(page: Page) {
  await page.getByRole("button", { name: "Review summary" }).click();
  const dlg = page.getByRole("dialog", { name: "Review summary" });
  await expect(dlg.getByRole("article", { name: "Review summary report" })).toBeVisible();
  return dlg;
}

async function exportPdf(page: Page, name: string) {
  await page.emulateMedia({ media: "print" });
  await page.pdf({ path: `${OUT}/${name}.pdf`, format: "A4", printBackground: true });
  await page.emulateMedia({ media: "screen" });
}

test("Participant 01, Day 9 20:38: a pending warning with a long review note; the copy stays frozen", async ({ page }) => {
  const p = await patient(page, "dataset_replay", (x) => x.display_alias === "Participant 01");
  test.skip(!p, "CGMacros not imported on this machine");
  const sid = await replayAt(page, p!.patient_id, "dataset_replay", "2000-01-11T20:38:00Z", true);
  await page.getByRole("button", { name: "Mark warning issued Day 9 · 20:30 as reviewed" }).click();
  const review = page.getByRole("dialog", { name: "Review research warning" });
  await review.getByLabel("Review note (optional)").fill(NOTE);
  await review.getByRole("button", { name: "Save review" }).click();
  await expect(review).toBeHidden();

  const dlg = await openSummary(page);
  await expect(dlg).toContainText("Replay cutoff");
  await expect(dlg).toContainText("Day 9 · 20:38");
  await expect(dlg).toContainText("not a medical report");
  await exportPdf(page, "p01-day9-2038-pending-long-note");
  await dlg.getByRole("button", { name: "Close" }).first().click();

  // the replay moves on within the same revision; the copy must not change
  for (let i = 0; i < 7; i++) await page.getByRole("button", { name: "Step 5 min forward" }).click();
  await expect.poll(async () => (await (await page.request.get(`${API}/replay/sessions/${sid}`)).json()).clock_at)
    .toContain("21:13");
  const again = await openSummary(page);
  await expect(again.getByText(/The replay has moved to Day 9 · 21:13 since this copy/)).toBeVisible();
  await expect(again.getByRole("article", { name: "Review summary report" })).toContainText("Day 9 · 20:38");
  await exportPdf(page, "p01-day9-2038-after-replay-moved");
});

test("Participant 12: stale glucose before the gap closes, then abstention", async ({ page }) => {
  const p = await patient(page, "dataset_replay", (x) => x.display_alias === "Participant 12");
  test.skip(!p, "CGMacros not imported on this machine");
  await replayAt(page, p!.patient_id, "dataset_replay", "2000-01-11T10:50:00Z", true);
  let dlg = await openSummary(page);
  await expect(dlg.getByRole("article")).toContainText("Stale");
  await exportPdf(page, "p12-day9-1050-stale");
  await dlg.getByRole("button", { name: "Close" }).first().click();

  await replayAt(page, p!.patient_id, "dataset_replay", "2000-01-11T11:45:00Z", true);
  dlg = await openSummary(page);
  await expect(dlg.getByRole("article")).toContainText(/Insufficient|not usable|none was usable/);
  await exportPdf(page, "p12-day9-1145-abstained");
});

test("synthetic participant with a missing health-record value", async ({ page }) => {
  const p = await patient(page, "synthetic_demo", (x) => Array.isArray(x.missing_fields) && (x.missing_fields as string[]).length > 0);
  test.skip(!p, "no synthetic participant with a missing profile value");
  await replayAt(page, p!.patient_id, "synthetic_demo", null);
  for (let i = 0; i < 6; i++) await page.getByRole("button", { name: "Step 1 h forward" }).click();
  const dlg = await openSummary(page);
  await expect(dlg.getByRole("article")).toContainText("Baseline profile");
  await exportPdf(page, `synthetic-missing-profile-${p!.display_alias.replace(/\W+/g, "-").toLowerCase()}`);
});
