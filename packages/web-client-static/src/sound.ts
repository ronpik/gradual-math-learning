/**
 * Tiny WebAudio chime helper — gentle tones on correct / wrong, plus a
 * localStorage-backed on/off preference. No audio assets are bundled; the
 * sounds are synthesised so the production `dist/` stays self-contained.
 */

const PREF_KEY = "math-meadow.sound";

/** Read the persisted sound preference (defaults to ON). */
export function readSoundPref(): boolean {
  try {
    const raw = window.localStorage.getItem(PREF_KEY);
    if (raw === null) {
      return true;
    }
    return raw === "1";
  } catch {
    return true;
  }
}

/** Persist the sound preference. */
export function saveSoundPref(enabled: boolean): void {
  try {
    window.localStorage.setItem(PREF_KEY, enabled ? "1" : "0");
  } catch {
    // Non-fatal.
  }
}

let ctx: AudioContext | null = null;

function audioContext(): AudioContext | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    if (!ctx) {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext;
      if (!Ctor) {
        return null;
      }
      ctx = new Ctor();
    }
    if (ctx.state === "suspended") {
      void ctx.resume();
    }
    return ctx;
  } catch {
    return null;
  }
}

function tone(
  frequency: number,
  startAt: number,
  duration: number,
  peak: number,
): void {
  const ac = audioContext();
  if (!ac) {
    return;
  }
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.type = "sine";
  osc.frequency.value = frequency;
  const t0 = ac.currentTime + startAt;
  gain.gain.setValueAtTime(0, t0);
  gain.gain.linearRampToValueAtTime(peak, t0 + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
  osc.connect(gain);
  gain.connect(ac.destination);
  osc.start(t0);
  osc.stop(t0 + duration + 0.02);
}

/** A bright, happy two-note rise. */
export function playCorrect(): void {
  tone(660, 0, 0.16, 0.18);
  tone(880, 0.1, 0.22, 0.18);
}

/** A soft, low, non-scary single tone. */
export function playWrong(): void {
  tone(300, 0, 0.26, 0.12);
}
