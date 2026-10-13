"""Information cutoff, native-cadence recovery, split purging and adaptation maturity."""

import numpy as np
import pandas as pd
from glucotwin.data.cgmacros import recover_native
from glucotwin.data.synthetic import SCENARIOS, generate
from glucotwin.features import FEATURE_SETS, build_features, prepare, profile_unavailable
from glucotwin.models.adaptation import AdaptationPolicy, AdaptationState
from glucotwin.splits import SplitConfig, assign_segments, boundaries_for

SPEC = FEATURE_SETS["dyn-prof-meal-v2"]


def _patient(pid="SYN-A"):
    return generate(next(s for s in SCENARIOS if s.patient_id == pid))


def test_future_values_cannot_change_earlier_features():
    p = _patient()
    prep = prepare(p)
    origin = prep.g_obs[300]
    before = build_features(prep, np.array([origin]), SPEC).frame
    q = p.glucose.copy()
    q.loc[q["observed_at"] > pd.Timestamp("2000-01-01T00:00Z") + pd.Timedelta(minutes=origin), "value_mg_dl"] = 399.0
    m = p.meals.copy()
    m["carbs_g"] = np.where(m["observed_at"] > pd.Timestamp("2000-01-01T00:00Z") + pd.Timedelta(minutes=origin),
                            500.0, m["carbs_g"])
    p2 = type(p)(p.meta, p.profile, q, p.activity, m)
    after = build_features(prepare(p2), np.array([origin]), SPEC).frame
    pd.testing.assert_frame_equal(before, after)


def test_late_logged_meal_is_hidden_until_available():
    p = _patient("SYN-C")  # meal records become available 90 minutes after the meal
    prep = prepare(p)
    meal_t, meal_avail = prep.m_obs[2], prep.m_avail[2]
    assert meal_avail - meal_t == 90
    without = type(p)(p.meta, p.profile, p.glucose, p.activity, p.meals.drop(p.meals.index[2]))
    prep_wo = prepare(without)
    for dt, should_differ in ((1, False), (30, False), (89, False), (95, True)):
        o = np.array([meal_t + dt])
        a = build_features(prep, o, SPEC).frame
        b = build_features(prep_wo, o, SPEC).frame
        assert (not a.equals(b)) == should_differ, f"meal visibility wrong at +{dt} min"


def test_unavailable_or_missing_lab_values_stay_missing():
    p = _patient()
    for a in p.profile:
        if a["name"] == "hba1c":
            a["available_at"] = "2000-01-05T00:00:00+00:00"  # result arrives two days into the record
    prep = prepare(p)
    spec = FEATURE_SETS["dyn-prof-v2"]
    early = build_features(prep, np.array([prep.g_obs[100]]), spec).frame.iloc[0]
    late = build_features(prep, np.array([prep.g_obs[-1]]), spec).frame.iloc[0]
    assert np.isnan(early["p_hba1c"]) and np.isfinite(late["p_hba1c"])
    assert np.isnan(late["p_fasting_insulin"])  # missing in source -> NaN, never 0


def test_profile_model_is_gated_until_every_profile_value_is_available():
    p = _patient()  # SYN-A: fasting insulin missing in source; the other values arrive on day 2
    prep = prepare(p)
    prof_spec, dyn_spec = FEATURE_SETS["dyn-prof-v2"], FEATURE_SETS["dyn-v2"]
    early, late = prep.g_obs[100], prep.g_obs[-1]
    assert profile_unavailable(prep, np.array([early, late]), prof_spec).all()  # a value missing in source
    assert not profile_unavailable(prep, np.array([early, late]), dyn_spec).any()  # dynamic model never gated

    for a in p.profile:
        if a["name"] == "fasting_insulin":
            a.update(value=9.0, available_at="2000-01-03T00:00:00+00:00", status="available")
        if a["name"] == "hba1c":
            a["available_at"] = "2000-01-05T00:00:00+00:00"  # result arrives later in the record
    prep = prepare(p)
    assert profile_unavailable(prep, np.array([early, late]), prof_spec).tolist() == [True, False]
    # the gate is a serving rule; offline feature quality is unchanged by it
    assert "profile_unavailable" not in build_features(prep, np.array([early]), prof_spec).reasons[0]


def test_one_minute_interpolated_rows_do_not_inflate_observations():
    native = np.array([100, 106, 106, 106, 120, 118, 130, 131], dtype=float)
    minute = np.interp(np.arange(0, 36), np.arange(0, 40, 5), native)
    rows, flags, stats = recover_native(minute, 5)
    assert rows.tolist() == [0, 5, 10, 15, 20, 25, 30, 35]
    assert np.allclose(minute[rows], native)
    assert stats["collinear_recovered"] >= 1  # 106,106,106 are collinear hidden knots
    # a non-integer midpoint is never accepted as a native reading
    bridged = np.interp(np.arange(0, 11), [0, 10], [100, 107])
    r2, _, s2 = recover_native(bridged, 5)
    assert r2.tolist() == [0, 10] and s2["collinear_non_integer"] == 1


def test_split_purging_keeps_label_support_inside_segments():
    t = np.arange(0, 10 * 1440, 5, dtype=float)
    cfg = SplitConfig()
    b = boundaries_for(t, cfg)
    seg, purged = assign_segments(t, b, cfg)
    bounds = b.segment_bounds()
    for name, (lo, hi) in bounds.items():
        sel = seg == name
        assert (t[sel] + cfg.purge_minutes < hi).all()
        assert (t[sel] >= lo).all()
    assert purged.sum() > 0
    assert b.train_end < b.select_end < b.val_end < b.end


def test_sixty_minute_residual_matures_only_when_target_is_available():
    pol = AdaptationPolicy(min_residuals=1, shrinkage_k=0.0, half_life_minutes=1e9)
    st = AdaptationState(pol, [60])
    obs = np.arange(0, 200, 5, dtype=float)
    val = np.full(obs.size, 150.0)
    avail = obs.copy()
    avail[obs == 60] = 100.0  # the 60-minute target reading arrives late (at t=100)
    st.step(0.0, obs, val, avail, {60: 140.0}, "f0")  # population forecast for t=60 is 10 mg/dL low
    for t in obs[1:]:
        c = st.step(float(t), obs, val, avail, {60: None}, f"f{t}")
        if t <= 95:
            assert c[60] == 0.0, f"residual used before its target was available (t={t})"
    assert st.h[60].n == 1 and abs(c[60] - 10.0) < 1e-9


def test_corrections_never_stack_on_corrected_predictions():
    pol = AdaptationPolicy(min_residuals=1, shrinkage_k=0.0, half_life_minutes=1e9, cap_mg_dl=100)
    st = AdaptationState(pol, [30])
    obs = np.arange(0, 400, 5, dtype=float)
    val = np.full(obs.size, 150.0)
    out = None
    for t in obs:
        out = st.step(float(t), obs, val, obs, {30: 140.0}, f"f{t}")  # population always 10 low
    # residuals are measured against the frozen population forecast, so the correction converges to +10, not +20
    assert abs(out[30] - 10.0) < 1e-9


def test_fusion_constraint_carries_its_disclosures():
    """A serving model chosen under an eligibility constraint is always reported with the constraint's timing, the
    absence of evidence for unseen patients and the reason it was chosen; unconstrained experiments carry none."""
    from glucotwin.evaluation.report import selection_disclosures

    assert selection_disclosures({"experiment_id": "x", "selection": {"eligible_feature_sets": None}}) == []
    m = {"experiment_id": "gt-primary-2026-10-13-fusion", "corrects_experiment_id": "gt-primary-2026-10-11-v1",
         "selection": {"eligible_feature_sets": ["dyn-prof-v2"], "selected_label": "lightgbm:dyn-prof-v2",
                       "serving_personalization": "adaptive"},
         "cohort": {"participants": 14}, "events": [], "alert_threshold_selection": {}}
    d = selection_disclosures(m)
    text = " ".join(d)
    assert len(d) >= 4
    assert "declared on 2026-10-13 after the test segment had already been inspected" in d[0]
    assert "gt-primary-2026-10-11-v2" in d[0]  # derived_from, read from the protocol file
    assert "participant identifier" in text
    assert "have not established that profile features improve forecasting for unseen patients" in text
