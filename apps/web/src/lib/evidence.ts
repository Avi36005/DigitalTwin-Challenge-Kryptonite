/** Pure helpers for the model-evidence page. Every number comes from the evaluation report; nothing is typed in here. */
import type { ModelResultRow } from "@/api/types";

export const FAMILY: Record<string, string> = {
  persistence: "Persistence",
  linear_trend: "Linear trend",
  ridge: "Ridge",
  lightgbm: "LightGBM",
  catboost: "CatBoost",
};
export const FEATURES: Record<string, string> = {
  "cgm-only": "latest glucose only",
  dyn: "dynamic glucose and activity",
  "dyn-prof": "dynamic + baseline profile",
  "dyn-prof-meal": "dynamic + profile + meals (optimistic)",
};

/** Plain-language name of a feature set, independent of its version suffix ("dyn-prof-v2" → "dynamic + baseline profile"). */
export function featureLabel(featureSetId: string): string {
  return FEATURES[featureSetId.replace(/-v\d+$/, "")] ?? featureSetId;
}
export const PERSONALIZATION: Record<string, string> = {
  off: "population only",
  adaptive: "with patient adaptation",
  frozen_state: "frozen adaptation state",
};

/** Column and metric names used on the page. Kept here so their meaning is tested, not just their styling. */
export const LABELS = {
  mae: "Mean absolute error",
  maeHelp: "Average prediction error; lower is better. Participants are weighted equally.",
  availability: "Forecast availability",
  availabilityHelp: "Share of forecast times with an observed target at which a forecast was issued. Not accuracy.",
  rangeCoverage: "Prediction-range coverage",
  latency: "Batch model inference per 1,000 forecasts",
  latencyHelp: "Measured offline on the recorded environment; not end-to-end app response time.",
  falseAlarmRate: "False alarms per eligible forecastable day",
  warningRate: "Warnings per observed forecastable day",
  falseAlarmRateObserved: "False alarms per observed forecastable day",
  warningRateEligible: "Warnings per eligible forecastable day",
  episodeLead: "Episode-start-to-onset time (median)",
  qualifiedLead: "Qualified forecast lead (median)",
  qualifiedLeadHelp: "Onset minus the earliest warning whose own forecast horizon contains the onset; never more than the horizon.",
} as const;

export type Pipeline = {
  key: string;
  label: string;
  family: string;
  feature: string;
  pers: string;
  selected: boolean;
  h30?: ModelResultRow;
  h60?: ModelResultRow;
};

export function pipelines(rows: ModelResultRow[]): Pipeline[] {
  const map = new Map<string, Pipeline>();
  for (const r of rows) {
    const key = `${r.model_label}|${r.personalization}`;
    const g = map.get(key) ?? { key, label: r.model_label, family: r.model_family, feature: r.feature_set_id, pers: r.personalization, selected: false };
    if (r.horizon_minutes === 30) g.h30 = r;
    if (r.horizon_minutes === 60) g.h60 = r;
    g.selected = g.selected || !!r.selected_for_serving;
    map.set(key, g);
  }
  return Array.from(map.values());
}

export function pipelineName(p: Pick<Pipeline, "family" | "feature" | "pers">): string {
  const fam = FAMILY[p.family] ?? p.family;
  if (p.family === "persistence") return "Persistence — repeat the latest reading";
  if (p.family === "linear_trend") return "Linear trend — extend the recent slope";
  return `${fam}, ${featureLabel(p.feature)}, ${PERSONALIZATION[p.pers] ?? p.pers}`;
}

export type Role = "Serving pipeline" | "Baseline" | "Comparable candidate" | "Candidate";

export function roleOf(p: Pipeline, serving: Pipeline | undefined): Role {
  if (p.selected) return "Serving pipeline";
  if (p.family === "persistence" || p.family === "linear_trend" || p.family === "ridge") return "Baseline";
  if (serving && p.feature === serving.feature && p.pers === serving.pers && p.family !== serving.family) return "Comparable candidate";
  return "Candidate";
}

/**
 * Default comparison: the serving pipeline, the baselines (persistence, linear trend, ridge on the serving feature set)
 * and the closest comparable candidate (another family on the same features and personalization). Chosen by rule, never
 * by score, so a candidate that beats the serving model is not hidden; every row stays one click away.
 */
export function defaultComparison(all: Pipeline[]): Pipeline[] {
  const serving = all.find((p) => p.selected);
  const pick = (f: (p: Pipeline) => boolean) => all.find(f);
  const out = [
    serving,
    pick((p) => p.family === "persistence"),
    pick((p) => p.family === "linear_trend"),
    pick((p) => p.family === "ridge" && p.feature === serving?.feature) ?? pick((p) => p.family === "ridge"),
    serving && pick((p) => roleOf(p, serving) === "Comparable candidate"),
  ];
  return out.filter((p, i): p is Pipeline => !!p && out.indexOf(p) === i);
}

/** Percentage by which `a` is lower than `b` (positive = lower error), from the report's unrounded values. */
export function pctLower(a: number | null | undefined, b: number | null | undefined): number | null {
  if (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b) || b === 0) return null;
  return ((b - a) / b) * 100;
}

/** Latency with honest precision: a measured 0.01 ms is "<0.1 ms", never "0.0 ms". */
export function fmtLatency(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v < 0.1) return "<0.1 ms";
  return `${v.toFixed(1)} ms`;
}

/* ------------------------------------------------------------------ research experiments (nested + external) */

export const REGIME: Record<string, string> = {
  serving_retrospective: "Corrected retrospective · serving evidence",
  nested_research: "New participants · internal nested + external",
  superseded_original: "Original · superseded",
};

export const RESEARCH_LABELS = {
  falseAlarmsObserved: "False alarms per observed forecastable day",
  falseAlarmsObservedHelp:
    "Denominator: non-overlapping, gap-respecting time with an issued forecast (each origin counts at most 5 minutes).",
  falseAlarmsEligible: "per eligible uncensored day",
  recall: "Event recall",
  recallHelp: "Share of assessable new high-glucose onsets that a warning preceded. Not overall accuracy.",
  precision: "Warning precision",
  precisionHelp: "Share of assessable warning episodes matched to an onset; censored warnings are excluded.",
  coverageTarget: "Target level",
  coverageMeasured: "Measured coverage",
  highGlucose: "MAE when target > 180",
} as const;

export const POLICY: Record<string, string> = {
  primary: "≤ 2 false alarms per observed day (primary, chosen on inner folds)",
  f1_comparator: "Highest event F1 (v1/v2 rule)",
  v2_fixed: "v2 margin −30 mg/dL",
  "budget_0.5": "≤ 0.5 per day (sensitivity)",
  "budget_1.0": "≤ 1 per day (sensitivity)",
  "budget_3.0": "≤ 3 per day (sensitivity)",
};

type RP = { pipeline: string; mode: string };

/**
 * Default research comparison, chosen by rule (never by score): the per-fold selected pipeline, the current v2 recipe
 * refit per fold, persistence and the best pipeline of each tree configuration. Everything else stays one click away.
 */
export function researchDefault<T extends RP>(all: T[]): T[] {
  const want: [string, string][] = [["selected", "final"], ["v2_recipe:dyn-v2", "v2_policy"], ["persistence:-", "off"],
    ["best:lightgbm_l2", "final"], ["best:lightgbm_l1", "final"], ["best:catboost", "final"]];
  return want.map(([p, m]) => all.find((x) => x.pipeline === p && x.mode === m)).filter((x): x is T => !!x);
}

/** Signed mg/dL difference with a true minus sign ("−0.42"), or an em dash when missing. */
export function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}`;
}

/** "3 of 5 folds" style summary of which pipeline the declared rule chose per outer fold (the final fit excluded). */
export function selectionSummary(byFold: Record<string, { selected?: string }>): { label: string; folds: number; of: number }[] {
  const outer = Object.entries(byFold).filter(([f]) => f !== "final");
  const counts = new Map<string, number>();
  for (const [, v] of outer) if (v.selected) counts.set(v.selected, (counts.get(v.selected) ?? 0) + 1);
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]).map(([label, folds]) => ({ label, folds, of: outer.length }));
}
