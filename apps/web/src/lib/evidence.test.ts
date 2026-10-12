import { describe, expect, it } from "vitest";
import type { ModelResultRow } from "@/api/types";
import { defaultComparison, featureLabel, fmtLatency, fmtSigned, LABELS, pctLower, pipelineName, pipelines, POLICY, RESEARCH_LABELS, researchDefault, roleOf, selectionSummary } from "./evidence";
import { featureSetOf, modelUsesProfile } from "./forecast";
import { stableYMax } from "./chart";

const row = (label: string, family: string, feature: string, pers: ModelResultRow["personalization"], h: number, mae: number, selected = false): ModelResultRow => ({
  model_family: family, model_label: label, feature_set_id: feature, personalization: pers, split: "test", horizon_minutes: h,
  mae_mg_dl: { value: mae }, rmse_mg_dl: { value: mae * 1.4 }, n_patients: 14, n_origins: 7700, coverage_fraction: 0.999,
  selected_for_serving: selected,
});
const rows: ModelResultRow[] = [
  ...[30, 60].map((h) => row("lightgbm:dyn-v1", "lightgbm", "dyn-v1", "adaptive", h, h === 30 ? 13.32 : 21.2, true)),
  ...[30, 60].map((h) => row("persistence:cgm-only-v1", "persistence", "cgm-only-v1", "off", h, h === 30 ? 14.84 : 23.23)),
  ...[30, 60].map((h) => row("linear_trend:cgm-only-v1", "linear_trend", "cgm-only-v1", "off", h, 15)),
  ...[30, 60].map((h) => row("ridge:dyn-v1", "ridge", "dyn-v1", "off", h, 14)),
  ...[30, 60].map((h) => row("catboost:dyn-v1", "catboost", "dyn-v1", "adaptive", h, h === 30 ? 13.35 : 20.83)),
  ...[30, 60].map((h) => row("catboost:dyn-prof-v1", "catboost", "dyn-prof-v1", "adaptive", h, h === 30 ? 13.04 : 19.8)),
];

describe("evidence semantics", () => {
  it("names forecast availability as availability, never as coverage or accuracy", () => {
    expect(LABELS.availability).toBe("Forecast availability");
    expect(LABELS.availabilityHelp).toMatch(/Not accuracy/);
    expect(LABELS.rangeCoverage).toBe("Prediction-range coverage");
  });

  it("names both warning-rate denominators and the episode-start lead", () => {
    expect(LABELS.falseAlarmRate).toMatch(/eligible forecastable day/);
    expect(LABELS.warningRate).toMatch(/observed forecastable day/);
    expect(LABELS.episodeLead).toMatch(/Episode-start/);
  });

  it("chooses the default comparison by rule, not by score, and keeps a better candidate visible in the full list", () => {
    const all = pipelines(rows);
    const shown = defaultComparison(all).map((p) => p.label);
    expect(shown).toEqual(["lightgbm:dyn-v1", "persistence:cgm-only-v1", "linear_trend:cgm-only-v1", "ridge:dyn-v1", "catboost:dyn-v1"]);
    expect(all.map((p) => p.label)).toContain("catboost:dyn-prof-v1"); // better on test, still listed under all configurations
    const serving = all.find((p) => p.selected)!;
    expect(roleOf(all.find((p) => p.label === "catboost:dyn-v1")!, serving)).toBe("Comparable candidate");
    expect(roleOf(all.find((p) => p.label === "persistence:cgm-only-v1")!, serving)).toBe("Baseline");
  });

  it("names feature sets in plain words whatever their version", () => {
    expect(featureLabel("dyn-prof-v2")).toBe("dynamic + baseline profile");
    expect(featureLabel("dyn-v1")).toBe("dynamic glucose and activity");
    expect(pipelineName({ family: "lightgbm", feature: "dyn-v2", pers: "adaptive" })).toBe(
      "LightGBM, dynamic glucose and activity, with patient adaptation");
  });

  it("computes improvement from the report's values and never invents precision", () => {
    expect(pctLower(13.32, 14.84)?.toFixed(1)).toBe("10.2");
    expect(pctLower(null, 14.84)).toBeNull();
    expect(fmtLatency(0.0119)).toBe("<0.1 ms");
    expect(fmtLatency(3.284)).toBe("3.3 ms");
    expect(fmtLatency(null)).toBe("—");
  });

  it("reads the feature set from a model version to decide whether profile values are inputs", () => {
    expect(featureSetOf("lightgbm.dyn-v1.gt-primary-2026-10-11-v1")).toBe("dyn-v1");
    expect(modelUsesProfile("lightgbm.dyn-v1.gt-primary-2026-10-11-v1")).toBe(false);
    expect(modelUsesProfile("catboost.dyn-prof-v1.x")).toBe(true);
    expect(modelUsesProfile("something-else")).toBeNull();
  });
});

describe("chart y-range", () => {
  it("grows to include real extremes but does not shrink on ordinary updates", () => {
    const store = { key: "", max: 0 };
    expect(stableYMax(store, "s:1:6", 150)).toBe(260);
    expect(stableYMax(store, "s:1:6", 300)).toBe(320);
    expect(stableYMax(store, "s:1:6", 150)).toBe(320); // no jump back down
    expect(stableYMax(store, "s:2:6", 150)).toBe(260); // a new revision starts again
  });
});

describe("research evidence helpers", () => {
  it("picks the default comparison by rule, not by score", () => {
    const all = [
      { pipeline: "catboost:dyn-prof-v2", mode: "off" }, { pipeline: "persistence:-", mode: "off" },
      { pipeline: "selected", mode: "final" }, { pipeline: "best:catboost", mode: "final" },
      { pipeline: "v2_recipe:dyn-v2", mode: "v2_policy" },
    ];
    expect(researchDefault(all).map((x) => x.pipeline)).toEqual(["selected", "v2_recipe:dyn-v2", "persistence:-", "best:catboost"]);
  });

  it("states the false-alarm denominator and never calls recall accuracy", () => {
    expect(RESEARCH_LABELS.falseAlarmsObserved).toMatch(/observed forecastable day/);
    expect(RESEARCH_LABELS.recallHelp).toMatch(/Not overall accuracy/);
    expect(POLICY.primary).toMatch(/inner folds/);
  });

  it("formats signed differences with a true minus sign and summarises per-fold selections", () => {
    expect(fmtSigned(-0.4234)).toBe("−0.42");
    expect(fmtSigned(null)).toBe("—");
    const s = selectionSummary({ "outer-1": { selected: "a" }, "outer-2": { selected: "a" }, "outer-3": { selected: "b" }, final: { selected: "b" } });
    expect(s).toEqual([{ label: "a", folds: 2, of: 3 }, { label: "b", folds: 1, of: 3 }]);
  });
});
