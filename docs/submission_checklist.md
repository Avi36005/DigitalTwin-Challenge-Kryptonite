# Submission checklist — Digital Twin Challenge 2026 (Happiest Health)

**Source of requirements.** The one-page Unstop submission form supplied by the team (transcribed in prompt pack v3,
inspected 11 October 2026): a **public GitHub repository link** whose root README contains **twelve mandatory items**.
The broader challenge page (checked 11 October 2026) gives the prototype deadline **20 October 2026, 7:00 PM IST**;
the form itself shows no deadline. **Rechecked 14 October 2026:** the challenge page lists the deliverables as README
items and requires a **"Minimum 20-minute video explaining and demonstrating your prototype"** (PowerPoint recording or
unlisted YouTube); deadlines unchanged (registration 18 Oct, submission 20 Oct, both 7:00 PM IST). Where the form
transcription and the challenge page differ, the challenge page governs. Recheck both live pages before submitting and
record any change below.

**Overall status (rechecked 19 October 2026): ready for local review — not ready to submit.** Submission-ready requires every
row below to be *Ready*: today the recorded and uploaded video and the public-access checks are outstanding (the
college was supplied on 17 October 2026). Cloud deployment is not required by the form and is not part of this gate.

## The twelve mandatory README items

Verification date for every row: 19 October 2026 (local repository; `scripts/check_submission.py`).

| # | Form item | README anchor | Evidence (files / URLs) | Status | Owner |
|---|---|---|---|---|---|
| 1 | Team details | [`#1-team-details`](../README.md#1-team-details) | Team Kryptonite; Avinash Gehi (leader), Hardik Hinduja; [`team_details.md`](team_details.md) | Ready | — |
| 2 | College / incubator information | [`#2-college-or-incubator-information`](../README.md#2-college-or-incubator-information) | Vivekanand Education Society's Institute of Technology (VESIT), Mumbai; [`team_details.md`](team_details.md) | Ready (supplied 17 Oct 2026) | — |
| 3 | Project title | [`#3-project-title`](../README.md#3-project-title) | README | Ready | — |
| 4 | Problem statement | [`#4-problem-statement`](../README.md#4-problem-statement) | README; [`product.md`](product.md) | Ready | — |
| 5 | Healthcare use case | [`#5-healthcare-use-case`](../README.md#5-healthcare-use-case) | README (workflow + screenshots); [`product.md`](product.md) | Ready | — |
| 6 | Technical stack | [`#6-technical-stack`](../README.md#6-technical-stack) | README; `uv.lock`; `apps/web/package-lock.json` | Ready | — |
| 7 | AI/ML model or framework details | [`#7-ai-and-ml-model-details`](../README.md#7-ai-and-ml-model-details) | README; [`model_card.md`](model_card.md); [`../reports/evaluation_report.md`](../reports/evaluation_report.md) | Ready | — |
| 8 | Demo video — unlisted YouTube, **minimum 20 min** (target 20:15) | [`#8-demo-video`](../README.md#8-demo-video) | Plan: [`demo_script.md`](demo_script.md); sequence: [`../reports/demo_sequence.md`](../reports/demo_sequence.md); link: — | **Missing** — not recorded; not uploaded | Team (recording, upload needs authorization) |
| 9 | Open-source license details | [`#9-open-source-license`](../README.md#9-open-source-license) | [`../LICENSE`](../LICENSE) (MIT, code); data terms in README and [`data_card.md`](data_card.md) | Ready — holder wording to be confirmed | Team |
| 10 | Architecture diagram (PDF/PPT) | [`#10-architecture-diagram`](../README.md#10-architecture-diagram) | [`submission/GlucoTwin_Architecture.pdf`](submission/GlucoTwin_Architecture.pdf) (2 pages) | Ready | — |
| 11 | Presentation with project details and outcomes (PDF/PPT) | [`#11-presentation`](../README.md#11-presentation) | [`submission/GlucoTwin_Presentation.pdf`](submission/GlucoTwin_Presentation.pdf) / `.pptx` (21 slides, incl. “Project outcomes” and the research-evidence slide) | Ready — regenerate after adding video/repository URLs | Team |
| 12 | Files and links accessible without additional permissions | [`#12-accessible-files-and-links`](../README.md#12-accessible-files-and-links) | [`submission_access_audit.md`](submission_access_audit.md) | **Unverified** — local checks pass; public/signed-out checks pending publication | Team |

**Separate form field — GitHub repository URL** (≤ 500 characters): the direct public repository URL, not a local
path or app-hosting URL. Status: **not yet created** (publication requires the team's authorization). Record it in
`configs/submission.yaml` → `links.repository`, then rerun `scripts/build_submission_assets.py` and
`scripts/check_submission.py --online`.

## Other instructions and conflicts recorded

| Instruction | Source | Status / note |
|---|---|---|
| Video length | Challenge page (rechecked 14 Oct 2026): “Minimum 20-minute video”. Form transcription (11 Oct): 15–20 min, unlisted YouTube | **At least 20:00** by both the rendered file and YouTube's displayed duration; target **20:15** so rounding or trimming cannot drop it below the minimum. The challenge page governs; recheck if organisers clarify (D-040) |
| Folder name `Team Name_College Name` | Challenge page (not on the form) | **Done locally (19 Oct 2026, D-042):** top-level [`Kryptonite_VESIT/`](../Kryptonite_VESIT/README.md) indexes the submission files; repository not renamed. Visible to judges once the repository is public |
| Repository public; all files and links accessible | Form and challenge page | **Outstanding** (needs explicit approval). Before publishing: `context.md` stays git-ignored (personal email); `git ls-files data artifacts var` lists only `artifacts/README.md` |
| Team leader submits name, phone, email and repository link | Challenge page / form | **Outstanding** — the team leader submits on Unstop; not automated |
| Deadline | Challenge page: 20 Oct 2026, 7:00 PM IST; form: none shown | Recheck before submitting |

## Challenge rules covered by the build

| Rule | Evidence |
|---|---|
| Anonymised, open-source or synthetic data only | CGMacros (de-identified, open access) + fictional synthetic fixtures; [`data_card.md`](data_card.md) |
| Fusion of static/historical (EHR-like) and dynamic (wearable) data | Baseline profile + native CGM + Fitbit summaries; [`feature_availability.md`](feature_availability.md). **Decided 13 Oct 2026 (D-038, D-039):** the serving forecaster `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion` reads 8 profile values and 38 dynamic features in one model. Disclosed everywhere it is named: the constraint was added after test inspection; no benefit on people held out entirely; the profile can act as an identity code with 14 people; chosen for the brief, not for accuracy ([`model_card.md`](model_card.md)) |
| Working model ingesting both streams and predicting an adverse event | One profile + dynamic model; 30/60-min forecasts + new sustained high-glucose warning; [`../reports/evaluation_report.md`](../reports/evaluation_report.md) |
| Conceptual UI dashboard for a doctor | Working React workspace; [`../reports/ui/`](../reports/ui/) |

## Final pre-submission steps (in order)

- [x] Supply the college/incubator → README §2, `configs/submission.yaml`, `team_details.md`; rebuild slides (17 Oct 2026)
- [x] Team folder `Kryptonite_VESIT/`, README results table and branding, app evaluation wording, hypothetical example (19 Oct 2026, D-042)
- [ ] Confirm the license holder wording in `LICENSE`
- [ ] Record the video per [`demo_script.md`](demo_script.md); measure the rendered duration (**at least 20:00**; target 20:15)
- [ ] With authorization: upload to YouTube as **Unlisted**; confirm the displayed duration is at least 20:00; record URL and displayed duration in `configs/submission.yaml` and README §8
- [ ] With authorization: publish the repository; record its URL; rebuild slides (`uv run --group docs python scripts/build_submission_assets.py`)
- [ ] `uv run python scripts/check_submission.py --online`; open the repository, PDFs, PPTX and video from a signed-out browser; update README §12 and this table
- [ ] `make check` on a fresh clone (synthetic mode)
- [ ] Team leader submits the Unstop form before the deadline
