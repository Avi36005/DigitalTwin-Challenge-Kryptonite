import { snapshotLine } from "./snapshot";

describe("snapshotLine", () => {
  it("names the export date and commit of a published snapshot", () => {
    expect(snapshotLine({ source: "published_snapshot", snapshot_exported_at: "2026-10-20T14:56:20+00:00", snapshot_commit: "1d6ba9759618" }))
      .toBe("Published snapshot of saved experiment files (exported 2026-10-20, commit 1d6ba9759618)");
  });
  it("says nothing for evidence read from the saved artifacts", () => {
    expect(snapshotLine({ source: null })).toBeNull();
    expect(snapshotLine({})).toBeNull();
    expect(snapshotLine(undefined)).toBeNull();
  });
  it("still labels a snapshot whose manifest lacks details", () => {
    expect(snapshotLine({ source: "published_snapshot" })).toBe("Published snapshot of saved experiment files");
  });
});
