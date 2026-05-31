import type { JSX } from "react";

export type KeypadKey = string | "back" | "enter";

/**
 * Clean on-screen numeric keypad for touch — mirrors the keyboard. Digits 0-9,
 * a delete key, and Enter. Submit is disabled while there is nothing to submit.
 */
export function Keypad({
  onKey,
  disabled,
  canSubmit,
}: {
  onKey: (key: KeypadKey) => void;
  disabled: boolean;
  canSubmit: boolean;
}): JSX.Element {
  const digits = ["1", "2", "3", "4", "5", "6", "7", "8", "9"];
  return (
    <div className="keypad" role="group" aria-label="Number pad">
      {digits.map((d) => (
        <button
          key={d}
          type="button"
          className="key"
          disabled={disabled}
          onClick={() => onKey(d)}
          aria-label={d}
        >
          {d}
        </button>
      ))}
      <button
        type="button"
        className="key key--action"
        disabled={disabled}
        onClick={() => onKey("back")}
        aria-label="Delete"
      >
        ⌫
      </button>
      <button
        type="button"
        className="key"
        disabled={disabled}
        onClick={() => onKey("0")}
        aria-label="0"
      >
        0
      </button>
      <button
        type="button"
        className="key key--enter"
        disabled={disabled || !canSubmit}
        onClick={() => onKey("enter")}
        aria-label="Enter"
      >
        ⏎
      </button>
    </div>
  );
}
