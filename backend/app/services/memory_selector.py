"""관련 기억 선택 (SPEC 8-2, 규칙 기반 — 임베딩·벡터 DB 사용 안 함).

1. 대상: 현재 사용자의 status=active 기억. scope=trip이면 이번 여행 것만.
2. hard 제약은 항상 포함.
3. soft 선호는 (이번 여행 한정 → 카테고리 관련도 → learned 우선 → 최신 수정) 순으로 최대 15개.
   subject=companion은 이번 여행에 동행인이 있을 때만.
4. sensitive=true & share_with_ai=false는 외부 AI 전송에서 제외(withheld).
"""
from dataclasses import dataclass, field
from typing import Any

MAX_SOFT = 15
CATEGORY_PRIORITY = {"pace": 0, "mobility": 1, "transport": 2, "activity": 3, "food": 4, "budget": 5, "lodging": 6, "other": 7}


@dataclass
class Selection:
    selected: list[dict[str, Any]] = field(default_factory=list)  # AI에 보낼 기억
    withheld_sensitive: list[dict[str, Any]] = field(default_factory=list)  # 민감·전송 비동의로 제외
    dropped_over_limit: list[dict[str, Any]] = field(default_factory=list)


def is_ai_shareable(pref: dict[str, Any]) -> bool:
    return not (pref.get("sensitive") and not pref.get("share_with_ai"))


def select_for_trip(prefs: list[dict[str, Any]], trip: dict[str, Any]) -> Selection:
    has_companions = bool(trip.get("companions"))
    eligible = []
    for p in prefs:
        if p.get("status") != "active":
            continue
        if p.get("scope") == "trip" and p.get("trip_id") != trip["id"]:
            continue
        if p.get("subject") == "companion" and not has_companions:
            continue
        eligible.append(p)

    result = Selection()
    shareable = []
    for p in eligible:
        (shareable if is_ai_shareable(p) else result.withheld_sensitive).append(p)

    hard = [p for p in shareable if p.get("strength") == "hard"]
    soft = [p for p in shareable if p.get("strength") != "hard"]
    soft.sort(key=lambda p: (0 if p.get("scope") == "trip" else 1,
                             CATEGORY_PRIORITY.get(p.get("category"), 9),
                             0 if p.get("scope") == "learned" else 1,
                             -p["updated_at"].timestamp()))
    result.selected = hard + soft[:MAX_SOFT]
    result.dropped_over_limit = soft[MAX_SOFT:]
    return result
