"""Experiment origin table: one row per (participant, forecast origin).

Each row holds the shared model-neutral features (superset; each model selects its feature-set
columns), the forecast quality decision, matched numeric targets with their observation/availability
times, new-onset event labels, online episode state and the split segment. Feature columns are
computed by ``glucotwin.features.build_features`` — the same function used during replay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import fingerprint, load_config
from glucotwin.data.store import Store, from_minutes
from glucotwin.events import EventDefinition, label_new_onsets
from glucotwin.features import FEATURE_SETS, FeatureSpec, build_features, match_targets, prepare
from glucotwin.splits import SplitConfig, assign_segments, boundaries_for

SUPERSET = "dyn-prof-meal-v1"


@dataclass
class ExperimentSettings:
    horizons: list[int]
    event: EventDefinition
    split: SplitConfig
    spec: FeatureSpec
    target_tolerance: float
    raw: dict[str, Any]

    @property
    def config_hash(self) -> str:
        return fingerprint(self.raw)


def load_settings(device: str | None = None) -> ExperimentSettings:
    exp = load_config("experiment")
    data_cfg = load_config("data")
    device = device or exp["cohort"]["primary_device"]
    dcfg = data_cfg["normalization"]["devices"][device]
    ev = exp["event"]
    event = EventDefinition(
        threshold_mg_dl=float(ev["threshold_mg_dl"]), confirm_minutes=float(ev["confirm_minutes"]),
        recovery_minutes=float(ev["recovery_minutes"]), max_gap_minutes=float(dcfg["max_continuity_gap_minutes"]),
        jitter_minutes=float(ev["jitter_minutes"]),
    )
    sp = exp["splits"]
    split = SplitConfig(sp["train_fraction"], sp["selection_fraction"], sp["calibration_fraction"],
                        sp["max_label_support_minutes"], sp["continuity_allowance_minutes"])
    base = FEATURE_SETS[SUPERSET]
    f = exp["features"]
    spec = FeatureSpec(
        SUPERSET, use_activity=base.use_activity, use_profile=base.use_profile, use_meals=base.use_meals,
        lookback_minutes=float(f["lookback_minutes"]), min_history_minutes=float(f["min_history_minutes"]),
        cadence_minutes=float(dcfg["nominal_cadence_minutes"]),
        match_tolerance_minutes=float(dcfg["match_tolerance_minutes"]),
        stale_threshold_minutes=float(f["stale_threshold_minutes"]),
    )
    return ExperimentSettings(list(exp["horizons_minutes"]), event, split, spec,
                              float(exp["target"]["match_tolerance_minutes"]), {"experiment": exp, "data": data_cfg})


def build_patient_rows(pdata, st: ExperimentSettings) -> tuple[pd.DataFrame, dict[str, Any]]:
    prep = prepare(pdata)
    origins = np.unique(prep.g_avail)
    fr = build_features(prep, origins, st.spec)
    df = fr.frame.copy()
    df.insert(0, "patient_id", pdata.patient_id)
    df.insert(1, "origin", origins)
    df["quality"] = fr.quality
    df["quality_reasons"] = [";".join(r) for r in fr.reasons]
    support_end = np.full(origins.size, np.nan)
    for h in st.horizons:
        tv, tt, ta = match_targets(prep.g_obs, prep.g_val, prep.g_avail, origins, h, st.target_tolerance)
        df[f"target_{h}"] = tv
        df[f"target_{h}_at"] = tt
        df[f"target_{h}_avail"] = ta
        support_end = np.fmax(support_end, ta)
        lab = label_new_onsets(prep.g_obs, prep.g_val, st.event, h)
        # origins == native sample times here; map label arrays (indexed by sample) onto origins
        pos = np.searchsorted(prep.g_obs, origins)
        df[f"label_{h}"] = lab.label[pos]
        df[f"onset_{h}"] = lab.onset_at[pos]
        df[f"label_{h}_support_end"] = lab.support_end[pos]
        df[f"label_{h}_censor"] = [lab.censor_reason[i] for i in pos]
        support_end = np.fmax(support_end, lab.support_end[pos])
        if h == st.horizons[0]:
            df["episode_state"] = [lab.state[i] for i in pos]
            df["ew_eligible"] = lab.eligible[pos]
    b = boundaries_for(prep.g_obs, st.split)
    seg, purged = assign_segments(origins, b, st.split, support_end)
    df["segment"] = seg
    df["purged"] = purged
    info = {
        "patient_id": pdata.patient_id,
        "display_alias": pdata.meta["display_alias"],
        "boundaries_minutes": b.as_dict(),
        "boundaries_iso": {k: from_minutes(v).isoformat() for k, v in b.as_dict().items()},
    }
    return df, info


def build_origin_table(store: Store, st: ExperimentSettings, out_dir: Path, include=None) -> dict[str, Any]:
    """Build the origin table. ``include(meta)`` overrides eligibility (used for synthetic dry runs)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames, patients, excluded = [], [], []
    include = include or (lambda meta: bool(meta.get("eligible_for_primary_analysis")))
    for pid in store.patient_ids():
        meta = store.meta(pid)
        if not include(meta):
            excluded.append({"display_alias": meta["display_alias"], "cohort": meta["cohort"]["label"],
                             "reason": meta.get("exclusion_reason")})
            continue
        df, info = build_patient_rows(store.load(pid), st)
        frames.append(df)
        patients.append(info)
    table = pd.concat(frames, ignore_index=True)
    table.to_parquet(out_dir / "origins.parquet", index=False)
    summary = summarize(table, st)
    prov = store.directory / "provenance.json"
    data_fp = fingerprint(json.loads(prov.read_text())) if prov.exists() else fingerprint(
        {"synthetic_store": store.get_info("generator_version")})
    manifest = {
        "experiment_id": st.raw["experiment"]["experiment_id"],
        "config_hash": st.config_hash,
        "data_fingerprint": data_fp,
        "selected_device": st.raw["experiment"]["cohort"]["primary_device"],
        "split_scheme": st.raw["experiment"]["splits"]["scheme"],
        "purge_minutes": st.split.purge_minutes,
        "patients": patients,
        "excluded": excluded,
        "summary": summary,
    }
    manifest["split_hash"] = fingerprint([p["boundaries_minutes"] for p in patients])
    (out_dir / "split_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


def summarize(table: pd.DataFrame, st: ExperimentSettings) -> dict[str, Any]:
    out: dict[str, Any] = {"participants": int(table["patient_id"].nunique()), "by_segment": {}}
    for seg in ("training", "validation", "calibration", "test"):
        s = table[table["segment"] == seg]
        d: dict[str, Any] = {
            "origins": int(len(s)),
            "issued_forecast_origins": int((s["quality"] != "insufficient").sum()),
            "covered_hours": round(len(s) * 5 / 60, 1),
        }
        for h in st.horizons:
            ok = s["quality"] != "insufficient"
            d[f"matched_targets_{h}"] = int((ok & s[f"target_{h}"].notna()).sum())
            d[f"ew_eligible_{h}"] = int(s["ew_eligible"].sum())
            d[f"positive_origins_{h}"] = int((s[f"label_{h}"] == 1).sum())
            d[f"negative_origins_{h}"] = int((s[f"label_{h}"] == 0).sum())
            d[f"censored_eligible_origins_{h}"] = int((s["ew_eligible"] & s[f"label_{h}"].isna()).sum())
        onsets = s.loc[s["label_60"] == 1, ["patient_id", "onset_60"]].drop_duplicates()
        d["distinct_new_onsets_60"] = int(len(onsets))
        out["by_segment"][seg] = d
    out["purged_origins"] = int(table["purged"].sum())
    out["unassigned_origins"] = int((table["segment"] == "").sum())
    out["quality_counts"] = table["quality"].value_counts().to_dict()
    return out
