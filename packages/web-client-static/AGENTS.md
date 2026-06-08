# AGENTS.md — web-client-static ("Math Meadow")

React 18 + Vite + TypeScript (strict) SPA. **Managed with `npm`, not `uv`** — it
is excluded from the uv workspace.

## Commands

```bash
npm install
npm run dev        # Vite dev server :5173, proxies /v1 -> http://127.0.0.1:8000
npm run typecheck  # tsc --noEmit
npm run build      # tsc -b && vite build  -> dist/
```

## Boundaries

### Always Do
- Talk **only** to the student-safe `/v1/play` API (typed client in `src/api`).
- Measure answer time with `performance.now()`; send `elapsed_seconds`.
- Bundle fonts via `@fontsource` (no CDN); keep design tokens in `src/styles`.
- Send the Firebase ID token as `Authorization: Bearer` for authed requests.

### Ask First
- Adding npm dependencies; changing the Firebase config or enabled providers.

### Never Do
- Render or fetch engine internals (θ, mastery/total counts, score `s`,
  predicted success `E`). The student must never see them.
- Run `uv` against this package.

## Architecture

- `src/firebase.ts` — the **only** Firebase SDK importer (email/password +
  Google helpers, `observeAuth`, `getIdToken`). Config is public, env-overridable
  via `VITE_FIREBASE_*`.
- `src/api/` — typed `/v1/play` client + types; `setAuthToken` injects the bearer
  header with a 401-refresh retry. `VITE_API_BASE` (build-time) or `?api=`
  (runtime) sets the API origin; default is same-origin.
- Auth flow: on login, `claimAnonymous(localStorage learner)` merges anonymous
  progress, then switches to the user's learner.
- `session_id` persists in `localStorage` for 24h resume.

## Tool-Specific Instructions
- The repo root `CLAUDE.md` holds Claude Code-specific guidance and the global
  architecture.
