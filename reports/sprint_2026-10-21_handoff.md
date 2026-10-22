# Sprint handoff — 21 October 2026 (00:09–05:50 IST)

Local only: nothing pushed, deployed or published. Branch `public-demo` (local commits after `78cf649`); `main` on GitHub is
unchanged at `78cf649`.

## What got measurably better, and against which comparator?

* **Model (research, not serving).** D-052 (`reports/joint_study.md`, 1,570 fresh fits, 0 failures): choosing model
  settings and patient correction together, and the family inside each fold, lowered 60-minute personalised error
  against the refitted serving recipe R0 — 21.62 vs 22.50 mg/dL, −0.88 [−1.75, −0.13], 8 of 14 people better; 30 min
  −0.50 [−0.85, −0.18]. Internal validation on 14 previously inspected people.
* **Warning notice (research).** The same procedure warned 34.3 % of all onsets ≥ 30 min ahead vs 18.8 % for R0
  (320 vs 255 of 329 detected), at more alarms (see gates).
* **Product.** The six-step patient-review journey now runs as an automated browser test (`judge-journey.spec.ts`,
  screenshots in `reports/ui/journey/`); one display defect fixed ("mg/dl", range label).

## Did the predeclared gates pass?

No. Primary gate: size and interval met, but 60-minute error on targets above 180 mg/dL worsened by 1.70 (limit 1.0).
Release guardrails: false alarms +0.60/day (limit +0.10) and time in warning +5.4 pt (limit +2.0) — not met. Not
adopted. D-049 and D-051 stay as recorded.

## What can the judge now do that was missing or broken?

Follow one verified journey (inputs read by the model → forecast components → pinned forecast with its real outcome →
warnings incl. a false alarm → review note and frozen summary → sensor gap, abstention and recovery), with the exact
values in `docs/demo_script.md` and `docs/judge_guide.md`. The judge guide now lists every protocol with its pre-fit
commit time (D-032 … D-052).

## Competitive gaps

Closed or narrowed: clear review workflow (verified end to end); inspectable evidence (manifest 21/21, artifact hashes;
saved parity); honest uncertainty per trend. Remaining: no model change that improves peaks; no pretrained time-series
or physiology baseline tested; serving ranges still 74 %; no video link or public repository yet.

## Serving, candidate, and what switching would require

Serving: `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion` (unchanged; parity 15,440/15,440 saved). Candidate: none —
D-052 failed its gates. The online 24-hour history feature set (`dyn-prof-hist-v1`) exists, tested, on branch
`worktree-agent-a690b60e0f4d64ecc` (not merged); switching to any history model would need a new declared study that
passes, packaging, parity, its own evaluation and trend data, and the team's decision.

## Checks on the final local revision

pytest all passed (1 existing skip); ruff clean; link check 121/121. Agent QA on `83deb24` (code unchanged since except
docs/scripts): vitest 131/131, build, e2e 27/27, public 4/4, summary export 3/3.

## Remaining user actions

Record the video (script ready), upload unlisted, send the link and length; confirm the copyright holder; say
"make it public"; push these local commits when ready; submit the Unstop form before 24 Oct 19:00 IST.
