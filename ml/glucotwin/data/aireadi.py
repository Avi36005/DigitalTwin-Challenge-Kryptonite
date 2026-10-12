"""AI-READI v3 CGM adapter (``aireadi-cgm-adapter-1.0``) — built against the published documentation and FICTIONAL
fixtures only. No AI-READI record has been downloaded or inspected for this project (access requires the FAIRhub
workflow; see configs/sources.yaml ``ai_readi_v3.user_steps``).

Documented layout (docs.aireadi.org, dataset v3.0.0, "Continuous glucose monitor")::

    wearable_blood_glucose/manifest.tsv
    wearable_blood_glucose/continuous_glucose_monitoring/dexcom_g6/<participant>/<participant>_DEX.json

Each JSON follows an extended Open mHealth ``blood-glucose`` schema: ``header`` (uuid, patient_id, timezone,
acquisition_rate) and ``body.cgm`` — a list of readings with ``effective_time_frame.time_interval.start_date_time``,
``event_type`` (EGV), ``source_device_id``, ``blood_glucose {unit, value}``, ``transmitter_time``, ``transmitter_id``.

Governance: the documentation restricts uploading participant data to third-party LLM providers without an
institutional agreement. This module therefore runs locally, logs only aggregate counts, and must never print records.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.data import canonical as cn

ADAPTER_VERSION = "aireadi-cgm-adapter-1.0"
DATASET_ID = "ai_readi_v3"
DEVICE_ID = "dexcom_g6"
NATIVE_CADENCE = 5.0
VALID_RANGE = (40.0, 400.0)  # Dexcom G6 reporting range; LOW/HIGH codes outside it are kept as codes
CGM_SUBPATH = "wearable_blood_glucose/continuous_glucose_monitoring/dexcom_g6"
AVAILABILITY = "replay-zero-latency (Dexcom G6 real-time CGM; transmission latency not documented per reading)"

# Selective acquisition: path prefixes worth requesting. Everything else (retinal imaging, ECG, environment raw) is
# deliberately excluded to avoid terabytes of unrelated files.
SELECTED_PREFIXES = (
    "participants.tsv", "participants.json", "dataset_description.json", "README", "LICENSE", "CHANGELOG",
    "clinical_data/", "wearable_blood_glucose/", "wearable_activity_monitor/heart_rate/",
    "wearable_activity_monitor/physical_activity/",
)
EXCLUDED_HINTS = ("retinal_", "cardiac_ecg", "environment/", "retinal")


class AIReadiError(RuntimeError):
    pass


def plan_selective_download(manifest_rows: list[dict[str, Any]], pilot_participants: list[str] | None = None) -> dict:
    """From a REAL file manifest (rows with ``path`` and ``size_bytes``), list only the files needed and their bytes.

    ``pilot_participants`` restricts per-participant files to a deterministic pilot subset (shared files are always
    included). The size is summed from the manifest, never estimated."""
    keep, skipped_bytes = [], 0
    for r in manifest_rows:
        p = str(r["path"]).lstrip("./")
        size = int(r.get("size_bytes") or 0)
        wanted = p.startswith(SELECTED_PREFIXES) and not any(h in p for h in EXCLUDED_HINTS)
        if wanted and pilot_participants is not None and p.startswith(CGM_SUBPATH):
            parts = p[len(CGM_SUBPATH):].strip("/").split("/")
            wanted = bool(parts) and parts[0] in pilot_participants
        if wanted:
            keep.append({"path": p, "size_bytes": size})
        else:
            skipped_bytes += size
    return {"files": keep, "selected_bytes": sum(f["size_bytes"] for f in keep), "skipped_bytes": skipped_bytes,
            "pilot": pilot_participants is not None}


def deterministic_pilot(participant_ids: list[str], n: int, seed: int = 20261012) -> list[str]:
    ids = sorted(set(participant_ids))
    rng = np.random.default_rng(seed)
    return sorted(rng.permutation(ids)[: min(n, len(ids))].tolist())


def read_manifest_tsv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def parse_cgm_json(path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    """Return (header, readings) with readings columns: start, value_raw, unit, event_type, device, row."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    header = doc.get("header") or {}
    body = (doc.get("body") or {}).get("cgm")
    if not isinstance(body, list):
        raise AIReadiError(f"{path.name}: body.cgm missing or not a list")
    rows = []
    for i, r in enumerate(body):
        tf = ((r.get("effective_time_frame") or {}).get("time_interval") or {})
        bg = r.get("blood_glucose") or {}
        rows.append({"row": i, "start": tf.get("start_date_time"), "end": tf.get("end_date_time"),
                     "value_raw": bg.get("value"), "unit": bg.get("unit"), "event_type": r.get("event_type"),
                     "device": r.get("source_device_id"), "transmitter_id": r.get("transmitter_id")})
    return header, pd.DataFrame(rows)


def normalize_cgm_file(path: Path, patient_id: str, synthetic_origin: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Canonical rows for one participant's ``*_DEX.json``. Only Estimated Glucose Value events are readings."""
    header, df = parse_cgm_json(path)
    audit: dict[str, Any] = {"rows": int(len(df)), "non_egv_events": 0}
    if df.empty:
        return pd.DataFrame(columns=list(cn.CANONICAL_COLUMNS)), audit
    egv = df["event_type"].astype(str).str.upper().str.contains("EGV") | df["event_type"].isna()
    audit["non_egv_events"] = int((~egv).sum())
    df = df[egv].reset_index(drop=True)
    ts = pd.to_datetime(df["start"], errors="coerce", utc=True)
    parsed = []
    for v, u in zip(df["value_raw"].tolist(), df["unit"].tolist(), strict=True):
        unit = str(u) if u else ""
        if not unit:
            parsed.append(cn.ParsedValue(None, "invalid", "unit_not_declared", ""))
        else:
            parsed.append(cn.parse_glucose_value(v, unit, VALID_RANGE))
    sha = cn.file_hash(path)
    p = pd.DataFrame({
        "recording_id": f"{patient_id}-r0", "_source_ts": ts.dt.tz_localize(None),
        "glucose_mg_dl": [x.mg_dl if x.mg_dl is not None else np.nan for x in parsed],
        "quality": [x.quality for x in parsed], "missing_reason": [x.missing_reason for x in parsed],
    })
    audit.update(cn.flag_timestamp_anomalies(p))
    valid = p["_source_ts"].dropna()
    first_day = valid.min().normalize() if len(valid) else pd.Timestamp(synthetic_origin).tz_localize(None)
    offset = pd.Timestamp(synthetic_origin).tz_localize(None) - first_day
    obs = (p["_source_ts"] + offset).dt.tz_localize("UTC")
    canon = pd.DataFrame({
        "dataset_id": DATASET_ID, "dataset_version": "3.0.0", "patient_id": patient_id,
        "recording_id": p["recording_id"], "device_id": DEVICE_ID,
        "source_record_id": [f"{path.name}#cgm[{r}]" for r in df["row"].tolist()],
        "observed_at": obs, "available_at": obs,
        "original_timestamp": df["start"].astype("string").fillna(""),
        "original_timezone": f"UTC offset in source timestamps; header timezone {header.get('timezone')!r}",
        "native_cadence_minutes": NATIVE_CADENCE, "glucose_mg_dl": p["glucose_mg_dl"],
        "original_value": df["value_raw"].astype("string").fillna(""), "original_unit": df["unit"].astype("string").fillna(""),
        "unit_conversion": [x.conversion for x in parsed], "quality": p["quality"], "missing_reason": p["missing_reason"],
        "source_file_hash": sha, "parser_version": ADAPTER_VERSION, "availability_assumption": AVAILABILITY,
    })
    audit["usable_readings"] = int(canon["quality"].isin(cn.USABLE_QUALITIES).sum())
    audit["sensor_codes"] = int(canon["quality"].isin(["sensor_low", "sensor_high"]).sum())
    return cn.conform_canonical(canon), audit


def local_status(raw_root: Path) -> dict[str, Any]:
    """What exists locally for AI-READI (never reads participant files)."""
    root = raw_root
    if not root.exists():
        return {"access_status": "access_required", "files_present": 0, "detail": "No local AI-READI files."}
    files = list((root / CGM_SUBPATH).glob("*/*_DEX.json")) if (root / CGM_SUBPATH).exists() else []
    return {"access_status": "available_locally" if files else "access_required", "files_present": len(files),
            "detail": f"{len(files)} CGM files found locally." if files else "Directory exists but holds no CGM files."}
