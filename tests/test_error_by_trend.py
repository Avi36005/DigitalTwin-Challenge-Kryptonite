"""The workspace's trend note is read only for the exact serving model version it was computed for."""

import json

from glucotwin.evaluation.report import _error_by_trend

ROW = {"horizon": 60, "trend": "rising_fast", "label": "Rising > 2 mg/dL/min", "slope_min": 2.0, "slope_max": None,
       "mae_macro": 35.3, "origins": 138, "participants": 12, "mean_signed_error_target_above_180": -16.9}


def _write(tmp_path, version):
    doc = {"model_version": version, "pipeline": "lightgbm:dyn-prof-v2", "personalization": "adaptive",
           "segment": "validation", "trend_feature": "slope_15 (mg/dL per minute)", "min_participants": 3,
           "generated_at": "2026-10-20T15:30:00+00:00", "rows": [ROW]}
    (tmp_path / "error_by_trend.json").write_text(json.dumps(doc))


def test_matching_model_version_is_read(tmp_path):
    _write(tmp_path, "m-1")
    out = _error_by_trend(tmp_path, "m-1")
    assert out["rows"] == [ROW] and out["segment"] == "validation" and "generated_at" not in out


def test_other_model_version_or_missing_file_is_ignored(tmp_path):
    assert _error_by_trend(tmp_path, "m-1") is None
    _write(tmp_path, "m-0")
    assert _error_by_trend(tmp_path, "m-1") is None
