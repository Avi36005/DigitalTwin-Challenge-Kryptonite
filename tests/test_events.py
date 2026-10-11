"""Research event definition: cutoff, native-cadence duration, recovery, gaps and censoring."""

import numpy as np
from glucotwin.events import EventDefinition, label_new_onsets, trace_episodes

D = EventDefinition()  # >180, 15 min confirmation/recovery, 7.5 min continuity, 1 min jitter


def series(values, start=0.0, step=5.0):
    t = start + step * np.arange(len(values), dtype=float)
    return t, np.asarray(values, dtype=float)


def test_exact_cutoff_is_not_high():
    t, v = series([120] * 4 + [180] * 6 + [120] * 4)
    assert trace_episodes(t, v, D).onsets == []


def test_four_readings_span_fifteen_minutes_but_three_do_not():
    t3, v3 = series([120] * 4 + [190] * 3 + [120] * 4)
    assert trace_episodes(t3, v3, D).onsets == []  # three readings span only 10 minutes
    t4, v4 = series([120] * 4 + [190] * 4 + [120] * 4)
    onsets = trace_episodes(t4, v4, D).onsets
    assert len(onsets) == 1
    assert onsets[0].onset_at == t4[4]          # onset = first high reading of the confirmed run
    assert onsets[0].confirmed_at == t4[7]      # confirmed by the fourth reading
    assert onsets[0].certain


def test_return_above_cutoff_before_recovery_continues_same_episode():
    # episode, 10 minutes below (no recovery), high again -> still one onset
    t, v = series([120] * 4 + [200] * 5 + [150] * 2 + [200] * 5 + [120] * 5)
    assert len(trace_episodes(t, v, D).onsets) == 1
    # with a full 15-minute recovery a second onset is counted
    t, v = series([120] * 4 + [200] * 5 + [150] * 4 + [200] * 5 + [120] * 5)
    assert len(trace_episodes(t, v, D).onsets) == 2


def test_missing_reading_breaks_confirmation_and_onset_after_gap_is_uncertain():
    t = np.array([0, 5, 10, 15, 20, 25, 35, 40, 45, 50], dtype=float)  # 10-minute gap between 25 and 35
    v = np.array([120, 120, 120, 120, 190, 190, 190, 190, 190, 190], dtype=float)
    onsets = trace_episodes(t, v, D).onsets
    assert len(onsets) == 1 and not onsets[0].certain  # run after the gap: onset time unknown


def test_new_onset_labels_and_horizon_window():
    t, v = series([120] * 6 + [200] * 6 + [120] * 6)
    lab = label_new_onsets(t, v, D, 30)
    onset = t[6]
    for i in range(len(t)):
        if not lab.eligible[i]:
            continue
        if onset - 30 <= t[i] < onset:
            assert lab.label[i] == 1 and lab.onset_at[i] == onset
        elif t[i] < onset - 30:
            assert lab.label[i] == 0


def test_already_high_origin_is_not_eligible_for_early_warning():
    t, v = series([120] * 6 + [200] * 8 + [120] * 6)
    lab = label_new_onsets(t, v, D, 60)
    high_idx = np.where(v > 180)[0]
    assert not lab.eligible[high_idx].any()
    assert all(s in ("pending_high", "in_episode") for s in np.array(lab.state)[high_idx])


def test_missing_future_support_is_censored_not_negative():
    t, v = series([120] * 20)
    lab = label_new_onsets(t, v, D, 60)
    tail = t > t[-1] - 60
    assert np.isnan(lab.label[tail & lab.eligible]).all()  # end of record -> censored
    # a gap inside the window censors the label
    t2 = np.concatenate([t[:10], t[10:] + 30])
    lab2 = label_new_onsets(t2, v, D, 60)
    assert np.isnan(lab2.label[6]) and lab2.censor_reason[6] == "gap_in_label_support"


def test_label_support_extends_to_confirmation():
    # record starts 'unknown' until 15 minutes at or below the cutoff, so use a long normal prefix
    t, v = series([120] * 20 + [190] * 4 + [120] * 4)   # onset at t=100, confirmed at t=115
    lab = label_new_onsets(t, v, D, 60)
    i = 7  # origin 35: window (35, 95] -> no onset inside -> negative once a reading after 95 is seen
    assert lab.eligible[i] and lab.label[i] == 0
    i = 8  # origin 40: onset at 100 is inside (40, 100]; resolved only at confirmation = origin + 75
    assert lab.label[i] == 1 and lab.support_end[i] == t[23] == t[i] + 75
    assert not lab.eligible[2]  # still 'unknown' at the start of the record
