import { useEffect, useRef, useState } from "react";
import type { JSX } from "react";
import { motion, useReducedMotion } from "framer-motion";

const TICK_MS = 250;
const ALERT_THRESHOLD_MS = 30_000;

/** Format a non-negative millisecond span as `m:ss`. */
function formatRemaining(ms: number): string {
  const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/**
 * A live countdown to a server-authoritative `deadline` (ISO datetime). Ticks
 * every 250ms so the final seconds feel responsive, switches to an "alert" look
 * under 30s, and calls `onExpire` EXACTLY once when the clock reaches zero —
 * then stops. The deadline is parsed against the browser clock each tick (the
 * server owns truth; this is just the display + the local zero-trigger).
 */
export function CountdownTimer({
  deadline,
  onExpire,
}: {
  deadline: string;
  onExpire: () => void;
}): JSX.Element {
  const reduceMotion = useReducedMotion();
  const deadlineMs = Date.parse(deadline);

  const computeRemaining = (): number =>
    Number.isNaN(deadlineMs) ? 0 : deadlineMs - Date.now();

  const [remaining, setRemaining] = useState<number>(computeRemaining);

  // Guard so onExpire fires once even across re-renders / strict-mode.
  const expiredRef = useRef(false);
  // Keep the latest onExpire without re-arming the interval.
  const onExpireRef = useRef(onExpire);
  onExpireRef.current = onExpire;

  useEffect(() => {
    expiredRef.current = false;

    const fireIfDone = (left: number): void => {
      if (left <= 0 && !expiredRef.current) {
        expiredRef.current = true;
        onExpireRef.current();
      }
    };

    // Evaluate immediately in case we mounted already past the deadline.
    const initial = computeRemaining();
    setRemaining(initial);
    fireIfDone(initial);
    if (expiredRef.current) {
      return;
    }

    const id = window.setInterval(() => {
      const left = computeRemaining();
      setRemaining(left);
      if (left <= 0) {
        fireIfDone(left);
        window.clearInterval(id);
      }
    }, TICK_MS);

    return () => window.clearInterval(id);
    // Re-arm only when the deadline itself changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deadline]);

  const clamped = Math.max(0, remaining);
  const alert = clamped <= ALERT_THRESHOLD_MS;

  return (
    <motion.div
      className={`countdown ${alert ? "countdown--alert" : ""}`}
      role="timer"
      aria-label="Time remaining"
      aria-live="off"
      animate={
        alert && !reduceMotion ? { scale: [1, 1.06, 1] } : { scale: 1 }
      }
      transition={
        alert && !reduceMotion
          ? { duration: 1, repeat: Infinity, ease: "easeInOut" }
          : { duration: 0.2 }
      }
    >
      <span className="countdown__icon" aria-hidden="true">
        ⏱️
      </span>
      <span className="countdown__time" aria-hidden="true">
        {formatRemaining(clamped)}
      </span>
      <span className="sr-only">{formatRemaining(clamped)} remaining</span>
    </motion.div>
  );
}
