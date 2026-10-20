import { Section } from "@/components/ui";

/** The guardrails enforced in code, in the README's wording (README.md · Safety guardrails). Rules only: measured values
 *  (coverage, warning outcomes) appear in the sections above and in the replay workspace, read from the API. */
export const GUARDRAILS: { title: string; text: string; source: string }[] = [
  { title: "Abstains instead of guessing", source: "ml/glucotwin/features.py · tests/test_replay_api.py",
    text: "No forecast is issued with less than 60 min of history, fewer than half the expected readings in the last hour or without a new reading; after 15 min without one, the last forecast is shown marked Stale. The reason is shown." },
  { title: "Flags weak inputs", source: "ml/glucotwin/features.py",
    text: "A forecast is marked Degraded, with reasons, after a gap longer than 15 min, an incomplete last hour, a reading at the sensor limit (40 or 400 mg/dL) or a missing wearable summary." },
  { title: "Fusion model needs its health record", source: "tests/test_leakage.py",
    text: "The profile model was trained on complete profiles only, so it abstains when a profile value is missing or not yet available." },
  { title: "No look-ahead", source: "docs/data_card.md · tests/test_leakage.py",
    text: "Only native sensor readings are used, never the dataset’s interpolated 1-minute rows. Labs, meals and wearable summaries enter only after the time they became available." },
  { title: "Bounded patient correction", source: "ml/glucotwin/models/adaptation.py",
    text: "The per-patient correction learns only from forecasts whose outcome has been observed, needs at least 6 of them, is capped at ±25 mg/dL and resets after a 3-hour gap." },
  { title: "Implausible data rejected", source: "ml/glucotwin/data/cgmacros.py · canonical.py",
    text: "Readings outside the device’s reporting range and impossible timestamps are marked invalid and never used; readings at the limit are marked suspect." },
  { title: "Every warning shows its outcome", source: "ml/glucotwin/evaluation/alerts.py",
    text: "Each warning is labelled Research warning, stays Outcome pending until it can be judged, and is then matched to an onset, counted as a false alarm or marked Outcome unknown (gap) when missing data hides the outcome. Firings within 30 min merge into one episode. The false-alarm rate is published next to the hit rate." },
  { title: "Uncertainty shown", source: "Replay workspace · Results at a glance",
    text: "Every forecast carries an 80% prediction range, and the measured coverage is stated next to it." },
  { title: "No clinical claims", source: "Help & demo guide",
    text: "Research demonstration only: not a medical device, no treatment advice, a replay and never a live device." },
  { title: "Tests cannot be quietly re-run", source: "ml/glucotwin/research/assess.py · promote.py",
    text: "An opened test writes a lock file; re-running needs a written reason and is then marked exploratory. Research runs cannot change the demo model; promotion and rollback are separate, explicit commands." },
  { title: "App matches the evaluation", source: "reports/verification.md",
    text: "Replaying every test participant through the app reproduced each saved test forecast within 0.05 mg/dL." },
];

export function SafetyGuardrails() {
  return (
    <Section title="Safety guardrails" id="safety-guardrails"
      description="Enforced in the code and covered by tests. The replay workspace shows which of them applied to each forecast.">
      <dl className="guardrail-list">
        {GUARDRAILS.map((g) => (
          <div key={g.title} className="guardrail-list__row">
            <dt>{g.title}</dt>
            <dd>{g.text}<span className="guardrail-list__src">{g.source}</span></dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}
