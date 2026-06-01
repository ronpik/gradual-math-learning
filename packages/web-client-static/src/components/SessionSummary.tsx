import { useEffect } from "react";
import type { JSX } from "react";
import { motion, useReducedMotion } from "framer-motion";

import { celebrate } from "../confetti";
import type { LevelProgress, Summary } from "../api/types";

/** Format a second count as `m:ss` (used for time-based headlines / bests). */
function formatTime(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}

/** Accuracy may arrive as a 0-1 fraction or a 0-100 percent; normalise. */
function formatAccuracy(accuracy: number): string {
  const pct = accuracy <= 1 ? accuracy * 100 : accuracy;
  return `${Math.round(pct)}%`;
}

/** The mode-specific big headline derived from `summary.headline`. */
function headlineFor(summary: Summary): { value: string; caption: string } {
  switch (summary.mode) {
    case "fastest_20":
      return {
        value: formatTime(summary.headline.total_time_seconds ?? 0),
        caption: "Total time",
      };
    case "three_minute":
      return {
        value: String(summary.headline.questions_done ?? 0) + " solved",
        caption: "In three minutes",
      };
    case "endless":
      return {
        value: Math.round((summary.headline.accuracy ?? 0) * 100) + "% correct",
        caption: "Accuracy",
      };
    default:
      return { value: `${summary.questions_done} done`, caption: "Nice work" };
  }
}

/** The personal best, formatted the same way as its mode's headline. */
function formatPersonalBest(summary: Summary): string | null {
  if (summary.personal_best === null) {
    return null;
  }
  const best = summary.personal_best;
  switch (summary.mode) {
    case "fastest_20":
      return formatTime(best);
    case "three_minute":
      return `${Math.round(best)} solved`;
    case "endless":
      return `${Math.round(best * 100)}%`;
    default:
      return String(best);
  }
}

/** A row of up-to-`total` stars, the first `mastered` of them filled. */
function LevelStars({ level }: { level: LevelProgress }): JSX.Element {
  const total = Math.max(0, level.total);
  const mastered = Math.min(total, Math.max(0, level.mastered));
  const complete = total > 0 && mastered >= total;
  return (
    <div className="level-row">
      <span className="level-row__label">Level {level.level}</span>
      <span
        className="level-row__stars"
        role="img"
        aria-label={`Level ${level.level}: ${mastered} of ${total} mastered`}
      >
        {Array.from({ length: total }, (_, i) => (
          <span
            key={i}
            className={`level-star ${i < mastered ? "is-filled" : ""}`}
            aria-hidden="true"
          >
            {i < mastered ? "★" : "☆"}
          </span>
        ))}
      </span>
      <span className="level-row__count" aria-hidden="true">
        {complete ? "🎉" : `${mastered}/${total}`}
      </span>
    </div>
  );
}

/**
 * The end-of-run results card: a celebratory mode headline, the core figures
 * (done / correct / accuracy / avg time), the personal best with a "New best!"
 * badge, per-level star progress, and the two actions. Fires a confetti burst on
 * mount only when this run set a new personal best. Student-safe throughout.
 */
export function SessionSummary({
  summary,
  onPlayAgain,
  onMenu,
}: {
  summary: Summary;
  onPlayAgain: () => void;
  onMenu: () => void;
}): JSX.Element {
  const reduceMotion = useReducedMotion();
  const headline = headlineFor(summary);
  const personalBest = formatPersonalBest(summary);

  useEffect(() => {
    if (summary.is_new_best) {
      celebrate();
    }
  }, [summary.is_new_best]);

  const spring = reduceMotion
    ? { duration: 0 }
    : { type: "spring" as const, stiffness: 300, damping: 22 };

  return (
    <motion.section
      className="summary"
      aria-label="Practice results"
      initial={reduceMotion ? false : { opacity: 0, scale: 0.94, y: 12 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={spring}
    >
      <header className="summary__head">
        <span className="summary__emoji" aria-hidden="true">
          🌟
        </span>
        <h2 className="summary__title">{summary.label}</h2>
      </header>

      <div className="summary__headline">
        <span className="summary__headline-value">{headline.value}</span>
        <span className="summary__headline-caption">{headline.caption}</span>
      </div>

      {summary.is_new_best ? (
        <motion.div
          className="summary__best-badge"
          initial={reduceMotion ? false : { scale: 0.6, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={
            reduceMotion
              ? { duration: 0 }
              : { type: "spring", stiffness: 420, damping: 16, delay: 0.15 }
          }
        >
          New best! 🎉
        </motion.div>
      ) : personalBest !== null ? (
        <p className="summary__best">
          Personal best: <strong>{personalBest}</strong>
        </p>
      ) : null}

      <div className="summary__stats">
        <div className="stat">
          <span className="stat__value">{summary.questions_done}</span>
          <span className="stat__label">Done</span>
        </div>
        <div className="stat">
          <span className="stat__value">{summary.correct}</span>
          <span className="stat__label">Correct</span>
        </div>
        <div className="stat">
          <span className="stat__value">{formatAccuracy(summary.accuracy)}</span>
          <span className="stat__label">Accuracy</span>
        </div>
        <div className="stat">
          <span className="stat__value">
            {summary.avg_time_seconds.toFixed(1)}s
          </span>
          <span className="stat__label">Avg / question</span>
        </div>
      </div>

      {summary.levels.length > 0 ? (
        <div className="summary__levels">
          <h3 className="summary__levels-title">Your stars</h3>
          <div className="level-list">
            {summary.levels.map((lvl) => (
              <LevelStars key={lvl.level} level={lvl} />
            ))}
          </div>
        </div>
      ) : null}

      <div className="summary__actions">
        <button
          type="button"
          className="btn btn--primary"
          onClick={onPlayAgain}
        >
          Play again
        </button>
        <button type="button" className="btn btn--ghost" onClick={onMenu}>
          Back to menu
        </button>
      </div>
    </motion.section>
  );
}
