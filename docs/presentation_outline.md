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
| 10 | Safety guardrails built into the twin | Abstention and Stale/Degraded states, availability-time inputs and the fusion profile gate, bounded patient correction (observed outcomes, 6, ±25 mg/dL, 3-h reset), warning outcomes, ranges with measured coverage, locked tests and 15,440/15,440 parity |
| 11 | Results at a glance | One table, three labelled groups never blended: serving model (later recordings of the 14 known people), participant-held-out research (D-032, D-053, D-054, each from its saved summary) and the external CGM-only check (D-045); serving range coverage stated |
| 12 | Research: zero-shot foundation baseline (D-054) | From `artifacts/research/gt-foundation-2026-10-21/summary.json`: vs persistence and vs the refitted serving recipe on identical origins; not fine-tuned, not served |
| 13 | Project outcomes | What was built, the provenance finding, serving MAE vs persistence and per-person counts, warnings (61/64, false alarms per observed patient-day, 48.4 % ≥ 30 min ahead), reproducibility |
| 14 | Limitations | Cohort and site, blinded CGM, medication and meal timing, profile as identity code, under-covering ranges, retrospective only; next step |
| 15 | Team, links, reproducibility and licenses | Team; repository and video links (added after publication/upload); quick start; data licences; evidence pointers incl. the research workbook |

Trimmed on 24 Oct 2026 from 28 to 15 slides to cut theory; slides 1–5 are byte-identical to the earlier deck. The
28-slide technical deck (fusion analysis, screenshots, per-participant and personalization charts, the full research
series and next steps) is kept as backup in
[`submission/backup_28slide_2026-10-24/`](submission/backup_28slide_2026-10-24/); its numbers are in README §7 and the
[research workbook](submission/GlucoTwin_Research_Workbook.xlsx).
