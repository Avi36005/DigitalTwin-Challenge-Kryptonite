/** Pure helpers for temporal integrity in the chart and summaries (unit-tested). */
import type { Forecast, ObservationEvent } from "@/api/types";
import { ms } from "./time";

export const GAP_MINUTES = 15;
const MIN = 60_000;

/** An observation may be shown only when it was observed AND available no later than the replay clock. */
export function visibleAt(e: Pick<ObservationEvent, "observed_at" | "available_at">, clock: number): boolean {
  return ms(e.observed_at) <= clock && ms(e.available_at) <= clock;
}

export interface ObsPoint {
  t: number;
  v: number | null;
  id?: string;
  kind: "observed";
}

/** Observed glucose within [from, clock], with explicit null breaks across gaps > GAP_MINUTES. */
export function observedSeries(events: ObservationEvent[], clock: number, from: number): ObsPoint[] {
  const pts = events
    .filter((e) => e.kind === "glucose" && visibleAt(e, clock))
    .map((e) => ({ t: ms(e.observed_at), v: e.values.value as number | null, id: e.event_id }))
    .filter((p) => p.t >= from - GAP_MINUTES * MIN && typeof p.v === "number")
    .sort((a, b) => a.t - b.t);
  const out: ObsPoint[] = [];
  for (let i = 0; i < pts.length; i++) {
    if (i > 0 && pts[i].t - pts[i - 1].t > GAP_MINUTES * MIN) {
      out.push({ t: (pts[i].t + pts[i - 1].t) / 2, v: null, kind: "observed" }); // keep the gap visible
    }
    out.push({ ...pts[i], kind: "observed" });
  }
  return out;
}

export function latestGlucose(events: ObservationEvent[], clock: number): ObservationEvent | null {
  let best: ObservationEvent | null = null;
  for (const e of events) {
    if (e.kind !== "glucose" || !visibleAt(e, clock)) continue;
    if (!best || ms(e.observed_at) > ms(best.observed_at)) best = e;
  }
  return best;
}

/** Nearest available reading within ±tol minutes of target, only if released by the clock. */
export function outcomeFor(events: ObservationEvent[], target: number, clock: number, tolMin = 2.5) {
  if (target > clock) return null;
  let best: ObservationEvent | null = null;
  let bestD = Infinity;
  for (const e of events) {
    if (e.kind !== "glucose" || !visibleAt(e, clock)) continue;
    const d = Math.abs(ms(e.observed_at) - target);
    if (d <= tolMin * MIN && d < bestD) {
      best = e;
      bestD = d;
    }
  }
  return best;
}

/** Change over ~15 minutes computed from actual released readings (null if no matching reading). */
export function trendFrom(events: ObservationEvent[], clock: number, lagMin = 15) {
  const last = latestGlucose(events, clock);
  if (!last) return null;
  const prev = outcomeFor(events, ms(last.observed_at) - lagMin * MIN, clock);
  if (!prev) return null;
  const delta = (last.values.value as number) - (prev.values.value as number);
  return { delta, minutes: (ms(last.observed_at) - ms(prev.observed_at)) / MIN };
}

/** Forecasts whose origin is after the clock are never displayed (synchronization guard). */
export function forecastUsable(f: Forecast | null | undefined, clock: number): f is Forecast {
  return !!f && ms(f.as_of) <= clock;
}

export function hourTicks(from: number, to: number, everyH: number): number[] {
  const step = everyH * 60 * MIN;
  const first = Math.ceil(from / step) * step;
  const out: number[] = [];
  for (let t = first; t <= to; t += step) out.push(t);
  return out;
}

/**
 * Upper y-limit that grows to include every real value (nothing is clipped) but does not shrink back while the same
 * session revision and time window are shown, so ordinary updates never make the axis jump. `store` persists across
 * renders (a ref); a new key (session, revision or window) starts again from the data.
 */
export function stableYMax(store: { key: string; max: number }, key: string, peak: number, floor = 260): number {
  const needed = Math.max(floor, Math.ceil((peak + 20) / 20) * 20);
  if (store.key !== key) {
    store.key = key;
    store.max = needed;
  } else if (needed > store.max) store.max = needed;
  return store.max;
}
