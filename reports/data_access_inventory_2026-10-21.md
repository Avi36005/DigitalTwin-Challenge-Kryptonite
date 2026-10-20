# Data access inventory — 21 October 2026

Read-only summary of `reports/dataset_inventory.json`, `reports/dataset_expansion_audit.md` and `docs/data_card.md`.
Nothing was downloaded, no agreement was accepted, and no account was used. No raw data or participant identifiers
appear here.

| Source | Licence / terms | Acquired | Parsed | Participants: acquired / parsed / task-eligible | Cadence | Role | Blocking step |
|---|---|---|---|---|---|---|---|
| CGMacros 1.0.0 (PhysioNet) | CC BY-NC-SA 4.0 | Yes (publisher checksums verified) | Yes | 45 / 45 / **14** (Type 2 diabetes, ≥ 72 observed hours, wearable and baseline profile available for the fusion task) | Native 5-min Dexcom readings, recovered from the interpolated 1-min columns; 5-min wearable summaries | **Development**: the 14 Type 2 participants only | None |
| ShanghaiT2DM (figshare v5) | CC BY 4.0 | Yes (publisher MD5 verified) | Yes | 100 / 100 / **98** (≥ 72 observed hours); 0 for the fusion task, which needs wearable data and dated labs this source lacks | 15-min CGM | **External CGM-only benchmark** (portable 15-minute track); never trained on | None for its current role |
| AI-READI v3 (FAIRhub) | Custom AI-READI Data License Agreement; restricted data also need a DTUA and Data Access Committee approval | No | No | 0 / 0 / 0 (the publisher's catalog count is never a GlucoTwin count) | — | Not used | The team's own credentialing: FAIRhub login via CILogon with institutional credentials, an Azure Storage container, training questions, a published research purpose, and acceptance of the licence. Only the team can do this |
| Glucose-ML collection | MIT for the code only; each component dataset keeps its own terms | No | No | 0 / 0 / 0 | — | Discovery only | Its harmonised copies overlap CGMacros, ShanghaiT2DM and AI-READI, so it adds no new eligible people |

Plainly:

* **CGMacros:** 45 people overall, but only **14 are eligible Type 2 participants** for the primary task (16 have
  pre-diabetes, 15 no diabetes, by the documented HbA1c rule). The other 31 could only support a separately declared
  auxiliary-training study. They would change the training population but add no Type 2 assessment participants, and
  they are not part of the current studies.
* **ShanghaiT2DM:** 100 people imported and 98 eligible. It is the external CGM-only benchmark, never trained on, and
  it cannot enter the fusion model, which needs wearable and profile inputs.
* **Overlap:** recordings across sources were compared (199 recordings, 19,656 pairs). The largest overlap was 0.17,
  against a 0.5 flag threshold, and no pair was flagged.
* **No additional eligible data is accessible now.** AI-READI remains blocked on steps only the team can take, and
  Glucose-ML adds no new people.
