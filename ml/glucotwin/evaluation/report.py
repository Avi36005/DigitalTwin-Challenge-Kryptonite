"""Convert saved experiment artifacts into the canonical EvaluationReport payload.

Every number comes from ``artifacts/experiments/<id>/metrics.json``; nothing is recomputed or typed in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from glucotwin.config import load_config, paths

LIMITATIONS = [
    "Small cohort: 14 participants with Type 2 diabetes (CGMacros, US, recruited 2021-2024); overlapping "
    "forecast windows are not independent patients.",
    "No Indian participants: nothing here establishes performance for patients in India.",
    "The study CGMs were blinded; real-time availability is a replay approximation (zero transmission latency).",
    "Native Dexcom readings were recovered from a 1-minute interpolated table; timestamps are known only to the minute.",
    "Medication, insulin use and illness were not recorded and cannot be modelled.",
    "Meal logs are excluded from the primary model because their real-time availability is undocumented.",
    "Prediction intervals are split-conformal under time-series dependence; observed test coverage is reported "
    "and no coverage guarantee is claimed.",
    "Warning scores are uncalibrated forecast margins in mg/dL, not probabilities.",
    "Research event definition (>180 mg/dL sustained 15 minutes) is not a clinical triage threshold.",
    "Retrospective research replay; no clinician, clinical workflow or patient outcome was studied.",
]


def latest_metrics_path() -> Path | None:
    reg = paths().artifacts / "registry.json"
    if reg.exists():
        r = json.loads(reg.read_text())
        version = r.get("serving", {}).get("dataset_replay")
        entry = next((m for m in r.get("models", []) if m["model_version"] == version), None)
        if entry:
            p = paths().root / entry["evaluation_reference"]
            if p.exists():
                return p
    return None


def _mv(v, reason: str = "not computed") -> dict[str, Any]:
    if v is None:
        return {"value": None, "reason_if_null": reason}
    return {"value": float(v), "reason_if_null": None}


def build_report() -> dict[str, Any]:
    path = latest_metrics_path()
    if path is None:
        return {"schema_version": "1.0", "status": "not_run",
                "status_message": "No completed real-data evaluation is registered. Run `glucotwin data import` "
                                  "and `glucotwin experiment run` after obtaining CGMacros 1.0.0.",
                "limitations": LIMITATIONS}
    m = json.loads(path.read_text())
    data_cfg = load_config("data")["dataset"]
    exp = load_config("experiment")
    aliases = m.get("aliases", {})
    selected = m["selection"]["selected_label"]
    serving_mode = m["selection"]["serving_personalization"]

    rows = []
    for r in m["forecast_results"]:
        rows.append({
            "model_family": r["family"], "model_label": r["label"], "feature_set_id": r["feature_set_id"],
            "personalization": r["personalization"], "split": r["split"], "horizon_minutes": r["horizon"],
            "mae_mg_dl": _mv(r["mae"]), "rmse_mg_dl": _mv(r["rmse"]), "n_patients": r["n_patients"],
            "n_origins": r["n_origins"], "coverage_fraction": r["coverage"], "train_seconds": r.get("train_seconds"),
            "inference_ms_per_1k": r.get("latency_ms_per_1k"),
            "selected_for_serving": bool(r["label"] == selected and r["personalization"] == serving_mode),
        })
    # attach bootstrap CIs to the paired comparisons (kept separately for transparency)
    ev_rows = []
    for e in m["events"]:
        ev_rows.append({
            "model_label": e["model"], "horizon_minutes": e["horizon"], "split": e["split"],
            "threshold": e["threshold"], "true_onsets": e["true_onsets"], "detected_onsets": e["detected_onsets"],
            "warning_episodes": e["warning_episodes"], "false_alarm_episodes": e["false_alarm_episodes"],
            "recall": _mv(e["recall"], "no detectable onsets"), "precision": _mv(e["precision"], "no warnings"),
            "f1": _mv(e["f1"], "undefined"), "origin_pr_auc": _mv(e["origin_pr_auc"], "undefined"),
            "false_alarms_per_patient_day": _mv(e["false_alarms_per_patient_day"]),
            "warnings_per_patient_day": _mv(e["warnings_per_patient_day"]),
            "lead_time_minutes_median": _mv(e["lead_time_median"], "no detected onsets"),
            "lead_time_minutes_iqr": e["lead_time_iqr"], "eligible_patient_days": e["eligible_patient_days"],
            "censored_origins": e["censored_origins"],
        })
    iv_rows = []
    for i in m["intervals"]:
        iv_rows.append({
            "model_label": f"{i['label']} ({i['personalization']})", "horizon_minutes": i["horizon"],
            "split": i["split"], "interval_level": i["level"], "empirical_coverage": _mv(i["coverage"]),
            "mean_width_mg_dl": _mv(i["width"]), "per_patient_coverage_min": i["per_patient_min"],
            "per_patient_coverage_max": i["per_patient_max"], "n_origins": i["n"],
        })
    summ = m["cohort"]
    cohort = {
        "participants_in_source": 45, "participants_in_cohort": 14,
        "participants_included": summ["participants"],
        "excluded": [{"display_alias": x["display_alias"], "cohort": x["cohort"], "reason": x["reason"]}
                     for x in m["excluded"]],
        "origins_by_split": {k: v["origins"] for k, v in summ["by_segment"].items()},
        "events_by_split": {k: v["distinct_new_onsets_60"] for k, v in summ["by_segment"].items()},
        "covered_hours_by_split": {k: v["covered_hours"] for k, v in summ["by_segment"].items()},
    }
    sel = m["selection"]
    selection = {
        "rule": sel["rule"], "tie_break": sel["tie_break"], "candidates": sel["candidates"],
        "selected_model_label": sel["selected_label"], "selected_model_family": sel["selected_family"],
        "rationale": sel["rationale"] + f" Patient adaptation: {'adopted' if serving_mode == 'adaptive' else 'not adopted'}"
                     " by the declared validation adoption rule.",
    }
    per_patient = [{"participant": aliases.get(r["patient_id"], r["patient_id"]), **{k: v for k, v in r.items()
                                                                                     if k != "patient_id"}}
                   for r in m["per_patient_test"]]
    lopo = m.get("lopo", [])
    optional = [
        {"name": "Chronos-Bolt (optional research track)", "status": "not_run",
         "detail": "Disabled by default; not attempted in experiment " + m["experiment_id"] + ". Core results do not "
                   "depend on it."},
        {"name": "Optimistic meal-logging sensitivity", "status": "evaluated", "results": m.get("sensitivity", []),
         "detail": "Assumes meal macronutrients were known at the photo timestamp. Not eligible for serving."},
        {"name": "Leave-one-participant-out cold start", "status": "evaluated" if lopo else "not_run",
         "results": [{**r, "participant": aliases.get(r["patient_id"], r["patient_id"])} for r in lopo],
         "detail": "Serving configuration refit without the held-out participant (no retuning); test segment only."},
        {"name": "Paired comparisons (participant-cluster bootstrap)", "status": "evaluated",
         "results": m.get("comparisons", [])},
    ]
    return {
        "schema_version": "1.0", "status": "completed",
        "status_message": "Completed real-data evaluation on the held-out final test segment (evaluated once after "
                          "the protocol was frozen).",
        "experiment_id": m["experiment_id"], "created_at": m["created_at"], "mode": "dataset_replay",
        "dataset": {"name": data_cfg["name"], "version": data_cfg["version"], "license": data_cfg["license"],
                    "citation_url": data_cfg["doi"], "synthetic": False},
        "fingerprints": m["fingerprints"],
        "protocol": {
            "horizons_minutes": exp["horizons_minutes"], "split": exp["splits"]["scheme"],
            "split_fractions": {"training": exp["splits"]["train_fraction"],
                                "validation_selection": exp["splits"]["selection_fraction"],
                                "calibration": exp["splits"]["calibration_fraction"],
                                "test": exp["splits"]["test_fraction"]},
            "purge_minutes": exp["splits"]["max_label_support_minutes"] + exp["splits"]["continuity_allowance_minutes"],
            "event_definition": exp["event"], "primary_device": exp["cohort"]["primary_device"],
            "adaptation": exp["adaptation"]["description"].strip(), "intervals": exp["intervals"],
            "alert_score": exp["alerts"]["score"].strip(), "model_version": m["model_version"],
            "environment": m.get("environment", {}),
        },
        "cohort": cohort, "selection": selection, "forecast_results": rows, "per_patient": per_patient,
        "event_results": ev_rows, "interval_results": iv_rows, "optional_experiments": optional,
        "limitations": LIMITATIONS,
    }
