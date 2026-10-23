import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import type { Forecast } from "@/api/types";
import { forecast, glucose } from "@/test/fixtures";
import { ms } from "@/lib/time";
import { ForecastDetail } from "./ForecastDetail";

// jsdom has no modal <dialog>: open/close by the attribute, as the Dialog primitive's own fallback does
beforeAll(() => {
  const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
  if (typeof proto.showModal !== "function") proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
  if (typeof proto.close !== "function") {
    proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); };
  }
});

// issued 09:57 with targets 10:27 (30 min) and 10:57 (60 min)
const heading = (f: Forecast, events: ReturnType<typeof glucose>[], clock: string) => {
  render(<ForecastDetail f={f} open onClose={() => {}} events={events} clock={ms(clock)} />);
  return screen.getByRole("region", { name: "Outcome" }).querySelector(".outcome-state") as HTMLElement;
};
const at30 = glucose("g30", "2000-01-03T10:28:00Z", 171);
const at60 = glucose("g60", "2000-01-03T10:56:00Z", 176);

describe("forecast outcome heading", () => {
  it("is pending with due times while no target time has passed", () => {
    const h = heading(forecast(), [at30, at60], "2000-01-03T10:10:00Z");
    expect(h).toHaveAttribute("data-state", "pending");
    expect(h).toHaveTextContent("Pending · No outcome is observed yet at this replay time (30 min, due 10:27; 60 min, due 10:57).");
  });

  it("never says partly observed when nothing is observed: a sensor gap at 30 min while 60 min is pending", () => {
    const h = heading(forecast(), [], "2000-01-03T10:40:00Z");
    expect(h).toHaveAttribute("data-state", "pending");
    expect(h).not.toHaveTextContent(/Partly observed|0 of 2/);
    expect(h).toHaveTextContent(
      "Pending · No outcome is observed yet at this replay time. No reading near the 30-minute target (10:27), so that outcome is unknown. Still pending: 60 min, due 10:57.");
    // the per-horizon lines keep their own facts
    const region = screen.getByRole("region", { name: "Outcome" });
    expect(region).toHaveTextContent("30 min (for 10:27): No reading near the target time — outcome unknown.");
    expect(region).toHaveTextContent("60 min (for 10:57): Outcome not yet observed at this replay time.");
  });

  it("is partly observed only with at least one observed horizon", () => {
    const h = heading(forecast(), [at30], "2000-01-03T10:40:00Z");
    expect(h).toHaveAttribute("data-state", "partial");
    expect(h).toHaveTextContent("Partly observed · 1 of 2 horizons observed; still pending: 60 min, due 10:57.");
  });

  it("keeps an unavailable outcome visible when the rest are observed and none are pending", () => {
    const h = heading(forecast(), [at30], "2000-01-03T11:10:00Z");
    expect(h).toHaveAttribute("data-state", "mixed");
    expect(h).toHaveTextContent("Some outcomes observed · 1 of 2 horizons observed. No reading near the 60-minute target (10:57), so that outcome is unknown.");
  });

  it("is observed only when every horizon has a reading", () => {
    expect(heading(forecast(), [at30, at60], "2000-01-03T11:10:00Z")).toHaveTextContent(
      "Observed · Every horizon has an observed reading at this replay time.");
  });

  it("says outcome unknown without 'either' wording", () => {
    expect(heading(forecast(), [], "2000-01-03T11:10:00Z")).toHaveTextContent("Outcome unknown · No reading near any target time (sensor gap).");
  });

  it("uses singular wording for a forecast with one horizon", () => {
    const one = forecast();
    one.estimates = one.estimates.slice(0, 1);
    expect(heading(one, [], "2000-01-03T11:10:00Z")).toHaveTextContent("Outcome unknown · No reading near the target time (sensor gap).");
  });

  it("handles an abstained forecast with no estimates without '0 of 0'", () => {
    const h = heading(forecast({ estimates: [] }), [], "2000-01-03T11:10:00Z");
    expect(h).toHaveTextContent("No outcome · This forecast has no horizon estimates to compare with a reading.");
    expect(h).not.toHaveTextContent(/0 of 0/);
  });
});
