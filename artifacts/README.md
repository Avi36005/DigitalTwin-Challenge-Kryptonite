# artifacts/

Generated, versioned model outputs. Contents are **git-ignored by default** (see `docs/artifact_manifest.md`).

* `models/<model_version>/` — trusted model artifacts (LightGBM text / CatBoost `.cbm` / JSON), `manifest.json`
  with SHA-256 checksums and feature order, and `serving.json` (adaptation policy, conformal quantiles, alert rule).
* `experiments/<experiment_id>/` — `metrics.json`, `predictions.parquet`, `alerts.json`, `search_log.json`.
* `registry.json` — which artifact serves each mode, with selection rationale and evaluation reference.

Models trained on CGMacros are derived from a CC BY-NC-SA 4.0 dataset; they are not redistributed here.
Regenerate them with `make data experiment` after obtaining the dataset.
