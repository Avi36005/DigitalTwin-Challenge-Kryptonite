# Artifact manifest

| Artifact | Purpose | Producing command | Source dependency | Sharing status |
|---|---|---|---|---|
| `data/raw/cgmacros/1.0.0/*` | Original CGMacros files (657 MB zip + metadata) | `make data-download` | PhysioNet (CC BY-NC-SA 4.0) | Local only (git-ignored) |
| `data/processed/cgmacros/v1/` | Normalized store, `audit.json`, `provenance.json`, `experiment/origins.parquet`, `split_manifest.json` | `make data` | CGMacros | Local only — patient-level derived data |
| `data/private/*` | Pseudonym salt and participant↔pseudonym map, time offsets | `make data` | — | Never shared |
| `data/synthetic/generated/v1/` | Synthetic fixtures store | `make synthetic` | Generator code (CC0) | Regenerable; git-ignored |
| `artifacts/models/lightgbm.dyn-v1.gt-primary-2026-10-11-v1/` | Serving model (`h30.lgb.txt`, `h60.lgb.txt`, `manifest.json`, `serving.json`) | `make experiment` | CGMacros-derived | Local only; not redistributed (no legal clearance assumed) |
| `artifacts/models/synthetic-demo.lightgbm.dyn-v1.v1/` | Synthetic demonstration model | `make synthetic` | Synthetic data | Regenerable |
| `artifacts/experiments/gt-primary-2026-10-11-v1/` | `metrics.json`, `predictions.parquet` (per-origin predictions), `alerts.json`, `search_log.json` | `make experiment` | CGMacros-derived | Local; `metrics.json` aggregates may be shared |
| `artifacts/registry.json` | Serving model per mode, checksums, rationale | `make experiment`, `make synthetic` | — | Local |
| `reports/data_audit.md`, `reports/evaluation_report.md` | Aggregate audit and results (pseudonymous aliases only) | `make report` | Saved artifacts | Committed |
| `reports/ui/*.png` | UI screenshots (synthetic and recorded replay) | `make e2e` | Running app | Committed (CGMacros-derived visuals attributed) |
| `docs/submission/*.pptx, *.pdf`, `docs/assets/*.png` | Presentation, architecture PDF, charts | `uv run python scripts/build_submission_assets.py` | `metrics.json`, screenshots | Committed |
| `packages/contracts/openapi.json`, `examples/`, `src/schema.d.ts` | Shared contract | `make contracts` | Code | Committed |
| `var/glucotwin.sqlite3` | Issued-forecast audit, acknowledgements, session log | Running API | — | Local only |

Checksums: model files are listed with SHA-256 in each `manifest.json` and verified on load; source files are
verified against `SHA256SUMS.txt` and recorded in `provenance.json`.

Fingerprints for experiment `gt-primary-2026-10-11-v1`: config `e049a6a7769f8ff8`, data `289d296590837618`,
split `b31e8d8c071eb425` (also stored in `metrics.json` and `serving.json`).
