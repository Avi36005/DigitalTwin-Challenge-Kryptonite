# Documentation index

Every document, grouped by what you want to know. File paths are kept flat on purpose: frozen experiment
protocols, report generators and earlier reports link to these exact paths, and a protocol file cannot change
after it is frozen.

## Start here

| Document | What it answers |
|---|---|
| [`../README.md`](../README.md) | Submission overview: problem, results, how to run, the twelve challenge items |
| [`product.md`](product.md) | Who GlucoTwin is for, what it does, what it deliberately does not do |
| [`architecture.md`](architecture.md) | How the Python package, the API and the web app fit together |

## Model and data — what the numbers mean

| Document | What it answers |
|---|---|
| [`model_card.md`](model_card.md) | The serving model: inputs, adaptation, ranges, warnings, measured results, limits |
| [`data_card.md`](data_card.md) | CGMacros and ShanghaiT2DM: source, licence, cohort, devices, known problems |
| [`feature_availability.md`](feature_availability.md) | When each input becomes usable at a forecast time (the leakage ledger) |
| [`data_schema.md`](data_schema.md) | Normalised store layout and table columns |
| [`decisions.md`](decisions.md) | Every design and protocol decision, with its reason and date |
| [`next_experiment.md`](next_experiment.md) | The declared successor research protocol and what it changes |

## System — how it is built

| Document | What it answers |
|---|---|
| [`replay.md`](replay.md) | Replay clock, release rule, session revisions, immutable forecasts |
| [`contracts.md`](contracts.md) | API contract (`/api/v1`, schema 1.0) and example payloads |
| [`frontend-handoff.md`](frontend-handoff.md) | Web app stack, routes, states and visual rules |
| [`artifact_manifest.md`](artifact_manifest.md) | Every generated artifact, the command that makes it, and whether it may be shared |

## Submission — challenge deliverables

| Document | What it answers |
|---|---|
| [`submission/GlucoTwin_Presentation.pdf`](submission/GlucoTwin_Presentation.pdf) · [`.pptx`](submission/GlucoTwin_Presentation.pptx) | The presentation (generated from the experiment artifacts) |
| [`submission/GlucoTwin_Architecture.pdf`](submission/GlucoTwin_Architecture.pdf) | The architecture diagram (2 pages) |
| [`team_details.md`](team_details.md) | Team and institution details supplied for publication |
| [`submission_checklist.md`](submission_checklist.md) | The twelve form items, their status and the remaining steps |
| [`submission_access_audit.md`](submission_access_audit.md) | Link and file accessibility check (`scripts/check_submission.py`) |
| [`demo_script.md`](demo_script.md) | The video plan (minimum 20 minutes), chapter by chapter |
| [`presentation_outline.md`](presentation_outline.md) | Slide-by-slide outline of the deck |
| [`jury_questions.md`](jury_questions.md) | Anticipated jury questions with evidence-based answers |

## Reports (generated — in [`../reports/`](../reports/))

| Report | Produced by |
|---|---|
| [`evaluation_report.md`](../reports/evaluation_report.md) | `glucotwin experiment report` — serving experiment |
| [`repair_report.md`](../reports/repair_report.md) | Corrections between v1 and v2 |
| [`nested_benchmark_report.md`](../reports/nested_benchmark_report.md) · [`model_upgrade_review.md`](../reports/model_upgrade_review.md) | `glucotwin research report` — people-held-out and external evidence |
| [`data_audit.md`](../reports/data_audit.md) · [`dataset_expansion_audit.md`](../reports/dataset_expansion_audit.md) | `make data` · `make manifest` |
| [`verification.md`](../reports/verification.md) · [`integration_audit.md`](../reports/integration_audit.md) | Recorded test runs and the integration review |
| [`demo_sequence.md`](../reports/demo_sequence.md) | `scripts/demo_sequence.py` — the video's replay sequence, recorded from the API |
| [`ui/`](../reports/ui/README.md) | `make e2e` — application screenshots |
| [`archive/`](../reports/archive/) | The preserved v1 evaluation report |
