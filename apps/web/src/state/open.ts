import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { useClient } from "@/api/client";
import type { ReplayMode, ReplaySessionList } from "@/api/types";
import { friendlyError } from "@/lib/apiErrors";
import { paths } from "@/lib/routes";
import { useDeployment } from "./deployment";
import { usePreferences } from "./preferences";
import { useToast } from "./toasts";

/** Create a replay session explicitly (New replay). */
export function useCreateReplay() {
  const client = useClient();
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const { prefs } = usePreferences();
  const { publicDemo } = useDeployment();
  return useMutation({
    mutationFn: (a: { patientId: string; mode: ReplayMode; startAt?: string }) =>
      client.createSession(a.patientId, a.mode, { start_at: a.startAt, speed: prefs.defaultSpeed }),
    onSuccess: (s) => {
      qc.setQueryData(["session", s.id], s);
      qc.invalidateQueries({ queryKey: ["sessions"] });
      toast(`Replay started for ${s.patient_alias}`);
      nav(paths.session(s.id));
    },
    onError: (e: Error) => toast(`Could not start the replay: ${friendlyError(e, publicDemo)}`, "error"),
  });
}

/** Open a participant's twin: resume their most recent local session, or create one. */
export function useOpenTwin() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const create = useCreateReplay();
  return {
    isPending: create.isPending,
    open: (patientId: string, mode: ReplayMode) => {
      const list = qc.getQueryData<ReplaySessionList>(["sessions"]);
      const existing = list?.items.find((s) => s.patient_id === patientId);
      if (existing) nav(paths.session(existing.id));
      else create.mutate({ patientId, mode });
    },
  };
}
