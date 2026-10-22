# GlucoTwin — demonstration video script (minimum 20 minutes, app-led)

**GlucoTwin — Team Kryptonite, VESIT (Mumbai).** The challenge page (rechecked 14 Oct 2026) requires a **minimum
20-minute video** explaining and demonstrating the prototype, as a PowerPoint recording or an **unlisted** YouTube video
(D-040). Target **20:30**, so that neither the rendered file nor YouTube's displayed duration falls below 20:00. This is
a script, not a recording: nothing has been recorded or uploaded. Only a timed rehearsal with real clicks and the rendered
file establish the duration; record both durations in `configs/submission.yaml` and README §8 after upload.

**How to read this file.** Each scene gives the screen and route, the exact clicks, the replay times, the values the
screen is expected to show, the words to say (in quotation blocks — read only these aloud), a transition sentence and a
fallback. Everything else is a stage direction.

**Where the values come from.** Every on-screen value below was recorded from the running app: the patient-review
journey by the browser test [`apps/web/e2e/judge-journey.spec.ts`](../apps/web/e2e/judge-journey.spec.ts) (screenshots
in [`reports/ui/journey/`](../reports/ui/journey/)), the remaining scenes by `scripts/demo_sequence.py`
([`reports/demo_sequence.md`](../reports/demo_sequence.md)). Research numbers come from each experiment's saved summary
through the generated deck. If a value on screen differs, **narrate what the screen shows — never the number written
here.**

**Model-specific values (†).** Values marked **†** belong to the serving model,
`lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`. The final model decision of 22 Oct 2026 kept it (D-053 did not pass
its primary gate), so these recorded values stand. If a different model is ever activated, every † value must be
re-recorded from the app (re-run the judge journey and `scripts/demo_sequence.py`); never narrate one model's numbers
over another model's screen. Research numbers come only from locked, verified summaries.

**Deck.** [`docs/submission/GlucoTwin_Presentation.pdf`](submission/GlucoTwin_Presentation.pdf), 28 slides at this
writing; the video shows slides 1–4, 7, 14, 19–24 and 26–28. The rest stay in the PDF for the judges. If the deck is
regenerated, recheck the slide numbers in the table below.

## Main cut and extension

| Video time | Surface | Scene | Shown |
|---|---|---|---|
| 00:00–02:00 | **Slides** | 1 · Opening, problem, team, twin concept | Slides 1, 2, 3, 4 |
| 02:00–05:30 | **App** | 2 · A real patient's inputs, sources and quality · 3 · Forecast components and bounded personalisation | Participant 01, Day 9 · 20:38 |
| 05:30–06:15 | Slide | 4 · Architecture of what was just shown | Slide 7 |
| 06:15–10:00 | **App** | 5 · Pinned forecast and its outcome · 6 · Warnings with outcomes and a review · 7 · A real sensor gap: stale, abstain, recover | Participant 01 21:38; Participant 12 |
| 10:00–10:45 | Slide | 8 · Results, each with its model, cohort and comparator | Slide 14 |
| 10:45–14:15 | **App** | 9 · Model evidence · 10 · Replay consistency: rewind and parity · 11 · The newest research inside the app | Model evidence, Participant 12 |
| 14:15–15:00 | Slides | 12 · Closing: strengths, limits, next validation step | Slides 26, 27 |
| 15:00–20:30 | **App-led** | 13 · Synthetic edge cases · 14 · A false alarm and the review queue · 15 · Hard regime: rising glucose · 16 · Research cutaway · 17 · Reproduce it, close | Synthetic C/E, Participant 01, Review queue, slides 19–24, 28 |

App time in the first fifteen minutes: 3:30 + 3:45 + 3:30 = **10:45 of 15:00 (about 72 %)**. Scenes 13–17 extend the
video past the 20-minute minimum with app-led material. YouTube chapters: paste the scene start times above into the
description after the timed rehearsal confirms them.

**Timing is an estimate, not a measurement.** The spoken lines total about 2,230 words (counted from this file on
21 Oct 2026; the D-053 sentences added on 22 Oct add about 120): about 130 words a minute on the slides and slower in the app, where
clicks and pauses take the rest of each slot. No timed rehearsal has been recorded yet; it, and the rendered file, set
the real scene times.

## Recording setup (before 00:00)

* `make dev`; open http://127.0.0.1:5173 (landing page) in Chromium at **1920×1080** (or 1440×900), zoom 100 %, one tab.
* Preferences → default replay speed 10×, density *Comfortable*. Silence notifications.
* Second window: `docs/submission/GlucoTwin_Presentation.pdf`, presenter view off, slide 1 showing.
* Recorded data needs `make data experiment`. Aliases (“Participant 01”) are stable across machines; `pt-…` pseudonyms
  are not.
* Confirm the running model before recording: **Model evidence** (`/app/evidence`) names the serving model. It must read
  `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`; if not, stop and re-record the † values first.
* Start a timer. If a live scene runs short, stay on the screen and point rather than speed up; if long, drop the
  optional lines marked *(optional)*.

---

## Scene 1 — Opening, problem, team and the twin concept (00:00–02:00) · slides 1–4

**Screen:** presentation, slide 1. **Clicks:** advance at each *[Slide n]* mark.

> *[Slide 1]* “A glucose reading describes this moment. GlucoTwin helps a care team examine what may happen next, and
> then shows whether that forecast was right. We are Team Kryptonite from VESIT, Mumbai — Avinash Gehi and Hardik
> Hinduja — and this is our working patient digital twin, a student research prototype.”
>
> *[Slide 2]* “For an adult with Type 2 diabetes, HbA1c summarises about three months of glucose. It cannot show the
> short high-glucose excursions between appointments. A glucose sensor can — but it produces close to three hundred
> readings a day. Our target: using only data available up to now, forecast glucose thirty and sixty minutes ahead, and
> warn of a *new* episode above 180 lasting at least fifteen minutes — a research definition, not a triage rule.”
>
> *[Slide 3]* “Who is this for? A clinician or diabetes educator reviewing adults who already wear a CGM between visits.
> Picture an educator in Mumbai before a quarterly review — an illustration, not a deployment. She opens one person's
> replay and sees the forecasts, any warning, the data behind it, and later, whether the forecast was right. It never
> gives insulin or medication advice.”
>
> *[Slide 4]* “What makes it a twin: each person has a versioned state — a baseline profile of demographics and
> screening labs, and two streams, the glucose sensor and a fitness tracker, released by a replay clock only once they
> were available. A population model forecasts; a bounded correction learned from this person's own past errors adjusts
> it; every outcome updates that correction. A statistical twin, not a physiological simulator. Let me show you one.”

**Transition (on slide 4):** switch to the browser.
**Fallback:** if the slide window misbehaves, say the slide text from this script over the landing page.

## Scene 2 — A real patient's inputs, sources and quality (02:00–03:30) · App

**Screen / route:** landing page `/` → **Open workspace** → Overview `/app`.
**Clicks:** 1. **Open workspace**. 2. **Open recorded demo** (same as **New replay** → *Recorded-data replay* →
**Participant 01** → *Final test period* → **Start replay**). 3. Drag the timeline to **Day 9 · 20:38** and release.
4. Scroll to **How the twin reached this forecast**; point at *Inputs at issue time*
([screenshot](../reports/ui/journey/01-inputs-read-by-the-model.png)).
**Expected on screen:** top bar *Recorded-data replay*; Participant 01, final test period; latest reading 165 at
20:35, rising †; *Inputs at issue time*: “Health record: read by this model; 8 values known” (age, sex, BMI, HbA1c,
fasting glucose, fasting insulin, triglycerides, HDL); body weight, height, ethnicity and the cholesterol fractions
marked *context only*; wearable five-minute summaries *available and used*.

> “This is the front door of a research prototype. It replays recorded or synthetic data — never a live device — and
> the top bar always says which. I'll open the recorded demonstration: Participant 01 from CGMacros, a public,
> de-identified dataset. This is the final test period — later recordings of a person the model was trained on, so it is
> a test over time, not a new patient. I'll jump to the evening of Day 9, 20:38. Glucose is 165 and rising.
>
> First, what does the twin actually read? The health record: eight values, known at this moment — age, sex, BMI, HbA1c,
> fasting glucose and insulin, triglycerides and HDL. Body weight, height, ethnicity and the cholesterol fractions are
> displayed for context only; the model does not read them, and the screen says so. Wearable activity: the five-minute
> heart-rate and activity summaries from the last hour were available and used. And every record carries two times —
> when it was measured and when it became available — so nothing arrives early.”

**Transition:** “So what did the twin forecast from these inputs?”
**Fallback:** if **Open recorded demo** is missing, use **New replay** → *Recorded-data replay* → Participant 01 →
*Final test period*. If recorded data is not installed, say so and switch to Scene 13's synthetic participants.

## Scene 3 — Forecast components and bounded personalisation (03:30–05:30) · App

**Screen:** same replay, Day 9 · 20:38. **Clicks:** point at the forecast table, *Patient correction*, *Prediction range*,
*Accuracy at this trend*, then the *Guardrails* block in the right-hand **Review and guardrails** inspector
([screenshot](../reports/ui/journey/02-forecast-components.png)).
**Expected on screen †:** forecast issued 20:35; population 192 (30 min) and 195 (60 min); correction −3.0 and −6.7,
learned from 713 and 707 observed outcomes, bound ±25 mg/dL; final 189 and 188; range target 80 %, measured 74.2 % and
74.0 %; rising 3.3 mg/dL per minute; at this trend 60-minute error 35.3 vs 19.5 when steady, range held 46 %; a research
warning issued at 20:30, outcome pending.

> “The forecast was issued at 20:35. The population model — one LightGBM per horizon reading those eight profile values
> and thirty-eight glucose and wearable features together — said 192 at thirty minutes and 195 at sixty. Then this
> person's own correction: learned from 713 and 707 forecasts whose outcomes had already been observed, never from the
> future, and bounded at plus or minus twenty-five. It moved them by minus 3.0 and minus 6.7, to 189 and 188.
>
> Each forecast carries a range that targets eighty percent. We measured 74.2 and 74.0 percent on the test period, so
> the screen tells you it under-covers. And glucose is rising 3.3 per minute: at this trend, this model's sixty-minute
> error was 35.3 milligrams, against 19.5 when steady, and its range held the outcome only 46 percent of the time. We
> show that here, beside the forecast, because a fast rise is exactly when a reviewer needs to be careful.
>
> On the right, the guardrails that applied to this forecast: enough recent history, a fresh reading, complete inputs.
> And at 20:30 the twin issued a research warning. Its outcome is still pending — we cannot know it yet.”

**Transition:** “Before we follow that warning, here is the path we just walked through.”
**Fallback:** if the explanation panel is collapsed, click its header; if values differ, read the screen.

## Scene 4 — Architecture of what was just shown (05:30–06:15) · slide 7

> *[Slide 7]* “The profile and the two streams enter through an adapter that stamps when each record was observed and
> when it became available. A replay session owns the clock. The twin engine builds causal features, runs the fusion
> LightGBM, applies the bounded patient update, then the range, the warning and the guardrails. The dashboard shows it;
> a review goes to a local ledger. The offline build shares the same code. The dashed box is research: candidates reach
> the app only if every declared release gate passes.”

**Transition:** back to the browser: “Now let's see whether that forecast was right.”
**Fallback:** none needed; if the slide window fails, describe the diagram over the replay.

## Scene 5 — The pinned forecast and its outcome (06:15–07:15) · App

**Clicks:** 1. **View forecast details** (opens the 20:35 forecast: cutoff, model version, evaluation period). 2. **Esc**
— the forecast stays pinned. 3. **Step 1 h** → **Day 9 · 21:38**. 4. **View forecast details** → point at *Outcome*
([screenshot](../reports/ui/journey/03-forecast-outcome.png)).
**Expected on screen †:** 30 min: observed 189 at 21:05, error +0.0 (population +3.0, correction 3.0 closer); 60 min:
observed 169 at 21:35, error +19.1 (population +25.8, correction 6.7 closer).

> “Every forecast is an immutable record, with its information cutoff and model version. I pin it and move the replay
> on one hour. Now the outcome is known. Thirty minutes ahead it said 189, and the sensor read 189 at 21:05 — an error of
> zero, where the population model alone was three too high. Sixty minutes ahead it said 188; the reading at 21:35 was
> 169 — nineteen too high — but the population model alone was almost twenty-six too high, so the correction moved it 6.7
> closer. One case says nothing about how often that happens; the evidence page answers that.”

**Transition:** “And the warning from 20:30?”
**Fallback:** if the drawer opens on a newer forecast, select the 20:35 forecast from *Saved forecasts*.

## Scene 6 — Warnings with outcomes, a review and a frozen summary (07:15–08:45) · App

**Clicks:** 1. **Esc**; scroll to **Warnings** ([screenshot](../reports/ui/journey/04-warnings-hit-and-false-alarm.png)).
2. On the 20:30 warning: **Mark as reviewed** → type *“Seen; recheck after dinner.”* → **Save review**. 3. **Review
summary** in the header ([screenshot](../reports/ui/journey/05-frozen-review-summary.png)); point at **Print / Save as
PDF**. 4. **Esc** → **Step 5 min** (→ 21:43) → **Review summary** again. Do **not** seek in this replay after reviewing:
a seek starts a new revision.
**Expected on screen †:** 20:30 warning → onset 20:45, forecast lead 15 min; 09:15 and 11:25 *No onset (false alarm)*;
summary: session revision 2, model `lightgbm.dyn-prof-v2.gt-primary-2026-10-13-fusion`, cutoff Day 9 · 21:38 (replay
time), the note; after the step the copy is unchanged and says the replay has moved to 21:43.

> “The 20:30 warning now has its outcome: a sustained episode began at 20:45 — fifteen minutes of forecast lead. Earlier
> that day, warnings at 09:15 and 11:25 ended without an episode. They are false alarms, and the list says so. We show
> them on purpose: across the test period this rule caught 61 of 64 new episodes, at 1.49 false alarms per observed
> patient-day.
>
> The educator records that she reviewed the warning, with a note. The review summary freezes what was known: the
> participant, the session and its revision, the model version, the replay cutoff at 21:38 — kept apart from the
> wall-clock time of the review — and the note. When the replay moves on to 21:43, this copy does not change; it only
> says the replay has moved since.”

**Transition:** “Real data also has holes. Here is a real one.”
**Fallback:** if **Save review** is disabled, check that the note field has text; if the summary fails to open, show the
reviewed badge on the warning instead.

## Scene 7 — A real sensor gap: stale, abstain, recover (08:45–10:00) · App

**Clicks:** 1. **New replay** → **Participant 12** → *Final test period* → seek **Day 9 · 10:27**. 2. Seek **10:52**, then
**11:32**; point at *Data freshness* and the forecast cards. 3. Seek **11:47** ([screenshot](../reports/ui/journey/06-gap-abstention.png)).
4. **Step 5 min** four times → **12:07** ([screenshot](../reports/ui/journey/06b-gap-recovery.png)). This timeline stops
at :x2/:x7 minutes.
**Expected on screen:** 10:27 glucose 397, already high; last reading 391 at 10:29; *Stale* at 10:52 and 11:32; at 11:47
195 at 11:44, both forecasts *Not available*, “Unavailable is not the same as low risk”; at 12:07 a forecast again — 79
mg/dL at 60 min, range 53–105 †, labelled *Degraded data*.

> “Participant 12's own record has a seventy-minute gap. At 10:27 glucose is 397 — already high, and the review panel
> keeps that observation separate from any prediction. The last reading, 391, came at 10:29. Now data freshness turns
> *Stale*: twenty-three minutes, then over an hour old. No new forecast is made without a new reading; the last one stays
> visible, marked stale, and the chart leaves the gap empty instead of drawing a line through it.
>
> Readings resume — 195 at 11:44 — but the last hour is too sparse, so the twin abstains. Both forecasts read *Not
> available*, with the reason, and the screen says that unavailable is not the same as low risk. A few readings later it
> forecasts again, labelled *Degraded data* with its reason. Recovery is shown as it is, not as a clean success.”

**Transition (to slide 14):** “So how good is it — and on whom was each number measured?”
**Fallback:** if seeking lands a minute off, step 5 minutes until the stated time; narrate the screen.

## Scene 8 — Results, each with its model, cohort and comparator (10:00–10:45) · slide 14

> *[Slide 14]* “Three kinds of evidence, never blended. The serving model, on later recordings of the same fourteen
> people: average error 12.96 and 20.26 milligrams at thirty and sixty minutes, against 14.84 and 23.23 for carrying
> the last reading forward †. With each person held out entirely, a CGM-only procedure: 13.88 and 22.30, against 15.34
> and 24.47. Our newest study came close — 22.00 against 23.20 for the refitted recipe — but missed its peak limit. On ninety-eight independent people
> from Shanghai, a separate CGM-only model: 10.90 and 19.31, against 12.14 and 20.44. Different models, different
> tests.”

**Transition:** back to the browser: “All of this is inside the app, read from the saved files.”

## Scene 9 — Model evidence (10:45–12:00) · App

**Route:** sidebar → **Model evidence** (`/app/evidence`).
**Clicks:** scroll the summary, the fusion disclosures ([screenshot](../reports/ui/18-model-evidence-fusion-disclosures.png)),
then **All safety guardrails** from a replay's inspector (it scrolls to *Safety guardrails*).
**Expected on screen †:** serving model named; test period ≈ 644 hours, 64 new onsets; MAE 13.0 / 20.3 vs 14.8 / 23.2;
the disclosures notice; the guardrail list with the file that enforces each.

> “This page names the serving model and reads every number from the saved experiment. On later recordings of the same
> fourteen people — about 644 hours and 64 new onsets — the average error was 13.0 and 20.3, against 14.8 and 23.2 for
> persistence. The notice at the top says what qualifies these numbers: two code fixes and the fusion constraint came
> after that test period had been seen, so they are retrospective. The model reads the health record because the brief
> asks for fusion; we have not shown that the profile improves forecasts for new patients, and the page says that too.
>
> Here is the full list of guardrails, each with the code that enforces it: abstaining instead of guessing, flagging
> weak inputs, the health-record gate, no look-ahead, the bounded correction, rejecting implausible sensor values,
> warnings that always show their outcome, ranges with measured coverage, no clinical claims, and locked evaluations
> that cannot be quietly re-run.”

**Transition:** “Two of those guardrails are easy to say and hard to prove. Let me prove them.”
**Fallback:** if a section is collapsed, expand it; numbers on screen govern.

## Scene 10 — Replay consistency: rewind and parity (12:00–13:00) · App

**Clicks:** open the Participant 12 replay from the sidebar's recent replays; seek **back** to **Day 9 · 10:27**.
**Expected on screen:** a new session revision; the 10:27 state (397) exactly as before; no later forecasts.

> “I seek backwards. That creates a new revision of the session: the twin is rebuilt from earlier data only and every
> later response is discarded, so nothing from the future can leak in. Every forecast shown now is the one the twin
> would have made at 10:27 — an automated test checks exactly this.
>
> And the app is the evaluation. We replayed every test participant through this same service and compared it with the
> saved experiment: all 15,440 test forecasts matched within 0.05 milligrams per decilitre. What you see in the app is
> what we measured.”

**Transition:** “Finally, the newest research — and what we did with it.”
**Fallback:** if the recent-replay link is gone, start Participant 12 again and seek to 10:27.

## Scene 11 — The newest research inside the app (13:00–14:15) · App

**Route:** **Model evidence** → research view (*Research after the demo model*,
[screenshot](../reports/ui/21-research-after-demo-model.png)).
**Clicks:** scroll the research list; point at each experiment's tag (*Shown*, *Not shown*, *Negative result*).
**Expected on screen:** each experiment with who it was evaluated on, when it was opened, and a tag per finding.
The two newest studies (D-053, D-054) are not in this in-app list; they are on slides 22–23 and in the README, so the
last sentences below are said over this screen, then shown on slide 22 in Scene 16.

> “Every attempt to improve the model is listed here, read from its saved files, with who it was evaluated on and a tag
> for each finding: shown, not shown, or a negative result. We declared each study before its own run. Later studies
> reused previously inspected participants, so those results are internal validation. Our joint-selection study lowered
> the average sixty-minute error but made peaks above 180 worse and raised false alarms, so it failed our own gates. The
> zero-shot foundation model beat persistence on every one of the fourteen people, but not our refitted recipe. And our
> last study, declared before its run, chose model settings and the patient correction with a guard on high readings. It
> lowered sixty-minute error by 1.19 milligrams against the refitted recipe, for eleven of fourteen people, and passed
> the warning and range checks — but error above 180 rose by 1.07, past our limit of 1.0. One gate failed, so we did
> not adopt it. The model you have been watching is unchanged.”

**Transition (to slide 26):** “So where does that leave us?”
**Fallback:** if the research view is unavailable on this installation, it says “Not run on this installation”; switch
to slide 21 and read the same findings.

## Scene 12 — Closing: strengths, limits and the next validation step (14:15–15:00) · slides 26, 27

> *[Slide 26]* “What works end to end: a replayed twin that forecasts, warns, shows whether each forecast was right,
> records a review, and abstains when data is missing. The limits are real: fourteen people from one US site, no Indian
> participants, blinded sensors, unknown medication, under-covering ranges, more than one false alarm per observed day.
> Nothing here is clinical validation.
>
> *[Slide 27]* Next: a consented Indian cohort with real-time sensors, medications and meal times; evaluation on new
> people and sites; a warning budget agreed with clinicians; and a usability and data-protection review.”

**Transition:** “In the remaining minutes, a few more cases from the app.”

---

## Scene 13 — Extension: synthetic edge cases (15:00–16:15) · App

**Clicks:** 1. **New replay** → *Synthetic demonstration* → **Synthetic Participant E** → **Step 5 min**. 2. **New replay**
→ *Synthetic demonstration* → **Synthetic Participant C** → seek **Day 1 · 09:30**, then **10:00**; point at
*Observations*.
**Expected on screen:** E: forecasts not available, reason *not enough glucose history yet*, patient correction *warming
up*. C: at 09:30 no breakfast record; at 10:00 breakfast eaten 08:27, logged about ninety minutes later.

> “Synthetic participants are fictional; they run without any download and exercise the edge cases on purpose. Synthetic
> Participant E has under an hour of history, so the twin abstains and says why, and the patient correction is still
> warming up. Synthetic Participant C ate breakfast at 08:27 but logged it ninety minutes later. At 09:30 the meal is
> invisible to the twin; at 10:00 it appears, with both times. The twin can only use what was known at the time — and
> that is why our main model does not use meals at all: in the real dataset the logging time is undocumented.”

**Fallback:** if the synthetic model is missing, run `make synthetic` before recording; skip to Scene 14.

## Scene 14 — Extension: a false alarm and the review queue (16:15–17:15) · App

**Clicks:** 1. **New replay** → **Participant 01** → *Final test period* → seek **Day 9 · 09:24**. 2. **Step 1 h** twice →
**11:24**. 3. Sidebar → **Review queue** (`/app/review-queue`, [screenshot](../reports/ui/20-review-queue.png)); point
at the rows; **Open** one.
**Expected on screen †:** at 09:24 glucose 158, 30-minute forecast 180 [163–197], warning 09:15 *pending*; at 11:24 the
09:15 warning reads *No onset (false alarm)*. Queue: replays with unreviewed warnings first.

> “Here is what a false alarm looks like as it happens. At 09:24 glucose is 158 and the thirty-minute forecast is 180, so
> a warning is issued and stays pending. Two hours later the outcome is known: no sustained episode. The warning is
> marked a false alarm — not deleted, not hidden.
>
> The review queue lists every replay with unreviewed warnings first. It is an order of work, not a risk ranking, and
> its counts stop at each replay's own clock, so nothing after that moment leaks into the list.”

**Fallback:** if the queue is empty on a fresh install, say so and show the screenshot linked above.

## Scene 15 — Extension: the hard regime, rising glucose (17:15–18:15) · App

**Clicks:** reopen Participant 01 at **Day 9 · 20:38**; point at *Accuracy at this trend*; then sidebar → **Data quality**
(`/app/data-quality`).
**Expected on screen †:** rising 3.3 mg/dL per minute; 60-minute error 35.3 vs 19.5 steady; range held 46 %. Data
quality: sources, model-input limits, coverage.

> “Rapid rises are where every glucose forecaster struggles, and ours is no exception. On its validation data this
> model's sixty-minute error was about 35 milligrams while glucose rose more than two per minute, against about 20 when
> steady, and it tends to under-forecast peaks. We put that number next to the forecast instead of hiding it in a report.
> The data-quality page then separates three things a reviewer should not confuse: this replay's data, the dataset's
> coverage, and the limits of what the model can read.”

**Fallback:** if the trend block is absent for this forecast, step 5 minutes to a rising reading.

## Scene 16 — Extension: research cutaway (18:15–19:15) · slides 19–24

> *[Slide 19]* “Because the serving model was tested on people it had seen, we also held each person out entirely.”
>
> *[Slide 20]* “Two hours ahead, error was 30.6 against 35.9 for persistence, better for all fourteen people — but the
> median warning lead was fifteen minutes: a two-hour forecast, not two hours of notice.”
>
> *[Slide 21]* “Pooled calibration brought research ranges close to eighty percent. Blending, retraining, tuning and
> joint selection each failed our declared bars.”
>
> *[Slide 22]* “The peak-aware study was a near miss: better on average, warnings and ranges within limits, but 1.07
> worse above 180 against a limit of 1.0 — so it stays research.”
>
> *[Slide 23]* “A zero-shot foundation model, on glucose alone, beat persistence for all fourteen people at sixty
> minutes — 22.92 against 24.47 — but not our refitted recipe at 22.50.”
>
> *[Slide 24]* “And on ninety-eight independent people from Shanghai, a separate CGM-only model beat persistence at
> thirty minutes and at two hours. That cohort has now been opened twice, for different horizons, and nothing was chosen
> on it.”

**Fallback:** if short of time, read only slides 20, 23 and 24.

## Scene 17 — Extension: reproduce it, and close (19:15–20:30) · README, slide 28

**Clicks:** browser tab with the repository README → *Run it locally* and *Verification*; then slide 28.

> “Everything you saw is reproducible. The synthetic demonstration runs from three commands with no download; the
> recorded-data results need the public CGMacros download and three more. Backend, frontend and browser tests run from
> one command each, and every number in this video traces to a saved experiment file. The code is MIT-licensed; each
> dataset keeps its own licence and is downloaded by each user.
>
> *[Slide 28]* We are Team Kryptonite from VESIT. GlucoTwin does not tell anyone what to do. It shows what may happen
> next, records who looked, and then shows whether it was right. Forecast. Review. Verify. Thank you for watching.”

Hold slide 28 for five seconds of silence before stopping the recording, so trimming cannot drop the video below 20:00.

---

## Three-minute judge walkthrough (local install, recorded data)

For a judge with three minutes and the app running (`make data experiment`, then `make dev`). Without the download, the
synthetic demonstration shows the same screens on fictional participants. † = values of the serving model (see above).

| Time | Route and click | Look for |
|---|---|---|
| 0:00 | `/` → **Open workspace** → **Open recorded demo**; drag to **Day 9 · 20:38** | *Recorded-data replay*; Participant 01, final test period — later recordings of a known person, not a new patient |
| 0:20 | *How the twin reached this forecast* → inputs | 8 health-record values read by the model; context-only fields labelled; wearable summaries used |
| 0:40 | Same panel → forecast table | Population vs bounded correction (±25 mg/dL) vs final †; range target 80 %, measured 74.2 % / 74.0 % †; accuracy at the current trend † |
| 1:05 | **View forecast details** → **Esc** → **Step 1 h** → **View forecast details** → *Outcome* | The pinned forecast against the reading that followed † |
| 1:30 | **Warnings** | A hit with its forecast lead and two false alarms, all labelled † |
| 1:50 | **Mark as reviewed** + note → **Review summary** | Revision, model version, replay cutoff, note — frozen |
| 2:15 | **New replay** → Participant 12 → seek **10:52**, **11:47** | *Stale* across a real gap; abstention with the reason, “Unavailable is not the same as low risk” |
| 2:40 | `/app/evidence` | The serving model named; results with their cohort; the fusion disclosures |

The same steps run as an automated browser test, [`apps/web/e2e/judge-journey.spec.ts`](../apps/web/e2e/judge-journey.spec.ts).

## Recording checklist

1. Running model confirmed on `/app/evidence` and equal to the model these values were recorded against (else re-record †).
2. Browser 1920×1080, zoom 100 %, one tab, notifications off; deck PDF open in a second window at slide 1.
3. Fresh replays: no earlier reviews on Participant 01 (a reviewed warning changes Scene 6).
4. Timer running; scene start times noted live for the YouTube chapters.
5. After export: rendered duration **≥ 20:00** (target 20:30); after an *unlisted* upload (needs authorisation): the
   displayed duration ≥ 20:00. Record both in `configs/submission.yaml` and README §8.
6. Watch the export once end to end: no personal data, notifications or unrelated windows on screen.
