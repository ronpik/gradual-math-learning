import { useEffect, useId, useRef, useState } from "react";
import type { JSX } from "react";
import { motion } from "framer-motion";

import { getStats } from "../api/client";
import type { StudentStats } from "../api/types";

/** Accuracy may arrive as a 0-1 fraction or a 0-100 percent; normalise. */
function formatAccuracy(accuracy: number): string {
  const pct = accuracy <= 1 ? accuracy * 100 : accuracy;
  return `${Math.round(pct)}%`;
}

function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) {
    return `${s}s`;
  }
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem === 0 ? `${m}m` : `${m}m ${rem}s`;
}

/**
 * Accessible stats dialog: focus trap, Esc-to-close, aria-modal, spring in/out.
 * Fetches fresh stats from the student-safe endpoint each time it opens. Only
 * student-safe figures are shown (done, accuracy, time, streak) — never any
 * engine internals.
 */
export function StatsModal({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}): JSX.Element {
  const titleId = useId();
  const descId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const [stats, setStats] = useState<StudentStats | null>(null);
  const [error, setError] = useState(false);

  // Fetch on open.
  useEffect(() => {
    let alive = true;
    setStats(null);
    setError(false);
    getStats(sessionId)
      .then((s) => {
        if (alive) {
          setStats(s);
        }
      })
      .catch(() => {
        if (alive) {
          setError(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [sessionId]);

  // Remember the trigger, focus the close button, restore on unmount.
  useEffect(() => {
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => {
      restoreFocusRef.current?.focus?.();
    };
  }, []);

  // Esc to close + focus trap.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") {
        return;
      }
      const root = dialogRef.current;
      if (!root) {
        return;
      }
      const focusable = root.querySelectorAll<HTMLElement>(
        'button, [href], input, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <motion.div
      className="scrim"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
    >
        <motion.div
          ref={dialogRef}
          className="modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={descId}
          initial={{ scale: 0.85, opacity: 0, y: 12 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.9, opacity: 0, y: 12 }}
          transition={{ type: "spring", stiffness: 320, damping: 24 }}
        >
          <div className="modal__head">
            <h2 className="modal__title" id={titleId}>
              Your stats
            </h2>
            <button
              ref={closeRef}
              type="button"
              className="icon-btn"
              onClick={onClose}
              aria-label="Close stats"
            >
              ✕
            </button>
          </div>

          <p id={descId} className="sr-only">
            A summary of your practice this session.
          </p>

          {error ? (
            <p className="modal__error">
              Couldn&rsquo;t load your stats right now. Try again in a moment.
            </p>
          ) : !stats ? (
            <div className="modal__loading">
              <span className="sr-only">Loading stats</span>
              <div className="spinner" style={{ margin: "0 auto" }} />
            </div>
          ) : (
            <div className="stats-grid">
              <div className="stat">
                <span className="stat__value">{stats.questions_done}</span>
                <span className="stat__label">Done</span>
              </div>
              <div className="stat">
                <span className="stat__value">
                  {formatAccuracy(stats.accuracy)}
                </span>
                <span className="stat__label">Accuracy</span>
              </div>
              <div className="stat">
                <span className="stat__value">
                  {formatDuration(stats.total_time_seconds)}
                </span>
                <span className="stat__label">Total time</span>
              </div>
              <div className="stat">
                <span className="stat__value">
                  {stats.avg_time_seconds.toFixed(1)}s
                </span>
                <span className="stat__label">Avg / question</span>
              </div>
              <div className="stat stat--wide">
                <span className="stat__value">
                  {stats.streak > 0 ? "🔥 " : ""}
                  {stats.streak}
                </span>
                <span className="stat__label">Current streak</span>
              </div>
            </div>
          )}

          <button type="button" className="btn btn--primary" onClick={onClose}>
            Keep practising
          </button>
        </motion.div>
    </motion.div>
  );
}
