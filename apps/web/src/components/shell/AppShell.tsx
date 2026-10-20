import { ChevronRight, Database, FlaskConical, Menu, Plus, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, Outlet, useLocation, useNavigationType, useSearchParams } from "react-router";
import { useClient } from "@/api/client";
import { modeLabel } from "@/lib/format";
import { APP, paths } from "@/lib/routes";
import { RAIL_QUERY, useMediaQuery } from "@/lib/useMediaQuery";
import { useDeployment } from "@/state/deployment";
import { usePreferences } from "@/state/preferences";
import { useReadiness, useSession } from "@/state/replay";
import { Button, IconButton, InlineNotice } from "../ui";
import { HelpDialog, NewReplayDialog, PreferencesDialog, WorkspaceSearch } from "./Dialogs";
import { ShellContext, type ShellDialog } from "./ShellContext";
import { NAV, Sidebar } from "./Sidebar";

export function AppShell() {
  const { prefs } = usePreferences();
  const narrow = useMediaQuery(RAIL_QUERY);
  const [dialog, setDialog] = useState<ShellDialog>(null);
  const [initialPatient, setInitialPatient] = useState<string | undefined>();
  const close = useCallback(() => setDialog(null), []);
  const ctx = useMemo(
    () => ({
      open: (d: Exclude<ShellDialog, null>, opts?: { patientId?: string }) => {
        setInitialPatient(opts?.patientId);
        setDialog(d);
      },
      close,
    }),
    [close],
  );

  // Cmd/Ctrl+K opens search; never hijacks typing inside form fields.
  useEffect(() => {
    if (!prefs.shortcuts) return;
    const onKey = (e: KeyboardEvent) => {
      if (!(e.key === "k" || e.key === "K") || !(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return;
      const t = e.target as HTMLElement | null;
      const typing = t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
      if (typing) return;
      e.preventDefault();
      setDialog("search");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [prefs.shortcuts]);

  useHeadingFocusOnNavigation();

  return (
    <ShellContext.Provider value={ctx}>
      <a href="#main" className="skip-link">Skip to content</a>
      <div className="shell" data-collapsed={prefs.sidebarCollapsed || narrow ? "true" : "false"}>
        <div className="shell__side"><Sidebar /></div>
        <div className="shell__main">
          <TopBar onMenu={() => setDialog("mobile-nav")} onNew={() => setDialog("new-replay")} />
          <main id="main" tabIndex={-1} className="main">
            <ApiStatus />
            <Outlet />
          </main>
        </div>
      </div>
      <MobileNav open={dialog === "mobile-nav"} onClose={close} />
      <WorkspaceSearch open={dialog === "search"} onClose={close} />
      <NewReplayDialog open={dialog === "new-replay"} onClose={close} initialPatient={initialPatient} />
      <PreferencesDialog open={dialog === "preferences"} onClose={close} />
      <HelpDialog open={dialog === "help"} onClose={close} />
    </ShellContext.Provider>
  );
}

/**
 * Route-aware focus: a new primary navigation starts at the new page heading (scroll position itself is handled by
 * the router's ScrollRestoration — top on push, restored on Back). Polling and same-page query updates are untouched.
 */
function useHeadingFocusOnNavigation() {
  const loc = useLocation();
  const type = useNavigationType();
  const prev = useRef(loc.pathname + loc.search);
  useEffect(() => {
    const here = loc.pathname + loc.search;
    if (here === prev.current) return;
    prev.current = here;
    if (type !== "PUSH") return;
    const t = window.setTimeout(() => {
      const active = document.activeElement as HTMLElement | null;
      if (active && active.closest("dialog[open]")) return;
      document.querySelector<HTMLElement>("#main h1")?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(t);
  }, [loc.pathname, loc.search, type]);
}

function TopBar({ onMenu, onNew }: { onMenu: () => void; onNew: () => void }) {
  const loc = useLocation();
  const [params] = useSearchParams();
  const sid = loc.pathname === APP ? params.get("session") : null;
  const session = useSession(sid);
  const page = NAV.find((n) => (n.to === APP ? loc.pathname === APP : loc.pathname.startsWith(n.to)));
  const mode = session.data?.mode;
  const ModeIcon = mode === "synthetic_demo" ? FlaskConical : Database;
  return (
    <header className="topbar">
      <span className="topbar__menu">
        <IconButton icon={Menu} label="Open navigation" onClick={onMenu} tooltip={false} />
      </span>
      <nav className="crumbs" aria-label="Breadcrumb">
        <ol>
          {sid ? (
            <>
              <li><Link to={paths.overview()}>Overview</Link></li>
              <li aria-hidden><ChevronRight size={14} /></li>
              <li><span aria-current="page">{session.data?.patient_alias ?? "Replay"}</span></li>
            </>
          ) : (
            <li><span aria-current="page">{page?.label ?? "Page not found"}</span></li>
          )}
        </ol>
      </nav>
      <span className="topbar__spacer" />
      {mode && (
        <span className="topbar__mode">
          <ModeIcon size={15} aria-hidden strokeWidth={1.8} />
          {modeLabel(mode)}
        </span>
      )}
      <span className="topbar__mobile-action">
        <Button size="sm" variant="primary" icon={Plus} onClick={onNew}>New replay</Button>
      </span>
    </header>
  );
}

function MobileNav({ open, onClose }: { open: boolean; onClose: () => void }) {
  // Native modal <dialog>: focus moves inside, background is inert, Escape closes, focus returns to the opener.
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      opener.current = document.activeElement;
      el.showModal?.();
    } else if (!open && el.open) el.close();
  }, [open]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onCancel = (e: Event) => {
      e.preventDefault();
      onClose();
    };
    const onClosed = () => (opener.current as HTMLElement | null)?.focus?.();
    el.addEventListener("cancel", onCancel);
    el.addEventListener("close", onClosed);
    return () => {
      el.removeEventListener("cancel", onCancel);
      el.removeEventListener("close", onClosed);
    };
  }, [onClose]);
  return (
    <dialog ref={ref} className="drawer" aria-label="Navigation" onClick={(e) => e.target === ref.current && onClose()}>
      {open && <Sidebar inDrawer onNavigate={onClose} />}
    </dialog>
  );
}

function ApiStatus() {
  const client = useClient();
  const r = useReadiness();
  const { publicDemo } = useDeployment();
  if (client.transportKind === "fixtures") {
    return (
      <InlineNotice tone="attention" icon={TriangleAlert} role="status">
        Fixture transport: static synthetic example payloads, no replay. Not connected to the GlucoTwin API.
      </InlineNotice>
    );
  }
  if (r.isError) {
    return (
      <InlineNotice tone="danger" icon={TriangleAlert} role="alert"
        action={<Button size="sm" onClick={() => r.refetch()}>Retry</Button>}>
        {publicDemo ? <>The demonstration’s API is not reachable right now; try again shortly.</>
          : <>The GlucoTwin API is not reachable. Start it with <code>make api</code> (or <code>uv run glucotwin serve</code>);</>}
        {" "}nothing on this page is being replaced with example data.
      </InlineNotice>
    );
  }
  return null;
}
