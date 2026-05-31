/**
 * A brief, tasteful star/confetti burst for correct answers. Respects the
 * user's reduced-motion preference (no burst at all) and uses the meadow
 * palette so it stays on-theme.
 */
import confetti from "canvas-confetti";

const MEADOW_COLORS = ["#FF7A4D", "#18B7A6", "#FFC53D", "#3FB75E"];

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

export function celebrate(): void {
  if (prefersReducedMotion()) {
    return;
  }
  confetti({
    particleCount: 70,
    spread: 70,
    startVelocity: 38,
    origin: { y: 0.7 },
    colors: MEADOW_COLORS,
    scalar: 0.9,
    ticks: 140,
    disableForReducedMotion: true,
  });
}
