"""Prompt pack v4 / 02-04 unit checks: folds, stopping metric, adaptation state, calibration and warning selection."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from glucotwin.models.adaptation import AdaptationPolicy, AdaptationState
from glucotwin.research import calibration, warnings
from glucotwin.research.metrics import exposure_minutes, macro_mae_grouped, paired_bootstrap
from glucotwin.research.models import fit_lightgbm
from glucotwin.research.protocol import ProtocolError, make_plans

FOLDS = {"outer_folds": 5, "calibration_fraction": 0.2, "calibration_min_participants": 2, "inner_folds": 3}


# ------------------------------------------------------------------------------------------------ folds


def test_plans_are_deterministic_participant_disjoint_and_cover_everyone_once():
    ids = [f"p{i:02d}" for i in range(14)]
    a, b = make_plans(ids, FOLDS, 7), make_plans(list(reversed(ids)), FOLDS, 7)
    assert [x.as_dict() for x in a] == [x.as_dict() for x in b]
    outer = [p for p in a if p.fold != "final"]
    assert sorted(x for p in outer for x in p.assessment) == ids
    for p in a:
        assert len(p.calibration) >= 2
        assert not (set(p.assessment) & set(p.calibration) or set(p.assessment) & set(p.development)
                    or set(p.calibration) & set(p.development))
    assert a[-1].fold == "final" and not a[-1].assessment


def test_a_cohort_too_small_for_the_declared_folds_is_refused():
    with pytest.raises(ProtocolError):
        make_plans(["a", "b", "c"], FOLDS, 1)


def test_tail_early_stopping_purges_rows_whose_labels_reach_the_tail():
    from types import SimpleNamespace

    from glucotwin.research.develop import head_tail

    o = np.arange(0, 1000, 5.0)
    t = pd.DataFrame({"origin": o, "patient_id": "a"})
    ctx = SimpleNamespace(proto={"folds": {"early_stopping_tail_fraction": 0.2, "purge_minutes": 82.5}}, t=t,
                          pids=t["patient_id"].to_numpy())
    head, tail = head_tail(ctx, np.ones(o.size, bool))
    start = o.min() + 0.8 * (o.max() - o.min())
    assert o[tail].min() >= start and (o[head] + 82.5 < start).all()
    assert not (head & tail).any() and (~head & ~tail).sum() > 0   # purged gap


# ------------------------------------------------------------------------------------------------ objective / stopping


def test_macro_mae_stopping_metric_is_what_lightgbm_early_stops_on():
    rng = np.random.default_rng(0)
    n = 600
    X = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = 3 * X["a"].to_numpy() + rng.normal(size=n)
    groups = np.array(["big"] * 500 + ["small"] * 100)
    m, info = fit_lightgbm(["a", "b"], {"learning_rate": 0.1, "num_leaves": 7}, "l1", "macro_mae", X[:400], y[:400],
                           X[400:], y[400:], groups[400:], 1, 300, 10, 1)
    assert info["objective"] == "l1" and info["stopping_metric"] == "macro_mae"
    hist = m.booster.best_score["valid_0"]["macro_mae"]
    assert hist == pytest.approx(macro_mae_grouped(m.predict_delta(X[400:]), y[400:], groups[400:]), rel=1e-6)


def test_paired_bootstrap_resamples_people_and_counts_improvements():
    a = pd.Series({"p1": 10.0, "p2": 12.0, "p3": 9.0})
    b = pd.Series({"p1": 11.0, "p2": 12.0, "p3": 10.0})
    r = paired_bootstrap(a, b, 500, 1)
    assert r["mean_diff"] == pytest.approx(-2 / 3) and (r["improved"], r["worsened"], r["unchanged"]) == (2, 0, 1)
    assert r["ci95"][0] <= r["mean_diff"] <= r["ci95"][1]


# ------------------------------------------------------------------------------------------------ adaptation state


def _state(k=0.0):
    return AdaptationState(AdaptationPolicy(shrinkage_k=k, half_life_minutes=1e9, min_residuals=1, cap_mg_dl=100.0,
                                            match_tolerance_minutes=2.5), [30])


def test_repeating_a_forecast_request_never_counts_its_residual_twice():
    obs = np.array([0.0, 30.0, 60.0])
    val = np.array([100.0, 130.0, 160.0])
    avail = obs.copy()
    s = _state()
    s.step(0.0, obs, val, avail, {30: 100.0}, "f0")
    s.step(0.0, obs, val, avail, {30: 100.0}, "f0-again")      # duplicate request: ignored
    out = s.step(40.0, obs, val, avail, {30: 130.0}, "f1")
    assert s.h[30].n == 1 and out[30] == pytest.approx(30.0)
    with pytest.raises(ValueError):
        s.step(10.0, obs, val, avail, {30: 1.0}, "back")       # time never goes backwards


def test_no_residual_matures_before_its_target_is_available():
    obs = np.array([0.0, 30.0])
    val = np.array([100.0, 140.0])
    avail = np.array([0.0, 80.0])                               # target observed at 30, released at 80
    s = _state()
    s.step(0.0, obs, val, avail, {30: 100.0}, "f0")
    assert s.step(50.0, obs, val, avail, {30: None}, "f1")[30] == 0.0 and s.h[30].n == 0
    assert s.step(85.0, obs, val, avail, {30: None}, "f2")[30] == pytest.approx(40.0) and s.h[30].n == 1


def test_frozen_state_control_stops_learning_at_the_declared_boundary():
    from glucotwin.research.adapt import prequential

    o = np.arange(0, 600, 5.0)
    t = pd.DataFrame({"patient_id": "a", "origin": o, "elapsed_min": o})
    obs = o.copy()
    val = 100 + np.where(o > 300, 40.0, 10.0)
    prep = {"a": type("P", (), {"g_obs": obs, "g_val": val, "g_avail": obs})()}
    pop = {30: np.full(o.size, 100.0)}
    pol = AdaptationPolicy(shrinkage_k=0.0, half_life_minutes=60.0, min_residuals=1, match_tolerance_minutes=2.5)
    live, _ = prequential(t, prep, np.ones(o.size, bool), pop, pol, [30])
    frozen, _ = prequential(t, prep, np.ones(o.size, bool), pop, pol, [30], freeze_after_min=200.0)
    after = o >= 200
    assert np.allclose(frozen[30][after], frozen[30][after][0])  # constant after freezing
    assert np.allclose(frozen[30][~after], live[30][~after])     # identical before
    assert live[30][-1] > frozen[30][-1]                          # the live state kept learning the shift


# ------------------------------------------------------------------------------------------------ calibration


def test_finite_sample_rank_and_insufficient_calibration():
    q, k, n = calibration.finite_sample_quantile(np.arange(1, 100, dtype=float), 0.8)
    assert (k, n) == (80, 99) and q == 80.0
    assert calibration.finite_sample_quantile(np.arange(10, dtype=float), 0.8)[0] is None


def test_calibration_artifacts_refuse_a_different_pipeline_and_ranges_are_not_clipped():
    rng = np.random.default_rng(3)
    n = 400
    t = pd.DataFrame({"patient_id": np.repeat(["a", "b"], n // 2), "origin": np.tile(np.arange(n // 2) * 5.0, 2),
                      "target_30": rng.normal(60, 20, n), "target_30_avail": np.tile(np.arange(n // 2) * 5.0 + 30, 2),
                      "target_60": rng.normal(60, 30, n), "target_60_avail": np.tile(np.arange(n // 2) * 5.0 + 60, 2)})
    final = {30: np.full(n, 60.0), 60: np.full(n, 60.0)}
    ident = {"pipeline": "x", "mode": "off", "bundle_hash": "abc"}
    cfg = {"half_life": 720.0, "k_s": 24.0, "min_residuals": 6, "reset_gap": 180.0}
    cal = calibration.calibrate(t, np.ones(n, bool), final, [30, 60], 0.8, 2.5, cfg, ident)
    assert cal["horizons"]["30"]["global_q"] < cal["horizons"]["60"]["global_q"]  # per horizon, never pooled
    calibration.check_compatible(cal, ident)
    with pytest.raises(calibration.CalibrationError):
        calibration.check_compatible(cal, {**ident, "bundle_hash": "other"})
    iv = calibration.intervals(t, np.ones(n, bool), final, cal, [30, 60], 2.5)
    lo = iv["global"][60][0]
    assert np.allclose(lo, 60.0 - cal["horizons"]["60"]["global_q"])  # may go below 40 mg/dL: no clipping


# ------------------------------------------------------------------------------------------------ warnings


def test_exposure_counts_bounded_non_overlapping_time():
    o = np.array([0.0, 5.0, 10.0, 100.0, 0.0, 3.0])
    p = np.array(["a", "a", "a", "a", "b", "b"])
    # a: 5 + 5 + 5 (capped) + 5 (last) = 20; b: 3 + 5 = 8
    assert exposure_minutes(o, p, np.ones(6, bool), 5.0) == pytest.approx(28.0)
    assert exposure_minutes(o, p, np.array([True, False, True, False, False, False]), 5.0) == pytest.approx(10.0)


def _row(th, recall, prec, fa, eps, assessable=1):
    return {"threshold": th, "recall": recall, "precision": prec, "false_alarms_per_observed_patient_day": fa,
            "warning_episodes": eps, "assessable_warnings": assessable, "f1": None, "warnings_per_patient_day": eps}


def test_workload_rule_maximizes_recall_within_budget_with_declared_ties():
    rows = [_row(-30, 1.0, 0.4, 3.0, 50), _row(-20, 0.9, 0.5, 1.9, 30), _row(-10, 0.9, 0.5, 1.5, 28),
            _row(0, 0.9, 0.6, 1.0, 20), _row(10, 0.5, 0.9, 0.2, 5)]
    th, _ = warnings.select_workload(rows, 2.0)
    assert th == 0  # recall 0.9 ties broken by higher precision
    rows2 = [_row(-10, 0.8, 0.5, 1.0, 20), _row(0, 0.8, 0.5, 1.0, 20)]
    assert warnings.select_workload(rows2, 2.0)[0] == 0  # full tie -> higher (more conservative) threshold
    none, why = warnings.select_workload([_row(-30, 1.0, 0.4, 3.0, 50)], 2.0)
    assert none is None and "no threshold" in why
    silent = [_row(40, None, None, 0.0, 0, assessable=0)]
    assert warnings.select_workload(silent, 2.0)[0] is None  # undefined precision is not perfect precision


def test_zero_onsets_and_zero_warnings_give_unavailable_not_perfect_metrics():
    from glucotwin.evaluation.alerts import EpisodeResult, summarize

    s = summarize([EpisodeResult()], 1.0, 1.0, 60.0)
    assert s["recall"] is None and s["precision"] is None and s["f1"] is None
    assert macro_mae_grouped(np.array([1.0]), np.array([0.0]), np.array(["a"])) == 1.0


# ------------------------------------------------------------------------------------------------ next-protocol guardrails


def _proto_with_windows(windows):
    return {"models": {"baselines": {"linear_trend": {"window_minutes": windows}}},
            "tracks": {"portable_15min": {"cadence_minutes": 15, "superset_feature_set": "cgm15-v1"},
                       "multimodal_5min": {"cadence_minutes": 5, "superset_feature_set": "dyn-prof-v2"}}}


def test_trend_windows_too_short_for_the_cadence_are_refused_but_v1_lists_are_kept():
    from glucotwin.research.develop import trend_windows

    assert trend_windows(_proto_with_windows([15, 30]), "portable_15min") == [15, 30]  # frozen v1: reproduced as is
    with pytest.raises(ProtocolError):
        trend_windows(_proto_with_windows({"portable_15min": [15, 30]}), "portable_15min")
    assert trend_windows(_proto_with_windows({"portable_15min": [30, 60]}), "portable_15min") == [30, 60]
    assert trend_windows(_proto_with_windows({"multimodal_5min": [15, 30]}), "multimodal_5min") == [15, 30]


def test_valid_15_minute_trend_windows_extrapolate_instead_of_repeating_the_last_reading():
    from glucotwin.data.store import EPOCH, PatientData, empty_table
    from glucotwin.features import FEATURE_SETS, build_features, prepare
    from glucotwin.models.population import LinearTrendModel

    t = np.arange(0, 240, 15.0)
    g = pd.DataFrame({"event_id": [f"x-r0-{i:05d}" for i in range(t.size)],
                      "observed_at": EPOCH + pd.to_timedelta(t, unit="min"),
                      "available_at": EPOCH + pd.to_timedelta(t, unit="min"), "value_mg_dl": 100 + t / 3,
                      "quality": "ok", "flags": "", "source": "fixture"})
    p = PatientData({"patient_id": "x"}, [], g, empty_table("activity"), empty_table("meals"))
    X = build_features(prepare(p), np.array([225.0]), FEATURE_SETS["cgm15-v1"]).frame
    for w in (30, 60):
        delta = LinearTrendModel(60, w, 1.0).predict_delta(X)[0]
        assert delta == pytest.approx(20.0)        # 1/3 mg/dL per minute for 60 minutes: a real trend
    assert LinearTrendModel(60, 15, 1.0).predict_delta(X)[0] == 0.0  # the v1 window: silently persistence


def test_public_key_fold_assignment_is_identical_under_different_pseudonym_salts():
    src = [f"cgmacros:CGMacros-{i:03d}" for i in range(1, 15)]
    a = {f"pt-a{i:02d}": k for i, k in enumerate(src)}
    b = {f"pt-z{13 - i:02d}": k for i, k in enumerate(src)}  # another installation: different salted pseudonyms
    pa = make_plans(list(a), FOLDS, 7, keys=a)
    pb = make_plans(list(b), FOLDS, 7, keys=b)
    for x, y in zip(pa, pb, strict=True):
        assert sorted(a[i] for i in x.assessment) == sorted(b[i] for i in y.assessment)
        assert sorted(a[i] for i in x.calibration) == sorted(b[i] for i in y.calibration)


def test_a_protocol_needing_an_unavailable_source_cannot_be_frozen():
    from glucotwin.research.protocol import check_required_sources

    proto = {"experiment_id": "x", "requires_sources": ["cgmacros", "ai_readi_v3"]}
    with pytest.raises(ProtocolError, match="ai_readi_v3"):
        check_required_sources(proto, {"cgmacros": "eligible_for_experiment", "ai_readi_v3": "access_required"})
    check_required_sources(proto, {"cgmacros": "eligible_for_experiment", "ai_readi_v3": "eligible_for_experiment"})


def test_multi_criteria_promotion_fails_when_high_glucose_error_exceeds_its_bound():
    from glucotwin.research.render import promotion_check

    def c(title, h, m, lo, hi):
        return {"comparison": title, "horizon": h, "mean_diff": m, "ci95": [lo, hi], "n_participants": 14,
                "improved": 10, "worsened": 4}
    t = {"comparisons": [c("Selected pipeline minus current v2 recipe", 30, -0.6, -1.0, -0.3),
                         c("Selected pipeline minus current v2 recipe", 60, -1.9, -2.8, -1.0),
                         c("High-glucose error (target > 180): selected minus current v2 recipe", 30, 0.6, -0.2, 1.8),
                         c("High-glucose error (target > 180): selected minus current v2 recipe", 60, 2.7, 0.3, 5.1)],
         "warnings": {"policies": [
             {"pipeline": "selected", "horizon": 60, "policy": "primary", "recall": 0.91, "false_alarms_per_observed_day": 1.3},
             {"pipeline": "v2_recipe:dyn-v2", "horizon": 60, "policy": "v2_fixed", "recall": 1.0,
              "false_alarms_per_observed_day": 2.8}]}}
    crit = {"high_glucose_error": {"horizons": [30, 60], "max_ci_upper_mg_dl": 1.0},
            "missed_onsets": {"horizon": 60, "max_recall_drop": 0.05},
            "false_warnings": {"horizon": 60, "max_per_observed_day": 2.0, "not_above_serving": True}}
    res = {r["criterion"]: r["passed"] for r in promotion_check({"tracks": {"multimodal_5min": t}}, crit)}
    assert res["average error, 30 min"] and res["average error, 60 min"] and res["false warnings"]
    assert not res["high-glucose error, 60 min"] and not res["high-glucose error, 30 min"]
    assert not res["missed onsets"]   # 0.91 is more than 0.05 below 1.0


def test_the_declared_next_protocol_refuses_to_freeze_without_ai_readi():
    from glucotwin.research import runner
    from glucotwin.research.protocol import load_protocol, split_file_path

    p = load_protocol("gt-nested-2026-10-12-v2")
    assert p["status"] == "declared_not_frozen" and p["folds"]["assignment_key"] == "source_participant_key"
    with pytest.raises(ProtocolError, match="ai_readi_v3"):
        runner.do_freeze("gt-nested-2026-10-12-v2")
    assert not split_file_path("gt-nested-2026-10-12-v2").exists()


def test_public_key_ordering_makes_tables_independent_of_the_pseudonym_salt(synthetic_ready, tmp_path):
    from glucotwin.data.pipeline import synthetic_store_dir
    from glucotwin.data.store import Store
    from glucotwin.research.protocol import load_protocol
    from glucotwin.research.tables import build_track

    proto = load_protocol("gt-nested-2026-10-12-v2")
    syn = Store(synthetic_store_dir())
    src = ["SYN-T01", "SYN-T02", "SYN-T03"]
    tables = []
    for name, ids in (("a", ["pt-b", "pt-a", "pt-c"]), ("b", ["pt-x", "pt-z", "pt-y"])):  # different salts
        st = Store(tmp_path / name)
        for new, old in zip(ids, src, strict=True):
            p = syn.load(old)
            p.meta["patient_id"] = new
            st.write_patient(p)
        keys = {new: f"fixture:{old}" for new, old in zip(ids, src, strict=True)}
        td = build_track(proto, "portable_15min", st, ids, "fixture", None, "fp", order=keys)
        tables.append(td.table.assign(key=td.table["patient_id"].map(keys)).drop(columns=["patient_id", "recording_id"]))
    pd.testing.assert_frame_equal(tables[0], tables[1])


def test_identical_catboost_fits_save_byte_identical_files(tmp_path):
    from glucotwin.models.population import CatBoostModel
    from glucotwin.research.models import fit_catboost

    rng = np.random.default_rng(4)
    X = pd.DataFrame({"a": rng.normal(size=300), "b": rng.normal(size=300)})
    y = 2 * X["a"].to_numpy() + rng.normal(size=300)
    digests = []
    for i in range(2):
        m, _ = fit_catboost(["a", "b"], {"depth": 3}, X[:200], y[:200], X[200:], y[200:], 7, 40, 10, 1)
        assert isinstance(m, CatBoostModel)
        d = tmp_path / str(i)
        d.mkdir()
        m.save(d, "h30")
        digests.append((d / "h30.cbm").read_bytes())
    assert digests[0] == digests[1]
