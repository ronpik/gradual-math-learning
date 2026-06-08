/**
 * Math Meadow — the play experience.
 *
 * Owns app state and the flow: menu (pick module + method) -> playing (boot:
 * resume or create a run) -> getNext -> show & time -> submit -> feedback ->
 * auto-advance -> summary. Talks only to the student-safe `/v1/play` API and
 * renders only student-safe figures (equation, done-count, module %, accuracy,
 * time, streak, per-mode HUD) — never engine internals.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { JSX } from "react";
import { AnimatePresence, motion } from "framer-motion";

import {
  ApiError,
  claimAnonymous,
  createSession,
  getMe,
  getNext,
  getSummary,
  listModes,
  listModules,
  setAuthToken,
  setTokenRefresher,
  submitAnswer,
} from "./api/client";
import type {
  Exercise,
  ModeDescriptor,
  ModuleDescriptor,
  Summary,
} from "./api/types";
import {
  clearRun,
  readLearnerId,
  readRun,
  saveLearnerId,
  saveRun,
  type RunContext,
} from "./session";
import {
  getIdToken,
  observeAuth,
  signOutUser,
  type User,
} from "./firebase";
import { AuthModal } from "./components/AuthModal";
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
import { MainMenu } from "./components/MainMenu";
import { SessionSummary } from "./components/SessionSummary";
import { StatsModal } from "./components/StatsModal";
import "./styles/app.css";

type View = "loading" | "menu" | "playing" | "summary" | "error";

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

/** True for the ApiError(409) the server raises once a run's stop rule is met. */
function isComplete(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409;
}

/** True for the "session gone" statuses — expired/unknown -> start over. */
function isGone(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 410);
}

export default function App(): JSX.Element {
  const [view, setView] = useState<View>("loading");

  // Menu data (loaded once when entering the menu).
  const [modules, setModules] = useState<ModuleDescriptor[]>([]);
  const [modes, setModes] = useState<ModeDescriptor[]>([]);
  const [menuBusy, setMenuBusy] = useState(false);
  const [menuError, setMenuError] = useState<string | null>(null);

  // Long-lived learner identity.
  const [learnerId, setLearnerId] = useState<string | null>(() =>
    readLearnerId(),
  );

  // Active run context (null until a run is started/resumed).
  const [run, setRun] = useState<RunContext | null>(null);

  // Play state.
  const [exercise, setExercise] = useState<Exercise | null>(null);
  const [phase, setPhase] = useState<Phase>("answering");
  const [value, setValue] = useState("");
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [done, setDone] = useState(0);
  const [percent, setPercent] = useState(0);
  const [streak, setStreak] = useState(0);

  // Summary view.
  const [summary, setSummary] = useState<Summary | null>(null);

  const [statsOpen, setStatsOpen] = useState(false);
  const [soundOn, setSoundOn] = useState<boolean>(() => readSoundPref());

  // Auth state. `signedIn` reflects a live Firebase user; `accountEmail` is the
  // user's email (for the Header chip). The AuthModal is opened from the
  // Header / menu account control.
  const [signedIn, setSignedIn] = useState(false);
  const [accountEmail, setAccountEmail] = useState<string | null>(null);
  const [authOpen, setAuthOpen] = useState(false);

  // Timing: set when an exercise is shown, read at submit.
  const shownAtRef = useRef<number>(0);
  // Auto-advance timer handle.
  const advanceTimerRef = useRef<number | null>(null);
  // Guards against double-submits.
  const submittingRef = useRef(false);
  // Guards against double-navigation to the summary (finished / 409 / expiry).
  const endingRef = useRef(false);
  // Latest learner id, readable from the auth callback without re-subscribing.
  const learnerIdRef = useRef<string | null>(learnerId);
  learnerIdRef.current = learnerId;

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

  /** Load the menu descriptors and switch to the menu view. */
  const goToMenu = useCallback(async () => {
    clearAdvanceTimer();
    clearRun();
    setRun(null);
    setExercise(null);
    setSummary(null);
    setStatsOpen(false);
    setMenuError(null);
    setMenuBusy(false);
    endingRef.current = false;
    // Reuse already-loaded descriptors when we have them.
    if (modules.length > 0 && modes.length > 0) {
      setView("menu");
      return;
    }
    setView("loading");
    try {
      const [mods, mds] = await Promise.all([listModules(), listModes()]);
      setModules(mods);
      setModes(mds);
      setView("menu");
    } catch {
      setView("error");
    }
  }, [clearAdvanceTimer, modes.length, modules.length]);

  /** Fetch and show the end-of-run summary for a session. Guarded once. */
  const goToSummary = useCallback(
    async (sid: string) => {
      if (endingRef.current) {
        return;
      }
      endingRef.current = true;
      clearAdvanceTimer();
      try {
        const result = await getSummary(sid);
        setSummary(result);
        setView("summary");
      } catch (err) {
        if (isGone(err)) {
          // The run vanished out from under us — fall back to the menu.
          await goToMenu();
        } else {
          setView("error");
        }
      }
    },
    [clearAdvanceTimer, goToMenu],
  );

  /**
   * Start a run for `moduleId` + `modeId`: create the session, persist the
   * learner id + run context, draw the first exercise, and enter "playing".
   * Shared by the menu's Start and the summary's Play again.
   */
  const startRun = useCallback(
    async (moduleId: string, modeId: string) => {
      clearAdvanceTimer();
      setMenuBusy(true);
      setMenuError(null);
      try {
        // When signed in, send `null` so the server resolves the user's
        // account learner (and ignores the body) per the auth wire contract.
        const session = await createSession({
          learnerId: signedIn ? null : learnerId,
          moduleId,
          mode: modeId,
        });
        if (signedIn) {
          // Track the user's learner in memory, but DON'T overwrite the
          // anonymous learner key in localStorage — it must survive sign-out.
          setLearnerId(session.learner_id);
        } else {
          saveLearnerId(session.learner_id);
          setLearnerId(session.learner_id);
        }
        const ctx: RunContext = {
          sessionId: session.session_id,
          moduleId: session.module_id,
          mode: session.mode,
          targetCount: session.target_count,
          targetSeconds: session.target_seconds,
          deadline: session.deadline,
        };
        saveRun(ctx);
        const ex = await getNext(session.session_id);
        // Reset the per-run play state.
        setDone(0);
        setPercent(0);
        setStreak(0);
        setSummary(null);
        endingRef.current = false;
        setRun(ctx);
        presentExercise(ex);
        setMenuBusy(false);
        setView("playing");
      } catch (err) {
        setMenuBusy(false);
        if (isComplete(err)) {
          // Extremely unlikely on a fresh run, but be safe.
          setView("summary");
        } else {
          setMenuError("Couldn't start — please try again.");
        }
      }
    },
    [clearAdvanceTimer, learnerId, presentExercise, signedIn],
  );

  // Boot: resume a stored run, else show the menu.
  useEffect(() => {
    let alive = true;
    (async () => {
      const stored = readRun();
      if (stored) {
        try {
          const ex = await getNext(stored.sessionId);
          if (!alive) {
            return;
          }
          setRun(stored);
          saveRun(stored);
          endingRef.current = false;
          presentExercise(ex);
          setView("playing");
          return;
        } catch (err) {
          if (!alive) {
            return;
          }
          if (isComplete(err)) {
            await goToSummary(stored.sessionId);
            return;
          }
          if (isGone(err)) {
            clearRun();
            // Fall through to the menu.
          } else {
            setView("error");
            return;
          }
        }
      }
      if (alive) {
        await goToMenu();
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

  /**
   * Auth flow. Subscribe once to Firebase auth-state changes:
   *
   *  - Signed in: fetch an ID token -> `setAuthToken`; merge the current
   *    anonymous learner into the user's account (`claimAnonymous`, best-effort,
   *    once); then `getMe()` and switch the active learner to the user's
   *    learner. We clear any in-flight anonymous run and return to the menu so
   *    play resumes cleanly as the signed-in user.
   *  - Signed out: `setAuthToken(null)` and revert to the persisted anonymous
   *    learner id (the pre-login behaviour).
   *
   * A periodic refresh keeps the ~1h token fresh; 401s are also recovered
   * lazily via `getIdToken(true)` at the call sites that need it.
   */
  useEffect(() => {
    let alive = true;
    let refreshTimer: number | null = null;

    // A 401 on an authed request triggers a single forced token refresh + retry.
    setTokenRefresher(() => getIdToken(true));

    const clearRefresh = (): void => {
      if (refreshTimer !== null) {
        window.clearInterval(refreshTimer);
        refreshTimer = null;
      }
    };

    const unsubscribe = observeAuth((user: User | null) => {
      void (async () => {
        if (!alive) {
          return;
        }
        if (!user) {
          // Signed out -> anonymous play.
          clearRefresh();
          setAuthToken(null);
          setSignedIn(false);
          setAccountEmail(null);
          setLearnerId(readLearnerId());
          return;
        }

        // Signed in -> attach token, merge, adopt the user's learner.
        const token = await getIdToken();
        if (!alive) {
          return;
        }
        setAuthToken(token);

        // Best-effort one-shot merge of the anonymous learner.
        const anon = learnerIdRef.current;
        if (anon) {
          try {
            await claimAnonymous(anon);
          } catch {
            // Non-fatal: a failed merge must not block sign-in.
          }
        }
        if (!alive) {
          return;
        }

        try {
          const me = await getMe();
          if (!alive) {
            return;
          }
          // Switch the active learner to the user's account learner.
          clearAdvanceTimer();
          clearRun();
          setRun(null);
          setExercise(null);
          setSummary(null);
          endingRef.current = false;
          saveLearnerId(me.learner_id);
          setLearnerId(me.learner_id);
          setAccountEmail(me.email ?? user.email ?? null);
          setSignedIn(true);
          // Start fresh as the user.
          void goToMenu();
        } catch {
          // If /me fails we still consider the user signed in for UI purposes.
          if (alive) {
            setAccountEmail(user.email ?? null);
            setSignedIn(true);
          }
        }

        // Keep the token fresh (~every 50 min).
        clearRefresh();
        refreshTimer = window.setInterval(() => {
          void (async () => {
            const fresh = await getIdToken(true);
            if (alive) {
              setAuthToken(fresh);
            }
          })();
        }, 50 * 60 * 1000);
      })();
    });

    return () => {
      alive = false;
      clearRefresh();
      setTokenRefresher(null);
      unsubscribe();
    };
    // Subscribe once; the callback reads the latest learner via the ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSignOut = useCallback(() => {
    void signOutUser();
  }, []);

  /** Draw the next exercise; route 409 -> summary, gone -> menu. */
  const loadNext = useCallback(
    async (sid: string) => {
      try {
        const ex = await getNext(sid);
        presentExercise(ex);
      } catch (err) {
        if (isComplete(err)) {
          await goToSummary(sid);
        } else if (isGone(err)) {
          await goToMenu();
        } else {
          setView("error");
        }
      }
    },
    [goToMenu, goToSummary, presentExercise],
  );

  const advance = useCallback(() => {
    clearAdvanceTimer();
    if (endingRef.current) {
      return;
    }
    if (run) {
      void loadNext(run.sessionId);
    }
  }, [clearAdvanceTimer, loadNext, run]);

  const handleSubmit = useCallback(async () => {
    if (
      !run ||
      !exercise ||
      phase !== "answering" ||
      submittingRef.current ||
      endingRef.current
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
      const result = await submitAnswer(run.sessionId, answer, elapsedSeconds);
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
      if (result.finished) {
        // Let the feedback land, then surface the summary.
        advanceTimerRef.current = window.setTimeout(() => {
          void goToSummary(run.sessionId);
        }, ADVANCE_DELAY_MS);
      } else {
        advanceTimerRef.current = window.setTimeout(advance, ADVANCE_DELAY_MS);
      }
    } catch (err) {
      if (isComplete(err)) {
        await goToSummary(run.sessionId);
      } else if (isGone(err)) {
        await goToMenu();
      } else {
        setView("error");
      }
    } finally {
      submittingRef.current = false;
    }
  }, [
    advance,
    clearAdvanceTimer,
    exercise,
    goToMenu,
    goToSummary,
    phase,
    run,
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

  /** The 3-minute countdown hit zero — close out the run into the summary. */
  const handleDeadlineExpire = useCallback(() => {
    if (run) {
      void goToSummary(run.sessionId);
    }
  }, [goToSummary, run]);

  const handleQuit = useCallback(() => {
    void goToMenu();
  }, [goToMenu]);

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

      {view !== "playing" && (
        <div className="account-bar">
          {signedIn ? (
            <div className="account">
              {accountEmail ? (
                <span className="account__email" title={accountEmail}>
                  {accountEmail}
                </span>
              ) : null}
              <button
                type="button"
                className="account__btn"
                onClick={handleSignOut}
              >
                Sign out
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="account__btn account__btn--primary"
              onClick={() => setAuthOpen(true)}
            >
              Sign in
            </button>
          )}
        </div>
      )}

      <main className="app">
        {view === "loading" && (
          <div className="banner" role="status" aria-live="polite">
            <div className="spinner" style={{ margin: "0 auto" }} />
            <p>Getting your meadow ready…</p>
          </div>
        )}

        {view === "error" && (
          <div className="banner" role="alert">
            <span className="banner__emoji" aria-hidden="true">
              🌧️
            </span>
            <p>Oops — we lost the connection. Let&rsquo;s try again.</p>
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void goToMenu()}
            >
              Try again
            </button>
          </div>
        )}

        {view === "menu" && (
          <motion.div
            style={{ width: "min(100%, 40rem)", display: "flex", justifyContent: "center" }}
            custom={0}
            variants={reveal}
            initial="hidden"
            animate="show"
          >
            <MainMenu
              modules={modules}
              modes={modes}
              onStart={(moduleId, modeId) => void startRun(moduleId, modeId)}
              busy={menuBusy}
              error={menuError}
            />
          </motion.div>
        )}

        {view === "playing" && exercise && run && (
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
                mode={run.mode}
                targetCount={run.targetCount}
                questionsDone={done}
                deadline={run.deadline}
                onDeadlineExpire={handleDeadlineExpire}
                soundOn={soundOn}
                onToggleSound={handleToggleSound}
                onOpenStats={() => setStatsOpen(true)}
                onQuit={handleQuit}
                email={accountEmail}
                signedIn={signedIn}
                onSignIn={() => setAuthOpen(true)}
                onSignOut={handleSignOut}
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

        {view === "summary" && summary && run && (
          <motion.div
            style={{ width: "min(100%, 32rem)", display: "flex", justifyContent: "center" }}
            custom={0}
            variants={reveal}
            initial="hidden"
            animate="show"
          >
            <SessionSummary
              summary={summary}
              onPlayAgain={() => void startRun(run.moduleId, run.mode)}
              onMenu={() => void goToMenu()}
            />
          </motion.div>
        )}
      </main>

      <AnimatePresence>
        {statsOpen && run && (
          <StatsModal
            sessionId={run.sessionId}
            onClose={() => setStatsOpen(false)}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {authOpen && <AuthModal onClose={() => setAuthOpen(false)} />}
      </AnimatePresence>
    </>
  );
}
