// Firebase Auth만 사용한다. Firestore SDK는 불러오지 않는다 (모든 데이터는 API 서버 경유).
import { initializeApp } from "https://www.gstatic.com/firebasejs/12.19.0/firebase-app.js";
import {
  connectAuthEmulator,
  createUserWithEmailAndPassword,
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut as fbSignOut,
} from "https://www.gstatic.com/firebasejs/12.19.0/firebase-auth.js";
import { config } from "../config.js";

const app = initializeApp(config.firebase);
const auth = getAuth(app);
if (config.authEmulatorUrl) {
  connectAuthEmulator(auth, config.authEmulatorUrl, { disableWarnings: true });
}

export const usingAuthEmulator = Boolean(config.authEmulatorUrl);

export function onAuthChange(callback) {
  return onAuthStateChanged(auth, (user) => callback(user ? { uid: user.uid, email: user.email } : null));
}

export async function signIn(email, password) {
  await signInWithEmailAndPassword(auth, email, password);
}

export async function signUp(email, password) {
  await createUserWithEmailAndPassword(auth, email, password);
}

export async function signOut() {
  await fbSignOut(auth);
}

export async function getIdToken() {
  const user = auth.currentUser;
  if (!user) return null;
  return user.getIdToken();
}

const AUTH_MESSAGES = {
  "auth/invalid-email": "이메일 형식이 올바르지 않습니다.",
  "auth/invalid-credential": "이메일 또는 비밀번호가 올바르지 않습니다.",
  "auth/user-not-found": "이메일 또는 비밀번호가 올바르지 않습니다.",
  "auth/wrong-password": "이메일 또는 비밀번호가 올바르지 않습니다.",
  "auth/email-already-in-use": "이미 가입된 이메일입니다.",
  "auth/weak-password": "비밀번호는 6자 이상이어야 합니다.",
  "auth/network-request-failed": "네트워크 오류로 로그인하지 못했습니다.",
  "auth/too-many-requests": "시도가 너무 많습니다. 잠시 후 다시 시도하세요.",
};

export function authErrorMessage(error) {
  return AUTH_MESSAGES[error?.code] || "로그인에 실패했습니다.";
}
