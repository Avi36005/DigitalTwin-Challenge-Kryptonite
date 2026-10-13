import { History, Search, User } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import type { PatientSummary, ReplayMode } from "@/api/types";
import { modeLabel } from "@/lib/format";
import { paths } from "@/lib/routes";
import { replayTime } from "@/lib/time";
import { usePreferences } from "@/state/preferences";
import { useCreateReplay } from "@/state/open";
import { usePatient, usePatients, useSessions } from "@/state/replay";
import { Button, Dialog } from "../ui";
import { NAV, statusWord } from "./Sidebar";

/* ================================================================ Command search */
type Item = { id: string; group: string; label: string; meta?: string; icon: typeof Search; go: () => void };

export function WorkspaceSearch({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate();
  const patients = usePatients();
  const sessions = useSessions();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (open) {
      setQ("");
      setActive(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const go = (path: string) => () => {
      onClose();
      nav(path);
    };
    const all: Item[] = [
      ...NAV.map((n) => ({ id: `nav:${n.to}`, group: "Go to", label: n.label, icon: n.icon, go: go(n.to) })),
      ...(sessions.data?.items ?? []).map((s) => ({
        id: `s:${s.id}`, group: "Replay sessions", label: s.patient_alias, icon: History,
        meta: `${s.mode === "synthetic_demo" ? "Synthetic" : "Recorded"} · ${statusWord(s.status)} · ${replayTime(s.clock_at)}`,
        go: go(paths.session(s.id)),
      })),
      ...(patients.data?.items ?? []).map((p) => ({
        id: `p:${p.patient_id}`, group: "Participants", label: p.display_alias, icon: User,
        meta: `${p.cohort.label} · ${p.mode === "synthetic_demo" ? "Synthetic" : "CGMacros"} · ${p.patient_id}`,
        go: go(paths.participants(p.patient_id)),
      })),
    ];
    const needle = q.trim().toLowerCase();
    if (!needle) return all.slice(0, 18);
    return all.filter((i) => `${i.label} ${i.meta ?? ""} ${i.group}`.toLowerCase().includes(needle)).slice(0, 30);
  }, [q, patients.data, sessions.data, nav, onClose]);

  useEffect(() => setActive(0), [q]);
  const loading = patients.isLoading || sessions.isLoading;

  let lastGroup = "";
  return (
    <Dialog open={open} onClose={onClose} bare width={600} labelledBy="search-label">
      <div className="palette-input__wrap">
        <Search size={18} aria-hidden className="palette-input__icon" />
        <label id="search-label" htmlFor="workspace-search" className="visually-hidden">
          Search participants, replay sessions and pages
        </label>
        <input
          ref={inputRef}
          id="workspace-search"
          className="palette-input"
          placeholder="Search participants, replay sessions and pages"
          value={q}
          role="combobox"
          aria-expanded="true"
          aria-controls="workspace-search-list"
          aria-activedescendant={items[active] ? `opt-${items[active].id}` : undefined}
          autoComplete="off"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, items.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && items[active]) {
              e.preventDefault();
              items[active].go();
            }
          }}
        />
      </div>
      <ul className="palette-list" id="workspace-search-list" role="listbox" aria-label="Results">
        {loading && <li className="palette-group">Loading workspace…</li>}
        {!loading && items.length === 0 && (
          <li className="palette-group" role="presentation">
            No matches for “{q}”.{" "}
            <button type="button" className="btn btn--quiet btn--sm" onClick={() => setQ("")}>
              Clear search
            </button>
          </li>
        )}
        {items.map((it, i) => {
          const header = it.group !== lastGroup ? it.group : null;
          lastGroup = it.group;
          const Icon = it.icon;
          return (
            <li key={it.id} role="presentation">
              {header && <div className="palette-group">{header}</div>}
              <div
                id={`opt-${it.id}`}
                role="option"
                aria-selected={i === active}
                className="palette-item"
                onMouseEnter={() => setActive(i)}
                onClick={it.go}
              >
                <Icon size={16} aria-hidden />
                <span className="palette-item__text">
                  <span className="palette-item__label">{it.label}</span>
                  {it.meta && <span className="palette-item__meta">{it.meta}</span>}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </Dialog>
  );
}

/* ================================================================ New replay */
export function NewReplayDialog({ open, onClose, initialPatient }: { open: boolean; onClose: () => void; initialPatient?: string }) {
  const patients = usePatients();
  const create = useCreateReplay();
  const [mode, setMode] = useState<ReplayMode>("dataset_replay");
  const [pid, setPid] = useState<string>("");
  const [start, setStart] = useState<"start" | "test">("start");
  const list = useMemo(() => (patients.data?.items ?? []).filter((p) => p.mode === mode), [patients.data, mode]);
  const detail = usePatient(pid || null);
  const initialized = useRef(false);
  // Layout effect: initialise before the native dialog is shown (its showModal runs in a passive effect), so a
  // user's first click can never be overwritten; once per opening, never on background refetches.
  useLayoutEffect(() => {
    if (!open) {
      initialized.current = false;
      return;
    }
    if (initialized.current || !patients.data) return;
    initialized.current = true;
    const all = patients.data.items;
    const init = all.find((p) => p.patient_id === initialPatient);
    const hasDataset = all.some((p) => p.mode === "dataset_replay");
    const m: ReplayMode = init?.mode ?? (hasDataset ? "dataset_replay" : "synthetic_demo");
    setMode(m);
    setPid(init?.patient_id ?? all.find((p) => p.mode === m && (m !== "dataset_replay" || p.eligible_for_primary_analysis))?.patient_id ?? "");
    setStart("start");
  }, [open, initialPatient, patients.data]);
  const testSeg = detail.data?.evaluation_segments?.find((s) => s.name === "test");

  const submit = () => {
    if (!pid) return;
    create.mutate({ patientId: pid, mode, startAt: start === "test" && testSeg ? testSeg.start_at : undefined }, {
      onSuccess: onClose,
    });
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New replay"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={!pid} busy={create.isPending}>
            {create.isPending ? "Starting…" : "Start replay"}
          </Button>
        </>
      }
    >
      <p className="dialog__lead">
        Replays recorded measurements as if they were arriving, using only information available at each replay time.
        This is not a live device connection.
      </p>
      <fieldset className="field">
        <legend>Data mode</legend>
        <div className="radio-row">
          {(["dataset_replay", "synthetic_demo"] as const).map((m) => {
            const n = (patients.data?.items ?? []).filter((p) => p.mode === m).length;
            return (
              <label key={m} className="radio-card">
                <input type="radio" name="mode" value={m} checked={mode === m} disabled={n === 0}
                  onChange={() => { setMode(m); setPid(""); }} />
                <span>
                  <strong className="radio-card__title">{modeLabel(m)}</strong>
                  <span className="radio-card__desc">
                    {m === "dataset_replay"
                      ? n ? "CGMacros research recordings (de-identified)" : "CGMacros not imported on this machine"
                      : "Fictional participants for software demonstration"}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <div className="field">
        <label htmlFor="nr-participant">Participant</label>
        <select id="nr-participant" className="select" value={pid} onChange={(e) => setPid(e.target.value)}>
          <option value="">Choose a participant…</option>
          {groupByCohort(list).map(([cohort, ps]) => (
            <optgroup key={cohort} label={cohort}>
              {ps.map((p) => (
                <option key={p.patient_id} value={p.patient_id}>
                  {p.display_alias}
                  {p.mode === "dataset_replay" && !p.eligible_for_primary_analysis ? " (outside primary analysis)" : ""}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {patients.isError && <span className="hint">Participants could not be loaded.</span>}
      </div>
      {testSeg && (
        <fieldset className="field">
          <legend>Starting point</legend>
          <div className="radio-row">
            <label className="radio-card">
              <input type="radio" name="start" checked={start === "start"} onChange={() => setStart("start")} />
              <span>
                <strong className="radio-card__title">Start of recording</strong>
                <span className="radio-card__desc">Early forecasts fall in the model’s training period (in-sample).</span>
              </span>
            </label>
            <label className="radio-card">
              <input type="radio" name="start" checked={start === "test"} onChange={() => setStart("test")} />
              <span>
                <strong className="radio-card__title">Held-out test period</strong>
                <span className="radio-card__desc">Begins at {replayTime(testSeg.start_at)}; the twin rebuilds its state from earlier data.</span>
              </span>
            </label>
          </div>
        </fieldset>
      )}
    </Dialog>
  );
}

function groupByCohort(ps: PatientSummary[]): [string, PatientSummary[]][] {
  const m = new Map<string, PatientSummary[]>();
  for (const p of ps) m.set(p.cohort.label, [...(m.get(p.cohort.label) ?? []), p]);
  return Array.from(m.entries());
}

/* ================================================================ Preferences */
export function PreferencesDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { prefs, update } = usePreferences();
  return (
    <Dialog open={open} onClose={onClose} title="Preferences" footer={<Button onClick={onClose}>Done</Button>}>
      <p className="dialog__lead">Saved in this browser only.</p>
      <div className="field">
        <label htmlFor="pref-sidebar">Sidebar</label>
        <select id="pref-sidebar" className="select" value={prefs.sidebarCollapsed ? "collapsed" : "expanded"}
          onChange={(e) => update({ sidebarCollapsed: e.target.value === "collapsed" })}>
          <option value="expanded">Expanded</option>
          <option value="collapsed">Collapsed rail</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="pref-density">Density</label>
        <select id="pref-density" className="select" value={prefs.density}
          onChange={(e) => update({ density: e.target.value as "comfortable" | "compact" })}>
          <option value="comfortable">Comfortable</option>
          <option value="compact">Compact</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="pref-speed">Default replay speed</label>
        <select id="pref-speed" className="select" value={prefs.defaultSpeed}
          onChange={(e) => update({ defaultSpeed: Number(e.target.value) })}>
          {SPEEDS.map((s) => (
            <option key={s} value={s}>{s} replay minutes per second</option>
          ))}
        </select>
        <span className="hint">Applies to new replays. Change the speed of an open replay from its toolbar.</span>
      </div>
      <div className="field">
        <label htmlFor="pref-motion">Motion</label>
        <select id="pref-motion" className="select" value={prefs.motion}
          onChange={(e) => update({ motion: e.target.value as "system" | "reduce" })}>
          <option value="system">Follow system setting</option>
          <option value="reduce">Reduce motion</option>
        </select>
      </div>
      <label className="check">
        <input type="checkbox" checked={prefs.shortcuts} onChange={(e) => update({ shortcuts: e.target.checked })} />
        Enable keyboard shortcut for search (⌘K / Ctrl K)
      </label>
    </Dialog>
  );
}

export const SPEEDS = [5, 10, 30, 60];

/* ================================================================ Help */
export function HelpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Help & demo guide" width={640} footer={<Button onClick={onClose}>Close</Button>}>
      <div className="prose small">
        <p><strong>What this is.</strong> GlucoTwin is a student research prototype. A patient-specific state is updated from
          replayed glucose and wearable activity measurements and forecasts glucose 30 and 60 minutes ahead. It is not a
          medical device and gives no treatment advice.</p>
        <p><strong>Data modes.</strong></p>
        <ul>
          <li><strong>Recorded-data replay</strong> — de-identified CGMacros research recordings (Type 2 diabetes group
            is the primary cohort). Measurements are released as the replay clock passes their availability time.</li>
          <li><strong>Synthetic demonstration</strong> — fictional participants that exercise edge cases (gaps, late meal
            logs, short history). Results on these are never clinical evidence.</li>
        </ul>
        <p><strong>Replay controls.</strong> Play/pause advances the server-owned clock; Step moves 5 minutes; the timeline
          seeks to any time (a new revision is built from earlier data only); Reset returns to the start.</p>
        <p><strong>Reading the forecast.</strong> Black line: observed glucose (breaks mark sensor gaps). Blue points: the
          latest 30- and 60-minute forecasts, with whiskers for the prediction range (target coverage 80%; measured
          coverage on the test period was lower and varies by participant). Faint blue circles are earlier forecasts; they
          stay fixed so you can compare them with what was later observed. The amber dashed line is a research threshold
          (180 mg/dL), not a triage rule.</p>
        <p><strong>Warnings.</strong> A warning fires when the highest forecast within 60 minutes reaches the warning trigger
          (the 180 mg/dL episode threshold plus a margin chosen on validation data; the Review panel shows the level) and
          glucose is not already high. The panel names the forecast that fired it. It is a forecast level in mg/dL, not a probability. “Mark as reviewed” only records a local acknowledgement — no
          message is sent to anyone.</p>
        <p><strong>Evidence.</strong> Model evidence shows the measured comparison (persistence, linear trend, ridge,
          LightGBM, CatBoost) on a held-out test period. Mean absolute error is an average error in mg/dL, not an accuracy
          percentage.</p>
        <p className="muted">Shortcut: ⌘K / Ctrl K opens search (not while typing in a field).</p>
      </div>
    </Dialog>
  );
}

