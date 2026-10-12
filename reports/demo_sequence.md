# Demonstration replay sequence (recorded by `scripts/demo_sequence.py`)

Generated from live API responses on this installation; regenerate with `uv run python scripts/demo_sequence.py`. Values are what the dashboard shows at each replay time. Nothing was edited to make the recording look better: false alarms, late warnings and abstentions are kept.

* Generated: 2026-10-11 16:14 UTC · serving model (recorded data): `lightgbm.dyn-v2.gt-primary-2026-10-11-v2` · synthetic model: `synthetic-demo.lightgbm.dyn-v2.v1`
* Participant aliases are stable (`Participant NN` follows the dataset's participant order); the `pt-…` pseudonyms are salted per installation and will differ on another machine.
* Forecast cells show predicted mg/dL with the 80 % interval in brackets when one is issued. “Risk (60)” is the uncalibrated warning score in mg/dL above 180, not a probability.

## Scene A — recorded data: a false alarm, then a true warning

Held-out test period of the serving model. Shows saved forecasts, a research warning whose outcome is unknown until later, a false alarm, a rewind (new revision) and a true warning.

Participant **Participant 01** (`pt-1eef47`) · mode `dataset_replay` · clock range Day 9 · 08:14 → Day 9 · 21:10

| Action | Replay clock | Latest reading | Latest forecast | 30-min | 60-min | Risk (60) | Personalization | Warnings issued in this scene | Meal records visible |
|---|---|---|---|---|---|---|---|---|---|
| start at Day 9 · 08:14 | Day 9 · 08:14 | 115 at 08:10 | available; quality ok | 119 [102–136] | 132 [104–160] | -48 (eligible) | active | none | 25; last released: eaten Day 8 · 20:28, logged Day 8 · 20:28 |
| step 1 h — orientation | Day 9 · 09:14 | 149 at 09:10 | available; quality ok | 169 [152–186] | 163 [135–191] | -11 (eligible) | active | Day 9 · 08:55: pending | 25; last released: eaten Day 8 · 20:28, logged Day 8 · 20:28 |
| step 10 min — warning issued? | Day 9 · 09:24 | 158 at 09:20 | available; quality ok | 183 [166–200] | 169 [141–197] | +3 (eligible) | active | Day 9 · 08:55: pending | 25; last released: eaten Day 8 · 20:28, logged Day 8 · 20:28 |
| step 2 h — outcome now known | Day 9 · 11:24 | 152 at 11:20 | available; quality ok | 165 [148–182] | 164 [136–192] | -15 (eligible) | active | Day 9 · 11:15: pending; Day 9 · 08:55: no_onset_observed | 26; last released: eaten Day 9 · 10:59, logged Day 9 · 10:59 |
| seek to Day 9 · 20:00 — rewind/seek creates a new revision | Day 9 · 20:00 | 92 at 20:00 | available; quality ok | 99 [82–116] | 101 [73–129] | -79 (eligible) | active | Day 9 · 11:15: no_onset_observed; Day 9 · 08:55: no_onset_observed | 28; last released: eaten Day 9 · 19:22, logged Day 9 · 19:22 |
| step 35 min | Day 9 · 20:35 | 165 at 20:35 | available; quality ok | 190 [173–207] | 180 [151–208] | +10 (eligible) | active | Day 9 · 20:25: pending; Day 9 · 11:15: no_onset_observed; Day 9 · 08:55: no_onset_observed | 28; last released: eaten Day 9 · 19:22, logged Day 9 · 19:22 |
| step 5 min | Day 9 · 20:40 | 176 at 20:40 | available; quality ok | 198 [182–215] | 187 [159–215] | +18 (eligible) | active | Day 9 · 20:25: pending; Day 9 · 11:15: no_onset_observed; Day 9 · 08:55: no_onset_observed | 28; last released: eaten Day 9 · 19:22, logged Day 9 · 19:22 |
| step 30 min — outcome of the second warning | Day 9 · 21:10 | 190 at 21:10 | available; quality ok | 184 [168–201] | 180 [152–208] | +4 (in_episode) | active | Day 9 · 20:25: onset_observed, onset 20:45, forecast lead 20 min, first warning 20 min before; Day 9 · 11:15: no_onset_observed; Day 9 · 08:55: no_onset_observed | 28; last released: eaten Day 9 · 19:22, logged Day 9 · 19:22 |

## Scene B — recorded data: a real 70-minute sensor gap

A genuine gap in the native Dexcom readings during this participant's held-out test period.

Participant **Participant 12** (`pt-d260d8`) · mode `dataset_replay` · clock range Day 9 · 07:58 → Day 9 · 11:45

| Action | Replay clock | Latest reading | Latest forecast | 30-min | 60-min | Risk (60) | Personalization | Warnings issued in this scene | Meal records visible |
|---|---|---|---|---|---|---|---|---|---|
| start at Day 9 · 07:58 | Day 9 · 07:58 | 148 at 07:54 | available; quality ok | 157 [140–174] | 164 [136–192] | -16 (eligible) | active | none | 21; last released: eaten Day 8 · 17:56, logged Day 8 · 17:56 |
| seek to Day 9 · 10:25 — before the gap | Day 9 · 10:25 | 397 at 10:24 | available; quality ok | 386 [369–403] | 310 [282–338] | +206 (in_episode) | active | none | 22; last released: eaten Day 9 · 08:16, logged Day 9 · 08:16 |
| seek to Day 9 · 10:50 — 21 min without a reading | Day 9 · 10:50 | 391 at 10:29 | stale, 21 min old; quality ok (stale_forecast) | 358 [341–375] | 292 [264–320] | +178 (in_episode) | active | none | 22; last released: eaten Day 9 · 08:16, logged Day 9 · 08:16 |
| seek to Day 9 · 11:30 — 61 min without a reading | Day 9 · 11:30 | 391 at 10:29 | stale, 61 min old; quality ok (stale_forecast) | 358 [341–375] | 292 [264–320] | +178 (in_episode) | active | none | 22; last released: eaten Day 9 · 08:16, logged Day 9 · 08:16 |
| seek to Day 9 · 11:45 — readings resume | Day 9 · 11:45 | 195 at 11:44 | not_ready; quality insufficient (sparse_recent_history) | not available | not available | — | active | none | 22; last released: eaten Day 9 · 08:16, logged Day 9 · 08:16 |

## Scene C — synthetic: abstention with a short history

Less than an hour of history: the twin abstains instead of guessing.

Participant **Synthetic Participant E** (`SYN-E`) · mode `synthetic_demo` · clock range Day 1 · 00:00 → Day 1 · 01:35

| Action | Replay clock | Latest reading | Latest forecast | 30-min | 60-min | Risk (60) | Personalization | Warnings issued in this scene | Meal records visible |
|---|---|---|---|---|---|---|---|---|---|
| start | Day 1 · 00:00 | none | not_ready (no_forecast_yet) | not available | not available | — | warming_up | none | none |
| step 5 min | Day 1 · 00:05 | 143 at 00:01 | not_ready; quality insufficient (insufficient_history, sparse_recent_history, activity_unavailable) | not available | not available | — | warming_up | none | none |
| step 30 min | Day 1 · 00:35 | 150 at 00:32 | not_ready; quality insufficient (insufficient_history) | not available | not available | — | warming_up | none | none |
| step 1 h | Day 1 · 01:35 | 138 at 00:57 | stale, 38 min old; quality insufficient (insufficient_history) | not available | not available | — | warming_up | none | none |

## Scene D — synthetic: a 2.5-hour sensor outage

The chart leaves the gap empty; reading and forecast are marked stale.

Participant **Synthetic Participant D** (`SYN-D`) · mode `synthetic_demo` · clock range Day 1 · 00:00 → Day 2 · 09:30

| Action | Replay clock | Latest reading | Latest forecast | 30-min | 60-min | Risk (60) | Personalization | Warnings issued in this scene | Meal records visible |
|---|---|---|---|---|---|---|---|---|---|
| start | Day 1 · 00:00 | none | not_ready (no_forecast_yet) | not available | not available | — | warming_up | none | none |
| seek to Day 2 · 06:00 — before the outage | Day 2 · 06:00 | 157 at 05:57 | available; quality ok | 157 [142–172] | 159 [135–182] | -21 (eligible) | active | Day 1 · 19:36: onset_observed, onset 19:52, forecast lead 15 min, first warning 15 min before; Day 1 · 12:46: onset_observed, onset 12:51, forecast lead 5 min, first warning 5 min before; Day 1 · 11:22: no_onset_observed | 3; last released: eaten Day 1 · 19:30, logged Day 1 · 19:30 |
| seek to Day 2 · 09:30 — inside the outage | Day 2 · 09:30 | 139 at 06:57 | stale, 153 min old; quality ok (stale_forecast) | 142 [127–157] | 156 [132–180] | -24 (eligible) | active | Day 1 · 19:36: onset_observed, onset 19:52, forecast lead 15 min, first warning 15 min before; Day 1 · 12:46: onset_observed, onset 12:51, forecast lead 5 min, first warning 5 min before; Day 1 · 11:22: no_onset_observed | 4; last released: eaten Day 2 · 07:52, logged Day 2 · 07:52 |

## Scene E — synthetic: a meal logged 90 minutes late

The meal record appears only once it was logged (its available_at), not when it was eaten.

Participant **Synthetic Participant C** (`SYN-C`) · mode `synthetic_demo` · clock range Day 1 · 00:00 → Day 1 · 10:00

| Action | Replay clock | Latest reading | Latest forecast | 30-min | 60-min | Risk (60) | Personalization | Warnings issued in this scene | Meal records visible |
|---|---|---|---|---|---|---|---|---|---|
| start | Day 1 · 00:00 | none | not_ready (no_forecast_yet) | not available | not available | — | warming_up | none | none |
| seek to Day 1 · 08:30 — breakfast eaten at about 08:27 | Day 1 · 08:30 | 150 at 08:26 | available; quality ok | 158 [142–173] | 170 [146–193] | -10 (eligible) | active | Day 1 · 07:36: pending | none |
| seek to Day 1 · 09:30 — eaten, not yet logged | Day 1 · 09:30 | 162 at 09:27 | available; quality ok | 165 [149–180] | 159 [136–183] | -15 (eligible) | active | Day 1 · 08:36: pending; Day 1 · 07:36: no_onset_observed | none |
| seek to Day 1 · 10:00 — logged at about 09:57 | Day 1 · 10:00 | 160 at 09:57 | available; quality ok | 160 [145–176] | 156 [132–179] | -20 (eligible) | active | Day 1 · 08:36: pending; Day 1 · 07:36: no_onset_observed | 1; last released: eaten Day 1 · 08:27, logged Day 1 · 09:57 |

