import type { JSX } from "react";

import { ProgressBar } from "./ProgressBar";
import { CountdownTimer } from "./CountdownTimer";

/**
 * Slim header: brand, the per-mode HUD slot, a friendly "Done" tally, the module
 * progress bar, and the action cluster (stats, sound toggle, quit-to-menu).
 * Exposes only student-safe figures.
 *
 * The HUD is mode-driven:
 *   - fastest_20  -> an "n / 20" counter (from questionsDone / targetCount).
 *   - three_minute -> a live <CountdownTimer> driven by the server deadline.
 *   - endless     -> nothing extra (today's plain play).
 */
export function Header({
  done,
  percent,
  mode,
  targetCount,
  questionsDone,
  deadline,
  onDeadlineExpire,
  soundOn,
  onToggleSound,
  onOpenStats,
  onQuit,
}: {
  done: number;
  percent: number;
  mode: string;
  targetCount: number | null;
  questionsDone: number;
  deadline: string | null;
  onDeadlineExpire: () => void;
  soundOn: boolean;
  onToggleSound: () => void;
  onOpenStats: () => void;
  onQuit: () => void;
}): JSX.Element {
  let hud: JSX.Element | null = null;
  if (mode === "fastest_20" && targetCount !== null) {
    const shown = Math.min(questionsDone, targetCount);
    hud = (
      <div
        className="hud-chip"
        aria-label={`${shown} of ${targetCount} done`}
      >
        <span className="hud-chip__value" aria-hidden="true">
          {shown} / {targetCount}
        </span>
      </div>
    );
  } else if (mode === "three_minute" && deadline !== null) {
    hud = <CountdownTimer deadline={deadline} onExpire={onDeadlineExpire} />;
  }

  return (
    <header className="header">
      <div className="brand">
        <span className="brand__mark" aria-hidden="true">
          🌻
        </span>
        <span className="brand__name">Math Meadow</span>
      </div>

      {hud ? <div className="header__hud">{hud}</div> : null}

      <div className="header__progress">
        <ProgressBar percent={percent} />
      </div>

      <div className="done-chip" aria-label={`${done} exercises done`}>
        <span className="done-chip__label">Done</span>
        <span aria-hidden="true">{done}</span>
      </div>

      <div className="header__actions">
        <button
          type="button"
          className="icon-btn"
          onClick={onOpenStats}
          aria-label="Open stats"
          title="Stats"
        >
          📊
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={onToggleSound}
          aria-label={soundOn ? "Turn sound off" : "Turn sound on"}
          aria-pressed={soundOn}
          title={soundOn ? "Sound on" : "Sound off"}
        >
          {soundOn ? "🔊" : "🔇"}
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={onQuit}
          aria-label="Back to menu"
          title="Menu"
        >
          🏡
        </button>
      </div>
    </header>
  );
}
