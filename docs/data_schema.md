# Normalized data schema

Store layout (`data/processed/cgmacros/v1/`, `data/synthetic/generated/v1/`; both git-ignored):

```text
catalog.sqlite                      store_info, patients(meta_json), profile(attr_json), import_log
patients/<patient_id>/glucose.parquet          primary device (Dexcom) native readings
patients/<patient_id>/glucose_<device>.parquet  per-device tables (Dexcom, Libre) for sensitivity work
patients/<patient_id>/activity.parquet
patients/<patient_id>/meals.parquet
provenance.json  audit.json  experiment/{origins.parquet, split_manifest.json}
```

`store_info.schema_version = "1.0"`; opening a store with another schema fails with an actionable message. Each
participant has its own partition, so importing one never overwrites another. Re-running the import is
idempotent (verified: identical Parquet hashes).

## Tables

**glucose** — `event_id` (string), `observed_at`, `available_at` (UTC timestamps), `value_mg_dl` (float),
`quality` (`ok` | `suspect`), `flags` (`detected_knot` | `collinear_recovered`, plus `sensor_limit_value`),
`source` (`cgmacros-1.0.0:dexcom_g6_pro`).
Readings exactly at the sensor limits (40 or 400 mg/dL) are kept and flagged `suspect`; values outside 40–400 are
dropped and counted.

**activity** — trailing 5-minute Fitbit summaries ending on the 5-minute grid: `window_minutes`, `minutes_covered`,
`heart_rate_bpm` (mean), `mets` (mean, METs = source ÷ 10), `activity_kcal` (sum), `quality` (`ok` or
`estimated` when < 5 minutes covered), `flags` (`mets_not_in_source`, `activity_kcal_not_in_source`).
`observed_at = available_at =` window end.

**meals** — `meal_type` (Breakfast/Lunch/Dinner/Snack/Unspecified), `energy_kcal`, `carbs_g`, `protein_g`,
`fat_g`, `fiber_g`, `amount_consumed_pct`; `quality = estimated`; flags
`macros_estimated;timestamp_from_photo;logging_latency_unknown`.

**profile** (SQLite) — per attribute: `name, label, value, unit, source, available_at, status, note,
availability_rule`. Status: `available`, `missing_in_source`, `excluded_suspect` (documented error codes:
LDL 800, VLDL 400). Unit conversions (lb→kg, in→cm) are recorded in `note`.

**patients.meta_json** — `patient_id, display_alias, mode, dataset, cohort{label, provenance},
eligible_for_primary_analysis, exclusion_reason, primary_device, timeline_start/end, coverage, time_policy,
availability_policy_id, notes, adapter_version`.

## Null semantics

Missing numeric values are `null`/NaN in storage and `null` in JSON. Nothing is zero-filled, carried forward
across gaps, or interpolated. Unknown columns are reported in `audit.json` and not interpreted.

## Timestamp policy

Canonical time = synthetic origin 2000-01-03T00:00Z + (source timestamp − source day 1 at midnight). The
reversible per-participant offset is stored privately in `data/private/cgmacros_pseudonym_map.json` with the
pseudonym mapping (git-ignored). Source time of day is preserved; dates, weekdays and seasons are synthetic and
not used as features.

## Example (glucose, as served by the API)

```json
{"schema_version":"1.0","event_id":"pt-1eef47-dexcom_g6_pro-02294","patient_id":"pt-1eef47","kind":"glucose",
 "observed_at":"2000-01-11T09:10:00Z","available_at":"2000-01-11T09:10:00Z","source":"cgmacros-1.0.0:dexcom_g6_pro",
 "quality":"ok","quality_flags":["collinear_recovered"],"units":{"value":"mg/dL"},"values":{"value":149.0}}
```
(Identifiers differ per installation because pseudonyms use a locally generated salt.)
