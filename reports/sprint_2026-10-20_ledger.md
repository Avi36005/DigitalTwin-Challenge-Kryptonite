# Sprint ledger — 20–21 October 2026 (eight-hour local improvement)

Start 2026-10-20 20:32 IST · end 2026-10-21 04:32 IST · branch `public-demo` (main = `535575b`, release tag
`v1.0-2026-10-20` = `1ddd116`). Local only: no deployment, no publication, no visibility change.

## Baseline (verified 20:32 IST)

* Serving registry (`artifacts/registry.json`): dataset_replay = `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`,
  synthetic_demo = `synthetic-demo.lightgbm.dyn-v2.v1`; the running local API reports the same. No working-tree change
  touches the registry.
* Recording app on :8000/:5173 is left running; specialists that edit the web app work in separate Git worktrees so
  the recording app does not hot-reload half-finished edits.

## Inventory

| Item | State | Owner | Acceptance check |
|---|---|---|---|
| Public synthetic demo mode (isolation, synthetic-only, limits, one process, Docker) | Done, committed `1d6ba97`; public browser tests 4/4 locally and in the container | Lead | Kept; not deployed |
| Bundled aggregate-only evidence for the public demo | Done `e5d52ff`, `8f90560` (two public-mode ID leaks found and fixed) | Lead | pytest 121 + vitest 102 at integration |
| Public-demo documentation (README, deploy.md, D-047) | Done `e5d52ff` | Lead | Link check 0 failures |
| §4A Review queue correctness (unknown ≠ zero, failed forecast state, session/revision/cutoff validation, rewind, deep link) | Done `6ff105f`, `d34480c` | Specialist A | Targeted tests for delayed, partial-failure, playing, paused, rewind, duplicate-session cases |
| §4B Twin behaviour panel (population + correction + final, maturity state, inputs used, warning track record, coverage for the exact model) | Done `e08df48`, `e8c08d4`, `f2e4a89`, trend line `457eb7a` | Specialist A | Values from API only; vitest + e2e |
| §4C Frozen review summary verification (long notes, missing profile, stale, abstention, pending outcomes; PDF inspected) | Done: reports/review_summary_check.md | Specialist C + Lead | Exported PDF opened and inspected |
| §5 Model: LightGBM–CatBoost population blend, protocol before fitting | **Done — negative.** Protocol `2799ab3` (20:36:41 IST) before first blend score (20:36:54); dev 60-min gain +0.02 vs ≥ 0.5 target; incumbent kept; outer folds not opened (`fdd6924`) | Specialist B | Met: stop rule followed |
| Error by glucose trend for the exact serving model (validation segment) | Done `81fb9b5`; UI line pending A's panel merge | Lead | pytest |
| §6 Evidence manifest (claim → model → population → horizon → type → artifact → report → status); summaries distinguish absent / malformed / incompatible / valid; D-046 verdict wording not a declared bar | Done `37cd812`: 16/17 match, 0 mismatch | Specialist C | Manifest generated from saved files; tests |
| §8 Judge demo sync (2-min PPT intro, app from 02:00, 3-minute judge journey) | Done `3e88a2a`, `49defb8` | Lead | Script, deck, README consistent |
| §9 Handoff report | Done: reports/sprint_2026-10-20_handoff.md | Lead | This ledger + final report |

## Checkpoints

| IST | State |
|---|---|
| 20:32 | Start; inventory; registry verified |
| 20:37 | D-048 protocol committed; A, B, C running |
| 20:41 | D-048 negative (incumbent kept); trend-error evidence committed |
| 21:42 | Specialists A and C stopped by usage limits after committing; lead integrated their work |
| 21:54 | Integrated state passes pytest, vitest 126, build, e2e 23 + public 4; link check 0 failures |
| 22:00 | main fast-forwarded to `49defb8`, CI success; local app restarted on the integrated code |
