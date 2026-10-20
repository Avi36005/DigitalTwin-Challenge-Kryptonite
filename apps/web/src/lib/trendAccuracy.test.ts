import { describe, expect, it } from "vitest";
import type { EvaluationReport, Forecast } from "@/api/types";
import { trendAccuracy } from "./explain";

const rows = [
  { horizon: 60, trend: "all", label: "All origins", slope_min: null, slope_max: null, mae_macro: 20.9, origins: 3766, participants: 14, mean_signed_error_target_above_180: -16.9 },
  { horizon: 60, trend: "steady", label: "Steady (within ±1 mg/dL/min)", slope_min: -1, slope_max: 1, mae_macro: 19.5, origins: 2947, participants: 14, mean_signed_error_target_above_180: null },
  { horizon: 60, trend: "rising_fast", label: "Rising > 2 mg/dL/min", slope_min: 2, slope_max: null, mae_macro: 35.3, origins: 138, participants: 12, mean_signed_error_target_above_180: null, range_coverage: 0.46 },
] as const;
const report = { experiment_id: "exp", error_by_trend: { model_version: "m-1", pipeline: "p", personalization: "adaptive", segment: "validation", trend_feature: "slope_15", min_participants: 3, rows } } as unknown as EvaluationReport;
const fc = (slope: number | null, model = "m-1") => ({ glucose_trend_mg_dl_per_min: slope, model_version: model }) as unknown as Forecast;

describe("trendAccuracy", () => {
  it("reads the stratum of the forecast's own trend for the exact model", () => {
    const t = trendAccuracy(fc(2.4), report)!;
    expect(t.label).toBe("Rising > 2 mg/dL/min");
    expect(t.byHorizon).toEqual([{ horizon: 60, mae: 35.3, steadyMae: 19.5, origins: 138, rangeCoverage: 0.46 }]);
    expect(t.peakBias60).toBe(-16.9);
  });
  it("is null for another model version, a missing trend or no saved trend errors", () => {
    expect(trendAccuracy(fc(2.4, "m-2"), report)).toBeNull();
    expect(trendAccuracy(fc(null), report)).toBeNull();
    expect(trendAccuracy(fc(2.4), { ...report, error_by_trend: null } as EvaluationReport)).toBeNull();
  });
  it("uses exclusive lower and inclusive upper bounds", () => {
    expect(trendAccuracy(fc(1), report)!.steady).toBe(true);
    expect(trendAccuracy(fc(2), report)).toBeNull(); // 2.0 falls in "rising 1–2", which this fixture omits
  });
});
