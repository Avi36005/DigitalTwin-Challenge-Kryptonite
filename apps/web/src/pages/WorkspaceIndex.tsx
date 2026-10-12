import { useSearchParams } from "react-router";
import { OverviewPage } from "./OverviewPage";
import { ReplayPage } from "./ReplayPage";

/** /app shows the overview; /app?session=<id> opens that replay (the session is never created or reset here). */
export function WorkspaceIndex() {
  const [params] = useSearchParams();
  const sid = params.get("session");
  return sid ? <ReplayPage key={sid} sid={sid} /> : <OverviewPage />;
}
