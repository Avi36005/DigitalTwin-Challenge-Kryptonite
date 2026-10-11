# Shared contracts (`schema_version: "1.0"`, prefix `/api/v1`)

**Owner:** `ml/glucotwin/schemas.py` (Pydantic). The API serves these models directly; `glucotwin contracts export`
writes `packages/contracts/openapi.json` and schema-validated example payloads to `packages/contracts/examples/`;
`npm run contracts` (in `apps/web`) generates `packages/contracts/src/schema.d.ts`. The web app imports only
these generated types (`apps/web/src/api/types.ts`). Any change must update schema, OpenAPI, examples, types and
this page together — run `make contracts`.

## Conventions

* Identifiers are opaque strings. Dataset participants use salted pseudonyms (`pt-xxxxxx`); synthetic ones `SYN-*`.
* Missing numeric values are `null` — never 0, `"N/A"` or `NaN`.
* Timestamps are offset-qualified ISO-8601. Dataset timelines use the declared synthetic UTC mapping
  (`synthetic-utc-day-aligned-v1`): source time of day preserved, study day 1 = 2000-01-03, the `Z` is a transport
  convention, not a verified timezone.
* Glucose is mg/dL everywhere; carbohydrate g; activity METs (converted from the source's METs × 10).
* `observed_at` = when it happened; `available_at` = when the system could know it. Everything served for a
  session obeys `available_at ≤ clock`.

## Resources

| Resource | Key semantics |
|---|---|
| `PatientSummary` / `PatientDetail` | Catalogue entry with identifiers, cohort label **with provenance**, attribute *availability* (no clinical values), coverage, active session; detail adds time policy, availability policy and `evaluation_segments` (training/validation/calibration/test bounds) |
| `SessionProfile` | Baseline values as known at the session clock; `status` ∈ available / not_yet_available / missing_in_source / excluded_suspect |
| `ObservationEvent` | `event_id, patient_id, kind (glucose/meal/activity), observed_at, available_at, source, quality, quality_flags, units, values` |
| `ReplaySession` | `id, patient_id, patient_alias, created_at (wall clock), mode, clock_at, status, speed, revision, timeline, time_policy, freshness, released_event_count` |
| `TwinState` | Session-clock view of history, episode state, personalization (per-horizon matured residuals, correction, consumed forecast IDs) |
| `Forecast` | Immutable: `forecast_id, session_revision, as_of, model_version, model_family, personalization, observed_glucose, estimates[], trajectory (null), event_risk[], episode_state, quality, explanations[], split_segment` |
| `HorizonEstimate` | `horizon_minutes, target_at, predicted_mg_dl, lower_mg_dl, upper_mg_dl, interval_level, interval_status, components{population_mg_dl, patient_correction_mg_dl}` |
| `EventRisk` | `probability` is always `null` (no calibrated event model); `score` is the uncalibrated forecast margin in mg/dL with `score_kind = forecast_margin_mg_dl`; `state` ∈ eligible / already_high / in_episode / unknown / insufficient |
| `LatestForecast` | `availability` ∈ available / stale / not_ready, `age_minutes`, reasons, forecast |
| `Alert` | Research warning episode with evidence, supporting forecast IDs, outcome (pending / onset_observed with lead time / no_onset_observed / unknown) and local acknowledgement |
| `EvaluationReport` | `status` ∈ completed / not_run / unavailable / synthetic_only, protocol, cohort accounting, selection record, forecast/event/interval rows, optional experiments, limitations |
| `ErrorEnvelope` | `{schema_version, error: {code, message, request_id, details}}` — never a stack trace |

Enumerations: modes `dataset_replay | synthetic_demo`; session status `ready | playing | paused | completed | error`;
forecast quality `ok | degraded | insufficient`; control actions `play | pause | step | seek | reset`.

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness |
| `GET /health/ready` | Separate readiness for dataset store, synthetic store, model artifacts and evaluation |
| `GET /patients?mode&limit&cursor` | Paginated catalogue (no future observations, no clinical values) |
| `GET /patients/{id}` | Catalogue detail + evaluation segments |
| `GET /replay/sessions` | Local sessions, newest first |
| `POST /replay/sessions` | Create (`patient_id, mode, start_at?, speed`) |
| `GET /replay/sessions/{id}` | Authoritative clock, status, revision, freshness |
| `POST /replay/sessions/{id}/control` | `play`, `pause`, `step{steps}`, `seek{seek_to}`, `reset`, optional `speed`; serialized per session |
| `GET /replay/sessions/{id}/events?cursor&limit` | Released events in deterministic order; cursor `r{revision}.{index}`; old revision → `409 stale_cursor` |
| `GET /replay/sessions/{id}/profile` | Clock-filtered baseline values |
| `GET /replay/sessions/{id}/twin` | Twin state at the clock |
| `GET /replay/sessions/{id}/forecast` | Latest forecast or explicit not-ready/stale response |
| `GET /replay/sessions/{id}/forecasts?cursor&limit&order` | Immutable issued forecasts of the current revision (≤ clock) |
| `GET /replay/sessions/{id}/alerts` | Research warnings and review state |
| `POST /replay/sessions/{id}/alerts/{alert_id}/acknowledgement` | Idempotent local acknowledgement; sends nothing |
| `GET /evaluations/latest` | Measured report built from saved artifacts, or `not_run` |

Errors: 404 for unknown resources, 409 for stale cursors / completed replays, 422 for malformed commands
(`validation_error`, `time_out_of_bounds`, `mode_mismatch`). Scientific abstention is a normal 200 response with
`quality.status = insufficient`, never an HTTP error.

## Confidence, data quality and urgency are different things

* **Model confidence** — the conformal interval width (when calibrated) and the forecast `quality`.
* **Observed data quality** — freshness, gaps, sensor-limit flags, reasons on the forecast.
* **Clinical urgency** — not modelled. The research warning is an uncalibrated score against a research
  threshold and is never presented as triage.

## Example payloads

`packages/contracts/examples/`: complete synthetic patient detail, synthetic ready session, session profile with a
nullable field, insufficient-history forecast, valid forecast with calibrated interval, valid forecast with
unavailable interval, malformed control command error. All are generated by the running service in synthetic
mode and validated against the Pydantic models during export.
