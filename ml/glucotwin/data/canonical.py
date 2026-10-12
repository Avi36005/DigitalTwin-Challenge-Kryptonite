"""Canonical, provenance-carrying CGM records shared by every source adapter (``canonical-cgm-1``).

The model-facing store (``glucotwin.data.store``) keeps its compact schema so the v1/v2 experiments reproduce byte for
byte. This layer sits beside it: one partitioned Parquet file per (dataset, participant) with the full provenance of
every native reading, including readings the model tables drop (sensor LOW/HIGH codes, impossible timestamps,
duplicates). Model tables are derived from it, never the other way round.

Time fields are kept apart on purpose:

* ``observed_at``        physiology time on the canonical (synthetic, day-aligned UTC) timeline;
* ``available_at``       when the reading is released to the twin under the declared replay assumption;
* ``original_timestamp`` the source's own wall-clock string, untouched; ``original_timezone`` says what is known of it.

Import/export times of files are provenance, not physiology, and live in the source manifest.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CANONICAL_SCHEMA_VERSION = "canonical-cgm-1"
MMOL_TO_MG_DL = 18.0  # declared conversion factor (clinical convention); the factor is stored with every converted row

CANONICAL_COLUMNS: dict[str, str] = {
    "dataset_id": "string",
    "dataset_version": "string",
    "patient_id": "string",
    "recording_id": "string",
    "device_id": "string",
    "source_record_id": "string",
    "observed_at": "datetime64[ns, UTC]",
    "available_at": "datetime64[ns, UTC]",
    "original_timestamp": "string",
    "original_timezone": "string",
    "native_cadence_minutes": "float64",
    "glucose_mg_dl": "float64",
    "original_value": "string",
    "original_unit": "string",
    "unit_conversion": "string",
    "quality": "string",          # ok | suspect | sensor_low | sensor_high | invalid | duplicate
    "missing_reason": "string",   # why glucose_mg_dl is null or the row is not model-eligible ("" when usable)
    "source_file_hash": "string",
    "parser_version": "string",
    "availability_assumption": "string",
}
USABLE_QUALITIES = ("ok", "suspect")
LOW_CODES = {"low", "lo", "<40", "below range"}
HIGH_CODES = {"high", "hi", ">400", ">500", "above range"}


def conform_canonical(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in CANONICAL_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"canonical table missing columns {missing}")
    out = df[list(CANONICAL_COLUMNS)].copy()
    for c, t in CANONICAL_COLUMNS.items():
        if t.startswith("datetime64"):
            out[c] = pd.to_datetime(out[c], utc=True)
        elif t == "string":
            out[c] = out[c].astype("string").fillna("")
        else:
            out[c] = out[c].astype(t)
    key = ["dataset_id", "patient_id", "recording_id", "source_record_id"]
    if out.duplicated(key).any():
        raise ValueError("canonical table has duplicate (dataset, patient, recording, source record) keys")
    return out.sort_values(["observed_at", "recording_id", "source_record_id"], kind="mergesort").reset_index(drop=True)


def canonical_path(root: Path, dataset_id: str, patient_id: str) -> Path:
    return root / CANONICAL_SCHEMA_VERSION / f"dataset_id={dataset_id}" / f"patient_id={patient_id}" / "glucose.parquet"


def write_canonical(root: Path, df: pd.DataFrame) -> Path:
    df = conform_canonical(df)
    ds, pids = df["dataset_id"].unique(), df["patient_id"].unique()
    if len(ds) != 1 or len(pids) != 1:
        raise ValueError("write_canonical expects exactly one (dataset, participant) partition")
    path = canonical_path(root, str(ds[0]), str(pids[0]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)
    return path


def model_glucose_table(df: pd.DataFrame, event_prefix: str, source: str) -> pd.DataFrame:
    """Derive the compact model-facing glucose table (``store.GLUCOSE_COLUMNS``) from canonical rows."""
    use = df[df["quality"].isin(USABLE_QUALITIES) & df["glucose_mg_dl"].notna()].reset_index(drop=True)
    flags = np.where(use["quality"].to_numpy(str) == "suspect", "sensor_limit_value", "")
    return pd.DataFrame({
        "event_id": [f"{event_prefix}-{r}-{i:05d}" for i, r in enumerate(use["recording_id"].astype(str))],
        "observed_at": use["observed_at"], "available_at": use["available_at"],
        "value_mg_dl": use["glucose_mg_dl"].astype(float), "quality": use["quality"].astype(str),
        "flags": flags, "source": source,
    })


# ------------------------------------------------------------------------------------------------ values and units


@dataclass(frozen=True)
class ParsedValue:
    mg_dl: float | None
    quality: str
    missing_reason: str
    conversion: str


def parse_glucose_value(raw: Any, unit: str, valid_range_mg_dl: tuple[float, float]) -> ParsedValue:
    """Parse one source value in its DECLARED unit. Sensor LOW/HIGH codes are kept as codes, never as numbers.

    Values equal to a reporting limit are ``suspect``; values outside the range are ``invalid`` (kept in the canonical
    layer, excluded from model tables)."""
    lo, hi = valid_range_mg_dl
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return ParsedValue(None, "invalid", "missing_value", "")
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in LOW_CODES:
            return ParsedValue(None, "sensor_low", "sensor_low_code", "")
        if s in HIGH_CODES:
            return ParsedValue(None, "sensor_high", "sensor_high_code", "")
        try:
            raw = float(s)
        except ValueError:
            return ParsedValue(None, "invalid", "non_numeric_value", "")
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return ParsedValue(None, "invalid", "non_numeric_value", "")
    if not math.isfinite(v):
        return ParsedValue(None, "invalid", "non_finite_value", "")
    u = unit.strip().lower().replace(" ", "")
    if u in ("mmol/l", "mmol/litre"):
        v, conv = v * MMOL_TO_MG_DL, f"mmol/L x {MMOL_TO_MG_DL:g}"
    elif u in ("mg/dl", "mg/dl(declared)"):
        conv = ""
    else:
        raise ValueError(f"Undeclared or unsupported glucose unit {unit!r}; refusing to guess")
    v = round(v, 6)
    if v < lo - 1e-6 or v > hi + 1e-6:
        return ParsedValue(v, "invalid", "outside_device_reporting_range", conv)
    if abs(v - lo) < 1e-6 or abs(v - hi) < 1e-6:
        return ParsedValue(v, "suspect", "", conv)
    return ParsedValue(v, "ok", "", conv)


# ------------------------------------------------------------------------------------------------ anomalies


def flag_timestamp_anomalies(df: pd.DataFrame, plausible: tuple[str, str] = ("1990-01-01", "2035-01-01")) -> dict:
    """Mark impossible timestamps and duplicate samples IN PLACE (quality/missing_reason) and count recording resets.

    ``df`` needs ``recording_id``, ``_source_ts`` (naive source datetime, NaT if unparseable), ``quality``,
    ``missing_reason`` and source order. Returns counts for the audit."""
    counts = {"unparseable_timestamps": 0, "implausible_timestamps": 0, "duplicate_samples": 0,
              "conflicting_duplicates": 0, "recording_resets": 0}
    ts = df["_source_ts"]
    bad = ts.isna()
    counts["unparseable_timestamps"] = int(bad.sum())
    lo, hi = pd.Timestamp(plausible[0]), pd.Timestamp(plausible[1])
    implausible = ~bad & ((ts < lo) | (ts > hi))
    counts["implausible_timestamps"] = int(implausible.sum())
    df.loc[bad | implausible, "quality"] = "invalid"
    df.loc[bad, "missing_reason"] = "unparseable_timestamp"
    df.loc[implausible, "missing_reason"] = "implausible_timestamp"
    for _rec, g in df[~(bad | implausible)].groupby("recording_id", sort=False):
        back = (g["_source_ts"].diff().dt.total_seconds() < 0).sum()
        counts["recording_resets"] += int(back)
        dup = g["_source_ts"].duplicated(keep="first")
        if dup.any():
            first_val = g.drop_duplicates("_source_ts", keep="first").set_index("_source_ts")["glucose_mg_dl"]
            vals = g.loc[dup, "glucose_mg_dl"].to_numpy(float)
            ref = first_val.reindex(g.loc[dup, "_source_ts"]).to_numpy(float)
            conflict = ~((np.isnan(vals) & np.isnan(ref)) | (np.abs(vals - ref) < 1e-9))
            counts["duplicate_samples"] += int(dup.sum())
            counts["conflicting_duplicates"] += int(conflict.sum())
            idx = g.index[dup]
            df.loc[idx, "quality"] = "duplicate"
            df.loc[idx, "missing_reason"] = "duplicate_timestamp_in_recording"
    return counts


def drop_cross_recording_overlap(df: pd.DataFrame) -> int:
    """Within one participant, a reading whose timestamp already exists in an EARLIER recording (by first timestamp)
    is a repeated/overlapping recording sample: mark it ``duplicate``. Returns the number marked."""
    usable = df["quality"].isin(USABLE_QUALITIES)
    starts = df[usable].groupby("recording_id")["observed_at"].min().sort_values()
    seen: set = set()
    marked = 0
    for rec in starts.index:
        rows = df.index[(df["recording_id"] == rec) & usable]
        t = df.loc[rows, "observed_at"]
        dup = t.isin(seen)
        if dup.any():
            df.loc[rows[dup.to_numpy()], ["quality", "missing_reason"]] = ["duplicate", "overlaps_earlier_recording"]
            marked += int(dup.sum())
        seen.update(t[~dup].tolist())
    return marked


# ------------------------------------------------------------------------------------------------ cadence


def causal_decimate(times_min: np.ndarray, step_minutes: float = 15.0) -> np.ndarray:
    """Boolean mask keeping the FIRST reading in each absolute ``step``-minute bin (bins anchored at the store epoch).

    Whether a reading is kept depends only on earlier readings, so decimation never uses future information. Nothing
    is interpolated; dropped readings are simply not part of the decimated history."""
    t = np.asarray(times_min, dtype=float)
    if t.size == 0:
        return np.zeros(0, dtype=bool)
    if np.any(np.diff(t) < 0):
        raise ValueError("causal_decimate expects times sorted ascending")
    b = np.floor(t / step_minutes + 1e-9)
    keep = np.ones(t.size, dtype=bool)
    keep[1:] = b[1:] != b[:-1]
    return keep


def observed_minutes(times_min: np.ndarray, cadence_minutes: float) -> float:
    """Gap-respecting observed time: every reading represents at most one native cadence interval."""
    t = np.sort(np.asarray(times_min, dtype=float))
    if t.size == 0:
        return 0.0
    d = np.diff(t)
    return float(np.minimum(d, cadence_minutes).sum() + cadence_minutes)


def calendar_days_with_readings(observed_at: pd.Series) -> int:
    return int(pd.to_datetime(observed_at, utc=True).dt.floor("D").nunique())


def long_gaps(times_min: np.ndarray, threshold_minutes: float) -> int:
    t = np.sort(np.asarray(times_min, dtype=float))
    return int((np.diff(t) > threshold_minutes).sum()) if t.size > 1 else 0


# ------------------------------------------------------------------------------------------------ overlap detection


def recording_signature(times_min: Iterable[float], values_mg_dl: Iterable[float], n: int = 6) -> set[int]:
    """Shift-invariant signature of a recording: hashed n-grams of (rounded interval, rounded mg/dL value).

    Two copies of the same recording (e.g. an original file and a harmonized collection copy with shifted dates or a
    unit round trip) share most n-grams; unrelated people almost never do. Used to refuse double counting."""
    t = np.asarray(list(times_min), dtype=float)
    v = np.asarray(list(values_mg_dl), dtype=float)
    ok = np.isfinite(t) & np.isfinite(v)
    t, v = t[ok], v[ok]
    order = np.argsort(t, kind="mergesort")
    t, v = t[order], v[order]
    if t.size < n + 1:
        return set()
    dt = np.rint(np.diff(t)).astype(int)
    vq = np.rint(v[1:] / 2.0).astype(int)  # 2 mg/dL buckets absorb mmol/L rounding round trips
    toks = list(zip(dt.tolist(), vq.tolist(), strict=True))
    out = set()
    for i in range(len(toks) - n + 1):
        h = hashlib.blake2b(repr(toks[i:i + n]).encode(), digest_size=8).digest()
        out.add(int.from_bytes(h, "big"))
    return out


def signature_overlap(a: set[int], b: set[int]) -> float:
    """Share of the smaller signature found in the other (0..1)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


OVERLAP_THRESHOLD = 0.5


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
