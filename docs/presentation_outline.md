# Presentation outline

Finished files: [`docs/submission/GlucoTwin_Presentation.pptx`](submission/GlucoTwin_Presentation.pptx) (editable) and
[`GlucoTwin_Presentation.pdf`](submission/GlucoTwin_Presentation.pdf). Both are generated from the same slide
specification by `scripts/build_submission_assets.py`, which reads every number from the serving experiment's
`metrics.json` (currently the fusion-constrained `gt-primary-2026-10-13-fusion`), and every team/link line from `configs/submission.yaml` (null values print as “to be confirmed” /
“added after …”). After adding the college, repository URL or video URL to that file, regenerate with
`uv run --group docs python scripts/build_submission_assets.py`.

| # | Slide | Content and evidence |
|---|---|---|
| 1 | Title | GlucoTwin — personalized glucose forecasting between clinic visits; **Team Kryptonite, VESIT** (brand line from `configs/submission.yaml`); Avinash Gehi, leader; Hardik Hinduja; full college name |
| 2 | The problem | HbA1c vs between-visit excursions; clinician question; target definition |
| 3 | Use case and boundaries | Hypothetical Mumbai example, labelled as an illustration; users; proposed workflow (a review queue lists replays with unreviewed warnings first — an order of work, not triage — and each person is reviewed in their own workspace); what it never does; fit as proposal |
| 4 | What makes it a twin | Operational definition + twin loop figure |
| 5 | Data and provenance | CGMacros facts, cohort, interpolation finding, synthetic fixtures |
| 6 | Availability and leakage controls | Two timestamps, meals excluded, split figure, frozen protocol |
| 7 | Architecture | Architecture diagram: inputs → causal features → fusion LightGBM → bounded patient update → ranges and warnings → clinician review and ledger; research candidates in a dashed box, never served unless every release gate passes |
| 8 | Models and personalization | Fusion (38 dynamic + 8 profile inputs in one model), baselines, LightGBM/CatBoost, adaptation, conformal prediction ranges (target coverage 80 %), warning score |
| 9 | Why this learner | Validation-only candidate table + declared rule; eligibility restricted to profile + wearable models (declared after the test segment had been inspected); what the rule picks without the constraint |
| 10 | Fusion: what the profile adds, and what it does not show | Brief's fusion requirement; within-cohort profile effect vs dynamic-only; no reliable benefit on people held out entirely (nested experiment); profile as identity code with 14 people; warning trade-off vs the earlier model; the claim we make and the one we do not |
| 11 | Clinician workflow | Screenshot: recorded-data replay in the final test period (later recordings of the same participants) |
| 12 | Demonstration | Screenshot: forecast details drawer |
| 13 | Safety guardrails built into the twin | Abstention (history, sparse hour, no new reading; Stale after 15 min), Degraded flags, fusion profile gate, availability-time inputs, bounded personal correction (matured residuals, 6, ±25 mg/dL, 3-h reset), warning outcomes and episode merge, ranges with measured coverage, no clinical claims, locked evaluation and 15,440/15,440 parity — same list as the README's Safety guardrails table |
| 14 | Results at a glance | One table, three labelled groups never blended: serving model (later recordings of the 14 known people), participant-held-out research (D-032; D-053 *pending* until its locked summary; D-054 from its `summary.json`) and the external CGM-only check (D-045, the cohort's second opening); serving range coverage stated |
| 15 | Forecast accuracy | *Serving model* section label. Test MAE chart + paired differences vs persistence; later recordings of the same 14 people, not new patients |
| 16 | Personalization | *Serving model.* Forest plot of paired differences; frozen-state control; cold start |
| 17 | Every participant | *Serving model.* Per-participant chart (14/14 at 30 min, 13/14 at 60 min) |
| 18 | Early warning and uncertainty | *Serving model.* Detected onsets, false alarms per observed patient-day, qualified forecast lead vs a threshold rule; range coverage vs target, overall and per participant; meal sensitivity |
| 19 | Research: people held out entirely | *Participant-held-out research.* `gt-nested-2026-10-12-v1` from its `report.json`: v2 recipe and Ridge candidate kept separate; high-glucose trade-off; warning burden; not promoted |
| 20 | Research: warning two hours ahead | *Participant-held-out research.* `gt-2h-2026-10-20` (D-043) from `two_hour_summary.json`: 120-minute error vs persistence, 120- vs 60-minute warnings, profile ablation |
| 21 | Research: what we fixed, and what we could not | *Participant-held-out research.* D-046 re-analysis and the D-048/D-049/D-051/D-052 negative results, each from its saved summary |
| 22 | Research: constrained LightGBM (D-053) | *Pending* until phase 2 maps its locked, verified summary; release gates and outcome |
| 23 | Research: zero-shot foundation baseline (D-054) | From `artifacts/research/gt-foundation-2026-10-21/summary.json`: vs persistence and vs the refitted serving recipe on identical origins; F1 residual descriptive; not fine-tuned, not served |
| 24 | External check | *External cohort, CGM only.* ShanghaiT2DM: D-032 (first opening, 30/60 min) and D-045 (first 120-minute assessment, second opening); not the serving fusion model |
| 25 | Project outcomes | What was built, the provenance finding, measured outcomes, the corrected re-run and the fusion constraint, reproducibility |
| 26 | Limitations | Cohort, population, blinded CGM, medication, profile as identity code, thresholds, intervals, retrospective; zero-shot foundation baseline only |
| 27 | Next steps | Evidence needed before use with Indian patients; AI-READI under the declared successor protocol; optional foundation-model fine-tuning |
| 28 | Team, links, reproducibility and licenses | Team; repository and video links (added after publication/upload); quick start; data citation; experiment ID |

The deck follows the prompt's twelve-topic structure (problem, use case, twin definition, data, availability/leakage,
architecture, models, clinician workflow, demonstration, evaluation, limitations, next steps) with one evidence slide
on learner selection, one on what the profile fusion does and does not show, three evaluation slides and a project-outcomes slide (the form asks for a presentation with
“project details and outcomes”).
