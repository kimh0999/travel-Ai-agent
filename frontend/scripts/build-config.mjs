// Vercel 빌드 단계에서 환경변수로 공개 설정(config.js)을 생성한다.
// 서버 비밀값(ANTHROPIC_API_KEY, 서비스 계정, 카카오 키)은 절대 읽지 않는다 — 아래 목록의 공개값만 사용한다.
import { writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const env = process.env;
const useEmulator = env.USE_AUTH_EMULATOR === "true";
const config = {
  apiBaseUrl: (env.API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, ""),
  firebase: {
    apiKey: env.FIREBASE_API_KEY || (useEmulator ? "fake-api-key" : ""),
    authDomain: env.FIREBASE_AUTH_DOMAIN || "",
    projectId: env.FIREBASE_PROJECT_ID || (useEmulator ? "demo-travel" : ""),
    appId: env.FIREBASE_APP_ID || "",
  },
  authEmulatorUrl: useEmulator ? env.AUTH_EMULATOR_URL || "http://127.0.0.1:9099" : null,
};
if (!useEmulator && (!config.firebase.apiKey || !config.firebase.projectId)) {
  console.error("FIREBASE_API_KEY와 FIREBASE_PROJECT_ID가 필요합니다 (로컬 에뮬레이터는 USE_AUTH_EMULATOR=true).");
  process.exit(1);
}
const out = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "config.js");
writeFileSync(out, `// 빌드 시 생성되는 공개 설정. 직접 수정하지 마세요.\nexport const config = Object.freeze(${JSON.stringify(config, null, 2)});\n`);
console.log(`config.js 생성: apiBaseUrl=${config.apiBaseUrl}, emulator=${useEmulator}`);
