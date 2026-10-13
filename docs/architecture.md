# GlucoTwin architecture

GlucoTwin is a small, local, CPU-only research application. One Python package (`ml/glucotwin`) owns data,
features, labels, models, adaptation and evaluation; one FastAPI service (`services/api`) owns replay sessions
and exposes the shared contract; one React app (`apps/web`) renders it. A PDF export of this document's diagram
is in [`docs/submission/GlucoTwin_Architecture.pdf`](submission/GlucoTwin_Architecture.pdf).

## Data flow

```text
                       OFFLINE (reproducible commands)                              ONLINE (local demo)
 ┌──────────────────────┐   verify SHA-256   ┌────────────────────────────┐
 │ CGMacros 1.0.0 (CSV) │ ─────────────────▶ │ cgmacros-adapter-1.0       │
 │ data/raw (ignored)   │                    │ • native Dexcom recovery   │
 └──────────────────────┘                    │ • 5-min activity summaries │
 ┌──────────────────────┐                    │ • meals, baseline profile  │
 │ Synthetic generator  │ ─────────────────▶ │ • synthetic UTC timeline   │
 └──────────────────────┘                    └─────────────┬──────────────┘
                                                           ▼
                               ┌──────────────────────────────────────────────┐
                               │ Canonical store (Parquet per patient + SQLite)│
                               └───────┬───────────────────────────┬──────────┘
                                       │                           │ full recording = replay SOURCE
                     build_features ◀──┘                           ▼
   ┌───────────────────────────────────────────┐      ┌──────────────────────────────────────┐
   │ Origin table: features, quality, targets, │      │ Replay session (backend-owned clock)  │
   │ new-onset labels, chronological splits    │      │ releases events with available_at ≤ t │
   └──────────────────┬────────────────────────┘      └──────────────────┬───────────────────┘
                      ▼                                                  ▼ released events only
   ┌───────────────────────────────────────────┐      ┌──────────────────────────────────────┐
   │ Experiment: baselines, LightGBM, CatBoost  │      │ TwinEngine (per session revision)     │
   │ validation-only selection, adaptation,     │─────▶│ build_features → population model →  │
   │ conformal intervals, alert threshold,      │ artifact  AdaptationState → interval → score│
   │ single final-test evaluation               │ registry │ → episode state → alert → Forecast │
   └──────────────────┬────────────────────────┘      └──────────────────┬───────────────────┘
                      ▼                                                  ▼ /api/v1 (schema 1.0)
   metrics.json · predictions.parquet · alerts.json        React clinician workspace (polling)
   reports/evaluation_report.md                            Landing page (/) · workspace (/app): Overview ·
                                                           Participants · Sessions · Model evidence · Data quality
```

The same functions run in both columns: `glucotwin.features.build_features` (features and quality),
`glucotwin.models.adaptation.AdaptationState` (personalization), `glucotwin.events.EpisodeMachine`
(event state). Tests compare offline and online outputs (`tests/test_replay_api.py::test_offline_features_match_online_engine`)
and the reloaded artifact reproduces every evaluated adaptive prediction exactly (max absolute difference 0.0).

## The operational twin

A GlucoTwin "twin" is a **versioned patient state** plus a **forecasting model** updated by **incoming
observations**:

| Part | Implementation |
|---|---|
| Initialization | Baseline profile values available at twin initialization (screening labs, demographics) and an empty adaptation state |
| Observations | Native CGM readings, 5-minute wearable summaries, meal records (context only), released by the replay clock |
| Model | Population forecaster (serving: LightGBM on the baseline profile plus dynamic features, `dyn-prof-v2`) predicting 30- and 60-minute glucose change; it abstains if a profile value is unavailable |
| Patient state | Per-horizon shrunk, bounded, decaying bias correction learned only from matured forecast errors; episode state; issued-forecast history |
| Outputs | Immutable forecasts with conformal prediction ranges (target coverage 80 %), uncalibrated warning score, factual explanations, research alerts |

It is a **statistical research twin**, not a validated physiological simulator.

## Forecast lifecycle and the availability boundary

1. A native glucose reading becomes available at time `t` → `t` is a forecast origin.
2. Features use only records with `observed_at ≤ t` **and** `available_at ≤ t`.
3. The population model predicts glucose change at 30 and 60 minutes; the adaptation state adds a correction
   learned from earlier forecasts whose target readings were already available.
4. Conformal quantiles (calibrated on the calibration segment for this exact pipeline) give prediction ranges with a
   target coverage of 80 % (measured test coverage is lower and reported).
5. The warning score is `max(forecasts within H) − 180 mg/dL`; the alert rule fires only in the online
   `normal` episode state and above the validation-selected threshold.
6. The forecast is stored immutably (SQLite, `INSERT OR IGNORE`) under a deterministic ID
   `uuid5(session, revision, origin, model_version)`.
7. Later readings reveal outcomes only when the replay clock passes their availability time.

Seek and reset create a new **session revision**: the engine is rebuilt from scratch from events released by the
new clock; old cursors return `409 stale_cursor`; the browser keys every cache by `(session, revision, clock)` and
discards responses from other revisions.

## State ownership

| State | Owner | Lifetime |
|---|---|---|
| Source recordings, profiles | Canonical store | Persistent (local, git-ignored) |
| Replay clock, status, revision | `SessionManager` (API process) | In memory; ends when the API restarts |
| Patient adaptation, episode state, alerts | `TwinEngine` per session revision | Rebuilt deterministically on seek/reset |
| Issued forecasts (audit) | SQLite `var/glucotwin.sqlite3` | Persistent, all revisions; queries filter to current revision |
| Review acknowledgements | SQLite | Persistent; local only (no messages are sent) |
| Model artifacts + selection | `artifacts/registry.json` | Versioned, checksummed |
| UI preferences | Browser `localStorage` | Optional; defaults if storage is unavailable |

## Technology

| Layer | Choice (installed versions recorded in `uv.lock` / `apps/web/package-lock.json`) |
|---|---|
| Data & models | Python 3.12, NumPy 2.5, pandas 3.0, PyArrow 26, scikit-learn 1.9, LightGBM 4.7, CatBoost 1.2.10 |
| API | FastAPI 0.143, Pydantic 2.14, Uvicorn 0.54, SQLite |
| Web | React 19.3, TypeScript 5.9, Vite 8.3, React Router 7, TanStack Query 5, Recharts 3, Lucide icons, Inter (bundled) |
| Contracts | Pydantic → OpenAPI (`packages/contracts/openapi.json`) → `openapi-typescript` types |
| Tests | pytest, Vitest + Testing Library, Playwright (Chromium) |

No cloud account, GPU, API key or LLM is used. Optional Chronos-Bolt dependencies live in a separate extra and
are not installed by default.

## Security and deployment posture

Local demonstration defaults: loopback binding, narrow CORS (`localhost:5173/4173` only), no authentication, no
external network calls at runtime, trusted local artifacts verified by SHA-256 before loading, no pickles. This is
**not** a production or regulatory-compliant deployment.

## Research runner and canonical data layer (prompt pack v4)

* `ml/glucotwin/data/canonical.py` — provenance-carrying canonical CGM records (`canonical-cgm-1`), unit handling,
  LOW/HIGH codes, timestamp anomalies, causal decimation and shift-invariant overlap signatures. Adapters:
  `cgmacros.py` (export only; the model store is unchanged), `shanghai.py`, `aireadi.py` (fixtures only).
  `inventory.py` writes the source manifest and `reports/dataset_expansion_audit.md`.
* `ml/glucotwin/research/` — isolated nested experiments: `protocol` (frozen membership), `tables` (origin tables with
  the serving feature code), `develop` (inner participant CV, selection, adaptation, workload-aware thresholds, refit,
  calibration, freeze), `assess` (outer folds and the external cohort, each opened once; candidate packaging and
  online/offline parity), `report`/`render` (everything recomputed from saved predictions) and `promote` (explicit,
  atomic, verified registry change with rollback). Nothing in this package writes the registry implicitly.
* API: `/evaluations`, `/evaluations/{id}`, `/research/{id}`, `/serving`, `/datasets`; `/patients` filters, sorts and
  pages on the server. The Model evidence page shows the serving model on its own line above whichever experiment is
  selected.
