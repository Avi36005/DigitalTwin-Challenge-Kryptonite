# GlucoTwin — demonstration video plan (target 20:00)

**Team Kryptonite.** The submission form asks for a 15–20-minute demonstration uploaded to YouTube as **unlisted**.
This plan targets **exactly 20:00** including the opening and closing. It is a plan, not a recording: rehearse with a
timer, edit the finished video to 20:00, then record the rendered and YouTube-displayed durations in
`configs/submission.yaml` and the README. It supersedes the earlier 22-minute plan.

Every on-screen value in Chapter 4 was recorded from the running API by `scripts/demo_sequence.py`; see
[`reports/demo_sequence.md`](../reports/demo_sequence.md). If a value on screen differs (for example after re-running
the experiment), narrate what the screen shows — never the number written here.

## Chapter plan

| Video time | Segment | Duration | Shown | Narration (words) |
|---|---|---|---|---|
| 00:00–02:00 | Team, problem and healthcare use case | 2:00 | Slides 1–3 | 245 |
| 02:00–04:30 | Data, provenance and information availability | 2:30 | Slides 5–6 | 290 |
| 04:30–07:00 | Architecture, models and patient adaptation | 2:30 | Slides 4, 7–9 | 312 |
| 07:00–14:00 | Working dashboard and replay, including missing-data and abstention cases | 7:00 | Live app | 603 + screen actions |
| 14:00–18:00 | Measured comparison, baseline performance and limits of the evidence | 4:00 | Model evidence page, slides 12–15 | 490 + navigation |
| 18:00–20:00 | Project outcomes, limitations, reproducibility and next steps | 2:00 | Slides 17–20 (16 optional: research evidence) | 216 |

Narration words are counted from this file (2,156 in total). At about 130 words per minute that is roughly 16.6
minutes of speech; the remainder is slide transitions, clicks and waiting in Chapters 4 and 5. This is an estimate —
only a timed rehearsal and the rendered file establish the real duration. YouTube chapters: paste the six start times above into the video description.

## Recording setup (before 00:00)

* `make dev`; open http://127.0.0.1:5173 (landing page) in Chromium at **1920×1080** (or 1440×900), browser zoom 100 %, one tab.
  Chart labels and controls were checked for legibility at both sizes ([`reports/verification.md`](../reports/verification.md)).
* Preferences → default replay speed 10×, density *Comfortable*. Close other apps' notifications.
* Open `docs/submission/GlucoTwin_Presentation.pdf` in a second window for Chapters 1–3, 5 and 6.
* Recorded data needs `make data experiment`. Participant aliases (“Participant 01”) are stable across machines; the
  `pt-…` pseudonyms are not.

---

## Chapter 1 — Team, problem and healthcare use case (00:00–02:00) · slides 1–3

> *[Slide 1]* Hello, we are Team Kryptonite — Avinash Gehi and Hardik Hinduja — and this is GlucoTwin: personalized
> glucose forecasting between clinic visits, a student research prototype for the Happiest Health Digital Twin
> Challenge 2026.
>
> *[Slide 2]* For people with Type 2 diabetes, the main lab measure, HbA1c, summarises about three months of glucose.
> It cannot show the short high-glucose excursions that happen between appointments. Continuous glucose monitors can,
> but they produce close to three hundred readings a day — far too many for a clinician to review by hand. And the
> same meal or the same walk affects each person differently, so a population average is not enough. A digital twin
> keeps a separate, continuously updated state for each person, so that each forecast reflects that person's own
> recent history and recent forecast errors.
>
> Our target is concrete: using only the data available up to now, forecast glucose thirty and sixty minutes ahead,
> and warn of a *new* episode above 180 milligrams per decilitre lasting at least fifteen minutes. That threshold is a
> research definition, not a triage rule.
>
> *[Slide 3]* The user is a clinician reviewing a small monitored cohort, and the question we answer is: which
> patient's glucose pattern merits review, and what observations support that? The twin combines a static baseline
> profile — demographics and screening labs, like an EHR — with dynamic streams from the glucose sensor and a fitness
> tracker. We deliberately leave out medication advice, triage, live device claims and any LLM-generated prediction.

## Chapter 2 — Data, provenance and information availability (02:00–04:30) · slides 5–6

> *[Slide 5]* Our data is CGMacros version 1.0.0 from PhysioNet, licensed CC BY-NC-SA 4.0. Forty-five adults wore two
> glucose sensors and a Fitbit for about ten days, logged their meals, and had screening labs on day one. The dataset's
> own HbA1c rule places fourteen people in the Type 2 group; they are our primary cohort. The others can be replayed
> but are never used for training or evaluation. The download is checked against PhysioNet's published SHA-256
> checksums, and the dataset is not redistributed in our repository.
>
> One finding shaped everything. The published one-minute glucose columns are linearly interpolated between the real
> sensor readings. Training on them would count invented values as measurements. So our adapter recovers the native
> five-minute Dexcom readings — about 2,850 genuine readings per participant — and the app never treats a one-minute
> row as an observation. Columns without
> documentation are reported, not interpreted. Dates are shifted and the timezone is unknown, so we use a declared
> synthetic clock — “Day N” — and no time-of-day features. Baseline labs are treated as known from the start of the
> recording, and a missing lab stays missing; it is never filled with an average.
>
> *[Slide 6]* Every record carries two times: when it happened, and when the system could have known it. A forecast at
> time t only uses records where both are at or before t. Meal logging time is undocumented, so meals are excluded
> from the main model. Each participant's own timeline is split chronologically — sixty percent training, ten for
> choosing models, ten for calibrating intervals, and the final twenty percent as a test — with purge gaps so no label
> crosses a boundary. The protocol was frozen before any model was fitted, and the test period was evaluated once.

## Chapter 3 — Architecture, models and patient adaptation (04:30–07:00) · slides 4, 7–9

> *[Slide 4]* What makes it a twin? A versioned patient state, observations released over time, a forecasting model,
> and measured updates. The patient state issues a forecast; later, when the real reading for that time arrives, the
> error updates this person's own correction. Model weights are never refit during replay. It is a statistical
> research twin, not a simulator of human physiology.
>
> *[Slide 7]* Offline, a versioned adapter builds a canonical store, and a frozen experiment produces a checksummed
> model artifact and a metrics file. Online, a FastAPI replay session owns the clock and releases only what would have
> been available; the twin engine sees only those events. The same feature, adaptation and episode code runs offline
> and online, and our tests confirm the served predictions equal the evaluated ones. The browser talks to the API
> through one typed contract, generated from the same schema the backend validates.
>
> *[Slide 8]* We compared persistence, a linear trend and ridge regression with LightGBM and CatBoost. Both tree
> families received the same inputs, the same forecast times and the same twelve-trial search. Personalization is one
> policy for both: a small, shrunk and capped correction learned from this patient's forecast errors once their
> targets are known. Intervals are split-conformal, calibrated on held-out data. The warning score is the highest
> forecast in the next hour minus 180 — a score in milligrams per decilitre, not a probability.
>
> *[Slide 9]* The serving model was chosen on validation data only, by a rule we wrote down first: lowest average
> error over both horizons, with anything within half a milligram counted as a tie that goes to the simpler model.
> Four tree models tied, and the rule picked LightGBM with dynamic features. The models that also use the baseline
> profile scored slightly better — we will show they were better on test too — but switching after seeing test
> results would be test-informed selection, so we did not.

## Chapter 4 — Working dashboard and replay (07:00–14:00) · live app

**07:00 — Orientation.** *Screen:* the landing page, then **Open workspace** → Overview.
> This is the front door: a research prototype that replays recorded or synthetic data — never a live device. Inside
> the workspace, the left sidebar holds New replay, search, five destinations and our recent replays, and the top bar
> always says whether we are watching recorded data or the synthetic demonstration.

*Action:* **New replay** → *Recorded-data replay* → **Participant 01** → *Held-out test period* → **Start replay**.
The clock shows **Day 9 · 08:14**; current glucose **115** (08:10); 30-min forecast **119**, range **102–136**; 60-min
**132**, range **104–160**; patient adaptation **active**.

**07:45 — Reading the twin.**
> The participant's name heads the page, with the replay time. The line below shows baseline values as known at this
> moment — context only; this model forecasts from recent glucose and activity. Then the current reading and the
> thirty- and sixty-minute forecasts, each with a prediction range whose target coverage is eighty percent; Details
> shows that on the test period it actually covered about seventy-five percent. In the chart, the black line is
> observed glucose, the blue points with whiskers are the newest forecasts, and the faint circles are earlier forecasts
> that were saved and never changed. The replay controls sit under the chart, with the training, validation,
> calibration and test segments on the timeline.

*Action:* **Step 1 h** → **Day 9 · 09:14**: glucose **149**; forecasts **169** (152–186) and **163** (135–191).

**08:45 — A warning and an honest outcome.** *Action:* **Step 5 min** twice → **Day 9 · 09:24**.
> Glucose is rising. At 08:55 the twin issued a research warning: a forecast within the hour reached the threshold
> chosen on validation data. The review panel shows the forecast margin and its threshold — not a probability — and
> the Warnings list says *pending*, because at this replay time the outcome cannot be known yet. Mark as reviewed only
> records a local note; no one is messaged.

*Action:* **Mark as reviewed**; then **Step 1 h** twice → **Day 9 · 11:24**.
> Now the outcome is known: no sustained episode followed. That was a false alarm, and the app says so. This warning
> rule is sensitive: on the test period it caught every new episode, but raised about four and a half false alarms
> per eligible patient-day.

**09:45 — Rewind and a true warning.** *Action:* drag the timeline to **Day 9 · 20:00** (the “Seek to…” preview
appears), release; then step to **20:35**.
> Seeking created a new revision of the session: the twin was rebuilt from earlier data only, and older responses are
> discarded, so nothing from the future can leak in. At 20:25 the twin warned again; now glucose is 165 and the
> thirty-minute forecast is 190.

*Action:* step to **Day 9 · 21:10**.
> This time a sustained episode began at 20:45 — twenty minutes after the warning. The Warnings list reports that as
> the forecast lead: time from a warning whose own sixty-minute forecast contained the onset, never more than the
> horizon.

**10:45 — Evidence behind one forecast.** *Action:* click an **earlier forecast point** near 20:30, then **View
forecast details**.
> Selecting an earlier forecast marks when it was issued and compares it with readings observed later — only those
> already available at the replay clock. Each forecast is an immutable record: its information cutoff, model version,
> evaluation period, population forecast and patient correction, and factual explanations — associations, not causes.

**11:15 — A real sensor gap in recorded data.** *Action:* **New replay** → **Participant 12** → *Held-out test
period* → seek to **Day 9 · 10:25**.
> Participant 12's own record has a seventy-minute gap in its test period. At 10:25 glucose is 397 and the review
> status says glucose is already high — a current observation, kept separate from predictions.

*Action:* seek to **Day 9 · 10:50**, then **11:30**.
> The last reading was at 10:29. The current reading is marked stale with its age — twenty-one, then sixty-one minutes
> — so is the forecast, and the chart leaves the gap empty instead of drawing a line through it.

*Action:* seek to **Day 9 · 11:45**.
> Readings have resumed — 195 at 11:44 — but recent history is too sparse, so the twin abstains. The forecasts show a
> dash and one plain reason: two readings in the last hour; more recent history is required. Unavailable is never
> displayed as low risk, and forecasting resumes once enough readings arrive.

**12:30 — Short history: abstention.** *Action:* **New replay** → *Synthetic demonstration* → **SYN-E** → **Step
5 min**.
> Synthetic Participant E has under an hour of history. The twin abstains with the reason “not enough glucose
> history yet”, and patient adaptation is warming up.

**13:15 — Late information stays hidden.** *Action:* **New replay** → **SYN-C** → seek to **Day 1 · 09:30**, then
**10:00**; point at Observations.
> Here breakfast was eaten at 08:27 but logged ninety minutes later. At 09:30 the meal is invisible; at 10:00 it
> appears, with its eating time and its logging time. The twin can only use what was known at the time.

## Chapter 5 — Measured comparison and limits of the evidence (14:00–18:00) · Model evidence + slides 12–15

*Action:* sidebar → **Model evidence**.
> Everything on this page is read from the saved experiment artifact — and the first line says something important.
> An independent review of our code found two defects: activity features could count sixty-five minutes inside a
> sixty-minute window, and the replay screen could credit one episode to two warnings. We reproduced both, fixed them,
> and re-ran the same declared protocol. The original results are preserved; because that run had already looked at
> the test period, these corrected numbers are retrospective, not untouched test evidence.
>
> On the test period — fourteen participants, about 640 hours and 64 new high-glucose onsets — the serving model's mean
> absolute error was 13.2 milligrams per decilitre at thirty minutes and 20.8 at sixty, against 14.8 and 23.2 for
> carrying the last reading forward. That is an average error, not an accuracy percentage. The paired differences are
> minus 1.7 and minus 2.4, and the participant-level bootstrap intervals exclude zero.
>
> *[Slide 14]* Per participant, it beat persistence for all fourteen people at thirty minutes and twelve of fourteen at
> sixty. The gains are uneven, and fourteen people cannot establish population-level performance.
>
> *[Slide 13]* Does personalization help? A little: about a quarter of a milligram at thirty minutes and four tenths at
> sixty. A frozen-state control shows the gain comes from updating during the test period. For brand-new participants,
> left out of training entirely, error rises to 14.9 and 25.5, and adaptation brings it down to 14.1 and 23.1. LightGBM
> and CatBoost were statistically indistinguishable on dynamic features.
>
> *[Slide 15]* For early warning, the sixty-minute rule detected all 64 onsets, but with precision 0.45: 79 false
> alarms, four and a half per eligible patient-day — about as noisy as warning whenever glucose passes 150. Its forecast
> lead had a median of 55 minutes. The threshold came from our declared F1 rule, which turned out almost flat, so we
> report it as it is and propose a workload-aware rule next. Our prediction ranges covered about seventy-five percent
> on test against an eighty-percent target, so we do not claim calibrated uncertainty. And if meals were known the
> moment they were photographed, sixty-minute error would fall from 21.2 to 18.9 — optimistic, but a strong argument
> for timely meal logging.

*Action:* sidebar → **Data quality**.
> This page separates the current replay's data, the dataset's coverage and the limits of the model's inputs.

*Action:* back to **Model evidence**; scroll to Limitations.
> How far does this evidence go? Overlapping forecast windows from one person are not independent, so every interval
> here resamples whole participants. Each person contributes one test period of about two days. The study sensors were
> blinded and we replay them as if every reading arrived instantly, which flatters real-time performance. And the twin
> forecasts at 99.9 percent of test times — that is availability, not accuracy; when it abstains, those times are
> excluded, not counted as correct.
>
> One judgement call: profile-augmented models, which use the baseline labs, did better on test — CatBoost reached
> 12.9 and 19.8. Our pre-declared rule did not pick them, and we kept that rule.

## Chapter 6 — Outcomes, limitations, reproducibility and next steps (18:00–20:00) · slides 17–20

> *[Slide 17]* What did we deliver? A working digital twin and clinician workspace; a reproducible pipeline that found
> and corrected interpolated sensor data; and an evaluation we were willing to correct in public: better than
> persistence for every participant at thirty minutes, small gains from personalization, and a warning rule that catches
> every episode but raises too many false alarms.
>
> *[Slide 18]* The limits are real: fourteen people from one US site, no Indian participants, blinded research sensors
> replayed with assumed zero delay, unknown medication use, under-covering prediction ranges, and a corrected test
> result on a segment we had already seen. Nothing here is clinical validation.
>
> *[Slide 19]* Before use with Indian patients we would need a consented prospective cohort with real-time sensors,
> medications and meal-logging times; evaluation on held-out participants and sites; a warning policy with an alert
> budget agreed with clinicians; a usability study; and a regulatory and data-protection review.
>
> *[Slide 20]* Everything is reproducible: the README runs the synthetic demonstration in three commands, and the
> recorded-data results with three more. A fresh copy of the repository, without the dataset, passes the automated
> backend, frontend and browser tests, and every number in this video traces to a saved experiment file. The code is
> MIT-licensed; the dataset keeps its own license and is downloaded by each user from PhysioNet. Thank you for
> watching.

## Optional segment — larger-data evidence (prompt pack v4, ≈ 3 minutes)

Fits inside Chapter 5 or replaces part of it. Every number is read from the screen or from
`reports/model_upgrade_review.md`; nothing is typed in. The serving model does not change.

1. **Audited inventory** — *Data quality → Data sources and scale.* Read the summary sentence. Point out the columns:
   publisher-reported people are external metadata; imported, eligible and assessed are measured on this machine.
   AI-READI shows *Access required* with the steps only the team can complete; Glucose-ML is discovery only.
2. **A real recorded replay** — *New replay → Participant 01* (Scene A in `reports/demo_sequence.md`): a forecast is
   issued before its outcome; step forward until the 60-minute target matures and compare it with the forecast.
3. **One true and one false warning** — Scene A again: the Day 9 · 08:55 warning ends `no_onset_observed` (a false
   alarm); the Day 9 · 20:25 warning ends `onset_observed`. Scene B (Participant 12) shows a censoring sensor gap.
4. **Model comparison with participant and source counts** — *Model evidence → Evidence: “Nested participant benchmark
   + external cohort”.* The line under the header still names the serving model. Read: 14 CGMacros people, each
   assessed once in five outer folds; the declared rule's choice 13.88 / 22.30 mg/dL at 30 / 60 min versus the v2
   recipe refit per fold 14.52 / 24.25 and persistence 15.34 / 24.47. Open *Research warnings*: 301 of 329 onsets at
   1.31 false alarms per observed forecastable day, versus 329 of 329 at 2.80 for the v2 recipe.
5. **External cohort and what remains unproven** — switch to *15-minute · portable* and open *External cohort
   (ShanghaiT2DM)*: 98 people, CGM only, opened once; candidate 11.15 / 20.11 versus persistence 12.14 / 20.44 mg/dL.
   Say plainly: at 60 minutes the gain is not distinguishable from zero; other frozen pipelines scored lower there and
   were not adopted; ranges covered 86–87 % (wider than needed); CGMacros was already inspected, so its folds are internal
   validation; no Indian cohort; nothing was promoted.
