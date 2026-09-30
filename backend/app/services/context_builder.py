"""AI 요청 컨텍스트 구성. 여기서 만든 문자열이 외부 AI로 전송되는 전부다."""
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from app.clients.places_base import PlaceResult
from app.schemas.common import CATEGORY_LABELS

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _clean(text: Optional[str], limit: int = 300) -> str:
    """데이터 블록 안 텍스트: 줄바꿈·태그 문자를 정리해 블록 구조를 깨지 못하게 한다."""
    if not text:
        return ""
    return " ".join(str(text).replace("<", "‹").replace(">", "›").split())[:limit]


@dataclass
class ContextMemory:
    id: str
    strength: str
    subject: str
    category: str
    scope: str
    value: str
    source_destinations: list[str]


@dataclass
class PastTrip:
    trip_id: str
    destination: str
    lessons: list[str]


@dataclass
class CourseContext:
    trip: dict[str, Any]
    home_base: Optional[str]
    memories: list[ContextMemory]
    unknown_categories: list[str]
    past_trips: list[PastTrip]
    place_candidates: list[PlaceResult] = field(default_factory=list)
    pinned: list[str] = field(default_factory=list)  # 사용자가 고정한 장소 이름 (반드시 포함)
    request_note: Optional[str] = None  # 이번 생성 요청에만 쓰는 사용자 요청 (예: 바다 보이는 카페 위주)


@dataclass
class FeedbackVisit:
    item_id: str
    place_name: str
    visited: bool
    rating: Optional[int]
    comment: str


@dataclass
class FeedbackEntry:
    feedback_id: str
    overall_text: str
    overall_rating: Optional[int]
    visits: list[FeedbackVisit]


@dataclass
class ProposalContext:
    destination: str
    companions: list[dict[str, Any]]
    feedback: list[FeedbackEntry]
    existing_memories: list[ContextMemory]


def to_context_memory(pref: dict[str, Any], trips_by_id: dict[str, dict[str, Any]]) -> ContextMemory:
    dests = []
    for s in pref.get("sources", []):
        if s.get("type") != "feedback_proposal":
            continue  # 여행 피드백 승인으로 생긴 출처만 '지난 여행'으로 표시한다.
        dest = s.get("trip_destination") or (trips_by_id.get(s.get("trip_id") or "", {}).get("destination"))
        if dest and dest not in dests:
            dests.append(dest)
    return ContextMemory(id=pref["id"], strength=pref["strength"], subject=pref["subject"], category=pref["category"],
                         scope=pref["scope"], value=pref["value"], source_destinations=dests)


def _trip_block(trip: dict[str, Any], home_base: Optional[str]) -> str:
    days = trip["days"]
    lines = [f"목적지: {_clean(trip['destination'], 50)}"]
    period = f"{days - 1}박 {days}일" if days > 1 else "당일"
    lines.append(f"기간: {period}" + (" (사용자가 기간을 정하지 않아 기본값으로 만든 임시 코스)" if trip.get("days_is_default") else ""))
    if trip.get("start_date"):
        lines.append(f"날짜: {trip['start_date']} ~ {trip.get('end_date') or ''}")
    elif trip.get("period_hint"):
        lines.append(f"날짜: 미정, 대략 {_clean(trip['period_hint'], 40)} (요일·영업일·예약 가능 여부를 확정하지 말 것)")
    else:
        lines.append("날짜: 미정 (영업일·예약 가능 여부를 확정하지 말 것)")
    transport = {"car": "자가용·렌터카", "public": "대중교통", "mixed": "대중교통과 택시 등 혼합"}.get(trip.get("transport") or "")
    lines.append(f"이번 여행 이동수단: {transport or '모름'}")
    if trip.get("companions"):
        comp = ", ".join(_clean(c.get("relation"), 30) + (f"({_clean(c.get('note'), 60)})" if c.get("note") else "")
                         for c in trip["companions"])
        lines.append(f"동행인: {comp}")
    else:
        lines.append("동행인: 없음 또는 미입력")
    b = trip.get("budget")
    if b:
        lines.append(f"이번 여행 예산: {'1인당' if b['per'] == 'person' else '전체'} "
                     f"{'1일' if b['unit'] == 'day' else '여행 전체'} {b['amount']:,}원")
    if trip.get("conditions"):
        lines.append(f"이번 여행 조건(이번 여행에만 적용): {_clean(trip['conditions'], 500)}")
    lines.append(f"주 출발지: {_clean(home_base, 100) or '모름'}")
    return "\n".join(lines)


def _memory_line(m: ContextMemory) -> str:
    src = f"지난 {', '.join(m.source_destinations)} 여행 피드백" if m.source_destinations else \
        {"base": "사용자 직접 입력", "trip": "이번 여행 한정", "learned": "여행 피드백"}.get(m.scope, m.scope)
    return (f"{m.id} | {m.strength} | {m.subject} | {CATEGORY_LABELS.get(m.category, m.category)} | "
            f"{_clean(m.value, 200)} | 출처: {src}")


def build_course_prompt(ctx: CourseContext) -> str:
    memories = "\n".join(_memory_line(m) for m in ctx.memories) or "(저장된 취향 없음)"
    unknown = ", ".join(CATEGORY_LABELS.get(c, c) for c in ctx.unknown_categories) or "(없음)"
    past = "\n".join(f"- {_clean(p.destination, 50)} 여행: 승인된 교훈 — {'; '.join(_clean(l, 150) for l in p.lessons)}"
                     for p in ctx.past_trips if p.lessons) or "(없음)"
    places = "\n".join(f"- {_clean(p.name, 80)} | {_clean(p.category, 60)} | {_clean(p.address, 100)}"
                       for p in ctx.place_candidates) or "(검색된 후보 없음)"
    pinned = "\n".join(f"- {_clean(n, 100)}" for n in ctx.pinned) or "(없음)"
    note = _clean(ctx.request_note, 500) or "(없음)"
    return (
        f"<trip>\n{_trip_block(ctx.trip, ctx.home_base)}\n</trip>\n\n"
        f"<memories>\n# id | strength | subject | 분류 | 내용 | 출처\n{memories}\n</memories>\n\n"
        f"<unknown>\n{unknown}\n</unknown>\n\n"
        f"<past_trips>\n{past}\n</past_trips>\n\n"
        f"<place_candidates>\n{places}\n</place_candidates>\n\n"
        f"<pinned_places>\n{pinned}\n</pinned_places>\n\n"
        f"<request_note>\n{note}\n</request_note>\n\n"
        "위 정보로 여행 코스를 만들어 주세요."
    )


def build_proposal_prompt(ctx: ProposalContext) -> str:
    fb_lines = []
    for f in ctx.feedback:
        fb_lines.append(f"[피드백 {f.feedback_id}] 여행 전체 평가: {f.overall_rating or '없음'}/5")
        if f.overall_text:
            fb_lines.append(f"여행 전체 소감: {_clean(f.overall_text, 2000)}")
        for v in f.visits:
            status = "visited=true" if v.visited else "visited=false (방문하지 않음)"
            line = f"- item_id={v.item_id} | {_clean(v.place_name, 80)} | {status}"
            if v.visited:
                line += f" | 평점 {v.rating or '없음'}/5"
                if v.comment:
                    line += f" | 소감: {_clean(v.comment, 500)}"
            fb_lines.append(line)
    existing = "\n".join(_memory_line(m) for m in ctx.existing_memories) or "(없음)"
    companions = ", ".join(_clean(c.get("relation"), 30) for c in ctx.companions) or "없음"
    return (
        f"<trip>\n목적지: {_clean(ctx.destination, 50)}\n동행인: {companions}\n</trip>\n\n"
        f"<feedback>\n" + "\n".join(fb_lines) + "\n</feedback>\n\n"
        f"<existing_memories>\n# id | strength | subject | 분류 | 내용 | 출처\n{existing}\n</existing_memories>\n\n"
        "위 피드백에서 장기 기억 변경안을 추출해 주세요."
    )
