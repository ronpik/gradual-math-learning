/**
 * Sign-in / sign-up dialog (Sunny-Meadow styled).
 *
 * Offers an email+password form (toggle between sign-in and sign-up) and a
 * "Sign in with Google" button. Mirrors StatsModal's accessibility contract:
 * focus trap, Esc-to-close, aria-modal, restore-focus, spring in/out.
 *
 * It only triggers the Firebase sign-in helpers; the actual learner switch is
 * driven by App's `observeAuth` subscription. On success the dialog closes
 * itself. Firebase error codes are mapped to friendly, kid-parent-safe copy.
 *
 * No engine internals are ever touched here — auth is orthogonal to play state.
 */
import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, JSX } from "react";
import { motion } from "framer-motion";

import { signInEmail, signInGoogle, signUpEmail } from "../firebase";

/** Map a Firebase error to a friendly message. Falls back to a generic line. */
function friendlyError(err: unknown): string {
  const code =
    typeof err === "object" && err !== null && "code" in err
      ? String((err as { code: unknown }).code)
      : "";
  switch (code) {
    case "auth/invalid-email":
      return "That email doesn't look right. Please check it.";
    case "auth/missing-password":
      return "Please enter your password.";
    case "auth/weak-password":
      return "Pick a password with at least 6 characters.";
    case "auth/email-already-in-use":
      return "That email already has an account — try signing in.";
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
      return "Email or password didn't match. Please try again.";
    case "auth/too-many-requests":
      return "Too many tries. Please wait a moment and try again.";
    case "auth/popup-closed-by-user":
    case "auth/cancelled-popup-request":
      return "Sign-in was cancelled.";
    case "auth/popup-blocked":
      return "Your browser blocked the popup. Please allow it and retry.";
    case "auth/network-request-failed":
      return "Network hiccup — check your connection and try again.";
    default:
      return "Something went wrong. Please try again.";
  }
}

export function AuthModal({ onClose }: { onClose: () => void }): JSX.Element {
  const titleId = useId();
  const descId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFieldRef = useRef<HTMLInputElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Remember the trigger, focus the email field, restore on unmount.
  useEffect(() => {
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    firstFieldRef.current?.focus();
    return () => {
      restoreFocusRef.current?.focus?.();
    };
  }, []);

  // Esc to close + focus trap.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") {
        return;
      }
      const root = dialogRef.current;
      if (!root) {
        return;
      }
      const focusable = Array.from(
        root.querySelectorAll<HTMLElement>(
          'button, [href], input, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("disabled"));
      if (focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function handleEmailSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    if (busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") {
        await signUpEmail(email.trim(), password);
      } else {
        await signInEmail(email.trim(), password);
      }
      // App's observeAuth handles the learner switch; just close.
      onClose();
    } catch (err) {
      setError(friendlyError(err));
      setBusy(false);
    }
  }

  async function handleGoogle(): Promise<void> {
    if (busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signInGoogle();
      onClose();
    } catch (err) {
      setError(friendlyError(err));
      setBusy(false);
    }
  }

  const isSignup = mode === "signup";

  return (
    <motion.div
      className="scrim"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
    >
      <motion.div
        ref={dialogRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        initial={{ scale: 0.85, opacity: 0, y: 12 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.9, opacity: 0, y: 12 }}
        transition={{ type: "spring", stiffness: 320, damping: 24 }}
      >
        <div className="modal__head">
          <h2 className="modal__title" id={titleId}>
            {isSignup ? "Create an account" : "Welcome back"}
          </h2>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label="Close sign in"
          >
            ✕
          </button>
        </div>

        <p id={descId} className="auth__intro">
          {isSignup
            ? "Save your progress and pick up on any device."
            : "Sign in to keep all your meadow progress together."}
        </p>

        <form className="auth__form" onSubmit={(e) => void handleEmailSubmit(e)}>
          <label className="auth__field">
            <span className="auth__label">Email</span>
            <input
              ref={firstFieldRef}
              className="auth__input"
              type="email"
              name="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </label>

          <label className="auth__field">
            <span className="auth__label">Password</span>
            <input
              className="auth__input"
              type="password"
              name="password"
              autoComplete={isSignup ? "new-password" : "current-password"}
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </label>

          {error ? (
            <p className="auth__error" role="alert">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            className="btn btn--primary auth__submit"
            disabled={busy}
          >
            {busy ? "One moment…" : isSignup ? "Create account" : "Sign in"}
          </button>
        </form>

        <div className="auth__divider" aria-hidden="true">
          <span>or</span>
        </div>

        <button
          type="button"
          className="btn auth__google"
          onClick={() => void handleGoogle()}
          disabled={busy}
        >
          <span className="auth__google-mark" aria-hidden="true">
            G
          </span>
          Sign in with Google
        </button>

        <p className="auth__toggle">
          {isSignup ? "Already have an account?" : "New to Math Meadow?"}{" "}
          <button
            type="button"
            className="auth__link"
            onClick={() => {
              setMode(isSignup ? "signin" : "signup");
              setError(null);
            }}
          >
            {isSignup ? "Sign in" : "Create one"}
          </button>
        </p>
      </motion.div>
    </motion.div>
  );
}
