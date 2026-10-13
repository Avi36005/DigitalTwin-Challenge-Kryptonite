# Anticipated jury questions

Numbers come from `artifacts/experiments/gt-primary-2026-10-13-fusion/metrics.json` — the serving experiment: v2's
protocol with serving restricted to models that read the profile and the dynamic streams (see
`reports/evaluation_report.md`; v2 in `reports/archive/`, corrections in `reports/repair_report.md`).

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
before fitting; v1 evaluated test once (v2 re-runs the same protocol after code fixes, and the fusion experiment adds
one eligibility constraint, both on that same, already-inspected segment); adaptation uses a residual only after its target reading was available; the
online engine never receives unreleased events; tests check that future changes cannot alter earlier features and
that the served predictions equal the evaluated ones.

**How many independent participants and events?** 14 participants (Type 2 group, CGMacros). Test segment: 7,730
forecast origins (~644 hours) and 64 distinct new high-glucose onsets. Overlapping windows are not independent, so
uncertainty uses a participant-cluster bootstrap.

**How accurate is it?** Mean absolute error — an average error in mg/dL, not an accuracy percentage — was 12.96
(30 min) and 20.26 (60 min) on test, vs persistence 14.84 / 23.23. Paired difference −1.88 [−2.53, −1.32] and −2.96
[−4.34, −1.77]. Better than persistence for 14/14 participants at 30 min and 13/14 at 60 min. These are later days of
the same 14 people, not unseen patients.

**Why did the numbers change?** An independent review found that activity features counted up to 65 minutes in a
60-minute window and that the replay screen could credit one onset to two warnings. We reproduced both, fixed them,
and re-ran the same declared protocol as `gt-primary-2026-10-11-v2`. v1 (13.32 / 21.20) is preserved. Because v1
had already looked at the test segment, v2 is a corrected retrospective result, not untouched test evidence. On
13 October we then switched the demo model to the fusion-constrained experiment (next question).

**How many alerts are false?** On test, the 60-minute rule (margin −10 mg/dL) raised 101 warning episodes and 40 were
false alarms (1.49 per observed patient-day; 2.28 per eligible day). It detected 61 of 64 onsets (precision 0.60). Its
qualified forecast lead — from the earliest warning whose own 60-minute horizon contained the onset — had a median of
30 minutes. The previous demo model (margin −30) caught all 64 with 79 false alarms and a 55-minute lead. Both margins
come from the same declared F1 rule on a nearly flat curve, so the drop in false alarms is a threshold trade-off, not
evidence that the profile helps. A workload-aware threshold objective is the first item of `docs/next_experiment.md`.
We did not retune on test.

**Is a 60-minute forecast a 60-minute warning?** No. The horizon is how far a forecast looks ahead. We report the
qualified lead (never more than the horizon) separately from the time between the first warning of an episode and the
onset, which can be longer (median 30 minutes; 16 episodes started more than 60 minutes before their onset).

**Does adaptation help?** A little: −0.18 [−0.35, −0.01] mg/dL at 30 min and −0.33 [−0.68, +0.02] at 60 min (serving
LightGBM; inconclusive at 60 min); 8/14 and 9/14 participants improved. A frozen-state control showed no gain, so the
benefit comes from online updating. For unseen participants (leave-one-out, a secondary analysis that reuses globally
chosen hyperparameters) adaptation reduced error from 14.66 → 13.81 and 24.26 → 22.12 mg/dL.

**Why LightGBM and not CatBoost?** Both were searched equally; on validation they tied within the declared 0.5 mg/dL
margin (17.36 vs 17.44) and the rule prefers the simpler/faster family. On test, with the same inputs, they were
indistinguishable at 30 min (LightGBM − CatBoost +0.02 [−0.15, +0.20]) and CatBoost was slightly better at 60 min
(+0.46 [+0.05, +0.92]). We did not switch on that test result.

**Does the demo model really fuse static and dynamic data?** Yes. One LightGBM per horizon reads 8 baseline profile
values (age, sex, BMI, HbA1c, fasting glucose and insulin, triglycerides, HDL) together with 38 glucose and wearable
features; it abstains if a profile value is missing. The brief asks for exactly this, so we restricted serving to
models that read both streams and applied our unchanged validation rule to them.

**Isn't requiring the profile after seeing test results test-set selection?** It is a constraint added after the test
segment had been inspected, and we disclose it as such (protocol header, decisions D-038 and D-039, the evidence page).
We added it for compliance with the brief, not for accuracy. The rule itself — score, tie margin, tie-break — is
unchanged, and without the constraint it still picks the dynamic-only LightGBM, which stays registered for rollback.

**Does the profile improve forecasts?** Within the same 14 people, yes, slightly: −0.25 [−0.43, −0.04] mg/dL at 30 min
and −0.61 [−1.15, −0.09] at 60 min (LightGBM, population models). But a profile is constant per person, so with 14
people it can act as an identity code. On people held out entirely (nested experiment) the difference was +0.34
[−0.28, +0.89] at 30 min and −0.75 [−2.19, +0.61] at 60 min — no reliable benefit. We selected a model that implements
the required fusion; we have not established that profile features improve forecasting for unseen patients.

**What does the 99.9 % on the evidence page mean?** Forecast availability: the share of test origins with an observed
target at which the twin issued a forecast. It is not accuracy and not range coverage.

**What happens during gaps?** Readings are never interpolated. After 15 minutes without a reading, forecasts are marked
stale or the twin abstains; gaps longer than 7.5 minutes break episode continuity and censor event labels; gaps over
3 hours reset adaptation. The chart leaves gaps empty.

**Is uncertainty calibrated?** Split-conformal prediction ranges with a target coverage of 80 % covered 74.2 % (30 min)
and 74.0 % (60 min) on test, ranging 51–88 % across participants. We report this as under-coverage and claim no guarantee. The warning
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
