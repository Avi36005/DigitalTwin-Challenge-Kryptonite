# GlucoTwin — demonstration video plan (minimum 20 minutes, demo first)

**GlucoTwin — Team Kryptonite, VESIT (Mumbai).** The challenge page (rechecked 14 Oct 2026) requires a **minimum 20-minute video**
explaining and demonstrating the prototype, as a PowerPoint recording or an **unlisted** YouTube video; the form
transcription said 15–20 minutes, and the challenge page governs (D-040). This plan is **demo first**: two minutes of slides, then the app from
02:00, with about 12¼ minutes in the live app overall. Aim for about **20:30** so that neither the rendered file nor YouTube's
displayed duration falls below 20:00. It is a plan, not a recording: rehearse with a timer, check the finished video is
at least 20:00, then record the rendered and YouTube-displayed durations in `configs/submission.yaml` and the README.

Every on-screen value in the live chapters was recorded from the running API by `scripts/demo_sequence.py`; see
[`reports/demo_sequence.md`](../reports/demo_sequence.md) (Scene A = Participant 01, Scene B = Participant 12, Scenes C
and E = synthetic). The two-hour numbers come from [`reports/two_hour_benchmark.md`](../reports/two_hour_benchmark.md).
If a value on screen differs (for example after re-running an experiment), narrate what the screen shows — never the
number written here. The deck has 24 slides; slides not shown in the video stay in the PDF for the judges.

## Chapter plan

| Video time | Segment | Duration | Shown | Narration (words) |
|---|---|---|---|---|
| 00:00–02:00 | Opening, team, problem and use case | 2:00 | Slides 1–3 | 237 |
| 02:00–03:00 | Live demo: opening a recorded replay | 1:00 | Landing → Overview → workspace | 86 |
| 03:00–04:30 | The twin workspace and its guardrails | 1:30 | Workspace, *Review and guardrails* | 176 |
| 04:30–05:30 | Evidence behind one forecast | 1:00 | Forecast details drawer | 98 |
| 05:30–08:00 | Warnings with honest outcomes (Day 9), review note, review queue and review summary | 2:30 | Participant 01, Review queue | 231 |
| 08:00–08:45 | Cutaway: data and architecture | 0:45 | Slides 5, 7 | 97 |
| 08:45–10:45 | Guardrails in action: a real sensor gap | 2:00 | Participant 12 | 140 |
| 10:45–11:30 | Rewind: nothing from the future leaks in | 0:45 | Participant 12 | 49 |
| 11:30–12:30 | Synthetic edge cases | 1:00 | Synthetic Participants E and C | 85 |
| 12:30–13:30 | Model evidence and the safety guardrails | 1:00 | Model evidence | 153 |
| 13:30–15:00 | Cutaway: measured results (end of the main narrative) | 1:30 | Slides 14, 17 | 153 |
| 15:00–17:15 | Extension: research beyond the demo model | 2:15 | Slides 18, 19, 20 | 385 |
| 17:15–18:45 | Extension: the evidence inside the app | 1:30 | Model evidence (research view), Data quality | 105 |
| 18:45–20:30 | Limits, next steps and links | 1:45 | Slides 22–24 | 189 |

**Format (team decision, 20 Oct 2026):** slides only for the first two minutes, the app from **02:00**. The first fifteen
minutes are the main narrative — 10:45 of it in the live app (about 72 %), with two short slide cutaways — and chapters
12–14 extend it past the 20-minute minimum. Narration words are counted from this file (2,184 in total, recounted on
20 Oct 2026): 1,123 in the 12.25 live minutes and 1,061 in the slide minutes. At about
130 words per minute, rehearse with a timer; if a live chapter runs short, pause on the screen rather than speed up.
This is an estimate — only a timed rehearsal and the rendered file establish the real duration. YouTube chapters:
paste the fourteen start times above into the video description.

## Recording setup (before 00:00)

* `make dev`; open http://127.0.0.1:5173 (landing page) in Chromium at **1920×1080** (or 1440×900), browser zoom 100 %, one tab.
  Chart labels and controls were checked for legibility at both sizes ([`reports/verification.md`](../reports/verification.md)).
* Preferences → default replay speed 10×, density *Comfortable*. Close other apps' notifications.
* Open `docs/submission/GlucoTwin_Presentation.pdf` in a second window for the slide chapters.
* Recorded data needs `make data experiment`. Participant aliases (“Participant 01”) are stable across machines; the
  `pt-…` pseudonyms are not.
* The right-hand inspector of the workspace is labelled **Review and guardrails**; its *Guardrails* block is the one
  this video points at.

---

## Chapter 1 — Opening, team, problem and use case (00:00–02:00) · slides 1–3

> *[Slide 1]* A glucose reading tells us where someone is now. The harder question is what may happen next — and
> whether a doctor can trust the warning. Hello, we are Team Kryptonite from VESIT, Mumbai — Avinash Gehi and Hardik Hinduja — and this is
> GlucoTwin: personalized glucose forecasting between clinic visits, a student research prototype for the Happiest
> Health Digital Twin Challenge 2026.
>
> *[Slide 2]* For people with Type 2 diabetes, HbA1c summarises about three months of glucose. It cannot show the short
> high-glucose excursions between appointments. Continuous glucose monitors can, but they produce close to three
> hundred readings a day — far too many to review by hand. A digital twin keeps a separate, continuously updated state
> for each person. Our target: using only data available up to now, forecast glucose thirty and sixty minutes ahead,
> and warn of a *new* episode above 180 milligrams per decilitre lasting at least fifteen minutes — a research
> definition, not a triage rule.
>
> *[Slide 3]* A hypothetical example — an illustration, not a deployment: a diabetes educator in Mumbai follows adults
> with Type 2 diabetes who wear glucose sensors between quarterly visits, and opens one person's replay to see the
> forecasts, any warning and the data behind it. The twin combines a static baseline profile — demographics and
> screening labs, like an EHR — with the glucose sensor and a fitness tracker. It never gives medication advice.

## Chapter 2 — Live demo: opening a recorded replay (02:00–03:00)

*Screen:* the landing page, then **Open workspace** → Overview.
> This is the front door: a research prototype that replays recorded or synthetic data — never a live device. Inside
> the workspace, the left sidebar holds New replay, search and our recent replays; inside a replay, the top bar says
> whether we are watching recorded data or the synthetic demonstration.

*Action:* **Open recorded demo** on the Overview (the same as **New replay** → *Recorded-data replay* →
**Participant 01** → *Final test period* → **Start replay**).
> This is Participant 01 in the final test period — the later recordings of a person the model was trained on, so a
> test over time, not a new patient. The clock reads Day 9, 08:14.

## Chapter 3 — The twin workspace and its guardrails (03:00–04:30)

The clock shows **Day 9 · 08:14**; current glucose **115** (08:10); 30-min forecast **119**, range **103–136**; 60-min
**129**, range **103–155**; patient correction **active** (Scene A).
> The current reading is 115. The twin forecasts 119 in thirty minutes and 129 in sixty, each with a prediction range
> whose target coverage is eighty percent. In the chart, the black line is observed glucose, the blue points are the
> newest forecasts, and the faint circles are earlier forecasts, saved and never changed.

*Action:* point at the **Guardrails** block in the *Review and guardrails* inspector; read each row as the screen
shows it.
> On the right are the guardrails that applied to this forecast. *Data freshness*: the latest reading is fresh, with
> its age and the fifteen-minute limit. *Forecast inputs*: complete, with how many readings arrived in the last hour.
> *Health record*: every profile value this model reads was known at this time — if one were missing, it would
> abstain. *Patient correction*: learned only from forecasts whose outcome was observed, capped at twenty-five
> milligrams, reset after a three-hour gap. *Warnings*: what has been issued so far and how each ended. *Prediction
> range*: the eighty-percent target, and the coverage actually measured on the test period — about seventy-four
> percent, so no guarantee. *All safety guardrails* opens the full list; we will come back to it.

## Chapter 4 — Evidence behind one forecast (04:30–05:30)

*Action:* **Step 1 h** → **Day 9 · 09:14**: glucose **149**; forecasts **168** (151–184) and **161** (134–187). Click
**View forecast details** in the inspector.
> Every forecast is an immutable record. Here is its information cutoff, the model version and the evaluation period.
> And here is what makes it a twin: the population forecast, plus this patient's own correction learned from earlier
> errors, gives the final forecast — read the two numbers on screen. The explanations are factual associations, not
> causes. Nothing in this drawer can change after the fact. The population model is shared by everyone; the
> correction belongs to this person alone, and it only moves once a forecast's real outcome has arrived. Model weights
> are never refit during the replay.

## Chapter 5 — Warnings with honest outcomes (05:30–08:00)

*Action:* close the drawer; **Step 5 min** twice → **Day 9 · 09:24** (glucose **158**).
> Glucose is rising. At 09:15 the twin issued a research warning: a forecast reached the warning trigger of 170 — ten
> below the 180 threshold, a margin chosen on validation data. The Review panel names the forecast that fired and the
> trigger; scroll down, and the Warnings list marks 09:15 *Outcome pending*, because at this replay time the outcome
> cannot be known yet.

*Action:* **Step 1 h** twice → **Day 9 · 11:24**.
> Now it is known: no sustained episode followed. That was a false alarm, and the app says so.

*Action:* drag the timeline to about **Day 9 · 20:03**, release; point at the Warnings list (09:15 and 11:25, both
*No onset (false alarm)*).
> A second warning at 11:25 also ended without an episode — two false alarms today. We show them on purpose: across
> the test period this rule raised 1.49 false alarms per observed patient-day.

*Action:* **Step 5 min** seven times → **Day 9 · 20:38**; click **View forecast details** once and close it (this keeps
the 20:35 forecast selected for later).
> At 20:30 the twin warned again. Glucose is now 165 and the thirty-minute forecast is 189. Outcome pending.

*Action:* **Step 5 min** seven more times → **Day 9 · 21:13**; scroll to the **Warnings** list.
> Glucose is 190. A sustained episode began at 20:45 — fifteen minutes after the warning. The top three entries are today's:
> two false alarms and one matched onset, with its forecast lead. On the whole test period this rule caught 61 of 64
> new episodes.

*Action:* **Step 1 h** → **Day 9 · 22:13**, then click **View forecast details** (it opens the selected 20:35 forecast);
point at *Outcome*.
> Now we can check that forecast against what happened. Thirty minutes ahead it said 189, and the sensor read 189.
> Sixty minutes ahead it said 188 and the reading was 169 — nineteen too high — but the patient correction had moved
> it almost seven milligrams closer than the population model alone. One case says nothing about how often that happens.

*Action:* close the drawer; on the 20:30 warning click **Mark as reviewed**, type a short note (*"Seen; recheck after dinner"*), save. Click
**Review queue** in the sidebar, point at this replay's row, then **Open** to come back; click **Review summary** in the
header and show **Print / Save as PDF**. Do not seek again in this replay after reviewing: a seek starts a new revision
and the review count resets.
> A clinician records that they reviewed the warning, with a note. The review queue lists the replays with unreviewed
> warnings first — an order of work, not a risk ranking — and its counts stop at each replay's own clock. The review
> summary freezes what was known at this moment into a printable page.

## Chapter 6 — Cutaway: data and architecture (08:00–08:45) · slides 5, 7

> *[Slide 5]* The data is CGMacros 1.0.0 from PhysioNet: the fourteen people in its Type 2 group. Its one-minute glucose
> columns are interpolated, so we recover the native five-minute sensor readings, and every record carries the time it
> became available.
>
> *[Slide 7]* Two streams — the static profile and the glucose and wearable data — feed one model. A replay session owns
> the clock; the twin adapts to the patient, adds a range, a warning and guardrails, and the same code runs offline and
> online. We have not shown that the profile improves forecasts for new patients.

## Chapter 7 — Guardrails in action: a real sensor gap (08:45–10:45)

*Action:* **New replay** → **Participant 12** → *Final test period* → seek to **Day 9 · 10:27** (Scene B; this timeline stops at :x2/:x7 minutes).
> Participant 12's own record has a seventy-minute gap in its test period. At 10:27 glucose is 397 — already high; the
> review panel says so, and keeps that observation separate from predictions.

*Action:* seek to **Day 9 · 10:52**, then **11:32**; point at *Data freshness* and the forecast cards.
> The last reading was at 10:29. The guardrail turns: data freshness is *Stale*, twenty-three minutes and then over an hour
> old, over the fifteen-minute limit. No new forecast is made without a new reading; the last one stays visible, marked
> stale, and the chart leaves the gap empty instead of drawing a line through it. A warning open across such a gap
> would be marked *Outcome unknown (gap)*, never counted as a hit.

*Action:* seek to **Day 9 · 11:47**; point at *Forecast inputs*.
> Readings have resumed — 195 at 11:44 — but the last hour is too sparse, so the twin abstains: *Abstained, no forecast
> is shown*, with the plain reason. Unavailable is never displayed as low risk.

## Chapter 8 — Rewind: nothing from the future leaks in (10:45–11:30)

*Action:* seek **back** to **Day 9 · 10:27**.
> Seeking backwards creates a new revision of the session: the twin is rebuilt from earlier data only and later
> responses are discarded, so nothing from the future can leak in. Every forecast it shows is the one it would have made
> at 10:27. An automated test checks exactly this.

## Chapter 9 — Synthetic edge cases (11:30–12:30)

*Action:* **New replay** → *Synthetic demonstration* → **Synthetic Participant E** → **Step 5 min** (Scene C).
> Synthetic participants are fictional; they exercise edge cases like these without any download. Synthetic
> Participant E has under an hour of history. *Forecast inputs* says the twin abstained, with the reason —
> not enough glucose history yet — and the patient correction is warming up.

*Action:* **New replay** → *Synthetic demonstration* → **Synthetic Participant C** → seek to **Day 1 · 09:30**, then **10:00**; point at Observations (Scene E).
> Here breakfast was eaten at 08:27 but logged ninety minutes later. At 09:30 the meal is invisible; at 10:00 it
> appears, with its eating time and its logging time. The twin can only use what was known at the time.

## Chapter 10 — Model evidence and the safety guardrails (12:30–13:30)

*Action:* sidebar → **Model evidence**.
> Everything on this page is read from the saved experiment artifact. On the test period — later recordings of the same
> fourteen people, about 644 hours and 64 new onsets — the demo model's average error was 13.0 milligrams at thirty
> minutes and 20.3 at sixty, against 14.8 and 23.2 for carrying the last reading forward. These results are
> retrospective: two code fixes and the fusion constraint came after the test period had been seen. The notice at the
> top of the page lists what qualifies these numbers, and the earlier results are preserved.

*Action:* back in a replay, scroll the inspector down and click **All safety guardrails** (it scrolls to *Safety guardrails* on this
page); scroll through the list.
> This is the full list, each with the file that enforces or documents it: abstaining instead of guessing, flagging weak inputs, the
> health-record gate, no look-ahead, the bounded correction, rejecting implausible sensor values, warnings that show
> their outcome, ranges with measured coverage, no clinical claims, tests that cannot be quietly re-run, and the app
> reproducing every saved test forecast.

## Chapter 11 — Cutaway: measured results, end of the main narrative (13:30–15:00) · slides 14, 17

> *[Slide 14]* Forecast accuracy on later days of the same fourteen people: 13.0 and 20.3 milligrams per decilitre at
> thirty and sixty minutes, against 14.8 and 23.2 for persistence. That is an average error, not an accuracy
> percentage. It beat persistence for all fourteen people at thirty minutes and thirteen of fourteen at sixty. The
> gains are uneven, and fourteen people cannot establish population-level performance.
>
> *[Slide 17]* Early warning: the sixty-minute rule detected 61 of 64 onsets with 40 false alarms — 1.49 per observed
> patient-day — and a median forecast lead of thirty minutes. Warning whenever glucose passes 150 caught 63 but raised
> 2.61 false alarms per day. Compared with our earlier model, fewer false alarms came with three missed onsets and a
> shorter lead: a threshold trade-off, not a gain from the profile. Our prediction ranges covered about seventy-four
> percent against an eighty-percent target, so we do not claim calibrated uncertainty.

*End of the fifteen-minute main narrative.* The extension below keeps the video at or above the 20-minute minimum.

---

## Chapter 12 — Extension: research beyond the demo model (15:00–17:15) · slides 18, 19, 20

> *[Slide 18]* Those people were seen in training, so we also ran a protocol frozen before fitting, holding each person
> out entirely. The research procedure — Ridge on glucose only, not the demo model — scored 13.88 and 22.30 against
> 15.34 and 24.47 for persistence, and with warnings limited to two false alarms a day it caught 301 of 329 onsets at
> 1.31 per observed day. On ninety-eight people from an independent cohort, ShanghaiT2DM, opened once, a
> separate fifteen-minute model scored 11.15 against 12.14 at thirty minutes; at sixty minutes the difference is
> inconclusive.
>
> *[Slide 19]* The brief's example is a spike predicted two hours ahead, so on submission day we declared one more
> protocol before fitting anything — decision D-043 — with the same folds and a 120-minute horizon, each person held
> out. At two hours, error was 30.6 against 35.9 for persistence: 5.25 lower, interval minus 6.44 to minus 4.05, better
> for all fourteen people. The two-hour warning caught 315 of 329 onsets at 1.62 false alarms per observed day, against
> 313 at 1.48 for the sixty-minute warning. Its median forecast lead was fifteen minutes; a quarter of warnings came
> sixty-five minutes or more ahead. Ranges covered 76.5 percent. The health-record inputs gave no reliable benefit at
> two hours: minus 0.86, interval minus 2.60 to plus 1.02, and with Ridge they made error worse. These fourteen people
> were already inspected, so this is internal validation; it is not the demo model, and nothing was promoted.
>
> *[Slide 20]* Then we tried to fix three weaknesses, declaring each test before computing it — decision D-046. One
> worked: calibrating the ranges on all development people instead of two raised two-hour coverage from 76.5 to 79.8
> percent, against a target of 80. Two did not: no rule reliably warned more onsets at least thirty minutes ahead at the same
> alarm budget, and using the health record as a new person's starting correction gave minus 0.53 milligrams per
> decilitre, an interval that crosses zero. We report all three.
> Tonight we also tested blending the two tree models, again declared before scoring — decision D-048. On
> development people it improved sixty-minute error by only 0.02 milligrams per decilitre, far short of the half a
> milligram we required, so we kept the current model and never opened the held-out results. We then retrained the
> model itself four ways — decision D-049 — including twenty-four hours of past glucose history. The best gained 0.41
> milligrams per decilitre, again short of the bar we set in advance, so the model you saw is still the one we evaluated.

## Chapter 13 — Extension: the evidence inside the app (17:15–18:45)

*Action:* sidebar → **Model evidence** → evidence selector → the research experiment; scroll to *Research after the demo
model*.
> The same research is inside the app, read from the saved files: each experiment with who it was evaluated on, when it
> was opened, and a tag for each finding — shown, not shown, or a negative result. None of them is the demo model.

*Action:* sidebar → **Data quality**.
> This page separates the current replay's data, the dataset's coverage and the limits of the model's inputs. And when
> glucose is rising fast, the workspace says so: on its validation data this model's sixty-minute error was about 35
> milligrams per decilitre while glucose rose more than two per minute, against about 20 when steady, and it tended to
> under-forecast peaks.

## Chapter 14 — Limits, next steps and links (18:45–20:30) · slides 22–24

> *[Slide 22]* The limits are real: fourteen people from one US site, no Indian participants, blinded research sensors
> replayed with assumed zero delay, unknown medication use, under-covering prediction ranges, a profile that may act as
> an identity code, and demo-model results on a segment we had already seen. Nothing here is clinical validation. And
> scores depend on the dataset, prediction task and evaluation protocol; performance on simulated patients does not
> establish performance on real patients.
>
> *[Slide 23]* Before use with Indian patients we would need a consented prospective cohort with real-time sensors,
> medications and meal-logging times; evaluation on held-out participants and sites; a warning policy with an alert
> budget agreed with clinicians; a usability study; and a regulatory and data-protection review.
>
> *[Slide 24]* Everything is reproducible: the README runs the synthetic demonstration in three commands, and the
> recorded-data results with three more. Automated backend, frontend and browser tests pass, and every number in this
> video traces to a saved experiment file. The code is MIT-licensed; the dataset keeps its own license and is
> downloaded by each user from PhysioNet. We are Team Kryptonite from VESIT. Thank you for watching.
