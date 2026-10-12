/**
 * Browser tests run against their own API and web server with throwaway session storage, so they never add replay
 * sessions or audit rows to the workspace you are using on :8000/:5173.
 */
import { tmpdir } from "node:os";
import { join } from "node:path";

export const API_PORT = Number(process.env.E2E_API_PORT ?? 8010);
export const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5180);
export const API = `http://127.0.0.1:${API_PORT}/api/v1`;
export const WEB = `http://127.0.0.1:${WEB_PORT}`;
export const VAR_DIR = process.env.E2E_VAR_DIR ?? join(tmpdir(), "glucotwin-e2e-var");
