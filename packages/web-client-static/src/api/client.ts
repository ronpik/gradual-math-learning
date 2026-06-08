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
  ClaimResult,
  Exercise,
  Me,
  ModeDescriptor,
  ModuleDescriptor,
  StudentSession,
  StudentStats,
  Summary,
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

/**
 * Module-level Firebase ID token. `null` means anonymous play (no Authorization
 * header). `setAuthToken` is called by the auth flow on sign-in/out and after a
 * forced token refresh.
 */
let authToken: string | null = null;

/** Set (or clear, with `null`) the bearer token attached to every request. */
export function setAuthToken(token: string | null): void {
  authToken = token;
}

/**
 * Optional token-refresh hook. When set (by the auth layer to
 * `() => getIdToken(true)`), a request that gets a `401` will refresh the token
 * once and retry. Kept as an injected callback so this module stays free of any
 * Firebase import.
 */
let refreshToken: (() => Promise<string | null>) | null = null;

/** Register (or clear) the forced-refresh callback used on a 401. */
export function setTokenRefresher(
  fn: (() => Promise<string | null>) | null,
): void {
  refreshToken = fn;
}

async function send(path: string, init: RequestInit | undefined): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string> | undefined) ?? {}),
  };
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }
  return fetch(`${BASE}${path}`, { ...init, headers });
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await send(path, init);
  } catch {
    // Network / CORS failure — surface as a status-0 ApiError.
    throw new ApiError(0, `Network request to ${path} failed`);
  }

  // On a 401 while authed, refresh the token once and retry.
  if (response.status === 401 && authToken && refreshToken) {
    const fresh = await refreshToken();
    if (fresh) {
      authToken = fresh;
      try {
        response = await send(path, init);
      } catch {
        throw new ApiError(0, `Network request to ${path} failed`);
      }
    }
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

/** List the available practice modules for the main screen. */
export function listModules(): Promise<ModuleDescriptor[]> {
  return request<ModuleDescriptor[]>("/v1/play/modules", { method: "GET" });
}

/** List the available practice modes for the main screen. */
export function listModes(): Promise<ModeDescriptor[]> {
  return request<ModeDescriptor[]>("/v1/play/modes", { method: "GET" });
}

/**
 * Create a new practice run for a module + mode. `learnerId` is the long-lived
 * learner identity (or `null` on first ever visit; the server mints one and
 * returns it on the session).
 */
export function createSession(params: {
  learnerId: string | null;
  moduleId: string;
  mode: string;
}): Promise<StudentSession> {
  return request<StudentSession>("/v1/play/sessions", {
    method: "POST",
    body: JSON.stringify({
      learner_id: params.learnerId,
      module_id: params.moduleId,
      mode: params.mode,
    }),
  });
}

/**
 * Draw the next exercise (re-shows the pending one on resume).
 *
 * A `409` means the run's stop rule is already met — it surfaces as
 * `ApiError(409)` and is NOT swallowed; the caller navigates to the summary.
 */
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

/** Fetch the end-of-run summary (headline, personal best, per-level stars). */
export function getSummary(sid: string): Promise<Summary> {
  return request<Summary>(
    `/v1/play/sessions/${encodeURIComponent(sid)}/summary`,
    { method: "GET" },
  );
}

/** Fetch student-safe aggregate statistics. */
export function getStats(sid: string): Promise<StudentStats> {
  return request<StudentStats>(
    `/v1/play/sessions/${encodeURIComponent(sid)}/stats`,
    { method: "GET" },
  );
}

/**
 * Resolve the signed-in user's identity (their account learner + email).
 * Requires a valid auth token; a 401 surfaces as `ApiError(401)`.
 */
export function getMe(): Promise<Me> {
  return request<Me>("/v1/play/me", { method: "GET" });
}

/**
 * Merge an anonymous learner's progress into the signed-in user's learner and
 * return the user's learner id. Requires a valid auth token. Idempotent on the
 * server, so the client may call it once per sign-in safely.
 */
export function claimAnonymous(
  anonymousLearnerId: string,
): Promise<ClaimResult> {
  return request<ClaimResult>("/v1/play/claim", {
    method: "POST",
    body: JSON.stringify({ anonymous_learner_id: anonymousLearnerId }),
  });
}
