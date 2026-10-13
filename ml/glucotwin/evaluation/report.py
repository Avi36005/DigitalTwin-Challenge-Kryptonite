"""Convert saved experiment artifacts into the canonical EvaluationReport payload.

Every number comes from ``artifacts/experiments/<id>/metrics.json``; nothing is recomputed or typed in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from glucotwin.config import load_config, load_experiment_config, paths

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


NESTED_EVIDENCE_ID = "gt-nested-2026-10-12-v1"  # the people-held-out experiment that tested the profile inputs


def _serving_event(m: dict[str, Any], split: str = "test") -> dict[str, Any] | None:
    sel = m["selection"]
    name = f"{sel['selected_label']} ({'adaptive' if sel['serving_personalization'] == 'adaptive' else 'population'})"
    H = int(m.get("serving_alert_horizon", 60))
    return next((e for e in m["events"] if e["model"] == name and e["split"] == split and e["horizon"] == H), None)


def profile_benefit_on_new_people() -> list[dict[str, Any]]:
    p = paths().artifacts / "research" / NESTED_EVIDENCE_ID / "report.json"
    rep = json.loads(p.read_text()) if p.exists() else {}
    if rep.get("status") != "completed":
        return []
    cmp = rep.get("tracks", {}).get("multimodal_5min", {}).get("comparisons", [])
    return sorted((c for c in cmp if c["comparison"].startswith("Profile inputs")), key=lambda c: c["horizon"])


def selection_disclosures(m: dict[str, Any]) -> list[str]:
    """Statements that must accompany a serving model chosen under an eligibility constraint (empty otherwise).
    Every number is read from saved artifacts."""
    eligible = m["selection"].get("eligible_feature_sets")
    if not eligible:
        return []
    exp = load_experiment_config(m["experiment_id"])
    inspected = [x for x in (m.get("corrects_experiment_id"), exp.get("derived_from")) if x]
    out = [f"Eligibility was restricted to models that read both the baseline profile and the dynamic streams "
           f"({', '.join(eligible)}) by protocol {m['experiment_id']}, declared on {exp.get('declared_on')} after the "
           f"test segment had already been inspected{' in ' + ' and '.join(inspected) if inspected else ''}. The "
           "validation score, tie margin and tie-break are unchanged."]
    rows = profile_benefit_on_new_people()
    if rows:
        parts = "; ".join(f"{r['mean_diff']:+.2f} [{r['ci95'][0]:+.2f}, {r['ci95'][1]:+.2f}] mg/dL at {r['horizon']} min"
                          for r in rows)
        verdict = ("Every interval includes zero: no reliable benefit was shown."
                   if all(r["ci95"][0] <= 0 <= r["ci95"][1] for r in rows) else "See the nested report for details.")
        out.append(f"On people held out entirely ({NESTED_EVIDENCE_ID}), adding the profile to LightGBM changed mean "
                   f"absolute error by {parts} (negative = better; participant-cluster bootstrap). {verdict}")
    else:
        out.append("Whether the profile improves forecasts for people outside the training cohort has not been "
                   "assessed on this machine.")
    n = m["cohort"].get("participants", "the same")
    out.append(f"Profile values are constant within a person and the model is trained and tested on the same {n} "
               "people, so the profile can act as a participant identifier. A better score here does not show that "
               "the profile helps unseen patients.")
    out.append("This model was selected to implement the required fusion of static and dynamic data, not because it "
               "was more accurate. We have not established that profile features improve forecasting for unseen "
               "patients.")
    base = exp.get("derived_from")
    own = _serving_event(m)
    bp = paths().artifacts / "experiments" / str(base) / "metrics.json"
    theirs = _serving_event(json.loads(bp.read_text())) if base and bp.exists() else None
    H = int(m.get("serving_alert_horizon", 60))
    key = f"{m['selection']['selected_label']} ({'adaptive' if m['selection']['serving_personalization'] == 'adaptive' else 'population'})|{H}"
    log = m.get("alert_threshold_selection", {}).get(key, [])
    if own and theirs and log:
        best = max((r["f1"] or 0) for r in log)
        near = [r["threshold"] for r in log if (r["f1"] or 0) >= best - 0.03]
        out.append(f"The warning margin ({own['threshold']:+.0f} mg/dL; {base}: {theirs['threshold']:+.0f}) was "
                   f"re-derived by the same event-level F1 rule, and margins {', '.join(f'{t:+.0f}' for t in near)} "
                   f"were within 0.03 F1 of the best on validation. Because the model and its margin changed "
                   f"together, the change in false alarms per observed day "
                   f"({theirs['false_alarms_per_observed_patient_day']:.2f} to "
                   f"{own['false_alarms_per_observed_patient_day']:.2f}) and in detected onsets "
                   f"({theirs['detected_onsets']} to {own['detected_onsets']} of {own['true_onsets']}) is not evidence "
                   "that the profile improves warnings.")
    return out


def _mv(v, reason: str = "not computed") -> dict[str, Any]:
    if v is None:
        return {"value": None, "reason_if_null": reason}
    return {"value": float(v), "reason_if_null": None}


def metrics_path(experiment_id: str | None) -> Path | None:
    """Saved metrics of a chronological-split experiment (None = the one behind the serving model)."""
    if experiment_id is None:
        return latest_metrics_path()
    p = paths().artifacts / "experiments" / experiment_id / "metrics.json"
    return p if p.exists() else None


def build_report(experiment_id: str | None = None) -> dict[str, Any]:
    path = metrics_path(experiment_id)
    if path is None:
        return {"schema_version": "1.0", "status": "not_run",
                "status_message": "No completed real-data evaluation is registered. Run `glucotwin data import` "
                                  "and `glucotwin experiment run` after obtaining CGMacros 1.0.0.",
                "limitations": LIMITATIONS}
    m = json.loads(path.read_text())
    data_cfg = load_config("data")["dataset"]
    exp = load_experiment_config(m["experiment_id"])
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
            # present only for experiments run after the Prompt 05 corrections
            "observed_patient_days": e.get("observed_patient_days"),
            "false_alarms_per_observed_patient_day": (_mv(e["false_alarms_per_observed_patient_day"])
                                                      if "false_alarms_per_observed_patient_day" in e else None),
            "warnings_per_eligible_patient_day": (_mv(e["warnings_per_eligible_patient_day"])
                                                  if "warnings_per_eligible_patient_day" in e else None),
            "qualified_lead_minutes_median": (_mv(e["qualified_lead_median"], "no qualifying firing")
                                              if "qualified_lead_median" in e else None),
            "qualified_lead_minutes_iqr": e.get("qualified_lead_iqr"),
            "qualified_lead_n": e.get("qualified_lead_n"),
            "episode_start_lead_max_minutes": e.get("episode_start_lead_max"),
            "episode_start_lead_over_horizon": e.get("episode_start_lead_over_horizon"),
            "matched_without_qualified_firing": e.get("matched_without_qualified_firing"),
            "time_base": e.get("time_base"),
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
    corrects = m.get("corrects_experiment_id")
    base = exp.get("derived_from")
    status_message = (
        "Completed real-data evaluation on the held-out final test segment (evaluated once after the protocol was frozen)."
        if not corrects else
        f"Retrospective evaluation: the protocol of {base} re-run with serving eligibility restricted to models that "
        f"read the baseline profile and the dynamic streams. The test segment had already been inspected in {corrects} "
        f"and {base}, so these are not untouched test results."
        if base and m["selection"].get("eligible_feature_sets") else
        f"Corrected retrospective evaluation: the declared protocol of {corrects} re-run after code corrections. "
        f"The test segment had already been inspected in {corrects}, so these are not untouched test results.")
    limitations = LIMITATIONS + ([
        f"This experiment corrects {corrects} (feature and warning-accounting defects; see reports/repair_report.md). "
        "Its test segment is the same one inspected before; the original results are preserved."] if corrects else [])
    return {
        "schema_version": "1.0", "status": "completed",
        "status_message": status_message,
        "experiment_id": m["experiment_id"], "created_at": m["created_at"], "mode": "dataset_replay",
        "corrects_experiment_id": corrects, "correction_note": m.get("correction_note"),
        "selection_disclosures": selection_disclosures(m),
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
        "limitations": limitations,
    }
