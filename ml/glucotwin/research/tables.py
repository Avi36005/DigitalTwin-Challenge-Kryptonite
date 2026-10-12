"""Origin tables of the research tracks: one row per (participant, forecast origin).

Built with the SAME causal functions the serving engine uses (``prepare``, ``build_features``, ``match_targets``,
``label_new_onsets``). Tables are cached under ``artifacts/research/<id>/tables`` and keyed by the data, parser and
feature-transformation fingerprints, so a change in any of them rebuilds the table instead of silently reusing it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import fingerprint
from glucotwin.data import canonical as cn
from glucotwin.data.store import PatientData, Store, to_minutes
from glucotwin.events import EventDefinition, label_new_onsets
from glucotwin.features import FEATURE_SETS, FeatureSpec, Prepared, build_features, match_targets, prepare

REC_RE = re.compile(r"-(r\d+)-\d{5}$")


@dataclass
class TrackData:
    track: str
    dataset_id: str
    table: pd.DataFrame
    prep: dict[str, Prepared]
    cadence: float
    tolerance: float
    meta: dict[str, Any]


def track_spec(proto: dict[str, Any], track: str) -> FeatureSpec:
    return FEATURE_SETS[proto["tracks"][track]["superset_feature_set"]]


def event_definition(proto: dict[str, Any]) -> EventDefinition:
    e = proto["warnings"]["event"]
    return EventDefinition(float(e["threshold_mg_dl"]), float(e["confirm_minutes"]), float(e["recovery_minutes"]),
                           float(e["max_gap_minutes"]), float(e["jitter_minutes"]))


def decimate_patient(pdata: PatientData, step: float) -> tuple[PatientData, dict[str, int]]:
    g = pdata.glucose.sort_values(["observed_at", "available_at", "event_id"], kind="mergesort").reset_index(drop=True)
    keep = cn.causal_decimate(to_minutes(g["observed_at"]), step)
    dec = PatientData(pdata.meta, pdata.profile, g[keep].reset_index(drop=True), pdata.activity.iloc[0:0],
                      pdata.meals.iloc[0:0])
    return dec, {"retained": int(keep.sum()), "dropped": int((~keep).sum())}


def patient_rows(pdata: PatientData, spec: FeatureSpec, horizons: list[int], tol: float,
                 event: EventDefinition | None, dataset_id: str) -> tuple[pd.DataFrame, Prepared]:
    prep = prepare(pdata)
    origins = np.unique(prep.g_avail)
    fr = build_features(prep, origins, spec)
    df = fr.frame.copy()
    df.insert(0, "patient_id", pdata.patient_id)
    df.insert(1, "dataset_id", dataset_id)
    df.insert(2, "origin", origins)
    latest = fr.latest_index
    recs = np.array([(REC_RE.search(str(prep.g_ids[i])).group(1) if i >= 0 and REC_RE.search(str(prep.g_ids[i]))
                      else "r0") for i in latest], dtype=object)
    df["recording_id"] = [f"{pdata.patient_id}-{r}" for r in recs]
    first_by_rec: dict[str, float] = {}
    for i, gid in enumerate(prep.g_ids.tolist()):
        m = REC_RE.search(str(gid))
        r = f"{pdata.patient_id}-{m.group(1) if m else 'r0'}"
        first_by_rec[r] = min(first_by_rec.get(r, np.inf), float(prep.g_obs[i]))
    df["elapsed_min"] = origins - np.array([first_by_rec.get(r, np.nan) for r in df["recording_id"]])
    df["quality"] = fr.quality
    df["quality_reasons"] = [";".join(r) for r in fr.reasons]
    for h in horizons:
        tv, tt, ta = match_targets(prep.g_obs, prep.g_val, prep.g_avail, origins, h, tol)
        df[f"target_{h}"], df[f"target_{h}_at"], df[f"target_{h}_avail"] = tv, tt, ta
        if event is not None:
            lab = label_new_onsets(prep.g_obs, prep.g_val, event, h)
            pos = np.searchsorted(prep.g_obs, origins)
            df[f"label_{h}"] = lab.label[pos]
            df[f"onset_{h}"] = lab.onset_at[pos]
            df[f"label_{h}_support_end"] = lab.support_end[pos]
            df[f"label_{h}_censor"] = [lab.censor_reason[i] for i in pos]
            if h == horizons[0]:
                df["episode_state"] = [lab.state[i] for i in pos]
                df["ew_eligible"] = lab.eligible[pos]
    return df, prep


def _cache_ok(path: Path, key: str) -> bool:
    meta = path.with_suffix(".json")
    return path.exists() and meta.exists() and json.loads(meta.read_text()).get("cache_key") == key


def build_track(proto: dict[str, Any], track: str, store: Store, participant_ids: list[str], dataset_id: str,
                cache_dir: Path | None, data_fingerprint: str, order: dict[str, str] | None = None) -> TrackData:
    """``order`` (participant -> public source key) fixes the participant order of the table independently of the
    installation's pseudonym salt; row order matters to bagged and ordered boosting. Without it (protocol v1) rows are
    ordered by pseudonym, exactly as in the frozen experiment."""
    tcfg = proto["tracks"][track]
    spec = track_spec(proto, track)
    horizons = [int(h) for h in proto["horizons_minutes"]]
    tol = float(tcfg["target_match_tolerance_minutes"])
    cadence = float(tcfg["cadence_minutes"])
    event = event_definition(proto) if tcfg.get("events") else None
    decimate = track == "portable_15min"
    key = fingerprint({"track": track, "dataset": dataset_id, "participants": sorted(participant_ids),
                       "data": data_fingerprint, "transform": spec.transform_fingerprint(), "tol": tol,
                       "horizons": horizons, "event": None if event is None else event.__dict__,
                       "decimation": tcfg.get("decimation") if decimate else None, "builder": "research-tables-1",
                       **({"order": "public_source_key"} if order is not None else {})})
    rank = ({p: order[p] for p in participant_ids} if order is not None else {p: p for p in participant_ids})
    frames, preps, dec_counts = [], {}, {"retained": 0, "dropped": 0}
    path = cache_dir / f"{track}__{dataset_id}.parquet" if cache_dir is not None else None
    cached = path is not None and _cache_ok(path, key)
    for pid in sorted(participant_ids, key=rank.__getitem__):
        pdata = store.load(pid)
        if decimate:
            pdata, c = decimate_patient(pdata, cadence)
            dec_counts = {k: dec_counts[k] + c[k] for k in dec_counts}
        if cached:
            preps[pid] = prepare(pdata)
            continue
        df, prep = patient_rows(pdata, spec, horizons, tol, event, dataset_id)
        frames.append(df)
        preps[pid] = prep
    if cached:
        table = pd.read_parquet(path)
    else:
        table = pd.concat(frames, ignore_index=True)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            table.to_parquet(path, index=False)
            path.with_suffix(".json").write_text(json.dumps({"cache_key": key, "rows": len(table)}))
    table = (table.assign(_rank=table["patient_id"].map(rank)).sort_values(["_rank", "origin"], kind="mergesort")
             .drop(columns="_rank").reset_index(drop=True))
    meta = {"cache_key": key, "decimation": dec_counts if decimate else None, "rows": int(len(table)),
            "transform_fingerprint": spec.transform_fingerprint(), "feature_set": spec.feature_set_id}
    return TrackData(track, dataset_id, table, preps, cadence, tol, meta)
