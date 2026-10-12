"""Import pipeline: verified source files -> canonical store + provenance + audit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from glucotwin.config import load_config, paths
from glucotwin.data import acquire
from glucotwin.data.cgmacros import (
    ADAPTER_VERSION,
    normalize_participant,
    participant_files,
    save_private_mapping,
)
from glucotwin.data.store import Store
from glucotwin.data.synthetic import build_store as build_synthetic_store

COHORT_ORDER = {"Type 2 diabetes": 0, "Pre-diabetes": 1, "No diabetes": 2, "Unknown": 3}


def dataset_store_dir() -> Path:
    return paths().processed / load_config("data")["dataset"]["processed_subdir"]


def synthetic_store_dir() -> Path:
    return paths().synthetic / "v1"


def import_cgmacros(verify_only: bool = False) -> dict[str, Any]:
    cfg = load_config("data")
    files = acquire.verify()
    if verify_only:
        return {"verified": [f.relative_path for f in files]}
    tables_dir = acquire.raw_dir() / "tables"
    extracted = acquire.extract_tables(tables_dir)
    bio = pd.read_csv(tables_dir / "bio.csv")
    bio.columns = [c.strip() for c in bio.columns]
    by_subject = {int(r["subject"]): r for _, r in bio.iterrows()}

    out_dir = dataset_store_dir()
    store = Store(out_dir)
    results = []
    private_rows = []
    pdatas = []
    for key, path in participant_files(tables_dir).items():
        subject = int(key.split("-")[1])
        if subject not in by_subject:
            results.append({"source_key": key, "error": "No bio.csv row"})
            continue
        pdata, info = normalize_participant(key, path, by_subject[subject], cfg)
        pdatas.append(pdata)
        results.append(info["audit"])
        private_rows.append(info["private"])

    # Deterministic, explicitly synthetic display aliases (cohort first, then pseudonym).
    pdatas.sort(key=lambda p: (COHORT_ORDER.get(p.meta["cohort"]["label"], 9), p.patient_id))
    for i, p in enumerate(pdatas, start=1):
        p.meta["display_alias"] = f"Participant {i:02d}"
        p.meta["sort_key"] = f"{i:03d}"
        store.write_patient(p)
        pdir = out_dir / "patients" / p.patient_id
        for device, table in p.extras.get("glucose_by_device", {}).items():
            table.to_parquet(pdir / f"glucose_{device}.parquet", index=False)
    alias_by_pid = {p.patient_id: p.meta["display_alias"] for p in pdatas}
    for r in results:
        if "patient_id" in r:
            r["display_alias"] = alias_by_pid[r["patient_id"]]
    save_private_mapping(private_rows)

    store.set_info("mode", "dataset_replay")
    store.set_info("adapter_version", ADAPTER_VERSION)
    store.set_info("license", cfg["dataset"]["license"])
    store.set_info("dataset", {k: cfg["dataset"][k] for k in ("name", "version", "doi", "license")})
    manifest = acquire.write_provenance(files, extracted, ADAPTER_VERSION, out_dir / "provenance.json")
    audit = {"adapter_version": ADAPTER_VERSION, "participants": results,
             "bio_columns": list(bio.columns), "bio_rows": int(len(bio))}
    (out_dir / "audit.json").write_text(json.dumps(audit, indent=2, default=str))
    store.log_import({"adapter_version": ADAPTER_VERSION, "participants": len(pdatas)})
    return {"store": str(out_dir), "participants": len(pdatas), "manifest_files": len(manifest["files"])}


def export_cgmacros_canonical() -> dict[str, Any]:
    """Write CGMacros canonical-cgm-1 partitions from the verified raw files WITHOUT touching the model store, and
    check that the store's primary-device glucose table is exactly what the canonical layer derives."""
    import numpy as np

    from glucotwin.data import canonical as cn

    cfg = load_config("data")
    acquire.verify()
    tables_dir = acquire.raw_dir() / "tables"
    acquire.extract_tables(tables_dir)
    bio = pd.read_csv(tables_dir / "bio.csv")
    bio.columns = [c.strip() for c in bio.columns]
    by_subject = {int(r["subject"]): r for _, r in bio.iterrows()}
    store = Store(dataset_store_dir())
    root = paths().processed / "canonical"
    written, mismatches = 0, []
    for key, path in participant_files(tables_dir).items():
        subject = int(key.split("-")[1])
        if subject not in by_subject:
            continue
        pdata, _ = normalize_participant(key, path, by_subject[subject], cfg)
        pid = pdata.patient_id
        sha = cn.file_hash(path)
        frames = []
        for device, rows in pdata.extras["canonical_rows"].items():
            dcfg = cfg["normalization"]["devices"][device]
            quality = np.where(rows["out_of_range"], "invalid", np.where(rows["at_limit"], "suspect", "ok"))
            frames.append(pd.DataFrame({
                "dataset_id": "cgmacros", "dataset_version": cfg["dataset"]["version"], "patient_id": pid,
                "recording_id": f"{pid}-r0", "device_id": device,
                "source_record_id": [f"{path.name}@{t}#{device}" for t in rows["original_timestamp"]],
                "observed_at": rows["observed_at"], "available_at": rows["observed_at"],
                "original_timestamp": rows["original_timestamp"], "original_timezone": "undocumented",
                "native_cadence_minutes": float(dcfg["nominal_cadence_minutes"]), "glucose_mg_dl": rows["value"],
                "original_value": [f"{v:g}" for v in rows["value"]], "original_unit": "mg/dL", "unit_conversion": "",
                "quality": quality,
                "missing_reason": np.where(rows["out_of_range"], "outside_device_reporting_range", ""),
                "source_file_hash": sha, "parser_version": ADAPTER_VERSION,
                "availability_assumption": "replay-zero-latency (study CGMs were blinded; sensor_latency_minutes = 0)",
            }))
        canon = cn.conform_canonical(pd.concat(frames, ignore_index=True))
        cn.write_canonical(root, canon)
        written += 1
        # compatibility check against the existing model store (primary device only)
        prim = canon[(canon["device_id"] == cfg["normalization"]["primary_device"]) &
                     canon["quality"].isin(cn.USABLE_QUALITIES)]
        stored = store.load(pid).glucose.sort_values("observed_at")
        same = (len(prim) == len(stored)
                and (prim["observed_at"].to_numpy() == stored["observed_at"].to_numpy()).all()
                and np.allclose(prim["glucose_mg_dl"].to_numpy(float), stored["value_mg_dl"].to_numpy(float)))
        if not same:
            mismatches.append(pid)
    return {"participants_written": written, "store_mismatches": mismatches,
            "canonical_root": str(root / cn.CANONICAL_SCHEMA_VERSION)}


def build_synthetic() -> dict[str, Any]:
    store = build_synthetic_store(synthetic_store_dir())
    return {"store": str(store.directory), "participants": len(store.patient_ids())}
