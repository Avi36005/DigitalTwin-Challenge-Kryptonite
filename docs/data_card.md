# Data card

## Recorded data: CGMacros 1.0.0

* **Source:** Gutierrez-Osuna R., Kerr D., Mortazavi B., Das A. (2025). *CGMacros: a scientific dataset for
  personalized nutrition and diet monitoring* (version 1.0.0). PhysioNet. https://doi.org/10.13026/3z8q-x658.
  Please also cite the PhysioNet platform paper as requested on the dataset page.
* **License:** Creative Commons Attribution-NonCommercial-ShareAlike 4.0. This is separate from GlucoTwin's MIT code
  license. Raw and patient-level processed files are **not** in this repository; users download them with
  `make data-download` (or manually) and verify them against the published `SHA256SUMS.txt`.
* **Collection:** Sansum Diabetes Research Institute, Santa Barbara, CA; 45 adults recruited 2021–2024; ~10 days of
  free-living data; Dexcom G6 Pro (5-min) and FreeStyle Libre Pro (15-min) CGMs, both **blinded**; Fitbit Sense;
  meal photos and logged meals (breakfast shakes and restaurant lunches of known composition, free-choice dinners);
  screening labs on day 1. Dates were shifted by the publishers (365–720 days).
* **Usable cohort (measured):** 45 participant files; cohort by the documented HbA1c rule: 14 Type 2 diabetes,
  16 pre-diabetes, 15 no diabetes. Primary analysis: the 14 Type 2 participants, all with ≥ 72 h of native Dexcom
  readings (≈ 9.9 days, ≈ 2,850 readings each; ≥ 99.5 % of intervals exactly 5 minutes).
* **Selected device:** Dexcom G6 Pro only (Libre stored separately, unused).
* **Field availability:** see [feature availability](feature_availability.md). Meals are excluded from the primary
  model (logging latency unknown). Baseline labs assumed available at twin initialisation.
* **Missingness and quality (Type 2 cohort):** few gaps > 15 minutes (0–2 per participant); some sensor-limit
  readings at 400 mg/dL (up to 27 in one participant) are kept and flagged; activity coverage 82–100 % of minutes.
  Undocumented columns (`Intensity`, `Steps`, `Sugar`, `RecordIndex`) are reported and not interpreted.
* **Time:** synthetic UTC timeline preserving source time of day; timezone undocumented; no calendar features.
* **Exclusions:** 31 participants outside the Type 2 group (by HbA1c) — available for replay, labelled
  "outside primary analysis", never used in training or evaluation.
* **Known issues:** the data dictionary labels HbA1c in mmol/mol although values are in %; CGM columns in the merged
  table are linearly interpolated (we recover native readings); `LDL (Cal)`=800 and `VLDL (Cal)`=400 are documented
  error codes.

Full measured inventory: [`reports/data_audit.md`](../reports/data_audit.md).

## Recorded data: ShanghaiT2DM (figshare 21600933 v5) — reserved external cohort

* **Source:** *Chinese diabetes datasets for data-driven machine learning*, Scientific Data 10, 35 (2023),
  https://doi.org/10.1038/s41597-023-01940-7; data: Zhao, Zhu, Wang, Rao (2022), `diabetes_datasets.zip`, figshare,
  https://doi.org/10.6084/m9.figshare.21600933.v5. **License:** CC BY 4.0. Downloaded 2026-10-12 (3,738,354 bytes,
  publisher MD5 verified) with `glucotwin data download --dataset shanghai_t2dm`; raw and participant-level files stay
  out of git.
* **Collection (data descriptor):** diagnosed Type 2 diabetes (WHO 1999), Shanghai Fourth People's Hospital and
  Shanghai East Hospital (DiaDRIL registry, inpatients and outpatients); FreeStyle Libre H flash CGM storing a reading
  every 15 minutes for 3–14 days; capillary glucose, ketones, diet, insulin and oral agents recorded; labs taken up to
  6 months before or after CGM.
* **Imported (measured):** 100 people, 109 recordings (92 people with one recording, 7 with two, 1 with three — the
  descriptor's own count differs), 112,462 native readings, 28,115 gap-respecting observed hours. Every CGM value is a
  multiple of 1.8 (mmol/L × 18 upstream); values are kept in the declared mg/dL. 13 missing cells (a documented device
  change), 329 readings at the assumed reporting limit (39.6 mg/dL) flagged `suspect`, two files without a unit in the
  header (dataset convention used, recorded per row). No duplicates, overlaps or timestamp anomalies.
* **Eligible:** 98 people with ≥ 72 observed hours (declared before any result). Role: external assessment of the
  portable 15-minute CGM-only track, opened once; never trained, tuned or calibrated on.
* **Not used as inputs:** labs and demographics (no dates; never causally available), diet, insulin and medication
  records (different semantics and timing), capillary glucose. 16 ShanghaiT1DM files in the archive are not imported.
* **Time:** the same synthetic day-aligned UTC policy as CGMacros; recordings of one person keep their relative
  order (visit numbers are not chronological); source wall-clock strings are kept in the canonical layer.

## Canonical layer and inventory

Both datasets are also written to `data/processed/canonical/canonical-cgm-1/` (one partition per dataset and person)
with dataset/version, recording, device, source record, observed/available/original timestamps, timezone status,
native cadence, value, original value and unit, conversion, quality, missing reason, source-file hash, parser
version and availability assumption. The CGMacros model store was not rewritten; its glucose tables equal the
canonical layer for all 45 people. Measured counts, bytes, overlap checks and split membership:
[`reports/dataset_expansion_audit.md`](../reports/dataset_expansion_audit.md) and `reports/dataset_inventory.json`.

## Not acquired

* **AI-READI v3** (2,280 people across disease stages, 3.82 TB release; publisher figures) — `access_required`. The
  FAIRhub workflow (Azure container, CILogon login, training questions, public research purpose, licence acceptance)
  must be completed by the user; nothing was requested or accepted on their behalf. A local parser for its Open mHealth
  CGM JSON and a selective-download planner are tested on fictional fixtures only.
* **Glucose-ML** — discovery only; its harmonized copies include CGMacros, ShanghaiT2DM and AI-READI, so importing
  them would double-count people. Its catalogue total is never a GlucoTwin count.

## Synthetic data

Generated by `glucotwin.data.synthetic` (deterministic seeds; CC0-1.0). Fictional participants with simulated meals,
activity, glucose responses, sensor noise, gaps, sensor-limit readings and late meal logging. Not derived from,
copied from, or perturbed from any real participant. Used to test software behaviour and to fit a demonstration
model that is labelled `synthetic_fitted` everywhere. Nothing computed on it is clinical evidence.
