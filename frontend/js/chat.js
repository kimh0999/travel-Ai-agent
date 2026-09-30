// 대화 턴 실행: 보내기 → 실시간 이벤트 받기 → 끊기면 이어 받기 → 실패하면 이어서 재시도.
// 같은 요청은 같은 client_turn_id로만 보내므로, 네트워크 오류로 다시 보내도 서버에서 한 번만 실행된다.
import { api } from "./api.js";
import { getState, showToast, update, updateLive } from "./store.js";

const MAX_RECONNECTS = 6;
let following = null; // 지금 따라가는 turnId (같은 턴을 두 번 따라가지 않도록)

function newClientTurnId() {
  return (crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`).replace(/[^A-Za-z0-9]/g, "").slice(0, 40);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function loadLists() {
  try {
    const [trips, conversations] = await Promise.all([api.listTrips(), api.listConversations()]);
    update({ trips: { items: trips, status: "ready", error: null }, conversations: { items: conversations, status: "ready", error: null } });
  } catch (error) {
    update({ trips: { ...getState().trips, status: "error", error } });
  }
}

export async function openConversation(id) {
  if (!id) {
    update({ conv: { id: null, data: null, status: "idle", error: null }, live: null });
    return;
  }
  const s = getState();
  if (s.conv.id !== id) update({ conv: { id, data: null, status: "loading", error: null }, live: null });
  try {
    const data = await api.getConversation(id);
    if (getState().conv.id !== id) return;
    update({ conv: { id, data, status: "ready", error: null }, activeTripId: data.trip_id || getState().activeTripId });
    const open = data.open_turn;
    if (open && !getState().live) {
      update({ live: fromTurn(open) });
      if (open.status === "running") follow(open.id, open.attempt);
    }
  } catch (error) {
    if (getState().conv.id === id) update({ conv: { id, data: null, status: "error", error } });
  }
}

function fromTurn(turn) {
  return {
    turnId: turn.id, clientTurnId: null, attempt: turn.attempt, lastSeq: 0, message: turn.message,
    text: turn.reply || "", tools: [], cards: turn.cards || [], status: turn.status, error: turn.error, reconnecting: false,
  };
}

export async function send(text, { clientTurnId } = {}) {
  const message = (text || "").trim();
  const s = getState();
  if (!message || s.live?.status === "running") return;
  const id = clientTurnId || newClientTurnId();
  update({
    draft: "",
    live: { turnId: null, clientTurnId: id, attempt: 1, lastSeq: 0, message, text: "", tools: [], cards: [],
      status: "running", error: null, reconnecting: false },
  });
  let turn = null;
  for (let tries = 0; tries < 3 && !turn; tries += 1) {
    try {
      turn = await api.startTurn({ client_turn_id: id, conversation_id: s.conv.id, trip_id: s.activeTripId, message });
    } catch (error) {
      // 요청이 서버에 닿았는지 모를 때(네트워크·시간 초과)는 같은 ID로 다시 보낸다. 서버가 중복 실행을 막는다.
      if (!["NETWORK", "TIMEOUT"].includes(error.code) || tries === 2) {
        updateLive({ status: "failed", error: { code: error.code, message: error.message } });
        return;
      }
      await sleep(1000 * (tries + 1));
    }
  }
  if (!getState().conv.id) {
    update({ conv: { id: turn.conversation_id, data: null, status: "ready", error: null } });
    history.replaceState(null, "", `#/c/${encodeURIComponent(turn.conversation_id)}`);
    loadLists();
  }
  updateLive({ turnId: turn.id, attempt: turn.attempt });
  if (turn.status === "running") follow(turn.id, turn.attempt);
  else applyFinal(turn);
}

export async function retry() {
  const live = getState().live;
  if (!live || live.status !== "failed") return;
  if (!live.turnId) {
    send(live.message, { clientTurnId: live.clientTurnId }); // 서버에 닿지 못한 요청: 같은 ID로 다시 보낸다
    return;
  }
  updateLive({ status: "running", error: null, text: live.text, tools: [] });
  try {
    const turn = await api.retryTurn(live.turnId);
    updateLive({ attempt: turn.attempt, lastSeq: 0 });
    if (turn.status === "running") follow(turn.id, turn.attempt);
    else applyFinal(turn);
  } catch (error) {
    updateLive({ status: "failed", error: { code: error.code, message: error.message } });
  }
}

async function follow(turnId, attempt) {
  if (following === `${turnId}:${attempt}`) return;
  following = `${turnId}:${attempt}`;
  let failures = 0;
  try {
    while (failures <= MAX_RECONNECTS) {
      const live = getState().live;
      if (!live || live.turnId !== turnId || live.status !== "running") return;
      try {
        await api.streamEvents(turnId, { after: live.lastSeq, attempt, onEvent: (e) => onEvent(turnId, e) });
        const after = getState().live;
        if (!after || after.turnId !== turnId || after.status !== "running") return;
        failures = 0; // 스트림은 끝났는데 결과가 없으면 저장된 상태로 확인한다
        await syncFromServer(turnId);
        return;
      } catch (error) {
        if (error.status === 404 || error.status === 401) {
          updateLive({ status: "failed", error: { code: error.code, message: error.message } });
          return;
        }
        failures += 1;
        updateLive({ reconnecting: true });
        await sleep(Math.min(8000, 800 * 2 ** failures));
      }
    }
    await syncFromServer(turnId);
  } finally {
    if (following === `${turnId}:${attempt}`) following = null;
  }
}

async function syncFromServer(turnId) {
  try {
    const turn = await api.getTurn(turnId);
    if (turn.status === "running") {
      await sleep(2000);
      const live = getState().live;
      if (live?.turnId === turnId) {
        following = null;
        follow(turnId, turn.attempt);
      }
      return;
    }
    applyFinal(turn);
  } catch (error) {
    updateLive({ status: "failed", error: { code: error.code, message: "연결이 끊겼어요. 다시 시도하면 진행한 곳부터 이어서 해요." } });
  }
}

function onEvent(turnId, e) {
  const live = getState().live;
  if (!live || live.turnId !== turnId) return;
  const seq = e.seq || live.lastSeq;
  const base = { lastSeq: Math.max(live.lastSeq, seq), reconnecting: false };
  switch (e.type) {
    case "start":
      updateLive({ ...base, text: e.text || "", cards: e.cards || [], tools: [] });
      break;
    case "text":
      updateLive({ ...base, text: live.text + e.delta });
      break;
    case "text_reset":
      updateLive({ ...base, text: "" });
      break;
    case "tool_start":
      updateLive({ ...base, tools: [...live.tools, { key: e.key, name: e.name, label: e.label, status: "running" }] });
      break;
    case "tool_end":
      updateLive({ ...base, tools: live.tools.map((t) => (t.key === e.key && t.status === "running"
        ? { ...t, status: e.ok ? "ok" : "failed", message: e.message } : t)) });
      break;
    case "card":
      if (!live.cards.some((c) => c.key === e.card.key)) updateLive({ ...base, cards: [...live.cards, e.card] });
      break;
    case "active_trip":
      update({ activeTripId: e.trip.id });
      updateLive(base);
      loadLists();
      break;
    case "done":
      updateLive({ ...base, status: "done", text: e.reply, cards: e.cards || live.cards });
      finalize();
      break;
    case "error":
      updateLive({ ...base, status: "failed", error: e.error });
      break;
    case "snapshot":
      applyFinal(e.turn);
      break;
    default:
      updateLive(base);
  }
}

function applyFinal(turn) {
  if (turn.status === "done") {
    updateLive({ status: "done", text: turn.reply, cards: turn.cards });
    finalize();
  } else if (turn.status === "failed") {
    updateLive({ status: "failed", error: turn.error, cards: turn.cards, text: turn.reply || getState().live?.text || "" });
  }
}

async function finalize() {
  const convId = getState().conv.id;
  await Promise.all([convId ? reloadConversation(convId) : null, loadLists()]);
  const live = getState().live;
  if (live?.status === "done") update({ live: null });
}

export async function reloadConversation(id) {
  try {
    const data = await api.getConversation(id);
    if (getState().conv.id === id) update({ conv: { id, data, status: "ready", error: null } });
  } catch (error) {
    showToast(error.message, "error");
  }
}
