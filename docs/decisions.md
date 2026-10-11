# Decision log

Dates are 2026-10-11 unless stated. "Before evaluation" means before any test-segment metric was computed.

| ID | Decision | Reason | Consequence |
|---|---|---|---|
| D-001 | Topic: GlucoTwin (Type 2 diabetes), as selected in the prompt pack | Best route to a complete, defensible submission (see `context.md` research) | Other topics not built |
| D-002 | Stack: FastAPI/Pydantic + React/TS/Vite; LightGBM first, CatBoost challenger | Prompt pack defaults; CPU-only, student-runnable | No cloud/GPU/LLM dependency |
| D-003 | Download CGMacros from the PhysioNet open-data S3 mirror | `physionet.org` delivered ~12 KB/s; the mirror is byte-identical and verified against the published `SHA256SUMS.txt` | `glucotwin data download` uses the mirror by default; `--primary` uses physionet.org |
| D-004 | Recover native Dexcom readings from the interpolated 1-minute table (integer knots + integer collinear points on the 5-minute grid) | Inspection showed linear interpolation; no non-integer collinear midpoints were found, supporting genuine collinear readings | One-minute rows never count as observations; timestamps known to the minute |
| D-005 | Primary device: Dexcom G6 Pro for all participants; Libre stored separately, not stitched | Finer native cadence (5 min); avoids mixing devices | Libre sensitivity analysis not run in v1 |
| D-006 | Cohort label from the dataset's documented HbA1c criterion (T2D: HbA1c > 6.4 %) | No diagnosis column exists | 14 primary participants; documented dictionary unit discrepancy (mmol/mol vs %) |
| D-007 | Time policy `synthetic-utc-day-aligned-v1`; no time-of-day features | Dates are shifted and timezone undocumented | Clock shown as "Day N · HH:MM (replay time)" |
| D-008 | Meals excluded from the primary model; optimistic meal-logging sensitivity run separately | Real-time availability of logs is undocumented | Primary model uses glucose history, wearable activity and (in one candidate) baseline profile |
| D-009 | Sensor and wearable latency = 0 in replay | Study CGMs were blinded; no transmission timing exists | Stated as a replay approximation everywhere |
| D-010 | Protocol frozen in `configs/experiment.yaml` (`gt-primary-2026-10-11-v1`) before fitting | Prevents test-informed choices | Test evaluated exactly once |
| D-011 | Before any fit: removed CatBoost `min_data_in_leaf` from the search space; simplified alert episode merging to a single 30-minute rule | `min_data_in_leaf` is incompatible with CatBoost's default symmetric trees; one merge rule is easier to state | Config hash changed before the first fit; no results affected |
| D-012 | A validation-only dry run on real data (`--validation-only`) preceded the single full run | Catch pipeline bugs without touching test | No protocol change resulted |
| D-013 | Serving model selected by the declared rule: `lightgbm:dyn-v1` (tie margin 0.5 mg/dL → simpler/smaller) | Declared before evaluation | Profile-augmented models scored better on test; we did **not** switch after seeing test results |
| D-014 | Patient adaptation adopted for serving | Lowered validation-selection macro MAE (adoption rule) | Selected settings (k = 96, half-life 240 min) lie at the grid edge |
| D-015 | After the frozen run: pending adaptation targets now wait up to 120 min for late-arriving readings instead of being dropped | Found by a unit test; matters only when glucose arrives late | Verified to reproduce every evaluated prediction exactly (max abs diff 0.0) because CGMacros glucose has zero latency |
| D-016 | Contract extension (still schema 1.0, additive): `GET /replay/sessions`, `ReplaySession.created_at/patient_alias`, `PatientDetail.evaluation_segments` | Needed by the premium UI (session list, recent replays, in-sample labelling) | Schema, OpenAPI, examples and TS types regenerated together |
| D-017 | UI follows `GlucoTwin-Premium-UI-Prompt.md` (white sidebar workspace) instead of Prompt 04's visual direction | User supplied it mid-build as a replacement UI prompt | Prompt 04 behavioural requirements retained |
| D-018 | Coverage fraction capped at 1.0 and expected count made endpoint-inclusive | Minute-rounded timestamps produced values like 100.2 % | Display only; experiment origins byte-identical |
| D-019 | Chronos-Bolt not attempted | Optional track; core work prioritised before the deadline | Reported as "Not run" |
| D-020 | Code license MIT; copyright holder "Avinash Gehi and Hardik Hinduja (Team Kryptonite)" (was the placeholder "GlucoTwin contributors") | Prompt requires an open-source license; team names supplied on 11 Oct 2026 | Team should confirm the holder wording before publishing |
| D-021 | `context.md` git-ignored | It contains a personal email address | Team decides whether to publish it |
| D-022 | Adopted prompt pack v3: the Unstop submission form's twelve README items become the README structure; demo video targets 20:00 (form: 15–20 min) and replaces the 22-minute plan | v3 transcribes the user-supplied submission form | `docs/submission_checklist.md`, `docs/submission_access_audit.md`, new `docs/demo_script.md`; no model, data or UI behaviour changed |
| D-023 | Team details filled with the names the user supplied (Kryptonite; Avinash Gehi, leader; Hardik Hinduja); college/incubator left missing | Never infer affiliation | README item 2 stays "Missing" until supplied |
| D-024 | Demonstration sequence recorded from the API by `scripts/demo_sequence.py`; recorded-data missing-data case = Participant 12, a genuine 70-minute Dexcom gap (Day 9 · 10:29–11:39) in its test period | v3 asks for a deterministic sequence with genuine metadata, including a missing-data case | Video narration cites only values in `reports/demo_sequence.md` |
