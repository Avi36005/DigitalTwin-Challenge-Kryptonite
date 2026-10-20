import { describe, expect, it } from "vitest";
import type { Alert, AlertList, ReplaySession } from "@/api/types";
import { forecast, latest, session } from "@/test/fixtures";
import { inputState, queueRow, sortQueue } from "./queue";

function alert(id: string, issued: string, acknowledged = false, over: Partial<Alert> = {}): Alert {
  return {
    schema_version: "1.0", alert_id: id, session_id: "s1", patient_id: "SYN-A", session_revision: 1, issued_at: issued,
    last_supported_at: issued, horizon_minutes: 60, rule_version: "r", model_version: "m", kind: "predicted_new_high_episode",
    title: "Research warning", supporting_forecast_ids: ["f1"], state: "open",
    evidence: { forecast_id: "f1", score: 12, score_kind: "forecast_margin_mg_dl", threshold: -10, latest_glucose_mg_dl: 160,
      predicted_mg_dl: { "30": 175, "60": 192 }, explanation_codes: [] },
    outcome: { status: "pending" },
    acknowledgement: { acknowledged, acknowledged_at: acknowledged ? issued : null, note: null },
    ...over,
  } as Alert;
}

const list = (s: ReplaySession, items: Alert[]): AlertList => ({
  schema_version: "1.0", session_id: s.id, session_revision: s.revision, clock_at: s.clock_at, rule_available: true,
  rule_description: null, items,
});

describe("review queue rows", () => {
  it("counts unreviewed and reviewed warnings and describes the latest one", () => {
    const s = session();
    const r = queueRow(s, list(s, [alert("a", "2000-01-03T08:00:00Z", true), alert("b", "2000-01-03T09:30:00Z")]), latest(forecast()));
    expect(r.unreviewed).toBe(1);
    expect(r.reviewed).toBe(1);
    expect(r.lastWarningAt).toBe("2000-01-03T09:30:00Z");
    expect(r.lastOutcome).toBe("Outcome pending");
    expect(r.lastTrigger).toBe("Fired by the 60-min forecast 192 mg/dL ≥ 170 mg/dL trigger");
    expect(r.inputs).toBe("ok");
  });

  it("ignores warnings from another revision of the session instead of showing stale counts", () => {
    const s = session({ revision: 2 });
    const r = queueRow(s, { ...list(s, [alert("a", "2000-01-03T08:00:00Z")]), session_revision: 1 });
    expect(r.unreviewed).toBeNull();
    expect(r.lastWarningAt).toBeNull();
  });

  it("never reports an outcome resolved after the replay clock", () => {
    const s = session();
    const late = alert("a", "2000-01-03T09:00:00Z", false, { outcome: { status: "no_onset_observed", confirmed_at: "2000-01-03T11:00:00Z" } });
    expect(queueRow(s, list(s, [late])).lastOutcome).toBe("Outcome pending at the cutoff");
  });

  it("flags degraded and abstained inputs", () => {
    expect(inputState(latest(forecast({ quality: { status: "degraded", reasons: [] } })))).toBe("degraded");
    expect(inputState(latest(null))).toBe("abstained");
    expect(inputState(undefined)).toBe("unknown");
  });
});

describe("review queue order", () => {
  const row = (id: string, alias: string, items: Alert[]) => {
    const s = session({ id, patient_alias: alias });
    return queueRow(s, list(s, items));
  };

  it("puts unreviewed warnings first, then the most recent warning, then replays without warnings", () => {
    const rows = [
      row("quiet", "Participant A", []),
      row("old-open", "Participant B", [alert("1", "2000-01-03T06:00:00Z")]),
      row("reviewed-recent", "Participant C", [alert("2", "2000-01-03T09:50:00Z", true)]),
      row("new-open", "Participant D", [alert("3", "2000-01-03T09:00:00Z")]),
      row("reviewed-old", "Participant E", [alert("4", "2000-01-03T05:00:00Z", true)]),
    ];
    expect(sortQueue(rows).map((r) => r.session.id)).toEqual(["new-open", "old-open", "reviewed-recent", "reviewed-old", "quiet"]);
  });

  it("keeps rows whose warnings are still loading after those with warnings, sorted by name", () => {
    const loading = queueRow(session({ id: "z", patient_alias: "Participant A" }));
    const quiet = row("q", "Participant B", []);
    const open = row("o", "Participant C", [alert("1", "2000-01-03T06:00:00Z")]);
    expect(sortQueue([quiet, loading, open]).map((r) => r.session.id)).toEqual(["o", "z", "q"]);
  });
});
