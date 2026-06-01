/**
 * TypeScript shapes mirroring the student-safe `/v1/play` API.
 *
 * These intentionally contain ONLY the fields the endpoints return — counts,
 * percentages, streaks, timing, and module/mode descriptors. None of the engine
 * internals (theta, mastered_count, total, score `s`, predicted success `E`)
 * ever reach the client, so they are absent here too.
 *
 * Datetime fields are ISO-8601 strings over the wire.
 */

/** A practice module — `GET /v1/play/modules`. One operation × one range. */
export interface ModuleDescriptor {
  id: string;
  op: string;
  range_bound: number;
  label: string;
  levels: number[];
}

/** A practice mode — `GET /v1/play/modes`. Mode = stop-rule + headline metric. */
export interface ModeDescriptor {
  id: string;
  label: string;
  description: string;
}

/** A drawn (pending) exercise — `POST /v1/play/sessions/{sid}/next`. */
export interface Exercise {
  a: number;
  b: number;
  op: string;
  issued_at: string;
}

/** A freshly created play session — `POST /v1/play/sessions`. */
export interface StudentSession {
  session_id: string;
  learner_id: string;
  module_id: string;
  mode: string;
  started_at: string;
  expires_at: string;
  target_count: number | null;
  target_seconds: number | null;
  deadline: string | null;
}

/** Result of submitting an answer — `POST /v1/play/sessions/{sid}/answers`. */
export interface AnswerResult {
  correct: boolean;
  questions_done: number;
  module_completion_percent: number;
  streak: number;
  finished: boolean;
  seconds_left: number | null;
  questions_left: number | null;
}

/** Per-level mastery progress, surfaced in the summary as stars. */
export interface LevelProgress {
  level: number;
  mastered: number;
  total: number;
}

/** End-of-run summary — `GET /v1/play/sessions/{sid}/summary`. */
export interface Summary {
  module_id: string;
  label: string;
  mode: string;
  status: string;
  questions_done: number;
  correct: number;
  accuracy: number;
  total_time_seconds: number;
  avg_time_seconds: number;
  headline: Record<string, number>;
  personal_best: number | null;
  is_new_best: boolean;
  levels: LevelProgress[];
}

/** Aggregate stats — `GET /v1/play/sessions/{sid}/stats`. */
export interface StudentStats {
  questions_done: number;
  correct: number;
  accuracy: number;
  total_time_seconds: number;
  avg_time_seconds: number;
  module_completion_percent: number;
  streak: number;
}
