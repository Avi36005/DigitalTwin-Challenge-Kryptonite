# CGMacros data audit

Generated 2026-10-11 by `glucotwin data audit` from `data/processed/cgmacros/v1/audit.json`
(adapter `cgmacros-adapter-1.0`). Patient-level processed data stays local (git-ignored); this report contains
aggregate counts and pseudonymous display aliases only.

## Source and provenance

* Dataset: CGMacros 1.0.0 — https://physionet.org/content/cgmacros/1.0.0/ (https://doi.org/10.13026/3z8q-x658)
* License: **CC BY-NC-SA 4.0** (https://creativecommons.org/licenses/by-nc-sa/4.0/). The dataset license is separate from the application code
  license; source records are not redistributed by this repository.
* Retrieved: 2026-10-11T08:52:20+00:00 from the PhysioNet open-data mirror (byte-identical; verified against the
  published `SHA256SUMS.txt`). Parser: `cgmacros-adapter-1.0`.
* Citation: Gutierrez-Osuna, R., Kerr, D., Mortazavi, B., & Das, A. (2025). CGMacros: a scientific dataset for personalized nutrition and diet monitoring (version 1.0.0). PhysioNet. RRID:SCR_007345. https://doi.org/10.13026/3z8q-x658

| File | Bytes | SHA-256 | Verified |
|---|---|---|---|
| CGMacros_dateshifted365.zip | 657187340 | 05c8b0e6f1a27570… | True |
| DataDictionary.pdf | 967993 | f161ff8df4bd95ef… | True |
| DataDictionary_Bio.csv | 2079 | 2d5b4c27873284dd… | True |
| DataDictionary_CGMacros-00X.csv | 1604 | db7bf114d61b90fc… | True |
| DataDictionary_Gut_Health_Test.csv | 4427 | fbc7555aacb93b2f… | True |
| LICENSE.txt | 0 | e3b0c44298fc1c14… | True |

Only the CSV tables were extracted (48 files); meal photographs were not extracted.

## What the source files actually contain (inspected, not assumed)

* **45 participant files** (`CGMacros-0XX.csv`, IDs 1–49 with 24, 25, 37 and 40 absent) plus `bio.csv`
  (45 rows), `gut_health_test.csv` and `microbes.csv` (the last two are not used).
* **Cohort membership** follows the dataset's documented HbA1c criterion (`A1c PDL (Lab)`): {'No diabetes': 15, 'Type 2 diabetes': 14, 'Pre-diabetes': 16}.
  There is no separate diagnosis column. The data dictionary labels HbA1c "mmol/mol", but the 4.6–8.5 range is
  in %; we treat it as % and record the discrepancy.
* **CGM columns are interpolated.** Each file is a 1-minute merged grid and both `Dexcom GL` and `Libre GL` are
  linearly interpolated between native readings (e.g. 141.0 → 144.6 → 148.2 … → 159.0). One-minute rows are
  therefore *not* independent measurements.
* **Native Dexcom recovery.** Native readings are integer-valued interpolation knots. We recovered
  106,153 knots from slope changes and run endpoints, plus 20,785 collinear readings on the 5-minute grid
  whose interpolated value is an integer (equal consecutive changes, often flat overnight values), and dropped
  668 non-integer slope-change points. Supporting evidence: of all hidden 5-minute grid
  points inside collinear segments, 20,785 had integer values and 0 did not. If missed readings
  had been bridged by interpolation, roughly half of the bridged midpoints of sloped segments would be non-integer.
  Long missing runs are left as NaN in the source and are not bridged.
  Native timestamps are known only to the minute.
* **Undocumented columns** (reported, not interpreted): {'Unnamed: 0': 9, 'Steps': 1, 'RecordIndex': 1, 'Intensity': 11, 'Sugar': 1}. `Intensity` (values 0–3) replaces `METs`
  for some participants and is not mapped to METs; one file has `Steps`/`RecordIndex` instead of
  `Calories (Activity)`.
* **Activity**: `METs` is documented as METs × 10 and converted to METs; per-minute Fitbit values are summarised into
  trailing 5-minute windows that become available at the window end.
* **Meals**: rows with a `Meal Type` (case-normalised to Breakfast/Lunch/Dinner/Snack). Macronutrients were
  estimated by the study team and meal times come from photographs. Logging latency is undocumented, so meals are
  excluded from the primary model (conservative availability policy) and used only in a named optimistic
  sensitivity experiment.
* **Baseline profile**: screening values from `bio.csv` (demographics, anthropometrics, fasting labs). `LDL (Cal)`
  = 800, `VLDL (Cal)` = 400 and `Cho/HDL Ratio` = 400 are documented error codes and are excluded as suspect.
  Pounds and inches are converted to kg and cm. No medication or insulin information exists in the source.
* **Time**: dates were shifted by the publishers (±365–720 days); the timezone is undocumented. We keep the source
  time of day, map study day 1 to a synthetic date (2000-01-03) and label the `Z` offset as a transport
  convention. No weekday, season or biological-clock features are used.
* Timestamp parse failures: 0; duplicate timestamps:
  0; out-of-order rows: 0;
  missing minutes in the merged grid: 18,732 (mostly one participant with a
  multi-day break, excluded from the primary cohort by HbA1c group).

## Primary cohort and device

Primary device: **dexcom_g6_pro** for every participant (chosen before any outcome
evaluation because Dexcom has the finer 5-minute native cadence). Libre readings are stored separately for a
possible sensitivity analysis and are never stitched into the primary series.

Included: **14 participants** with Type 2 diabetes by the dataset criterion and ≥
72 h of native Dexcom readings. Excluded:
31 participants (pre-diabetes or no diabetes by HbA1c; outside the primary analysis).
Sensor-limit readings (exactly 40 or 400 mg/dL) are kept but flagged `suspect`, which degrades forecast quality
at those origins.

| Participant | Cohort | Dexcom native | Detected knots | Collinear recovered | Dropped non-integer | 5-min share | Gaps >15 min | Sensor-limit values | Libre native | Activity coverage | Meals | Missing grid minutes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Participant 01 | Type 2 diabetes | 2855 | 2426 | 433 | 4 | 0.999 | 0 | 0 | 977 | 0.999 | 33 | 15 |
| Participant 02 | Type 2 diabetes | 2855 | 2455 | 401 | 1 | 1.000 | 0 | 25 | 1147 | 1.000 | 34 | 0 |
| Participant 03 | Type 2 diabetes | 2855 | 2307 | 549 | 1 | 1.000 | 0 | 0 | 1141 | 0.891 | 30 | 0 |
| Participant 04 | Type 2 diabetes | 2846 | 2369 | 482 | 5 | 1.000 | 1 | 0 | 1250 | 0.820 | 34 | 0 |
| Participant 05 | Type 2 diabetes | 2855 | 2359 | 497 | 1 | 1.000 | 0 | 2 | 964 | 0.999 | 46 | 0 |
| Participant 06 | Type 2 diabetes | 2854 | 2424 | 451 | 21 | 0.996 | 0 | 0 | 993 | 0.998 | 29 | 30 |
| Participant 07 | Type 2 diabetes | 2853 | 2106 | 760 | 13 | 0.999 | 0 | 0 | 971 | 0.999 | 35 | 15 |
| Participant 08 | Type 2 diabetes | 2855 | 2358 | 498 | 1 | 1.000 | 0 | 0 | 1021 | 1.000 | 28 | 0 |
| Participant 09 | Type 2 diabetes | 2854 | 2525 | 334 | 5 | 1.000 | 0 | 13 | 960 | 1.000 | 27 | 0 |
| Participant 10 | Type 2 diabetes | 2855 | 2378 | 478 | 1 | 1.000 | 0 | 0 | 968 | 1.000 | 22 | 0 |
| Participant 11 | Type 2 diabetes | 2858 | 2508 | 351 | 1 | 0.998 | 0 | 0 | 968 | 1.000 | 40 | 0 |
| Participant 12 | Type 2 diabetes | 2843 | 2429 | 418 | 4 | 0.999 | 1 | 27 | 1030 | 0.894 | 28 | 0 |
| Participant 13 | Type 2 diabetes | 2855 | 2296 | 560 | 1 | 1.000 | 0 | 0 | 1150 | 0.887 | 40 | 0 |
| Participant 14 | Type 2 diabetes | 2846 | 2459 | 399 | 12 | 0.999 | 2 | 0 | 1046 | 1.000 | 29 | 0 |

## Event prevalence and split accounting (primary cohort)

Research event: new onset of glucose > 180 mg/dL sustained ≥ 15 elapsed minutes on native readings (≥ 4 readings
at 5-minute cadence), recovery after 15 minutes ≤ 180 mg/dL; gaps > 7.5 minutes break continuity and censor labels.
Splits are within-participant and chronological (60 % training, 10 % validation-selection, 10 % calibration,
20 % test) with origins purged when label support (75 min + 7.5 min continuity allowance) would cross a boundary.
Purged origins: 932.

| Segment | Origins | Forecast issued | Covered hours | Matched 30-min targets | Matched 60-min targets | Early-warning eligible | Positive origins (60) | Censored eligible (60) | Distinct new onsets (60) |
|---|---|---|---|---|---|---|---|---|---|
| training | 23745 | 23577 | 1978.8 | 23567 | 23567 | 15562 | 2022 | 41 | 203 |
| validation | 3766 | 3766 | 313.8 | 3766 | 3766 | 2256 | 300 | 0 | 32 |
| calibration | 3766 | 3766 | 313.8 | 3766 | 3766 | 2786 | 257 | 0 | 28 |
| test | 7730 | 7720 | 644.2 | 7699 | 7690 | 5044 | 660 | 0 | 64 |

## Unresolved limitations

* 14 Type 2 participants from one US site; no Indian participants.
* CGMs were blinded during the study; the replay assumes zero transmission latency for sensor data.
* Lab turnaround time is undocumented; baseline values are assumed available at twin initialisation.
* Medication and insulin use are unknown; some Type 2 participants may have been treated with glucose-lowering drugs.
* `Intensity`/`Steps` columns are not interpreted, so some participants have no METs (heart rate is still available).

## Full inventory (all participants)

| Participant | Cohort | Primary | Dexcom native | Detected knots | Collinear recovered | Dropped non-integer | 5-min share | Gaps >15 min | Sensor-limit values | Libre native | Activity coverage | Meals | Missing grid minutes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Participant 01 | Type 2 diabetes | yes | 2855 | 2426 | 433 | 4 | 0.999 | 0 | 0 | 977 | 0.999 | 33 | 15 |
| Participant 02 | Type 2 diabetes | yes | 2855 | 2455 | 401 | 1 | 1.000 | 0 | 25 | 1147 | 1.000 | 34 | 0 |
| Participant 03 | Type 2 diabetes | yes | 2855 | 2307 | 549 | 1 | 1.000 | 0 | 0 | 1141 | 0.891 | 30 | 0 |
| Participant 04 | Type 2 diabetes | yes | 2846 | 2369 | 482 | 5 | 1.000 | 1 | 0 | 1250 | 0.820 | 34 | 0 |
| Participant 05 | Type 2 diabetes | yes | 2855 | 2359 | 497 | 1 | 1.000 | 0 | 2 | 964 | 0.999 | 46 | 0 |
| Participant 06 | Type 2 diabetes | yes | 2854 | 2424 | 451 | 21 | 0.996 | 0 | 0 | 993 | 0.998 | 29 | 30 |
| Participant 07 | Type 2 diabetes | yes | 2853 | 2106 | 760 | 13 | 0.999 | 0 | 0 | 971 | 0.999 | 35 | 15 |
| Participant 08 | Type 2 diabetes | yes | 2855 | 2358 | 498 | 1 | 1.000 | 0 | 0 | 1021 | 1.000 | 28 | 0 |
| Participant 09 | Type 2 diabetes | yes | 2854 | 2525 | 334 | 5 | 1.000 | 0 | 13 | 960 | 1.000 | 27 | 0 |
| Participant 10 | Type 2 diabetes | yes | 2855 | 2378 | 478 | 1 | 1.000 | 0 | 0 | 968 | 1.000 | 22 | 0 |
| Participant 11 | Type 2 diabetes | yes | 2858 | 2508 | 351 | 1 | 0.998 | 0 | 0 | 968 | 1.000 | 40 | 0 |
| Participant 12 | Type 2 diabetes | yes | 2843 | 2429 | 418 | 4 | 0.999 | 1 | 27 | 1030 | 0.894 | 28 | 0 |
| Participant 13 | Type 2 diabetes | yes | 2855 | 2296 | 560 | 1 | 1.000 | 0 | 0 | 1150 | 0.887 | 40 | 0 |
| Participant 14 | Type 2 diabetes | yes | 2846 | 2459 | 399 | 12 | 0.999 | 2 | 0 | 1046 | 1.000 | 29 | 0 |
| Participant 15 | Pre-diabetes | no | 2856 | 2423 | 433 | 0 | 1.000 | 0 | 0 | 1077 | 0.946 | 45 | 0 |
| Participant 16 | Pre-diabetes | no | 2848 | 2481 | 380 | 13 | 0.997 | 2 | 25 | 983 | 0.982 | 30 | 0 |
| Participant 17 | Pre-diabetes | no | 2857 | 2487 | 371 | 1 | 0.998 | 0 | 0 | 1079 | 0.947 | 42 | 0 |
| Participant 18 | Pre-diabetes | no | 2733 | 2390 | 349 | 6 | 1.000 | 0 | 1 | 1038 | 0.940 | 32 | 0 |
| Participant 19 | Pre-diabetes | no | 2861 | 2329 | 537 | 5 | 0.996 | 0 | 0 | 982 | 0.999 | 64 | 15 |
| Participant 20 | Pre-diabetes | no | 2766 | 2389 | 381 | 4 | 0.999 | 1 | 0 | 1087 | 0.940 | 36 | 0 |
| Participant 21 | Pre-diabetes | no | 2855 | 2388 | 468 | 1 | 1.000 | 0 | 0 | 1086 | 0.939 | 28 | 0 |
| Participant 22 | Pre-diabetes | no | 2854 | 2504 | 351 | 1 | 1.000 | 0 | 0 | 1175 | 0.871 | 42 | 0 |
| Participant 23 | Pre-diabetes | no | 2854 | 2306 | 552 | 4 | 0.996 | 0 | 31 | 958 | 1.000 | 41 | 0 |
| Participant 24 | Pre-diabetes | no | 2855 | 2306 | 550 | 1 | 1.000 | 0 | 0 | 1182 | 0.866 | 30 | 0 |
| Participant 25 | Pre-diabetes | no | 1374 | 1600 | 225 | 451 | 0.716 | 117 | 0 | 635 | 0.543 | 17 | 4755 |
| Participant 26 | Pre-diabetes | no | 2849 | 2405 | 444 | 0 | 1.000 | 0 | 0 | 954 | 1.000 | 48 | 0 |
| Participant 27 | Pre-diabetes | no | 2855 | 2439 | 417 | 1 | 1.000 | 0 | 0 | 1084 | 0.946 | 41 | 0 |
| Participant 28 | Pre-diabetes | no | 2845 | 2295 | 555 | 5 | 1.000 | 1 | 0 | 969 | 1.000 | 43 | 0 |
| Participant 29 | Pre-diabetes | no | 2854 | 2374 | 481 | 1 | 1.000 | 0 | 0 | 1056 | 0.967 | 39 | 0 |
| Participant 30 | Pre-diabetes | no | 2856 | 2365 | 491 | 0 | 1.000 | 0 | 0 | 987 | 1.000 | 39 | 0 |
| Participant 31 | No diabetes | no | 2860 | 2283 | 582 | 5 | 0.996 | 0 | 0 | 976 | 0.999 | 48 | 15 |
| Participant 32 | No diabetes | no | 2854 | 2234 | 621 | 1 | 1.000 | 0 | 0 | 937 | 1.000 | 62 | 0 |
| Participant 33 | No diabetes | no | 2855 | 2315 | 541 | 1 | 1.000 | 0 | 0 | 1075 | 0.952 | 39 | 0 |
| Participant 34 | No diabetes | no | 2789 | 2362 | 428 | 1 | 0.999 | 1 | 0 | 941 | 0.510 | 39 | 13497 |
| Participant 35 | No diabetes | no | 2853 | 2500 | 362 | 9 | 0.999 | 0 | 1 | 982 | 1.000 | 43 | 0 |
| Participant 36 | No diabetes | no | 2844 | 2379 | 503 | 38 | 0.994 | 0 | 0 | 1210 | 0.876 | 52 | 360 |
| Participant 37 | No diabetes | no | 2731 | 2353 | 384 | 6 | 1.000 | 1 | 0 | 914 | 0.954 | 20 | 0 |
| Participant 38 | No diabetes | no | 2845 | 2536 | 328 | 19 | 0.997 | 1 | 2 | 1059 | 0.780 | 33 | 15 |
| Participant 39 | No diabetes | no | 2735 | 2302 | 434 | 1 | 1.000 | 0 | 0 | 915 | 1.000 | 54 | 0 |
| Participant 40 | No diabetes | no | 2842 | 2432 | 415 | 5 | 1.000 | 1 | 0 | 968 | 1.000 | 36 | 0 |
| Participant 41 | No diabetes | no | 2855 | 2012 | 844 | 1 | 1.000 | 0 | 0 | 964 | 0.998 | 38 | 0 |
| Participant 42 | No diabetes | no | 2857 | 2512 | 354 | 9 | 0.997 | 0 | 7 | 1170 | 0.999 | 36 | 15 |
| Participant 43 | No diabetes | no | 2855 | 2444 | 412 | 1 | 1.000 | 0 | 0 | 980 | 1.000 | 49 | 0 |
| Participant 44 | No diabetes | no | 2736 | 2241 | 496 | 1 | 1.000 | 0 | 0 | 1135 | 0.859 | 37 | 0 |
| Participant 45 | No diabetes | no | 2848 | 2368 | 485 | 5 | 1.000 | 1 | 1 | 1080 | 0.946 | 48 | 0 |
