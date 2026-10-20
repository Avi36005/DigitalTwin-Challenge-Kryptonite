/** Evidence responses served from the committed aggregate-only snapshot (public demonstration only) say so. */
export interface SnapshotMarked {
  source?: "published_snapshot" | null;
  snapshot_exported_at?: string | null;
  snapshot_commit?: string | null;
}

/** "Published snapshot of saved experiment files (exported 2026-10-20, commit 1d6ba9759618)", or null for live artifacts. */
export function snapshotLine(x: SnapshotMarked | null | undefined): string | null {
  if (!x || x.source !== "published_snapshot") return null;
  const parts = [x.snapshot_exported_at ? `exported ${x.snapshot_exported_at.slice(0, 10)}` : null,
    x.snapshot_commit ? `commit ${x.snapshot_commit}` : null].filter(Boolean);
  return `Published snapshot of saved experiment files${parts.length ? ` (${parts.join(", ")})` : ""}`;
}
