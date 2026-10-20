/**
 * What happened after a saved forecast, judged at the replay clock: the observed reading matched to each horizon's target
 * time and how far the saved final and population forecasts were from it. Only saved forecast fields and readings the
 * clock has released are used; the forecast is never recomputed, and nothing is said about why the error arose.
 */
import type { HorizonEstimate, ObservationEvent } from "@/api/types";
import { outcomeFor } from "./chart";
import { ms } from "./time";

/** Matching window around t + h, in minutes: `match_tolerance_minutes` of configs/experiment.yaml (5-minute data). */
export const OUTCOME_TOLERANCE_MIN = 2.5;
/** Below this difference in absolute error the patient correction is said to have made no difference. */
export const NO_DIFFERENCE_MG_DL = 0.5;

export type HorizonOutcome =
  | { state: "pending" }
  | { state: "unknown" }
  | {
    state: "observed";
    observed: number;
    observedAt: string;
    /** saved final forecast minus the observed reading */
    finalError: number | null;
    /** saved population forecast minus the observed reading */
    populationError: number | null;
    /** how the saved patient correction changed the absolute error; null without a correction or population value */
    correction: { effect: "closer" | "further" | "none"; by: number } | null;
  };

export function horizonOutcome(e: HorizonEstimate, events: ObservationEvent[], clock: number): HorizonOutcome {
  const target = ms(e.target_at);
  if (target > clock) return { state: "pending" };
  const hit = outcomeFor(events, target, clock, OUTCOME_TOLERANCE_MIN);
  if (!hit) {
    // a matching reading may still be released within the tolerance window after the target time
    return clock < target + OUTCOME_TOLERANCE_MIN * 60_000 ? { state: "pending" } : { state: "unknown" };
  }
  const observed = hit.values.value as number;
  const finalError = e.predicted_mg_dl == null ? null : e.predicted_mg_dl - observed;
  const pop = e.components?.population_mg_dl;
  const populationError = pop == null ? null : pop - observed;
  let correction: { effect: "closer" | "further" | "none"; by: number } | null = null;
  if (finalError != null && populationError != null && e.components?.patient_correction_mg_dl != null) {
    const d = Math.abs(populationError) - Math.abs(finalError);
    correction = Math.abs(d) < NO_DIFFERENCE_MG_DL ? { effect: "none", by: Math.abs(d) }
      : { effect: d > 0 ? "closer" : "further", by: Math.abs(d) };
  }
  return { state: "observed", observed, observedAt: hit.observed_at, finalError, populationError, correction };
}
