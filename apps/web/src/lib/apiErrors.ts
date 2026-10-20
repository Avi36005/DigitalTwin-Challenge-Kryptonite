import { ApiError } from "@/api/transport";
import { RECORDED_UNAVAILABLE } from "@/state/deployment";

export const EXPIRED_REPLAY = "This replay has expired or belongs to another browser.";

/** One sentence for an API failure. Rate limits and the public demonstration's synthetic-only rule are worded the same
 *  everywhere; a missing session is only described as expired or private in the public demonstration, where it can be. */
export function friendlyError(e: unknown, publicDemo = false): string {
  if (e instanceof ApiError) {
    if (e.status === 429 || e.code === "rate_limited") return "Too many requests; wait a moment and try again.";
    if (e.code === "public_demo_synthetic_only") return RECORDED_UNAVAILABLE;
    if (publicDemo && e.status === 404 && e.code === "session_not_found") return EXPIRED_REPLAY;
  }
  return e instanceof Error ? e.message : String(e);
}
