# GlucoTwin — product definition

**GlucoTwin: personalized glucose forecasting between clinic visits.** A student research proof of concept for
the Happiest Health Digital Twin Challenge 2026.

## Mission

Help a clinician answer: **"Which monitored patient's glucose pattern merits review, and what observations
support that conclusion?"**

HbA1c summarises roughly three months of glucose and cannot show the short excursions that happen between
appointments. GlucoTwin keeps a patient-specific state that is initialised from baseline information, updated as
continuous-glucose and wearable observations arrive, and used to forecast glucose 30 and 60 minutes ahead. It
investigates early warning of a new sustained high-glucose episode and shows — with measured evidence — whether
learning from a patient's own earlier forecast errors improves later forecasts.

## Users

* **Primary:** a clinician reviewing a small monitored cohort (research setting).
* **Secondary:** a jury member or reviewer inspecting the evidence.

## Scope (version 1)

In scope: Type 2 diabetes; recorded-data replay of CGMacros 1.0.0; synthetic demonstration mode; 30/60-minute
glucose forecasts with prediction ranges calibrated on a separate calibration segment (target coverage 80 %, measured coverage reported); research warning of a new sustained episode
(> 180 mg/dL for ≥ 15 minutes); patient adaptation; clinician dashboard; measured evaluation against baselines.

Out of scope: patient app, EHR integration, real device connection, notifications, billing, prescriptions,
insulin dosing, treatment recommendations, production deployment, LLM-generated predictions or explanations.

## What "digital twin" means here

An operational research description: a versioned patient state, a stream of incoming observations, a
forecasting model and measured updates over time. It is **not** a validated whole-body physiological replica.
See [architecture](architecture.md#the-operational-twin).

## Honesty rules the product enforces

* Replay is always labelled "Recorded-data replay" or "Synthetic demonstration" — never "live".
* Only information available at the replay time is used or shown; issued forecasts are immutable.
* Unknown is not low risk; null is not zero; scores are not probabilities.
* Synthetic outputs never appear as measured clinical performance.
* Explanations state observations and model associations, never causes or treatment advice.
* Every reported metric traces to `artifacts/experiments/<experiment_id>/metrics.json`.

## Potential fit (proposal, not a claim)

Happiest Health describes diagnostics and outpatient clinic businesses
([company page](https://www.happiesthealth.com/about-us)). A workflow of *baseline labs → everyday sensor
measurements → personalised forecasts → clinician review* could fit such services. No partnership, pilot,
endorsement or clinical benefit is claimed.
