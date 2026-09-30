// 채팅 안의 카드: 여행 · 코스 · 기억 변경안 · 이번 여행 조건 · 장소 고정 · 질문.
// 카드는 서버 도구가 만든 데이터다. 모든 텍스트는 텍스트 노드로 넣는다.
import { CATEGORY_LABELS, KIND_LABELS, MODE_LABELS, TRANSPORT_LABELS, formatDateTime, formatKRW, formatMinutes, h } from "../dom.js";

const WEEKDAYS = "일월화수목금토";

function fmtDate(iso) {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${WEEKDAYS[d.getDay()]})`;
}

export function tripWhen(t) {
  if (t.start_date) {
    return t.end_date && t.end_date !== t.start_date ? `${fmtDate(t.start_date)} ~ ${fmtDate(t.end_date)}` : fmtDate(t.start_date);
  }
  return t.period_hint ? `${t.period_hint} · 날짜 미정` : "날짜 미정";
}

export function tripLength(t) {
  return t.days > 1 ? `${t.days - 1}박 ${t.days}일` : "당일";
}

function tripMeta(t) {
  return h("div", { class: "trip-meta" },
    h("span", { class: t.start_date ? "" : "undated" }, tripWhen(t)),
    h("span", {}, tripLength(t) + (t.days_is_default ? " (임시)" : "")),
    t.transport ? h("span", {}, TRANSPORT_LABELS[t.transport]) : h("span", { class: "unknown" }, "이동수단 미정"));
}

function cardHead(kicker, title, extra) {
  return h("header", { class: "card-head" },
    h("div", {}, h("p", { class: "kicker" }, kicker), title ? h("h3", {}, title) : null),
    extra || null);
}

// ---------------- 여행 ----------------

function tripCard(card) {
  const t = card.trip;
  return h("article", { class: "tcard trip" },
    cardHead(card.action === "created" ? "새 여행" : "여행 정보 변경", `${t.destination} 여행`),
    tripMeta(t),
    t.start_date ? null : h("p", { class: "hint" }, "날짜가 정해지지 않아 요일·영업일은 확정하지 않았어요. 날짜를 알려주시면 반영할게요."));
}

// ---------------- 코스 ----------------

const PLACE_STATUS = {
  verified: ["ok", "장소 확인됨"],
  unverified: ["warn", "미확인 장소"],
  mock: ["muted", "모의 데이터"],
};

function mapLink(item, destination) {
  const url = item.place?.place_url;
  if (url && /^https:\/\//.test(url)) return url;
  const q = item.place?.matched_name || item.search_keyword || item.name;
  const query = q.includes(destination) ? q : `${destination} ${q}`;
  return `https://map.kakao.com/link/search/${encodeURIComponent(query)}`;
}

function itemRow(item, { day, card, trip, pinnedIds, openKeys, version, canAct }) {
  const place = item.place || {};
  const [tone, label] = PLACE_STATUS[place.status] || [];
  const pinned = pinnedIds.has(item.item_id);
  const detailKey = `${card.key}:${version.id}:${item.item_id}`;
  const applied = (version.applied_memories || []).filter((m) => item.applied_preference_ids?.includes(m.preference_id));
  const leg = item.travel_from_prev;
  return h("li", { class: `stop kind-${item.kind}${pinned ? " pinned" : ""}` },
    leg ? h("div", { class: "leg" }, `${MODE_LABELS[leg.mode] || "이동"} ${formatMinutes(leg.minutes_estimate)} · 추정`) : null,
    h("div", { class: "stop-main" },
      h("span", { class: "time" }, item.start_time || ""),
      h("div", { class: "stop-body" },
        h("div", { class: "stop-title" },
          h("span", { class: "kind" }, KIND_LABELS[item.kind]),
          h("strong", {}, item.name),
          pinned ? h("span", { class: "badge accent" }, "고정") : null,
          label ? h("span", { class: `badge ${tone}` }, label) : null),
        h("p", { class: "stop-sub" },
          `${formatMinutes(item.stay_minutes)} 머무름`,
          item.cost_estimate_krw != null ? ` · 약 ${formatKRW(item.cost_estimate_krw)} (추정)` : ""),
        h("details", { dataset: { openKey: detailKey }, open: Boolean(openKeys[detailKey]) },
          h("summary", {}, "추천 이유 · 정보 출처"),
          h("div", { class: "stop-detail" },
            h("p", {}, item.reason),
            applied.length ? h("ul", { class: "applied" }, applied.map((m) => h("li", {}, m.reason))) : null,
            item.kind !== "rest" ? h("p", { class: "source" },
              place.status === "verified" ? `장소 검색으로 확인 (${place.provider === "kakao" ? "카카오" : place.provider})`
                : place.status === "mock" ? "모의 장소 데이터 (실제 장소 아님)" : "장소 검색으로 찾지 못함 — 이름이 다르거나 없는 곳일 수 있어요",
              place.checked_at ? ` · 확인 시점 ${formatDateTime(place.checked_at)}` : "") : null,
            item.kind !== "rest" ? h("p", { class: "notice-line" }, place.info_notice || "영업시간·휴무일·가격: 최신 정보 미확인") : null,
            item.cost_basis ? h("p", { class: "source" }, `비용 기준: ${item.cost_basis}`) : null,
            item.backup ? h("p", { class: "backup" }, h("strong", {}, "비 오거나 문 닫으면 · "),
              `${item.backup.name} — ${item.backup.reason} (미확인)`) : null,
            canAct && item.kind !== "rest" ? h("div", { class: "row wrap" },
              h("button", { class: "btn small", type: "button", dataset: { action: "pinItem", tripId: trip.id, itemId: item.item_id, pinned: pinned ? "false" : "true" } },
                pinned ? "고정 풀기" : "꼭 갈래요 (고정)"),
              pinned ? null : h("button", { class: "btn small", type: "button", dataset: { action: "sendText", text: `${trip.destination} ${day}일차 '${item.name}' 대신 다른 곳으로 바꿔줘` } }, "다른 장소로 교체"),
              h("a", { class: "btn small ghost", href: mapLink(item, trip.destination), target: "_blank", rel: "noopener noreferrer" }, "지도")) : null)))));
}

function courseCard(card, state) {
  const version = card.version;
  const course = version.course;
  const liveTrip = state.trips.items.find((t) => t.id === card.trip.id);
  const trip = { ...card.trip, ...(liveTrip || {}) };
  const deleted = state.trips.status === "ready" && !liveTrip;
  const isCurrent = card.is_current ?? trip.current_version_id === version.id;
  const pinnedIds = new Set((trip.pinned_places || []).map((p) => p.item_id));
  const tabKey = `${card.key}:${version.id}`;
  const days = course.days;
  const selected = state.dayTab[tabKey] || version.changed_days?.[0] || 1;
  const day = days.find((d) => d.day_index === selected) || days[0];
  const canAct = isCurrent && !deleted;
  const warnings = version.warnings || [];
  return h("article", { class: `tcard course${isCurrent ? "" : " past"}` },
    cardHead(`${trip.destination} · ${tripWhen(trip)} · ${tripLength(trip)}`, course.title,
      h("span", { class: `badge ${isCurrent ? "accent" : "muted"}` }, deleted ? "삭제된 여행" : isCurrent ? "현재 일정" : "이전 버전")),
    version.changes?.length ? h("div", { class: "changes" }, h("p", { class: "kicker" }, "바뀐 점"),
      h("ul", {}, version.changes.map((c) => h("li", {}, c)))) : null,
    h("p", { class: "summary" }, course.summary_explanation),
    course.assumptions?.length ? h("p", { class: "hint" }, course.assumptions.join(" · ")) : null,
    warnings.length ? h("ul", { class: "warnings" }, warnings.map((w) => h("li", {}, w))) : null,
    h("div", { class: "day-tabs", role: "tablist" }, days.map((d) => h("button", {
      class: `tab${d.day_index === day.day_index ? " active" : ""}`, type: "button", role: "tab",
      "aria-selected": d.day_index === day.day_index ? "true" : "false",
      dataset: { action: "selectDay", tab: tabKey, day: String(d.day_index) },
    }, `${d.day_index}일차`, version.changed_days?.includes(d.day_index) ? h("span", { class: "dot", "aria-label": "바뀐 날" }) : null))),
    h("div", { class: "day" },
      h("p", { class: "day-theme" }, day.date ? `${fmtDate(day.date)} · ` : "", day.theme),
      h("ol", { class: "timeline" }, day.items.map((item) => itemRow(item, {
        day: day.day_index, card, trip, pinnedIds, openKeys: state.open, version, canAct }))),
      h("details", { class: "day-map", dataset: { openKey: `${tabKey}:map:${day.day_index}` }, open: Boolean(state.open[`${tabKey}:map:${day.day_index}`]) },
        h("summary", {}, "지도 보기"),
        h("ol", {}, day.items.filter((i) => i.kind !== "rest").map((i) => h("li", {},
          h("a", { href: mapLink(i, trip.destination), target: "_blank", rel: "noopener noreferrer" }, i.name))))),
      canAct ? h("div", { class: "row wrap day-actions" },
        h("button", { class: "btn small", type: "button", dataset: { action: "prefill", text: `${trip.destination} ${day.day_index}일차를 이렇게 바꾸고 싶어요: ` } }, "이 날 수정"),
        h("button", { class: "btn small", type: "button", dataset: { action: "openTrip", tripId: trip.id } }, "모든 버전 보기")) : null),
    h("footer", { class: "card-foot" },
      h("span", { class: "muted small" }, `${version.label} · ${formatDateTime(version.created_at)}`),
      deleted ? null : isCurrent && version.parent_version_id
        ? h("button", { class: "btn small", type: "button", dataset: { action: "restoreVersion", tripId: trip.id, versionId: version.parent_version_id } }, "이전 일정으로 되돌리기")
        : !isCurrent ? h("button", { class: "btn small", type: "button", dataset: { action: "restoreVersion", tripId: trip.id, versionId: version.id } }, "이 일정으로 되돌리기") : null));
}

// ---------------- 기억 변경안 ----------------

function proposalCard(card, state) {
  const p = card.proposal;
  const editing = state.proposalEdits[p.id];
  const busy = state.busy[`proposal:${p.id}`];
  const decided = p.status !== "pending";
  let body;
  if (p.type === "update") body = h("p", { class: "statement" }, h("s", {}, p.before), " → ", p.edited_value || p.after);
  else if (p.type === "deactivate") body = h("p", { class: "statement" }, `‘${p.before}’ 더 이상 적용하지 않기`);
  else body = h("p", { class: "statement" }, p.edited_value || p.after);
  const status = { approved: "기억했어요", edited_approved: "고쳐서 기억했어요", rejected: "기억하지 않았어요" }[p.status];
  return h("article", { class: `tcard proposal${p.certainty === "guess" ? " guess" : ""}${decided ? " decided" : ""}` },
    cardHead("기억 변경안 · 다른 여행에도 반영", null,
      p.certainty === "guess" ? h("span", { class: "badge warn" }, "추정 · 확인 필요") : h("span", { class: "badge muted" }, "승인해야 저장돼요")),
    editing !== undefined && !decided
      ? h("form", { class: "stack", dataset: { action: "approveEdited", id: p.id } },
        h("input", { type: "text", maxlength: 200, value: editing, "aria-label": "저장할 문장", dataset: { bind: `proposalEdits.${p.id}` } }),
        h("div", { class: "row wrap" },
          h("button", { class: "btn primary small", type: "submit", disabled: busy }, "이 문장으로 기억하기"),
          h("button", { class: "btn small", type: "button", dataset: { action: "cancelEditProposal", id: p.id } }, "취소")))
      : body,
    h("dl", { class: "facts" },
      h("div", {}, h("dt", {}, "적용 범위"), h("dd", {}, p.applies_to || "모든 여행")),
      h("div", {}, h("dt", {}, "분류"), h("dd", {}, CATEGORY_LABELS[p.category] || p.category)),
      h("div", {}, h("dt", {}, "근거"), h("dd", {}, h("q", {}, p.evidence_text)))),
    p.certainty === "guess" && p.question && !decided ? h("p", { class: "question" }, p.question) : null,
    decided
      ? h("div", { class: "row wrap decided-line" }, h("span", {}, status),
        p.status !== "rejected" ? h("button", { class: "btn link small", type: "button", dataset: { action: "openPrefs" } }, "내 취향에서 관리") : null)
      : editing === undefined ? h("div", { class: "row wrap" },
        h("button", { class: "btn primary small", type: "button", disabled: busy, dataset: { action: "approveProposal", id: p.id } }, "기억하기"),
        h("button", { class: "btn small", type: "button", disabled: busy, dataset: { action: "rejectProposal", id: p.id } },
          p.certainty === "guess" ? "이번만 그랬어요" : "기억하지 않기"),
        p.type !== "deactivate" ? h("button", { class: "btn link small", type: "button", dataset: { action: "editProposal", id: p.id, value: p.after || "" } }, "문장 고치기") : null) : null);
}

// ---------------- 기타 ----------------

function conditionCard(card) {
  return h("article", { class: "tcard condition" },
    cardHead(`이번 여행 조건 · ${card.trip.destination}`, null),
    h("p", { class: "statement" }, card.preference.value),
    h("p", { class: "hint" }, "이 여행에만 적용돼요. 다른 여행의 장기 기억은 바뀌지 않아요."));
}

function pinCard(card) {
  return h("article", { class: "tcard pin" },
    h("p", {}, h("strong", {}, card.pinned ? "고정했어요 · " : "고정을 풀었어요 · "), card.name),
    card.pinned ? h("p", { class: "hint" }, `${card.trip.destination} 코스를 고쳐도 이 장소는 빠지지 않아요.`) : null);
}

function questionCard(card, { answered }) {
  return h("article", { class: "tcard question-card" },
    h("p", { class: "statement" }, card.question),
    card.options.length ? h("div", { class: "row wrap" }, card.options.map((o) => h("button", {
      class: "btn chip", type: "button", disabled: answered, dataset: { action: "sendText", text: o } }, o))) : null);
}

export function renderCard(card, state, ctx = {}) {
  switch (card.type) {
    case "trip": return tripCard(card);
    case "course": return courseCard(card, state);
    case "proposal": return proposalCard(card, state);
    case "condition": return conditionCard(card);
    case "pin": return pinCard(card);
    case "question": return questionCard(card, ctx);
    default: return null;
  }
}
