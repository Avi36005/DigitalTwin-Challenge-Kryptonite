import { useDeployment } from "@/state/deployment";

/** Slim, persistent notice on every page of the hosted public demonstration; renders nothing on a local installation. */
export function PublicDemoBanner() {
  const { publicDemo, limits } = useDeployment();
  if (!publicDemo) return null;
  const idle = limits?.session_idle_minutes;
  return (
    <div className="demo-banner" role="note" aria-label="Public synthetic demonstration">
      <strong>Public synthetic demonstration</strong> — fictional participants and a synthetic demonstration model, not the
      evaluated real-data fusion model. Replays are private to this browser
      {idle ? <> and expire after <span className="num">{idle}</span> minutes of inactivity</> : null}. Research prototype — not a
      medical device.
    </div>
  );
}
