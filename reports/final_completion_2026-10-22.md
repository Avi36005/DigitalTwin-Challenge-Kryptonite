# Final completion handoff — 22 Oct 2026 (IST)

**Status: recording-ready, with the limitations disclosed below. Not submission-complete:** the video, its durations,
public repository access and the Unstop form are still the team's to do.

## Source revision and verification

- **Tested revision:** `f073a10` on `public-demo`. Every check below ran on it with no uncommitted tracked changes at the
  start. The only working-tree entries were untracked private audit files.
- **During the run:**
  - `docs/next_experiment.md` was edited (docs only, a future-study plan); the README/submission link check saw that edit.
  - The browser suites regenerated tracked screenshots and one summary PDF in `reports/ui/`, as they are designed to.
  - The commit after `f073a10` adds those, the verification evidence and this handoff. It contains no runtime source
    changes.
- **Ledger:** [`reports/verification/final_2026-10-22_145326Z/LEDGER.md`](verification/final_2026-10-22_145326Z/LEDGER.md),
  with `ledger.json`, `logs/`, `junit/`, `parity/` and `visual/`.

| # | Check | Result |
|---|---|---|
| 1 | Backend `uv run pytest -q` (complete) | **221 passed**, 0 failed, 2 skipped |
| 2 | `uv run ruff check --extend-exclude reports/overnight_codex .` | passed |
| 3 | Frontend typecheck | passed |
| 4 | Frontend unit (vitest) | **141 passed** (133 before plus 8 new outcome-heading tests) |
| 5 | Production build | passed |
| 6 | e2e normal + recorded journeys, including the judge journey | **29 passed** |
| 7 | e2e public/synthetic mode, local only (`PUBLIC_BASE_URL` unset) | **4 passed** |
| 8 | e2e summary/export | **3 passed** |
| 9 | Evidence manifest | **23 of 23 selected claims match** their artifacts |
| 10 | README/submission links | 127 links, 0 failures |
| 11 | D-053 validator (read-only) | complete-valid, 5 development and 5 assessment folds |
| 12 | Serving parity, registered incumbent, new output path | **15,440 / 15,440** within 0.05 mg/dL; 0 missing |

- **Run time:** 22 Oct 2026, 20:27–20:32 IST (14:57–15:02 UTC).
- **Aggregate:** every required check passed.

**Skips (2).** A skip is not a pass, and neither path below executed here.
- The research-only Torch dependency is not installed, so the D-054 foundation-model import test is skipped. I did not
  install Torch.
- One check is compared once, from the fusion side, by design.

**The earlier failure is preserved.**
- The overnight integrated run at `c9b6100` (219 passed, 2 failed in `tests/test_evidence_manifest.py`) remains
  unchanged in `reports/verification/overnight/`.
- No saved passing rerun at `be011f9` was found, so the overnight handoff's claim of one has no preserved evidence.
- The fresh full run above replaces that claim with saved evidence.

**Captures** (`visual/`, 87 PNGs):
- **States:** landing, queue, workspace, pending, observed, mixed unknown/pending, warnings, frozen summary, sensor gap
  with abstention, recovery and evidence.
- **Viewports:** 1920×1080, 1440×900, 1280×800, tablet 820×1180, phone 390×844, and 640×400. The 640×400 layout is
  what 1280×800 at 200 % browser zoom gives.
- Every state was reached, and the runner checks each state before saving it.
- Keyboard focus trapping, Escape and focus return, and reduced motion are covered by the e2e suite. No screen-reader
  test or formal contrast audit was done.

**Protected hashes** were identical before and after:
- `artifacts/registry.json`: `04540adc…4af1c`, the same as the reviewed snapshot.
- The serving model directory, the fusion experiment's metrics and predictions, and `reports/serving_parity.json`.

## Changes

1. **Forecast-outcome heading (fix A)**, `60a375b`.
   - "Partly observed" now requires at least one observed horizon.
   - If none is observed and a target fell in a sensor gap, the heading reads: *Pending · No outcome is observed yet at
     this replay time. No reading near the 30-minute target (10:59), so that outcome is unknown. Still pending: 60 min,
     due 11:29.*
   - Observed plus unknown with none pending reads *Some outcomes observed* and names the unknown target.
   - No "either" or "0 of 0" wording remains.
   - The per-horizon lines and the replay-time guards are unchanged.
   - Tests: `apps/web/src/components/twin/ForecastDetail.test.tsx` (8), plus the browser capture
     `05c-forecast-detail-mixed` on Participant 12 at 11:05.
2. **Narration (fix B)**, `f073a10`.
   - Scene 11 now opens: "This screen shows our earlier research studies and their evidence … Our two newest studies
     are documented in the README and on slides 22 and 23."
   - Slide numbers were checked against the regenerated deck: 22 is D-053 and 23 is D-054.
   - D-053's failed gate (+1.07 against +1.0) and the reuse of previously inspected people are still said aloud.
3. **Backend evidence gap (fix C):** closed by the fresh full run above.
4. **Documentation**, `f073a10`.
   - **Warning notice:** the README results row, model card and slides 18 and 25 now give 48.4 % of **all** onsets
     warned at least 30 minutes ahead next to 61/64 detected.
   - **Model card limits:** it adds per-person range coverage (51.4–87.6 %) and rising-glucose coverage (51.6 % at
     60 min), plus D-053's outcome.
   - **Slide 28:** it separates the serving sources from the research sources.
   - **Recording checklist:** it now has the running order with the 02:00 switch and the team-only steps.
   - **Next studies:** `docs/next_experiment.md` has a bounded plan of future studies. None of it is declared or run.
5. **Assets** regenerated from saved results (no fitting):
   - **Files:** PPTX/PDF (28 slides), architecture PDF (2 pages), narration PDF (8 pages).
   - **Inspection:** every page was rendered and inspected; no clipping or overflow was seen.

## Serving model

- Recorded-data replay serves `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`.
- Synthetic mode serves `synthetic-demo.lightgbm.dyn-v2.v1`.
- Both are unchanged, with no promotion, rollback or refit.
- No experiment was opened or rerun, and no `make experiment` or `make research` target was run.

## Scientific limits (unchanged, stated in the README, model card and slides)

- **Serving results:** 12.96 / 20.26 mg/dL. These are later recordings of the same 14 people, a retrospective selection
  with the fusion constraint; they are not new-patient results.
- **Ranges:** cover 74.2 % / 74.0 % against a nominal 80 %, and less when glucose is rising.
- **Warnings:** 61/64 detected, but only 48.4 % of all onsets were warned at least 30 minutes ahead. False alarms are
  1.49 per observed patient-day, with 11.8 % of eligible time in warning.
- **Fusion:** the profile is a model input, but no reliable benefit has been shown for unseen people.
- **D-053:** not adopted. Its 60-minute change against the refitted serving recipe was −1.19 [−2.09, −0.39], but error
  above 180 mg/dL rose by +1.0658 against a +1.0 limit.
- **D-054:** zero-shot and CGM only; better than persistence, not better than the refitted recipe; not fine-tuned and not
  served.
- **Shanghai (D-045):** a separate 15-minute model on CGM only. It does not validate the serving fusion model.
- **Overall:** none of this is clinical validation.

## Recording

- **Script and checklist:** `docs/demo_script.md` and `docs/submission/recording_checklist.md`.
  - 00:00–02:00 is on the slides; switch to the app at 02:00.
  - Cutaways at 05:30 (architecture) and 10:00 (results); closing at 14:15.
  - App-led extension to the 20:30 target; the minimum is 20:00.
- **Not done here:** no spoken, timed rehearsal. The automated judge journey confirms the screens and values. Only a
  rehearsal and the rendered file measure the duration.

## GitHub

- **Branch:** commits are pushed to `public-demo` through Avi36005 (see the final message for the pushed SHA).
- **PR #1:**
  - It was merged into `main` earlier on 22 Oct (merge `3753961`, 14:31 UTC), at the team's request, before this
    completion task.
  - CI passed on that merge commit: run 39796382079.
- **CI on new commits:** CI runs only for `main` and pull requests into `main`, so the new `public-demo` commits have no CI
  run until a new PR is opened or they are merged.
- **CI scope:** CI does not run the recorded-data browser suites; those passed locally above.
- **Paused:** no deployment and no visibility change. The repository is still private.

## Remaining team-only actions

1. **Video:** record it following the script; the rendered duration must be at least 20:00. Upload it as unlisted
   YouTube, check the displayed duration and signed-out playback, and enter the URL and both durations in
   `configs/submission.yaml` and README §8. Then regenerate the assets so slide 28 shows the link.
2. **Merge to `main`:** decide whether to open a PR from `public-demo` into `main` for CI and merge, so `main` carries
   these fixes.
3. **Make the repository public:** check signed-out access, then fill in `links.repository`.
4. **Copyright holder:** confirm it, if it is still open.
5. **Submit:** on Unstop before 24 Oct 2026, 19:00 IST. That is the previously recorded deadline; it was not rechecked
   today.
