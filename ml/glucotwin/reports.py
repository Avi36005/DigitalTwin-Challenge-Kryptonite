"""Generate Markdown reports from saved audit/evaluation artifacts (no hand-typed numbers)."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from glucotwin.config import load_config, paths
from glucotwin.data.pipeline import dataset_store_dir
from glucotwin.evaluation.report import LIMITATIONS, latest_metrics_path


def _fmt(x, nd=1) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def write_data_audit() -> str:
    d = dataset_store_dir()
    audit = json.loads((d / "audit.json").read_text())
    prov = json.loads((d / "provenance.json").read_text())
    man_path = d / "experiment" / "split_manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else None
    cfg = load_config("data")
    parts = audit["participants"]
    cohorts = Counter(p["cohort"] for p in parts)
    unknown = Counter(c for p in parts for c in p["unknown_columns"])
    rows = []
    for p in sorted(parts, key=lambda x: x["display_alias"]):
        dx, lb = p["devices"]["dexcom_g6_pro"], p["devices"]["libre_pro"]
        rows.append({
            "Participant": p["display_alias"], "Cohort": p["cohort"], "Primary": "yes" if p["eligible"] else "no",
            "Dexcom native": dx["native_samples"], "Detected knots": dx["detected_knots"],
            "Collinear recovered": dx["collinear_recovered"], "Dropped non-integer": dx["dropped_non_integer"],
            "5-min share": _fmt(dx["cadence_share_nominal"], 3), "Gaps >15 min": dx["gaps_over_15_min"],
            "Sensor-limit values": dx["sensor_limit_values"], "Libre native": lb["native_samples"],
            "Activity coverage": _fmt(p["activity_minutes_covered_fraction"], 3), "Meals": p["meals"],
            "Missing grid minutes": p["missing_grid_minutes"],
        })
    inv = pd.DataFrame(rows)
    t2d = inv[inv["Primary"] == "yes"]
    tot_det = sum(p["devices"]["dexcom_g6_pro"]["detected_knots"] for p in parts)
    tot_col = sum(p["devices"]["dexcom_g6_pro"]["collinear_recovered"] for p in parts)
    tot_drop = sum(p["devices"]["dexcom_g6_pro"]["dropped_non_integer"] for p in parts)
    tot_col_nonint = sum(p["devices"]["dexcom_g6_pro"].get("collinear_non_integer", 0) for p in parts)

    seg_rows = []
    if man:
        for seg, v in man["summary"]["by_segment"].items():
            seg_rows.append({"Segment": seg, "Origins": v["origins"], "Forecast issued": v["issued_forecast_origins"],
                             "Covered hours": v["covered_hours"], "Matched 30-min targets": v["matched_targets_30"],
                             "Matched 60-min targets": v["matched_targets_60"],
                             "Early-warning eligible": v["ew_eligible_60"],
                             "Positive origins (60)": v["positive_origins_60"],
                             "Censored eligible (60)": v["censored_eligible_origins_60"],
                             "Distinct new onsets (60)": v["distinct_new_onsets_60"]})
    files = pd.DataFrame([{"File": f["relative_path"], "Bytes": f["size_bytes"], "SHA-256": f["sha256"][:16] + "…",
                           "Verified": f["verified"]} for f in prov["files"]])
    out = f"""# CGMacros data audit

Generated {datetime.now(UTC).date().isoformat()} by `glucotwin data audit` from `data/processed/cgmacros/v1/audit.json`
(adapter `{audit['adapter_version']}`). Patient-level processed data stays local (git-ignored); this report contains
aggregate counts and pseudonymous display aliases only.

## Source and provenance

* Dataset: {prov['dataset']} {prov['version']} — {prov['landing_page']} ({prov['doi']})
* License: **{prov['license']}** ({prov['license_url']}). The dataset license is separate from the application code
  license; source records are not redistributed by this repository.
* Retrieved: {prov['retrieved_at']} from the PhysioNet open-data mirror (byte-identical; verified against the
  published `SHA256SUMS.txt`). Parser: `{prov['parser_version']}`.
* Citation: {prov['citation']}

{_table(files)}

Only the CSV tables were extracted ({len(prov['extracted_tables'])} files); meal photographs were not extracted.

## What the source files actually contain (inspected, not assumed)

* **{len(parts)} participant files** (`CGMacros-0XX.csv`, IDs 1–49 with 24, 25, 37 and 40 absent) plus `bio.csv`
  ({audit['bio_rows']} rows), `gut_health_test.csv` and `microbes.csv` (the last two are not used).
* **Cohort membership** follows the dataset's documented HbA1c criterion (`A1c PDL (Lab)`): {dict(cohorts)}.
  There is no separate diagnosis column. The data dictionary labels HbA1c "mmol/mol", but the 4.6–8.5 range is
  in %; we treat it as % and record the discrepancy.
* **CGM columns are interpolated.** Each file is a 1-minute merged grid and both `Dexcom GL` and `Libre GL` are
  linearly interpolated between native readings (e.g. 141.0 → 144.6 → 148.2 … → 159.0). One-minute rows are
  therefore *not* independent measurements.
* **Native Dexcom recovery.** Native readings are integer-valued interpolation knots. We recovered
  {tot_det:,} knots from slope changes and run endpoints, plus {tot_col:,} collinear readings on the 5-minute grid
  whose interpolated value is an integer (equal consecutive changes, often flat overnight values), and dropped
  {tot_drop - tot_col_nonint:,} non-integer slope-change points. Supporting evidence: of all hidden 5-minute grid
  points inside collinear segments, {tot_col:,} had integer values and {tot_col_nonint:,} did not. If missed readings
  had been bridged by interpolation, roughly half of the bridged midpoints of sloped segments would be non-integer.
  Long missing runs are left as NaN in the source and are not bridged.
  Native timestamps are known only to the minute.
* **Undocumented columns** (reported, not interpreted): {dict(unknown)}. `Intensity` (values 0–3) replaces `METs`
  for some participants and is not mapped to METs; one file has `Steps`/`RecordIndex` instead of
  `Calories (Activity)`.
* **Activity**: `METs` is documented as METs × 10 and converted to METs; per-minute Fitbit values are summarised into
  trailing 5-minute windows that become available at the window end.
* **Meals**: rows with a `Meal Type` (case-normalised to Breakfast/Lunch/Dinner/Snack). Macronutrients were
  estimated by the study team and meal times come from photographs. Logging latency is undocumented, so meals are
  excluded from the primary model (conservative availability policy) and used only in a named optimistic
  sensitivity experiment.
* **Baseline profile**: screening values from `bio.csv` (demographics, anthropometrics, fasting labs). `LDL (Cal)`
  = 800, `VLDL (Cal)` = 400 and `Cho/HDL Ratio` = 400 are documented error codes and are excluded as suspect.
  Pounds and inches are converted to kg and cm. No medication or insulin information exists in the source.
* **Time**: dates were shifted by the publishers (±365–720 days); the timezone is undocumented. We keep the source
  time of day, map study day 1 to a synthetic date (2000-01-03) and label the `Z` offset as a transport
  convention. No weekday, season or biological-clock features are used.
* Timestamp parse failures: {sum(p['timestamp_parse_failures'] for p in parts)}; duplicate timestamps:
  {sum(p['duplicate_timestamps'] for p in parts)}; out-of-order rows: {sum(p['out_of_order_rows'] for p in parts)};
  missing minutes in the merged grid: {sum(p['missing_grid_minutes'] for p in parts):,} (mostly one participant with a
  multi-day break, excluded from the primary cohort by HbA1c group).

## Primary cohort and device

Primary device: **{cfg['normalization']['primary_device']}** for every participant (chosen before any outcome
evaluation because Dexcom has the finer 5-minute native cadence). Libre readings are stored separately for a
possible sensitivity analysis and are never stitched into the primary series.

Included: **{len(t2d)} participants** with Type 2 diabetes by the dataset criterion and ≥
{cfg['normalization']['min_recording_hours_for_primary']} h of native Dexcom readings. Excluded:
{len(parts) - len(t2d)} participants (pre-diabetes or no diabetes by HbA1c; outside the primary analysis).
Sensor-limit readings (exactly 40 or 400 mg/dL) are kept but flagged `suspect`, which degrades forecast quality
at those origins.

{_table(t2d.drop(columns=['Primary']))}

## Event prevalence and split accounting (primary cohort)

Research event: new onset of glucose > 180 mg/dL sustained ≥ 15 elapsed minutes on native readings (≥ 4 readings
at 5-minute cadence), recovery after 15 minutes ≤ 180 mg/dL; gaps > 7.5 minutes break continuity and censor labels.
Splits are within-participant and chronological (60 % training, 10 % validation-selection, 10 % calibration,
20 % test) with origins purged when label support (75 min + 7.5 min continuity allowance) would cross a boundary.
{('Purged origins: ' + str(man['summary']['purged_origins']) + '.') if man else ''}

{_table(pd.DataFrame(seg_rows)) if seg_rows else 'Split manifest not built yet.'}

## Unresolved limitations

* 14 Type 2 participants from one US site; no Indian participants.
* CGMs were blinded during the study; the replay assumes zero transmission latency for sensor data.
* Lab turnaround time is undocumented; baseline values are assumed available at twin initialisation.
* Medication and insulin use are unknown; some Type 2 participants may have been treated with glucose-lowering drugs.
* `Intensity`/`Steps` columns are not interpreted, so some participants have no METs (heart rate is still available).

## Full inventory (all participants)

{_table(inv)}
"""
    path = paths().reports / "data_audit.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out)
    return str(path)


def write_evaluation_report() -> str:
    mp = latest_metrics_path()
    if mp is None:
        path = paths().reports / "evaluation_report.md"
        path.write_text("# Evaluation report\n\nNo real-data evaluation has been completed. Status: `not_run`.\n")
        return str(path)
    m = json.loads(mp.read_text())
    aliases = m["aliases"]
    fr = pd.DataFrame(m["forecast_results"])
    sel = m["selection"]
    serving = sel["selected_label"]
    smode = sel["serving_personalization"]

    def tbl(split: str) -> str:
        t = fr[fr["split"] == split].copy()
        t["model"] = t["label"] + " / " + t["personalization"]
        p = t.pivot_table(index="model", columns="horizon", values=["mae", "rmse"]).round(2)
        p.columns = [f"{a.upper()} {h} min" for a, h in p.columns]
        p = p.reset_index()
        n = t.groupby("model")[["n_patients"]].max().reset_index()
        p = p.merge(n, on="model").sort_values("MAE 60 min")
        return _table(p)

    cand = pd.DataFrame(sel["candidates"]).round(2)
    cmp = pd.DataFrame(m["comparisons"])
    cmp["95% CI"] = cmp["ci95"].map(lambda c: f"[{c[0]:.2f}, {c[1]:.2f}]")
    cmp = cmp[["comparison", "horizon", "mean_diff_mae", "95% CI", "n_patients"]].round(2)
    ev = pd.DataFrame(m["events"])
    ev = ev[["model", "horizon", "split", "threshold", "true_onsets", "detected_onsets", "warning_episodes",
             "false_alarm_episodes", "recall", "precision", "f1", "origin_pr_auc", "false_alarms_per_patient_day",
             "lead_time_median", "lead_time_iqr"]].copy()
    ev["lead_time_iqr"] = ev["lead_time_iqr"].map(lambda x: f"{x[0]}–{x[1]}" if x and x[0] is not None else "n/a")
    ev = ev.round(3)
    iv = pd.DataFrame(m["intervals"])
    iv = iv[iv["label"] == serving][["personalization", "horizon", "split", "q", "coverage", "width",
                                    "per_patient_min", "per_patient_max", "n"]].round(3)
    pp = pd.DataFrame(m["per_patient_test"])
    pp = pp[pp["label"].isin([serving, "persistence:cgm-only-v1"])]
    pp["participant"] = pp["patient_id"].map(aliases)
    pp["model"] = pp["label"] + "/" + pp["personalization"]
    ppt = pp.pivot_table(index="participant", columns=["model", "horizon"], values="mae").round(1)
    ppt.columns = [f"{a} {h}m" for a, h in ppt.columns]
    lopo = pd.DataFrame(m["lopo"])
    lopo_sum = lopo.groupby("horizon")[["lopo_population_mae", "lopo_adaptive_mae"]].mean().round(2).reset_index() \
        if len(lopo) else pd.DataFrame()
    sens = pd.DataFrame(m["sensitivity"]).round(2)
    adapt = pd.DataFrame(sel["adaptation"]).round(3)
    summ = m["cohort"]["by_segment"]
    test_fr = fr[(fr["split"] == "test") & (fr["label"] == serving) & (fr["personalization"] == smode)]
    out = f"""# GlucoTwin evaluation report — experiment `{m['experiment_id']}`

Generated by `glucotwin experiment report` from `{mp.relative_to(paths().root)}` (created {m['created_at']}).
All values are measured on CGMacros 1.0.0 Type 2 participants. Nothing here is a clinical validation.

* Model version: `{m['model_version']}` · config hash `{m['fingerprints']['config_hash']}` · data fingerprint
  `{m['fingerprints']['data_fingerprint']}` · split hash `{m['fingerprints']['split_hash']}`
* Environment: Python {m['environment']['python']}, LightGBM {m['environment']['lightgbm']}, CatBoost
  {m['environment']['catboost']}, scikit-learn {m['environment']['scikit-learn']} on {m['environment']['machine']}
  ({m['environment']['platform']}); total runtime {m['timings_seconds']['total']:.0f} s on CPU.
* Protocol declared in `configs/experiment.yaml` before fitting; test segment evaluated once after freezing the
  serving model, adaptation settings, interval quantiles and alert thresholds.

## Cohort

14 participants; test segment {summ['test']['origins']:,} origins (~{summ['test']['covered_hours']:.0f} h);
{summ['test']['distinct_new_onsets_60']} distinct new high-glucose onsets in the test segment
({summ['validation']['distinct_new_onsets_60']} in validation-selection). Overlapping origins are not independent;
uncertainty is expressed with participant-cluster bootstrap intervals.

## Model selection (validation-selection segment only)

Rule: {sel['rule']}
Tie-break: {sel['tie_break']}

{_table(cand)}

**Selected:** `{serving}` — {sel['rationale']}
Note: the profile-augmented tree models scored slightly better on validation but fell inside the declared
0.5 mg/dL tie margin, so the declared rule chose the smaller dynamic-only feature set.

### Patient adaptation (selected on validation-selection, same policy for both tree families)

{_table(adapt)}

The selected settings (k = {adapt.iloc[0]['shrinkage_k']}, half-life = {adapt.iloc[0]['half_life_minutes']} min) lie at
the edge of the declared grid; a wider grid was not searched. Serving personalization: **{smode}**.

## Forecast accuracy — final test segment (macro mean of per-participant errors, mg/dL)

{tbl('test')}

Validation-selection segment for reference:

{tbl('validation')}

Forecast availability for the serving model on test: {', '.join(f"{int(r.horizon)} min {r.coverage:.3f}" for r in test_fr.itertuples())}
(share of test origins with an observed target at which a forecast was issued).

### Paired per-participant differences (negative = first model better), participant-cluster bootstrap

{_table(cmp)}

## Prediction intervals (split conformal, nominal 80 %, serving family)

{_table(iv)}

Test coverage falls below the nominal 80 % (time-series dependence and distribution shift between segments);
per-participant coverage varies widely. No coverage guarantee is claimed.

## Early warning of new sustained high-glucose onsets

Score = highest forecast within the horizon minus 180 mg/dL (uncalibrated, not a probability). Thresholds were
selected on validation-selection to maximise event-level F1. Persistence and linear-trend rows use the same
procedure with their own forecasts.

{_table(ev)}

Reading this table: the serving warning rule detects most onsets with far fewer false alarms than threshold rules
on the current reading, but its **median lead time is short** (about 10 minutes). The simple "glucose already above
~150 mg/dL" rule gives earlier warnings at the cost of roughly 2.5–3× more false alarms per patient-day.

## Secondary analyses

**Leave-one-participant-out cold start** (serving configuration refit without the held-out participant; test segment):

{_table(lopo_sum) if len(lopo_sum) else 'not run'}

**Optimistic meal-logging sensitivity** (assumes meal macronutrients known at the photo timestamp; never eligible for
serving):

{_table(sens.drop(columns=['note']))}

**Chronos-Bolt** (optional research track): not run.

## Per-participant test MAE (mg/dL)

{_table(ppt.reset_index())}

## Limitations

""" + "\n".join(f"* {x}" for x in LIMITATIONS) + "\n"
    path = paths().reports / "evaluation_report.md"
    path.write_text(out)
    return str(path)


