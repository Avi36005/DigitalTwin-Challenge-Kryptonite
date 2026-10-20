"""hist-v1 (D-049): long-history features use only readings observed and available by the origin."""

import numpy as np
from glucotwin.research.history import COLUMNS, history_features


def _readings(n=600, seed=0):
    rng = np.random.default_rng(seed)
    obs = np.arange(n) * 5.0
    return obs, obs.copy(), 120 + rng.normal(0, 20, n)


def test_future_readings_never_change_a_past_origin():
    obs, avail, vals = _readings()
    origins = np.array([1500.0, 2400.0])
    g_last = np.array([vals[300], vals[480]])
    base = history_features(origins, g_last, obs, avail, vals)
    later = vals.copy()
    later[obs > 2400] += 500.0  # perturb only the future of both origins
    assert np.allclose(base.to_numpy(), history_features(origins, g_last, obs, avail, later).to_numpy(), equal_nan=True)


def test_reading_available_after_the_origin_is_excluded():
    obs, avail, vals = _readings()
    t = 1500.0
    late = avail.copy()
    late[(obs > t - 60) & (obs <= t)] = t + 30  # observed before t but released later
    a = history_features(np.array([t]), np.array([vals[300]]), obs, avail, vals)
    b = history_features(np.array([t]), np.array([vals[300]]), obs, late, vals)
    assert b["hist_cov_360"].iloc[0] < a["hist_cov_360"].iloc[0]


def test_sparse_window_is_missing_not_estimated():
    obs, avail, vals = _readings(n=30)  # 150 minutes of readings: 30 of the 72 expected in 6 h
    f = history_features(np.array([145.0]), np.array([vals[-1]]), obs, avail, vals)
    assert set(f.columns) == set(COLUMNS)
    assert np.isnan(f["hist_mean_360"].iloc[0]) and 0 < f["hist_cov_360"].iloc[0] < 0.5
    assert np.isnan(f["hist_dev_1440"].iloc[0])


def test_suspect_readings_are_excluded():
    obs, avail, vals = _readings()
    sus = np.zeros(len(vals), bool)
    sus[250:300] = True
    a = history_features(np.array([1495.0]), np.array([vals[299]]), obs, avail, vals)
    b = history_features(np.array([1495.0]), np.array([vals[299]]), obs, avail, vals, sus)
    assert b["hist_cov_360"].iloc[0] < a["hist_cov_360"].iloc[0]
