"""Regression tests for the Prompt 05 corrections (reports/repair_report.md).

1. Activity windows count only the part of each 5-minute summary inside the lookback window (feature sets *-v2).
2. Online warning outcomes use the same one-to-one matcher as the offline evaluation.
3. Qualified forecast lead never exceeds its own horizon; the v1 episode-start duration is kept separately.
4. Model artifacts carry a transformation fingerprint; mismatched semantics are refused.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from glucotwin.data.store import EPOCH, PatientData
from glucotwin.data.synthetic import SCENARIOS, generate
from glucotwin.evaluation.alerts import evaluate_patient, match_episodes, qualified_lead, summarize
from glucotwin.events import EventDefinition, Onset
from glucotwin.features import FEATURE_SETS, build_features, prepare
from glucotwin.models.population import ArtifactError, PopulationBundle, RidgeModel
from glucotwin.twin import AlertRecord, TwinEngine

V1, V2 = FEATURE_SETS["dyn-v1"], FEATURE_SETS["dyn-v2"]
T0 = EPOCH  # feature/engine times are minutes since the store epoch


def _activity_patient(ends: list[float], *, kcal: float = 10.0, mets: float = 1.5, avail_delay: float = 0.0,
                      covered: int = 5) -> PatientData:
    """Glucose every 5 min for 3 h plus 5-minute activity summaries ending at ``ends`` (minutes)."""
    g_t = np.arange(0, 181, 5.0)
    glucose = pd.DataFrame({
        "event_id": [f"g{i}" for i in range(g_t.size)], "observed_at": T0 + pd.to_timedelta(g_t, unit="min"),
        "available_at": T0 + pd.to_timedelta(g_t, unit="min"), "value_mg_dl": 120.0, "quality": "ok", "flags": "",
        "source": "test"})
    e = np.asarray(ends, dtype=float)
    activity = pd.DataFrame({
        "event_id": [f"a{i}" for i in range(e.size)], "observed_at": T0 + pd.to_timedelta(e, unit="min"),
        "available_at": T0 + pd.to_timedelta(e + avail_delay, unit="min"), "window_minutes": 5,
        "minutes_covered": covered, "heart_rate_bpm": 80.0, "mets": mets, "activity_kcal": kcal, "quality": "ok",
        "flags": "", "source": "test"})
    meals = pd.DataFrame(columns=["event_id", "observed_at", "available_at", "carbs_g", "energy_kcal", "protein_g",
                                  "fat_g", "fiber_g"])
    return PatientData({"patient_id": "T", "display_alias": "T"}, [], glucose, activity, meals)


def _row(p: PatientData, t: float, spec=V2) -> pd.Series:
    return build_features(prepare(p), np.array([t]), spec).frame.iloc[0]


# ------------------------------------------------------------------------------------------------ 1. activity windows


def test_twelve_contiguous_blocks_cover_exactly_sixty_minutes_and_the_boundary_block_adds_nothing():
    t = 120.0
    twelve = [t - 55 + 5 * k for k in range(12)]  # (60,65] ... (115,120]
    assert _row(_activity_patient(twelve), t)["act_cov_60"] == pytest.approx(1.0)
    with_boundary = [t - 60, *twelve]  # summary (55, 60] ends exactly at t - 60: outside (t - 60, t]
    r2 = _row(_activity_patient(with_boundary), t)
    assert r2["act_cov_60"] == pytest.approx(1.0)
    assert r2["kcal_sum_60"] == pytest.approx(120.0)
    # the legacy v1 convention (kept only to reproduce v1) counted 65 minutes here — the defect being fixed
    assert _row(_activity_patient(with_boundary), t, V1)["act_cov_60"] == pytest.approx(65 / 60)


def test_nonaligned_origin_uses_only_the_overlapping_part_of_each_summary():
    t = 122.0  # window (62, 122]
    ends = [5.0 * k for k in range(1, 25)]  # summaries ending 5..120; the one ending 125 is not released yet
    r = _row(_activity_patient(ends), t)
    assert r["act_cov_60"] == pytest.approx(58 / 60)  # (62,65] = 3 min + 11 whole summaries (65..120] = 55 min
    assert r["kcal_sum_60"] == pytest.approx(10 * 3 / 5 + 11 * 10)  # proportional allocation (documented)


def test_missing_and_overlapping_summaries_cannot_inflate_coverage_or_energy():
    t = 120.0
    twelve = [t - 55 + 5 * k for k in range(12)]
    gappy = [e for e in twelve if e not in (80.0, 85.0)]
    r = _row(_activity_patient(gappy), t)
    assert r["act_cov_60"] == pytest.approx(50 / 60)
    dup = _row(_activity_patient(twelve + [100.0, 100.0]), t)  # duplicated summaries are counted once
    assert dup["act_cov_60"] == pytest.approx(1.0) and dup["kcal_sum_60"] == pytest.approx(120.0)
    active = _row(_activity_patient(twelve, mets=4.0), t)
    assert active["active_min_60"] == pytest.approx(60.0)


def test_missing_wearable_data_stays_missing_not_inactive():
    r = _row(_activity_patient([]), 120.0)
    assert r["act_cov_60"] == 0.0
    assert np.isnan(r["hr_mean_60"]) and np.isnan(r["kcal_sum_60"]) and np.isnan(r["active_min_60"])
    no_kcal = _row(_activity_patient([115.0, 120.0], kcal=np.nan), 120.0)
    assert np.isnan(no_kcal["kcal_sum_60"])  # not 0 kcal


def test_a_delayed_summary_has_no_influence_before_it_is_available():
    ends = [100.0, 105.0, 110.0, 115.0]
    late = _activity_patient(ends, avail_delay=30.0)
    assert _row(late, 120.0)["act_cov_60"] == 0.0  # observed, but not yet available at 120
    assert _row(late, 140.0)["act_cov_60"] == pytest.approx(15 / 60)  # the summary ending 115 arrives at 145
    assert _row(late, 145.0)["act_cov_60"] == pytest.approx(20 / 60)


@pytest.mark.parametrize("pid", ["SYN-A", "SYN-D"])
def test_offline_and_online_features_agree(pid):
    """Features from the full recording (filtered per origin) equal features from only the released events."""
    p = generate(next(s for s in SCENARIOS if s.patient_id == pid))
    prep = prepare(p)
    origins = prep.g_avail[200:260:7]
    offline = build_features(prep, origins, V2).frame
    for i, t in enumerate(origins.tolist()):
        t_ts = EPOCH + pd.Timedelta(minutes=t + 1e-6)  # same tolerance as the replay release rule
        rel = PatientData(p.meta, p.profile,
                          p.glucose[p.glucose["available_at"] <= t_ts], p.activity[p.activity["available_at"] <= t_ts],
                          p.meals[p.meals["available_at"] <= t_ts])
        online = build_features(prepare(rel), np.array([t]), V2).frame.iloc[0]
        pd.testing.assert_series_equal(offline.iloc[i], online, check_names=False)
    assert (offline["act_cov_60"] <= 1.0 + 1e-9).all()


# ------------------------------------------------------------------------------------------------ 4. artifacts


def _tiny_bundle(fs: str) -> PopulationBundle:
    cols = FEATURE_SETS[fs].columns()
    X = pd.DataFrame(np.random.default_rng(0).normal(size=(50, len(cols))), columns=cols)
    m = RidgeModel(cols, alpha=1.0).fit(X, np.zeros(50))
    return PopulationBundle("ridge", fs, [30], {30: m}, label=f"ridge:{fs}")


def test_loader_rejects_weights_from_a_different_feature_transformation(tmp_path):
    d = tmp_path / "m"
    _tiny_bundle("dyn-v2").save(d)
    assert PopulationBundle.load(d).feature_set_id == "dyn-v2"
    man = json.loads((d / "manifest.json").read_text())
    man["transform_fingerprint"] = FEATURE_SETS["dyn-v1"].transform_fingerprint()  # same columns, old semantics
    (d / "manifest.json").write_text(json.dumps(man))
    with pytest.raises(ArtifactError, match="transformation"):
        PopulationBundle.load(d)
    del man["transform_fingerprint"]  # a pre-fingerprint (v1-era) artifact claiming the corrected feature set
    (d / "manifest.json").write_text(json.dumps(man))
    with pytest.raises(ArtifactError, match="predates"):
        PopulationBundle.load(d)


def test_pre_fingerprint_v1_artifacts_still_load_with_the_legacy_transformation(tmp_path):
    d = tmp_path / "v1"
    _tiny_bundle("dyn-v1").save(d)
    man = json.loads((d / "manifest.json").read_text())
    del man["transform_fingerprint"]
    (d / "manifest.json").write_text(json.dumps(man))
    assert PopulationBundle.load(d).feature_set_id == "dyn-v1"
    assert V1.columns() == V2.columns() and V1.transform_fingerprint() != V2.transform_fingerprint()


# ------------------------------------------------------------------------------------------------ 2. matching


EV = EventDefinition(threshold_mg_dl=180, confirm_minutes=15, recovery_minutes=15, max_gap_minutes=7.5, jitter_minutes=1.0)


def _engine(*alerts: tuple[str, list[float]]) -> TwinEngine:
    eng = TwinEngine.__new__(TwinEngine)
    eng.serving = SimpleNamespace(alert={"horizon_minutes": 60, "episode_merge_minutes": 30})
    eng.event_def = EV
    eng.gap_times = []
    eng.confirmed_onsets = []
    eng.alerts = [AlertRecord(aid, f[0], f[-1], [f"{aid}:{x}" for x in f], {}, firing_times=list(f)) for aid, f in alerts]
    return eng


def _offline(firings: list[float], onset: float | None, end: float = 300.0):
    times = np.arange(0, end, 5.0)
    firing = np.isin(times, firings)
    label = np.zeros(times.size)
    on = np.full(times.size, np.nan)
    if onset is not None:
        pre = (times < onset) & (times >= onset - 60)
        label[pre], on[pre] = 1, onset
    ones = np.ones(times.size, bool)
    return evaluate_patient(times, ones, ones, ones, np.where(firing, 1.0, -1.0), label, on, 0.0, 60, 30)


def test_one_onset_is_credited_to_one_warning_online_and_offline():
    eng = _engine(("a0", [0.0]), ("a40", [40.0]))
    eng._update_alert_outcomes(65.0, [Onset(50.0, 65.0, True)])
    eng._update_alert_outcomes(200.0, [])  # follow-up of the second warning is now complete
    online = [a.outcome["status"] for a in eng.alerts]
    assert online == ["onset_observed", "no_onset_observed"]
    off = _offline([0.0, 40.0], 50.0)
    assert [e["outcome"] for e in off.episodes] == ["true_warning", "false_alarm"] and off.matched_onsets == 1


def test_one_episode_and_two_onsets_matches_only_the_earliest():
    assert match_episodes([(0.0, 10.0)], [30.0, 50.0], 60) == [30.0]
    eng = _engine(("a0", [0.0, 10.0]))
    eng._update_alert_outcomes(65.0, [Onset(30.0, 45.0, True), Onset(50.0, 65.0, True)])
    assert pd.Timestamp(eng.alerts[0].outcome["onset_at"]) == T0 + pd.Timedelta(minutes=30)


def test_repeated_confirmation_callbacks_change_nothing():
    eng = _engine(("a0", [0.0]), ("a40", [40.0]))
    for t in (65.0, 66.0, 70.0):
        eng._update_alert_outcomes(t, [Onset(50.0, 65.0, True)])
    assert len(eng.confirmed_onsets) == 1
    assert [a.state for a in eng.alerts] == ["closed", "open"]


def test_outcome_stays_pending_until_follow_up_is_observable_and_gaps_censor_it():
    eng = _engine(("a0", [0.0]))
    eng._update_alert_outcomes(55.0, [])  # onset at 50 not yet confirmed: no negative outcome inferred
    assert eng.alerts[0].state == "open" and eng.alerts[0].outcome["status"] == "pending"
    eng._update_alert_outcomes(82.0, [])  # 60 + 15 + 7.5 = 82.5 minutes of follow-up not complete yet
    assert eng.alerts[0].state == "open"
    eng._update_alert_outcomes(83.0, [])
    assert eng.alerts[0].outcome["status"] == "no_onset_observed"
    gap = _engine(("a0", [0.0]))
    gap.gap_times = [40.0]
    gap._update_alert_outcomes(83.0, [])
    assert gap.alerts[0].outcome["status"] == "unknown"


def test_incremental_matching_equals_batch_matching_on_the_same_stream():
    rng = np.random.default_rng(7)
    for _ in range(50):
        starts = np.sort(rng.choice(np.arange(0, 1000, 5.0), size=6, replace=False))
        windows = [(float(s), float(s + rng.choice([0, 10, 20]))) for s in starts]
        onsets = sorted({float(x) for x in rng.choice(np.arange(5, 1100, 5.0), size=5, replace=False)})
        batch = match_episodes(windows, onsets, 60)
        eng = _engine(*[(f"a{i}", [w[0], w[1]] if w[1] > w[0] else [w[0]]) for i, w in enumerate(windows)])
        for o in onsets:  # onsets arrive one by one, each at its confirmation time
            eng._update_alert_outcomes(o + 15, [Onset(o, o + 15, True)])
        eng._update_alert_outcomes(5000.0, [])
        inc = [(pd.Timestamp(a.outcome["onset_at"]) - EPOCH).total_seconds() / 60
               if a.outcome["status"] == "onset_observed" else None for a in eng.alerts]
        assert [None if b is None else round(b, 6) for b in batch] == [None if x is None else round(x, 6) for x in inc]


# ------------------------------------------------------------------------------------------------ 3. lead time


def test_qualified_lead_never_exceeds_the_horizon_in_a_long_warning_chain():
    firings = [0.0, 25.0, 50.0, 75.0, 100.0]  # one merged episode (30-minute merge rule)
    off = _offline(firings, 155.0)
    ep = off.episodes[0]
    assert ep["episode_start_to_onset"] == 155.0  # v1 "lead time": exceeds the 60-minute horizon
    assert ep["qualified_lead"] == 55.0  # from the firing at 100, whose horizon contains the onset
    assert 0 < ep["qualified_lead"] <= 60
    s = summarize([off], eligible_days=1.0, observed_days=2.0, horizon=60)
    assert s["episode_start_lead_over_horizon"] == 1 and s["qualified_lead_median"] == 55.0


def test_a_firing_whose_horizon_misses_the_onset_does_not_qualify():
    assert qualified_lead([0.0, 20.0], 70.0, 60) == (50.0, 20.0)  # 0 + 60 < 70, so only the firing at 20 counts
    assert qualified_lead([0.0], 55.0, 60) == (55.0, 0.0)
    assert match_episodes([(0.0, 0.0)], [61.0], 60) == [None]


def test_onset_is_credited_only_after_its_confirmation_arrives():
    eng = _engine(("a0", [0.0]))
    eng._update_alert_outcomes(55.0, [])  # onset happened at 50 but is not confirmed until 65
    assert eng.alerts[0].outcome["status"] == "pending"
    eng._update_alert_outcomes(65.0, [Onset(50.0, 65.0, True)])
    out = eng.alerts[0].outcome
    assert out["status"] == "onset_observed" and out["qualified_lead_minutes"] == 50.0
    assert out["episode_start_to_onset_minutes"] == 50.0


def test_rates_are_reported_on_both_time_bases():
    off = _offline([0.0, 200.0], 50.0, end=400.0)
    s = summarize([off], eligible_days=0.5, observed_days=2.0, horizon=60)
    assert s["false_alarm_episodes"] == 1 and s["warning_episodes"] == 2
    assert s["false_alarms_per_patient_day"] == 2.0 and s["false_alarms_per_observed_patient_day"] == 0.5
    assert s["warnings_per_patient_day"] == 1.0 and s["warnings_per_eligible_patient_day"] == 4.0
