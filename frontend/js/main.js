// 초기화, 화면 조립, 이벤트 위임. 화면은 하나(대화)이고 해시로 대화를 고른다: #/ (새 대화), #/c/{id}
import { api } from "./api.js";
import { authErrorMessage, onAuthChange, signIn, signOut, signUp, usingAuthEmulator } from "./auth.js";
import { loadLists, openConversation } from "./chat.js";
import { h } from "./dom.js";
import { getState, resetUserData, subscribe, update } from "./store.js";
import chatView from "./views/chat.js";
import { panelActions, renderPanel } from "./views/panels.js";
import sidebarView from "./views/sidebar.js";

const appRoot = document.getElementById("app");

function conversationFromHash() {
  const m = location.hash.match(/^#\/c\/([^/?]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

// ---------- 렌더링 ----------

function renderServerBanner(server) {
  if (server.status === "waking") {
    return h("div", { class: "banner", role: "status" }, "서버를 깨우는 중이에요… 무료 서버는 첫 접속에 30초 넘게 걸릴 수 있어요.");
  }
  if (server.status === "error") {
    return h("div", { class: "banner error", role: "alert" }, server.error || "서버에 연결할 수 없습니다.",
      h("button", { class: "btn small", type: "button", dataset: { action: "retryHealth" } }, "다시 연결"));
  }
  return null;
}

function renderLogin(state) {
  const d = state.authDraft;
  const isSignup = d.mode === "signup";
  return h("main", { class: "login" },
    h("section", { class: "login-card" },
      h("p", { class: "brand" }, "여행 비서"),
      h("h1", {}, "말로 계획하는 여행"),
      h("p", { class: "muted" }, "가고 싶은 곳을 말하면 코스를 짜고, 다녀온 뒤 이야기를 들려주면 승인한 것만 다음 여행에 반영해요."),
      usingAuthEmulator ? h("p", { class: "badge warn" }, "로컬 인증 에뮬레이터 사용 중") : null,
      h("form", { class: "stack", dataset: { action: isSignup ? "signUp" : "signIn" } },
        h("label", {}, "이메일", h("input", { type: "email", required: true, autocomplete: "email", value: d.email, dataset: { bind: "authDraft.email" } })),
        h("label", {}, "비밀번호", h("input", { type: "password", required: true, minlength: 6, autocomplete: isSignup ? "new-password" : "current-password", value: d.password, dataset: { bind: "authDraft.password" } })),
        state.auth.error ? h("p", { class: "notice error", role: "alert" }, state.auth.error) : null,
        h("button", { class: "btn primary block", type: "submit", disabled: state.auth.busy }, isSignup ? "가입하기" : "로그인"),
        h("button", { class: "btn link", type: "button", dataset: { action: "toggleAuthMode" } },
          isSignup ? "이미 계정이 있어요 · 로그인" : "처음이에요 · 가입하기"))));
}

function renderApp(state) {
  return h("div", { class: "app" },
    sidebarView.render(state),
    state.sidebarOpen ? h("button", { class: "scrim only-mobile", type: "button", "aria-label": "메뉴 닫기", dataset: { action: "toggleSidebar" } }) : null,
    h("main", { class: "main" },
      renderServerBanner(state.server),
      state.server.status === "ready" ? safe(() => chatView.render(state)) : h("p", { class: "muted center" }, "서버 준비 후 대화를 불러와요.")),
    renderPanel(state),
    state.toast ? h("div", { class: `toast ${state.toast.kind}`, role: "status" }, state.toast.message) : null);
}

function safe(fn) {
  try {
    return fn();
  } catch (err) {
    // 렌더 오류가 상태 갱신 흐름(스트리밍 등)까지 멈추지 않도록 화면에만 표시한다.
    console.error(err);
    return h("div", { class: "notice error", role: "alert" }, "화면을 표시하지 못했어요. 새로고침해 주세요.");
  }
}

let forceBottom = false;

function render() {
  const state = getState();
  let node;
  if (state.auth.status === "unknown") node = h("p", { class: "muted center" }, "로그인 상태 확인 중…");
  else if (state.auth.status === "signedOut") node = h("div", {}, renderServerBanner(state.server), renderLogin(state));
  else node = renderApp(state);

  // 스크롤: 바닥 근처에 있었으면 새 내용이 와도 바닥을 따라가고, 위를 읽고 있었으면 위치를 유지한다.
  const prev = document.getElementById("messages");
  const stick = !prev || forceBottom || prev.scrollHeight - prev.scrollTop - prev.clientHeight < 120;
  const top = prev?.scrollTop || 0;
  // 포커스 유지: 같은 data-bind 입력이 다시 그려지면 포커스와 커서를 복원한다.
  const active = document.activeElement;
  const bind = active?.dataset?.bind;
  const caret = bind && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;

  appRoot.replaceChildren(node);

  const next = document.getElementById("messages");
  if (next) next.scrollTop = stick ? next.scrollHeight : top;
  forceBottom = false;
  const composer = document.getElementById("composer-input");
  if (composer) autosize(composer);
  if (bind) {
    const again = appRoot.querySelector(`[data-bind="${CSS.escape(bind)}"]`);
    if (again) {
      again.focus();
      if (caret && typeof again.setSelectionRange === "function") {
        try { again.setSelectionRange(caret[0], caret[1]); } catch { /* 선택 범위를 지원하지 않는 입력 */ }
      }
    }
  }
}

let frame = 0;
function scheduleRender() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    render();
  });
}

function autosize(el) {
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
}

// ---------- 이벤트 위임 ----------

function setPath(path, value) {
  const [head, ...rest] = path.split(".");
  const s = getState();
  const clone = (obj, keys) => {
    if (!keys.length) return value;
    const [k, ...more] = keys;
    const base = obj && typeof obj === "object" ? obj : {};
    return { ...base, [k]: clone(base[k], more) };
  };
  return { [head]: clone(s[head], rest) };
}

function handleBind(event) {
  const el = event.target.closest("[data-bind]");
  if (!el) return;
  const value = el.type === "checkbox" ? el.checked : el.value;
  // 입력창은 매 글자마다 다시 그리지 않는다(보내기 버튼 상태만 바꾼다).
  update(setPath(el.dataset.bind, value), { render: el.dataset.rerender === "true" });
  if (el.id === "composer-input") {
    autosize(el);
    const sendBtn = appRoot.querySelector(".composer .send");
    if (sendBtn) sendBtn.disabled = getState().live?.status === "running" || !el.value.trim();
  }
}

const globalActions = {
  async signIn() {
    await doAuth(signIn);
  },
  async signUp() {
    await doAuth(signUp);
  },
  toggleAuthMode() {
    const d = getState().authDraft;
    update({ authDraft: { ...d, mode: d.mode === "signup" ? "signin" : "signup" }, auth: { ...getState().auth, error: null } });
  },
  async signOut() {
    await signOut();
  },
  retryHealth() {
    wakeServer();
  },
};

const ACTIONS = { ...globalActions, ...sidebarView.actions, ...panelActions, ...chatView.actions };

async function doAuth(fn) {
  const { email, password } = getState().authDraft;
  update({ auth: { ...getState().auth, busy: true, error: null } });
  try {
    await fn(email.trim(), password);
    update({ authDraft: { ...getState().authDraft, password: "" } });
  } catch (err) {
    update({ auth: { ...getState().auth, busy: false, error: authErrorMessage(err) } });
  }
}

function dispatch(action, el, event) {
  const fn = ACTIONS[action];
  if (!fn) return;
  if (["sendMessage", "sendText"].includes(action)) forceBottom = true;
  Promise.resolve(fn({ el, event, data: { ...el.dataset } })).catch((err) => console.error(err));
}

appRoot.addEventListener("click", (event) => {
  const el = event.target.closest("[data-action]");
  if (!el || el.tagName === "FORM") return;
  event.preventDefault();
  dispatch(el.dataset.action, el, event);
});
appRoot.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-action]");
  if (!form) return;
  event.preventDefault();
  dispatch(form.dataset.action, form, event);
});
appRoot.addEventListener("input", handleBind);
appRoot.addEventListener("change", (event) => {
  // 글 입력은 input 이벤트로 이미 반영된다. 다시 그리면서 포커스를 잃은 입력창의 change가
  // 보낸 뒤 비운 입력값을 되살리지 않도록 체크박스·선택 상자만 여기서 반영한다.
  if (["checkbox", "select-one"].includes(event.target.type)) handleBind(event);
  const el = event.target.closest("[data-change-action]");
  if (el) dispatch(el.dataset.changeAction, el, event);
});
appRoot.addEventListener("keydown", (event) => {
  const el = event.target;
  // Enter로 보내기, Shift+Enter로 줄바꿈. 한글 조합 중(isComposing)에는 보내지 않는다.
  if (el.dataset?.submitOnEnter && event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    el.form?.requestSubmit();
  }
  if (event.key === "Escape" && getState().panel) update({ panel: null });
});
// <details>는 다시 그려도 열린 상태를 유지한다(toggle 이벤트는 버블링되지 않아 캡처로 받는다).
appRoot.addEventListener("toggle", (event) => {
  const key = event.target.dataset?.openKey;
  if (key) update((s) => ({ open: { ...s.open, [key]: event.target.open } }), { render: false });
}, true);

// ---------- 초기화 ----------

async function wakeServer() {
  update({ server: { status: "waking", error: null } });
  try {
    await api.health();
    update({ server: { status: "ready", error: null } });
    afterReady();
  } catch (err) {
    update({ server: { status: "error", error: err.message } });
  }
}

function afterReady() {
  const s = getState();
  if (s.auth.status !== "signedIn" || s.server.status !== "ready") return;
  loadLists();
  openConversation(conversationFromHash());
}

subscribe(scheduleRender);
window.addEventListener("hashchange", () => {
  update({ sidebarOpen: false });
  if (getState().auth.status === "signedIn") openConversation(conversationFromHash());
});

onAuthChange((user) => {
  if (user) {
    update({ auth: { status: "signedIn", user, error: null, busy: false } });
    afterReady();
  } else {
    resetUserData();
    update({ auth: { status: "signedOut", user: null, error: null, busy: false } });
  }
});

wakeServer();
