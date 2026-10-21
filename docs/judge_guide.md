# Evaluate GlucoTwin in 5 minutes

For judges of the Digital Twin Challenge 2026 (Happiest Health). Team Kryptonite, VESIT. Every number below is copied
from the [README](../README.md) or the linked reports; this page adds no new evidence.

## 1. What it is

GlucoTwin is a student research prototype that keeps a patient-specific state for an adult with Type 2 diabetes and
updates it as continuous-glucose and wearable readings arrive. It forecasts glucose 30 and 60 minutes ahead and warns of
a new episode above 180 mg/dL sustained for at least 15 minutes (a research definition, not triage), while showing a
clinician exactly what was known at each moment. Every result was measured on recorded CGM data from real people
(14 CGMacros Type 2 participants, and 98 ShanghaiT2DM people as an independent external check); none comes from
simulated patients.

## 2. How it meets the brief

| Brief requirement | Where it is shown | Honest status |
|---|---|---|
| Fuse static EHR-like data with dynamic wearable data | One LightGBM per horizon reads 8 baseline profile values and 38 glucose and wearable features: README [§7](../README.md#what-the-profile-fusion-does-and-does-not-show) · [model card](model_card.md) · app **Model evidence** screen ([screenshot](../reports/ui/18-model-evidence-fusion-disclosures.png)) | **Met, with caveats.** The profile is read by the model but shows no reliable benefit on new people: +0.34 [−0.28, +0.89] mg/dL at 30 min and −0.75 [−2.19, +0.61] at 60 min on people held out entirely; with 14 people it may act as an identity code. The constraint was declared after the test segment had been inspected. Wearable activity inputs made new-person forecasts worse in this cohort. Chosen for the brief, not for accuracy. |
| Predict an adverse event ahead of time (e.g. a spike 2 h ahead) | Demo model: 60-minute *Research warning* in the workspace ([screenshot](../reports/ui/08-recording-1920-warning-pending.png), README GIF). Two hours: separate research benchmark ([report](../reports/two_hour_benchmark.md)) | **Partly met.** Demo model: 61 of 64 new high-glucose onsets warned; 40 false alarms, 1.49 per observed patient-day; median forecast lead 30 min. Two hours ahead (research procedure, **not** the demo model): MAE 30.6 at 120 min (persistence 35.9; better for 14 of 14 people); 315 of 329 onsets at 1.62 false alarms per observed day, but median forecast lead only 15 min (IQR 5–65): a two-hour forecast, not two hours of notice. On 98 independent ShanghaiT2DM people (a separate CGM-only research procedure, not the serving fusion model; D-045 was its first 120-minute assessment and the cohort's second opening): 29.55 vs 31.68 mg/dL at 120 min, better for 78 of 98 ([external check](../reports/two_hour_external.md)). The demo warning is active at 11.8 % of eligible times ([time in warning](../reports/warning_time_share.md)). |
| Conceptual dashboard for a doctor | Working React workspace: README [§5](../README.md#5-healthcare-use-case) · [screenshots](../reports/ui/README.md) | **Met** as a working research workspace. A review queue lists the 50 most recent replays, unreviewed warnings first (an order of work, not a risk ranking; [screenshot](../reports/ui/20-review-queue.png)); each replay shows one person, from recorded or synthetic data, never a live device. |
| Open, anonymised or synthetic data | CGMacros 1.0.0 (de-identified, CC BY-NC-SA 4.0), ShanghaiT2DM (CC BY 4.0), synthetic fixtures (CC0-1.0): [data card](data_card.md) · README [§9](../README.md#9-open-source-license) · app **Data sources** screen ([screenshot](../reports/ui/16-data-sources.png)) | **Met.** The datasets are downloaded by each user and not redistributed. |
| Submission items (twelve README items, video, PDFs) | README [checklist](../README.md#submission-checklist-unstop-form) · [submission checklist](submission_checklist.md) | **Partly met on 20 October 2026:** items 1–7 and 9–11 Ready; item 8 (demo video) missing — not yet recorded or uploaded; item 12 (public access) unverified — repository not yet public. The README checklist holds the current status. |

## 3. The 5-minute path

1. **Video.** Unlisted YouTube link in README [§8](../README.md#8-demo-video) (minimum 20 minutes). Chapter timestamps
   added after upload. For a short look, watch *Warnings with outcomes, a review and a frozen summary* (07:15),
   *A real sensor gap* (08:45) and *Results* (10:00) ([script](demo_script.md); planned times, confirmed after the
   timed rehearsal).
2. **README GIF** ([`demo-recorded-warning.gif`](../reports/ui/demo-recorded-warning.gif)): recorded CGMacros data,
   Participant 01. A research warning is issued at Day 9 · 20:30 and the onset follows at 20:45 (forecast lead 15 min);
   the same participant had two false alarms earlier that day, and across the test 40 of 101 warning episodes were
   false alarms.
3. **Results table** ([Results at a glance](../README.md#results-at-a-glance)): read the *Evaluated on* column first;
   each row is a different model and a different test.
4. **Safety guardrails** ([table](../README.md#safety-guardrails)): abstention, degraded-input flags, no look-ahead,
   bounded personalisation, an outcome for every warning and locked tests, each linked to its code and tests.
5. **Run the synthetic demo** (no download, ~3 minutes; needs [uv](https://docs.astral.sh/uv/) and Node.js 24; 22.22 or later also works):

```bash
make setup        # Python + web dependencies
make synthetic    # fictional fixtures + synthetic demonstration model
make dev          # API on http://127.0.0.1:8000 and web app on http://127.0.0.1:5173
```

Open http://127.0.0.1:5173 (landing page) → **Open workspace** → **New replay** → *Synthetic demonstration*. Nothing
computed on synthetic participants is clinical evidence. Recorded-data replays need the CGMacros download
([Run it locally](../README.md#run-it-locally)).

### Three-minute judge journey (recorded data, local install)

Each click shows one claim, on a local install with CGMacros imported (`make data experiment`). Without the download,
the synthetic demonstration shows the same screens on fictional participants. Routes: landing `/`, workspace and
replays `/app`, review queue `/app/review-queue`, model evidence `/app/evidence`, data quality `/app/data-quality`. The
forecast, outcome and warning values below belong to the current serving model
(`lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`); `TODO-VALUES` (phase 2): re-record them if the model changes.
The same walkthrough, condensed, closes the [video script](demo_script.md#three-minute-judge-walkthrough-local-install-recorded-data).

| Time | Step and click | What it shows ([screenshots](../reports/ui/journey/)) | Claim it supports |
|---|---|---|---|
| 0:00 | Landing → **Open workspace** → **Open recorded demo**; drag the timeline to **Day 9 · 20:38** | Participant 01, final test period, glucose 165 and rising | A replay of recorded data — never a live sensor |
| 0:15 | **1** · *How the twin reached this forecast* → inputs | "Health record: read by this model; 8 values known (Age, Sex (male = 1), BMI, HbA1c, Fasting glucose, Fasting insulin, Triglycerides, HDL cholesterol)"; body weight, height, ethnicity and cholesterol fractions marked context only; wearable 5-minute summaries available and used ([01](../reports/ui/journey/01-inputs-read-by-the-model.png)) | The profile and wearable data are model inputs, and the app says exactly which |
| 0:35 | **2** · the same panel → forecast table | 20:35 forecast: population 192 / 195, correction −3.0 / −6.7 (713 / 707 observed outcomes, bounded ±25 mg/dL), final 189 / 188; range target 80 %, measured 74.2 % / 74.0 %; rising 3.3 mg/dL/min, 60-min error 35.3 vs 19.5 when steady, range held 46 % at that trend ([02](../reports/ui/journey/02-forecast-components.png)) | Personalisation is bounded and past-only; uncertainty limits are shown, not hidden |
| 1:00 | **3** · **View forecast details** (pins it) → **Esc** → **Step 1 h** (21:38) → **View forecast details** → *Outcome* | 30 min: observed 189 at 21:05, error +0.0 (population +3.0, correction 3.0 closer); 60 min: observed 169 at 21:35, error +19.1 (population +25.8, correction 6.7 closer) ([03](../reports/ui/journey/03-forecast-outcome.png)) | Each forecast can be checked against the reading that followed |
| 1:30 | **4** · Warnings list | 20:30 warning → onset 20:45, forecast lead 15 min; 09:15 and 11:25 marked *No onset (false alarm)* ([04](../reports/ui/journey/04-warnings-hit-and-false-alarm.png)) | Every warning ends with an outcome, false alarms included |
| 1:55 | **5** · **Mark as reviewed** with a note → **Review summary**; step 5 min and reopen it | Participant, session and revision 2, model `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`, cutoff Day 9 · 21:38 (replay time), the note; after the step the copy is unchanged and says the replay has moved to 21:43 ([05](../reports/ui/journey/05-frozen-review-summary.png)) | The review is traceable and frozen at its cutoff |
| 2:25 | **6** · **New replay** → Participant 12 → seek **10:52**, **11:47**, then **Step 5 min** ×4 | 391 *Stale* across a real sensor gap; at 11:47 both forecasts *Not available* ("Unavailable is not the same as low risk"); at 12:07 a forecast again — 79 mg/dL at 60 min (53–105), *Degraded data* ([06](../reports/ui/journey/06-gap-abstention.png), [06b](../reports/ui/journey/06b-gap-recovery.png)) | Missing data is shown, never filled in; recovery is labelled honestly |

The same six steps run as an automated browser test, [`apps/web/e2e/judge-journey.spec.ts`](../apps/web/e2e/judge-journey.spec.ts),
which also checks that a rewind clears the pinned forecast and that the review queue never shows an unknown count as zero.

## 4. Evidence you can verify yourself

Commands from README [Verification](../README.md#verification):

```bash
make test       # backend tests: leakage, labels, splits, adaptation maturity, activity windows, warning matching, replay invariants, API, integration
make test-web   # type check + frontend tests + production build
make e2e        # Playwright journeys on their own API + web server with throwaway storage (also refreshes reports/ui/*.png)
uv run python scripts/check_submission.py  # README links, anchors, tracked files, PDF/PPTX readability
scripts/clean_copy_check.sh /tmp/gt-clean  # Git-publishable files only, in an empty directory: setup, tests, e2e, Shanghai path
```

* **App matches the evaluation:** replaying every test participant through the app reproduced all 15,440 saved test
  forecasts within 0.05 mg/dL ([verification](../reports/verification.md)).
* **Lock files:** an opened assessment writes `opened.json` under `artifacts/research/<experiment>/` (git-ignored, so it
  appears when you run the research steps). Running it again is refused without `--reopen-reason` and is then
  exploratory ([`assess.py`](../ml/glucotwin/research/assess.py), [`two_hour_classifier.py`](../scripts/two_hour_classifier.py)).
  The reports record the times: the two-hour benchmark was opened once at 2026-10-20T09:35:52+00:00; the classifier was
  first opened at 2026-10-20T09:57:29+00:00 and re-opened at 2026-10-20T09:58:18+00:00 for a post-hoc diagnostic (the
  declared metrics did not change).
* **Declared protocols** (each decision is a row in [`decisions.md`](decisions.md)):

| Decision | Experiment and protocol file | When declared | Report |
|---|---|---|---|
| D-032 | [`gt-nested-2026-10-12-v1`](../configs/experiments/gt-nested-2026-10-12-v1.yaml): 14 people each held out once, ShanghaiT2DM reserved as external cohort | Before any fit, 12 Oct 2026 | [nested benchmark](../reports/nested_benchmark_report.md) |
| D-038 | [`gt-primary-2026-10-13-fusion`](../configs/experiments/gt-primary-2026-10-13-fusion.yaml): the demo model | 13 Oct 2026, **after** the test segment had been inspected (retrospective) | [evaluation report](../reports/evaluation_report.md) · [model card](model_card.md) |
| D-043 | [`gt-2h-2026-10-20`](../configs/experiments/gt-2h-2026-10-20.yaml): two-hour benchmark | Before any fit, 20 Oct 2026 | [two-hour benchmark](../reports/two_hour_benchmark.md) |
| D-044 | [`gt-2h-clf-2026-10-20`](../configs/experiments/gt-2h-clf-2026-10-20.yaml): direct two-hour onset classifier | Before any fit, 20 Oct 2026 | [classifier report](../reports/two_hour_classifier.md) — **negative result, kept** |
| D-045 | [`gt-2h-ext-2026-10-20`](../configs/experiments/gt-2h-ext-2026-10-20.yaml): two hours ahead on 98 ShanghaiT2DM people | Before any fit, 20 Oct 2026; assessed once at 2026-10-20T10:10:25+00:00 | [external two-hour check](../reports/two_hour_external.md) |
| D-046 | [`gt-warn-range-2026-10-20`](../configs/experiments/gt-warn-range-2026-10-20.yaml): earlier warnings, pooled ranges, profile as starting correction (saved two-hour predictions re-analysed) | Before any arm was computed, 20 Oct 2026 (protocol committed first); outer predictions read once at 2026-10-20T12:24:25+00:00 | [re-analysis](../reports/warning_range_experiment.md) — ranges fixed (79.8 % at 120 min); earlier warning and profile benefit **not shown** |
| D-048 | [`gt-blend-2026-10-21`](../configs/experiments/gt-blend-2026-10-21.yaml): LightGBM–CatBoost blend | Protocol commit `2799ab3`, 20 Oct 20:36 IST, before any blend was scored | [blend](../reports/blend_experiment.md) — not adopted, held-out folds never opened |
| D-049 | [`gt-retrain-2026-10-21`](../configs/experiments/gt-retrain-2026-10-21.yaml): four fixed retraining arms | Protocol commit `83b36ec`, 20 Oct 22:30 IST, before any fit | [retraining](../reports/retrain_study.md) — not adopted |
| D-050 | [`gt-ranges-2026-10-21`](../configs/experiments/gt-ranges-2026-10-21.yaml): ranges for the serving pipeline | Protocol commit `0de0889`, 20 Oct 23:09 IST, before any candidate | [ranges](../reports/serving_ranges_study.md) — served ranges kept |
| D-051 | [`gt-tune-2026-10-21`](../configs/experiments/gt-tune-2026-10-21.yaml): nested tuning, history vs current features | Protocol commit `e7ff594`, 20 Oct 23:14 IST, before any fit | [tuning](../reports/tune_study.md) — small internal gain, below the bar |
| D-052 | [`gt-joint-2026-10-21`](../configs/experiments/gt-joint-2026-10-21.yaml): joint model + correction selection | Protocol commit `903419d`, 21 Oct 00:10 IST, before any fit | [joint selection](../reports/joint_study.md) — gates not met |
| D-053 | [`gt-constrained-2026-10-21`](../configs/experiments/gt-constrained-2026-10-21.yaml): constrained, peak-aware LightGBM fusion selection | Protocol commit `2e2b01a`, 21 Oct 22:31 IST, before any formal fit | Result pending (`TODO-VALUES`, phase 2: from the locked summary only) |
| D-054 | [`gt-foundation-2026-10-21`](../configs/experiments/gt-foundation-2026-10-21.yaml): zero-shot foundation baseline, CGM only | Protocol commit `1967c25`, 21 Oct 21:31 IST, before any participant forecast | [foundation baseline](../reports/foundation_baseline.md) — better than persistence (60 min 22.92 vs 24.47), not better than the refitted serving recipe (22.50); not served |

* **The negative result (D-044):** the classifier looked perfect on episode counts (329 of 329 onsets, 0.18 false
  alarms per day) only because its inner-fold threshold made it warn at 99 % of eligible times; its ROC AUC was 0.64.
  It is not used, and it shows why time spent in warning must be read beside alarm counts.
* **Reproduction note:** research numbers need the downloaded datasets, and fold membership of
  `gt-nested-2026-10-12-v1` follows this installation's salted pseudonyms, so another installation gets an equally
  valid but different draw ([README](../README.md#larger-data-research-experiment-optional)).

## 5. What we do NOT claim

* **Not a medical device.** Research demonstration only: not a medical device, no treatment advice, and a replay of
  recorded or synthetic data, never a live device. No LLM-generated predictions.
* **Not tested on new patients (demo model).** Its test results come from later recordings of the same 14 CGMacros
  people it was trained on; a test over time, not on new patients (retrospective).
* **No proven benefit of the health record.** We selected a model that implements the required fusion; we have not
  established that profile features improve forecasting for unseen patients.
* **Not two hours of notice.** The two-hour warning comes from a research procedure, not the demo model, and its median
  forecast lead was 15 min.
* **Limitations (README §7):** 14 participants from one US site; no Indian participants; blinded research CGMs replayed
  with assumed zero latency; medication use unknown; ranges under-cover; the warning rule still raises more than one
  false alarm per observed day; 180 mg/dL is a research threshold; with 14 people the profile may act as an identity
  code; v2 and the fusion constraint re-use an already-inspected test segment. Nothing here is clinical validation.
* **Uncertainty:** the demo model's prediction ranges (target 80 %) covered 74.2 % / 74.0 %: under-coverage. In the
  two-hour research procedure, pooled calibration fixed coverage (76.5 % → 79.8 % at 120 min, D-046); that fix does not
  apply to the demo model, whose under-coverage most likely comes from drift between time segments.
* **Not novel, not ranked.** We do not claim novelty of glucose twins or predictive alerts (commercial programs and CGM
  alerts exist), and we make no comparison with other teams. It is a statistical research twin, not a physiological
  simulator. The Mumbai diabetes educator in the README is a hypothetical example: no clinic, partner or pilot is
  involved.
* Scores depend on the dataset, prediction task and evaluation protocol; performance on simulated patients does not
  establish performance on real patients.

## 6. Links

* [README](../README.md): the twelve submission items, results, guardrails and run instructions
* [Presentation (PDF)](submission/GlucoTwin_Presentation.pdf) · [Architecture diagram (PDF)](submission/GlucoTwin_Architecture.pdf)
* [Model card](model_card.md) · [Data card](data_card.md) · [Decisions](decisions.md) · [Jury questions](jury_questions.md)
* [Evaluation report](../reports/evaluation_report.md) · [Two-hour benchmark](../reports/two_hour_benchmark.md) ·
  [Two-hour classifier](../reports/two_hour_classifier.md) · [Nested benchmark](../reports/nested_benchmark_report.md) ·
  [Verification](../reports/verification.md)
* [Demo script](demo_script.md) · [Screenshots](../reports/ui/README.md) · [Submission checklist](submission_checklist.md)
* Demo video: README [§8](../README.md#8-demo-video) (unlisted YouTube link added after upload)
