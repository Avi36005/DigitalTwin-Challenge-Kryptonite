import { Table2, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  ErrorBar,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Forecast, ObservationEvent, ReplaySession } from "@/api/types";
import { hourTicks, observedSeries, outcomeFor, stableYMax, visibleAt } from "@/lib/chart";
import { fmtGlucose } from "@/lib/format";
import { hhmm, ms, replayTime } from "@/lib/time";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { Button } from "../ui";

const MIN = 60_000;
const INK = "#111827"; // observed glucose
const BLUE = "#2563EB"; // model forecasts
const AXIS_TEXT = "#475569";
const Y_MIN = 40;

type Pt = {
  t: number;
  v: number | null;
  kind: "observed" | "forecast" | "earlier" | "selected" | "meal";
  err?: [number, number];
  horizon?: number;
  origin?: number;
  target?: number;
  lower?: number | null;
  upper?: number | null;
  label?: string;
  forecastId?: string;
};

export function GlucoseChart({ session, events, latest, history, selected, onSelect, reduceMotion, eventsLoaded = true }: {
  session: ReplaySession;
  events: ObservationEvent[];
  latest: Forecast | null;
  history: Forecast[];
  selected: Forecast | null;
  onSelect: (f: Forecast | null) => void;
  reduceMotion: boolean;
  /** false while the released events of this session revision are still being fetched */
  eventsLoaded?: boolean;
}) {
  const [hours, setHours] = useState(6);
  const [earlier, setEarlier] = useState<0 | 30 | 60>(30);
  const [table, setTable] = useState(false);
  const phone = useMediaQuery("(max-width: 760px)");
  const clock = ms(session.clock_at);
  const from = clock - hours * 60 * MIN;
  const to = clock + 75 * MIN;

  const observed = useMemo(() => observedSeries(events, clock, from), [events, clock, from]);
  const meals: Pt[] = useMemo(
    () =>
      events
        .filter((e) => e.kind === "meal" && visibleAt(e, clock) && ms(e.observed_at) >= from)
        .map((e) => ({
          t: ms(e.observed_at), v: Y_MIN + 6, kind: "meal" as const,
          label: `${e.values.meal_type ?? "Meal"}${e.values.carbohydrate != null ? ` · ~${Math.round(e.values.carbohydrate as number)} g carbohydrate (estimated)` : ""} · logged ${replayTime(e.available_at)}`,
        })),
    [events, clock, from],
  );
  const forecastPts = (f: Forecast, kind: "forecast" | "selected"): Pt[] =>
    f.estimates
      .filter((e) => e.predicted_mg_dl !== null)
      .map((e) => ({
        t: ms(e.target_at), v: e.predicted_mg_dl, kind, horizon: e.horizon_minutes, origin: ms(f.as_of), target: ms(e.target_at),
        lower: e.lower_mg_dl, upper: e.upper_mg_dl, forecastId: f.forecast_id,
        err: e.lower_mg_dl != null && e.upper_mg_dl != null ? [e.predicted_mg_dl! - e.lower_mg_dl, e.upper_mg_dl - e.predicted_mg_dl!] : [0, 0],
      }));
  const latestPts = latest ? forecastPts(latest, "forecast") : [];
  const selectedPts = selected && selected.forecast_id !== latest?.forecast_id ? forecastPts(selected, "selected") : [];
  const earlierPts: Pt[] = useMemo(() => {
    if (!earlier) return [];
    return history
      .filter((f) => ms(f.as_of) <= clock && f.forecast_id !== latest?.forecast_id)
      .flatMap((f) => {
        const e = f.estimates.find((x) => x.horizon_minutes === earlier);
        if (!e || e.predicted_mg_dl === null) return [];
        const t = ms(e.target_at);
        if (t < from || t > to) return [];
        return [{ t, v: e.predicted_mg_dl, kind: "earlier" as const, horizon: earlier, origin: ms(f.as_of), target: t, forecastId: f.forecast_id }];
      });
  }, [history, earlier, clock, from, to, latest]);

  // y-range: never clips a real value, grows when needed, and does not shrink back on ordinary updates (no jumping axis)
  const peak = Math.max(0, ...[...observed, ...latestPts, ...selectedPts, ...earlierPts].map((p) => ("upper" in p && p.upper != null ? p.upper : p.v ?? 0)));
  const yStore = useRef<{ key: string; max: number }>({ key: "", max: 0 });
  const yMax = stableYMax(yStore.current, `${session.id}:${session.revision}:${hours}`, peak);
  const ticks = hourTicks(from, to, (hours <= 6 ? 1 : hours <= 12 ? 2 : 4) * (phone && hours > 3 ? 2 : 1));
  const lastObs = [...observed].reverse().find((p) => p.v !== null);
  const summary = lastObs
    ? `Observed glucose over the last ${hours} hours: ${observed.filter((p) => p.v !== null).length} readings, latest ${fmtGlucose(lastObs.v)} mg/dL at ${replayTime(lastObs.t)}.` +
      (latestPts.length ? ` Latest forecast: ${latestPts.map((p) => `${p.horizon}-minute ${fmtGlucose(p.v)} mg/dL`).join(", ")}.` : " No current forecast.")
    : "No glucose observations released in this window.";
  const anim = { isAnimationActive: false }; // charts never animate on polling updates
  void reduceMotion;

  return (
    <section className="chart" aria-labelledby="chart-title">
      <div className="chart__head">
        <div>
          <h2 className="chart__title" id="chart-title">Glucose trace</h2>
          <p className="chart__sub">mg/dL · replay time (source clock; timezone undocumented)</p>
        </div>
        <div className="chart__controls">
          <div className="seg" role="group" aria-label="Time window">
            {[3, 6, 12, 24].map((h) => (
              <button key={h} type="button" aria-pressed={hours === h} onClick={() => setHours(h)}>{h} h</button>
            ))}
          </div>
          <label className="visually-hidden" htmlFor="earlier-select">Earlier forecasts shown</label>
          <select id="earlier-select" className="select select--sm" value={earlier}
            onChange={(e) => setEarlier(Number(e.target.value) as 0 | 30 | 60)}>
            <option value={30}>Earlier 30-min forecasts</option>
            <option value={60}>Earlier 60-min forecasts</option>
            <option value={0}>Hide earlier forecasts</option>
          </select>
          <Button size="sm" variant="ghost" icon={Table2} aria-pressed={table} onClick={() => setTable((x) => !x)}>
            Table view
          </Button>
        </div>
      </div>

      <ul className="legend" aria-label="Chart legend">
        <li><span className="legend__key legend__key--obs" aria-hidden />Observed glucose</li>
        <li><span className="legend__key legend__key--fc" aria-hidden />Latest forecast, 30 and 60 min, with range</li>
        {earlier > 0 && <li><span className="legend__key legend__key--earlier" aria-hidden />Earlier {earlier}-min forecasts</li>}
        {selectedPts.length > 0 && <li><span className="legend__key legend__key--sel" aria-hidden />Selected earlier forecast</li>}
        <li><span className="legend__key legend__key--thr" aria-hidden />Research threshold 180 mg/dL</li>
        {meals.length > 0 && <li><span className="legend__key legend__key--meal" aria-hidden />Meal log (context only, not a model input)</li>}
      </ul>

      <p className="visually-hidden" aria-live="off">{summary}</p>

      {table ? (
        <ChartTable observed={observed} forecasts={[...latestPts, ...selectedPts]} meals={meals} />
      ) : (
        <figure className="chart__plot" aria-label={summary}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart margin={{ top: 24, right: 24, bottom: 2, left: 0 }}>
              <CartesianGrid vertical={false} stroke="#EEF0F3" />
              <XAxis dataKey="t" type="number" domain={[from, to]} ticks={ticks} tickFormatter={(t) => hhmm(t)}
                allowDataOverflow tick={{ fontSize: 12, fill: AXIS_TEXT }} stroke="#D1D5DB" tickLine={false} />
              <YAxis domain={[Y_MIN, yMax]} ticks={[70, 100, 140, 180, 250, 300, 350, 400].filter((v) => v <= yMax)}
                tick={{ fontSize: 12, fill: AXIS_TEXT }} stroke="#D1D5DB" tickLine={false} width={58}
                label={{ value: "mg/dL", angle: -90, position: "insideLeft", offset: 4, fill: AXIS_TEXT, fontSize: 12 }} />
              {hours <= 6 && (
                <ReferenceArea x1={clock} x2={to} fill="#FFFFFF" fillOpacity={0} ifOverflow="hidden"
                  label={{ value: "Forecasts", position: "insideTop", fill: AXIS_TEXT, fontSize: 11, offset: 8 }} />
              )}
              <ReferenceLine y={180} stroke="#D97706" strokeDasharray="5 5" strokeWidth={1.2}
                label={{ value: "Research threshold 180", position: "insideBottomLeft", fill: "#92400E", fontSize: 11 }} />
              <Line data={observed} dataKey="v" type="linear" stroke={INK} strokeWidth={2} dot={false}
                connectNulls={false} name="Observed" {...anim} />
              {earlierPts.length > 0 && (
                <Scatter data={earlierPts} dataKey="v" cursor="pointer" {...anim}
                  shape={(d: { cx?: number; cy?: number }) => (
                    <circle cx={d.cx} cy={d.cy} r={2.6} fill="#fff" stroke={BLUE} strokeOpacity={0.45} strokeWidth={1} />
                  )}
                  onClick={(d: { payload?: Pt }) => {
                    const id = d?.payload?.forecastId;
                    const f = history.find((x) => x.forecast_id === id);
                    if (f) onSelect(f);
                  }} />
              )}
              {selectedPts.length > 0 && (
                <ReferenceLine x={selectedPts[0].origin} stroke={BLUE} strokeDasharray="3 4" strokeOpacity={0.7}
                  label={{ value: "Selected forecast issued", position: "insideTopRight", fill: "#1D4ED8", fontSize: 11 }} />
              )}
              {selectedPts.length > 0 && (
                <Scatter data={selectedPts} dataKey="v" fill="#fff" stroke={BLUE} strokeWidth={2} shape="diamond" {...anim}>
                  <ErrorBar dataKey="err" direction="y" width={6} stroke={BLUE} strokeWidth={1.2} strokeDasharray="2 2" />
                </Scatter>
              )}
              {latestPts.length > 0 && (
                <Scatter data={latestPts} dataKey="v" fill={BLUE} {...anim}>
                  <ErrorBar dataKey="err" direction="y" width={8} stroke={BLUE} strokeWidth={1.5} />
                </Scatter>
              )}
              {meals.length > 0 && <Scatter data={meals} dataKey="v" fill="#A16207" shape="triangle" {...anim} />}
              <ReferenceLine x={clock} stroke={INK} strokeWidth={1.4}
                label={{ value: `Replay clock ${hhmm(clock)}`, position: "top", fill: INK, fontSize: 11, fontWeight: 600 }} />
              <RTooltip content={<ChartTip />} cursor={{ stroke: "#D1D5DB" }} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </figure>
      )}

      {selected && selected.forecast_id !== latest?.forecast_id && (
        <SelectedForecastNote f={selected} events={events} clock={clock} onClear={() => onSelect(null)} />
      )}
      {!eventsLoaded && (
        <p className="chart__hint" role="status">Loading released observations… the observed line appears when they arrive.</p>
      )}
      {eventsLoaded && !selected && earlier > 0 && earlierPts.length > 0 && !table && (
        <p className="chart__hint">Select an earlier forecast point to compare it with what was later observed, or use Table view.</p>
      )}
    </section>
  );
}

function ChartTip({ active, payload }: { active?: boolean; payload?: { payload: Pt }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as Pt;
  if (!p || p.v === null) return null;
  return (
    <div className="chart-tooltip">
      {p.kind === "meal" ? (
        <>
          <div className="chart-tooltip__k">Meal log · eaten {replayTime(p.t)}</div>
          <div>{p.label}</div>
        </>
      ) : p.kind === "observed" ? (
        <>
          <div className="chart-tooltip__k">Observed glucose</div>
          <div className="chart-tooltip__v num">{fmtGlucose(p.v)} mg/dL</div>
          <div className="chart-tooltip__k">{replayTime(p.t)}</div>
        </>
      ) : (
        <>
          <div className="chart-tooltip__k">{p.kind === "earlier" ? "Earlier" : p.kind === "selected" ? "Selected" : "Latest"} {p.horizon}-min forecast</div>
          <div className="chart-tooltip__v num">{fmtGlucose(p.v)} mg/dL</div>
          <div className="chart-tooltip__k">Issued {replayTime(p.origin ?? 0)} · for {replayTime(p.target ?? p.t)}</div>
          {p.lower != null && p.upper != null && (
            <div className="chart-tooltip__k">Range {fmtGlucose(p.lower)}–{fmtGlucose(p.upper)} mg/dL (target coverage 80%)</div>
          )}
        </>
      )}
    </div>
  );
}

function SelectedForecastNote({ f, events, clock, onClear }: { f: Forecast; events: ObservationEvent[]; clock: number; onClear: () => void }) {
  return (
    <div className="selected-note" role="region" aria-label="Selected earlier forecast">
      <div>
        <p className="selected-note__title">Earlier forecast issued {replayTime(f.as_of)} <span className="muted">(saved, unchanged since issue)</span></p>
        <ul className="facts">
          {f.estimates.map((e) => {
            const t = ms(e.target_at);
            const out = outcomeFor(events, t, clock);
            const pred = e.predicted_mg_dl;
            return (
              <li key={e.horizon_minutes}>
                {e.horizon_minutes}-min: predicted <strong className="num">{fmtGlucose(pred) ?? "—"} mg/dL</strong> for {replayTime(t)} —{" "}
                {t > clock ? <span className="muted">outcome not yet available at the replay clock</span>
                  : out && pred !== null ? <>observed <strong className="num">{fmtGlucose(out.values.value as number)} mg/dL</strong>
                      {" "}(error {(out.values.value as number) - pred >= 0 ? "+" : ""}{Math.round((out.values.value as number) - pred)} mg/dL)</>
                  : <span className="muted">no reading at the target time</span>}
              </li>
            );
          })}
        </ul>
      </div>
      <Button size="sm" variant="ghost" icon={X} onClick={onClear}>Back to latest</Button>
    </div>
  );
}

function ChartTable({ observed, forecasts, meals }: { observed: { t: number; v: number | null }[]; forecasts: Pt[]; meals: Pt[] }) {
  const rows = [
    ...observed.filter((p) => p.v !== null).map((p) => ({ t: p.t, what: "Observed glucose", v: `${fmtGlucose(p.v)} mg/dL`, note: "" })),
    ...forecasts.map((p) => ({ t: p.t, what: `${p.horizon}-min forecast${p.kind === "selected" ? " (selected earlier)" : ""}`,
      v: `${fmtGlucose(p.v)} mg/dL`,
      note: `${p.lower != null ? `range ${fmtGlucose(p.lower)}–${fmtGlucose(p.upper ?? null)} (target coverage 80%)` : "range unavailable"}; issued ${replayTime(p.origin ?? 0)}` })),
    ...meals.map((p) => ({ t: p.t, what: "Meal log (context only)", v: "", note: p.label ?? "" })),
  ].sort((a, b) => b.t - a.t);
  return (
    <div className="table-scroll chart__table">
      <table className="table">
        <caption className="visually-hidden">Observed glucose, forecasts and meal records in the chart window</caption>
        <thead><tr><th scope="col">Replay time</th><th scope="col">Series</th><th scope="col" className="num">Value</th><th scope="col">Notes</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}><td className="num">{replayTime(r.t)}</td><td>{r.what}</td><td className="num">{r.v}</td><td className="muted">{r.note}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
