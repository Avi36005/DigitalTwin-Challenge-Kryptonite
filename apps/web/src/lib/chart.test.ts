import { describe, expect, it } from "vitest";
import { forecast, glucose, meal } from "@/test/fixtures";
import { forecastUsable, latestGlucose, observedSeries, outcomeFor, visibleAt } from "./chart";
import { ms } from "./time";

const CLOCK = ms("2000-01-03T10:00:00Z");

describe("temporal visibility", () => {
  it("hides a meal observed earlier but logged after the replay clock", () => {
    const late = meal("m1", "2000-01-03T09:00:00Z", "2000-01-03T10:30:00Z");
    expect(visibleAt(late, CLOCK)).toBe(false);
    expect(visibleAt(late, ms("2000-01-03T10:30:00Z"))).toBe(true);
  });

  it("never shows readings observed after the clock", () => {
    const evs = [glucose("a", "2000-01-03T09:55:00Z", 120), glucose("b", "2000-01-03T10:05:00Z", 300)];
    expect(latestGlucose(evs, CLOCK)?.event_id).toBe("a");
    expect(observedSeries(evs, CLOCK, CLOCK - 3600_000).map((p) => p.v)).toEqual([120]);
  });

  it("keeps long gaps visibly missing instead of bridging them", () => {
    const evs = [glucose("a", "2000-01-03T09:00:00Z", 120), glucose("b", "2000-01-03T09:05:00Z", 125),
      glucose("c", "2000-01-03T09:45:00Z", 140)];
    const s = observedSeries(evs, CLOCK, CLOCK - 3 * 3600_000);
    expect(s.map((p) => p.v)).toEqual([120, 125, null, 140]);
  });

  it("reveals an outcome only once the target time has passed and its reading is available", () => {
    const evs = [glucose("t", "2000-01-03T10:27:00Z", 170)];
    const target = ms("2000-01-03T10:27:00Z");
    expect(outcomeFor(evs, target, CLOCK)).toBeNull();
    expect(outcomeFor(evs, target, ms("2000-01-03T10:30:00Z"))?.event_id).toBe("t");
  });

  it("rejects a forecast whose origin is after the replay clock (e.g. a late response after rewind)", () => {
    expect(forecastUsable(forecast({ as_of: "2000-01-03T11:00:00Z" }), CLOCK)).toBe(false);
    expect(forecastUsable(forecast(), CLOCK)).toBe(true);
  });
});
