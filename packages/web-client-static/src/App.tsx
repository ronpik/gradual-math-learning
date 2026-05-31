/**
 * Math Meadow — the play experience.
 *
 * Owns app state and the answer flow: boot (resume or create a session) ->
 * getNext -> show & time -> submit -> feedback -> auto-advance. Talks only to
 * the student-safe `/v1/play` API. Renders only student-safe figures (equation,
 * done-count, module %, accuracy, time, streak) — never engine internals.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { JSX } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { ApiError, createSession, getNext, submitAnswer } from "./api/client";
import type { Exercise } from "./api/types";
import {
  clearSessionId,
  readSessionId,
  saveSessionId,
} from "./session";
import {
  playCorrect,
  playWrong,
  readSoundPref,
  saveSoundPref,
} from "./sound";
import { celebrate } from "./confetti";
import { Header } from "./components/Header";
import {
  ExerciseCard,
  type FeedbackState,
  type Phase,
} from "./components/ExerciseCard";
import { StatsModal } from "./components/StatsModal";
import "./styles/app.css";

type Boot = "loading" | "ready" | "error";

const ADVANCE_DELAY_MS = 1500;

const WRONG_MESSAGES = [
  "Almost! Try the next one.",
  "Good try! Here comes another.",
  "So close! Keep going.",
  "Nice effort! Next one up.",
];

const CORRECT_MESSAGES = [
  "Great job!",
  "You got it!",
  "Brilliant!",
  "Way to go!",
  "Super!",
];

function pick(list: string[]): string {
  return list[Math.floor(Math.random() * list.length)];
}

export default function App(): JSX.Element {
  const [boot, setBoot] = useState<Boot>("loading");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [exercise, setExercise] = useState<Exercise | null>(null);
  const [phase, setPhase] = useState<Phase>("answering");

  const [value, setValue] = useState("");
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);

  const [done, setDone] = useState(0);
  const [percent, setPercent] = useState(0);
  const [streak, setStreak] = useState(0);

  const [statsOpen, setStatsOpen] = useState(false);
  const [soundOn, setSoundOn] = useState<boolean>(() => readSoundPref());

  // Timing: set when an exercise is shown, read at submit.
  const shownAtRef = useRef<number>(0);
  // Auto-advance timer handle.
  const advanceTimerRef = useRef<number | null>(null);
  // Guards against double-submits.
  const submittingRef = useRef(false);

  const clearAdvanceTimer = useCallback(() => {
    if (advanceTimerRef.current !== null) {
      window.clearTimeout(advanceTimerRef.current);
      advanceTimerRef.current = null;
    }
  }, []);

  /** Show a freshly drawn exercise and start its timer. */
  const presentExercise = useCallback((ex: Exercise) => {
    setExercise(ex);
    setValue("");
    setFeedback(null);
    setPhase("answering");
    shownAtRef.current = performance.now();
  }, []);

  /** Create a brand-new session and draw its first exercise. */
  const startFresh = useCallback(async () => {
    setBoot("loading");
    clearSessionId();
    setDone(0);
    setPercent(0);
    setStreak(0);
    try {
      const session = await createSession();
      saveSessionId(session.session_id);
      setSessionId(session.session_id);
      const ex = await getNext(session.session_id);
      presentExercise(ex);
      setBoot("ready");
    } catch {
      setBoot("error");
    }
  }, [presentExercise]);

  /** Draw the next exercise for an existing session; recover on expiry. */
  const loadNext = useCallback(
    async (sid: string) => {
      try {
        const ex = await getNext(sid);
        presentExercise(ex);
      } catch (err) {
        if (err instanceof ApiError && (err.status === 404 || err.status === 410)) {
          await startFresh();
        } else {
          setBoot("error");
        }
      }
    },
    [presentExercise, startFresh],
  );

  // Boot: resume a stored session, else create one.
  useEffect(() => {
    let alive = true;
    (async () => {
      const stored = readSessionId();
      if (stored) {
        try {
          const ex = await getNext(stored);
          if (!alive) {
            return;
          }
          setSessionId(stored);
          saveSessionId(stored);
          presentExercise(ex);
          setBoot("ready");
          return;
        } catch (err) {
          if (
            !(err instanceof ApiError) ||
            (err.status !== 404 && err.status !== 410)
          ) {
            if (alive) {
              setBoot("error");
            }
            return;
          }
          // Expired/unknown — fall through to a fresh session.
        }
      }
      if (alive) {
        await startFresh();
      }
    })();
    return () => {
      alive = false;
    };
    // Boot once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tidy the advance timer on unmount.
  useEffect(() => clearAdvanceTimer, [clearAdvanceTimer]);

  const advance = useCallback(() => {
    clearAdvanceTimer();
    if (sessionId) {
      void loadNext(sessionId);
    }
  }, [clearAdvanceTimer, loadNext, sessionId]);

  const handleSubmit = useCallback(async () => {
    if (
      !sessionId ||
      !exercise ||
      phase !== "answering" ||
      submittingRef.current
    ) {
      return;
    }
    const answer = Number.parseInt(value, 10);
    if (!Number.isFinite(answer) || value.length === 0) {
      return;
    }
    submittingRef.current = true;
    const elapsedSeconds = Math.max(
      0,
      (performance.now() - shownAtRef.current) / 1000,
    );
    try {
      const result = await submitAnswer(sessionId, answer, elapsedSeconds);
      setDone(result.questions_done);
      setPercent(result.module_completion_percent);
      setStreak(result.streak);
      setFeedback({
        correct: result.correct,
        message: result.correct ? pick(CORRECT_MESSAGES) : pick(WRONG_MESSAGES),
      });
      setPhase("feedback");
      if (soundOn) {
        if (result.correct) {
          playCorrect();
        } else {
          playWrong();
        }
      }
      if (result.correct) {
        celebrate();
      }
      clearAdvanceTimer();
      advanceTimerRef.current = window.setTimeout(advance, ADVANCE_DELAY_MS);
    } catch (err) {
      if (
        err instanceof ApiError &&
        (err.status === 404 || err.status === 410)
      ) {
        await startFresh();
      } else {
        setBoot("error");
      }
    } finally {
      submittingRef.current = false;
    }
  }, [
    advance,
    clearAdvanceTimer,
    exercise,
    phase,
    sessionId,
    soundOn,
    value,
  ]);

  const handleContinue = useCallback(() => {
    if (phase !== "feedback") {
      return;
    }
    advance();
  }, [advance, phase]);

  const handleToggleSound = useCallback(() => {
    setSoundOn((prev) => {
      const next = !prev;
      saveSoundPref(next);
      if (next) {
        // Confirm the toggle audibly.
        playCorrect();
      }
      return next;
    });
  }, []);

  const handleNewSession = useCallback(() => {
    const ok = window.confirm(
      "Start a brand-new session? Your current progress will be cleared.",
    );
    if (ok) {
      clearAdvanceTimer();
      setStatsOpen(false);
      void startFresh();
    }
  }, [clearAdvanceTimer, startFresh]);

  // --- render ---------------------------------------------------------- //

  const reveal = {
    hidden: { opacity: 0, y: 16 },
    show: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: { delay: 0.08 * i, type: "spring" as const, stiffness: 220, damping: 22 },
    }),
  };

  return (
    <>
      <div className="meadow" aria-hidden="true">
        <div className="meadow__sun" />
        <div className="meadow__hill meadow__hill--back" />
        <div className="meadow__hill meadow__hill--front" />
      </div>

      <main className="app">
        {boot === "loading" && (
          <div className="banner" role="status" aria-live="polite">
            <div className="spinner" style={{ margin: "0 auto" }} />
            <p>Getting your meadow ready…</p>
          </div>
        )}

        {boot === "error" && (
          <div className="banner" role="alert">
            <span className="banner__emoji" aria-hidden="true">
              🌧️
            </span>
            <p>Oops — we lost the connection. Let&rsquo;s try again.</p>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void startFresh()}
            >
              Try again
            </button>
          </div>
        )}

        {boot === "ready" && exercise && sessionId && (
          <>
            <motion.div
              style={{ width: "min(100%, 46rem)", display: "flex", justifyContent: "center" }}
              custom={0}
              variants={reveal}
              initial="hidden"
              animate="show"
            >
              <Header
                done={done}
                percent={percent}
                soundOn={soundOn}
                onToggleSound={handleToggleSound}
                onOpenStats={() => setStatsOpen(true)}
                onNewSession={handleNewSession}
              />
            </motion.div>

            <motion.div
              style={{ width: "min(100%, 30rem)", display: "flex", justifyContent: "center" }}
              custom={1}
              variants={reveal}
              initial="hidden"
              animate="show"
            >
              <ExerciseCard
                exercise={exercise}
                value={value}
                phase={phase}
                feedback={feedback}
                streak={streak}
                onChange={setValue}
                onSubmit={() => void handleSubmit()}
                onContinue={handleContinue}
              />
            </motion.div>
          </>
        )}
      </main>

      <AnimatePresence>
        {statsOpen && sessionId && (
          <StatsModal
            sessionId={sessionId}
            onClose={() => setStatsOpen(false)}
          />
        )}
      </AnimatePresence>
    </>
  );
}
