from datetime import datetime, timezone
from typing import Literal

Scope = Literal["base", "trip", "learned"]
Strength = Literal["hard", "soft"]
Subject = Literal["self", "companion"]
Category = Literal["activity", "pace", "transport", "budget", "food", "mobility", "lodging", "other"]
PreferenceStatus = Literal["active", "paused", "deleted"]
TripStatus = Literal["planned", "completed"]
ProposalType = Literal["add", "update", "deactivate"]
ProposalStatus = Literal["pending", "approved", "edited_approved", "rejected"]

CATEGORY_LABELS: dict[str, str] = {
    "activity": "선호 활동",
    "pace": "일정 밀도·휴식",
    "transport": "교통수단",
    "budget": "예산",
    "food": "음식",
    "mobility": "걷기·이동 제약",
    "lodging": "숙소",
    "other": "기타",
}

# 초기 설정에서 묻는 항목. 기억이 없으면 '모름'으로 취급하고 AI가 추측하지 않는다.
ONBOARDING_CATEGORIES: list[str] = ["transport", "budget", "activity", "mobility", "pace", "food"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
