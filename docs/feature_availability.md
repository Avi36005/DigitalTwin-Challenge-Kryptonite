# Feature availability ledger

Rule for every forecast origin `t`: a record may contribute only if `observed_at ≤ t` **and** `available_at ≤ t`.
All aggregates are trailing; no centred windows, back-fills or interpolation across future points.
Primary availability policy: `conservative-v1` (`configs/data.yaml`).

| Source field | Meaning | Unit | Observation time | Availability rule | Transformation (support) | Missing handling | Prediction use |
|---|---|---|---|---|---|---|---|
| `Dexcom GL` (native knots) | Interstitial glucose | mg/dL | Native reading time (to the minute) | Available when observed (replay approximation; the study CGM was blinded) | Latest value, lags 5–120 min (±2.5 min match), changes and slopes over 15/30/60 min, acceleration, mean/SD/min/max/fraction > 180 over 60/180 min, counts, largest gap, history span (≤ 180 min lookback) | Unmatched lag → NaN; never filled | Primary (all model families) |
| `Libre GL` (native knots) | Second CGM | mg/dL | Native reading time | Same | Stored only | — | Not used (sensitivity analysis not run) |
| `HR` | Heart rate, last minute | bpm | Minute | Available at the end of its 5-minute summary window | Window means over 30/60/120 min, weighted by covered minutes inside the window (`dyn-v2`) | NaN if no covered minutes | Primary (`dyn-*` feature sets) |
| `METs` | Activity intensity (METs × 10 in source) | MET | Minute | End of 5-minute window | Mean/max over 30/60 min, active minutes (≥ 3 METs) | NaN; participants with `Intensity` instead of `METs` have no METs | Primary (`dyn-*`) |
| `Calories (Activity)` | Fitbit activity energy | kcal | Minute | End of 5-minute window | Sum over 60 min, wearable coverage fraction (`dyn-v2`: each summary contributes only its share inside `(t − 60, t]`, so coverage ≤ 100 %) | NaN / coverage 0 → quality `degraded` (`activity_unavailable`); energy NaN, not 0, when unrecorded | Primary (`dyn-*`) |
| `Meal Type`, `Calories`, `Carbs`, `Protein`, `Fat`, `Fiber` | Meal start (photo) and study-estimated macronutrients | g, kcal | Photo timestamp | **Unknown** logging latency → excluded from the primary model | Sums over 60/180 min, minutes since meal, last-meal carbohydrate | 0 when no meal in window (explicit sums), NaN for time since meal | **Sensitivity only** (`dyn-prof-meal-v2`; `-v1` in experiment v1; optimistic: assumes availability at photo time) |
| `Amount Consumed` | Share eaten (from after-photo) | % | After the meal | Not available at meal start | — | — | Not used |
| `Age`, `Gender`, `BMI` | Baseline | years, –, kg/m² | Screening, day 1 | Available at twin initialisation (recording start) | Constant | NaN if missing | `dyn-prof-v2` candidate only (`dyn-prof-v1` in experiment v1) |
| `A1c PDL (Lab)`, `Fasting GLU`, `Insulin`, `Triglycerides`, `HDL` | Screening labs | %, mg/dL, µU/mL | Screening, day 1 | Assumed available at initialisation; lab turnaround undocumented | Constant | NaN if missing | `dyn-prof-v2` candidate only (`dyn-prof-v1` in experiment v1) |
| `LDL (Cal)`, `VLDL (Cal)`, cholesterol, ethnicity, weight, height | Baseline | various | Screening | As above | — | Error codes excluded | Display only |
| Fingerstick glucose, microbiome, gut-health scores | Day-1 measurements | — | Day 1 | — | — | — | Not used |
| Participant ID | Grouping key | — | — | — | — | — | **Never** a model input |

Forecast quality rules (shared by evaluation and serving): `insufficient` when the latest reading is older than
15 minutes, history spans < 60 minutes (−2.5 min tolerance), or fewer than half the expected readings exist in the
last 60 minutes; `degraded` for < 80 % expected readings, a gap > 15 minutes in the last hour, a sensor-limit
reading, or no wearable data in the last hour.

**Activity-window convention.** A 5-minute wearable summary observed at `e` covers `(e − 5, e]`. Feature sets `*-v2`
(serving since `gt-primary-2026-10-11-v2`) count only the part of each released summary inside the lookback window
`(t − w, t]`; a summary ending exactly at `t − w` contributes nothing. Energy and active minutes are allocated in
proportion to that share (an approximation at non-aligned origins), and duplicate summaries are counted once. The
`*-v1` feature sets keep the original rule — every summary ending in `[t − w, t]`, counted in full, which could reach
65 minutes in a 60-minute window — only so the v1 experiment reproduces (`reports/repair_report.md`).

**Portable 15-minute track (`cgm15-v1`, experiment `gt-nested-2026-10-12-v1`).** CGM only. Native 15-minute readings
(ShanghaiT2DM) are used as they are; 5-minute Dexcom readings are causally decimated to the first reading in each
absolute 15-minute bin (keeping a reading depends only on earlier readings; nothing is interpolated). Lags 15–120 min
(±7.5 min match), the same trailing windows, freshness limit 22.5 min, targets matched to a real decimated/native
reading within ±7.5 min. `slope_15` is always missing at this cadence. ShanghaiT2DM labs, diet and medication records
are never inputs: the labs have no dates, and "unknown" is not an assumed baseline.
