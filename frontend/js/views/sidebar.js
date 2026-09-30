// 왼쪽 사이드바: 새 대화, 내 여행, 대화 목록. 대화와 여행은 따로 관리한다(한 대화에서 여러 여행을 다룰 수 있음).
import { api } from "../api.js";
import { openConversation } from "../chat.js";
import { formatDateTime, h } from "../dom.js";
import { getState, showToast, update, updateIn } from "../store.js";
import { tripLength, tripWhen } from "./cards.js";

function tripItem(t, state) {
  const active = state.activeTripId === t.id;
  return h("li", {},
    h("button", { class: `side-item${active ? " active" : ""}`, type: "button", dataset: { action: "openTrip", tripId: t.id } },
      h("span", { class: "side-title" }, t.destination,
        t.status === "completed" ? h("span", { class: "badge muted" }, "다녀옴") : null),
      h("span", { class: "side-sub" }, `${tripWhen(t)} · ${tripLength(t)}${t.current_version_id ? "" : " · 코스 없음"}`)));
}

function convItem(c, state) {
  const current = state.conv.id === c.id;
  const confirming = state.busy[`delconv:${c.id}`] === "confirm";
  return h("li", { class: "conv-row" },
    h("a", { class: `side-item${current ? " active" : ""}`, href: `#/c/${encodeURIComponent(c.id)}` },
      h("span", { class: "side-title" }, c.title),
      h("span", { class: "side-sub" }, [c.trip_destination, formatDateTime(c.last_message_at || c.created_at)].filter(Boolean).join(" · "))),
    h("button", { class: `btn link small del${confirming ? " confirm" : ""}`, type: "button", dataset: { action: "deleteConversation", id: c.id },
      "aria-label": confirming ? "정말 삭제" : `${c.title} 대화 삭제` }, confirming ? "정말 삭제" : "삭제"));
}

function render(state) {
  const { trips, conversations } = state;
  return h("aside", { class: `sidebar${state.sidebarOpen ? " open" : ""}`, "aria-label": "여행과 대화" },
    h("div", { class: "side-top" },
      h("p", { class: "brand" }, "여행 비서"),
      h("button", { class: "btn icon only-mobile", type: "button", "aria-label": "메뉴 닫기", dataset: { action: "toggleSidebar" } }, "✕")),
    h("a", { class: "btn primary block", href: "#/" }, "새 대화"),
    h("nav", { class: "side-scroll" },
      h("section", {},
        h("h2", { class: "side-head" }, "내 여행"),
        trips.items.length ? h("ul", { class: "side-list" }, trips.items.map((t) => tripItem(t, state)))
          : h("p", { class: "muted small side-empty" }, "대화로 여행을 만들면 여기에 모여요.")),
      h("section", {},
        h("h2", { class: "side-head" }, "대화"),
        conversations.items.length ? h("ul", { class: "side-list" }, conversations.items.map((c) => convItem(c, state)))
          : h("p", { class: "muted small side-empty" }, "아직 대화가 없어요."))),
    h("div", { class: "side-foot" },
      h("span", { class: "muted small ellipsis" }, state.auth.user?.email || ""),
      h("button", { class: "btn link small", type: "button", dataset: { action: "signOut" } }, "로그아웃")));
}

const actions = {
  toggleSidebar() {
    update({ sidebarOpen: !getState().sidebarOpen });
  },
  async deleteConversation({ data }) {
    const key = `delconv:${data.id}`;
    if (getState().busy[key] !== "confirm") {
      updateIn("busy", key, "confirm");
      setTimeout(() => updateIn("busy", key, false), 4000);
      return;
    }
    updateIn("busy", key, false);
    try {
      await api.deleteConversation(data.id);
      const s = getState();
      update({ conversations: { ...s.conversations, items: s.conversations.items.filter((c) => c.id !== data.id) } });
      if (s.conv.id === data.id) {
        location.hash = "#/";
        openConversation(null);
      }
      showToast("대화를 삭제했어요. 여행과 코스는 그대로 있어요.");
    } catch (error) {
      showToast(error.message, "error");
    }
  },
};

export default { render, actions };
