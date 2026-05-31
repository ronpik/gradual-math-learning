import type { JSX } from "react";
import { motion } from "framer-motion";

/**
 * Slim module-completion bar with a % label. Renders module progress ONLY —
 * never exercise counts or mastery numbers.
 */
export function ProgressBar({ percent }: { percent: number }): JSX.Element {
  const clamped = Math.max(0, Math.min(100, percent));
  const rounded = Math.round(clamped);
  return (
    <div className="progress">
      <div
        className="progress__track"
        role="progressbar"
        aria-label="Module progress"
        aria-valuenow={rounded}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={`${rounded} percent complete`}
      >
        <motion.div
          className="progress__fill"
          initial={false}
          animate={{ width: `${clamped}%` }}
          transition={{ type: "spring", stiffness: 120, damping: 20 }}
        />
      </div>
      <span className="progress__pct" aria-hidden="true">
        {rounded}%
      </span>
    </div>
  );
}
