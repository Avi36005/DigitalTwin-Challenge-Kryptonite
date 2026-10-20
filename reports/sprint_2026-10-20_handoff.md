# Sprint handoff — 20 October 2026 (local improvement sprint)

Started 20:32 IST; this handoff written at 22:00 IST on the final checked revision `49defb8` (branch `public-demo`, fast-forwarded to
`main` and pushed). Local work only: nothing was deployed or published, and repository visibility was not changed.
Ledger: [`sprint_2026-10-20_ledger.md`](sprint_2026-10-20_ledger.md).

## 1. Completed / in progress / deferred

**Completed**
* Review queue correctness (§4A, `6ff105f`, `d34480c`). Each row reads one coherent snapshot from the new endpoint
  `GET /replay/sessions/{id}/review-snapshot` (session, warnings and latest forecast under one lock). Answers about
  another session, another participant, an earlier revision or with disagreeing clocks are refused. Loading or failed
  rows stay *unknown*, never zero, and have a retry. The header states complete, partial or unavailable totals. The
  order is administrative.
* "How the twin reached this forecast" panel (§4B, `e08df48`, `e8c08d4`, `f2e4a89`). It shows per horizon the
  population forecast, the patient correction applied at issue time and the final estimate. It shows the correction
  state, observed-outcome counts and the ±25 mg/dL bound reported by the API. It shows the inputs used: the 8 profile
  values the model reads, with the others marked context only and missing values left missing. It shows the warning
  track record at the replay clock, and target and measured coverage for the exact model.
* Accuracy at the current glucose trend (`81fb9b5`, `457eb7a`). Forecasts now carry their 15-minute trend. The panel
  shows this model's validation-segment error at that trend: 60 min 35.3 mg/dL when rising > 2 mg/dL/min, against
  19.5 when steady; peaks are under-forecast by 16.9 mg/dL. The figures come from
  [`error_by_trend.md`](error_by_trend.md); the test segment is not read.
* Frozen review summary verified (§4C, [`review_summary_check.md`](review_summary_check.md)). Five edge cases were
  exported to PDF, rendered and inspected, and the summary stays frozen after the replay moves on. Branding and an
  article were fixed.
* Evidence manifest (§6, [`evidence_manifest.md`](evidence_manifest.md)). Of 17 README claims, 16 match their saved
  artifacts, 0 mismatch and 1 is author-reported (replay parity).
* Research summaries (§6). Status now distinguishes absent, malformed and incompatible files and never says "not run"
  for a file that exists. Each finding states whether its verdict is a declared rule or a display description; the
  D-046 ranges verdict no longer implies a 1-point pass bar.
* Model experiment D-048 (§5, [`blend_experiment.md`](blend_experiment.md)). Negative result; see section 3.
* Public synthetic demonstration mode, Docker image and aggregate-only evidence snapshot (D-047). Built, tested and
  kept. Not deployed: deployment is on hold.
* Judge demo synchronisation (§8). The video script now runs slides 00:00–02:00 and the app from 02:00, a 15-minute
  main narrative (about 72 % app) plus an extension to 20:30. A three-minute judge journey is in
  [`docs/judge_guide.md`](../docs/judge_guide.md). Deck slide 20 adds D-048, and the brand line reads "Team Kryptonite,
  VESIT".

**Deferred:** correction-history visualisation, because the saved values do not support it causally. No further model
candidates, per D-048's stop rule.

## 2. Product walkthrough (60–90 s, local, recorded data)

1. Landing → **Open workspace** → **Open recorded demo** (Participant 01, Day 9 · 08:14).
2. Drag the timeline to Day 9 · 20:38, then scroll to **How the twin reached this forecast**: population 195,
   correction −6.7 and final 188 mg/dL at 60 min. The panel also shows the 8 profile values read and *Accuracy at this
   trend*: rising 3.3 mg/dL/min, 60-min error 35.3 against 19.5 when steady
   (screenshot [`ui/24-twin-explanation.png`](ui/24-twin-explanation.png)).
3. On the 20:30 warning, **Mark as reviewed** → **Review summary** → *Print / Save as PDF*.
4. **Review queue**: the replay shows one reviewed warning, and its counts stop at the replay clock.

## 3. Research result (D-048)

* **Question:** does a LightGBM–CatBoost population blend on the fusion features improve 60-minute error for a person
  held out entirely, with the declared patient update applied once?
* **Candidates:** alpha ∈ {0, 0.25, 0.5, 0.75, 1}.
* **Protocol:** committed at 20:36:41 IST, before the first blend score at 20:36:54.
* **Development result:** alpha 0.75 selected; 60-min development MAE 22.28 → 22.26 (+0.02 vs ≥ 0.5 target).
  Guardrails held.
* **Decision:** stop rule applied. The incumbent is kept, the outer folds were not opened, and no replacement candidate
  was launched.
* **Error analysis:** errors are largest while glucose rises and at peaks, the same pattern as the serving model. That
  finding went into the product as the trend-accuracy line, not into a model change.
* **Already-inspected cohorts:** the 14 CGMacros Type 2 people; this is internal research.

## 4. Serving identity

**Unchanged.** dataset_replay is `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion` and synthetic_demo is
`synthetic-demo.lightgbm.dyn-v2.v1` (`artifacts/registry.json`, confirmed by `/api/v1/serving` after the restart). No
parity re-run was needed: forecasts are unchanged and only the additive trend field was added. Rollback is unchanged:
`glucotwin research rollback --to lightgbm.dyn-v2.gt-primary-2026-10-11-v2`.

## 5. Verification run in this sprint, on the integrated code

| Check | Result |
|---|---|
| `uv run pytest -q` | all passed, 1 skipped (the existing skip) |
| `uv run ruff check .` | clean |
| `npm run typecheck`, `npx vitest run` | clean; 126 / 126 |
| `npm run build` | built |
| `npm run e2e` (standard, :8010/:5180, throwaway storage) | 23 / 23 on `457eb7a`; review-queue journeys re-run 2 / 2 after `f2e4a89` |
| `npx playwright test --config playwright.public.config.ts` | 4 / 4, local public server |
| Review-summary export (`playwright.summary.config.ts`) | 5 cases exported and inspected (Specialist C run, before the branding fix) |
| `uv run python scripts/check_submission.py` | 114 links, 0 failures |
| GitHub Actions CI on `main` (`49defb8`) | run 39457216708: success |

Author-reported, not re-run tonight: online/offline replay parity (15,440 forecasts).

## 6. Artifacts

* Protocol: `configs/experiments/gt-blend-2026-10-21.yaml`.
* Reports: `reports/blend_experiment.md`, `reports/error_by_trend.md`, `reports/evidence_manifest.md`,
  `reports/review_summary_check.md`.
* Screenshots: `reports/ui/24-twin-explanation.png`, `reports/ui/summary_check/`.
* Demo and deck: `docs/demo_script.md` (14 chapters), `docs/judge_guide.md` (judge journey),
  `docs/submission/GlucoTwin_Presentation.pdf` (24 slides; also copied to ~/Downloads).

## 7. Submission tasks for the team

1. **Video.** Record from `docs/demo_script.md` with slides for the first two minutes and the app from 02:00, aim for
   about 20:30, upload as Unlisted, and send the link and the length YouTube shows.
2. **Deadline time.** Confirm the time of day for 24 October on Unstop.
3. **Copyright holder.** Confirm "Avinash Gehi and Hardik Hinduja (Team Kryptonite)".
4. **Public repository.** Say "make it public" when ready.
5. **Unstop form.** The team leader submits it.

No deployment is authorised; the public-demo mode stays local.
