"""Shared context for the research stages: protocol, stores, track tables and row masks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import fingerprint
from glucotwin.data import shanghai
from glucotwin.data.pipeline import dataset_store_dir
from glucotwin.data.store import Store
from glucotwin.research.protocol import DEFAULT_EXPERIMENT, load_protocol, research_dir
from glucotwin.research.tables import TrackData, build_track

V2_MODEL_DIR = Path("artifacts/models/lightgbm.dyn-v2.gt-primary-2026-10-11-v2")


def development_store() -> Store:
    return Store(dataset_store_dir())


def external_store() -> Store:
    return Store(shanghai.store_dir())


def store_fingerprint(store: Store) -> str:
    prov = store.directory / "provenance.json"
    return fingerprint(json.loads(prov.read_text())) if prov.exists() else fingerprint({"store": str(store.directory)})


def source_keys() -> dict[str, str]:
    """pseudonymous participant -> public source key (e.g. ``cgmacros:CGMacros-001``) from the private maps."""
    from glucotwin.config import paths

    out: dict[str, str] = {}
    for name, ds, key in (("cgmacros_pseudonym_map.json", "cgmacros", "source_key"),
                          ("shanghai_pseudonym_map.json", "shanghai_t2dm", "source_patient")):
        p = paths().private / name
        if p.exists():
            for row in json.loads(p.read_text()):
                out[row["patient_id"]] = f"{ds}:{row[key]}"
    return out


def development_ids(store: Store) -> list[str]:
    return sorted(p for p in store.patient_ids() if store.meta(p).get("eligible_for_primary_analysis"))


def external_ids(store: Store) -> list[str]:
    return sorted(p for p in store.patient_ids() if store.meta(p).get("eligible_for_portable_external"))


@dataclass
class Ctx:
    experiment_id: str
    proto: dict[str, Any]
    track: str
    td: TrackData
    horizons: list[int]
    seed: int

    @property
    def t(self) -> pd.DataFrame:
        return self.td.table

    @property
    def pids(self) -> np.ndarray:
        return self.t["patient_id"].to_numpy()

    @property
    def issued(self) -> np.ndarray:
        return (self.t["quality"] != "insufficient").to_numpy()

    def rows(self, participants) -> np.ndarray:
        return np.isin(self.pids, list(participants))

    def target(self, h: int) -> np.ndarray:
        return self.t[f"target_{h}"].to_numpy(float)

    def scored(self, participants, h: int) -> np.ndarray:
        return self.rows(participants) & self.issued & np.isfinite(self.target(h))

    def y(self, h: int) -> np.ndarray:
        return self.target(h) - self.t["g_last"].to_numpy(float)


def load_ctx(track: str, which: str = "development", experiment_id: str = DEFAULT_EXPERIMENT,
             participants: list[str] | None = None) -> Ctx:
    proto = load_protocol(experiment_id)
    store = development_store() if which == "development" else external_store()
    ids = development_ids(store) if which == "development" else external_ids(store)
    dataset_id = "cgmacros" if which == "development" else shanghai.DATASET_ID
    order = source_keys() if proto["folds"].get("assignment_key") == "source_participant_key" else None
    td = build_track(proto, track, store, ids, dataset_id, research_dir(experiment_id) / "tables",
                     store_fingerprint(store), order)
    if participants is not None:
        # a fold job only ever holds its own participants' rows (outer-assessment people are dropped here)
        keep = td.table["patient_id"].isin(list(participants)).to_numpy()
        td.table = td.table[keep].reset_index(drop=True)
        td.prep = {p: v for p, v in td.prep.items() if p in set(participants)}
    return Ctx(experiment_id, proto, track, td, [int(h) for h in proto["horizons_minutes"]], int(proto["random_seed"]))


def v2_recipe() -> dict[str, Any]:
    from glucotwin.config import paths

    m = json.loads((paths().root / V2_MODEL_DIR / "manifest.json").read_text())
    params = {}
    for h, p in m["params"].items():
        params[int(h)] = {k: v for k, v in p.items() if k not in ("best_iteration", "fit_seconds")}
        params[int(h)]["_rounds"] = int(p["best_iteration"])
    return {"feature_set": m["feature_set_id"], "params": params, "adaptation": m["serving"]["adaptation"],
            "threshold": m["serving"]["alerts"]["threshold_margin_mg_dl"], "model_version": m["serving"]["model_version"]}
