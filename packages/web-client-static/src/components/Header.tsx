import type { JSX } from "react";

import { ProgressBar } from "./ProgressBar";

/**
 * Slim header: brand, a friendly "Done" tally, the module progress bar, and the
 * action cluster (stats, sound toggle, new session). Exposes only student-safe
 * figures.
 */
export function Header({
  done,
  percent,
  soundOn,
  onToggleSound,
  onOpenStats,
  onNewSession,
}: {
  done: number;
  percent: number;
  soundOn: boolean;
  onToggleSound: () => void;
  onOpenStats: () => void;
  onNewSession: () => void;
}): JSX.Element {
  return (
    <header className="header">
      <div className="brand">
        <span className="brand__mark" aria-hidden="true">
          🌻
        </span>
        <span className="brand__name">Math Meadow</span>
      </div>

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
          onClick={onNewSession}
          aria-label="Start a new session"
          title="New session"
        >
          🔄
        </button>
      </div>
    </header>
  );
}
