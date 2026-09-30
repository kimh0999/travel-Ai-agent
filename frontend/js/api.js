// 모든 서버 요청은 이 모듈을 거친다: 인증 헤더, 타임아웃(AbortController), 오류 변환, SSE 읽기.
import { config } from "../config.js";
import { getIdToken } from "./auth.js";

export class ApiError extends Error {
  constructor(code, message, status = 0) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

const DEFAULT_TIMEOUT_MS = 20000;
const STREAM_IDLE_MS = 40000; // 서버는 15초마다 keepalive를 보낸다. 이보다 오래 조용하면 끊긴 것으로 보고 다시 붙는다.

async function authHeaders(auth) {
  if (!auth) return {};
  const token = await getIdToken();
  if (!token) throw new ApiError("UNAUTHENTICATED", "로그인이 필요합니다.", 401);
  return { Authorization: `Bearer ${token}` };
}

async function toError(res) {
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  const e = data?.error;
  return new ApiError(e?.code || `HTTP_${res.status}`, e?.message || `요청에 실패했습니다 (${res.status}).`, res.status);
}

async function request(method, path, { body, timeoutMs = DEFAULT_TIMEOUT_MS, auth = true } = {}) {
  const headers = await authHeaders(auth);
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`${config.apiBaseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    if (err.name === "AbortError") {
      throw new ApiError("TIMEOUT", "응답이 너무 오래 걸립니다. 입력 내용은 그대로 있으니 다시 시도하세요.");
    }
    throw new ApiError("NETWORK", "서버에 연결할 수 없습니다. 네트워크 상태를 확인하고 다시 시도하세요.");
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 204) return null;
  if (!res.ok) throw await toError(res);
  try {
    return await res.json();
  } catch {
    return null;
  }
}

// 턴 이벤트(SSE)를 읽어 onEvent로 넘긴다. 스트림이 끝나면 resolve, 끊기거나 너무 오래 조용하면 reject.
async function streamEvents(turnId, { after, attempt, onEvent, signal }) {
  const headers = await authHeaders(true);
  const q = new URLSearchParams({ after: String(after) });
  if (attempt) q.set("attempt", String(attempt));
  const controller = new AbortController();
  signal?.addEventListener("abort", () => controller.abort());
  let idle = setTimeout(() => controller.abort(), STREAM_IDLE_MS);
  const bump = () => {
    clearTimeout(idle);
    idle = setTimeout(() => controller.abort(), STREAM_IDLE_MS);
  };
  try {
    const res = await fetch(`${config.apiBaseUrl}/api/chat/turns/${encodeURIComponent(turnId)}/events?${q}`, {
      headers, signal: controller.signal,
    });
    if (!res.ok) throw await toError(res);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      bump();
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const chunk = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const data = chunk.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
        if (data) onEvent(JSON.parse(data));
      }
    }
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("STREAM_LOST", "연결이 잠시 끊겼어요. 다시 연결하는 중…");
  } finally {
    clearTimeout(idle);
  }
}

const enc = encodeURIComponent;

export const api = {
  health: () => request("GET", "/health", { auth: false, timeoutMs: 60000 }),

  listPreferences: () => request("GET", "/api/preferences"),
  createPreference: (body) => request("POST", "/api/preferences", { body }),
  updatePreference: (id, body) => request("PUT", `/api/preferences/${enc(id)}`, { body }),
  deletePreference: (id) => request("DELETE", `/api/preferences/${enc(id)}`),

  listTrips: () => request("GET", "/api/trips"),
  deleteTripPreview: (id) => request("GET", `/api/trips/${enc(id)}/delete-preview`),
  deleteTrip: (id, body) => request("DELETE", `/api/trips/${enc(id)}`, { body }),
  listVersions: (id) => request("GET", `/api/trips/${enc(id)}/versions`),
  restoreVersion: (id, vid) => request("POST", `/api/trips/${enc(id)}/versions/${enc(vid)}/restore`),
  setPin: (id, itemId, pinned) => request("POST", `/api/trips/${enc(id)}/pins`, { body: { item_id: itemId, pinned } }),

  approveProposal: (id, editedValue) =>
    request("POST", `/api/memory-proposals/${enc(id)}/approve`, { body: editedValue ? { edited_value: editedValue } : {} }),
  rejectProposal: (id) => request("POST", `/api/memory-proposals/${enc(id)}/reject`),

  startTurn: (body) => request("POST", "/api/chat/turns", { body }),
  getTurn: (id) => request("GET", `/api/chat/turns/${enc(id)}`),
  retryTurn: (id) => request("POST", `/api/chat/turns/${enc(id)}/retry`),
  streamEvents,

  listConversations: () => request("GET", "/api/conversations"),
  getConversation: (id) => request("GET", `/api/conversations/${enc(id)}`),
  deleteConversation: (id) => request("DELETE", `/api/conversations/${enc(id)}`),
};
