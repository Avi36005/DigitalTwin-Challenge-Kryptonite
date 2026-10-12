"""End-to-end check of the isolated research runner on FICTIONAL participants in a throwaway GLUCOTWIN_HOME.

Covers: freeze -> develop -> assess -> external -> report -> promote/rollback, plus the guarantees the prompts ask for:
no registry side effects, participant-disjoint folds, assessment opened once, frozen-protocol edits refused, headline
numbers recomputable from saved predictions, and online/offline parity of the packaged candidate.
"""

from __future__ import annotations

import hashlib
import json
import shutil

import numpy as np
import pandas as pd
import pytest
import yaml
from glucotwin.config import _load_yaml, paths

EXP = "gt-nested-2026-10-12-v1"
REAL_REGISTRY = paths().artifacts / "registry.json"


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


@pytest.fixture(scope="module")
def research_home(tmp_path_factory, synthetic_ready):
    from glucotwin.data import canonical as cn
    from glucotwin.data.pipeline import synthetic_store_dir
    from glucotwin.data.store import Store, to_minutes

    real_root = paths().root
    root = tmp_path_factory.mktemp("home")
    shutil.copytree(real_root / "configs", root / "configs")
    (root / "reports").mkdir()
    proto_path = root / "configs" / "experiments" / f"{EXP}.yaml"
    proto = yaml.safe_load(proto_path.read_text())
    proto["folds"].update({"outer_folds": 3, "inner_folds": 2})
    proto["models"]["search"].update({"trials_per_config": 1, "max_boosting_rounds": 40, "early_stopping_rounds": 5,
                                      "threads_per_fit": 1})
    proto["adaptation"]["grid"] = {"shrinkage_k": [24], "half_life_minutes": [240]}
    proto["evaluation"]["bootstrap_resamples"] = 50
    proto_path.write_text(yaml.safe_dump(proto, sort_keys=False))
    # A FICTIONAL "current recipe" (hyperparameters, iterations, adaptation, warning margin) stands in for the real v2
    # artifact, which is git-ignored and absent from a fresh checkout. The previously serving model is the synthetic
    # demonstration model built by `make synthetic`.
    v2 = root / "artifacts" / "models" / "lightgbm.dyn-v2.gt-primary-2026-10-11-v2"
    v2.mkdir(parents=True)
    recipe = {"learning_rate": 0.08, "num_leaves": 15, "max_depth": 4, "min_child_samples": 40, "lambda_l2": 1.0,
              "feature_fraction": 0.9, "bagging_fraction": 0.9, "best_iteration": 25}
    (v2 / "manifest.json").write_text(json.dumps({
        "feature_set_id": "dyn-v2", "params": {"30": recipe, "60": recipe},
        "serving": {"model_version": "fixture-current-recipe",
                    "adaptation": {"shrinkage_k": 96.0, "half_life_minutes": 240.0},
                    "alerts": {"threshold_margin_mg_dl": -30.0}}}))
    from glucotwin.synthetic_model import VERSION as SYN_MODEL

    syn_dir = f"artifacts/models/{SYN_MODEL}"
    shutil.copytree(real_root / syn_dir, root / syn_dir)
    entry = next(m for m in json.loads(REAL_REGISTRY.read_text())["models"] if m["model_version"] == SYN_MODEL)
    (root / "artifacts" / "registry.json").write_text(json.dumps(
        {"models": [{**entry, "mode": "dataset_replay"}], "serving": {"dataset_replay": SYN_MODEL}}))
    syn = Store(synthetic_store_dir())
    dev = Store(root / "data" / "processed" / "cgmacros" / "v1")
    ext = Store(root / "data" / "processed" / "shanghai" / "v1")
    for i in range(1, 13):
        pdata = syn.load(f"SYN-T{i:02d}")
        if i <= 8:
            pdata.meta.update({"eligible_for_primary_analysis": True})
            dev.write_patient(pdata)
        else:
            g = pdata.glucose.sort_values("observed_at").reset_index(drop=True)
            keep = cn.causal_decimate(to_minutes(g["observed_at"]), 15.0)
            pdata.glucose = g[keep].reset_index(drop=True)
            pdata.activity = pdata.activity.iloc[0:0]
            pdata.meta.update({"eligible_for_portable_external": True, "eligible_for_primary_analysis": False})
            ext.write_patient(pdata)
    for s in (dev, ext):
        (s.directory / "provenance.json").write_text(json.dumps({"fixture": "synthetic", "store": s.directory.name}))
    mp = pytest.MonkeyPatch()
    mp.setenv("GLUCOTWIN_HOME", str(root))
    _load_yaml.cache_clear()
    yield root
    mp.undo()
    _load_yaml.cache_clear()


@pytest.fixture(scope="module")
def ran(research_home):
    from glucotwin.research import runner
    from glucotwin.research.report import write_reports

    before = _sha(REAL_REGISTRY)
    tmp_reg_before = _sha(research_home / "artifacts" / "registry.json")
    frozen = runner.do_freeze(EXP)
    dev = runner.do_develop(EXP, workers=0)
    internal = runner.do_assess(EXP)
    external = runner.do_external(EXP)
    rep = write_reports(EXP)
    return {"frozen": frozen, "develop": dev, "internal": internal, "external": external, "report": rep,
            "real_registry_unchanged": _sha(REAL_REGISTRY) == before,
            "home_registry_unchanged": _sha(research_home / "artifacts" / "registry.json") == tmp_reg_before}


def test_runner_never_writes_any_registry(ran):
    assert ran["real_registry_unchanged"] and ran["home_registry_unchanged"]


def test_fold_membership_is_participant_disjoint_and_every_person_assessed_once(ran, research_home):
    doc = json.loads((research_home / "artifacts" / "research" / EXP / "splits.json").read_text())
    outer = [p for p in doc["plans"] if p["fold"] != "final"]
    assessed = [x for p in outer for x in p["assessment"]]
    assert sorted(assessed) == sorted(doc["development_participants"]) and len(set(assessed)) == len(assessed)
    for p in doc["plans"]:
        a, c, d = set(p["assessment"]), set(p["calibration"]), set(p["development"])
        assert not (a & c or a & d or c & d)
        assert set().union(*map(set, p["inner"])) == d
    assert not set(doc["external_participants"]) & set(doc["development_participants"])
    preds = pd.read_parquet(research_home / "artifacts" / "research" / EXP / "assessment" / "predictions.parquet")
    for p in outer:
        got = set(preds.loc[preds["fold"] == p["fold"], "patient_id"])
        assert got == set(p["assessment"])  # a fold's predictions only cover its own held-out people


def test_development_never_saw_assessment_or_external_people(ran, research_home):
    root = research_home / "artifacts" / "research" / EXP
    doc = json.loads((root / "splits.json").read_text())
    for p in doc["plans"]:
        for track in ("multimodal_5min", "portable_15min"):
            d = root / "development" / p["fold"] / track
            oof = pd.read_parquet(d / "inner_oof.parquet")
            cal = pd.read_parquet(d / "calibration_predictions.parquet")
            assert set(oof["patient_id"]) <= set(p["development"])
            assert set(cal["patient_id"]) <= set(p["calibration"])
            for b in json.loads((d / "pipeline.json").read_text())["bundles"].values():
                man = json.loads((root / b["dir"] / "manifest.json").read_text())
                if "research" in man:
                    assert set(man["research"]["development_participants"]) == set(p["development"])


def test_assessment_is_opened_once(ran):
    from glucotwin.research import runner
    from glucotwin.research.assess import AssessmentError

    with pytest.raises(AssessmentError):
        runner.do_assess(EXP)
    with pytest.raises(AssessmentError):
        runner.do_external(EXP)


def test_headline_numbers_are_recomputed_from_saved_predictions(ran, research_home):
    root = research_home / "artifacts" / "research" / EXP
    rep = json.loads((root / "report.json").read_text())
    preds = pd.read_parquet(root / "assessment" / "predictions.parquet")
    row = next(p for p in rep["tracks"]["multimodal_5min"]["pipelines"]
               if p["pipeline"] == "persistence:-" and p["mode"] == "off")
    d = preds[(preds["track"] == "multimodal_5min") & (preds["pipeline"] == "persistence:-") & (preds["mode"] == "off")
              & (preds["horizon"] == 60) & (preds["quality"] != "insufficient") & np.isfinite(preds["target"])]
    mae = (d["final"] - d["target"]).abs().groupby(d["patient_id"]).mean().mean()
    assert row["horizons"]["60"]["mae"] == pytest.approx(mae, abs=1e-3)
    # every candidate in a track is scored on identical origins
    n = {p["pipeline"] + p["mode"]: p["horizons"]["30"]["n_origins"] for p in rep["tracks"]["multimodal_5min"]["pipelines"]}
    assert len(set(n.values())) == 1
    assert rep["external"]["status"] == "completed"
    assert (paths().reports / "nested_benchmark_report.md").exists()


def test_packaged_candidate_matches_offline_path_before_rounding(ran):
    for track, c in ran["internal"]["candidates"].items():
        assert c["parity"]["passed"], (track, c["parity"])
        assert c["parity"]["warning_firings_online"] == c["parity"]["warning_firings_offline"]


def test_promotion_is_explicit_atomic_and_reversible(ran, research_home):
    from glucotwin.research.promote import PromotionError, promote, rollback
    from glucotwin.serving import load_serving

    reg = research_home / "artifacts" / "registry.json"
    before = _sha(reg)
    dry = promote(EXP, "multimodal_5min")
    assert dry["status"] == "dry_run" and _sha(reg) == before
    with pytest.raises(PromotionError):
        promote(EXP, "portable_15min", confirm=True)  # not serving-eligible
    previous = load_serving("dataset_replay").model_version
    out = promote(EXP, "multimodal_5min", confirm=True)
    s = load_serving("dataset_replay")
    assert s is not None and s.model_version == out["model_version"] and out["previous"] == previous
    rollback(previous)
    assert load_serving("dataset_replay").model_version == previous


def test_editing_a_frozen_protocol_is_refused(ran, research_home):
    from glucotwin.research.protocol import ProtocolError, load_frozen

    p = research_home / "configs" / "experiments" / f"{EXP}.yaml"
    text = p.read_text()
    try:
        p.write_text(text.replace("tie_margin_mg_dl: 0.5", "tie_margin_mg_dl: 0.4"))
        _load_yaml.cache_clear()
        with pytest.raises(ProtocolError):
            load_frozen(EXP)
    finally:
        p.write_text(text)
        _load_yaml.cache_clear()
