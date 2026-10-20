"""Evidence catalogue for the API: which experiments exist, the serving model on its own, research reports and the
measured dataset inventory. Every value is read from saved artifacts or reports; nothing is typed in here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from glucotwin.config import load_config, paths
from glucotwin.evaluation.report import latest_metrics_path

RESEARCH_EXPERIMENTS = ("gt-nested-2026-10-12-v1",)
SHORT_NAMES = {"cgmacros": "CGMacros", "shanghai_t2dm": "ShanghaiT2DM", "ai_readi_v3": "AI-READI", "glucose_ml": "Glucose-ML"}
INPUTS = {"cgmacros": ("Fitbit 5-min summaries", "baseline labs, assumed at start"),
          "shanghai_t2dm": ("none", "labs undated: not used")}
TITLES = {
    "gt-primary-2026-10-11-v1": ("superseded_original", "Original primary experiment (v1)",
                                 "Within-participant chronological split; superseded by the corrected v2 re-run "
                                 "(activity-window and warning-accounting defects)."),
    "gt-primary-2026-10-11-v2": ("superseded_serving", "Corrected retrospective experiment (v2)",
                                 "Its model reads the dynamic streams only (no baseline profile); it served replays until "
                                 "13 Oct 2026 and stays registered for rollback. Its test segment had already been "
                                 "inspected in v1, so it is a corrected retrospective result."),
    "gt-primary-2026-10-13-fusion": ("serving_retrospective", "Fusion-constrained experiment (profile + wearable)",
                                     "v2's protocol with one change: the selected model must read both the baseline "
                                     "profile and the dynamic streams. Declared after the test segment had been "
                                     "inspected, so it is a retrospective result."),
    "gt-nested-2026-10-12-v1": ("nested_research", "Nested participant benchmark + external cohort",
                                "New people only: 5 outer participant folds on CGMacros (internal validation of an "
                                "already-inspected cohort) and a reserved ShanghaiT2DM external assessment."),
}


def serving_experiment_id() -> str | None:
    p = latest_metrics_path()
    return json.loads(p.read_text())["experiment_id"] if p else None


def list_experiments() -> dict[str, Any]:
    items = []
    serving_id = serving_experiment_id()
    for d in sorted((paths().artifacts / "experiments").glob("*/metrics.json")):
        m = json.loads(d.read_text())
        eid = m["experiment_id"]
        regime, title, desc = TITLES.get(eid, ("superseded_original", eid, "Chronological-split experiment."))
        if eid == serving_id:
            regime = "serving_retrospective"
        elif regime == "serving_retrospective":
            regime = "superseded_serving"
        items.append({"experiment_id": eid, "regime": regime, "title": title, "description": desc,
                      "status": "completed", "created_at": m.get("created_at"), "is_serving_evidence": eid == serving_id})
    for eid in RESEARCH_EXPERIMENTS:
        rep = research_report_raw(eid)
        root = paths().artifacts / "research" / eid
        regime, title, desc = TITLES[eid]
        status = ("completed" if rep and rep.get("status") == "completed" else
                  "development_only" if (root / "splits.json").exists() else "not_run")
        items.append({"experiment_id": eid, "regime": regime, "title": title, "description": desc, "status": status,
                      "created_at": rep.get("created_at") if rep else None, "is_serving_evidence": False})
    order = {"serving_retrospective": 0, "nested_research": 1, "superseded_serving": 2, "superseded_original": 3}
    items.sort(key=lambda x: (order[x["regime"]], x["experiment_id"]))
    return {"schema_version": "1.0", "items": items, "serving_experiment_id": serving_id}


def research_report_raw(experiment_id: str) -> dict[str, Any] | None:
    p = paths().artifacts / "research" / experiment_id / "report.json"
    return json.loads(p.read_text()) if p.exists() else None


def _strip(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if not str(k).startswith("_") and k != "per_participant_mae"}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def research_report(experiment_id: str) -> dict[str, Any] | None:
    if experiment_id not in RESEARCH_EXPERIMENTS:
        return None
    rep = research_report_raw(experiment_id)
    if rep is None:
        return {"schema_version": "1.0", "experiment_id": experiment_id, "status": "not_run",
                "status_message": "The research experiment has not produced an assessed report on this machine. Run "
                                  "`glucotwin research develop`, `assess`, `external` and `report`."}
    rep = _strip(rep)
    if rep.get("status") != "completed":
        return {"schema_version": "1.0", "experiment_id": experiment_id, "status": "not_run",
                "status_message": rep.get("status_message", "Not run.")}
    # keep only the contract's per-track warning lists (policies / curves)
    for t in rep.get("tracks", {}).values():
        if t.get("warnings"):
            t["warnings"] = {"policies": t["warnings"].get("policies", []), "curves": t["warnings"].get("curves", [])}
    return rep


def profile_inputs(feature_set_id: str) -> list[str] | None:
    """The profile values a feature set reads, named as in the session profile; None if the feature set is unknown."""
    from glucotwin.features import FEATURE_SETS, PROFILE_FEATURES

    spec = FEATURE_SETS.get(feature_set_id)
    if spec is None:
        return None
    return [name for _, name in PROFILE_FEATURES] if spec.use_profile else []


def serving_summaries(serving: dict[str, Any], errors: dict[str, str]) -> dict[str, Any]:
    items = []
    sid = serving_experiment_id()
    for mode in ("dataset_replay", "synthetic_demo"):
        s = serving.get(mode)
        if s is None:
            items.append({"schema_version": "1.0", "mode": mode, "status": "unavailable",
                          "detail": errors.get(mode, "No verified model artifact for this mode.")})
            continue
        cfg = s.config
        exp = cfg.get("experiment_id")
        items.append({
            "schema_version": "1.0", "mode": mode, "status": "ready",
            "detail": "Synthetic demonstration model (fictional data)." if s.synthetic_fitted else
                      "Model used by recorded-data replay sessions.",
            "model_version": s.model_version, "model_family": s.family, "feature_set_id": s.bundle.feature_set_id,
            "experiment_id": exp,
            "evaluation_regime": ("serving_retrospective" if exp and exp == sid else None),
            "adaptation": cfg.get("adaptation"), "interval_level": s.interval_level,
            "interval_quantiles_mg_dl": (cfg.get("intervals") or {}).get("quantiles_mg_dl"),
            "warning_threshold_margin_mg_dl": s.alert.get("threshold_margin_mg_dl"),
            "warning_horizon_minutes": s.alert.get("horizon_minutes"),
            "requires_complete_profile": s.profile_gate,
            "profile_inputs": profile_inputs(s.bundle.feature_set_id),
        })
    return {"schema_version": "1.0", "items": items}


def dataset_inventory() -> dict[str, Any]:
    p = paths().reports / "dataset_inventory.json"
    if not p.exists():
        return {"schema_version": "1.0", "status": "not_generated"}
    inv = json.loads(p.read_text())
    srcs = load_config("sources")["sources"]
    out = []
    for d in inv["datasets"]:
        pub = d.get("publisher", {})
        did = d["dataset_id"]
        cad = sorted({float(x["native_cadence_minutes"]) for x in srcs[did].get("devices", [])})
        readings = hours = None
        wearable, profile = INPUTS.get(did, (None, None))
        detail = d.get("detail")
        if did == "cgmacros":
            m = d.get("all_participants_dexcom") or {}
            readings, hours = m.get("native_readings"), m.get("observed_hours")   # primary device only: one definition
            libre = (d.get("all_participants_libre") or {}).get("native_readings")
            if libre:
                detail = f"Also imported: {libre:,} FreeStyle Libre Pro readings (second device, not used by any model)."
        elif did == "shanghai_t2dm":
            m = d.get("all_participants") or {}
            readings, hours = m.get("native_readings"), m.get("observed_hours")
        site = (pub.get("country_site") or "").split(" (")[0].split(";")[0] or None
        out.append({
            "dataset_id": did, "name": SHORT_NAMES.get(did, pub.get("name", did)),
            "release": (pub.get("release") or "").split(" (")[0] or None,
            "access_status": d["access_status"], "role": pub.get("role"),
            "license": srcs[did].get("license_short") or pub.get("license"),
            "country_site": site, "native_cadence_minutes": cad,
            "publisher_participants": pub.get("publisher_participants"),
            "acquired_participants": d.get("acquired_participants"), "parsed_participants": d.get("parsed_participants"),
            "eligible": {k: int(v) for k, v in (d.get("eligible") or {}).items()},
            "native_readings": readings, "observed_hours": hours, "wearable": wearable, "profile": profile,
            "split_counts": d.get("split_counts"), "detail": detail, "user_steps": d.get("user_steps", []),
            "citation_url": pub.get("doi") or pub.get("landing_page"),
        })
    sentence = None
    rep = research_report_raw(RESEARCH_EXPERIMENTS[0])
    imported = sum(x["parsed_participants"] or 0 for x in out)
    if rep and rep.get("status") == "completed":
        internal = rep["tracks"]["multimodal_5min"]["participants"]
        ext = rep.get("external") or {}
        external = ext.get("participants") if ext.get("status") == "completed" else 0
        sentence = (f"{imported} participants imported; {internal} evaluated internally and "
                    + (f"{external} evaluated externally." if external else "none evaluated externally yet."))
    return {"schema_version": "1.0", "status": "available", "generated_at": inv.get("generated_at"),
            "canonical_schema": inv.get("canonical_schema"), "datasets": out, "summary_sentence": sentence,
            "overlap_check": inv.get("overlap_check"), "synthetic": inv.get("synthetic")}


# Research run after the demo model was chosen (20 Oct 2026): (decision, experiment, saved summary, evaluated on)
SUMMARIES = (
    ("D-043", "gt-2h-2026-10-20", "two_hour_summary.json", "people_held_out"),
    ("D-045", "gt-2h-ext-2026-10-20", "two_hour_external_summary.json", "independent_cohort"),
    ("D-044", "gt-2h-clf-2026-10-20", "summary.json", "people_held_out"),
    ("D-046", "gt-warn-range-2026-10-20", "summary.json", "reanalysis_inspected"),
)


def _lower(ci: list[float]) -> str:
    """Verdict for a difference where lower is better: shown only when the whole 95 % interval is below zero."""
    return "shown" if ci[1] < 0 else "not_shown"


# How each verdict was reached. Only D-046 part C declared a claim rule before computing (configs/experiments/
# gt-warn-range-2026-10-20.yaml part_C_profile_prior.claim_rule); every other verdict is this page's display description
# of the saved interval or diagnostic, not a pass bar any protocol declared.
DISPLAY = "display_heuristic"
DECLARED = "declared_rule"
BASIS = {
    "forecast_120": (DISPLAY, "Shown when the whole 95 % participant-bootstrap interval of the difference is below zero."),
    "notice_120": (DISPLAY, "Two hours of notice is described as shown only if the median forecast lead reaches 60 "
                            "minutes; no protocol declared a lead target."),
    "profile_inputs_120": (DISPLAY, "Shown when the whole 95 % interval of with-minus-without profile is below zero."),
    "classifier": (DISPLAY, "Described as a negative result because it warned at more than half of eligible times; "
                            "its report rejects it for warning almost constantly."),
    "ranges_120": (DISPLAY, "Described as shown when pooled coverage moved closer to the 80 % target than the incumbent "
                            "range; D-046 declared pooled calibration as its primary method, not a pass bar."),
    "earlier_warning_120": (DISPLAY, "Shown when the whole 95 % interval of the difference in onsets warned at least "
                                     "30 minutes ahead is above zero; D-046 part A declared no claim rule."),
    "profile_prior_120": (DECLARED, "D-046 part C declared it before computing: the profile is said to help only if the "
                                    "95 % interval of profile prior minus population only is below zero at 120 min."),
}


def _finding(key: str, verdict: str, c: dict[str, Any] | None = None, unit: str | None = None, **values: Any) -> dict:
    basis, note = BASIS[key]
    out = {"key": key, "verdict": verdict, "basis": basis, "basis_note": note, "unit": unit, "values": values}
    if c is not None:
        out.update({"estimate": c.get("mean_diff", c.get("mean_difference")), "ci95": c["ci95"],
                    "better_for": c.get("better_for", c.get("improved")), "n": c.get("n", c.get("participants", c.get("n_participants")))})
    return out


def _two_hour(s: dict[str, Any]) -> tuple[int | None, dict, list[dict]]:
    f, comps = s["forecasts"], s["comparisons"]
    cmp = lambda title: next(c for c in comps if c["comparison"] == title and c["horizon"] == 120)  # noqa: E731
    sel = cmp("Selected (personalised) minus persistence")
    prof = cmp("Profile (EHR-like) inputs: LightGBM dyn-prof-v2 minus dyn-v2")
    w = next(x for x in s["warnings"] if x["pipeline"] == "selected" and x["horizon"] == 120)
    iqr = w.get("qualified_lead_iqr") or [None, None]
    lead = w.get("qualified_lead_median")
    return s.get("participants"), s["assessment_opened"], [
        _finding("forecast_120", _lower(sel["ci95"]), sel, "mg/dL", mae=f["selected|final"]["horizons"]["120"]["mae"],
                 persistence_mae=f["persistence:-|off"]["horizons"]["120"]["mae"]),
        _finding("notice_120", "shown" if lead is not None and lead >= 60 else "not_shown", None, "min",
                 detected=w["detected_onsets"], onsets=w["true_onsets"], false_alarms_per_day=w["false_alarms_per_observed_day"],
                 lead_median=lead, lead_q1=iqr[0], lead_q3=iqr[1]),
        _finding("profile_inputs_120", _lower(prof["ci95"]), prof, "mg/dL")]


def _external(s: dict[str, Any]) -> tuple[int | None, dict, list[dict]]:
    c = s["minus_persistence"]["120"]
    return s.get("participants"), s["opened"], [
        _finding("forecast_120", _lower(c["ci95"]), c, "mg/dL", mae=s["mae"]["120"], persistence_mae=s["persistence_mae"]["120"])]


def _classifier(s: dict[str, Any]) -> tuple[int | None, dict, list[dict]]:
    r = s["results"]["selected"]
    share = r.get("share_of_eligible_time_warning")
    # rejected by its own report: near-constant firing makes episode counts meaningless (D-044)
    return None, s["opened"], [
        _finding("classifier", "negative" if share is not None and share > 0.5 else "not_shown", None, None,
                 detected=r.get("detected_onsets"), onsets=r.get("true_onsets"),
                 false_alarms_per_day=r.get("false_alarms_per_observed_day"), share_time_warning=share,
                 roc_auc=r.get("origin_roc_auc"))]


def _warn_range(s: dict[str, Any]) -> tuple[int | None, dict, list[dict]]:
    r, w, d = s["ranges"], s["warnings"], s["warning_diff_selected_minus_incumbent"]
    b0, b1 = r["B0_calibration"], r["B1_pooled"]
    p, p24 = s["profile_prior"]["all"]["120"], s["profile_prior"]["first_24h"]["120"]
    pooled = b1["120"]["coverage_pooled"]
    closer = abs(pooled - 0.8) < abs(b0["120"]["coverage_pooled"] - 0.8)
    early = {"mean_diff": 100 * d["early_share_diff"], "ci95": [100 * x for x in d["early_share_ci95"]], "n": d["people"]}
    return d.get("people"), s["opened"], [
        _finding("ranges_120", "shown" if closer else "not_shown", None, "%",
                 before=b0["120"]["coverage_pooled"], after=pooled, before_60=b0["60"]["coverage_pooled"],
                 after_60=b1["60"]["coverage_pooled"], width_before=b0["120"]["width_mean"], width_after=b1["120"]["width_mean"]),
        _finding("earlier_warning_120", "shown" if early["ci95"][0] > 0 else "not_shown", early, "points",
                 early_selected=w["selected"]["early"], early_incumbent=w["incumbent"]["early"], onsets=w["incumbent"]["onsets"],
                 lead_median=w["selected"]["lead_median"]),
        _finding("profile_prior_120", _lower(p["c1_minus_population"]["ci95"]), p["c1_minus_population"], "mg/dL",
                 first_24h_estimate=p24["c1_minus_population"]["mean_diff"],
                 first_24h_ci_low=p24["c1_minus_population"]["ci95"][0],
                 first_24h_ci_high=p24["c1_minus_population"]["ci95"][1])]


_READERS = {"D-043": _two_hour, "D-045": _external, "D-044": _classifier, "D-046": _warn_range}


def _summary_id(s: dict[str, Any]) -> str | None:
    """The experiment a saved summary says it belongs to (D-046's summary records it in its lock record)."""
    for v in (s.get("experiment_id"), (s.get("opened") or {}).get("protocol"),
              (s.get("assessment_opened") or {}).get("protocol")):
        if isinstance(v, str):
            return v
    return None


def read_summary(dec: str, eid: str, path: Path) -> dict[str, Any]:
    """Status of one saved summary, never half-read:

    * ``not_run``      — no saved summary on this installation;
    * ``malformed``    — the file exists but is not readable JSON (or not a JSON object);
    * ``incompatible`` — it is JSON but belongs to another experiment or lacks the fields this page reads
      (for example an older summary format);
    * ``available``    — read in full.
    """
    if not path.exists():
        return {"status": "not_run", "status_detail": None}
    try:
        s = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"status": "malformed", "status_detail": f"{path.name} could not be read as JSON ({type(exc).__name__})."}
    if not isinstance(s, dict):
        return {"status": "malformed", "status_detail": f"{path.name} is not a JSON object."}
    sid = _summary_id(s)
    if sid is not None and sid != eid:
        return {"status": "incompatible", "status_detail": f"{path.name} belongs to {sid}, not {eid}."}
    try:
        n, opened, findings = _READERS[dec](s)
    except (KeyError, StopIteration, TypeError, ValueError, IndexError, AttributeError) as exc:
        return {"status": "incompatible",
                "status_detail": f"{path.name} lacks a field this page reads ({type(exc).__name__}); it may be from "
                                 "an older summary format."}
    return {"status": "available", "status_detail": None, "participants": n, "opened_at": opened.get("opened_at"),
            "reopened_at": [r["at"] for r in opened.get("reopened", [])], "findings": findings}


def research_summaries() -> dict[str, Any]:
    """Headline results of the 20 Oct research experiments, when their saved summaries exist on this installation.
    Only pooled numbers are returned: no per-participant values and no pseudonymous IDs."""
    items = []
    for dec, eid, fname, on in SUMMARIES:
        item = {"decision_id": dec, "experiment_id": eid, "evaluated_on": on}
        item.update(read_summary(dec, eid, paths().artifacts / "research" / eid / fname))
        items.append(item)
    return {"schema_version": "1.0", "items": items}
