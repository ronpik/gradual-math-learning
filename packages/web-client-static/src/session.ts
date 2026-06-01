/**
 * localStorage persistence for two distinct things:
 *
 *  1. The active **run context** (key "math-meadow.session"), with a 24h resume
 *     window. It carries everything needed to rehydrate the right HUD on a
 *     refresh: the session id plus the module/mode and the mode's stop-rule
 *     params. Sessions expire server-side (the client treats 404/410 as "start
 *     fresh"), but we also locally drop a stored run once it is older than 24h.
 *
 *  2. The long-lived **learner id** (key "math-meadow.learner"), with NO TTL.
 *     This is the persistent learner identity; the server seeds per-(learner,
 *     module) progress from it, so it must outlive any single run.
 *
 * All operations are non-fatal: quota / parse / sandboxed-storage failures
 * return null or no-op rather than throwing.
 */

const RUN_KEY = "math-meadow.session";
const LEARNER_KEY = "math-meadow.learner";
const TTL_MS = 24 * 60 * 60 * 1000;

/** The active run context needed to resume into "playing" with the right HUD. */
export interface RunContext {
  sessionId: string;
  moduleId: string;
  mode: string;
  targetCount: number | null;
  targetSeconds: number | null;
  deadline: string | null;
}

interface StoredRun extends RunContext {
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

/* ------------------------------------------------------------------ */
/* Run store (24h TTL)                                                 */
/* ------------------------------------------------------------------ */

/** Persist the active run context with the current timestamp. */
export function saveRun(ctx: RunContext): void {
  const store = storage();
  if (!store) {
    return;
  }
  const payload: StoredRun = { ...ctx, savedAt: Date.now() };
  try {
    store.setItem(RUN_KEY, JSON.stringify(payload));
  } catch {
    // Quota / serialization failure — non-fatal.
  }
}

/** Read a still-fresh (<24h) run context, or `null`. Prunes stale entries. */
export function readRun(): RunContext | null {
  const store = storage();
  if (!store) {
    return null;
  }
  const raw = store.getItem(RUN_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<StoredRun>;
    if (
      typeof parsed.sessionId !== "string" ||
      typeof parsed.moduleId !== "string" ||
      typeof parsed.mode !== "string" ||
      typeof parsed.savedAt !== "number"
    ) {
      clearRun();
      return null;
    }
    if (Date.now() - parsed.savedAt > TTL_MS) {
      clearRun();
      return null;
    }
    return {
      sessionId: parsed.sessionId,
      moduleId: parsed.moduleId,
      mode: parsed.mode,
      targetCount:
        typeof parsed.targetCount === "number" ? parsed.targetCount : null,
      targetSeconds:
        typeof parsed.targetSeconds === "number" ? parsed.targetSeconds : null,
      deadline: typeof parsed.deadline === "string" ? parsed.deadline : null,
    };
  } catch {
    clearRun();
    return null;
  }
}

/** Remove any persisted run context. */
export function clearRun(): void {
  const store = storage();
  if (!store) {
    return;
  }
  try {
    store.removeItem(RUN_KEY);
  } catch {
    // Non-fatal.
  }
}

/* ------------------------------------------------------------------ */
/* Learner store (no TTL)                                              */
/* ------------------------------------------------------------------ */

/** Persist the long-lived learner id (overwrites any previous value). */
export function saveLearnerId(id: string): void {
  const store = storage();
  if (!store) {
    return;
  }
  try {
    store.setItem(LEARNER_KEY, id);
  } catch {
    // Quota failure — non-fatal.
  }
}

/** Read the persisted learner id, or `null` if none / storage unavailable. */
export function readLearnerId(): string | null {
  const store = storage();
  if (!store) {
    return null;
  }
  try {
    const id = store.getItem(LEARNER_KEY);
    return id && id.length > 0 ? id : null;
  } catch {
    return null;
  }
}

/** Remove any persisted learner id. */
export function clearLearnerId(): void {
  const store = storage();
  if (!store) {
    return;
  }
  try {
    store.removeItem(LEARNER_KEY);
  } catch {
    // Non-fatal.
  }
}
