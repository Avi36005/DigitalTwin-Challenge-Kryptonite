"""Foundation baseline (D-054): causal windows, horizon indexing, batch/origin independence, metric conventions.

Logic tests use a tiny fake adapter (they prove adapter logic only). The real-checkpoint smoke test runs only where
the optional isolated environment (torch + chronos-forecasting + the pinned checkpoint) is present; it skips cleanly
in the project's ordinary CPU environment.
"""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import foundation_baseline as fb  # noqa: E402


def _series(n=400, start=0.0, step=5.0, seed=0):
    rng = np.random.default_rng(seed)
    obs = start + step * np.arange(n, dtype=float)
    val = 120 + 40 * np.sin(np.arange(n) / 15.0) + rng.normal(0, 2, n)
    return obs, obs.copy(), val


def _fake_linear(ctxs):
    """Per-row linear extrapolation from the last two finite slots (rows never see each other)."""
    out = np.zeros((len(ctxs), 9, fb.PRED_LEN))
    for i, c in enumerate(ctxs):
        f = np.flatnonzero(np.isfinite(c))
        last, prev = c[f[-1]], c[f[-2]]
        slope = (last - prev) / (5.0 * (f[-1] - f[-2]))
        out[i] = last + slope * 5.0 * np.arange(1, fb.PRED_LEN + 1)
    return out


def _fake_leaky(ctxs):
    """Deliberately wrong adapter: every row sees the batch mean (cross-series leakage)."""
    m = np.nanmean(ctxs)
    return np.full((len(ctxs), 9, fb.PRED_LEN), m)


def test_this_module_keeps_torch_out_of_the_project_path():
    assert "torch" not in sys.modules or importlib.util.find_spec("chronos") is not None


def test_horizon_step_mapping_at_native_five_minute_cadence():
    assert fb.step_index(30) == 5 and fb.step_index(60) == 11   # steps 6 and 12 (1-based)
    assert fb.step_index(5) == 0
    with pytest.raises(ValueError):
        fb.step_index(32)
    # a fake adapter that outputs the 1-based step number: +30 must read step 6, +60 step 12
    q = np.tile(np.arange(1, fb.PRED_LEN + 1, dtype=float), (2, 9, 1))
    assert q[0, 4, fb.step_index(30)] == 6 and q[0, 4, fb.step_index(60)] == 12


def test_linear_series_forecast_lands_on_the_right_future_time():
    obs = 5.0 * np.arange(200)
    val = 100 + 0.5 * obs                        # +0.5 mg/dL per minute
    readings = {"p": (obs, obs.copy(), val)}
    t = obs[150]
    q, _ = fb.forecast_origins(readings, np.array(["p"]), np.array([t]), _fake_linear)
    assert q[0, 4, fb.step_index(30)] == pytest.approx(100 + 0.5 * (t + 30))
    assert q[0, 4, fb.step_index(60)] == pytest.approx(100 + 0.5 * (t + 60))


def test_context_reads_only_observed_and_available_past():
    obs, avail, val = _series()
    t = obs[300]
    ctx = fb.build_context(obs, avail, val, t, length=64)
    assert ctx[-1] == pytest.approx(val[300], abs=1e-4)       # last slot is the reading at the origin
    assert ctx[-2] == pytest.approx(val[299], abs=1e-4)
    np.testing.assert_allclose(ctx, val[237:301].astype(np.float32))
    # a reading observed before t but only available after t is excluded
    late = avail.copy()
    late[299] = t + 10
    assert np.isnan(fb.build_context(obs, late, val, t, length=64)[-2])
    # future readings never enter, whatever their values
    v2 = val.copy()
    v2[301:] = 999.0
    np.testing.assert_array_equal(fb.build_context(obs, avail, v2, t, length=64), ctx)


def test_gaps_are_missing_slots_and_short_history_is_left_padded():
    obs, avail, val = _series(n=50)
    keep = np.ones(50, bool)
    keep[40:43] = False                         # a 20-minute gap
    ctx = fb.build_context(obs[keep], avail[keep], val[keep], obs[49], length=64)
    assert np.isnan(ctx[-10:-7]).all() and np.isfinite(ctx[-7:]).all()
    assert np.isnan(ctx[:14]).all()             # 64 slots, only 50 readings exist
    # jittered timestamps (within 2.5 min) still map to their slot
    j = obs + np.where(np.arange(50) % 2 == 0, 1.2, -1.4)
    ctx2 = fb.build_context(j, j.copy(), val, obs[49], length=64)
    assert np.isfinite(ctx2[-49:]).all()


def test_changing_another_windows_future_cannot_change_an_earlier_forecast():
    obs, avail, val = _series(n=400)
    readings = {"a": (obs, avail, val)}
    origins = np.array([obs[200], obs[260], obs[330]])
    pids = np.array(["a", "a", "a"])
    q1, h1 = fb.forecast_origins(readings, pids, origins, _fake_linear, batch=3)
    v2 = val.copy()
    v2[201:] += 80.0                            # changes the later windows' contexts (the earlier origin's future)
    q2, h2 = fb.forecast_origins({"a": (obs, avail, v2)}, pids, origins, _fake_linear, batch=3)
    np.testing.assert_array_equal(q1[0], q2[0])
    assert h1[0] == h2[0] and h1[1] != h2[1]
    assert not np.allclose(q1[1], q2[1])
    # the same harness detects an adapter that mixes rows of a batch
    l1, _ = fb.forecast_origins(readings, pids, origins, _fake_leaky, batch=3)
    l2, _ = fb.forecast_origins({"a": (obs, avail, v2)}, pids, origins, _fake_leaky, batch=3)
    assert not np.allclose(l1[0], l2[0])


def test_batch_size_and_order_do_not_change_forecasts():
    obs, avail, val = _series(n=300)
    readings = {"a": (obs, avail, val), "b": (obs, avail, val[::-1].copy())}
    pids = np.array(["a", "b"] * 20)
    origins = np.repeat(obs[100:120], 2)
    q1, h1 = fb.forecast_origins(readings, pids, origins, _fake_linear, batch=40)
    q2, h2 = fb.forecast_origins(readings, pids[::-1], origins[::-1], _fake_linear, batch=7)
    np.testing.assert_array_equal(q1, q2[::-1])
    assert h1 == h2[::-1]


def test_macro_versus_pooled_and_bootstrap_sign():
    pids = np.array(["p1"] * 8 + ["p2"] * 2)
    err = np.array([1.0] * 8 + [10.0] * 2)
    assert fb.pooled_mae(err) == pytest.approx(2.8)
    assert fb.macro_mae(err, pids) == pytest.approx(5.5)
    a = pd.Series({"p1": 1.0, "p2": 2.0, "p3": 3.0})
    b = a + 1.0
    d = fb.paired_bootstrap(a, b, n=200)
    assert d["mean"] == pytest.approx(-1.0) and d["hi"] < 0 and d["people_better"] == 3   # first − second


def test_real_checkpoint_smoke_isolation_and_shape():
    pytest.importorskip("torch")
    pytest.importorskip("chronos")
    try:
        ad = fb.ChronosAdapter(threads=2)
    except Exception as exc:  # checkpoint not cached / offline
        pytest.skip(f"pinned checkpoint unavailable: {exc}")
    assert ad.kind == "ChronosBoltPipeline" and fb.REVISION in str(ad.path)
    obs, avail, val = _series(n=700)
    a = fb.build_context(obs, avail, val, obs[600])
    b = fb.build_context(obs, avail, val, obs[650])
    alone = ad(a[None])
    assert alone.shape == (1, 9, fb.PRED_LEN) and np.isfinite(alone).all()
    both = ad(np.stack([a, b]))
    b2 = b.copy()
    b2[-60:] += 100.0
    changed = ad(np.stack([a, b2]))
    np.testing.assert_allclose(both[0], alone[0], atol=1e-3)
    np.testing.assert_allclose(changed[0], both[0], atol=1e-3)
    assert not np.allclose(changed[1], both[1], atol=1e-3)
    med = alone[0, 4]
    assert np.all(np.diff(alone[0], axis=0) >= -1e-4)          # quantiles ordered
    assert 40 < med[fb.step_index(30)] < 400
