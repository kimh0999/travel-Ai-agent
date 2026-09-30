"""AI_MODE=mock: 외부 호출 없이 컨텍스트 규칙으로 결정적인 응답을 만든다.

- 실제 AI처럼 '보낸 프롬프트'를 CALLS에 기록해 테스트가 전송 내용을 검증할 수 있게 한다.
- FAILURES에 "timeout" | "invalid" | "error"를 넣으면 다음 호출부터 순서대로 실패를 흉내 낸다(테스트용).
  "error_after_tool:N"은 대화 턴에서 새 도구를 N개 실행한 뒤 실패한다(중단·재시도 테스트용).
- 대화 턴은 실제 모델처럼 transcript에 tool_use/tool_result를 쌓는다. 저장된 transcript로 다시 실행하면
  이미 실행한 도구는 결과를 재사용하고 이어서 진행한다.
- 결과는 모두 is_mock으로 저장되고 화면에 '모의 응답'으로 표시된다.
"""
import json
import re
from datetime import date as _date, timedelta
from typing import Any, Callable, Optional

from pydantic import ValidationError

from app.clients.ai_base import (AIError, AIInvalidResponse, AITimeout, Emit, OnStep, T, ToolExecutor, ToolSpec,
                                 TurnResult)
from app.services.context_builder import CourseContext, ProposalContext

CALLS: list[dict[str, Any]] = []
FAILURES: list[str] = []


class MockAIClient:
    name = "mock"
    model = "mock-ai"
    is_mock = True

    def parse(self, *, kind: str, system: str, user: str, schema: type[T], context: Any, timeout: float) -> T:
        CALLS.append({"kind": kind, "system": system, "user": user})
        if FAILURES:
            failure = FAILURES.pop(0)
            if failure == "timeout":
                raise AITimeout()
            if failure == "error":
                raise AIError()
            if failure == "invalid":
                raw: dict[str, Any] = {"title": "", "days": "not-a-list"}
                try:
                    return schema.model_validate(raw)
                except ValidationError as e:
                    raise AIInvalidResponse("AI 응답 형식이 올바르지 않습니다.") from e
        if kind == "course":
            raw = mock_course(context)
        elif kind == "proposals":
            raw = mock_proposals(context)
        else:
            raise AIError(f"mock AI는 '{kind}' 요청을 지원하지 않습니다.")
        try:
            return schema.model_validate(raw)
        except ValidationError as e:
            raise AIInvalidResponse("AI 응답 형식이 올바르지 않습니다.") from e

    def run_turn(self, *, system: str, transcript: list[dict[str, Any]], tools: list[ToolSpec],
                 execute: ToolExecutor, emit: Emit, on_step: OnStep, deadline: float,
                 max_tool_calls: int) -> TurnResult:
        start = max(i for i, m in enumerate(transcript) if m["role"] == "user" and isinstance(m["content"], str))
        message = transcript[start]["content"]
        history = [m for m in transcript[:start] if isinstance(m["content"], str)]
        CALLS.append({"kind": "chat", "system": system, "user": message, "history": history,
                      "tools": [t.name for t in tools]})
        if FAILURES and FAILURES[0] in ("timeout", "error"):
            failure = FAILURES.pop(0)
            raise AITimeout() if failure == "timeout" else AIError()

        done: dict[tuple[str, str], dict[str, Any]] = {}
        pending: dict[str, tuple[str, str]] = {}
        for m in transcript[start + 1:]:
            for b in m["content"] if isinstance(m["content"], list) else []:
                if b.get("type") == "tool_use":
                    pending[b["id"]] = (b["name"], json.dumps(b["input"], sort_keys=True, ensure_ascii=False))
                elif b.get("type") == "tool_result" and b["tool_use_id"] in pending:
                    done[pending[b["tool_use_id"]]] = json.loads(b["content"])
        called: list[str] = []
        new_calls = [0]

        def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
            key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
            called.append(name)
            if key in done:
                return done[key]
            if FAILURES and FAILURES[0].startswith("error_after_tool:") \
                    and new_calls[0] >= int(FAILURES[0].split(":")[1]):
                FAILURES.pop(0)
                raise AIError("모의 실패: 도구 실행 뒤 연결이 끊겼어요.")
            if len(called) > max_tool_calls:
                return {"error": "도구 호출 한도 초과"}
            tool_id = f"mock_{len(transcript)}"
            transcript.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": tool_id, "name": name, "input": args}]})
            on_step(transcript)
            out = execute(name, json.dumps(args, ensure_ascii=False))
            transcript.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": out}]})
            on_step(transcript)
            new_calls[0] += 1
            done[key] = json.loads(out)
            return done[key]

        m = re.search(r"현재 작업 중인 여행: .*?\(trip_id=([^)]+)\)", system)
        _ACTIVE["trip_id"] = m.group(1) if m else None
        reply = "(모의 응답) " + _script(message, history, call)
        if FAILURES and FAILURES[0].startswith("error_after_tool:"):
            FAILURES.pop(0)
            raise AIError("모의 실패: 답변 직전에 연결이 끊겼어요.")
        for i in range(0, len(reply), 20):
            emit({"type": "text", "delta": reply[i:i + 20]})
        transcript.append({"role": "assistant", "content": [{"type": "text", "text": reply}]})
        on_step(transcript)
        return TurnResult(reply=reply, tool_calls=called)


# ---------------- 대화 턴 시나리오 (규칙 기반) ----------------

DESTINATIONS = ["부산", "여수", "제주", "강릉", "경주", "전주", "속초", "통영", "서울", "인천"]
_ORDINAL_DAYS = {"첫째": 1, "첫날": 1, "둘째": 2, "셋째": 3, "넷째": 4}
Call = Callable[[str, dict[str, Any]], dict[str, Any]]


def _dest_in(text: str) -> Optional[str]:
    return next((d for d in DESTINATIONS if d in text), None)


def _transport_in(text: str) -> Optional[str]:
    if any(k in text for k in ("차로", "자가용", "렌터카", "자동차", "운전")):
        return "car"
    if any(k in text for k in ("대중교통", "기차", "KTX", "버스", "지하철")):
        return "public"
    return None


def _days_in(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*박\s*(\d+)\s*일", text)
    if m:
        return int(m.group(2))
    if "당일" in text:
        return 1
    m = re.search(r"(\d+)\s*일\s*(?:여행|코스|일정|동안)", text)
    return int(m.group(1)) if m else None


def _next_month_hint() -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone(timedelta(hours=9)))
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return f"{year}년 {month}월"


_ACTIVE: dict[str, Optional[str]] = {"trip_id": None}  # 시스템 프롬프트의 '현재 작업 중인 여행'


def _target_trip(call: Call, text: str) -> Optional[dict[str, Any]]:
    """말한 목적지의 여행 → 현재 작업 중인 여행 → 가장 최근 여행 순으로 고른다."""
    trips = call("list_trips", {}).get("trips", [])
    dest = _dest_in(text)
    if dest:
        return next((t for t in trips if t["destination"] == dest), None)
    active = next((t for t in trips if t["id"] == _ACTIVE["trip_id"]), None)
    return active or (trips[0] if trips else None)


def _plan_trip(call: Call, request: str, transport: Optional[str]) -> str:
    dest = _dest_in(request)
    if transport is None:
        prefs = call("get_preferences", {}).get("preferences", [])
        known = next((p for p in prefs if p["category"] == "transport"), None)
        transport = _transport_in(known["value"]) if known else None
    if transport is None:
        call("ask_user", {"question": "이동은 어떻게 하세요?", "options": ["대중교통", "자동차"]})
        return f"{dest} 코스를 짜기 전에 이동수단만 알려주세요."
    args: dict[str, Any] = {"destination": dest, "transport": transport}
    days = _days_in(request)
    if days:
        args["days"] = days
    if "다음 달" in request:
        args["period_hint"] = _next_month_hint()
    trip = call("create_trip", args)
    if "trip" not in trip:
        return f"여행을 만들지 못했어요: {trip.get('error')}"
    course = call("generate_course", {"trip_id": trip["trip"]["id"], "request_note": request[:500]})
    if "version_id" not in course:
        return f"코스를 만들지 못했어요: {course.get('error')}"
    when = trip["trip"].get("period_hint") or "날짜 미정"
    return f"{dest} 코스를 만들었어요 ({when}). 영업시간은 확인하지 못했으니 방문 전에 확인해 주세요."


def _relax_day(day: dict[str, Any], pinned_names: set[str]) -> list[str]:
    """고정하지 않은 마지막 방문지를 빼고, 휴식이 없으면 넣는다. 변경점 문구를 돌려준다."""
    changes = []
    places = [i for i in day["items"] if i["kind"] == "place" and i["name"] not in pinned_names]
    if len(places) > 0 and len([i for i in day["items"] if i["kind"] == "place"]) > 1:
        day["items"].remove(places[-1])
        changes.append(f"{day['day_index']}일차 '{places[-1]['name']}' 방문 제외")
    if not any(i["kind"] == "rest" for i in day["items"]):
        dinner = len(day["items"]) - 1 if day["items"][-1]["kind"] == "meal" else len(day["items"])
        day["items"].insert(dinner, {
            "item_id": f"d{day['day_index']}-r", "kind": "rest", "name": "휴식", "search_keyword": None,
            "reason": "일정을 여유 있게 하려고 휴식을 넣었어요 (모의 응답).", "applied_preference_ids": [],
            "start_time": None, "stay_minutes": 60,
            "travel_from_prev": {"mode": "walk", "minutes_estimate": 5, "note": "추정(모의)"},
            "cost_estimate_krw": None, "cost_basis": None, "backup": None})
        changes.append(f"{day['day_index']}일차 휴식 60분 추가")
    day["items"][0]["travel_from_prev"] = None
    _schedule(day["items"])
    return changes


def _revise(call: Call, text: str) -> str:
    trip = _target_trip(call, text)
    if not trip:
        return "수정할 여행을 찾지 못했어요."
    current = call("get_course", {"trip_id": trip["id"]})
    if "course" not in current:
        return f"수정할 코스를 찾지 못했어요: {current.get('error')}"
    course = current["course"]
    m = re.search(r"(\d+)\s*일\s*차", text)
    day_no = int(m.group(1)) if m else next((v for k, v in _ORDINAL_DAYS.items() if k in text), None)
    targets = [d for d in course["days"] if day_no is None or d["day_index"] == day_no]
    if not targets:
        return f"{day_no}일차는 이 코스에 없어요."
    pinned = {p["name"] for p in current.get("pinned") or []}
    changes = [c for d in targets for c in _relax_day(d, pinned)]
    res = call("revise_course", {"trip_id": trip["id"], "base_version_id": current["version_id"], "days": targets,
                                 "changes": changes or ["변경 없음"], "label": "여유 있게"})
    if "version_id" not in res:
        return f"수정본을 저장하지 못했어요: {res.get('error')}"
    return f"{trip['destination']} 코스를 고쳤어요: {', '.join(changes)}. 다른 날은 그대로예요."


def _pin(call: Call, text: str) -> str:
    trip = _target_trip(call, text)
    current = call("get_course", {"trip_id": trip["id"]}) if trip else {}
    if "course" not in current:
        return "고정할 코스를 찾지 못했어요."
    items = [i for d in current["course"]["days"] for i in d["items"] if i["kind"] == "place"]
    words = [w for w in re.split(r"\s+", text) if len(w) >= 2]
    item = next((i for i in items if any(w in i["name"] for w in words)), None)
    if item is None and "카페" in text:
        item = next((i for i in items if "카페" in i["name"]), None)
    if item is None:
        return "어느 장소를 고정할지 찾지 못했어요. 장소 이름을 알려주세요."
    res = call("pin_place", {"trip_id": trip["id"], "item_id": item["item_id"], "pinned": True})
    return f"'{item['name']}'을(를) 고정했어요." if "pinned_places" in res else f"고정하지 못했어요: {res.get('error')}"


def _feedback(call: Call, text: str) -> str:
    trip = _target_trip(call, text)
    prefs = call("get_preferences", {}).get("preferences", [])
    pace = next((p for p in prefs if p["category"] == "pace" and p["subject"] == "self" and p["scope"] != "trip"), None)
    trip_id = trip["id"] if trip else None
    made = []
    for clause in _clauses(text):
        base = {"trip_id": trip_id, "evidence_text": clause, "subject": "self", "strength": "soft"}
        if "카페" in clause and "좋" in clause:
            made.append(call("propose_memory", {**base, "type": "add", "category": "activity",
                                                "statement": "바다 전망 카페 선호" if "바다" in clause else "카페 방문 선호",
                                                "applies_to": "모든 여행", "certainty": "clear"}))
        elif "시장" in clause and any(k in clause for k in ("별로", "붐비", "붐볐")):
            made.append(call("propose_memory", {**base, "type": "add", "category": "activity",
                                                "statement": "혼잡한 시장은 피하는 편", "applies_to": "모든 여행",
                                                "certainty": "guess",
                                                "question": "그 시장만 그랬나요, 시장 전반이 별로였나요?"}))
        elif "힘들" in clause and any(k in clause for k in ("곳", "일정", "코스")):
            args = {**base, "category": "pace", "statement": "하루 주요 방문지 두세 곳 선호", "applies_to": "모든 여행",
                    "certainty": "clear"}
            if pace:
                args.update({"type": "update", "target_preference_id": pace["id"]})
            else:
                args["type"] = "add"
            made.append(call("propose_memory", args))
    if trip and "다녀왔" in text:
        call("update_trip", {"trip_id": trip["id"], "status": "completed"})
    ok = [r for r in made if "proposal_id" in r]
    return f"기억 변경안 {len(ok)}개를 만들었어요. 카드에서 [기억하기]를 눌러야 저장돼요." if ok \
        else "기억으로 남길 만한 내용을 찾지 못했어요."


def _condition(call: Call, text: str) -> str:
    trip = _target_trip(call, text)
    if not trip:
        return "조건을 적용할 여행이 없어요."
    category = "mobility" if "걷" in text else "other"
    res = call("add_trip_condition", {"trip_id": trip["id"], "category": category, "text": text[:200]})
    return f"이번 {trip['destination']} 여행에만 적용할게요." if "preference_id" in res else f"저장하지 못했어요: {res.get('error')}"


def _script(message: str, history: list[dict[str, Any]], call: Call) -> str:
    text = message.strip()
    if text in ("대중교통", "자동차"):  # 앞선 질문 카드의 답
        request = next((m["content"] for m in reversed(history) if m["role"] == "user" and _dest_in(m["content"])), "")
        if request:
            return _plan_trip(call, request, "public" if text == "대중교통" else "car")
    if any(k in text for k in ("앞으로", "기억해")):
        res = call("propose_memory", {"type": "add", "category": "other", "statement": text[:100],
                                      "applies_to": "모든 여행", "evidence_text": text, "certainty": "clear"})
        return "기억 변경안을 만들었어요. 카드에서 [기억하기]를 누르면 저장돼요." if "proposal_id" in res \
            else f"변경안을 만들지 못했어요: {res.get('error')}"
    if any(k in text for k in ("이번에는", "이번엔", "이번 여행은")):
        return _condition(call, text)
    if "꼭 가고 싶" in text:
        return _pin(call, text)
    if any(k in text for k in ("좋았", "별로", "힘들었", "붐볐")):
        return _feedback(call, text)
    if any(k in text for k in ("빡빡", "줄여", "여유", "수정", "바꿔")):
        return _revise(call, text)
    if _dest_in(text) and any(k in text for k in ("박", "여행", "코스", "짜", "일정")):
        return _plan_trip(call, text, _transport_in(text))
    prefs = call("get_preferences", {})
    count = len(prefs.get("preferences", []))
    return f"저장된 취향 {count}개를 참고하고 있어요. '부산 2박 3일 코스 짜줘'처럼 말씀해 주세요."


# ---------------- 코스 ----------------

def _places_per_day(ctx: CourseContext) -> tuple[int, list[str]]:
    for m in ctx.memories:
        if m.category != "pace":
            continue
        v = m.value
        if any(k in v for k in ("두세 곳", "2곳", "두 곳", "여유")):
            return 2, [m.id]
        if any(k in v for k in ("5곳", "빡빡", "알차게")):
            return 4, [m.id]
    return 3, []


def _wants_rest(ctx: CourseContext) -> list[str]:
    return [m.id for m in ctx.memories if m.category == "pace" and "휴식" in m.value and "없어도" not in m.value]


def _transport(ctx: CourseContext) -> tuple[str, list[str]]:
    for m in ctx.memories:
        if m.category == "transport":
            if "대중교통" in m.value:
                return "subway", [m.id]
            if any(k in m.value for k in ("자가용", "렌터카", "자동차")):
                return "car", [m.id]
            if "택시" in m.value:
                return "taxi", [m.id]
    return "other", []


def _short_walk(ctx: CourseContext) -> list[str]:
    return [m.id for m in ctx.memories if m.category == "mobility" and any(k in m.value for k in ("피하", "적게", "30분"))]


def _explain(m, decision: str) -> str:
    who = "동행인이" if m.subject == "companion" else ""
    if m.source_destinations:
        return f"지난 {', '.join(m.source_destinations)} 여행에서 {who}'{m.value}'라고 하셔서 {decision}"
    return f"{who}'{m.value}'라고 하셔서 {decision}"


def _schedule(items: list[dict[str, Any]]) -> None:
    """10시부터 체류·이동 시간을 더해 시작 시각을 매긴다. 저녁은 17:30 이후로 맞춘다."""
    t = 10 * 60
    for i, item in enumerate(items):
        if item["travel_from_prev"]:
            t += item["travel_from_prev"]["minutes_estimate"]
        if item["kind"] == "meal" and i == len(items) - 1:
            t = max(t, 17 * 60 + 30)
        item["start_time"] = f"{t // 60:02d}:{t % 60:02d}"
        t += item["stay_minutes"]


def mock_course(ctx: CourseContext) -> dict[str, Any]:
    trip = ctx.trip
    dest = trip["destination"]
    per_day, pace_ids = _places_per_day(ctx)
    rest_ids = _wants_rest(ctx)
    mode, transport_ids = _transport(ctx)
    mode = {"car": "car", "public": "subway"}.get(trip.get("transport") or "", mode)
    walk_ids = _short_walk(ctx)
    activity_mems = [m for m in ctx.memories if m.category == "activity"]
    candidates = [p.name for p in ctx.place_candidates] or [f"{dest} 대표 관광지", f"{dest} 해변", f"{dest} 전망대"]
    candidates = list(ctx.pinned) + [c for c in candidates if c not in ctx.pinned]
    applied_common = pace_ids + transport_ids + walk_ids
    leg_minutes = 15 if walk_ids else 25

    days = []
    idx = 0
    for d in range(1, trip["days"] + 1):
        items = []
        n = 0

        def add(kind, name, reason, stay, applied, cost=None, basis=None, keyword=None):
            nonlocal n
            n += 1
            backup = {"name": f"{dest} 실내 전시관", "search_keyword": None,
                      "reason": "비가 오거나 문을 닫았을 때 가까운 실내 대안이에요 (모의 응답)."} if kind == "place" else None
            items.append({
                "item_id": f"d{d}-{n}", "kind": kind, "name": name, "search_keyword": keyword, "reason": reason,
                "applied_preference_ids": applied, "start_time": None, "stay_minutes": stay,
                "travel_from_prev": None if n == 1 else {"mode": mode if kind != "rest" else "walk",
                                                         "minutes_estimate": leg_minutes if kind != "rest" else 5,
                                                         "note": "추정 이동시간(모의)"},
                "cost_estimate_krw": cost, "cost_basis": basis, "backup": backup,
            })

        for p in range(per_day):
            name = candidates[idx % len(candidates)]
            idx += 1
            act = activity_mems[(idx - 1) % len(activity_mems)] if activity_mems else None
            reason = f"{dest}의 주요 방문지로 넣었어요 (모의 응답)."
            applied = list(applied_common)
            if act:
                reason = _explain(act, "관련 장소로 골랐어요 (모의 응답).")
                applied.append(act.id)
            add("place", name, reason, 90, applied, keyword=name)
            if p == 0:
                add("meal", f"{dest} 점심 식사", "점심 식사 구간이에요 (모의 응답).", 60, [],
                    cost=15000, basis="1인 점심 일반 가격대 추정(모의, 실제 가격 미확인)", keyword=f"{dest} 맛집")
                if rest_ids:
                    add("rest", "오후 휴식", "오후 휴식을 원하셔서 넣었어요 (모의 응답).", 60, rest_ids)
        add("meal", f"{dest} 저녁 식사", "저녁 식사 구간이에요 (모의 응답).", 70, [],
            cost=25000, basis="1인 저녁 일반 가격대 추정(모의, 실제 가격 미확인)", keyword=f"{dest} 맛집")
        _schedule(items)
        date = None
        if trip.get("start_date"):
            date = (_date.fromisoformat(trip["start_date"]) + timedelta(days=d - 1)).isoformat()
        days.append({"day_index": d, "date": date, "theme": f"{d}일차 {dest} 둘러보기", "items": items})

    applied = []
    explanations = []
    used = set(applied_common + rest_ids + [m.id for m in activity_mems])
    for m in ctx.memories:
        if m.id in used:
            decision = {
                "pace": f"하루 주요 방문지를 {per_day}곳으로 구성했어요",
                "transport": "이동 구간을 그 수단 기준으로 짰어요",
                "mobility": "이동 구간을 짧게 줄였어요",
                "activity": "관련 장소를 우선 넣었어요",
            }.get(m.category, "반영했어요")
            if m.category == "pace" and m.id in rest_ids:
                decision = "오후 휴식을 넣었어요"
            reason = _explain(m, decision + ".")
            applied.append({"preference_id": m.id, "reason": reason})
            explanations.append(reason)
    hard = [m for m in ctx.memories if m.strength == "hard" and m.id not in used]
    for m in hard:
        applied.append({"preference_id": m.id, "reason": f"필수 조건 '{m.value}'을(를) 지키도록 구성했어요."})

    assumptions = []
    if trip.get("days_is_default"):
        nights = trip["days"] - 1
        assumptions.append(f"{nights}박 {trip['days']}일 기준 임시 코스" if nights else "당일 기준 임시 코스")
    if not trip.get("start_date"):
        assumptions.append("날짜가 없어 영업일·예약 가능 여부는 확인하지 않았어요.")
    questions = [] if trip.get("companions") else ["동행인이 있나요? 있다면 알려주시면 코스를 맞춰 드릴게요."]
    summary = " ".join(explanations[:3]) or f"저장된 취향이 적어 {dest}의 대표 방문지 위주로 구성했어요."
    return {
        "title": f"{dest} {trip['days']}일 코스 (모의)",
        "summary_explanation": summary[:1000],
        "assumptions": assumptions,
        "questions_for_user": questions,
        "days": days,
        "applied_memories": applied,
    }


# ---------------- 기억 변경안 ----------------

_CLAUSE_SPLIT = re.compile(r"[.!?\n]+|,\s*")
_COMPANION_WORDS = ("아이", "부모님", "엄마", "아빠", "동행", "친구가", "남편", "아내")


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_SPLIT.split(text or "") if c.strip()]


def _situational(clause: str) -> dict[str, Any]:
    if any(k in clause for k in ("비가", "비 와", "날씨", "추워", "더워")):
        return {"is_situational": True, "factor": "weather", "reason": "그날 날씨 때문일 수 있어요."}
    if any(k in clause for k in ("피곤", "컨디션", "아파")):
        return {"is_situational": True, "factor": "condition", "reason": "그날 컨디션 때문일 수 있어요."}
    if any(k in clause for k in ("주말이라", "연휴", "축제")):
        return {"is_situational": True, "factor": "crowd_timing", "reason": "특정 시기의 혼잡 때문일 수 있어요."}
    return {"is_situational": False, "factor": None, "reason": "여러 여행에 적용될 수 있는 취향으로 보여요."}


def mock_proposals(ctx: ProposalContext) -> dict[str, Any]:
    proposals: list[dict[str, Any]] = []
    notes: list[str] = []
    pace_mem = next((m for m in ctx.existing_memories if m.category == "pace" and m.subject == "self"), None)

    sources: list[tuple[str, str | None]] = []
    for f in ctx.feedback:
        sources += [(c, None) for c in _clauses(f.overall_text)]
        for v in f.visits:
            if v.visited:
                sources += [(c, v.item_id) for c in _clauses(v.comment)]
            elif v.comment:
                notes.append(f"'{v.place_name}'은(는) 방문하지 않아 방문 경험으로 추출하지 않았어요.")

    def add(clause, item_id, category, after, *, typ="add", target=None, before=None):
        if any(p["after"] == after for p in proposals):
            return
        subject = "companion" if any(w in clause for w in _COMPANION_WORDS) else "self"
        proposals.append({"type": typ, "target_preference_id": target, "category": category, "strength": "soft",
                          "subject": subject, "before": before, "after": after, "evidence_text": clause,
                          "evidence_item_id": item_id, "situational": _situational(clause)})

    for clause, item_id in sources:
        if "카페" in clause and "좋" in clause:
            add(clause, item_id, "activity", "바다 전망 카페 선호" if "바다" in clause else "카페 방문 선호")
        if any(k in clause for k in ("붐비", "붐볐", "사람이 많", "복잡했")):
            add(clause, item_id, "activity", "혼잡한 장소를 피하는 편")
        if "힘들" in clause and any(k in clause for k in ("곳", "일정", "코스")):
            after = "하루 주요 방문지 두세 곳 선호"
            if pace_mem:
                add(clause, item_id, "pace", after, typ="update", target=pace_mem.id, before=pace_mem.value)
            else:
                add(clause, item_id, "pace", after)
        if "걷" in clause and any(k in clause for k in ("힘들", "많이", "오래")):
            add(clause, item_id, "mobility", "오래 걷는 일정은 피하는 편")
    return {"proposals": proposals[:6], "excluded_notes": notes}
