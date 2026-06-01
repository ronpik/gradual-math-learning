import { useMemo, useState } from "react";
import type { JSX } from "react";
import { motion, useReducedMotion } from "framer-motion";

import type { ModeDescriptor, ModuleDescriptor } from "../api/types";

/**
 * The landing screen: pick a problem module (6 cards, grouped Addition /
 * Subtraction) and a practice method (3 mode cards), then Start. Selection lives
 * in local state; `onStart` is only enabled once BOTH a module and a mode are
 * chosen (and we're not already busy creating a session).
 *
 * Student-safe: modules/modes are plain descriptors — no engine internals here.
 */
export function MainMenu({
  modules,
  modes,
  onStart,
  busy = false,
  error = null,
}: {
  modules: ModuleDescriptor[];
  modes: ModeDescriptor[];
  onStart: (moduleId: string, modeId: string) => void;
  busy?: boolean;
  error?: string | null;
}): JSX.Element {
  const reduceMotion = useReducedMotion();
  const [moduleId, setModuleId] = useState<string | null>(null);
  const [modeId, setModeId] = useState<string | null>(null);

  // Split the 6 modules into the two friendly groups by operation.
  const { addition, subtraction } = useMemo(() => {
    const addition: ModuleDescriptor[] = [];
    const subtraction: ModuleDescriptor[] = [];
    for (const m of modules) {
      (m.op === "-" ? subtraction : addition).push(m);
    }
    return { addition, subtraction };
  }, [modules]);

  const ready = moduleId !== null && modeId !== null && !busy;

  const cardTransition = reduceMotion
    ? { duration: 0 }
    : { type: "spring" as const, stiffness: 320, damping: 22 };

  function renderModuleGroup(
    title: string,
    emoji: string,
    group: ModuleDescriptor[],
  ): JSX.Element | null {
    if (group.length === 0) {
      return null;
    }
    return (
      <div className="menu-group">
        <h3 className="menu-group__title">
          <span aria-hidden="true">{emoji}</span> {title}
        </h3>
        <div className="menu-grid">
          {group.map((m) => {
            const selected = m.id === moduleId;
            return (
              <motion.button
                key={m.id}
                type="button"
                className={`pick-card pick-card--module ${
                  selected ? "is-selected" : ""
                }`}
                aria-pressed={selected}
                onClick={() => setModuleId(m.id)}
                whileTap={reduceMotion ? undefined : { scale: 0.96 }}
                transition={cardTransition}
              >
                <span className="pick-card__title">{m.label}</span>
                <span className="pick-card__hint">
                  {m.levels.length} level{m.levels.length === 1 ? "" : "s"}
                </span>
                <span className="pick-card__check" aria-hidden="true">
                  ✓
                </span>
              </motion.button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <motion.section
      className="menu"
      aria-label="Choose what to practice"
      initial={reduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={cardTransition}
    >
      <header className="menu__head">
        <span className="menu__mark" aria-hidden="true">
          🌻
        </span>
        <h2 className="menu__title">Let&rsquo;s practice!</h2>
        <p className="menu__subtitle">Pick a kind of math, then how to play.</p>
      </header>

      <div className="menu__section">
        <h3 className="menu__step">
          <span className="menu__step-num" aria-hidden="true">
            1
          </span>
          Choose your math
        </h3>
        {renderModuleGroup("Addition", "➕", addition)}
        {renderModuleGroup("Subtraction", "➖", subtraction)}
      </div>

      <div className="menu__section">
        <h3 className="menu__step">
          <span className="menu__step-num" aria-hidden="true">
            2
          </span>
          Choose how to play
        </h3>
        <div className="menu-grid menu-grid--modes">
          {modes.map((mode) => {
            const selected = mode.id === modeId;
            return (
              <motion.button
                key={mode.id}
                type="button"
                className={`pick-card pick-card--mode ${
                  selected ? "is-selected" : ""
                }`}
                aria-pressed={selected}
                onClick={() => setModeId(mode.id)}
                whileTap={reduceMotion ? undefined : { scale: 0.96 }}
                transition={cardTransition}
              >
                <span className="pick-card__title">{mode.label}</span>
                <span className="pick-card__desc">{mode.description}</span>
                <span className="pick-card__check" aria-hidden="true">
                  ✓
                </span>
              </motion.button>
            );
          })}
        </div>
      </div>

      {error ? (
        <p className="menu__error" role="alert">
          {error}
        </p>
      ) : null}

      <motion.button
        type="button"
        className="btn btn--primary menu__start"
        disabled={!ready}
        onClick={() => {
          if (moduleId !== null && modeId !== null) {
            onStart(moduleId, modeId);
          }
        }}
        whileTap={reduceMotion || !ready ? undefined : { scale: 0.97 }}
      >
        {busy ? "Getting ready…" : "Start"}
      </motion.button>
    </motion.section>
  );
}
