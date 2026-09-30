// 에뮬레이터(Auth, Firestore) 안에서 백엔드 pytest를 실행한다.
// firebase-tools는 Java 21+가 필요하다. 프로젝트의 .tools/jdk-21*가 있으면 그것을 우선 사용한다.
// 사용: npm test -- [pytest 인자]   예) npm test -- backend/tests/test_preferences.py -k crud
import { spawnSync } from "node:child_process";
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
const python = isWin ? "backend\\.venv\\Scripts\\python.exe" : "backend/.venv/bin/python";
const args = process.argv.slice(2);
const pytestArgs = args.length ? args.join(" ") : "backend/tests";
const cmd = `${python} -m pytest -c backend/pytest.ini --rootdir backend -q ${pytestArgs}`;
// npx(.cmd)를 셸로 감싸면 인용 처리가 꼬이므로 firebase-tools를 node로 직접 실행한다.
const firebaseBin = path.join(root, "node_modules", "firebase-tools", "lib", "bin", "firebase.js");
const result = spawnSync(
  process.execPath,
  // 테스트용 포트(firebase.test.json)를 따로 써서 `npm run dev`를 켜 둔 채로도 실행할 수 있다.
  [firebaseBin, "emulators:exec", "--config", "firebase.test.json", "--only", "auth,firestore", "--project", "demo-travel", cmd],
  { cwd: root, env, stdio: "inherit" },
);
process.exit(result.status ?? 1);
