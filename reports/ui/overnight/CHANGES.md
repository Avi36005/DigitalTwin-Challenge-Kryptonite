# Overnight UI polish (sprint-ui), 21–22 Oct 2026

Before: `fd87ca2`. After: branch `sprint-ui`. Captures: `before/` and `after/`, made by
`apps/web/e2e-shots/overnight-shots.spec.ts`. Both sets use fresh API storage, the same two replays (Participant 01 at
Day 9 · 20:38, then 21:38; Participant 12 at Day 9 · 11:47, then the recovery), and the same scroll positions. Viewports
are 1440×900, 1280×800, 820×1180 (tablet) and 390×844 (phone), with 13 states each plus 3 full-page shots at 1440. The
runner fails if a state is not reached or a file is missing. `print/` holds rendered PDF pages of the frozen summary.

| Area | Before | After | Purpose |
|---|---|---|---|
| Sidebar | 240 px; 38 px rows; the active page had only a blue rule | 224 px; 36 px rows, 13.5 px labels; the active page has a quiet fill plus the blue rule | A calmer and narrower sidebar with the same icons, so the chart gets more room |
| Header | Source label only | Source plus the replay state ("Recorded-data replay \| Paused · Day 9 · 20:38") | Location, source and cutoff can be read without scrolling |
| Review queue | "Recorded · session …" repeated on every row; a plain error notice; one skeleton; at 820 px the Data and Open columns were cut off | One source line for the page ("Source: Recorded-data replay for every replay listed"). A row names its source only when sources differ. Loading shows row skeletons with a status label; a failed load has Retry. Icons for stale, abstained and degraded. Tablet rows use two lines in four columns | One source label per page, distinct loading and failed states, and no clipping at tablet width |
| Glucose chart | Final forecast, range and earlier forecasts were all the same blue; no population value; gaps showed only as a break in the line | Final forecast: solid blue point. Range: lighter blue whisker. Population forecast: hollow slate square, with a dashed slate connector to the final value (the patient correction). Sensor gaps over 15 min: grey band labelled "Sensor gap" or "No reading since". The legend, tooltip, table view and help text describe each mark | Observed, population, correction, final forecast, range and gap can be told apart. All values come from the saved forecast |
| Forecast details | Outcome lines only | A state line comes first: Pending (with due times), Partly observed, Observed, or Outcome unknown | Shows at a glance whether the outcome has resolved, without revealing future readings |
| Warnings and quality | Outcomes were text only; stale, abstained and degraded used the same dot | Onset observed: check icon. False alarm: cross. Unknown after a gap: timer-off. Pending: amber dot. Stale: timer-off. Abstention: dashed circle. Data or model limitation: triangle. Words are always shown | Warning, sensor gap, abstention and data-quality limitation are told apart by both text and icon |
| Evidence | Serving, nested and external results were separated only by the selector and notices | A strip of three hairline-divided columns: serving model (internal final test), nested internal (held-out people), external (CGM-only). The one shown is marked; the others are one click away. It holds descriptions only, with no numbers | Keeps the three kinds of result clearly apart |
| Motion | Drawers and dialogs used the 140 ms control duration | `--gt-dur-panel` 200 ms for drawers and dialogs; 0 ms under reduced motion (checked in E2E) | Within the 180–240 ms band for panels |
| Scroll | Opening a page directly could restore the scroll position of the page loaded before it (seen in the before set at 1440: evidence opened at Safety guardrails) | A fresh document load is keyed by its path | Pages open at the top |
| Printed summary | Whole sections were kept together, so a long warning list left page 1 half empty | Sections can break across pages, while single warnings, rows and headings stay whole. Point sizes, darker secondary text and repeated table headers | Fuller printed pages with no clipping. Checked in the rendered PDF (`print/p01-pages.png`, `print/p12-pages.png`) |

## Tests added or extended

- `ReviewQueuePage.test.tsx`: the page-level source label, per-row labels when sources differ, and Retry on a failed list.
- `judge-journey.spec.ts`: forecast details say Pending (with due times) before maturity and Observed after.
- `journey.spec.ts`:
  - Forecast details open with Enter. Focus moves inside, Tab never reaches the page behind, and Escape returns focus to the trigger. The drawer animation is 0 s under reduced motion.
  - At 820 px, the queue's Open link and data state stay on screen.
  - The review summary test now waits for the app's own readiness signal instead of racing the reload. This fixes the baseline flake; its assertions are unchanged.

## Not changed

API semantics, model values, disclosures, units and source labels. No new dependencies.
