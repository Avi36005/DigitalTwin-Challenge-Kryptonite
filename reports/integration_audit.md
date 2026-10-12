# Integration audit

Audited 2026-10-11 after the UI redesign (`glucotwin-ui-redesign 2`, Prompts 01–04) and the model-pipeline
corrections (Prompt 05), by inspecting code, running the application and the checks in `reports/verification.md`.

| Area | Evidence | Status | Gaps found → resolution |
|---|---|---|---|
| Data | Versioned adapter `cgmacros-adapter-1.0`; SHA-256 provenance; explicit units; availability policy `conservative-v1`; synthetic-only path works without the dataset | OK | Coverage could exceed 100 % (minute rounding) → capped, endpoint-inclusive (D-018) |
| Features | One feature code path offline and online; activity windows count only the overlapping part of each summary (`overlap-v2`); transformation fingerprint stored in artifacts and checked on load | OK | Activity windows counted up to 65 of 60 minutes (5,711 of 39,939 v1 origins) → corrected feature sets `*-v2`, v1 kept for reproduction (D-025, D-028) |
| Replay | Backend-owned clock; per-session locks; revisions on seek/reset; `409 stale_cursor`; deterministic release order; isolation and forward/seek/reset equivalence tested | OK | Warning outcomes could credit one onset twice online → shared one-to-one matcher (D-025) |
| Forecast | Registered, checksummed LightGBM artifact `lightgbm.dyn-v2.gt-primary-2026-10-11-v2`; 1,152 replay forecasts match the saved offline predictions within the API's 0.1 mg/dL rounding; immutable forecast records | OK | — |
| Evaluation | v1 protocol declared before fitting and preserved; v2 = the same protocol re-run after the fixes and labelled a corrected retrospective result; all 32 v2 test rows recompute exactly from saved predictions; both lead measures and both warning-rate time bases reported | OK | Lead time could exceed the horizon (155 min in v1) → qualified lead added; the declared F1 threshold rule chose −30 mg/dL in v2 (79 false alarms) — reported as is, workload-aware rule proposed (D-026, D-027) |
| Interface | Landing page at `/`; workspace at `/app` with replace-redirects for every old URL; flat white workspace; 13 Playwright journeys (isolated API + web server) including the video's recorded-data sequence at 1920×1080; no overflow at 390–1440 px | OK | "Coverage" label meant availability → renamed; ranges labelled with their target coverage; loading, abstention and model-unavailable states separated; e2e no longer writes sessions into the user's running app |
| Reproducibility | Fresh copy of Git-publishable files: setup, synthetic build, backend and frontend tests (see `reports/verification.md`); recorded-data path via `make data experiment report`; v1 reproducible with `--experiment gt-primary-2026-10-11-v1` | OK | — |
| Submission (v3 form) | README with the form's twelve sections; MIT license; architecture PDF; 19-slide PPTX/PDF built from the serving experiment; 20:00 video plan and an API-recorded demo sequence; checklist and access audit | **Ready for local review — not ready to submit** | College/incubator missing; video not recorded or uploaded; repository not public; Unstop form not submitted |

## Severity-ranked open items

1. **(Team decision) Warning operating point.** The declared validation-F1 rule now fires at a forecast of 150 mg/dL:
   all 64 test onsets detected but 79 false alarms (4.5 per eligible day). This follows the protocol; changing it needs a
   newly declared objective (e.g. a false-alarm budget) evaluated without the inspected test segment
   (`docs/next_experiment.md`).
2. **(Team decision) Static-profile fusion in the serving model.** The serving forecaster selected by the declared rule
   uses dynamic streams only; profile-augmented candidates scored better on test (CatBoost 12.93 / 19.80 mg/dL with
   adaptation). Switching after seeing test results would be test-informed selection.
3. **(Team) Supply the college/incubator; confirm the license holder wording.**
4. **(Team) Record the 20:00 video** following `docs/demo_script.md` (updated for v2 and the new interface); upload as
   unlisted (with authorization); add the link.
5. **(Team, needs approval) Publish the repository** and submit on Unstop before 20 Oct 2026, 7:00 PM IST.
6. (Optional) Chronos-Bolt research track not run.

No defects known to remain in the implemented workflows.
