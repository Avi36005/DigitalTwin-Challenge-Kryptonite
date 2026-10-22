# Data opportunity check — 21 October 2026

A bounded (≤ 45 minute) desk check for **additional eligible data**, made during the 21–22 October sprint. Research
only: **nothing was downloaded, no agreement was accepted, no account was used**, and no participant-level file was
opened. Sources read: the Glucose-ML repository's per-dataset README files and the summary tables it publishes for its
paper (Prioleau, Lu and Cui, 2025, arXiv:2507.14077), read through the GitHub API at `main` on 21 Oct 2026, and the
figshare item metadata of ShanghaiT2DM. No participant identifiers appear here. It complements
[`data_access_inventory_2026-10-21.md`](data_access_inventory_2026-10-21.md) and does **not** change any study,
cohort, model or result.

## What "eligible" means here

The primary task needs adults with **Type 2 diabetes**, at least **72 observed CGM hours**, and — for the serving
fusion model — a **wearable stream and a baseline profile** (labs, demographics) with known availability times. A
CGM-only source can only test the forecasting core (like the existing ShanghaiT2DM check), never the profile and
wearable fusion. Catalogue totals and unopened archives are not evaluated participants.

## Glucose-ML components, one row each

Counts are the collection's published per-dataset person counts (its Table 2/3), not GlucoTwin counts. "Licence" is
the component's **own** terms as stated in its Glucose-ML README; the collection's MIT licence covers its code only.

| Component | Access | Licence of the original data (as stated) | Population | People | Days / person (mean) | CGM, native cadence | Relation to our data |
|---|---|---|---|---|---|---|---|
| CGMacros (Dexcom and Libre copies) | Open | CC BY-NC-SA 4.0 | T2D, prediabetes, no diabetes | 45 (listed twice: one per sensor) | 11 | Dexcom G6 Pro 5 min; Libre Pro 15 min | **Already ours** (the two copies are the same 45 people, two sensors — recordings, not extra persons) |
| ShanghaiT2DM | Open | figshare item: **CC BY 4.0** (README says "no dataset licence found"; the figshare record lists CC BY 4.0, version 5) | T2D | 100 | 12.9 | Libre H, 15 min | **Already ours** — the external CGM-only check; must not be repurposed for training while keeping its external label |
| ShanghaiT1DM | Open | as ShanghaiT2DM (same figshare collection) | T1D | 12 | 15.1 | Libre H, 15 min | Out of population (Type 1) |
| AI-READI | Controlled | AI-READI licence + agreements | T2D, prediabetes, no diabetes | 2,280 | 10.7 | Dexcom G6, 5 min | **Access dependency** — not accessed; only the team can complete the steps |
| Hall 2018 | Open (with the publication) | CC BY 4.0 (publication) | T2D, prediabetes, no diabetes | 57 | 8.3 | Dexcom G4, 5 min | Mixed population; HbA1c range 4.6–6.7 %, so few if any meet our Type 2 rule; wearable stream not listed |
| Colas 2019 | Open (with the publication) | CC BY 4.0 (publication) | T2D, no diabetes | 208 | 1.9 | Medtronic iPro, 5 min | Recordings of about 2 days: below the 72-hour rule |
| Park 2025 | Open (Stanford CGM database) | **No dataset licence found**; publication CC BY-NC-ND 4.0 | T2D, prediabetes, no diabetes | 38 | not reported (≈ 23.5 k readings in total) | Dexcom G4, 5 min | Short records; licence unclear — would need the publisher's terms first |
| BIG IDEAs | Open (PhysioNet) | ODC-By 1.0 | Prediabetes, no diabetes | 16 | 9.4 | Dexcom G6, 5 min (+ smartwatch) | No Type 2; possible auxiliary-training data only |
| T1DEXI, T1DEXIP, DiaTrend, OhioT1DM, T1DiabetesGranada | Controlled | each needs its own agreement | T1D | 497 / 247 / 54 / 12 / 736 | 10–512 | Dexcom / Medtronic / Libre | Out of population (Type 1) |
| AZT1D, HUPA-UCM, T1D-UOM, Bris-T1D Open, PhysioCGM, D1NAMO | Open | CC BY 4.0 (AZT1D, HUPA-UCM, T1D-UOM, Bris-T1D); CC0 (PhysioCGM); CC BY-SA 4.0 (D1NAMO) | T1D (D1NAMO also lists healthy volunteers) | 25 / 25 / 17 / 20 / 10 / 9 | 4–183 | Dexcom / Libre / Medtronic | Out of population (Type 1) |
| UCHTT1DM | Open | **No dataset licence found**; publication CC BY-NC-ND 4.0 | T1D, no diabetes | 20 | 6.4 | Medtronic Guardian 3 | Out of population |

No component is described as **synthetic**; none is gestational.

## Findings

1. **No additional eligible Type 2 fusion data is accessible without agreements.** The open components with Type 2
   people (Hall 2018, Colas 2019, Park 2025) are mixed populations with low HbA1c ranges, short recordings or an unclear
   dataset licence, and none lists a wearable stream with dated labs. Even a later import would be CGM-only, so it
   could test the forecasting core but not the profile-plus-wearable fusion.
2. **Several components are already ours.** CGMacros appears twice (one copy per sensor: the same people, not new
   persons) and ShanghaiT2DM is our external check. Hall 2018 and Park 2025 both come from the same research group;
   whether people overlap between them is not documented in what we read.
3. **Licence discrepancy noted, no change needed.** Glucose-ML's README says no dataset licence was found for the
   Shanghai datasets; the figshare record we use lists **CC BY 4.0** (version 5), which is what the README and data card
   cite.
4. **Possible future auxiliary-training arm (not run, not declared):** the **31 non-Type-2 CGMacros participants**
   (16 prediabetes, 15 no diabetes) already imported, and potentially BIG IDEAs (prediabetes/no diabetes, ODC-By).
   This would change the training population only; it adds **no Type 2 assessment people**, keeps the Type 2 estimand
   and held-out groups unchanged, and would need its own protocol declared before any fit, with the mixed training
   population reported openly. It was not frozen in this sprint's first hour, so it is reserved for later.
5. **AI-READI stays an access dependency.** It is the only listed source with a large Type 2 group, 5-minute CGM and a
   wearable stream, but it requires the team's own credentialing and licence acceptance. Nothing was requested.

## Not done, deliberately

No data or metadata files were downloaded; no participant-level identifiers were read, so recording-level
deduplication against our cohorts was not possible and is left to any future import (the inventory's overlap check
would apply). No account was created and no agreement accepted.
