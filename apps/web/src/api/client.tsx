import { createContext, useContext, type ReactNode } from "react";
import type {
  Alert,
  AlertList,
  ControlCommand,
  DatasetInventory,
  EvaluationList,
  EvaluationReport,
  EventPage,
  ForecastPage,
  Health,
  LatestForecast,
  PatientDetail,
  PatientPage,
  Readiness,
  ReplayMode,
  ReplaySession,
  ReplaySessionList,
  ResearchReport,
  ResearchSummaryList,
  ServingList,
  SessionProfile,
  TwinState,
} from "./types";

export type PatientQuery = {
  mode?: ReplayMode; cohort?: string; eligible?: boolean; q?: string;
  sort?: "alias" | "recording_days" | "coverage" | "meals"; order?: "asc" | "desc"; limit?: number; cursor?: string | null;
};
import { defaultTransport, type Transport } from "./transport";

export function createClient(t: Transport) {
  const get = <T,>(p: string, signal?: AbortSignal) => t.request<T>("GET", p, undefined, signal);
  const post = <T,>(p: string, body?: unknown) => t.request<T>("POST", p, body ?? {});
  const q = (o: Record<string, string | number | undefined | null>) => {
    const s = new URLSearchParams();
    for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
    const str = s.toString();
    return str ? `?${str}` : "";
  };
  return {
    transportKind: t.kind,
    health: (signal?: AbortSignal) => get<Health>("/health", signal),
    readiness: (signal?: AbortSignal) => get<Readiness>("/health/ready", signal),
    patients: (signal?: AbortSignal) => get<PatientPage>(`/patients${q({ limit: 200 })}`, signal),
    patientPage: (p: PatientQuery, signal?: AbortSignal) =>
      get<PatientPage>(`/patients${q({ ...p, eligible: p.eligible === undefined ? undefined : String(p.eligible) })}`, signal),
    patient: (id: string, signal?: AbortSignal) => get<PatientDetail>(`/patients/${encodeURIComponent(id)}`, signal),
    sessions: (signal?: AbortSignal) => get<ReplaySessionList>(`/replay/sessions${q({ limit: 50 })}`, signal),
    createSession: (patient_id: string, mode: ReplayMode, opts: { start_at?: string; speed?: number } = {}) =>
      post<ReplaySession>("/replay/sessions", { patient_id, mode, ...opts }),
    session: (sid: string, signal?: AbortSignal) => get<ReplaySession>(`/replay/sessions/${sid}`, signal),
    control: (sid: string, cmd: ControlCommand) => post<ReplaySession>(`/replay/sessions/${sid}/control`, cmd),
    events: (sid: string, cursor: string | null, signal?: AbortSignal) =>
      get<EventPage>(`/replay/sessions/${sid}/events${q({ cursor, limit: 2000 })}`, signal),
    profile: (sid: string, signal?: AbortSignal) => get<SessionProfile>(`/replay/sessions/${sid}/profile`, signal),
    twin: (sid: string, signal?: AbortSignal) => get<TwinState>(`/replay/sessions/${sid}/twin`, signal),
    forecast: (sid: string, signal?: AbortSignal) => get<LatestForecast>(`/replay/sessions/${sid}/forecast`, signal),
    forecasts: (sid: string, limit: number, signal?: AbortSignal) =>
      get<ForecastPage>(`/replay/sessions/${sid}/forecasts${q({ limit, order: "desc" })}`, signal),
    alerts: (sid: string, signal?: AbortSignal) => get<AlertList>(`/replay/sessions/${sid}/alerts`, signal),
    acknowledge: (sid: string, alertId: string, note?: string) =>
      post<Alert>(`/replay/sessions/${sid}/alerts/${alertId}/acknowledgement`, note ? { note } : {}),
    evaluation: (signal?: AbortSignal) => get<EvaluationReport>("/evaluations/latest", signal),
    evaluations: (signal?: AbortSignal) => get<EvaluationList>("/evaluations", signal),
    evaluationById: (id: string, signal?: AbortSignal) =>
      get<EvaluationReport>(`/evaluations/${encodeURIComponent(id)}`, signal),
    research: (id: string, signal?: AbortSignal) => get<ResearchReport>(`/research/${encodeURIComponent(id)}`, signal),
    researchSummaries: (signal?: AbortSignal) => get<ResearchSummaryList>("/research-summaries", signal),
    serving: (signal?: AbortSignal) => get<ServingList>("/serving", signal),
    datasets: (signal?: AbortSignal) => get<DatasetInventory>("/datasets", signal),
  };
}

export type Client = ReturnType<typeof createClient>;

const ClientContext = createContext<Client | null>(null);

export function ClientProvider({ client, children }: { client?: Client; children: ReactNode }) {
  return <ClientContext.Provider value={client ?? createClient(defaultTransport())}>{children}</ClientContext.Provider>;
}

export function useClient(): Client {
  const c = useContext(ClientContext);
  if (!c) throw new Error("ClientProvider missing");
  return c;
}
