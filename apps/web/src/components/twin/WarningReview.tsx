import { CircleCheck, TriangleAlert } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import type { Alert } from "@/api/types";
import { friendlyError } from "@/lib/apiErrors";
import { replayTime } from "@/lib/time";
import { Button, Dialog, InlineNotice } from "../ui";
import "@/styles/warning-review.css";

/** The API's limit for a review note (AcknowledgementRequest.note, max_length=500). */
export const NOTE_MAX = 500;

type Status = "idle" | "saving" | "error" | "stale";

/**
 * Review of one research warning, saved through the existing acknowledgement endpoint as a local session annotation.
 * The warning shown is the CURRENT revision's copy (its outcome can change while the dialog is open); the note is
 * plain text. Cancel never saves. A warning from an earlier revision (the replay was rewound or reset) is never
 * submitted: the dialog says so instead.
 */
export function WarningReviewDialog({ alert, current, revision, participant, trigger, outcome, onSave, onClose }: {
  /** the warning the reviewer opened (null = closed) */
  alert: Alert | null;
  /** the same warning in the current alert list, or undefined when it no longer exists */
  current: Alert | undefined;
  /** the session's current revision */
  revision: number | undefined;
  participant: string;
  trigger?: ReactNode;
  outcome?: ReactNode;
  onSave: (a: Alert, note: string | undefined) => Promise<unknown>;
  onClose: () => void;
}) {
  const [note, setNote] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const noteId = useId();
  const hintId = useId();
  const countId = useId();
  const inFlight = useRef(false);
  const openId = alert?.alert_id ?? null;

  // a new warning starts from an empty note; never carry text across warnings
  useEffect(() => {
    setNote("");
    setStatus("idle");
    setError("");
  }, [openId]);

  // the replay was rewound or reset while the dialog was open: drop the unsaved note, never submit the old warning
  const stale = !!alert && (current === undefined || alert.session_revision !== revision || current.session_revision !== revision);
  useEffect(() => {
    if (stale && status !== "stale") {
      setStatus("stale");
      setNote("");
    }
  }, [stale, status]);

  const save = async () => {
    if (!alert || !current || inFlight.current || stale) return;
    inFlight.current = true;
    setStatus("saving");
    setError("");
    try {
      const text = note.trim();
      await onSave(current, text ? text : undefined);
      setStatus("idle");
      setNote("");
      onClose();
    } catch (e) {
      setStatus("error"); // the typed note stays in the field for a retry
      setError(friendlyError(e));
    } finally {
      inFlight.current = false;
    }
  };

  const shown = current ?? alert;
  const saving = status === "saving";
  return (
    <Dialog open={!!alert} onClose={() => { if (!saving) onClose(); }} title="Review research warning" width={520}
      description={shown ? <>{participant} · issued {replayTime(shown.issued_at)}</> : undefined}
      footer={status === "stale" ? (
        <Button variant="primary" onClick={onClose}>Close</Button>
      ) : (
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button variant="primary" onClick={save} busy={saving} disabled={!current}>
            {saving ? "Saving…" : status === "error" ? "Try again" : "Save review"}
          </Button>
        </>
      )}>
      {shown && (
        <div className="wreview">
          <dl className="wreview__facts">
            <div><dt>Warning</dt><dd>{shown.title}</dd></div>
            {trigger && <div><dt>Trigger</dt><dd>{trigger}</dd></div>}
            <div><dt>Outcome so far</dt><dd>{outcome}</dd></div>
          </dl>
          {status === "stale" ? (
            <InlineNotice tone="attention" icon={TriangleAlert} role="alert">
              The replay was rewound or reset, so this warning is no longer part of the current replay. Nothing was saved.
            </InlineNotice>
          ) : (
            <div className="field wreview__field">
              <label htmlFor={noteId}>Review note (optional)</label>
              <textarea id={noteId} className="input wreview__note" rows={4} maxLength={NOTE_MAX} value={note}
                onChange={(e) => setNote(e.target.value)} disabled={saving} aria-describedby={`${hintId} ${countId}`} />
              <div className="wreview__meta">
                <span id={hintId} className="hint">Plain text, kept in this local research session. Not an order, not advice
                  and not a message to anyone. A saved note cannot be edited.</span>
                <span id={countId} className="hint num" aria-live="polite">{note.length} / {NOTE_MAX}</span>
              </div>
            </div>
          )}
          {status === "error" && (
            <InlineNotice tone="danger" icon={TriangleAlert} role="alert">
              Could not save the review: {error}. Your note is kept; try again.
            </InlineNotice>
          )}
        </div>
      )}
    </Dialog>
  );
}

/** A saved review, read-only. The note is rendered as text (React escapes it); the time is the computer's clock. */
export function SavedReview({ a }: { a: Alert }) {
  const ack = a.acknowledgement;
  const at = ack.acknowledged_at ? new Date(ack.acknowledged_at) : null;
  return (
    <div className="wreview-saved">
      <span className="warn__acked"><CircleCheck size={13} aria-hidden /> Marked as reviewed
        {at && !Number.isNaN(at.getTime()) && (
          <span className="wreview-saved__at"> · saved {at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} computer time</span>
        )}
      </span>
      {ack.note && <p className="wreview-saved__note">{ack.note}</p>}
    </div>
  );
}
