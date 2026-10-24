# Evidence consistency checklist — 20 October 2026

Read-only audit of README.md (Results at a glance, Safety guardrails, §7), docs/judge_guide.md, docs/model_card.md
(two-hour sections), docs/demo_script.md and the 23-slide deck (docs/submission/GlucoTwin_Presentation.pptx, text
extracted with python-pptx), checked against the saved artifacts and reports. No existing file was changed.

## Verified claims

| Claim (where) | Source checked | Status |
|---|---|---|
| Serving model id `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion` (README §7, model card, deck slide 9) | `artifacts/registry.json` → `serving.dataset_replay`; `artifacts/experiments/gt-primary-2026-10-13-fusion/metrics.json` → `model_version` | Match |
| Demo model test MAE 12.96 / 20.26 vs persistence 14.84 / 23.23 (README row 1, §7, judge guide, jury Q&A, deck 10/15/20) | metrics.json test: 12.956 / 20.264; persistence 14.837 / 23.225 | Match. Every occurrence says "later recordings of the same 14 people", "not new/unseen patients" (README:22, :195, :221; judge guide:90; jury_questions:50; deck 11/14/20). No wording implies unseen patients |
| Serving − persistence −1.88 [−2.53, −1.32] / −2.96 [−4.34, −1.77]; 14/14 and 13/14 people better | metrics.json comparisons; per_patient_test | Match |
| Adaptation −0.18 [−0.35, −0.01] / −0.33 [−0.68, +0.02]; frozen state 13.19 / 20.65; LOPO 14.66 / 24.26 → 13.81 / 22.12 | metrics.json | Match |
| 60-min warning 61/64, 40 false alarms, 1.49 per observed day, 2.28 per eligible day, qualified lead median 30 min, 101 episodes | metrics.json events (adaptive, test, h60, margin −10) | Match |
| v2 comparator 64/64, 79 false alarms, 2.95/day, lead 55; persistence 63/64, 70, 2.61; v1 13.32 / 21.20, 26 false alarms | v2 / v1 metrics.json | Match |
| Ranges 74.2 % / 74.0 %, per participant 60–82 % / 51–88 % | metrics.json intervals (adaptive, test) | Match |
| Selection scores 17.36 vs CatBoost 17.44; validation MAE table (deck slide 9) | metrics.json selection.candidates | Match |
| Meal sensitivity 19.07 vs 20.59 at 60 min (deck 17) | metrics.json sensitivity | Match |
| Warning active at 11.8 % of eligible times (README row 2, judge guide) | reports/warning_time_share.md (596 of 5,042) | Match |
| Nested v1: 13.88 / 22.30 vs persistence 15.34 / 24.47; Ridge chosen in 4 of 5 folds; v2 recipe 14.52 / 24.25; −0.64 / −1.95; high-glucose 39.71 vs 37.00 (+2.71 [+0.28, +5.11]); warnings 301/329 at 1.31 vs 329/329 at 2.80; ranges 80.1 % / 78.8 %; profile +0.34 / −0.75 | reports/nested_benchmark_report.md | Match |
| ShanghaiT2DM 30/60 (nested v1): 11.15 / 20.11 vs 12.14 / 20.44; −0.99 [−1.21, −0.77] 80/98; −0.34 [−0.76, +0.10] inconclusive; coverage 87.1 % / 86.1 %; lowest other pipeline 10.81 / 19.00 reported not adopted | nested report, external section (freeze `31b8872ba8a28293`) | Match |
| `gt-2h-2026-10-20`: 120-min MAE 30.617 vs 35.869; −5.25 [−6.44, −4.05], 14/14; 60 min 22.288 vs 24.467; warning 315/329, 1.623 FA/observed day, precision 0.5844, median lead 15 (IQR 5–65); 60-min warning 313/329, 1.478, lead 10; coverage 76.5 %; selected per fold LightGBM 3 / Ridge 2 (all CGM-only); profile LightGBM −0.86 [−2.60, +1.02], Ridge +12.65 [+1.34, +29.24]; wearable +0.75 / +2.68 / +2.50 | `artifacts/research/gt-2h-2026-10-20/two_hour_summary.json`; reports/two_hour_benchmark.md | Match (README row 5, §7, judge guide, model card, deck 19, demo script ch. 11) |
| `gt-2h-clf-2026-10-20` presented only as negative: 329/329, 0.18 FA/day, 99 % of eligible time in warning, ROC AUC 0.64 "not used" | `artifacts/research/gt-2h-clf-2026-10-20/summary.json`; reports/two_hour_classifier.md | Match; README:327–330 and judge guide:79–81 call it a negative result. Not in the deck or model card (absence is acceptable) |
| `gt-2h-ext-2026-10-20`: 29.55 vs 31.68 at 120 min, −2.12 [−2.67, −1.53], 78/98; 30/60 10.90 / 19.31; coverage ~87 % | `two_hour_external_summary.json` (29.553 / 31.675; 78 of 98); reports/two_hour_external.md | Match (README row 6, judge guide:20, deck 19 rounded 29.6 / 31.7) |
| Cold-start profile note labelled exploratory (CatBoost 36.72 → 32.70, −4.02 [−6.87, −1.38], 10/14) | reports/cold_start_profile.md ("Exploratory, not pre-specified") | Match; README:271 says "exploratory look (not pre-specified, many comparisons)" |
| Safety guardrails table (README:55–67) vs app `SafetyGuardrails.tsx` and deck slide 13 | Same eleven rules, same thresholds (60 min, 15 min, ±25 mg/dL, ≥ 6, 3 h, 40/400, 15,440 within 0.05) | Consistent |
| No superiority claim over other teams; no clinical claim | README, judge guide (:101–102 "no comparison with other teams"), deck, model card | None found. "Not a medical device" stated throughout |

## Discrepancies with exact file:line and fix

1. **Two different external fits under one label.** README.md:26 ("A separate 15-minute LightGBM", 11.15 / 20.11) and
   README.md:28 ("A separate 15-minute LightGBM on CGM only", 10.90 / 19.31 at 30 / 60) are two separate fits on the
   same 98 people (freeze `31b8872ba8a28293` vs `aa43715707e8e80b`). A reader sees two 30/60 numbers for "the" external
   model. **Fix (README:28, Model cell):** "The same 15-minute CGM-only procedure re-fitted with a 120-minute horizon
   (`gt-2h-ext-2026-10-20`), **not** the row above's frozen candidate and **not** the demo model". Optionally drop its
   30/60 numbers or add "(a separate fit; differs from the row above)".
2. **"Three models" omits the two-hour procedures.** README.md:190 says results come from three models, but Results at a
   glance rows 5–6 come from `gt-2h-2026-10-20` and `gt-2h-ext-2026-10-20`. **Fix:** after README:206 add a bullet:
   "*Two-hour research procedures* (`gt-2h-2026-10-20`, D-043; `gt-2h-ext-2026-10-20`, D-045): research re-runs with a
   120-minute horizon; not the demo model, nothing promoted ([two-hour benchmark](reports/two_hour_benchmark.md) ·
   [external two-hour check](reports/two_hour_external.md))."
3. **Judge guide misses D-045.** docs/judge_guide.md:72–77 lists D-032, D-038, D-043, D-044 only. **Fix:** add row
   `| D-045 | [gt-2h-ext-2026-10-20](../configs/experiments/gt-2h-ext-2026-10-20.yaml): two hours ahead on 98 ShanghaiT2DM people | Before any fit, 20 Oct 2026 | [external two-hour check](../reports/two_hour_external.md) |`.
   Also judge_guide.md:67–69: add "the external two-hour check was opened once at 2026-10-20T10:10:25+00:00".
   judge_guide.md:113–115 (Links): add [Two-hour external](../reports/two_hour_external.md) ·
   [Time in warning](../reports/warning_time_share.md) · [Cold-start profile (exploratory)](../reports/cold_start_profile.md).
4. **Model card has no D-044 / D-045.** docs/model_card.md ends at :245 after `gt-2h-2026-10-20`. **Fix:** append two
   bullets: "External two-hour check `gt-2h-ext-2026-10-20` (D-045, not serving): 29.55 vs 31.68 mg/dL at 120 min,
   −2.12 [−2.67, −1.53], 78 of 98 ShanghaiT2DM people; CGM only." and "Direct two-hour classifier
   `gt-2h-clf-2026-10-20` (D-044): **negative result** — warned at 99 % of eligible times (ROC AUC 0.62–0.66); not used."
5. **Video status contradicts itself.** docs/decisions.md:49 (D-043) says "Added after the demo video was recorded" and
   :50 (D-044) says "the recorded video are unchanged", while README.md:83/:338, judge_guide.md:23,
   submission_checklist.md:29 and configs/submission.yaml:11 say the video is **not recorded**. **Fix:** whichever is
   true, make all match. If not recorded, edit decisions.md:49 to "Declared before the demo video was recorded" and
   :50 to "the demo model is unchanged". If recorded, update the checklist rows listed below.
6. **README index and layout miss the new reports/configs.** README.md:503–506 (Evidence index) lacks
   two_hour_benchmark, two_hour_classifier, two_hour_external, warning_time_share and cold_start_profile (exploratory).
   README.md:481 lists configs/experiments as "v1; fusion…; nested v1/v2". **Fix:** add the five reports and
   "two-hour gt-2h / gt-2h-clf / gt-2h-ext (D-043–D-045)".
7. **Same comparison, two intervals (note, not an error).** Ridge profile at 120 min is +12.65 [+1.34, +29.24] in
   two_hour_benchmark.md:27 and +12.65 [+1.50, +28.43] in cold_start_profile.md:75 (and LightGBM −0.86 [−2.60, +1.02] vs
   [−2.69, +0.96]): different bootstrap and pairing. README/model card cite the benchmark values correctly. Optional:
   add one line to cold_start_profile.md saying its intervals come from its own paired bootstrap.

No number in any checked document disagrees with its source artifact.

## Evidence page gap

`apps/web/src/pages/EvidencePage.tsx` shows the serving experiment, superseded v1/v2, and one research experiment.
`services/api/glucotwin_api/evidence.py:12` has `RESEARCH_EXPERIMENTS = ("gt-nested-2026-10-12-v1",)`, and the
gt-2h runs write `two_hour_summary.json` rather than `report.json`. So **the two-hour research (D-043/D-044/D-045) and
the 11.8 % time-in-warning are not visible in the app.** The Safety guardrails section (`components/evidence/SafetyGuardrails.tsx`)
matches the README.

**Recommendation for today:** no app change. README rows 5–6 already link `reports/two_hour_benchmark.md` and
`reports/two_hour_external.md`, and §7 links the classifier report; apply fixes 2 and 6 so the README links all of them.
If a change is wanted after submission, the smallest one that keeps "every value read from artifacts" is a single
`<Disclosure title="Two hours ahead (research, not the demo model)">` inside `ResearchEvidence.tsx` with no numbers,
naming D-043/D-044/D-045 and pointing to the three report paths. Typed-in numbers would break the evidence-API rule.

## Stale submission metadata

| File:line | Stale text | Exact fix |
|---|---|---|
| docs/submission_checklist.md:32 | "(21 slides, incl. …)" | "(23 slides, incl. “Project outcomes”, the research-evidence slide and the two-hour slide)". The access audit already says 23 |
| docs/submission_checklist.md:12 | "Overall status (rechecked 19 October 2026)" | "rechecked 20 October 2026" after re-running `scripts/check_submission.py` |
| docs/submission_checklist.md:18 | "Verification date for every row: 19 October 2026" | "20 October 2026" (after the re-run) |
| docs/submission_checklist.md:48 | Deadline "Recheck before submitting" | Add "Rechecked 20 Oct 2026: 7:00 PM IST" once confirmed on the live page |
| README.md:71 | "its status on **19 October 2026**" | "**20 October 2026**" |
| README.md:376 | "Last local check: **19 October 2026**" | "**20 October 2026**" after the re-run |
| README.md:481 | configs/experiments list | Add gt-2h-2026-10-20, gt-2h-clf-2026-10-20, gt-2h-ext-2026-10-20 |
| docs/decisions.md:49–50 | "after the demo video was recorded" / "the recorded video are unchanged" | See discrepancy 5 |
| configs/submission.yaml:10–16 | `repository`, `video`, `rendered_duration`, `youtube_displayed_duration` all null | Correct while unpublished/unrecorded. Fill only with confirmed values after upload, then rebuild slides (`scripts/build_submission_assets.py`) so the closing slide carries the links |
| docs/demo_script.md | Says demo first and 23 slides; chapter titles match judge_guide.md:28–29 | Up to date. Optional: add one sentence in Chapter 4/6 for the new Review dialog and Review summary once they ship |

## 90-second walkthrough (judges)

Recorded data, Participant 01, final test period (later recordings of a participant the model was trained on). Times
come from `reports/demo_sequence.md`, Scene A. Button names may change; use the labels on screen.

1. **0:00–0:15 · Open the replay.** Workspace → recorded replay → Participant 01 at **Day 9 · 08:14**. Glucose 115
   (08:10); forecasts 119 [103–136] at 30 min and 129 [102–155] at 60 min. "A replay of recorded data, not a live device."
2. **0:15–0:30 · Guardrails readout.** In the review and guardrails inspector, read the rows: data freshness, forecast
   inputs complete, health record known at this time (the model abstains otherwise), patient correction bounded, and
   prediction range (80 % target, ~74 % measured).
3. **0:30–0:45 · Forecast details drawer.** Step 1 h → **Day 9 · 09:14** (glucose 149; forecasts 168 [151–184] and
   161 [134–187]). Click the newest point → forecast details: information cutoff, model version, then the **population
   forecast → patient correction → final forecast**. "Read the two numbers on screen. The correction learns only from
   outcomes already observed."
4. **0:45–1:05 · A warning and its review.** Step to **Day 9 · 09:24** (glucose 158): a research warning issued at
   **09:15**, *Outcome pending*. Open the warning's **Review** dialog, add an optional note (for example "pending, recheck
   after lunch"), and save. The note is stored through the existing acknowledgement endpoint
   (`POST /api/v1/replay/sessions/{session_id}/alerts/{alert_id}/acknowledgement`). Step to **Day 9 · 11:24**: no
   onset observed, a false alarm, and the app says so. Seek to **Day 9 · 20:35**: a new warning issued at **20:30**,
   then step to **Day 9 · 21:10**. The onset began at **20:45**, so the forecast lead was 15 min. "Two false alarms (09:15, 11:25) and one
   matched onset that day; across the test, 61 of 64 onsets warned at 1.49 false alarms per observed patient-day."
5. **1:05–1:20 · Review summary.** Click **Review summary**: a frozen, printable snapshot of this replay time showing
   the forecasts, the warnings with their outcomes and notes, and the model version. Download the JSON. "This
   snapshot does not change when the replay moves on."
6. **1:20–1:30 · Evidence page.** Sidebar → Model evidence → **Safety guardrails** (or *All safety guardrails* from the
   inspector): each rule with the code that enforces it. Close with the README: two-hour research (30.6 vs 35.9 mg/dL
   at 120 min on 14 held-out people; 29.55 vs 31.68 on 98 ShanghaiT2DM people) is **research, not the demo model**,
   and its median warning lead was 15 min, so it does not give two hours of notice.

Say nothing about clinical use, triage or comparisons with other teams.
