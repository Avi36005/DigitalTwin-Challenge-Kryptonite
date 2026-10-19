import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { API } from "./env";

// The README GIF (`npm run demo-gif`, needs ffmpeg). Participant 01, recorded CGMacros data, final test period: the
// replay steps 5 minutes at a time from Day 9 · 20:00 until a research warning is issued (20:30, outcome pending) and
// its outcome is knowable (onset 20:45). Values are those of reports/demo_sequence.md, Scene A; each key frame is
// checked before it is captured. Frames are screenshots cropped to the workspace (no sidebar, no scaling), so text
// stays sharp.
const OUT = resolve("../../reports/ui/demo-recorded-warning.gif");

test("README GIF: a research warning on recorded data, from issue to outcome", async ({ page }, info) => {
  test.setTimeout(180_000);
  const pts = await (await page.request.get(`${API}/patients?mode=dataset_replay&limit=200`)).json();
  const p = (pts.items ?? []).find((x: { display_alias: string }) => x.display_alias === "Participant 01");
  test.skip(!p, "CGMacros not imported on this machine");

  await page.goto("/app");
  await page.getByRole("button", { name: "Open recorded demo" }).click();
  await expect(page).toHaveURL(/session=/);
  const sid = new URL(page.url()).searchParams.get("session")!;
  await page.request.post(`${API}/replay/sessions/${sid}/control`, { data: { action: "seek", seek_to: "2000-01-11T20:00:00Z" } });
  await page.reload();
  const current = page.getByRole("region", { name: "Current glucose" });
  await expect(current).toContainText("92");

  const dir = info.outputPath("frames");
  mkdirSync(dir, { recursive: true });
  const frames: [string, number][] = [];
  const shot = async (seconds: number) => {
    await expect(page.getByText(/Loading released observations/).first()).toBeHidden();
    await page.evaluate(() => window.scrollTo(0, 0)); // the Step button scrolls; keep one view for every frame
    await page.waitForTimeout(400); // let the chart finish its transition
    const f = join(dir, `f${String(frames.length).padStart(2, "0")}.png`);
    await page.screenshot({ path: f });
    frames.push([f, seconds]);
  };
  const stepTo = async (hhmm: string) => {
    await page.getByRole("button", { name: "Step 5 min forward" }).click();
    await expect(page.getByText(`Day 9 · ${hhmm}`).first()).toBeVisible();
  };

  await shot(2.0);
  for (const t of ["20:05", "20:10", "20:15", "20:20", "20:25", "20:30"]) {
    await stepTo(t);
    await shot(0.7);
  }
  await stepTo("20:35");
  await expect(page.getByText("Outcome pending").first()).toBeVisible();
  await expect(page.getByText(/Fired by the (30|60)-min forecast \d+ mg\/dL ≥ \d+ trigger/).first()).toBeVisible();
  await shot(3.5);
  for (const t of ["20:40", "20:45", "20:50", "20:55", "21:00", "21:05"]) {
    await stepTo(t);
    await shot(0.7);
  }
  await stepTo("21:10");
  await expect(current).toContainText("190");
  await expect(page.getByText(/Onset 20:45/).first()).toBeVisible();
  await shot(5.0);

  // concat demuxer: each frame shown for its duration; the last file is repeated so its duration is honoured
  const list = join(dir, "frames.txt");
  writeFileSync(list, [...frames.map(([f, s]) => `file '${f}'\nduration ${s}`), `file '${frames.at(-1)![0]}'`].join("\n"));
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list, "-vf",
    "fps=10,crop=1040:1260:240:0,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle",
    "-loop", "0", OUT]);
});
