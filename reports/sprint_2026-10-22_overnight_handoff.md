# Overnight sprint handoff — 21 Oct 21:25 → 22 Oct 2026 (IST)

The sprint started at 21:25 IST instead of the planned 21:00. The usage limit then paused all agent work from about 23:00 to 03:30 IST. The D-053 run itself finished during that pause, at 23:39.

## Active model
- Serving model unchanged: `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`. The registry was hash-checked before and after (`artifacts/registry.json` sha256 `04540adc4f16…`).
- No candidate passed every gate, so no promotion or rollback was needed.

## Research results
All results are internal validation on the 14 Type 2 participants inspected in earlier studies.

**D-053 `gt-constrained-2026-10-21`** (protocol sha256 `93b45c3ec35c…`, committed before any fit at 2e2b01a / ba4c39c; report `reports/constrained_study.md`)
- Fits: 1,490 logical and 2,930 physical, with 0 failures. Each fold selected its own family: LightGBM in 3, CatBoost in 2.
- 60-min macro MAE: selected procedure 22.00 vs refitted R0 23.20. Difference **−1.19 [−2.09, −0.39]**; 11 of 14 people better.
- 30-min difference: −0.50 [−0.77, −0.24].
- High-target (> 180 mg/dL) 60-min error: **+1.07, over the +1.0 limit → primary gate not met.**
- Operational gate vs R0-P passed: false alarms 1.15 vs 1.20 per day; onsets warned ≥ 30 min ahead 21.9 % vs 16.4 %; time in warning +1.1 pt.
- Exact-predictor 80 % ranges: 79.4 % at 30 min and 77.3 % at 60 min; range guardrails passed.
- Rising-glucose (> 2 mg/dL/min) coverage stays low: 46.2 % primary, 74.8 % for the trend-scaled secondary range.
- Decision: **not adopted.** The gate was not relaxed after seeing the result.

**D-054 `gt-foundation-2026-10-21`** (protocol 1967c25; report `reports/foundation_baseline.md`)
- Checkpoint: zero-shot `amazon/chronos-bolt-tiny`, revision a0e552de, Apache-2.0. CGM only.
- 60-min error: 22.92 vs persistence 24.47 (−1.54 [−1.81, −1.30]).
- Not better than R0 (22.50). Worse on targets above 180.
- Not run: fine-tuning and Chronos-2.
- The F1 residual (−0.46 vs the R0 refit) is descriptive only.

**D-052 erratum**: its range calibration mixed fitted models. The note is added to its report; its saved results are unchanged.

## Product
Full list with before/after captures: `reports/ui/overnight/CHANGES.md`.
- Sidebar and header.
- Review-queue states, plus the tablet layout fix.
- Distinct chart marks for the population forecast, the patient correction and the final forecast.
- Pending and resolved status on forecast details.
- Warning and quality cues shown as icon plus text.
- Evidence scope strip.
- Print layout for the review summary.

## Testing
Latest verified commit: be011f9 (ledger: `reports/verification/overnight/LEDGER.md`).

| Suite | Result |
|---|---|
| ruff | passed |
| pytest | all passed, 2 skips (one by design, one because torch is absent) |
| typecheck | passed |
| vitest | 133 passed |
| build | passed |
| e2e, including the judge journey | 29 passed |
| public mode | 4 passed |
| summary | 3 passed |
| check_submission | passed |
| evidence manifest | 23/23 claims match |
| D-053 validate | complete-valid |
| Incumbent parity | 15,440/15,440 within 0.05 mg/dL |

Two failures earlier in the night were fixed and confirmed:
- The baseline e2e flake was fixed in the UI branch.
- Two evidence-manifest tests failed at c9b6100 because of README wording, which was fixed in c0ef77b. They passed on the full pytest rerun at be011f9.

## GitHub
- Branch `public-demo` was pushed and its remote SHA confirmed: `be011f98009c…`.
- PR #1 (`public-demo` → `main`) ran CI on be011f9: **backend pass, web pass** (run 39684916670). `main` itself is **not updated** until that PR is merged.
- No deployment and no visibility change. The repo stays private.

## Submission pack
- In the repo: `docs/submission/GlucoTwin_Presentation.{pptx,pdf}`, `GlucoTwin_Architecture.pdf`, `GlucoTwin_Demo_Script.pdf`, `docs/demo_script.md` and `docs/submission/recording_checklist.md`.
- Copies, sha256-matched, in `~/Downloads/GlucoTwin_Overnight_22Oct2026/`.

## Remaining for the team
1. Record the video (about 20:30, following the app-led script) and upload it. Add the link and duration.
2. Merge PR #1 into `main` once CI is green, if `main` is the branch to submit.
3. Make the repo public when the team decides; that is not done yet.
4. Confirm the copyright holder.
5. Submit on Unstop before 24 Oct 2026, 19:00 IST.
