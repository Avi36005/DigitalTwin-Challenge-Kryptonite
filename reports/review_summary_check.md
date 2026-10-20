# Review summary export check — 20 October 2026

The printed copy of the review summary was exported to PDF through Chromium's print path by
`apps/web/e2e-summary/review-summary-export.spec.ts` (`npx playwright test --config playwright.summary.config.ts`, own
ports 8030/5200 and throwaway storage), for five cases. Each PDF was rendered to PNG and inspected page by page, and its
text was extracted. Files: [`reports/ui/summary_check/`](ui/summary_check/) (one full PDF, its pages, one abstention
page and the extracted text of every case).

| Case | What was checked | Result |
|---|---|---|
| Participant 01, Day 9 · 20:38, warning pending, 500-character note with HTML-like text and a long unbroken word | Note wraps inside the page; the `<b>` text is shown literally, not rendered; pending outcome stays "Outcome pending" | Pass: no clipping; text escaped; 3 pages, warnings table breaks cleanly between rows |
| Same summary after the replay moved on | Values frozen at the cutoff | Pass: extracted text identical to the copy taken before the replay moved |
| Participant 12, Day 9 · 10:50, sensor gap | Stale glucose shown with its age and the 15-minute limit | Pass: "Stale — 21 min old, over the 15-min limit" |
| Participant 12, Day 9 · 11:45, abstention | No forecast values; reason stated; unavailable ≠ low risk | Pass: "Insufficient — abstained … Unavailable is not the same as low risk" |
| Synthetic Participant A, missing profile value | Missing value stays missing | Pass: "Fasting insulin — Not available" |

All five: replay time ("Day 9 · 20:38 (replay time)") and wall-clock review time ("wall clock, this computer") are
labelled separately; the header says "Research replay review — not a medical report"; the long model ID
`lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion` fits; text is selectable (extracted from the PDF).

Fixed after the check: header branding now reads "GlucoTwin — Team Kryptonite, VESIT", and "against a 80 % target"
now reads "an 80 %". Observed, not changed: the first page ends after the forecast block, leaving white space before the
warnings table (the table avoids splitting a row); acceptable for a printed record.
