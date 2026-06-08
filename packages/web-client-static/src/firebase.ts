/**
 * Firebase Auth bootstrap for Math Meadow.
 *
 * The web config below is **public** (it ships in every Firebase web app and is
 * not a secret); we still let a deployment override any field via
 * `import.meta.env.VITE_FIREBASE_*` so the same bundle can target another
 * project. Analytics is intentionally NOT initialised — we keep the student
 * experience free of tracking.
 *
 * This module is the ONLY place that imports the Firebase SDK. The rest of the
 * app talks to the small helper surface exported here (sign-in/out, an auth
 * observer, and an ID-token getter), so swapping the auth provider later is a
 * single-file change.
 */
import { initializeApp, type FirebaseApp } from "firebase/app";
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  type Auth,
  type User,
} from "firebase/auth";

const env = import.meta.env;

const firebaseConfig = {
  apiKey: env.VITE_FIREBASE_API_KEY ?? "AIzaSyAawI_a8FdWKRHxRStQgEDhFWGiYUiqwG8",
  authDomain:
    env.VITE_FIREBASE_AUTH_DOMAIN ?? "math-practice-498810.firebaseapp.com",
  projectId: env.VITE_FIREBASE_PROJECT_ID ?? "math-practice-498810",
  storageBucket:
    env.VITE_FIREBASE_STORAGE_BUCKET ??
    "math-practice-498810.firebasestorage.app",
  messagingSenderId:
    env.VITE_FIREBASE_MESSAGING_SENDER_ID ?? "1012906156465",
  appId:
    env.VITE_FIREBASE_APP_ID ??
    "1:1012906156465:web:cf3654da6f85ef9e171d90",
  measurementId: env.VITE_FIREBASE_MEASUREMENT_ID ?? "G-3P6E07DCDK",
};

const app: FirebaseApp = initializeApp(firebaseConfig);

/** The shared Auth instance. */
export const auth: Auth = getAuth(app);

/** Create a new email/password account (also signs the user in). */
export function signUpEmail(email: string, password: string): Promise<unknown> {
  return createUserWithEmailAndPassword(auth, email, password);
}

/** Sign in with an existing email/password account. */
export function signInEmail(email: string, password: string): Promise<unknown> {
  return signInWithEmailAndPassword(auth, email, password);
}

/** Sign in with Google via a popup. */
export function signInGoogle(): Promise<unknown> {
  const provider = new GoogleAuthProvider();
  return signInWithPopup(auth, provider);
}

/** Sign the current user out. */
export function signOutUser(): Promise<void> {
  return signOut(auth);
}

/**
 * Subscribe to auth-state changes. The callback fires with the current `User`
 * (or `null` when signed out) immediately and on every subsequent change.
 * Returns the unsubscribe function.
 */
export function observeAuth(cb: (user: User | null) => void): () => void {
  return onAuthStateChanged(auth, cb);
}

/**
 * Resolve the current user's Firebase ID token, or `null` when signed out.
 * Pass `forceRefresh = true` to bypass the SDK cache (used to recover from a
 * 401 after the ~1h token lifetime).
 */
export async function getIdToken(
  forceRefresh = false,
): Promise<string | null> {
  const user = auth.currentUser;
  if (!user) {
    return null;
  }
  try {
    return await user.getIdToken(forceRefresh);
  } catch {
    return null;
  }
}

export type { User };
