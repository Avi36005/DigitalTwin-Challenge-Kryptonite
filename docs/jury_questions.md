# Anticipated jury questions

Numbers come from `artifacts/experiments/gt-primary-2026-10-11-v2/metrics.json` — the corrected re-run of the frozen
v1 protocol (see `reports/evaluation_report.md` and `reports/repair_report.md`).

**What makes this a twin?** A versioned patient state (baseline profile, episode state, adaptation state, issued
forecasts) that is updated as observations arrive and used to forecast; its correction is learned from that
person's own matured forecast errors. It is a statistical research twin — not a physiological simulator, and we do
not call it one.

**What is available at prediction time?** Only records with `observed_at ≤ t` and `available_at ≤ t`: native CGM
readings up to t, 5-minute wearable summaries that ended by t, and baseline labs (assumed available at
initialisation). Meals are excluded because their logging time is unknown. Calendar/time-of-day features are not used.

**Why 30 and 60 minutes?** They are long enough to act on a review list and short enough for CGM history to be
informative; they are the prompt pack's declared horizons. The challenge's "two hours" is an example, and our data
would make two-hour claims weaker; we did not evaluate it.

**How do you avoid future leakage?** Two timestamps per record; trailing features only; chronological within-person
splits with 82.5-minute purges; scalers/models/thresholds/calibration fit only on earlier segments; protocol frozen
before fitting; v1 evaluated test once (v2 re-runs the same protocol after code fixes, on that same, already-inspected
segment); adaptation uses a residual only after its target reading was available; the
online engine never receives unreleased events; tests check that future changes cannot alter earlier features and
that the served predictions equal the evaluated ones.

**How many independent participants and events?** 14 participants (Type 2 group, CGMacros). Test segment: 7,730
forecast origins (~644 hours) and 64 distinct new high-glucose onsets. Overlapping windows are not independent, so
uncertainty uses a participant-cluster bootstrap.

**How accurate is it?** Mean absolute error — an average error in mg/dL, not an accuracy percentage — was 13.15
(30 min) and 20.81 (60 min) on test, vs persistence 14.84 / 23.23. Paired difference −1.69 [−2.34, −1.11] and −2.42
[−3.81, −1.11]. Better than persistence for 14/14 participants at 30 min and 12/14 at 60 min.

**Why did the numbers change?** An independent review found that activity features counted up to 65 minutes in a
60-minute window and that the replay screen could credit one onset to two warnings. We reproduced both, fixed them,
and re-ran the same declared protocol as `gt-primary-2026-10-11-v2`. v1 (13.32 / 21.20) is preserved. Because v1
had already looked at the test segment, v2 is a corrected retrospective result, not untouched test evidence.

**How many alerts are false?** On test, the 60-minute rule raised 143 warning episodes and 79 were false alarms (4.51
per eligible patient-day, 2.95 per observed day). It detected all 64 onsets (precision 0.45). Its qualified forecast lead
— from the earliest warning whose own 60-minute horizon contained the onset — had a median of 55 minutes. The declared
F1 rule chose the lowest threshold of a nearly flat curve, so the rule is sensitive but noisy. A workload-aware
threshold objective is the first item of `docs/next_experiment.md`. We did not retune on test.

**Is a 60-minute forecast a 60-minute warning?** No. The horizon is how far a forecast looks ahead. We report the
qualified lead (never more than the horizon) separately from the time between the first warning of an episode and the
onset, which can be longer (median 67.5 minutes; 33 episodes started more than 60 minutes before their onset).

**Does adaptation help?** A little: −0.24 [−0.43, −0.07] mg/dL at 30 min and −0.39 [−0.79, −0.02] at 60 min (LightGBM);
9/14 participants improved at each horizon. A frozen-state control showed no gain, so the benefit comes from online
updating. For unseen participants (leave-one-out, a secondary analysis that reuses globally chosen hyperparameters)
adaptation reduced error from 14.92 → 14.07 and 25.47 → 23.12 mg/dL.

**Why LightGBM and not CatBoost?** Both were searched equally; on validation they tied within the declared 0.5 mg/dL
margin and the rule prefers the simpler/faster family. On test they were statistically indistinguishable for dynamic
features (LightGBM − CatBoost: −0.13 [−0.34, 0.07] at 30 min, +0.18 [−0.29, 0.66] at 60 min).

**Why not use the profile features, which did better on test?** The selection rule was declared before seeing test
results and chose the smaller feature set within the tie margin. Switching now would be test-set selection. With 14
participants a profile vector also acts like an identifier, so its within-person gain may not generalise.

**What does the 99.9 % on the evidence page mean?** Forecast availability: the share of test origins with an observed
target at which the twin issued a forecast. It is not accuracy and not range coverage.

**What happens during gaps?** Readings are never interpolated. After 15 minutes without a reading, forecasts are marked
stale or the twin abstains; gaps longer than 7.5 minutes break episode continuity and censor event labels; gaps over
3 hours reset adaptation. The chart leaves gaps empty.

**Is uncertainty calibrated?** Split-conformal prediction ranges with a target coverage of 80 % covered 74.4 % (30 min)
and 75.9 % (60 min) on test, ranging 60–86 % across participants. We report this as under-coverage and claim no guarantee. The warning
score is uncalibrated and never shown as a probability.

**What distinguishes this from existing metabolic monitoring products?** We do not claim novelty of glucose twins or
predictive alerts (commercial programs and CGM alerts exist). Our contribution is a transparent, reproducible
evaluation: native-reading recovery, availability-aware features, frozen protocol, measured personalization effect,
false-alarm and lead-time reporting, and a clinician view that shows what was known when.

**What evidence is needed before use with Indian patients?** A consented Indian cohort with real-time CGMs, recorded
latency, medication and meal-logging times; held-out participant and site evaluation; calibrated event models with an
agreed alert burden; usability and safety studies; regulatory and DPDP Act review.

**Did you use an LLM to generate predictions or explanations?** No. Forecasts are numerical models; explanations are
templated from actual inputs and tree contributions, labelled as associations, not causes.

**Can it run offline?** Yes, after setup: the synthetic mode needs no download; the recorded mode needs the dataset to
be downloaded once. The app binds to localhost and makes no external calls at runtime.
