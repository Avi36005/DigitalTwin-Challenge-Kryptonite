import { describe, expect, it } from "vitest";
import type { Alert, AlertList, EvaluationReport, SessionProfile } from "@/api/types";
import { forecast } from "@/test/fixtures";
import { explainForecast, trackRecord } from "./explain";
import { ms } from "./time";

const CUTOFF = ms("2000-01-03T10:00:00Z");

function alert(id: string, issued: string, outcome: Alert["outcome"]): Alert {
  return { alert_id: id, session_id: "s1", session_revision: 1, issued_at: issued, outcome } as Alert;
}
const alerts = (items: Alert[], over: Partial<AlertList> = {}): AlertList => ({
  schema_version: "1.0", session_id: "s1", session_revision: 1, clock_at: "2000-01-03T10:00:00Z", rule_available: true,
  rule_description: null, items, ...over,
});

function profile(values: SessionProfile["values"], over: Partial<SessionProfile> = {}): SessionProfile {
  return { schema_version: "1.0", session_id: "s1", patient_id: "SYN-A", session_revision: 1, as_of: "2000-01-03T10:00:00Z",
    cohort: { label: "x" }, values, ...over } as SessionProfile;
}

describe("how the twin reached a forecast", () => {
  it("reports the forecast's own components and its final estimate, without re-adding them", () => {
    const f = forecast({
      personalization: { enabled: true, status: "active", policy_id: "p", state_version: 3, cap_mg_dl: 25, reset_gap_minutes: 180,
        horizons: [{ horizon_minutes: 30, matured_residuals: 40, min_required: 6, correction_mg_dl: 9.9, consumed_forecast_ids: [] }] },
      estimates: [{ horizon_minutes: 30, target_at: "2000-01-03T10:27:00Z", predicted_mg_dl: 171.4, lower_mg_dl: 150, upper_mg_dl: 190,
        interval_level: 0.8, interval_status: "calibrated", components: { population_mg_dl: 168.2, patient_correction_mg_dl: 3.2 } }],
    });
    const e = explainForecast(f, { cutoff: CUTOFF });
    expect(e.horizons).toEqual([{ horizon: 30, targetAt: "2000-01-03T10:27:00Z", population: 168.2, correction: 3.2, final: 171.4 }]);
    // the correction applied at issue time (3.2), not the twin's later state (9.9); the bound comes from the API
    expect(e.correction).toEqual({ status: "active", matured: [{ horizon: 30, n: 40, needed: 6 }], cap: 25, resetGap: 180 });
  });

  it("keeps a missing wearable summary missing and says which profile values the forecast could know", () => {
    const f = forecast({ model_version: "lightgbm.dyn-prof-v2.x", as_of: "2000-01-03T09:57:00Z",
      quality: { status: "degraded", reasons: [{ code: "activity_unavailable", message: "No wearable" }] } });
    const p = profile([
      { name: "age", label: "Age", value: 50, status: "available", available_at: "2000-01-01T00:00:00Z" },
      { name: "hba1c", label: "HbA1c", value: 8, status: "available", available_at: "2000-01-03T09:59:00Z" }, // after issue
      { name: "insulin", label: "Fasting insulin", value: null, status: "missing_in_source" },
    ] as SessionProfile["values"]);
    const e = explainForecast(f, { cutoff: CUTOFF, profile: p });
    expect(e.inputs.wearable).toBe("used_missing");
    expect(e.inputs.profile).toEqual({ use: "used", known: ["Age"], notYet: ["HbA1c"], missing: ["Fasting insulin"], context: [] });
    expect(e.inputs.glucose).toEqual({ value: 150, observedAt: "2000-01-03T09:57:00Z" });
  });

  it("does not read a profile from another revision, and says the profile is not an input of a dynamic-only model", () => {
    const dyn = forecast({ model_version: "synthetic-demo.lightgbm.dyn-v2.v1" });
    const p = profile([{ name: "age", label: "Age", value: 50, status: "available", available_at: "2000-01-01T00:00:00Z" }] as SessionProfile["values"]);
    expect(explainForecast(dyn, { cutoff: CUTOFF, profile: p }).inputs.profile?.use).toBe("not_input");
    expect(explainForecast(dyn, { cutoff: CUTOFF }).inputs.wearable).toBe("used");
    const fusion = forecast({ model_version: "lightgbm.dyn-prof-v2.x" });
    const other = profile(p.values, { session_revision: 2 });
    expect(explainForecast(fusion, { cutoff: CUTOFF, profile: other }).inputs.profile).toEqual({ use: "unknown", known: [], notYet: [], missing: [], context: [] });
  });

  it("counts warning outcomes as known at the cutoff, and only from this session revision", () => {
    const list = alerts([
      alert("a", "2000-01-03T06:00:00Z", { status: "onset_observed", onset_at: "2000-01-03T06:40:00Z", confirmed_at: "2000-01-03T06:55:00Z" }),
      alert("b", "2000-01-03T07:00:00Z", { status: "no_onset_observed", confirmed_at: "2000-01-03T09:00:00Z" }),
      alert("c", "2000-01-03T09:30:00Z", { status: "onset_observed", onset_at: "2000-01-03T09:55:00Z", confirmed_at: "2000-01-03T10:10:00Z" }),
      alert("d", "2000-01-03T08:00:00Z", { status: "unknown" }),
      alert("e", "2000-01-03T10:30:00Z", { status: "pending" }), // after the cutoff: not counted
    ]);
    expect(trackRecord(list, CUTOFF)).toEqual({ total: 4, onset: 1, falseAlarm: 1, pending: 1, unknown: 1 });
    expect(explainForecast(forecast(), { cutoff: CUTOFF, alerts: { ...list, session_revision: 2 } }).track).toBeNull();
  });

  it("uses measured coverage only for the exact model that issued the forecast", () => {
    const report = {
      status: "completed", experiment_id: "exp", protocol: { model_version: "lightgbm.dyn-prof-v2.x", intervals: { level: 0.8 } },
      forecast_results: [{ selected_for_serving: true, model_label: "lgbm", personalization: "adaptive" }],
      interval_results: [{ split: "test", model_label: "lgbm (adaptive)", horizon_minutes: 30, interval_level: 0.8,
        empirical_coverage: { value: 0.742 }, per_patient_coverage_min: 0.6, per_patient_coverage_max: 0.82 }],
    } as unknown as EvaluationReport;
    const same = explainForecast(forecast({ model_version: "lightgbm.dyn-prof-v2.x" }), { cutoff: CUTOFF, report });
    expect(same.coverage).toEqual({ target: 0.8, measured: [{ horizon: 30, coverage: 0.742 }], experiment: "exp" });
    const synthetic = explainForecast(forecast(), { cutoff: CUTOFF, report });
    expect(synthetic.coverage).toEqual({ target: 0.8, measured: null, experiment: null });
  });
});

describe("profile values the model reads", () => {
  it("lists only the issuing model's profile inputs as read and the rest as context", () => {
    const e = explainForecast(forecast({ model_version: "lightgbm.dyn-prof-v2.x", as_of: "2000-01-03T09:57:00Z" }), {
      cutoff: CUTOFF, profileInputs: ["age"], profile: profile([
        { name: "age", label: "Age", value: 50, status: "available", available_at: "2000-01-01T00:00:00Z" },
        { name: "weight", label: "Body weight", value: 80, status: "available", available_at: "2000-01-01T00:00:00Z" },
      ] as SessionProfile["values"]) });
    expect(e.inputs.profile?.known).toEqual(["Age"]);
    expect(e.inputs.profile?.context).toEqual(["Body weight"]);
  });
});
