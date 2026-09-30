// 로컬 확인용: 에뮬레이터, 백엔드(8010), 프론트(5500)를 한 번에 띄운다. Ctrl+C로 모두 종료.
// AI·장소 검색 모드는 backend/.env를 따른다(없으면 모의 모드). 실제 Claude: backend/.env에 ANTHROPIC_API_KEY, AI_MODE=live
import { spawn } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const toolsDir = path.join(root, ".tools");
const env = { ...process.env };
if (existsSync(toolsDir)) {
  const jdk = readdirSync(toolsDir).find((d) => d.startsWith("jdk-21"));
  if (jdk) {
    env.JAVA_HOME = path.join(toolsDir, jdk);
    env.PATH = path.join(env.JAVA_HOME, "bin") + path.delimiter + env.PATH;
  }
}
const isWin = process.platform === "win32";
const python = path.join(root, "backend", ".venv", isWin ? "Scripts\\python.exe" : "bin/python");
const firebaseBin = path.join(root, "node_modules", "firebase-tools", "lib", "bin", "firebase.js");

const backendEnv = {
  ...env,
  FIRESTORE_EMULATOR_HOST: "127.0.0.1:8080",
  FIREBASE_AUTH_EMULATOR_HOST: "127.0.0.1:9099",
  FIREBASE_PROJECT_ID: "demo-travel",
  CORS_ORIGINS: "http://127.0.0.1:5500",
};

const children = [
  spawn(process.execPath, [firebaseBin, "emulators:start", "--only", "auth,firestore", "--project", "demo-travel"],
    { cwd: root, env, stdio: "inherit" }),
  spawn(python, ["-m", "uvicorn", "app.main:app", "--port", "8010"],
    { cwd: path.join(root, "backend"), env: backendEnv, stdio: "inherit" }),
  spawn(python, ["-m", "http.server", "5500", "--bind", "127.0.0.1"],
    { cwd: path.join(root, "frontend"), env, stdio: "inherit" }),
];

console.log("\n  앱: http://127.0.0.1:5500   API 문서: http://127.0.0.1:8010/docs   에뮬레이터 UI: http://127.0.0.1:4000\n");

const stopAll = () => {
  for (const c of children) if (c.exitCode === null) c.kill();
};
process.on("SIGINT", stopAll);
process.on("SIGTERM", stopAll);
for (const c of children) c.on("exit", stopAll);
