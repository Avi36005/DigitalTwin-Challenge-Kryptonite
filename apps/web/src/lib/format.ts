export const fmtGlucose = (v: number | null | undefined) =>
  v === null || v === undefined || !Number.isFinite(v) ? null : Math.round(v).toString();

export const fmtNum = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : v.toFixed(digits);

export const fmtPct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

export function fmtProfileValue(value: number | string | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined || value === "") return "Not available";
  if (typeof value === "number") {
    const v = Number.isInteger(value) ? value.toString() : value.toFixed(1);
    return unit ? `${v} ${unit}` : v;
  }
  return value;
}

export function initials(alias: string): string {
  const m = alias.match(/(\d+|[A-Z])\s*$/);
  if (m) return m[1].slice(-2);
  return alias.slice(0, 2).toUpperCase();
}

export const modeLabel = (mode: string) =>
  mode === "synthetic_demo" ? "Synthetic demonstration" : "Recorded-data replay";
