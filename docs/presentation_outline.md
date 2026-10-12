# Presentation outline

Finished files: [`docs/submission/GlucoTwin_Presentation.pptx`](submission/GlucoTwin_Presentation.pptx) (editable) and
[`GlucoTwin_Presentation.pdf`](submission/GlucoTwin_Presentation.pdf). Both are generated from the same slide
specification by `scripts/build_submission_assets.py`, which reads every number from the serving experiment's
`metrics.json` (currently the corrected `gt-primary-2026-10-11-v2`), and every team/link line from `configs/submission.yaml` (null values print as “to be confirmed” /
“added after …”). After adding the college, repository URL or video URL to that file, regenerate with
`uv run --group docs python scripts/build_submission_assets.py`.

| # | Slide | Content and evidence |
|---|---|---|
| 1 | Title | GlucoTwin — personalized glucose forecasting between clinic visits; Team Kryptonite (Avinash Gehi, leader; Hardik Hinduja); college to be confirmed |
| 2 | The problem | HbA1c vs between-visit excursions; clinician question; target definition |
| 3 | Use case and boundaries | Users, proposed workflow, what it never does, fit as proposal |
| 4 | What makes it a twin | Operational definition + twin loop figure |
| 5 | Data and provenance | CGMacros facts, cohort, interpolation finding, synthetic fixtures |
| 6 | Availability and leakage controls | Two timestamps, meals excluded, split figure, frozen protocol |
| 7 | Architecture | Architecture diagram |
| 8 | Models and personalization | Baselines, LightGBM/CatBoost, adaptation, conformal prediction ranges (target coverage 80 %), warning score |
| 9 | Why this learner | Validation-only candidate table + declared rule + honest note on profile features |
| 10 | Clinician workflow | Screenshot: recorded-data replay in the test period |
| 11 | Demonstration | Screenshot: forecast details drawer |
| 12 | Forecast accuracy | Test MAE chart + paired differences vs persistence |
| 13 | Personalization | Forest plot of paired differences; frozen-state control; cold start |
| 14 | Every participant | Per-participant chart (14/14 at 30 min, 12/14 at 60 min) |
| 15 | Early warning and uncertainty | Detected onsets, false alarms per eligible day, qualified forecast lead vs a threshold rule; range coverage vs target; meal sensitivity |
| 16 | New people and an independent cohort | Research experiment `gt-nested-2026-10-12-v1` from its saved `report.json` (omitted until run): the three models kept separate (LightGBM v2 demo model, Ridge five-minute candidate, separate 15-minute LightGBM external check); 145 imported, 14 internal, 98 external; high-glucose trade-off; warning burden; external result with intervals; not promoted |
| 17 | Project outcomes | What was built, the provenance finding, measured outcomes (computed from `metrics.json`), the corrected re-run, reproducibility |
| 18 | Limitations | Cohort, population, blinded CGM, medication, thresholds, intervals, retrospective |
| 19 | Next steps | Evidence needed before use with Indian patients; AI-READI under the declared successor protocol |
| 20 | Team, links, reproducibility and licenses | Team; repository and 20:00 video links (added after publication/upload); quick start; data citation; experiment ID |

The deck follows the prompt's twelve-topic structure (problem, use case, twin definition, data, availability/leakage,
architecture, models, clinician workflow, demonstration, evaluation, limitations, next steps) with one evidence slide
on learner selection, three evaluation slides and a project-outcomes slide (the form asks for a presentation with
“project details and outcomes”).
