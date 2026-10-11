"""Population forecasters (one direct model per horizon) and their trusted, non-pickle serialization.

Every model predicts the glucose CHANGE from the latest available reading (``delta_from_latest``);
``PopulationBundle.predict`` adds the latest reading back. Families:

* ``persistence``  — future = latest reading
* ``linear_trend`` — bounded, damped extrapolation of a trailing slope
* ``ridge``        — median imputation + missing indicators + standardization + ridge (training-fitted)
* ``lightgbm``     — gradient-boosted trees (LightGBM text model format)
* ``catboost``     — ordered boosting (CatBoost .cbm format)

Artifacts are written as JSON/text/cbm plus a manifest with SHA-256 checksums; loading verifies the
checksums and the feature order. Python pickles are never written or loaded.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from glucotwin.config import file_sha256
from glucotwin.features import FEATURE_SETS

COMPLEXITY = ["persistence", "linear_trend", "ridge", "lightgbm", "catboost"]


class ArtifactError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------
# Per-horizon delta models
# ------------------------------------------------------------------------------------------------


class DeltaModel:
    family: str = ""

    def predict_delta(self, X: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError

    def save(self, directory: Path, stem: str) -> list[str]:
        raise NotImplementedError


class PersistenceModel(DeltaModel):
    family = "persistence"

    def predict_delta(self, X: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(X))

    def save(self, directory: Path, stem: str) -> list[str]:
        return []


@dataclass
class LinearTrendModel(DeltaModel):
    horizon: int
    window: int = 30
    damping: float = 0.5
    max_change: float = 120.0
    family: str = "linear_trend"

    def predict_delta(self, X: pd.DataFrame) -> np.ndarray:
        slope = X[f"slope_{self.window}"].to_numpy(float)
        delta = np.clip(np.nan_to_num(slope, nan=0.0) * self.horizon * self.damping, -self.max_change, self.max_change)
        return delta

    def params(self) -> dict[str, Any]:
        return {"window": self.window, "damping": self.damping, "max_change": self.max_change}

    def save(self, directory: Path, stem: str) -> list[str]:
        p = directory / f"{stem}.json"
        p.write_text(json.dumps(self.params()))
        return [p.name]


@dataclass
class RidgeModel(DeltaModel):
    columns: list[str]
    alpha: float = 1.0
    medians: np.ndarray | None = None
    indicator_cols: list[int] = field(default_factory=list)
    mean: np.ndarray | None = None
    scale: np.ndarray | None = None
    coef: np.ndarray | None = None
    intercept: float = 0.0
    family: str = "ridge"

    def _design(self, X: pd.DataFrame) -> np.ndarray:
        A = X[self.columns].to_numpy(float)
        miss = np.isnan(A)
        A = np.where(miss, self.medians, A)
        if self.indicator_cols:
            A = np.hstack([A, miss[:, self.indicator_cols].astype(float)])
        return (A - self.mean) / self.scale

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> RidgeModel:
        from sklearn.linear_model import Ridge

        A = X[self.columns].to_numpy(float)
        miss = np.isnan(A)
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-missing columns -> median 0 below
            med = np.nanmedian(A, axis=0)
        self.medians = np.where(np.isnan(med), 0.0, med)
        self.indicator_cols = [i for i in range(A.shape[1]) if miss[:, i].any()]
        A = np.where(miss, self.medians, A)
        if self.indicator_cols:
            A = np.hstack([A, miss[:, self.indicator_cols].astype(float)])
        self.mean = A.mean(axis=0)
        sd = A.std(axis=0)
        self.scale = np.where(sd > 1e-9, sd, 1.0)
        m = Ridge(alpha=self.alpha).fit((A - self.mean) / self.scale, y)
        self.coef, self.intercept = m.coef_.astype(float), float(m.intercept_)
        return self

    def predict_delta(self, X: pd.DataFrame) -> np.ndarray:
        return self._design(X) @ self.coef + self.intercept

    def save(self, directory: Path, stem: str) -> list[str]:
        p = directory / f"{stem}.json"
        p.write_text(json.dumps({
            "alpha": self.alpha, "columns": self.columns, "medians": self.medians.tolist(),
            "indicator_cols": self.indicator_cols, "mean": self.mean.tolist(), "scale": self.scale.tolist(),
            "coef": self.coef.tolist(), "intercept": self.intercept,
        }))
        return [p.name]

    @classmethod
    def load(cls, path: Path) -> RidgeModel:
        d = json.loads(path.read_text())
        return cls(columns=d["columns"], alpha=d["alpha"], medians=np.array(d["medians"]),
                   indicator_cols=d["indicator_cols"], mean=np.array(d["mean"]), scale=np.array(d["scale"]),
                   coef=np.array(d["coef"]), intercept=d["intercept"])


class LightGBMModel(DeltaModel):
    family = "lightgbm"

    def __init__(self, columns: list[str], params: dict[str, Any] | None = None, booster=None):
        self.columns = columns
        self.params = dict(params or {})
        self.booster = booster
        self.best_iteration: int | None = None

    def fit(self, X, y, Xv, yv, seed: int, early_stopping: int, max_rounds: int) -> LightGBMModel:
        import lightgbm as lgb

        p = {
            "objective": "regression", "metric": "l2", "verbosity": -1, "seed": seed, "deterministic": True,
            "force_row_wise": True, "num_threads": 4, "bagging_freq": 1, **self.params,
        }
        dtrain = lgb.Dataset(X[self.columns].to_numpy(float), label=y, feature_name=self.columns, free_raw_data=False)
        dval = lgb.Dataset(Xv[self.columns].to_numpy(float), label=yv, reference=dtrain)
        self.booster = lgb.train(p, dtrain, num_boost_round=max_rounds, valid_sets=[dval],
                                 callbacks=[lgb.early_stopping(early_stopping, verbose=False)])
        self.best_iteration = int(self.booster.best_iteration or self.booster.current_iteration())
        return self

    def predict_delta(self, X: pd.DataFrame) -> np.ndarray:
        return self.booster.predict(X[self.columns].to_numpy(float), num_iteration=self.best_iteration)

    def save(self, directory: Path, stem: str) -> list[str]:
        p = directory / f"{stem}.lgb.txt"
        self.booster.save_model(str(p), num_iteration=self.best_iteration)
        return [p.name]

    @classmethod
    def load(cls, path: Path, columns: list[str]) -> LightGBMModel:
        import lightgbm as lgb

        booster = lgb.Booster(model_file=str(path))
        if list(booster.feature_name()) != list(columns):
            raise ArtifactError(f"Feature order mismatch in {path.name}")
        m = cls(columns, booster=booster)
        return m


class CatBoostModel(DeltaModel):
    family = "catboost"

    def __init__(self, columns: list[str], params: dict[str, Any] | None = None, model=None):
        self.columns = columns
        self.params = dict(params or {})
        self.model = model

    def fit(self, X, y, Xv, yv, seed: int, early_stopping: int, max_rounds: int) -> CatBoostModel:
        from catboost import CatBoostRegressor

        self.model = CatBoostRegressor(
            loss_function="RMSE", iterations=max_rounds, random_seed=seed, verbose=False, thread_count=4,
            allow_writing_files=False, od_type="Iter", od_wait=early_stopping, use_best_model=True,
            nan_mode="Min", **self.params,
        )
        self.model.fit(X[self.columns].to_numpy(float), y, eval_set=(Xv[self.columns].to_numpy(float), yv))
        return self

    @property
    def best_iteration(self) -> int | None:
        return int(self.model.get_best_iteration()) if self.model is not None else None

    def predict_delta(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X[self.columns].to_numpy(float))

    def save(self, directory: Path, stem: str) -> list[str]:
        p = directory / f"{stem}.cbm"
        self.model.save_model(str(p), format="cbm")
        return [p.name]

    @classmethod
    def load(cls, path: Path, columns: list[str]) -> CatBoostModel:
        from catboost import CatBoostRegressor

        m = CatBoostRegressor()
        m.load_model(str(path), format="cbm")
        return cls(columns, model=m)


# ------------------------------------------------------------------------------------------------
# Bundle across horizons
# ------------------------------------------------------------------------------------------------


@dataclass
class PopulationBundle:
    family: str
    feature_set_id: str
    horizons: list[int]
    models: dict[int, DeltaModel]
    label: str = ""
    params: dict[int, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def columns(self) -> list[str]:
        return FEATURE_SETS[self.feature_set_id].columns()

    def predict(self, X: pd.DataFrame) -> dict[int, np.ndarray]:
        g_last = X["g_last"].to_numpy(float)
        return {h: g_last + self.models[h].predict_delta(X) for h in self.horizons}

    def measure_latency_ms_per_1k(self, X: pd.DataFrame, repeats: int = 3) -> float:
        sample = X.iloc[: min(len(X), 1000)]
        best = np.inf
        for _ in range(repeats):
            t0 = time.perf_counter()
            self.predict(sample)
            best = min(best, time.perf_counter() - t0)
        return float(best * 1000 * 1000 / max(1, len(sample)))

    def save(self, directory: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        directory.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = {}
        for h in self.horizons:
            for name in self.models[h].save(directory, f"h{h}"):
                files[name] = file_sha256(directory / name)
        manifest = {
            "artifact_format": "glucotwin-population-1",
            "family": self.family, "feature_set_id": self.feature_set_id, "label": self.label,
            "horizons": self.horizons, "columns": self.columns, "target": "delta_from_latest",
            "params": {str(h): p for h, p in self.params.items()}, "files": files,
            **(extra or {}),
        }
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
        return manifest

    @classmethod
    def load(cls, directory: Path) -> PopulationBundle:
        mpath = directory / "manifest.json"
        if not mpath.exists():
            raise ArtifactError(f"No model manifest at {mpath}")
        m = json.loads(mpath.read_text())
        if m.get("artifact_format") != "glucotwin-population-1":
            raise ArtifactError(f"Unsupported artifact format {m.get('artifact_format')!r}")
        if m["feature_set_id"] not in FEATURE_SETS:
            raise ArtifactError(f"Unknown feature set {m['feature_set_id']!r}")
        if FEATURE_SETS[m["feature_set_id"]].columns() != m["columns"]:
            raise ArtifactError("Artifact feature order differs from this code version's feature set")
        for name, digest in m["files"].items():
            if file_sha256(directory / name) != digest:
                raise ArtifactError(f"Checksum mismatch for {name}; refusing to load an altered artifact")
        horizons = [int(h) for h in m["horizons"]]
        models: dict[int, DeltaModel] = {}
        fam = m["family"]
        for h in horizons:
            params = m["params"].get(str(h), {})
            if fam == "persistence":
                models[h] = PersistenceModel()
            elif fam == "linear_trend":
                models[h] = LinearTrendModel(h, **params)
            elif fam == "ridge":
                models[h] = RidgeModel.load(directory / f"h{h}.json")
            elif fam == "lightgbm":
                models[h] = LightGBMModel.load(directory / f"h{h}.lgb.txt", m["columns"])
            elif fam == "catboost":
                models[h] = CatBoostModel.load(directory / f"h{h}.cbm", m["columns"])
            else:
                raise ArtifactError(f"Unknown model family {fam!r}")
        return cls(fam, m["feature_set_id"], horizons, models, m.get("label", ""),
                   {int(k): v for k, v in m["params"].items()}, m)
