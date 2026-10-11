"""Versioned CGMacros 1.0.0 -> canonical adapter (``cgmacros-adapter-1.0``).

Evidence-based mapping decisions (see reports/data_audit.md for the measured inventory):

* ``CGMacros-0XX.csv`` rows are a 1-minute merged grid. Both CGM columns are LINEARLY INTERPOLATED to
  that grid between native readings. Native Dexcom readings (integer mg/dL, ~5 min apart) are the
  interpolation knots. We recover them as (a) points where the 1-minute slope changes, (b) run
  endpoints, and (c) collinear hidden knots on the 5-minute grid between detected knots, accepted only
  when the interpolated value is an integer. Non-integer "knots" are dropped and counted. One-minute
  rows are never treated as independent observations. Native timestamps are only known to the minute.
* Missing CGM minutes are left missing; nothing is interpolated across gaps.
* Columns outside the data dictionary (``Intensity``, ``Steps``, ``Sugar``, ``RecordIndex``,
  unnamed index columns) are reported, not interpreted.
* ``METs`` is documented as METs x 10 and is converted to METs. Activity is summarised into trailing
  5-minute windows that end on the 5-minute grid, so a summary is only available after its window ends.
* Meals are rows with a ``Meal Type`` value. Macronutrients were estimated by the study team; meal
  timing comes from photographs. Real-time availability of logs is not documented, so the primary
  model excludes meals (configs/data.yaml ``availability.meal_policy``).
* Cohort membership follows the dataset's documented HbA1c criterion (T2D: HbA1c > 6.4 %), using the
  ``A1c PDL (Lab)`` column. The dictionary labels that column "mmol/mol" but its 4.6-8.5 range is in %,
  which we record as a documented discrepancy.
* ``LDL (Cal)`` = 800, ``VLDL (Cal)`` = 400 and ``Cho/HDL Ratio`` = 400 are documented error codes and
  are excluded as suspect values.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import load_config, paths
from glucotwin.data.store import PatientData

ADAPTER_VERSION = "cgmacros-adapter-1.0"
KNOWN_COLUMNS = {
    "Timestamp", "Libre GL", "Dexcom GL", "HR", "Calories (Activity)", "METs", "Meal Type", "Calories",
    "Carbs", "Protein", "Fat", "Fiber", "Amount Consumed", "Image path",
}
SOURCE_PREFIX = "cgmacros-1.0.0"
MEAL_TYPES = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack",
              "snacks": "Snack", "snack 1": "Snack"}


# ------------------------------------------------------------------------------------------------
# Pseudonyms (private mapping kept outside the public repository)
# ------------------------------------------------------------------------------------------------


def _salt() -> str:
    p = paths().private / "pseudonym_salt.txt"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(16))
    return p.read_text().strip()


def pseudonym(source_key: str) -> str:
    cfg = load_config("data")["pseudonyms"]
    digest = hashlib.sha256(f"{_salt()}:{source_key}".encode()).hexdigest()
    return f"{cfg['prefix']}{digest[: cfg['length']]}"


def save_private_mapping(rows: list[dict[str, Any]]) -> Path:
    p = paths().private / "cgmacros_pseudonym_map.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=2))
    return p


# ------------------------------------------------------------------------------------------------
# Native CGM recovery
# ------------------------------------------------------------------------------------------------


def recover_native(values: np.ndarray, cadence: int) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    """Recover native readings from a 1-minute linearly interpolated series.

    Returns (row_indices, flags, stats) where flags is 'detected_knot' or 'collinear_recovered'.
    """
    v = np.asarray(values, dtype=float)
    n = v.size
    ok = ~np.isnan(v)
    knot = np.zeros(n, dtype=bool)
    if n >= 3:
        d2 = np.abs(np.diff(np.diff(v)))
        knot[1:-1] = np.nan_to_num(d2, nan=0.0) > 1e-6
    prev_ok = np.concatenate([[False], ok[:-1]])
    next_ok = np.concatenate([ok[1:], [False]])
    knot |= ok & ~prev_ok
    knot |= ok & ~next_ok
    knot &= ok
    detected = np.where(knot)[0]
    rows: list[int] = []
    flags: list[str] = []
    stats = {"detected_knots": int(detected.size), "collinear_recovered": 0, "collinear_non_integer": 0,
             "dropped_non_integer": 0, "irregular_intervals": 0}

    def is_int(x: float) -> bool:
        return abs(x - round(x)) < 1e-6

    for i, k in enumerate(detected):
        if is_int(v[k]):
            rows.append(int(k))
            flags.append("detected_knot")
        else:
            stats["dropped_non_integer"] += 1
        if i + 1 < detected.size:
            nxt = detected[i + 1]
            gap = nxt - k
            if gap > cadence and ok[k:nxt + 1].all():
                if gap % cadence == 0:
                    for j in range(k + cadence, nxt, cadence):
                        if is_int(v[j]):
                            rows.append(int(j))
                            flags.append("collinear_recovered")
                            stats["collinear_recovered"] += 1
                        else:
                            stats["collinear_non_integer"] += 1
                            stats["dropped_non_integer"] += 1
                else:
                    stats["irregular_intervals"] += 1
    order = np.argsort(rows, kind="mergesort")
    return np.asarray(rows, dtype=int)[order], np.asarray(flags, dtype=object)[order], stats


# ------------------------------------------------------------------------------------------------
# Source reading
# ------------------------------------------------------------------------------------------------


def read_participant(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    unknown = [c for c in df.columns if c not in KNOWN_COLUMNS]
    audit: dict[str, Any] = {"source_rows": int(len(df)), "unknown_columns": unknown}
    ts = pd.to_datetime(df["Timestamp"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    bad = int(ts.isna().sum())
    audit["timestamp_parse_failures"] = bad
    df = df.assign(_ts=ts).dropna(subset=["_ts"])
    audit["duplicate_timestamps"] = int(df["_ts"].duplicated().sum())
    audit["out_of_order_rows"] = int((df["_ts"].diff().dt.total_seconds() < 0).sum())
    # Deterministic conflict policy: stable sort by time, keep the first row per timestamp.
    df = df.sort_values("_ts", kind="mergesort").drop_duplicates("_ts", keep="first").reset_index(drop=True)
    return df, audit


def _reindex_minutes(df: pd.DataFrame) -> pd.DataFrame:
    """Place rows on a complete 1-minute grid so that missing minutes are explicit NaN rows."""
    grid = pd.date_range(df["_ts"].min(), df["_ts"].max(), freq="1min")
    out = df.set_index("_ts").reindex(grid)
    out.index.name = "_ts"
    return out.reset_index()


def normalize_participant(
    source_key: str, path: Path, bio_row: pd.Series, cfg: dict[str, Any]
) -> tuple[PatientData, dict[str, Any]]:
    norm = cfg["normalization"]
    avail_cfg = cfg["availability"]
    tp = cfg["time_policy"]
    lo, hi = norm["glucose_valid_range_mg_dl"]
    pid = pseudonym(source_key)
    raw, audit = read_participant(path)
    grid = _reindex_minutes(raw)
    audit["missing_grid_minutes"] = int(len(grid) - len(raw))

    # ---- time policy: synthetic UTC, day-aligned, reversible offset kept privately
    first_day = grid["_ts"].min().normalize()
    origin = pd.Timestamp(tp["synthetic_origin"])
    offset = origin.tz_localize(None) - first_day

    def canon(ts: pd.Series) -> pd.Series:
        return (pd.to_datetime(ts) + offset).dt.tz_localize("UTC")

    grid["_t"] = canon(grid["_ts"])

    # ---- glucose (each device separately)
    glucose_tables: dict[str, pd.DataFrame] = {}
    device_stats: dict[str, Any] = {}
    for device, dcfg in norm["devices"].items():
        col = dcfg["column"]
        if col not in grid.columns:
            device_stats[device] = {"present": False}
            continue
        values = pd.to_numeric(grid[col], errors="coerce").to_numpy(float)
        rows, flags, stats = recover_native(values, int(dcfg["nominal_cadence_minutes"]))
        vals = values[rows]
        times = grid["_t"].iloc[rows].reset_index(drop=True)
        out_of_range = (vals < lo) | (vals > hi)
        at_limit = (vals == lo) | (vals == hi)
        keep = ~out_of_range
        quality = np.where(at_limit, "suspect", "ok")
        flag_str = np.where(at_limit, np.char.add(flags.astype(str), ";sensor_limit_value"), flags.astype(str))
        tmin = ((times - times.iloc[0]).dt.total_seconds() / 60).to_numpy(float) if rows.size else np.array([])
        steps = np.diff(tmin) if rows.size > 1 else np.array([])
        stats.update({
            "present": True,
            "native_samples": int(keep.sum()),
            "out_of_range_dropped": int(out_of_range.sum()),
            "sensor_limit_values": int(at_limit.sum()),
            "cadence_minutes_median": float(np.median(steps)) if steps.size else None,
            "cadence_share_nominal": float(np.mean(steps == dcfg["nominal_cadence_minutes"])) if steps.size else None,
            "gaps_over_15_min": int(np.sum(steps > 15)) if steps.size else 0,
        })
        device_stats[device] = stats
        g = pd.DataFrame({
            "event_id": [f"{pid}-{device}-{i:05d}" for i in range(int(keep.sum()))],
            "observed_at": times[keep].to_numpy(),
            "value_mg_dl": vals[keep].astype(float),
            "quality": quality[keep].astype(str),
            "flags": flag_str[keep].astype(str),
            "source": f"{SOURCE_PREFIX}:{device}",
        })
        g["observed_at"] = pd.to_datetime(g["observed_at"], utc=True)
        g["available_at"] = g["observed_at"] + pd.Timedelta(minutes=avail_cfg["sensor_latency_minutes"])
        glucose_tables[device] = g
    audit["devices"] = device_stats

    # ---- activity: trailing 5-minute summaries ending on the source 5-minute grid
    window = int(norm["activity_window_minutes"])
    act = pd.DataFrame({
        "_t": grid["_t"],
        "hr": pd.to_numeric(grid["HR"], errors="coerce") if "HR" in grid else np.nan,
        "mets": pd.to_numeric(grid["METs"], errors="coerce") / 10.0 if "METs" in grid else np.nan,
        "kcal": pd.to_numeric(grid["Calories (Activity)"], errors="coerce") if "Calories (Activity)" in grid else np.nan,
    })
    # window ending at e covers minutes (e - 5min, e]; label each minute by its window end
    minute_of = (act["_t"] - act["_t"].dt.floor("D")).dt.total_seconds() // 60
    end = act["_t"] + pd.to_timedelta((window - (minute_of % window)) % window, unit="min")
    act["_end"] = end
    act["_covered"] = act[["hr", "mets", "kcal"]].notna().any(axis=1).astype(int)
    agg = act.groupby("_end").agg(
        heart_rate_bpm=("hr", "mean"), mets=("mets", "mean"), activity_kcal=("kcal", lambda s: s.sum(min_count=1)),
        minutes_covered=("_covered", "sum"), minutes_in_grid=("_covered", "size"),
    ).reset_index()
    agg = agg[agg["minutes_covered"] > 0].reset_index(drop=True)
    act_flags = []
    if "METs" not in grid:
        act_flags.append("mets_not_in_source")
    if "Calories (Activity)" not in grid:
        act_flags.append("activity_kcal_not_in_source")
    activity = pd.DataFrame({
        "event_id": [f"{pid}-act-{i:05d}" for i in range(len(agg))],
        "observed_at": agg["_end"],
        "available_at": agg["_end"] + pd.Timedelta(minutes=avail_cfg["activity_latency_minutes"]),
        "window_minutes": window,
        "minutes_covered": agg["minutes_covered"].astype(int),
        "heart_rate_bpm": agg["heart_rate_bpm"].round(2),
        "mets": agg["mets"].round(3),
        "activity_kcal": agg["activity_kcal"].round(3),
        "quality": np.where(agg["minutes_covered"] < window, "estimated", "ok"),
        "flags": ";".join(act_flags),
        "source": f"{SOURCE_PREFIX}:fitbit_sense",
    })
    audit["activity_windows"] = int(len(activity))
    audit["activity_minutes_covered_fraction"] = round(float(act["_covered"].mean()), 4)

    # ---- meals
    meal_rows = raw[raw["Meal Type"].notna()].copy() if "Meal Type" in raw else raw.iloc[0:0]
    meal_rows["_t"] = canon(meal_rows["_ts"])
    mt = meal_rows["Meal Type"].astype(str).str.strip().str.lower().map(MEAL_TYPES)
    audit["meal_type_unmapped"] = int(mt.isna().sum())

    def num(col: str) -> pd.Series:
        if col in meal_rows:
            return pd.to_numeric(meal_rows[col], errors="coerce").astype(float)
        return pd.Series(np.nan, index=meal_rows.index, dtype=float)

    meals = pd.DataFrame({
        "event_id": [f"{pid}-meal-{i:03d}" for i in range(len(meal_rows))],
        "observed_at": meal_rows["_t"].to_numpy(),
        "available_at": (meal_rows["_t"] + pd.Timedelta(minutes=avail_cfg["meal_display_latency_minutes"])).to_numpy(),
        "meal_type": mt.fillna("Unspecified").to_numpy(),
        "energy_kcal": num("Calories").to_numpy(), "carbs_g": num("Carbs").to_numpy(),
        "protein_g": num("Protein").to_numpy(), "fat_g": num("Fat").to_numpy(), "fiber_g": num("Fiber").to_numpy(),
        "amount_consumed_pct": num("Amount Consumed").to_numpy(),
        "quality": "estimated",
        "flags": "macros_estimated;timestamp_from_photo;logging_latency_unknown",
        "source": f"{SOURCE_PREFIX}:meal_log",
    })
    audit["meals"] = int(len(meals))

    # ---- profile (baseline, measured at screening on study day 1)
    start_t = grid["_t"].min()
    profile = build_profile(bio_row, start_t)
    a1c = _to_float(bio_row.get("A1c PDL (Lab)"))
    cohort = "Type 2 diabetes" if a1c is not None and a1c > 6.4 else (
        "Pre-diabetes" if a1c is not None and a1c >= 5.7 else ("No diabetes" if a1c is not None else "Unknown"))

    primary = norm["primary_device"]
    pg = glucose_tables.get(primary)
    span_h = 0.0
    if pg is not None and len(pg) > 1:
        span_h = (pg["observed_at"].max() - pg["observed_at"].min()).total_seconds() / 3600
    eligible = cohort == "Type 2 diabetes" and pg is not None and span_h >= norm["min_recording_hours_for_primary"]
    reason = None
    if cohort != "Type 2 diabetes":
        reason = f"Cohort '{cohort}' is outside the primary Type 2 analysis."
    elif pg is None or not len(pg):
        reason = "No primary-device (Dexcom) readings."
    elif not eligible:
        reason = f"Primary-device span {span_h:.1f} h below the {norm['min_recording_hours_for_primary']} h minimum."
    exp_samples = span_h * 60 / 5 + 1 if span_h else 0
    coverage = {
        "primary_device": primary,
        "native_cadence_minutes": float(norm["devices"][primary]["nominal_cadence_minutes"]),
        "recording_days": round(span_h / 24, 2),
        "glucose_samples": int(len(pg)) if pg is not None else 0,
        # capped at 1: minute-rounded native timestamps occasionally produce 4-minute intervals
        "glucose_coverage_fraction": round(min(1.0, len(pg) / exp_samples), 3) if exp_samples else None,
        "gaps_over_threshold": device_stats.get(primary, {}).get("gaps_over_15_min"),
        "meals_logged": int(len(meals)),
        "activity_coverage_fraction": audit["activity_minutes_covered_fraction"],
    }
    meta = {
        "patient_id": pid,
        "display_alias": "",  # assigned after all participants are known
        "mode": "dataset_replay",
        "sort_key": "",
        "visible": True,
        "dataset": {"name": cfg["dataset"]["name"], "version": cfg["dataset"]["version"],
                    "license": cfg["dataset"]["license"], "citation_url": cfg["dataset"]["doi"], "synthetic": False},
        "cohort": {"label": cohort,
                   "provenance": "CGMacros documented HbA1c criterion at screening (T2D: HbA1c > 6.4%); "
                                 "not a diagnosis made by GlucoTwin."},
        "eligible_for_primary_analysis": bool(eligible),
        "exclusion_reason": reason,
        "primary_device": primary,
        "native_cadence_minutes": coverage["native_cadence_minutes"],
        "timeline_start": start_t.isoformat(),
        "timeline_end": grid["_t"].max().isoformat(),
        "coverage": coverage,
        "time_policy": {
            "policy_id": tp["policy_id"], "description": " ".join(tp["description"].split()),
            "source_timezone_known": False, "calendar_values_synthetic": True,
        },
        "availability_policy_id": avail_cfg["policy_id"],
        "notes": [
            "Recorded research data replayed as if arriving; the study CGMs were blinded to participants.",
            "Native Dexcom readings recovered from a 1-minute interpolated table (timestamps to the minute).",
            "Meal macronutrients were estimated by the study team; meals are context only in the primary model.",
        ],
        "adapter_version": ADAPTER_VERSION,
    }
    pdata = PatientData(meta, profile, glucose_tables.get(primary, pd.DataFrame()), activity, meals)
    pdata.extras["glucose_by_device"] = glucose_tables
    private = {"source_key": source_key, "patient_id": pid, "source_first_day": str(first_day.date()),
               "synthetic_offset_days": int(offset / pd.Timedelta(days=1))}
    audit.update({"patient_id": pid, "cohort": cohort, "eligible": bool(eligible), "exclusion_reason": reason,
                  "primary_span_hours": round(span_h, 2)})
    return pdata, {"audit": audit, "private": private}


def _to_float(x: Any) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


PROFILE_MAP = [
    # name, label, source column, unit, transform, suspect codes, model feature
    ("age", "Age", "Age", "years", None, (), True),
    ("sex_male", "Sex (male = 1)", "Gender", None, "sex", (), True),
    ("bmi", "BMI", "BMI", "kg/m²", "round2", (), True),
    ("body_weight", "Body weight", "Body weight", "kg", "lb_to_kg", (), False),
    ("height", "Height", "Height", "cm", "in_to_cm", (), False),
    ("ethnicity", "Self-identified ethnicity", "Self-identify", None, "str", (), False),
    ("hba1c", "HbA1c", "A1c PDL (Lab)", "%", None, (), True),
    ("fasting_glucose", "Fasting glucose", "Fasting GLU - PDL (Lab)", "mg/dL", None, (), True),
    ("fasting_insulin", "Fasting insulin", "Insulin", "µU/mL", None, (), True),
    ("triglycerides", "Triglycerides", "Triglycerides", "mg/dL", None, (), True),
    ("total_cholesterol", "Total cholesterol", "Cholesterol", "mg/dL", None, (), False),
    ("hdl", "HDL cholesterol", "HDL", "mg/dL", None, (), True),
    ("ldl", "LDL cholesterol (calculated)", "LDL (Cal)", "mg/dL", None, (800,), False),
    ("vldl", "VLDL cholesterol (calculated)", "VLDL (Cal)", "mg/dL", None, (400,), False),
]


def build_profile(bio_row: pd.Series, available_at: pd.Timestamp) -> list[dict[str, Any]]:
    row = {str(k).strip(): v for k, v in bio_row.items()}
    out = []
    for name, label, col, unit, transform, suspect, _model in PROFILE_MAP:
        raw = row.get(col)
        value: Any = None
        status = "available"
        note = None
        if raw is None or (isinstance(raw, float) and np.isnan(raw)) or (isinstance(raw, str) and not raw.strip()):
            status, note = "missing_in_source", "Not recorded in bio.csv"
        elif transform == "sex":
            value = {"M": 1.0, "F": 0.0}.get(str(raw).strip().upper())
            if value is None:
                status, note = "missing_in_source", f"Unrecognized value {raw!r}"
        elif transform == "str":
            value = str(raw).strip()
        else:
            f = _to_float(raw)
            if f is None:
                status, note = "missing_in_source", f"Non-numeric value {raw!r}"
            elif f in suspect:
                status, note = "excluded_suspect", f"Source value {f:g} is a documented error code"
            else:
                if transform == "lb_to_kg":
                    f = round(f * 0.45359237, 1)
                    note = "Converted from pounds (x 0.45359237)"
                elif transform == "in_to_cm":
                    f = round(f * 2.54, 1)
                    note = "Converted from inches (x 2.54)"
                elif transform == "round2":
                    f = round(f, 2)
                value = f
        if name == "hba1c" and status == "available":
            note = "Data dictionary states mmol/mol; the 4.6-8.5 range is consistent with % (NGSP)."
        out.append({
            "name": name, "label": label, "value": value, "unit": unit,
            "source": f"{SOURCE_PREFIX}:bio.csv:{col}",
            "available_at": available_at.isoformat() if status != "missing_in_source" else None,
            "status": status, "note": note,
            "availability_rule": "Screening labs on study day 1; assumed available at twin initialization "
                                 "(start of the recording). Lab turnaround is not documented.",
        })
    return out


def participant_files(tables_dir: Path) -> dict[str, Path]:
    out = {}
    for p in sorted(tables_dir.glob("CGMacros-*.csv")):
        m = re.search(r"CGMacros-(\d+)\.csv$", p.name)
        if m:
            out[f"CGMacros-{int(m.group(1)):03d}"] = p
    return out
