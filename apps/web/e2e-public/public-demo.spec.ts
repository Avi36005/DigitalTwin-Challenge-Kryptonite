import { expect, test, type Browser, type Page } from "@playwright/test";

const API = "/api/v1";

async function startSynthetic(page: Page, patient: string) {
  await page.getByRole("button", { name: "New replay" }).first().click();
  const dialog = page.getByRole("dialog", { name: "New replay" });
  await expect(dialog.getByRole("radio", { name: /Recorded-data replay/ })).toBeDisabled();
  await dialog.getByLabel("Participant", { exact: true }).selectOption(patient);
  await dialog.getByRole("button", { name: "Start replay" }).click();
  await expect(page).toHaveURL(/session=/);
  return new URL(page.url()).searchParams.get("session")!;
}

async function visitor(browser: Browser) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return { ctx, page, errors };
}

test("a fresh visitor sees the public synthetic demonstration, labelled as such", async ({ browser }) => {
  const { ctx, page, errors } = await visitor(browser);
  const health = await (await page.request.get(`${API}/health`)).json();
  expect(health.public_demo).toBe(true);
  await page.goto("/");
  await expect(page.getByRole("note", { name: "Public synthetic demonstration" })).toBeVisible();
  await page.goto("/app");
  await expect(page.getByRole("note", { name: "Public synthetic demonstration" })).toBeVisible();
  // recorded data is refused by the backend, not just hidden
  expect((await page.request.get(`${API}/patients?mode=dataset_replay`)).status()).toBe(403);
  const pts = await (await page.request.get(`${API}/patients?limit=200`)).json();
  expect(pts.items.length).toBeGreaterThan(0);
  expect(pts.items.every((p: { mode: string }) => p.mode === "synthetic_demo")).toBe(true);
  expect(errors).toEqual([]);
  await ctx.close();
});

test("replay, forecasts and warnings work, and a refresh keeps the replay", async ({ browser }) => {
  const { ctx, page, errors } = await visitor(browser);
  await page.goto("/app");
  const sid = await startSynthetic(page, "SYN-B");
  for (let i = 0; i < 12; i++) await page.getByRole("button", { name: "Step 1 h forward" }).click();
  await expect(page.getByRole("region", { name: "30-minute forecast" }).getByText("mg/dL", { exact: true })).toBeVisible();
  const clock = (await (await page.request.get(`${API}/replay/sessions/${sid}`)).json()).clock_at;
  const alerts = await page.request.get(`${API}/replay/sessions/${sid}/alerts`);
  expect(alerts.status()).toBe(200);
  // the forecast is labelled as the synthetic demonstration model, never the evaluated fusion model
  const fc = await (await page.request.get(`${API}/replay/sessions/${sid}/forecast`)).json();
  expect(JSON.stringify(fc)).not.toContain("gt-primary-2026-10-13-fusion");
  await page.reload();
  await expect(page).toHaveURL(new RegExp(`session=${sid}`));
  await expect(page.getByRole("region", { name: "30-minute forecast" })).toBeVisible();
  expect((await (await page.request.get(`${API}/replay/sessions/${sid}`)).json()).clock_at).toBe(clock);
  await page.screenshot({ path: "../../reports/ui/22-public-demo-workspace.png" });
  expect(errors).toEqual([]);
  await ctx.close();
});

test("two simultaneous visitors cannot see or control each other's replays", async ({ browser }) => {
  const a = await visitor(browser);
  const b = await visitor(browser);
  await a.page.goto("/app");
  await b.page.goto("/app");
  const sa = await startSynthetic(a.page, "SYN-B");
  const sb = await startSynthetic(b.page, "SYN-C");
  const listB = await (await b.page.request.get(`${API}/replay/sessions`)).json();
  expect(listB.items.map((s: { id: string }) => s.id)).toEqual([sb]);
  const listA = await (await a.page.request.get(`${API}/replay/sessions`)).json();
  expect(listA.items.map((s: { id: string }) => s.id)).toEqual([sa]);
  for (const path of ["", "/events", "/forecast", "/forecasts", "/alerts", "/twin", "/profile"]) {
    expect((await b.page.request.get(`${API}/replay/sessions/${sa}${path}`)).status(), path).toBe(404);
  }
  expect((await b.page.request.post(`${API}/replay/sessions/${sa}/control`, { data: { action: "step", steps: 1 } })).status()).toBe(404);
  // B opening A's link gets an honest message, not A's replay
  await b.page.goto(`/app?session=${sa}`);
  await expect(b.page.getByText("This replay has expired or belongs to another browser.")).toBeVisible();
  await expect(b.page.getByRole("button", { name: "Start a new replay" })).toBeVisible();
  // A is unaffected
  expect((await a.page.request.post(`${API}/replay/sessions/${sa}/control`, { data: { action: "step", steps: 1 } })).status()).toBe(200);
  expect(a.errors).toEqual([]);
  expect(b.errors).toEqual([]);
  await a.ctx.close();
  await b.ctx.close();
});

test("evidence pages and their in-app links load", async ({ browser }) => {
  const { ctx, page, errors } = await visitor(browser);
  for (const path of ["/app/evidence", "/app/data-quality", "/app/participants", "/app/sessions", "/app/review-queue"]) {
    await page.goto(path);
    await expect(page.getByRole("note", { name: "Public synthetic demonstration" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
  await page.goto("/app/evidence");
  await expect(page.getByText(/synthetic demonstration model/i).first()).toBeVisible();
  await expect(page.locator("main .skeleton")).toHaveCount(0);  // every evidence block finished loading
  const hrefs = await page.locator("main a[href^='/']").evaluateAll((as) => [...new Set(as.map((a) => a.getAttribute("href")!))]);
  for (const href of hrefs) {
    const r = await page.request.get(href);
    expect(r.status(), href).toBe(200);
  }
  await page.screenshot({ path: "../../reports/ui/23-public-demo-evidence.png", fullPage: false });
  expect(errors).toEqual([]);
  await ctx.close();
});
