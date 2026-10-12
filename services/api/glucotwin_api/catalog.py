"""Participant catalogue over the dataset store and the synthetic store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from glucotwin.data.pipeline import dataset_store_dir, synthetic_store_dir
from glucotwin.data.store import PatientData, Store, to_minutes
from glucotwin.splits import Boundaries

KIND_RANK = {"glucose": 0, "activity": 1, "meal": 2}


@dataclass
class SourceTimeline:
    """Full recording for the replay SOURCE (never handed to the twin engine)."""

    pdata: PatientData
    avail: dict[str, np.ndarray]          # per table: available_at minutes (tables sorted by available_at)
    order: list[tuple[float, float, int, str, str, int]]  # (avail, obs, kind rank, event_id, table, row)
    order_avail: np.ndarray
    start: float
    end: float

    def released(self, clock: float) -> PatientData:
        cut = {k: int(np.searchsorted(a, clock + 1e-6, "right")) for k, a in self.avail.items()}
        p = self.pdata
        return PatientData(p.meta, p.profile, p.glucose.iloc[: cut["glucose"]], p.activity.iloc[: cut["activity"]],
                           p.meals.iloc[: cut["meals"]])

    def released_count(self, clock: float) -> int:
        return int(np.searchsorted(self.order_avail, clock + 1e-6, "right"))


class Catalog:
    def __init__(self) -> None:
        self.stores: dict[str, Store] = {}
        for mode, d in (("dataset_replay", dataset_store_dir()), ("synthetic_demo", synthetic_store_dir())):
            s = Store(d)
            if s.exists():
                self.stores[mode] = s
        self._meta: dict[str, dict[str, Any]] = {}
        self._mode: dict[str, str] = {}
        for mode, s in self.stores.items():
            for pid in s.patient_ids():
                m = s.meta(pid)
                if not m.get("visible", True):
                    continue
                self._meta[pid] = m
                self._mode[pid] = mode
        self.boundaries = self._load_boundaries()

    def _load_boundaries(self) -> dict[str, Boundaries]:
        out: dict[str, Boundaries] = {}
        from glucotwin.dataset import current_split_manifest

        path = current_split_manifest(dataset_store_dir())
        if path.exists():
            for p in json.loads(path.read_text())["patients"]:
                out[p["patient_id"]] = Boundaries(**p["boundaries_minutes"])
        return out

    def ids(self) -> list[str]:
        return list(self._meta)

    def has(self, pid: str) -> bool:
        return pid in self._meta

    def meta(self, pid: str) -> dict[str, Any]:
        return self._meta[pid]

    def mode(self, pid: str) -> str:
        return self._mode[pid]

    def profile(self, pid: str) -> list[dict[str, Any]]:
        return self.stores[self._mode[pid]].profile(pid)

    @lru_cache(maxsize=8)  # noqa: B019 - small bounded cache of immutable recordings
    def timeline(self, pid: str) -> SourceTimeline:
        pdata = self.stores[self._mode[pid]].load(pid)
        avail = {k: to_minutes(getattr(pdata, k)["available_at"]) for k in ("glucose", "activity", "meals")}
        order = []
        for table, kind in (("glucose", "glucose"), ("activity", "activity"), ("meals", "meal")):
            df = getattr(pdata, table)
            obs = to_minutes(df["observed_at"])
            for i, (a, o, eid) in enumerate(zip(avail[table].tolist(), obs.tolist(), df["event_id"].tolist(),
                                                strict=True)):
                order.append((a, o, KIND_RANK[kind], str(eid), table, i))
        order.sort()
        start = float(to_minutes(pd.Series([pdata.meta["timeline_start"]]))[0])
        end = float(to_minutes(pd.Series([pdata.meta["timeline_end"]]))[0])
        return SourceTimeline(pdata, avail, order, np.array([o[0] for o in order]), start, end)
