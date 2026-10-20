import { useQuery } from "@tanstack/react-query";
import { useClient } from "@/api/client";
import type { PublicDemoLimits } from "@/api/types";

export type Deployment = { publicDemo: boolean; limits: PublicDemoLimits | null; known: boolean };

/** Local installation or public synthetic demonstration, from GET /health. Unknown or unreachable reads as local:
 *  the API itself refuses recorded data in a public demo, so the UI never relies on this for enforcement. */
export function useDeployment(): Deployment {
  const client = useClient();
  const q = useQuery({ queryKey: ["health"], queryFn: ({ signal }) => client.health(signal), staleTime: Infinity,
    retry: false });
  const publicDemo = q.data?.public_demo === true;
  return { publicDemo, limits: publicDemo ? q.data?.public_demo_limits ?? null : null, known: q.isSuccess || q.isError };
}

/** Why recorded-data replays are missing here (one sentence, reused wherever the choice would appear). */
export const RECORDED_UNAVAILABLE =
  "Recorded-data replays run only on a local installation: each user downloads the CGMacros dataset, and this public demonstration does not redistribute it.";
