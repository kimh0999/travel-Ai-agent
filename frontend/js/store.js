// 단일 상태 객체 + 구독. 상태 변경은 이 모듈의 함수로만 한다.

const state = {
  server: { status: "waking", error: null }, // waking | ready | error
  auth: { status: "unknown", user: null, error: null, busy: false }, // unknown | signedOut | signedIn
  authDraft: { email: "", password: "", mode: "signin" },

  trips: { items: [], status: "idle", error: null },
  conversations: { items: [], status: "idle", error: null },
  conv: { id: null, data: null, status: "idle", error: null }, // 지금 보고 있는 대화
  activeTripId: null, // 화면 상단에서 고른 '현재 작업 중인 여행'
  draft: "", // 입력창
  // 진행 중이거나 실패한 턴: { turnId, clientTurnId, attempt, lastSeq, message, text, tools, cards, status, error, reconnecting }
  live: null,

  sidebarOpen: false, // 모바일 사이드바
  panel: null, // null | { type: "prefs" } | { type: "trip", tripId }
  open: {}, // 펼친 <details> 키 → true (다시 그려도 유지)
  dayTab: {}, // 코스 카드 키 → 선택한 날
  busy: {}, // 버튼 중복 클릭 방지 키 → true
  proposalEdits: {}, // 변경안 id → 수정 중인 문장 (undefined면 수정 안 함)

  preferences: { items: [], status: "idle", error: null },
  prefDraft: { category: "activity", value: "", strength: "soft", subject: "self", sensitive: false, share_with_ai: false },
  prefEditing: null, // { id, value, strength, subject }
  prefConfirmDeleteId: null,
  tripPanel: { versions: [], preview: null, status: "idle", error: null, selected: [], confirming: false },

  toast: null,
};

const listeners = new Set();

export function getState() {
  return state;
}

// patch: 객체 또는 (state) => 객체. options.render=false면 구독자에게 알리지 않는다(입력 초안 저장용).
export function update(patch, options = {}) {
  const next = typeof patch === "function" ? patch(state) : patch;
  Object.assign(state, next);
  if (options.render !== false) listeners.forEach((fn) => fn(state));
}

// state[key][id] 형태의 중첩 상태를 부분 갱신한다.
export function updateIn(key, id, value, options = {}) {
  update((s) => ({ [key]: { ...s[key], [id]: value } }), options);
}

export function updateLive(patch) {
  update((s) => (s.live ? { live: { ...s.live, ...(typeof patch === "function" ? patch(s.live) : patch) } } : {}));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

let toastTimer = null;
export function showToast(message, kind = "info") {
  update({ toast: { message, kind } });
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => update({ toast: null }), 4000);
}

// 로그아웃 시 이전 사용자의 데이터가 화면에 남지 않도록 사용자 데이터 영역을 초기값으로 되돌린다.
const INITIAL = structuredClone(state);
const KEEP_ON_RESET = new Set(["server", "auth", "authDraft", "toast"]);
export function resetUserData() {
  const fresh = structuredClone(INITIAL);
  for (const key of Object.keys(fresh)) {
    if (!KEEP_ON_RESET.has(key)) state[key] = fresh[key];
  }
}
