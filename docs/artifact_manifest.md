# Artifact manifest

| Artifact | Purpose | Producing command | Source dependency | Sharing status |
|---|---|---|---|---|
| `data/raw/cgmacros/1.0.0/*` | Original CGMacros files (657 MB zip + metadata) | `make data-download` | PhysioNet (CC BY-NC-SA 4.0) | Local only (git-ignored) |
| `data/processed/cgmacros/v1/` | Normalized store, `audit.json`, `provenance.json`; origin tables + split manifests per experiment (`experiment/` = v1, `experiment/gt-primary-2026-10-11-v2/` = v2) | `make data` | CGMacros | Local only — patient-level derived data |
| `data/raw/shanghai/figshare-21600933.v5/diabetes_datasets.zip` | ShanghaiT2DM archive (3.7 MB, publisher MD5 verified) | `make data-shanghai` | figshare (CC BY 4.0) | Local only (git-ignored) |
| `data/processed/shanghai/v1/` | ShanghaiT2DM model store, `audit.json`, `provenance.json` | `make data-shanghai` | ShanghaiT2DM | Local only — participant-level derived data |
| `data/processed/canonical/canonical-cgm-1/` | Provenance-carrying canonical CGM partitions per dataset and person | `make manifest`, `make data-shanghai` | CGMacros, ShanghaiT2DM | Local only |
| `data/processed/source_manifest.json` | Full source manifest with local paths | `glucotwin data manifest` | All sources | Local only |
| `data/private/*` | Pseudonym salt and participant↔pseudonym map, time offsets | `make data` | — | Never shared |
| `data/synthetic/generated/v1/` | Synthetic fixtures store | `make synthetic` | Generator code (CC0) | Regenerable; git-ignored |
| `artifacts/models/lightgbm.dyn-v2.gt-primary-2026-10-11-v2/` | Serving model (`h30.lgb.txt`, `h60.lgb.txt`, `manifest.json` with transformation fingerprint, `serving.json`) | `make experiment` | CGMacros-derived | Local only; not redistributed (no legal clearance assumed) |
| `artifacts/models/lightgbm.dyn-v1.gt-primary-2026-10-11-v1/` | Original v1 model (legacy activity windows); kept for traceability, not serving | `glucotwin experiment run --experiment gt-primary-2026-10-11-v1` | CGMacros-derived | Local only |
| `artifacts/models/synthetic-demo.lightgbm.dyn-v2.v1/` | Synthetic demonstration model | `make synthetic` | Synthetic data | Regenerable |
| `artifacts/experiments/gt-primary-2026-10-11-v2/` (serving) and `…-v1/` (original) | `metrics.json`, `predictions.parquet` (per-origin predictions), `alerts.json` (with firing times and both lead measures in v2), `search_log.json` | `make experiment` | CGMacros-derived | Local; `metrics.json` aggregates may be shared |
| `artifacts/registry.json` | Serving model per mode, checksums, rationale | `make experiment`, `make synthetic` | — | Local |
| `reports/data_audit.md`, `reports/evaluation_report.md` | Aggregate audit and results for the serving experiment (pseudonymous aliases only) | `make report` | Saved artifacts | Committed |
| `reports/archive/evaluation_report_gt-primary-2026-10-11-v1.md`, `reports/repair_report.md` | Preserved v1 report; corrections, reproductions and migration | Copied / written | Saved artifacts | Committed |
| `artifacts/research/gt-nested-2026-10-12-v1/` | Isolated research experiment: `splits.json` (frozen membership), `smoke.json`, `tables/`, `development/<fold>/<track>/` (pipeline.json, bundles, inner out-of-fold and calibration predictions, search trace), `assessment/` and `external/` (predictions, events, `opened.json` locks), `candidates/<track>/` (packaged frozen candidates with checksums and parity), `report.json` | `make research` | CGMacros-, ShanghaiT2DM-derived | Local only; never written to the registry |
| `reports/dataset_expansion_audit.md`, `reports/dataset_inventory.json` | Measured data inventory (aggregate only) | `glucotwin data manifest` | Local data | Committed |
| `reports/nested_benchmark_report.md`, `reports/model_upgrade_review.md`, `reports/figures/*.png` | Research results and candidate handoff, generated from saved predictions | `make research-report` | Research artifacts | Committed (aggregate only) |
| `reports/ui/*.png` | UI screenshots (synthetic and recorded replay) | `make e2e` | Running app | Committed (CGMacros-derived visuals attributed) |
| `docs/submission/*.pptx, *.pdf`, `docs/assets/fig_architecture.png` | Presentation, architecture PDF, architecture figure (README) | `uv run --group docs python scripts/build_submission_assets.py` | serving `metrics.json`, screenshots | Committed |
| `build/figures/*.png` | Charts embedded in the deck | same script | serving `metrics.json` | Regenerated; git-ignored |
| `apps/web/src/content/landing-preview.json` | Landing-page chart: one synthetic-demonstration snapshot | `uv run python scripts/landing_preview.py` | Synthetic model | Committed (fictional data) |
| `packages/contracts/openapi.json`, `examples/`, `src/schema.d.ts` | Shared contract | `make contracts` | Code | Committed |
| `var/glucotwin.sqlite3` | Issued-forecast audit, acknowledgements, session log | Running API | — | Local only |

Checksums: model files are listed with SHA-256 in each `manifest.json` and verified on load; source files are
verified against `SHA256SUMS.txt` and recorded in `provenance.json`.

Fingerprints (also stored in `metrics.json` and `serving.json`): v2 (serving) config `33d8d94369043801`, data
`289d296590837618`, split `b31e8d8c071eb425`, transformation `8e85d78d17122ef4`; v1 config `e049a6a7769f8ff8`, same data and
split. A model whose transformation fingerprint differs from the code's feature set is refused on load.
