"""Serving model adapter: one interface for whichever evaluated artifact is selected.

The API never contains algorithm-specific code; it asks this adapter for population predictions,
optional tree contributions, adaptation policy, interval quantiles and the alert rule. If the
registered artifact is missing or fails verification, ``load_serving`` returns ``None`` and the API
reports the model as not ready instead of substituting another model under the selected name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import paths
from glucotwin.features import FEATURE_SETS, FeatureSpec
from glucotwin.models.adaptation import AdaptationPolicy
from glucotwin.models.population import ArtifactError, PopulationBundle


@dataclass
class ServingModel:
    model_version: str
    bundle: PopulationBundle
    config: dict[str, Any]
    artifact_dir: Path

    @property
    def family(self) -> str:
        return self.bundle.family

    @property
    def horizons(self) -> list[int]:
        return self.bundle.horizons

    @property
    def spec(self) -> FeatureSpec:
        return FEATURE_SETS[self.bundle.feature_set_id]

    @property
    def synthetic_fitted(self) -> bool:
        return bool(self.config.get("synthetic_fitted"))

    @property
    def policy(self) -> AdaptationPolicy:
        return AdaptationPolicy(**self.config["adaptation"])

    def interval_q(self, h: int) -> float | None:
        q = self.config.get("intervals", {}).get("quantiles_mg_dl", {}).get(str(h))
        return float(q) if q is not None else None

    @property
    def interval_level(self) -> float | None:
        return self.config.get("intervals", {}).get("level")

    @property
    def alert(self) -> dict[str, Any]:
        return self.config.get("alerts", {})

    def predict(self, X: pd.DataFrame) -> dict[int, np.ndarray]:
        return self.bundle.predict(X)

    def contributions(self, X: pd.DataFrame, h: int) -> list[tuple[str, float]] | None:
        """Tree contributions (TreeSHAP) for the POPULATION model at horizon ``h``; None if unsupported."""
        model = self.bundle.models[h]
        cols = self.bundle.columns
        try:
            if self.family == "lightgbm":
                contrib = model.booster.predict(X[cols].to_numpy(float), pred_contrib=True)[0]
            elif self.family == "catboost":
                from catboost import Pool

                contrib = model.model.get_feature_importance(Pool(X[cols].to_numpy(float)), type="ShapValues")[0]
            else:
                return None
        except Exception:  # explanation is optional; never fabricate one
            return None
        pairs = list(zip(cols, contrib[:-1].tolist(), strict=True))
        return sorted(pairs, key=lambda p: -abs(p[1]))


def load_serving(mode: str) -> ServingModel | None:
    reg_path = paths().artifacts / "registry.json"
    if not reg_path.exists():
        return None
    reg = json.loads(reg_path.read_text())
    version = reg.get("serving", {}).get(mode)
    if not version:
        return None
    entry = next((m for m in reg["models"] if m["model_version"] == version), None)
    if entry is None:
        return None
    directory = paths().root / entry["artifact_dir"]
    try:
        bundle = PopulationBundle.load(directory)
        cfg = json.loads((directory / "serving.json").read_text())
    except (ArtifactError, FileNotFoundError, json.JSONDecodeError):
        return None
    if cfg.get("model_version") != version:
        return None
    return ServingModel(version, bundle, cfg, directory)
