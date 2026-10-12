/**
 * Transport abstraction. The real transport talks to the local API; the fixture transport serves the
 * schema-validated example payloads in packages/contracts/examples and is ONLY used when explicitly
 * enabled (VITE_GLUCOTWIN_TRANSPORT=fixtures). A failed real request is never replaced by fixtures.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string | null;
  constructor(status: number, code: string, message: string, requestId?: string | null) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export interface Transport {
  readonly kind: "http" | "fixtures";
  request<T>(method: "GET" | "POST", path: string, body?: unknown, signal?: AbortSignal): Promise<T>;
}

export function httpTransport(base = import.meta.env.VITE_API_BASE ?? ""): Transport {
  return {
    kind: "http",
    async request<T>(method: "GET" | "POST", path: string, body?: unknown, signal?: AbortSignal) {
      let res: Response;
      try {
        res = await fetch(`${base}/api/v1${path}`, {
          method,
          signal,
          headers: body === undefined ? undefined : { "Content-Type": "application/json" },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
      } catch (e) {
        if ((e as Error).name === "AbortError") throw e;
        throw new ApiError(0, "api_unreachable", "The GlucoTwin API could not be reached.");
      }
      const text = await res.text();
      const data = text ? JSON.parse(text) : null;
      if (!res.ok) {
        const err = data?.error;
        throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `Request failed (${res.status})`,
          err?.request_id);
      }
      return data as T;
    },
  };
}

const fixtureFiles = import.meta.glob("../../../../packages/contracts/examples/*.json", { eager: true, import: "default" });

function fixture(name: string): unknown {
  const key = Object.keys(fixtureFiles).find((k) => k.endsWith(`/${name}`));
  if (!key) throw new ApiError(404, "fixture_missing", `Fixture ${name} not found`);
  return structuredClone(fixtureFiles[key]);
}

/** Static example payloads (synthetic). No replay happens in this mode. */
export function fixtureTransport(): Transport {
  return {
    kind: "fixtures",
    async request<T>(method: "GET" | "POST", path: string) {
      const patient = fixture("patient_detail_complete_synthetic.json") as { patient_id: string };
      const session = fixture("replay_session_synthetic_ready.json") as { id: string };
      if (path.startsWith("/health/ready")) {
        throw new ApiError(503, "fixture_mode", "Fixture transport: readiness is not available.");
      }
      if (path === "/patients" || path.startsWith("/patients?"))
        return { schema_version: "1.0", items: [patient], next_cursor: null, total: 1 } as T;
      if (path.startsWith("/patients/")) return patient as T;
      if (path.startsWith("/replay/sessions") && method === "POST" && !path.includes("/control")) return session as T;
      if (path === "/replay/sessions" || path.startsWith("/replay/sessions?"))
        return { schema_version: "1.0", items: [session] } as T;
      if (path.endsWith("/profile")) return fixture("session_profile_nullable_field_synthetic.json") as T;
      if (path.endsWith("/forecast")) return fixture("forecast_ok_synthetic.json") as T;
      if (path.includes("/forecasts")) {
        const f = fixture("forecast_ok_synthetic.json") as { forecast: unknown; session_id: string };
        return { schema_version: "1.0", session_id: session.id, session_revision: 1, clock_at: (f as any).clock_at,
          items: [f.forecast], next_cursor: null, order: "desc" } as T;
      }
      if (path.includes("/control")) return session as T;
      if (path.match(/\/replay\/sessions\/[^/]+$/)) return session as T;
      throw new ApiError(404, "fixture_missing", `No fixture for ${method} ${path}`);
    },
  };
}

export function defaultTransport(): Transport {
  return import.meta.env.VITE_GLUCOTWIN_TRANSPORT === "fixtures" ? fixtureTransport() : httpTransport();
}
