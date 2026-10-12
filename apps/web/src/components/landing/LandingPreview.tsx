import preview from "@/content/landing-preview.json";
import { hhmm, ms, replayTime } from "@/lib/time";
import { useMediaQuery } from "@/lib/useMediaQuery";

/**
 * Static, read-only preview for the landing page. The data is one genuine synthetic-demonstration snapshot captured by
 * scripts/landing_preview.py (fictional participant, synthetic demonstration model). It renders without the API, creates
 * no session and contains no controls. Two forecast endpoints are drawn as points with range whiskers — no curve is
 * invented between them.
 */
const PAD = { l: 44, r: 20, t: 22, b: 30 };
const MIN = 60_000;

export function LandingPreview() {
  // a narrower drawing on phones keeps axis text readable instead of scaling a wide chart down
  const narrow = useMediaQuery("(max-width: 600px)");
  const W = narrow ? 360 : 560;
  const H = narrow ? 260 : 300;
  const clock = ms(preview.clock_at);
  const from = clock - 3 * 60 * MIN;
  const to = clock + 70 * MIN;
  const obs = preview.observed.map((p) => ({ t: ms(p.t), v: p.v }));
  const fc = preview.forecasts.map((f) => ({ ...f, t: ms(f.target_at) }));
  const values = [...obs.map((p) => p.v), ...fc.flatMap((f) => [f.lower ?? f.value, f.upper ?? f.value])];
  const y0 = Math.floor((Math.min(...values) - 15) / 20) * 20;
  const y1 = Math.ceil((Math.max(...values) + 15) / 20) * 20;
  const x = (t: number) => PAD.l + ((t - from) / (to - from)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - y0) / (y1 - y0)) * (H - PAD.t - PAD.b);
  const yTicks = Array.from({ length: Math.floor((y1 - y0) / 40) + 1 }, (_, i) => y0 + i * 40).filter((v) => v <= y1);
  const hourTicks: number[] = [];
  for (let t = Math.ceil(from / (60 * MIN)) * 60 * MIN; t <= to; t += 60 * MIN) hourTicks.push(t);
  const path = obs.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const last = obs[obs.length - 1];
  const level = Math.round((fc[0]?.interval_level ?? 0.8) * 100);
  const alt =
    `Preview of the replay chart for ${preview.participant}, a synthetic demonstration with fictional data. ` +
    `Observed glucose over the three hours before the replay clock (${replayTime(clock)}), latest ${Math.round(last.v)} mg/dL; ` +
    `forecasts issued at the clock: ${fc.map((f) => `${f.horizon} minutes ahead ${Math.round(f.value)} mg/dL (range ${Math.round(f.lower ?? f.value)}–${Math.round(f.upper ?? f.value)})`).join(", ")}.`;

  return (
    <figure className="preview">
      <div className="preview__head">
        <div>
          <p className="preview__title">{preview.participant}</p>
          <p className="preview__sub">Synthetic demonstration · fictional data · replay time</p>
        </div>
        <div className="preview__now">
          <span className="preview__now-label">Observed {hhmm(last.t)}</span>
          <span className="preview__now-value num">{Math.round(last.v)}<span> mg/dL</span></span>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="preview__svg" role="img" aria-label={alt}>
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="#EEF0F3" />
            <text x={PAD.l - 8} y={y(v) + 4} textAnchor="end" className="preview__tick">{v}</text>
          </g>
        ))}
        {hourTicks.map((t) => (
          <text key={t} x={x(t)} y={H - 8} textAnchor="middle" className="preview__tick">{hhmm(t)}</text>
        ))}
        <text x={8} y={PAD.t - 8} className="preview__tick">mg/dL</text>
        <line x1={x(clock)} x2={x(clock)} y1={PAD.t - 6} y2={H - PAD.b} stroke="#111827" strokeWidth={1.2} />
        <text x={x(clock)} y={PAD.t - 10} textAnchor="middle" className="preview__label">Replay clock {hhmm(clock)}</text>
        <path d={path} fill="none" stroke="#111827" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {fc.map((f) => (
          <g key={f.horizon}>
            {f.lower != null && f.upper != null && (
              <>
                <line x1={x(f.t)} x2={x(f.t)} y1={y(f.lower)} y2={y(f.upper)} stroke="#2563EB" strokeWidth={1.5} />
                <line x1={x(f.t) - 5} x2={x(f.t) + 5} y1={y(f.lower)} y2={y(f.lower)} stroke="#2563EB" strokeWidth={1.5} />
                <line x1={x(f.t) - 5} x2={x(f.t) + 5} y1={y(f.upper)} y2={y(f.upper)} stroke="#2563EB" strokeWidth={1.5} />
              </>
            )}
            <circle cx={x(f.t)} cy={y(f.value)} r={4.5} fill="#2563EB" />
            <text x={x(f.t)} y={y(f.upper ?? f.value) - 8} textAnchor="middle" className="preview__fc">
              +{f.horizon} min · {Math.round(f.value)}
            </text>
          </g>
        ))}
      </svg>
      <figcaption className="preview__legend">
        <span><i className="lg lg--obs" aria-hidden />Observed glucose</span>
        <span><i className="lg lg--fc" aria-hidden />Forecasts, 30 and 60 min</span>
        <span><i className="lg lg--range" aria-hidden />Prediction range · target coverage {level}%</span>
      </figcaption>
    </figure>
  );
}
