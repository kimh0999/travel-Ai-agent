// 메인 화면: 현재 작업 중인 여행 + 대화 + 입력창.
import { api } from "../api.js";
import { reloadConversation, retry, send } from "../chat.js";
import { h, richText, select } from "../dom.js";
import { getState, showToast, update, updateIn } from "../store.js";
import { renderCard, tripLength, tripWhen } from "./cards.js";

const SUGGESTIONS = [
  "다음 달 부산 2박 3일, 바다 보이는 카페 위주로 짜줘",
  "지난 여행 다녀왔어. 좋았던 점이랑 아쉬운 점 말해 줄게",
  "당일치기로 갈 만한 곳 추천해줘",
];

function assistantBlock({ text, cards, tools, state, answered, streaming }) {
  const questions = cards.filter((c) => c.type === "question");
  const others = cards.filter((c) => c.type !== "question");
  return h("div", { class: "msg assistant" },
    h("div", { class: "avatar", "aria-hidden": "true" }, "여"),
    h("div", { class: "msg-body" },
      tools?.length ? h("ul", { class: "steps", "aria-label": "진행 상황" }, tools.map((t) => h("li", { class: `step ${t.status}` },
        h("span", { class: "step-icon", "aria-hidden": "true" }),
        t.label, t.status === "failed" && t.message ? h("span", { class: "step-error" }, ` — ${t.message}`) : null))) : null,
      others.map((c) => renderCard(c, state)),
      text ? h("div", { class: "rt" }, richText(text)) : streaming && !others.length && !tools?.length
        ? h("p", { class: "typing", role: "status" }, h("span"), h("span"), h("span")) : null,
      questions.map((c) => renderCard(c, state, { answered }))));
}

function userBlock(text) {
  return h("div", { class: "msg user" }, h("p", { class: "bubble" }, text));
}

function renderLive(live, state) {
  const failed = live.status === "failed";
  return h("div", { class: "live" },
    userBlock(live.message),
    assistantBlock({ text: live.text, cards: live.cards, tools: live.tools, state, answered: true, streaming: !failed }),
    live.reconnecting ? h("p", { class: "notice", role: "status" }, "연결이 잠시 끊겨 다시 연결하는 중이에요. 진행한 내용은 서버에 저장되고 있어요.") : null,
    failed ? h("div", { class: "notice error", role: "alert" },
      h("p", {}, live.error?.message || "처리하지 못했어요."),
      h("p", { class: "small" }, "이미 만든 여행·코스는 그대로 있어요. 다시 시도하면 진행한 곳부터 이어서 하고 같은 작업을 두 번 하지 않아요."),
      h("div", { class: "row wrap" },
        h("button", { class: "btn primary small", type: "button", dataset: { action: "retryTurn" } }, "다시 시도"),
        h("button", { class: "btn small", type: "button", dataset: { action: "dismissLive" } }, "닫기"))) : null);
}

function renderEmpty() {
  return h("div", { class: "welcome" },
    h("h1", {}, "어디로 떠나볼까요?"),
    h("p", { class: "muted" }, "가고 싶은 곳과 기간을 말해 주세요. 필요한 것만 짧게 여쭤보고 바로 코스를 짜 드려요. 여행을 다녀온 뒤 소감을 말해 주시면, 승인하신 것만 다음 여행에 반영해요."),
    h("div", { class: "suggestions" }, SUGGESTIONS.map((s) => h("button", { class: "btn chip", type: "button", dataset: { action: "sendText", text: s } }, s))));
}

function renderHeader(state) {
  const trips = state.trips.items;
  const active = trips.find((t) => t.id === state.activeTripId);
  return h("header", { class: "chat-head" },
    h("button", { class: "btn icon only-mobile", type: "button", "aria-label": "메뉴 열기", dataset: { action: "toggleSidebar" } }, "☰"),
    h("div", { class: "trip-picker" },
      h("label", { class: "sr-only", for: "trip-select" }, "현재 작업 중인 여행"),
      select({ id: "trip-select", dataset: { changeAction: "selectTrip" } },
        [["", trips.length ? "여행 선택 안 함" : "아직 여행이 없어요"], ...trips.map((t) => [t.id, `${t.destination} · ${tripWhen(t)}`])],
        state.activeTripId || ""),
      active ? h("span", { class: "muted small trip-sub" }, `${tripLength(active)}${active.status === "completed" ? " · 다녀옴" : ""}`) : null),
    h("button", { class: "btn small", type: "button", dataset: { action: "openPrefs" } }, "내 취향"));
}

function renderMessages(state) {
  const { conv, live } = state;
  const messages = conv.data?.messages || [];
  if (conv.status === "loading" && !messages.length) return h("p", { class: "muted center" }, "대화를 불러오는 중…");
  if (conv.status === "error") {
    return h("div", { class: "notice error", role: "alert" }, conv.error?.message || "대화를 불러오지 못했어요.",
      h("button", { class: "btn small", type: "button", dataset: { action: "reloadConv" } }, "다시 시도"));
  }
  if (!messages.length && !live) return renderEmpty();
  const lastUserSeq = Math.max(0, ...messages.filter((m) => m.role === "user").map((m) => m.seq));
  return h("div", { class: "thread" },
    messages.map((m) => (m.role === "user" ? userBlock(m.content)
      : assistantBlock({ text: m.content, cards: m.cards || [], state, answered: Boolean(live) || m.seq < lastUserSeq }))),
    live ? renderLive(live, state) : null);
}

function renderComposer(state) {
  const running = state.live?.status === "running";
  return h("form", { class: "composer", dataset: { action: "sendMessage" } },
    h("label", { class: "sr-only", for: "composer-input" }, "메시지"),
    h("textarea", {
      id: "composer-input", rows: 1, maxlength: 2000, value: state.draft,
      placeholder: running ? "답변을 만드는 중이에요…" : "예: 둘째 날 너무 빡빡해 / 이 카페는 꼭 가고 싶어",
      dataset: { bind: "draft", submitOnEnter: "true" },
    }),
    h("button", { class: "btn primary send", type: "submit", disabled: running || !state.draft.trim(), "aria-label": "보내기" }, "보내기"));
}

function render(state) {
  return h("section", { class: "chat" },
    renderHeader(state),
    h("div", { class: "messages", id: "messages" }, h("div", { class: "messages-inner" }, renderMessages(state))),
    h("div", { class: "composer-wrap" }, renderComposer(state),
      h("p", { class: "fineprint" }, "영업시간·가격은 확인되지 않은 정보예요. 기억은 카드에서 승인한 것만 저장돼요.")));
}

async function withBusy(key, fn) {
  if (getState().busy[key]) return;
  updateIn("busy", key, true);
  try {
    await fn();
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    updateIn("busy", key, false);
  }
}

function focusComposer() {
  queueMicrotask(() => {
    const el = document.getElementById("composer-input");
    if (el) {
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }
  });
}

async function refreshAfterChange() {
  const { conv } = getState();
  const [trips] = await Promise.all([api.listTrips(), conv.id ? reloadConversation(conv.id) : null]);
  update({ trips: { items: trips, status: "ready", error: null } });
}

const actions = {
  sendMessage() {
    send(getState().draft);
  },
  sendText({ data }) {
    if (getState().live?.status === "running") return;
    send(data.text);
  },
  prefill({ data }) {
    update({ draft: data.text });
    focusComposer();
  },
  retryTurn() {
    retry();
  },
  dismissLive() {
    update({ live: null });
  },
  reloadConv() {
    const id = getState().conv.id;
    if (id) reloadConversation(id);
  },
  selectTrip({ el }) {
    update({ activeTripId: el.value || null });
  },
  selectDay({ data }) {
    updateIn("dayTab", data.tab, Number(data.day));
  },
  pinItem({ data }) {
    return withBusy(`pin:${data.itemId}`, async () => {
      await api.setPin(data.tripId, data.itemId, data.pinned === "true");
      await refreshAfterChange();
      showToast(data.pinned === "true" ? "고정했어요. 코스를 고쳐도 빠지지 않아요." : "고정을 풀었어요.");
    });
  },
  restoreVersion({ data }) {
    return withBusy(`restore:${data.versionId}`, async () => {
      await api.restoreVersion(data.tripId, data.versionId);
      await refreshAfterChange();
      showToast("이 일정을 현재 코스로 되돌렸어요. 다른 버전도 그대로 남아 있어요.");
    });
  },
  approveProposal({ data }) {
    return withBusy(`proposal:${data.id}`, async () => {
      await api.approveProposal(data.id);
      await refreshAfterChange();
      showToast("기억했어요. 다음 여행부터 반영돼요.");
    });
  },
  approveEdited({ data }) {
    const value = (getState().proposalEdits[data.id] || "").trim();
    if (!value) {
      showToast("저장할 문장을 입력하세요.", "error");
      return null;
    }
    return withBusy(`proposal:${data.id}`, async () => {
      await api.approveProposal(data.id, value);
      updateIn("proposalEdits", data.id, undefined);
      await refreshAfterChange();
      showToast("고친 문장으로 기억했어요.");
    });
  },
  rejectProposal({ data }) {
    return withBusy(`proposal:${data.id}`, async () => {
      await api.rejectProposal(data.id);
      await refreshAfterChange();
      showToast("기억하지 않았어요.");
    });
  },
  editProposal({ data }) {
    updateIn("proposalEdits", data.id, data.value);
  },
  cancelEditProposal({ data }) {
    updateIn("proposalEdits", data.id, undefined);
  },
};

export default { render, actions };
