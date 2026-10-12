import { History } from "lucide-react";
import { useSessions } from "@/state/replay";
import { useShell } from "@/components/shell/ShellContext";
import { Button, EmptyState, InlineNotice, PageHeader, Skeleton } from "@/components/ui";
import { SessionRows } from "./OverviewPage";

export function SessionsPage() {
  const sessions = useSessions();
  const shell = useShell();
  const items = sessions.data?.items ?? [];
  return (
    <>
      <PageHeader title="Replay sessions">
        Sessions held by the local API process. Opening one resumes it exactly where it is; nothing is renamed or deleted.
      </PageHeader>
      {sessions.isLoading ? <Skeleton h={160} /> : sessions.isError ? (
        <InlineNotice tone="danger" role="alert">Sessions could not be loaded: {(sessions.error as Error).message}</InlineNotice>
      ) : items.length === 0 ? (
        <EmptyState icon={History} title="No replay sessions yet"
          action={<Button variant="primary" onClick={() => shell.open("new-replay")}>Choose participant</Button>}>
          Sessions are kept in memory by the API and end when it restarts.
        </EmptyState>
      ) : (
        <SessionRows items={items} detailed />
      )}
      <p className="page-note">
        Replay time is the recording’s own timeline (study day and source clock time). “Started” is when the session was created on
        this computer, in your local time.
      </p>
    </>
  );
}
