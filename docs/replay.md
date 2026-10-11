# Replay

The backend owns the replay clock. Sessions live in the API process and end when it restarts; issued forecasts
and acknowledgements persist in `var/glucotwin.sqlite3`.

## Lifecycle

```text
POST /replay/sessions ──► ready ──play──► playing ──pause──► paused ──step──► paused
                            │                │                       │
                            └──── seek / reset (new revision, state rebuilt) ◄──┘
                                              └──► completed (clock reached the end)
```

* **Clock:** starts at the timeline start (or `start_at`). `play` advances lazily on every read in whole 5-minute
  steps: `clock = anchor + floor(elapsed_seconds × speed / 5) × 5` minutes, where `speed` is replay minutes per
  wall-clock second (1–240). Event release is therefore deterministic for a given clock.
* **Step:** `steps × 5` minutes (1–2016), leaves the session paused.
* **Seek / reset:** `revision += 1`; the `TwinEngine` is rebuilt from scratch using only events released by the new
  clock; no future observation, forecast, alert or adaptation state survives; old cursors are rejected.
* **Concurrency:** each session has its own lock; commands serialise; sessions never share state.

## Release order and cursors

Events are released when `available_at ≤ clock`, ordered by `(available_at, observed_at, kind rank, event_id)`.
A late-arriving record keeps its original `observed_at`. The events cursor is `r{revision}.{index}` into that
order; within a revision the list only grows, so paging never skips or duplicates. A cursor from another revision
returns `409 stale_cursor` — the client restarts from the beginning.

## Forecast issuance

A forecast is issued at each newly available native glucose reading (the origin). `GET /forecast` returns the
latest with `availability`: `available`, `stale` (no new reading for > 15 min; the old forecast and its age are
returned unchanged) or `not_ready` (none yet or the twin abstained). `GET /forecasts` pages the immutable history
of the current revision.

## Deterministic reproduction

* Same clock ⇒ same released events ⇒ same features ⇒ same forecasts (verified by
  `test_forward_replay_equals_reset_and_seek`: stepping forward vs seeking directly vs reset-then-seek).
* Forecast IDs are `uuid5(session, revision, origin, model_version)`.

## Commands

```bash
make api        # API on 127.0.0.1:8000
curl -s -X POST localhost:8000/api/v1/replay/sessions -H 'Content-Type: application/json' \
     -d '{"patient_id":"SYN-B","mode":"synthetic_demo"}'
curl -s -X POST localhost:8000/api/v1/replay/sessions/<id>/control -H 'Content-Type: application/json' \
     -d '{"action":"step","steps":12}'
curl -s localhost:8000/api/v1/replay/sessions/<id>/forecast
```

## Synthetic fixtures

Fictional, deterministic, CC0 participants (no real data copied or perturbed): `SYN-A` normal operation, `SYN-B`
rising glucose with frequent highs, `SYN-C` meals logged 90 minutes late, `SYN-D` sensor gaps and sensor-limit
readings, `SYN-E` insufficient history; `SYN-T01…T12` hidden training participants for the synthetic
demonstration model (`synthetic-demo.lightgbm.dyn-v1.v1`, labelled synthetic in API and UI).
