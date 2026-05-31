/**
 * Typed, fetch-based client for the student-safe `/v1/play` API.
 *
 * Base URL resolution (first match wins):
 *   1. `?api=<base>` query param — handy for a standalone build pointed at a
 *      remote backend.
 *   2. `import.meta.env.VITE_API_BASE` — build-time override.
 *   3. `""` (same origin) — the default when the bundle is mounted by the
 *      backend, or proxied by the Vite dev server.
 */

import type {
  AnswerResult,
  Exercise,
  StudentSession,
  StudentStats,
} from "./types";

/** Error carrying the HTTP status so callers can branch on 404 / 410 / 409. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function resolveBase(): string {
  if (typeof window !== "undefined") {
    const override = new URLSearchParams(window.location.search).get("api");
    if (override) {
      return override.replace(/\/+$/, "");
    }
  }
  const envBase = import.meta.env.VITE_API_BASE;
  if (envBase) {
    return envBase.replace(/\/+$/, "");
  }
  return "";
}

const BASE = resolveBase();

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    // Network / CORS failure — surface as a status-0 ApiError.
    throw new ApiError(0, `Network request to ${path} failed`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Non-JSON error body; keep the status text.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** Create a new practice session. */
export function createSession(): Promise<StudentSession> {
  return request<StudentSession>("/v1/play/sessions", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

/** Draw the next exercise (re-shows the pending one on resume). */
export function getNext(sid: string): Promise<Exercise> {
  return request<Exercise>(
    `/v1/play/sessions/${encodeURIComponent(sid)}/next`,
    { method: "POST" },
  );
}

/**
 * Submit an answer. The client measures `elapsedSeconds` itself (via
 * `performance.now()`), as the API contract requires.
 */
export function submitAnswer(
  sid: string,
  answer: number,
  elapsedSeconds: number,
): Promise<AnswerResult> {
  return request<AnswerResult>(
    `/v1/play/sessions/${encodeURIComponent(sid)}/answers`,
    {
      method: "POST",
      body: JSON.stringify({ answer, elapsed_seconds: elapsedSeconds }),
    },
  );
}

/** Fetch student-safe aggregate statistics. */
export function getStats(sid: string): Promise<StudentStats> {
  return request<StudentStats>(
    `/v1/play/sessions/${encodeURIComponent(sid)}/stats`,
    { method: "GET" },
  );
}
