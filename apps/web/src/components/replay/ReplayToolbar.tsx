import { Pause, Play, RotateCcw, Target } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { ControlCommand, EvaluationSegment, ReplaySession } from "@/api/types";
import { ms, replayTime, toIso } from "@/lib/time";
import { useControl } from "@/state/replay";
import { useToast } from "@/state/toasts";
import { Button, InlineNotice } from "../ui";
import { SPEEDS } from "../shell/Dialogs";
import { statusWord } from "../shell/Sidebar";

const SEG_COLORS: Record<string, string> = { training: "#D1D5DB", validation: "#93C5FD", calibration: "#60A5FA", test: "#1D4ED8" };
const SEG_LABEL: Record<string, string> = {
  training: "Training (in-sample)",
  validation: "Validation",
  calibration: "Calibration",
  test: "Held-out test",
};

/** Compact replay controls under the chart. The backend owns the clock; a seek creates a new revision. */
export function ReplayToolbar({ session, segments, onAnnounce }: {
  session: ReplaySession; segments?: EvaluationSegment[] | null; onAnnounce: (msg: string) => void;
}) {
  const control = useControl(session.id);
  const toast = useToast();
  const lastCmd = useRef<ControlCommand | null>(null);
  const [pending, setPending] = useState<number | null>(null);
  const sliderId = useId();
  const start = ms(session.timeline.start_at);
  const end = ms(session.timeline.end_at);
  const clock = ms(session.clock_at);
  const busy = control.isPending;
  const playing = session.status === "playing";
  const completed = session.status === "completed";

  useEffect(() => setPending(null), [session.id, session.revision]);

  const run = (cmd: ControlCommand, done?: string) => {
    lastCmd.current = cmd;
    control.mutate(cmd, {
      onSuccess: (s) => {
        if (done) {
          toast(done);
          onAnnounce(`${done}. Replay time ${replayTime(s.clock_at)}.`);
        }
      },
      onError: (e) => toast(`Replay control failed: ${(e as Error).message}`, "error"),
    });
  };
  const commitSeek = (t: number) => {
    setPending(null);
    const snapped = Math.round(t / 60_000) * 60_000;
    run({ action: "seek", seek_to: toIso(snapped) }, `Moved to ${replayTime(snapped)}`);
  };
  const test = segments?.find((s) => s.name === "test");
  const span = end - start || 1;
  const segText = segments?.length
    ? `Evaluation periods: ${segments.map((s) => `${SEG_LABEL[s.name] ?? s.name} from ${replayTime(s.start_at)} to ${replayTime(s.end_at)}`).join("; ")}.`
    : "";

  return (
    <div className="replay-bar" role="group" aria-label="Replay controls">
      <div className="replay-bar__buttons">
        {playing ? (
          <Button variant="primary" size="sm" icon={Pause} disabled={busy} aria-label="Pause replay" onClick={() => run({ action: "pause" })}>Pause</Button>
        ) : (
          <Button variant="primary" size="sm" icon={Play} disabled={busy || completed} aria-label={completed ? "Replay completed" : "Play replay"}
            onClick={() => run({ action: "play" })}>{completed ? "Completed" : "Play"}</Button>
        )}
        <Button variant="ghost" size="sm" disabled={busy || completed} aria-label="Step 5 min forward" onClick={() => run({ action: "step", steps: 1 })}>Step 5 min</Button>
        <Button variant="ghost" size="sm" disabled={busy || completed} aria-label="Step 1 h forward" onClick={() => run({ action: "step", steps: 12 })}>Step 1 h</Button>
        <Button variant="ghost" size="sm" icon={RotateCcw} disabled={busy} aria-label="Reset to start of recording" onClick={() => run({ action: "reset" }, "Replay reset")}>Reset</Button>
      </div>

      <p className="replay-bar__clock">
        <span className="replay-bar__clock-label">Replay time</span> <strong className="num">{replayTime(session.clock_at)}</strong>
        <span className="replay-bar__state"> · {statusWord(session.status)}</span>
      </p>

      <div className="replay-bar__end">
        {test && (
          <Button size="sm" variant={clock < ms(test.start_at) ? "secondary" : "ghost"} icon={Target} disabled={busy} onClick={() => commitSeek(ms(test.start_at))}
            title={`Jump to the start of the held-out test period (${replayTime(test.start_at)})`}>Test period</Button>
        )}
        <label className="visually-hidden" htmlFor={`${sliderId}-speed`}>Replay speed</label>
        <select id={`${sliderId}-speed`} className="select select--sm" value={session.speed} disabled={busy}
          onChange={(e) => run({ action: playing ? "play" : "pause", speed: Number(e.target.value) })}>
          {Array.from(new Set([...SPEEDS, session.speed])).sort((a, b) => a - b).map((s) => (
            <option key={s} value={s}>{s} min/s</option>
          ))}
        </select>
      </div>

      <div className="timeline">
        <div className="timeline__track">
          <div className="timeline__segments" aria-hidden>
            {segments?.length
              ? segments.map((s) => (
                  <span key={s.name} title={SEG_LABEL[s.name] ?? s.name} style={{
                    width: `${((ms(s.end_at) - ms(s.start_at)) / span) * 100}%`,
                    marginLeft: s === segments[0] ? `${((ms(s.start_at) - start) / span) * 100}%` : 0,
                    background: SEG_COLORS[s.name] ?? "#D1D5DB",
                  }} />
                ))
              : <span style={{ width: `${((clock - start) / span) * 100}%`, background: "#93C5FD" }} />}
          </div>
          <label htmlFor={sliderId} className="visually-hidden">Seek replay time</label>
          <input id={sliderId} type="range" min={start} max={end} step={5 * 60_000} value={pending ?? clock} disabled={busy}
            aria-valuetext={replayTime(pending ?? clock)} aria-describedby={segText ? `${sliderId}-segs` : undefined}
            onChange={(e) => setPending(Number(e.target.value))}
            onPointerUp={(e) => commitSeek(Number((e.target as HTMLInputElement).value))}
            onKeyDown={(e) => {
              if (e.key === "Enter" && pending !== null) commitSeek(pending);
              if (e.key === "Escape") setPending(null);
            }} />
        </div>
        <div className="timeline__labels">
          <span className="num">{replayTime(start)}</span>
          {pending !== null ? (
            <span className="timeline__pending" aria-live="polite">Seek to {replayTime(pending)} — press Enter or release</span>
          ) : segments?.length ? (
            <span className="timeline__key" aria-hidden>
              {segments.map((s) => <span key={s.name}><i style={{ background: SEG_COLORS[s.name] }} />{s.name === "test" ? "test" : s.name}</span>)}
            </span>
          ) : <span />}
          <span className="num">{replayTime(end)}</span>
        </div>
        {segText && <p id={`${sliderId}-segs`} className="visually-hidden">{segText}</p>}
      </div>

      {control.isError && (
        <div className="replay-bar__error">
          <InlineNotice tone="danger" role="alert"
            action={<Button size="sm" disabled={busy} onClick={() => lastCmd.current && run(lastCmd.current)}>Retry</Button>}>
            The last replay command failed; the replay state shown is the server’s current state.
          </InlineNotice>
        </div>
      )}
    </div>
  );
}
