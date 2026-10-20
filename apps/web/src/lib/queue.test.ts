import { describe, expect, it } from "vitest";
import type { Alert, AlertList, LatestForecast, QueueSnapshot, ReplaySession } from "@/api/types";
import { forecast, latest, session } from "@/test/fixtures";
import { inputState, queueRow, snapshotProblem, sortQueue, summarizeQueue } from "./queue";

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

/** A coherent snapshot of ``s``: every part carries the session's id, revision and clock. */
function snap(s: ReplaySession, items: Alert[] = [], lf?: LatestForecast): QueueSnapshot {
  const alerts: AlertList = { schema_version: "1.0", session_id: s.id, session_revision: s.revision, clock_at: s.clock_at,
    rule_available: true, rule_description: null, items };
  return { schema_version: "1.0", session: s, alerts,
    latest_forecast: { ...(lf ?? latest(forecast())), session_id: s.id, session_revision: s.revision, clock_at: s.clock_at } };
}

describe("review queue rows", () => {
  it("counts unreviewed and reviewed warnings and describes the latest one", () => {
    const s = session();
    const r = queueRow(s, snap(s, [alert("a", "2000-01-03T08:00:00Z", true), alert("b", "2000-01-03T09:30:00Z")]));
    expect(r.status).toBe("complete");
    expect([r.unreviewed, r.reviewed]).toEqual([1, 1]);
    expect(r.lastWarningAt).toBe("2000-01-03T09:30:00Z");
    expect(r.lastOutcome).toBe("Outcome pending");
    expect(r.lastTrigger).toBe("Fired by the 60-min forecast 192 mg/dL ≥ 170 mg/dL trigger");
    expect(r.inputs).toBe("ok");
  });

  it("keeps counts unknown — not zero — while loading or after a failure", () => {
    const s = session();
    const loading = queueRow(s);
    expect([loading.status, loading.unreviewed, loading.inputs]).toEqual(["loading", null, "unknown"]);
    const failed = queueRow(s, undefined, "offline");
    expect([failed.status, failed.unreviewed, failed.inputs, failed.problem]).toEqual(["unavailable", null, "unavailable", "offline"]);
    // the header never says "none" while any count is unknown
    expect(summarizeQueue([loading]).text).toBe("Counting warnings for 1 replay of 1 participant");
    expect(summarizeQueue([failed]).text).toBe("Warnings could not be counted for 1 replay of 1 participant");
    expect(summarizeQueue([loading]).text).not.toMatch(/No replay has unreviewed/);
  });

  it("states a partial total when some rows failed", () => {
    const a = session({ id: "a", patient_id: "SYN-A" });
    const b = session({ id: "b", patient_id: "SYN-B" });
    const rows = [queueRow(a, snap(a, [alert("x", "2000-01-03T09:00:00Z", false, { session_id: "a" })])), queueRow(b, undefined, "offline")];
    expect(summarizeQueue(rows).text).toBe("At least 1 of 2 replays of 2 participants has unreviewed warnings · 1 could not be counted");
  });

  it("refuses an answer about a different session even when its revision matches", () => {
    const s = session({ id: "s1" });
    const other = session({ id: "s2" });
    const r = queueRow(s, { ...snap(other, [alert("a", "2000-01-03T09:00:00Z", false, { session_id: "s2" })]) });
    expect(r.status).toBe("unavailable");
    expect(r.unreviewed).toBeNull();
    expect(r.problem).toMatch(/different replay/);
  });

  it("refuses an answer about a different participant", () => {
    const s = session();
    const x = snap(s);
    expect(snapshotProblem(s, { ...x, session: { ...x.session, patient_id: "SYN-Z" } })).toMatch(/different participant/);
  });

  it("refuses a delayed answer from an earlier revision and accepts the newer revision after a rewind", () => {
    const listed = session({ revision: 2 });
    const old = session({ revision: 1 });
    expect(queueRow(listed, snap(old, [alert("a", "2000-01-03T09:00:00Z")])).status).toBe("unavailable");
    // rewound after the list was read: the snapshot's own (newer) revision and earlier clock are shown, nothing later
    const rewound = session({ revision: 3, clock_at: "2000-01-03T06:00:00Z" });
    const r = queueRow(listed, snap(rewound, [alert("e", "2000-01-03T05:00:00Z", false, { session_revision: 3 })]));
    expect(r.status).toBe("complete");
    expect(r.session.revision).toBe(3);
    expect(r.cutoff).toBe("2000-01-03T06:00:00Z");
    expect(r.unreviewed).toBe(1);
  });

  it("shows a playing replay at the snapshot's own clock, never an earlier clock with later warnings", () => {
    const listed = session({ status: "playing", clock_at: "2000-01-03T10:00:00Z" });
    const later = { ...listed, clock_at: "2000-01-03T10:30:00Z" };
    const r = queueRow(listed, snap(later, [alert("a", "2000-01-03T10:20:00Z")]));
    expect(r.cutoff).toBe("2000-01-03T10:30:00Z");
    expect(r.session.clock_at).toBe("2000-01-03T10:30:00Z");
    expect(r.lastWarningAt).toBe("2000-01-03T10:20:00Z");
    // and a warning issued after the snapshot's clock is never counted
    const leaked = queueRow(listed, snap(listed, [alert("b", "2000-01-03T10:05:00Z")]));
    expect([leaked.unreviewed, leaked.lastWarningAt]).toEqual([0, null]);
  });

  it("refuses parts that disagree on the clock", () => {
    const s = session();
    const x = snap(s);
    expect(queueRow(s, { ...x, alerts: { ...x.alerts, clock_at: "2000-01-03T10:05:00Z" } }).status).toBe("unavailable");
  });

  it("keeps an outcome resolved after the cutoff pending, consistently with the counts", () => {
    const s = session({ clock_at: "2000-01-03T10:00:00Z" });
    const a = alert("a", "2000-01-03T09:00:00Z", false, {
      outcome: { status: "onset_observed", onset_at: "2000-01-03T09:50:00Z", confirmed_at: "2000-01-03T10:05:00Z" } });
    const r = queueRow(s, snap(s, [a]));
    expect(r.lastOutcome).toBe("Outcome pending at the cutoff");
    expect(r.unreviewed).toBe(1);
  });

  it("orders administratively, never by replay time across participants", () => {
    const early = session({ id: "e", patient_id: "SYN-A", patient_alias: "A", created_at: "2026-10-20T09:00:00Z" });
    const late = session({ id: "l", patient_id: "SYN-B", patient_alias: "B", created_at: "2026-10-20T10:00:00Z", clock_at: "2000-01-02T10:00:00Z" });
    const none = session({ id: "n", patient_id: "SYN-C", patient_alias: "C", created_at: "2026-10-20T11:00:00Z" });
    const pending = session({ id: "p", patient_id: "SYN-D", patient_alias: "D", created_at: "2026-10-20T08:00:00Z" });
    const rows = [
      // the earlier-started replay has the later replay-time warning; replay times of different people are not compared
      queueRow(early, snap(early, [alert("x", "2000-01-03T09:59:00Z", false, { session_id: "e" })])),
      queueRow(late, snap(late, [alert("y", "2000-01-02T09:00:00Z", false, { session_id: "l" })])),
      queueRow(none, snap(none)),
      queueRow(pending),
    ];
    expect(sortQueue(rows).map((r) => r.session.id)).toEqual(["l", "e", "p", "n"]);
    expect(sortQueue([...rows].reverse()).map((r) => r.session.id)).toEqual(["l", "e", "p", "n"]);
  });

  it("counts several replays of one participant as replays, not more patients", () => {
    const a = session({ id: "a" });
    const b = session({ id: "b" });
    const rows = [queueRow(a, snap(a)), queueRow(b, snap(b))];
    expect(summarizeQueue(rows).text).toBe("No replay has unreviewed warnings · 2 replays of 1 participant");
    expect(rows.map((r) => r.session.id)).toEqual(["a", "b"]);
  });

  it("names the input state of the latest forecast", () => {
    expect(inputState(latest(forecast()))).toBe("ok");
    expect(inputState(latest(null))).toBe("abstained");
    expect(inputState(latest(forecast({ quality: { status: "degraded", reasons: [] } })))).toBe("degraded");
    expect(inputState(undefined)).toBe("unknown");
  });
});
