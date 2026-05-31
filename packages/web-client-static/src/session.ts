/**
 * localStorage persistence for the active session id, with a 24h resume window.
 *
 * Sessions expire server-side (the client treats 404/410 as "start fresh"), but
 * we also locally drop a stored id once it is older than 24h so a returning
 * learner does not flash a stale session before the server rejects it.
 */

const KEY = "math-meadow.session";
const TTL_MS = 24 * 60 * 60 * 1000;

interface StoredSession {
  sessionId: string;
  savedAt: number;
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    // localStorage can throw in private-mode / sandboxed contexts.
    return null;
  }
}

/** Persist the active session id with the current timestamp. */
export function saveSessionId(sessionId: string): void {
  const store = storage();
  if (!store) {
    return;
  }
  const payload: StoredSession = { sessionId, savedAt: Date.now() };
  try {
    store.setItem(KEY, JSON.stringify(payload));
  } catch {
    // Quota / serialization failure — non-fatal.
  }
}

/** Read a still-fresh (<24h) session id, or `null`. Prunes stale entries. */
export function readSessionId(): string | null {
  const store = storage();
  if (!store) {
    return null;
  }
  const raw = store.getItem(KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (
      typeof parsed.sessionId !== "string" ||
      typeof parsed.savedAt !== "number"
    ) {
      clearSessionId();
      return null;
    }
    if (Date.now() - parsed.savedAt > TTL_MS) {
      clearSessionId();
      return null;
    }
    return parsed.sessionId;
  } catch {
    clearSessionId();
    return null;
  }
}

/** Remove any persisted session id. */
export function clearSessionId(): void {
  const store = storage();
  if (!store) {
    return;
  }
  try {
    store.removeItem(KEY);
  } catch {
    // Non-fatal.
  }
}
