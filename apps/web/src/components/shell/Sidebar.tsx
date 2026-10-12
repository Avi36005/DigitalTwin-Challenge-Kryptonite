import {
  CircleHelp,
  Database,
  FlaskConical,
  History,
  LayoutGrid,
  Monitor,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Settings,
  Users,
  type LucideIcon,
} from "lucide-react";
import { Link, NavLink, useLocation, useSearchParams } from "react-router";
import { replayTime } from "@/lib/time";
import { modeLabel } from "@/lib/format";
import { APP, paths } from "@/lib/routes";
import { RAIL_QUERY, useMediaQuery } from "@/lib/useMediaQuery";
import { usePreferences } from "@/state/preferences";
import { useSessions } from "@/state/replay";
import { IconButton, Tooltip } from "../ui";
import { Wordmark } from "./Brand";
import { useShell } from "./ShellContext";

export const NAV: { to: string; label: string; icon: LucideIcon }[] = [
  { to: paths.overview(), label: "Overview", icon: LayoutGrid },
  { to: paths.participants(), label: "Participants", icon: Users },
  { to: paths.sessions(), label: "Replay sessions", icon: History },
  { to: paths.evidence(), label: "Model evidence", icon: FlaskConical },
  { to: paths.dataQuality(), label: "Data quality", icon: Database },
];

const ICON = { size: 18, strokeWidth: 1.75 } as const;
const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

export function Sidebar({ inDrawer = false, onNavigate }: { inDrawer?: boolean; onNavigate?: () => void }) {
  const { prefs, update } = usePreferences();
  const shell = useShell();
  const sessions = useSessions();
  const [params] = useSearchParams();
  const location = useLocation();
  const narrow = useMediaQuery(RAIL_QUERY);
  const collapsed = (prefs.sidebarCollapsed || narrow) && !inDrawer;
  const current = location.pathname === APP ? params.get("session") : null;
  const all = sessions.data?.items ?? [];
  const recent = all.slice(0, 5);

  // collapsed rail: every control keeps its accessible name and gets a tooltip that also shows on keyboard focus
  const wrap = (label: string, node: React.ReactNode) =>
    collapsed ? <Tooltip label={label} side="right">{node}</Tooltip> : node;

  return (
    <nav className="sidebar" aria-label="Workspace" data-collapsed={collapsed ? "true" : "false"}>
      <div className="sidebar__top">
        <Link to={paths.overview()} className="brand" aria-label="GlucoTwin workspace overview" onClick={onNavigate}>
          <Wordmark />
        </Link>
        {!inDrawer && !narrow && (
          <span className="sidebar__collapse">
            <IconButton icon={collapsed ? PanelLeftOpen : PanelLeftClose} label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              size="sm" tooltipSide={collapsed ? "right" : "below"} aria-expanded={!collapsed}
              onClick={() => update({ sidebarCollapsed: !collapsed })} />
          </span>
        )}
      </div>

      <div className="sidebar__actions">
        {wrap("New replay",
          <button type="button" className="btn btn--primary btn--block sidebar__new" aria-label={collapsed ? "New replay" : undefined}
            onClick={() => { onNavigate?.(); shell.open("new-replay"); }}>
            <Plus size={16} aria-hidden strokeWidth={2} />
            <span className="sidebar__label-text">New replay</span>
          </button>)}
        {wrap("Search workspace",
          <button type="button" className="side-row side-row--search" aria-label="Search workspace"
            aria-keyshortcuts={isMac ? "Meta+K" : "Control+K"} onClick={() => { onNavigate?.(); shell.open("search"); }}>
            <Search {...ICON} aria-hidden />
            <span className="sidebar__label-text">Search</span>
            {prefs.shortcuts && <kbd className="kbd-hint sidebar__label-text">{isMac ? "⌘K" : "Ctrl K"}</kbd>}
          </button>)}
      </div>

      <div className="sidebar__scroll">
        <ul className="nav">
          {NAV.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              {wrap(label,
                <NavLink to={to} end={to === APP} className="side-row nav__link" aria-label={collapsed ? label : undefined} onClick={onNavigate}>
                  <Icon {...ICON} aria-hidden />
                  <span className="sidebar__label-text">{label}</span>
                </NavLink>)}
            </li>
          ))}
        </ul>

        {!collapsed && (
          <div className="recent">
            <div className="recent__head">
              <h2 className="recent__label" id="recent-label">Recent replays</h2>
              {all.length > 0 && <Link to={paths.sessions()} className="recent__all" onClick={onNavigate}>View all</Link>}
            </div>
            {recent.length === 0 ? (
              <p className="recent__empty">{sessions.isLoading ? "Loading…" : "Replays you open appear here."}</p>
            ) : (
              <ul className="recent__list" aria-labelledby="recent-label">
                {recent.map((s) => (
                  <li key={s.id}>
                    <Link to={paths.session(s.id)} className="recent__item" aria-current={current === s.id ? "true" : undefined}
                      title={s.patient_alias} onClick={onNavigate}>
                      <span className="recent__title">{s.patient_alias}</span>
                      <span className="recent__meta">
                        {s.mode === "synthetic_demo" ? "Synthetic" : "Recorded"} · {replayTime(s.clock_at)}
                      </span>
                      <span className="visually-hidden">, {modeLabel(s.mode)}, {statusWord(s.status)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="sidebar__footer">
        {wrap("Preferences",
          <button type="button" className="side-row" aria-label={collapsed ? "Preferences" : undefined}
            onClick={() => { onNavigate?.(); shell.open("preferences"); }}>
            <Settings {...ICON} aria-hidden />
            <span className="sidebar__label-text">Preferences</span>
          </button>)}
        {wrap("Help & demo guide",
          <button type="button" className="side-row" aria-label={collapsed ? "Help & demo guide" : undefined}
            onClick={() => { onNavigate?.(); shell.open("help"); }}>
            <CircleHelp {...ICON} aria-hidden />
            <span className="sidebar__label-text">Help &amp; demo guide</span>
          </button>)}
        {wrap("Local research workspace",
          <div className="side-row side-row--static" aria-label={collapsed ? "Local research workspace" : undefined} role={collapsed ? "img" : undefined}
            tabIndex={collapsed ? 0 : undefined}>
            <Monitor {...ICON} aria-hidden />
            <span className="sidebar__label-text">
              <span className="side-row__main">Local research workspace</span>
              <span className="side-row__sub">Runs on this computer</span>
            </span>
          </div>)}
      </div>
    </nav>
  );
}

export function statusWord(s: string) {
  return { ready: "Ready", playing: "Playing", paused: "Paused", completed: "Completed", error: "Error" }[s] ?? s;
}
