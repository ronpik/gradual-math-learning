import { useEffect, useRef } from "react";
import type { JSX, KeyboardEvent } from "react";
import { motion, useReducedMotion } from "framer-motion";

import type { Exercise } from "../api/types";
import { Keypad, type KeypadKey } from "./Keypad";
import { StreakChip } from "./StreakChip";

export type Phase = "answering" | "feedback";

export interface FeedbackState {
  correct: boolean;
  message: string;
}

/**
 * The play card: the huge equation, the focused numeric input, an on-screen
 * keypad, and the feedback line. All answer state lives in the parent; this
 * component is keyboard-first with auto-refocus and mirrors keys to the keypad.
 */
export function ExerciseCard({
  exercise,
  value,
  phase,
  feedback,
  streak,
  onChange,
  onSubmit,
  onContinue,
}: {
  exercise: Exercise;
  value: string;
  phase: Phase;
  feedback: FeedbackState | null;
  streak: number;
  onChange: (next: string) => void;
  onSubmit: () => void;
  onContinue: () => void;
}): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const reduceMotion = useReducedMotion();
  const canSubmit = value.length > 0;
  // Spoken operation name for the screen-reader prompt ("+" -> "plus").
  const opWord = exercise.op === "-" ? "minus" : "plus";

  // Keep the input focused for keyboard-first play: on mount, on each new
  // exercise, and whenever we return to the answering phase.
  useEffect(() => {
    inputRef.current?.focus();
  }, [exercise.a, exercise.b, phase]);

  function handleInputChange(raw: string): void {
    // Digits only, capped so silly-long entries can't break the layout.
    const cleaned = raw.replace(/[^0-9]/g, "").slice(0, 4);
    onChange(cleaned);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>): void {
    if (e.key === "Enter") {
      e.preventDefault();
      if (phase === "feedback") {
        onContinue();
      } else if (canSubmit) {
        onSubmit();
      }
    }
  }

  function handleKeypad(key: KeypadKey): void {
    inputRef.current?.focus();
    if (phase === "feedback") {
      if (key === "enter") {
        onContinue();
      }
      return;
    }
    if (key === "enter") {
      if (canSubmit) {
        onSubmit();
      }
    } else if (key === "back") {
      onChange(value.slice(0, -1));
    } else {
      handleInputChange(value + key);
    }
  }

  const answerStateClass =
    phase === "feedback" && feedback
      ? feedback.correct
        ? "answer--correct"
        : "answer--wrong"
      : "";

  // Gentle horizontal shake on a wrong answer (skipped under reduced motion).
  const wrongShake =
    phase === "feedback" && feedback && !feedback.correct && !reduceMotion;
  const correctPop =
    phase === "feedback" && feedback && feedback.correct && !reduceMotion;

  return (
    <motion.section
      className="card"
      aria-label="Practice exercise"
      animate={
        wrongShake
          ? { x: [0, -10, 10, -7, 7, -3, 0] }
          : correctPop
            ? { scale: [1, 1.03, 1] }
            : { x: 0, scale: 1 }
      }
      transition={
        wrongShake
          ? { duration: 0.45 }
          : { type: "spring", stiffness: 300, damping: 18 }
      }
    >
      <div className="equation" aria-live="off">
        <span className="equation__slot" aria-hidden="true">
          {exercise.a}
        </span>
        <span className="equation__op" aria-hidden="true">
          {exercise.op}
        </span>
        <span className="equation__slot" aria-hidden="true">
          {exercise.b}
        </span>
        <span className="equation__eq" aria-hidden="true">
          =
        </span>
        <span className="equation__slot equation__op" aria-hidden="true">
          ?
        </span>
        <span className="sr-only">
          What is {exercise.a} {opWord} {exercise.b}?
        </span>
      </div>

      <div className={`answer ${answerStateClass}`}>
        <label className="sr-only" htmlFor="answer-input">
          Your answer
        </label>
        <input
          id="answer-input"
          ref={inputRef}
          className="answer__input"
          type="text"
          inputMode="numeric"
          autoComplete="off"
          enterKeyHint="done"
          placeholder="?"
          aria-describedby="feedback-line"
          value={value}
          readOnly={phase === "feedback"}
          onChange={(e) => handleInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
        />
      </div>

      <p
        id="feedback-line"
        className={`feedback ${
          feedback ? (feedback.correct ? "feedback--correct" : "feedback--wrong") : ""
        }`}
        role="status"
        aria-live="polite"
      >
        {phase === "feedback" && feedback
          ? `${feedback.correct ? "✓ " : ""}${feedback.message}`
          : " "}
      </p>

      <Keypad
        onKey={handleKeypad}
        disabled={false}
        canSubmit={phase === "feedback" || canSubmit}
      />

      <StreakChip streak={streak} />
    </motion.section>
  );
}
