"""Source manifest + measured dataset inventory (``glucotwin data manifest``).

Everything here is computed from what exists on disk: verified raw files, canonical partitions, model stores and the
frozen split membership of the research protocol. Publisher-reported scale is copied from configs/sources.yaml and is
always labelled as external metadata. Outputs:

* ``data/processed/source_manifest.json``  full machine-readable manifest (git-ignored, local paths)
* ``reports/dataset_inventory.json``       aggregate inventory (no participant-level rows; committed)
* ``reports/dataset_expansion_audit.md``   human-readable audit
"""

from __future__ import annotations

import json
import resource
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import load_config, paths
from glucotwin.data import canonical as cn
from glucotwin.data.store import Store, to_minutes

STATUSES = ("planned", "access_required", "available_locally", "imported", "failed_validation",
            "eligible_for_experiment")
LONG_GAP_MINUTES = 60.0


def _dir_bytes(d: Path) -> int:
    return int(sum(p.stat().st_size for p in d.rglob("*") if p.is_file())) if d.exists() else 0


def _canonical_frames(dataset_id: str) -> list[pd.DataFrame]:
    root = paths().processed / "canonical" / cn.CANONICAL_SCHEMA_VERSION / f"dataset_id={dataset_id}"
    return [pd.read_parquet(p) for p in sorted(root.glob("patient_id=*/glucose.parquet"))]


def _recording_stats(frames: list[pd.DataFrame], device: str | None, cadence: float) -> dict[str, Any]:
    readings = obs_min = days = gaps = 0
    excluded: dict[str, int] = {}
    dup = 0
    recs = 0
    for f in frames:
        if device is not None:
            f = f[f["device_id"] == device]
        use = f[f["quality"].isin(cn.USABLE_QUALITIES) & f["glucose_mg_dl"].notna()]
        for _r, g in use.groupby("recording_id"):
            t = np.sort(to_minutes(g["observed_at"]))
            obs_min += cn.observed_minutes(t, cadence)
            gaps += cn.long_gaps(t, LONG_GAP_MINUTES)
            recs += 1
        readings += len(use)
        days += cn.calendar_days_with_readings(use["observed_at"]) if len(use) else 0
        bad = f[~f.index.isin(use.index)]
        for k, v in bad["missing_reason"].replace("", "unspecified").value_counts().items():
            excluded[k] = excluded.get(k, 0) + int(v)
        dup += int((f["quality"] == "duplicate").sum())
    return {"native_readings": int(readings), "observed_hours": round(obs_min / 60.0, 1),
            "observed_days_equivalent": round(obs_min / 1440.0, 1), "calendar_days_with_readings": int(days),
            "recordings": int(recs), "long_gaps_over_60_min": int(gaps), "excluded_rows_by_reason": excluded,
            "duplicates_removed": dup}


def _cgmacros(src: dict, splits: dict | None) -> dict[str, Any]:
    from glucotwin.data import acquire
    from glucotwin.data.pipeline import dataset_store_dir

    out: dict[str, Any] = {"dataset_id": "cgmacros"}
    raw = acquire.raw_dir()
    try:
        files = acquire.verify()
        out["files"] = [{"name": f.relative_path, "size_bytes": f.size_bytes, "sha256": f.sha256, "verified": f.verified}
                        for f in files]
        out["acquired_bytes"] = int(sum(f.size_bytes for f in files))
        verified = True
    except Exception as exc:  # report, never hide
        out["files"], out["acquired_bytes"], verified = [], _dir_bytes(raw), False
        out["validation_error"] = str(exc)
    store = Store(dataset_store_dir())
    metas = [store.meta(p) for p in store.patient_ids()] if store.exists() else []
    groups: dict[str, int] = {}
    for m in metas:
        groups[m["cohort"]["label"]] = groups.get(m["cohort"]["label"], 0) + 1
    prim = [m for m in metas if m.get("eligible_for_primary_analysis")]
    frames = _canonical_frames("cgmacros")
    prim_ids = {m["patient_id"] for m in prim}
    out.update({
        "acquired_participants": len(metas), "parsed_participants": len(frames),
        "participants_by_group": groups,
        "eligible": {"5-min Type 2 cohort": len(prim), "15-min development": len(prim)},
        "all_participants_dexcom": _recording_stats(frames, "dexcom_g6_pro", 5.0),
        "all_participants_libre": _recording_stats(frames, "libre_pro", 15.0),
        "type2_cohort_dexcom": _recording_stats([f for f in frames if f["patient_id"].iloc[0] in prim_ids],
                                                "dexcom_g6_pro", 5.0),
        "activity": {"source": "Fitbit Sense (5-minute summaries)", "type2_participants_with_activity":
                     sum(1 for m in prim if (m["coverage"].get("activity_coverage_fraction") or 0) > 0),
                     "type2_mean_minute_coverage": round(float(np.mean([m["coverage"]["activity_coverage_fraction"]
                                                                        for m in prim])), 3) if prim else None},
        "baseline_profile": {"type2_participants_with_profile": len(prim),
                             "availability": "assumed available at recording start (screening labs on study day 1)"},
        "excluded_people": {k: v for k, v in groups.items() if k != "Type 2 diabetes"},
        "excluded_people_reason": "Outside the Type 2 population of the primary analysis (kept for replay only).",
    })
    status = "failed_validation" if not verified else ("eligible_for_experiment" if prim else "imported")
    out["access_status"] = status
    if splits:
        out["split_counts"] = splits.get("cgmacros")
    return out


def _shanghai(src: dict, splits: dict | None) -> dict[str, Any]:
    from glucotwin.data import shanghai

    out: dict[str, Any] = {"dataset_id": "shanghai_t2dm"}
    try:
        v = shanghai.verify()
        out["files"] = [v]
        out["acquired_bytes"] = v["size_bytes"]
        verified = True
    except Exception as exc:
        out["files"], out["acquired_bytes"], verified = [], _dir_bytes(shanghai.raw_dir()), False
        out["validation_error"] = str(exc)
    sd = shanghai.store_dir()
    store = Store(sd)
    metas = [store.meta(p) for p in store.patient_ids()] if store.exists() else []
    frames = _canonical_frames("shanghai_t2dm")
    audit = json.loads((sd / "audit.json").read_text()) if (sd / "audit.json").exists() else {}
    elig = [m for m in metas if m.get("eligible_for_portable_external")]
    stats = _recording_stats(frames, None, 15.0)
    out.update({
        "acquired_participants": len(audit.get("participants", [])) + len(audit.get("failed", [])),
        "acquired_recordings": sum(len(p["recordings"]) for p in audit.get("participants", [])),
        "parsed_participants": len(frames), "failed_participants": audit.get("failed", []),
        "participants_by_group": {"Type 2 diabetes": len(metas)},
        "eligible": {"15-min external (≥ 72 h)": len(elig)},
        "not_eligible": [{"reason": m["exclusion_reason"]} for m in metas if not m.get("eligible_for_portable_external")],
        "all_participants": stats,
        "eligible_participants": _recording_stats([f for f in frames if f["patient_id"].iloc[0] in
                                                   {m["patient_id"] for m in elig}], None, 15.0),
        "activity": {"source": None, "detail": "No wearable activity in ShanghaiT2DM."},
        "baseline_profile": {"participants_with_summary_row": len(metas),
                             "availability": "labs up to 6 months before/after CGM without dates: not causally usable"},
        "t1dm_files_not_imported": audit.get("t1dm_files_not_imported"),
        "limit_values_flagged_suspect": sum(r["limit_values"] for p in audit.get("participants", []) for r in p["recordings"]),
        "unit_from_dataset_convention_files": sum(1 for p in audit.get("participants", []) for r in p["recordings"]
                                                  if r["unit_source"] != "header"),
        "import_duration_seconds": audit.get("duration_seconds"), "import_peak_rss_bytes": audit.get("peak_rss_bytes"),
    })
    out["access_status"] = ("failed_validation" if not verified else
                            "eligible_for_experiment" if elig else "imported" if metas else "available_locally")
    if splits:
        out["split_counts"] = splits.get("shanghai_t2dm")
    return out


def _aireadi(src: dict) -> dict[str, Any]:
    from glucotwin.data.aireadi import local_status

    st = local_status(paths().raw / src["raw_subdir"])
    return {"dataset_id": "ai_readi_v3", "access_status": st["access_status"], "files_present": st["files_present"],
            "detail": st["detail"], "acquired_participants": 0, "parsed_participants": 0, "acquired_bytes": 0,
            "user_steps": src.get("user_steps", []),
            "work_completed_without_access": ["Open mHealth CGM JSON parser (fictional fixtures)",
                                              "selective-download planner from a real manifest (fixture-tested)",
                                              "canonical conversion with LOW/HIGH codes and timestamp anomaly checks"]}


def _overlap_check() -> dict[str, Any]:
    """Pairwise shift-invariant overlap between every imported recording of different datasets (and within them)."""
    sigs = []
    for ds, dev in (("cgmacros", "dexcom_g6_pro"), ("cgmacros", "libre_pro"), ("shanghai_t2dm", None)):
        for f in _canonical_frames(ds):
            if dev is not None:
                f = f[f["device_id"] == dev]
            f = f[f["quality"].isin(cn.USABLE_QUALITIES)]
            for rid, g in f.groupby("recording_id"):
                s = cn.recording_signature(to_minutes(g["observed_at"]), g["glucose_mg_dl"].to_numpy(float))
                if s:
                    sigs.append((ds, f"{rid}:{dev or ''}", s))
    worst, flagged, pairs = 0.0, [], 0
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            if sigs[i][1].split(":")[0] == sigs[j][1].split(":")[0]:
                continue  # two devices of one recording are not duplicates of each other's source
            pairs += 1
            o = cn.signature_overlap(sigs[i][2], sigs[j][2])
            worst = max(worst, o)
            if o >= cn.OVERLAP_THRESHOLD:
                flagged.append({"a": sigs[i][0], "b": sigs[j][0], "overlap": round(o, 3)})
    return {"recordings_compared": len(sigs), "pairs": pairs, "max_overlap": round(worst, 4),
            "threshold": cn.OVERLAP_THRESHOLD, "flagged_pairs": flagged}


def _synthetic() -> dict[str, Any]:
    from glucotwin.data.pipeline import synthetic_store_dir

    s = Store(synthetic_store_dir())
    if not s.exists():
        return {"participants": 0, "glucose_rows": 0}
    rows = sum(len(s.load(p).glucose) for p in s.patient_ids())
    return {"participants": len(s.patient_ids()), "glucose_rows": int(rows),
            "note": "Fictional software fixtures and the demonstration model; never counted as real participants."}


def build(splits_path: Path | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    cfg = load_config("sources")
    srcs = cfg["sources"]
    splits = json.loads(splits_path.read_text())["counts_by_dataset"] if splits_path and splits_path.exists() else None
    datasets = [_cgmacros(srcs["cgmacros"], splits), _shanghai(srcs["shanghai_t2dm"], splits),
                _aireadi(srcs["ai_readi_v3"]),
                {"dataset_id": "glucose_ml", "access_status": "planned", "acquired_participants": 0,
                 "parsed_participants": 0, "acquired_bytes": 0,
                 "detail": "Discovery resource only. Its harmonized copies overlap CGMacros, ShanghaiT2DM and AI-READI; "
                           "no component was imported. Catalog totals are never GlucoTwin counts."}]
    for d in datasets:
        s = srcs[d["dataset_id"]]
        assert d["access_status"] in STATUSES, d["access_status"]
        d["publisher"] = {k: s.get(k) for k in ("name", "release", "landing_page", "doi", "license", "license_url",
                                                 "publisher_participants", "publisher_recordings", "publisher_bytes",
                                                 "population", "country_site", "devices", "role", "access")
                          if s.get(k) is not None}
        d["publisher"]["citation"] = " ".join(str(s.get("citation", "")).split()) or None
        d["requested_modalities"] = s.get("requested_modalities", [])
        d["expected_bytes"] = s.get("expected_bytes")
        d["permitted_local_use"] = " ".join(str(s.get("permitted_local_use", "")).split())
        d["redistribution"] = " ".join(str(s.get("redistribution", "")).split())
    real_assessed = None
    if splits:
        real_assessed = {k: v.get("assessed_participants") for k, v in splits.items()}
    inv = {
        "manifest_version": cfg["manifest_version"], "canonical_schema": cn.CANONICAL_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "datasets": datasets, "overlap_check": _overlap_check(), "synthetic": _synthetic(),
        "split_membership_source": str(splits_path.relative_to(paths().root)) if splits_path and splits_path.exists() else None,
        "assessed_participants_by_dataset": real_assessed,
        "run": {"duration_seconds": round(time.perf_counter() - t0, 2),
                "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)},
    }
    return inv


def write(splits_path: Path | None = None) -> dict[str, Any]:
    inv = build(splits_path)
    local = paths().processed / "source_manifest.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(inv, indent=2, default=str))
    public = json.loads(json.dumps(inv, default=str))
    for d in public["datasets"]:
        for f in d.get("files", []):
            f.pop("path", None)
    (paths().reports / "dataset_inventory.json").write_text(json.dumps(public, indent=2, default=str) + "\n")
    (paths().reports / "dataset_expansion_audit.md").write_text(render_markdown(public))
    return {"manifest": str(local), "inventory": "reports/dataset_inventory.json",
            "audit": "reports/dataset_expansion_audit.md"}


def _fmt(n: Any) -> str:
    if n is None:
        return "—"
    if isinstance(n, float):
        return f"{n:,.1f}"
    if isinstance(n, int):
        return f"{n:,}"
    return str(n)


def render_markdown(inv: dict[str, Any]) -> str:
    ds = {d["dataset_id"]: d for d in inv["datasets"]}
    cg, sh, ai, gm = ds["cgmacros"], ds["shanghai_t2dm"], ds["ai_readi_v3"], ds["glucose_ml"]
    L = ["# Dataset expansion audit", "",
         f"Generated by `glucotwin data manifest` on {inv['generated_at'][:10]} from verified local files, canonical "
         f"partitions (`{inv['canonical_schema']}`) and model stores. Publisher-reported scale is external metadata, "
         "never a GlucoTwin count. Machine-readable copy: `reports/dataset_inventory.json`.", "",
         "## Sources and status", "",
         "| Source | Release | Status | Publisher-reported participants | Acquired | Parsed | Eligible (task) | Licence |",
         "|---|---|---|---:|---:|---:|---|---|"]
    for d in (cg, sh, ai, gm):
        p = d["publisher"]
        elig = "; ".join(f"{v} ({k})" for k, v in (d.get("eligible") or {}).items()) or "—"
        L.append(f"| {p.get('name')} | {p.get('release')} | `{d['access_status']}` | {_fmt(p.get('publisher_participants'))} "
                 f"| {_fmt(d.get('acquired_participants'))} | {_fmt(d.get('parsed_participants'))} | {elig} | {p.get('license')} |")
    L += ["", "Acquired = participants present in verified local source files; parsed = participants with a canonical "
          "partition written; eligible = meeting the declared criterion for that task. A URL or archive alone is never "
          "an import.", "",
          "## Measured scale (native readings only)", "",
          "Observed hours count each native reading as at most one native cadence interval, so long gaps add nothing. "
          "Calendar days count distinct days with at least one reading. Native readings and forecast windows are "
          "different units; neither is a count of independent patients.", "",
          "| Group | Recordings | Native readings | Observed hours | Calendar days with readings | Gaps > 60 min | Duplicates removed |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    rows = [("CGMacros, all 45, Dexcom (5 min)", cg["all_participants_dexcom"]),
            ("CGMacros, all 45, Libre Pro (15 min)", cg["all_participants_libre"]),
            ("CGMacros Type 2 cohort, Dexcom", cg["type2_cohort_dexcom"]),
            ("ShanghaiT2DM, all imported (15 min)", sh["all_participants"]),
            ("ShanghaiT2DM, eligible", sh["eligible_participants"])]
    for name, s in rows:
        L.append(f"| {name} | {_fmt(s['recordings'])} | {_fmt(s['native_readings'])} | {_fmt(s['observed_hours'])} | "
                 f"{_fmt(s['calendar_days_with_readings'])} | {_fmt(s['long_gaps_over_60_min'])} | {_fmt(s['duplicates_removed'])} |")
    L += ["", "## People by diabetes group and exclusions", "",
          f"* CGMacros: {', '.join(f'{k} {v}' for k, v in cg['participants_by_group'].items())}. "
          f"{sum(cg['excluded_people'].values())} people are outside the Type 2 population: kept for replay only, never "
          "trained on, tuned on or assessed.",
          f"* ShanghaiT2DM: {_fmt(sh['parsed_participants'])} people with Type 2 diabetes in {_fmt(sh['acquired_recordings'])} "
          f"recordings; {len(sh['not_eligible'])} below the declared 72 observed-hour minimum "
          f"({'; '.join(x['reason'].rstrip('.') for x in sh['not_eligible']) or 'none'}). "
          f"{_fmt(sh['t1dm_files_not_imported'])} ShanghaiT1DM files in the same archive were not imported (Type 1).",
          f"* ShanghaiT2DM rows excluded: {sh['all_participants']['excluded_rows_by_reason'] or 'none'}; "
          f"{_fmt(sh['limit_values_flagged_suspect'])} readings at the assumed device reporting limit kept as `suspect`; "
          f"{_fmt(sh['unit_from_dataset_convention_files'])} files without a unit in the header took the dataset's "
          "documented mg/dL convention.",
          f"* CGMacros rows excluded from the canonical Dexcom layer: {cg['all_participants_dexcom']['excluded_rows_by_reason'] or 'none'}.",
          "", "## Matched wearable and profile data", "",
          f"* CGMacros Type 2 cohort: wearable activity for {cg['activity']['type2_participants_with_activity']} of "
          f"{cg['eligible'][next(iter(cg['eligible']))]} (mean minute coverage {cg['activity']['type2_mean_minute_coverage']}); "
          f"baseline profile {cg['baseline_profile']['availability']}.",
          f"* ShanghaiT2DM: no wearable activity; {sh['baseline_profile']['availability']}. The portable track is "
          "therefore CGM-only.", "",
          "## Split membership", ""]
    if inv.get("split_membership_source"):
        L.append(f"From `{inv['split_membership_source']}` (written before any fit):")
        L.append("")
        for d in (cg, sh):
            sc = d.get("split_counts")
            if sc:
                L.append(f"* **{d['publisher']['name']}**: " + "; ".join(f"{k.replace('_', ' ')} {v}" for k, v in sc.items()
                                                                          if not isinstance(v, (dict, list))))
    else:
        L.append("Not yet frozen: run `glucotwin research freeze` to write the split membership.")
    ov = inv["overlap_check"]
    L += ["", "## Duplicate and overlap checks", "",
          f"Shift-invariant recording signatures were compared for {ov['recordings_compared']} recordings "
          f"({ov['pairs']:,} cross-recording pairs). Largest overlap {ov['max_overlap']:.4f} "
          f"(flag threshold {ov['threshold']}); flagged pairs: {len(ov['flagged_pairs'])}. Exact duplicate samples and "
          "readings repeated across a participant's overlapping recordings are marked `duplicate` in the canonical layer. "
          "No attempt is made to link people across unrelated datasets.", "",
          "## Access-blocked and planned sources", "",
          f"* **AI-READI v3** — `{ai['access_status']}`. {ai['detail']} Completed without access: "
          f"{'; '.join(ai['work_completed_without_access'])}. Steps only the user can complete:"]
    L += [f"  {i}. {s}" for i, s in enumerate(ai["user_steps"], 1)]
    L += [f"* **Glucose-ML** — `{gm['access_status']}`. {gm['detail']}", "",
          "## Synthetic data (separate)", "",
          f"{_fmt(inv['synthetic']['participants'])} fictional participants with {_fmt(inv['synthetic']['glucose_rows'])} "
          f"glucose rows. {inv['synthetic'].get('note', '')}", "",
          "## Bytes, time and memory", "",
          f"* CGMacros verified source files: {_fmt(cg.get('acquired_bytes'))} bytes. ShanghaiT2DM archive: "
          f"{_fmt(sh.get('acquired_bytes'))} bytes (publisher MD5 verified). AI-READI: 0 bytes.",
          f"* ShanghaiT2DM import: {sh.get('import_duration_seconds')} s, peak resident memory "
          f"{_fmt((sh.get('import_peak_rss_bytes') or 0) // (1 << 20))} MiB.",
          f"* This inventory run: {inv['run']['duration_seconds']} s, peak resident memory "
          f"{_fmt(inv['run']['peak_rss_bytes'] // (1 << 20))} MiB.", "",
          "## Reproduce", "", "```bash",
          "uv run glucotwin data download                       # CGMacros (opt-in, ~657 MB)",
          "uv run glucotwin data import && uv run glucotwin data canonical",
          "uv run glucotwin data download --dataset shanghai_t2dm   # 3.7 MB, CC BY 4.0",
          "uv run glucotwin data import --dataset shanghai_t2dm",
          "uv run glucotwin data manifest", "```", ""]
    return "\n".join(L)
