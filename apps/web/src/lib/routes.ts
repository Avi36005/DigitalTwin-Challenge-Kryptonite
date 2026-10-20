/**
 * Every in-app URL is built here, so a route change is one edit rather than a search-and-replace.
 * The landing page lives at "/", the workspace under "/app". API paths (/api/v1) are unrelated.
 */
export const APP = "/app";

export const paths = {
  landing: () => "/",
  overview: () => APP,
  session: (id: string) => `${APP}?session=${encodeURIComponent(id)}`,
  participants: (focus?: string) => `${APP}/participants${focus ? `?focus=${encodeURIComponent(focus)}` : ""}`,
  sessions: () => `${APP}/sessions`,
  reviewQueue: () => `${APP}/review-queue`,
  evidence: (hash?: string) => `${APP}/evidence${hash ? `#${hash}` : ""}`,
  dataQuality: () => `${APP}/data-quality`,
};

/** Workspace pages that existed at the site root before the landing page; old links redirect to /app/<page>. */
export const LEGACY_PAGES = ["participants", "sessions", "evidence", "data-quality"] as const;

/** Where an old URL now lives. Query string and hash are preserved; returns null when no redirect applies. */
export function migrateLegacyUrl(pathname: string, search: string, hash: string): string | null {
  const page = pathname.replace(/^\/+|\/+$/g, "");
  if (page === "" && new URLSearchParams(search).has("session")) return `${APP}${search}${hash}`;
  if ((LEGACY_PAGES as readonly string[]).includes(page)) return `${APP}/${page}${search}${hash}`;
  return null;
}
