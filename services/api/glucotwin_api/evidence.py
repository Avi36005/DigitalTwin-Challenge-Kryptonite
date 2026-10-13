"""Evidence catalogue for the API: which experiments exist, the serving model on its own, research reports and the
measured dataset inventory. Every value is read from saved artifacts or reports; nothing is typed in here."""

from __future__ import annotations

import json
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
