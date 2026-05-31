/**
 * TypeScript shapes mirroring the student-safe `/v1/play` API.
 *
 * These intentionally contain ONLY the fields the endpoints return — counts,
 * percentages, streaks, and timing. None of the engine internals (theta,
 * mastered_count, total, score `s`, predicted success `E`) ever reach the
 * client, so they are absent here too.
 *
 * Datetime fields are ISO-8601 strings over the wire.
 */

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
  expires_at: string;
}

/** Result of submitting an answer — `POST /v1/play/sessions/{sid}/answers`. */
export interface AnswerResult {
  correct: boolean;
  questions_done: number;
  module_completion_percent: number;
  streak: number;
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
