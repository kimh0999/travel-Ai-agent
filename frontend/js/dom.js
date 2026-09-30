// DOM 생성 헬퍼. 모든 텍스트는 텍스트 노드로 넣는다 (innerHTML 사용 금지).

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key === "value") el.value = value;
    else if (key === "checked") el.checked = Boolean(value);
    else if (key === "selected") el.selected = Boolean(value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  append(el, children);
  return el;
}

function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}


export function select(attrs, options, current) {
  return h("select", attrs, options.map(([value, label]) => h("option", { value, selected: value === current }, label)));
}

export function formatDateTime(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

export const CATEGORY_LABELS = {
  activity: "선호 활동",
  pace: "일정 밀도·휴식",
  transport: "교통수단",
  budget: "예산",
  food: "음식",
  mobility: "걷기·이동 제약",
  lodging: "숙소",
  other: "기타",
};

export const SOURCE_LABELS = {
  manual: "직접 입력",
  onboarding: "초기 설정",
  feedback_proposal: "여행 피드백 승인",
  chat: "대화에서 말한 이번 여행 조건",
};

export const TRANSPORT_LABELS = { car: "자가용·렌터카", public: "대중교통", mixed: "대중교통·택시" };

// AI 답변의 간단한 마크다운(문단, 목록, **굵게**, 제목)을 텍스트 노드로만 만든다. innerHTML을 쓰지 않는다.
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean)
    .map((part) => (part.startsWith("**") && part.endsWith("**") && part.length > 4 ? h("strong", {}, part.slice(2, -2)) : part));
}

export function richText(text) {
  const blocks = String(text || "").replace(/\r/g, "").split(/\n{2,}/);
  return blocks.map((block) => {
    const lines = block.split("\n").filter((l) => l.trim());
    if (!lines.length) return null;
    if (lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l))) {
      const ordered = /^\s*\d/.test(lines[0]);
      return h(ordered ? "ol" : "ul", {}, lines.map((l) => h("li", {}, inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, "")))));
    }
    if (lines.length === 1 && /^#{1,4}\s/.test(lines[0])) return h("p", { class: "rt-heading" }, inline(lines[0].replace(/^#+\s/, "")));
    return h("p", {}, lines.flatMap((l, i) => (i ? [h("br"), ...inline(l)] : inline(l))));
  });
}

export function loadingBlock(text = "불러오는 중…") {
  return h("p", { class: "muted", role: "status" }, text);
}

export function errorBlock(error, retryAction, retryData = {}) {
  return h("div", { class: "notice error", role: "alert" },
    h("p", {}, error?.message || "요청에 실패했습니다."),
    retryAction ? h("button", { class: "btn", type: "button", dataset: { action: retryAction, ...retryData } }, "다시 시도") : null);
}

export const MODE_LABELS = {
  walk: "도보", bus: "버스", subway: "지하철", train: "기차", taxi: "택시", car: "자동차", ferry: "배", other: "기타 이동",
};

export const KIND_LABELS = { place: "방문", meal: "식사", rest: "휴식" };

export function formatMinutes(min) {
  if (min == null) return "";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? `${h}시간${m ? ` ${m}분` : ""}` : `${m}분`;
}

export function formatKRW(n) {
  return `${Number(n).toLocaleString("ko-KR")}원`;
}
