# Anticipated jury questions

Numbers come from `artifacts/experiments/gt-primary-2026-10-11-v1/metrics.json` (see `reports/evaluation_report.md`).

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
before fitting; test evaluated once; adaptation uses a residual only after its target reading was available; the
online engine never receives unreleased events; tests check that future changes cannot alter earlier features and
that the served predictions equal the evaluated ones.

**How many independent participants and events?** 14 participants (Type 2 group, CGMacros). Test segment: 7,730
forecast origins (~644 hours) and 64 distinct new high-glucose onsets. Overlapping windows are not independent, so
uncertainty uses a participant-cluster bootstrap.

**How accurate is it?** Test MAE 13.32 mg/dL (30 min) and 21.20 mg/dL (60 min) vs persistence 14.84 / 23.23. Paired
difference −1.51 [−2.15, −0.95] and −2.02 [−3.40, −0.80]. Better than persistence for 14/14 participants at 30 min and
11/14 at 60 min.

**How many alerts are false?** On test, the 60-minute rule raised 79 warning episodes; 26 were false alarms
(1.49 per patient-day); it detected 53 of 64 onsets (recall 0.83, precision 0.67). Median lead time was only
10 minutes (IQR 5–20).

**Does adaptation help?** Modestly but consistently: −0.28 [−0.45, −0.11] mg/dL at 30 min and −0.53 [−0.92, −0.16] at
60 min (LightGBM), similar for CatBoost; 11/14 participants improved at each horizon. A frozen-state control showed no
gain, so the benefit comes from online updating. For unseen participants (leave-one-out) adaptation reduced error from
14.76 → 14.09 and 24.87 → 23.06 mg/dL.

**Why LightGBM and not CatBoost?** Both were searched equally; on validation they tied within the declared 0.5 mg/dL
margin and the rule prefers the simpler/faster family. On test they were statistically indistinguishable for dynamic
features (LightGBM − CatBoost: −0.03 [−0.19, 0.13] at 30 min, +0.35 [−0.08, 0.80] at 60 min).

**Why not use the profile features, which did better on test?** The selection rule was declared before seeing test
results and chose the smaller feature set within the tie margin. Switching now would be test-set selection. With 14
participants a profile vector also acts like an identifier, so its within-person gain may not generalise.

**What happens during gaps?** Readings are never interpolated. After 15 minutes without a reading, forecasts are marked
stale or the twin abstains; gaps longer than 7.5 minutes break episode continuity and censor event labels; gaps over
3 hours reset adaptation. The chart leaves gaps empty.

**Is uncertainty calibrated?** Split-conformal intervals at nominal 80 % covered 74.4 % (30 min) and 75.7 % (60 min)
on test, ranging 58–85 % across participants. We report this as under-coverage and claim no guarantee. The warning
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
