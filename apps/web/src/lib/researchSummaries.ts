import type { ResearchFinding, ResearchSummaryItem } from "@/api/types";
import { fmtSigned } from "./evidence";
import { fmtNum, fmtPct } from "./format";

/** Words for the research run after the demo model was chosen. Every number comes from the saved summaries. */
export const TITLE: Record<string, string> = {
  "D-043": "Two hours ahead",
  "D-045": "Two hours ahead, independent cohort",
  "D-044": "Direct two-hour onset classifier",
  "D-046": "Ranges, earlier warning and the health record",
};

export const TAG: Record<ResearchFinding["verdict"], string> = {
  shown: "Shown",
  not_shown: "Not shown",
  negative: "Negative result",
};

/** How a tag was decided: only D-046 part C declared its claim rule before computing; the rest describe the interval. */
export const BASIS: Record<NonNullable<ResearchFinding["basis"]>, string> = {
  declared_rule: "Declared rule",
  display_heuristic: "How this page describes it",
};

/** A saved summary that exists but cannot be used is said so, never shown as "not run". */
export const UNREADABLE: Record<"malformed" | "incompatible", string> = {
  malformed: "The saved summary on this installation could not be read.",
  incompatible: "The saved summary on this installation does not match this experiment or this page's format.",
};

export function evaluatedOn(it: ResearchSummaryItem): string {
  const n = it.participants;
  if (it.evaluated_on === "independent_cohort")
    return `${n ?? "—"} ShanghaiT2DM people, an independent cohort, assessed once`;
  if (it.evaluated_on === "reanalysis_inspected")
    return `Re-analysis of saved predictions for the same ${n ?? "—"} already-inspected CGMacros people (internal validation)`;
  return n != null
    ? `${n} CGMacros people, each held out entirely once (internal validation)`
    : "CGMacros people held out entirely, same folds as D-043 (internal validation)";
}

/** "Opened once at 2026-10-20 09:35 UTC", with any re-opening. */
export function openedText(it: ResearchSummaryItem): string | null {
  const t = (s: string) => `${s.slice(0, 10)} ${s.slice(11, 16)} UTC`;
  if (!it.opened_at) return null;
  const re = it.reopened_at ?? [];
  return re.length ? `First opened at ${t(it.opened_at)}; re-opened at ${re.map(t).join(", ")} for a diagnostic`
    : `Opened once at ${t(it.opened_at)}`;
}

const ci = (f: ResearchFinding, digits = 2) =>
  f.ci95 ? `${fmtSigned(f.estimate, digits)} [${fmtSigned(f.ci95[0], digits)}, ${fmtSigned(f.ci95[1], digits)}]` : fmtSigned(f.estimate, digits);
const better = (f: ResearchFinding) => (f.better_for != null && f.n != null ? `, better for ${f.better_for} of ${f.n} people` : "");

/** What was tested and its headline result, worded from one finding. */
export function findingText(dec: string, f: ResearchFinding): { tested: string; result: string } {
  const v = f.values ?? {};
  switch (f.key) {
    case "forecast_120": {
      const d = dec === "D-045" ? 2 : 1;
      return {
        tested: dec === "D-045" ? "Two-hour forecast error on new people from another country" : "Two-hour forecast error",
        result: `MAE ${fmtNum(v.mae, d)} vs persistence ${fmtNum(v.persistence_mae, d)} mg/dL at 120 min: ${ci(f)}${better(f)}`,
      };
    }
    case "notice_120":
      return {
        tested: "Two hours of notice",
        result: `${v.detected} of ${v.onsets} onsets warned at ${fmtNum(v.false_alarms_per_day, 2)} false alarms per observed day, ` +
          `but median forecast lead ${fmtNum(v.lead_median, 0)} min (IQR ${fmtNum(v.lead_q1, 0)}–${fmtNum(v.lead_q3, 0)})`,
      };
    case "profile_inputs_120":
      return { tested: "Health-record inputs at 120 min", result: `LightGBM with minus without: ${ci(f)} mg/dL${better(f)}` };
    case "classifier":
      return {
        tested: "A classifier trained on the onset itself",
        result: `${v.detected} of ${v.onsets} onsets at ${fmtNum(v.false_alarms_per_day, 2)} false alarms per day only because it ` +
          `warned at ${fmtPct(v.share_time_warning)} of eligible times; ROC AUC ${fmtNum(v.roc_auc, 2)}. Not used`,
      };
    case "ranges_120": {
      const wider = v.width_after != null && v.width_before != null ? v.width_after - v.width_before : null;
      return {
        tested: "Prediction ranges calibrated on more people",
        result: `Coverage at 120 min ${fmtPct(v.before, 1)} → ${fmtPct(v.after, 1)} (target 80%); 60 min ` +
          `${fmtPct(v.before_60, 1)} → ${fmtPct(v.after_60, 1)}; ranges ${fmtNum(wider, 0)} mg/dL wider`,
      };
    }
    case "earlier_warning_120":
      return {
        tested: "Earlier two-hour warning",
        result: `${v.early_selected} vs ${v.early_incumbent} of ${v.onsets} onsets warned at least 30 min ahead: ${ci(f, 1)} points ` +
          `at the same alarm budget; median lead still ${fmtNum(v.lead_median, 0)} min`,
      };
    case "profile_prior_120":
      return {
        tested: "Health record as a new person's starting correction",
        result: `${ci(f)} mg/dL at 120 min${better(f)}; first 24 h ${fmtSigned(v.first_24h_estimate)} ` +
          `[${fmtSigned(v.first_24h_ci_low)}, ${fmtSigned(v.first_24h_ci_high)}]`,
      };
    default:
      return { tested: f.key, result: ci(f) };
  }
}
