/**
 * Replay state hooks. The backend owns the clock; the browser only reads.
 *
 * Every session-dependent cache key contains (session id, revision, clock). Responses whose
 * session_revision differs from the current revision are rejected, so a late response from before a
 * seek/reset can never overwrite the rebuilt state.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useClient, type PatientQuery } from "@/api/client";
import { ApiError } from "@/api/transport";
import type { ControlCommand, ObservationEvent, ReplaySession } from "@/api/types";

export function useReadiness() {
  const client = useClient();
  return useQuery({
    queryKey: ["readiness"],
    queryFn: ({ signal }) => client.readiness(signal),
    retry: 0,
    refetchInterval: (q) => (q.state.status === "error" ? 5000 : 60_000),
  });
}

export function usePatients() {
  const client = useClient();
  return useQuery({ queryKey: ["patients"], queryFn: ({ signal }) => client.patients(signal), staleTime: 30_000 });
}

/** One server-filtered, server-sorted page of participants; ``total`` counts every match. */
export function usePatientPage(p: PatientQuery) {
  const client = useClient();
  return useQuery({
    queryKey: ["patients", "page", p],
    queryFn: ({ signal }) => client.patientPage(p, signal),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function usePatient(id: string | null | undefined) {
  const client = useClient();
  return useQuery({
    queryKey: ["patient", id],
    queryFn: ({ signal }) => client.patient(id!, signal),
    enabled: !!id,
    staleTime: 60_000,
  });
}

export function useSessions() {
  const client = useClient();
  return useQuery({
    queryKey: ["sessions"],
    queryFn: ({ signal }) => client.sessions(signal),
    refetchInterval: 4000,
  });
}

export function useSession(sid: string | null | undefined) {
  const client = useClient();
  return useQuery({
    queryKey: ["session", sid],
    queryFn: ({ signal }) => client.session(sid!, signal),
    enabled: !!sid,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 1,
    refetchInterval: (q) => (q.state.data?.status === "playing" ? 1000 : false),
  });
}

type Scoped = readonly [string, string | undefined, number | undefined, string | undefined];

function scopedKey(name: string, s: ReplaySession | undefined): Scoped {
  return [name, s?.id, s?.revision, s?.clock_at] as const;
}

function useScoped<T extends { session_revision: number }>(
  name: string,
  s: ReplaySession | undefined,
  fn: (sid: string, signal: AbortSignal) => Promise<T>,
) {
  const q = useQuery<T, Error, T, Scoped>({
    queryKey: scopedKey(name, s),
    queryFn: ({ signal }) => fn(s!.id, signal),
    enabled: !!s,
    staleTime: Infinity,
    // keep previous data only while the session and revision are unchanged (avoids flicker, never leaks)
    placeholderData: (prev, prevQuery) => {
      const k = prevQuery?.queryKey;
      return k && s && k[1] === s.id && k[2] === s.revision ? prev : undefined;
    },
  });
  // reject responses that belong to another revision of this session
  const data = q.data && s && q.data.session_revision === s.revision ? q.data : undefined;
  return { ...q, data };
}

export function useLatestForecast(s: ReplaySession | undefined) {
  const client = useClient();
  return useScoped("forecast", s, (sid, signal) => client.forecast(sid, signal));
}

export function useForecastHistory(s: ReplaySession | undefined, limit = 144) {
  const client = useClient();
  return useScoped(`forecasts:${limit}`, s, (sid, signal) => client.forecasts(sid, limit, signal));
}

export function useAlerts(s: ReplaySession | undefined) {
  const client = useClient();
  return useScoped("alerts", s, (sid, signal) => client.alerts(sid, signal));
}

export function useTwin(s: ReplaySession | undefined) {
  const client = useClient();
  return useScoped("twin", s, (sid, signal) => client.twin(sid, signal));
}

export function useSessionProfile(s: ReplaySession | undefined) {
  const client = useClient();
  return useScoped("profile", s, (sid, signal) => client.profile(sid, signal));
}

/**
 * Accumulate released events with cursor polling. Deduplicated by event_id, reset on a new revision
 * or session, restarted on a stale-cursor (409) response. Never accumulates duplicates on re-render.
 */
export function useReleasedEvents(s: ReplaySession | undefined) {
  const client = useClient();
  const store = useRef<{ key: string; byId: Map<string, ObservationEvent>; cursor: string | null }>({
    key: "",
    byId: new Map(),
    cursor: null,
  });
  const [events, setEvents] = useState<ObservationEvent[]>([]);
  const [error, setError] = useState<Error | null>(null);
  // Key of the session revision whose released events have been fetched completely at least once. Until then the
  // UI must show a loading state rather than "no observation released".
  const [loadedKey, setLoadedKey] = useState("");
  const key = s ? `${s.id}:${s.revision}` : "";
  const target = s?.released_event_count ?? 0;
  const sid = s?.id;
  const revision = s?.revision;

  useEffect(() => {
    if (!sid || revision === undefined) {
      store.current = { key: "", byId: new Map(), cursor: null };
      setEvents([]);
      return;
    }
    if (store.current.key !== key) {
      store.current = { key, byId: new Map(), cursor: null };
      setEvents([]);
    }
    if (store.current.byId.size >= target && store.current.cursor !== null) return;
    const ctrl = new AbortController();
    let cancelled = false;
    (async () => {
      try {
        for (let guard = 0; guard < 50; guard++) {
          const page = await client.events(sid, store.current.cursor, ctrl.signal);
          if (cancelled || store.current.key !== key || page.session_revision !== revision) return;
          for (const e of page.items) store.current.byId.set(e.event_id, e);
          store.current.cursor = page.next_cursor;
          if (!page.has_more) break;
        }
        if (!cancelled) {
          setEvents(Array.from(store.current.byId.values()));
          setLoadedKey(key);
          setError(null);
        }
      } catch (e) {
        if (cancelled || (e as Error).name === "AbortError") return;
        if (e instanceof ApiError && e.status === 409) {
          store.current = { key, byId: new Map(), cursor: null }; // stale cursor: restart from the beginning
          setEvents([]);
        } else setError(e as Error);
      }
    })();
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [client, key, target, sid, revision]);

  return { events, error, revisionKey: key, loaded: key !== "" && loadedKey === key };
}

export function useControl(sid: string | undefined) {
  const client = useClient();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["control", sid],
    mutationFn: (cmd: ControlCommand) => client.control(sid!, cmd),
    onSuccess: (session) => {
      qc.setQueryData(["session", session.id], session);
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}
