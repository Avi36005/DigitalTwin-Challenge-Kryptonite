"""D-053 (gt-constrained-2026-10-21): behavioural tests written before the formal fits.

Small fixtures with independently specified expectations: causal correction, participant isolation, peak-aware loss
weights, role exclusion, retained-winner identity, failure/fallback handling, gate boundaries, calibration identity
(the D-052 mixed-fit regression) and warning accounting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import constrained_study as C  # noqa: E402
from glucotwin.models.adaptation import AdaptationPolicy  # noqa: E402
from glucotwin.research import adapt  # noqa: E402
from glucotwin.research.calibration import CalibrationError  # noqa: E402

# ----------------------------------------------------------------------------------------------- fixtures


def _cfg(weights="W1", features="F0", objective="l2", template_index=0, cid="x"):
    return {"family": "lightgbm", "id": cid, "features": features, "weights": weights, "objective": objective,
            "template": "T", "template_index": template_index,
            "params": {"learning_rate": 0.2, "num_leaves": 4, "max_depth": 2, "min_data_in_leaf": 5,
                       "lambda_l2": 0.0, "feature_fraction": 1.0, "bagging_fraction": 1.0}}


def _data(n_people=6, n=120, seed=0):
    rng = np.random.default_rng(seed)
    pids = np.repeat([f"p{i}" for i in range(n_people)], n)
    origins = np.tile(np.arange(n) * 5.0, n_people)
    X = rng.normal(size=(len(pids), 3))
    g = 150 + 30 * X[:, 0]
    y_abs = g + 20 * X[:, 1] + rng.normal(0, 3, len(pids))
    return pids, origins, X, g, y_abs


# ----------------------------------------------------------------------------------------------- peak-aware weights


def test_peak_weight_uses_absolute_future_glucose_not_the_delta():
    # 185 mg/dL reached from 183 (delta +2) is a high target; 170 reached from 100 (delta +70) is not
    w = C.peak_weights(np.array([185.0, 170.0]), "WP")
    assert w[0] > w[1]
    assert w[0] / w[1] == pytest.approx(2.0)


def test_peak_weights_are_finite_nonnegative_mean_one_and_unweighted_policy_is_none():
    y = np.array([100.0, 190.0, 250.0, 120.0, 181.0])
    w = C.peak_weights(y, "WP")
    assert np.all(np.isfinite(w)) and np.all(w > 0) and w.mean() == pytest.approx(1.0)
    assert C.peak_weights(y, "W1") is None
    assert C.peak_weights(np.array([180.0]), "WP")[0] == pytest.approx(1.0)  # exactly 180 is not above 180
    with pytest.raises(ValueError):
        C.peak_weights(np.array([np.nan, 200.0]), "WP")


def test_outcomes_of_people_outside_the_fit_never_change_weights_or_forecasts():
    pids, o, X, g, y_abs = _data()
    train = np.isin(pids, ["p0", "p1", "p2", "p3"])
    test = ~train
    fp1, _ = C.fit_tree(_cfg("WP"), X, y_abs - g, y_abs, pids, o, train, 1, ["a", "b", "c"], rounds=20)
    y2 = y_abs.copy()
    y2[test] += 400.0  # every held-out target becomes a "high" target and much larger
    fp2, _ = C.fit_tree(_cfg("WP"), X, y2 - g, y2, pids, o, train, 1, ["a", "b", "c"], rounds=20)
    assert fp1.model_hash == fp2.model_hash
    assert np.array_equal(fp1.predict_delta(X[test]), fp2.predict_delta(X[test]))


def test_the_high_target_weight_reaches_the_loss_but_not_the_features():
    pids, o, X, g, y_abs = _data()
    train = np.isin(pids, ["p0", "p1", "p2", "p3"])
    a, _ = C.fit_tree(_cfg("W1"), X, y_abs - g, y_abs, pids, o, train, 1, ["a", "b", "c"], rounds=20)
    b, info = C.fit_tree(_cfg("WP"), X, y_abs - g, y_abs, pids, o, train, 1, ["a", "b", "c"], rounds=20)
    assert a.model_hash != b.model_hash               # the weights change the fitted loss
    assert b.columns == ["a", "b", "c"]               # no label-derived column enters the inputs
    assert b.model.num_feature() == 3
    assert info["weight_mean"] == pytest.approx(1.0)


# ----------------------------------------------------------------------------------------------- stopping uses training people only


def test_early_stopping_head_and_tail_come_only_from_training_people_with_a_purge_gap():
    pids, o, *_ = _data()
    train = np.isin(pids, ["p0", "p1", "p2"])
    head, tail = C.head_tail(o, pids, train)
    assert not (head | tail)[~train].any()
    assert not (head & tail).any()
    for p in ["p0", "p1", "p2"]:
        m = pids == p
        assert o[head & m].max() + C.PURGE < o[tail & m].min()


def test_early_stopped_fit_records_its_best_iteration_and_the_refit_uses_it():
    pids, o, X, g, y_abs = _data()
    train = np.isin(pids, ["p0", "p1", "p2", "p3"])
    fp, info = C.fit_tree(_cfg(), X, y_abs - g, y_abs, pids, o, train, 1, ["a", "b", "c"])
    assert info["best_iteration"] >= 1 and info["rounds"] == info["best_iteration"] == fp.rounds
    assert fp.model.current_iteration() == fp.rounds


def test_failed_fit_is_reported_and_makes_the_candidate_infeasible():
    pids, o, X, g, y_abs = _data()
    train = np.isin(pids, ["p0", "p1"])
    bad = y_abs.copy()
    bad[np.where(train)[0][0]] = np.nan
    fp, info = C.fit_tree(_cfg(), X, bad - g, bad, pids, o, train, 1, ["a", "b", "c"], rounds=5)
    assert fp is None and "error" in info
    r0 = {"mae": 20.0, "high": 30.0, "avail": 1.0}
    ok, why = C.check_feasible({"failed": True, "mae": 10.0, "high": 20.0, "avail": 1.0}, r0, 60)
    assert not ok and "fit failed in this fold" in why
    # missing forecasts cannot make a candidate look better: availability loss alone excludes it
    ok, why = C.check_feasible({"failed": False, "mae": 10.0, "high": 20.0, "avail": 0.99}, r0, 60)
    assert not ok and any("availability" in w for w in why)


# ----------------------------------------------------------------------------------------------- roles


def test_role_guard_refuses_calibration_or_assessment_people_in_a_fit():
    plan = SimpleNamespace(fold="outer-x", development=("a", "b", "c"), calibration=("d",), assessment=("e",))
    C.check_roles(plan, ["a", "b"], "inner")
    with pytest.raises(RuntimeError):
        C.check_roles(plan, ["a", "d"], "outer")   # a dev+calibration refit is not allowed in this study
    with pytest.raises(RuntimeError):
        C.check_roles(plan, ["a", "e"], "outer")


def test_frozen_split_holds_out_complete_people_in_disjoint_roles():
    f = ROOT / "artifacts/research/gt-2h-2026-10-20/splits.json"
    if not f.exists():
        pytest.skip("frozen base split not available (dataset-free checkout)")
    d = json.loads(f.read_text())
    seen = []
    for p in d["plans"]:
        a, c, dv = set(p["assessment"]), set(p["calibration"]), set(p["development"])
        assert not (a & c) and not (a & dv) and not (c & dv)
        assert set().union(*map(set, p["inner"])) == dv
        if p["fold"] != "final":
            seen += p["assessment"]
    assert len(seen) == len(set(seen)) == 14


# ----------------------------------------------------------------------------------------------- causal correction


def _prep_and_table():
    obs = np.arange(0, 600, 5.0)
    val = 120 + 0.1 * obs
    prep = {"p": SimpleNamespace(g_obs=obs.copy(), g_val=val.copy(), g_avail=obs.copy()),
            "q": SimpleNamespace(g_obs=obs.copy(), g_val=val.copy() + 30, g_avail=obs.copy())}
    origins = np.arange(0, 500, 5.0)
    t = pd.DataFrame({"patient_id": ["p"] * len(origins) + ["q"] * len(origins),
                      "origin": np.r_[origins, origins], "elapsed_min": np.r_[origins, origins]})
    pol = AdaptationPolicy("test", True, 1.0, 240.0, 25.0, 1, 180.0, 2.5, 120.0)
    pop = {30: np.full(len(t), 100.0)}
    return prep, t, pol, pop


def test_correction_at_an_origin_ignores_readings_after_it_including_late_releases():
    prep, t, pol, pop = _prep_and_table()
    rows = np.ones(len(t), bool)
    base, _ = adapt.prequential(t, prep, rows, pop, pol, [30])
    i = int(np.where((t["patient_id"] == "p") & (t["origin"] == 300.0))[0][0])
    p = prep["p"]
    p.g_val[p.g_obs > 300] += 500.0                       # the future changes
    late = (p.g_obs > 250) & (p.g_obs <= 300)
    p.g_avail[late] = 400.0                               # observed before 300 but released afterwards
    new, _ = adapt.prequential(t, prep, rows, pop, pol, [30])
    prep2, t2, pol2, pop2 = _prep_and_table()
    prep2["p"].g_val[prep2["p"].g_obs > 300] += 500.0     # ... but a pure future change never alters it
    fut, _ = adapt.prequential(t2, prep2, rows, pop2, pol2, [30])
    assert np.array_equal(fut[30][: i + 1], base[30][: i + 1])
    # a reading released after the origin cannot have matured by then: the late-release correction equals the one
    # computed from readings that are simply absent
    prep3, t3, pol3, pop3 = _prep_and_table()
    keep = ~late
    for k in ("g_obs", "g_val", "g_avail"):
        setattr(prep3["p"], k, getattr(prep3["p"], k)[keep])
    absent, _ = adapt.prequential(t3, prep3, rows, pop3, pol3, [30])
    assert new[30][i] == pytest.approx(absent[30][i])


def test_another_persons_data_never_changes_this_persons_correction():
    prep, t, pol, pop = _prep_and_table()
    rows = np.ones(len(t), bool)
    base, _ = adapt.prequential(t, prep, rows, pop, pol, [30])
    prep["q"].g_val[:] -= 40.0                             # q's residuals move away from the 25 mg/dL cap
    pop2 = {30: np.where(t["patient_id"] == "q", 105.0, 100.0)}
    new, _ = adapt.prequential(t, prep, rows, pop2, pol, [30])
    p = (t["patient_id"] == "p").to_numpy()
    assert np.array_equal(new[30][p], base[30][p])
    assert not np.array_equal(new[30][~p], base[30][~p])


# ----------------------------------------------------------------------------------------------- selection


def _cand(config, mae, features="F0", weights="W1", objective="l2", template_index=0, k=None, hl=None, feasible=True):
    return {"config": config, "mae": mae, "features": features, "weights": weights, "objective": objective,
            "template_index": template_index, "k": k, "half_life": hl, "feasible": feasible, "family": "lightgbm"}


def test_retained_winner_is_the_recorded_object_and_ties_go_to_the_simpler_setting():
    a = _cand("A", 20.000, features="F1")
    b = _cand("B", 20.004, features="F0")                 # within 0.005 of A and simpler -> preferred
    c = _cand("C", 19.900, weights="WP")                  # clearly lower
    d = _cand("D", 18.0, feasible=False)                  # infeasible never retained
    out = C.retain([a, b, c, d], 3)
    assert [x["config"] for x in out] == ["C", "B", "A"]
    assert out[0] is c and out[1] is b
    # one policy per configuration: the best feasible policy of that configuration
    p1 = _cand("E", 19.0, k=24, hl=120)
    p2 = _cand("E", 19.003)                               # tie within 0.005: correction off is simpler
    assert C.retain([p1, p2], 3) == [p2]
    # exact tie between configurations: deterministic simplicity order, independent of input order
    x, y = _cand("X", 21.0, objective="l1"), _cand("Y", 21.0, objective="l2")
    assert C.retain([x, y], 1)[0] is y and C.retain([y, x], 1)[0] is y


def test_no_feasible_candidate_returns_no_pairs_and_the_fold_falls_back_to_r0():
    assert C.retain([_cand("A", 1.0, feasible=False)]) == []
    assert C.make_pairs([], [], {"r0": True}) == []
    assert C.select_pair([]) is None
    r0_30 = {"r0": True, "id": "R0_30"}
    pairs = C.make_pairs([], [_cand("A", 1.0)], r0_30)
    assert pairs == [(r0_30, pairs[0][1])]
    assert len(C.make_pairs([_cand(str(i), 1.0) for i in range(3)], [_cand(str(i), 1.0) for i in range(3)], r0_30)) == 9


def test_inner_filters_apply_the_gain_and_high_target_limits_at_their_boundaries():
    r0 = {"mae": 22.0, "high": 40.0, "avail": 1.0}
    ok, _ = C.check_feasible({"mae": 21.5, "high": 41.0, "avail": 1.0}, r0, 60)       # exactly 0.5 gain, +1.0 high
    assert ok
    assert not C.check_feasible({"mae": 21.51, "high": 40.0, "avail": 1.0}, r0, 60)[0]  # gain 0.49
    assert not C.check_feasible({"mae": 21.0, "high": 41.01, "avail": 1.0}, r0, 60)[0]  # high +1.01
    assert C.check_feasible({"mae": 22.25, "high": 40.0, "avail": 1.0}, r0, 30)[0]      # 30 min: +0.25 allowed
    assert not C.check_feasible({"mae": 22.26, "high": 40.0, "avail": 1.0}, r0, 30)[0]
    assert not C.check_feasible({"mae": 21.0, "high": None, "avail": 1.0}, r0, 60)[0]   # undefined never passes


def test_high_support_mask_comes_from_targets_only_with_a_declared_fallback():
    pids = np.array(["a"] * 60 + ["b"] * 60 + ["c"] * 30)
    y = np.r_[np.full(60, 200.0), np.full(60, 200.0), np.full(30, 200.0)]
    m, used = C.high_support(y, pids, np.ones(len(y), bool))
    assert used == 50 and set(pids[m]) == {"a", "b"}
    pids2 = np.array(["a"] * 60 + ["c"] * 30)
    m2, used2 = C.high_support(np.full(90, 200.0), pids2, np.ones(90, bool))
    assert used2 == 20 and set(pids2[m2]) == {"a", "c"}


def test_macro_mae_weights_people_equally_and_differs_from_pooled():
    pids = np.array(["a"] * 9 + ["b"])
    y = np.zeros(10)
    pred = np.r_[np.ones(9), np.full(1, 11.0)]            # a: 1, b: 11
    m = np.ones(10, bool)
    assert C.macro_mae(pred, y, pids, m) == pytest.approx(6.0)
    assert C.pooled_mae(pred, y, m) == pytest.approx(2.0)
    assert C.macro_mae(np.full(10, np.nan), y, pids, m) is None


# ----------------------------------------------------------------------------------------------- gates


def test_point_gate_boundaries():
    assert C.point_gate(-0.5, [-1.0, -0.01], 0.25, 1.0, 0.5)["passed"]
    assert not C.point_gate(-0.49, [-1.0, -0.01], 0.0, 0.0, 0.0)["passed"]
    assert not C.point_gate(-0.8, [-1.0, 0.0], 0.0, 0.0, 0.0)["passed"]           # interval touching zero
    assert not C.point_gate(-0.8, [-1.0, -0.1], 0.26, 0.0, 0.0)["passed"]
    assert not C.point_gate(-0.8, [-1.0, -0.1], 0.0, 1.01, 0.0)["passed"]
    assert not C.point_gate(-0.8, [-1.0, -0.1], 0.0, 0.0, 0.51)["passed"]
    assert not C.point_gate(-0.8, [-1.0, -0.1], 0.0, None, 0.0)["passed"]          # undefined fails
    # sign convention: candidate minus R0 (negative = candidate better)
    assert C.point_gate(-0.8, [-1.0, -0.1], -0.3, -2.0, -1.0)["passed"]


def test_operational_gate_boundaries_and_undefined_cases():
    r = {"fa_day": 1.2, "tiw": 0.05, "share30": 0.20, "onsets": 100, "nonempty": True}
    at = {"fa_day": 1.3, "tiw": 0.07, "share30": 0.18, "onsets": 100, "nonempty": True}
    assert C.operational_gate(at, r)["passed"]
    assert not C.operational_gate({**at, "fa_day": 1.3001}, r)["passed"]
    assert not C.operational_gate({**at, "tiw": 0.0701}, r)["passed"]
    assert not C.operational_gate({**at, "share30": 0.1799}, r)["passed"]
    assert not C.operational_gate({**at, "share30": None}, r)["passed"]
    assert not C.operational_gate(at, {**r, "onsets": 0})["passed"]
    assert not C.operational_gate({**at, "nonempty": False}, r)["passed"]
    assert not C.operational_gate(None, r)["passed"]


def test_range_gate_boundaries():
    def side(cov, pmin, width, rc, n=300, people=4):
        return {"coverage": cov, "per_person_min": pmin, "width_mean": width, "rapid": {"coverage": rc, "n": n, "people": people}}
    r0 = {"identity_ok": True, "finite_ok": True, "30": side(0.8, 0.6, 40.0, 0.5), "60": side(0.8, 0.6, 60.0, 0.5)}
    ok = {"identity_ok": True, "finite_ok": True, "30": side(0.75, 0.55, 46.0, 0.45), "60": side(0.85, 0.55, 69.0, 0.45)}
    assert C.range_gate(ok, r0)["passed"]
    assert not C.range_gate({**ok, "identity_ok": False}, r0)["passed"]
    assert not C.range_gate({**ok, "60": side(0.7499, 0.6, 60.0, 0.5)}, r0)["passed"]
    assert not C.range_gate({**ok, "60": side(0.8, 0.6, 69.1, 0.5)}, r0)["passed"]      # widening beyond 1.15x
    assert not C.range_gate({**ok, "60": side(0.8, 0.6, 60.0, 0.4499)}, r0)["passed"]
    assert not C.range_gate({**ok, "60": side(0.8, 0.6, 60.0, 0.6, n=100)}, r0)["passed"]  # unsupported stratum


# ----------------------------------------------------------------------------------------------- calibration identity


def test_calibration_rejects_a_dev_plus_calibration_refit_applied_to_a_dev_only_calibration():
    """Regression test for D-052's mixed-fit range: quantiles from a development-only fit must not be applied to a
    model refitted on development + calibration people."""
    pids, o, X, g, y_abs = _data(n_people=6)
    dev = np.isin(pids, ["p0", "p1", "p2", "p3"])
    cal = pids == "p4"
    ass = pids == "p5"
    fp_dev, _ = C.fit_tree(_cfg(), X, y_abs - g, y_abs, pids, o, dev, 1, ["a", "b", "c"], rounds=20)
    ident = fp_dev.identity("pol", "feat")
    res = np.abs(y_abs[cal] - (g[cal] + fp_dev.predict_delta(X[cal])))
    rec = C.calibrate(res, ident)
    fin = g + fp_dev.predict_delta(X)
    b = C.bands(np.where(ass, fin, np.nan), rec, fp_dev.identity("pol", "feat"))   # same frozen predictor: accepted
    assert np.all(b["lower"][ass] <= fin[ass]) and np.all(fin[ass] <= b["upper"][ass])
    fp_mix, _ = C.fit_tree(_cfg(), X, y_abs - g, y_abs, pids, o, dev | cal, 1, ["a", "b", "c"], rounds=20)
    with pytest.raises(CalibrationError):
        C.bands(fin, rec, fp_mix.identity("pol", "feat"))
    with pytest.raises(CalibrationError):                  # same model, different correction policy
        C.bands(fin, rec, fp_dev.identity("other-pol", "feat"))
    with pytest.raises(CalibrationError):                  # same model, different feature transform
        C.bands(fin, rec, fp_dev.identity("pol", "other-feat"))


def test_conformal_quantile_rank_and_insufficient_calibration():
    ident = {"x": 1}
    rec = C.calibrate(np.arange(1, 101, dtype=float), ident)
    assert rec["n"] == 100 and rec["rank"] == 81 and rec["global_q"] == 81.0      # ceil(101 * 0.8) = 81
    small = C.calibrate(np.arange(1, 50, dtype=float), ident)
    assert small["global_q"] is None
    b = C.bands(np.array([100.0, 120.0]), small, ident)
    assert np.all(np.isnan(b["lower"])) and np.all(np.isnan(b["upper"]))          # unavailable, not imputed


def test_trend_scales_are_learned_from_development_residuals_only_and_bounded():
    rng = np.random.default_rng(1)
    n = 2000
    slope = rng.choice([-2.0, 0.0, 1.5, 3.0], n)
    pids = np.array([f"p{i % 5}" for i in range(n)])
    res = np.where(slope > 2, 30.0, 10.0) + rng.uniform(0, 1, n)
    s = C.trend_scale(res, slope, pids)
    assert s["rapid"] > s["steady"] and C.SCALE_CLIP[0] <= min(s.values()) and max(s.values()) <= C.SCALE_CLIP[1]
    few = C.trend_scale(res[:100], slope[:100], pids[:100])
    assert all(v == 1.0 for v in few.values())                                   # unsupported bins fall back to 1
    # the calibration quantile uses those frozen scales; calibration residuals never change the scales
    cal_res = rng.uniform(0, 50, 500)
    cal_slope = rng.choice([-2.0, 0.0, 3.0], 500)
    r1 = C.calibrate(cal_res, {"i": 1}, C.scale_of(cal_slope, s))
    r2 = C.calibrate(cal_res * 3, {"i": 1}, C.scale_of(cal_slope, s))
    assert r2["scaled_q"] == pytest.approx(3 * r1["scaled_q"])
    assert C.scale_of(np.array([np.nan]), s)[0] == 1.0


# ----------------------------------------------------------------------------------------------- warning accounting


def _warn_table(n=288, onset=600.0, censor_after=None, gap_after=None):
    """One person, 5-minute origins; a new high starts at ``onset``; labels 1 within the 60 min before it."""
    o = np.arange(n) * 5.0
    if gap_after is not None:
        o = np.where(o > gap_after, o + 600.0, o)          # a 10-hour sensor gap
    lab = np.where((o >= onset - 60) & (o < onset), 1.0, 0.0)
    elig = ~((o >= onset) & (o < onset + 120))             # already high: suppressed (not eligible)
    lab = np.where(elig, lab, np.nan)
    if censor_after is not None:
        lab = np.where(o > censor_after, np.nan, lab)
    on = np.where(lab == 1, onset, np.nan)
    return pd.DataFrame({"patient_id": "p", "origin": o, "ew_eligible": elig, "label_60": lab, "onset_60": on})


def _final(t, fire_mask):
    v = np.where(fire_mask, 200.0, 120.0)
    return {30: v, 60: v}


def test_successful_and_false_warnings_and_all_onset_notice():
    t = _warn_table()
    o = t["origin"].to_numpy()
    rows = np.ones(len(t), bool)
    fire = ((o >= 550) & (o < 600)) | ((o >= 100) & (o <= 110))
    w = C.warn_metrics(t, rows, rows, _final(t, fire), 0.0)
    assert w["onsets"] == 1 and w["detected"] == 1 and w["missed"] == 0
    assert w["false_alarms"] == 1 and w["episodes"] == 2
    assert w["ge30"] == 1 and w["share30"] == 1.0 and w["ge60"] == 0
    # a missed onset counts against the all-onset share
    w2 = C.warn_metrics(t, rows, rows, _final(t, (o >= 100) & (o <= 110)), 0.0)
    assert w2["detected"] == 0 and w2["share30"] == 0.0 and w2["share15"] == 0.0


def test_censored_warning_is_unresolved_not_a_false_alarm_and_no_policy_has_zero_recall():
    t = _warn_table(censor_after=900.0)
    o = t["origin"].to_numpy()
    rows = np.ones(len(t), bool)
    w = C.warn_metrics(t, rows, rows, _final(t, (o >= 1000) & (o <= 1010)), 0.0)
    assert w["false_alarms"] == 0 and w["censored"] == 1 and w["assessable"] == 0 and not w["nonempty"]
    none = C.warn_metrics(t, rows, rows, _final(t, o >= 0), None)
    assert none["episodes"] == 0 and none["detected"] == 0 and none["share30"] == 0.0 and none["tiw"] == 0.0


def test_near_continuous_warning_shows_its_time_in_warning_even_with_few_alarms():
    t = _warn_table()
    o = t["origin"].to_numpy()
    rows = np.ones(len(t), bool)
    w = C.warn_metrics(t, rows, rows, _final(t, o >= 0), 0.0)
    assert w["episodes"] <= 2                              # merging makes the count look small ...
    assert w["tiw"] > 0.95                                 # ... but the warning is on almost all the time
    assert C.choose_threshold([w]) is None                 # and the 12 % ceiling rejects it


def test_exposure_respects_gaps_and_false_alarm_rate_uses_it():
    o = np.array([0.0, 5.0, 10.0, 1000.0, 1005.0])
    p = np.array(["a"] * 5)
    step = C.exposure_steps(o, p, np.ones(5, bool))
    assert step.sum() == pytest.approx(25.0)               # not 1005 minutes
    t = _warn_table(gap_after=300.0)
    rows = np.ones(len(t), bool)
    oo = t["origin"].to_numpy()
    w = C.warn_metrics(t, rows, rows, _final(t, (oo >= 100) & (oo <= 110)), 0.0)
    assert w["observed_days"] == pytest.approx(len(t) * 5.0 / 1440.0)
    assert w["fa_day"] == pytest.approx(1 / (len(t) * 5.0 / 1440.0))


def test_threshold_rule_respects_absolute_and_relative_limits():
    def row(th, s30, fa, tiw, nonempty=True, onsets=10):
        return {"threshold": th, "share30": s30, "fa_day": fa, "tiw": tiw, "nonempty": nonempty, "onsets": onsets}
    curve = [row(-30, 0.60, 2.0, 0.20), row(-10, 0.40, 1.5, 0.12), row(0, 0.40, 1.0, 0.08), row(10, 0.2, 0.5, 0.04)]
    assert C.choose_threshold(curve)["threshold"] == 0                # tie on share30 -> fewer false alarms
    assert C.choose_threshold(curve, fa_max=0.6)["threshold"] == 10
    ref = {"fa_day": 0.5, "tiw": 0.04, "share30": 0.2}
    assert C.choose_threshold(curve, ref=ref)["threshold"] == 10      # +0.10/day and +2 pt limits bind
    assert C.choose_threshold([row(0, 0.5, 0.1, 0.01, nonempty=False)]) is None


def test_pair_selection_prefers_notice_then_burden_then_error():
    def item(s30, fa, tiw, mae60, fam="lightgbm"):
        return {"warn": {"share30": s30, "fa_day": fa, "tiw": tiw}, "mae60": mae60, "mae30": 14.0, "family": fam,
                "key60": (0,), "key30": (0,), "name": f"{s30}-{fa}-{mae60}-{fam}"}
    a, b, c = item(0.300, 1.2, 0.06, 21.0), item(0.295, 1.0, 0.05, 21.5), item(0.25, 0.5, 0.02, 20.0)
    assert C.select_pair([a, b, c]) is b                   # within 1 pt of the best notice, fewer false alarms
    d, e = item(0.30, 1.0, 0.05, 21.0, "catboost"), item(0.30, 1.0, 0.05, 21.0)
    assert C.select_pair([d, e]) is e                       # exact tie: LightGBM first


# ----------------------------------------------------------------------------------------------- run control


def test_resume_refuses_when_protocol_or_code_hashes_differ(tmp_path, monkeypatch):
    if not (ROOT / "artifacts/research/gt-2h-2026-10-20/splits.json").exists():
        pytest.skip("frozen base split not available")
    monkeypatch.setattr(C, "OUT", tmp_path)
    monkeypatch.setattr(C, "LOG", tmp_path / "progress.log")
    h = C.hashes()
    (tmp_path / "run_manifest.json").write_text(json.dumps({"hashes": {**h, "code_sha256": "different"}}))
    with pytest.raises(SystemExit, match="Refusing to resume"):
        C.run(resume=True)
    with pytest.raises(SystemExit, match="already exists"):
        C.run(resume=False)


def test_portfolio_is_the_declared_size_and_order():
    rec = {h: {"params": {"learning_rate": 0.02, "num_leaves": 8, "max_depth": 3, "min_child_samples": 100,
                          "lambda_l2": 1.0, "feature_fraction": 0.7, "bagging_fraction": 0.7}, "rounds": 100} for h in (30, 60)}
    lg = C.lgb_configs(rec, 60)
    assert len(lg) == 32 and len({c["id"] for c in lg}) == 32
    assert [c["objective"] for c in lg[:2]] == ["l2", "l1"] and lg[0]["template"] == "T0"
    assert len(C.cb_configs()) == 16
    assert C.min_leaf(0.25, 16000, 6) == 667


# ----------------------------------------------------------------------------------------------- audit follow-ups (pre-fit)


def _need_base():
    if not (ROOT / "artifacts/research/gt-2h-2026-10-20/splits.json").exists():
        pytest.skip("frozen base split not available")


def _stub(n_people=6, n=120):
    pids, o, X, g, y_abs = _data(n_people, n)
    st = object.__new__(C.Constrained)
    st.pids, st.o, st.g = pids, o, g
    st.issued = np.ones(len(pids), bool)
    st.y = {30: y_abs, 60: y_abs}
    st.Xn = {"F0": X}
    st.cols = {"F0": ["a", "b", "c"]}
    st.fit_log, st.failures, st.ledger, st.segment = [], [], None, "test"
    st.t = pd.DataFrame({"patient_id": pids, "origin": o})
    plan = SimpleNamespace(fold="stub", development=tuple(f"p{i}" for i in range(n_people)), calibration=(),
                           assessment=(), inner=(("p0", "p1"), ("p2", "p3"), ("p4", "p5")))
    return st, plan


def test_every_fit_attempt_reaches_the_on_disk_ledger_immediately(tmp_path):
    st, plan = _stub()
    st.ledger = tmp_path / "fits.jsonl"
    st.fit(_cfg(), 30, ["p0", "p1", "p2"], plan, "inner-1")                  # early-stopped: 2 physical fits
    st.fit(_cfg(), 30, ["p0", "p1", "p2"], plan, "outer", rounds=5)          # fixed rounds: 1 physical fit
    rows = [json.loads(x) for x in st.ledger.read_text().splitlines()]
    assert [r["physical_fits"] for r in rows] == [2, 1] and all(r["segment"] == "test" for r in rows)


def test_a_failed_or_partial_r0_control_aborts_the_fold_instead_of_qualifying_candidates():
    st, plan = _stub()
    st.r0_cfg = lambda h: {"id": f"R0-{h}", "r0": True}
    st.inner_oof = lambda cfg, h, plan: (np.full(len(st.pids), np.nan), [], True)
    with pytest.raises(RuntimeError, match="R0 inner fit failed"):
        st.develop_fold(plan)
    part = np.where(st.pids == "p0", np.nan, 150.0)                          # one person missing, no failure flag
    st.inner_oof = lambda cfg, h, plan: (part, [10], False)
    with pytest.raises(RuntimeError, match="partial"):
        st.develop_fold(plan)
    ok, why = C.check_feasible({"mae": 1.0, "high": 1.0, "avail": 1.0}, {"mae": 30.0, "high": 30.0, "avail": 0.8,
                                                                         "failed": True}, 60)
    assert not ok and "control R0 failed in this fold" in why


def test_an_outer_fit_failure_of_the_selected_member_falls_back_to_r0_for_both_horizons(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path)
    monkeypatch.setattr(C, "LOG", tmp_path / "progress.log")
    st, plan = _stub()
    st.rec = {30: {"rounds": 5}, 60: {"rounds": 5}}
    r0 = {h: {**_cfg(cid=f"R0-{h}"), "r0": True} for h in (30, 60)}
    cand = {h: _cfg(cid=f"cand-{h}") for h in (30, 60)}
    st.member_cfg = lambda mid, h: (r0[h], 96, 240) if mid.startswith("R0") else (cand[h], None, None)
    real_fit = C.Constrained.fit

    def fit(self, cfg, h, people, plan_, scope, rounds=None):
        if cfg["id"] == "cand-60":
            return None, {"error": "boom", "config": cfg["id"]}
        return real_fit(self, cfg, h, people, plan_, scope, rounds)
    st.fit = fit.__get__(st)
    ddoc = {"selected": {"m30": "cand|off|30", "m60": "cand|off|60"},
            "best_iterations": {"cand-30|30": [4, 5, 6], "cand-60|60": [4, 5, 6]}}
    members, fitted, failed = st.fit_members(plan, ddoc)
    assert failed["error"] == "boom" and members["S"] == {30: "R0_30", 60: "R0_60"}
    assert fitted[("cand-30", 30)].rounds == 5                                 # median of the inner best iterations


def test_resume_refuses_a_development_fold_changed_after_publication(tmp_path, monkeypatch):
    _need_base()
    monkeypatch.setattr(C, "OUT", tmp_path)
    monkeypatch.setattr(C, "LOG", tmp_path / "progress.log")
    (tmp_path / "run_manifest.json").write_text(json.dumps({"hashes": C.hashes(), "started_at": "x"}))
    C.publish_fold(tmp_path / "development", "outer-1", {"selected": {"m60": "a"}}, {"x": np.arange(3.0)})
    assert C.fold_state(tmp_path / "development", "outer-1") == "complete"
    (tmp_path / "development" / "outer-1.json").write_text(json.dumps({"selected": {"m60": "b"}}))
    with pytest.raises(RuntimeError, match="checksum"):
        C.fold_state(tmp_path / "development", "outer-1")
    with pytest.raises(SystemExit, match="Refusing to resume"):
        C.run(resume=True)
    (tmp_path / "development" / "outer-1.json").unlink()
    with pytest.raises(RuntimeError, match="missing"):
        C.fold_state(tmp_path / "development", "outer-1")
    # an interrupted publication (no sidecar yet) is not a published fold
    C._save_arrays(tmp_path / "development" / "outer-2.npz", {"x": np.arange(2.0)})
    assert C.fold_state(tmp_path / "development", "outer-2") == "absent"


def test_validate_distinguishes_incomplete_from_complete_and_invalid(tmp_path, monkeypatch, capsys):
    _need_base()
    monkeypatch.setattr(C, "OUT", tmp_path)
    monkeypatch.setattr(C, "REPORT", tmp_path / "r.md")
    h = C.hashes()
    (tmp_path / "run_manifest.json").write_text(json.dumps({"hashes": h}))
    assert C.validate() == 2 and json.loads(capsys.readouterr().out)["status"] == "intact-incomplete"
    assert C.validate(checkpoint=True) == 0
    (tmp_path / "assessment_opened.json").write_text(json.dumps({"opened_at": "z", "hashes": h}))
    assert C.validate(checkpoint=True) == 1                                     # lock without frozen development
    (tmp_path / "assessment_opened.json").unlink()
    (tmp_path / "run_manifest.json").write_text(json.dumps({"hashes": {**h, "inputs_sha256": "other"}}))
    assert C.validate(checkpoint=True) == 1                                     # data/recipe changed


def test_fingerprints_cover_the_recipe_table_bytes_and_base_protocol():
    _need_base()
    names = {p.name for p in C.input_paths()}
    assert {"manifest.json", "multimodal_5min__cgmacros.parquet", "splits.json", "gt-2h-2026-10-20.yaml"} <= names
    assert {"inputs_sha256", "recipe_fingerprint", "code_sha256", "protocol_sha256"} <= set(C.hashes())


def test_final_package_round_trip_checksum_and_calibration_identity(tmp_path):
    pids, o, X, g, y_abs = _data()
    dev = np.isin(pids, ["p0", "p1", "p2", "p3"])
    cal = pids == "p4"
    fp, _ = C.fit_tree(_cfg(), X, y_abs - g, y_abs, pids, o, dev, 1, ["a", "b", "c"], rounds=20)
    ident = fp.identity("pol", "feat")
    rec = C.calibrate(np.abs(y_abs[cal] - (g[cal] + fp.predict_delta(X[cal]))), ident)
    entry = {"fp": fp, "policy": {"k": 96}, "columns": ["a", "b", "c"], "calibration": rec, "scales": {}}
    C.write_package(tmp_path / "pkg", {30: entry}, {"experiment_id": "t"})
    loaded = C.load_package(tmp_path / "pkg")
    model, e = loaded[30]
    assert np.allclose(model.predict(X[:20]), fp.predict_delta(X[:20]))
    with pytest.raises(FileExistsError):
        C.write_package(tmp_path / "pkg", {30: entry}, {})
    # a calibration made for another fit (e.g. development + calibration refit) is refused at load time
    fp2, _ = C.fit_tree(_cfg(), X, y_abs - g, y_abs, pids, o, dev | cal, 1, ["a", "b", "c"], rounds=20)
    C.write_package(tmp_path / "mixed", {30: {**entry, "fp": fp2}}, {})
    with pytest.raises(CalibrationError):
        C.load_package(tmp_path / "mixed")
    f = tmp_path / "pkg" / "model_30.txt"
    f.write_text(f.read_text() + "\n# tampered\n")
    with pytest.raises(ValueError, match="checksum"):
        C.load_package(tmp_path / "pkg")
