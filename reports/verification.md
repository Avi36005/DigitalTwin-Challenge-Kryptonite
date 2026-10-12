# Verification record

Environment: macOS 15.7 (Darwin 24.6, Apple M4, 10 cores, 16 GB), Python 3.12.12 (uv 0.9.14), Node 26.7 / npm 11.19,
Playwright Chromium headless shell 156. Date: 2026-10-11. All results below were actually run; nothing is assumed.

This record covers the state after the UI redesign (`glucotwin-ui-redesign 2`, Prompts 01–04) and the model-pipeline
corrections (Prompt 05, `reports/repair_report.md`).

## Main working copy (CGMacros imported)

| Command | Exit | Outcome |
|---|---|---|
| Reproduce the review findings on the unchanged code | — | 5,711 of 39,939 v1 origins with `act_cov_60 > 1` (max 1.0833); two warnings + one onset credited twice online and once offline; 2 serving test episodes with episode-start lead > 60 min (max 155); range coverage 74.37 % / 75.66 %; false alarms per 17.5 eligible days vs warnings per 26.8 observed days |
| `uv run glucotwin experiment build` (v2) | 0 | New origin table `experiment/gt-primary-2026-10-11-v2/`; split hash, data fingerprint, segments, labels, quality and glucose features identical to v1; activity features changed; `act_cov_60 ≤ 1` everywhere |
| `uv run glucotwin experiment run` (v2) | 0 | 110 s; same declared selection (`lightgbm:dyn-v2`, adaptation adopted); test MAE 13.15 / 20.81 mg/dL; serving `lightgbm.dyn-v2.gt-primary-2026-10-11-v2` registered; v1 artifacts untouched |
| Recompute v2 test metrics from `predictions.parquet` | 0 | All 32 MAE/RMSE rows match `metrics.json` (max difference 0) |
| Online replay vs offline predictions (v2, 4 participants, test period) | 0 | 1,152 forecasts; max difference 0.05 mg/dL (API rounds to 0.1) |
| Serving identity | — | Registry, `/api/v1/health/ready`, `/api/v1/evaluations/latest` and the forecast-details drawer all show `lightgbm.dyn-v2.gt-primary-2026-10-11-v2`; v1 protocol hash `e049a6a7769f8ff8` still reproduced from the archived config |
| `uv run glucotwin experiment report` | 0 | `reports/evaluation_report.md` describes v2 as a corrected retrospective result; v1 report archived unchanged |
| `uv run ruff check .` | 0 | All checks passed |
| `uv run pytest` | 0 | 46 passed (adds 18 correction tests: activity boundaries, overlap, missing/duplicate/delayed summaries, offline/online feature parity, transformation-fingerprint loading, one-to-one matching, follow-up censoring, incremental = batch matching, qualified lead, time bases) |
| `npm run typecheck` / `npm test` / `npm run build` (apps/web) | 0 | Types OK; 35 Vitest tests passed; production build OK (landing and workspace in separate chunks) |
| `npm run e2e` (own API on :8010 with throwaway `GLUCOTWIN_VAR_DIR`, own web server on :5180) | 0 | 13 passed: replay journey, missing/stale/abstention, recorded-data ranges + drawer, evidence semantics + sorting + data quality, API failure + landing without API, 1920×1080 demo sequence (Participant 01, Participant 12), mobile drawer, phone landing, landing actions, old `/?session=` link (same session, clock unchanged, Back works), old page URLs and unknown session, heading focus and scroll on navigation |
| Layout check: 8 pages/states at 390, 768, 1024, 1280 and 1440 px | 0 | No page-level horizontal overflow; screenshots inspected and corrected (chart labels, sidebar wrapping, table scroll containers) |
| `uv run --group docs python scripts/build_submission_assets.py` | 0 | Deck (19 slides) and architecture PDF built from the serving experiment's metrics; slides 15–16 rendered and inspected |
| `uv run python scripts/demo_sequence.py` | 0 | 5 scenes recorded from the v2 API: Participant 01 warning 08:55 → false alarm; rewind; warning 20:25 → onset 20:45 (forecast lead 20 min); Participant 12 genuine 70-min gap → stale → abstention; SYN-E, SYN-D, SYN-C |
| `uv run python scripts/landing_preview.py` | 0 | Landing chart refreshed from the synthetic demonstration model (fictional data) |
| `uv run python scripts/check_submission.py` | 0 | 12/12 mandatory README sections; 45/45 README links and images pass local checks |
| Narration word count of `docs/demo_script.md` | — | 2,156 words ≈ 16.6 min of speech at 130 wpm + screen actions; **a plan, not a recorded duration** |

## Prompt pack v4 — larger data, nested benchmark, warnings, ranges, integration (2026-10-12)

| Command | Exit | Outcome |
|---|---|---|
| ShanghaiT2DM archive fetched from the figshare URL in `configs/sources.yaml`; `glucotwin data download/verify --dataset shanghai_t2dm` | 0 | 3,738,354 bytes, MD5 `4bfb61cf…` = publisher value; re-running transfers 0 bytes |
| `glucotwin data import --dataset shanghai_t2dm` | 0 | 100 people, 109 recordings, 0 failures, 3.3 s; 16 T1DM files not imported |
| `glucotwin data canonical` | 0 | 45 CGMacros partitions; the model store's glucose tables equal the canonical layer for all 45 (0 mismatches) |
| `glucotwin data manifest` | 0 | Inventory + audit written; 199 recordings, 19,656 pairs, max overlap 0.17, 0 flagged |
| `glucotwin research smoke` | 0 | Development-only timing: ~13 CPU-min of tree fits estimated; declared budget kept |
| `glucotwin research freeze` | 0 | Protocol hash `7ef1a58ff9ec1807`, split hash `e3695ca98334797c` (before any fit of this experiment) |
| `glucotwin research develop` | 0 | 12 fold/track pipelines frozen in 13.5 min (5 workers × 2 threads) |
| `glucotwin research assess` | 0 | Outer folds opened once (31 s); both candidates packaged; online/offline parity 0.0 mg/dL on 2,843 / 948 forecasts, identical warning firings (45 / 45) |
| `glucotwin research external` | 0 | ShanghaiT2DM opened once with the frozen portable candidate: 98 people, 29 s |
| `glucotwin research assess` again (no reason) | 1 | Refused: "already opened … needs --reopen-reason" |
| `glucotwin research promote --track multimodal_5min` (no `--yes`) | 0 | Dry run only; `artifacts/registry.json` unchanged (last modified 2026-10-11 21:32), still serving `lightgbm.dyn-v2.gt-primary-2026-10-11-v2` |
| Independent recompute from `assessment/predictions.parquet` | 0 | Selected pipeline 13.8836 / 22.3046 mg/dL and coverage 80.07 % / 78.81 % match the report |
| `uv run ruff check .` | 0 | All checks passed |
| `uv run pytest` | 0 | 89 passed (adds 17 data-expansion, 13 research-unit, 8 research end-to-end on fictional participants in a throwaway home, 2 v2-preservation, 3 API tests) |
| `glucotwin contracts export` (throwaway `GLUCOTWIN_VAR_DIR`) + `npm run contracts` | 0 | OpenAPI, 7 examples and TypeScript types regenerated (additive, schema 1.0) |
| `npm run typecheck` / `npm test` / `npm run build` | 0 | Types OK; 38 Vitest tests passed; build OK |
| `npm run e2e` | 0 | 15 passed (adds research evidence vs serving model, data sources and scale, mobile overflow check); screenshots 07–10 inspected and the data-sources table re-laid out until it fit at 1440 px |
| `uv run python scripts/check_submission.py` | 0 | 48 links, 0 failures |

## Clean copy of the latest version (2026-10-12, `scripts/clean_copy_check.sh`)

Only Git-publishable files (`git ls-files --cached --others --exclude-standard`, 203 files) copied into an empty
directory; no dataset, artifacts, caches or local state. Two runs.

**Synthetic-only path** (no dataset, plus the documented ShanghaiT2DM acquisition), after the fixes below:

| Step | Exit | Outcome |
|---|---|---|
| `make setup` | 0 | Python and web dependencies installed |
| `make synthetic` | 0 | Fixtures and the synthetic demonstration model |
| `make test` | 0 | 92 passed, 4 skipped (need local artifacts or a Git work tree) |
| `make test-web` | 0 | Types, unit tests and production build |
| `make e2e` | 0 | 10 passed, 5 skipped (recorded-data and research journeys need datasets) |
| `make data-shanghai` | 0 | Archive downloaded from figshare, publisher MD5 verified, 100 people imported |

**Full recorded-data path** (CGMacros files copied from this machine instead of the 657 MB download and verified
against `SHA256SUMS.txt` by `make data`; the team's pseudonym salt copied so pseudonyms match):

| Step | Exit | Outcome |
|---|---|---|
| `make data` → `make experiment` | 0 / 0 | 45 people imported; v2 re-run in 148 s: `predictions.parquet` bit-identical, all 64 metric rows identical, same model-artifact fingerprint |
| `make manifest` → `make research` | 0 / 0 | Full nested experiment in 878 s: every headline number identical (selected 13.884 / 22.305, portable 14.057 / 22.208, external 11.153 / 20.105 mg/dL); outer-fold `predictions.parquet` bit-identical; all 4,029,624 external prediction rows identical when joined on public ShanghaiT2DM IDs (max difference 5.7e-14) |

Found by these runs and fixed:

* The research end-to-end test copied the real v2 model and registry from git-ignored `artifacts/`, so it failed in a
  fresh checkout; it now builds a fictional recipe and uses the synthetic demonstration model.
* With no recorded-data evaluation, Model evidence defaulted to the unassessed research experiment instead of
  “Evaluation not run”; it now falls back to the serving-evidence report.
* The script imported ShanghaiT2DM before copying the salt (different Shanghai pseudonyms); the salt is now copied
  first.
* Fold freeze hashes included wall-clock fit times, and CatBoost files embed a random model GUID and training time,
  so identical runs had different hashes. New pipelines use a timing-free freeze hash (version 2) and CatBoost files
  are saved with fixed metadata (byte-identical re-saves, tested); the original v1 pipelines keep and still verify
  their recorded hashes.
* Not fixed, documented: the data fingerprint hashes `provenance.json`, which contains the retrieval time, so it
  differs between installations with identical files — compare the per-file SHA-256 values instead. Without the
  team's salt, fold membership and row order of `gt-nested-2026-10-12-v1` differ (a valid but different draw); the
  declared successor protocol assigns folds and orders rows by public source keys.

## Fresh copy before prompt pack v4 (2026-10-11; only Git-publishable files; no dataset, no artifacts, no local state)

| Command | Exit | Outcome |
|---|---|---|
| `make setup` | 0 | Python and web dependencies installed |
| `make synthetic` | 0 | Synthetic fixtures and the `dyn-v2` synthetic demonstration model registered |
| `make test` | 0 | 44 passed, 2 skipped (dataset provenance — not imported; Git-ignore check — not a Git work tree) |
| `make test-web` | 0 | 35 passed; build OK |
| `npm run e2e` | 0 | 10 passed, 3 skipped (recorded-data journeys need CGMacros) |

## What the checks establish (and their limits)

* **Information cutoff:** future values and meals cannot change earlier features. Late-logged meals and late activity
  summaries stay hidden until available. Labs with a later availability time stay missing. Limit: availability times
  for real data are policy assumptions (blinded CGM, undocumented meal logging).
* **Feature correctness:** activity windows count exactly the overlapping support, a boundary summary adds nothing,
  coverage never exceeds the window, and missing data stays missing. Artifacts refuse mismatched transformations.
  Limit: proportional allocation at non-aligned origins is an approximation.
* **Chronological evaluation:** purging keeps label support inside segments; selection, adaptation, calibration and
  thresholds use validation and calibration only. Limit: v2 re-uses a test segment already inspected in v1.
* **Warning accounting:** one onset per warning episode online and offline, with outcomes final only after follow-up.
  The qualified lead never exceeds the horizon. Limit: the declared F1 threshold rule is unstable (flat curve).
* **Replay equivalence and isolation:** forward vs seek vs reset-then-seek give identical forecasts; sessions are
  isolated; rewind removes future forecasts and alerts; online equals offline within rounding.
* **UI behaviour:** temporal visibility, gap rendering, loading vs absence vs abstention vs model unavailable, ranges
  labelled with their target coverage, late responses from older revisions rejected, route migration, scroll and
  focus on navigation, mobile drawer and landing menu, API-down behaviour.
* **Submission package:** twelve README sections, link targets present and not Git-ignored, PDF/PPTX open. Limit:
  public visibility, signed-out access and the YouTube video are **not verified** — nothing has been published or
  uploaded.

Not verified: accessibility certification (only manual checks and semantic structure), offline operation after setup
(not tested with networking disabled), Windows/Linux hosts, browsers other than Chromium, a Lighthouse score (not
measured), the optional Chronos-Bolt track.
