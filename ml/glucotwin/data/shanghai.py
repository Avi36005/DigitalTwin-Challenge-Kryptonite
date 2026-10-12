"""ShanghaiT2DM (figshare 21600933 v5) -> canonical records + model store (``shanghai-adapter-1.0``).

Evidence behind the mapping (measured on the verified archive, see reports/dataset_expansion_audit.md):

* ``Shanghai_T2DM/<patient>_<visit>_<yyyymmdd>.xls[x]``: one sheet per recording with ``Date`` and ``CGM (mg / dl)``
  every 15 minutes (FreeStyle Libre H, per the data descriptor). Several files can belong to one participant; they are
  separate recordings of ONE person. The visit index is not chronological (e.g. visit 1 can precede visit 0), so
  recordings are ordered by their first timestamp.
* Values are declared in mg/dL; every numeric value is a multiple of 1.8 (mmol/L with one decimal x 18 upstream).
  They are kept as declared (no second conversion). Two files lack the unit in the header; the dataset convention
  (mg/dL in the other 107 files, matching magnitudes) is recorded as ``unit_from_dataset_convention``.
* Device reporting range (FreeStyle Libre family): 2.2-27.8 mmol/L = 39.6-500.4 mg/dL. Values at a limit are
  ``suspect``; values outside are ``invalid``. This range is an engineering assumption, not stated by the dataset.
* Native 15-minute readings are retained as they are; nothing is upsampled or interpolated.
* Timestamps are local wall-clock times without a documented timezone. The calendar date is replaced by synthetic
  study days (policy ``synthetic-utc-day-aligned-v1``) exactly as for CGMacros; the offset is stored privately.
* Summary-sheet labs were taken up to 6 months before or after CGM without dates, so they are never causally
  available; demographics/labs are kept for the audit with ``available_at = null``.
* Capillary glucose, ketones, diet and medication columns are counted for the audit only (not model inputs).
* T1DM files in the same archive are outside the Type 2 population and are not imported (counted only).
"""

from __future__ import annotations

import hashlib
import io
import json
import resource
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import load_config, paths
from glucotwin.data import canonical as cn
from glucotwin.data.store import PatientData, Store, empty_table, to_minutes

ADAPTER_VERSION = "shanghai-adapter-1.0"
DATASET_ID = "shanghai_t2dm"
DEVICE_ID = "freestyle_libre_h"
NATIVE_CADENCE = 15.0
VALID_RANGE = (39.6, 500.4)
AVAILABILITY = ("replay-zero-latency: Libre H readings were stored on the sensor and retrieved by scanning; real-time "
                "availability is undocumented, so replay releases each reading at its own timestamp")
ORIGINAL_TZ = "undocumented (recorded in Shanghai, China; not verified)"
AUDIT_COLUMNS = {"cbg": "CBG", "ketone": "Blood Ketone", "diet": "Dietary intake", "insulin_sc": "Insulin dose - s.c.",
                 "oral_agents": "Non-insulin hypoglycemic agents", "insulin_iv": "Insulin dose - i.v."}


class ShanghaiError(RuntimeError):
    pass


def source_cfg() -> dict[str, Any]:
    return load_config("sources")["sources"][DATASET_ID]


def raw_dir() -> Path:
    return paths().raw / source_cfg()["raw_subdir"]


def store_dir() -> Path:
    return paths().processed / source_cfg()["processed_subdir"]


def canonical_root() -> Path:
    return paths().processed / "canonical"


# ------------------------------------------------------------------------------------------------ acquisition


def _md5(path: Path) -> str:
    h = hashlib.md5()  # noqa: S324 - integrity check against the publisher's MD5, not security
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(force: bool = False) -> dict[str, Any]:
    """Fetch the archive (resumable) and verify the publisher's size and MD5. Idempotent."""
    from glucotwin.data.acquire import _fetch

    cfg = source_cfg()
    d = raw_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / cfg["archive"]
    transferred = 0
    if force or not dest.exists():
        before = dest.with_suffix(dest.suffix + ".part")
        start = before.stat().st_size if before.exists() else 0
        _fetch(cfg["download_url"], dest)
        transferred = dest.stat().st_size - start
    out = verify()
    out["transferred_bytes_this_call"] = transferred
    return out


def verify() -> dict[str, Any]:
    cfg = source_cfg()
    path = raw_dir() / cfg["archive"]
    if not path.exists():
        raise ShanghaiError(f"Missing {path}. Run `glucotwin data download --dataset shanghai_t2dm`.")
    size, md5 = path.stat().st_size, _md5(path)
    if size != int(cfg["expected_bytes"]) or md5 != cfg["expected_md5"]:
        raise ShanghaiError(f"{path.name}: size {size} / md5 {md5} differ from the published "
                            f"{cfg['expected_bytes']} / {cfg['expected_md5']}; delete it and download again.")
    return {"file": path.name, "size_bytes": size, "md5": md5, "sha256": cn.file_hash(path), "verified": True}


# ------------------------------------------------------------------------------------------------ parsing


@dataclass
class Recording:
    member: str
    source_pid: str
    visit: int
    file_date: str
    sha256: str
    frame: pd.DataFrame


def _safe(name: str) -> bool:
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and "__MACOSX" not in p.parts and not p.name.startswith(".")


def _read_sheet(data: bytes, name: str) -> pd.DataFrame:
    engine = "openpyxl" if name.lower().endswith(".xlsx") else "xlrd"
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, engine=engine)
    if len(sheets) != 1:
        raise ShanghaiError(f"{name}: expected one sheet, found {len(sheets)}")
    df = next(iter(sheets.values()))
    df.columns = [str(c).strip() for c in df.columns]
    return df


def read_archive(zpath: Path) -> tuple[list[Recording], pd.DataFrame, dict[str, Any]]:
    """Recordings of the T2DM folder + the T2DM summary sheet. Archive contents are only read, never executed."""
    recs: list[Recording] = []
    info = {"t1dm_files_not_imported": 0, "skipped_members": 0}
    with zipfile.ZipFile(zpath) as zf:
        for m in zf.infolist():
            name = m.filename
            if m.is_dir() or not _safe(name):
                info["skipped_members"] += 1
                continue
            if name.startswith("Shanghai_T1DM/") and name.lower().endswith((".xls", ".xlsx")):
                info["t1dm_files_not_imported"] += 1
                continue
            if not (name.startswith("Shanghai_T2DM/") and name.lower().endswith((".xls", ".xlsx"))):
                continue
            stem = PurePosixPath(name).name.rsplit(".", 1)[0]
            parts = stem.split("_")
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                raise ShanghaiError(f"Unexpected recording file name {name!r}")
            data = zf.read(m)
            recs.append(Recording(name, parts[0], int(parts[1]), parts[2], cn.bytes_hash(data), _read_sheet(data, name)))
        summary = _read_sheet(zf.read("Shanghai_T2DM_Summary.xlsx"), "Shanghai_T2DM_Summary.xlsx")
    return recs, summary, info


def _cgm_column(df: pd.DataFrame) -> tuple[str, str, str]:
    """(column, declared unit, unit provenance)."""
    cands = [c for c in df.columns if c.startswith("CGM")]
    if len(cands) != 1:
        raise ShanghaiError(f"Expected one CGM column, found {cands}")
    c = cands[0]
    norm = c.lower().replace(" ", "")
    if "(mg/dl)" in norm:
        return c, "mg/dL", "header"
    if norm == "cgm":
        return c, "mg/dL", "unit_from_dataset_convention"
    raise ShanghaiError(f"Undeclared CGM unit in header {c!r}")


def _pseudonym(source_pid: str) -> str:
    from glucotwin.data.cgmacros import _salt

    digest = hashlib.sha256(f"{_salt()}:{DATASET_ID}:{source_pid}".encode()).hexdigest()
    return f"sh-{digest[:6]}"


def normalize_participant(source_pid: str, recs: list[Recording], summary_rows: pd.DataFrame,
                          data_cfg: dict[str, Any]) -> tuple[PatientData, pd.DataFrame, dict[str, Any]]:
    pid = _pseudonym(source_pid)
    tp = data_cfg["time_policy"]
    parts, rec_audit = [], []
    for r in recs:
        df = r.frame
        col, unit, unit_src = _cgm_column(df)
        ts = pd.to_datetime(df["Date"], errors="coerce")
        parsed = [cn.parse_glucose_value(v, unit, VALID_RANGE) for v in df[col].tolist()]
        rid = f"{pid}-r{r.visit}"
        p = pd.DataFrame({
            "recording_id": rid, "_source_ts": ts, "_row": np.arange(len(df)),
            "original_value": df[col].astype("string").fillna(""), "original_unit": unit,
            "glucose_mg_dl": [x.mg_dl if x.mg_dl is not None else np.nan for x in parsed],
            "quality": [x.quality for x in parsed], "missing_reason": [x.missing_reason for x in parsed],
            "unit_conversion": [x.conversion or ("" if unit_src == "header" else unit_src) for x in parsed],
            "source_file_hash": r.sha256, "source_record_id": [f"{PurePosixPath(r.member).name}#row{i + 2}"
                                                               for i in range(len(df))],
        })
        counts = cn.flag_timestamp_anomalies(p)
        steps = ts.dropna().diff().dt.total_seconds().div(60).dropna()
        vals = p["glucose_mg_dl"].to_numpy(float)
        fin = vals[np.isfinite(vals)]
        rec_audit.append({
            "recording_id": rid, "file": PurePosixPath(r.member).name, "sha256": r.sha256, "rows": int(len(df)),
            "unit": unit, "unit_source": unit_src, **counts,
            "missing_cgm_cells": int(df[col].isna().sum()),
            "sensor_codes": int(p["quality"].isin(["sensor_low", "sensor_high"]).sum()),
            "invalid_values": int(((p["quality"] == "invalid") & (p["missing_reason"] != "missing_value")).sum()),
            "limit_values": int((p["quality"] == "suspect").sum()),
            "share_multiple_of_1_8": float(np.mean(np.abs(fin / 1.8 - np.rint(fin / 1.8)) < 1e-6)) if fin.size else None,
            "step_share_15min": float(np.mean(np.abs(steps - 15.0) < 0.5)) if len(steps) else None,
            "audit_only_columns": {k: int(df[c].notna().sum()) for k, c in
                                   ((k, next((x for x in df.columns if x.startswith(v)), None))
                                    for k, v in AUDIT_COLUMNS.items()) if c is not None},
        })
        parts.append(p)
    allp = pd.concat(parts, ignore_index=True)
    valid_ts = allp["_source_ts"].dropna()
    if valid_ts.empty:
        raise ShanghaiError(f"Participant {source_pid}: no parseable timestamps")
    first_day = valid_ts.min().normalize()
    offset = pd.Timestamp(tp["synthetic_origin"]).tz_localize(None) - first_day
    allp["observed_at"] = (allp["_source_ts"] + offset).dt.tz_localize("UTC")
    overlap = cn.drop_cross_recording_overlap(allp)
    canon = pd.DataFrame({
        "dataset_id": DATASET_ID, "dataset_version": "figshare-21600933.v5", "patient_id": pid,
        "recording_id": allp["recording_id"], "device_id": DEVICE_ID, "source_record_id": allp["source_record_id"],
        "observed_at": allp["observed_at"], "available_at": allp["observed_at"],
        "original_timestamp": allp["_source_ts"].dt.strftime("%Y-%m-%d %H:%M:%S").fillna(""),
        "original_timezone": ORIGINAL_TZ, "native_cadence_minutes": NATIVE_CADENCE,
        "glucose_mg_dl": allp["glucose_mg_dl"], "original_value": allp["original_value"],
        "original_unit": allp["original_unit"], "unit_conversion": allp["unit_conversion"],
        "quality": allp["quality"], "missing_reason": allp["missing_reason"],
        "source_file_hash": allp["source_file_hash"], "parser_version": ADAPTER_VERSION,
        "availability_assumption": AVAILABILITY,
    })
    canon = cn.conform_canonical(canon)
    glucose = cn.model_glucose_table(canon, pid, f"{DATASET_ID}:{DEVICE_ID}")
    t = to_minutes(glucose["observed_at"])
    obs_h = cn.observed_minutes(t, NATIVE_CADENCE) / 60.0
    span_h = float((t.max() - t.min()) / 60.0) if t.size > 1 else 0.0
    first_rows = summary_rows.iloc[0] if len(summary_rows) else pd.Series(dtype=object)
    profile = _profile(first_rows)
    min_obs = float(load_config("sources")["sources"][DATASET_ID].get("min_observed_hours", 72))
    eligible = obs_h >= min_obs
    recordings = []
    for rid, g in canon[canon["quality"].isin(cn.USABLE_QUALITIES)].groupby("recording_id"):
        recordings.append({"recording_id": rid, "readings": int(len(g)), "start": g["observed_at"].min().isoformat(),
                           "end": g["observed_at"].max().isoformat()})
    coverage = {
        "primary_device": DEVICE_ID, "native_cadence_minutes": NATIVE_CADENCE,
        "recording_days": round(span_h / 24, 2), "glucose_samples": int(len(glucose)),
        "observed_hours": round(obs_h, 2), "calendar_days_with_readings": cn.calendar_days_with_readings(glucose["observed_at"]),
        "glucose_coverage_fraction": None, "gaps_over_threshold": cn.long_gaps(t, 60.0),
        "meals_logged": 0, "activity_coverage_fraction": None,
    }
    meta = {
        "patient_id": pid, "display_alias": "", "mode": "research_external", "sort_key": "", "visible": False,
        "dataset": {"name": "ShanghaiT2DM", "version": "figshare-21600933.v5", "license": "CC BY 4.0",
                    "citation_url": "https://doi.org/10.6084/m9.figshare.21600933.v5", "synthetic": False},
        "dataset_id": DATASET_ID,
        "cohort": {"label": "Type 2 diabetes", "provenance": "Diagnosed T2DM (WHO 1999) per the ShanghaiT2DM data "
                                                             "descriptor; not a diagnosis made by GlucoTwin."},
        "eligible_for_primary_analysis": False,
        "eligible_for_portable_external": bool(eligible),
        "exclusion_reason": None if eligible else f"{obs_h:.1f} observed hours below the {min_obs:g} h minimum.",
        "primary_device": DEVICE_ID, "native_cadence_minutes": NATIVE_CADENCE,
        "timeline_start": glucose["observed_at"].min().isoformat(), "timeline_end": glucose["observed_at"].max().isoformat(),
        "coverage": coverage, "recordings": recordings,
        "time_policy": {"policy_id": tp["policy_id"], "description": " ".join(tp["description"].split()),
                        "source_timezone_known": False, "calendar_values_synthetic": True},
        "availability_policy_id": "replay-zero-latency",
        "notes": ["Native 15-minute FreeStyle Libre H readings; several recordings of one person are kept separate.",
                  "Summary labs lack dates (up to 6 months from CGM) and are never model inputs."],
        "adapter_version": ADAPTER_VERSION,
    }
    pdata = PatientData(meta, profile, glucose, empty_table("activity"), empty_table("meals"))
    audit = {"patient_id": pid, "source_patient": source_pid, "recordings": rec_audit,
             "cross_recording_overlap_marked_duplicate": overlap, "observed_hours": round(obs_h, 2),
             "native_readings": int(len(glucose)), "eligible": bool(eligible),
             "excluded_rows_by_reason": canon.loc[~canon["quality"].isin(cn.USABLE_QUALITIES), "missing_reason"]
             .value_counts().to_dict()}
    private = {"source_patient": source_pid, "patient_id": pid, "synthetic_offset_days": int(offset / pd.Timedelta(days=1))}
    return pdata, canon, {"audit": audit, "private": private}


SUMMARY_PROFILE = [
    ("age", "Age", "Age (years)", "years"), ("sex_male", "Sex (male = 1)", "Gender (Female=1, Male=2)", None),
    ("bmi", "BMI", "BMI (kg/m2)", "kg/m²"), ("hba1c_mmol_mol", "HbA1c", "HbA1c (mmol/mol)", "mmol/mol"),
    ("diabetes_duration", "Duration of diabetes", "Duration of diabetes (years)", "years"),
]


def _profile(row: pd.Series) -> list[dict[str, Any]]:
    out = []
    for name, label, col, unit in SUMMARY_PROFILE:
        raw = row.get(col) if len(row) else None
        val = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
        if name == "sex_male" and pd.notna(val):
            val = {1: 0.0, 2: 1.0}.get(int(val))
        present = val is not None and pd.notna(val)
        out.append({"name": name, "label": label, "value": float(val) if present else None, "unit": unit,
                    "source": f"{DATASET_ID}:Shanghai_T2DM_Summary.xlsx:{col}", "available_at": None,
                    "status": "timing_unknown" if present else "missing_in_source",
                    "note": "Recorded up to 6 months before or after CGM without a date; never a causal model input.",
                    "availability_rule": "Not causally available at any forecast origin."})
    return out


def import_shanghai() -> dict[str, Any]:
    """Verify -> parse -> canonical partitions + model store + audit + provenance. Idempotent, bounded memory per person."""
    t0 = time.perf_counter()
    cfg = source_cfg()
    data_cfg = load_config("data")
    ver = verify()
    recs, summary, info = read_archive(raw_dir() / cfg["archive"])
    summary["_stem"] = summary["Patient Number"].astype(str).str.strip()
    by_pid: dict[str, list[Recording]] = {}
    for r in recs:
        by_pid.setdefault(r.source_pid, []).append(r)
    sd = store_dir()
    store = Store(sd)
    audits, private, failed = [], [], []
    pdatas = []
    for spid in sorted(by_pid):
        rs = sorted(by_pid[spid], key=lambda r: r.member)
        rows = summary[summary["_stem"].isin([PurePosixPath(r.member).name.rsplit(".", 1)[0] for r in rs])]
        try:
            pdata, canon, inf = normalize_participant(spid, rs, rows, data_cfg)
        except (ShanghaiError, ValueError) as exc:
            failed.append({"source_patient": spid, "error": str(exc)})
            continue
        cn.write_canonical(canonical_root(), canon)
        pdatas.append(pdata)
        audits.append(inf["audit"])
        private.append(inf["private"])
    ids = [p.patient_id for p in pdatas]
    if len(set(ids)) != len(ids):
        raise ShanghaiError("Pseudonym collision; refusing to merge two people")
    for i, p in enumerate(sorted(pdatas, key=lambda p: p.patient_id), start=1):
        p.meta["display_alias"] = f"Shanghai participant {i:03d}"
        p.meta["sort_key"] = f"{i:03d}"
        store.write_patient(p)
    pmap = paths().private / "shanghai_pseudonym_map.json"
    pmap.parent.mkdir(parents=True, exist_ok=True)
    pmap.write_text(json.dumps(private, indent=2))
    store.set_info("mode", "research_external")
    store.set_info("adapter_version", ADAPTER_VERSION)
    store.set_info("license", cfg["license"])
    store.set_info("dataset", {"name": cfg["name"], "version": cfg["release"], "doi": cfg["doi"], "license": cfg["license"]})
    prov = {"dataset_id": DATASET_ID, "dataset": cfg["name"], "release": cfg["release"], "doi": cfg["doi"],
            "license": cfg["license"], "license_url": cfg["license_url"], "citation": " ".join(cfg["citation"].split()),
            "retrieved_at": _previous(sd / "provenance.json", "retrieved_at") or datetime.now(UTC).isoformat(timespec="seconds"),
            "parser_version": ADAPTER_VERSION, "canonical_schema": cn.CANONICAL_SCHEMA_VERSION,
            "files": [ver], "recordings": [{"file": a["file"], "sha256": a["sha256"]} for x in audits for a in x["recordings"]]}
    (sd / "provenance.json").write_text(json.dumps(prov, indent=2) + "\n")
    summary_audit = {
        "adapter_version": ADAPTER_VERSION, "participants": audits, "failed": failed, **info,
        "summary_rows": int(len(summary)), "summary_columns": [c for c in summary.columns if c != "_stem"],
        "duration_seconds": round(time.perf_counter() - t0, 2),
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }
    (sd / "audit.json").write_text(json.dumps(summary_audit, indent=2, default=str))
    store.log_import({"adapter_version": ADAPTER_VERSION, "participants": len(pdatas), "failed": len(failed)})
    return {"store": str(sd), "participants": len(pdatas), "recordings": sum(len(a["recordings"]) for a in audits),
            "failed": len(failed), "t1dm_files_not_imported": info["t1dm_files_not_imported"],
            "duration_seconds": summary_audit["duration_seconds"]}


def _previous(path: Path, key: str):
    try:
        return json.loads(path.read_text()).get(key)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
