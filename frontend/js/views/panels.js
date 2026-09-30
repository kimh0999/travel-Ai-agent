// 오른쪽 패널: 내 취향(근거 보기·일시중지·삭제·직접 추가) / 여행(버전 되돌리기·이어서 대화·삭제).
import { api } from "../api.js";
import { loadLists, openConversation } from "../chat.js";
import { CATEGORY_LABELS, SOURCE_LABELS, TRANSPORT_LABELS, errorBlock, formatDateTime, h, loadingBlock, select } from "../dom.js";
import { getState, showToast, update } from "../store.js";
import { tripLength, tripWhen } from "./cards.js";

const SCOPE_LABELS = { base: "직접 입력", trip: "이번 여행 한정", learned: "여행 피드백에서 승인" };

// ---------------- 내 취향 ----------------

export async function loadPrefs() {
  update({ preferences: { ...getState().preferences, status: "loading", error: null } });
  try {
    update({ preferences: { items: await api.listPreferences(), status: "ready", error: null } });
  } catch (error) {
    update({ preferences: { ...getState().preferences, status: "error", error } });
  }
}

function replacePref(updated) {
  const p = getState().preferences;
  update({ preferences: { ...p, items: p.items.map((i) => (i.id === updated.id ? updated : i)) } });
}

async function patchPref(id, body, message) {
  try {
    replacePref(await api.updatePreference(id, body));
    if (message) showToast(message);
  } catch (error) {
    showToast(error.message, "error");
  }
}

function sourceLine(src, tripsById) {
  const trip = src.trip_id ? tripsById[src.trip_id] : null;
  const tripName = trip?.destination || src.trip_destination;
  return h("li", {},
    h("span", {}, SOURCE_LABELS[src.type] || src.type, tripName ? ` · ${tripName} 여행` : ""),
    src.trip_deleted ? h("span", { class: "badge muted" }, "삭제된 여행") : null,
    src.evidence_text ? h("q", { class: "evidence" }, src.evidence_text) : null);
}

function prefItem(item, state, tripsById) {
  const editing = state.prefEditing?.id === item.id ? state.prefEditing : null;
  const confirming = state.prefConfirmDeleteId === item.id;
  const trip = item.scope === "trip" ? tripsById[item.trip_id] : null;
  const openKey = `pref:${item.id}`;
  return h("li", { class: `pref${item.status === "paused" ? " paused" : ""}` },
    h("div", { class: "pref-tags" },
      h("span", { class: `badge ${item.strength === "hard" ? "accent" : "muted"}` }, item.strength === "hard" ? "필수" : "선호"),
      h("span", { class: "badge muted" }, CATEGORY_LABELS[item.category] || item.category),
      h("span", { class: "badge muted" }, trip ? `${trip.destination} 여행 한정` : SCOPE_LABELS[item.scope]),
      item.subject === "companion" ? h("span", { class: "badge muted" }, "동행인") : null,
      item.status === "paused" ? h("span", { class: "badge warn" }, "일시중지") : null,
      item.sensitive ? h("span", { class: `badge ${item.share_with_ai ? "muted" : "warn"}` }, item.share_with_ai ? "민감 · AI 전송 허용" : "민감 · AI에 안 보냄") : null),
    editing
      ? h("form", { class: "stack", dataset: { action: "savePrefEdit" } },
        h("input", { type: "text", maxlength: 200, value: editing.value, "aria-label": "내용", dataset: { bind: "prefEditing.value" } }),
        h("div", { class: "row wrap" },
          h("button", { class: "btn primary small", type: "submit" }, "저장"),
          h("button", { class: "btn small", type: "button", dataset: { action: "cancelPrefEdit" } }, "취소")))
      : h("p", { class: "pref-value" }, item.value),
    h("details", { dataset: { openKey }, open: Boolean(state.open[openKey]) },
      h("summary", {}, "근거 보기"),
      h("ul", { class: "sources" }, item.sources.map((s) => sourceLine(s, tripsById))),
      h("p", { class: "muted small" }, `저장 ${formatDateTime(item.created_at)} · 수정 ${formatDateTime(item.updated_at)}`)),
    confirming
      ? h("div", { class: "row wrap confirm-line" }, h("span", {}, "삭제할까요? 이후 추천에서 빠져요."),
        h("button", { class: "btn danger small", type: "button", dataset: { action: "confirmPrefDelete", id: item.id } }, "삭제"),
        h("button", { class: "btn small", type: "button", dataset: { action: "cancelPrefDelete" } }, "취소"))
      : h("div", { class: "row wrap" },
        h("button", { class: "btn small", type: "button", dataset: { action: "startPrefEdit", id: item.id } }, "고치기"),
        h("button", { class: "btn small", type: "button", dataset: { action: "togglePause", id: item.id } }, item.status === "paused" ? "다시 적용" : "일시중지"),
        item.sensitive ? h("button", { class: "btn small", type: "button", dataset: { action: "toggleShare", id: item.id } }, item.share_with_ai ? "AI 전송 끄기" : "AI 전송 허용") : null,
        h("button", { class: "btn small danger-outline", type: "button", dataset: { action: "askPrefDelete", id: item.id } }, "삭제")));
}

function addForm(d) {
  return h("form", { class: "stack add-form", dataset: { action: "addPref" } },
    h("h3", {}, "직접 추가"),
    h("div", { class: "row wrap" },
      h("label", {}, "분류", select({ dataset: { bind: "prefDraft.category" } }, Object.entries(CATEGORY_LABELS), d.category)),
      h("label", {}, "구분", select({ dataset: { bind: "prefDraft.strength" } }, [["soft", "선호"], ["hard", "필수 조건"]], d.strength))),
    h("label", {}, "내용", h("input", { type: "text", maxlength: 200, placeholder: "예: 걷는 건 하루 30분 이내", value: d.value, dataset: { bind: "prefDraft.value" } })),
    h("label", { class: "check" }, h("input", { type: "checkbox", checked: d.sensitive, dataset: { bind: "prefDraft.sensitive", rerender: "true" } }),
      "민감한 항목이에요 (건강·음식 제약 등)"),
    d.sensitive ? h("label", { class: "check indent" }, h("input", { type: "checkbox", checked: d.share_with_ai, dataset: { bind: "prefDraft.share_with_ai" } }),
      "코스를 짤 때 외부 AI(Claude)에 이 항목을 보내도 돼요") : null,
    h("button", { class: "btn primary", type: "submit" }, "저장"));
}

function prefsPanel(state) {
  const p = state.preferences;
  const tripsById = Object.fromEntries(state.trips.items.map((t) => [t.id, t]));
  let list;
  if (p.status === "loading" && !p.items.length) list = loadingBlock();
  else if (p.status === "error") list = errorBlock(p.error, "reloadPrefs");
  else if (!p.items.length) list = h("p", { class: "muted" }, "아직 저장된 취향이 없어요. 대화에서 기억 변경안을 승인하거나 직접 추가하세요.");
  else list = h("ul", { class: "pref-list" }, p.items.map((i) => prefItem(i, state, tripsById)));
  return [
    h("header", { class: "panel-head" }, h("h2", {}, "내 취향"),
      h("button", { class: "btn icon", type: "button", "aria-label": "닫기", dataset: { action: "closePanel" } }, "✕")),
    h("p", { class: "muted small" }, "코스를 짤 때 참고하는 기억이에요. 일시중지하거나 삭제한 항목은 쓰지 않고, 없는 항목은 추측하지 않아요."),
    list,
    addForm(state.prefDraft),
  ];
}

// ---------------- 여행 ----------------

export async function loadTripPanel(tripId) {
  update({ tripPanel: { versions: [], preview: null, status: "loading", error: null, selected: [], confirming: false } });
  try {
    const versions = await api.listVersions(tripId);
    update({ tripPanel: { ...getState().tripPanel, versions, status: "ready" } });
  } catch (error) {
    update({ tripPanel: { ...getState().tripPanel, status: "error", error } });
  }
}

function tripPanel(state, tripId) {
  const trip = state.trips.items.find((t) => t.id === tripId);
  const tp = state.tripPanel;
  const head = h("header", { class: "panel-head" }, h("h2", {}, trip ? `${trip.destination} 여행` : "여행"),
    h("button", { class: "btn icon", type: "button", "aria-label": "닫기", dataset: { action: "closePanel" } }, "✕"));
  if (!trip) return [head, h("p", { class: "muted" }, "여행을 찾을 수 없어요.")];
  return [
    head,
    h("div", { class: "trip-meta" },
      h("span", {}, tripWhen(trip)), h("span", {}, tripLength(trip)),
      h("span", {}, trip.transport ? TRANSPORT_LABELS[trip.transport] : "이동수단 미정")),
    trip.pinned_places?.length ? h("p", { class: "small" }, "고정한 장소: ", trip.pinned_places.map((p) => p.name).join(", ")) : null,
    h("div", { class: "row wrap" },
      h("button", { class: "btn primary small", type: "button", dataset: { action: "chatAboutTrip", tripId } }, "이 여행으로 새 대화")),
    h("section", { class: "stack" },
      h("h3", {}, "코스 버전"),
      tp.status === "loading" ? loadingBlock() : tp.status === "error" ? errorBlock(tp.error, "reloadTripPanel", { tripId })
        : tp.versions.length ? h("ol", { class: "versions" }, tp.versions.slice().reverse().map((v) => h("li", { class: v.is_current ? "current" : "" },
          h("div", {}, h("strong", {}, v.label), h("span", { class: "muted small" }, ` · ${formatDateTime(v.created_at)}`),
            h("p", { class: "small" }, v.title)),
          v.is_current ? h("span", { class: "badge accent" }, "현재")
            : h("button", { class: "btn small", type: "button", dataset: { action: "restoreFromPanel", tripId, versionId: v.id } }, "이 버전으로"))))
          : h("p", { class: "muted small" }, "아직 코스가 없어요. 대화에서 코스를 만들어 보세요.")),
    h("section", { class: "stack danger-zone" },
      h("h3", {}, "여행 삭제"),
      tp.preview ? deletePreview(tp, tripId)
        : h("button", { class: "btn small danger-outline", type: "button", dataset: { action: "previewDelete", tripId } }, "삭제하기…")),
  ];
}

function deletePreview(tp, tripId) {
  const p = tp.preview;
  return h("div", { class: "stack" },
    h("p", { class: "small" }, `코스 버전 ${p.counts.course_versions}개, 이번 여행 조건 ${p.counts.trip_preferences}개, 승인하지 않은 변경안 ${p.counts.undecided_proposals}개가 함께 삭제돼요. 대화는 남기고 이 여행의 카드만 지워요.`),
    p.learned_preferences.length ? h("fieldset", {}, h("legend", {}, "이 여행에서 배운 기억도 지울까요? (선택하지 않으면 유지)"),
      p.learned_preferences.map((l) => h("label", { class: "check" },
        h("input", { type: "checkbox", checked: tp.selected.includes(l.id), dataset: { changeAction: "toggleDeletePref", id: l.id } }),
        l.value, l.only_from_this_trip ? "" : " (다른 여행에서도 배움)"))) : null,
    h("div", { class: "row wrap" },
      h("button", { class: "btn danger small", type: "button", dataset: { action: "confirmDeleteTrip", tripId } }, "여행 삭제"),
      h("button", { class: "btn small", type: "button", dataset: { action: "cancelDeleteTrip" } }, "취소")));
}

export function renderPanel(state) {
  const panel = state.panel;
  if (!panel) return null;
  const content = panel.type === "prefs" ? prefsPanel(state) : tripPanel(state, panel.tripId);
  return h("div", { class: "panel-layer" },
    h("button", { class: "scrim", type: "button", "aria-label": "패널 닫기", dataset: { action: "closePanel" } }),
    h("aside", { class: "panel", role: "dialog", "aria-modal": "true", "aria-label": panel.type === "prefs" ? "내 취향" : "여행" }, content));
}

async function refreshTripsAndPanel(tripId) {
  await loadLists();
  if (tripId) await loadTripPanel(tripId);
}

export const panelActions = {
  openPrefs() {
    update({ panel: { type: "prefs" }, sidebarOpen: false });
    loadPrefs();
  },
  openTrip({ data }) {
    update({ panel: { type: "trip", tripId: data.tripId }, activeTripId: data.tripId, sidebarOpen: false });
    loadTripPanel(data.tripId);
  },
  closePanel() {
    update({ panel: null });
  },
  reloadPrefs: loadPrefs,
  reloadTripPanel({ data }) {
    loadTripPanel(data.tripId);
  },
  chatAboutTrip({ data }) {
    update({ panel: null, activeTripId: data.tripId });
    location.hash = "#/";
    openConversation(null);
    update({ activeTripId: data.tripId });
  },
  async restoreFromPanel({ data }) {
    try {
      await api.restoreVersion(data.tripId, data.versionId);
      await refreshTripsAndPanel(data.tripId);
      const convId = getState().conv.id;
      if (convId) openConversation(convId);
      showToast("이 버전을 현재 코스로 되돌렸어요.");
    } catch (error) {
      showToast(error.message, "error");
    }
  },
  async previewDelete({ data }) {
    try {
      const preview = await api.deleteTripPreview(data.tripId);
      update({ tripPanel: { ...getState().tripPanel, preview, selected: [] } });
    } catch (error) {
      showToast(error.message, "error");
    }
  },
  toggleDeletePref({ el, data }) {
    const tp = getState().tripPanel;
    const selected = el.checked ? [...tp.selected, data.id] : tp.selected.filter((x) => x !== data.id);
    update({ tripPanel: { ...tp, selected } });
  },
  cancelDeleteTrip() {
    update({ tripPanel: { ...getState().tripPanel, preview: null, selected: [] } });
  },
  async confirmDeleteTrip({ data }) {
    try {
      await api.deleteTrip(data.tripId, { delete_preference_ids: getState().tripPanel.selected });
      const s = getState();
      update({ panel: null, activeTripId: s.activeTripId === data.tripId ? null : s.activeTripId });
      await loadLists();
      if (s.conv.id) openConversation(s.conv.id);
      showToast("여행을 삭제했어요.");
    } catch (error) {
      showToast(error.message, "error");
    }
  },
  async addPref() {
    const d = getState().prefDraft;
    if (!d.value.trim()) {
      showToast("내용을 입력하세요.", "error");
      return;
    }
    try {
      const created = await api.createPreference({
        category: d.category, value: d.value.trim(), strength: d.strength, subject: d.subject,
        sensitive: d.sensitive, share_with_ai: d.sensitive ? d.share_with_ai : true,
      });
      const p = getState().preferences;
      update({ preferences: { ...p, items: [created, ...p.items] }, prefDraft: { ...d, value: "", sensitive: false, share_with_ai: false } });
      showToast("저장했어요.");
    } catch (error) {
      showToast(error.message, "error");
    }
  },
  startPrefEdit({ data }) {
    const item = getState().preferences.items.find((i) => i.id === data.id);
    if (item) update({ prefEditing: { id: item.id, value: item.value } });
  },
  cancelPrefEdit() {
    update({ prefEditing: null });
  },
  async savePrefEdit() {
    const e = getState().prefEditing;
    if (!e?.value.trim()) {
      showToast("내용을 입력하세요.", "error");
      return;
    }
    await patchPref(e.id, { value: e.value.trim() }, "고쳤어요.");
    update({ prefEditing: null });
  },
  togglePause({ data }) {
    const item = getState().preferences.items.find((i) => i.id === data.id);
    const next = item.status === "paused" ? "active" : "paused";
    return patchPref(data.id, { status: next }, next === "paused" ? "일시중지했어요. 코스를 짤 때 쓰지 않아요." : "다시 적용해요.");
  },
  toggleShare({ data }) {
    const item = getState().preferences.items.find((i) => i.id === data.id);
    return patchPref(data.id, { share_with_ai: !item.share_with_ai },
      item.share_with_ai ? "이 항목은 외부 AI에 보내지 않아요." : "이 항목을 외부 AI에 보내는 데 동의했어요.");
  },
  askPrefDelete({ data }) {
    update({ prefConfirmDeleteId: data.id });
  },
  cancelPrefDelete() {
    update({ prefConfirmDeleteId: null });
  },
  async confirmPrefDelete({ data }) {
    try {
      await api.deletePreference(data.id);
      const p = getState().preferences;
      update({ preferences: { ...p, items: p.items.filter((i) => i.id !== data.id) }, prefConfirmDeleteId: null });
      showToast("삭제했어요. 이후 추천에서 빠져요.");
    } catch (error) {
      showToast(error.message, "error");
    }
  },
};
