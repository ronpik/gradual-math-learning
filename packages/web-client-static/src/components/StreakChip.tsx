import type { JSX } from "react";
import { AnimatePresence, motion } from "framer-motion";

/**
 * Small, kid-safe correct-streak indicator. Hidden entirely at streak 0 so it
 * only appears as positive reinforcement.
 */
export function StreakChip({ streak }: { streak: number }): JSX.Element | null {
  if (streak < 1) {
    return null;
  }
  const hot = streak >= 3;
  return (
    <AnimatePresence mode="popLayout">
      <motion.div
        key={streak}
        className="streak"
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.6, opacity: 0 }}
        transition={{ type: "spring", stiffness: 400, damping: 18 }}
      >
        <span className="streak__icon" aria-hidden="true">
          {hot ? "🔥" : "⭐"}
        </span>
        <span>
          {streak} in a row
          <span className="sr-only"> correct streak</span>
        </span>
      </motion.div>
    </AnimatePresence>
  );
}
