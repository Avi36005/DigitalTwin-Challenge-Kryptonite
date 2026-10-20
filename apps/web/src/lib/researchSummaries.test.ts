import { describe, expect, it } from "vitest";
import { researchSummaries } from "@/test/researchSummaries";
import { evaluatedOn, findingText, openedText } from "./researchSummaries";

const item = (dec: string) => researchSummaries.items.find((x) => x.decision_id === dec)!;
const text = (dec: string, key: string) => findingText(dec, item(dec).findings!.find((f) => f.key === key)!);

describe("research summaries wording", () => {
  it("states the re-analysis results exactly as the saved summary has them", () => {
    expect(text("D-046", "ranges_120").result).toContain("Coverage at 120 min 76.5% → 79.8% (target 80%)");
    expect(text("D-046", "earlier_warning_120").result).toContain("+0.9 [−5.5, +6.6] points");
    expect(text("D-046", "profile_prior_120").result).toContain("−0.53 [−1.57, +0.58] mg/dL at 120 min");
    expect(evaluatedOn(item("D-046"))).toMatch(/already-inspected/);
  });

  it("keeps the two-hour notice, the external cohort and the rejected classifier honest", () => {
    expect(text("D-043", "forecast_120").result).toBe(
      "MAE 30.6 vs persistence 35.9 mg/dL at 120 min: −5.25 [−6.44, −4.05], better for 14 of 14 people");
    expect(text("D-043", "notice_120").result).toContain("median forecast lead 15 min (IQR 5–65)");
    expect(text("D-045", "forecast_120").result).toContain("29.55 vs persistence 31.68 mg/dL at 120 min: −2.12 [−2.67, −1.53], better for 78 of 98");
    expect(text("D-044", "classifier").result).toContain("warned at 99% of eligible times; ROC AUC 0.64");
    expect(openedText(item("D-044"))).toBe("First opened at 2026-10-20 09:57 UTC; re-opened at 2026-10-20 09:58 UTC for a diagnostic");
  });
});
