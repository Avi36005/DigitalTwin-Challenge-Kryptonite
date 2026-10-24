# GlucoTwin research workbook — methodology and use

`GlucoTwin_Research_Workbook.xlsx` traces every public claim in the deck, README and narration to a saved source value
and shows the calculation. It is an evidence companion, not a new experiment: building it fits nothing and re-opens no
assessment. A source match shows a number was reported faithfully; it is **not** clinical validation.

## Sheets

| Sheet | Content |
|---|---|
| ClaimIndex | One row per claim: exact text, every location, scope, status, source IDs, a formula for the value, the stated value and a match check. Live status counts (COUNTIF) at the top. |
| Sources | Each source value stored **once**, at full precision, with its repository path, JSON pointer / field locator, source date, file SHA-256, protocol identity and publication status. All other sheets reference these cells. |
| Cohorts | Who each result counts: dataset, participants, split roles, horizon, origins, hours, onsets, inspected status. |
| Forecasts | MAE by evaluation group, model and horizon, persistence on the same origins, candidate − persistence and relative change (formulas), saved paired differences and CIs. Chart: serving vs persistence. |
| WarningRanges | Warning counts with explicit numerators and denominators, notice shares, false-alarm rates, time in warning, range coverage and per-person extremes; trend context with validation and final-test rows kept apart. Chart: range coverage vs the 80 % target. |
| Studies | D-032 and D-043 … D-054: purpose, population, protocol first-commit time vs run/open time, fit budget, opening status, candidate/control metric, gate outcome, adoption, negative findings. D-047 is software (public mode), not a model experiment. |
| Gates | The declared gates applied with formulas to unrounded values, next to each artifact's own saved pass/fail flag. |
| Verification | Test runs from the saved ledgers (commit, command, times, exit, counts, logs, JUnit), parity runs, and author-reported rows. |
| Guardrails | Non-numerical behaviours mapped to code and to tests that passed in the saved JUnit. |

## Status meanings

* **supported** — The stated value or fact matches a saved artifact, report or dataset record named in Sources.
* **supported-arithmetic** — Follows by arithmetic from stated definitions (formula shown); no experiment involved.
* **tested** — Behaviour covered by a test that passed in the saved test record (JUnit) named in the row.
* **implemented** — Present in code or configuration only; no saved passing test is cited for the behaviour.
* **negative-result** — A saved study result that did not meet its declared bar; reported as negative, not as a gain.
* **author-reported** — Stated by the team without a saved log, artifact or primary source in the repository.
* **proposed/illustrative** — A proposal, scenario or illustration; not an evidential claim.
* **pending** — Evidence is not on this installation or a primary-source check is still to be done.
* **unsupported/contradicted** — The saved source disagrees with the stated value, or no support exists.

A numeric claim is checked automatically (and again by the `Check` formula): the stated value must lie within half a
unit of its last stated decimal of the source value, otherwise the builder sets the claim to `unsupported/contradicted`;
if the source file is absent it becomes `pending`. A source value that is itself an exact rounding tie at its own saved
precision (for example 22.305 saved with three decimals, stated as 22.30) is accepted and flagged in the limitation
column.

## Aggregation and conventions

* **MAE** is the mean absolute error in mg/dL, averaged **equally over participants** (participant-macro) unless a row
  says pooled. **RMSE** is reported where the source has it; it is not interchangeable with MAE.
* **Sign convention:** differences are **candidate − control**; negative means the candidate had lower error. Where a
  study saved a positive "gain" or "improvement" (D-048, D-049, D-050), the Gates sheet labels it as such.
* **Matching:** every difference compares the same forecast origins and people as its source analysis. Rows from
  different evaluation groups (serving test, participant-held-out internal, external CGM-only, synthetic) are never
  compared with each other.
* **Denominators:** notice shares (≥ 15 / 30 / 60 min) divide by **all** eligible onsets (64 on the serving test), so a
  missed onset counts against them; the median qualified lead uses **detected** onsets only (61). False alarms per
  observed patient-day divide the saved false-alarm count by the saved **observed** patient-day denominator; per
  eligible patient-day uses the different, smaller **eligible** base. Neither is recomputed from rounded hours.
* **Counts are different things:** 15,440 parity comparisons are forecasts (issued origins × two horizons); forecast
  origins, matched targets, participants and episodes are separate counts.
* **Uncertainty:** confidence intervals are the saved participant-cluster bootstrap endpoints from each artifact (seed
  and resample count as recorded by the study, e.g. 2,000 resamples for D-053). The workbook never creates a new
  interval and never treats overlapping windows as independent people.
* **Gates** use unrounded values: D-053's high-target worsening is about +1.0658 against a +1.0 limit, so the gate fails
  however the value is displayed.

## Populations

The serving model's results are **later recordings of the same 14 people** (final test segment, inspected,
retrospective). Participant-held-out studies reuse 14 already-inspected people (internal validation, not an untouched
cohort). The 98-person ShanghaiT2DM checks test a **CGM-only** procedure, not the serving fusion model. CGMacros has 45
participants; 14 form the Type 2 evaluation group. Synthetic participants are fictional and never evidence.

## Freshness and provenance

Each Sources row carries the source file's SHA-256 and date (the artifact's own timestamp where it has one, else the
last git commit, else the file time). Most full artifacts live under `artifacts/`, which is **git-ignored**: those rows
are marked `local / reproducible-only (git-ignored)` and a judge cannot download them from GitHub; they can be
regenerated with the recorded-data path (`make data-download && make data && make experiment`, then the research
targets), after which the hashes can be compared. Files marked `public in repo (tracked)` are in the repository.
Protocol-before-run uses git commit times of `configs/experiments/*.yaml`; that is local commit evidence, not a
clinical trial registration.

The latest full local test matrix is dated to commit `f073a10` (22 Oct 2026); it is not a pass on any later revision.
Fresh-clone checks reported by the team on 23 Oct have no saved logs and are marked author-reported.

## Rebuild and check

```bash
uv run --group docs python scripts/build_research_workbook.py
uv run --group docs python scripts/check_research_workbook.py   # LibreOffice recalculation + checks
```

To add slide or narration claims, edit `DECK_CLAIMS` / `EXTRA_LOCATIONS` in `scripts/build_research_workbook.py` and
rebuild.
