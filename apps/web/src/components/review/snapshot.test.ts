import { createElement } from "react";
import { describe, expect, it } from "vitest";
import type { Alert, AlertList, SessionProfile, TwinState } from "@/api/types";
import { forecast, glucose, latest, session } from "@/test/fixtures";
import { buildSnapshot, MAX_WARNINGS, nodeText, snapshotFileName, snapshotReadiness } from "./snapshot";

const CUT = "2000-01-03T10:00:00Z";

function alert(id: string, issued: string, over: Partial<Alert> = {}): Alert {
  return {
    schema_version: "1.0", alert_id: id, session_id: "s1", patient_id: "SYN-A", session_revision: 1, issued_at: issued,
    last_supported_at: issued, horizon_minutes: 60, rule_version: "r", model_version: "m", kind: "predicted_new_high_episode",
    title: "t", evidence: { forecast_id: "f", score: 5, score_kind: "forecast_margin_mg_dl", threshold: -10, latest_glucose_mg_dl: 150,
      predicted_mg_dl: { "30": 165, "60": 185 }, explanation_codes: [] },
    supporting_forecast_ids: [], state: "open", outcome: { status: "pending" },
    acknowledgement: { acknowledged: false, meaning: "local" }, ...over,
  } as Alert;
}
const alerts = (items: Alert[], over: Partial<AlertList> = {}): AlertList =>
  ({ schema_version: "1.0", session_id: "s1", session_revision: 1, clock_at: CUT, rule_available: true, rule_description: null,
    items, ...over }) as AlertList;
const profile = (values: SessionProfile["values"]): SessionProfile =>
  ({ schema_version: "1.0", session_id: "s1", patient_id: "SYN-A", session_revision: 1, as_of: CUT,
    cohort: { label: "Type 2 diabetes" }, values }) as unknown as SessionProfile;
const twin = { schema_version: "1.0", session_id: "s1", patient_id: "SYN-A", session_revision: 1, as_of: CUT, model_version: "synthetic-demo",
  personalization: { enabled: false, status: "disabled", state_version: 0, horizons: [] }, history: { valid_samples_60: 12 } } as unknown as TwinState;

const base = (over: Partial<Parameters<typeof buildSnapshot>[0]> = {}) => buildSnapshot({
  session: session(), events: [glucose("g1", "2000-01-03T09:55:00Z", 150)], latest: latest(forecast()), alerts: alerts([]),
  twin, profile: profile([]), guardrails: [], generatedAt: "2026-10-20T11:00:00Z", ...over,
});

describe("review snapshot", () => {
  it("keeps the replay cutoff and the wall-clock generation time apart", () => {
    const s = base();
    expect(s.replay_cutoff).toBe(CUT);
    expect(s.replay_cutoff_label).toBe("Day 1 · 10:00 (replay time)");
    expect(s.generated_at_wall_clock).toBe("2026-10-20T11:00:00Z");
    expect(s.disclaimer).toBe("Research replay review — not a medical report");
  });

  it("never includes observations, warnings or outcomes from after the cutoff", () => {
    const s = base({
      events: [glucose("g1", "2000-01-03T09:55:00Z", 150), glucose("g2", "2000-01-03T10:05:00Z", 999),
        glucose("g3", "2000-01-03T09:58:00Z", 777, "2000-01-03T10:02:00Z")], // observed before, released after
      alerts: alerts([
        alert("a1", "2000-01-03T09:00:00Z", { outcome: { status: "onset_observed", onset_at: "2000-01-03T10:20:00Z", confirmed_at: "2000-01-03T10:35:00Z" } }),
        alert("a2", "2000-01-03T10:10:00Z"),
      ]),
    });
    expect(s.glucose?.value_mg_dl).toBe(150);
    expect(s.warnings.total).toBe(1);
    expect(s.warnings.items[0].outcome).toBe("Outcome pending at the cutoff");
    expect(JSON.stringify(s)).not.toMatch(/999|777|10:10/);
  });

  it("does not show a forecast issued after the cutoff and never substitutes zeros", () => {
    const s = base({ latest: latest(forecast({ as_of: "2000-01-03T10:30:00Z" })) });
    expect(s.forecast.estimates).toEqual([]);
    const none = base({ latest: latest(null) });
    expect(none.forecast.availability).toBe("Not available");
    expect(none.forecast.unavailable).toMatch(/Forecast unavailable/);
    expect(none.forecast.estimates).toEqual([]);
  });

  it("marks a stale reading and keeps unavailable ranges unavailable", () => {
    const s = base({ events: [glucose("g1", "2000-01-03T09:30:00Z", 150)], latest: latest(forecast({}, false)) });
    expect(s.glucose?.stale).toBe(true);
    expect(s.glucose?.age_minutes).toBe(30);
    expect(s.forecast.estimates[0].range_mg_dl).toBeNull();
    expect(s.forecast.estimates[0].range_status).toBe("Unavailable");
    expect(s.forecast.estimates[0].population_mg_dl).toBe(160);
  });

  it("keeps profile values that were not yet known at the cutoff unknown", () => {
    const s = base({ profile: profile([
      { name: "hba1c", label: "HbA1c", value: 7.6, unit: "%", status: "available", available_at: "2000-01-03T08:00:00Z" },
      { name: "bmi", label: "BMI", value: 34, unit: "kg/m²", status: "available", available_at: "2000-01-03T12:00:00Z" },
      { name: "tg", label: "Triglycerides", value: null, status: "missing_in_source" },
    ]) });
    expect(s.profile?.items.map((v) => v.value)).toEqual(["7.6 %", "Not yet available", "Not available"]);
  });

  it("lists the most recent warnings, states the total and carries saved review notes as text", () => {
    const many = Array.from({ length: 25 }, (_, i) => alert(`a${i}`, `2000-01-03T0${Math.floor(i / 6)}:${String((i % 6) * 10).padStart(2, "0")}:00Z`));
    many[24] = alert("a24", "2000-01-03T09:50:00Z", { acknowledgement: { acknowledged: true, acknowledged_at: "2026-10-20T10:00:00Z",
      note: "<img src=x onerror=alert(1)> checked trend", meaning: "local" } });
    const s = base({ alerts: alerts(many) });
    expect(s.warnings.total).toBe(25);
    expect(s.warnings.listed).toBe(MAX_WARNINGS);
    expect(s.warnings.truncated).toBe(true);
    expect(s.warnings.items[0].note).toBe("<img src=x onerror=alert(1)> checked trend"); // kept verbatim as data, rendered as text
  });

  it("ignores data from another participant or revision", () => {
    const s = base({ alerts: alerts([alert("a1", "2000-01-03T09:00:00Z")], { session_revision: 2 }),
      events: [{ ...glucose("x", "2000-01-03T09:59:00Z", 300), patient_id: "OTHER" }, glucose("g1", "2000-01-03T09:55:00Z", 150)] });
    expect(s.warnings.total).toBe(0);
    expect(s.glucose?.value_mg_dl).toBe(150);
  });

  it("survives a JSON round trip unchanged", () => {
    const s = base();
    expect(JSON.parse(JSON.stringify(s))).toEqual(s);
    expect(snapshotFileName(s)).toBe("glucotwin-review-synthetic-participant-a-r1-2000-01-03t10-00-00z.json");
  });
});

describe("snapshot readiness", () => {
  const q = { latest: { data: latest(forecast()) }, alerts: { data: alerts([]) }, twin: { data: twin }, profile: { data: profile([]) } };
  it("is ready only when every response belongs to this revision and replay time", () => {
    expect(snapshotReadiness(session(), q, true)).toEqual({ ok: true });
    expect(snapshotReadiness(session(), q, false).ok).toBe(false);
    expect(snapshotReadiness(session(), { ...q, latest: { data: latest(forecast()), isPlaceholderData: true } }, true).ok).toBe(false);
    expect(snapshotReadiness(session({ revision: 2 }), q, true).ok).toBe(false);
    expect(snapshotReadiness(session({ clock_at: "2000-01-03T10:05:00Z" }), q, true).ok).toBe(false);
    expect(snapshotReadiness(session({ patient_id: "SYN-B" }), q, true).ok).toBe(false);
  });
});

describe("nodeText", () => {
  it("flattens small JSX fragments to plain text", () => {
    expect(nodeText(createElement("span", null, "Fresh · 3 min old ", createElement("span", { className: "muted" }, "(limit 15 min)")))).toBe("Fresh · 3 min old (limit 15 min)");
  });
});
