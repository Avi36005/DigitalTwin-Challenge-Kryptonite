import { describe, expect, it } from "vitest";
import type { HorizonEstimate } from "@/api/types";
import { glucose } from "@/test/fixtures";
import { horizonOutcome } from "./outcome";
import { ms } from "./time";

const est = (over: Partial<HorizonEstimate> = {}): HorizonEstimate => ({
  horizon_minutes: 30, target_at: "2000-01-03T10:30:00Z", predicted_mg_dl: 170,
  components: { population_mg_dl: 180, patient_correction_mg_dl: -10 }, ...over,
}) as HorizonEstimate;
const reading = glucose("g1", "2000-01-03T10:31:00Z", 168);

describe("horizonOutcome", () => {
  it("is pending before the target time, even when a later reading exists in the list", () => {
    expect(horizonOutcome(est(), [reading], ms("2000-01-03T10:20:00Z"))).toEqual({ state: "pending" });
  });

  it("matches the observed reading within 2.5 minutes and reports both errors", () => {
    const o = horizonOutcome(est(), [reading], ms("2000-01-03T10:40:00Z"));
    expect(o).toMatchObject({ state: "observed", observed: 168, observedAt: "2000-01-03T10:31:00Z", finalError: 2, populationError: 12 });
  });

  it("says the correction moved the forecast closer, further or made no difference", () => {
    const at = ms("2000-01-03T10:40:00Z");
    expect(horizonOutcome(est(), [reading], at)).toMatchObject({ correction: { effect: "closer", by: 10 } });
    const hurt = est({ predicted_mg_dl: 150, components: { population_mg_dl: 165, patient_correction_mg_dl: -15 } });
    expect(horizonOutcome(hurt, [reading], at)).toMatchObject({ correction: { effect: "further", by: 15 } });
    const same = est({ predicted_mg_dl: 168.2, components: { population_mg_dl: 167.9, patient_correction_mg_dl: 0.3 } });
    expect(horizonOutcome(same, [reading], at)).toMatchObject({ correction: { effect: "none" } });
    const noCorr = est({ components: { population_mg_dl: 170, patient_correction_mg_dl: null } as HorizonEstimate["components"] });
    expect(horizonOutcome(noCorr, [reading], at)).toMatchObject({ correction: null });
  });

  it("is unknown when no reading lies near the target (a gap), but pending while one could still arrive", () => {
    const far = glucose("g2", "2000-01-03T10:45:00Z", 150);
    expect(horizonOutcome(est(), [far], ms("2000-01-03T10:31:00Z"))).toEqual({ state: "pending" });
    expect(horizonOutcome(est(), [far], ms("2000-01-03T11:00:00Z"))).toEqual({ state: "unknown" });
  });

  it("follows the replay clock after a rewind: a reading not yet released is not used", () => {
    const late = glucose("g3", "2000-01-03T10:31:00Z", 168, "2000-01-03T10:50:00Z"); // available 19 min later
    expect(horizonOutcome(est(), [late], ms("2000-01-03T10:40:00Z"))).toEqual({ state: "unknown" });
    expect(horizonOutcome(est(), [late], ms("2000-01-03T10:55:00Z"))).toMatchObject({ state: "observed" });
    expect(horizonOutcome(est(), [late], ms("2000-01-03T10:25:00Z"))).toEqual({ state: "pending" });
  });
});
