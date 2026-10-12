"""Prompt pack v4 / 01: canonical records, adapters and cadence handling — on FICTIONAL fixtures only.

No AI-READI or ShanghaiT2DM record is used here; the fixtures below are invented to mimic the documented layouts.
"""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest
from glucotwin.data import aireadi
from glucotwin.data import canonical as cn
from glucotwin.data.store import EPOCH, PatientData, empty_table, to_minutes
from glucotwin.features import FEATURE_SETS, build_features, prepare
from glucotwin.research.metrics import macro_mae_grouped

CGM15 = FEATURE_SETS["cgm15-v1"]


# ------------------------------------------------------------------------------------------------ units and codes


def test_mmol_is_converted_only_when_declared_and_the_factor_is_recorded():
    v = cn.parse_glucose_value(7.0, "mmol/L", (39.6, 500.4))
    assert v.mg_dl == pytest.approx(126.0) and v.conversion == "mmol/L x 18" and v.quality == "ok"
    same = cn.parse_glucose_value(126.0, "mg/dL", (39.6, 500.4))
    assert same.mg_dl == 126.0 and same.conversion == ""
    with pytest.raises(ValueError):
        cn.parse_glucose_value(7.0, "", (39.6, 500.4))  # undeclared unit: refuse to guess


def test_sensor_low_high_codes_stay_codes_and_limits_are_suspect():
    assert cn.parse_glucose_value("LOW", "mg/dL", (40, 400)).quality == "sensor_low"
    assert cn.parse_glucose_value("High", "mg/dL", (40, 400)).mg_dl is None
    assert cn.parse_glucose_value(40, "mg/dL", (40, 400)).quality == "suspect"
    assert cn.parse_glucose_value(401, "mg/dL", (40, 400)).quality == "invalid"
    assert cn.parse_glucose_value(float("nan"), "mg/dL", (40, 400)).missing_reason == "missing_value"


def test_timestamp_anomalies_duplicates_and_resets_are_counted_not_hidden():
    df = pd.DataFrame({
        "recording_id": "r0",
        "_source_ts": pd.to_datetime(["2021-01-01 00:00", "2021-01-01 00:15", "2021-01-01 00:15", "1970-01-01 00:00",
                                      None, "2021-01-01 00:10"]),
        "glucose_mg_dl": [100.0, 110.0, 120.0, 90.0, 95.0, 105.0], "quality": "ok", "missing_reason": ""})
    c = cn.flag_timestamp_anomalies(df)
    assert c["unparseable_timestamps"] == 1 and c["implausible_timestamps"] == 1
    assert c["duplicate_samples"] == 1 and c["conflicting_duplicates"] == 1
    assert c["recording_resets"] == 1
    assert (df["quality"] == "ok").sum() == 3


def test_canonical_rows_with_duplicate_keys_are_rejected():
    row = {c: "x" for c, t in cn.CANONICAL_COLUMNS.items() if t == "string"}
    row.update({"observed_at": EPOCH, "available_at": EPOCH, "native_cadence_minutes": 15.0, "glucose_mg_dl": 100.0})
    with pytest.raises(ValueError):
        cn.conform_canonical(pd.DataFrame([row, row]))


# ------------------------------------------------------------------------------------------------ cadence


def _series(times, values=None, avail_delay=0.0) -> PatientData:
    t = np.asarray(times, float)
    v = np.full(t.size, 120.0) if values is None else np.asarray(values, float)
    g = pd.DataFrame({"event_id": [f"x-r0-{i:05d}" for i in range(t.size)],
                      "observed_at": EPOCH + pd.to_timedelta(t, unit="min"),
                      "available_at": EPOCH + pd.to_timedelta(t + avail_delay, unit="min"),
                      "value_mg_dl": v, "quality": "ok", "flags": "", "source": "fixture"})
    return PatientData({"patient_id": "x", "display_alias": "x"}, [], g, empty_table("activity"), empty_table("meals"))


def test_decimation_keeps_the_first_reading_per_15_minute_bin_and_never_upsamples():
    five = np.arange(0, 120, 5.0) + 1.0          # 1, 6, 11, 16, ...
    keep = cn.causal_decimate(five, 15.0)
    assert five[keep].tolist() == [1.0, 16.0, 31.0, 46.0, 61.0, 76.0, 91.0, 106.0]
    fifteen = np.arange(0, 240, 15.0)
    assert cn.causal_decimate(fifteen, 15.0).all()  # native 15-minute data pass unchanged
    # causal: whether a reading is kept never depends on later readings
    for k in range(1, five.size):
        assert (cn.causal_decimate(five[:k], 15.0) == keep[:k]).all()


def test_native_15_minute_features_use_15_minute_lags_and_no_activity():
    t = np.arange(0, 300, 15.0)
    fr = build_features(prepare(_series(t, 100 + t / 10)), np.array([240.0]), CGM15)
    row = fr.frame.iloc[0]
    assert row["g_lag_15"] == pytest.approx(100 + 22.5) and row["g_lag_60"] == pytest.approx(118.0)
    assert np.isnan(row["slope_15"])           # three readings never fit in 15 minutes at this cadence
    assert fr.quality[0] == "ok" and row["n_60"] == 5
    assert not any(c.startswith(("hr_", "mets_", "kcal", "act_")) for c in CGM15.columns())


def test_future_mutation_cannot_change_15_minute_features_or_decimation():
    t = np.arange(0, 600, 5.0)
    v = 120 + 20 * np.sin(t / 50)
    base = _series(t, v)
    mut = _series(t, np.where(t > 300, v + 80, v))
    def at(p):
        g = p.glucose
        keep = cn.causal_decimate(to_minutes(g["observed_at"]), 15.0)
        d = PatientData(p.meta, [], g[keep].reset_index(drop=True), p.activity, p.meals)
        return build_features(prepare(d), np.array([300.0]), CGM15).frame.iloc[0]
    pd.testing.assert_series_equal(at(base), at(mut))


def test_a_reading_released_late_is_invisible_before_its_availability():
    p = _series(np.arange(0, 120, 15.0), avail_delay=0.0)
    late = p.glucose.copy()
    late.loc[late.index[-1], "available_at"] = late["available_at"].iloc[-1] + pd.Timedelta(minutes=30)
    p2 = PatientData(p.meta, [], late, p.activity, p.meals)
    t_last = float(to_minutes(late["observed_at"]).max())
    row = build_features(prepare(p2), np.array([t_last]), CGM15).frame.iloc[0]
    assert row["g_age_min"] == pytest.approx(15.0)  # the newest reading is not yet available at its own time


def test_unknown_lab_timing_never_enters_features():
    p = _series(np.arange(0, 240, 5.0))
    p.profile = [{"name": "hba1c", "value": 8.1, "available_at": None, "status": "timing_unknown"}]
    row = build_features(prepare(p), np.array([200.0]), FEATURE_SETS["dyn-prof-v2"]).frame.iloc[0]
    assert np.isnan(row["p_hba1c"])


def test_observed_hours_respect_gaps_and_calendar_days_are_counted_separately():
    t = np.concatenate([np.arange(0, 60, 15.0), np.arange(1440 + 600, 1440 + 660, 15.0)])
    assert cn.observed_minutes(t, 15.0) == pytest.approx(8 * 15.0)   # a 33-hour gap adds nothing
    assert cn.long_gaps(t, 60.0) == 1
    assert cn.calendar_days_with_readings(pd.Series(EPOCH + pd.to_timedelta(t, unit="min"))) == 2


# ------------------------------------------------------------------------------------------------ overlap


def test_a_time_shifted_unit_round_tripped_copy_is_detected_but_strangers_are_not():
    rng = np.random.default_rng(1)
    t = np.arange(0, 3 * 1440, 15.0)
    v = np.round((120 + np.cumsum(rng.normal(0, 4, t.size))) / 18.0, 1) * 18.0  # mmol/L x 18 like the source
    copy_t = t + 7 * 1440 + 3                                                  # harmonized copy, shifted dates
    copy_v = np.round(v / 18.0, 1) * 18.0
    other = 120 + np.cumsum(rng.normal(0, 4, t.size))
    a, b, c = (cn.recording_signature(t, v), cn.recording_signature(copy_t, copy_v), cn.recording_signature(t, other))
    assert cn.signature_overlap(a, b) >= 0.9
    assert cn.signature_overlap(a, c) < cn.OVERLAP_THRESHOLD


def test_repeated_overlapping_visit_readings_are_marked_once():
    obs = pd.to_datetime(["2000-01-03 00:00", "2000-01-03 00:15", "2000-01-03 00:15", "2000-01-03 00:30"], utc=True)
    df = pd.DataFrame({"recording_id": ["a-r1", "a-r1", "a-r0", "a-r0"], "observed_at": obs,
                       "quality": "ok", "missing_reason": ""})
    assert cn.drop_cross_recording_overlap(df) == 1
    assert df.loc[2, "missing_reason"] == "overlaps_earlier_recording"


# ------------------------------------------------------------------------------------------------ ShanghaiT2DM adapter


def _xlsx(df: pd.DataFrame) -> bytes:
    b = io.BytesIO()
    df.to_excel(b, index=False)
    return b.getvalue()


def test_shanghai_adapter_on_a_fictional_archive(tmp_path, monkeypatch):
    from glucotwin.data import shanghai

    monkeypatch.setattr("glucotwin.data.cgmacros._salt", lambda: "fixture-salt")
    t0 = pd.Timestamp("2021-03-01 08:00")
    v0 = pd.DataFrame({"Date": pd.date_range(t0, periods=400, freq="15min"),
                       "CGM (mg / dl)": np.r_[39.6, np.full(398, 126.0), np.nan], "CBG (mg / dl)": np.nan,
                       "Blood Ketone (mmol / L)": np.nan, "Dietary intake": None, "饮食": None,
                       "Insulin dose - s.c.": None, "Non-insulin hypoglycemic agents": None,
                       "CSII - bolus insulin (Novolin R, IU)": np.nan, "CSII - basal insulin (Novolin R, IU / H)": np.nan,
                       "Insulin dose - i.v.": np.nan})
    v1 = v0.copy()
    v1["Date"] = pd.date_range(t0 - pd.Timedelta(days=40), periods=400, freq="15min")   # visit 1 precedes visit 0
    v1 = v1.rename(columns={"CGM (mg / dl)": "CGM"})                                      # unit missing in header
    summary = pd.DataFrame({"Patient Number": ["9001_0_20210301", "9001_1_20210120"],
                            "Gender (Female=1, Male=2)": [2, 2], "Age (years)": [60, 60], "BMI (kg/m2)": [25.0, 25.0],
                            "HbA1c (mmol/mol)": [60, 61], "Duration of diabetes (years)": [5, 5]})
    zpath = tmp_path / "fixture.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("Shanghai_T2DM/9001_0_20210301.xlsx", _xlsx(v0))
        zf.writestr("Shanghai_T2DM/9001_1_20210120.xlsx", _xlsx(v1))
        zf.writestr("Shanghai_T1DM/1001_0_20210101.xlsx", _xlsx(v0))
        zf.writestr("__MACOSX/._junk", b"x")
        zf.writestr("Shanghai_T2DM_Summary.xlsx", _xlsx(summary))
    recs, summ, info = shanghai.read_archive(zpath)
    assert len(recs) == 2 and info["t1dm_files_not_imported"] == 1
    from glucotwin.config import load_config
    pdata, canon, inf = shanghai.normalize_participant("9001", recs, summ, load_config("data"))
    assert pdata.patient_id.startswith("sh-") and set(canon["recording_id"]) == {f"{pdata.patient_id}-r0",
                                                                                   f"{pdata.patient_id}-r1"}
    assert (canon["unit_conversion"] == "unit_from_dataset_convention").sum() == 400
    assert (canon["quality"] == "suspect").sum() == 2 and (canon["missing_reason"] == "missing_value").sum() == 2
    first = canon.sort_values("observed_at").iloc[0]
    assert first["recording_id"].endswith("-r1") and str(first["observed_at"].date()) == "2000-01-03"
    assert len(pdata.glucose) == 798 and pdata.meta["eligible_for_portable_external"]
    assert all(a["available_at"] is None for a in pdata.profile)          # labs never causally available
    assert canon["original_timestamp"].str.startswith("2021").all()       # source wall clock kept verbatim


# ------------------------------------------------------------------------------------------------ AI-READI adapter


def _dex(path, readings):
    doc = {"header": {"uuid": "FICTIONAL-0001", "patient_id": "FICTIONAL-0001", "timezone": "pst",
                      "acquisition_rate": {"number_of_times": 1, "time_window": {"value": 5, "unit": "min"}}},
           "body": {"cgm": readings}}
    path.write_text(json.dumps(doc))


def _reading(ts, value, unit="mg/dL", event="EGV"):
    return {"effective_time_frame": {"time_interval": {"start_date_time": ts, "end_date_time": ts}},
            "event_type": event, "source_device_id": "FAKE", "blood_glucose": {"unit": unit, "value": value},
            "transmitter_time": {"unit": "long integer", "value": 1}, "transmitter_id": "FAKE"}


def test_aireadi_parser_on_fictional_open_mhealth_json(tmp_path):
    p = tmp_path / "0001_DEX.json"
    _dex(p, [_reading("2023-08-08T21:15:10Z", 138), _reading("2023-08-08T21:20:10Z", "Low"),
             _reading("2023-08-08T21:25:10Z", "High"), _reading("2023-08-08T21:30:10Z", 7.5, unit="mmol/L"),
             _reading("2023-08-08T21:30:10Z", None, event="Calibration"), _reading("2023-08-08T21:35:10Z", 140, unit="")])
    canon, audit = aireadi.normalize_cgm_file(p, "ar-000001", "2000-01-03T00:00:00+00:00")
    assert audit["non_egv_events"] == 1
    q = canon.set_index("source_record_id")["quality"]
    assert q["0001_DEX.json#cgm[1]"] == "sensor_low" and q["0001_DEX.json#cgm[2]"] == "sensor_high"
    assert canon.loc[canon["unit_conversion"] != "", "glucose_mg_dl"].iloc[0] == pytest.approx(135.0)
    assert canon.loc[canon["source_record_id"] == "0001_DEX.json#cgm[5]", "missing_reason"].iloc[0] == "unit_not_declared"
    assert str(canon["observed_at"].min().date()) == "2000-01-03"


def test_aireadi_selective_download_skips_imaging_and_respects_the_pilot():
    rows = [{"path": "participants.tsv", "size_bytes": 10},
            {"path": "retinal_photography/cfp/x.dcm", "size_bytes": 10_000_000},
            {"path": f"{aireadi.CGM_SUBPATH}/0001/0001_DEX.json", "size_bytes": 100},
            {"path": f"{aireadi.CGM_SUBPATH}/0002/0002_DEX.json", "size_bytes": 200},
            {"path": "cardiac_ecg/ecg_12lead/x.dat", "size_bytes": 5000}]
    full = aireadi.plan_selective_download(rows)
    assert full["selected_bytes"] == 310 and full["skipped_bytes"] == 10_005_000
    pilot = aireadi.plan_selective_download(rows, ["0002"])
    assert [f["path"] for f in pilot["files"]] == ["participants.tsv", f"{aireadi.CGM_SUBPATH}/0002/0002_DEX.json"]
    assert aireadi.deterministic_pilot(["3", "1", "2", "4"], 2) == aireadi.deterministic_pilot(["4", "2", "1", "3"], 2)


def test_local_aireadi_status_is_access_required_without_files(tmp_path):
    assert aireadi.local_status(tmp_path / "missing")["access_status"] == "access_required"


# ------------------------------------------------------------------------------------------------ metric used for stopping


def test_macro_mae_weights_participants_not_rows():
    pred = np.array([1.0, 1.0, 1.0, 5.0])
    target = np.zeros(4)
    groups = np.array(["A", "A", "A", "B"])
    assert macro_mae_grouped(pred, target, groups) == pytest.approx(3.0)   # (1 + 5) / 2
    assert np.mean(np.abs(pred - target)) == pytest.approx(2.0)            # the row-weighted MAE differs
