import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, Link, Navigate, Outlet, RouterProvider, ScrollRestoration, useLocation, type RouteObject } from "react-router";
import { ClientProvider, type Client } from "./api/client";
import { PublicDemoBanner } from "./components/shell/PublicDemoBanner";
import { PageHeader } from "./components/ui";
import { migrateLegacyUrl, paths } from "./lib/routes";
import { LandingPage } from "./pages/LandingPage";
import { PreferencesProvider } from "./state/preferences";
import { ToastProvider } from "./state/toasts";

/** Root: restores scroll on Back/Forward and starts new pages at the top (window is the only page scroller); the hosted
 *  public demonstration adds its banner above every page. */
function Root() {
  return (
    <>
      <ScrollRestoration />
      <PublicDemoBanner />
      <Outlet />
    </>
  );
}

/** "/" is the landing page, except an old replay link "/?session=<id>", which moves to the workspace unchanged. */
function LandingOrLegacy() {
  const loc = useLocation();
  const to = migrateLegacyUrl(loc.pathname, loc.search, loc.hash);
  return to ? <Navigate to={to} replace /> : <LandingPage />;
}

/** Old workspace URLs (/participants, /sessions, /evidence, /data-quality) keep working; replace avoids a Back loop. */
function LegacyRedirect() {
  const loc = useLocation();
  return <Navigate to={migrateLegacyUrl(loc.pathname, loc.search, loc.hash) ?? paths.overview()} replace />;
}

function NotFound() {
  return (
    <PageHeader title="Page not found">
      This page does not exist. <Link to={paths.overview()}>Go to the workspace overview</Link>.
    </PageHeader>
  );
}

function SiteNotFound() {
  return (
    <main className="site-404" id="main" tabIndex={-1}>
      <NotFound />
      <p><Link to={paths.landing()}>GlucoTwin home</Link></p>
    </main>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Root />,
    hydrateFallbackElement: <div className="boot" aria-busy="true" />,
    children: [
      { index: true, element: <LandingOrLegacy /> },
      {
        path: "app",
        lazy: () => import("./components/shell/AppShell").then((m) => ({ Component: m.AppShell })),
        children: [
          { index: true, lazy: () => import("./pages/WorkspaceIndex").then((m) => ({ Component: m.WorkspaceIndex })) },
          { path: "participants", lazy: () => import("./pages/ParticipantsPage").then((m) => ({ Component: m.ParticipantsPage })) },
          { path: "sessions", lazy: () => import("./pages/SessionsPage").then((m) => ({ Component: m.SessionsPage })) },
          { path: "review-queue", lazy: () => import("./pages/ReviewQueuePage").then((m) => ({ Component: m.ReviewQueuePage })) },
          { path: "evidence", lazy: () => import("./pages/EvidencePage").then((m) => ({ Component: m.EvidencePage })) },
          { path: "data-quality", lazy: () => import("./pages/DataQualityPage").then((m) => ({ Component: m.DataQualityPage })) },
          { path: "*", element: <NotFound /> },
        ],
      },
      { path: "participants", element: <LegacyRedirect /> },
      { path: "sessions", element: <LegacyRedirect /> },
      { path: "evidence", element: <LegacyRedirect /> },
      { path: "data-quality", element: <LegacyRedirect /> },
      { path: "*", element: <SiteNotFound /> },
    ],
  },
];

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
  });
}

export function Providers({ client, children, queryClient }: { client?: Client; children: React.ReactNode; queryClient?: QueryClient }) {
  const [qc] = useState(() => queryClient ?? makeQueryClient());
  return (
    <QueryClientProvider client={qc}>
      <ClientProvider client={client}>
        <PreferencesProvider>
          <ToastProvider>{children}</ToastProvider>
        </PreferencesProvider>
      </ClientProvider>
    </QueryClientProvider>
  );
}

const router = createBrowserRouter(routes);

export function App() {
  return (
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  );
}
