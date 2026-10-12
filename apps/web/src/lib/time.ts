/**
 * Replay time formatting. Replay timestamps use a declared synthetic UTC timeline (study day 1 =
 * 2000-01-03). They are formatted in UTC as "Day N · HH:MM" — never converted to the viewer's local
 * timezone, and never presented as a verified Indian clock.
 */
const DAY1 = Date.UTC(2000, 0, 3);
const MIN = 60_000;

export const ms = (iso: string | null | undefined): number => (iso ? Date.parse(iso) : NaN);

export function replayDay(t: number): number {
  return Math.floor((t - DAY1) / (24 * 60 * MIN)) + 1;
}

export function hhmm(t: number): string {
  const d = new Date(t);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

export function replayTime(iso: string | number | null | undefined, opts: { day?: boolean } = {}): string {
  const t = typeof iso === "number" ? iso : ms(iso ?? null);
  if (!Number.isFinite(t)) return "—";
  return opts.day === false ? hhmm(t) : `Day ${replayDay(t)} · ${hhmm(t)}`;
}

export function minutesBetween(a: string | number, b: string | number): number {
  const ta = typeof a === "number" ? a : ms(a);
  const tb = typeof b === "number" ? b : ms(b);
  return (tb - ta) / MIN;
}

export function durationLabel(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return "—";
  const m = Math.round(minutes);
  if (Math.abs(m) < 60) return `${m} min`;
  const h = Math.floor(Math.abs(m) / 60);
  const r = Math.abs(m) % 60;
  return `${m < 0 ? "-" : ""}${h} h${r ? ` ${r} min` : ""}`;
}

/** Wall-clock (real) time for session creation; shown in the viewer's locale, clearly labelled. */
export function wallTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const STEP_MIN = 5;
export const toIso = (t: number) => new Date(t).toISOString().replace(".000Z", "Z");
